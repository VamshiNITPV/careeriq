# Near-duplicate detection

Generated 2026-09-10T07:24:13.908990+00:00.

> **The positive class has three members.** 72 labelled pairs, 3 of them duplicates. Precision and recall computed over three positives move by a third of their range when one pair is reclassified, so every figure here is a direction, not a measurement. The targets below are reported because ml.md names them, not because this dataset can settle them.

Pool floor 0.880 — deliberately well under any plausible threshold, so the false-negative region is labelled rather than assumed empty. Without that, recall would be 1.0 by construction.

**Stage one catches 0 of these pairs.** The content hash finds a posting pasted twice verbatim; none of these are that. Stage two is doing work stage one cannot.

## Threshold sweep

| Threshold | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| 0.88 | 3 | 69 | 0 | 0 | 0.042 | 1.000 | 0.080 |
| 0.90 | 3 | 29 | 0 | 40 | 0.094 | 1.000 | 0.171 |
| 0.92 | 3 | 11 | 0 | 58 | 0.214 | 1.000 | 0.353 |
| 0.94 | 3 | 2 | 0 | 67 | 0.600 | 1.000 | 0.750 |
| 0.95 _(ml.md)_ | 3 | 1 | 0 | 68 | 0.750 | 1.000 | 0.857 |
| 0.96 | 2 | 1 | 1 | 68 | 0.667 | 0.667 | 0.667 |
| 0.97 **(shipped)** | 2 | 0 | 1 | 69 | 1.000 | 0.667 | 0.800 |
| 0.98 | 2 | 0 | 1 | 69 | 1.000 | 0.667 | 0.800 |
| 0.99 | 1 | 0 | 2 | 69 | 1.000 | 0.333 | 0.500 |
| _target_ | | | | | 0.95 | 0.85 | |

## The trade-off, and why the threshold moved

**At ml.md's 0.95**: precision 0.750, recall 1.000. Recall is perfect and precision is not — it admits 1 pair(s) that are not duplicates.

**At the shipped 0.97**: precision 1.000, recall 0.667. The reverse.

Neither threshold meets both targets, and on three positives neither could be shown to. 0.97 is shipped because **the two errors are not symmetric**: a false positive marks a real posting as a copy and hides it from everyone who would have seen it, while a false negative leaves a duplicate in a list that already shows duplicates. Precision is the one to protect when the action is destructive.

True duplicates sit at 0.993, 0.986, 0.951.

### What 0.95 wrongly flags

| Similarity | Pair | Company |
|---|---|---|
| 0.960 | Senior Engineering Manager - Machine L / Senior Machine Learning Engineer, Data | Roku |

## The finding worth acting on

**Company boilerplate dominates the cosine**, and it is measured rather than inferred. 3 of 72 pairs begin with an identical 300 characters, and **2 of those are not duplicates**. Every false positive above the 0.95 threshold is one of them (1 of 1). One employer's postings open with several identical paragraphs of marketing copy, so a 15-year engineering *manager* role scores 0.960 against a 5-year *engineer* role on text that describes neither.

Note what this does **not** justify: refusing to flag pairs with a shared opening. The highest-scoring true duplicate shares one too, because two copies of the same advert necessarily do. The confound is upstream, and so is the fix.

`description_clean` is documented as boilerplate-stripped and evidently does not remove this kind. Stripping it would raise the signal available to *both* duplicate detection and the semantic ranking dimension, which is a better lever than moving a threshold — and unlike the threshold, it does not need a larger labelled set to justify.

Also worth noting: only 6 of 72 pooled pairs share an employer. The rest are different companies advertising similar work, which is the normal state of a job market rather than duplication — and it is why the scoping in `near_duplicate.py` keeps the candidate set small without discarding the cases that matter.

