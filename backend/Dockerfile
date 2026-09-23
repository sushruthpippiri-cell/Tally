# Build context is the repo root (the backend depends on the shared contract package):
#   docker build -f backend/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /src
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY shared ./shared
COPY backend ./backend
COPY agent/pyproject.toml ./agent/pyproject.toml
COPY tools/pyproject.toml ./tools/pyproject.toml
RUN mkdir -p agent/tally_agent tools/tally_tools \
 && touch agent/tally_agent/__init__.py tools/tally_tools/__init__.py \
 && uv sync --frozen --no-dev --no-editable --package tally-backend

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --system --create-home --uid 10001 tally
COPY --from=builder /src/.venv /opt/venv
COPY --chown=tally:tally backend/alembic /app/alembic
COPY --chown=tally:tally backend/alembic.ini /app/alembic.ini
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
USER tally
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
