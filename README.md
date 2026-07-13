# Vaultix ⚡

**An asynchronous, event-driven payment gateway** built with FastAPI, PostgreSQL, RabbitMQ, and Celery — simulating how real gateways like Stripe and Razorpay decouple *accepting* a payment from *settling* it.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-broker-FF6600?logo=rabbitmq&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-workers-37814A?logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Why Vaultix?

Payment processing is slow, unreliable, and unforgiving of mistakes. A gateway can't block an HTTP request for 15 seconds while a bank responds, can't lose a payment because a server crashed, and can't ever charge a customer twice. Vaultix demonstrates the architecture patterns that solve these problems:

- **The API never processes payments inline.** It records intent in PostgreSQL, publishes a job to RabbitMQ, and returns in milliseconds.
- **Workers do the slow work** — processing, fraud checks, receipts, webhooks — and can crash and restart without losing a single job.
- **Every state transition is auditable** through an append-only event log.

## Features

| Feature | How it works |
|---|---|
| 💳 **Payment lifecycle** | `PENDING → PROCESSING → SUCCEEDED / FAILED → REFUNDED` state machine |
| 🔁 **Idempotency** | `Idempotency-Key` header + DB unique constraint — retried requests never double-charge |
| 📜 **Event sourcing (lite)** | Append-only `payment_events` audit log for every transition |
| 🐇 **Queue isolation** | Dedicated `payment`, `email`, `refund`, and `notification` queues — an email flood can never starve payment processing |
| ⛓️ **Celery chains** | `process_payment → fraud_check → send_receipt → notify_merchant` pipeline via Celery canvas |
| 🕵️ **Fraud detection** | Amount-threshold rule (> ₹50,000) + per-merchant velocity rule (> 10 payments/min) |
| ♻️ **Retries + backoff** | Simulated timeouts retry at 2s → 4s → 8s, capped at 3 attempts, then marked `FAILED` |
| 💸 **Safe refunds** | Row-level locking (`SELECT ... FOR UPDATE`) + state guards prevent double refunds |
| 🪝 **Signed webhooks** | HMAC-SHA256 payload signatures with exponential-backoff redelivery (up to 5 attempts) |
| ⏰ **Reconciliation** | Celery Beat nightly job sweeps payments stuck in `PROCESSING` and fails them cleanly |
| 📊 **Observability** | `/admin/stats` metrics, Celery worker introspection, structured JSON logs correlated by `payment_id`, optional Flower dashboard |
| 🚦 **Rate limiting** | Token-bucket limiting (100 req/min per client) via slowapi |

## Architecture

```
Client ──HTTP──▶ FastAPI (api)
                    │  1. validate + persist payment (PENDING)
                    │  2. write CREATED event
                    ▼
               PostgreSQL  ◀──────────────┐  status updates,
                    │                     │  event log
                    │ 3. publish task     │
                    ▼                     │
               RabbitMQ (broker) ──▶ Celery workers
                  queues:                 ├─ process_payment
                  payment_queue           ├─ fraud_check
                  email_queue             ├─ send_receipt / notify_merchant
                  refund_queue            ├─ process_refund
                  notification_queue      └─ deliver_webhook
               Celery Beat ──▶ scheduled cleanup of stuck payments
```

**Design decisions worth noting:**

- **`Numeric(12, 2)`, never `Float`** — floats can't represent money exactly.
- **UUID primary keys** — safe to expose publicly, no guessable sequential IDs.
- **`task_acks_late=True`** — messages are acknowledged only *after* a task finishes, giving at-least-once delivery. Tasks are written to be idempotent and re-read state from the DB on every attempt.
- **Fraud flags annotate rather than block** — a flagged payment gets a `FRAUD_FLAGGED` event but continues through the pipeline, keeping the flow linear and the decision reversible.

## Quick Start

**Prerequisites:** Docker & Docker Compose.

```bash
git clone https://github.com/Prathameshworks247/Vaultix.git
cd Vaultix

cp .env.example .env          # defaults work out of the box
docker compose up --build
```

This starts five services:

| Service | Purpose | Port |
|---|---|---|
| `api` | FastAPI application | `8000` |
| `postgres` | Source of truth (payments, events, refunds) | `5432` |
| `rabbitmq` | Message broker (+ management UI) | `5672` / `15672` |
| `celery_worker` | Consumes all four task queues | — |
| `celery_beat` | Scheduled reconciliation jobs | — |

