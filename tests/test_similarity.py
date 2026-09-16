from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.similarity import (
    hard_cutoff_reasons,
    similar_transfers,
    similarity_score,
)

CONFIG = load_bidding_config()


def make_row(market_value=10_000_000, kauf_rank=50, start_probability=1, points_per_value=8e-6,
             market_value_change_day=0, position="MF", status="fit", season_avg=6.0, team_form=0.5):
    return {
        "market_value": market_value, "kauf_rank": kauf_rank, "start_probability": start_probability,
        "points_per_value": points_per_value, "market_value_change_day": market_value_change_day,
        "position": position, "status": status, "season_avg": season_avg, "team_form": team_form,
    }


def make_record(overpay_pct, dt="2026-09-14T00:00:00Z", backfilled=False, bid_count=1, **kwargs):
    row = make_row(**kwargs)
    row.update({
        "overpay_pct": overpay_pct, "dt": dt, "backfilled": backfilled, "bid_count": bid_count,
        "player_name": "X", "buyer": "Y", "transfer_price": row["market_value"] * (1 + overpay_pct / 100.0),
    })
    return row


# ---------------------------------------------------------------------------
# similarity_score: kontinuierliche Distanz statt fester Gruppen
# ---------------------------------------------------------------------------

def test_identical_profile_has_similarity_one():
    row = make_row()
    assert similarity_score(row, dict(row), None, CONFIG) == 1.0


def test_rank_45_more_similar_to_55_than_to_150():
    target = make_row(kauf_rank=45)
    close = make_row(kauf_rank=55)
    far = make_row(kauf_rank=150)
    sim_close = similarity_score(target, close, None, CONFIG)
    sim_far = similarity_score(target, far, None, CONFIG)
    assert sim_close > sim_far


def test_market_value_9_vs_11_more_similar_than_9_vs_25():
    target = make_row(market_value=9_000_000)
    close = make_row(market_value=11_000_000)
    far = make_row(market_value=25_000_000)
    sim_close = similarity_score(target, close, None, CONFIG)
    sim_far = similarity_score(target, far, None, CONFIG)
    assert sim_close > sim_far


def test_start_probability_sicher_more_similar_to_erwartet_than_to_ausgeschlossen():
    target = make_row(start_probability=1)
    erwartet = make_row(start_probability=2)
    ausgeschlossen = make_row(start_probability=5)
    assert similarity_score(target, erwartet, None, CONFIG) > similarity_score(target, ausgeschlossen, None, CONFIG)


def test_missing_dimension_is_neutral_not_disqualifying():
    target = make_row(season_avg=None, team_form=None)
    candidate = make_row(season_avg=10.0, team_form=0.9)
    score = similarity_score(target, candidate, None, CONFIG)
    assert 0.0 < score < 1.0  # weder 0 (Absturz) noch automatisch 1.0


# ---------------------------------------------------------------------------
# hard_cutoff_reasons: fundamentale Ausschluesse, unabhaengig von der Distanz
# ---------------------------------------------------------------------------

def test_missing_market_value_is_cut_off():
    target = make_row(market_value=None)
    candidate = make_row()
    assert hard_cutoff_reasons(target, candidate, CONFIG) != []


def test_sicher_vs_ausgeschlossen_is_cut_off():
    target = make_row(start_probability=1)
    candidate = make_row(start_probability=5)
    assert hard_cutoff_reasons(target, candidate, CONFIG) != []


def test_erwartet_vs_unsicher_is_not_cut_off():
    # "Unsicher" (3) ueberbrueckt beide Seiten -- kein harter Ausschluss,
    # nur eine (moderate) Distanz.
    target = make_row(start_probability=2)
    candidate = make_row(start_probability=3)
    assert hard_cutoff_reasons(target, candidate, CONFIG) == []


