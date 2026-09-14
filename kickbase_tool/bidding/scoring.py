"""Regelbasierter Attraktivitaets-Score + Gebotskategorie. Bewusst
Cold-Start-fest: braucht keine einzige echte Liga-Transaktion, um schon
sinnvolle Ergebnisse zu liefern (siehe Aufgabenstellung "Cold Start") --
pricing.py mischt diesen regelbasierten Score erst in einem zweiten Schritt
mit der empirischen Liga-Kalibrierung.

Startwahrscheinlichkeit ist mit Abstand am staerksten gewichtet (explizite
Vorgabe), gefolgt vom Rang-Tier, dann PKT/MIO-Effizienz (deren Gewicht mit
steigendem Marktwert bewusst sinkt) und zuletzt dem Marktwert-Trend."""
from typing import Dict, List, Optional

CATEGORY_ALL_IN = "all_in"
CATEGORY_WILL_HABEN = "will_haben"
CATEGORY_UEBER_MARKTWERT = "ueber_marktwert"
CATEGORY_MARKTWERT = "marktwert"

CATEGORY_ORDER = [CATEGORY_ALL_IN, CATEGORY_WILL_HABEN, CATEGORY_UEBER_MARKTWERT, CATEGORY_MARKTWERT]
CATEGORY_LABELS = {
    CATEGORY_ALL_IN: "\U0001F525 ALL IN",
    CATEGORY_WILL_HABEN: "⭐ WILL ICH HABEN",
    CATEGORY_UEBER_MARKTWERT: "\U0001F7E2 ÜBER MARKTWERT",
    CATEGORY_MARKTWERT: "⚪ MARKTWERT",
}

# Identische Tabelle wie im Spielerkartei-Artifact (PKT/MIO-Schnellfilter) --
# bewusst nicht neu erfunden, damit Gebotsmodell und sichtbare Filter/Kennzahl
# konsistent dieselbe Definition von "gut" verwenden.
PPM_TIERS = [
    {"limit": 5_000_000, "min": 8.0, "good": 10.0, "top": 13.0},
    {"limit": 10_000_000, "min": 8.0, "good": 10.0, "top": 12.0},
    {"limit": 15_000_000, "min": 7.0, "good": 8.5, "top": 10.0},
    {"limit": 20_000_000, "min": 6.0, "good": 7.5, "top": 9.0},
    {"limit": 25_000_000, "min": 5.5, "good": 6.5, "top": 8.0},
    {"limit": 30_000_000, "min": 5.0, "good": 6.0, "top": 7.5},
    {"limit": float("inf"), "min": 4.5, "good": 5.5, "top": 7.0},
]


def ppm_thresholds_for(market_value: Optional[float]) -> dict:
    mv = market_value if market_value is not None else 0.0
    for tier in PPM_TIERS:
        if mv < tier["limit"]:
            return tier
    return PPM_TIERS[-1]


def rank_tier_index(kauf_rank: Optional[float], config: dict) -> Optional[int]:
    if kauf_rank is None:
        return None
    for i, tier in enumerate(config["rank_tiers"]):
        max_rank = tier.get("max_rank")
        if max_rank is None or kauf_rank <= max_rank:
            return i
    return len(config["rank_tiers"]) - 1


def rank_tier_score(kauf_rank: Optional[float], config: dict) -> float:
    idx = rank_tier_index(kauf_rank, config)
    if idx is None:
        return 0.5
    return float(config["rank_tiers"][idx]["score"])


def start_probability_score(value: Optional[int], config: dict) -> float:
    scores = config["start_probability_score"]
    if value is None:
        return float(scores.get("none", 0.5))
    return float(scores.get(str(value), scores.get("none", 0.5)))


