from decimal import Decimal
from typing import Optional 
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from uuid import UUID

SUPPORTED = {"INR", "USD", "EUR"}

class PaymentCreate(BaseModel):
    merchant_id: str
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = "INR"
    
    @field_validator("currency")
    @classmethod
    def check_currency(cls,v):
        v = v.upper()
        if v not in SUPPORTED:
            raise ValueError(f"unsupported currency {v}")
        return v
    
class PaymentOut(BaseModel):
    id: UUID
    merchant_id: str
    amount: Decimal
    currency:str
    status: str
    created_at: datetime
    model_config = {"from_attributes":True}
        
    
        