"""Job description section detection.

A separate vocabulary from the resume's (`services/resume/sections.py`) because
the two document types share almost no headings. More importantly, a job's
sections carry a meaning a resume's do not: the split between "Requirements" and
"Nice to have" is the *only* signal distinguishing a REQUIRED skill from a
PREFERRED one, and that distinction is weighted in the ranking formula (ml.md
section 4.1).

Same shape as the resume detector — classify headings, take the text between
them — so the two can be read together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class JobSectionType(StrEnum):
    ABOUT = "ABOUT"
    RESPONSIBILITIES = "RESPONSIBILITIES"
    REQUIREMENTS = "REQUIREMENTS"
    NICE_TO_HAVE = "NICE_TO_HAVE"
    BENEFITS = "BENEFITS"
    UNKNOWN = "UNKNOWN"


# Ordered longest-phrase-first within each type, because "preferred
# qualifications" must win over "qualifications" — they map to different types
# and the shorter one would otherwise claim the heading.
_HEADINGS: tuple[tuple[JobSectionType, tuple[str, ...]], ...] = (
    (
        JobSectionType.NICE_TO_HAVE,
        (
            "preferred qualifications",
            "preferred skills",
            "preferred experience",
            "preferred candidate profile",
            "good-to-have skills",
            "good to have skills",
            "nice to have",
            "nice-to-have",
            "nice to haves",
            "bonus points",
            "bonus points if",
            "good to have",
            "desirable",
            "desired skills",
            "pluses",
            "it would be great if",
            "what will make you stand out",
            "extra credit",
        ),
    ),
    (
        JobSectionType.REQUIREMENTS,
        (
            "minimum qualifications",
            "basic qualifications",
            "required qualifications",
            "required skills",
            "requirements",
            "qualifications",
            "what we are looking for",
            "what we're looking for",
            "who you are",
            "skills and experience",
            "skills & experience",
            "experience required",
            "must have",
            "must haves",
            "you should have",
            "you have",
            "our ideal candidate",
            "candidate profile",
            "eligibility",
            # Also mined from real failures. Several of these are Naukri and
            # Indian-portal standards, which is why the gap was this wide on a
            # corpus of Indian postings.
            "job requirements",
            "candidate requirements",
            "skills required",
            "mandatory skills",
            "key skills",
            "technical skills",
            "desired candidate profile",
            "what you bring",
            "what you'll bring",
            "what you will bring",
            "about you",
            "ideal candidate",
            "knowledge skills and abilities",
            "you'll need",
            "you will need",
        ),
    ),
    (
        JobSectionType.RESPONSIBILITIES,
        (
            "key responsibilities",
            "roles and responsibilities",
            "job responsibilities",
            "responsibilities",
            "what you will do",
            "what you'll do",
            "what you will be doing",
            "your role",
            "the role",
            "duties",
            "day to day",
            "day-to-day",
            "in this role you will",
            "job description",
            "the opportunity",
            # Mined from the 131 postings this parser produced nothing for.
            # Folded form matters: `classify_heading` turns "&" into a space and
            # collapses, so "Role & Responsibilities" arrives as
            # "role responsibilities" — the ampersand spellings need their own
            # entries rather than relying on the "and" forms above.
            "role responsibilities",
            "roles responsibilities",
            "your responsibilities",
            "role overview",
            "about the role",
            "what is the role",
            "job summary",
            "position summary",
            "what you'll be working on",
            "what you will be working on",
            "essential duties",
            "key deliverables",
        ),
    ),
    (
        JobSectionType.BENEFITS,
        (
            "what we offer",
            "benefits and perks",
            "perks and benefits",
            "benefits",
            "perks",
            "compensation and benefits",
            "why join us",
            "why work with us",
            "what is in it for you",
            "what's in it for you",
        ),
    ),
    (
        JobSectionType.ABOUT,
        (
            "about the company",
            "about us",
            "about the team",
            "who we are",
            "company overview",
            "our story",
            "our mission",
        ),
    ),
)

# A heading is short, mostly its own line, and often decorated with colons,
# asterisks or hashes from markdown. Anything longer is a sentence that happens
# to begin with a heading word.
_MAX_HEADING_WORDS = 7
_DECORATION = re.compile(r"^[\s#*_•\-\u2013\u2014>\d.)\]]+|[\s:*_#]+$")


def classify_heading(line: str) -> JobSectionType | None:
    """Return the section a line introduces, or None if it is not a heading.

    Longest phrase wins across the whole vocabulary, not just within one type:
    "preferred qualifications" and "qualifications" both match a line saying the
    former, and the specific one has to take it or every preferred-skills block
    would be read as required.
    """
    stripped = _DECORATION.sub("", line).strip()
    if not stripped or len(stripped.split()) > _MAX_HEADING_WORDS:
        return None

    folded = re.sub(r"[^a-z0-9' ]+", " ", stripped.lower())
    folded = re.sub(r"\s+", " ", folded).strip()
    if not folded:
        return None

    best: tuple[int, JobSectionType] | None = None
    for section_type, phrases in _HEADINGS:
        for phrase in phrases:
            # Equality or "heading + trailing words", not substring containment:
            # "we have no requirements for this" is prose, not a heading.
            matched = folded == phrase or folded.startswith(f"{phrase} ")
            if matched and (best is None or len(phrase) > best[0]):
                best = (len(phrase), section_type)

    return best[1] if best is not None else None


@dataclass(frozen=True, slots=True)
class JobSection:
    type: JobSectionType
    heading: str
    text: str
    start: int
    end: int


def detect_sections(text: str) -> list[JobSection]:
    """Split a description into labelled blocks.

    Text before the first recognised heading becomes an ABOUT section: it is
    almost always the company blurb and the role summary, and skills mentioned
    there are real but weaker evidence than a requirements bullet.
    """
    lines = text.splitlines()
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1

    marks: list[tuple[int, int, JobSectionType, str]] = []
    for index, line in enumerate(lines):
        section_type = classify_heading(line)
        if section_type is not None:
            marks.append((index, offsets[index], section_type, line.strip()))

    sections: list[JobSection] = []

    if not marks:
        body = text.strip()
        return [JobSection(JobSectionType.UNKNOWN, "", body, 0, len(text))] if body else []

    # Preamble before the first heading.
    preamble = text[: marks[0][1]].strip()
    if preamble:
        sections.append(JobSection(JobSectionType.ABOUT, "", preamble, 0, marks[0][1]))

    for position, (line_index, start, section_type, heading) in enumerate(marks):
        body_start = start + len(lines[line_index]) + 1
        end = marks[position + 1][1] if position + 1 < len(marks) else len(text)
        body = text[body_start:end].strip()
        if body:
            sections.append(JobSection(section_type, heading, body, body_start, end))

    return sections


def section_map(sections: list[JobSection]) -> dict[JobSectionType, str]:
    """Merge sections of the same type into one block each.

    A description can carry two "Requirements" headings — one for the role and
    one for the team — and both mean the same thing to extraction.
    """
    merged: dict[JobSectionType, list[str]] = {}
    for section in sections:
        merged.setdefault(section.type, []).append(section.text)
    return {key: "\n".join(values) for key, values in merged.items()}


# Bullet markers, for pulling responsibilities and requirements out as lists.
#
# Extended after measuring this corpus rather than from a style guide: U+00B7
# (middle dot) and U+2219 arrive in provider payloads, `o` is Word's
# second-level bullet surviving a copy-paste, and U+00BB, `>` and `+` all
# appear in real postings here.
#
# Written as escapes, not glyphs: en dash, em dash and middle dot are
# indistinguishable from a hyphen and a full stop in source, so the escape is
# what makes the intent reviewable. normalization.py makes the same choice.
#
# Two deliberate loosenings. Trailing whitespace is optional, because
# "-Design APIs" with no space after the dash is common and was silently
# skipped. And `o` matches only when whitespace follows, so a line opening
# "or the team will..." is not read as a bullet.
_BULLET = re.compile(
    r"^[ \t]*(?:"
    r"[\u2022\u25cf\u25aa\u25e6\u2023\u2219\u00b7*+>\u00bb\-\u2013\u2014]"
    r"|o(?=\s)|\d+[.)])\s*"
)


def extract_bullets(text: str, *, limit: int = 30) -> list[str]:
    """Pull a section's items out as a list.

    Bullets first. When a section carries none, its **sentences** are used
    instead — which is a deliberate reversal of the original rule here, so it is
    worth saying why.

    That rule was: never take every line, because prose would otherwise produce a
    "responsibilities" array containing the whole posting. The concern was right
    about an *unlabelled* description and wrong about a labelled section. When a
    heading has been recognised, the text beneath it is bounded and is about that
    subject, so sentences from it are exactly the items wanted. The whole-posting
    failure cannot happen here: with no recognised heading there is no section to
    read, and this is never reached.

    Measured on the live corpus: 38 of 131 postings that produced nothing had a
    correctly identified Responsibilities or Requirements section whose body was
    prose, or bullets whose markers had been stripped upstream. Three shapes, all
    handled by sentence splitting:

      - genuine paragraphs
      - one item per line with the marker gone, hard-wrapped mid-item, which
        rejoins once newlines collapse to spaces
      - items run together with no separator at all, "...using FastAPI.Build and
        maintain..." — the boundary is the full stop against a capital

    Sentences are only a fallback. A section with real bullets is unaffected, so
    this cannot change what already worked.
    """
    bullets: list[str] = []
    for line in text.splitlines():
        if not _BULLET.match(line):
            continue
        cleaned = _BULLET.sub("", line).strip(" .;")
        # Two words filters out stray dashes used as separators; 300 characters
        # excludes a paragraph that happens to open with a dash.
        if len(cleaned.split()) >= 2 and len(cleaned) <= 300:
            bullets.append(cleaned)
        if len(bullets) >= limit:
            break
    return bullets or _sentences(text, limit=limit)


#: A sentence boundary: a full stop, question or exclamation mark, followed
#: either by whitespace or straight into a capital letter.
#:
#: The second case is the one that matters here. Provider payloads arrive with
#: list markup flattened away, leaving "...using FastAPI.Build and maintain..."
#: — no space, so splitting on "period plus space" alone finds nothing.
#:
#: The lookahead excludes a digit after the stop, so "3.5 years" and version
#: numbers are not cut in half.
_SENTENCE_END = re.compile(r"(?<=[.!?])(?=[ \t]+[A-Z]|[A-Z])")


def _sentences(text: str, *, limit: int) -> list[str]:
    """A section's prose as a list of items, for sections with no bullets."""
    # Newlines first: an item hard-wrapped across two lines is one sentence, and
    # it has to be rejoined before the boundaries can be found.
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return []

    items: list[str] = []
    for piece in _SENTENCE_END.split(flat):
        cleaned = piece.strip(" .;")
        # The same filters the bullet path uses, for the same reasons: two words
        # excludes fragments, 300 characters excludes a wall of text that happens
        # to contain no sentence boundary at all.
        if len(cleaned.split()) >= 2 and len(cleaned) <= 300:
            items.append(cleaned)
        if len(items) >= limit:
            break
    return items
