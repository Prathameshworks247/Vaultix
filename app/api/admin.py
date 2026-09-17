from decimal import Decimal

from fastapi import APIRouter, Depends
from kombu import Connection
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.celery_app import app as celery_app
from app.core.auth import require_admin
from app.db.session import get_db
from app.models.payments import DeadLetter, Payment, PaymentStatus, Refund
from app.services import fx_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

QUEUE_NAMES = ["payment_queue", "email_queue", "refund_queue", "notification_queue"]


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Payment.id)).scalar()
    by_status = dict(
        db.query(Payment.status, func.count(Payment.id)).group_by(Payment.status).all()
    )
    counts = {status.value: by_status.get(status, 0) for status in PaymentStatus}

    # PENDING/PROCESSING payments haven't settled yet - excluded from the rate so an
    # in-flight backlog doesn't dilute (or skew) the numbers.
    settled = counts["SUCCEEDED"] + counts["FAILED"] + counts["REFUNDED"]
    success_rate = (counts["SUCCEEDED"] + counts["REFUNDED"]) / settled if settled else None
    failure_rate = counts["FAILED"] / settled if settled else None

    by_currency = dict(
        db.query(Payment.currency, func.coalesce(func.sum(Payment.amount), 0))
        .group_by(Payment.currency)
        .all()
    )
    total_in_base = sum((fx_service.to_base(amount, currency) for currency, amount in by_currency.items()), Decimal("0"))

    refund_total = db.query(func.count(Refund.id)).scalar()
    refund_by_status = dict(
        db.query(Refund.status, func.count(Refund.id)).group_by(Refund.status).all()
    )
    refunded_amount = (
        db.query(func.coalesce(func.sum(Refund.amount), 0))
        .filter(Refund.status == "COMPLETED")
        .scalar()
    )

    return {
        "payments": {
            "total": total,
            "by_status": counts,
            "settled": settled,
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "total_by_currency": {c: str(a) for c, a in by_currency.items()},
            "total_in_base_currency": {"currency": fx_service.BASE_CURRENCY, "amount": str(total_in_base)},
        },
        "refunds": {
            "total": refund_total,
            "by_status": refund_by_status,
            "completed_amount": str(refunded_amount),
        },
    }


@router.get("/queues")
def get_queue_stats():
    """Message backlog per queue, read directly off the broker (passive queue_declare) -
    avoids a separate dependency on the RabbitMQ management HTTP API/credentials."""
    results = []
    try:
        with Connection(celery_app.conf.broker_url) as conn:
            channel = conn.channel()
            for name in QUEUE_NAMES:
                try:
                    queue = channel.queue_declare(queue=name, passive=True)
                    results.append({
                        "queue": name,
                        "messages": queue.message_count,
                        "consumers": queue.consumer_count,
                    })
                except Exception as exc:
                    # Queue doesn't exist yet (no worker has started to declare it) or a
                    # per-queue broker error - report it without failing the whole endpoint.
                    results.append({"queue": name, "error": str(exc)})
    except Exception as exc:
        return {"error": f"could not reach broker: {exc}", "queues": []}

    return {"queues": results}


@router.get("/workers")
def get_worker_status():
    """Live worker roster via Celery's control/inspect protocol (a broadcast over the
    broker) - shows what's actually running right now, not a static config list."""
    inspect = celery_app.control.inspect(timeout=2)
    stats = inspect.stats() or {}
    active = inspect.active() or {}
    scheduled = inspect.scheduled() or {}

    workers = [
        {
            "name": name,
            "pool_size": (info.get("pool") or {}).get("max-concurrency"),
            "active_tasks": len(active.get(name, [])),
            "scheduled_tasks": len(scheduled.get(name, [])),
        }
        for name, info in stats.items()
    ]
    return {"worker_count": len(workers), "workers": workers}


@router.get("/dead-letters")
def get_dead_letters(db: Session = Depends(get_db)):
    """Tasks that raised and were never recovered - see app.celery_app._capture_dead_letter."""
    rows = db.query(DeadLetter).order_by(DeadLetter.created_at.desc()).limit(100).all()
    return {
        "dead_letters": [
            {
                "id": r.id,
                "task_name": r.task_name,
                "task_id": r.task_id,
                "args": r.args,
                "exception": r.exception,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    }