Then run migrations:

```bash
docker compose exec api alembic upgrade head
```

- API docs (Swagger): http://localhost:8000/docs
- RabbitMQ UI: http://localhost:15672 (`guest` / `guest`)

## API Walkthrough

### 1. Create a payment (idempotent)

```bash
curl -X POST http://localhost:8000/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-42-attempt-1" \
  -d '{"merchant_id": "m_123", "amount": "499.00", "currency": "INR"}'
```

```json
{
  "id": "8f14e45f-ceea-467f-a9b2-7c3d0011a3c1",
  "merchant_id": "m_123",
  "amount": "499.00",
  "currency": "INR",
  "status": "PENDING",
  "created_at": "2026-07-13T10:15:04Z"
}
```

Send the same request again with the same `Idempotency-Key` → you get the **same payment back**, not a duplicate charge.

### 2. Watch it settle

```bash
curl http://localhost:8000/payments/8f14e45f-ceea-467f-a9b2-7c3d0011a3c1
```

The response includes the full event history:

```json
{
  "status": "SUCCEEDED",
  "events": [
    {"type": "CREATED",    "at": "2026-07-13T10:15:04Z"},
    {"type": "PROCESSING", "at": "2026-07-13T10:15:05Z", "detail": {"attempt": 1}},
    {"type": "SUCCEEDED",  "at": "2026-07-13T10:15:13Z"},
    {"type": "RECEIPT_SENT", "at": "2026-07-13T10:15:14Z"}
  ]
}
```

Processing is simulated: each payment takes 5–15s and resolves **70% success / 20% failure / 10% timeout** (timeouts trigger the retry-with-backoff path).

### 3. Refund it

```bash
curl -X POST http://localhost:8000/payments/{id}/refund
# → 202 Accepted  {"refund_id": "...", "status": "PENDING"}
```

Refunding a non-succeeded or already-refunded payment returns `409 Conflict`.

### 4. Register a webhook

```bash
curl -X PUT "http://localhost:8000/webhooks/m_123?url=https://merchant.example/hooks&secret=s3cret"
```

On settlement, Vaultix POSTs `{payment_id, status}` to your URL with an `X-Gateway-Signature` header (HMAC-SHA256 of the raw body). Verify it server-side with `hmac.compare_digest`.

### 5. Check system health

```bash
curl http://localhost:8000/admin/stats
# {"total": 128, "by_status": {...}, "success_rate": 0.71, "failure_rate": 0.22}
```

## Project Structure

```
vaultix/
├── app/
│   ├── api/            # HTTP layer: payments, refunds, webhooks, admin
│   ├── models/         # SQLAlchemy: Payment, PaymentEvent, Refund, WebhookEndpoint
│   ├── schemas/        # Pydantic request/response contracts
│   ├── services/       # Pure business logic (fraud rules, etc.)
│   ├── tasks/          # Celery app, queues, routing, all task definitions
│   ├── db/             # Engine, sessions, Alembic base
│   └── main.py         # FastAPI app + rate limiter
├── alembic/            # Schema migrations
├── tests/              # Unit, integration, and eager-mode task tests
├── docker-compose.yml
└── README.md
```

## Running Tests

Tests run Celery tasks **in-process** (`task_always_eager=True`), so CI needs no broker or worker:

```bash
docker compose exec api pytest -v
```

Coverage includes input validation edge cases (negative amounts, unknown currencies), idempotency race handling, and refund state guards.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://gateway:gateway@postgres:5432/gateway` | Postgres DSN |
| `CELERY_BROKER_URL` | `amqp://guest:guest@rabbitmq:5672//` | RabbitMQ broker |
| `CELERY_RESULT_BACKEND` | `db+postgresql://...` | Task result storage |
| `FRAUD_AMOUNT_THRESHOLD` | `50000` | Amount above which payments are flagged |

## Roadmap

- [ ] Multi-currency support with conversion rates
- [ ] Partial refunds
- [ ] Merchant-level API keys / auth
- [ ] Dead-letter queue handling for permanently failed messages

## License

MIT — see [LICENSE](LICENSE).