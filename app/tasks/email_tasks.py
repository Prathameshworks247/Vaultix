import random

from app.celery_app import app
from app.db.session import SessionLocal
from app.models.payments import Payment, PaymentEvent

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


@app.task(name="tasks.notify_merchant")
def notify_merchant(payment_id: str):
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
        # Simulate notifying the merchant (Phase 9 turns this into a real webhook POST).
        print(f"[notify] merchant {payment.merchant_id} notified: payment {payment_id} status={payment.status}")
        db.add(PaymentEvent(payment_id=payment.id, event_type="MERCHANT_NOTIFIED"))
        db.commit()
        return payment_id
    finally:
        db.close()
