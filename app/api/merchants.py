import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.payments import Merchant
from app.schemas.merchants import MerchantCreate, MerchantCreated

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.post("", response_model=MerchantCreated, status_code=201)
def create_merchant(body: MerchantCreate, db: Session = Depends(get_db)):
    merchant = Merchant(name=body.name, api_key=secrets.token_urlsafe(32))
    db.add(merchant)
    db.commit()
    return merchant
