"""Adversarial cases for the fabrication validator (ml.md section 6.3, ADR-012).

The validator's target is **100% fabrication-detection recall** -- the one metric
in the system with no tolerance for a miss, because what gets through does not
land in a report, it lands on a resume and then in an interview.

## How these were written

Each case is a (resume, suggestion) pair with the answer stated up front, and the
answers were written from ADR-012's rule -- *any entity in the output and not in
the input* -- **before** running the validator. Writing them the other way round
produces a dataset that agrees with the code by construction and measures
nothing. Several cases below fail; they are kept exactly as written, because a
dataset edited to match the implementation is not evidence about it.

## Both directions are measured

`FABRICATED` cases must all be caught: a miss is the failure this component
exists to prevent. `HONEST` cases must all pass: a validator that rejects
everything scores 100% recall and ships nothing, so the false-positive rate on
legitimate rewrites is the cost side of the same measurement and is reported
next to it.

## The evasions are deliberate

A model does not invent things in one tidy format. The fabricated set includes
the same claim written as digits, as words, as an abbreviation and as a scaled
unit, plus proper nouns in every sentence position, because a check that works
only on "40%" and not on "forty percent" is not a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Source resumes
# --------------------------------------------------------------------------- #

BACKEND = """
Priya Raman
Senior Backend Engineer

Summary
Backend engineer with 6 years building payment services at Zerodha.

Experience
Zerodha - Senior Backend Engineer (March 2019 - Present)
- Worked on the payments backend, handling 12,000 transactions per day.
- Reduced p99 latency by 35% across the settlement service.
- Mentored three junior engineers.
- Migrated the ledger from MySQL to PostgreSQL with no downtime.

Skills
Python, Django, PostgreSQL, Redis, Docker, Git

Education
B.Tech in Computer Science, NIT Warangal, 2017
"""

DATA = """
Aditya Shah
Data Analyst

Summary
Analyst working on reporting pipelines for a retail business.

Experience
Reliance Retail - Data Analyst (June 2021 - Present)
- Built daily sales reports used by the category team.
- Automated a manual spreadsheet process that took two days each week.
- Wrote SQL queries against the warehouse to answer merchandising questions.

Skills
SQL, Excel, Python, Tableau

Education
B.Com, University of Mumbai, 2021
"""

FRONTEND = """
Sana Qureshi
Frontend Engineer

Experience
Freshworks - Frontend Engineer (2020 - 2024)
- Rebuilt the billing settings screen in React.
- Cut the main bundle from 900KB to 410KB.
- Ran accessibility fixes across the onboarding flow.