def test_extreme_market_value_ratio_is_cut_off():
    # Marktwertklasse <3M hat das engste erlaubte Verhaeltnis (40%) --
    # 2 Mio. vs. 4 Mio. (+100%) liegt weit darueber.
    target = make_row(market_value=2_000_000)
    candidate = make_row(market_value=4_000_000)
    assert hard_cutoff_reasons(target, candidate, CONFIG) != []


def test_same_relative_gap_tolerated_at_high_market_value_not_at_low():
    # <3M-Klasse erlaubt max. 40% Verhaeltnis, 30M+-Klasse 200% -- derselbe
    # relative Abstand (+50%) wird bei niedrigem Marktwert ausgeschlossen,
    # bei hohem Marktwert aber toleriert.
    low_target = make_row(market_value=2_000_000)
    low_candidate = make_row(market_value=3_000_000)  # +50%
    assert hard_cutoff_reasons(low_target, low_candidate, CONFIG) != []

    high_target = make_row(market_value=32_000_000)
    high_candidate = make_row(market_value=48_000_000)  # +50%, aber 30M+-Klasse erlaubt 200%
    assert hard_cutoff_reasons(high_target, high_candidate, CONFIG) == []


def test_opposite_trend_polarity_is_cut_off():
    target = make_row(market_value=10_000_000, market_value_change_day=800_000)  # stark steigend
    candidate = make_row(market_value=10_000_000, market_value_change_day=-800_000)  # stark fallend
    assert hard_cutoff_reasons(target, candidate, CONFIG) != []


def test_injury_mismatch_is_cut_off():
    target = make_row(status="fit")
    candidate = make_row(status="verletzt")
    assert hard_cutoff_reasons(target, candidate, CONFIG) != []


def test_both_injured_is_not_cut_off_on_injury_grounds():
    target = make_row(status="verletzt")
    candidate = make_row(status="Reha")
    reasons = hard_cutoff_reasons(target, candidate, CONFIG)
    assert not any("Verletzungsstatus" in r for r in reasons)


def test_position_no_longer_a_hard_cutoff():
    # Explizite Nutzervorgabe: Position ist kein hartes Kriterium mehr, nur
    # noch die gewichtete Distanz (hier nicht mal Teil der Similarity-
    # Dimensionen) entscheidet indirekt ueber die uebrigen Merkmale.
    target = make_row(position="ST")
    candidate = make_row(position="TW")
    assert hard_cutoff_reasons(target, candidate, CONFIG) == []


# ---------------------------------------------------------------------------
# similar_transfers: Similarity-basierte Auswahl statt Chronologie
# ---------------------------------------------------------------------------

def test_similar_transfers_empty_log_returns_zero_confidence_shape():
    result = similar_transfers(make_row(), [], CONFIG)
    assert result["n"] == 0
    assert result["median_pct"] is None
    assert result["neighbors"] == []


def test_similar_transfers_excludes_hard_cutoff_candidates():
    target = make_row(market_value=10_000_000, start_probability=1)
    log = [
        make_record(overpay_pct=15.0, market_value=10_200_000, start_probability=1),
        make_record(overpay_pct=999.0, market_value=500_000, start_probability=5),  # MV-Cutoff + Startchance-Cutoff
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["n"] == 1
    assert result["median_pct"] == 15.0


def test_similar_transfers_excludes_below_min_similarity_threshold():
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1, points_per_value=1.2e-5)
    # Besteht die harten Cutoffs, ist aber in fast jeder Dimension weit weg --
    # muss unterhalb similarity_min_score herausfallen.
    weak_candidate = make_record(
        overpay_pct=10.0, market_value=10_000_000, kauf_rank=230, start_probability=3,
        points_per_value=1e-6, market_value_change_day=-150_000, season_avg=1.0, team_form=-0.9,
    )
    result = similar_transfers(target, [weak_candidate], CONFIG)
    assert result["n"] == 0


