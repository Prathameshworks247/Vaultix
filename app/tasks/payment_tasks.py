import random
import time

from celery import chain, group

from app.celery_app import app
from app.db.session import SessionLocal
from app.models.payments import Payment, PaymentEvent, PaymentStatus
from app.tasks.email_tasks import send_receipt, notify_merchant

OUTCOMES = ["success", "failure", "timeout"]
WEIGHTS = [70, 20, 10]


@app.task(name="tasks.process_payment", bind=True, max_retries=3)
def process_payment(self, payment_id: str):
    db = SessionLocal()
    try:
        payment = db.get(Payment, payment_id)

        payment.status = PaymentStatus.PROCESSING
        db.add(PaymentEvent(
            payment_id=payment.id,
            event_type="PROCESSING",
            detail={"attempt": self.request.retries + 1},
        ))
        db.commit()

        time.sleep(random.uniform(5, 15))
        outcome = random.choices(OUTCOMES, weights=WEIGHTS)[0]

        if outcome == "success":
            payment.status = PaymentStatus.SUCCEEDED
            db.add(PaymentEvent(payment_id=payment.id, event_type="SUCCEEDED"))
            db.commit()
            return payment_id

        if outcome == "timeout":
            db.add(PaymentEvent(
                payment_id=payment.id,
                event_type="TIMEOUT",
                detail={"attempt": self.request.retries + 1},
            ))
            db.commit()
            raise self.retry(countdown=2 ** self.request.retries)

        # outcome == "failure"
        payment.status = PaymentStatus.FAILED
        db.add(PaymentEvent(payment_id=payment.id, event_type="FAILED", detail={"reason": "simulated_failure"}))
        db.commit()
        raise RuntimeError(f"payment {payment_id} failed")

    except self.MaxRetriesExceededError:
        payment.status = PaymentStatus.FAILED
        db.add(PaymentEvent(payment_id=payment.id, event_type="FAILED", detail={"reason": "timeout_exhausted"}))
        db.commit()
        raise
    finally:
        db.close()


@app.task(name="tasks.fraud_check")
def fraud_check(payment_id: str):
    # TODO(Phase 5): amount threshold + velocity checks
    print(f"[stub] fraud_check for payment {payment_id}")
    return payment_id


def payment_pipeline(payment_id: str):
    # send_receipt and notify_merchant are independent side effects of a settled payment -
    # a failed/slow receipt email must not gate (or be gated by) the merchant notification,
    # so they fan out as a group rather than chaining linearly.
    return chain(
        process_payment.s(payment_id),
        fraud_check.s(),
        group(send_receipt.s(), notify_merchant.s()),
    ).apply_async()
