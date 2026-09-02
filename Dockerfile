# Fase 8.1 — Multi-stage, non-root, layer cache, copy migrations
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for building psycopg/asyncpg etc. — minimal
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app \
    && chown appuser:appuser /app

WORKDIR /app

# Install runtime system deps (curl for healthcheck, libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python deps from builder
COPY --from=builder /install /usr/local

# Copy app code + migrations for alembic
COPY --chown=appuser:appuser ./app /app/app
COPY --chown=appuser:appuser alembic.ini /app/alembic.ini
COPY --chown=appuser:appuser migrations /app/migrations
COPY --chown=appuser:appuser pyproject.toml /app/pyproject.toml

# Env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

USER appuser

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8005/health/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
