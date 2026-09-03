"""Tests for contact extraction from a resume header (services/resume/contact.py).

The negative tests matter most. These values are written into a real person's
profile, so a confident wrong answer is worse than a blank: nobody notices an
empty field is wrong, but "Curriculum Vitae" sitting in a name field is both
embarrassing and hard to trace back to a parser.
"""

from __future__ import annotations

import pytest

from app.services.resume.contact import extract_contact, head_of

INDIAN_HEADER = """\
PRIYA SHARMA
priya.sharma@example.com | +91 98765 43210 | Bengaluru, India
linkedin.com/in/priyasharma | github.com/priyasharma
"""

US_HEADER = """\
Priya Sharma
Senior Backend Engineer
(415) 555-0198 · priya@example.com · San Francisco, CA
https://github.com/priya/careeriq
"""


class TestFullExtraction:
    def test_indian_style_header(self) -> None:
        contact = extract_contact(INDIAN_HEADER)

        assert contact.full_name == "Priya Sharma"
        assert contact.email == "priya.sharma@example.com"
        assert contact.phone == "+91 98765 43210"
        assert contact.location == "Bengaluru, India"
        assert contact.linkedin_url == "https://www.linkedin.com/in/priyasharma"
        assert contact.github_url == "https://github.com/priyasharma"

    def test_us_style_header(self) -> None:
        contact = extract_contact(US_HEADER)

        assert contact.full_name == "Priya Sharma"
        # Original formatting is kept — the user expects to see what they wrote,
        # not a normalised digit string.
        assert contact.phone == "(415) 555-0198"
        assert contact.location == "San Francisco, CA"

    def test_all_caps_name_is_title_cased(self) -> None:
        assert extract_contact("PRIYA SHARMA\nx@y.com\n").full_name == "Priya Sharma"

    @pytest.mark.parametrize("name", ["Priya McDonald", "Sean O'Brien", "Ada van Berg"])
    def test_mixed_case_names_are_left_alone(self, name: str) -> None:
        # Title-casing these would produce "Mcdonald", "O'brien", "Van Berg".
        assert extract_contact(f"{name}\nx@y.com\n").full_name == name


class TestPhoneRejection:
    def test_a_year_range_is_not_a_phone_number(self) -> None:
        """The single most common false positive on a resume header."""
        header = "Priya Sharma\nB.Tech Computer Science 2019 - 2023\npriya@example.com\n"

        assert extract_contact(header).phone is None

    @pytest.mark.parametrize(
        "line",
        [
            "Graduated 2020 — 2024",
            "Employed 2018-2022",
            "94105-1234",  # ZIP+4
            "Score: 1234567",  # bare digits, no phone formatting
        ],
    )
    def test_digit_runs_that_are_not_phone_numbers(self, line: str) -> None:
        assert extract_contact(f"Priya Sharma\n{line}\n").phone is None

    def test_accepts_international_and_bracketed_forms(self) -> None:
        assert extract_contact("Priya Sharma\n+91 98765 43210\n").phone is not None
        assert extract_contact("Priya Sharma\n(415) 555-0198\n").phone is not None


class TestNameRejection:
    @pytest.mark.parametrize(
        "line",
        [
            "Curriculum Vitae",
            "RESUME",
            "Senior Backend Engineer",
            "Software Developer",
            "Data Analyst",
            "priya@example.com",
            "+91 98765 43210",
            "linkedin.com/in/priya",
        ],
    )
    def test_lines_that_must_never_become_a_name(self, line: str) -> None:
        # A document label or a job title in the name field is worse than blank.
        assert extract_contact(f"{line}\nmore text here\n").full_name != line

    def test_a_header_with_only_an_email_yields_no_name(self) -> None:
        assert extract_contact("priya.sharma@example.com\n").full_name is None

    def test_the_headline_under_the_name_does_not_win(self) -> None:
        contact = extract_contact("Priya Sharma\nSenior Backend Engineer\nx@y.com\n")
        assert contact.full_name == "Priya Sharma"


class TestUrls:
    def test_github_repo_url_reduces_to_the_profile(self) -> None:
        # github.com/priya/careeriq identifies the person as "priya".
        contact = extract_contact("Priya Sharma\ngithub.com/priya/careeriq\n")
        assert contact.github_url == "https://github.com/priya"

    def test_github_feature_pages_are_not_usernames(self) -> None:
        assert extract_contact("Priya\ngithub.com/features/actions\n").github_url is None

    def test_linkedin_is_normalised(self) -> None:
        for form in (
            "linkedin.com/in/priya",
            "https://www.linkedin.com/in/priya",
            "in.linkedin.com/in/priya/",
        ):
            assert extract_contact(f"Priya Sharma\n{form}\n").linkedin_url == (
                "https://www.linkedin.com/in/priya"
            )

    def test_portfolio_excludes_social_links(self) -> None:
        contact = extract_contact(
            "Priya Sharma\nlinkedin.com/in/priya | github.com/priya | priya.dev\n"
        )
        assert contact.portfolio_url == "https://priya.dev"

    def test_an_email_domain_is_not_a_portfolio(self) -> None:
        # The generic URL pattern matches the domain half of an address, which
        # would publish the user's mail provider as their personal site.
        contact = extract_contact("Priya Sharma\npriya@example.com\n")
        assert contact.portfolio_url is None


class TestLocation:
    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            ("Bengaluru, India", "Bengaluru, India"),
            ("San Francisco, CA", "San Francisco, CA"),
            ("New Delhi, India", "New Delhi, India"),
        ],
    )
    def test_recognises_city_country_pairs(self, segment: str, expected: str) -> None:
        header = f"Priya Sharma\nx@y.com | {segment} | +91 98765 43210\n"
        assert extract_contact(header).location == expected

    @pytest.mark.parametrize(
        "segment",
        ["Senior Engineer, Payments", "priya@example.com", "Open to remote"],
    )
    def test_rejects_segments_that_are_not_places(self, segment: str) -> None:
        assert extract_contact(f"Priya Sharma\n{segment}\n").location != segment


class TestNeverGuesses:
    def test_country_code_is_never_inferred(self) -> None:
        """Deliberately out of scope.

        Mapping "India" to "IN" needs a country table this project does not
        have, and a wrong guess silently distorts the location dimension of the
        ranking formula — while also violating a CHECK constraint if the length
        is wrong.
        """
        contact = extract_contact(INDIAN_HEADER)
        assert not hasattr(contact, "country_code")

    @pytest.mark.parametrize("text", ["", "   \n\n  ", "\n"])
    def test_empty_input_returns_everything_none(self, text: str) -> None:
        contact = extract_contact(text)
        assert contact.full_name is None
        assert contact.phone is None
        assert contact.location is None

    def test_unparseable_header_does_not_raise(self) -> None:
        assert extract_contact("░▒▓ ██ ▓▒░\n\x00\x01\n").full_name is None


class TestHeadOf:
    def test_takes_the_first_lines(self) -> None:
        # Used when no CONTACT section was detected, because detect_sections
        # only emits one for text before the first heading.
        text = "\n".join(f"line {i}" for i in range(40))
        assert head_of(text, limit=3) == "line 0\nline 1\nline 2"
