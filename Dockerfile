FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runs as a non-root user in prod - dev's bind-mounted volume keeps working since it's
# mounted at the same path this user already owns.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# ${PORT:-8000} - defaults to 8000 for docker-compose/Fly (no PORT set), but Render and
# similar platforms inject their own PORT and expect the app to bind to it.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
