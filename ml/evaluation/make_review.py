"""Turn the labelled pool into something a person can correct in half an hour.

    docker compose run --rm --no-deps -v "$(pwd)/ml:/ml" backend \
        sh -c 'cd /ml && python -m evaluation.make_review'

Writes `ml/datasets/matching/REVIEW.md`. The labels in `pairs.jsonl` are proposed
by Claude, which makes the evaluation partly circular: the same process that
designed the six-dimension formula also decided what counts as a good match, and
the ablation in the results file is measured against that opinion. **Human
correction is what breaks the circle**, so the job of this file is to make
correcting cheap.

Sorted by proposed label, highest first, because that is where a wrong label
costs most: a HIGH that should be IRRELEVANT distorts Precision@5 and NDCG@10
far more than a LOW that should be IRRELEVANT.
"""

from __future__ import annotations

import json
import pathlib
import re

DATA = pathlib.Path("/ml/datasets/matching")

NAMES = {3: "HIGH", 2: "MEDIUM", 1: "LOW", 0: "IRRELEVANT"}


def _clean(text: str) -> str:
    """Drop characters a terminal or a diff will mangle, and collapse runs.

    Pipes are escaped, not stripped: real job titles are full of them — "Urgent
    Hiring Python Developer | Freshers Welcome | Delhi NCR" — and an unescaped
    one silently splits the row into extra columns, which misaligns every label
    after it in the rendered table.
    """
    collapsed = re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7e]", " ", text)).strip()
    return collapsed.replace("|", r"\|")


def main() -> None:
    queries = {
        q["query_id"]: q
        for q in (
            json.loads(line)
            for line in (DATA / "queries.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    pairs = [
        json.loads(line) for line in (DATA / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    lines = [
        "# Label review",
        "",
        "Proposed labels for the matching evaluation set. **Please correct the `Label` column.**",
        "",
        "| | meaning |",
        "|---|---|",
        "| **HIGH** | I would genuinely apply to this |",
        "| **MEDIUM** | worth considering |",
        "| **LOW** | adjacent, but not really |",
        "| **IRRELEVANT** | no |",
        "",
        "Only HIGH and MEDIUM count as relevant when the metrics are computed, so the "
        "MEDIUM/LOW line is the one that moves the numbers most. Rows are ordered by proposed "
        "label, highest first — a wrong HIGH costs far more than a wrong LOW.",
        "",
        "`outside recall` marks jobs the retrieval stage never returned. Those exist so "
        "Recall@200 is a real measurement rather than 1.0 by construction; if one of them is "
        "relevant, stage one lost a good job.",
        "",
    ]

    for query_id, query in queries.items():
        rows = [p for p in pairs if p["query_id"] == query_id]
        rows.sort(key=lambda p: (-p["label"], p["title"].lower()))
        lines += [
            f"## {query_id} — {query['kind']}",
            "",
            f"{len(rows)} jobs. Resume: {query['resume_chars']} characters.",
            "",
            "| Label | Asks | Job | Note |",
            "|---|---|---|---|",
        ]
        for row in rows:
            note = "outside recall" if not row.get("in_recall_set", True) else ""
            years = f"{row['min_years']}y" if row["min_years"] else "-"
            lines.append(
                f"| **{NAMES[row['label']]}** | {years} | {_clean(row['title'])[:70]} | {note} |"
            )
        lines.append("")

    (DATA / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {DATA / 'REVIEW.md'} with {len(pairs)} rows")


if __name__ == "__main__":
    main()
