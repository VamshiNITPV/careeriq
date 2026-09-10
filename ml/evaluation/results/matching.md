# Matching evaluation

`ranking_version` **v1-hand-tuned** — generated 2026-09-10T11:06:20.584684+00:00.

> **Read the sample size before the numbers.** 2 queries, 102 ranked pairs. ml.md's per-query targets were written for a corpus with many users; averaged over 2 they are an anecdote, not evidence. The pair-level correlation at the bottom is the figure that carries statistical weight here.

Labels are proposed by Claude and pending human correction (`labelled_by: claude-proposed`). A relevant result means label >= 2 (MEDIUM or HIGH).

## Rankers

| Ranker | P@5 | P@10 | NDCG@10 | MRR |
|---|---|---|---|---|
| **hybrid** | 0.900 | 0.850 | 0.628 | 0.750 |
| embedding_only | 0.700 | 0.600 | 0.480 | 1.000 |
| skill_only | 0.800 | 0.850 | 0.609 | 0.750 |
| tfidf | 0.700 | 0.650 | 0.418 | 0.750 |
| random | 0.500 | 0.450 | 0.345 | 1.000 |
| _ml.md target_ | 0.70 | 0.60 | 0.75 | 0.65 |

## Retrieval

**Recall@200 = 0.931** (target 0.95). Measured over every labelled relevant job, including those sampled from outside the recall set — without that sample this number would be 1.0 by construction.

- `q1` (3701 chars): 27 relevant of 63 labelled, 50 ranked, recall 0.889
  - missed by stage one: Python- React, Next JS Fullstack Engineer
  - missed by stage one: Python With Gen AI Developer
  - missed by stage one: AI Engineering Interns | Claude & Engineering AI (Pune)
- `q2` (1402 chars): 37 relevant of 59 labelled, 52 ranked, recall 0.973
  - missed by stage one: AI/ML Engineer (Open-Source LLM – BFSI Domain)

## Against the targets

Four of the five targets are met. **NDCG@10 is not** (0.628 against 0.75), and that is the headline result: the hybrid puts relevant jobs near the top (P@5 0.900) but does not order HIGH above MEDIUM well enough.

**MRR is uninformative on this pool** and should not be read as a pass. Random scores 1.000 on it, because 48% of the pooled pairs are relevant and landing one first is close to a coin toss. A metric a shuffle can max out discriminates nothing here.

**Raw cosine beats a shuffle on NDCG@10** (0.480 against 0.345), so similarity alone does carry ordering information — but not much. Raw cosine reliably surfaces postings that *read* like the resume and are wrong on seniority — a near-duplicate of the candidate's own words attached to a role demanding eight years. That is the failure ADR-005 predicted of pure similarity, and the hybrid's 0.628 against cosine's 0.480 is the clearest evidence here that the extra dimensions earn their complexity.

### Is this run comparable with the last one?

**Ranked-pair digest `b7d87d92a229`** over 102 of 122 labelled pairs, label distribution {0: 13, 1: 29, 2: 39, 3: 21}. `pairs.jsonl` is pinned in git, but only pairs whose jobs are still active and embedded get ranked, so the *comparison set* can move even when the dataset does not. **If the digest differs from the run you are comparing against, the deltas are confounded** — part of any change is a different set of pairs, not a better ranker.

`random` is the detector for exactly this. It is a seeded shuffle of the job ids and never reads an embedding, so it cannot move when the model or the documents change. A shifted `random` means the comparison set shifted.

## Pair-level

**Spearman(score, label) = 0.386** over 102 pairs. Label distribution: {0: 13, 1: 29, 2: 39, 3: 21}.

## Ablation

NDCG@10 with each dimension's weight removed and redistributed over the rest. A figure at or near the full hybrid's 0.628 means that dimension is currently contributing no ordering information.

| Dimension removed | NDCG@10 | change |
|---|---|---|
| semantic | 0.573 | -0.055 |
| skill | 0.723 | +0.095 |
| experience | 0.590 | -0.038 |
| education | 0.594 | -0.035 |
| location | 0.699 | +0.071 |
| salary | 0.634 | +0.006 |

### What the ablation does not prove

**The labels were written by the same process that designed the formula, and the rubric weighted seniority heavily** — a senior role was marked down for a candidate with under a year of experience. The experience dimension is therefore being scored against a rubric built partly around it, and its apparent strength is partly circular. Human correction of the labels is what breaks that circularity, and until it happens these rows indicate where to look rather than what to change.

**Two queries cannot justify removing a dimension.** A result that survives human relabelling and more resumes would be grounds to act; this one is grounds to investigate.

Hybrid NDCG@10 0.628 against embedding-only 0.480 — ml.md: *"If the six-dimension hybrid does not beat raw cosine similarity on NDCG@10, ADR-005 was wrong and the weights need rework — or the complexity should be removed."*

