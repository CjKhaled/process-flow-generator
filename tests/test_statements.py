"""Splitting the first description into statements."""

from session.statements import split
from tests.conftest import ENROLLMENT_DESCRIPTION


def test_each_line_is_its_own_statement() -> None:
    assert split("The HCP faxes a form\nThe vendor keys it") == ["The HCP faxes a form", "The vendor keys it"]


def test_a_line_of_several_sentences_is_divided() -> None:
    assert split("The form arrives. The vendor keys it! Is it complete? Then it is routed.") == [
        "The form arrives.",
        "The vendor keys it!",
        "Is it complete?",
        "Then it is routed.",
    ]


def test_a_heading_is_a_statement_of_its_own() -> None:
    """Whether marked up or bare, a heading sits on its own line and so stands alone."""
    assert split(
        "# Off-label process\nIf it is off-label, it is reviewed.\n\nDuplicate handling\nThen duplicates."
    ) == [
        "# Off-label process",
        "If it is off-label, it is reviewed.",
        "Duplicate handling",
        "Then duplicates.",
    ]


def test_blank_lines_and_surrounding_space_are_dropped() -> None:
    assert split("\n\n   The form arrives.   \n\n\n") == ["The form arrives."]
    assert split("   \n\t\n") == []


def test_a_list_marker_is_not_part_of_the_statement() -> None:
    assert split("- The form arrives.\n2. The vendor keys it.\n* It is routed.") == [
        "The form arrives.",
        "The vendor keys it.",
        "It is routed.",
    ]


def test_an_abbreviation_does_not_end_a_sentence() -> None:
    assert split("Missing items, e.g. The signature, are chased. Dr. Lee signs.") == [
        "Missing items, e.g. The signature, are chased.",
        "Dr. Lee signs.",
    ]


def test_a_decimal_or_a_lowercase_continuation_does_not_end_a_sentence() -> None:
    assert split("The form is v2.1 of the PEF. it is faxed.") == ["The form is v2.1 of the PEF. it is faxed."]


def test_every_statement_is_a_verbatim_slice_of_the_description() -> None:
    """Quotes are checked against statement text, so the split may not reword anything."""
    description = ENROLLMENT_DESCRIPTION.read_text(encoding="utf-8")

    statements = split(description)

    assert len(statements) > 40
    assert all(statement in description for statement in statements)


def test_the_split_is_deterministic() -> None:
    description = ENROLLMENT_DESCRIPTION.read_text(encoding="utf-8")

    assert split(description) == split(description)
