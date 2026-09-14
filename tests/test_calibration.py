from datetime import datetime, timedelta, timezone

from kickbase_tool.bidding.calibration import (
    lookup_class_tier_stats,
    market_stats_by_class_and_tier,
    overall_market_factor,
    record_weight,
)
from kickbase_tool.bidding.config import load_bidding_config

CONFIG = load_bidding_config()
NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_transfer(overpay_pct, days_ago=1, market_value=10_000_000, kauf_rank=50, backfilled=False):
    return {
        "overpay_pct": overpay_pct, "dt": iso(days_ago), "market_value": market_value,
        "kauf_rank": kauf_rank, "backfilled": backfilled,
    }


def test_record_weight_decays_with_age():
    fresh = record_weight(make_transfer(10.0, days_ago=1), CONFIG, now=NOW)
    medium = record_weight(make_transfer(10.0, days_ago=14), CONFIG, now=NOW)
    old = record_weight(make_transfer(10.0, days_ago=60), CONFIG, now=NOW)
    assert fresh > medium > old


def test_record_weight_reduced_for_backfilled_records():
    normal = record_weight(make_transfer(10.0, days_ago=1, backfilled=False), CONFIG, now=NOW)
    backfilled = record_weight(make_transfer(10.0, days_ago=1, backfilled=True), CONFIG, now=NOW)
    assert backfilled < normal
    assert backfilled == normal * CONFIG["backfilled_weight_factor"]


def test_overall_market_factor_neutral_on_empty_log():
    result = overall_market_factor([], CONFIG, now=NOW)
    assert result["label"] == "neutral"
    assert result["shift_pct"] == 0.0
    assert result["overall_n"] == 0


def test_overall_market_factor_detects_recent_aggressive_shift():
    # Viele aeltere, niedrig gewichtete Transfers muessen in Summe mehr
    # Gewicht tragen als die wenigen juengsten, damit der Gesamt-Median
    # tatsaechlich beim alten (ruhigeren) Niveau bleibt und die juengste
    # Teilmenge als klarer Ausschlag sichtbar wird.
    log = (
        [make_transfer(5.0, days_ago=d) for d in range(10, 200, 5)]
        + [make_transfer(30.0, days_ago=d) for d in range(1, 6)]
    )
    result = overall_market_factor(log, CONFIG, now=NOW)
    assert result["shift_pct"] > 0
    assert result["label"] == "aktuell aggressiv"


def test_overall_market_factor_shift_is_capped():
    log = [make_transfer(-50.0, days_ago=d) for d in range(10, 200, 5)] + [
        make_transfer(500.0, days_ago=d) for d in range(1, 6)
    ]
    result = overall_market_factor(log, CONFIG, now=NOW)
    cap = CONFIG["market_factor_max_shift_pct"]
    assert result["shift_pct"] == cap


def test_market_stats_by_class_and_tier_segments_by_bucket():
    log = [
        make_transfer(10.0, market_value=2_000_000, kauf_rank=10, days_ago=1),
        make_transfer(12.0, market_value=2_500_000, kauf_rank=15, days_ago=2),
        make_transfer(50.0, market_value=25_000_000, kauf_rank=300, days_ago=1),
    ]
    stats = market_stats_by_class_and_tier(log, CONFIG, now=NOW)
    cheap_top_key = (0, 0)  # unter 3M, Rang-Tier 0 (<=20)
    assert cheap_top_key in stats
    assert stats[cheap_top_key]["n"] == 2


def test_lookup_class_tier_stats_returns_none_when_segment_missing():
    log = [make_transfer(10.0, market_value=2_000_000, kauf_rank=10, days_ago=1)]
    stats_by_key = market_stats_by_class_and_tier(log, CONFIG, now=NOW)
    result = lookup_class_tier_stats(stats_by_key, market_value=28_000_000, kauf_rank=200, config=CONFIG)
    assert result is None


def test_lookup_class_tier_stats_returns_matching_segment():
    log = [
        make_transfer(10.0, market_value=2_000_000, kauf_rank=10, days_ago=1),
        make_transfer(14.0, market_value=2_200_000, kauf_rank=12, days_ago=2),
    ]
    stats_by_key = market_stats_by_class_and_tier(log, CONFIG, now=NOW)
    result = lookup_class_tier_stats(stats_by_key, market_value=2_100_000, kauf_rank=11, config=CONFIG)
    assert result is not None
    assert result["n"] == 2
