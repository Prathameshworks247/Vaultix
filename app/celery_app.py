import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging
from kombu import Queue

from app.core.logging import configure_logging


@setup_logging.connect
def _configure_worker_logging(**kwargs):
    # Take over logging setup entirely instead of letting Celery configure its own
    # handlers/formatters - keeps worker/beat log output in the same JSON-lines format as
    # the API process.
    configure_logging()


app = Celery(
    "payment_gateway",
    broker=os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    backend=os.environ.get("CELERY_RESULT_BACKEND"),
    include=[
        "app.tasks.payment_tasks",
        "app.tasks.email_tasks",
        "app.tasks.refund_tasks",
        "app.tasks.maintenance_tasks",
    ],
)

app.conf.task_queues = (
    Queue("payment_queue"),
    Queue("email_queue"),
    Queue("refund_queue"),
    Queue("notification_queue"),
)

app.conf.task_default_queue = "payment_queue"

app.conf.task_routes = {
    "tasks.process_payment": {"queue": "payment_queue"},
    "tasks.fraud_check": {"queue": "payment_queue"},
    "tasks.send_receipt": {"queue": "email_queue"},
    "tasks.notify_merchant": {"queue": "notification_queue"},
    "tasks.process_refund": {"queue": "refund_queue"},
    "tasks.reap_stuck_payments": {"queue": "payment_queue"},
}

# Nightly sweep for payments stuck in PROCESSING (worker died, task message lost, etc.) -
# see app.tasks.maintenance_tasks.reap_stuck_payments.
app.conf.beat_schedule = {
    "reap-stuck-payments-nightly": {
        "task": "tasks.reap_stuck_payments",
        "schedule": crontab(hour=2, minute=0),
    },
}

@app.task(name="tasks.hello_world")
def hello_world():
    print("hello from the celery worker")
    return "pong"

app.autodiscover_tasks(["app"], related_name="tasks")

