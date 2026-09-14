"""Reject any rewrite that says something the resume does not (ADR-012 step 4).

The most important safety component in the system. An LLM asked to "improve this
resume for this job" will cheerfully add an AWS certification the candidate does
not hold, and that is career damage rather than a bug report: the cost lands in
an interview, on the user, months later, with no way to trace it back here.

**This is deterministic code, not a model.** Using an LLM to check an LLM shares
the failure mode being checked for -- a model that invents a credential is not
reliably the same model that notices it did. Nothing here calls anything.

## What it does

Set difference over entities. Every number, year, skill, proper noun and
credential in the *suggested* text must already appear in the *source* resume.
Anything in the output and not in the input is a fabrication and rejects the
whole suggestion.

    "improved performance"            -> allowed, no new claim
    "improved performance by 40%"     -> rejected unless 40% is in the source

## It deliberately over-rejects

A false negative and a false positive are not comparable here. Rejecting a good
suggestion costs the user one phrasing they will never know they missed.
Accepting a fabricated one costs them their credibility in an interview. So
every ambiguous case resolves to rejection, and the tuning target is 100%
fabrication recall rather than any balance of the two.

That is also why this rejects on *entities* rather than on meaning. Judging
whether a rewrite changed the meaning is exactly the open-ended language problem
an LLM would be needed for, and would put a model back in the safety path.

## Purity

No database, no network, no model. The skill matcher is injected, so the whole
module is exhaustively unit-testable against literal strings, which is what lets
the adversarial dataset in `ml/datasets/fabrication/` cover it directly.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.services.resume.skill_extraction import SkillMatcher


class EntityKind(StrEnum):
    """What sort of claim was invented. Reported so a rejection is explicable."""

    NUMBER = "NUMBER"
    DATE = "DATE"
    SKILL = "SKILL"
    ORGANIZATION = "ORGANIZATION"
    CREDENTIAL = "CREDENTIAL"


@dataclass(frozen=True, slots=True)
class FabricatedEntity:
    kind: EntityKind
    #: The surface text as it appeared in the suggestion, for display.
    text: str
    #: Why this counts as invented, in a sentence a user could read.
    reason: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    fabricated: tuple[FabricatedEntity, ...]


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

#: Characters a word processor substitutes that would otherwise break matching.
#:
#: A resume pasted out of Word has curly quotes and en dashes; a model's output
#: has straight ones. Without folding these together, the same possessive would
#: read as a different token in each and every such word would look invented.
#:
#: Keyed by code point rather than by the characters themselves. Written
#: literally these are exactly the "ambiguous character" class a linter objects
#: to, and the objection is fair -- a stray en dash in source is nearly always a
#: typo. Here it is the subject matter, so it is named explicitly instead.
_PUNCTUATION_FOLD = {
    0x2018: "'",  # left single quote
    0x2019: "'",  # right single quote / apostrophe
    0x201C: '"',  # left double quote
    0x201D: '"',  # right double quote
    0x2013: "-",  # en dash
    0x2014: "-",  # em dash
    0x2212: "-",  # minus sign
    0x00D7: "x",  # multiplication sign
    0x00A0: " ",  # non-breaking space
}


def _fold(text: str) -> str:
    """Normalise to a form where equal claims compare equal.

    NFKC first, so a ligature or a full-width digit becomes its plain
    equivalent -- those are a real way for text to differ invisibly.
    """
    return unicodedata.normalize("NFKC", text).translate(_PUNCTUATION_FOLD)


def _haystack(text: str) -> str:
    """The source, flattened for substring tests.

    Punctuation becomes spaces rather than vanishing, so "React,Node" does not
    fuse into one token that matches neither name.
    """
    folded = _fold(text).casefold()
    return " " + re.sub(r"[^\w%$€£₹+#.]+", " ", folded).strip() + " "


def _contains_word(haystack: str, word: str) -> bool:
    """Whole-token membership.

    Substring matching would let "Java" pass because the source says
    "JavaScript", which is precisely the sort of near-miss that should reject.
    """
    return f" {word.casefold()} " in haystack


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #

_SCALES = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
}

#: Written-out numbers, so "three engineers" and "3 engineers" are one claim.
#:
#: Without this a rephrase that merely changes the notation would be rejected as
#: invention, which is a false positive with no safety value at all.
_NUMBER_WORDS = {
    "zero": 0.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "fifteen": 15.0,
    "twenty": 20.0,
    "thirty": 30.0,
    "forty": 40.0,
    "fifty": 50.0,
    "sixty": 60.0,
    "seventy": 70.0,
    "eighty": 80.0,
    "ninety": 90.0,
    "hundred": 100.0,
}

_NUMBER = re.compile(
    r"""
    (?P<currency>[$€£₹])?\s*
    (?P<value>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s*
    (?P<suffix>
        %|percent(?:age)?\ points?|percent(?:age)?
        |(?:k|m|mm|b|bn)(?![\w])
        |thousand|million|billion
        |x(?![\w])
    )?
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Quantity:
    value: float
    #: "%", "x", a currency symbol, or None for a bare count.
    #:
    #: Carried because the unit is part of the claim. "40 people" and "40%" are
    #: different assertions, and treating the shared 40 as a match would let a
    #: rewrite invent a percentage out of a headcount.
    unit: str | None

    def display(self) -> str:
        number = f"{self.value:,.10g}"
        if self.unit == "%":
            return f"{number}%"
        if self.unit == "x":
            return f"{number}x"
        if self.unit:
            return f"{self.unit}{number}"
        return number


def _quantities(text: str) -> list[_Quantity]:
    folded = _fold(text)
    found: list[_Quantity] = []

    for match in _NUMBER.finditer(folded):
        raw = match.group("value").replace(",", "")
        try:
            value = float(raw)
        except ValueError:  # pragma: no cover - the pattern only matches numerals
            continue

        suffix = (match.group("suffix") or "").strip().casefold()
        currency = match.group("currency")

        unit: str | None = currency
        if suffix.startswith("percent") or suffix == "%":
            unit = "%"
        elif suffix == "x":
            unit = "x"
        elif suffix in _SCALES:
            value *= _SCALES[suffix]

        found.append(_Quantity(value=value, unit=unit))

    # Written numbers carry no unit and no scale; "three" is a count.
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"(?<![\w]){word}(?![\w])", folded, re.IGNORECASE):
            found.append(_Quantity(value=value, unit=None))

    return found


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_MONTH = re.compile(rf"(?<![\w])({_MONTHS})(?![\w])", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Proper nouns and credentials
# --------------------------------------------------------------------------- #

#: Capitalised words that are not proper nouns.
#:
#: Only needed for tokens that are capitalised *mid-sentence*, since a
#: sentence-initial capital is already ignored. "I" and the weekday and month
#: names are the realistic cases.
_NOT_PROPER = {
    "i",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "english",
    "agile",
    "scrum",
    "kanban",
}

#: Words that mark the phrase around them as a credential claim.
_CREDENTIAL_WORDS = re.compile(
    r"(?<![\w])(certified|certification|certificate|licensed|accredited|chartered"
    r"|bachelor|master|mba|phd|doctorate|degree|diploma)(?![\w])",
    re.IGNORECASE,
)

#: Well-known credential acronyms, which are the highest-cost fabrications and
#: are short enough to be missed by a general proper-noun rule.
_CREDENTIAL_ACRONYMS = {
    "pmp",
    "cissp",
    "ccna",
    "ccnp",
    "cka",
    "ckad",
    "cfa",
    "cpa",
    "itil",
    "prince2",
    "csm",
    "pmi",
    "comptia",
    "oscp",
    "ceh",
}

#: Ordinary English words that can open a sentence in resume prose.
#:
#: Needed because a capital at the start of a sentence says nothing about what
#: the word is: "Delivered the backend" and "Stripe was my employer" look
#: identical to a capitalisation rule. Skipping sentence-initial words entirely
#: -- the first version of this -- let a fabricated employer through whenever it
#: happened to land first, which is exactly the claim that must never pass.
#:
#: So the rule inverts: a sentence-initial capital is checked like any other
#: token *unless* it is recognisable English. The list is deliberately weighted
#: to resume verbs, because that is what these sentences actually start with. A
#: word missing from it is over-rejected, which costs one suggestion; a proper
#: noun wrongly admitted costs the user an interview.
#:
#: Kept as a wrapped block rather than a list of quoted strings: at this length
#: the quotes and commas are most of the characters on the page, and a word list
#: is reviewed by reading it.
_SENTENCE_OPENER_WORDS = """
    a an the and or but if as at by for from in into of on to with within across over
    this that these those there here it its their his her our your my
    i we they he she you
    achieved acted adapted added addressed administered advanced advised advocated
    analysed analyzed answered applied appointed approved architected arranged
    assembled assessed assigned assisted attained audited authored automated awarded
    balanced began boosted broadened budgeted built
    backfilled backported benchmarked bootstrapped bridged
    calculated captured carried catalogued centralised centralized chaired championed
    containerised containerized decoupled deduplicated dockerised dockerized
    hardened instrumented parallelised parallelized productionised productionized
    profiled provisioned rearchitected rearchitectured scaffolded sharded
    stubbed templated versioned
    changed clarified classified coached collaborated collected combined communicated
    compared compiled completed composed computed conceived conducted configured
    connected consolidated constructed consulted contributed controlled converted
    coordinated corrected created cultivated curated customised customized cut
    debugged decreased defined delegated delivered demonstrated deployed designed
    detected determined developed devised diagnosed directed discovered dispatched
    displayed distributed diversified documented doubled drafted drove
    earned edited educated eliminated enabled encouraged enforced engineered enhanced
    enlarged ensured established estimated evaluated examined exceeded executed
    expanded expedited explained explored extended extracted
    facilitated finalised finalized focused forecast formed formulated fostered
    found founded fulfilled
    gained gathered generated grew guided
    handled headed helped hired hosted
    identified implemented improved increased influenced informed initiated innovated
    inspected installed instituted instructed integrated interpreted interviewed
    introduced invented investigated involved issued
    joined judged justified
    launched led lectured leveraged liaised listed logged
    maintained managed mapped marketed mastered maximised maximized measured mediated
    mentored merged migrated minimised minimized modelled modeled moderated modernised
    modernized modified monitored motivated moved
    navigated negotiated
    observed obtained offered operated optimised optimized orchestrated organised
    organized oriented originated outlined overhauled oversaw owned
    partnered performed pioneered planned prepared presented presided prevented
    prioritised prioritized processed produced programmed promoted proposed proved
    provided published purchased pursued
    qualified quantified queried
    raised ran ranked rated reached realised realized rebuilt received recommended
    reconciled recorded recruited redesigned reduced refactored refined regulated
    rehabilitated reinforced rejected related released remodelled removed rendered
    reorganised reorganized repaired replaced reported represented researched
    resolved responded restored restructured retained retrieved reviewed revised
    revitalised revitalized rewrote
    saved scaled scheduled screened secured selected served serviced set shaped
    shared shipped simplified simulated solved sourced spearheaded specified
    spoke standardised standardized started steered stimulated streamlined
    strengthened structured studied submitted succeeded suggested summarised
    summarized supervised supplied supported surveyed sustained synthesised
    synthesized systematised systematized
    tabulated tailored targeted taught tested tightened tracked trained transcribed
    transferred transformed translated travelled treated trimmed tripled troubleshot
    tutored
    uncovered underwent undertook unified updated upgraded used utilised utilized
    validated valued verified visualised visualized volunteered
    widened won worked wrote
"""

_SENTENCE_OPENERS = frozenset(_SENTENCE_OPENER_WORDS.split())

_SENTENCE_BREAK = re.compile(r"[.!?:;\n]\s*$")
#: Internal dots and pluses are kept -- Node.js, .NET and C++ are real names --
#: but a token never ends in punctuation, or "Java." fails to match a source
#: that says "Java".
_TOKEN = re.compile(r"[A-Za-z][\w&.+#'-]*")
_TRAILING_PUNCTUATION = re.compile(r"[.'\-&+#]+$")


def _proper_tokens(text: str) -> list[str]:
    """Capitalised tokens that look like names rather than ordinary words.

    A rewrite of existing content has no legitimate reason to introduce a proper
    noun the resume never mentions, so an unknown one is strong evidence of
    invention.
    """
    folded = _fold(text)
    found: list[str] = []

    for match in _TOKEN.finditer(folded):
        token = _TRAILING_PUNCTUATION.sub("", match.group(0))
        if not token:
            continue

        before = folded[: match.start()]

        # A letter hanging off a number is a unit, not a name: the "M" of "$2M"
        # and the "x" of "10x" are already accounted for as quantities, and
        # reading them as organisations rejected honest rewrites.
        if before[-1:].isdigit():
            continue

        starts_sentence = not before.strip() or bool(_SENTENCE_BREAK.search(before))
        is_capitalised = token[0].isupper()
        # An all-caps acronym is a proper noun wherever it sits, including at the
        # start of a sentence -- "AWS Certified..." is the canonical fabrication
        # and must not be skipped for being first.
        is_acronym = len(token) > 1 and token.isupper()

        if not is_capitalised:
            continue
        if token.casefold() in _NOT_PROPER:
            continue
        # Sentence-initial words are checked too, but only once recognisable
        # English is excluded -- see `_SENTENCE_OPENERS` for why skipping them
        # wholesale was a hole rather than a simplification.
        if starts_sentence and not is_acronym and token.casefold() in _SENTENCE_OPENERS:
            continue

        found.append(token)

    return found


def _classify(token: str, suggested: str) -> EntityKind:
    """Credential or plain organisation, for the rejection message."""
    if token.casefold() in _CREDENTIAL_ACRONYMS:
        return EntityKind.CREDENTIAL
    if _CREDENTIAL_WORDS.search(suggested):
        return EntityKind.CREDENTIAL
    return EntityKind.ORGANIZATION


# --------------------------------------------------------------------------- #
# The validator
# --------------------------------------------------------------------------- #


def validate_suggestion(
    *,
    suggested: str,
    source: str,
    matcher: SkillMatcher | None = None,
) -> ValidationResult:
    """Reject `suggested` if it claims anything `source` does not.

    `source` is the **whole resume**, not just the span being rewritten. A
    rephrase of one bullet may legitimately pull a detail from the summary or the
    skills block, and validating against the span alone would reject it for
    using the candidate's own words from two lines up.

    `matcher` is optional so the module stays usable without a taxonomy; without
    it, skills are still caught by the proper-noun and token rules whenever they
    are capitalised, which taxonomy skills almost always are.
    """
    haystack = _haystack(source)
    fabricated: list[FabricatedEntity] = []
    seen: set[tuple[EntityKind, str]] = set()

    def record(kind: EntityKind, text: str, reason: str) -> None:
        key = (kind, text.casefold())
        if key not in seen:
            seen.add(key)
            fabricated.append(FabricatedEntity(kind=kind, text=text, reason=reason))

    # --- numbers ---------------------------------------------------------- #
    # Compared as (value, unit) pairs rather than as text, so "2 million" in the
    # source covers "$2M" in the rewrite, while "40 people" does not cover "40%".
    source_quantities = {(q.value, q.unit) for q in _quantities(source)}
    for quantity in _quantities(suggested):
        if (quantity.value, quantity.unit) not in source_quantities:
            record(
                EntityKind.NUMBER,
                quantity.display(),
                f"{quantity.display()} does not appear anywhere in your resume.",
            )

    # --- dates ------------------------------------------------------------ #
    source_years = set(_YEAR.findall(_fold(source)))
    for year in _YEAR.findall(_fold(suggested)):
        if year not in source_years:
            record(EntityKind.DATE, year, f"Your resume does not mention {year}.")

    source_months = {m.casefold() for m in _MONTH.findall(_fold(source))}
    for month in _MONTH.findall(_fold(suggested)):
        if month.casefold() not in source_months:
            record(EntityKind.DATE, month, f"Your resume does not mention {month}.")

    # --- skills ----------------------------------------------------------- #
    if matcher is not None:
        held = {span.canonical_name for span in matcher.find_spans(source)}
        for span in matcher.find_spans(suggested):
            if span.canonical_name not in held:
                record(
                    EntityKind.SKILL,
                    span.matched_text,
                    f"{span.canonical_name} is not a skill your resume claims.",
                )

    # --- proper nouns and credentials ------------------------------------- #
    for token in _proper_tokens(suggested):
        if _contains_word(haystack, token):
            continue
        # A trailing possessive or plural is a grammatical form, not a different
        # organisation: "Google's" must match a source that says "Google".
        stem = re.sub(r"(?:'s|s)$", "", token)
        if stem and stem != token and _contains_word(haystack, stem):
            continue

        kind = _classify(token, suggested)
        reason = (
            f"{token} is not named anywhere in your resume."
            if kind is EntityKind.ORGANIZATION
            else f"{token} is a credential your resume does not claim."
        )
        record(kind, token, reason)

    return ValidationResult(passed=not fabricated, fabricated=tuple(fabricated))
