"""Unit tests for parsing citation markers out of an answer."""

from __future__ import annotations

from docmind.rag.service import cited_indices


def test_separate_markers() -> None:
    assert cited_indices("See [1] and also [2].", 2) == [1, 2]


def test_repeated_bracket_markers() -> None:
    assert cited_indices("Both [1][2] agree.", 2) == [1, 2]


def test_grouped_marker() -> None:
    assert cited_indices("Both sources [1, 2] agree.", 2) == [1, 2]


def test_grouped_marker_without_spaces() -> None:
    assert cited_indices("See [1,2,3].", 3) == [1, 2, 3]


def test_grouped_marker_drops_out_of_range() -> None:
    assert cited_indices("See [1, 5].", 2) == [1]


def test_zero_and_out_of_range_ignored() -> None:
    assert cited_indices("Nothing here: [0], [7].", 2) == []
