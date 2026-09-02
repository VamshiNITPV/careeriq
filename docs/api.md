# CareerIQ — API Design

**Document status:** Phase 1 · Living document
**Last updated:** 2026-09-01
**Base URL:** `/api/v1`
**Format:** JSON. `Content-Type: application/json` except file upload (`multipart/form-data`).

The live, always-accurate contract is the OpenAPI schema FastAPI generates at `/docs` and
`/openapi.json`. This document exists to record the *design* — resource modelling, status code
conventions, pagination, and the reasoning behind them.

---

## 1. Conventions

### 1.1 Versioning
The version lives in the path (`/api/v1`). Header-based versioning is cleaner in theory but harder
to test with a browser or curl, and path versioning makes it obvious in every log line which
contract was used.

### 1.2 Authentication
`Authorization: Bearer <access_token>` on every endpoint except those marked 🔓.

Access tokens are short-lived (30 min). Refresh tokens are rotated on every use and returned in the
body — **not** set as a cookie, because the SPA and API are served from different origins in
production and a cross-site cookie adds CSRF surface we would then have to defend.

### 1.3 Status codes

| Code | Used for |
|---|---|
| `200` | Successful read or update |
| `201` | Resource created — includes a `Location` header |
| `202` | Accepted for asynchronous processing — returns a task id |
| `204` | Successful delete, no body |
| `400` | Malformed request |
| `401` | Missing or invalid credentials |
| `403` | Authenticated but not permitted — **role failures only** |
| `404` | Not found, **or found but not owned by the caller** (ADR-014) |
| `409` | Conflict — duplicate, or invalid state transition |
| `413` | Payload too large |
| `415` | Unsupported media type |
| `422` | Validation failed — FastAPI/Pydantic default |
| `429` | Rate limit exceeded — includes `Retry-After` |
| `500` | Unhandled server error — opaque body in production |

> **Why cross-user access is `404` and not `403`:** returning `403` confirms the resource exists.
> An attacker enumerating UUIDs learns which ids are real. `404` leaks nothing. `403` is reserved
> for role failures, where the caller already knows the endpoint exists.

### 1.4 Error envelope
Every non-2xx response uses one shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Resume file exceeds the maximum size of 5 MB",
    "details": { "field": "file", "max_bytes": 5242880 },
    "correlation_id": "01927b3e-..."
  }
}
```

`code` is a stable machine-readable constant the frontend switches on. `message` is for humans and
may change. `correlation_id` matches the structured log entry (architecture.md §4), so a user
reporting an error gives us the exact request.

### 1.5 Pagination
Cursor-based on list endpoints:

```
GET /api/v1/jobs?limit=20&cursor=eyJpZCI6...
```
```json
{
  "items": [...],
  "page": { "next_cursor": "eyJpZCI6...", "has_more": true, "limit": 20 }
}
```

> **Why cursor and not offset:** the job corpus and recommendation lists change while a user pages
> through them. `OFFSET 40` on a shifting set skips and repeats rows. Cursors are stable, and
> `OFFSET` degrades linearly on large tables. Cost: no random page access — acceptable, since
> nothing in the UI needs "jump to page 7".

`limit` defaults to 20, maximum 100.

### 1.6 Filtering & sorting
Explicit named query parameters only — `?work_mode=REMOTE&min_salary=1200000`. No generic
filter-expression language: it would be an injection surface and impossible to index for.

### 1.7 Rate limiting
Per NFR-8. Every response carries:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1756713600
```

| Scope | Limit |
|---|---|
| Default authenticated | 100 / min |
| Unauthenticated (auth endpoints) | 10 / min per IP |
| AI endpoints (`/optimize`, `/interviews/*/answer`) | 10 / min |
| File upload | 5 / hour |

### 1.8 Idempotency
`POST` endpoints that trigger expensive or non-repeatable work accept an `Idempotency-Key` header.
A repeat within 24 hours returns the original response instead of re-running the work.

