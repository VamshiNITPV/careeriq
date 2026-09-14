"""The resume optimization prompt, versioned (ml.md section 6.2, ADR-012).

A template rather than an f-string in a service, because a prompt change alters
output quality and an unversioned one is a regression nobody can reproduce.
`VERSION` is bumped on **any** edit to the text below -- including a word -- and
logged with every call, so a bad batch of suggestions can be traced to the exact
wording that produced it.

## The prompt is not the safety mechanism

It asks the model not to invent things, and that is worth doing: ADR-012 calls
prompt instructions "necessary but not sufficient". The guarantee comes from
`services/resume/fabrication.py`, which re-derives the answer from the text
afterwards and does not trust a word of this.

Writing the constraints here anyway raises the share of suggestions that survive
validation. A model told "rephrase only" invents less than one told "improve
this", so fewer good rewrites are lost alongside the bad ones. That is a quality
argument, not a safety one, and the distinction matters: if this file were the
defence, every improvement to it would be a security change.

## Why `grounded_in` is requested

Each suggestion must cite the source lines it derives from. Two uses: it gives a
reviewer something to check the rewrite against, and a model that cannot name a
source for a claim tends not to make the claim. It is evidence, not proof --
nothing stops a model citing a line that does not support it, which is why the
validator ignores these and re-reads the resume itself.
"""

from __future__ import annotations

from app.integrations.llm.base import Prompt

NAME = "resume_optimization"
#: Bump on any edit to the text below.
VERSION = "1"

_SYSTEM = """
You are a resume editor. You rewrite a candidate's existing bullet points so they
read more strongly and align better with a specific job, and you do nothing else.

Absolute rules:

1. Never introduce a fact that is not already in the resume. No skill, employer,
   job title, technology, certification, degree, date, duration, team size,
   percentage, currency amount or any other number may appear in your output
   unless that exact fact is already written in the resume.
2. Never make a number bigger, rounder or more impressive. If the resume says
   35%, you may not write 40%, "over a third", or "significantly".
3. Never derive a new figure. If the resume says a bundle went from 900KB to
   410KB, you may not describe that as a 54% reduction. The percentage is not in
   the resume.
4. If a bullet cannot be improved without adding something, return no suggestion
   for it. Returning fewer suggestions is always correct. Padding the list with
   invented detail is the single worst thing you can do here, because a person
   will be asked about it in an interview.
5. You may rephrase, reorder, use stronger verbs, move an existing detail
   forward, and drop filler. That is the whole permitted set of operations.

The candidate is a real person. Anything you invent, they will have to defend in
an interview, having never claimed it.
"""

_INSTRUCTION = """
Read the resume and the job description. Identify bullet points in the resume
whose wording undersells work that the job description asks for, and rewrite
those bullets.

For each rewrite, give the original text exactly as it appears, your rewritten
version, a one-sentence reason referring to the job, and the resume lines your
rewrite draws on.

Return at most 8 suggestions. Prefer few strong ones over many weak ones. If no
bullet can be improved without inventing something, return an empty list.
"""

_FORMAT = """
Reply with JSON only. No prose before or after, no markdown fences.

{
  "suggestions": [
    {
      "section": "experience",
      "original": "the exact text from the resume, copied character for character",
      "suggested": "your rewritten version",
      "rationale": "one sentence on why this helps for this job",
      "grounded_in": ["the resume line(s) this draws on, copied exactly"]
    }
  ]
}

If there is nothing to suggest, reply exactly: {"suggestions": []}
"""


def build(*, resume_text: str, job_title: str, job_description: str) -> Prompt:
    """Assemble the prompt for one (resume, job) pair.

    Both documents go in `context`, which is the only field that gets sanitised
    and delimited. A resume is untrusted input -- anyone can write "ignore
    previous instructions" into one -- and so is a job description, which came
    off somebody else's website entirely.
    """
    return Prompt(
        name=NAME,
        version=VERSION,
        system=_SYSTEM,
        instruction=_INSTRUCTION,
        context={
            "RESUME": resume_text,
            "JOB TITLE": job_title,
            "JOB DESCRIPTION": job_description,
        },
        output_format=_FORMAT,
    )
