"""Findet je Spieler die AEHNLICHSTEN echten Ligatransfers (nicht mehr die
zeitlich juengsten) und leitet daraus eine Overpay-Verteilung + Confidence-
relevante Kennzahlen ab (siehe Aufgabenstellung "Aehnliche Transfers
methodisch ueberarbeiten").

Kern-Neuerung gegenueber der fruehen Version: "Vergleichbar" ist kein
binaeres Kriterium mehr (Marktwertfenster + gleiche Position), sondern ein
GEWICHTETER, KONTINUIERLICHER Similarity-Score (0..1) ueber mehrere
Dimensionen (`similarity_score`), zusaetzlich zu harten Ausschlusskriterien
fuer fundamental unaehnliche Profile (`hard_cutoff_reasons`) -- explizite
Nutzervorgabe: "keine groben Vergleichsgruppen mehr", "Distanz statt fester
Kategorien", "ein Unterschied bei Sicher vs. Ausgeschlossen soll staerker
bestraft werden als Rang 75 vs. 90".

Auswahl: von allen Kandidaten, die die harten Cutoffs bestehen UND eine
Similarity >= `similarity_min_score` erreichen, zaehlen die `similar_
transfers_max_k` AEHNLICHSTEN (nicht mehr die zeitlich juengsten) -- keine
Zwangs-Auffuellung auf eine feste Anzahl (siehe Aufgabenstellung Punkt 6:
"wenn nur 7 wirklich vergleichbare existieren, verwende 7"). Aktualitaet
wirkt NICHT mehr ueber die Auswahl, sondern ueber das Gewicht innerhalb der
Statistik (siehe calibration.record_weight: Exponential-Decay +
Backfilled-Faktor + Wettbewerbs-Signal), zusaetzlich multipliziert mit der
Similarity selbst -- ein Transfer, der nur knapp ueber der Mindestschwelle
liegt, darf die Verteilung weniger stark praegen als ein nahezu identischer.
"""
import math
from datetime import datetime, timezone
from typing import Optional

from kickbase_tool.bidding.calibration import record_weight
from kickbase_tool.bidding.scoring import (
    market_value_trend_score,
    ppm_score,
    ppm_thresholds_for,
    rank_tier_score,
)
from kickbase_tool.bidding.stats import market_value_class_index, robust_weighted_stats

_INJURY_STATUSES = {"verletzt", "reha"}


def _is_injured(status: Optional[str]) -> Optional[bool]:
    if not status:
        return None
    return status.strip().lower() in _INJURY_STATUSES


def _start_probability_bucket(value: Optional[int]) -> Optional[str]:
    """Sicher/Erwartet (1/2) vs. Unsicher (3) vs. Unwahrscheinlich/
    Ausgeschlossen (4/5) -- nur die AEUSSEREN Buckets werden fuer den harten
    Cutoff verwendet, "Unsicher" darf beide Seiten ueberbruecken (siehe
    Aufgabenstellung: "Sicher soll relativ aehnlich zu Erwartet sein, aber
    deutlich unaehnlicher zu Ausgeschlossen")."""
    if value is None:
        return None
    if value in (1, 2):
        return "sicher"
    if value in (4, 5):
        return "unwahrscheinlich"
    return "unsicher"


def hard_cutoff_reasons(target: dict, candidate: dict, config: dict) -> list:
    """Nicht-leere Liste = `candidate` scheidet als Vergleich fuer `target`
    komplett aus, unabhaengig davon, wie aehnlich er sonst waere (siehe
    Modul-Docstring/Aufgabenstellung Punkt 5). Bewusst als Liste von Gruenden
    statt nur bool, damit die Debug-Ansicht (pricing.py/Artifact-UI) spaeter
    zeigen kann, WARUM ein Kandidat nicht verwendet wurde."""
    reasons = []
    target_mv, candidate_mv = target.get("market_value"), candidate.get("market_value")
    if not target_mv or not candidate_mv or target_mv <= 0 or candidate_mv <= 0:
        reasons.append("Marktwert fehlt oder ungueltig")
        return reasons  # ohne Marktwert ist keine der uebrigen Pruefungen sinnvoll

    cutoffs = config.get("similarity_hard_cutoffs", {})

    if cutoffs.get("exclude_start_probability_bucket_clash", True):
        target_bucket = _start_probability_bucket(target.get("start_probability"))
        candidate_bucket = _start_probability_bucket(candidate.get("start_probability"))
        if target_bucket and candidate_bucket and {target_bucket, candidate_bucket} == {"sicher", "unwahrscheinlich"}:
            reasons.append("Startchance fundamental verschieden (sicher/erwartet vs. unwahrscheinlich/ausgeschlossen)")

    ratio_table = cutoffs.get("max_market_value_ratio_pct")
    if ratio_table:
        class_bounds = config.get("market_value_classes", [])
        idx = market_value_class_index(target_mv, class_bounds)
        max_ratio_pct = ratio_table[min(idx, len(ratio_table) - 1)] if idx is not None else ratio_table[-1]
        actual_ratio_pct = abs(candidate_mv - target_mv) / min(target_mv, candidate_mv) * 100.0
        if actual_ratio_pct > max_ratio_pct:
            reasons.append(f"Marktwert-Unterschied zu extrem ({actual_ratio_pct:.0f}% > {max_ratio_pct}% erlaubt)")

    trend_hi = cutoffs.get("trend_polarity_high", 0.75)
    trend_lo = cutoffs.get("trend_polarity_low", 0.25)
    target_trend_sc = market_value_trend_score(target.get("market_value_change_day"), target_mv, None)
    candidate_trend_sc = market_value_trend_score(candidate.get("market_value_change_day"), candidate_mv, None)
    if (target_trend_sc >= trend_hi and candidate_trend_sc <= trend_lo) or (
        target_trend_sc <= trend_lo and candidate_trend_sc >= trend_hi
    ):
        reasons.append("MW-Trend gegensaetzlich (stark steigend vs. stark fallend)")

    if cutoffs.get("exclude_injury_mismatch", True):
        target_injured, candidate_injured = _is_injured(target.get("status")), _is_injured(candidate.get("status"))
        if target_injured is not None and candidate_injured is not None and target_injured != candidate_injured:
            reasons.append("Verletzungsstatus unvereinbar (langfristig verletzt vs. fit)")

    return reasons


