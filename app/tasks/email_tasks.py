from app.celery_app import app


@app.task(name="tasks.send_receipt")
def send_receipt(payment_id: str):
    # TODO(Session 5): simulate sending a receipt email, log to email_queue
    print(f"[stub] send_receipt for payment {payment_id}")
    return payment_id


@app.task(name="tasks.notify_merchant")
def notify_merchant(payment_id: str):
    # TODO(Session 5): simulate notifying the merchant, log to notification_queue
    print(f"[stub] notify_merchant for payment {payment_id}")
    return payment_id
