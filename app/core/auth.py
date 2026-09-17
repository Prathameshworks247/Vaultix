import os
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.payments import Merchant

# Static shared secret for /admin/* - an operator concern, not tied to any merchant.
# No default: an unset ADMIN_API_KEY disables the admin routes entirely rather than silently
# leaving them open, so a prod deploy can't forget to set it and end up unauthenticated.
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY")


def require_merchant(x_api_key: Optional[str] = Header(default=None), db: Session = Depends(get_db)) -> Merchant:
    # Header(default=None) + a manual check, rather than Header(...), so a missing key
    # returns the same 401 as a wrong one - not FastAPI's 422 "field required".
    merchant = db.query(Merchant).filter_by(api_key=x_api_key).first() if x_api_key else None
    if not merchant:
        raise HTTPException(401, "invalid API key")
    return merchant


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(401, "invalid admin key")
