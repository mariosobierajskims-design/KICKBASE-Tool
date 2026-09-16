"""Kombiniert Attraktivitaets-Score (scoring.py), aehnliche Transfers
(similarity.py), Marktwertklassen-Kalibrierung und Liga-Markt-Faktor
(calibration.py) zur finalen Gebotsempfehlung inkl. Confidence, Gebotsspanne
und Begruendung. Bewusst als letzter, duenner Kombinationsschritt gehalten --
alle inhaltlich schweren Entscheidungen (was ist attraktiv, was ist aehnlich,
was ist der Marktzustand) passieren in den jeweils zustaendigen Modulen.

Der Attraktivitaets-Score entscheidet NUR, wie aggressiv ein Spieler gekauft
werden soll -- er wird nicht direkt in einen Prozentsatz uebersetzt. Stattdessen
bestimmt die Kategorie ein ZIEL-PERZENTIL der (similarity- und zeitgewichteten)
historischen Overpay-Verteilung (siehe calibration.category_target_value) --
das ist die methodische Umsetzung von Aufgabenstellung Punkt 11: "Wenn ich
einen Spieler unbedingt haben will, ist der Median historischer Gewinnerpreise
als Gebot zu konservativ." Ohne genug valide Vergleiche faellt das Modell auf
das regelbasierte Cold-Start-Band zurueck (_rule_based_overpay_pct), gewichtet
nach Confidence -- niemals schlechte Vergleiche "auffuellen", nur um eine
Mindestanzahl zu erreichen (siehe similarity.py).

_bid_efficiency_check() ist eine rein NACHGELAGERTE zweite Pruefung (P/L beim
tatsaechlichen Gebot statt beim Marktwert) und fliesst nirgends zurueck in den
Score oder final_pct -- kein Kreislauf Gebot -> P/L -> Rang -> Gebot."""
from typing import Optional

