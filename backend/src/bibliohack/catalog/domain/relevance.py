"""Catalogue relevance — the intrinsic, precomputable score behind ``/browse``.

Every record gets a ``relevance_score`` ∈ [0,1] so the catalogue and search
lead with the *best* titles instead of "newest TITN first". The score is
**global** (intrinsic to a record, no per-user context — that's the library
*scope*, applied separately at query time) and **precomputable** (a nightly
batch over the availability time-series + holdings; off the OPAC path).

This module is the pure heart of Phase R: it knows nothing about SQL, sessions,
or HTTP. The repository extracts raw per-record signals from Postgres; this
module turns a whole corpus of those signals into scores. Splitting it this way
keeps the blend — and its many judgement calls — unit-testable without a DB.

The score is a **balanced blend of four corpus-normalised components**
(D3/D4 — demand carries the largest weight):

    demand        (0.45)  — pulled purely from the availability series
    holdings      (0.25)  — the library system's own buying signal
    recency       (0.20)  — keep the first look fresh
    completeness  (0.10)  — sparse/broken records shouldn't lead the page

Demand itself blends three sub-signals (D5 — trending is in v1, but built so it
can't run away on two weeks of data):

    scarcity   — share of observed copy-time that copies are loaned/reserved
    velocity   — available→loaned transitions per copy per week (checkouts)
    trending   — recent velocity vs the record's own baseline (acceleration),
                 shrunk toward neutral while history is thin

**Cold-start (no availability history):** the demand component is set
*neutral*, not zero, so a brand-new acquisition ranks on recency + completeness
+ holdings and is never buried under titles that merely had time to accrue
loans (R1 cold-start rule).

Normalisation note: unbounded counts (velocity, copies, branches) are
log-compressed then scaled against a corpus **p95** (not the max) so a single
runaway title can't flatten everyone else. Components that are already ratios
(scarcity, completeness) pass through directly.

**Canon boost (Phase C2).** On top of the four-component blend sits a
*positive-only* canon term: records the canon seed matched (a classic the RBPA
actually holds — see ``docs/design/canon-import.md``) get a small, capped
**additive** lift. It is applied *after* the blend, not mixed into it, so a
non-canon record is never penalised (the term is 0 for it) and a single award
can't dominate the four real signals. The lift is base (just for being a
matched classic) + notability (corpus-p95-scaled Wikipedia sitelinks) + an
award bump, the whole thing capped at ``CANON_MAX_BOOST``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.pub_year import max_plausible_pub_year

if TYPE_CHECKING:
    from datetime import datetime
    from typing import TypeGuard

# --- tunable constants -------------------------------------------------------

# Starting component weights (D4). Empirical — retune after ~1-2 months of
# availability history (see "thin demand history" risk in the design doc).
DEFAULT_DEMAND_WEIGHT = 0.45
DEFAULT_HOLDINGS_WEIGHT = 0.25
DEFAULT_RECENCY_WEIGHT = 0.20
DEFAULT_COMPLETENESS_WEIGHT = 0.10

# Demand sub-signal blend (within the demand component).
_SCARCITY_SUBWEIGHT = 0.45
_VELOCITY_SUBWEIGHT = 0.35
_TRENDING_SUBWEIGHT = 0.20

# Neutral value used for cold-start demand and a steady (non-accelerating)
# trend. 0.5, not 0 — see the cold-start rule in the module docstring.
NEUTRAL = 0.5

# Weeks of observation needed before the trending sub-signal gets full weight;
# below this it's linearly shrunk toward NEUTRAL so thin history can't dominate.
TREND_FULL_CONFIDENCE_WEEKS = 8.0

# Recency: gentle exponential decay on "first seen" age, ~6-month half-life.
FIRST_SEEN_HALF_LIFE_DAYS = 180.0

# Plausible publication-year band. Years outside it (0/negatives, and MARC
# "unknown date" sentinels like 9999) are treated as *unknown* → neutral
# recency, and excluded from the corpus min/max so a 9999 can't define the top
# of the recency scale and drag sentinel-year records to the front of /browse.
# The upper bound is the shared dynamic ceiling (current year + 1), see
# catalog.domain.pub_year — never a fixed far-future constant.
_MIN_PLAUSIBLE_PUB_YEAR = 1

# Completeness sub-weights (must sum to 1).
_COVER_SUBWEIGHT = 0.40
_SUMMARY_SUBWEIGHT = 0.30
_ISBN_SUBWEIGHT = 0.15
_SUBJECTS_SUBWEIGHT = 0.15

# Canon boost (C2). The canon *component* ∈ [0,1] is base + notability + award
# (sub-weights sum to 1); the final additive lift is CANON_MAX_BOOST * that
# component, so a matched marquee classic gains at most CANON_MAX_BOOST and a
# non-match gains nothing. Deliberately small: it nudges held classics up the
# ranking without overruling demand on the titles people are actually borrowing.
CANON_MAX_BOOST = 0.15
_CANON_BASE_SUBWEIGHT = 0.40  # just for being a matched, genuinely-held classic
_CANON_NOTABILITY_SUBWEIGHT = 0.40  # Wikipedia ubiquity (corpus-p95 scaled)
_CANON_AWARD_SUBWEIGHT = 0.20  # carries at least one literary award

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class RelevanceWeights:
    """The four top-level component weights. Normalised to sum to 1 on init."""

    demand: float = DEFAULT_DEMAND_WEIGHT
    holdings: float = DEFAULT_HOLDINGS_WEIGHT
    recency: float = DEFAULT_RECENCY_WEIGHT
    completeness: float = DEFAULT_COMPLETENESS_WEIGHT

    def normalised(self) -> RelevanceWeights:
        total = self.demand + self.holdings + self.recency + self.completeness
        if total <= _EPS:
            msg = "relevance weights must sum to a positive value"
            raise ValueError(msg)
        return RelevanceWeights(
            demand=self.demand / total,
            holdings=self.holdings / total,
            recency=self.recency / total,
            completeness=self.completeness / total,
        )


@dataclass(frozen=True, slots=True)
class RecordSignals:
    """Raw, un-normalised signals for one record, as read from the DB.

    The repository fills these from set-based SQL; this module never touches
    persistence. ``None``/empty history is meaningful (cold-start), so it is
    represented explicitly rather than as a zero.
    """

    record_id: object  # opaque to the domain (a UUID in practice)

    # Demand (availability series). All over a trailing window.
    has_history: bool
    observation_weeks: float  # span of usable snapshots, for trend shrinkage
    scarcity: float  # [0,1] share of observed copy-time loaned/reserved
    weekly_velocity: float  # available→loaned transitions per copy per week
    baseline_velocity: float  # velocity over the earlier part of the window

    # Holdings breadth.
    copies: int
    branches: int

    # Recency.
    pub_year: int | None
    first_seen_at: datetime | None

    # Display completeness.
    has_cover: bool
    has_summary: bool
    has_isbn: bool
    has_subjects: bool

    # Canon (C2). Whether the canon seed matched this record, and — if so — the
    # strongest matched work's notability (Wikipedia sitelinks) and award count.
    # Defaulted so pre-canon call sites and tests keep working unchanged; a
    # non-canon record carries is_canon=False and contributes no boost.
    is_canon: bool = False
    canon_notability: int = 0
    canon_award_count: int = 0


@dataclass(frozen=True, slots=True)
class CorpusStats:
    """Corpus-wide normalisation bounds, derived from every record's signals.

    Computed once per recompute run (``build_corpus_stats``) and then shared
    across every ``score_record`` call so components are comparable corpus-wide.
    """

    velocity_p95: float
    copies_p95: float
    branches_p95: float
    min_pub_year: int
    max_pub_year: int
    # p95 of canon notability over *matched* records — the ceiling the canon
    # notability sub-signal is log-scaled against. 0.0 when nothing matched.
    canon_notability_p95: float = 0.0


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    """The scored output for one record: the blend plus its breakdown."""

    score: float
    components: dict[str, float] = field(default_factory=dict)


# --- normalisation helpers ---------------------------------------------------


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct / 100.0 * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _is_plausible_pub_year(pub_year: int | None) -> TypeGuard[int]:
    """True for a real publication year; False for None or out-of-band values
    (0/negatives and MARC 'unknown date' sentinels like 9999). A TypeGuard so
    callers get `int` narrowing in both branches."""
    return pub_year is not None and _MIN_PLAUSIBLE_PUB_YEAR <= pub_year <= max_plausible_pub_year()


def _log_scale(value: float, p95: float) -> float:
    """log1p-compress an unbounded count, scaled to [0,1] against a p95 ceiling.

    Diminishing returns (the 50th copy matters far less than the 5th) and
    robust to outliers — the p95, not the max, is the top of the scale, so
    everything at or above p95 saturates at 1.0.
    """
    if p95 <= _EPS or value <= 0.0:
        return 0.0
    return _clamp01(math.log1p(value) / math.log1p(p95))


# --- corpus stats ------------------------------------------------------------


def build_corpus_stats(signals: list[RecordSignals]) -> CorpusStats:
    """Derive normalisation bounds from the whole corpus of raw signals."""
    velocities = sorted(s.weekly_velocity for s in signals if s.weekly_velocity > 0.0)
    copies = sorted(float(s.copies) for s in signals if s.copies > 0)
    branches = sorted(float(s.branches) for s in signals if s.branches > 0)
    years = [s.pub_year for s in signals if _is_plausible_pub_year(s.pub_year)]
    # Only matched canon records define the notability ceiling — an unmatched
    # record's (zero) notability would otherwise drag the p95 toward 0.
    canon_notability = sorted(
        float(s.canon_notability) for s in signals if s.is_canon and s.canon_notability > 0
    )

    min_year = min(years) if years else 0
    max_year = max(years) if years else 0
    return CorpusStats(
        velocity_p95=_percentile(velocities, 95.0),
        copies_p95=_percentile(copies, 95.0),
        branches_p95=_percentile(branches, 95.0),
        min_pub_year=min_year,
        max_pub_year=max_year,
        canon_notability_p95=_percentile(canon_notability, 95.0),
    )


# --- component scorers -------------------------------------------------------


def _trend_signal(s: RecordSignals) -> float:
    """Acceleration mapped to [0,1] (0.5 = steady), shrunk toward NEUTRAL while
    history is thin so two weeks of data can't make a title 'trending'."""
    if not s.has_history or s.baseline_velocity <= _EPS:
        # No baseline to accelerate from → treat as steady/neutral.
        accel = NEUTRAL
    else:
        ratio = s.weekly_velocity / s.baseline_velocity
        # ratio 1.0 → 0.5 (steady); 2.0+ → ~1.0; 0 → 0.0. Squashed, not linear.
        accel = _clamp01(0.5 * ratio) if ratio < 2.0 else 1.0
    confidence = _clamp01(s.observation_weeks / TREND_FULL_CONFIDENCE_WEEKS)
    return NEUTRAL + (accel - NEUTRAL) * confidence


