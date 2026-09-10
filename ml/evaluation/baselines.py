"""The rankers the hybrid model has to beat (ml.md section 4.3).

Four baselines, each answering a different question, and the order matters
because each one narrows what a good result could be explained by:

| Baseline | The question it settles |
|---|---|
| Random | Is anything happening at all? |
| TF-IDF cosine | Does semantic embedding beat plain keyword overlap? |
| **Embedding-only** | **Does the six-dimension hybrid earn its complexity?** |
| Skill-overlap only | Does semantic understanding add anything over rules? |

ml.md is unambiguous that the third is the one that matters: *"If the
six-dimension hybrid does not beat raw cosine similarity on NDCG@10, ADR-005 was
wrong and the weights need rework — or the complexity should be removed."* This
module exists so that sentence can be checked rather than assumed.

Every function returns `{job_id: score}` with higher meaning better, so the
runner sorts them all through one code path and cannot accidentally order one
baseline differently from another.

**TF-IDF is implemented here in about twenty lines rather than imported.** The
base backend image carries no numpy or scikit-learn — only the 3 GB `ml` image
does, via sentence-transformers — and adding either to the API image to support
one offline baseline would undo the separation architecture.md's cold-start risk
note exists to protect.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence

#: Same token shape the fake embedding provider uses, so "c++" and "node.js"
#: survive tokenisation rather than becoming "c" and "node", "js".
_TOKEN = re.compile(r"[a-z0-9+#.]+")

#: Words carrying no discriminating signal in a corpus that is entirely job
#: adverts. Kept deliberately short: IDF already suppresses anything that appears
#: in most documents, and a long hand-written list quietly becomes a second,
#: untested model.
_STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those
    of to in for with on at by from as
    is are was were be been being have has had do does did
    will would can could should may might must
    we you they it our your their its i me my he she his her them us
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


def rank_random(job_ids: Sequence[str], *, seed: int = 0) -> dict[str, float]:
    """The sanity floor.

    Seeded, because an unseeded floor moves between runs and a committed result
    that cannot be reproduced is not a baseline — it is a number from a terminal
    that has since been closed (ml.md section 8).
    """
    generator = random.Random(seed)
    shuffled = list(job_ids)
    generator.shuffle(shuffled)
    # Descending scores so "higher is better" holds uniformly across this module.
    return {job_id: float(len(shuffled) - position) for position, job_id in enumerate(shuffled)}


def rank_tfidf(query_text: str, documents: Mapping[str, str]) -> dict[str, float]:
    """Cosine similarity between TF-IDF vectors of the resume and each posting.

    The lexical control. If embeddings cannot beat this, the 420 MB model and the
    vector column are buying nothing that a term count would not.

    IDF is computed over the candidate pool rather than the whole corpus. That is
    the honest choice for a pooled evaluation — the pool is what is being ranked —
    but it does mean the figure is not comparable across runs with different
    pools, which is why the runner records the pool size alongside it.
    """
    if not documents:
        return {}

    doc_tokens = {job_id: tokenize(text) for job_id, text in documents.items()}
    total_docs = len(doc_tokens)
    containing = Counter(token for tokens in doc_tokens.values() for token in set(tokens))
    # Smoothed, so a term present in every document gets a small positive weight
    # rather than exactly zero, and one absent from the pool cannot divide by zero.
    idf = {
        token: math.log((total_docs + 1) / (count + 1)) + 1 for token, count in containing.items()
    }

    query = _tfidf_vector(tokenize(query_text), idf)
    if not query:
        return dict.fromkeys(documents, 0.0)

    return {
        job_id: _cosine(query, _tfidf_vector(tokens, idf))
        for job_id, tokens in doc_tokens.items()
    }


def _tfidf_vector(tokens: Sequence[str], idf: Mapping[str, float]) -> dict[str, float]:
    """Log-normalised term frequency times IDF.

    Log-normalised rather than raw: a posting that says "Python" nine times is
    not nine times more about Python than one that says it once, and raw counts
    let a repetitive advert dominate the ranking on one term.
    """
    counts = Counter(tokens)
    return {
        token: (1 + math.log(count)) * idf[token]
        for token, count in counts.items()
        if token in idf
    }


def _cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if not a or not b:
        return 0.0
    # Iterate the smaller side: the intersection is all that contributes.
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(weight * large.get(token, 0.0) for token, weight in small.items())
    norm_a = math.sqrt(sum(weight * weight for weight in a.values()))
    norm_b = math.sqrt(sum(weight * weight for weight in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_embedding_only(cosines: Mapping[str, float]) -> dict[str, float]:
    """Raw candidate-job cosine, unrescaled and unweighted.

    **The baseline that decides whether ADR-005 was right.** Rescaling is
    deliberately *not* applied: it is monotonic, so it cannot change this
    ranking, and leaving it out keeps the baseline free of any constant the
    hybrid tuned for itself.
    """
    return dict(cosines)


def rank_skill_only(skill_scores: Mapping[str, float]) -> dict[str, float]:
    """The skill dimension alone — the rules-without-meaning control.

    Its expected failure is the career-switcher case (US-4.3): someone whose
    experience is described in words the posting does not use scores zero here
    however well they would do the job, which is precisely the gap semantic
    matching is supposed to close.
    """
    return dict(skill_scores)
