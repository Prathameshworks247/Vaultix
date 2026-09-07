import os
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.payments import Payment

# Config-driven, not hard-coded: lets thresholds change without a code deploy.
AMOUNT_THRESHOLD = Decimal(os.environ.get("FRAUD_AMOUNT_THRESHOLD", "50000"))
VELOCITY_LIMIT = int(os.environ.get("FRAUD_VELOCITY_LIMIT", "10"))
VELOCITY_WINDOW_SECONDS = 60


def check_amount_threshold(payment: Payment) -> dict | None:
    """Flag payments larger than a fixed amount. Pure function - no DB, easy to unit test."""
    if payment.amount > AMOUNT_THRESHOLD:
        return {
            "rule": "amount_threshold",
            "amount": str(payment.amount),
            "threshold": str(AMOUNT_THRESHOLD),
        }
    return None


def check_velocity(db: Session, payment: Payment) -> dict | None:
    """Flag a merchant pushing an unusual number of payments in a short window."""
    window_start = datetime.utcnow() - timedelta(seconds=VELOCITY_WINDOW_SECONDS)
    count = (
        db.query(Payment)
        .filter(
            Payment.merchant_id == payment.merchant_id,
            Payment.created_at >= window_start,
        )
        .count()
    )
    if count > VELOCITY_LIMIT:
        return {
            "rule": "velocity",
            "count": count,
            "limit": VELOCITY_LIMIT,
            "window_seconds": VELOCITY_WINDOW_SECONDS,
        }
    return None


def evaluate(db: Session, payment: Payment) -> list[dict]:
    """Run all rules, return the list of triggered flags (empty if clean)."""
    checks = (check_amount_threshold(payment), check_velocity(db, payment))
    return [flag for flag in checks if flag]
