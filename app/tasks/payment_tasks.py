from celery import chain
from app.celery_app import app
from app.tasks.email_tasks import send_receipt, notify_merchant


@app.task(name="tasks.process_payment")
def process_payment(payment_id: str):
    # TODO(Session 4): simulate processing delay, success/failure/timeout, retries
    print(f"[stub] process_payment for payment {payment_id}")
    return payment_id


@app.task(name="tasks.fraud_check")
def fraud_check(payment_id: str):
    # TODO(Session 5): amount threshold + velocity checks
    print(f"[stub] fraud_check for payment {payment_id}")
    return payment_id


def payment_pipeline(payment_id: str):
    return chain(
        process_payment.s(payment_id),
        fraud_check.s(),
        send_receipt.s(),
        notify_merchant.s(),
    ).apply_async()