from datetime import datetime, timedelta
from decimal import Decimal

from app.models.payments import Payment, PaymentStatus
from app.tasks import maintenance_tasks


def test_reaps_payment_stuck_past_timeout(db, merchant, monkeypatch):
    monkeypatch.setattr(maintenance_tasks.notify_merchant, "delay", lambda payment_id: None)

    stale = Payment(
        merchant_id=merchant.id, amount=Decimal("10"), currency="INR",
        status=PaymentStatus.PROCESSING,
    )
    db.add(stale)
    db.commit()
    # Backdate past the timeout window directly - simulates a payment that's been sitting
    # in PROCESSING since before the cutoff (a real payment's updated_at ticks on its own).
    stale.updated_at = datetime.utcnow() - timedelta(minutes=maintenance_tasks.STUCK_PAYMENT_TIMEOUT_MINUTES + 1)
    db.commit()

    reaped = maintenance_tasks.reap_stuck_payments.apply().result

    db.refresh(stale)
    assert str(stale.id) in reaped
    assert stale.status == PaymentStatus.FAILED


def test_leaves_fresh_processing_payment_alone(db, merchant, monkeypatch):
    monkeypatch.setattr(maintenance_tasks.notify_merchant, "delay", lambda payment_id: None)

    fresh = Payment(
        merchant_id=merchant.id, amount=Decimal("10"), currency="INR",
        status=PaymentStatus.PROCESSING,
    )
    db.add(fresh)
    db.commit()

    reaped = maintenance_tasks.reap_stuck_payments.apply().result

    db.refresh(fresh)
    assert reaped == []
    assert fresh.status == PaymentStatus.PROCESSING
