import logging

from app.celery_app import app
from app.core.logging import bind_payment_id
from app.db.session import SessionLocal
from app.models.payments import Payment, PaymentEvent, PaymentStatus, Refund

logger = logging.getLogger(__name__)


@app.task(name="tasks.process_refund", bind=True, max_retries=3)
def process_refund(self, refund_id: str):
    db = SessionLocal()
    try:
        refund = db.get(Refund, refund_id)
        if refund is None or refund.status != "PENDING":
            # Unknown refund, or a redelivered message for one we already finished -
            # idempotency keyed on the refund's own state, not a separate dedupe table.
            return refund_id

        with bind_payment_id(str(refund.payment_id)):
            # Lock the payment row for the rest of this transaction. A second refund request
            # (or a settlement still in flight) racing this one blocks here until we commit,
            # instead of both readers seeing "SUCCEEDED, no refund yet" and both proceeding.
            payment = db.query(Payment).filter_by(id=refund.payment_id).with_for_update().one()

            active_refund_exists = (
                db.query(Refund)
                .filter(
                    Refund.payment_id == payment.id,
                    Refund.status != "FAILED",
                    Refund.id != refund.id,
                )
                .first()
                is not None
            )

            # Authoritative check happens here, under the lock - not just in the API - because
            # the API's check can race with an in-flight settlement or a concurrent refund request.
            if payment.status != PaymentStatus.SUCCEEDED or active_refund_exists:
                refund.status = "FAILED"
                db.add(PaymentEvent(
                    payment_id=payment.id,
                    event_type="REFUND_FAILED",
                    detail={"refund_id": str(refund.id), "reason": "not_refundable"},
                ))
                db.commit()
                logger.warning(f"refund {refund_id} rejected: not refundable")
                return refund_id

            # Simulate calling out to the bank/processor to reverse the charge.
            refund.status = "COMPLETED"
            payment.status = PaymentStatus.REFUNDED
            db.add(PaymentEvent(
                payment_id=payment.id,
                event_type="REFUNDED",
                detail={"refund_id": str(refund.id), "amount": str(refund.amount)},
            ))
            db.commit()
            logger.info(f"refund {refund_id} completed: amount={refund.amount}")
            return refund_id
    finally:
        db.close()