---

## 2. Endpoints

### 2.1 Authentication — `/auth`

| Method | Path | Description |
|---|---|---|
| 🔓 `POST` | `/auth/register` | Create account. `201` |
| 🔓 `POST` | `/auth/login` | Exchange credentials for tokens. `200` |
| 🔓 `POST` | `/auth/refresh` | Rotate refresh token. `200` |
| `POST` | `/auth/logout` | Revoke the presented refresh token. `204` |
| 🔓 `GET` | `/auth/google/authorize` | Begin OAuth; returns provider URL + `state` |
| 🔓 `GET` | `/auth/google/callback` | Complete OAuth; validates `state` (US-1.2 AC2) |
| `GET` | `/auth/me` | Current user + role |
| `POST` | `/auth/change-password` | Requires current password; revokes all refresh families |
| 🔓 `POST` | `/auth/forgot-password` | Request a reset link. **Always 200**, identical response whether or not the account exists (US-1.6 AC1) |
| 🔓 `POST` | `/auth/reset-password` | Set a new password from a link. Single-use token; revokes all sessions |
| 🔓 `POST` | `/auth/verify-email` | Confirm an address. Unauthenticated — the link is often opened on another device |
| `POST` | `/auth/resend-verification` | Send the confirmation email again. Requires a session, so nothing is enumerable |

<details>
<summary><code>POST /auth/register</code></summary>

```json
// Request
{ "email": "priya@example.com", "password": "correct-horse-9", "full_name": "Priya S." }

// 201 Created
{
  "user": { "id": "0192...", "email": "priya@example.com", "role": "USER" },
  "tokens": {
    "access_token": "eyJ...", "refresh_token": "eyJ...",
    "token_type": "bearer", "expires_in": 1800
  }
}
```
Duplicate email returns `409` with code `REGISTRATION_FAILED` and a message that does **not**
confirm the address is registered (US-1.1 AC3).
</details>

---

### 2.2 Profile — `/profile`

| Method | Path | Description |
|---|---|---|
| `GET` | `/profile` | Full career profile — skills, education, experience, projects, certifications |
| `PATCH` | `/profile` | Update personal fields |
| `GET` | `/profile/preferences` | Career preferences |
| `PUT` | `/profile/preferences` | Replace preferences. **Invalidates recommendation cache** (US-1.4 AC2) |
| `GET` | `/profile/skills` | Candidate skills with proficiency and confidence |
| `POST` | `/profile/skills` | Add a skill manually → `is_user_verified = true` |
| `PATCH` | `/profile/skills/{id}` | Correct proficiency or years (US-2.4) |
| `DELETE` | `/profile/skills/{id}` | Remove |
| `GET/POST/PATCH/DELETE` | `/profile/education`, `/experience`, `/projects`, `/certifications` | Standard CRUD |
| `GET` | `/profile/completeness` | Score + specific missing items, for the dashboard tile |

> **`PUT` for preferences, `PATCH` for the profile:** preferences are a coherent settings object
> replaced wholesale by a settings form. Profile fields are edited individually.

---

### 2.3 Resumes — `/resumes`

| Method | Path | Description |
|---|---|---|
| `GET` | `/resumes` | List the caller's resumes |
| `POST` | `/resumes` | Upload. `multipart/form-data`. → **`202 Accepted`** |
| `GET` | `/resumes/{id}` | Detail with version list |
| `PATCH` | `/resumes/{id}` | Rename, set primary |
| `DELETE` | `/resumes/{id}` | Soft delete. `204` |
| `GET` | `/resumes/{id}/versions` | Version history |
| `GET` | `/resumes/{id}/versions/{vid}` | Parsed content of one version |
| `GET` | `/resumes/{id}/versions/{vid}/download` | Signed URL, expires in 5 min |
| `POST` | `/resumes/{id}/versions/{vid}/reparse` | Re-run the pipeline. → `202` |

