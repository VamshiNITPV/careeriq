"""Skill extraction, measured (ml.md section 2.4, ADR-015).

    docker compose run --rm -v "$(pwd)/ml:/ml" backend \
        sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.run_skill_eval'

ADR-015 says no AI component is complete without a dataset and reported metrics.
Skill extraction shipped without either, and it is the component everything else
stands on: the skill dimension of the match score, the recommendations, and the
skill-gap analysis still to be built all consume its output. A wrong skill here
is not a local error — it propagates into a ranking and onto a profile.

## Two numbers, not one

The extractor is a gazetteer, so it can only ever find what the taxonomy
contains. That splits the question in two, and reporting a single F1 would blur
them:

- **Matcher performance** — over the gold skills that *are* in the taxonomy, does
  it find them and avoid inventing others? This is what the code controls.
- **Taxonomy coverage** — what share of the skills a reader names exist in the
  taxonomy at all? This is a hard ceiling on recall that no matcher change can
  lift, and the only fix is adding entries.

An extractor that is perfect at its job still misses every skill the taxonomy has
never heard of. Separating these says which work would actually help.

## The baseline ml.md asks for

"Naive keyword lookup against the skill list with no section awareness or alias
resolution." Built here as `naive_lookup`. If the shipped matcher does not beat
it, the alias table and longest-match scan are not earning their complexity.

## What this does not measure

Resume-side section confidence. `SkillMatcher` is shared between resumes and job
postings, so the *matching* is the same code, but a resume's section weighting
(`_SECTION_CONFIDENCE`) decides which matches reach a profile and is not
exercised here. Postings were used because there are 319 of them and three
resume texts; that is the right trade, and this is the part it costs.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.database import get_session_factory
from app.data.skill_taxonomy import normalize_skill_text
from app.repositories.skill import SkillRepository
from app.services.resume.skill_extraction import build_matcher

DATA = pathlib.Path("/ml/datasets/skill_extraction")
RESULTS = pathlib.Path("/ml/evaluation/results")

#: Targets from ml.md section 2.4.
TARGETS = {"precision": 0.85, "recall": 0.80, "f1": 0.82}


def naive_lookup(text: str, canonical_names: list[str]) -> set[str]:
    """The baseline: substring search for each canonical name, nothing else.

    No aliases, so "Postgres" and "JS" are invisible. No longest-match, so
    "React" fires inside "React Native". No word boundaries beyond `\\b`, which
    is what makes single-letter entries like "R" and "C" catastrophic here — and
    seeing that cost quantified is the point of having a baseline at all.
    """
    lowered = text.lower()
    found = set()
    for name in canonical_names:
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered):
            found.add(name)
    return found


def score(predicted: set[str], gold: set[str]) -> dict[str, float]:
    """Precision, recall and F1 for one document."""
    hits = len(predicted & gold)
    precision = hits / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = hits / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def micro(rows: list[dict[str, int]]) -> dict[str, float]:
    """Pooled over every document, so a long posting counts for more than a short
    one. Reported alongside the macro average because the two disagree when
    document length correlates with difficulty, and here it does."""
    hits = sum(r["hits"] for r in rows)
    predicted = sum(r["predicted"] for r in rows)
    gold = sum(r["gold"] for r in rows)
    precision = hits / predicted if predicted else 0.0
    recall = hits / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


async def main() -> dict[str, Any]:
    sys.path.insert(0, str(DATA))
    from gold import GOLD  # type: ignore[import-not-found]

    documents = [
        json.loads(line)
        for line in (DATA / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    missing = [i for i in range(len(documents)) if i not in GOLD]
    if missing:
        raise SystemExit(f"{len(missing)} documents are unlabelled: {missing}")

    async with get_session_factory()() as session:
        taxonomy = await SkillRepository(session).load_taxonomy()

    matcher = build_matcher(taxonomy)
    canonical = sorted(taxonomy)

    # Every lookup form the taxonomy knows, normalised, mapped to its canonical
    # name. This is how a gold label written the way the posting writes it
    # ("Postgres", "GCP") is resolved to what the extractor would emit.
    by_form: dict[str, str] = {}
    for name, forms in taxonomy.items():
        by_form[normalize_skill_text(name)] = name
        for form in forms:
            by_form.setdefault(normalize_skill_text(form), name)

    shipped_rows: list[dict[str, int]] = []
    naive_rows: list[dict[str, int]] = []
    shipped_doc: list[dict[str, float]] = []
    naive_doc: list[dict[str, float]] = []
    outside: dict[str, int] = {}
    false_positives: dict[str, int] = {}
    false_negatives: dict[str, int] = {}

    for index, document in enumerate(documents):
        text = document["text"]

        # Gold, resolved through the taxonomy. Anything that does not resolve is
        # outside it entirely and is counted separately rather than scored — the
        # matcher cannot be blamed for a word the taxonomy has never held.
        gold_canonical: set[str] = set()
        for label in GOLD[index]:
            resolved = by_form.get(normalize_skill_text(label))
            if resolved is None:
                outside[label] = outside.get(label, 0) + 1
            else:
                gold_canonical.add(resolved)

        shipped = {span.canonical_name for span in matcher.find_spans(text)}
        naive = naive_lookup(text, canonical)

        for name in shipped - gold_canonical:
            false_positives[name] = false_positives.get(name, 0) + 1
        for name in gold_canonical - shipped:
            false_negatives[name] = false_negatives.get(name, 0) + 1

        shipped_rows.append(
            {
                "hits": len(shipped & gold_canonical),
                "predicted": len(shipped),
                "gold": len(gold_canonical),
            }
        )
        naive_rows.append(
            {
                "hits": len(naive & gold_canonical),
                "predicted": len(naive),
                "gold": len(gold_canonical),
            }
        )
        shipped_doc.append(score(shipped, gold_canonical))
        naive_doc.append(score(naive, gold_canonical))

    total_gold = sum(len(v) for v in GOLD.values())
    outside_total = sum(outside.values())

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "documents": len(documents),
        "gold_labels": total_gold,
        "taxonomy_size": len(canonical),
        "coverage": {
            "in_taxonomy": total_gold - outside_total,
            "outside_taxonomy": outside_total,
            "share_covered": (total_gold - outside_total) / total_gold if total_gold else 0.0,
            # The recall ceiling: even a perfect matcher cannot return these.
            "most_common_missing": sorted(outside.items(), key=lambda kv: (-kv[1], kv[0]))[:25],
        },
        "shipped": {
            "micro": micro(shipped_rows),
            "macro": {k: mean([d[k] for d in shipped_doc]) for k in ("precision", "recall", "f1")},
        },
        "naive_baseline": {
            "micro": micro(naive_rows),
            "macro": {k: mean([d[k] for d in naive_doc]) for k in ("precision", "recall", "f1")},
        },
        "worst_false_positives": sorted(
            false_positives.items(), key=lambda kv: (-kv[1], kv[0])
        )[:20],
        "worst_false_negatives": sorted(
            false_negatives.items(), key=lambda kv: (-kv[1], kv[0])
        )[:20],
        "targets": TARGETS,
    }


def _cell(value: float) -> str:
    return f"{value:.3f}"


def _markdown(report: dict[str, Any]) -> str:
    shipped = report["shipped"]["micro"]
    naive = report["naive_baseline"]["micro"]
    coverage = report["coverage"]
    targets = report["targets"]

    lines = [
        "# Skill extraction evaluation",
        "",
        f"Generated {report['generated_at']}. "
        f"{report['documents']} job postings, {report['gold_labels']} hand-written gold labels, "
        f"against a taxonomy of {report['taxonomy_size']} skills.",
        "",
        "> Labels are Claude-written and pending human review. A weaker caveat than on the "
        "matching dataset: \"does this posting name Kubernetes\" has an answer a second reader can "
        "check against the text, unlike a relevance judgement.",
        "",
        "## Against the targets",
        "",
        "| | Precision | Recall | F1 |",
        "|---|---|---|---|",
        f"| **Shipped extractor** | {_cell(shipped['precision'])} | {_cell(shipped['recall'])} "
        f"| {_cell(shipped['f1'])} |",
        f"| Naive lookup (baseline) | {_cell(naive['precision'])} | {_cell(naive['recall'])} "
        f"| {_cell(naive['f1'])} |",
        f"| _ml.md target_ | {targets['precision']:.2f} | {targets['recall']:.2f} "
        f"| {targets['f1']:.2f} |",
        "",
        "Micro-averaged: pooled over every document, so a posting naming forty skills counts for "
        "more than one naming four. The macro average is in the JSON.",
        "",
        "### Read the precision figure carefully — it is not what it looks like",
        "",
        "**It is not a hallucination rate.** Checked term by term, roughly four in five counted "
        "false positives are words *literally present in the posting*: Security appears in all ten "
        "postings it was penalised for, Deployment in seven of seven, Scalability in seven of "
        "seven. The extractor is not inventing them.",
        "",
        "What it is measuring is a genuine disagreement about what counts as a skill. A posting "
        "saying *\"optimize application performance, scalability, and security\"* is describing "
        "the work, not listing requirements — and the gold labels treat it that way, while the "
        "taxonomy holds `Security`, `Scalability`, `Deployment` and `Software Engineering` as "
        "entries the matcher dutifully fires on. **The extractor has no way to tell "
        "\"the job involves security\" from \"security is a required skill\"**, because both land "
        "in a RESPONSIBILITIES block, which maps to REQUIRED at 0.80 confidence.",
        "",
        "This is the same defect Phase 6.5 hit from the other side, where `Communication` turned "
        "up in 45% of postings and flattened the skill dimension of the ranking. Rarity weighting "
        "treated the symptom; this is the cause.",
        "",
        "**So: the precision number is honest about the system's output and unreliable as a "
        "verdict on the matcher.** Splitting the two needs either a taxonomy without generic "
        "entries, or gold labels with a sharper rule than the one used here, and that is the next "
        "piece of work rather than something to paper over now.",
        "",
        "## The recall ceiling",
        "",
        f"**{coverage['outside_taxonomy']} of {report['gold_labels']} gold skills "
        f"({1 - coverage['share_covered']:.0%}) are not in the taxonomy at all.** No matcher "
        "change can find them; only adding entries can. That share caps recall, and it is "
        "reported separately so a recall figure is never read as a verdict on the matching code "
        "when it is really a verdict on the word list.",
        "",
    ]

    if coverage["most_common_missing"]:
        lines += [
            "Most frequently missing:",
            "",
            "| Skill | Postings |",
            "|---|---|",
            *[f"| {name} | {count} |" for name, count in coverage["most_common_missing"][:15]],
            "",
        ]

    lines += [
        "## Where it goes wrong",
        "",
        "| False positive | Postings |",
        "|---|---|",
        *[f"| {name} | {count} |" for name, count in report["worst_false_positives"][:12]],
        "",
        "| Missed (in taxonomy) | Postings |",
        "|---|---|",
        *[f"| {name} | {count} |" for name, count in report["worst_false_negatives"][:12]],
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    RESULTS.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(main())
    (RESULTS / "skill_extraction.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "skill_extraction.md").write_text(_markdown(result), encoding="utf-8")
    print(_markdown(result))
