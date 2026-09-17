from decimal import Decimal

from app.models.payments import Payment, PaymentStatus, Refund
from app.tasks.refund_tasks import process_refund


def _succeeded_payment(db, merchant, amount="100.00"):
    p = Payment(merchant_id=merchant.id, amount=Decimal(amount), currency="INR", status=PaymentStatus.SUCCEEDED)
    db.add(p)
    db.commit()
    return p


def test_process_refund_completes_for_succeeded_payment(db, merchant):
    payment = _succeeded_payment(db, merchant)
    refund = Refund(payment_id=payment.id, amount=payment.amount, status="PENDING")
    db.add(refund)
    db.commit()

    process_refund.apply(args=[refund.id])

    db.refresh(refund)
    db.refresh(payment)
    assert refund.status == "COMPLETED"
    assert payment.status == PaymentStatus.REFUNDED


def test_process_refund_rejects_non_succeeded_payment(db, merchant):
    payment = Payment(merchant_id=merchant.id, amount=Decimal("50"), currency="INR", status=PaymentStatus.FAILED)
    db.add(payment)
    db.commit()
    refund = Refund(payment_id=payment.id, amount=payment.amount, status="PENDING")
    db.add(refund)
    db.commit()

    process_refund.apply(args=[refund.id])

    db.refresh(refund)
    assert refund.status == "FAILED"


def test_process_refund_rejects_second_active_refund(db, merchant):
    payment = _succeeded_payment(db, merchant)
    first = Refund(payment_id=payment.id, amount=Decimal("50"), status="PENDING")
    second = Refund(payment_id=payment.id, amount=Decimal("50"), status="PENDING")
    db.add_all([first, second])
    db.commit()

    process_refund.apply(args=[first.id])
    process_refund.apply(args=[second.id])

    db.refresh(first)
    db.refresh(second)
    # Exactly one of the two competing refunds should win - never both.
    statuses = {first.status, second.status}
    assert statuses == {"COMPLETED", "FAILED"}


def test_process_refund_is_idempotent_on_redelivery(db, merchant):
    payment = _succeeded_payment(db, merchant)
    refund = Refund(payment_id=payment.id, amount=payment.amount, status="PENDING")
    db.add(refund)
    db.commit()

    process_refund.apply(args=[refund.id])
    process_refund.apply(args=[refund.id])  # simulated broker redelivery

    db.refresh(payment)
    assert payment.status == PaymentStatus.REFUNDED
