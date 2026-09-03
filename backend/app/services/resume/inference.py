"""Skill inference from activity descriptions.

Gazetteer matching finds skills a resume **names**. This module finds skills a
resume **demonstrates**: "built responsive user interfaces" is evidence of
Responsive Web Design even though that phrase never appears.

**These are suggestions, never claims.** ADR-012 forbids the system inventing
anything about a candidate, and that rule applies to extraction as much as to
generation. An inferred skill is our interpretation of their words, not
something they said — and if a profile asserts "U-Net" and the candidate cannot
discuss it in an interview, we have done them real harm.

So inferences are structurally separated from matches:

* they are capped below the acceptance threshold and can never be written to a
  profile automatically;
* every one carries the **exact sentence it came from**, so the user judges the
  reasoning rather than trusting a label;
* the user confirms or discards each one, and confirming marks it user-verified
  like any hand-added skill.

The rules are deliberately narrow. A rule that fires on "database" alone would
suggest Database Design for anyone who has ever mentioned one; requiring
"design", "schema" or "model" nearby is what keeps a suggestion worth reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.resume.sections import SectionType

# Ceiling for any inference. REVIEW_THRESHOLD is 0.60, so nothing inferred can
# ever reach the profile without a human saying yes.
MAX_INFERENCE_CONFIDENCE = 0.55


@dataclass(frozen=True, slots=True)
class InferenceRule:
    """Maps evidence in prose to a skill.

    `patterns` are alternatives; any one firing is enough. `confidence` reflects
    how directly the phrasing implies the skill — "built REST APIs" is close to
    a statement of the skill, while "worked with data" barely implies anything.
    """

    skill: str
    patterns: tuple[str, ...]
    confidence: float = 0.50

    def compiled(self) -> list[re.Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in self.patterns]


# Sections whose prose describes what the candidate actually did. Inference is
# not run over SKILLS, because that section is an explicit list — anything there
# is matched directly and inferring from it would double-count.
_EVIDENCE_SECTIONS = frozenset(
    {
        SectionType.EXPERIENCE,
        SectionType.PROJECTS,
        SectionType.SUMMARY,
        SectionType.ACHIEVEMENTS,
        SectionType.UNKNOWN,
    }
)


INFERENCE_RULES: tuple[InferenceRule, ...] = (
    # ---------------------------------------------------------------- web
    InferenceRule(
        "Responsive Web Design",
        (
            r"responsive\s+(user\s+)?(interface|ui|design|layout|web|page|site)",
            r"mobile[- ]responsive",
            r"across\s+(all\s+)?(devices|screen sizes)",
        ),
        confidence=0.52,
    ),
    InferenceRule(
        "Frontend Development",
        (
            r"\b(built|developed|created|designed|implemented)\b[^.]{0,60}\b"
            r"(user\s+interface|ui|front[- ]?end|web\s+page|component)",
        ),
        confidence=0.50,
    ),
    InferenceRule(
        "Backend Development",
        (
            r"\bserver[- ]side\b",
            r"\bback[- ]?end\b",
            r"\b(built|developed|implemented)\b[^.]{0,40}\b(api|endpoint|service)s?\b",
        ),
        confidence=0.52,
    ),
    InferenceRule(
        "API Development",
        (
            r"\b(built|developed|created|designed|implemented|consumed)\b[^.]{0,40}"
            r"\b(rest(ful)?\s+api|api\s+endpoint|apis?)\b",
        ),
        confidence=0.52,
    ),
    InferenceRule(
        "Authentication",
        (
            r"\b(auth(entication)?|login|sign[- ]?in|sign[- ]?up)\b[^.]{0,40}"
            r"\b(implement|integrat|built|added|flow|system)",
            r"\b(implement|integrat|built|added)\w*\b[^.]{0,40}\bauth(entication)?\b",
        ),
        confidence=0.50,
    ),
    InferenceRule(
        "Deployment",
        (r"\bdeploy(ed|ment|ing)\b",),
        confidence=0.48,
    ),
    InferenceRule(
        "Performance Optimization",
        (
            r"\b(performance|load\s+time|latency|speed)\b[^.]{0,40}\b(optimi|improv|reduc|tun)",
            r"\boptimi[sz]\w*\b[^.]{0,40}\b(performance|speed|load|query|render)",
        ),
        confidence=0.52,
    ),
    InferenceRule(
        "Debugging",
        (
            r"\bdebug(ged|ging)?\b",
            r"\btroubleshoot(ing|ed)?\b",
            r"\b(fixed|resolved)\b[^.]{0,30}\bbugs?\b",
        ),
        confidence=0.50,
    ),
    InferenceRule(
        "Software Testing",
        (
            r"\b(wrote|written|added|implemented|performed)\b[^.]{0,40}\btest(s|ing|ed)?\b",
            r"\b(unit|integration|end[- ]to[- ]end)\s+test",
        ),
        confidence=0.52,
    ),
    # ---------------------------------------------------------------- data
    InferenceRule(
        "Database Design",
        (
            r"\bdatabase\b[^.]{0,40}\b(design|schema|model)",
            r"\b(design|schema|model)\w*\b[^.]{0,40}\bdatabase\b",
            r"\bschema\s+design\b",
        ),
        confidence=0.52,
    ),
    InferenceRule(
        "Database Management",
        (r"\bdatabase\b[^.]{0,30}\b(manage|maintain|administer)",),
        confidence=0.48,
    ),
    InferenceRule(
        "Data Preprocessing",
        (
            r"\b(pre[- ]?process(ed|ing)?|clean(ed|ing)|normali[sz]ed?)\b"
            r"[^.]{0,40}\b(data|dataset|image)",
            r"\b(data|dataset|image)s?\b[^.]{0,30}\b(pre[- ]?process|clean|augment)",
        ),
        confidence=0.52,
    ),
    InferenceRule(
        "Data Processing",
        (r"\bprocess(ed|ing)\b[^.]{0,30}\b(data|dataset|record|file)s?\b",),
        confidence=0.48,
    ),
    # ---------------------------------------------------------------- ml
    InferenceRule(
        "Model Training",
        (
            r"\btrain(ed|ing)\b[^.]{0,40}\b(model|network|cnn|classifier|architecture)",
            r"\b(model|network|classifier)s?\b[^.]{0,20}\btrain(ed|ing)\b",
        ),
        confidence=0.54,
    ),
    InferenceRule(
        "Model Validation",
        (
            r"\b(validat|evaluat)\w*\b[^.]{0,40}\b(model|performance|accuracy|result)",
            r"\b(accuracy|precision|recall|f1|auc|dice)\b[^.]{0,30}\b(of|score|achiev|report)",
        ),
        confidence=0.50,
    ),
    InferenceRule(
        "Image Segmentation",
        (
            r"\bsegment(ation|ed|ing)?\b[^.]{0,30}\b(image|scan|mri|ct|retina|lesion|tumou?r)",
            r"\b(image|medical|semantic)\s+segmentation\b",
        ),
        confidence=0.54,
    ),
    InferenceRule(
        "Computer Vision",
        (
            r"\b(image|visual|video)\b[^.]{0,40}\b(segmentation|classification|detection|recognition)",
            r"\bcomputer\s+vision\b",
        ),
        confidence=0.52,
    ),
    # ---------------------------------------------------------------- ways of working
    InferenceRule(
        "Teamwork",
        (r"\bcollaborat(ed|ing|ion)\b", r"\bteam\s+of\s+\d+", r"\bworked\s+with\s+a\s+team\b"),
        confidence=0.46,
    ),
    InferenceRule(
        "Mentoring",
        (r"\b(mentor|mentored|coached|guided|trained)\b[^.]{0,30}\b(junior|intern|team|student)",),
        confidence=0.48,
    ),
)


@dataclass(frozen=True, slots=True)
class InferredSkill:
    """A suggestion, with the sentence that produced it."""

    canonical_name: str
    confidence: float
    evidence: str
    section: SectionType

    @property
    def is_suggestion(self) -> bool:
        # Always true. Present so calling code reads as a statement of intent
        # rather than relying on a threshold comparison elsewhere.
        return self.confidence <= MAX_INFERENCE_CONFIDENCE


def _sentences(text: str) -> list[str]:
    """Split prose into sentence-ish units.

    Bullet points rarely end in a full stop, so newlines and bullet markers are
    boundaries too. Evidence is quoted back to the user, so a unit that ran
    across three unrelated bullets would be unreadable.
    """
    parts = re.split(r"(?<=[.!?])\s+|\n+|•", text)
    return [p.strip() for p in parts if p.strip()]


def infer_skills(
    *,
    sections: dict[SectionType, str],
    already_found: set[str],
) -> list[InferredSkill]:
    """Suggest skills demonstrated by the prose but never named.

    `already_found` is excluded: a skill the resume states outright needs no
    inference, and offering to "add" something already on the profile is noise.
    """
    compiled = [(rule, rule.compiled()) for rule in INFERENCE_RULES]
    best: dict[str, InferredSkill] = {}

    for section_type, text in sections.items():
        if section_type not in _EVIDENCE_SECTIONS:
            continue

        for sentence in _sentences(text):
            for rule, patterns in compiled:
                if rule.skill in already_found:
                    continue
                if not any(pattern.search(sentence) for pattern in patterns):
                    continue

                confidence = min(rule.confidence, MAX_INFERENCE_CONFIDENCE)
                existing = best.get(rule.skill)
                if existing is not None and existing.confidence >= confidence:
                    continue

                best[rule.skill] = InferredSkill(
                    canonical_name=rule.skill,
                    confidence=round(confidence, 3),
                    # Trimmed: this is shown verbatim in the UI, and a wall of
                    # text defeats the point of quoting the evidence.
                    evidence=sentence[:240],
                    section=section_type,
                )

    return sorted(best.values(), key=lambda s: (-s.confidence, s.canonical_name))
