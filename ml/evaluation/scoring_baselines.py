"""What the interview scorer has to beat (ml.md section 9, ADR-015).

ml.md's evaluation-first workflow puts a trivial baseline between building the
dataset and believing the component: *"implement the trivial baseline and
measure it"*. Separate from `baselines.py`, which ranks jobs -- these predict a
mark, which is a different shape of problem and shares none of that code.

| Baseline | The question it settles |
|---|---|
| Constant | Is the model's error better than predicting the average? |
| **Length** | **Is the model reading the answer, or measuring it?** |

The second is the one that matters, and it is the reason this file exists.
Interview answers that are good tend to be longer, so a scorer that had learned
nothing except "longer is better" would produce a respectable correlation with a
human. If the model does not beat length by a clear margin, the five dimensions,
the rubric and the citations are decoration on a word count.

## Both baselines are given every advantage

Each is calibrated against the human marks it is being compared to -- the
constant is the human mean, and length is mapped onto the human distribution by
rank. That is information a real predictor would not have, and it is given
deliberately: a baseline that is allowed to peek is a harder baseline, and the
point of a baseline is for the component to have to beat it. A win over a
handicapped baseline would mean nothing.

Note what the length baseline does to the per-dimension story. It returns one
number per answer, so the *same* prediction is compared against all five
dimensions. Where it scores well on a dimension, that dimension is substantially
predictable from length alone -- which is worth knowing before concluding the
model has understood anything about it.
"""

from __future__ import annotations

from collections.abc import Sequence


def constant_baseline(human: Sequence[float]) -> list[float]:
    """Predict the mean of the human marks for every answer.

    The floor for mean absolute error. A model whose MAE is not clearly below
    this has not learned to tell answers apart -- it has learned roughly where
    the middle is, which the arithmetic mean already knew.

    Its Pearson correlation is undefined rather than zero, because the
    prediction never varies. `metrics.pearson` returns `None` for exactly this,
    and the report prints that rather than a 0.0 that would read as "measured,
    and found unrelated".
    """
    if not human:
        return []
    mean = sum(human) / len(human)
    return [mean] * len(human)


def length_baseline(texts: Sequence[str], human: Sequence[float]) -> list[float]:
    """Rank answers by length, then map those ranks onto the human marks.

    The mapping is what makes this a serious baseline rather than a straw man.
    Raw character counts are not on the same scale as marks, so comparing them
    directly would understate it on MAE for a reason that has nothing to do with
    whether length predicts quality. Instead the longest answer is given the
    highest human mark that was awarded, the second longest the second highest,
    and so on -- so the baseline gets the right *distribution* for free and is
    judged purely on whether it gets the right *order*.

    Ties in length share the marks they span, so the result does not depend on
    the order the answers happened to arrive in.
    """
    if len(texts) != len(human):
        raise ValueError("texts and human marks must be the same length")
    if not texts:
        return []

    lengths = [len(text) for text in texts]
    # The marks that were actually awarded, sorted -- the distribution the
    # baseline is allowed to borrow.
    available = sorted(human)

    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    predicted = [0.0] * len(lengths)

    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and lengths[order[end + 1]] == lengths[order[position]]:
            end += 1
        # Every answer in a tie gets the average of the marks the group spans,
        # rather than an arbitrary one of them.
        shared = sum(available[position : end + 1]) / (end + 1 - position)
        for index in range(position, end + 1):
            predicted[order[index]] = shared
        position = end + 1

    return predicted
