import logging
import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, task_failure
from kombu import Queue

from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


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

# At-least-once delivery: only ack a message after the task finishes, and if the worker
# process itself dies mid-task, reject (not silently drop) so the message is redelivered.
# Tasks are written to be idempotent (re-read state from the DB on every attempt) so a
# redelivery is safe.
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True

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


@task_failure.connect
def _capture_dead_letter(sender=None, task_id=None, exception=None, args=None, traceback=None, **kwargs):
    # Fires for any task that raised and exhausted retries (or has none) - a bug, a DB
    # outage, anything the task itself didn't already turn into a PaymentEvent and swallow.
    # A dedicated DB session, not the task's own (which is already torn down by now).
    from app.db.session import SessionLocal
    from app.models.payments import DeadLetter

    db = SessionLocal()
    try:
        db.add(DeadLetter(
            task_name=sender.name if sender else "unknown",
            task_id=task_id or "unknown",
            args=[str(a) for a in (args or [])],
            exception=str(exception),
            traceback=str(traceback) if traceback else None,
        ))
        db.commit()
        logger.error(f"dead-lettered task {sender.name if sender else '?'}[{task_id}]: {exception}")
    finally:
        db.close()

