import os 
from celery import Celery
from kombu import Queue
app = Celery(
    "payment_gateway",
    broker=os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    backend=os.environ.get("CELERY_RESULT_BACKEND"),
    include=[
        "app.tasks.payment_tasks",
        "app.tasks.email_tasks",
        "app.tasks.refund_tasks",
    ],
)

app.conf.task_queues = (
    Queue("payment_queue"),
    Queue("email_queue"),
    Queue("refund_queue"),
    Queue("notification_queue"),
)

app.conf.task_default_queue = "payment_queue"

app.conf.task_routes = {
    "tasks.process_payment": {"queue": "payment_queue"},
    "tasks.fraud_check": {"queue": "payment_queue"},
    "tasks.send_receipt": {"queue": "email_queue"},
    "tasks.notify_merchant": {"queue": "notification_queue"},
    "tasks.process_refund": {"queue": "refund_queue"},
}

@app.task(name="tasks.hello_world")
def hello_world():
    print("hello from the celery worker")
    return "pong"

app.autodiscover_tasks(["app"], related_name="tasks")

