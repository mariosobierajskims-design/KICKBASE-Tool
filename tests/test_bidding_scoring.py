from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.scoring import (
    CATEGORY_ALL_IN,
    CATEGORY_UEBER_MARKTWERT,
    CATEGORY_WILL_HABEN,
    attractiveness,
    ppm_efficiency_weight,
    ppm_thresholds_for,
    rank_tier_score,
    start_probability_score,
)

CONFIG = load_bidding_config()


def test_ppm_thresholds_match_spec_table_for_cheap_and_expensive_players():
    cheap = ppm_thresholds_for(2_000_000)
    assert cheap["min"] == 8.0 and cheap["good"] == 10.0 and cheap["top"] == 13.0

    expensive = ppm_thresholds_for(35_000_000)
    assert expensive["min"] == 4.5 and expensive["good"] == 5.5 and expensive["top"] == 7.0


def test_rank_tier_score_bands_are_monotonically_decreasing():
    s1 = rank_tier_score(10, CONFIG)
    s2 = rank_tier_score(30, CONFIG)
    s3 = rank_tier_score(70, CONFIG)
    s4 = rank_tier_score(120, CONFIG)
    s5 = rank_tier_score(300, CONFIG)
    assert s1 > s2 > s3 > s4 > s5
    assert s5 > 0  # schlechter Rang wird nicht auf 0 abgestraft


def test_start_probability_score_ausgeschlossen_is_not_zero():
    sicher = start_probability_score(1, CONFIG)
    ausgeschlossen = start_probability_score(5, CONFIG)
    assert sicher > ausgeschlossen
    assert ausgeschlossen > 0.0  # explizite Vorgabe: "kann trotzdem eingewechselt werden"


def test_ppm_efficiency_weight_fades_for_expensive_players():
    assert ppm_efficiency_weight(5_000_000, CONFIG) == 1.0
    assert ppm_efficiency_weight(50_000_000, CONFIG) == CONFIG["ppm_efficiency_fade_min_weight"]
    mid = ppm_efficiency_weight(27_500_000, CONFIG)  # midpoint of 15M-40M fade
    assert 0.35 < mid < 1.0


def test_reggiani_capped_below_will_haben_despite_strong_trend():
    # Aus der Aufgabenstellung: MW ~4.653M, MW-Steigerung ~+373k/Tag, Rang ~218,
    # Startchance Ausgeschlossen -> erwartete Kategorie ist UEBER_MARKTWERT,
    # NICHT WILL_ICH_HABEN, obwohl der MW-Trend fuer sich genommen stark waere.
    row = {
        "market_value": 4_653_000, "market_value_change_day": 373_000,
        "kauf_rank": 218, "start_probability": 5, "points_per_value": None,
        "season_avg": 3.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["category"] == CATEGORY_UEBER_MARKTWERT


def test_schlotterbeck_reaches_all_in_despite_low_ppm_efficiency():
    # Starker Rang, sichere Startchance, hoher Marktwert mit unterdurch-
    # schnittlicher PKT/MIO-Effizienz -- soll trotzdem ALL IN erreichen, weil
    # absolute sportliche Qualitaet bei teuren Topspielern schwerer wiegt als
    # maximale Kapitaleffizienz (siehe Aufgabenstellung).
    row = {
        "market_value": 35_000_000, "market_value_change_day": 0,
        "kauf_rank": 15, "start_probability": 1,
        "points_per_value": 4.0 / 1_000_000,  # 4.0 Pkt/Mio -- unter dem "gut"-Schwellenwert fuer diese MW-Klasse
        "season_avg": 8.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["category"] == CATEGORY_ALL_IN


def test_dinkci_style_player_is_not_dragged_down_by_bad_rank_alone():
    # MW ~7.199M, starker MW-Trend, Rang 245 (schlecht), aber sichere
    # Startchance -- soll trotz schlechtem Rang mindestens WILL_ICH_HABEN
    # erreichen (Kalibrierungsbeispiel aus der Aufgabenstellung: hoher Preis
    # kam nicht primaer vom Rang).
    row = {
        "market_value": 7_199_000, "market_value_change_day": 267_000,
        "kauf_rank": 245, "start_probability": 1, "points_per_value": None,
        "season_avg": 6.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["category"] in (CATEGORY_WILL_HABEN, CATEGORY_ALL_IN)


def test_small_sample_relativizes_bad_rank():
    base_row = {
        "market_value": 5_000_000, "market_value_change_day": 0,
        "kauf_rank": 300, "start_probability": 3, "points_per_value": None,
        "status": "fit",
    }
    with_sample = attractiveness({**base_row, "season_avg": 5.0}, None, {}, CONFIG)
    without_sample = attractiveness({**base_row, "season_avg": None}, None, {}, CONFIG)
    assert without_sample["components"]["rank_tier"] > with_sample["components"]["rank_tier"]
    assert any("Stichprobe" in flag for flag in without_sample["special_cases"])
