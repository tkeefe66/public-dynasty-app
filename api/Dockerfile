FROM python:3.11-slim AS base
WORKDIR /app

# Install the existing grader package + the API service.
COPY pyproject.toml uv.lock* ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY api ./api
RUN pip install --no-cache-dir -e ./api

ENV PYTHONUNBUFFERED=1 \
    TRADE_GRADER_CACHE_DIR=/data/sleeper-dynasty/cache

# Railway provides PORT via env.
EXPOSE 8000
# Apply identity-DB migrations as a deploy step (not in lifespan, to avoid
# multi-instance races), then start the server. alembic runs from /app/api
# where alembic.ini + migrations/ live; uvicorn runs from /app for the
# `api.uvicorn_entry` module path. Bind IPv6 (::) so Railway private networking
# (IPv6-only) can reach us; on Linux dual-stack this also accepts IPv4 traffic.
CMD ["sh", "-c", "cd /app/api && alembic upgrade head && cd /app && uvicorn api.uvicorn_entry:app --host :: --port ${PORT:-8000}"]
