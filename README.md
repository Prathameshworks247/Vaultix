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
| 🔑 **API-key auth** | Every merchant-scoped endpoint requires `X-API-Key`; a merchant only ever sees or acts on its own payments |
| 💳 **Payment lifecycle** | `PENDING → PROCESSING → SUCCEEDED / FAILED → REFUNDED` state machine |
| 🔁 **Idempotency** | `Idempotency-Key` header, unique per merchant — retried requests never double-charge, and two merchants can't collide on the same key string |
| 📜 **Event sourcing (lite)** | Append-only `payment_events` audit log for every transition |
| 💱 **Multi-currency** | INR/USD/EUR accepted; `/admin/stats` converts everything to a base currency via static, env-overridable FX rates |
| 🐇 **Queue isolation** | Dedicated `payment`, `email`, `refund`, and `notification` queues — an email flood can never starve payment processing |
| ⛓️ **Celery chains** | `process_payment → fraud_check → send_receipt → notify_merchant` pipeline via Celery canvas |
| 🕵️ **Fraud detection** | Amount-threshold rule (> ₹50,000) + per-merchant velocity rule (> 10 payments/min) |
| ♻️ **Retries + backoff** | Simulated timeouts retry at 1s → 2s → 4s, capped at 3 attempts, then marked `FAILED` |
| 💸 **Safe refunds** | Row-level locking (`SELECT ... FOR UPDATE`) + state guards prevent double refunds |
| 🪝 **Signed webhooks** | HMAC-SHA256 payload signatures with exponential-backoff redelivery (up to 3 attempts) |
| ⏰ **Reconciliation** | Celery Beat nightly job sweeps payments stuck in `PROCESSING` and fails them cleanly |
| ☠️ **Dead-letter capture** | Any task that raises and is never recovered lands in `dead_letters` (`/admin/dead-letters`) instead of vanishing into a worker's stderr |
| 📊 **Observability** | `/admin/stats` metrics (admin-key protected), Celery worker introspection, structured JSON logs correlated by `payment_id`, optional Flower dashboard |
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
                  notification_queue      └─ notify_merchant (webhook if registered, else log)
               Celery Beat ──▶ nightly sweep of payments stuck in PROCESSING
```

**Design decisions worth noting:**

- **`Numeric(12, 2)`, never `Float`** — floats can't represent money exactly.
- **UUID primary keys** — safe to expose publicly, no guessable sequential IDs.
- **`task_acks_late=True` + `task_reject_on_worker_lost=True`** — messages are acknowledged only *after* a task finishes, and a worker that dies mid-task rejects (not silently drops) its message, giving at-least-once delivery. Tasks are written to be idempotent and re-read state from the DB on every attempt.
- **Merchant auth derives identity from the API key, not the request body** — `POST /payments` has no `merchant_id` field; the authenticated merchant *is* the owner. No path can be tricked into acting on someone else's data by naming their UUID.
- **Fraud flags annotate rather than block** — a flagged payment gets a `FRAUD_FLAGGED` event but continues through the pipeline, keeping the flow linear and the decision reversible.

## Quick Start

**Prerequisites:** Docker & Docker Compose.

```bash
git clone https://github.com/Prathameshworks247/Vaultix.git
cd Vaultix

docker compose up --build
```

Compose has defaults for everything, so this works with no `.env` file. `docker-compose.yml` reads `${VAR:-default}` for secrets (Postgres password, `ADMIN_API_KEY`, FX rates) so a real deployment can override them without editing the file — see [Deploying](#deploying) below. Copy `.env.example` to `.env` only if you want local (non-Docker) tooling like the tests to point at the containers' Postgres.

This starts six services, migrating the DB automatically on `api` startup (no separate `alembic upgrade` step needed):

| Service | Purpose | Port |
|---|---|---|
| `api` | FastAPI application | `8000` |
| `postgres` | Source of truth (payments, events, refunds) | `5433` (host) → `5432` |
| `rabbitmq` | Message broker (+ management UI) | `5672` / `15672` |
| `celery_worker` | Consumes all four task queues | — |
| `celery_beat` | Scheduled reconciliation jobs | — |
| `flower` | Visual Celery dashboard | `5555` |

Create a merchant to get an API key:

```bash
curl -X POST http://localhost:8000/merchants -H "Content-Type: application/json" -d '{"name": "Test Merchant"}'
# → {"id": "...", "name": "Test Merchant", "api_key": "..."}   -- shown once, save it
```

- API docs (Swagger): http://localhost:8000/docs
- RabbitMQ UI: http://localhost:15672 (`guest` / `guest`)
- Flower: http://localhost:5555

## API Walkthrough

### 1. Create a payment (idempotent)

```bash
curl -X POST http://localhost:8000/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <api-key-from-setup>" \
  -H "Idempotency-Key: order-42-attempt-1" \
  -d '{"amount": "499.00", "currency": "INR"}'