Skills
JavaScript, TypeScript, React, CSS, Webpack
"""


@dataclass(frozen=True, slots=True)
class Case:
    resume: str
    suggestion: str
    #: True if the suggestion asserts something the resume does not.
    fabricated: bool
    #: What was invented, for the report. Empty for honest rewrites.
    invented: str = ""
    #: Why this case is here, when that is not obvious from the text.
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Fabrications -- every one of these must be caught
# --------------------------------------------------------------------------- #

FABRICATED: tuple[Case, ...] = (
    # --- invented metrics ------------------------------------------------- #
    Case(
        BACKEND,
        "Reduced p99 latency by 40% across the settlement service.",
        True,
        "40%",
        "The resume says 35%. Inflating a real number is the commonest invention.",
        ("number",),
    ),
    Case(
        BACKEND,
        "Reduced p99 latency by forty percent across the settlement service.",
        True,
        "forty percent",
        "The same claim spelled out. A check that only reads digits is not a check.",
        ("number", "evasion"),
    ),
    Case(
        BACKEND,
        "Handled 120,000 transactions per day.",
        True,
        "120,000",
        "An order of magnitude added to a real figure; the digits overlap.",
        ("number",),
    ),
    Case(
        BACKEND,
        "Processed $4M in daily settlement volume.",
        True,
        "$4M",
        "No monetary figure appears anywhere in the resume.",
        ("number",),
    ),
    Case(
        BACKEND,
        "Drove a 3% improvement in settlement throughput.",
        True,
        "3%",
        "The resume's 'three' is a headcount. The unit is part of the claim.",
        ("number", "evasion"),
    ),
    Case(
        DATA,
        "Automated a manual process, saving 15 hours a week.",
        True,
        "15 hours",
        "The resume says two days, not fifteen hours. A restatement is a new figure.",
        ("number",),
    ),
    Case(
        FRONTEND,
        "Cut the main bundle by 60%.",
        True,
        "60%",
        "900KB to 410KB is a real pair; the percentage is derived and never stated.",
        ("number", "derived"),
    ),
    Case(
        DATA,
        "Reports used by more than 200 people across the business.",
        True,
        "200",
        "An audience size the resume never gives.",
        ("number",),
    ),
    # --- invented credentials --------------------------------------------- #
    Case(
        BACKEND,
        "AWS Certified Solutions Architect with payment systems experience.",
        True,
        "AWS Certified Solutions Architect",
        "ADR-012's opening example. Checkable by an interviewer in seconds.",
        ("credential",),
    ),
    Case(
        BACKEND,
        "Certified Kubernetes Administrator (CKA) maintaining production clusters.",
        True,
        "CKA",
        "An acronym credential, short enough to slip a general proper-noun rule.",
        ("credential",),
    ),
    Case(
        DATA,
        "PMP certified analyst delivering reporting projects.",
        True,
        "PMP",
        "",
        ("credential",),
    ),
    Case(
        BACKEND,
        "Holds an M.Tech in Distributed Systems from IIT Bombay.",
        True,
        "M.Tech, IIT Bombay",
        "A degree and an institution, neither in the resume.",
        ("credential", "organization"),
    ),
    # --- invented employers and products ---------------------------------- #
    Case(
        BACKEND,
        "Built payment services at Stripe and Zerodha.",
        True,
        "Stripe",
        "An employer appended to a real one, mid-sentence.",
        ("organization",),
    ),
    Case(
        BACKEND,
        "Stripe was where I built the payments platform.",
        True,
        "Stripe",
        "The same invention in sentence-initial position, where a capital says "
        "nothing on its own. This is the case that motivated the opener list.",
        ("organization", "evasion"),
    ),
    Case(
        BACKEND,
        "Owned Stripe's settlement integration end to end.",
        True,
        "Stripe's",
        "Possessive form, which must not be treated as a different token.",
        ("organization", "evasion"),
    ),
    Case(
        DATA,
        "Built reporting pipelines for Flipkart's category teams.",
        True,
        "Flipkart",
        "",
        ("organization",),
    ),
    Case(
        FRONTEND,
        "Rebuilt the billing screen in React at Zoho.",
        True,
        "Zoho",
        "",
        ("organization",),
    ),
    # --- invented skills --------------------------------------------------- #
    Case(
        BACKEND,
        "Deployed payment services on Kubernetes.",
        True,
        "Kubernetes",
        "Docker is in the resume; Kubernetes is the adjacent thing a model reaches for.",
        ("skill",),
    ),
    Case(
        DATA,
        "Built dashboards in Tableau and Power BI.",
        True,
        "Power BI",
        "One real tool, one added alongside it.",
        ("skill",),
    ),
    Case(
        FRONTEND,
        "Rebuilt the billing settings screen in React and Angular.",
        True,
        "Angular",
        "",
        ("skill",),
    ),
    Case(
        BACKEND,
        "Built services in Java and Python.",
        True,
        "Java",
        "The resume says Python. 'Java' must not be satisfied by a substring elsewhere.",
        ("skill", "evasion"),
    ),
    Case(
        BACKEND,
        "Managed streaming ingestion with Apache Kafka.",
        True,
        "Apache Kafka",
        "",
        ("skill",),
    ),
    # --- invented dates ---------------------------------------------------- #
    Case(
        BACKEND,
        "Led the payments backend since 2015.",
        True,
        "2015",
        "Predates the resume's own history.",
        ("date",),
    ),
    Case(
        FRONTEND,
        "Frontend engineer at Freshworks from 2018 to 2024.",
        True,
        "2018",
        "One endpoint of a real range moved.",
        ("date",),
    ),
    Case(
        DATA,
        "Joined Reliance Retail in January 2021.",
        True,
        "January",
        "Month changed from June; the year is real, which makes it harder to spot.",
        ("date",),
    ),
    # --- invented scope and seniority -------------------------------------- #
    Case(
        BACKEND,
        "Led a team of 8 engineers on the settlement service.",
        True,
        "8 engineers",
        "The resume says three, and mentoring is not leading.",
        ("number",),
    ),
    Case(
        DATA,
        "Managed the analytics function for Reliance Retail.",
        True,
        "Managed the analytics function",
        "A seniority claim with no number in it. Expected to be missed: nothing "
        "here is a new entity, so an entity-level check cannot see it. Kept to "
        "keep that limit visible in the reported number.",
        ("scope", "known-limit"),
    ),
    Case(
        FRONTEND,
        "Owned the entire billing platform architecture.",
        True,
        "Owned the entire billing platform",
        "Scope inflation using only words already present. Same known limit.",
        ("scope", "known-limit"),
    ),
    # --- lowercase evasion -------------------------------------------------- #
    Case(
        BACKEND,
        "Built payment rails at stripe before joining Zerodha.",
        True,
        "stripe",
        "Written expecting a miss -- lowercase defeats the proper-noun rule, which "
        "keys on capitalisation. It is caught, but by the *skill* check: Stripe is "
        "a taxonomy entry, and the matcher is case-insensitive. Worth recording "
        "because the case passes for a reason other than the one it was testing, "
        "and the next case is the one that actually isolates the gap.",
        ("organization", "evasion"),
    ),
    Case(
        DATA,
        "Built reporting pipelines at flipkart for two years.",
        True,
        "flipkart",
        "The lowercase gap with the taxonomy removed: Flipkart is an employer, not "
        "a skill, so nothing in the taxonomy covers it and capitalisation is the "
        "only remaining signal. Expected to be missed, and kept so the limit is "
        "sized rather than assumed away.",
        ("organization", "known-limit"),
    ),
)


# --------------------------------------------------------------------------- #
# Honest rewrites -- every one of these must pass
# --------------------------------------------------------------------------- #

HONEST: tuple[Case, ...] = (
    Case(
        BACKEND,
        "Built and maintained payment processing services.",
        False,
        note="A plain rephrase, which is what the feature is for.",
    ),
    Case(
        BACKEND,
        "Improved settlement service performance substantially.",
        False,
        note="Qualitative by design: 'improved performance' asserts no new fact.",
    ),
    Case(
        BACKEND,
        "Cut p99 latency 35% on the settlement path.",
        False,
        note="The figure is the resume's own.",
    ),
    Case(
        BACKEND,
        "Mentored 3 junior engineers on the payments team.",
        False,
        note="'three' written as a digit is a notation change, not a claim.",
    ),
    Case(
        BACKEND,
        "Senior Backend Engineer at Zerodha, owning the payments platform.",
        False,
        note="Restates a real employer and a real title.",
    ),
    Case(
        BACKEND,
        "Owned Zerodha's settlement service end to end.",
        False,
        note="Possessive of a real employer.",
    ),
    Case(
        BACKEND,
        "Migrated the ledger from MySQL to PostgreSQL without downtime.",
        False,
        note="Both databases are named in the resume.",
    ),
    Case(
        BACKEND,
        "Delivered payment services handling 12,000 transactions daily.",
        False,
        note="The real figure, reworded around it.",
    ),
    Case(
        DATA,
        "Produced daily sales reporting for the category team.",
        False,
    ),
    Case(
        DATA,
        "Replaced a manual spreadsheet process with an automated pipeline.",
        False,
    ),
    Case(
        DATA,
        "Wrote SQL against the warehouse to answer merchandising questions.",
        False,
    ),
    Case(
        DATA,
        "Data Analyst at Reliance Retail since June 2021.",
        False,
        note="Employer and start date exactly as written.",
    ),
    Case(
        FRONTEND,
        "Rebuilt the billing settings screen in React.",
        False,
    ),
    Case(
        FRONTEND,
        "Reduced the main bundle from 900KB to 410KB.",
        False,
        note="Both endpoints are the resume's own.",
    ),
    Case(
        FRONTEND,
        "Improved accessibility across the onboarding flow.",
        False,
    ),
    Case(
        FRONTEND,
        "Frontend engineer at Freshworks working in TypeScript and React.",
        False,
    ),
    Case(
        BACKEND,
        "Engineered resilient payment infrastructure in Python and Django.",
        False,
        note="Stronger verb, same facts. The suggestion the feature should produce.",
    ),
    Case(
        BACKEND,
        "Containerised the settlement service with Docker.",
        False,
        note="A technical opening verb -- the false-positive mode the opener list "
        "guards against.",
    ),
    Case(
        DATA,
        "Automated reporting that previously took two days each week.",
        False,
        note="'two days' is in the resume.",
    ),
    Case(
        FRONTEND,
        "Shipped accessibility improvements across onboarding.",
        False,
    ),
)


ALL_CASES: tuple[Case, ...] = FABRICATED + HONEST
