"""RecordFeedback use-case tests (in-memory FeedbackStore fake)."""

from __future__ import annotations

import pytest

from bibliohack.recommendations.application.use_cases.record_feedback import (
    RecordFeedback,
    RecordFeedbackError,
)
from bibliohack.recommendations.domain.feedback import FeedbackSignal
from bibliohack.shared.application.result import Err, Ok
from tests.recommendations.test_get_recommendations import FakeFeedback


@pytest.mark.parametrize(
    "signal",
    [
        FeedbackSignal.LIKE,
        FeedbackSignal.DISLIKE,
        FeedbackSignal.MORE_LIKE_THIS,
        FeedbackSignal.NOT_INTERESTED,
    ],
)
async def test_button_signals_are_recorded(signal: FeedbackSignal) -> None:
    store = FakeFeedback()
    result = await RecordFeedback(feedback=store).execute("u-1", "rec-1", signal)
    assert isinstance(result, Ok)
    assert store.recorded == [("u-1", "rec-1", signal)]


async def test_read_rating_is_rejected_in_p1() -> None:
    """The enum value exists for P2, but its writer is not the button surface."""
    store = FakeFeedback()
    result = await RecordFeedback(feedback=store).execute("u-1", "rec-1", FeedbackSignal.READ_RATING)
    assert result == Err(RecordFeedbackError.UNSUPPORTED_SIGNAL)
    assert store.recorded == []  # nothing persisted on a rejected signal
