from kickbase_tool.bidding.backtest import run_backtest
from kickbase_tool.bidding.config import load_bidding_config

CONFIG = load_bidding_config()


def make_transfer(player_id, overpay_pct, dt, market_value=10_000_000, kauf_rank=50,
                   start_probability=1, points_per_value=8e-6, market_value_change_day=0,
                   position="MF", status="fit", backfilled=False, bid_count=1):
    price = market_value * (1 + overpay_pct / 100.0)
    return {
        "player_id": player_id, "player_name": f"Player{player_id}", "buyer": "X",
        "dt": dt, "market_value": market_value, "kauf_rank": kauf_rank,
        "start_probability": start_probability, "points_per_value": points_per_value,
        "market_value_change_day": market_value_change_day, "position": position, "status": status,
        "transfer_price": price, "overpay_pct": overpay_pct, "overpay_abs": price - market_value,
        "backfilled": backfilled, "bid_count": bid_count,
    }


def test_run_backtest_never_raises_and_returns_expected_shape():
    log = [
        make_transfer("1", 10.0, "2026-08-01T00:00:00Z"),
        make_transfer("2", 15.0, "2026-08-10T00:00:00Z"),
        make_transfer("3", 8.0, "2026-08-20T00:00:00Z"),
    ]
    result = run_backtest(log, CONFIG)
    assert "by_category" in result
    assert "by_market_value_class" in result
    assert result["n_total"] + result["n_skipped_no_bid_or_missing_data"] == len(log)


def test_run_backtest_only_uses_strictly_earlier_transfers():
    # Der erste Transfer chronologisch darf NIE einen spaeteren Transfer als
    # Vergleich verwenden (Look-ahead-Bias) -- ueberpruefbar daran, dass ein
    # Backtest mit nur einem einzigen (dem fruehesten) Transfer exakt dasselbe
    # Ergebnis fuer diesen Transfer liefert wie ein Backtest mit dem vollen Log.
    earliest = make_transfer("1", 10.0, "2026-08-01T00:00:00Z", market_value=10_000_000, kauf_rank=50)
    later = make_transfer("2", 90.0, "2026-09-01T00:00:00Z", market_value=10_000_000, kauf_rank=50)

    result_full = run_backtest([earliest, later], CONFIG)
    result_single = run_backtest([earliest], CONFIG)

    row_full = next(r for r in result_full["rows"] if r["player_id"] == "1")
    row_single = next(r for r in result_single["rows"] if r["player_id"] == "1")
    assert row_full["recommended_bid_upper"] == row_single["recommended_bid_upper"]


def test_run_backtest_hit_rate_is_between_zero_and_one():
    log = [make_transfer(str(i), overpay, f"2026-08-{(i % 28) + 1:02d}T00:00:00Z")
           for i, overpay in enumerate([5, 8, 10, 12, 15, 20, 3, 7, 25, 30])]
    result = run_backtest(log, CONFIG)
    for stats in result["by_category"].values():
        if stats["n"]:
            assert 0.0 <= stats["hit_rate"] <= 1.0


def test_run_backtest_empty_log():
    result = run_backtest([], CONFIG)
    assert result["n_total"] == 0
    assert result["rows"] == []
