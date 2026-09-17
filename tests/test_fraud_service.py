from decimal import Decimal

from app.models.payments import Payment
from app.services import fraud_service


def test_amount_threshold_flags_large_payment():
    payment = Payment(amount=Decimal("60000"))
    flags = fraud_service.check_amount_threshold(payment)
    assert flags and flags["rule"] == "amount_threshold"


def test_amount_threshold_clean_for_small_payment():
    payment = Payment(amount=Decimal("100"))
    assert fraud_service.check_amount_threshold(payment) is None


def test_velocity_flags_burst_of_payments(db, merchant):
    for _ in range(fraud_service.VELOCITY_LIMIT + 1):
        db.add(Payment(merchant_id=merchant.id, amount=Decimal("10"), currency="INR"))
    db.commit()
    latest = Payment(merchant_id=merchant.id, amount=Decimal("10"), currency="INR")
    db.add(latest)
    db.commit()

    flags = fraud_service.check_velocity(db, latest)
    assert flags and flags["rule"] == "velocity"


def test_velocity_clean_under_limit(db, merchant):
    payment = Payment(merchant_id=merchant.id, amount=Decimal("10"), currency="INR")
    db.add(payment)
    db.commit()
    assert fraud_service.check_velocity(db, payment) is None
