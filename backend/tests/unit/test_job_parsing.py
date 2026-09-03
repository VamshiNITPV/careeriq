"""Job description parsing (US-3.1 AC2).

Weighted towards the cases that produce *wrong* structured data rather than
missing data. A missing salary is neutral in the ranking formula; a fabricated
one silently mis-scores every candidate against that job, and nobody can see
that it was invented.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.enums import (
    EducationLevel,
    EmploymentType,
    ExperienceLevel,
    SalaryPeriod,
    SkillRequirement,
    WorkMode,
)
from app.services.job.normalization import (
    clean_description,
    content_hash,
    normalize_company_name,
    normalize_title,
)
from app.services.job.parsing import (
    find_company,
    find_employment_type,
    find_experience_level,
    find_experience_range,
    find_location,
    find_min_education,
    find_salary,
    find_title,
    find_work_mode,
)
from app.services.job.sections import (
    JobSectionType,
    classify_heading,
    detect_sections,
    extract_bullets,
    section_map,
)
from app.services.job.skills import extract_job_skills
from app.services.resume.skill_extraction import build_matcher

TAXONOMY = {
    "Python": ["python"],
    "Kubernetes": ["kubernetes", "k8s"],
    "PostgreSQL": ["postgresql", "postgres"],
    "React": ["react", "react.js"],
    "Docker": ["docker"],
    "Go": ["go", "golang"],
}


class TestCompanyNormalization:
    def test_strips_legal_suffixes(self) -> None:
        assert normalize_company_name("Acme, Inc.") == "acme"
        assert normalize_company_name("ACME Inc") == "acme"
        assert normalize_company_name("Acme Technologies Pvt Ltd") == "acme technologies"

    def test_strips_stacked_suffixes(self) -> None:
        # "Pvt Ltd" is two suffixes in a row, so one pass is not enough.
        assert normalize_company_name("Zeta Labs Private Limited") == "zeta labs"

    def test_never_empties_a_name(self) -> None:
        # A company genuinely called "Group" must not normalise to "", which
        # every other unparseable name would then collide with.
        assert normalize_company_name("Group") == "group"
        assert normalize_company_name("Ltd") == "ltd"

    def test_keeps_distinct_companies_distinct(self) -> None:
        # Only the closed suffix list is removed. Stripping any trailing word
        # would merge these two into one employer.
        assert normalize_company_name("Acme Health") != normalize_company_name("Acme Motors")

    def test_folds_diacritics_and_punctuation(self) -> None:
        assert normalize_company_name("Nestlé S.A.") == normalize_company_name("Nestle SA")


class TestTitleNormalization:
    def test_strips_seniority_and_decorations(self) -> None:
        assert normalize_title("Sr. Software Engineer II (Remote)") == "software engineer"
        assert normalize_title("Senior Software Engineer") == "software engineer"
        assert normalize_title("Software Engineer") == "software engineer"

    def test_strips_requisition_numbers(self) -> None:
        assert normalize_title("Backend Engineer [Req 12345]") == "backend engineer"

    def test_never_empties_a_title(self) -> None:
        # Stripping everything would make every noise-only title collide.
        assert normalize_title("Senior") != ""


class TestDescriptionHashing:
    def test_same_posting_hashes_identically_despite_formatting(self) -> None:
        # The whole point of stage-one dedup: the same posting copied from two
        # sites differs in wrapping and quote characters, not in content.
        a = clean_description("We need a  Python   dev.\n\n\nApply now.")
        b = clean_description("We need a Python dev.\n\nAPPLY NOW.")
        assert content_hash(a) == content_hash(b)

    def test_different_postings_hash_differently(self) -> None:
        assert content_hash(clean_description("Python role")) != content_hash(
            clean_description("Java role")
        )

    def test_clean_keeps_case_and_punctuation(self) -> None:
        # description_clean is also what gets embedded in Phase 6, where case
        # and sentence structure carry meaning.
        assert "Python" in clean_description("We use Python.")
        assert "." in clean_description("We use Python.")

    def test_clean_preserves_single_blank_lines(self) -> None:
        # Paragraph breaks are what section detection reads.
        assert "\n\n" in clean_description("Requirements:\n\n- Python")


class TestSectionDetection:
    def test_preferred_beats_qualifications(self) -> None:
        # The longest phrase has to win across the whole vocabulary. Otherwise
        # every preferred-skills block is read as required.
        assert classify_heading("Preferred Qualifications") is JobSectionType.NICE_TO_HAVE
        assert classify_heading("Qualifications") is JobSectionType.REQUIREMENTS

    def test_tolerates_markdown_decoration(self) -> None:
        assert classify_heading("## Requirements:") is JobSectionType.REQUIREMENTS
        assert classify_heading("**What you'll do**") is JobSectionType.RESPONSIBILITIES

    def test_rejects_prose_containing_a_heading_word(self) -> None:
        assert classify_heading("We have no requirements for this role at present") is None

    def test_preamble_becomes_about(self) -> None:
        sections = detect_sections("We are Acme, a fintech.\n\nRequirements\n- Python")
        assert sections[0].type is JobSectionType.ABOUT
        assert "fintech" in sections[0].text

    def test_merges_repeated_sections(self) -> None:
        text = "Requirements\n- Python\n\nRequirements\n- Docker"
        merged = section_map(detect_sections(text))
        assert "Python" in merged[JobSectionType.REQUIREMENTS]
        assert "Docker" in merged[JobSectionType.REQUIREMENTS]

    def test_unstructured_text_yields_one_unknown_section(self) -> None:
        sections = detect_sections("We want a Python developer to join us.")
        assert len(sections) == 1
        assert sections[0].type is JobSectionType.UNKNOWN


class TestBullets:
    def test_extracts_only_real_bullets(self) -> None:
        text = "This is a prose paragraph that is not a bullet.\n- Build APIs\n* Review code"
        assert extract_bullets(text) == ["Build APIs", "Review code"]

    def test_prose_only_yields_nothing(self) -> None:
        # An array containing the whole posting is worse than an empty one.
        assert extract_bullets("We are looking for someone great. You will do things.") == []


class TestWorkMode:
    def test_hybrid_wins_over_remote(self) -> None:
        # "Hybrid — 3 days remote" contains the word remote. Classifying it
        # REMOTE scores a candidate who cannot relocate far too highly.
        assert find_work_mode("This is a hybrid role, 3 days remote") is WorkMode.HYBRID

    def test_detects_each_mode(self) -> None:
        assert find_work_mode("Fully remote position") is WorkMode.REMOTE
        assert find_work_mode("This is an on-site role") is WorkMode.ONSITE

    def test_returns_none_when_unstated(self) -> None:
        assert find_work_mode("We are hiring an engineer.") is None


class TestEmploymentType:
    def test_internship_beats_full_time(self) -> None:
        # Postings say "full-time internship". Checking FULL_TIME first would
        # classify every intern role as permanent.
        assert find_employment_type("A full-time internship") is EmploymentType.INTERNSHIP

    def test_detects_contract_and_part_time(self) -> None:
        assert find_employment_type("6-month contract role") is EmploymentType.CONTRACT
        assert find_employment_type("Part-time position") is EmploymentType.PART_TIME

    def test_returns_none_when_unstated(self) -> None:
        assert find_employment_type("Join our engineering team.") is None


class TestExperienceRange:
    def test_parses_a_range(self) -> None:
        result = find_experience_range("We want 3-5 years of experience")
        assert result is not None
        assert result.min_years == Decimal(3)
        assert result.max_years == Decimal(5)

    def test_parses_an_open_minimum(self) -> None:
        result = find_experience_range("5+ years of backend experience")
        assert result is not None
        assert result.min_years == Decimal(5)
        assert result.max_years is None

    def test_parses_at_least(self) -> None:
        result = find_experience_range("Minimum of 2 years in a similar role")
        assert result is not None
        assert result.min_years == Decimal(2)

    def test_ignores_a_bare_year_count(self) -> None:
        # "Five years ago we started" is not a requirement, and a wrong minimum
        # silently penalises every candidate below it.
        assert find_experience_range("We were founded 6 years ago") is None


class TestExperienceLevel:
    def test_title_wins_over_body(self) -> None:
        # "You will mentor junior engineers" describes the team, not the role.
        level = find_experience_level("Senior Backend Engineer", "You will mentor junior engineers")
        assert level is ExperienceLevel.SENIOR

    def test_falls_back_to_the_body(self) -> None:
        assert find_experience_level(None, "This is an entry-level role") is ExperienceLevel.ENTRY

    def test_returns_none_when_unstated(self) -> None:
        assert find_experience_level("Backend Engineer", "Build things.") is None


class TestEducation:
    def test_takes_the_lowest_named_level(self) -> None:
        # The column is a minimum: "Bachelor's required, Master's preferred"
        # asks for a bachelor's.
        text = "Bachelor's degree required. Master's preferred."
        assert find_min_education(text) is EducationLevel.BACHELORS

    def test_recognises_indian_degree_names(self) -> None:
        assert find_min_education("B.Tech in Computer Science") is EducationLevel.BACHELORS
        assert find_min_education("MCA or equivalent") is EducationLevel.MASTERS

    def test_returns_none_when_unstated(self) -> None:
        assert find_min_education("We care about what you can build.") is None


class TestSalary:
    def test_parses_lpa(self) -> None:
        # The magnitude is written once, after the second number.
        result = find_salary("Compensation: 12 - 18 LPA")
        assert result is not None
        assert result.minimum == Decimal(1_200_000)
        assert result.maximum == Decimal(1_800_000)
        assert result.currency == "INR"
        assert result.period is SalaryPeriod.YEARLY

    def test_parses_indian_digit_grouping(self) -> None:
        result = find_salary("Salary: ₹12,00,000 - ₹18,00,000 per annum")
        assert result is not None
        assert result.minimum == Decimal(1_200_000)
        assert result.maximum == Decimal(1_800_000)
        assert result.currency == "INR"

    def test_parses_dollars_with_k(self) -> None:
        result = find_salary("$120k - $150k per year")
        assert result is not None
        assert result.minimum == Decimal(120_000)
        assert result.maximum == Decimal(150_000)
        assert result.currency == "USD"

    def test_carries_a_trailing_magnitude_back(self) -> None:
        result = find_salary("$120 - 150k annually")
        assert result is not None
        assert result.minimum == Decimal(120_000)

    def test_detects_period(self) -> None:
        monthly = find_salary("Rs 50,000 - 80,000 per month")
        assert monthly is not None
        assert monthly.period is SalaryPeriod.MONTHLY

    def test_ignores_years_of_experience(self) -> None:
        # The guard that matters most: without a currency requirement, every
        # "3 - 5 years" in a description parses as pay.
        assert find_salary("We want 3 - 5 years of experience") is None

    def test_ignores_team_size(self) -> None:
        # "10 members" must not become 10 million.
        assert find_salary("You will join a team of 5 to 10 members") is None

    def test_returns_none_when_unstated(self) -> None:
        assert find_salary("Competitive salary and equity.") is None


class TestJobSkillExtraction:
    def build(self, text: str):
        matcher = build_matcher(TAXONOMY)
        sections = section_map(detect_sections(text))
        return {
            m.canonical_name: m
            for m in extract_job_skills(matcher=matcher, sections=sections, full_text=text)
        }

    def test_requirements_are_required_and_nice_to_haves_preferred(self) -> None:
        text = (
            "Requirements\n"
            "- Strong Python experience\n"
            "\n"
            "Nice to have\n"
            "- Exposure to Kubernetes\n"
        )
        found = self.build(text)
        assert found["Python"].requirement is SkillRequirement.REQUIRED
        assert found["Kubernetes"].requirement is SkillRequirement.PREFERRED

    def test_an_inline_hedge_demotes_a_requirement(self) -> None:
        # Postings routinely put "is a plus" inside the requirements list.
        # Reading that as mandatory over-constrains every match.
        text = "Requirements\n- Python\n- Experience with Docker is a plus\n"
        found = self.build(text)
        assert found["Python"].requirement is SkillRequirement.REQUIRED
        assert found["Docker"].requirement is SkillRequirement.PREFERRED

    def test_required_wins_when_a_skill_appears_in_both(self) -> None:
        text = "Requirements\n- Python\n\nNice to have\n- More Python\n"
        assert self.build(text)["Python"].requirement is SkillRequirement.REQUIRED

    def test_resolves_aliases(self) -> None:
        # The reason the matcher is shared with the resume side at all.
        assert "Kubernetes" in self.build("Requirements\n- K8s in production\n")
        assert "PostgreSQL" in self.build("Requirements\n- Postgres tuning\n")

    def test_captures_a_per_skill_minimum(self) -> None:
        found = self.build("Requirements\n- 4+ years of Python\n")
        assert found["Python"].min_years == Decimal(4)

    def test_unstructured_text_still_yields_skills(self) -> None:
        # Many real postings are one unbroken paragraph.
        found = self.build("We want someone who knows Python and Docker well.")
        assert "Python" in found
        assert "Docker" in found

    def test_carries_evidence(self) -> None:
        # Same principle as resume suggestions: the user judges the reasoning.
        found = self.build("Requirements\n- Strong Python experience\n")
        assert "Python" in found["Python"].evidence


class TestTitleAndCompanyExtraction:
    def test_prefers_a_labelled_header(self) -> None:
        text = "Some preamble here\nJob Title: Backend Engineer\nCompany: Acme Inc"
        assert find_title(text) == "Backend Engineer"

    def test_falls_back_to_the_first_line(self) -> None:
        assert find_title("Senior Backend Engineer\n\nAbout us...") == "Senior Backend Engineer"

    def test_does_not_name_a_role_after_a_sentence(self) -> None:
        # A description opening with prose does not lead with its title, and
        # guessing further down finds section headings instead.
        assert find_title("We are a fast growing fintech company.\n\nRequirements") is None

    def test_reads_a_company_from_an_about_sentence(self) -> None:
        text = "About us\nAcme Technologies Pvt Ltd builds payments infrastructure for teams."
        assert find_company(text) == "Acme Technologies Pvt Ltd"

    def test_does_not_invent_a_company_from_a_pronoun(self) -> None:
        # "We are a small team" would otherwise yield a company called "We" —
        # and every posting opening that way collapses into one employer.
        assert find_company("About us\nWe are a small engineering team.") is None
        assert find_company("Our mission is to make payments simple.") is None

    def test_prefers_a_label_over_a_sentence(self) -> None:
        text = "Company: Zeta Labs\n\nAbout us\nAcme Inc builds things."
        assert find_company(text) == "Zeta Labs"

    def test_location_strips_a_work_mode_annotation(self) -> None:
        assert find_location("Location: Bengaluru, India (Remote)") == "Bengaluru, India"

    def test_location_returns_none_when_unlabelled(self) -> None:
        assert find_location("We are hiring across the country.") is None
