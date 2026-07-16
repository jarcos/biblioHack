"""RecordFeedback — persist one reader signal on a recommended record (P1, §D4).

Thin by design: it validates the signal against what P1 accepts, then appends
via the `FeedbackStore`. The signal *doing something* lives in retrieval (the
weighted centroid + cache busting, `get_recommendations`) — this use case only
writes the event.

`read_rating` is rejected here: the enum value exists so the persisted column
never needs widening, but its writer is P2's mark-read loop (§6), not the
button surface P1 ships.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from bibliohack.recommendations.domain.feedback import FeedbackSignal
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.recommendations.application.ports import FeedbackStore
    from bibliohack.shared.application.result import Result


class RecordFeedbackError(StrEnum):
    UNSUPPORTED_SIGNAL = "unsupported_signal"  # e.g. read_rating before P2


# The button signals P1 exposes. `read_rating` is deliberately excluded.
_P1_SIGNALS = frozenset(
    {
        FeedbackSignal.LIKE,
        FeedbackSignal.DISLIKE,
        FeedbackSignal.MORE_LIKE_THIS,
        FeedbackSignal.NOT_INTERESTED,
    }
)


class RecordFeedback:
    def __init__(self, *, feedback: FeedbackStore) -> None:
        self._feedback = feedback

    async def execute(
        self, user_id: str, record_id: str, signal: FeedbackSignal
    ) -> Result[None, RecordFeedbackError]:
        if signal not in _P1_SIGNALS:
            return Err(RecordFeedbackError.UNSUPPORTED_SIGNAL)
        await self._feedback.record(user_id, record_id, signal)
        return Ok(None)
