from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.scoring import (
    CATEGORY_MARKTWERT,
    CATEGORY_UEBER_MARKTWERT,
    CATEGORY_WILL_HABEN,
    attractiveness,
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


def test_ppm_efficiency_has_no_market_value_dependent_fade():
    # Regressionstest fuer die entfernte Weight-Fade (Nutzervorgabe): die MW-
    # Abhaengigkeit steckt bereits in den PPM-Schwellen selbst
    # (ppm_thresholds_for), ein zusaetzlicher Weight-Fade wuerde den Marktwert
    # doppelt beruecksichtigen. Dieselbe PKT/MIO-Effizienz-Note muss deshalb
    # bei jedem Marktwert das volle konfigurierte Gewicht (20%) bekommen.
    cheap = attractiveness(
        {"market_value": 2_000_000, "points_per_value": 10.0 / 1_000_000, "kauf_rank": 50,
         "start_probability": 1, "market_value_change_day": 0, "season_avg": 5.0},
        None, {}, CONFIG,
    )
    expensive = attractiveness(
        {"market_value": 35_000_000, "points_per_value": 5.5 / 1_000_000, "kauf_rank": 50,
         "start_probability": 1, "market_value_change_day": 0, "season_avg": 5.0},
        None, {}, CONFIG,
    )
    # 10.0 Pkt/Mio bei <5M und 5.5 Pkt/Mio bei 30M+ liegen beide exakt auf der
    # "gut"-Schwelle ihrer jeweiligen MW-Klasse -> identischer ppm_efficiency-Wert.
    assert cheap["components"]["ppm_efficiency"] == expensive["components"]["ppm_efficiency"]


def test_bad_rank_and_ausgeschlossen_lands_at_marktwert_despite_strong_trend():
    # MW ~4.653M, MW-Steigerung ~+373k/Tag, Rang ~218, Startchance
    # Ausgeschlossen. Mit der rang-/startchance-lastigen Gewichtung (35%/30%)
    # und dem niedrigen Ausgeschlossen-Wert (0.10) reicht ein starker MW-Trend
    # allein nicht mehr aus, um ueber MARKTWERT hinauszukommen -- der Trend
    # beeinflusst bewusst vor allem den Overpay (pricing.py), nicht die
    # Grundkategorie (siehe Aufgabenstellung: "soll aber niemals einen
    # sportlich schlechten Nichtstarter allein zum Must-have machen").
    row = {
        "market_value": 4_653_000, "market_value_change_day": 373_000,
        "kauf_rank": 218, "start_probability": 5, "points_per_value": None,
        "season_avg": 3.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["category"] == CATEGORY_MARKTWERT


def test_start_probability_cap_still_engages_when_score_would_otherwise_be_higher():
    # Direkter Test der harten Deckelung (bleibt bestehen, Nutzervorgabe): ein
    # sonst sehr starker Spieler (Top-Rang, exzellente Effizienz, maximaler
    # Trend) wuerde ohne die Deckelung WILL_ICH_HABEN erreichen -- mit
    # Startchance Ausgeschlossen darf er trotzdem nicht ueber UEBER_MARKTWERT
    # hinaus.
    row = {
        "market_value": 3_000_000, "market_value_change_day": 600_000,
        "kauf_rank": 5, "start_probability": 5, "points_per_value": 20.0 / 1_000_000,
        "season_avg": 5.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["score"] >= CONFIG["category_thresholds"]["will_haben"]  # Deckelung greift, nicht die Kategorie selbst
    assert result["category"] == CATEGORY_UEBER_MARKTWERT


def test_schlotterbeck_reaches_will_haben_despite_low_ppm_efficiency():
    # Starker Rang (35%) und sichere Startchance (30%) allein reichen mit den
    # aktuellen Gewichten nicht ganz bis ALL_IN, wenn die PKT/MIO-Effizienz
    # (20%) deutlich unterdurchschnittlich ist und kein MW-Trend (15%,
    # neutral bei 0.5) gegensteuert -- WILL_HABEN statt ALL_IN, aber
    # weiterhin klar nicht in einer niedrigeren Kategorie (absolute
    # sportliche Qualitaet zaehlt trotzdem noch spuerbar).
    row = {
        "market_value": 35_000_000, "market_value_change_day": 0,
        "kauf_rank": 15, "start_probability": 1,
        "points_per_value": 4.0 / 1_000_000,  # 4.0 Pkt/Mio -- unter dem "gut"-Schwellenwert fuer diese MW-Klasse
        "season_avg": 8.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["category"] == CATEGORY_WILL_HABEN


def test_dinkci_style_player_rank_now_weighs_more_heavily():
    # MW ~7.199M, starker MW-Trend, Rang 245 (schlecht), aber sichere
    # Startchance. Mit der neuen, rang-lastigen Gewichtung (35% statt vorher
    # gleichgewichtet) zieht der schlechte Rang die Kategorie jetzt auf
    # UEBER_MARKTWERT statt (wie zuvor bei Gleichgewichtung) WILL_ICH_HABEN --
    # explizite, gewollte Folge der neuen Gewichte (Rang bildet den
    # langfristigen sportlichen Gesamtwert am staerksten ab).
    row = {
        "market_value": 7_199_000, "market_value_change_day": 267_000,
        "kauf_rank": 245, "start_probability": 1, "points_per_value": None,
        "season_avg": 6.0, "status": "fit",
    }
    result = attractiveness(row, snapshot_history=None, trend={}, config=CONFIG)
    assert result["category"] == CATEGORY_UEBER_MARKTWERT


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
