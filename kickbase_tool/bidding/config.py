"""Laedt kickbase_tool/bidding/bidding_config.yaml -- zentrale, frei anpassbare
Gewichte/Schwellenwerte fuer das Gebotsmodell, analog zu ranking/weights.yaml.
Nie hart im Code, damit sich das Modell ohne Code-Aenderung nachjustieren
laesst. Fehlt die Datei oder ein Schluessel, greifen die hier hinterlegten
Defaults (siehe DEFAULTS unten) -- das Modell darf nie hart abstuerzen, nur
weil eine Konfigurationsdatei fehlt oder unvollstaendig ist.
"""
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).with_name("bidding_config.yaml")

# Tief verschachtelte Defaults, damit ein Teil-Override in der YAML-Datei
# (z.B. nur "attractiveness.start_probability") den Rest nicht zerstoert.
DEFAULTS: Dict[str, Any] = {
    # Wie stark jeder Faktor in den 0..1 Attraktivitaets-Score einfliesst
    # (scoring.py). Explizite Nutzervorgabe, NICHT gleich gewichtet: Kauf-Rang
    # bildet den langfristigen sportlichen Gesamtwert am besten ab (35%),
    # Startchance ist fuer tatsaechliche Punkte am wichtigsten (30%),
    # PKT/MIO-Effizienz zaehlt fuer die Kaderoptimierung (20%), MW-Trend
    # beeinflusst Overpay/Tradingwert am wenigsten (15%). Summe = 1.0. KEIN
    # zusaetzlicher marktwertabhaengiger Fade auf PKT/MIO mehr (das waere eine
    # doppelte Marktwert-Beruecksichtigung, siehe ppm_thresholds_for).
    "attractiveness": {
        "rank_tier_weight": 0.35,
        "start_probability_weight": 0.30,
        "ppm_efficiency_weight": 0.20,
        "market_value_trend_weight": 0.15,
    },
    # Rang-Baender, explizite Nutzervorgabe (feiner gestuft als zuvor, vor
    # allem im Mittelfeld 141-250).
    "rank_tiers": [
        {"max_rank": 20, "score": 1.00},
        {"max_rank": 50, "score": 0.85},
        {"max_rank": 90, "score": 0.70},
        {"max_rank": 140, "score": 0.55},
        {"max_rank": 200, "score": 0.35},
        {"max_rank": 250, "score": 0.20},
        {"max_rank": None, "score": 0.05},
    ],
    # Score je Startwahrscheinlichkeits-Kategorie (1=Sicher..5=Ausgeschlossen),
    # explizite Nutzervorgabe. Ausgeschlossen bewusst > 0 (kann trotzdem
    # eingewechselt werden, bedeutet nicht automatisch 0 Einsatzminuten).
    "start_probability_score": {"1": 1.00, "2": 0.80, "3": 0.55, "4": 0.30, "5": 0.10, "none": 0.50},
    # Score-Schwellen fuer die vier Gebotskategorien (auf den finalen 0..1 Score).
    "category_thresholds": {"all_in": 0.80, "will_haben": 0.62, "ueber_marktwert": 0.37},
    # Harte Deckelung: Startchance Ausgeschlossen/Unwahrscheinlich darf nicht
    # allein durch MW-Trend/Rang bis WILL-ICH-HABEN oder ALL-IN durchbrechen
    # (siehe Reggiani-Beispiel in der Aufgabenstellung).
    "start_probability_category_cap": {"4": "ueber_marktwert", "5": "ueber_marktwert"},
    # Cold-Start-Overpay-Spannen (%) je Kategorie, genutzt so lange zu wenig
    # aehnliche echte Transfers vorliegen. Werden mit wachsendem Transfer-Log
    # zunehmend von den echten Ligadaten ueberschrieben (siehe pricing.py).
    "cold_start_overpay_pct": {
        "all_in": {"low": 10.0, "mid": 16.0, "high": 25.0},
        "will_haben": {"low": 6.0, "mid": 10.0, "high": 16.0},
        "ueber_marktwert": {"low": 1.0, "mid": 4.0, "high": 8.0},
        "marktwert": {"low": -4.0, "mid": -1.0, "high": 2.0},
    },
    # Unterhalb dieses Attraktivitaets-Scores UND wenn selbst der kalibrierte
    # Overpay nicht klar positiv ist, wird "kein Gebot" statt einer Zahl
    # empfohlen (siehe pricing.py).
    "no_bid_score_threshold": 0.30,
    "no_bid_overpay_pct_threshold": 1.0,
    # Zweite Sicherheitspruefung (pricing.py): wie gut ist die PKT/MIO-Effizienz
    # noch, wenn man tatsaechlich das empfohlene Gebot statt des Marktwerts
    # bezahlt? Bei ALL-IN-Spielern darf die normale Mindestschwelle
    # (ppm_thresholds_for) um diesen Faktor unterschritten werden, weil
    # absolute Punkte und begrenzte Startelfplaetze bei absoluten Elite-
    # Spielern einen eigenen Wert haben.
    "elite_ppm_min_relaxation": 0.85,
    # "Vergleichbar" (similarity.py) ist explizit hart auf zwei Kriterien
    # reduziert: Marktwertfenster (similarity_mv_window_pct) + gleiche
    # Position. Von den Treffern zaehlen nur die zeitlich juengsten max_k
    # ("die letzten zehn vergleichbaren Transfers", rein chronologisch sortiert
    # statt nach Aehnlichkeit) -- haelt das Modell aktuell und stabil gegen
    # einzelne neue Ausreisser. target_n = max_k, weil das Fenster bei zehn
    # Treffern voll "eingeschwungen" ist.
    "similar_transfers_target_n": 10,
    "similar_transfers_max_k": 10,
    # Marktwertfenster je Marktwertklasse (market_value_classes) in Prozent
    # des Zielmarktwerts: eng bei niedrigem Marktwert, weit bei hohem
    # Marktwert (siehe Modul-Docstring similarity.py). Ersetzt die fruehere
    # gewichtete Distanz ueber Rang/Startchance/PPM/Trend -- diese fliessen
    # nicht mehr in die Vergleichbarkeit ein.
    "similarity_mv_window_pct": [15, 20, 25, 30, 40, 50, 60, 75],
    # Zeitgewichtung (Tage seit Transfer -> Gewicht) fuer calibration.py +
    # similarity.py, aus der Aufgabenstellung uebernommen (7 Tage stark, 8-21
    # Tage mittel, aelter schwach).
    "recency_weight_days": [
        {"max_days": 7, "weight": 1.0},
        {"max_days": 21, "weight": 0.5},
        {"max_days": None, "weight": 0.2},
    ],
    # Transfers, die beim allerersten Import "rueckwirkend" entdeckt wurden
    # (also mit dem MW/Rang von HEUTE statt vom echten Transfer-Zeitpunkt
    # angereichert werden mussten, siehe transfers.py) fliessen mit reduziertem
    # Gewicht ein, um Look-ahead-Bias zu daempfen statt die Daten zu verwerfen.
    "backfilled_weight_factor": 0.6,
    # Wie stark der Liga-Markt-Faktor (aktuelle Liga-weite Preis-Aggressivitaet,
    # 7-Tage- vs. 21-Tage-Median) den finalen Overpay noch zusaetzlich
    # verschieben darf (Prozentpunkte, gedeckelt).
    "market_factor_max_shift_pct": 4.0,
    # Wie stark ein stark beschleunigender MW-Trend den Overpay INNERHALB der
    # Kategorie nach oben ziehen darf (Prozentpunkte, gedeckelt) -- siehe
    # Aufgabenstellung: "darf aggressiver gekauft werden, aber nicht den
    # sportlichen Wert dominieren".
    "trend_bonus_max_shift_pct": 3.0,
    # Marktwertklassen fuer calibration.py/similarity.py (Grenzen exklusiv oben).
    "market_value_classes": [3_000_000, 6_000_000, 10_000_000, 15_000_000, 20_000_000, 25_000_000, 30_000_000],
    # Gebotsspanne um den empfohlenen oberen Wert (Prozent des Overpay-Bereichs).
    "bid_range_lower_fraction": 0.85,
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_bidding_config(path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        user_config = {}
    return _deep_merge(DEFAULTS, user_config)
