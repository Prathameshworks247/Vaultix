import os 
from celery import Celery

app = Celery(
    "payment_gateway",
    broker=os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    backend=os.environ.get("CELERY_RESULT_BACKEND"),
)


