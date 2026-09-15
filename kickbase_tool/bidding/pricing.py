"""Kombiniert Attraktivitaets-Score (scoring.py), aehnliche Transfers
(similarity.py), Marktwertklassen-Kalibrierung und Liga-Markt-Faktor
(calibration.py) zur finalen Gebotsempfehlung inkl. Confidence, Gebotsspanne
und Begruendung. Bewusst als letzter, duenner Kombinationsschritt gehalten --
alle inhaltlich schweren Entscheidungen (was ist attraktiv, was ist aehnlich,
was ist der Marktzustand) passieren in den jeweils zustaendigen Modulen.

Der Attraktivitaets-Score entscheidet NUR, wie aggressiv ein Spieler gekauft
werden soll -- er wird nicht direkt in einen Prozentsatz uebersetzt. Der
tatsaechliche Overpay kommt aus Kategorie + Cold-Start-Band, ggf. ueberschrieben
durch echte Liga-Transfers (similarity.py/calibration.py) + Liga-Markt-Faktor.
_bid_efficiency_check() ist eine rein NACHGELAGERTE zweite Pruefung (P/L beim
tatsaechlichen Gebot statt beim Marktwert) und fliesst nirgends zurueck in den
Score oder final_pct -- kein Kreislauf Gebot -> P/L -> Rang -> Gebot."""
from typing import Optional

from kickbase_tool.bidding.scoring import (
    CATEGORY_ALL_IN,
    CATEGORY_LABELS,
    CATEGORY_MARKTWERT,
    ppm_thresholds_for,
)


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
    # n_fresh statt n: die Confidence soll widerspiegeln, wie sehr der
    # empirische Anteil tatsaechlich das Ergebnis mittraegt (siehe
    # recommend_bid -- w_empirical haengt ebenfalls an n_fresh). Ein Pool aus
    # lauter "backfilled" (zeitlich nicht exakt zuordenbaren) Vergleichen darf
    # keine hohe Confidence erzeugen, auch wenn er zahlenmaessig gross ist.
    n_fresh = similar_result.get("n_fresh") or 0
    target_n = config.get("similar_transfers_target_n", 12) or 1
    base = min(1.0, n_fresh / target_n)

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
        # WICHTIG: n_fresh statt n. n zaehlt auch Vergleichstransfers, deren
        # Marktwert/Rang/etc. nur mit den Werten von HEUTE statt vom echten
        # Transferzeitpunkt angereichert wurden ("backfilled" -- siehe
        # transfers.py). Deren Overpay-Prozentsatz ist systematisch verzerrt
        # (siehe Root-Cause-Analyse: Median faellt mit zunehmendem Alter des
        # Transfers, weil der heutige Marktwert bei steigenden Spielern immer
        # weiter vom Wert zum Kaufzeitpunkt abweicht). Nur echte, zeitpunktnah
        # erfasste Treffer duerfen das regelbasierte Modell nennenswert
        # verdraengen -- sonst uebernimmt das Modell einen Bias mit voller
        # statt reduzierter Ueberzeugung.
        n_effective = similar_result.get("n_fresh", 0)
    elif class_tier_stats and class_tier_stats.get("n", 0) >= 3:
        empirical_pct = class_tier_stats["median"]
        n_effective = class_tier_stats.get("n_fresh", 0)

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
        # Untere Grenze = ein vorsichtigerer/guenstigerer Alternativwert --
        # MUSS unabhaengig vom Vorzeichen von final_pct <= bid_upper bleiben.
        # Die fruehere Formel (lower_pct = final_pct * fraction) verletzte das
        # bei negativem final_pct (Multiplikation mit einer Zahl < 1 macht
        # einen negativen Wert BETRAGSMAESSIG KLEINER, also naeher an 0 -->
        # bid_lower wurde dann groesser statt kleiner als bid_upper). Hier
        # stattdessen ein Abstand, der IMMER von final_pct weg in Richtung
        # "guenstiger" (kleinerer Prozentsatz) subtrahiert wird.
        spread_pct = abs(final_pct) * (1.0 - config.get("bid_range_lower_fraction", 0.85))
        lower_pct = final_pct - spread_pct
        bid_lower = market_value * (1.0 + lower_pct / 100.0)
        overpay_abs = bid_upper - market_value

    bid_efficiency_ppm, bid_efficiency_ok = _bid_efficiency_check(
        row, market_value, bid_upper, category, config
    )

    confidence = _confidence(similar_result, config)

    reasons = list(attractiveness_result.get("reasons", []))
    if similar_result and similar_result.get("n"):
        n_fresh = similar_result.get("n_fresh", 0)
        note = f"Liga-Vergleich ({similar_result['n']} aehnliche Transfers): Median {_fmt_pct(similar_result['median_pct'])}"
        if n_fresh < similar_result["n"]:
            note += f" -- nur {n_fresh} davon zeitpunktgenau erfasst, Einfluss auf das Gebot entsprechend reduziert"
        reasons.append(note)
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
        "bid_efficiency_ppm": bid_efficiency_ppm,
        "bid_efficiency_ok": bid_efficiency_ok,
    }


def _bid_efficiency_check(
    row: dict, market_value: Optional[float], bid_upper: Optional[float], category: str, config: dict
) -> tuple:
    """Zweite, NACHGELAGERTE Sicherheitspruefung (siehe Aufgabenstellung):
    wie gut ist die PKT/MIO-Effizienz noch, wenn tatsaechlich das empfohlene
    Gebot statt des Marktwerts bezahlt wird? Rein deskriptiv/nachgelagert --
    fliesst NICHT zurueck in den Attraktivitaets-Score oder in final_pct oben
    (kein Kreislauf Gebot -> P/L -> Rang -> Gebot). Bei ALL-IN-Spielern darf
    die normale Mindestschwelle etwas unterschritten werden (absolute Punkte/
    begrenzte Startelfplaetze haben bei Elite-Spielern einen eigenen Wert)."""
    ppm_at_market_value = row.get("points_per_value")
    if ppm_at_market_value is None or not bid_upper or not market_value:
        return None, None

    bid_efficiency_ppm = ppm_at_market_value * 1_000_000 * (market_value / bid_upper)
    min_threshold = ppm_thresholds_for(market_value)["min"]
    if category == CATEGORY_ALL_IN:
        min_threshold *= config.get("elite_ppm_min_relaxation", 1.0)
    return round(bid_efficiency_ppm, 2), bid_efficiency_ppm >= min_threshold


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"
