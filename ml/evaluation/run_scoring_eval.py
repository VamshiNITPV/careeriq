"""Does the interview scorer agree with a human? (ml.md section 7.3, ADR-015)

    docker compose run --rm -v "$(pwd)/ml:/ml" backend \
        sh -c 'export PYTHONPATH=/app:/ml; python -m evaluation.run_scoring_eval'

| Metric | Target |
|---|---|
| Pearson correlation with human scores | >= 0.70 |
| Mean absolute error | <= 0.15 |
| Rank correlation (Spearman) | >= 0.75 |

## Three numbers rather than one, and none of them is redundant

Pearson and MAE are blind to different things, and either alone would let a real
failure through. A scorer marking every answer 0.3 below the human correlates
perfectly -- the shape of its judgement is right, and it is wrong about every
answer. MAE catches that. A scorer whose errors are small but whose ordering is
inverted has a good MAE and has decided the weak answer was the strong one.
Pearson and Spearman catch that.

Spearman is reported because ordering is what the product actually needs.
Somebody rehearsing needs to be told that their second answer was better than
their first; whether the mark was 0.7 or 0.75 changes nothing they would do.

## The baselines are the point of the exercise

A correlation of 0.75 sounds like success until the length baseline scores 0.72,
at which point the model has bought 0.03 with a rubric, five dimensions and a
paid API call. Both baselines are calibrated against the human marks -- they are
allowed to peek -- because a win over a handicapped baseline means nothing.

## Per dimension, and per profile

The headline is computed over the overall marks, but the per-dimension table is
where a model that emits one number five times becomes visible: it would show
five nearly identical rows against human marks that genuinely differ. The
per-profile table answers the question the dataset was built to ask -- whether
the scorer is fooled by fluent nonsense, by length, or by an answer that
instructs it to award full marks.

## Model calls are cached

A hundred scoring calls is real money and real free-tier quota, so results are
written to `model_scores.json` keyed on the dataset digest, the prompt version
and the model name. Re-running the report costs nothing; changing any of those
three invalidates the cache, because all three change what the model was asked.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, "/app")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

from app.integrations.llm.base import LLMProvider
from app.services.interview.prompts import SCORING_PROMPT_VERSION
from app.services.interview.scoring import DIMENSIONS as MODEL_DIMENSIONS
from app.services.interview.scoring import ScoreRejected, score_answer
from datasets.interview_scoring import (
    ANSWERS_BY_ID,
    DIMENSIONS,
    QUESTIONS_BY_ID,
    HumanScores,
    ScoresStale,
    content_digest,
    load_human_scores,
    scores_path,
)

from evaluation.metrics import mean_absolute_error, pearson, spearman
from evaluation.scoring_baselines import constant_baseline, length_baseline

RESULTS = pathlib.Path(__file__).parent / "results"
CACHE = pathlib.Path(__file__).resolve().parents[1] / "datasets" / "interview_scoring"

TARGET_PEARSON = 0.70
TARGET_MAE = 0.15
TARGET_SPEARMAN = 0.75


def _check_dimensions() -> None:
    """The dataset duplicates the dimension list; this is what stops it drifting.

    `datasets/interview_scoring` must be readable without the backend on the
    path, so it cannot import the real list. If the two ever diverge, every
    per-dimension figure below would be comparing a human mark against a
    different dimension's model mark, and nothing would say so.
    """
    if tuple(DIMENSIONS) != tuple(MODEL_DIMENSIONS):
        raise SystemExit(
            f"dimension mismatch: dataset has {DIMENSIONS}, "
            f"scorer has {tuple(MODEL_DIMENSIONS)}"
        )


def _cache_key(provider_model: str) -> str:
    return f"{content_digest()}|prompt={SCORING_PROMPT_VERSION}|model={provider_model}"


def _load_cache(key: str) -> dict[str, dict[str, float]]:
    path = CACHE / "model_scores.json"
    if not path.exists():
        return {}
    stored = json.loads(path.read_text(encoding="utf-8"))
    # A different key means a different question was asked, so the stored
    # answers are not answers to it.
    return stored.get("scores", {}) if stored.get("key") == key else {}


def _save_cache(key: str, scores: dict[str, dict[str, float]]) -> None:
    (CACHE / "model_scores.json").write_text(
        json.dumps({"key": key, "scores": scores}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def _score_with_model(
    provider: LLMProvider, answer_ids: list[str], cached: dict[str, dict[str, float]]
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Mark each answer, reusing the cache. Returns (scores, ids that failed)."""
    scores = dict(cached)
    refused: list[str] = []

    for position, answer_id in enumerate(answer_ids, start=1):
        if answer_id in scores:
            continue
        answer = ANSWERS_BY_ID[answer_id]
        question = QUESTIONS_BY_ID[answer.question_id]
        print(f"  [{position}/{len(answer_ids)}] {answer_id}", flush=True)
        try:
            result = await score_answer(
                provider,
                question_text=question.text,
                expected_points=list(question.expected_points),
                answer_text=answer.text,
                target_role=question.target_role,
            )
        except ScoreRejected as exc:
            # Counted and reported, not retried into existence. An answer the
            # scorer cannot mark is a result about the scorer.
            print(f"      refused: {exc}", flush=True)
            refused.append(answer_id)
            continue
        scores[answer_id] = {
            name: float(value) for name, value in result.dimensions.items()
        }

    return scores, refused


