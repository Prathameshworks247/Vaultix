from decimal import Decimal
from typing import Optional
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RefundCreate(BaseModel):
    # Omit amount for a full refund. Partial refunds (amount < payment.amount) are
    # accepted here but the stretch-goal support for *multiple* partial refunds against
    # one payment isn't built yet - only one active refund per payment is allowed for now.
    amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class RefundOut(BaseModel):
    id: UUID
    payment_id: UUID
    amount: Decimal
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}
