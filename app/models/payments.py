import enum, uuid
from datetime import datetime
from sqlalchemy import (Column, String, Numeric, DateTime, Enum,
ForeignKey, Integer, JSON, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    
class Merchant(Base):
    __tablename__ = "merchants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    api_key = Column(String, unique=True, nullable=True, index=True)  # None = merchant can't authenticate yet
    webhook_url = Column(String, nullable=True)
    webhook_secret = Column(String, nullable=True)  # HMAC key used to sign outbound webhook payloads
    created_at = Column(DateTime, default=datetime.utcnow)
    payments = relationship("Payment", back_populates="merchant")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False) # never float for money!
    currency = Column(String(3), nullable=False, default="INR")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING, index=True)
    # Scoped per-merchant, not globally unique - two different merchants picking the same
    # key string (e.g. both using "order-1") must not collide or leak each other's payment.
    idempotency_key = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow,
    onupdate=datetime.utcnow)
    merchant = relationship("Merchant", back_populates="payments")
    events = relationship("PaymentEvent", back_populates="payment",
    order_by="PaymentEvent.created_at")
    refunds = relationship("Refund", back_populates="payment")

    __table_args__ = (UniqueConstraint("merchant_id", "idempotency_key", name="uq_merchant_idempotency_key"),)

class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id = Column(Integer, primary_key=True)
    payment_id = Column(UUID(as_uuid=True),ForeignKey("payments.id"), index=True)
    event_type = Column(String, nullable=False)
    detail = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    payment = relationship("Payment", back_populates="events")
    
# CREATED, PROCESSING, ...
class Refund(Base):
    __tablename__ = "refunds"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(UUID(as_uuid=True),ForeignKey("payments.id"), index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String, default="PENDING") # PENDING/COMPLETED/FAILED
    created_at = Column(DateTime, default=datetime.utcnow)
    payment = relationship("Payment", back_populates="refunds")


class DeadLetter(Base):
    """A task that raised an exception Celery never recovered from (a bug, a DB outage, a
    worker crash mid-retry) - captured via the task_failure signal so nothing that fails
    unexpectedly just vanishes into a worker's stderr. Business-outcome failures (a declined
    payment, exhausted webhook retries) are already recorded as PaymentEvents and never land
    here - this table is only for the unanticipated kind."""
    __tablename__ = "dead_letters"
    id = Column(Integer, primary_key=True)
    task_name = Column(String, nullable=False)
    task_id = Column(String, nullable=False)
    args = Column(JSON, default=list)
    exception = Column(String, nullable=False)
    traceback = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)