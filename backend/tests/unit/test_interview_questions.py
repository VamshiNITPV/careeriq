"""Refusing the questions that are wrong (US-8.1 AC1).

`parse_question` is pure, so every gate is testable against literal strings with
no model anywhere. That is deliberate: these gates are the only thing standing
between a rehearsal and a question about experience the candidate never had.
"""

from __future__ import annotations

import json

import pytest

from app.models.enums import QuestionDifficulty as D
from app.services.interview.questions import (
    QuestionRejected,
    check_entities,
    parse_question,
)

RESUME = """Asha Mehra
Backend Engineer

Experience
Zerodha - Backend Engineer (March 2022 - Present)
- Worked on the payments backend, handling 12,000 transactions per day.
- Migrated the ledger from MySQL to PostgreSQL with no downtime.

Skills
Python, Django, PostgreSQL, Redis, Docker
"""

TOPIC = "PostgreSQL"


def reply(**overrides: object) -> str:
    payload: dict[str, object] = {
        "question_text": "Walk me through how you kept writes consistent during that migration.",
        "topic": TOPIC,
        "difficulty": D.HARD.value,
        "expected_points": ["dual writes or a cutover plan", "how they verified parity"],
        "grounded_in": "Migrated the ledger from MySQL to PostgreSQL",
    }
    payload.update(overrides)
    return json.dumps(payload)


def parse(raw: str, *, topic: str = TOPIC, difficulty: D = D.HARD):
    return parse_question(raw, topic=topic, difficulty=difficulty, resume_text=RESUME)


class TestItParses:
    def test_a_well_formed_reply_becomes_a_question(self) -> None:
        question = parse(reply())

        assert question.topic == TOPIC
        assert question.difficulty is D.HARD
        assert question.grounded_in == "Migrated the ledger from MySQL to PostgreSQL"
        assert len(question.expected_points) == 2

    def test_a_fenced_reply_is_still_read(self) -> None:
        # Models wrap JSON in fences whatever the instruction says. Accepting
        # the habit is not leniency about the schema -- what is inside is still
        # parsed strictly.
        assert parse("```json\n" + reply() + "\n```").topic == TOPIC

    @pytest.mark.parametrize(
        "raw",
        ["not json at all", "[]", '"a string"', "null", ""],
    )
    def test_anything_that_is_not_the_object_is_refused(self, raw: str) -> None:
        with pytest.raises(QuestionRejected):
            parse(raw)

    def test_a_missing_question_is_refused_rather_than_defaulted(self) -> None:
        with pytest.raises(QuestionRejected, match="question_text"):
            parse(reply(question_text=""))


class TestItStaysOnTheAskedTopic:
    """ml.md:609 -- topic and difficulty must match the request.

    A model that substitutes an easier topic leaves the adaptive policy driving
    something that ignores it, and nothing downstream would notice.
    """

    def test_a_different_topic_is_refused(self) -> None:
        with pytest.raises(QuestionRejected, match="topic drifted"):
            parse(reply(topic="Redis"))

    def test_capitalisation_alone_is_not_drift(self) -> None:
        # Returning the right topic in different case has obeyed the
        # instruction. Punishing that would reject good questions for a reason
        # nobody cares about.
        assert parse(reply(topic="postgresql")).topic == TOPIC

    def test_a_different_difficulty_is_refused(self) -> None:
        with pytest.raises(QuestionRejected, match="difficulty drifted"):
            parse(reply(difficulty=D.EASY.value))

    def test_a_missing_difficulty_is_refused(self) -> None:
        with pytest.raises(QuestionRejected, match="difficulty"):
            parse(reply(difficulty=None))


class TestItDoesNotInventExperience:
    """The gate this feature exists behind.

    `grounded_in` is the model's claim about which of the candidate's own words
    it built on. A claim that is not in the resume is experience the candidate
    never reported, and asking about it is the interview equivalent of writing
    an AWS certification onto somebody's CV.
    """

    def test_a_grounding_that_is_not_in_the_resume_is_refused(self) -> None:
        with pytest.raises(QuestionRejected, match="not in the resume"):
            parse(reply(grounded_in="Led a team of ten engineers"))

    def test_a_plausible_but_absent_grounding_is_still_refused(self) -> None:
        # The hard case: every word is resume-ish and the sentence is not there.
        # A substring check would pass this; a word-exact one does not.
        with pytest.raises(QuestionRejected, match="not in the resume"):
            parse(reply(grounded_in="Migrated the payments backend to PostgreSQL"))

    def test_wrapped_resume_text_still_anchors(self) -> None:
        """Extracted PDF text wraps; a model writes it back on one line.

        Those are the same sentence, and rejecting the question over a newline
        would make the gate fire on formatting rather than on truthfulness.
        """
        wrapped = RESUME.replace(
            "Migrated the ledger from MySQL to PostgreSQL",
            "Migrated the ledger\n        from MySQL to PostgreSQL",
        )

        question = parse_question(
            reply(),
            topic=TOPIC,
            difficulty=D.HARD,
            resume_text=wrapped,
        )

        assert question.grounded_in is not None

    def test_no_grounding_at_all_is_allowed(self) -> None:
        # A question need not build on anything specific. Requiring it would
        # push the model to invent a connection, which is the opposite of what
        # this gate is for.
        assert parse(reply(grounded_in=None)).grounded_in is None


