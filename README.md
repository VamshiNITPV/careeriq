# CareerIQ — AI Career Intelligence & Job Optimization Platform

A full-stack AI/ML platform that builds a structured career profile from a resume, ingests and
parses job descriptions, ranks jobs by personalized fit using hybrid semantic + rule-based scoring,
identifies skill gaps, suggests grounded resume improvements, tracks application outcomes, and
conducts adaptive AI mock interviews.

> **Status:** Phases 1–5.8 complete, and Phase 6 is under way — 6.1 (embeddings) and 6.2
> (the explainable match score) are done.

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
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, React Query, React Router, Recharts |
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
| 5 | Job intelligence — ingestion, JD parsing, skill extraction, dedup | ✅ Done¹ |
| 5.5 | Resume entity extraction — work history, education, projects, certifications | ✅ Done |
| 5.6 | Live job ingestion — jobs API provider, admin fetch, `PARTNER_API` source | ✅ Done² |
| 5.7 | Saved jobs and applied tracking — bookmark, applied flag, profile lists | ✅ Done³ |
| 5.8 | Automatic job fetching — query rotation, request budget, scheduler | ✅ Done⁴ |
| 6.1 | Embeddings — `pgvector`, local model, "Similar jobs" | ✅ Done⁵ |
| 6.2 | Hybrid explainable score — six dimensions, `/jobs/{id}/match` | ✅ Done⁶ |
| 6.3 | Recommendations — two-stage retrieval, ranked list, dashboard tile | ⬜ |
| 6.4 | Evaluation — labelled dataset, metrics, weight tuning, near-duplicates | ⬜ |
| 7 | Career intelligence — skill gaps, learning paths, resume optimization | ⬜ |
| 8 | Application system — tracking, analytics, outcome analysis | ⬜ |
| 9 | AI interview — question generation, adaptive engine, evaluation | ⬜ |
| 10 | Production engineering — Redis, background jobs, WebSockets, security | ⬜ |
| 11 | Cloud — Docker, GCP, CI/CD, monitoring | ⬜ |
| 12 | Final polish — testing, documentation, diagrams, demo | ⬜ |

¹ **Duplicate detection is stage one of two.** A content hash catches exact and
reformatted re-posts (US-3.2 AC1, first half). The near-duplicate pass — the same
role reworded, or posted by both an agency and the employer — compares embedding
cosine similarity and cannot exist before Phase 6 builds the embeddings.
`jobs.status = 'DUPLICATE'` and `canonical_job_id` are in place for it.

² **A jobs API, not a job board.** The corpus grows by fetching from a permitted API
(ADR-019), so it is bounded by that provider's free tier — on the order of a couple of thousand
postings a month before duplicates, against NFR-2's 10k target. It is deliberately *not* "every
posting worldwide": nobody has that, scraping is out of scope, and there is no scheduled refresh
until Phase 10 brings a queue. Live ingestion is off unless `JOBS_PROVIDER` and `JOBS_API_KEY` are
set; without them the app runs exactly as before and `POST /admin/jobs/fetch` answers 503.
*(Superseded in part by 5.8: there is now a scheduled refresh, though not on a queue.)*

One thing to expect the first time you fetch: the list is ordered by `posted_at DESC NULLS LAST`,
and fetched postings carry a real date while hand-entered ones mostly do not — so every existing job
drops below the fetched ones. That is correct, not data loss.

³ **The first slice of Phase 8, not Phase 8.** Two statuses — saved and applied — with no event
log, no lifecycle beyond those two, and no funnel analytics. Applied is always the user's own
assertion: nothing infers it, and auto-submitting applications is explicitly out of scope. The
tracker and its analytics remain Phase 8.

⁵ **Meaning, not keywords — and it is measurable.** Every job and resume is turned into 768 numbers
that capture what it is *about*, by a model that runs locally on CPU: free, no API quota, no network.
So "Built REST APIs using Python" can match "backend service development" despite sharing no words.
`pgvector` stores the vectors and finds the closest ones in one SQL statement.