def test_similar_transfers_picks_most_similar_not_most_recent():
    # Explizite Nutzervorgabe (Punkt 6): Auswahl nach Aehnlichkeit, nicht
    # Chronologie -- ein aelterer, aber deutlich aehnlicherer Transfer muss
    # einen juengeren, aber unaehnlicheren verdraengen, wenn max_k erreicht ist.
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1)
    close_but_old = make_record(
        overpay_pct=10.0, dt="2026-01-01T00:00:00Z",
        market_value=10_050_000, kauf_rank=22, start_probability=1,
    )
    far_but_recent = make_record(
        overpay_pct=50.0, dt="2026-09-14T00:00:00Z",
        market_value=10_050_000, kauf_rank=180, start_probability=3,
        points_per_value=1e-6, market_value_change_day=-150_000, season_avg=1.0, team_form=-0.9,
    )
    scored_close = similarity_score(target, close_but_old, None, CONFIG)
    scored_far = similarity_score(target, far_but_recent, None, CONFIG)
    assert scored_close > scored_far

    result = similar_transfers(target, [close_but_old, far_but_recent], CONFIG)
    names = [n["player_name"] for n in result["neighbors"]]
    assert result["neighbors"][0]["overpay_pct"] == 10.0  # aehnlichster zuerst, nicht juengster


def test_similar_transfers_does_not_force_fill_to_max_k():
    # Nur 2 valide Vergleiche vorhanden (weit unter max_k=20) -- keine
    # kuenstliche Auffuellung mit schlechteren Vergleichen.
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1)
    good_1 = make_record(overpay_pct=8.0, market_value=10_000_000, kauf_rank=22, start_probability=1)
    good_2 = make_record(overpay_pct=12.0, market_value=9_900_000, kauf_rank=25, start_probability=1)
    bad = make_record(
        overpay_pct=999.0, market_value=10_000_000, kauf_rank=230, start_probability=3,
        points_per_value=1e-6, market_value_change_day=-150_000, season_avg=1.0, team_form=-0.9,
    )
    result = similar_transfers(target, [good_1, good_2, bad], CONFIG)
    assert result["n"] == 2


def test_similar_transfers_respects_max_k_cap():
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1)
    max_k = CONFIG["similar_transfers_max_k"]
    log = [
        make_record(overpay_pct=float(i), market_value=10_000_000 + i * 1_000, kauf_rank=20 + i, start_probability=1)
        for i in range(max_k + 10)
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["n_considered"] == max_k
    assert result["n_candidates_before_threshold"] > max_k


def test_similar_transfers_tracks_n_fresh_separately_from_n():
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1)
    log = [
        make_record(overpay_pct=10.0, market_value=10_100_000, kauf_rank=22, start_probability=1, backfilled=True),
        make_record(overpay_pct=12.0, market_value=9_900_000, kauf_rank=25, start_probability=1, backfilled=False),
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["n"] == 2
    assert result["n_fresh"] == 1


def test_similar_transfers_neighbors_include_similarity_and_full_debug_fields():
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1)
    log = [make_record(overpay_pct=10.0, market_value=10_100_000, kauf_rank=22, start_probability=1)]
    result = similar_transfers(target, log, CONFIG)
    neighbor = result["neighbors"][0]
    for field in (
        "player_name", "dt", "market_value", "transfer_price", "overpay_pct",
        "start_probability", "kauf_rank", "points_per_value", "market_value_trend", "similarity",
    ):
        assert field in neighbor
    assert 0.0 <= neighbor["similarity"] <= 1.0


def test_similar_transfers_exposes_percentiles_for_category_target_lookup():
    target = make_row(market_value=10_000_000, kauf_rank=20, start_probability=1)
    log = [
        make_record(overpay_pct=pct, market_value=10_000_000 + i * 1_000, kauf_rank=20 + i, start_probability=1)
        for i, pct in enumerate([3, 5, 7, 8, 10, 11, 13, 15, 19, 27])
    ]
    result = similar_transfers(target, log, CONFIG)
    assert result["percentiles"][75.0] is not None
    assert result["cleaned_points"]  # fuer beliebige (nicht-gebuendelte) Perzentile, siehe calibration.py
