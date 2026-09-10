import contextvars
import json
import logging
import sys

# Set by bind_payment_id() and picked up by ContextFilter - lets every log line emitted
# anywhere during a task/request carry the payment_id without threading it through every
# logger.info() call by hand.
payment_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("payment_id", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.payment_id = payment_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payment_id = getattr(record, "payment_id", None)
        if payment_id:
            payload["payment_id"] = payment_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    """Point the root logger at a single JSON-lines handler. Safe to call more than once
    (API import, Celery's setup_logging signal) - each call just replaces the handler list
    rather than stacking duplicate handlers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class bind_payment_id:
    """Context manager - tag every log line emitted inside the block with a payment_id, so
    a task's whole log trail (received -> retried -> settled) can be grepped/filtered as one
    unit. Usage: `with bind_payment_id(payment_id): ...`"""

    def __init__(self, payment_id: str):
        self.payment_id = payment_id
        self._token = None

    def __enter__(self) -> "bind_payment_id":
        self._token = payment_id_var.set(self.payment_id)
        return self

    def __exit__(self, *exc_info) -> None:
        payment_id_var.reset(self._token)
