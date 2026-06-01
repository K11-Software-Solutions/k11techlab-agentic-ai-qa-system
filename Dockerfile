# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY agents/     agents/
COPY mcps/       mcps/
COPY pipeline/   pipeline/
COPY api/        api/
COPY .env.example .env.example

# Create data directory for SQLite checkpointing
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 9000

CMD ["uvicorn", "api.webhook:app", "--host", "0.0.0.0", "--port", "9000"]
