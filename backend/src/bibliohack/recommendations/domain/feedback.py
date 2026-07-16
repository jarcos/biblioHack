"""Recommendation feedback — the reader's return channel (chat-recs P1, §D4).

Every like/dislike/«más como esto»/«no me interesa» on a recommendation is one
appended `RecommendationFeedback` event. Like `Recommendation`, this is a
*derived* signal with no lifecycle invariants of its own: the interesting logic
is how the latest signal per record re-weights the taste centroid (§4) and busts
the cache (§D4), and that lives behind the application ports.

`read_rating` (the mark-read loop, §6) is P2's writer — the value exists in the
enum now so the persisted `signal` column never needs widening, but P1 rejects
it at the use-case boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class FeedbackSignal(StrEnum):
    """What the reader said about one recommended record.

    Stored as a plain string (`String(20)`), matching the codebase's
    convention for enum-ish columns (`shelf`, `resolve_status`) — no native
    Postgres enum, so adding P2's `read_rating` writer is migration-free.
    """

    LIKE = "like"  # +0.7 to the centroid
    DISLIKE = "dislike"  # -0.5 to the centroid + hard-exclude the record
    MORE_LIKE_THIS = "more_like_this"  # +0.7, same as LIKE
    NOT_INTERESTED = "not_interested"  # 0 weight — hard-exclude only ("not now")
    READ_RATING = "read_rating"  # P2: a 1-5 rating after reading (uses `rating`)


@dataclass(frozen=True, slots=True)
class RecommendationFeedback:
    """One feedback event: (user, record, signal) at a point in time.

    `rating` is set only for `READ_RATING` (1-5); None for the button signals.
    The latest event per (user, record) is the one that counts — earlier events
    are kept as history but don't re-weight retrieval.
    """

    record_id: str
    signal: FeedbackSignal
    created_at: datetime
    rating: int | None = None
