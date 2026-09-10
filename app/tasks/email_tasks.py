import hashlib
import hmac
import random
import time

import requests

from app.celery_app import app
from app.db.session import SessionLocal
from app.models.payments import Payment, PaymentEvent

WEBHOOK_TIMEOUT_SECONDS = 5


def _sign(secret: str, body: bytes, timestamp: str) -> str:
    # Timestamp is part of the signed payload (not just sent alongside it) so a captured
    # request can't be replayed indefinitely - the receiver checks both the signature and
    # that the timestamp is recent.
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()

RECEIPT_FAILURE_RATE = 0.15


@app.task(name="tasks.send_receipt", bind=True, max_retries=3)
def send_receipt(self, payment_id: str):
    db = SessionLocal()
    try:
        already_sent = (
            db.query(PaymentEvent)
            .filter_by(payment_id=payment_id, event_type="RECEIPT_SENT")
            .first()
        )
        if already_sent:
            # Redelivered message (broker redelivery, retry racing a prior success) - don't email twice.
            return payment_id

        payment = db.get(Payment, payment_id)

        if random.random() < RECEIPT_FAILURE_RATE:
            raise self.retry(
                countdown=2 ** self.request.retries,
                exc=ConnectionError("simulated SMTP failure"),
            )

        # Simulate sending a receipt email (swap for real SMTP / Mailhog later).
        print(f"[email] receipt sent for payment {payment_id} amount={payment.amount} {payment.currency}")
        db.add(PaymentEvent(payment_id=payment.id, event_type="RECEIPT_SENT"))
        db.commit()
        return payment_id

    except self.MaxRetriesExceededError:
        # The payment already SUCCEEDED - a missing receipt is a CS issue, not a settlement
        # issue. Log it and stop; don't let this poison the payment or its sibling task.
        db.add(PaymentEvent(
            payment_id=payment_id,
            event_type="RECEIPT_FAILED",
            detail={"reason": "smtp_unavailable"},
        ))
        db.commit()
        return payment_id
    finally:
        db.close()


@app.task(name="tasks.notify_merchant", bind=True, max_retries=3)
def notify_merchant(self, payment_id: str):
    db = SessionLocal()
    try:
        already_notified = (
            db.query(PaymentEvent)
            .filter_by(payment_id=payment_id, event_type="MERCHANT_NOTIFIED")
            .first()
        )
        if already_notified:
            return payment_id

        payment = db.get(Payment, payment_id)
        merchant = payment.merchant

        if not merchant.webhook_url:
            # No webhook registered for this merchant - fall back to the simulated log line.
            print(f"[notify] merchant {merchant.id} notified: payment {payment_id} status={payment.status}")
            db.add(PaymentEvent(payment_id=payment.id, event_type="MERCHANT_NOTIFIED"))
            db.commit()
            return payment_id

        body = f'{{"payment_id": "{payment_id}", "status": "{payment.status.value}"}}'.encode()
        headers = {"Content-Type": "application/json"}
        if merchant.webhook_secret:
            timestamp = str(int(time.time()))
            headers["X-Webhook-Timestamp"] = timestamp
            headers["X-Webhook-Signature"] = _sign(merchant.webhook_secret, body, timestamp)

        try:
            resp = requests.post(merchant.webhook_url, data=body, headers=headers, timeout=WEBHOOK_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.RequestException as exc:
            # self.retry(..., exc=exc) re-raises exc itself (not MaxRetriesExceededError)
            # once retries are exhausted, so the exhaustion check has to happen here rather
            # than in an `except self.MaxRetriesExceededError` around this call.
            if self.request.retries >= self.max_retries:
                # Payment already settled - a merchant whose endpoint is down is their
                # problem to fix, not ours to keep retrying forever. Log it and stop.
                db.add(PaymentEvent(
                    payment_id=payment.id,
                    event_type="WEBHOOK_FAILED",
                    detail={"url": merchant.webhook_url, "reason": str(exc)},
                ))
                db.commit()
                return payment_id
            raise self.retry(countdown=2 ** self.request.retries, exc=exc)

        db.add(PaymentEvent(
            payment_id=payment.id,
            event_type="MERCHANT_NOTIFIED",
            detail={"webhook": True, "status_code": resp.status_code},
        ))
        db.commit()
        return payment_id
    finally:
        db.close()
