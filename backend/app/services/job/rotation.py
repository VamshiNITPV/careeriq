"""Which question to ask the jobs provider next.

The provider is a large, slowly-changing index rather than a live feed. Measured
against JSearch on 2026-09-07:

* `python developer in India` filtered to the last 3 days — **0 results**.
* The same query filtered to the last week — **0 results**.
* The same query filtered to the last month — 10 results, dated June to
  September, so the vendor's own recency filter does not agree with the dates it
  reports.
* `golang developer in Hyderabad`, unfiltered — **10 results, all 10 new**.

So repetition yields nothing and variety yields everything. The corpus grows by
working through a matrix of question-and-city combinations, never repeating one
until the rest have been tried.

**One request can ask about several roles at once.** Also measured, on the same
day, and it is what makes a day's budget cover the whole role list rather than
six-nineteenths of it:

* `ai engineer OR genai developer OR llm engineer OR prompt engineer in
  Bengaluru` — 10 results, genuinely mixed: *AI Engineer*, *Generative AI
  Engineer*, *Senior GenAI Engineer*, *LLM Engineer*.
* `python developer OR django developer OR fastapi developer OR backend
  developer in Bengaluru` — 10 results in 5.9s, again mixed: *Python Backend
  Developer*, *Python developer Fastapi*, *Backend Engineer (Python)*, one
  naming Django.

Two limits came with it, both paid for:

1. **A rare term is crowded out by its group.** `vibe coder` returns three real
   postings on its own, and none at all inside the AI group above — the common
   terms take all ten slots. So a term that is rare gets its own query rather
   than a share of someone else's.
2. **An incoherent group is slow enough to time out.** `devops engineer OR
   golang developer OR sql developer OR software development engineer in
   Bengaluru` ran past the 45s client timeout and returned nothing — while
   still costing a request, as ADR-019 records. The timeout has since been
   raised, and groups are kept to terms that describe one kind of job. If a
   group starts showing `created: 0` or timeouts in `job_fetch_runs`, split it.
"""

from __future__ import annotations

from datetime import datetime

#: Roles, grouped so that one request asks about a whole group.
#:
#: Six groups covering nineteen role names, so **six requests cover every role
#: in one city** — which is the point: a day's budget covers the whole list
#: rather than a sixth of it, and the rotation then moves city by city instead
#: of crawling role by role.
#:
#: Groups hold terms that describe one kind of job. That is not tidiness: the
#: measurement in the module docstring shows an incoherent group timing out and
#: costing a request for nothing.
#:
#: `vibe coder` sits alone deliberately. It is a real title — three postings in
#: Bengaluru on 2026-09-07 — but rare enough that grouping it with `ai engineer`
#: returned none of it at all.
ROLE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ai engineer", "genai developer", "llm engineer", "prompt engineer"),
    ("vibe coder",),
    ("python developer", "django developer", "fastapi developer", "backend developer"),
    ("data engineer", "data scientist", "machine learning engineer"),
    ("full stack developer", "react developer", "java developer"),
    ("devops engineer", "golang developer", "sql developer", "software development engineer"),
)

#: Cities, weighted to where the corpus already shows Indian tech hiring.
#: "remote" is included as a location because the provider treats it as one.
DEFAULT_LOCATIONS: tuple[str, ...] = (
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Chennai",
    "Gurugram",
    "Noida",
    "Mumbai",
    "Delhi",
    "remote India",
)


def build_queries(
    groups: tuple[tuple[str, ...], ...] = ROLE_GROUPS,
    locations: tuple[str, ...] = DEFAULT_LOCATIONS,
) -> list[str]:
    """Every role-group-and-city combination, in a stable order.

    Ordered **city-major**, which is the opposite of what it was and is the
    whole point of the grouping: six groups is one city's worth of questions,
    so at six requests a day each day covers every role in one city and the
    next day moves on. The full matrix comes round in nine days rather than
    twenty-eight, so a repeat is asked of an index that has had a week to
    change rather than a month.

    `OR` between the terms of a group, which the provider honours — see the
    module docstring for what was measured.
    """
    return [f"{' OR '.join(group)} in {location}" for location in locations for group in groups]


def next_query(candidates: list[str], last_used: dict[str, datetime]) -> str | None:
    """The query left unasked longest, or never asked at all.

    Unused ones come first — they are the only ones certain to return jobs the
    corpus does not have. After that it is least-recently-used, which is the
    best available guess at which has had the most time to accumulate new
    postings.

    Returns None only when there are no candidates at all; an exhausted matrix
    still returns its oldest entry, and it is the caller's decision whether a
    low-yield repeat is worth a request.
    """
    if not candidates:
        return None
    #: datetime.min is timezone-naive and every stored timestamp is aware, so
    #: they cannot be compared. Sorting on a (has-been-used, when) pair keeps
    #: the unused ones first without ever comparing the two kinds.
    return min(candidates, key=lambda q: (q in last_used, last_used.get(q, _EPOCH)))


_EPOCH = datetime.min