def _ratio_distance(a: Optional[float], b: Optional[float]) -> float:
    """Symmetrische relative Distanz in [0,1], unabhaengig von der Groessen-
    ordnung des Merkmals (Punkte/Spiel, Team-Form-Index, ...) -- 0.5 (neutral,
    weder bestrafend noch belohnend), wenn einer der beiden Werte fehlt,
    identisch zur Konvention der uebrigen Attraktivitaets-Bausteine in
    scoring.py (siehe z.B. start_probability_score's `none`-Fallback)."""
    if a is None or b is None:
        return 0.5
    denom = abs(a) + abs(b)
    if denom == 0:
        return 0.0
    return min(1.0, abs(a - b) / denom)


def _log_distance(a: Optional[float], b: Optional[float], ratio_cap: float = 3.0) -> float:
    """0 bei identischem Wert, saettigt bei 1.0 ab einem Verhaeltnis von
    `ratio_cap` (Default 3x). Log-Skala statt linear, damit z.B. 9 vs. 11
    Mio. (Verhaeltnis 1.22) deutlich naeher ist als 9 vs. 25 Mio. (Verhaeltnis
    2.78) -- explizite Nutzervorgabe ("MW 9 Mio. soll MW 11 Mio. aehnlicher
    sein als MW 25 Mio.")."""
    if not a or not b or a <= 0 or b <= 0:
        return 0.5
    log_cap = math.log(ratio_cap)
    if not log_cap:
        return 0.0
    return min(1.0, abs(math.log(a) - math.log(b)) / log_cap)


def similarity_score(target: dict, candidate: dict, target_trend: Optional[dict], config: dict) -> float:
    """0..1, 1.0 = identisches Profil. Gewichtete Summe kontinuierlicher
    Distanzen je Dimension (siehe similarity_weights in bidding_config.yaml
    fuer die Gewichte + Begruendung) -- KEINE binaere Gruppenzugehoerigkeit
    mehr (Aufgabenstellung Punkt 3/4: "Distanz statt fester Kategorien").
    Fuer historische Kandidaten ist keine Mehrtage-Trendhistorie bekannt
    (siehe transfers.py: nur der Tages-MW-Wechsel wird pro Transfer
    gespeichert), Beschleunigung fliesst daher nur fuer `target` (falls
    `target_trend` uebergeben) ein -- ein bewusster, dokumentierter
    Genauigkeitsverlust auf der Kandidatenseite statt eines Abbruchs."""
    weights = config["similarity_weights"]

    target_sp, candidate_sp = target.get("start_probability"), candidate.get("start_probability")
    sp_distance = abs(target_sp - candidate_sp) / 4.0 if target_sp is not None and candidate_sp is not None else 0.5

    rank_distance = abs(
        rank_tier_score(target.get("kauf_rank"), config) - rank_tier_score(candidate.get("kauf_rank"), config)
    )

    mv_distance = _log_distance(target.get("market_value"), candidate.get("market_value"))

    target_trend_sc = market_value_trend_score(
        target.get("market_value_change_day"), target.get("market_value"), (target_trend or {}).get("acceleration")
    )
    candidate_trend_sc = market_value_trend_score(candidate.get("market_value_change_day"), candidate.get("market_value"), None)
    trend_distance = abs(target_trend_sc - candidate_trend_sc)

    target_ppm, candidate_ppm = target.get("points_per_value"), candidate.get("points_per_value")
    target_ppm_sc = ppm_score(target_ppm * 1_000_000 if target_ppm is not None else None, ppm_thresholds_for(target.get("market_value")))
    candidate_ppm_sc = ppm_score(candidate_ppm * 1_000_000 if candidate_ppm is not None else None, ppm_thresholds_for(candidate.get("market_value")))
    ppm_distance = abs(target_ppm_sc - candidate_ppm_sc)

    performance_distance = _ratio_distance(target.get("season_avg"), candidate.get("season_avg"))
    team_strength_distance = _ratio_distance(target.get("team_form"), candidate.get("team_form"))

    weighted_terms = [
        (sp_distance, weights.get("start_probability", 0.0)),
        (rank_distance, weights.get("rank_tier", 0.0)),
        (mv_distance, weights.get("market_value", 0.0)),
        (trend_distance, weights.get("market_value_trend", 0.0)),
        (ppm_distance, weights.get("ppm_efficiency", 0.0)),
        (performance_distance, weights.get("expected_performance", 0.0)),
        (team_strength_distance, weights.get("team_strength", 0.0)),
    ]
    total_weight = sum(w for _, w in weighted_terms) or 1.0
    weighted_distance = sum(d * w for d, w in weighted_terms) / total_weight
    return max(0.0, min(1.0, 1.0 - weighted_distance))


