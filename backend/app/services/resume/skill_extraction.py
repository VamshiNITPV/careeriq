"""Skill extraction (ml.md section 2.3).

This is the **baseline** the evaluation-first workflow calls for (ml.md section
9): gazetteer matching against the taxonomy with alias resolution and
section-aware confidence. A spaCy pipeline is the candidate replacement, and it
ships only if it beats these numbers on the labelled set. Building the fancier
version first would mean never learning whether it earned its cost.

Precision is weighted above recall throughout (ml.md section 2.4). A falsely
extracted skill lands in a user's profile, inflates their match scores, and may
be asked about in an interview. A missed skill is one click to add.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.data.skill_taxonomy import normalize_skill_text
from app.services.resume.sections import SectionType

# Confidence by where the mention was found. A token inside an explicit skills
# list is a claim; the same token in prose may be incidental — "we migrated off
# MongoDB" is not a MongoDB skill.
_SECTION_CONFIDENCE: dict[SectionType, float] = {
    SectionType.SKILLS: 0.95,
    SectionType.PROJECTS: 0.80,
    SectionType.EXPERIENCE: 0.78,
    SectionType.CERTIFICATIONS: 0.75,
    SectionType.SUMMARY: 0.65,
    SectionType.EDUCATION: 0.60,
    SectionType.UNKNOWN: 0.55,
}
_DEFAULT_CONFIDENCE = 0.55

# Below this a skill is surfaced for review rather than written to the profile
# (US-2.3 AC3).
REVIEW_THRESHOLD = 0.60

# Repeated mentions across sections are weak corroboration, capped so a term
# appearing in a header and a footer cannot reach certainty on its own.
_REPEAT_BONUS = 0.03
_MAX_CONFIDENCE = 0.99


@dataclass(frozen=True, slots=True)
class SkillSpan:
    """A raw taxonomy match: what was found, and where. Nothing interpreted."""

    canonical_name: str
    matched_text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SkillMention:
    """One skill found in the text, with where and how confidently."""

    canonical_name: str
    matched_text: str
    section: SectionType
    confidence: float
    start: int
    end: int

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_THRESHOLD


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """A skill after merging every mention of it."""

    canonical_name: str
    confidence: float
    mention_count: int
    best_section: SectionType
    matched_texts: tuple[str, ...]
    first_span: tuple[int, int]

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_THRESHOLD


class SkillMatcher:
    """Matches taxonomy entries against text.

    Built once from the taxonomy and reused across documents. Patterns are
    compiled up front because building them per resume dominates the runtime of
    an otherwise trivial scan.
    """

    def __init__(self, entries: dict[str, list[str]]) -> None:
        """`entries` maps canonical name -> normalised lookup forms."""
        self._patterns: list[tuple[str, re.Pattern[str]]] = []

        for canonical, forms in entries.items():
            for form in forms:
                if form:
                    self._patterns.append((canonical, self._compile(form)))

        # Longest surface form first. Without this, "react" inside "react
        # native" matches first and the more specific skill is lost.
        self._patterns.sort(key=lambda pair: len(pair[1].pattern), reverse=True)

    @staticmethod
    def _compile(form: str) -> re.Pattern[str]:
        r"""Compile a lookup form into a boundary-anchored pattern.

        `\b` cannot be used directly: it is defined against `\w`, so `\bc\+\+\b`
        never matches because `+` is already a non-word character and there is no
        boundary after it. C++, C#, .NET and Node.js are all real skill names, so
        the boundaries are expressed as "not adjacent to an identifier
        character" instead, which behaves correctly for both.
        """
        escaped = re.escape(form).replace(r"\ ", r"[\s\-_/]+")
        return re.compile(rf"(?<![\w+#.]){escaped}(?![\w+#])", re.IGNORECASE)

    def find_spans(self, text: str) -> list[SkillSpan]:
        """Scan text for taxonomy entries. No confidence, no section.

        The matching engine on its own, so job-description parsing can reuse it
        without inheriting the resume's section vocabulary. Resume sections and
        job sections mean different things — SKILLS versus REQUIREMENTS — and
        the confidence each implies is a judgement about that document type, not
        about the scan.
        """
        spans: list[SkillSpan] = []
        # Character offsets already claimed, so a longer name that matched first
        # prevents a shorter one from also matching inside it.
        claimed: list[tuple[int, int]] = []

        for canonical, pattern in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < c_end and end > c_start for c_start, c_end in claimed):
                    continue
                claimed.append((start, end))
                spans.append(SkillSpan(canonical, match.group(0), start, end))

        return spans

    def find(self, text: str, section: SectionType) -> list[SkillMention]:
        confidence = _SECTION_CONFIDENCE.get(section, _DEFAULT_CONFIDENCE)
        return [
            SkillMention(
                canonical_name=span.canonical_name,
                matched_text=span.matched_text,
                section=section,
                confidence=confidence,
                start=span.start,
                end=span.end,
            )
            for span in self.find_spans(text)
        ]


def build_matcher(taxonomy: dict[str, list[str]]) -> SkillMatcher:
    return SkillMatcher(taxonomy)


def extract_skills(
    *,
    matcher: SkillMatcher,
    sections: dict[SectionType, str],
    full_text: str,
) -> list[SkillCandidate]:
    """Find skills across a resume and merge mentions per skill.

    Falls back to scanning the whole document when no sections were detected, so
    an unusually formatted resume still yields skills — at the lower confidence
    that an unstructured match deserves.
    """
    mentions: list[SkillMention] = []

    if sections:
        for section_type, text in sections.items():
            mentions.extend(matcher.find(text, section_type))
    else:
        mentions.extend(matcher.find(full_text, SectionType.UNKNOWN))

    grouped: dict[str, list[SkillMention]] = {}
    for mention in mentions:
        grouped.setdefault(mention.canonical_name, []).append(mention)

    candidates: list[SkillCandidate] = []
    for canonical, group in grouped.items():
        # The strongest section wins rather than the average: a skill listed in
        # the skills section is a claim, and an additional passing mention in
        # prose should not dilute that.
        best = max(group, key=lambda m: m.confidence)
        confidence = min(_MAX_CONFIDENCE, best.confidence + _REPEAT_BONUS * (len(group) - 1))
        candidates.append(
            SkillCandidate(
                canonical_name=canonical,
                confidence=round(confidence, 3),
                mention_count=len(group),
                best_section=best.section,
                matched_texts=tuple(dict.fromkeys(m.matched_text for m in group)),
                first_span=(best.start, best.end),
            )
        )

    return sorted(candidates, key=lambda c: (-c.confidence, c.canonical_name))


# Labels that introduce a list rather than being a skill themselves. A resume
# writes "Programming Languages: C, C++, Python", and without stripping the
# label the first value is reported as "programming languages c".
#
# The separator class accepts – (en dash) as well as a colon and hyphen,
# because "Tech Stack - Docker" is written with all three in the wild. It is an
# escape rather than the literal character: an en dash is visually
# indistinguishable from a hyphen in source, so the escape is what makes the
# intent readable.
_CATEGORY_LABEL = re.compile(
    r"""^[\s•\-*>•●▪]*(
        programming\s+languages? | languages? | web\s+development\s+tools? |
        development\s+tools? | developer\s+tools? | technical\s+skills? |
        frontend | front-end | backend | back-end | full\s*stack |
        databases? | frameworks?\s*(and\s*libraries)? | libraries |
        tools?(\s*and\s*technologies)? | technologies | tech\s+stack |
        cloud(\s*(and|&)\s*tools?)? | devops | platforms? |
        office\s+tools? | productivity\s+tools? | operating\s+systems? |
        coursework | relevant\s+coursework | subjects? | core\s+subjects? |
        soft\s+skills? | other | miscellaneous | misc |
        coding\s+profiles? | certifications? | concepts?
    )\s*[:\-–]\s*""",
    re.IGNORECASE | re.VERBOSE,
)


def _is_bare_category_label(term: str) -> bool:
    """True when the term is only a heading, with no values after it.

    "Coding Profiles" alone on a line has no separator, so label stripping
    leaves it untouched and it would otherwise be reported as an unrecognised
    skill. Matching against the same vocabulary keeps the two definitions from
    drifting apart.
    """
    return _CATEGORY_LABEL.match(f"{term}: x") is not None


def strip_category_label(line: str) -> str:
    """Remove a leading "Category:" prefix from a skills line.

    Applied per line before splitting, because the label attaches only to the
    first value on its line.

    The pattern tolerates leading bullets and indentation. Anchoring on `^`
    alone failed on every real resume, because extracted lines arrive as
    "• Programming Languages: C, C++" — the bullet meant the label was never
    recognised and stayed fused to the first value.
    """
    return _CATEGORY_LABEL.sub("", line, count=1)


def parse_skills_list(text: str) -> list[str]:
    """Split an explicit skills block into individual terms.

    Used to catch entries the taxonomy does not know yet. These are reported for
    review, never written straight to a profile — auto-creating a skill for
    every comma-separated fragment would fill the taxonomy with parser noise.

    Splitting on ':' matters as much as on ',': the overwhelmingly common resume
    layout is "Databases: MySQL, MongoDB", and without it the first value of
    every line comes back glued to its heading.
    """
    terms: list[str] = []

    for line in text.splitlines():
        # Strip the label first, then split. Doing it after would leave the
        # label fused to the first value.
        without_label = strip_category_label(line)

        for part in re.split(r"[,;|•/]|\s{3,}", without_label):
            cleaned = normalize_skill_text(part.strip(" .-:\t"))

            # Single characters are allowed: C and R are real languages, and a
            # minimum of two silently discarded them. The alphanumeric check
            # still rejects leftover punctuation from a split, and six words
            # excludes sentences that happen to sit in a skills block.
            if (
                1 <= len(cleaned) <= 60
                and len(cleaned.split()) <= 6
                and any(ch.isalnum() for ch in cleaned)
                # A heading with no separator after it — "Coding Profiles" on
                # its own line — reaches here intact and would be reported as
                # an unrecognised skill.
                and not _is_bare_category_label(cleaned)
            ):
                terms.append(cleaned)

    return list(dict.fromkeys(terms))
