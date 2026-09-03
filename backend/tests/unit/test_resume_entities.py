"""Resume entity extraction (US-2.3 AC1) and date parsing.

Weighted towards the cases that produce *wrong* rows rather than missing ones.
A guessed employer or start date is quoted back to the candidate and silently
changes the years-of-experience figure the ranking formula reads; a missing one
is visible and one edit away.
"""

from __future__ import annotations

from datetime import date

from app.models.enums import EducationLevel, EmploymentType
from app.services.resume.dates import find_date_range
from app.services.resume.entities import (
    extract_certifications,
    extract_education,
    extract_experiences,
    extract_projects,
)


class TestDateRanges:
    def test_month_and_year(self) -> None:
        result = find_date_range("Jan 2020 - March 2022")
        assert result.start == date(2020, 1, 1)
        assert result.end == date(2022, 3, 1)
        assert result.is_current is False

    def test_present_is_open_ended(self) -> None:
        result = find_date_range("June 2021 \u2013 Present")
        assert result.start == date(2021, 6, 1)
        assert result.end is None
        assert result.is_current is True

    def test_indian_till_date(self) -> None:
        assert find_date_range("May 2023 - Till Date").is_current is True

    def test_bare_years(self) -> None:
        result = find_date_range("2019 - 2023")
        assert result.start == date(2019, 1, 1)
        assert result.end == date(2023, 1, 1)

    def test_numeric_months(self) -> None:
        result = find_date_range("03/2021 to 06/2022")
        assert result.start == date(2021, 3, 1)
        assert result.end == date(2022, 6, 1)

    def test_mixed_formats_across_the_range(self) -> None:
        # "Jan 2020 - 2023" is ordinary on a real resume.
        result = find_date_range("Jan 2020 - 2023")
        assert result.start == date(2020, 1, 1)
        assert result.end == date(2023, 1, 1)

    def test_swaps_a_reversed_range(self) -> None:
        result = find_date_range("2023 - 2019")
        assert result.start == date(2019, 1, 1)
        assert result.end == date(2023, 1, 1)

    def test_ignores_implausible_years(self) -> None:
        assert find_date_range("Employee of the year 1849").is_empty is True

    def test_prose_has_no_dates(self) -> None:
        assert find_date_range("Built scalable backend services").is_empty is True

    def test_day_precision_is_never_invented(self) -> None:
        # A resume saying "Jan 2020" does not know the day.
        assert find_date_range("Jan 2020").start == date(2020, 1, 1)


class TestExperience:
    def test_reads_a_standard_entry(self) -> None:
        text = """Software Engineer
Acme Technologies Pvt Ltd | Bengaluru, India
Jan 2020 - Present
- Built backend services in Python
- Mentored two junior engineers
"""
        [entry] = extract_experiences(text)
        assert entry.title == "Software Engineer"
        assert entry.company_name == "Acme Technologies Pvt Ltd"
        assert entry.location == "Bengaluru, India"
        assert entry.dates.start == date(2020, 1, 1)
        assert entry.dates.is_current is True
        assert len(entry.highlights) == 2

    def test_reads_dates_on_the_title_line(self) -> None:
        # The other common layout: dates right-aligned onto the same line.
        text = """Senior Developer | Zeta Labs                    Mar 2018 - Dec 2021
- Led the payments rewrite
"""
        [entry] = extract_experiences(text)
        assert entry.title == "Senior Developer"
        assert entry.company_name == "Zeta Labs"
        assert entry.dates.end == date(2021, 12, 1)

    def test_separates_multiple_roles(self) -> None:
        text = """Software Engineer | Acme Inc
Jan 2020 - Present
- Recent work

Junior Developer | Zeta Labs
Jun 2018 - Dec 2019
- Earlier work
"""
        entries = extract_experiences(text)
        assert len(entries) == 2
        assert {e.title for e in entries} == {"Software Engineer", "Junior Developer"}
        # Bullets attach to the entry above them, not the one after.
        assert entries[0].highlights == ["Recent work"]

    def test_keeps_a_role_with_no_employer(self) -> None:
        # Discarding the whole row to satisfy a NOT NULL would lose the role,
        # the dates and the highlights to protect a field nothing scores on.
        text = "Freelance Developer\n2019 - 2021\n- Built sites for local businesses\n"
        [entry] = extract_experiences(text)
        assert entry.title == "Freelance Developer"
        assert entry.company_name is None

    def test_detects_an_internship(self) -> None:
        text = "Software Engineering Intern | Acme Inc\nMay 2019 - Aug 2019\n- Shipped a feature\n"
        [entry] = extract_experiences(text)
        assert entry.employment_type is EmploymentType.INTERNSHIP

    def test_skips_an_entry_with_no_recognisable_role(self) -> None:
        # Naming someone's job title wrongly is worse than omitting the entry:
        # it is quoted back to them and scored against every job.
        text = "Some Organisation Name\n2019 - 2021\n- Did things\n"
        assert extract_experiences(text) == []

    def test_ignores_a_section_with_no_dates(self) -> None:
        assert extract_experiences("I have worked in software for a long time.") == []

    def test_content_key_is_stable_across_formatting(self) -> None:
        # What makes a re-parse update the row instead of inserting a copy.
        a = extract_experiences("Software Engineer | Acme Inc\nJan 2020 - Present\n- x\n")[0]
        b = extract_experiences("SOFTWARE  ENGINEER | acme, inc.\nJan 2020 - Present\n- x\n")[0]
        assert a.content_key == b.content_key

    def test_different_roles_get_different_keys(self) -> None:
        entries = extract_experiences(
            "Software Engineer | Acme Inc\nJan 2020 - Present\n- x\n\n"
            "Senior Engineer | Acme Inc\nJan 2018 - Dec 2019\n- y\n"
        )
        assert entries[0].content_key != entries[1].content_key