def _trend_label(record: dict) -> str:
    score = market_value_trend_score(record.get("market_value_change_day"), record.get("market_value"), None)
    if score >= 0.6:
        return "steigend"
    if score <= 0.4:
        return "fallend"
    return "flach"


def similar_transfers(
    target_row: dict,
    transfer_log: list,
    config: dict,
    target_trend: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Liefert die `similar_transfers_max_k` AEHNLICHSTEN (nicht mehr
    zeitlich juengsten) validen Vergleichstransfers + daraus abgeleitete
    Overpay-Statistik (Median + volle Perzentil-Palette, siehe stats.py).
    `neighbors` enthaelt die VOLLE verwendete Liste (nicht nur die ersten 5)
    inkl. Similarity Score je Kandidat -- Grundlage fuer die aufklappbare
    Debug-Ansicht in der Spielerkartei (Aufgabenstellung Punkt 14)."""
    min_score = config.get("similarity_min_score", 0.55)
    max_k = config.get("similar_transfers_max_k", 20)

    scored = []
    for record in transfer_log:
        if record.get("overpay_pct") is None:
            continue
        if hard_cutoff_reasons(target_row, record, config):
            continue
        score = similarity_score(target_row, record, target_trend, config)
        if score >= min_score:
            scored.append((score, record))

    # Nach Aehnlichkeit absteigend (NICHT mehr chronologisch) -- Aktualitaet
    # wirkt stattdessen ueber das Gewicht (record_weight: Decay + Backfilled +
    # Wettbewerbssignal), nicht mehr ueber die Auswahl selbst. Siehe
    # Aufgabenstellung Punkt 6/8.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = scored[:max_k]

    n_fresh = sum(1 for _, record in top if not record.get("backfilled"))

    target_mv = target_row.get("market_value")
    weighted_points = []
    neighbor_summaries = []
    for score, record in top:
        # Die Similarity selbst zaehlt zusaetzlich als Gewicht: ein Kandidat
        # knapp ueber der Mindestschwelle darf die Verteilung weniger stark
        # praegen als ein nahezu identisches Profil (explizite Erweiterung
        # der "Distanz statt harter Gruppen"-Idee auf die Gewichtung selbst).
        weight = record_weight(record, config, now=now) * score
        weighted_points.append((record["overpay_pct"], weight))
        record_mv = record.get("market_value")
        mv_diff_pct = (
            round(abs(record_mv - target_mv) / target_mv * 100.0, 1) if record_mv and target_mv else None
        )
        neighbor_summaries.append({
            "player_name": record.get("player_name"),
            "buyer": record.get("buyer"),
            "dt": record.get("dt"),
            "market_value": record_mv,
            "transfer_price": record.get("transfer_price"),
            "overpay_pct": record.get("overpay_pct"),
            "start_probability": record.get("start_probability"),
            "kauf_rank": record.get("kauf_rank"),
            "points_per_value": record.get("points_per_value"),
            "market_value_trend": _trend_label(record),
            "mv_diff_pct": mv_diff_pct,
            "similarity": round(score, 3),
            "weight": round(weight, 3),
            "backfilled": bool(record.get("backfilled")),
            "bid_count": record.get("bid_count"),
        })

    stats = robust_weighted_stats(weighted_points)
    return {
        "n": stats["n"],
        "n_considered": len(top),
        "n_candidates_before_threshold": len(scored),
        "n_fresh": n_fresh,
        "median_pct": stats["median"],
        "p25_pct": stats["p25"],
        "p75_pct": stats["p75"],
        "percentiles": stats["percentiles"],
        # Fuer calibration.category_target_value/stats.target_percentile_value
        # -- die Kategorie-Zielperzentile (62./77./87.) liegen nicht in der
        # festen PERCENTILE_LEVELS-Palette und muessen bei Bedarf direkt aus
        # den (bereits Ausreisser-bereinigten) Punkten berechnet werden.
        "cleaned_points": stats["cleaned_points"],
        "min_score": min_score,
        "neighbors": neighbor_summaries,
    }
