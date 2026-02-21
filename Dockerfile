# ============================================================
# Multi-stage production Dockerfile
# Stage 1: build dependencies
# Stage 2: lean runtime image with non-root user
# ============================================================

# ---------- Stage 1: dependency builder ----------
FROM python:3.12-slim AS builder

WORKDIR /build

# System libs needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---------- Stage 2: runtime image ----------
FROM python:3.12-slim AS runtime

# Runtime system lib for psycopg2 (PostgreSQL driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create a non-root user — never run as root in production
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false appuser

WORKDIR /app

# Copy application code (secrets and .env are never baked into the image)
COPY app/ ./app/

# Ownership to non-root user
RUN chown -R appuser:appgroup /app

USER appuser

# Cloud Run injects PORT; default to 8080
ENV PORT=8080

EXPOSE 8080

# Gunicorn with uvicorn workers for production
CMD exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 2 \
    --loop uvloop \
    --access-log
