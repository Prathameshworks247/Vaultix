import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.payments import Merchant
from app.schemas.merchants import WebhookOut, WebhookRegister

router = APIRouter(prefix="/merchants", tags=["webhooks"])


@router.put("/{merchant_id}/webhook", response_model=WebhookOut)
def register_webhook(merchant_id: UUID, body: WebhookRegister, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "merchant not found")

    merchant.webhook_url = str(body.url)
    # A caller can pin their own secret (e.g. re-registering the same value their receiver
    # already has); otherwise mint one so the URL isn't usable without it.
    merchant.webhook_secret = body.secret or secrets.token_hex(32)
    db.commit()

    return WebhookOut(merchant_id=merchant.id, url=merchant.webhook_url, secret=merchant.webhook_secret)


@router.delete("/{merchant_id}/webhook", status_code=204)
def delete_webhook(merchant_id: UUID, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "merchant not found")

    merchant.webhook_url = None
    merchant.webhook_secret = None
    db.commit()


@router.get("/{merchant_id}/webhook", response_model=WebhookOut)
def get_webhook(merchant_id: UUID, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "merchant not found")

    # Secret is write-only past this point - never echoed back on a plain read.
    return WebhookOut(merchant_id=merchant.id, url=merchant.webhook_url, secret=None)