```

```json
{
  "id": "8f14e45f-ceea-467f-a9b2-7c3d0011a3c1",
  "merchant_id": "<merchant-uuid-from-setup>",
  "amount": "499.00",
  "currency": "INR",
  "status": "PENDING",
  "created_at": "2026-07-13T10:15:04Z"
}
```

The merchant is the one that authenticated, not a field you set — `merchant_id` comes from the API key, not the body. Send the same request again with the same `Idempotency-Key` → you get the **same payment back**, not a duplicate charge (unique per merchant, so another merchant reusing the same key string gets their own payment, not yours).

### 2. Watch it settle

```bash
curl http://localhost:8000/payments/8f14e45f-ceea-467f-a9b2-7c3d0011a3c1 \
  -H "X-API-Key: <api-key-from-setup>"
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
curl -X POST http://localhost:8000/payments/{id}/refund \
  -H "X-API-Key: <api-key-from-setup>" -H "Content-Type: application/json" -d '{}'
# → 202 Accepted  {"id": "...", "payment_id": "...", "amount": "499.00", "status": "PENDING", ...}
```

Omit `amount` for a full refund, or pass `{"amount": "100.00"}` for a partial one. Refunding a non-succeeded or already-refunded payment returns `409 Conflict`; a payment that isn't yours returns `404`, not a leak of its existence; only one active refund per payment is allowed.

### 4. Register a webhook

```bash
curl -X PUT http://localhost:8000/merchants/{merchant_id}/webhook \
  -H "X-API-Key: <api-key-from-setup>" -H "Content-Type: application/json" \
  -d '{"url": "https://merchant.example/hooks", "secret": "s3cret"}'
```

`merchant_id` in the path must match the authenticated merchant (`403` otherwise) — it's there for a readable URL, not as the actual authorization. On settlement, Vaultix POSTs `{payment_id, status}` to your URL with `X-Webhook-Signature` (HMAC-SHA256 of `"<timestamp>.<body>"`) and `X-Webhook-Timestamp` headers. Verify it server-side with `hmac.compare_digest`. No webhook registered → falls back to a log line instead.

### 5. Check system health (admin-key protected)

```bash
curl http://localhost:8000/admin/stats -H "X-Admin-Key: <ADMIN_API_KEY>"
# {"payments": {"total": 128, "by_status": {...}, "success_rate": 0.71,
#   "total_by_currency": {"INR": "...", "USD": "..."},
#   "total_in_base_currency": {"currency": "INR", "amount": "..."}}, "refunds": {...}}

