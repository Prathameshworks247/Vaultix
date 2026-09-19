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


def _normalize_result_backend(url: str | None) -> str | None:
    """A managed-Postgres env var (Render's fromDatabase, Heroku, etc.) hands over a bare
    "postgres://..." or "postgresql://..." connection string - Celery's DB result backend
    needs a "db+" scheme prefix, and SQLAlchemy needs "postgresql", not "postgres". Normalize
    both so the same DATABASE_URL-shaped value works here without hand-editing per deploy."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and not url.startswith("db+"):
        url = "db+" + url
    return url


def _scheme_only(url: str | None) -> str:
    """First ~20 chars, safe to log - enough to see the scheme/prefix without leaking a
    password that's typically right after it in a connection string."""
    return (url or "<unset>")[:20]


_raw_backend = os.environ.get("CELERY_RESULT_BACKEND")
_result_backend = _normalize_result_backend(_raw_backend)
# print(), not logger - this runs during import, before configure_logging() has taken
# effect (it's called later in app.main, after the import chain that pulls this module in),
# so a logger call here would silently get dropped by the default logging level.
print(f"[celery_app] result backend: raw={_scheme_only(_raw_backend)}... normalized={_scheme_only(_result_backend)}...")

# Celery's config system re-reads os.environ["CELERY_RESULT_BACKEND"] directly on every
# access to app.conf.result_backend - a legacy compatibility behavior that silently
# overrides whatever's passed to Celery(backend=...) or assigned to conf.result_backend
# afterwards. Confirmed by testing all three: only mutating the env var itself sticks.
if _result_backend:
    os.environ["CELERY_RESULT_BACKEND"] = _result_backend

app = Celery(
    "payment_gateway",
    broker=os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    backend=_result_backend,
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

