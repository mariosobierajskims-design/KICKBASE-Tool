from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.similarity import (
    is_comparable,
    market_value_window_pct,
    similar_transfers,
)

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


def test_window_grows_with_market_value():
    low = market_value_window_pct(2_000_000, CONFIG)
    high = market_value_window_pct(32_000_000, CONFIG)
    assert low < high


def test_candidate_within_window_and_same_position_is_comparable():
    target = make_row(market_value=10_000_000, position="MF")
    candidate = make_row(market_value=10_500_000, position="MF")  # +5%, weit innerhalb des 10-15M-Fensters (30%)
    assert is_comparable(target, candidate, CONFIG) is True


def test_candidate_outside_window_is_not_comparable():
    # 2 Mio. vs. 4 Mio.: Marktwertklasse <3M hat das engste Fenster (15%), ein
    # 100%-Aufschlag liegt weit ausserhalb.
    target = make_row(market_value=2_000_000)
    candidate = make_row(market_value=4_000_000)
    assert is_comparable(target, candidate, CONFIG) is False


def test_same_relative_gap_tolerated_at_high_market_value_not_at_low():
    # Derselbe relative Abstand (+35%) wird bei niedrigem Marktwert
    # ausgeschlossen (Fenster 15%), bei hohem Marktwert aber toleriert
    # (Fenster 75% fuer 30M+) -- genau die vom Nutzer gewuenschte Skalierung.
    low_target = make_row(market_value=2_000_000)
    low_candidate = make_row(market_value=2_700_000)
    assert is_comparable(low_target, low_candidate, CONFIG) is False

    high_target = make_row(market_value=32_000_000)
    high_candidate = make_row(market_value=43_200_000)
    assert is_comparable(high_target, high_candidate, CONFIG) is True


def test_different_position_is_not_comparable_even_within_window():
    target = make_row(market_value=10_000_000, position="ST")
    candidate = make_row(market_value=10_100_000, position="TW")
    assert is_comparable(target, candidate, CONFIG) is False


def test_missing_position_does_not_disqualify():
    target = make_row(market_value=10_000_000, position=None)
    candidate = make_row(market_value=10_100_000, position="ST")
    assert is_comparable(target, candidate, CONFIG) is True


def test_similar_transfers_empty_log_returns_zero_confidence_shape():
    result = similar_transfers(make_row(), [], CONFIG)
    assert result["n"] == 0
    assert result["median_pct"] is None
    assert result["neighbors"] == []


def test_similar_transfers_excludes_out_of_window_and_different_position():
    target = make_row(market_value=10_000_000, position="ST")
    log = [
        make_record(overpay_pct=15.0, market_value=10_200_000, position="ST"),
        make_record(overpay_pct=999.0, market_value=500_000, position="TW"),  # weder Fenster noch Position passen
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["n"] == 1
    assert result["median_pct"] == 15.0


def test_similar_transfers_keeps_only_the_most_recent_max_k():
    # Rein chronologisch: von mehr vergleichbaren Treffern als max_k zaehlen
    # nur die zeitlich juengsten -- explizite Nutzervorgabe fuer Aktualitaet.
    max_k = CONFIG["similar_transfers_max_k"]
    target = make_row(market_value=10_000_000, position="MF")
    old_records = [
        make_record(overpay_pct=-50.0, dt=f"2020-01-{i:02d}T00:00:00Z", market_value=10_000_000, position="MF")
        for i in range(1, max_k + 1)
    ]
    recent_records = [
        make_record(overpay_pct=20.0, dt=f"2026-09-{i:02d}T00:00:00Z", market_value=10_000_000, position="MF")
        for i in range(1, max_k + 1)
    ]
    result = similar_transfers(target, old_records + recent_records, CONFIG)
    assert result["n_considered"] == max_k
    # nur die (positiven) juengsten Treffer duerfen den Median bestimmen
    assert result["median_pct"] == 20.0


def test_similar_transfers_tracks_n_fresh_separately_from_n():
    target = make_row(market_value=10_000_000, position="MF")
    log = [
        make_record(overpay_pct=10.0, market_value=10_100_000, position="MF", backfilled=True),
        make_record(overpay_pct=12.0, market_value=9_900_000, position="MF", backfilled=False),
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["n"] == 2
    assert result["n_fresh"] == 1
