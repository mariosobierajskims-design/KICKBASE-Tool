"""Robuste, von jeder anderen bidding/-Datei wiederverwendete Statistik-
Hilfsfunktionen: gewichteter Median/Perzentil, Ausreisser-Erkennung (MAD) und
Marktwertklassen. Bewusst ohne numpy/scipy -- die Datenmengen sind klein
(hunderte, nicht Millionen Transfers) und eine Zusatzabhaengigkeit lohnt sich
hier nicht.
"""
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple


def weighted_percentile(values_with_weights: Sequence[Tuple[float, float]], percentile: float) -> Optional[float]:
    """percentile in [0, 100]. Jeder Punkt "belegt" das Intervall seines
    Gewichts auf der kumulierten Gewichtsachse; seine Position ist die Mitte
    dieses Intervalls (Standard-Definition fuer einen gewichteten Median/
    Perzentil). Linear zwischen den beiden umgebenden Positionen interpoliert
    -- robust gegenueber Ausreissern, weil ein einzelner extremer Wert nur
    sein eigenes Gewicht beitraegt statt die Summe zu verzerren wie beim
    arithmetischen Mittel."""
    points = [(v, w) for v, w in values_with_weights if v is not None and w is not None and w > 0]
    if not points:
        return None
    points.sort(key=lambda vw: vw[0])
    total_weight = sum(w for _, w in points)
    if total_weight <= 0:
        return None
    target = (percentile / 100.0) * total_weight

    positions = []  # (position_on_cumulative_axis, value)
    cumulative = 0.0
    for value, weight in points:
        positions.append((cumulative + weight / 2.0, value))
        cumulative += weight

    if target <= positions[0][0]:
        return positions[0][1]
    if target >= positions[-1][0]:
        return positions[-1][1]
    for (pos_a, val_a), (pos_b, val_b) in zip(positions, positions[1:]):
        if pos_a <= target <= pos_b:
            span = pos_b - pos_a
            frac = (target - pos_a) / span if span else 0.0
            return val_a + frac * (val_b - val_a)
    return positions[-1][1]


def weighted_median(values_with_weights: Sequence[Tuple[float, float]]) -> Optional[float]:
    return weighted_percentile(values_with_weights, 50.0)


def weighted_mad(values_with_weights: Sequence[Tuple[float, float]], median: Optional[float] = None) -> Optional[float]:
    """Gewichtete Median Absolute Deviation -- robustes Streuungsmass, das
    (anders als die Standardabweichung) nicht selbst von den Ausreissern
    dominiert wird, die es erkennen soll."""
    if median is None:
        median = weighted_median(values_with_weights)
    if median is None:
        return None
    deviations = [(abs(v - median), w) for v, w in values_with_weights if v is not None and w]
    return weighted_median(deviations)


def drop_extreme_outliers(
    values_with_weights: Sequence[Tuple[float, float]], mad_multiplier: float = 3.0
) -> List[Tuple[float, float]]:
    """Entfernt Datenpunkte, die mehr als `mad_multiplier` gewichtete MADs vom
    gewichteten Median entfernt liegen -- ein einzelner voellig uebertriebener
    Kauf soll die Kalibrierung nicht verschieben (siehe Aufgabenstellung
    "Robustheit"). Bei zu wenigen Punkten (<5) oder MAD==0 (alle Werte fast
    gleich) wird nichts entfernt, um nicht versehentlich alles wegzufiltern."""
    points = [(v, w) for v, w in values_with_weights if v is not None and w]
    if len(points) < 5:
        return points
    median = weighted_median(points)
    mad = weighted_mad(points, median=median)
    if not mad:
        return points
    threshold = mad_multiplier * mad
    return [(v, w) for v, w in points if abs(v - median) <= threshold]


def robust_weighted_stats(values_with_weights: Sequence[Tuple[float, float]], mad_multiplier: float = 3.0) -> dict:
    """Einmal-Aufruf, der die komplette Robustheits-Pipeline aus der
    Aufgabenstellung durchlaeuft: Ausreisser via MAD verwerfen, dann
    gewichteten Median + 25./75. Perzentil auf den bereinigten Daten. `n`
    zaehlt die tatsaechlich verwendeten (nach Ausreisser-Filterung) Punkte,
    `n_raw` alle eingegangenen -- fuer Confidence-Berechnung ist `n` massgeblich."""
    raw = [(v, w) for v, w in values_with_weights if v is not None and w]
    cleaned = drop_extreme_outliers(raw, mad_multiplier=mad_multiplier)
    if not cleaned:
        return {"median": None, "p25": None, "p75": None, "n": 0, "n_raw": len(raw), "effective_weight": 0.0}
    return {
        "median": weighted_median(cleaned),
        "p25": weighted_percentile(cleaned, 25.0),
        "p75": weighted_percentile(cleaned, 75.0),
        "n": len(cleaned),
        "n_raw": len(raw),
        "effective_weight": sum(w for _, w in cleaned),
    }


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Kickbase-Zeitstempel kommen als "...Z" (UTC); Python < 3.11 kennt das
        # "Z"-Suffix bei fromisoformat nicht, deshalb explizit ersetzen.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def days_since(iso_timestamp: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    dt = parse_iso_datetime(iso_timestamp)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


MARKET_VALUE_CLASS_LABELS = [
    "<3 Mio.", "3-6 Mio.", "6-10 Mio.", "10-15 Mio.", "15-20 Mio.", "20-25 Mio.", "25-30 Mio.", "30 Mio.+",
]


def market_value_class_index(market_value: Optional[float], class_bounds: Sequence[float]) -> Optional[int]:
    """class_bounds sind die oberen Grenzen (exklusiv) aller Klassen ausser der
    letzten, z.B. [3e6, 6e6, ..., 30e6] -> 8 Klassen (siehe MARKET_VALUE_CLASS_LABELS)."""
    if market_value is None:
        return None
    for i, bound in enumerate(class_bounds):
        if market_value < bound:
            return i
    return len(class_bounds)


def market_value_class_label(market_value: Optional[float], class_bounds: Sequence[float]) -> Optional[str]:
    idx = market_value_class_index(market_value, class_bounds)
    if idx is None:
        return None
    return MARKET_VALUE_CLASS_LABELS[idx] if idx < len(MARKET_VALUE_CLASS_LABELS) else MARKET_VALUE_CLASS_LABELS[-1]


def recency_weight(days_ago: Optional[float], schedule: Sequence[dict]) -> float:
    """schedule: [{"max_days": 7, "weight": 1.0}, {"max_days": 21, "weight": 0.5},
    {"max_days": None, "weight": 0.2}] -- erste passende Stufe gewinnt."""
    if days_ago is None:
        days_ago = 0.0
    for stage in schedule:
        max_days = stage.get("max_days")
        if max_days is None or days_ago <= max_days:
            return float(stage.get("weight", 1.0))
    return float(schedule[-1].get("weight", 1.0)) if schedule else 1.0
