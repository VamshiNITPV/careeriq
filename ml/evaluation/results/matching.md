# Matching evaluation

`ranking_version` **v1-hand-tuned** — generated 2026-09-12T05:49:39.720537+00:00.

> **Read the sample size before the numbers.** 2 queries, 117 ranked pairs. ml.md's per-query targets were written for a corpus with many users; averaged over 2 they are an anecdote, not evidence. The pair-level correlation at the bottom is the figure that carries statistical weight here.

Labels are proposed by Claude and pending human correction (`labelled_by: claude-proposed`). A relevant result means label >= 2 (MEDIUM or HIGH).

## Rankers

| Ranker | P@5 | P@10 | NDCG@10 | MRR |
|---|---|---|---|---|
| **hybrid** | 0.900 | 0.850 | 0.613 | 0.750 |
| embedding_only | 0.700 | 0.600 | 0.465 | 1.000 |
| skill_only | 0.700 | 0.800 | 0.545 | 0.750 |
| tfidf | 0.700 | 0.650 | 0.395 | 0.500 |
| random | 0.800 | 0.500 | 0.410 | 0.750 |
| _ml.md target_ | 0.70 | 0.60 | 0.75 | 0.65 |

## Retrieval

**Recall@300 = 1.000** (target 0.95). Measured over every labelled relevant job, including those sampled from outside the recall set — without that sample this number would be 1.0 by construction.

**Measured against 319 live jobs**, and that number belongs next to the one above. The window is a fixed 300 rows however large the corpus is, so recall falls on its own as postings are fetched — more competition for the same slots. A run against a bigger corpus is not comparable with one against a smaller one, and the difference reads as a regression if this is not on the page.

| Window | Recall | Share of corpus |
|---|---|---|
| 50 | 0.491 | 16% |
| 100 | 0.697 | 31% |
| 200 | 0.917 | 63% |
| 300 **(shipped)** | 1.000 | 94% |
| 500 | 1.000 | 100% |

The curve says which problem this is. If recall is already flat before 300, the missed jobs are ranked far down by the embedding and a wider window buys nothing — that is a *ranking* problem wearing a retrieval label. If it is still climbing, the window is simply too small a slice of the corpus and raising it is the cheap fix.

- `q1` (3701 chars): 27 relevant of 63 labelled, 59 ranked, recall 1.000
- `q2` (1402 chars): 37 relevant of 59 labelled, 58 ranked, recall 1.000

## Against the targets

Four of the five targets are met. **NDCG@10 is not** (0.613 against 0.75), and that is the headline result: the hybrid puts relevant jobs near the top (P@5 0.900) but does not order HIGH above MEDIUM well enough.

**MRR is uninformative on this pool** and should not be read as a pass. Random scores 0.750 on it, because 48% of the pooled pairs are relevant and landing one first is close to a coin toss. A metric a shuffle can max out discriminates nothing here.

**Raw cosine beats a shuffle on NDCG@10** (0.465 against 0.410), so similarity alone does carry ordering information — but not much. Raw cosine reliably surfaces postings that *read* like the resume and are wrong on seniority — a near-duplicate of the candidate's own words attached to a role demanding eight years. That is the failure ADR-005 predicted of pure similarity, and the hybrid's 0.613 against cosine's 0.465 is the clearest evidence here that the extra dimensions earn their complexity.

### Is this run comparable with the last one?

**Ranked-pair digest `57fc741ecb62`** over 117 of 122 labelled pairs, label distribution {0: 19, 1: 34, 2: 41, 3: 23}. `pairs.jsonl` is pinned in git, but only pairs whose jobs are still active and embedded get ranked, so the *comparison set* can move even when the dataset does not. **If the digest differs from the run you are comparing against, the deltas are confounded** — part of any change is a different set of pairs, not a better ranker.

`random` is the detector for exactly this. It is a seeded shuffle of the job ids and never reads an embedding, so it cannot move when the model or the documents change. A shifted `random` means the comparison set shifted.

## Pair-level

**Spearman(score, label) = 0.471** over 117 pairs. Label distribution: {0: 19, 1: 34, 2: 41, 3: 23}.

## Ablation

NDCG@10 with each dimension's weight removed and redistributed over the rest. A figure at or near the full hybrid's 0.613 means that dimension is currently contributing no ordering information.

| Dimension removed | NDCG@10 | change |
|---|---|---|
| semantic | 0.556 | -0.057 |
| skill | 0.700 | +0.087 |
| experience | 0.567 | -0.046 |
| education | 0.579 | -0.035 |
| location | 0.673 | +0.060 |
| salary | 0.610 | -0.003 |

### What the ablation does not prove

**The labels were written by the same process that designed the formula, and the rubric weighted seniority heavily** — a senior role was marked down for a candidate with under a year of experience. The experience dimension is therefore being scored against a rubric built partly around it, and its apparent strength is partly circular. Human correction of the labels is what breaks that circularity, and until it happens these rows indicate where to look rather than what to change.

**Two queries cannot justify removing a dimension.** A result that survives human relabelling and more resumes would be grounds to act; this one is grounds to investigate.

Hybrid NDCG@10 0.613 against embedding-only 0.465 — ml.md: *"If the six-dimension hybrid does not beat raw cosine similarity on NDCG@10, ADR-005 was wrong and the weights need rework — or the complexity should be removed."*

