# CareerIQ — AI Career Intelligence & Job Optimization Platform

[![CI](https://github.com/VamshiNITPV/careeriq/actions/workflows/ci.yml/badge.svg)](https://github.com/VamshiNITPV/careeriq/actions/workflows/ci.yml)

**Licence:** [AGPL-3.0](LICENSE). The resume tailoring feature edits PDFs in
place with [PyMuPDF](https://pymupdf.readthedocs.io/), which is AGPL-or-commercial
and has no permissive equivalent, so the project takes the same licence.

A full-stack AI/ML platform that builds a structured career profile from a resume, ingests and
parses job descriptions, ranks jobs by personalized fit using hybrid semantic + rule-based scoring,
identifies skill gaps, suggests grounded resume improvements, tracks application outcomes, and
conducts adaptive AI mock interviews.

> **Status:** Phases 1–8 complete. Matching is measured rather than asserted (6.4).
> Career intelligence — skill gaps, learning paths and grounded resume optimization —
> ships with the fabrication validator that makes the last of those safe to offer at all.
> The application funnel keeps an immutable event log, and its outcome rates are read from
> that history, so a rejection after two interviews still counts as an interview. The
> deployment is built and proven locally, waiting on a VM rather than on code. Phase 9,
> the AI mock interview, is next.

---

## Live demo

> **Not yet deployed.** The stack below is built and verified end to end on a local
> production stack, but no VM exists yet, so there is no URL to publish. This section
> is written ahead of it deliberately — when the link goes in, nothing else here changes.

| | |
|---|---|
| URL | *(pending — see [Deployment](#deployment))* |
| Email | `demo@careeriq.app` |
| Password | `CareerIQDemo2026!` |

**The password is meant to be public.** It opens a shared account holding invented data
and nothing else, so hiding it would make the demo harder to open without making anything
safer.

**The person is invented; the model output is not.** "Asha Mehra" is not anybody and her
resume was written for `backend/app/data/demo.py` — publishing a real person's resume to
be browsed by strangers is a different thing entirely. The 40 postings and every vector in
the fixture are **real model output** exported from a working database, so the match scores
are genuinely computed rather than written down. A fabricated vector would produce a
similarity score that looks meaningful and means nothing, which is the failure mode
[ADR-012](docs/architecture.md) exists to refuse.

She is a payments backend engineer targeting AI roles. That is not decoration: it is what
makes the skill-gap screen show real gaps (Machine Learning `CRITICAL`, LLMs and AWS `HIGH`)
instead of congratulating her on a completeness nobody measured.

The account is shared, so anything a visitor changes is reset nightly.

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
| Infrastructure | Docker Compose (local and deployed), one GCP `e2-micro` VM + Cloud Storage, Caddy for TLS |
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
| 6.3 | Recommendations — two-stage retrieval, ranked list, dashboard tile | ✅ Done⁷ |
| 6.4 | Evaluation — labelled dataset, metrics, weight tuning, near-duplicates | ✅ Done⁸ ⁹ |
| 7 | Career intelligence — skill gaps, learning paths, resume optimization | ✅ Done¹⁰ |
| 8 | Application system — tracking, analytics, outcome analysis | ✅ Done¹¹ |
| 9 | AI interview — question generation, adaptive engine, evaluation | ⬜ |
| 10 | Production engineering — Redis, background jobs, WebSockets, security | ⬜ |
| 11 | Cloud — Docker, GCP, CI/CD, monitoring | 🟡 Part¹² |
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

⁷ **The system brings you jobs, instead of waiting to be asked.** Until now a match score only
appeared once you had already found a posting yourself, which is backwards. The dashboard now shows
jobs ranked against your resume, highest fit first, with a link to the full breakdown on each.

Two stages, because scoring the whole corpus on every page load cannot be fast: one SQL query pulls
the 200 postings nearest your resume by meaning — applying every filter in the same statement, so
expired postings and jobs you have already applied to never reach the scorer — and then the same
six-dimension formula from 6.2 ranks those 200. The list score and the job page score come from one
code path, so they cannot disagree; a test checks every row.

**Measuring it changed the design.** The first version took 535 ms at p95, over the 500 ms budget,
which looked like a case for adding a cache. It was not: the cost was 400 database round trips —
one per job, twice — not the arithmetic. Caching would have hidden that instead of fixing it, and
left the first request slow anyway. Batching the two lookups brought it to **47.8 ms p95**, so no
cache was built and the docs that had promised one were corrected.

A feedback endpoint ships alongside it, and nothing reads it yet. That is the point: a learned
ranker needs labelled examples, and those can only be collected going forward — adding the endpoint
later would mean starting from an empty table.

⁸ **The step that checks whether any of the ranking actually works — and the honest answer is
"mostly, with one clear miss and one clear warning".**

There is now a labelled dataset (122 resume/job pairs), four baselines to beat, and a committed
results file under `ml/evaluation/results/`. The headline number is the one the whole design was
staked on: **the six-dimension hybrid scores NDCG@10 of 0.611 against 0.400 for raw embedding
similarity alone.** ADR-005 said that if the hybrid could not beat plain cosine, the complexity
should be removed. It beats it comfortably, and it also beats keyword matching (0.408) and
skill-rules-only (0.513).

**It misses one target.** NDCG@10 should be 0.75 and is 0.611 — the ranking puts relevant jobs in
the top five reliably (precision@5 of 0.800, against a 0.70 target) but does not sort the very best
above the merely good well enough.

**And the sample size is the real finding.** The dataset requirement was "at least 100 pairs", which
is met — but those pairs cover only **two distinct people**, because the corpus holds one real
resume and one test fixture that several test accounts uploaded. Averaging a per-query metric over
two queries is an anecdote however carefully it is computed, so a pair-level correlation is reported
alongside (0.392 over 122 pairs) and **weight tuning was refused**: six numbers cannot be fitted to
two people without simply memorising them.

An ablation stands in for tuning, and it threw up something worth chasing: removing the *skill*
dimension entirely would **raise** NDCG@10 to 0.739 and all but meet the target. That is a lead, not a
licence — the labels were proposed by me and my rubric leaned on seniority, so the result is partly
circular until a human corrects them. `ml/datasets/matching/REVIEW.md` exists to make that
correction take half an hour.

Two smaller things the run caught. **Random scores a perfect 1.000 on MRR**, because half the pool
is relevant and landing one first is near a coin toss — that metric discriminates nothing here and
should not be read as a pass. And **Recall@200 (0.954) only means anything because the dataset
deliberately includes jobs the retrieval stage never returned**; without them it would have reported
1.0 by construction. Three of those sampled jobs turned out to be relevant, including a
`Python- React, Next JS Fullstack Engineer` posting that matches the real resume closely and which
stage one simply lost.

Near-duplicate detection, the other half of this step, is covered in the next note.

⁹ **Catching the same job posted twice — and finding out the harder problem is boilerplate.**

The first stage of duplicate detection has existed since Phase 5: a hash of the cleaned description,
which catches a posting pasted twice verbatim. This is the second stage, for the same role *reworded*
— or listed by both an agency and the employer — where no hash can match. It compares embeddings,
but only against postings from the same company or with a similar title, so it stays cheap per
posting instead of scanning the corpus.

**Measured on 72 labelled pairs, of which three are genuinely duplicates.** The threshold `ml.md`
specified (0.95) catches all three but also flags one real job as a copy: precision 0.750, recall
1.000. Raising it to 0.97 gives perfect precision and misses one duplicate: 1.000 and 0.667. Neither
hits both targets, and with three positives neither could — reclassifying one pair swings recall by a
third.

It ships at 0.97 because **the two mistakes cost differently**. Flagging a real posting as a
duplicate hides it from everyone; missing one leaves a duplicate in a list that already has it. And
**nothing is marked automatically** — the detector reports candidates and a person decides, because
at 0.750 precision an automatic rule would quietly hide real jobs.

Two things worth more than the threshold. Stage one catches **none** of these 72 pairs, which
confirms stage two is doing work the hash cannot — that was the assumption and had never been
checked. And the one false positive is revealing: a 15-year engineering *manager* role scored 0.960
against a 5-year *engineer* role at the same company, almost entirely on several identical paragraphs
of company marketing copy opening both adverts. `description_clean` is supposed to strip boilerplate
and does not strip that. Fixing it would sharpen duplicate detection *and* the semantic match score,
and needs no extra labelling to justify — which makes it the better thing to do next.

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

¹⁰ **Three features, and the dangerous one is deliberately the most constrained.**
Skill gaps (`/skills/gaps`) compare what the target roles ask for against what the
candidate holds, weighted by how firmly each posting asks. Learning paths order
what to study so a prerequisite never follows the thing that needs it. Both are
computed per request and never stored, for the reason ADR-006 gives for not
caching match scores: a gap depends on a corpus that changes daily, so a stored
row would be wrong more often than right.

**Resume optimization is the one that could do real harm**, and it is built to
refuse rather than to impress. An LLM asked to improve a resume will invent an
AWS certification the candidate does not hold — that is career damage, not a bug.
So every suggestion is checked programmatically against the source resume, and
any entity that is not already there is rejected before a human ever sees it
(ADR-012). Suggestions that survive are shown as individual diffs to accept or
reject one at a time, and accepted edits are written into a **new version** —
the uploaded file is never modified. Some genuinely good suggestions get thrown
out by the validator. That is the correct trade: a false negative costs a
suggestion, a false positive costs the user their credibility in an interview.

¹¹ **The funnel, its log, and the numbers read off it — minus two slices.**
`ApplicationStatus` carries all seven stages, transitions are validated against
explicit rules rather than trusted from the client, and every change writes an
immutable `application_event`.

That log is the whole point, and US-7.2's rates are why. **Outcome rates are
computed from history, not from current status.** An application sitting at
REJECTED may have been rejected *after* two interviews, and scoring it by where
it is now would count it as never having reached one — every rate quietly too
low, with nothing failing. `/applications` shows application count, interview
rate and offer rate, sliced by role and by location.

**Below five applications a segment reports counts and no rate** (AC3). One
interview in two applications is not a 50% success rate, and a null rate is
rendered as an em-dash rather than as 0% — "not enough happened to say" and
"enough happened, and none of it was this" are different answers.

**All four of AC2's slices work**, and the last two are why the phase took a
migration. By resume version and by match-score band cannot be computed after
the fact — an application carried no `resume_version_id`, match scores are never
stored (ADR-006), and by next month both the resume and the corpus have moved.
So both are captured at the moment of applying, and applications filed before
that group under "Not recorded" rather than being dropped from a total they are
part of.

Recording it is not allowed to cost anything else: a bookmark records neither,
and a failure to score still saves the application. Recording *that* you applied
must not depend on computing *how well*.

¹² **Built and verified, not yet running anywhere.** The production stack, the
Cloud Storage adapter, the deploy script, CI, and a seeded demo account are all
done and were proven end to end on a local production stack — real migrations,
real Caddy, real match scores. What has not happened is the deploy itself, which
needs GCP credentials rather than code.

ADR-011 was amended rather than quietly contradicted: the free tier ruled out
Cloud SQL, so this runs on one Always Free `e2-micro` instead of Cloud Run.
[infrastructure/gcp/SETUP.md](infrastructure/gcp/SETUP.md) has the commands.
Monitoring is still outstanding.

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

## Deployment

One Always Free GCP `e2-micro`. Three containers stay up — Postgres, the backend, and
Caddy — plus a one-shot container that builds the frontend bundle and exits. That is **not** what
[ADR-011](docs/architecture.md) decided — it specified Cloud Run, Cloud SQL, Pub/Sub,
Secret Manager and a CDN — and the ADR carries an amendment saying so rather than
quietly contradicting itself.

The reason is a single line item: **Cloud SQL has no free tier**, and Cloud Run reaching
a Postgres anywhere else needs VPC egress. A stateless container with nowhere free to
keep state is not a system, and NFR-11 caps spend at zero.

```
  Internet ──▶ Caddy :443  (obtains and renews its own certificate)
                 ├── /        → the built frontend, from a volume
                 └── /api/*   → backend :8000
                                  │
               Postgres 16 + pgvector, same host, not exposed
```

Same-origin is not a preference here. `apiClient.ts` calls `/api/v1` on its own origin
with no build-time override, so one hostname *has* to serve both — which is also why the
repo's `frontend/nginx.conf` is not used in production: it has no `/api` proxy and would
answer every API call with `index.html` and a 200.

Creating the server is a one-off, and the commands are written out in
**[infrastructure/gcp/SETUP.md](infrastructure/gcp/SETUP.md)** — including the two
defaults that quietly cost money (`pd-balanced` boot disks and multi-region buckets are
not in the free tier) and the one item that may not be free at all: the external IPv4
address. After that:

```bash
cp .env.production.example .env.production   # fill in; chmod 600; never committed
./infrastructure/gcp/deploy.sh               # idempotent, same script every time

# Seed the demo account (nightly, via cron)
docker compose -f docker-compose.prod.yml run --rm backend python -m app.data.demo
```

`deploy.sh` runs `alembic upgrade head` as an explicit step before anything serves
traffic. Nothing migrates automatically: the app's lifespan seeds the skill taxonomy but
never migrates, and against a schema-less database that seeding logs an error and carries
on — so the API would come up looking healthy and be unusable.

**What is deliberately not deployed.** The embedder (the model wants ~2GB; the VM has 1GB),
Redis (nothing depends on it), and Mailpit. So `EMBEDDING_PROVIDER=none` — and note that
*no provider* does not mean *no vectors*: the demo's vectors are seeded, and comparing them
is SQL. The consequence that is real: a résumé uploaded to the deployed instance gets no
embedding until something else embeds it.

**Production refuses to boot misconfigured.** `config.py` checks the whole set at startup
and reports every problem together — `DEBUG=true`, a short or placeholder `JWT_SECRET_KEY`,
`*` in `CORS_ORIGINS`, a non-https `FRONTEND_BASE_URL`, `STORAGE_PROVIDER=local` (a
container's disk is the wrong place for somebody's résumé), `EMAIL_PROVIDER=console`
(password reset would silently never arrive), and `fake` providers. `none` is allowed and
degrades a feature to a 503 rather than inventing anything.

**On cost.** The instance-hours are free and so is 5GB of Cloud Storage, but **free quotas
do not stop when exhausted — they stop being free.** Egress is the line item that scales
with visitors rather than time (1GB/month from North America at the time of writing), and
serving the frontend from the same VM puts every asset byte through it. A **$1 budget alert
is part of the setup, not an optional extra.** Free-tier terms change; verify current
eligibility at `cloud.google.com/free` before deploying.

**On latency.** The free tier is US-region only, so expect ~250ms from India. Accepted
deliberately.

**No redundancy.** One VM. If it dies the demo is down until it is rebuilt — fine for a
portfolio demo and for nothing else.

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