from kickbase_tool.bidding.calibration import category_target_value
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
    zugestanden als einer, der die aktuelle Kategorie gerade so erreicht.
    Bleibt die Grundlage, solange zu wenig valide Vergleichstransfers
    vorliegen (siehe recommend_bid: w_empirical)."""
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
    target_n = config.get("similar_transfers_target_n", 20) or 1
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


def _empirical_estimate(
    category: str, similar_result: Optional[dict], class_tier_stats: Optional[dict], config: dict
) -> tuple:
    """Liefert (empirical_pct, n_effective, target_percentile, source) --
    bevorzugt die similarity-basierten Vergleichstransfers (similarity.py),
    faellt bei zu wenigen validen Treffern (< 3) auf die grobe Marktwertklasse-
    /Rang-Tier-Kalibrierung (calibration.market_stats_by_class_and_tier)
    zurueck, faellt ganz ohne Daten auf None zurueck (dann uebernimmt
    ausschliesslich das regelbasierte Cold-Start-Band). `source` ist ein
    Debug-Feld fuer die Artifact-UI ("similarity"/"class_tier"/None)."""
    target_percentile = config.get("category_target_percentile", {}).get(category)

    if similar_result and similar_result.get("n", 0) >= 3:
        empirical_pct = category_target_value(similar_result, category, config)
        if empirical_pct is not None:
            return empirical_pct, similar_result.get("n_fresh", 0), target_percentile, "similarity"

    if class_tier_stats and class_tier_stats.get("n", 0) >= 3:
        empirical_pct = category_target_value(class_tier_stats, category, config)
        if empirical_pct is not None:
            return empirical_pct, class_tier_stats.get("n_fresh", 0), target_percentile, "class_tier"

    return None, 0, target_percentile, None


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

    empirical_pct, n_effective, target_percentile, empirical_source = _empirical_estimate(
        category, similar_result, class_tier_stats, config
    )

    target_n = config.get("similar_transfers_target_n", 20) or 1
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
        # Ein Abstand, der IMMER von final_pct weg in Richtung "guenstiger"
        # (kleinerer Prozentsatz) subtrahiert wird.
        spread_pct = abs(final_pct) * (1.0 - config.get("bid_range_lower_fraction", 0.85))
        lower_pct = final_pct - spread_pct
        bid_lower = market_value * (1.0 + lower_pct / 100.0)
        overpay_abs = bid_upper - market_value

    ppm_at_market_value = _ppm_at_price(row, market_value, market_value)
    ppm_at_bid, bid_efficiency_ok = _bid_efficiency_check(row, market_value, bid_upper, category, config)

    confidence = _confidence(similar_result, config)

    reasons = list(attractiveness_result.get("reasons", []))
    if similar_result and similar_result.get("n"):
        n_fresh = similar_result.get("n_fresh", 0)
        note = (
            f"Liga-Vergleich ({similar_result['n']} valide aehnliche Transfers, "
            f"Similarity >= {similar_result.get('min_score', 0):.2f}): "
            f"Ziel-Perzentil {target_percentile}. -> {_fmt_pct(empirical_pct)}, "
            f"Median {_fmt_pct(similar_result['median_pct'])}"
        )
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
        "empirical_source": empirical_source,
        "target_percentile": target_percentile,
        "empirical_pct": round(empirical_pct, 1) if empirical_pct is not None else None,
        "rule_based_pct": round(rule_based_pct, 1),
        # Debug-Ansicht (Aufgabenstellung Punkt 14): P/L einmal beim
        # Marktwert (Status quo) und einmal beim tatsaechlich empfohlenen
        # Gebot, damit sichtbar ist, wie stark der Aufschlag die Effizienz
        # verwaessert.
        "ppm_at_market_value": ppm_at_market_value,
        "ppm_at_bid": ppm_at_bid,
        "bid_efficiency_ok": bid_efficiency_ok,
        # Rueckwaertskompatible Alias-Namen (siehe frueherer Feldname) --
        # falls irgendein Aufrufer noch die alten Schluessel liest.
        "bid_efficiency_ppm": ppm_at_bid,
    }


def _ppm_at_price(row: dict, market_value: Optional[float], price: Optional[float]) -> Optional[float]:
    """Punkte pro Million bei einem gegebenen Preis (statt beim Marktwert) --
    reine Umrechnung derselben absoluten Punkteerwartung auf einen anderen
    Nenner, keine neue Kennzahl. `market_value` ist der Bezugspunkt der
    urspruenglichen PPM-Note (row["points_per_value"]) und wird bewusst als
    eigener Parameter statt aus `row` gelesen, damit Aufrufer (siehe
    _bid_efficiency_check) unabhaengig davon bleiben, ob `row` selbst ein
    "market_value"-Feld enthaelt."""
    ppm_at_market_value = row.get("points_per_value")
    if ppm_at_market_value is None or not price or not market_value:
        return None
    return round(ppm_at_market_value * 1_000_000 * (market_value / price), 2)


def _bid_efficiency_check(
    row: dict, market_value: Optional[float], bid_upper: Optional[float], category: str, config: dict
) -> tuple:
    """Zweite, NACHGELAGERTE Sicherheitspruefung (siehe Aufgabenstellung):
    wie gut ist die PKT/MIO-Effizienz noch, wenn tatsaechlich das empfohlene
    Gebot statt des Marktwerts bezahlt wird? Rein deskriptiv/nachgelagert --
    fliesst NICHT zurueck in den Attraktivitaets-Score oder in final_pct oben
    (kein Kreislauf Gebot -> P/L -> Rang -> Gebot, siehe Aufgabenstellung
    Punkt 13). Bei ALL-IN-Spielern darf die normale Mindestschwelle etwas
    unterschritten werden (absolute Punkte/begrenzte Startelfplaetze haben
    bei Elite-Spielern einen eigenen Wert)."""
    bid_efficiency_ppm = _ppm_at_price(row, market_value, bid_upper)
    if bid_efficiency_ppm is None or not market_value:
        return None, None

    min_threshold = ppm_thresholds_for(market_value)["min"]
    if category == CATEGORY_ALL_IN:
        min_threshold *= config.get("elite_ppm_min_relaxation", 1.0)
    return bid_efficiency_ppm, bid_efficiency_ppm >= min_threshold


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"
