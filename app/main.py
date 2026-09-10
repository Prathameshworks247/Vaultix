import fastapi
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.limiter import limiter
from app.core.logging import configure_logging
from app.api.admin import router as admin_router
from app.api.payments import router as payments_router
from app.api.refunds import router as refunds_router
from app.api.webhooks import router as webhooks_router

configure_logging()

app = fastapi.FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(payments_router)
app.include_router(refunds_router)
app.include_router(webhooks_router)
app.include_router(admin_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}