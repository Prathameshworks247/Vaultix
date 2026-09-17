import os
from decimal import Decimal

BASE_CURRENCY = "INR"

# Static rates (units of BASE_CURRENCY per 1 unit of the currency), env-overridable - no live
# FX API. A demo/internal gateway doesn't need real-time rates, and pulling in an external
# rate provider would be a dependency for a number that's illustrative either way.
RATES = {
    "INR": Decimal("1"),
    "USD": Decimal(os.environ.get("FX_RATE_USD_INR", "83")),
    "EUR": Decimal(os.environ.get("FX_RATE_EUR_INR", "90")),
}


def to_base(amount: Decimal, currency: str) -> Decimal:
    return amount * RATES.get(currency, Decimal("1"))
