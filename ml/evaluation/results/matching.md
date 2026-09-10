# Matching evaluation

`ranking_version` **v1-hand-tuned** — generated 2026-09-10T07:00:42.023297+00:00.

> **Read the sample size before the numbers.** 2 queries, 102 ranked pairs. ml.md's per-query targets were written for a corpus with many users; averaged over 2 they are an anecdote, not evidence. The pair-level correlation at the bottom is the figure that carries statistical weight here.

Labels are proposed by Claude and pending human correction (`labelled_by: claude-proposed`). A relevant result means label >= 2 (MEDIUM or HIGH).

## Rankers

| Ranker | P@5 | P@10 | NDCG@10 | MRR |
|---|---|---|---|---|
| **hybrid** | 0.800 | 0.850 | 0.611 | 0.750 |
| embedding_only | 0.500 | 0.600 | 0.400 | 0.625 |
| skill_only | 0.800 | 0.800 | 0.513 | 0.750 |
| tfidf | 0.600 | 0.650 | 0.408 | 0.750 |
| random | 0.600 | 0.550 | 0.508 | 1.000 |
| _ml.md target_ | 0.70 | 0.60 | 0.75 | 0.65 |

## Retrieval

**Recall@200 = 0.954** (target 0.95). Measured over every labelled relevant job, including those sampled from outside the recall set — without that sample this number would be 1.0 by construction.

- `q1` (3701 chars): 27 relevant of 63 labelled, 53 ranked, recall 0.963
  - missed by stage one: Python- React, Next JS Fullstack Engineer
- `q2` (1402 chars): 37 relevant of 59 labelled, 49 ranked, recall 0.946
  - missed by stage one: AI/ML Engineer (Open-Source LLM – BFSI Domain)
  - missed by stage one: python developer 5 ,pyspark ,django flask (Bengaluru)

## Against the targets

Four of the five targets are met. **NDCG@10 is not** (0.611 against 0.75), and that is the headline result: the hybrid puts relevant jobs near the top (P@5 0.800) but does not order HIGH above MEDIUM well enough.

**MRR is uninformative on this pool** and should not be read as a pass. Random scores 1.000 on it, because 48% of the pooled pairs are relevant and landing one first is close to a coin toss. A metric a shuffle can max out discriminates nothing here.

**Random also beats embedding-only on NDCG@10** (0.508 against 0.400), which is worth dwelling on rather than dismissing. Raw cosine reliably surfaces postings that *read* like the resume and are wrong on seniority — a near-duplicate of the candidate's own words attached to a role demanding eight years. That is precisely the failure ADR-005 predicted of pure similarity, and it is the clearest evidence in this report that the hybrid is earning its complexity.

## Pair-level

**Spearman(score, label) = 0.392** over 102 pairs. Label distribution: {0: 11, 1: 30, 2: 39, 3: 22}.

## Ablation

NDCG@10 with each dimension's weight removed and redistributed over the rest. A figure at or near the full hybrid's 0.611 means that dimension is currently contributing no ordering information.

| Dimension removed | NDCG@10 | change |
|---|---|---|
| semantic | 0.507 | -0.104 |
| skill | 0.739 | +0.128 |
| experience | 0.420 | -0.191 |
| education | 0.588 | -0.024 |
| location | 0.681 | +0.070 |
| salary | 0.592 | -0.020 |

### What the ablation does not prove

**The labels were written by the same process that designed the formula, and the rubric weighted seniority heavily** — a senior role was marked down for a candidate with under a year of experience. The experience dimension is therefore being scored against a rubric built partly around it, and its apparent strength is partly circular. Human correction of the labels is what breaks that circularity, and until it happens these rows indicate where to look rather than what to change.

**Two queries cannot justify removing a dimension.** A result that survives human relabelling and more resumes would be grounds to act; this one is grounds to investigate.

Hybrid NDCG@10 0.611 against embedding-only 0.400 — ml.md: *"If the six-dimension hybrid does not beat raw cosine similarity on NDCG@10, ADR-005 was wrong and the weights need rework — or the complexity should be removed."*