def _agreement(model: list[float], human: list[float]) -> dict[str, float | None]:
    return {
        "pearson": pearson(model, human),
        "spearman": spearman(model, human),
        "mae": mean_absolute_error(model, human),
    }


def compute_report(
    *,
    usable: list[str],
    human: HumanScores,
    model_scores: dict[str, dict[str, float]],
) -> dict:
    """Every number in the report, with no I/O and no model.

    Separated from `main` so the arithmetic is covered by tests rather than by
    somebody reading one run and finding the figures plausible. The alternative
    was to write a synthetic `human_scores.json` into the dataset directory to
    exercise the pipeline, which would put a file full of invented marks exactly
    where the real ones belong. That file only has to be forgotten once.
    """
    human_overall = [human.overall(a) for a in usable]
    model_overall = [
        sum(model_scores[a][d] for d in DIMENSIONS) / len(DIMENSIONS) for a in usable
    ]
    texts = [ANSWERS_BY_ID[a].text for a in usable]

    overall = _agreement(model_overall, human_overall)

    per_dimension = {
        name: _agreement(
            [model_scores[a][name] for a in usable],
            [human.marks[a][name] for a in usable],
        )
        for name in DIMENSIONS
    }

    per_profile: dict[str, dict[str, object]] = {}
    for profile in sorted({ANSWERS_BY_ID[a].profile for a in usable}):
        rows = [a for a in usable if ANSWERS_BY_ID[a].profile == profile]
        h = sum(human.overall(a) for a in rows) / len(rows)
        m = sum(
            sum(model_scores[a][d] for d in DIMENSIONS) / len(DIMENSIONS) for a in rows
        ) / len(rows)
        # The gap is signed on purpose. Overmarking fluent nonsense and
        # undermarking a rambling but correct answer are different failures with
        # different fixes, and an absolute value would hide which one happened.
        per_profile[profile] = {"n": len(rows), "human": h, "model": m, "gap": m - h}

    missed = [
        name
        for name, ok in (
            (
                "pearson",
                overall["pearson"] is not None and overall["pearson"] >= TARGET_PEARSON,
            ),
            (
                "spearman",
                overall["spearman"] is not None
                and overall["spearman"] >= TARGET_SPEARMAN,
            ),
            ("mae", overall["mae"] is not None and overall["mae"] <= TARGET_MAE),
        )
        if not ok
    ]

    return {
        "overall": overall,
        "baselines": {
            "constant": _agreement(constant_baseline(human_overall), human_overall),
            "length": _agreement(length_baseline(texts, human_overall), human_overall),
        },
        "per_dimension": per_dimension,
        "per_profile": per_profile,
        "below_target": missed,
    }


def _fmt(value: float | None) -> str:
    return "   n/a" if value is None else f"{value:6.3f}"


