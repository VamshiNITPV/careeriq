# CareerIQ — Requirements & User Stories

**Document status:** Phase 1 · Living document
**Last updated:** 2026-09-01

---

## 1. Problem statement

A job seeker today runs an ad-hoc, unmeasured process. They read job descriptions one at a time,
subjectively judge fit, manually diff their resume against requirements, guess which skills to
learn, rewrite their resume per application, and track everything in a spreadsheet — if at all.
Nothing in that loop produces feedback. After 40 applications they know their outcome count but
not *which decisions caused it*.

CareerIQ replaces that with a system that (a) represents the candidate as structured data,
(b) represents jobs as structured data, (c) scores fit with an explainable model, and
(d) closes the loop by correlating application outcomes back to profile and resume decisions.

---

## 2. Personas

### P1 — Priya, the early-career applicant *(primary)*
Final-year CS student / 0–2 years experience. Applying to 50+ roles. Cannot tell which
postings are realistic. Needs ranked shortlists, honest skill-gap feedback, and interview practice.
**Success:** spends time on the 15 jobs worth applying to instead of all 300.

### P2 — Rahul, the career switcher *(secondary)*
3–6 years in one domain, moving to another. His resume undersells transferable work. Keyword
matching fails him — "built REST APIs in Python" never matches "backend service development".
**Success:** semantic matching surfaces roles keyword search would have hidden.

### P3 — Admin / operator *(supporting)*
Maintains the job corpus, reviews the skill taxonomy, monitors pipeline health and AI failures.
**Success:** can find and fix a bad ingestion batch without database surgery.

---

## 3. Scope

### 3.1 In scope (v1)

| # | Capability |
|---|---|
| C1 | Email/password + Google OAuth authentication, JWT sessions, RBAC (`USER`, `ADMIN`) |
| C2 | Resume upload (PDF/DOCX), text extraction, section detection, entity extraction |
| C3 | Persistent structured career profile, user-editable |
| C4 | Job ingestion from user submissions, public datasets, and permitted APIs |
| C5 | JD parsing, normalization, skill/requirement extraction, duplicate detection |
| C6 | Embedding generation and `pgvector` similarity search for resumes and jobs |
| C7 | Hybrid, explainable job ranking with per-dimension score breakdown |
| C8 | Skill gap analysis with severity prioritization |
| C9 | Generated learning paths targeting missing skills |
| C10 | Grounded resume optimization suggestions requiring explicit user approval |
| C11 | Application tracker with a status lifecycle and event history |
| C12 | Career analytics — funnel rates, per-role and per-resume-version performance |
| C13 | Adaptive AI mock interview with multi-dimensional scoring and feedback |
| C14 | Real-time progress via WebSockets for resume processing and live interviews |
| C15 | Background processing for parsing, embedding, and analysis |

### 3.2 Explicitly out of scope (v1)

- Aggressive scraping of sites whose terms prohibit it. Ingestion is limited to user-submitted
  postings, public datasets, and APIs that permit programmatic access.
- Auto-submitting applications to employers on the user's behalf.
- Recruiter-side or employer-side features.
- Payments, subscriptions, or billing.
- Native mobile apps. The web UI is responsive; that is the extent of mobile support.
- Multi-language resumes. v1 is English-only.
- Video or audio interview capture. Mock interviews are text-based in v1.

### 3.3 Deferred (candidate for v2)

- Learned ranking model trained on real outcome data, replacing the hand-tuned weight formula.
- Dedicated vector database, if `pgvector` becomes a bottleneck.
- Browser extension for one-click job capture.
- Cover letter generation.

---

## 4. User stories

Format: `As a <persona>, I want <capability>, so that <outcome>.`
Each story carries acceptance criteria (AC) that become test cases.

### Epic 1 — Authentication & Profile

**US-1.1** As a visitor, I want to register with email and password, so that I have a persistent account.
- AC1: Password must be ≥10 chars with at least one letter and one digit; weaker passwords are rejected with a specific message.
- AC2: Passwords are stored as bcrypt hashes. The plaintext never appears in logs or responses.
- AC3: Registering with an already-used email returns a generic failure that does not confirm the email exists.
- AC4: Successful registration returns an access token and a refresh token.

**US-1.2** As a visitor, I want to sign in with Google, so that I don't manage another password.
- AC1: A Google sign-in whose email matches an existing local account links to that account rather than creating a duplicate.
- AC2: OAuth state is validated to prevent CSRF on the callback.

**US-1.3** As a user, I want my session to persist safely, so that I'm not logged out constantly but am not exposed if a token leaks.
- AC1: Access tokens expire in 30 minutes; refresh tokens in 14 days.
- AC2: Refresh tokens rotate on use, and reuse of a consumed refresh token revokes the whole family.
- AC3: Logout invalidates the refresh token server-side.

