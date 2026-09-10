from typing import Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl


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
