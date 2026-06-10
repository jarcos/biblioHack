"""Recommendations domain — one suggested catalogue record for one user.

The aggregate is intentionally small: a recommendation is a *derived* fact
(re-computable from the shelf + catalogue at any time), so there are no
lifecycle invariants to defend — the interesting logic lives in how
candidates are retrieved and cached, behind the application ports.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A scored suggestion. `score` is cosine similarity in [0, 1]-ish space;
    `rationale` is the optional one-liner the LLM wrote for this user."""

    record_id: str
    score: float
    rationale: str | None = None
