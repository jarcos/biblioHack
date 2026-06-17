"""Unit tests for the catalogue relevance blend (Phase R, pure domain).

The repository (SQL) is exercised separately; here we pin the scoring contract:
score bounds, the four-component weighting, corpus normalisation, the
cold-start neutral-demand rule, and the thin-history trend shrinkage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bibliohack.catalog.domain.relevance import (
    NEUTRAL,
    RecordSignals,
    RelevanceWeights,
    build_corpus_stats,
    score_record,
)

NOW = datetime(2026, 6, 15, tzinfo=UTC)


def _signals(**overrides: object) -> RecordSignals:
    """A fully-populated, mid-range record; override fields per test."""
    base: dict[str, object] = {
        "record_id": "r",
        "has_history": True,
        "observation_weeks": 12.0,
        "scarcity": 0.5,
        "weekly_velocity": 1.0,
        "baseline_velocity": 1.0,
        "copies": 5,
        "branches": 3,
        "pub_year": 2024,
        "first_seen_at": NOW - timedelta(days=30),
        "has_cover": True,
        "has_summary": True,
        "has_isbn": True,
        "has_subjects": True,
    }
    base.update(overrides)
    return RecordSignals(**base)  # type: ignore[arg-type]


def test_weights_normalise_to_one() -> None:
    w = RelevanceWeights(demand=9, holdings=5, recency=4, completeness=2).normalised()
    assert w.demand + w.holdings + w.recency + w.completeness == pytest.approx(1.0)
    # Relative ordering preserved (demand largest — D4).
    assert w.demand > w.holdings > w.recency > w.completeness


def test_zero_weights_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        RelevanceWeights(demand=0, holdings=0, recency=0, completeness=0).normalised()


def test_score_is_bounded_unit_interval() -> None:
    sig = _signals()
    corpus = build_corpus_stats([sig])
    result = score_record(sig, corpus, RelevanceWeights(), now=NOW)
    assert 0.0 <= result.score <= 1.0


def test_components_breakdown_present() -> None:
    sig = _signals()
    corpus = build_corpus_stats([sig])
    comps = score_record(sig, corpus, RelevanceWeights(), now=NOW).components
    assert set(comps) == {"demand", "holdings", "recency", "completeness", "cold_start"}
    assert all(0.0 <= comps[k] <= 1.0 for k in ("demand", "holdings", "recency", "completeness"))


def test_cold_start_gets_neutral_demand_not_zero() -> None:
    """A record with no availability history must not be buried (R1 rule)."""
    cold = _signals(
        has_history=False,
        observation_weeks=0.0,
        scarcity=0.0,
        weekly_velocity=0.0,
        baseline_velocity=0.0,
    )
    corpus = build_corpus_stats([cold])
    result = score_record(cold, corpus, RelevanceWeights(), now=NOW)
    assert result.components["demand"] == pytest.approx(NEUTRAL)
    assert result.components["cold_start"] == 1.0


def test_cold_start_outranks_a_dead_title() -> None:
    """Brand-new (no history) should beat an in-corpus title with zero demand."""
    fresh = _signals(record_id="fresh", has_history=False, weekly_velocity=0.0, scarcity=0.0)
    dead = _signals(record_id="dead", scarcity=0.0, weekly_velocity=0.0, baseline_velocity=0.0)
    corpus = build_corpus_stats([fresh, dead])
    s_fresh = score_record(fresh, corpus, RelevanceWeights(), now=NOW).score
    s_dead = score_record(dead, corpus, RelevanceWeights(), now=NOW).score
    assert s_fresh > s_dead


def test_higher_demand_scores_higher() -> None:
    low = _signals(record_id="low", scarcity=0.1, weekly_velocity=0.2, baseline_velocity=0.2)
    high = _signals(record_id="high", scarcity=0.9, weekly_velocity=4.0, baseline_velocity=4.0)
    corpus = build_corpus_stats([low, high])
    s_low = score_record(low, corpus, RelevanceWeights(), now=NOW)
    s_high = score_record(high, corpus, RelevanceWeights(), now=NOW)
    assert s_high.score > s_low.score
    assert s_high.components["demand"] > s_low.components["demand"]


def test_more_holdings_scores_higher() -> None:
    few = _signals(record_id="few", copies=1, branches=1)
    many = _signals(record_id="many", copies=40, branches=20)
    corpus = build_corpus_stats([few, many])
    c_few = score_record(few, corpus, RelevanceWeights(), now=NOW).components
    c_many = score_record(many, corpus, RelevanceWeights(), now=NOW).components
    assert c_many["holdings"] > c_few["holdings"]


def test_completeness_rewards_full_records() -> None:
    full = _signals(record_id="full")
    sparse = _signals(
        record_id="sparse",
        has_cover=False,
        has_summary=False,
        has_isbn=False,
        has_subjects=False,
    )
    corpus = build_corpus_stats([full, sparse])
    c_full = score_record(full, corpus, RelevanceWeights(), now=NOW).components
    c_sparse = score_record(sparse, corpus, RelevanceWeights(), now=NOW).components
    assert c_full["completeness"] == pytest.approx(1.0)
    assert c_sparse["completeness"] == pytest.approx(0.0)


def test_trend_shrinks_toward_neutral_on_thin_history() -> None:
    """Same acceleration, thin vs thick history: thin must sit closer to neutral."""
    accel = {"weekly_velocity": 2.0, "baseline_velocity": 1.0}
    thin = _signals(record_id="thin", observation_weeks=1.0, **accel)
    thick = _signals(record_id="thick", observation_weeks=12.0, **accel)
    corpus = build_corpus_stats([thin, thick])
    d_thin = score_record(thin, corpus, RelevanceWeights(), now=NOW).components["demand"]
    d_thick = score_record(thick, corpus, RelevanceWeights(), now=NOW).components["demand"]
    # Accelerating title: more confidence (thicker history) → higher demand.
    assert d_thick > d_thin


def test_recency_prefers_newer_publication_year() -> None:
    old = _signals(record_id="old", pub_year=2023)
    new = _signals(record_id="new", pub_year=2026)
    corpus = build_corpus_stats([old, new])
    c_old = score_record(old, corpus, RelevanceWeights(), now=NOW).components
    c_new = score_record(new, corpus, RelevanceWeights(), now=NOW).components
    assert c_new["recency"] > c_old["recency"]


def test_sentinel_pub_year_is_neutral_not_newest() -> None:
    """A MARC 'unknown date' sentinel (9999) must NOT top the recency scale — it
    is treated as unknown (neutral), never as the newest year, and is excluded
    from the corpus max so it can't drag real years' normalisation."""
    real = _signals(record_id="real", pub_year=2026)
    older = _signals(record_id="older", pub_year=2020)
    sentinel = _signals(record_id="sentinel", pub_year=9999)
    corpus = build_corpus_stats([real, older, sentinel])
    # 9999 is ignored for the corpus span, so the real newest year defines it.
    assert corpus.max_pub_year == 2026
    assert corpus.min_pub_year == 2020
    c_real = score_record(real, corpus, RelevanceWeights(), now=NOW).components
    c_sentinel = score_record(sentinel, corpus, RelevanceWeights(), now=NOW).components
    # The sentinel record sits at neutral recency, below a genuinely recent one.
    assert c_sentinel["recency"] < c_real["recency"]


def test_velocity_normalised_against_corpus_p95() -> None:
    """A record's velocity sub-score depends on the corpus, not absolute counts."""
    target = _signals(record_id="t", weekly_velocity=2.0, baseline_velocity=2.0)
    # Same record, but in a corpus where 2.0/wk is huge vs one where it's tiny.
    small_corpus = build_corpus_stats([target, _signals(weekly_velocity=0.1)])
    big_corpus = build_corpus_stats([target, *[_signals(weekly_velocity=50.0) for _ in range(20)]])
    d_small = score_record(target, small_corpus, RelevanceWeights(), now=NOW).components["demand"]
    d_big = score_record(target, big_corpus, RelevanceWeights(), now=NOW).components["demand"]
    assert d_small > d_big


def test_empty_corpus_stats_are_safe() -> None:
    corpus = build_corpus_stats([])
    sig = _signals(has_history=False)
    # Must not raise on degenerate (zero) bounds.
    result = score_record(sig, corpus, RelevanceWeights(), now=NOW)
    assert 0.0 <= result.score <= 1.0
