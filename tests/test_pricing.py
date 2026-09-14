from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.scoring import (
    CATEGORY_ALL_IN,
    CATEGORY_MARKTWERT,
    CATEGORY_UEBER_MARKTWERT,
    attractiveness,
)
from kickbase_tool.bidding.pricing import (
    _category_bounds,
    _confidence,
    _rule_based_overpay_pct,
    recommend_bid,
)

CONFIG = load_bidding_config()

NEUTRAL_MARKET_FACTOR = {"shift_pct": 0.0, "label": "neutral"}


def test_category_bounds_cover_full_0_to_1_range_without_gaps():
    thresholds = CONFIG["category_thresholds"]
    assert _category_bounds("all_in", CONFIG) == (thresholds["all_in"], 1.0)
    assert _category_bounds("will_haben", CONFIG) == (thresholds["will_haben"], thresholds["all_in"])
    assert _category_bounds("ueber_marktwert", CONFIG) == (thresholds["ueber_marktwert"], thresholds["will_haben"])
    assert _category_bounds("marktwert", CONFIG) == (0.0, thresholds["ueber_marktwert"])


def test_rule_based_overpay_increases_with_score_within_band():
    thresholds = CONFIG["category_thresholds"]
    low_score = thresholds["ueber_marktwert"] + 0.001
    high_score = thresholds["will_haben"] - 0.001
    low_pct = _rule_based_overpay_pct("ueber_marktwert", low_score, CONFIG)
    high_pct = _rule_based_overpay_pct("ueber_marktwert", high_score, CONFIG)
    assert high_pct > low_pct


def test_confidence_zero_neighbors_is_low():
    result = _confidence(None, CONFIG)
    assert result["bucket"] == "rot"
    assert result["confidence"] < 0.4


def test_confidence_many_tight_neighbors_is_high():
    similar = {"n": 20, "p25_pct": 10.0, "p75_pct": 12.0}
    result = _confidence(similar, CONFIG)
    assert result["bucket"] == "gruen"


def test_confidence_many_but_widely_spread_neighbors_is_downgraded():
    tight = _confidence({"n": 20, "p25_pct": 10.0, "p75_pct": 12.0}, CONFIG)
    wide = _confidence({"n": 20, "p25_pct": -10.0, "p75_pct": 40.0}, CONFIG)
    assert wide["confidence"] < tight["confidence"]


def test_weak_marktwert_player_recommends_no_bid():
    row = {
        "market_value": 3_000_000, "market_value_change_day": 0,
        "kauf_rank": 400, "start_probability": 5, "points_per_value": 0.0,
        "season_avg": 2.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert attr["category"] == CATEGORY_MARKTWERT

    result = recommend_bid(
        {"market_value": row["market_value"]}, attr, None, None, NEUTRAL_MARKET_FACTOR, CONFIG
    )
    assert result["no_bid"] is True
    assert result["bid_upper"] is None
    assert result["overpay_pct"] is None


def test_all_in_player_cold_start_produces_positive_overpay_above_market_value():
    row = {
        "market_value": 35_000_000, "market_value_change_day": 0,
        "kauf_rank": 15, "start_probability": 1,
        "points_per_value": 4.0 / 1_000_000,
        "season_avg": 8.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert attr["category"] == CATEGORY_ALL_IN

    result = recommend_bid(
        {"market_value": row["market_value"]}, attr, None, None, NEUTRAL_MARKET_FACTOR, CONFIG
    )
    assert result["no_bid"] is False
    assert result["bid_upper"] > row["market_value"]
    assert result["bid_lower"] > row["market_value"]
    assert result["bid_lower"] < result["bid_upper"]
    assert result["overpay_abs"] == result["bid_upper"] - row["market_value"]
    assert result["overpay_pct"] > 0
    assert result["empirical_weight"] == 0.0  # keine aehnlichen Transfers vorhanden


def test_reggiani_style_player_lands_in_ueber_marktwert_with_moderate_overpay():
    row = {
        "market_value": 4_653_000, "market_value_change_day": 373_000,
        "kauf_rank": 218, "start_probability": 5, "points_per_value": None,
        "season_avg": 3.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert attr["category"] == CATEGORY_UEBER_MARKTWERT

    result = recommend_bid(
        {"market_value": row["market_value"]}, attr, None, None, NEUTRAL_MARKET_FACTOR, CONFIG
    )
    assert result["no_bid"] is False
    assert result["category"] == CATEGORY_UEBER_MARKTWERT
    assert result["bid_upper"] >= row["market_value"]


def test_empirical_similar_transfers_dominate_when_target_n_reached():
    row = {
        "market_value": 10_000_000, "market_value_change_day": 0,
        "kauf_rank": 60, "start_probability": 2, "points_per_value": 8.0 / 1_000_000,
        "season_avg": 5.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    target_n = CONFIG["similar_transfers_target_n"]

    similar_result = {"n": target_n, "median_pct": 50.0, "p25_pct": 48.0, "p75_pct": 52.0}
    result = recommend_bid(
        {"market_value": row["market_value"]}, attr, similar_result, None, NEUTRAL_MARKET_FACTOR, CONFIG
    )
    assert result["empirical_weight"] == 1.0
    # bei vollem empirischem Gewicht dominiert der empirische Median (plus
    # kleiner Trend-Bonus/Marktfaktor) klar gegenueber dem regelbasierten Wert.
    assert result["overpay_pct"] > 40.0
    assert result["confidence_bucket"] == "gruen"


def test_class_tier_stats_used_as_fallback_when_no_similar_transfers():
    row = {
        "market_value": 10_000_000, "market_value_change_day": 0,
        "kauf_rank": 60, "start_probability": 2, "points_per_value": 8.0 / 1_000_000,
        "season_avg": 5.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    class_tier_stats = {"n": 15, "median": 30.0}

    result = recommend_bid(
        {"market_value": row["market_value"]}, attr, None, class_tier_stats, NEUTRAL_MARKET_FACTOR, CONFIG
    )
    assert result["empirical_weight"] > 0.0
    assert result["overpay_pct"] > 0.0


def test_market_factor_shift_moves_overpay_up_or_down():
    row = {
        "market_value": 10_000_000, "market_value_change_day": 0,
        "kauf_rank": 60, "start_probability": 2, "points_per_value": 8.0 / 1_000_000,
        "season_avg": 5.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)

    neutral = recommend_bid({"market_value": row["market_value"]}, attr, None, None, NEUTRAL_MARKET_FACTOR, CONFIG)
    aggressive = recommend_bid(
        {"market_value": row["market_value"]}, attr, None, None,
        {"shift_pct": 4.0, "label": "aktuell aggressiv"}, CONFIG,
    )
    assert aggressive["overpay_pct"] > neutral["overpay_pct"]


def test_reasons_include_market_context_label():
    row = {
        "market_value": 10_000_000, "market_value_change_day": 0,
        "kauf_rank": 60, "start_probability": 2, "points_per_value": 8.0 / 1_000_000,
        "season_avg": 5.0, "status": "fit",
    }
    attr = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    result = recommend_bid(
        {"market_value": row["market_value"]}, attr, None, None,
        {"shift_pct": 0.0, "label": "aktuell zurueckhaltend"}, CONFIG,
    )
    assert any("aktuell zurueckhaltend" in r for r in result["reasons"])
