# CareerIQ — AI Career Intelligence & Job Optimization Platform

A full-stack AI/ML platform that builds a structured career profile from a resume, ingests and
parses job descriptions, ranks jobs by personalized fit using hybrid semantic + rule-based scoring,
identifies skill gaps, suggests grounded resume improvements, tracks application outcomes, and
conducts adaptive AI mock interviews.

> **Status:** Phase 1 (Architecture) — in progress.

---

## Why this project exists

Job searching is fragmented. A candidate manually reads hundreds of job descriptions, guesses
whether they qualify, compares their resume against requirements, identifies missing skills,
rewrites their resume, prepares for interviews, tracks applications, and never learns *why*
applications succeed or fail.

CareerIQ turns that into one instrumented, measurable system.

---

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Query, React Router, Recharts |
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic |
| Database | PostgreSQL 16 + `pgvector` |
| Cache / Queue | Redis 7 |
| AI / ML | spaCy, Sentence Transformers, Google Gemini (behind a provider abstraction) |
| Infrastructure | Docker Compose (local), GCP Cloud Run + Cloud SQL + Cloud Storage + Pub/Sub |
| CI/CD | GitHub Actions |
| Testing | Pytest, Vitest, React Testing Library |

---

## Repository layout

```
careeriq/
├── frontend/            React + TypeScript SPA
│   └── src/
│       ├── components/  Reusable presentational components
│       ├── pages/       Route-level views
│       ├── hooks/       Custom React hooks (data fetching, auth, websockets)
│       ├── services/    API client layer
│       ├── types/       Shared TypeScript types (mirrors backend schemas)
│       └── utils/       Pure helpers
│
├── backend/             FastAPI application
│   ├── app/
│   │   ├── api/         HTTP routers — request/response only, no business logic
│   │   ├── core/        Config, security, logging, dependencies
│   │   ├── models/      SQLAlchemy ORM models
│   │   ├── schemas/     Pydantic request/response schemas
│   │   ├── services/    Business logic — the layer that owns the rules
│   │   ├── repositories/Data access — the only layer that touches the ORM session
│   │   └── workers/     Background task handlers
│   └── tests/           unit / integration / api
│
├── ml/                  Offline ML work, kept out of the request path
│   ├── embeddings/      Embedding model wrappers and batching
│   ├── ranking/         Hybrid ranking, later a learned ranker
│   ├── classification/  Skill / seniority classifiers
│   ├── evaluation/      Metrics: Precision@K, NDCG@K, F1
│   └── datasets/        Labelled evaluation sets
│
├── infrastructure/
│   ├── docker/          Dockerfiles
│   ├── gcp/             Deployment configs
│   └── github-actions/  Reusable workflow fragments
│
└── docs/
    ├── architecture.md  Every significant decision + its rationale
    ├── requirements.md  Scope, personas, user stories, acceptance criteria
    ├── database.md      Full schema, relationships, indexes
    ├── api.md           REST contract
    └── ml.md            Models, ranking formula, evaluation methodology
```

---

## Documentation

Read these in order:

1. [docs/requirements.md](docs/requirements.md) — what we are building and for whom
2. [docs/architecture.md](docs/architecture.md) — how it is structured and **why**
3. [docs/database.md](docs/database.md) — the data model
4. [docs/api.md](docs/api.md) — the REST contract
5. [docs/ml.md](docs/ml.md) — the AI/ML design and how it is measured

---

## Development roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Architecture, requirements, schema, API design | ✅ Done |
| 2 | Backend foundation — FastAPI, Postgres, SQLAlchemy, Alembic, auth | ✅ Done |
| 3 | Frontend foundation — React, TypeScript, auth, dashboard shell | ✅ Done |
| 3.5 | Transactional email — password reset, email verification, security notices | ✅ Done |
| 4 | Resume intelligence — upload, parsing, NLP, structured profile | ✅ Done |
| 5 | Job intelligence — ingestion, JD parsing, skill extraction, dedup | ⬜ |
| 6 | AI matching — embeddings, pgvector, semantic search, hybrid ranking | ⬜ |
| 7 | Career intelligence — skill gaps, learning paths, resume optimization | ⬜ |
| 8 | Application system — tracking, analytics, outcome analysis | ⬜ |
| 9 | AI interview — question generation, adaptive engine, evaluation | ⬜ |
| 10 | Production engineering — Redis, background jobs, WebSockets, security | ⬜ |
| 11 | Cloud — Docker, GCP, CI/CD, monitoring | ⬜ |
| 12 | Final polish — testing, documentation, diagrams, demo | ⬜ |

