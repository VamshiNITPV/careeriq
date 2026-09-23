# Offline ML tooling

Evaluation harnesses and labelled datasets. **Nothing here is imported by the
application** — `ml/` is not on the backend's import path, and the API image does
not contain it. The *scorers* live under `backend/app/services/matching/` because
they run in the request path; see architecture.md's Phase 6.2 amendment for that
split.

## Running it

`ml/` is mounted rather than copied, because the backend image deliberately does
not ship it:

```bash
# Metrics and baseline unit tests (no database needed)
docker compose run --rm --no-deps -v "$(pwd)/ml:/ml" backend \
    sh -c 'cd /ml && ruff check . && python -m pytest evaluation/tests -q'

# The evaluation itself (needs the database and an embedding provider)
docker compose run --rm -v "$(pwd)/ml:/ml" backend \
    sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.run_matching_eval'
```

On Git Bash under Windows, `$(pwd)` needs to be `$(pwd -W)` — MSYS rewrites
POSIX paths inside `-v` and `-e` arguments, which silently turns `/app:/ml` into
`C:\Program Files\Git\ml` and leaves the modules unimportable.

## Layout

| Path | What it is |
|---|---|
| `evaluation/metrics.py` | Precision@K, NDCG@K, MRR, Recall@K, Spearman. Pure functions, no dependencies. |
| `evaluation/baselines.py` | Random, TF-IDF, embedding-only, skill-only — the rankers the hybrid must beat. |
| `evaluation/build_pool.py` | Builds the candidate pool for labelling. Run once per corpus refresh. |
| `evaluation/make_review.py` | Turns the pool into `REVIEW.md` for a human to correct. |
| `evaluation/run_matching_eval.py` | Scores every ranker and writes `results/`. |
| `evaluation/build_duplicate_pool.py` | Builds the near-duplicate pair pool (needs the database). |
| `evaluation/run_duplicate_eval.py` | Threshold sweep and confusion matrix. Pure arithmetic, no database. |
| `evaluation/scoring_baselines.py` | Constant and length — what the interview scorer must beat. |
| `evaluation/make_scoring_review.py` | Writes the sheet a human marks interview answers on. |
| `evaluation/read_scoring_review.py` | Reads the marked sheet back into `human_scores.json`. |
| `evaluation/run_scoring_eval.py` | Agreement between the scorer and the human. Needs an LLM provider. |
| `evaluation/results/` | **Committed.** A metric in a closed terminal cannot show a regression. |
| `datasets/matching/` | `queries.jsonl`, `pairs.jsonl`, `labels.json`, `REVIEW.md`. |
| `datasets/duplicates/` | `pairs.jsonl`, `labels.json` — 72 job pairs, binary labels. |
| `datasets/interview_scoring/` | 100 answers to 20 questions, `REVIEW.md`, and the human marks. |

## Marking the interview answers

`datasets/interview_scoring/` is the one dataset here that is **not yet usable**:
the answers exist, the harness exists, and nobody has marked them. Until somebody
does, `run_scoring_eval` prints what it needs and stops. It cannot be worked
around — a model scored against marks it produced itself agrees with itself.

```bash
docker compose run --rm --no-deps -v "$(pwd)/ml:/ml" backend \
    sh -c 'cd /ml && python -m evaluation.make_scoring_review'   # writes REVIEW.md
# fill in the 500 blanks, 0-10, then:
docker compose run --rm --no-deps -v "$(pwd)/ml:/ml" backend \
    sh -c 'cd /ml && python -m evaluation.read_scoring_review'   # -> human_scores.json
```

A partly-marked sheet is fine and the report says how much of it is done. What is
not fine is editing an answer after marking it: `human_scores.json` records a
digest of the questions and answers and is refused when they no longer match,
because a mark applied to the wrong answer produces a worse number and no error.

`ml/embeddings/`, `ml/ranking/` and `ml/classification/` are placeholders from
the original layout in ml.md section 8. The embedding provider and the scorers
both ended up under `app/` for the import-path reason above; these directories
are kept so the document and the tree still correspond, and so offline
counterparts have somewhere to go.

## The labels are not yet trustworthy

`pairs.jsonl` carries `labelled_by: claude-proposed`. The same process that
designed the six-dimension formula also decided what counts as a good match,
which makes the ablation in `results/matching.md` partly circular — most visibly
in the experience dimension, since the rubric leaned on seniority.

**`datasets/matching/REVIEW.md` is the fix.** It lists every pair sorted by
proposed label, highest first, so the labels that move the metrics most are
reviewed first. Correct the `Label` column, and the numbers become evidence
rather than a self-assessment.
