from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class MerchantCreate(BaseModel):
    name: str


class MerchantCreated(BaseModel):
    id: UUID
    name: str
    api_key: str  # shown once, at creation - not retrievable afterwards
    created_at: datetime
    model_config = {"from_attributes": True}


class WebhookRegister(BaseModel):
    url: HttpUrl
    # Optional - if omitted, the server generates one and returns it exactly once (it isn't
    # readable back afterwards, same as any API-key style secret).
    secret: Optional[str] = None


class WebhookOut(BaseModel):
    merchant_id: UUID
    url: Optional[str]
    # Only present in the response to a registration/rotation call, never on a plain read.
    secret: Optional[str] = None