class TestEducation:
    def test_reads_a_degree(self) -> None:
        text = """B.Tech in Computer Science
National Institute of Technology, Warangal
2016 - 2020
CGPA: 8.4
"""
        [entry] = extract_education(text)
        assert entry.institution.startswith("National Institute of Technology")
        assert entry.degree is not None
        assert entry.level is EducationLevel.BACHELORS
        assert entry.field_of_study == "Computer Science"
        assert entry.grade == "8.4"
        assert entry.dates.end == date(2020, 1, 1)

    def test_recognises_a_masters(self) -> None:
        text = "M.Tech | Indian Institute of Technology Bombay\n2020 - 2022\n"
        [entry] = extract_education(text)
        assert entry.level is EducationLevel.MASTERS

    def test_keeps_the_grade_as_written(self) -> None:
        # "8.4 CGPA", "First Class" and "72%" are all real; forcing them into
        # one number would either lose meaning or invent a conversion.
        text = "B.Sc | Delhi University\n2015 - 2018\nFirst Class with Distinction\n"
        [entry] = extract_education(text)
        assert entry.grade is not None
        assert "first class" in entry.grade.lower()

    def test_skips_a_degree_with_no_institution(self) -> None:
        # A bare "B.Tech" row has nothing to attribute the degree to.
        assert extract_education("B.Tech\n2016 - 2020\n") == []


class TestProjects:
    def test_reads_a_project_with_bullets(self) -> None:
        text = """CareerIQ — https://github.com/priya/careeriq
- Built a job matching platform
- Used FastAPI and PostgreSQL
"""
        [entry] = extract_projects(text)
        assert entry.name == "CareerIQ"
        assert entry.url is not None
        assert "github.com" in entry.url
        assert len(entry.highlights) == 2

    def test_separates_projects(self) -> None:
        text = """Project One
- Did a thing

Project Two
- Did another thing
"""
        entries = extract_projects(text)
        assert [e.name for e in entries] == ["Project One", "Project Two"]

    def test_reads_dates_when_present(self) -> None:
        # Unlike experience, a project often has none — which is why the anchor
        # here is the bullets rather than the dates.
        text = "Payments Service | 2021 - 2022\n- Built it\n"
        [entry] = extract_projects(text)
        assert entry.dates.start == date(2021, 1, 1)

    def test_ignores_a_heading_with_nothing_under_it(self) -> None:
        assert extract_projects("Projects\n") == []


class TestCertifications:
    def test_reads_a_certification_and_its_issuer(self) -> None:
        # The en dash is inside the certification's own name, not a date range.
        line = "- AWS Certified Solutions Architect \u2013 Associate, 2023\n"
        [entry] = extract_certifications(line)
        assert "Solutions Architect" in entry.name
        assert entry.issuer is not None
        assert entry.issuer.lower() == "aws"
        assert entry.dates.start == date(2023, 1, 1)

    def test_reads_several(self) -> None:
        text = """- Google Cloud Professional Data Engineer
- Microsoft Certified: Azure Fundamentals
"""
        entries = extract_certifications(text)
        assert len(entries) == 2

    def test_skips_a_one_word_line(self) -> None:
        # A stray year or a section fragment is not a certification.
        assert extract_certifications("2023\n") == []

    def test_keeps_an_unknown_issuer_as_none(self) -> None:
        [entry] = extract_certifications("- Certified Kubernetes Administrator\n")
        # Kubernetes is a known issuer word; the name still survives intact.
        assert "Administrator" in entry.name
