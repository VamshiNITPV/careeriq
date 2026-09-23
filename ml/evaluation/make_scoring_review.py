"""Turn the answer set into a sheet a person can mark (ml.md section 7.3).

    docker compose run --rm --no-deps -v "$(pwd)/ml:/ml" backend \
        sh -c 'cd /ml && python -m evaluation.make_scoring_review'

Writes `ml/datasets/interview_scoring/REVIEW.md`. `read_scoring_review.py` reads
it back into `human_scores.json`.

Five hundred judgements is the real cost of this evaluation, so the job of this
file is to make each one as cheap as it can honestly be made. The question and
its rubric are printed once per group rather than once per answer, the labels
are pre-printed so the only thing to type is a digit, and the scale is 0-10
integers rather than decimals -- `8` instead of `0.8`, five hundred times.

## Three decisions that affect what the marks mean

**The profile is not shown.** Every answer here was written to an intent --
`polished_but_wrong`, `adjacent`, and so on -- and printing it would hand the
marker the answer. The marks have to come from reading the answer, or the
agreement figure is measuring how well the model guesses a label that was
already written down. This is the one rule in this file that cannot be relaxed
for convenience, and `tests/test_scoring_review.py` asserts it.

**Answers are shuffled within their question, deterministically.** Written in
profile order, the strongest answer would sit first under every question and a
marker would learn the pattern by the third group. The seed is fixed so that
regenerating the sheet does not reshuffle a partly-marked one.

**Grouped by question, not interleaved.** This is a real trade. Reading the
question and rubric once for five answers is most of the cost saving, and it
does invite marking the five relative to each other rather than absolutely.
Since the headline metrics include a rank correlation, relative judgement is
close to what is being asked for anyway -- but it is a choice, and a marker who
wants to avoid it can mark each answer against the rubric before looking at the
next.

The scale is deliberately coarser than the model's. A human asked for 0.83
invents precision they do not have; a human asked for 8 out of 10 does not. The
rounding error that introduces is at most 0.05, comfortably inside the 0.15 MAE
target.
"""

from __future__ import annotations

import pathlib
import random
from collections.abc import Sequence

from datasets.interview_scoring import (
    ANSWERS,
    DIMENSIONS,
    QUESTIONS,
    Answer,
    content_digest,
)

OUT = pathlib.Path(__file__).resolve().parents[1] / "datasets" / "interview_scoring"

#: Fixed so that regenerating the sheet does not reshuffle a partly-marked one.
SHUFFLE_SEED = 20260923

#: What each dimension means, in the marker's terms rather than the model's.
#:
#: Written to be markable independently. "Is it clear?" and "is it organised?"
#: are close enough to collapse into one impression unless the difference is
#: spelled out, and if they collapse, two of the five dimensions stop carrying
#: information.
_GUIDE: dict[str, str] = {
    "technical": "Is what they said actually correct?",
    "relevance": "Does it answer THIS question, or a nearby one?",
    "completeness": "How much of the rubric below did they cover?",
    "communication": "Sentence by sentence, is it clear? (not: is it correct)",
    "structure": "Does it go somewhere in order, or wander?",
}

_HEADER = """\
# Interview scoring -- human marks

**Mark every answer on the five dimensions, 0 to 10.** Replace each `_` with a
number. Leave a `_` where you have not marked yet; a partly-marked sheet loads
fine and the run reports how many are done.

| | |
|---|---|
| **0-2** | wrong, or says nothing |
| **3-4** | some of it is there |
| **5-6** | acceptable, a real answer |
| **7-8** | good |
| **9-10** | could not reasonably be better |

{guide}

Do not try to be consistent with what the model would say -- the point of this
sheet is to disagree with it where you disagree. Mark what you actually think,
including where an answer is technically right and badly delivered, or well
delivered and wrong. Those are the rows that decide whether the five dimensions
are measuring five things.

Answers are shuffled within each question. Nothing tells you which answers were
written to be good, and that is deliberate.

When you are done:

```
docker compose run --rm --no-deps -v "$(pwd)/ml:/ml" backend \\
    sh -c 'cd /ml && python -m evaluation.read_scoring_review'
```

<!-- digest: {digest} -->
<!-- Do not edit the line above. It pins these marks to these answers; if the
     answers change, the marks are refused rather than silently reused. -->

---
"""


def _score_line() -> str:
    return "SCORES  " + "  ".join(f"{name}=_" for name in DIMENSIONS)


def build_sheet(answers: Sequence[Answer] = ANSWERS) -> str:
    """The sheet, as text. Pure, so a test can assert what it does not contain.

    Takes the answers as an argument for exactly one reason: a test regenerates
    the sheet with every profile relabelled and asserts the output is
    byte-identical, which proves nothing profile-derived reaches the page. A
    keyword search cannot prove that -- several profile names are ordinary
    English words, and one of the questions is about prompt injection.
    """
    # A fixed seed is the point: regenerating a partly-marked sheet must not
    # move answers under headings somebody has already read. Nothing here is
    # security-sensitive, so a predictable sequence is the requirement.
    shuffler = random.Random(SHUFFLE_SEED)  # noqa: S311
    guide = "\n".join(f"- **{name}** -- {text}" for name, text in _GUIDE.items())

    lines = [_HEADER.format(guide=guide, digest=content_digest())]

    for number, question in enumerate(QUESTIONS, start=1):
        for_question = [a for a in answers if a.question_id == question.id]
        shuffler.shuffle(for_question)

        rubric = "\n".join(f"  - {point}" for point in question.expected_points)
        article = "an" if question.target_role[0] in "AEIOU" else "a"
        lines.append(
            f"## Question {number} of {len(QUESTIONS)} "
            f"-- {question.topic} ({question.difficulty})\n\n"
            f"*Asked for {article} {question.target_role} role.*\n\n"
            f"> {question.text}\n\n"
            f"**A strong answer covers:**\n{rubric}\n"
        )

        for letter, answer in zip("ABCDE", for_question, strict=True):
            # The id is what the parser keys on, so it is printed rather than
            # implied by position -- a sheet with a section moved or deleted
            # still reads back correctly.
            lines.append(
                f"### {letter}. `{answer.id}`\n\n"
                f"{answer.text}\n\n"
                f"```\n{_score_line()}\n```\n"
            )

        lines.append("---\n")

    return "\n".join(lines)


def main() -> None:
    path = OUT / "REVIEW.md"
    path.write_text(build_sheet(), encoding="utf-8")
    print(f"wrote {path}")
    print(f"  {len(ANSWERS)} answers over {len(QUESTIONS)} questions")
    print(f"  {len(ANSWERS) * len(DIMENSIONS)} marks to give")
    print(f"  digest {content_digest()}")


if __name__ == "__main__":
    main()
