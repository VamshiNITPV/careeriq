"""The fabrication validator, measured (ml.md section 6.3, ADR-012, ADR-015).

    docker compose run --rm -v "$(pwd)/ml:/ml" backend \
        sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.run_fabrication_eval'

## Why recall is the headline and precision is not

ml.md sets one target here: **100% fabrication-detection recall**. That asymmetry
is the whole design. A missed fabrication puts a claim the candidate cannot
support onto their resume, and they find out in an interview. A false positive
withholds a suggestion they never see. The two errors are not comparable, so they
are not averaged into an F1 -- that would let a gain on the cheap side hide a
loss on the expensive one.

Precision *is* reported, because a validator that rejects everything scores
perfect recall and ships nothing. It is a cost, not a gate.

## Failures are reported, not hidden

Cases tagged `known-limit` are ones written knowing the current design cannot
catch them -- scope inflation that introduces no new entity, and a proper noun in
lowercase. They are counted in the headline number like any other. A dataset that
quietly excluded its hard cases would report a 100% that means nothing, and the
point of writing this down is to know which claims are actually covered.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime

# `/app` is where the backend lives inside the container; the repo layout is
# what CI has. Both are added rather than either assumed, so the same command
# works in Docker and on a bare runner.
sys.path.insert(0, "/app")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

from app.data.skill_taxonomy import SEED_SKILLS
from app.services.resume.fabrication import validate_suggestion
from app.services.resume.skill_extraction import SkillMatcher
from datasets.fabrication.cases import ALL_CASES, FABRICATED, HONEST, Case

RESULTS = pathlib.Path(__file__).parent / "results"


def build_matcher() -> SkillMatcher:
    """The same taxonomy the product uses, so the number describes the product."""
    entries: dict[str, list[str]] = {}
    for skill in SEED_SKILLS:
        forms = [skill.name.casefold(), *(alias.casefold() for alias in skill.aliases)]
        entries[skill.name] = sorted(set(forms))
    return SkillMatcher(entries)


def main() -> int:
    matcher = build_matcher()

    caught: list[Case] = []
    missed: list[Case] = []
    for case in FABRICATED:
        result = validate_suggestion(
            suggested=case.suggestion, source=case.resume, matcher=matcher
        )
        (caught if not result.passed else missed).append(case)

    passed: list[Case] = []
    over_rejected: list[tuple[Case, str]] = []
    for case in HONEST:
        result = validate_suggestion(
            suggested=case.suggestion, source=case.resume, matcher=matcher
        )
        if result.passed:
            passed.append(case)
        else:
            reasons = ", ".join(f"{e.kind}:{e.text}" for e in result.fabricated)
            over_rejected.append((case, reasons))

    recall = len(caught) / len(FABRICATED)
    specificity = len(passed) / len(HONEST)
    # Of everything rejected, how much deserved it.
    rejected_total = len(caught) + len(over_rejected)
    precision = len(caught) / rejected_total if rejected_total else 1.0

    # The headline with the known-limit cases set aside, reported *alongside*
    # rather than instead: it says how well the design works where it applies,
    # which is a different question from how much it covers.
    reachable = [c for c in FABRICATED if "known-limit" not in c.tags]
    reachable_caught = [c for c in caught if "known-limit" not in c.tags]
    reachable_recall = len(reachable_caught) / len(reachable) if reachable else 1.0

    print(f"cases                      {len(ALL_CASES)}")
    print(f"fabrications               {len(FABRICATED)}")
    print(f"honest rewrites            {len(HONEST)}")
    print()
    print(f"fabrication recall         {recall:.3f}   (target 1.000)")
    print(f"  excluding known limits   {reachable_recall:.3f}   over {len(reachable)} cases")
    print(f"honest rewrites passed     {specificity:.3f}   ({len(passed)}/{len(HONEST)})")
    print(f"precision of rejections    {precision:.3f}")
    print()

    if missed:
        print(f"MISSED -- {len(missed)} fabrication(s) reached the user:")
        for case in missed:
            limit = " [known limit]" if "known-limit" in case.tags else ""
            print(f"  - {case.invented!r}{limit}")
            print(f"      {case.suggestion}")
        print()

    if over_rejected:
        print(f"OVER-REJECTED -- {len(over_rejected)} honest rewrite(s) withheld:")
        for case, reasons in over_rejected:
            print(f"  - {case.suggestion}")
            print(f"      flagged: {reasons}")
        print()

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": len(ALL_CASES),
        "fabrications": len(FABRICATED),
        "honest": len(HONEST),
        "fabrication_recall": round(recall, 4),
        "fabrication_recall_excluding_known_limits": round(reachable_recall, 4),
        "honest_pass_rate": round(specificity, 4),
        "rejection_precision": round(precision, 4),
        "missed": [
            {"invented": c.invented, "suggestion": c.suggestion, "tags": list(c.tags)}
            for c in missed
        ],
        "over_rejected": [
            {"suggestion": c.suggestion, "flagged": reasons} for c, reasons in over_rejected
        ],
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "fabrication.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {RESULTS / 'fabrication.json'}")

    # Non-zero only on a miss the design claims to cover. A known limit is
    # already documented and should not turn every future run red -- it should
    # be visible in the number, which it is.
    unexpected = [c for c in missed if "known-limit" not in c.tags]
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