def ppm_efficiency_weight(market_value: Optional[float], config: dict) -> float:
    """Wie stark die PKT/MIO-Effizienz noch zaehlt: faellt linear von 1.0 auf
    ppm_efficiency_fade_min_weight zwischen den beiden konfigurierten
    Marktwert-Grenzen -- ein teurer Topspieler darf ineffizienter sein
    (Schlotterbeck-Beispiel), ohne dass die Effizienz komplett irrelevant wird."""
    if market_value is None:
        return 1.0
    start = config["ppm_efficiency_fade_start_mv"]
    end = config["ppm_efficiency_fade_end_mv"]
    min_weight = config["ppm_efficiency_fade_min_weight"]
    if market_value <= start:
        return 1.0
    if market_value >= end:
        return min_weight
    frac = (market_value - start) / (end - start)
    return 1.0 - frac * (1.0 - min_weight)


def ppm_score(ppm_value: Optional[float], thresholds: dict) -> float:
    """ppm_value = Punkte pro Million (also schon *1e6 skaliert, wie in der
    Spielerkartei angezeigt). Stueckweise linear zwischen den drei
    Schwellen -- keine harte Stufenfunktion, damit ein Wert knapp unter/ueber
    einer Schwelle nicht zu einem Sprung im Gesamtscore fuehrt."""
    if ppm_value is None:
        return 0.5
    lo, good, top = thresholds["min"], thresholds["good"], thresholds["top"]
    if ppm_value <= 0:
        return 0.0
    if ppm_value < lo:
        return max(0.0, 0.4 * (ppm_value / lo)) if lo else 0.4
    if ppm_value < good:
        return 0.4 + 0.3 * (ppm_value - lo) / (good - lo) if good != lo else 0.4
    if ppm_value < top:
        return 0.7 + 0.2 * (ppm_value - good) / (top - good) if top != good else 0.7
    # Ueber "sehr gut": weiterer, abgeflachter Bonus statt hartem Deckel.
    return min(1.0, 0.9 + 0.1 * min(1.0, (ppm_value - top) / max(top, 1.0)))


def market_value_trend_score(market_value_change_day: Optional[float], market_value: Optional[float], acceleration: Optional[float]) -> float:
    """Relativer Tages-Trend in Prozent des Marktwerts -- so wirkt derselbe
    absolute Euro-Betrag bei einem guenstigen Spieler automatisch staerker als
    bei einem teuren (siehe Aufgabenstellung). Bewusst eng gedeckelt (+-0.3 um
    den neutralen Wert 0.5), damit dieser Faktor den sportlichen Wert nicht
    dominiert."""
    if market_value_change_day is None or not market_value:
        return 0.5
    daily_pct = (market_value_change_day / market_value) * 100.0
    base = max(-0.30, min(0.30, daily_pct / 10.0))
    accel_bonus = 0.0
    if acceleration is not None and base > 0:
        accel_bonus = 0.05 if acceleration > 0 else (-0.05 if acceleration < 0 else 0.0)
    return max(0.0, min(1.0, 0.5 + base + accel_bonus))


def detect_special_cases(row: dict, snapshot_history: Optional[List[dict]]) -> List[str]:
    """Datengrenzen-bewusste, defensive Sonderfall-Erkennung -- es gibt keinen
    expliziten "neuer Transfer"/"Rueckkehr nach Verletzung"-Flag in den
    Kickbase-Daten, daher nur, was sich tatsaechlich aus vorhandenen Feldern
    ableiten laesst (siehe Aufgabenstellung: diese Faelle sollen den Rang
    relativieren, nicht erfunden werden)."""
    flags = []
    if not row.get("season_avg"):
        flags.append("kaum Einsatzzeit/geringe Stichprobe in dieser Saison")
    if row.get("status") and row.get("status") != "fit":
        flags.append(f"Status: {row['status']}")
    if snapshot_history and len(snapshot_history) >= 2:
        first_prob = snapshot_history[0].get("start_probability")
        last_prob = snapshot_history[-1].get("start_probability")
        if first_prob is not None and last_prob is not None and last_prob < first_prob - 1:
            flags.append("Startchance verbessert sich zuletzt deutlich")
    return flags


def has_small_sample(row: dict) -> bool:
    return not row.get("season_avg")


