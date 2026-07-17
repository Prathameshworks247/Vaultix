from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.payments import Payment, PaymentEvent,PaymentStatus
from app.schemas.payments import PaymentCreate, PaymentOut
from app.tasks.payment_tasks import payment_pipeline

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post(" ", response_model = PaymentOut, status_code=201)
def create_payment(body: PaymentCreate,
                   db:Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None)):
    if idempotency_key:
        existing = (db.query(Payment).filter_by(idempotency_key = idempotency_key).first())
        if existing:
            return existing
    
    payment = Payment(merchant_id = body.merchant_id, amount = body.amount, currency = body.currency, idempotency_key = idempotency_key)
    db.add(payment)
    db.add(PaymentEvent(payment = payment, event_type = "CREATED", details = {"amount": str(body.amount)}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (db.query(payment).filter_by(idempotency_key=idempotency_key).one())
    payment_pipeline(str(payment.id))
    return payment

@router.get("", response_model=list[PaymentOut])
def list_payments(status: PaymentStatus| None = None, db: Session = Depends(get_db)):
    q = db.query(Payment)
    if status:
        q = q.filter({Payment.status == status})
    return q.order_by(Payment.created_at.desc()).limit(100).all()

@router.get("/payment_id")
def get_payment(payment_id: UUID, db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(404, "payment not found")
    return  {**PaymentOut.model_validate(p).model_dump(),"events": [{"type": e.event_type, "at": e.created_at,"detail": e.detail} for e in p.events]}
