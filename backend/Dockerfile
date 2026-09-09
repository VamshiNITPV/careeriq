# CareerIQ backend image.
#
# Multi-stage so the production image does not carry pytest, ruff, mypy, or a
# compiler. `development` adds dev tooling and runs with --reload.

# ---------------------------------------------------------------- base
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------- development
FROM base AS development

# Requirements are copied before the source so that editing application code
# does not invalidate the (slow) dependency layer.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------------------------------------------------------- ml
# The embedding worker, and nothing else.
#
# Same source tree, different dependency set. torch and sentence-transformers
# are well over a gigabyte and are never imported by the API, so putting them in
# `development` or `production` would put that cost on every API cold start for
# code the API never runs — the risk architecture.md's table names directly.
FROM base AS ml

COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt -r requirements-ml.txt

# The model is baked in rather than downloaded at runtime. That makes the image
# reproducible, lets the container work with no network, and means a crash loop
# cannot re-download 420 MB on every restart.
ENV HF_HOME=/opt/hf
ARG EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('${EMBEDDING_MODEL}')"

COPY . .

CMD ["python", "-m", "app.workers.embedding_worker"]

# ---------------------------------------------------------------- production
FROM base AS production

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Never run as root. A container escape from an unprivileged user is a much
# smaller problem than one from root (ADR-014).
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

# No --reload in production. Worker count is left to the platform: Cloud Run
# scales by instance, so a single worker per container is correct there (ADR-011).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
