from kickbase_tool.bidding.stats import (
    drop_extreme_outliers,
    market_value_class_label,
    recency_weight,
    robust_weighted_stats,
    weighted_median,
    weighted_percentile,
)


def test_weighted_median_matches_plain_median_with_equal_weights():
    values = [(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)]
    assert weighted_median(values) == 20.0


def test_weighted_median_shifts_toward_heavier_weight():
    values = [(10.0, 1.0), (20.0, 10.0), (30.0, 1.0)]
    assert weighted_median(values) == 20.0


def test_weighted_percentile_interpolates():
    values = [(0.0, 1.0), (100.0, 1.0)]
    assert weighted_percentile(values, 50.0) == 50.0


def test_weighted_median_empty_is_none():
    assert weighted_median([]) is None


def test_drop_extreme_outliers_removes_single_far_outlier():
    values = [(v, 1.0) for v in [10.0, 11.0, 9.0, 10.5, 9.5, 200.0]]
    cleaned = drop_extreme_outliers(values)
    cleaned_values = [v for v, _ in cleaned]
    assert 200.0 not in cleaned_values
    assert len(cleaned_values) == 5


def test_drop_extreme_outliers_keeps_all_when_too_few_points():
    values = [(10.0, 1.0), (500.0, 1.0)]
    assert len(drop_extreme_outliers(values)) == 2


def test_robust_weighted_stats_reports_n_and_percentiles():
    values = [(v, 1.0) for v in [10.0, 12.0, 14.0, 16.0, 18.0]]
    stats = robust_weighted_stats(values)
    assert stats["n"] == 5
    assert stats["median"] == 14.0
    assert stats["p25"] < stats["median"] < stats["p75"]


def test_robust_weighted_stats_empty_input():
    stats = robust_weighted_stats([])
    assert stats["median"] is None
    assert stats["n"] == 0


MARKET_VALUE_CLASS_BOUNDS = [3_000_000, 6_000_000, 10_000_000, 15_000_000, 20_000_000, 25_000_000, 30_000_000]


def test_market_value_class_label_boundaries():
    assert market_value_class_label(1_000_000, MARKET_VALUE_CLASS_BOUNDS) == "<3 Mio."
    assert market_value_class_label(3_000_000, MARKET_VALUE_CLASS_BOUNDS) == "3-6 Mio."
    assert market_value_class_label(9_999_999, MARKET_VALUE_CLASS_BOUNDS) == "6-10 Mio."


def test_market_value_class_label_top_bucket_is_plus():
    assert market_value_class_label(50_000_000, MARKET_VALUE_CLASS_BOUNDS) == "30 Mio.+"


def test_market_value_class_label_none_is_none():
    assert market_value_class_label(None, MARKET_VALUE_CLASS_BOUNDS) is None


def test_recency_weight_stages():
    schedule = [{"max_days": 7, "weight": 1.0}, {"max_days": 21, "weight": 0.5}, {"max_days": None, "weight": 0.2}]
    assert recency_weight(3, schedule) == 1.0
    assert recency_weight(7, schedule) == 1.0
    assert recency_weight(15, schedule) == 0.5
    assert recency_weight(100, schedule) == 0.2
    assert recency_weight(None, schedule) == 1.0
