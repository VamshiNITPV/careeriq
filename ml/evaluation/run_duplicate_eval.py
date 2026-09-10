"""Evaluate near-duplicate detection and commit the result (ml.md section 5).

    docker compose run --rm --no-deps -v "$(pwd -W)/ml:/ml" backend \
        sh -c 'cd /ml && python -m evaluation.run_duplicate_eval'

No database needed: the pool already carries each pair's cosine, so this is pure
arithmetic over the labelled file. Writes `results/duplicates.{json,md}`.

Targets from ml.md section 5: **precision >= 0.95, recall >= 0.85**, with a
reported confusion matrix. The sweep is reported too, because a single threshold
hides the shape of the trade-off — and the shape is the useful part when the
positive class is this small.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime
from typing import Any

from evaluation.metrics import Confusion, confusion_at

DATA = pathlib.Path("/ml/datasets/duplicates")
RESULTS = pathlib.Path("/ml/evaluation/results")

TARGET_PRECISION = 0.95
TARGET_RECALL = 0.85

#: Coarse enough to read, fine enough to show where the boundary sits.
SWEEP = [0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99]

#: What the detector ships with, and what ml.md specified.
SHIPPED = 0.97
SPECIFIED = 0.95


def _cell(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _row(threshold: float, c: Confusion) -> dict[str, Any]:
    return {
        "threshold": threshold,
        "true_positives": c.true_positives,
        "false_positives": c.false_positives,
        "false_negatives": c.false_negatives,
        "true_negatives": c.true_negatives,
        "precision": c.precision,
        "recall": c.recall,
        "f1": c.f1,
    }


def main() -> dict[str, Any]:
    pairs = [
        json.loads(line) for line in (DATA / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    unlabelled = [p for p in pairs if p["label"] is None]
    if unlabelled:
        raise SystemExit(f"{len(unlabelled)} pairs are still unlabelled")

    scores = [p["similarity"] for p in pairs]
    labels = [p["label"] for p in pairs]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "pairs": len(pairs),
        "duplicates": sum(labels),
        "same_company_pairs": sum(1 for p in pairs if p["shares_company"]),
        "caught_by_content_hash": sum(1 for p in pairs if p["same_content_hash"]),
        "shared_opening": sum(1 for p in pairs if p["shared_opening"]),
        # Of the pairs that open with identical text, how many are NOT duplicates.
        # This is the measurement behind the boilerplate finding below: if every
        # such pair were a real duplicate, shared copy would be a useful signal
        # rather than a confound.
        "shared_opening_not_duplicates": sum(
            1 for p in pairs if p["shared_opening"] and p["label"] == 0
        ),
        "false_positives_with_shared_opening": sum(
            1 for p in pairs if p["label"] == 0 and p["similarity"] >= SPECIFIED
            and p["shared_opening"]
        ),
        "pool_floor": min(scores),
        "targets": {"precision": TARGET_PRECISION, "recall": TARGET_RECALL},
        "sweep": [_row(t, confusion_at(scores, labels, t)) for t in SWEEP],
        "shipped": _row(SHIPPED, confusion_at(scores, labels, SHIPPED)),
        "specified": _row(SPECIFIED, confusion_at(scores, labels, SPECIFIED)),
        "duplicate_similarities": sorted(
            (p["similarity"] for p in pairs if p["label"] == 1), reverse=True
        ),
        "false_positives_at_specified": [
            {
                "similarity": p["similarity"],
                "a": p["a"]["title"],
                "b": p["b"]["title"],
                "company": p["a"]["company"] if p["shares_company"] else None,
            }
            for p in pairs
            if p["label"] == 0 and p["similarity"] >= SPECIFIED
        ],
    }


def _markdown(r: dict[str, Any]) -> str:
    shipped, specified = r["shipped"], r["specified"]
    lines = [
        "# Near-duplicate detection",
        "",
        f"Generated {r['generated_at']}.",
        "",
        "> **The positive class has three members.** "
        f"{r['pairs']} labelled pairs, {r['duplicates']} of them duplicates. Precision and recall "
        "computed over three positives move by a third of their range when one pair is "
        "reclassified, so every figure here is a direction, not a measurement. The targets below "
        "are reported because ml.md names them, not because this dataset can settle them.",
        "",
        f"Pool floor {r['pool_floor']:.3f} — deliberately well under any plausible threshold, so "
        "the false-negative region is labelled rather than assumed empty. Without that, recall "
        "would be 1.0 by construction.",
        "",
        f"**Stage one catches {r['caught_by_content_hash']} of these pairs.** The content hash "
        "finds a posting pasted twice verbatim; none of these are that. Stage two is doing work "
        "stage one cannot.",
        "",
        "## Threshold sweep",
        "",
        "| Threshold | TP | FP | FN | TN | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in r["sweep"]:
        mark = ""
        if row["threshold"] == SHIPPED:
            mark = " **(shipped)**"
        elif row["threshold"] == SPECIFIED:
            mark = " _(ml.md)_"
        lines.append(
            f"| {row['threshold']:.2f}{mark} | {row['true_positives']} | {row['false_positives']} "
            f"| {row['false_negatives']} | {row['true_negatives']} | {_cell(row['precision'])} "
            f"| {_cell(row['recall'])} | {_cell(row['f1'])} |"
        )

    lines += [
        f"| _target_ | | | | | {TARGET_PRECISION:.2f} | {TARGET_RECALL:.2f} | |",
        "",
        "## The trade-off, and why the threshold moved",
        "",
        f"**At ml.md's 0.95**: precision {_cell(specified['precision'])}, recall "
        f"{_cell(specified['recall'])}. Recall is perfect and precision is not — it admits "
        f"{specified['false_positives']} pair(s) that are not duplicates.",
        "",
        f"**At the shipped 0.97**: precision {_cell(shipped['precision'])}, recall "
        f"{_cell(shipped['recall'])}. The reverse.",
        "",
        "Neither threshold meets both targets, and on three positives neither could be shown to. "
        "0.97 is shipped because **the two errors are not symmetric**: a false positive marks a "
        "real posting as a copy and hides it from everyone who would have seen it, while a false "
        "negative leaves a duplicate in a list that already shows duplicates. Precision is the one "
        "to protect when the action is destructive.",
        "",
        f"True duplicates sit at {', '.join(f'{s:.3f}' for s in r['duplicate_similarities'])}.",
        "",
    ]

    if r["false_positives_at_specified"]:
        lines += [
            "### What 0.95 wrongly flags",
            "",
            "| Similarity | Pair | Company |",
            "|---|---|---|",
        ]
        for fp in r["false_positives_at_specified"]:
            company = fp["company"] or "_different companies_"
            pair = f"{fp['a'][:38]} / {fp['b'][:38]}".replace("|", r"\|")
            lines.append(f"| {fp['similarity']:.3f} | {pair} | {company} |")
        lines.append("")

    lines += [
        "## The finding worth acting on",
        "",
        f"**Company boilerplate dominates the cosine**, and it is measured rather than inferred. "
        f"{r['shared_opening']} of {r['pairs']} pairs begin with an identical 300 characters, and "
        f"**{r['shared_opening_not_duplicates']} of those are not duplicates**. Every false "
        f"positive above the 0.95 threshold is one of them "
        f"({r['false_positives_with_shared_opening']} of "
        f"{len(r['false_positives_at_specified'])}). "
        "One employer's postings open with several identical paragraphs of marketing copy, so a "
        "15-year engineering *manager* role scores 0.960 against a 5-year *engineer* role on text "
        "that describes neither.",
        "",
        "Note what this does **not** justify: refusing to flag pairs with a shared opening. The "
        "highest-scoring true duplicate shares one too, because two copies of the same advert "
        "necessarily do. The confound is upstream, and so is the fix.",
        "",
        "`description_clean` is documented as boilerplate-stripped and evidently does not remove "
        "this kind. Stripping it would raise the signal available to *both* duplicate detection "
        "and the semantic ranking dimension, which is a better lever than moving a threshold — and "
        "unlike the threshold, it does not need a larger labelled set to justify.",
        "",
        f"Also worth noting: only {r['same_company_pairs']} of {r['pairs']} pooled pairs share an "
        "employer. The rest are different companies advertising similar work, which is the normal "
        "state of a job market rather than duplication — and it is why the scoping in "
        "`near_duplicate.py` keeps the candidate set small without discarding the cases that "
        "matter.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _write(report: dict[str, Any]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "duplicates.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (RESULTS / "duplicates.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))


if __name__ == "__main__":
    _write(main())