curl http://localhost:8000/admin/queues -H "X-Admin-Key: <ADMIN_API_KEY>"        # per-queue backlog, read straight off the broker
curl http://localhost:8000/admin/workers -H "X-Admin-Key: <ADMIN_API_KEY>"       # live worker roster via Celery inspect
curl http://localhost:8000/admin/dead-letters -H "X-Admin-Key: <ADMIN_API_KEY>" # tasks that failed and were never recovered
```

## Project Structure

```
vaultix/
├── app/
│   ├── api/            # HTTP layer: merchants, payments, refunds, webhooks, admin
│   ├── core/            # API-key auth, rate limiter, structured logging (JSON, correlated by payment_id)
│   ├── models/         # SQLAlchemy: Merchant (api_key, webhook_url/secret), Payment, PaymentEvent, Refund, DeadLetter
│   ├── schemas/        # Pydantic request/response contracts
│   ├── services/       # Pure business logic (fraud rules, FX conversion)
│   ├── tasks/          # Celery app, queues, routing, all task definitions (incl. the Beat reaper)
│   ├── db/             # Engine, sessions, Alembic base
│   └── main.py         # FastAPI app + rate limiter
├── alembic/            # Schema migrations
├── tests/              # Unit, API/DB integration, and task tests
├── docker-compose.yml
└── README.md
```

## Running Tests

Tests use SQLite and Celery's `.apply()` (which always runs a task synchronously in-process), so they need **no Docker, Postgres, or broker at all**:

```bash
pip install -r requirements-dev.txt
pytest -v
```

Coverage includes input validation edge cases (negative amounts, unknown currencies), API-key auth (missing/wrong key, cross-merchant access denied on refunds and webhooks), a real multi-threaded idempotency-key race (including across two merchants sharing a key string), and refund state guards (including a genuine concurrent double-refund attempt).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/payment_db` | Postgres DSN |
| `CELERY_BROKER_URL` | `amqp://guest:guest@rabbitmq:5672//` | RabbitMQ broker |
| `CELERY_RESULT_BACKEND` | `db+postgresql://postgres:postgres@postgres:5432/payment_db` | Task result storage |
| `ADMIN_API_KEY` | `admin-dev-key` (compose default) | Required header value (`X-Admin-Key`) for all `/admin/*` routes — **unset in prod means those routes 401 unconditionally**, so it must be set, never left as the dev default |
| `FRAUD_AMOUNT_THRESHOLD` | `50000` | Amount above which payments are flagged |
| `FRAUD_VELOCITY_LIMIT` | `10` | Payments/minute per merchant before the velocity rule flags |
| `STUCK_PAYMENT_TIMEOUT_MINUTES` | `30` | How long a payment may sit in `PROCESSING` before Beat reaps it as `FAILED` |
| `FX_RATE_USD_INR`, `FX_RATE_EUR_INR` | `83`, `90` | Static conversion rates used by `/admin/stats`'s base-currency total |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `postgres` / `postgres` / `payment_db` | Override for a real deployment — never ship the defaults |

## Deploying

The base `docker-compose.yml` is dev-friendly (live-reload, bind-mounted source, hardcoded-but-overridable dev secrets). `docker-compose.prod.yml` is an overlay that strips that out — no reload, no bind mounts, `restart: unless-stopped`, 4 Uvicorn workers instead of 1:

```bash
# .env holds the real secrets - see .env.example / the Configuration table above
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The image itself runs as a non-root user and migrates the DB on every start (`alembic upgrade head` before the server boots), so a fresh deploy or a new migration landing never needs a manual step.

For a managed platform (Railway, Render, Fly.io, etc.) instead of raw Compose: point `DATABASE_URL` at a managed Postgres and `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` at a managed RabbitMQ (e.g. CloudAMQP) or swap the broker for Redis, then run three processes from the same image — `api` (the Dockerfile's default `CMD`), `celery -A app.celery_app worker`, and `celery -A app.celery_app beat` — each with the same env vars.

### Deploying to Render

Render has no managed RabbitMQ, so this uses Render's own managed Postgres + Key Value (Redis) as the broker instead — no third-party signup needed. `redis` is already in `requirements.txt` for this.

1. **Push to GitHub** (Render deploys from a repo, not a local build).

2. **New → PostgreSQL.** Note the *Internal Database URL* Render gives you — it starts with `postgres://`; SQLAlchemy needs `postgresql://`, so change the scheme when you paste it into `DATABASE_URL` below.