def _demand_component(s: RecordSignals, corpus: CorpusStats) -> float:
    """Blend scarcity + velocity + trending. Neutral on cold-start (no history)."""
    if not s.has_history:
        return NEUTRAL
    scarcity = _clamp01(s.scarcity)
    velocity = _log_scale(s.weekly_velocity, corpus.velocity_p95)
    trending = _trend_signal(s)
    return (
        _SCARCITY_SUBWEIGHT * scarcity
        + _VELOCITY_SUBWEIGHT * velocity
        + _TRENDING_SUBWEIGHT * trending
    )


def _holdings_component(s: RecordSignals, corpus: CorpusStats) -> float:
    copies = _log_scale(float(s.copies), corpus.copies_p95)
    branches = _log_scale(float(s.branches), corpus.branches_p95)
    return 0.6 * copies + 0.4 * branches


def _recency_component(s: RecordSignals, corpus: CorpusStats, now: datetime) -> float:
    # Publication year, linearly placed within the corpus' year span. An
    # unknown/sentinel year (None, 0, 9999, …) is neutral, never the newest —
    # otherwise a MARC 9999 would top the recency scale (see _is_plausible_pub_year).
    if not _is_plausible_pub_year(s.pub_year) or corpus.max_pub_year <= corpus.min_pub_year:
        year_norm = NEUTRAL
    else:
        span = corpus.max_pub_year - corpus.min_pub_year
        year_norm = _clamp01((s.pub_year - corpus.min_pub_year) / span)

    # "First seen" recency — gentle exponential decay (half-life ~6 months) so
    # freshly ingested rows get a small, fading lift on the first look.
    if s.first_seen_at is None:
        first_seen_norm = NEUTRAL
    else:
        age_days = max(0.0, (now - s.first_seen_at).total_seconds() / 86400.0)
        first_seen_norm = 0.5 ** (age_days / FIRST_SEEN_HALF_LIFE_DAYS)

    return 0.6 * year_norm + 0.4 * first_seen_norm