Measured on the real corpus rather than asserted: 255 jobs indexed in under four minutes; two Python
backend postings score 0.82–0.92 against each other, a Python backend posting against a DevOps one
scores ~0.60, and across 3,586 random pairs the median is 0.602. That last number is the reason raw
cosine is never shown to a user — unrescaled, an unrelated pair already looks like 60%. It also
confirmed `ml.md`'s assumed rescaling range was about right, which had never been checked against data.

**The model runs in its own container.** `sentence-transformers` brings torch, and the API must not
carry it: the embedder image is ~3.0 GB while the API's stays ~630 MB, and a test fails the build if
anything in the API's import path so much as imports torch. Off by default —
`EMBEDDING_PROVIDER=sentence_transformers` plus `docker compose up embedder` turns it on.

⁶ **A score out of 100 you can check by hand — and it says what it does not know.** Every job page
now carries a breakdown: six weighted dimensions (semantic 35%, skills 25%, experience 15%,
education 10%, location 10%, salary 5%), each with its own number and a plain-English reason. The
six contributions add up to the total exactly, so anyone can reproduce the score from what is on
screen. That is the whole point — a number with no derivation is something you either trust or
don't, and neither is useful.

**The honest part is the interesting part.** A live audit found most of the formula's inputs simply
absent: `Profile.years_of_experience` set on 0 of 43 profiles, `highest_education` on 0 of 43, every
job with a country code naming the same country, and 245 of 256 postings listing no salary. Rather
than quietly renormalise — which would let a job rank higher because its employer left a field blank
— a dimension that cannot be computed scores a neutral 0.5, keeps its documented weight, and the
page says out loud *"based on 60% of what we compare"*. Rows that measured nothing get no progress
bar, because a half-filled bar is a picture of a mediocre result and we did not measure mediocre, we
measured nothing.

Measured across 420 real candidate-job pairs: the informed share runs 0.35 to 1.00 with a median of
0.60, and scores run 21.8 to 91.0. The contributions summed to the total on all 420.

Two rules the reasons follow. A dimension we could not compute never states a figure about you — a
test asserts that no such reason contains a digit at all. And a row is only allowed to suggest a fix
when there is one: "this posting doesn't say where it is" must never render a button telling you to
complete your profile.

Measurement also corrected a constant carried over from 6.1. That phase measured cosine between two
*jobs*; this formula compares a *resume* to a job, which turned out to be a different distribution
entirely — it tops out at 0.751 where job-to-job reaches 0.993. Reusing the old range would have
capped the best pair in the whole corpus at 0.69.

⁴ **Variety, not recency.** Measurement settled this: filtering the provider to the last three days
returned nothing, the last week returned nothing, and an unasked role-and-city combination returned
ten postings of which all ten were new. It is a large, slowly-changing index rather than a live
feed, so the corpus grows by working through a matrix of roles × cities and never repeating one
until the rest have been tried (ADR-019 amendment).

Set `JOBS_AUTO_FETCH_ENABLED=true` and the backend does this by itself — a few requests a day,
spread across the market, with the day's spending recorded in `job_fetch_runs` so a restart cannot
double-spend. It is off by default and needs a working `JOBS_PROVIDER`.

**The honest limit:** a 200-request month buys about six fetches a day, and the matrix takes about
a month to work through. After that, new arrivals slow to a trickle — a property of the free tier,
not something the design can engineer away.

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

**6. Optional — make yourself an admin.** Required for `/admin/jobs/*` (bulk
import and live fetch). Register in the web app first, then:

```bash
docker compose exec postgres psql -U careeriq -d careeriq \
  -c "UPDATE users SET role = 'ADMIN' WHERE email = 'you@example.com';"
```

There is deliberately no in-app way to do this. The role is changed by whoever
already owns the database, which is the honest description of what is happening —
an endpoint or a first-user-is-admin rule would be a privilege-escalation path
inside an application whose registration is open. No re-login is needed:
`get_current_user` loads the row on every request precisely so a role change
takes effect immediately.

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