**US-1.4** As a user, I want to set career preferences, so that ranking reflects what I actually want.
- AC1: I can set target roles, preferred locations, remote preference, experience level, minimum salary, and currency.
- AC2: Changing preferences invalidates cached recommendations and triggers a re-rank.

**US-1.6** As a user who forgot my password, I want to reset it by email, so that I am not permanently locked out.
- AC1: `forgot-password` returns an identical response for a registered and an unregistered address — it must not be an account-existence oracle.
- AC2: The reset link is single-use and expires in 30 minutes.
- AC3: Requesting a new link invalidates any outstanding one.
- AC4: Completing a reset revokes every existing session.
- AC5: The token is stored only as a hash; a database leak yields no usable links.
- AC6: A verification token cannot be used to reset a password, or vice versa.

**US-1.7** As a user, I want to confirm my email address, so that account notices reach me.
- AC1: A confirmation email is sent on registration.
- AC2: The account is fully usable before confirming — verification proves the address, it does not gate access.
- AC3: The link is single-use and expires in 24 hours; confirming twice is not an error.
- AC4: An authenticated user can request a new confirmation email, which invalidates the previous link.
- AC5: Completing a password reset also marks the address confirmed, since receiving the link proves control of the mailbox.

**US-1.8** As a user, I want to be told when my account's security changes, so that I can react if it was not me.
- AC1: A notification is sent when the password is changed or reset.
- AC2: A notification is sent when sessions are revoked by reuse detection, explaining why the user was signed out.

**US-1.5** As a user, I want to access only my own data, so that my resume and applications stay private.
- AC1: Requesting another user's resume, application, or interview returns `404`, not `403` — we do not leak existence.
- AC2: Every owned-resource endpoint has an authorization test covering the cross-user case.

### Epic 2 — Resume Intelligence

**US-2.1** As a user, I want to upload a PDF or DOCX resume, so that the system can analyze it.
- AC1: Only `application/pdf` and DOCX are accepted, validated by magic bytes and not by extension or client-supplied MIME type.
- AC2: Files over 5 MB are rejected before being read into memory.
- AC3: The uploaded filename is never used as a storage path; a generated UUID key is used.
- AC4: Upload returns `202 Accepted` immediately with a job id; parsing happens in the background.

**US-2.2** As a user, I want to watch processing progress, so that I know the system is working.
- AC1: A WebSocket channel emits stage updates: `uploaded → extracting → parsing → embedding → complete`.
- AC2: A failure emits a terminal `failed` event with a user-readable reason.

**US-2.3** As a user, I want my resume converted into a structured profile, so that I don't re-enter everything.
- AC1: The parser extracts contact info, education, skills, experience, projects, and certifications.
- AC2: Each extracted entity records a confidence score and the source text span it came from.
- AC3: Extraction below a confidence threshold is flagged for user review rather than silently accepted.

**US-2.4** As a user, I want to correct extracted data, so that errors don't poison my matches.
- AC1: Every extracted field is editable.
- AC2: A user edit is marked `user_verified` and is never overwritten by a later re-parse.

**US-2.5** As a user, I want multiple resume versions, so that I can compare which performs better.
- AC1: Uploading a new file creates a new `resume_version`, preserving prior versions.
- AC2: An application records which resume version was submitted.

### Epic 3 — Job Intelligence

**US-3.1** As a user, I want to add a job by pasting its description, so that I can analyze any posting I find.
- AC1: Paste raw text or provide a URL plus text; the system parses it into structured fields.
- AC2: Parsing extracts title, company, location, employment type, experience range, salary range, required skills, preferred skills, and education requirements.

**US-3.2** As the system, I want to detect duplicate jobs, so that the same posting doesn't flood rankings.
- AC1: Near-duplicates are detected via a content hash plus embedding cosine similarity above a threshold.
- AC2: A duplicate links to the canonical job rather than creating a new row.

**US-3.3** As an admin, I want to bulk-import a job dataset, so that the corpus is large enough for meaningful ranking.
- AC1: Import is idempotent — re-running the same batch creates no duplicates.
- AC2: A failed record does not abort the batch; failures are collected and reported.

### Epic 4 — Matching & Ranking

**US-4.1** As a user, I want jobs ranked by fit, so that I apply where I have a real chance.
- AC1: Ranking returns a 0–100 score with a per-dimension breakdown (semantic, skill, experience, education, location, salary).
- AC2: The breakdown sums to the total under the documented weights — the score is reproducible by hand.
- AC3: Ranking a corpus of 10,000 jobs returns in under 500 ms p95.

**US-4.2** As a user, I want to know *why* a job scored as it did, so that I trust the number.
- AC1: Each result lists matched skills, missing skills, and the reason for any low dimension.

**US-4.3** As a career switcher, I want semantically related experience to count, so that wording doesn't disqualify me.
- AC1: "Built REST APIs using Python" matches a job asking for "backend service development" with a semantic score materially above lexical overlap.
- AC2: This case is covered by a labelled example in the evaluation dataset.