<details>
<summary><code>POST /resumes</code> — asynchronous upload (ADR-009)</summary>

```
Content-Type: multipart/form-data
file: <binary>          # PDF or DOCX, ≤ 5 MB
title: "Backend resume" # optional
```
```json
// 202 Accepted
{
  "resume_id": "0192...",
  "version_id": "0192...",
  "task_id": "0192...",
  "status": "PENDING",
  "websocket_channel": "/ws/tasks/0192..."
}
```

Validation happens **before** `202`: magic-byte type check, size limit, and rate limit. A bad file
fails immediately with `415` or `413` rather than being accepted and failing silently in a worker.

Rejections: `415` non-PDF/DOCX · `413` over 5 MB · `422` password-protected or image-only PDF with
code `UNEXTRACTABLE_DOCUMENT` (requirements.md §6).
</details>

---

### 2.4 Jobs — `/jobs`

| Method | Path | Description |
|---|---|---|
| `GET` | `/jobs` | Browse/search. Filters: `q`, `work_mode`, `employment_type`, `experience_level`, `country_code`, `min_salary`, `posted_after`, `skill_ids` |
| `POST` | `/jobs` | Submit a job by pasting a description → `202` (parsing is async) |
| `GET` | `/jobs/{id}` | Detail with parsed structure and extracted skills |
| `GET` | `/jobs/{id}/match` | **This caller's** score breakdown for this job |
| `POST` | `/jobs/{id}/save` | Create an application in `SAVED` |
| `GET` | `/jobs/{id}/similar` | Nearest neighbours by embedding |
| `POST` | `/admin/jobs/import` | 🔒 `ADMIN` — bulk dataset import → `202` |

<details>
<summary><code>GET /jobs/{id}/match</code> — the explainable score (US-4.1, US-4.2)</summary>

```json
{
  "job_id": "0192...",
  "overall_score": 94.2,
  "ranking_version": "v1-hand-tuned",
  "computed_at": "2026-09-01T10:22:31Z",
  "breakdown": [
    { "dimension": "semantic",   "score": 0.93, "weight": 0.35, "contribution": 32.6,
      "reason": "Your API and distributed-systems experience closely matches the responsibilities." },
    { "dimension": "skill",      "score": 0.96, "weight": 0.25, "contribution": 24.0,
      "reason": "8 of 9 required skills matched." },
    { "dimension": "experience", "score": 0.90, "weight": 0.15, "contribution": 13.5,
      "reason": "You have 3.5 years; the role asks for 3–6." },
    { "dimension": "education",  "score": 1.00, "weight": 0.10, "contribution": 10.0,
      "reason": "Bachelor's meets the requirement." },
    { "dimension": "location",   "score": 1.00, "weight": 0.10, "contribution": 10.0,
      "reason": "Remote matches your preference." },
    { "dimension": "salary",     "score": 0.82, "weight": 0.05, "contribution": 4.1,
      "reason": "Range starts slightly below your stated minimum." }
  ],
  "skills": {
    "matched": [ { "id": "...", "name": "Python" }, { "id": "...", "name": "PostgreSQL" } ],
    "partial": [ { "id": "...", "name": "AWS", "reason": "Job asks for 3+ years; you have 1." } ],
    "missing": [ { "id": "...", "name": "Kubernetes", "requirement": "REQUIRED" } ]
  }
}
```

`contribution` values sum to `overall_score` (US-4.1 AC2). The score is reproducible by hand from
this payload — which is exactly what makes it debuggable and defensible.
</details>

---

### 2.5 Recommendations — `/recommendations`

| Method | Path | Description |
|---|---|---|
| `GET` | `/recommendations` | Ranked jobs for the caller. Cursor paginated |
| `POST` | `/recommendations/refresh` | Force recompute → `202` |
| `POST` | `/recommendations/{job_id}/feedback` | `RELEVANT` / `NOT_RELEVANT` / `NOT_INTERESTED` |