3. **New → Key Value** (Render's managed Redis). Note its *Internal Redis URL*.

4. **New → Web Service** for the API — connect the repo, environment **Docker**, Dockerfile at the repo root. Render injects its own `$PORT` and expects the app to bind to it, so override the **Start Command** (the Dockerfile's default `CMD` hardcodes `8000`):
   ```
   sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"
   ```
   Health check path: `/health`. Env vars:
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Postgres URL from step 2, `postgres://` → `postgresql://` |
   | `CELERY_BROKER_URL` | the Redis URL from step 3 |
   | `CELERY_RESULT_BACKEND` | `db+<same DATABASE_URL as above>` |
   | `ADMIN_API_KEY` | a strong random value |
   | `FX_RATE_USD_INR`, `FX_RATE_EUR_INR` | optional, defaults are fine |

5. **New → Background Worker**, same repo/Dockerfile/env vars as step 4, Start Command:
   ```
   celery -A app.celery_app worker --loglevel=info
   ```

6. **New → Background Worker** again for Beat, same env vars, Start Command:
   ```
   celery -A app.celery_app beat --loglevel=info
   ```
   (Flower is optional — skip it, or add it as its own Web Service with `celery -A app.celery_app flower --port=$PORT`.)

7. Once the API service is live, create your first merchant against its public URL:
   ```bash
   curl -X POST https://<your-render-api>.onrender.com/merchants \
     -H "Content-Type: application/json" -d '{"name": "Acme Corp"}'
   ```

Redeploys happen automatically on push once auto-deploy is on for each service (Render's own equivalent of the GitHub Actions workflow above — you don't need both).

### Deploying to Fly.io

The only realistically free option where the background worker and Beat actually run, not just the API — Fly's free allowance covers a few small always-on machines, which is enough for `api` + `worker` + `beat` at this scale. ("Free" here means Fly's current small usage credit + free machine allowance for new accounts, not an unconditional free tier forever — check Fly's current pricing page before relying on this long-term.) `fly.toml` in this repo already defines all three as process groups sharing one image.

1. **Install flyctl and log in:**
   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```

2. **Launch (from the repo root):**
   ```bash
   fly launch --no-deploy
   ```
   It detects the Dockerfile and this repo's `fly.toml` — say no to overwriting `fly.toml`, pick a region, and decline auto-deploy (we need secrets set first).

3. **Provision Postgres and attach it** (this sets the `DATABASE_URL` secret for you, already in the right `postgresql://` scheme — no manual fixup needed like Render):
   ```bash
   fly postgres create --name vaultix-db
   fly postgres attach vaultix-db
   ```

4. **Get a free Redis broker from [Upstash](https://upstash.com)** (their free tier persists, unlike Fly's Postgres-adjacent one) — create a database, copy its `rediss://` connection string.

5. **Set the remaining secrets:**
   ```bash
   fly secrets set \
     CELERY_BROKER_URL="rediss://<your-upstash-url>" \
     CELERY_RESULT_BACKEND="db+$(fly secrets list | grep DATABASE_URL)" \
     ADMIN_API_KEY="<strong-random-value>"
   ```
   (If that `CELERY_RESULT_BACKEND` one-liner doesn't resolve cleanly, just run `fly ssh console -C 'printenv DATABASE_URL'` after the first deploy, prefix it with `db+`, and set it directly.)

6. **Deploy, then scale the worker and beat process groups up from zero** (only `app` gets a machine by default):
   ```bash
   fly deploy
   fly scale count 1 --process-group worker
   fly scale count 1 --process-group beat
   ```

7. **Verify and create your first merchant:**
   ```bash
   curl https://vaultix.fly.dev/health
   curl -X POST https://vaultix.fly.dev/merchants -H "Content-Type: application/json" -d '{"name": "Acme Corp"}'
   ```

Redeploy any time with `fly deploy` (or wire the GitHub Actions workflow above to run `flyctl deploy` instead of the SSH/Compose script — swap the `script:` step for `flyctl deploy --remote-only` with a `FLY_API_TOKEN` secret).

### CI/CD

`.github/workflows/deploy.yml` SSHes into a server and redeploys on every push to `main` (or manually via the Actions tab): `git pull` → `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` → prunes dangling images → hits `/health` and fails the run if it doesn't come back up. It assumes the repo is already `git clone`d on the server once, with a working `.env` in place (see above) — the workflow only pulls and rebuilds, it doesn't bootstrap a fresh host.

Add these as repo secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `SSH_HOST` | Server IP or hostname |
| `SSH_USER` | SSH login user |
| `SSH_PRIVATE_KEY` | Private key for that user (deploy key with no passphrase) |
| `SSH_PORT` | Optional, defaults to `22` |
| `DEPLOY_PATH` | Absolute path to the cloned repo on the server, e.g. `/home/deploy/Vaultix` |
| `HEALTH_CHECK_URL` | Base URL the runner can reach, e.g. `http://your-server-ip:8000` |

## Roadmap

- [ ] Merchant self-service (rotate/revoke an API key; currently one-shot at creation)
- [ ] Live FX rates (currently a static, env-overridable table)

## License

MIT — see [LICENSE](LICENSE).