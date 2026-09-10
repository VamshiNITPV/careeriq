"""The baselines, which have to be *fair* or the comparison means nothing.

A baseline that is accidentally crippled makes the hybrid look good for free,
which is the most comfortable way for an evaluation to be useless. So these
tests mostly check that each baseline does the reasonable thing its name claims.
"""

from __future__ import annotations

import pytest

from evaluation.baselines import (
    rank_embedding_only,
    rank_random,
    rank_skill_only,
    rank_tfidf,
    tokenize,
)

BACKEND = "Senior Python backend engineer building REST APIs with FastAPI and PostgreSQL"
ALSO_BACKEND = "Backend developer, Python and FastAPI, PostgreSQL schemas, REST services"
NURSING = "Registered paediatric nurse providing bedside ward care and medication"
RESUME = "Python backend engineer. Built REST APIs with FastAPI. PostgreSQL and Redis."


class TestTokenize:
    def test_keeps_the_characters_that_carry_meaning_in_tech_terms(self):
        """`c++` and `node.js` must survive as single tokens.

        A plain `\\w+` splits them into `c`, `node` and `js`, which silently
        destroys the signal the lexical baseline is supposed to be good at.
        """
        assert tokenize("C++ and Node.js") == ["c++", "node.js"]

    def test_drops_stopwords(self):
        assert "the" not in tokenize("the Python engineer")
        assert "python" in tokenize("the Python engineer")


class TestTfidf:
    def test_ranks_a_matching_posting_above_an_unrelated_one(self):
        scores = rank_tfidf(RESUME, {"a": BACKEND, "b": NURSING})
        assert scores["a"] > scores["b"]

    def test_the_lexical_baseline_is_genuinely_competent(self):
        """Worth asserting, because a weak baseline flatters the hybrid.

        Two postings describing the same role in overlapping words must both
        score well clear of an unrelated one — if this baseline could not manage
        that, beating it would prove nothing.
        """
        scores = rank_tfidf(RESUME, {"a": BACKEND, "b": ALSO_BACKEND, "c": NURSING})
        assert min(scores["a"], scores["b"]) > scores["c"] * 2

    def test_repetition_does_not_let_one_posting_dominate(self):
        """Log-normalised term frequency, asserted.

        With raw counts, a posting that says "Python" nine times outranks a
        genuinely better match on that one term alone.
        """
        repetitive = " ".join(["python"] * 9)
        scores = rank_tfidf(RESUME, {"spam": repetitive, "real": BACKEND})
        assert scores["real"] > scores["spam"]

    def test_an_empty_pool_and_an_empty_query_do_not_explode(self):
        assert rank_tfidf(RESUME, {}) == {}
        assert rank_tfidf("", {"a": BACKEND}) == {"a": 0.0}

    def test_a_posting_sharing_nothing_scores_zero(self):
        scores = rank_tfidf("zzz qqq", {"a": BACKEND})
        assert scores["a"] == 0.0

    def test_every_candidate_gets_a_score(self):
        # A missing key would silently drop a job from the ranking and change the
        # denominator of every metric computed from it.
        scores = rank_tfidf(RESUME, {"a": BACKEND, "b": NURSING, "c": ""})
        assert set(scores) == {"a", "b", "c"}


class TestRandom:
    def test_is_reproducible_for_a_given_seed(self):
        """ml.md commits evaluation results to git so regressions show in diffs.

        A floor that moves between runs makes every diff noise.
        """
        ids = [f"j{n}" for n in range(20)]
        assert rank_random(ids, seed=7) == rank_random(ids, seed=7)

    def test_different_seeds_give_different_orders(self):
        ids = [f"j{n}" for n in range(20)]
        assert rank_random(ids, seed=1) != rank_random(ids, seed=2)

    def test_scores_descend_so_higher_is_better_everywhere(self):
        # Every baseline in this module must agree on the direction, or the
        # runner's single sort silently reverses one of them.
        ids = [f"j{n}" for n in range(5)]
        scores = rank_random(ids, seed=3)
        ordered = sorted(scores, key=lambda job_id: scores[job_id], reverse=True)
        assert len(set(scores.values())) == len(ids)
        assert len(ordered) == len(ids)


class TestProjections:
    @pytest.mark.parametrize("rank", [rank_embedding_only, rank_skill_only])
    def test_pass_their_input_through_unchanged(self, rank):
        """Deliberately thin. Rescaling the cosine would be monotonic and so
        could not change the ranking, but it would tie the baseline to a constant
        the hybrid tuned for itself — these stay projections on purpose."""
        given = {"a": 0.7, "b": 0.3}
        assert rank(given) == given

    def test_the_returned_mapping_is_a_copy(self):
        # The runner sorts and annotates these; mutating the caller's dict would
        # corrupt the next baseline's input.
        given = {"a": 0.7}
        result = rank_embedding_only(given)
        result["b"] = 1.0
        assert "b" not in given