---

## Getting started

**Prerequisite:** Docker Desktop (WSL2 backend on Windows).

```bash
# 1. Configure
cp .env.example .env

# 2. Generate a real JWT secret and paste it into .env as JWT_SECRET_KEY.
#    Startup fails loudly if it is left as the placeholder.
python -c "import secrets; print(secrets.token_urlsafe(64))"

# 3. Start Postgres (with pgvector) and Redis
docker compose up -d postgres redis

# 4. Create the schema
docker compose run --rm backend alembic upgrade head

# 5. Start the API and the web app
docker compose up -d
```

| | URL |
|---|---|
| Web app | **http://localhost:5173** |
| API | **http://localhost:8000** |
| API docs (Swagger) | http://localhost:8000/docs |
| OpenAPI schema | http://localhost:8000/openapi.json |
| **Mail inbox (Mailpit)** | **http://localhost:8025** |

> **Emails go to Mailpit, not to real addresses.** Registration, password reset
> and security notices are all sent locally and readable at
> [localhost:8025](http://localhost:8025) — so the flows can be exercised end to
> end without a provider account and without any risk of emailing a real person
> from test data (ADR-017).

The browser only ever calls `/api` on the web app's own origin; Vite proxies
that to the backend, so local development is same-origin and CORS is never
exercised — a CORS misconfiguration cannot hide until deployment.

> **Port already in use?** All three host ports are configurable in `.env` —
> `BACKEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT`. Container ports never change, and
> services inside the compose network always reach `postgres:5432` / `redis:6379`
> regardless. Check with `netstat -ano | findstr :5432`.
>
> ⚠️ **A native PostgreSQL install is the dangerous case.** On Windows a second
> process can bind an already-used port *instead of failing*, so both your native
> server and Docker end up listening on `5432` and the native one answers. The
> containers look healthy, the app works (it uses the internal network), but
> pgAdmin/DBeaver or any host-side script silently talks to the wrong database.
> Set `POSTGRES_PORT=5433` and confirm with:
>
> ```bash
> docker exec careeriq-postgres psql -U careeriq -d careeriq -tAc "SELECT version();"
> ```

### Common commands

```bash
docker compose run --rm backend pytest                  # full test suite
docker compose run --rm backend pytest tests/unit -q    # unit tests only
docker compose run --rm backend ruff check app tests    # lint
docker compose run --rm backend ruff format app tests   # format
docker compose run --rm backend alembic check           # detect model/schema drift
docker compose run --rm backend alembic revision --autogenerate -m "message"
docker compose logs -f backend                          # tail logs
docker compose down                                     # stop (data survives)
docker compose down -v                                  # stop and DELETE the database
```

Frontend:

```bash
docker compose run --rm frontend npm test               # vitest
docker compose run --rm frontend npm run typecheck      # tsc
docker compose run --rm frontend npm run lint           # eslint
docker compose run --rm frontend npm run build          # production bundle
```

> `node_modules` deliberately lives in a container volume, not on the host — it
> is 165 MB across 350 packages, and this repository sits in a OneDrive folder.
> Run npm through `docker compose` as above rather than installing locally.

### Verifying it works

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/ready

curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"correct-horse-9"}'
```

### Notes for this repository

This repository lives inside a OneDrive-synced folder. OneDrive converts empty
files into cloud-only placeholders that Docker's build cannot read, and it will
try to sync `node_modules/` and virtualenvs. If a build fails with
`invalid file request`, or `npm install` hits file-lock errors, that is the
cause — see ADR-016 in [docs/architecture.md](docs/architecture.md).

---

## Engineering principles

1. **Never invent candidate data.** The AI may rephrase, restructure, and highlight what exists in
   a resume. It must never fabricate experience, skills, metrics, or achievements.
2. **Measure the AI.** Every AI component ships with an evaluation dataset and reported metrics.
   "It seems to work" is not a result.
3. **Layered backend.** `api → services → repositories → models`. Routers never touch the ORM
   session directly; repositories never contain business rules.
4. **Providers behind abstractions.** LLM and embedding providers sit behind interfaces so they can
   be swapped without touching business logic.
5. **Every decision is documented.** If a choice had a real alternative, it belongs in
   `docs/architecture.md` with the reasoning.

---

## Licence

Personal portfolio project.
