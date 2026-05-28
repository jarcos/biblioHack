"""Tests for the `MediaTypeFilter` value object."""

from __future__ import annotations

import pytest

from bibliohack.catalog.domain.media_filter import (
    MediaTypeFilter,
    MediaTypeFilterPreset,
)


def _book() -> MediaTypeFilter:
    return MediaTypeFilter.from_preset(MediaTypeFilterPreset.BOOK)


def _book_and_audio() -> MediaTypeFilter:
    return MediaTypeFilter.from_preset(MediaTypeFilterPreset.BOOK_AND_AUDIO)


def _monograph() -> MediaTypeFilter:
    return MediaTypeFilter.from_preset(MediaTypeFilterPreset.MONOGRAPH)


def _all() -> MediaTypeFilter:
    return MediaTypeFilter.from_preset(MediaTypeFilterPreset.ALL)


# ───────────────────────────────────────────────────────────────


class TestBookPreset:
    """`book` accepts only printed/electronic monographs (LDR/06=a, LDR/07=m)."""

    def test_accepts_a_m(self) -> None:
        assert _book().accepts("a", "m") is True

    @pytest.mark.parametrize(
        ("ld06", "ld07"),
        [
            ("a", "s"),  # serial / magazine
            ("a", "i"),  # integrating resource
            ("i", "m"),  # audiobook
            ("j", "m"),  # CD
            ("g", "m"),  # DVD / video
            ("c", "m"),  # printed music
            ("e", "m"),  # map
            (None, "m"),  # unknown record type
            ("a", None),  # unknown level
            (None, None),
        ],
    )
    def test_rejects_other_combinations(self, ld06: str | None, ld07: str | None) -> None:
        assert _book().accepts(ld06, ld07) is False


class TestBookAndAudioPreset:
    def test_accepts_book(self) -> None:
        assert _book_and_audio().accepts("a", "m") is True

    def test_accepts_audiobook(self) -> None:
        assert _book_and_audio().accepts("i", "m") is True

    @pytest.mark.parametrize(
        ("ld06", "ld07"),
        [("j", "m"), ("g", "m"), ("a", "s"), ("i", "s")],
    )
    def test_rejects_non_book_non_audiobook(self, ld06: str | None, ld07: str | None) -> None:
        assert _book_and_audio().accepts(ld06, ld07) is False


class TestMonographPreset:
    @pytest.mark.parametrize("ld06", ["a", "i", "j", "g", "c", "k", "m"])
    def test_accepts_any_record_type_when_monographic(self, ld06: str) -> None:
        assert _monograph().accepts(ld06, "m") is True

    @pytest.mark.parametrize("ld07", ["s", "i", "a", "b", "c", None])
    def test_rejects_non_monographic(self, ld07: str | None) -> None:
        assert _monograph().accepts("a", ld07) is False


class TestAllPreset:
    @pytest.mark.parametrize(
        ("ld06", "ld07"),
        [
            ("a", "m"),
            ("a", "s"),
            ("j", "m"),
            (None, None),
            ("anything", "anything"),
        ],
    )
    def test_accepts_everything(self, ld06: str | None, ld07: str | None) -> None:
        assert _all().accepts(ld06, ld07) is True

    def test_is_open_is_true(self) -> None:
        assert _all().is_open is True


class TestIsOpen:
    def test_book_filter_is_not_open(self) -> None:
        assert _book().is_open is False

    def test_monograph_filter_is_not_open(self) -> None:
        # MONOGRAPH allows (None, "m") which has None in ld06, but
        # ld07 is fixed to "m" so it's not fully open.
        assert _monograph().is_open is False
