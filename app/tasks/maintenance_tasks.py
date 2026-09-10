import logging
import os
from datetime import datetime, timedelta

from app.celery_app import app
from app.core.logging import bind_payment_id
from app.db.session import SessionLocal
from app.models.payments import Payment, PaymentEvent, PaymentStatus
from app.tasks.email_tasks import notify_merchant

logger = logging.getLogger(__name__)

# How long a payment may sit in PROCESSING before we consider it stuck. process_payment's
# own retry/backoff loop settles well within a minute (sleep 5-15s + up to 3 retries), so
# anything still PROCESSING past this window means the worker that owned it died or the
# task message was lost - not that it's legitimately still working.
STUCK_PAYMENT_TIMEOUT_MINUTES = int(os.environ.get("STUCK_PAYMENT_TIMEOUT_MINUTES", "30"))


@app.task(name="tasks.reap_stuck_payments")
def reap_stuck_payments():
    cutoff = datetime.utcnow() - timedelta(minutes=STUCK_PAYMENT_TIMEOUT_MINUTES)
    db = SessionLocal()
    reaped = []
    try:
        stuck_ids = [
            row.id
            for row in db.query(Payment.id)
            .filter(Payment.status == PaymentStatus.PROCESSING, Payment.updated_at < cutoff)
            .all()
        ]

        for payment_id in stuck_ids:
            # Lock the row and re-check status under the lock - a worker could still be mid-commit
            # on this payment (finishing right as the reaper runs), so re-verify before flipping it.
            payment = (
                db.query(Payment)
                .filter_by(id=payment_id)
                .with_for_update()
                .one_or_none()
            )
            if payment is None or payment.status != PaymentStatus.PROCESSING or payment.updated_at >= cutoff:
                db.rollback()
                continue

            payment.status = PaymentStatus.FAILED
            db.add(PaymentEvent(
                payment_id=payment.id,
                event_type="FAILED",
                detail={
                    "reason": "stuck_in_processing",
                    "timeout_minutes": STUCK_PAYMENT_TIMEOUT_MINUTES,
                },
            ))
            db.commit()
            with bind_payment_id(str(payment.id)):
                logger.warning(f"reaped stuck payment (idle past {STUCK_PAYMENT_TIMEOUT_MINUTES}m in PROCESSING)")
            reaped.append(str(payment.id))

        for payment_id in reaped:
            notify_merchant.delay(payment_id)

        if reaped:
            logger.info(f"reap_stuck_payments: reaped {len(reaped)} payment(s)")
        return reaped
    finally:
        db.close()