def _completeness_component(s: RecordSignals) -> float:
    return (
        _COVER_SUBWEIGHT * float(s.has_cover)
        + _SUMMARY_SUBWEIGHT * float(s.has_summary)
        + _ISBN_SUBWEIGHT * float(s.has_isbn)
        + _SUBJECTS_SUBWEIGHT * float(s.has_subjects)
    )


def _canon_component(s: RecordSignals, corpus: CorpusStats) -> float:
    """Canon strength ∈ [0,1] for a record — 0 for anything not canon-matched.

    Positive-only: a non-match returns 0 (it adds nothing in ``score_record``,
    never subtracts). A match earns a base lift just for being a held classic,
    plus a notability term (log-scaled against the corpus p95 so one ultra-famous
    title can't flatten the rest) and an award bump. The three sub-weights sum to
    1, so the component saturates at 1.0 and the final additive boost is capped.
    """
    if not s.is_canon:
        return 0.0
    notability = _log_scale(float(s.canon_notability), corpus.canon_notability_p95)
    award = 1.0 if s.canon_award_count > 0 else 0.0
    return _clamp01(
        _CANON_BASE_SUBWEIGHT
        + _CANON_NOTABILITY_SUBWEIGHT * notability
        + _CANON_AWARD_SUBWEIGHT * award
    )


