import enum, uuid
from datetime import datetime
from sqlalchemy import (Column, String, Numeric, DateTime, Enum,
ForeignKey, Integer, JSON)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    
class Payment(Base):
    __tablename__ = "payments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(String, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False) # never float for money!
    currency = Column(String(3), nullable=False, default="INR")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING, index=True)
    idempotency_key = Column(String, unique=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow,
    onupdate=datetime.utcnow)
    events = relationship("PaymentEvent", back_populates="payment",
    order_by="PaymentEvent.created_at")
    refunds = relationship("Refund", back_populates="payment")

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