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

#: Roles. Mostly drawn from the target roles a candidate states and the skills a
#: resume actually carries, plus anything asked for by hand. Phrased as someone
#: would search, because the provider matches on the whole string rather than on
#: structured fields.
#:
#: This list is a hand-maintained constant, which is its main limitation: the
#: corpus grows only in the directions written here, so a user whose field is
#: absent finds nothing however long they wait. Reading it from users' stated
#: target roles is the obvious next step and has not been done.
#: Roles asked **everywhere first**, before any other role is asked anywhere.
#:
#: Ordering roles within a city is not enough on its own to make a role arrive
#: soon: the rotation is location-major, so putting a role at the top of one
#: list still leaves it eight city-blocks away from its last city. These are
#: crossed with every location up front instead, so the whole group is covered
#: in the first week rather than the last.
#:
#: Reserve it for a genuinely under-covered field. Everything promoted here
#: delays everything else by the same amount — the budget is fixed, so priority
#: is a reordering, never an increase.
#:
#: "vibe coder" is here on evidence rather than on the guess that preceded it:
#: it looked like a description of a practice rather than a title anyone
#: advertises under, so it was expected to return nothing. One request settled
#: it — "vibe coder in Bengaluru" returned three postings on 2026-09-07, headed
#: *Vibe Coder Entry Level Fresher*, *Tech Lead — Python+DataBricks - Vibe
#: Coder* and *Freelance Web Scraping Engineer (Vibe Coding)*. Employers are
#: using the term. The lesson is the one the module docstring records about
#: `date_posted`: measure the provider, do not reason about it.
PRIORITY_ROLES: tuple[str, ...] = (
    "ai engineer",
    "genai developer",
    "llm engineer",
    "prompt engineer",
    "vibe coder",
)

#: The established titles, already well represented in the corpus. Asked after
#: every priority role has been asked in every city.
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
    priority_roles: tuple[str, ...] = PRIORITY_ROLES,
) -> list[str]:
    """Every role-and-city combination, in a stable order.

    Two blocks: the priority roles across every city, then everything else. The
    split exists because ordering roles *within* a city does not actually make a
    role arrive soon — location-major ordering leaves the ninth city eight
    blocks away regardless of where the role sits in its list.

    Each block is ordered location-major so consecutive runs cover different
    cities rather than nineteen variations on Bengaluru — a day's fetch then
    spans the market instead of one corner of it.

    Duplicates are dropped rather than rejected: a role named in both tuples is
    a maintenance slip, not a reason to fail at startup, and asking the same
    question twice in one cycle would waste a request for nothing.
    """
    ordered = [
        *(f"{role} in {location}" for location in locations for role in priority_roles),
        *(f"{role} in {location}" for location in locations for role in roles),
    ]
    return list(dict.fromkeys(ordered))


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