### Epic 5 — Skill Gaps & Learning

**US-5.1** As a user, I want my skills classified against a target job, so that I know exactly what's missing.
- AC1: Each skill is classified `strong`, `partial`, or `missing`.
- AC2: Missing skills are prioritized `critical | high | medium | low` based on how often they appear as *required* across my target roles.

**US-5.2** As a user, I want a learning path for my gaps, so that I know what to study first.
- AC1: The path is ordered by dependency (Docker before Kubernetes) and severity.
- AC2: Each step has an estimated duration and a concrete outcome.

### Epic 6 — Resume Optimization

**US-6.1** As a user, I want suggestions to tailor my resume to a job, so that I present my real experience better.
- AC1: Every suggestion is a discrete, individually acceptable or rejectable diff.
- AC2: **No suggestion may introduce a skill, employer, metric, date, or achievement absent from the source resume.** A validation pass rejects any generation that does.
- AC3: Accepting suggestions produces a new resume version; the original is never mutated.

### Epic 7 — Applications & Analytics

**US-7.1** As a user, I want to track applications through a lifecycle, so that nothing falls through.
- AC1: Statuses: `saved → applied → assessment → interview → offer`, with `rejected` and `withdrawn` reachable from any active state.
- AC2: Every transition writes an immutable `application_event` with a timestamp.

**US-7.2** As a user, I want funnel analytics, so that I can see what's working.
- AC1: Reports application count, interview rate, and offer rate.
- AC2: Segments by role, location, resume version, and match-score band.
- AC3: Any segment with fewer than 5 applications is labelled low-confidence rather than shown as a hard rate.

### Epic 8 — AI Interview

**US-8.1** As a user, I want a mock interview for a target role, so that I can practise.
- AC1: Questions are generated from the target role and my actual profile, not from a fixed bank.
- AC2: The session persists and can be resumed.

**US-8.2** As a user, I want the interview to adapt, so that it probes my real level.
- AC1: A weak answer produces an easier clarifying follow-up; a strong answer escalates difficulty.
- AC2: The difficulty trajectory is recorded per question and visible in the report.

**US-8.3** As a user, I want scored feedback, so that I know how to improve.
- AC1: Each answer is scored on technical correctness, relevance, completeness, communication, and structure.
- AC2: Feedback cites the specific part of my answer it refers to.
- AC3: Scoring is validated against a human-labelled test set with reported agreement.

---

## 5. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | API latency, non-AI endpoints | p95 < 200 ms |
| NFR-2 | Ranked recommendations over 10k jobs | p95 < 500 ms |
| NFR-3 | Resume upload acknowledgement | < 1 s (processing is async) |
| NFR-4 | Full resume processing pipeline | < 30 s p95 |
| NFR-5 | Availability target | 99% (portfolio-grade, single region) |
| NFR-6 | Passwords | bcrypt, cost factor ≥ 12 |
| NFR-7 | Transport | HTTPS only in deployed environments; HSTS enabled |
| NFR-8 | Rate limiting | 100 req/min per user; 10 req/min on AI endpoints |
| NFR-9 | Backend test coverage | ≥ 80% on `services/` and `repositories/` |
| NFR-10 | Every AI component | ships with an evaluation dataset and reported metrics |
| NFR-11 | Cost ceiling during development | $0 — free tiers only |
| NFR-12 | Accessibility | WCAG 2.1 AA on primary flows |
| NFR-13 | Observability | `/health` + structured JSON logs with correlation ids |

---

## 6. Constraints & assumptions

**Constraints**
- Zero infrastructure spend during development. Every service must have a usable free tier.
- Single developer. Scope must stay achievable in phases, each independently demonstrable.
- Windows 11 development host; Docker Desktop with WSL2 provides the Linux runtime.
- Python 3.13 — verified against spaCy 3.8+, PyTorch 2.6+, and sentence-transformers.

**Assumptions**
- Resumes are English and text-extractable. Scanned image PDFs are out of scope for v1 (detected and rejected with a clear message rather than silently producing garbage).
- The job corpus during development comes from public datasets and manual entry, not live scraping.
- LLM calls are non-deterministic; anything user-visible from an LLM is validated before display.

---

## 7. Success criteria

The project is complete when:

1. All 12 phases are implemented, tested, and documented.
2. A cold-start user can register, upload a resume, receive ranked job recommendations with
   explanations, see skill gaps, complete a mock interview, and view analytics — end to end,
   in a deployed environment.
3. The matching system reports Precision@10 and NDCG@10 against a labelled dataset of ≥100
   resume/JD pairs.
4. Interview scoring reports agreement against a human-labelled test set.
5. CI runs lint, type-check, and the full test suite on every push, and deploys on merge to `main`.
6. `docs/architecture.md` explains every significant decision and the alternatives rejected.
