from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.similarity import similar_transfers, weighted_distance

CONFIG = load_bidding_config()


def make_row(market_value=10_000_000, kauf_rank=50, start_probability=1, points_per_value=8e-6,
             market_value_change_day=0, position="MF"):
    return {
        "market_value": market_value, "kauf_rank": kauf_rank, "start_probability": start_probability,
        "points_per_value": points_per_value, "market_value_change_day": market_value_change_day,
        "position": position,
    }


def make_record(overpay_pct, dt="2026-09-14T00:00:00Z", backfilled=False, **kwargs):
    row = make_row(**kwargs)
    row.update({"overpay_pct": overpay_pct, "dt": dt, "backfilled": backfilled,
                "player_name": "X", "buyer": "Y"})
    return row


def test_identical_feature_vectors_have_zero_distance():
    a = make_row()
    b = make_row()
    assert weighted_distance(a, b, CONFIG) == 0.0


def test_missing_dimensions_are_skipped_not_penalized():
    a = make_row()
    b = {"market_value": a["market_value"]}  # everything else missing
    dist = weighted_distance(a, b, CONFIG)
    assert dist == 0.0  # only market_value comparable, and it matches exactly


def test_far_apart_players_have_larger_distance_than_close_ones():
    target = make_row(market_value=10_000_000, kauf_rank=50, start_probability=1)
    close = make_row(market_value=10_500_000, kauf_rank=55, start_probability=1)
    far = make_row(market_value=1_000_000, kauf_rank=400, start_probability=5)
    assert weighted_distance(target, close, CONFIG) < weighted_distance(target, far, CONFIG)


def test_similar_transfers_empty_log_returns_zero_confidence_shape():
    result = similar_transfers(make_row(), [], CONFIG)
    assert result["n"] == 0
    assert result["median_pct"] is None
    assert result["neighbors"] == []


def test_similar_transfers_prefers_closer_matches_in_median():
    target = make_row(market_value=10_000_000, kauf_rank=50, start_probability=1)
    log = [
        make_record(overpay_pct=15.0, market_value=10_200_000, kauf_rank=52, start_probability=1),
        make_record(overpay_pct=14.0, market_value=9_800_000, kauf_rank=48, start_probability=1),
        make_record(overpay_pct=-5.0, market_value=1_000_000, kauf_rank=400, start_probability=5),
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["n"] >= 2
    assert result["median_pct"] > 0  # dominated by the two close, positive-overpay records