> The feedback endpoint exists from day one even though nothing consumes it yet. It is how we
> accumulate the labelled relevance data that a learned ranker will eventually need (ADR-005).
> Collecting it late means starting from zero later.

Query params: `limit`, `cursor`, `min_score`, `exclude_applied` (default `true`),
`resume_version_id` (default: primary resume's current version).

---

### 2.6 Skills & learning — `/skills`, `/learning`

| Method | Path | Description |
|---|---|---|
| `GET` | `/skills/search?q=` | Autocomplete over the taxonomy, alias-aware |
| `GET` | `/skills/gaps` | Aggregate gaps across target roles |
| `GET` | `/skills/gaps?job_id=` | Gaps against one specific job |
| `GET` | `/skills/demand` | Most in-demand skills for the caller's target roles |
| `GET` | `/learning/paths` | List |
| `POST` | `/learning/paths` | Generate for a role or job → `202` |
| `GET` | `/learning/paths/{id}` | Detail with ordered steps |
| `PATCH` | `/learning/paths/{id}/steps/{sid}` | Mark a step complete |
| `DELETE` | `/learning/paths/{id}` | `204` |

---

### 2.7 Resume optimization — `/optimize`

The most safety-critical surface in the API (ADR-012).

| Method | Path | Description |
|---|---|---|
| `POST` | `/optimize/analyze` | Analyze a resume version against a job → `202` |
| `GET` | `/optimize/{analysis_id}` | Suggestions, each individually actionable |
| `POST` | `/optimize/{analysis_id}/apply` | Apply accepted suggestions → **creates a new resume version** |

<details>
<summary><code>GET /optimize/{analysis_id}</code></summary>

```json
{
  "analysis_id": "0192...",
  "resume_version_id": "0192...",
  "job_id": "0192...",
  "status": "COMPLETE",
  "suggestions": [
    {
      "id": "0192...",
      "type": "REPHRASE",
      "section": "experience",
      "target_path": "experiences[0].highlights[2]",
      "original": "Worked on the payments backend.",
      "suggested": "Built and maintained payment processing services handling transaction workflows.",
      "rationale": "The job emphasises payment systems; your original phrasing understates existing work.",
      "grounded_in": ["experiences[0].description", "experiences[0].highlights[2]"],
      "validation": { "passed": true, "fabricated_entities": [] }
    }
  ],
  "rejected_by_validator": 2
}
```

Every suggestion carries `grounded_in` — the source spans it derives from — and a `validation`
result. **A suggestion failing validation is never returned to the user**; `rejected_by_validator`
reports the count so the behaviour is observable rather than invisible (ADR-012 step 4).

`POST /optimize/{id}/apply` takes `{ "accepted_suggestion_ids": [...] }` and returns `201` with the
new resume version. The source version is never mutated (US-6.1 AC3).
</details>

---

### 2.8 Applications — `/applications`

| Method | Path | Description |
|---|---|---|
| `GET` | `/applications` | List. Filter by `status`, `date_from`, `date_to` |
| `POST` | `/applications` | Create from a job |
| `GET` | `/applications/{id}` | Detail with full event timeline |
| `PATCH` | `/applications/{id}` | Update notes, `next_action_at` |
| `POST` | `/applications/{id}/status` | Transition status — **validated** |
| `DELETE` | `/applications/{id}` | Soft delete. `204` |
| `GET` | `/applications/{id}/events` | Immutable event history |

<details>
<summary><code>POST /applications/{id}/status</code> — transition validation</summary>

```json
{ "status": "INTERVIEW", "occurred_at": "2026-09-04T09:00:00Z", "note": "Round 1 scheduled" }
```

Legal transitions (US-7.1 AC1):
```
SAVED     → APPLIED, WITHDRAWN
APPLIED   → ASSESSMENT, INTERVIEW, REJECTED, WITHDRAWN
ASSESSMENT→ INTERVIEW, REJECTED, WITHDRAWN
INTERVIEW → OFFER, REJECTED, WITHDRAWN
OFFER     → REJECTED, WITHDRAWN
REJECTED  → (terminal)
WITHDRAWN → (terminal)
```
An illegal transition returns `409` with code `INVALID_STATUS_TRANSITION`. The transition table
lives in the service layer and is unit-tested exhaustively — every source status against every
target status.
</details>

---

### 2.9 Analytics — `/analytics`

| Method | Path | Description |
|---|---|---|
| `GET` | `/analytics/overview` | Dashboard tiles — counts and funnel rates |
| `GET` | `/analytics/funnel` | Conversion at each stage |
| `GET` | `/analytics/by-role` | Performance segmented by normalized title |
| `GET` | `/analytics/by-resume-version` | Which version converts better |
| `GET` | `/analytics/by-match-score` | Conversion by score band — **validates the ranking model** |
| `GET` | `/analytics/skill-correlation` | Skills correlated with reaching interview |

<details>
<summary><code>GET /analytics/funnel</code> — low-confidence labelling</summary>

```json
{
  "totals": { "applications": 42, "interviews": 11, "offers": 2 },
  "rates": {
    "interview_rate": { "value": 0.262, "sample_size": 42, "confidence": "MODERATE" },
    "offer_rate":     { "value": 0.047, "sample_size": 42, "confidence": "LOW" }
  },
  "segments": [
    { "key": "Backend Engineer", "applications": 18, "interviews": 7,
      "interview_rate": { "value": 0.389, "sample_size": 18, "confidence": "MODERATE" } },
    { "key": "ML Engineer", "applications": 3, "interviews": 0,
      "interview_rate": { "value": 0.0, "sample_size": 3, "confidence": "INSUFFICIENT" } }
  ]
}
```

Every rate ships with its `sample_size` and a `confidence` label (US-7.2 AC3). Reporting "0% success
rate for ML Engineer" from three applications would be actively misleading — the user might abandon
a viable target on noise. The API refuses to present a bare number without its sample size.
</details>

---

### 2.10 Interviews — `/interviews`

| Method | Path | Description |
|---|---|---|
| `GET` | `/interviews` | Session list |
| `POST` | `/interviews` | Start a session for a target role. `201` |
| `GET` | `/interviews/{id}` | State, questions, answers so far |
| `GET` | `/interviews/{id}/next-question` | Next question from the adaptive policy |
| `POST` | `/interviews/{id}/answer` | Submit an answer → scored → `200` |
| `POST` | `/interviews/{id}/complete` | End early and generate the report |
| `GET` | `/interviews/{id}/report` | Full report with per-dimension scores |
| `GET` | `/interviews/{id}/ticket` | Short-lived WebSocket ticket (ADR-010) |

<details>
<summary><code>POST /interviews/{id}/answer</code> — the adaptive turn (ADR-013)</summary>

```json
// Request
{ "question_id": "0192...", "answer_text": "I'd start by...", "duration_seconds": 145 }

// 200 OK
{
  "score": {
    "overall": 0.78,
    "technical": 0.86, "relevance": 0.91, "completeness": 0.74,
    "communication": 0.79, "structure": 0.72
  },
  "feedback": "Strong grasp of indexing trade-offs. You didn't address write amplification.",
  "strengths": ["Correctly identified the B-tree vs hash trade-off"],
  "improvements": ["Mention the write-path cost of additional indexes"],
  "cited_spans": [{ "start": 120, "end": 198, "note": "Clear explanation of the read path" }],
  "adaptation": {
    "previous_difficulty": "MEDIUM",
    "next_difficulty": "HARD",
    "reason": "Score ≥ 0.7 — increasing difficulty",
    "topics_covered": ["indexing", "query planning"]
  },
  "progress": { "questions_asked": 3, "question_budget": 10 }
}
```

`adaptation` is returned deliberately: exposing the policy's decision and its reason makes the
adaptive engine visible to the user instead of feeling arbitrary, and makes it inspectable in tests
and demos.
</details>

---

### 2.11 Tasks & notifications

| Method | Path | Description |
|---|---|---|
| `GET` | `/tasks/{id}` | Background task status — the polling fallback for WebSockets (ADR-010) |
| `GET` | `/notifications` | List, filter `unread_only` |
| `POST` | `/notifications/{id}/read` | Mark read |
| `POST` | `/notifications/read-all` | Mark all read |

### 2.12 System

| Method | Path | Description |
|---|---|---|
| 🔓 `GET` | `/health` | Liveness — no dependency checks, always fast |
| 🔓 `GET` | `/health/ready` | Readiness — verifies Postgres and Redis |
| 🔓 `GET` | `/version` | Build SHA and version |

> Liveness and readiness are separate on purpose. If `/health` checked the database, a brief
> database blip would make Cloud Run kill and restart healthy containers, turning a recoverable
> problem into an outage.

---

## 3. WebSocket channels

Two channels only (ADR-010). Both authenticate with a short-lived ticket from a REST endpoint —
the browser `WebSocket` API cannot send an `Authorization` header, and a token in the query string
would be written to access logs.

### `/ws/tasks/{task_id}`
```json
{ "type": "progress", "stage": "PARSING", "percent": 45, "message": "Extracting work experience" }
{ "type": "complete", "resource_type": "resume_version", "resource_id": "0192..." }
{ "type": "failed", "code": "UNEXTRACTABLE_DOCUMENT", "message": "This PDF contains no selectable text." }
```

### `/ws/interviews/{interview_id}`
```
client → { "type": "answer", "question_id": "...", "answer_text": "..." }
server → { "type": "scoring", "status": "in_progress" }
server → { "type": "score", "payload": { ... } }
server → { "type": "question", "payload": { "id": "...", "text": "...", "difficulty": "HARD" } }
server → { "type": "complete", "payload": { "report_url": "/api/v1/interviews/.../report" } }
```

---

## 4. Design decisions

**Async-first for expensive operations.** Resume upload, job submission, optimization analysis,
learning-path generation, and recommendation refresh all return `202` with a task id. This is
consistent enough to be a rule: *if it calls a model or parses a document, it is asynchronous.*

**Explanations are part of the payload, not a separate call.** `GET /jobs/{id}/match` returns the
breakdown inline. Splitting it into `/match` and `/match/explanation` would double the round trips
for a view that always shows both, and would let the two drift apart.

**No generic `/search`.** Each resource has its own filtered list endpoint. A universal search
endpoint returning heterogeneous types is convenient for one screen and awkward for every other,
and it cannot be typed cleanly on the frontend.

**Admin endpoints are namespaced under `/admin`.** Role enforcement is a router-level dependency,
so an admin endpoint cannot be added without it. Scattering admin actions among user endpoints
makes it easy to forget the role check on exactly one of them.

**Feedback endpoints exist before their consumers.** Relevance feedback (§2.5) and `human_score`
(database.md §3.8) collect training and evaluation data from day one, because the alternative is
having no data on the day the learned model is finally built.

---

## 5. Open questions

| # | Question | Resolve by |
|---|---|---|
| Q1 | Should `GET /recommendations` recompute synchronously on a cache miss, or return `202` and stream? Recompute is ~400 ms warm, but cold with no embeddings is much worse. | Phase 6 |
| Q2 | Bulk status updates for applications — worth the complexity, or is one-at-a-time fine at realistic volumes? | Phase 8 |
| Q3 | Does the interview need a resume-from-disconnect protocol beyond simple state reload? | Phase 9 |
| Q4 | Rate limit on `/optimize/analyze` may be too generous for the free-tier LLM quota. Needs a real measurement. | Phase 7 |
