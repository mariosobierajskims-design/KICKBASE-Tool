"""Robuste, von jeder anderen bidding/-Datei wiederverwendete Statistik-
Hilfsfunktionen: gewichteter Median/Perzentil, Ausreisser-Erkennung (MAD) und
Marktwertklassen. Bewusst ohne numpy/scipy -- die Datenmengen sind klein
(hunderte, nicht Millionen Transfers) und eine Zusatzabhaengigkeit lohnt sich
hier nicht.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple


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
    """Einmal-Aufruf, der die komplette Robustheits-Pipeline durchlaeuft:
    Ausreisser via MAD verwerfen, dann gewichteter Median + 25./75. Perzentil
    (Rueckwaertskompatibilitaet fuer bestehende Aufrufer) PLUS die volle
    Perzentil-Palette (siehe PERCENTILE_LEVELS/percentile_bundle, Punkt 10 der
    Aufgabenstellung: "nicht nur den einfachen Durchschnitt/Median") unter
    `percentiles` (Schluessel = Prozentwert als float, z.B. 75.0). `n` zaehlt
    die tatsaechlich verwendeten (nach Ausreisser-Filterung) Punkte, `n_raw`
    alle eingegangenen -- fuer Confidence-Berechnung ist `n` massgeblich."""
    raw = [(v, w) for v, w in values_with_weights if v is not None and w]
    cleaned = drop_extreme_outliers(raw, mad_multiplier=mad_multiplier)
    if not cleaned:
        return {
            "median": None, "p25": None, "p75": None, "percentiles": {level: None for level in PERCENTILE_LEVELS},
            "n": 0, "n_raw": len(raw), "effective_weight": 0.0, "cleaned_points": [],
        }
    return {
        "median": weighted_median(cleaned),
        "p25": weighted_percentile(cleaned, 25.0),
        "p75": weighted_percentile(cleaned, 75.0),
        "percentiles": percentile_bundle(cleaned),
        "n": len(cleaned),
        "n_raw": len(raw),
        "effective_weight": sum(w for _, w in cleaned),
        # Ausreisser-bereinigte Punkte, damit ein Aufrufer (z.B.
        # pricing.category_target_value) spaeter noch ein beliebiges,
        # NICHT in PERCENTILE_LEVELS enthaltenes Perzentil (z.B. 62. oder
        # 77.) berechnen kann, ohne die Bereinigung zu wiederholen.
        "cleaned_points": cleaned,
    }


def target_percentile_value(stats_result: dict, percentile: float) -> Optional[float]:
    """Liest ein beliebiges Perzentil aus einem bereits berechneten
    `robust_weighted_stats`-Ergebnis -- nutzt `percentiles` (schneller
    Lookup), wenn `percentile` dort exakt vorkommt, sonst `cleaned_points`
    fuer eine direkte Berechnung (z.B. die Kategorie-Zielperzentile 62/77/87
    aus category_target_percentile, die nicht in PERCENTILE_LEVELS stecken)."""
    percentiles = stats_result.get("percentiles") or {}
    if percentile in percentiles:
        return percentiles[percentile]
    cleaned = stats_result.get("cleaned_points") or []
    if not cleaned:
        return None
    return weighted_percentile(cleaned, percentile)


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


def decay_weight(days_ago: Optional[float], half_life_days: float) -> float:
    """Kontinuierliche Exponential-Decay-Gewichtung (Halbwertszeit in Tagen)
    statt einer Stufenfunktion -- explizite Nutzervorgabe ("keine starren
    Stufen, sondern eine zeitliche Halbwertszeit"). weight = 0.5 ** (days_ago
    / half_life_days): bei half_life_days=30 hat ein 30 Tage alter Transfer
    noch 50% Gewicht, ein 60 Tage alter noch 25%, ein frischer (0 Tage) volles
    Gewicht. `days_ago=None` (z.B. Datum fehlt) wird als "gerade eben" (0
    Tage, volles Gewicht) behandelt statt den Datenpunkt zu bestrafen --
    dieselbe Grundhaltung wie bei anderen fehlenden Werten in diesem Modul
    (siehe start_probability_score's `none`-Fallback)."""
    if days_ago is None:
        days_ago = 0.0
    if not half_life_days or half_life_days <= 0:
        return 1.0
    return 0.5 ** (max(0.0, days_ago) / half_life_days)


# Perzentile, die calibration.py/pricing.py aus einer (similarity- und
# zeitgewichteten) Overpay-Verteilung ziehen koennen -- ersetzt den fruehen
# reinen Median/p25/p75 (siehe Aufgabenstellung Punkt 10: "nicht nur den
# einfachen Durchschnitt/Median"). 50 bleibt enthalten, weil die
# ⚪-Kategorie weiterhin ungefaehr das "typische Marktniveau" abbilden soll.
PERCENTILE_LEVELS = [50.0, 60.0, 70.0, 75.0, 80.0, 85.0, 90.0]


def percentile_bundle(values_with_weights: Sequence[Tuple[float, float]], levels: Sequence[float] = PERCENTILE_LEVELS) -> Dict[float, Optional[float]]:
    """Berechnet mehrere Perzentile in einem Rutsch (identische Sortierung/
    Gewichtsachse wie weighted_percentile, nur einmal aufgebaut statt pro
    Perzentil neu) -- Schluessel sind die rohen Prozentwerte aus `levels`."""
    points = [(v, w) for v, w in values_with_weights if v is not None and w is not None and w > 0]
    if not points:
        return {level: None for level in levels}
    return {level: weighted_percentile(points, level) for level in levels}
