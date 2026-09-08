from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.payments import Payment, PaymentEvent, PaymentStatus, Refund
from app.schemas.refunds import RefundCreate, RefundOut
from app.tasks.refund_tasks import process_refund

router = APIRouter(prefix="/payments", tags=["refunds"])


@router.post("/{payment_id}/refund", response_model=RefundOut, status_code=202)
def create_refund(payment_id: UUID, body: RefundCreate, db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "payment not found")

    # Fast, courtesy check - the authoritative guard (under a row lock) lives in the
    # refund task, since this check can race with an in-flight settlement.
    if payment.status != PaymentStatus.SUCCEEDED:
        raise HTTPException(409, "payment is not eligible for refund")

    amount = body.amount or payment.amount
    if amount > payment.amount:
        raise HTTPException(400, "refund amount exceeds payment amount")

    refund_id = uuid4()
    refund = Refund(id=refund_id, payment_id=payment.id, amount=amount, status="PENDING")
    db.add(refund)
    db.add(PaymentEvent(
        payment_id=payment.id,
        event_type="REFUND_REQUESTED",
        detail={"refund_id": str(refund_id), "amount": str(amount)},
    ))
    db.commit()

    process_refund.delay(str(refund_id))
    return refund
