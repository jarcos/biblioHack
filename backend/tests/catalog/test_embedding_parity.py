"""Provider parity: do new vectors line up with the ones already stored?

The ~174k stored vectors came from BGE-M3 on Hugging Face; new ones come from
BGE-M3 on OpenRouter. Same model, so they should match. `parity_report`
re-embeds a sample of stored records and says how close the two are, so a
provider switch can't silently mix incompatible vectors into one index.
"""

from __future__ import annotations

import math

import pytest

from bibliohack.catalog.application.embedding_parity import (
    PARITY_THRESHOLD,
    cosine_similarity,
    parity_report,
)


def test_cosine_of_a_vector_with_itself_is_one() -> None:
    assert cosine_similarity([3.0, 4.0], [3.0, 4.0]) == pytest.approx(1.0)


def test_cosine_ignores_length() -> None:
    assert cosine_similarity([1.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 2.0]) == pytest.approx(0.0)


def test_cosine_with_a_zero_vector_is_zero_not_nan() -> None:
    result = cosine_similarity([0.0, 0.0], [1.0, 0.0])
    assert result == 0.0
    assert not math.isnan(result)


def test_cosine_rejects_different_dimensions() -> None:
    with pytest.raises(ValueError, match="dimension"):
        cosine_similarity([1.0], [1.0, 0.0])


def test_report_passes_when_every_pair_is_close() -> None:
    report = parity_report(stored=[[1.0, 0.0], [0.0, 1.0]], fresh=[[1.0, 0.001], [0.001, 1.0]])

    assert report.compared == 2
    assert report.minimum == pytest.approx(1.0, abs=1e-5)
    assert report.mean == pytest.approx(1.0, abs=1e-5)
    assert report.passed


def test_report_fails_when_any_pair_drifts() -> None:
    report = parity_report(stored=[[1.0, 0.0], [1.0, 0.0]], fresh=[[1.0, 0.0], [0.0, 1.0]])

    assert report.minimum == pytest.approx(0.0)
    assert report.mean == pytest.approx(0.5)
    assert not report.passed


def test_report_on_an_empty_sample_does_not_pass() -> None:
    report = parity_report(stored=[], fresh=[])

    assert report.compared == 0
    assert not report.passed


def test_report_needs_matching_samples() -> None:
    with pytest.raises(ValueError, match="same length"):
        parity_report(stored=[[1.0]], fresh=[])


def test_threshold_is_strict_enough_to_catch_a_different_model() -> None:
    assert 0.98 <= PARITY_THRESHOLD < 1.0
