from celery import chain
from app.tasks.email_tasks import send_receipt, notify_merchant


def payment_pipeline(payment_id: str):
    return chain(
        process_payment.s(payment_id),
        fraud_check.s(),
        send_receipt.s(),
        notify_merchant.s(),
    ).apply_async()