def attractiveness(row: dict, snapshot_history: Optional[List[dict]], trend: dict, config: dict) -> dict:
    sp_score = start_probability_score(row.get("start_probability"), config)

    small_sample = has_small_sample(row)
    base_rank_score = rank_tier_score(row.get("kauf_rank"), config)
    # Ein schlechter Rang wird relativiert, wenn er wahrscheinlich nur an
    # fehlender Stichprobe liegt (siehe Aufgabenstellung) statt an echter
    # sportlicher Schwaeche -- zieht den Score zur Haelfte Richtung neutral.
    rank_score = (base_rank_score + 0.5) / 2.0 if small_sample and base_rank_score < 0.5 else base_rank_score

    ppm_value = row.get("points_per_value")
    ppm_value_per_mio = ppm_value * 1_000_000 if ppm_value is not None else None
    ppm_sc = ppm_score(ppm_value_per_mio, ppm_thresholds_for(row.get("market_value")))
    ppm_w = ppm_efficiency_weight(row.get("market_value"), config)

    trend_sc = market_value_trend_score(
        row.get("market_value_change_day"), row.get("market_value"), (trend or {}).get("acceleration")
    )

    weights = config["attractiveness"]
    weighted_terms = [
        (sp_score, weights["start_probability_weight"]),
        (rank_score, weights["rank_tier_weight"]),
        (ppm_sc, weights["ppm_efficiency_weight"] * ppm_w),
        (trend_sc, weights["market_value_trend_weight"]),
    ]
    total_weight = sum(w for _, w in weighted_terms) or 1.0
    score = sum(s * w for s, w in weighted_terms) / total_weight

    thresholds = config["category_thresholds"]
    if score >= thresholds["all_in"]:
        category = CATEGORY_ALL_IN
    elif score >= thresholds["will_haben"]:
        category = CATEGORY_WILL_HABEN
    elif score >= thresholds["ueber_marktwert"]:
        category = CATEGORY_UEBER_MARKTWERT
    else:
        category = CATEGORY_MARKTWERT

    # Harte Deckelung: schlechte Startchance darf die Kategorie nicht allein
    # durch MW-Trend/Rang bis WILL-ICH-HABEN/ALL-IN heben (Reggiani-Beispiel).
    cap = config.get("start_probability_category_cap", {}).get(str(row.get("start_probability")))
    if cap and CATEGORY_ORDER.index(category) < CATEGORY_ORDER.index(cap):
        category = cap

    special_cases = detect_special_cases(row, snapshot_history)
    reasons = _build_reasons(sp_score, rank_score, ppm_sc, trend_sc, row, special_cases)

    return {
        "score": score,
        "category": category,
        "components": {
            "start_probability": sp_score,
            "rank_tier": rank_score,
            "ppm_efficiency": ppm_sc,
            "ppm_efficiency_weight": ppm_w,
            "market_value_trend": trend_sc,
        },
        "special_cases": special_cases,
        "reasons": reasons,
    }


def _build_reasons(sp_score: float, rank_score: float, ppm_sc: float, trend_sc: float, row: dict, special_cases: List[str]) -> List[str]:
    reasons = []

    def bullet(condition_score: float, high_text: str, low_text: str, strong_threshold=0.75, weak_threshold=0.4):
        if condition_score >= strong_threshold:
            reasons.append(f"+ {high_text}")
        elif condition_score <= weak_threshold:
            reasons.append(f"- {low_text}")

    bullet(sp_score, "sichere/erwartete Startchance", "unsichere Startchance")
    bullet(rank_score, "starker Kauf-Rang", "schwacher Kauf-Rang")
    bullet(ppm_sc, "ueberdurchschnittliche Punkte pro Million", "unterdurchschnittliche Punkte pro Million")
    bullet(trend_sc, "steigender Marktwert", "fallender Marktwert", strong_threshold=0.62, weak_threshold=0.4)

    for flag in special_cases:
        reasons.append(f"i {flag}")
    return reasons