class TestTheRubric:
    """`expected_points` is what 9.3 scores against.

    Without it, every score downstream is the model marking against its own
    impression -- which is exactly what ml.md section 7.1 says scoring must not
    be.
    """

    def test_a_missing_rubric_is_refused(self) -> None:
        with pytest.raises(QuestionRejected, match="expected_points"):
            parse(reply(expected_points=[]))

    def test_a_rubric_of_blanks_is_refused(self) -> None:
        with pytest.raises(QuestionRejected, match="expected_points"):
            parse(reply(expected_points=["", "   "]))

    def test_a_rubric_is_capped_rather_than_unbounded(self) -> None:
        question = parse(reply(expected_points=[f"point {n}" for n in range(50)]))

        assert len(question.expected_points) <= 8


class TestEntityCheck:
    """Gate 4, narrowed to credentials after measuring it against a real model.

    The full entity check flagged RAG, BM25, WSGI, ASGI and GIL -- the field's
    vocabulary, not inventions -- and made its own fallback the normal path. It
    cannot tell attribution from hypothesis, and that distinction is the whole
    question, so it now claims only the one thing it can claim.
    """

    def test_a_question_using_the_postings_vocabulary_is_not_flagged(self) -> None:
        """The reason this gate is soft.

        Examining somebody against a job means using that job's words. Treating
        them as fabrications would reject nearly every good question, which is
        why a failure here degrades rather than rejects.
        """
        question = parse(reply())
        posting = "We need experience with PostgreSQL, Kafka and distributed transactions."

        found = check_entities(question, resume_text=RESUME, posting_text=posting)

        assert found == ()

    def test_an_invented_credential_is_flagged(self) -> None:
        """The one thing this gate still claims.

        "Your AWS certification" is ADR-012's canonical fabrication, it is
        almost never legitimate vocabulary inside a question, and the validator
        already recognises the credential words that identify it.
        """
        question = parse(
            reply(
                question_text="Your AWS certification covers this. Describe how.",
                grounded_in=None,
            )
        )

        found = check_entities(question, resume_text=RESUME, posting_text=None)

        assert found == ("AWS",)

    @pytest.mark.parametrize(
        "vocabulary",
        [
            "Explain the GIL and how it affects PostgreSQL connection pooling.",
            "Compare WSGI and ASGI for this workload.",
            "Would RAG or BM25 suit the retrieval step here?",
        ],
    )
    def test_the_fields_vocabulary_is_not_a_fabrication(self, vocabulary: str) -> None:
        """Every one of these was flagged by the un-narrowed gate.

        Found by running against the real model twice and reading why questions
        degraded -- not by any test, because the fixtures were written in
        ordinary English and never contained an acronym.
        """
        question = parse(reply(question_text=vocabulary, grounded_in=None))

        found = check_entities(question, resume_text=RESUME, posting_text=None)

        assert found == ()

    def test_an_invented_employer_slips_past_and_that_is_known(self) -> None:
        """The cost of narrowing, stated rather than hidden.

        "At Netflix you handled failover" is an attribution the entity check no
        longer catches, because nothing at the entity level separates it from
        "how would you handle failover at Netflix's scale". What covers it
        instead: gate 3 refuses any *declared* grounding that is not in the
        resume, and the prompt forbids attribution in as many words.

        Asserted rather than left implicit so that the day somebody widens this
        gate again, they find out here that it was narrowed on purpose.
        """
        question = parse(
            reply(
                question_text="At Netflix you handled PostgreSQL failover. How?",
                grounded_in=None,
            )
        )

        found = check_entities(question, resume_text=RESUME, posting_text=None)

        assert found == ()