def _row(label: str, scores: dict[str, float | None], *, width: int = 22) -> str:
    return (
        f"{label:<{width}} {_fmt(scores['pearson'])} {_fmt(scores['spearman'])} "
        f"{_fmt(scores['mae'])}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="score only the first N answers -- for a cheap check that the "
        "pipeline runs before spending a hundred model calls on it",
    )
    args = parser.parse_args()

    _check_dimensions()

    try:
        human = load_human_scores()
    except FileNotFoundError:
        print(f"No human marks yet -- nothing at {scores_path()}.\n")
        print("This evaluation cannot run without them, and it cannot be faked:")
        print("a model scored against its own marks agrees with itself.\n")
        print("  1. python -m evaluation.make_scoring_review")
        print("  2. fill in datasets/interview_scoring/REVIEW.md")
        print("  3. python -m evaluation.read_scoring_review")
        return 0
    except ScoresStale as exc:
        print(f"The human marks are stale: {exc}", file=sys.stderr)
        return 1

    from app.integrations.llm import get_llm_provider

    provider = get_llm_provider()
    if provider is None:
        # The same answer the API gives: unconfigured is unconfigured, and a
        # stub would produce marks no model actually made.
        print("No LLM provider configured -- set LLM_PROVIDER and its key.", file=sys.stderr)
        return 1

    answer_ids = sorted(human.marks)
    if args.limit is not None:
        answer_ids = answer_ids[: args.limit]

    key = _cache_key(provider.model)
    cached = _load_cache(key)
    todo = [a for a in answer_ids if a not in cached]
    print(f"{len(answer_ids)} marked answers; {len(cached)} cached, {len(todo)} to score")

    model_scores, refused = asyncio.run(_score_with_model(provider, answer_ids, cached))
    _save_cache(key, model_scores)

    usable = [a for a in answer_ids if a in model_scores]
    if len(usable) < 2:
        print("\nToo few scored answers to compute a correlation.", file=sys.stderr)
        return 1

    report = compute_report(usable=usable, human=human, model_scores=model_scores)
    overall = report["overall"]

    print()
    print(f"answers scored by a human   {human.count} of {len(ANSWERS_BY_ID)}")
    print(f"used in this report         {len(usable)}")
    print(f"refused by the scorer       {len(refused)}")
    print(f"model                       {provider.model}")
    print(f"prompt version              {SCORING_PROMPT_VERSION}")
    print()
    print(f"{'':<22} {'pearson':>6} {'spearman':>6} {'mae':>6}")
    print(f"{'':<22} {'>=0.70':>6} {'>=0.75':>6} {'<=0.15':>6}")
    print("-" * 46)
    print(_row("overall", overall))
    print(_row("  baseline: constant", report["baselines"]["constant"]))
    print(_row("  baseline: length", report["baselines"]["length"]))
    print()

    for name, scores in report["per_dimension"].items():
        print(_row(f"  {name}", scores))
    print()

    # The question the dataset was built to ask. A scorer fooled by fluent
    # nonsense shows up here and nowhere else.
    print(f"{'by profile':<22} {'n':>6} {'human':>6} {'model':>6} {'gap':>6}")
    print("-" * 46)
    for profile, row in report["per_profile"].items():
        print(
            f"  {profile:<20} {row['n']:>6} {row['human']:6.3f} "
            f"{row['model']:6.3f} {row['gap']:+6.3f}"
        )
    print()

    missed = report["below_target"]
    partial = human.count < len(ANSWERS_BY_ID)
    if partial:
        print(
            f"NOTE: {human.count} of {len(ANSWERS_BY_ID)} answers are marked, so these "
            "figures are provisional."
        )
    if missed:
        print(f"BELOW TARGET: {', '.join(missed)}")
    else:
        print("All three targets met.")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "digest": content_digest(),
        "model": provider.model,
        "prompt_version": SCORING_PROMPT_VERSION,
        "scored_by": human.scored_by,
        "human_marked": human.count,
        "answers_in_report": len(usable),
        "refused_by_scorer": refused,
        "partial": partial,
        "targets": {
            "pearson": TARGET_PEARSON,
            "spearman": TARGET_SPEARMAN,
            "mae": TARGET_MAE,
        },
        **report,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "interview_scoring.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {RESULTS / 'interview_scoring.json'}")

    # A provisional run does not fail the build: a half-marked sheet is progress,
    # not a regression, and turning it red would teach everybody to skip it.
    return 1 if missed and not partial else 0


if __name__ == "__main__":
    raise SystemExit(main())
