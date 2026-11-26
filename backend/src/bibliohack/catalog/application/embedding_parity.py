"""Provider parity — are freshly made vectors compatible with the stored ones?

The HNSW index holds vectors from one provider; a switch (Hugging Face →
OpenRouter, 2026-11-26) must not mix in vectors that live somewhere else in
the space, or "más como este" and semantic search would quietly degrade. Same
model on both sides should give near-identical vectors; `parity_report`
measures it on a sample of already-embedded records before the backfill runs.
Pure functions, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Same weights through two providers lands well above this; a different model
# (or a different pooling) lands far below it.
PARITY_THRESHOLD = 0.99


@dataclass(frozen=True, slots=True)
class ParityReport:
    compared: int
    minimum: float
    mean: float

    @property
    def passed(self) -> bool:
        return self.compared > 0 and self.minimum >= PARITY_THRESHOLD


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        msg = f"cannot compare vectors of dimension {len(a)} and {len(b)}"
        raise ValueError(msg)
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm


def parity_report(
    *, stored: Sequence[Sequence[float]], fresh: Sequence[Sequence[float]]
) -> ParityReport:
    if len(stored) != len(fresh):
        msg = "stored and fresh samples must be the same length"
        raise ValueError(msg)
    scores = [cosine_similarity(s, f) for s, f in zip(stored, fresh, strict=True)]
    if not scores:
        return ParityReport(compared=0, minimum=0.0, mean=0.0)
    return ParityReport(compared=len(scores), minimum=min(scores), mean=sum(scores) / len(scores))
