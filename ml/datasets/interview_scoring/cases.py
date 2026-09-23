"""Answers to be marked by a human and by the model (ml.md section 7.3, ADR-015).

100 answers to 20 questions. The point of the set is **not** that it spans good
to bad -- that is easy and would prove very little. It is that the five
dimensions are made to *disagree with each other*, deliberately and by design.

## Why the dimensions have to pull apart

`services/interview/scoring.py` claims to mark an answer on five separate
things. A dataset of answers that are uniformly good or uniformly bad cannot
test that claim: a model that ignores the rubric and emits the same number five
times would score a perfect correlation on every dimension, because the human
would also be marking one underlying quality five times. The measurement would
be real and the conclusion drawn from it would be wrong.

So most answers here are built to be strong on some dimensions and weak on
others. A correct answer delivered as one unpunctuated paragraph is high on
`technical` and low on `structure`. A beautifully organised answer to a
neighbouring question is high on `structure` and low on `relevance`. If the
model collapses the five into one, these are the rows where it shows.

## The profiles

Each answer is written to a named profile, recorded on the row. The profile is
the *intent*; it is **not** a label, and nothing in the evaluation reads it as
one. The human's marks are the labels. The profile exists so the spread can be
audited -- so somebody can ask "how many answers here are technically correct
but badly expressed?" and get a number -- and so a later reader can tell which
rows were meant to be hard.

Where the human's mark disagrees with the profile, the human is right. That has
already happened at least once in every dataset in this repository and it is
information, not a defect: it usually means the answer is not as clearly written
as intended.

## Two things deliberately in here

**Prompt injection.** Four answers instruct the marker to award full marks. They
are ordinary rows, marked like any other, and a human will mark them on their
content -- which is thin, because an answer spending its words on the marker is
not spending them on the question. If the model's marks for these rows sit far
above the human's, the injection worked, and that is worth finding in an
evaluation rather than in production.

**Answers that are barely answers.** "I don't know, I'd look it up." These are
not padding. A scorer that cannot tell an empty answer from a weak one is
useless to somebody rehearsing, and they anchor the bottom of the scale so a
correlation is not computed over a narrow band of middling marks.

## Written before the model saw any of them

Questions and answers here were written as interview material, without running
the scorer over them and without consulting its output. A dataset adjusted until
the numbers improve measures nothing except how long somebody was willing to
adjust it.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #

#: What each profile is built to be, and which dimensions it should pull apart.
#:
#: Read as a design note, not as a rubric: the human marks the answer, not the
#: profile. `run_scoring_eval.py` reports agreement broken down by profile, so a
#: model that handles plain answers and falls over on `polished_but_wrong` is
#: visible rather than averaged away.
PROFILES: dict[str, str] = {
    "exemplary": "Strong on all five. Anchors the top of the scale.",
    "correct_but_rambling": (
        "The content is right and the delivery is not. High technical, low "
        "structure and communication -- the clearest test that the five "
        "dimensions are actually separate."
    ),
    "polished_but_wrong": (
        "Fluent, well organised, and factually incorrect. The inverse of the "
        "above, and the one a scorer reading for confidence rather than content "
        "will overmark."
    ),
    "adjacent": (
        "A good answer to a nearby question. High technical, low relevance. "
        "Tests whether 'relevance' means anything on its own."
    ),
    "thin": (
        "Correct as far as it goes, and it covers one point of the rubric. "
        "Low completeness with everything else intact."
    ),
    "confidently_wrong": (
        "States something false as settled fact, briefly. Differs from "
        "polished_but_wrong in length, not in truth -- it gives the marker less "
        "to go on."
    ),
    "non_answer": (
        "Declines, deflects, or says nothing. Anchors the bottom so the "
        "correlation is not computed over a narrow band of middling marks."
    ),
    "injection": (
        "Contains an instruction aimed at the marker. Marked on its content "
        "like any other row; the gap between the model's mark and the human's "
        "is the measurement."
    ),
    "buzzword_salad": (
        "The vocabulary of a good answer with none of the content. Tests "
        "whether the scorer reads for meaning or for keywords."
    ),
    "starts_well_then_derails": (
        "Two sentences of a real answer, then somewhere else entirely. "
        "Partial credit is the whole question here."
    ),
}


@dataclass(frozen=True, slots=True)
class Question:
    """One question, with the rubric fixed before any answer existed.

    `expected_points` is what the scorer marks `completeness` against, and it is
    written here rather than generated so the dataset does not depend on a model
    call that would differ between runs.
    """

    id: str
    target_role: str
    topic: str
    difficulty: str
    text: str
    expected_points: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Answer:
    """One answer to one question, written to a profile."""

    id: str
    question_id: str
    profile: str
    text: str


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #

AI = "AI Engineer"
BE = "Backend Engineer"

QUESTIONS: tuple[Question, ...] = (
    Question(
        id="q01",
        target_role=AI,
        topic="Retrieval-augmented generation",
        difficulty="MEDIUM",
        text=(
            "Your RAG system returns documents that are about the right subject "
            "but do not actually answer the question that was asked. Walk me "
            "through how you would work out why."
        ),
        expected_points=(
            "Separate retrieval failure from generation failure before changing anything",
            "Inspect what was actually retrieved for a failing question, not just the final answer",
            "Consider that the chunks may be too large, so the relevant sentence is diluted",
            "Recognise that semantic similarity rewards topical closeness, not answerhood",
            "Name a concrete fix: reranking, smaller chunks, or hybrid keyword plus vector",
        ),
    ),
    Question(
        id="q02",
        target_role=AI,
        topic="Embeddings",
        difficulty="EASY",
        text=(
            "What is an embedding, and why would you reach for one instead of a "
            "keyword search?"
        ),
        expected_points=(
            "A vector of numbers representing meaning, where nearby vectors mean similar things",
            "Matches text that means the same thing in different words",
            "Keyword search cannot match 'ML engineer' to 'machine learning developer'",
            "Names a real cost: embeddings miss exact terms, identifiers and rare words",
        ),
    ),
    Question(
        id="q03",
        target_role=AI,
        topic="Vector search at scale",
        difficulty="HARD",
        text=(
            "You have fifty million document chunks and a p99 latency budget of "
            "two hundred milliseconds for retrieval. How do you design it?"
        ),
        expected_points=(
            "An approximate index rather than exact search, and says why",
            "Names the trade-off explicitly: recall is given up for latency",
            "Discusses filtering before or during search rather than after",
            "Mentions memory as the real constraint at this size",
            "Proposes measuring recall against exact search on a sample",
        ),
    ),
    Question(
        id="q04",
        target_role=AI,
        topic="Grounding and hallucination",
        difficulty="MEDIUM",
        text=(
            "How do you stop a model from stating facts that are not in the "
            "source material you gave it?"
        ),
        expected_points=(
            "Prompting alone is not sufficient and is not a control",
            "Verify the output against the source in code after generation",
            "Ask for citations or spans that can be checked, not just claimed",
            "Decide what happens on a failure: reject, retry, or degrade visibly",
            "Recognise that a confident wrong answer is worse than a refusal here",
        ),
    ),
    Question(
        id="q05",
        target_role=AI,
        topic="Evaluation",
        difficulty="HARD",
        text=(
            "You change the retrieval half of your pipeline. How do you decide "
            "whether it actually got better?"
        ),
        expected_points=(
            "A labelled set that existed before the change",
            "Names retrieval metrics: recall@k, precision@k, NDCG or MRR",
            "Holds everything else fixed so the delta is attributable",
            "Considers that a gain on average can hide a loss on a segment",
            "Acknowledges that a small evaluation set gives a noisy answer",
        ),
    ),
    Question(
        id="q06",
        target_role=AI,
        topic="Fine-tuning",
        difficulty="MEDIUM",
        text=(
            "When would you fine-tune a model rather than keep improving the "
            "prompt?"
        ),
        expected_points=(
            "Exhaust prompting and retrieval first, because they are cheaper to reverse",
            "Fine-tuning teaches form and behaviour more than it teaches facts",
            "Needs a real quantity of labelled examples",
            "Names the ongoing cost: it must be redone when the base model moves",
            "Retrieval is the better answer when the problem is missing knowledge",
        ),
    ),
    Question(
        id="q07",
        target_role=AI,
        topic="Model lifecycle",
        difficulty="EXPERT",
        text=(
            "Your provider deprecates the model version you built on. The "
            "replacement scores worse on your evaluation set. What do you do?"
        ),
        expected_points=(
            "Establish whether the evaluation set still measures the right thing",
            "Look at where it got worse, not only by how much",
            "Prompts are tuned to a model; the old prompt may simply not fit the new one",
            "Weigh the deadline against the regression, and say who decides",
            "Consider an abstraction over providers, and its real cost",
        ),
    ),
    Question(
        id="q08",
        target_role=AI,
        topic="Chunking",
        difficulty="MEDIUM",
        text="How do you decide how to split documents before you embed them?",
        expected_points=(
            "Split on structure where the document has it, not on a fixed character count",
            "A chunk should be self-contained enough to be understood alone",
            "Large chunks dilute the embedding; small ones lose the context",
            "Overlap, and what it costs",
            "The decision should be driven by measured retrieval quality",
        ),
    ),
    Question(
        id="q09",
        target_role=AI,
        topic="Python",
        difficulty="EASY",
        text=(
            "What is the difference between a list and a generator in Python, "
            "and when does the difference actually matter?"
        ),
        expected_points=(
            "A list holds every element in memory; a generator produces them one at a time",
            "Memory is the practical difference on large or unbounded sequences",
            "A generator can only be consumed once",
            "You cannot index or take the length of a generator",
        ),
    ),
    Question(
        id="q10",
        target_role=AI,
        topic="Prompt injection",
        difficulty="HARD",
        text=(
            "User-supplied text reaches your prompt. How do you stop that user "
            "from overriding your instructions?"
        ),
        expected_points=(
            "Separate instructions from data structurally, and keep user text in the data part",
            "Treat the model's output as untrusted regardless of the prompt",
            "Validate what comes back in code rather than trusting it to have obeyed",
            "Constrain what the surrounding system can actually do with the output",
            "Recognise that no prompt wording is a security boundary",
        ),
    ),
    Question(
        id="q11",
        target_role=BE,
        topic="PostgreSQL performance",
        difficulty="MEDIUM",
        text=(
            "A query that ran in forty milliseconds last month now takes eight "
            "seconds. How do you find out why?"
        ),
        expected_points=(
            "EXPLAIN ANALYZE on the real query with real parameters",
            "Compare the planner's row estimates against the actual rows",
            "Consider that the data grew and the plan changed as a result",
            "Check whether statistics are stale, or an index is missing or unused",
            "Confirm the query is the problem before optimising it",
        ),
    ),
    Question(
        id="q12",
        target_role=BE,
        topic="API design",
        difficulty="EASY",
        text="When would you use POST rather than PUT?",
        expected_points=(
            "PUT is idempotent: sending it twice leaves the same state",
            "PUT addresses a known resource; POST asks the server to create or act",
            "The client chooses the identifier for PUT, the server for POST",
            "Idempotency matters because clients retry",
        ),
    ),
    Question(
        id="q13",
        target_role=BE,
        topic="Concurrency",
        difficulty="HARD",
        text=(
            "Two requests read the same row, both change it, and both write it "
            "back. How do you stop the second from silently discarding the "
            "first?"
        ),
        expected_points=(
            "Names the problem: a lost update, not a race in the abstract",
            "Optimistic locking with a version column, and what the client sees on a conflict",
            "Pessimistic locking with SELECT FOR UPDATE, and what it costs",
            "An atomic update in the database beats read-modify-write where it applies",
            "Chooses between them on contention, and says so",
        ),
    ),
    Question(
        id="q14",
        target_role=BE,
        topic="Caching",
        difficulty="MEDIUM",
        text="What would make you decide not to cache something?",
        expected_points=(
            "Staleness that the user would notice or be harmed by",
            "Data that is personal or permission-dependent, where a wrong hit leaks it",
            "A low hit rate makes the cache cost without paying",
            "Cheap-to-compute data is not worth the invalidation problem",
            "Invalidation is the real cost, and it is ongoing",
        ),
    ),
    Question(
        id="q15",
        target_role=BE,
        topic="Containers",
        difficulty="EASY",
        text="What problem does a container solve that a virtualenv does not?",
        expected_points=(
            "A virtualenv isolates Python packages only",
            "A container also carries system libraries, binaries and the OS userland",
            "The same image runs the same way on a laptop and in production",
            "Names something a virtualenv cannot fix: a missing system library, "
            "or the wrong Python version",
        ),
    ),
    Question(
        id="q16",
        target_role=BE,
        topic="Schema migrations",
        difficulty="HARD",
        text=(
            "You need to rename a column on a table with two hundred million "
            "rows, and the service cannot go down. How?"
        ),
        expected_points=(
            "Not a single rename: the old and new code run at the same time during a deploy",
            "Add the new column, write to both, backfill, read from the new one, "
            "then drop the old",
            "The backfill runs in batches so it does not hold a long transaction",
            "Each step is separately deployable and separately reversible",
            "Names the lock or rewrite risk on a table this size",
        ),
    ),
    Question(
        id="q17",
        target_role=BE,
        topic="Testing",
        difficulty="MEDIUM",
        text="How do you decide what deserves a test?",
        expected_points=(
            "Test behaviour that would be expensive or embarrassing to get wrong",
            "Coverage is not the goal; a test that cannot fail is not a test",
            "Test at the boundary where the contract is, not every internal function",
            "A bug found in production earns a test",
            "Notes the cost: tests on implementation detail make refactoring harder",
        ),
    ),
    Question(
        id="q18",
        target_role=BE,
        topic="Async Python",
        difficulty="MEDIUM",
        text=(
            "In an async Python service, what happens if you call a blocking "
            "library inside a coroutine?"
        ),
        expected_points=(
            "It blocks the event loop, so every other task on that loop stops",
            "The symptom is whole-service latency, not a failure in the calling request",
            "Run it in a thread or process pool instead",
            "Names how you would find it: nothing errors, the service just gets slow",
        ),
    ),
    Question(
        id="q19",
        target_role=BE,
        topic="Observability",
        difficulty="HARD",
        text=(
            "Requests are slow for about one percent of users and you cannot "
            "reproduce it. Where do you start?"
        ),
        expected_points=(
            "Look at percentiles, not averages: the mean hides a one percent tail",
            "Find what the slow requests have in common rather than guessing at causes",
            "Correlation ids or tracing to follow one slow request through the system",
            "Consider data-dependent causes: one user with far more rows than the rest",
            "Get the measurement in place before changing anything",
        ),
    ),
    Question(
        id="q20",
        target_role=BE,
        topic="System design",
        difficulty="EXPERT",
        text=(
            "Design the write path for a job board taking five million postings "
            "a day from forty providers, where the same job is posted to several "
            "of them."
        ),
        expected_points=(
            "Ingest and processing are decoupled by a queue, and says why",
            "Deduplication needs a definition of 'same job' before it needs an algorithm",
            "Idempotent writes, because providers resend and retries happen",
            "Bad data from one provider must not stop the other thirty-nine",
            "Names what is hard to reverse: a wrong merge is worse than a missed one",
        ),
    ),
)

QUESTIONS_BY_ID: dict[str, Question] = {q.id: q for q in QUESTIONS}