# --- public entry point ------------------------------------------------------


def score_record(
    signals: RecordSignals,
    corpus: CorpusStats,
    weights: RelevanceWeights,
    *,
    now: datetime,
) -> RelevanceResult:
    """Blend one record's signals into a final [0,1] score + its breakdown.

    ``now`` is injected (not read from the clock) so recency decay is
    deterministic and the whole thing stays unit-testable.
    """
    w = weights.normalised()
    demand = _clamp01(_demand_component(signals, corpus))
    holdings = _clamp01(_holdings_component(signals, corpus))
    recency = _clamp01(_recency_component(signals, corpus, now))
    completeness = _clamp01(_completeness_component(signals))
    canon = _canon_component(signals, corpus)

    blend = (
        w.demand * demand
        + w.holdings * holdings
        + w.recency * recency
        + w.completeness * completeness
    )
    # Positive-only, capped, additive: a non-canon record (canon=0) is left
    # exactly at its blend; a matched classic is lifted by at most CANON_MAX_BOOST.
    score = blend + CANON_MAX_BOOST * canon
    components = {
        "demand": round(demand, 6),
        "holdings": round(holdings, 6),
        "recency": round(recency, 6),
        "completeness": round(completeness, 6),
        "canon": round(canon, 6),
        "cold_start": float(not signals.has_history),
    }
    return RelevanceResult(score=_clamp01(score), components=components)
