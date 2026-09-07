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
working through a matrix of role-and-city combinations, never repeating one
until the rest have been tried.
"""

from __future__ import annotations

from datetime import datetime

#: Roles, drawn from the target roles a candidate states and the skills a resume
#: actually carries. Phrased as someone would search, because the provider
#: matches on the whole string rather than on structured fields.
DEFAULT_ROLES: tuple[str, ...] = (
    "python developer",
    "backend developer",
    "data engineer",
    "data scientist",
    "machine learning engineer",
    "software development engineer",
    "full stack developer",
    "devops engineer",
    "django developer",
    "fastapi developer",
    "golang developer",
    "java developer",
    "react developer",
    "sql developer",
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
    roles: tuple[str, ...] = DEFAULT_ROLES,
    locations: tuple[str, ...] = DEFAULT_LOCATIONS,
) -> list[str]:
    """Every role-and-city combination, in a stable order.

    Ordered location-major so consecutive runs cover different cities rather
    than fourteen variations on Bengaluru — a day's fetch then spans the market
    instead of one corner of it.
    """
    return [f"{role} in {location}" for location in locations for role in roles]


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
