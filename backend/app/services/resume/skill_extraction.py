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

    def find(self, text: str, section: SectionType) -> list[SkillMention]:
        confidence = _SECTION_CONFIDENCE.get(section, _DEFAULT_CONFIDENCE)
        mentions: list[SkillMention] = []
        # Character offsets already claimed, so a longer name that matched first
        # prevents a shorter one from also matching inside it.
        claimed: list[tuple[int, int]] = []

        for canonical, pattern in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < c_end and end > c_start for c_start, c_end in claimed):
                    continue
                claimed.append((start, end))
                mentions.append(
                    SkillMention(
                        canonical_name=canonical,
                        matched_text=match.group(0),
                        section=section,
                        confidence=confidence,
                        start=start,
                        end=end,
                    )
                )

        return mentions


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


def parse_skills_list(text: str) -> list[str]:
    """Split an explicit skills block into individual terms.

    Used to catch entries the taxonomy does not know yet. These are reported for
    review, never written straight to a profile — auto-creating a skill for
    every comma-separated fragment would fill the taxonomy with parser noise.
    """
    parts = re.split(r"[,;|•\n]|\s{3,}", text)
    terms: list[str] = []
    for part in parts:
        cleaned = normalize_skill_text(part.strip(" .-:\t"))
        # Two characters excludes stray initials; six words excludes sentences
        # that happen to sit in a skills block.
        if 2 <= len(cleaned) <= 60 and len(cleaned.split()) <= 6:
            terms.append(cleaned)
    return list(dict.fromkeys(terms))
