"""Kombiniert Attraktivitaets-Score (scoring.py), aehnliche Transfers
(similarity.py), Marktwertklassen-Kalibrierung und Liga-Markt-Faktor
(calibration.py) zur finalen Gebotsempfehlung inkl. Confidence, Gebotsspanne
und Begruendung. Bewusst als letzter, duenner Kombinationsschritt gehalten --
alle inhaltlich schweren Entscheidungen (was ist attraktiv, was ist aehnlich,
was ist der Marktzustand) passieren in den jeweils zustaendigen Modulen."""
from typing import Optional

from kickbase_tool.bidding.scoring import CATEGORY_LABELS, CATEGORY_MARKTWERT


def _category_bounds(category: str, config: dict) -> tuple:
    thresholds = config["category_thresholds"]
    if category == "all_in":
        return thresholds["all_in"], 1.0
    if category == "will_haben":
        return thresholds["will_haben"], thresholds["all_in"]
    if category == "ueber_marktwert":
        return thresholds["ueber_marktwert"], thresholds["will_haben"]
    return 0.0, thresholds["ueber_marktwert"]


def _rule_based_overpay_pct(category: str, score: float, config: dict) -> float:
    """Cold-Start-Basiswert: skaliert innerhalb der Low/Mid/High-Spanne der
    Kategorie danach, WO im Score-Band der Spieler liegt -- ein Spieler knapp
    unter der naechsthoeheren Kategorie bekommt tendenziell mehr Overpay
    zugestanden als einer, der die aktuelle Kategorie gerade so erreicht."""
    band = config["cold_start_overpay_pct"][category]
    lower, upper = _category_bounds(category, config)
    frac = (score - lower) / (upper - lower) if upper != lower else 0.5
    frac = max(0.0, min(1.0, frac))
    if frac < 0.5:
        return band["low"] + (frac / 0.5) * (band["mid"] - band["low"])
    return band["mid"] + ((frac - 0.5) / 0.5) * (band["high"] - band["mid"])


def _confidence(similar_result: Optional[dict], config: dict) -> dict:
    similar_result = similar_result or {}
    n = similar_result.get("n") or 0
    target_n = config.get("similar_transfers_target_n", 12) or 1
    base = min(1.0, n / target_n)

    p25, p75 = similar_result.get("p25_pct"), similar_result.get("p75_pct")
    if p25 is not None and p75 is not None:
        spread = abs(p75 - p25)
        spread_factor = max(0.3, 1.0 - spread / 30.0)
    else:
        spread_factor = 0.6  # unbekannte Streuung -- vorsichtig statt blind zuversichtlich

    confidence = max(0.05, min(0.95, base * spread_factor))
    if confidence >= 0.70:
        bucket = "gruen"
    elif confidence >= 0.40:
        bucket = "gelb"
    else:
        bucket = "rot"
    return {"confidence": confidence, "bucket": bucket}


def recommend_bid(
    row: dict,
    attractiveness_result: dict,
    similar_result: Optional[dict],
    class_tier_stats: Optional[dict],
    market_factor: dict,
    config: dict,
) -> dict:
    market_value = row.get("market_value")
    category = attractiveness_result["category"]
    score = attractiveness_result["score"]

    rule_based_pct = _rule_based_overpay_pct(category, score, config)

    empirical_pct = None
    n_effective = 0
    if similar_result and similar_result.get("n", 0) >= 3:
        empirical_pct = similar_result["median_pct"]
        n_effective = similar_result["n"]
    elif class_tier_stats and class_tier_stats.get("n", 0) >= 3:
        empirical_pct = class_tier_stats["median"]
        n_effective = class_tier_stats["n"]

    target_n = config.get("similar_transfers_target_n", 12) or 1
    w_empirical = min(1.0, n_effective / target_n) if empirical_pct is not None else 0.0
    final_pct = w_empirical * empirical_pct + (1.0 - w_empirical) * rule_based_pct if empirical_pct is not None else rule_based_pct

    final_pct += market_factor.get("shift_pct", 0.0)

    trend_component = attractiveness_result["components"].get("market_value_trend", 0.5)
    trend_bonus = (trend_component - 0.5) / 0.5 * config.get("trend_bonus_max_shift_pct", 0.0)
    final_pct += trend_bonus

    no_bid = (
        category == CATEGORY_MARKTWERT
        and score < config.get("no_bid_score_threshold", 0.30)
        and final_pct <= config.get("no_bid_overpay_pct_threshold", 1.0)
    )

    bid_upper = bid_lower = overpay_abs = None
    if not no_bid and market_value:
        bid_upper = market_value * (1.0 + final_pct / 100.0)
        lower_pct = final_pct * config.get("bid_range_lower_fraction", 0.85)
        bid_lower = market_value * (1.0 + lower_pct / 100.0)
        overpay_abs = bid_upper - market_value

    confidence = _confidence(similar_result, config)

    reasons = list(attractiveness_result.get("reasons", []))
    if similar_result and similar_result.get("n"):
        reasons.append(
            f"Liga-Vergleich ({similar_result['n']} aehnliche Transfers): Median {_fmt_pct(similar_result['median_pct'])}"
        )
    reasons.append(f"Liga-Markt aktuell: {market_factor.get('label', 'neutral')}")

    return {
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "score": round(score, 3),
        "no_bid": no_bid,
        "market_value": market_value,
        "bid_upper": bid_upper,
        "bid_lower": bid_lower,
        "overpay_abs": overpay_abs,
        "overpay_pct": None if no_bid else round(final_pct, 1),
        "confidence_pct": round(confidence["confidence"] * 100),
        "confidence_bucket": confidence["bucket"],
        "market_context_label": market_factor.get("label", "neutral"),
        "reasons": reasons,
        "similar_transfers": similar_result,
        "empirical_weight": round(w_empirical, 2),
    }


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"
