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
    # Gewichtung (Nutzer-Korrektur, 25.9.: "Kauf-Rang + Startchance sollen mit
    # 75% klar dominieren"; vorher 35/30/20/15). MW-Trend bleibt bewusst am
    # niedrigsten gewichtet -- "darf einen sportlich schlechten Spieler
    # alleine nicht zu einem hohen Overpay-Kandidaten machen" (siehe auch die
    # separate start_probability_category_cap-Deckelung).
    "attractiveness": {
        "rank_tier_weight": 0.40,
        "start_probability_weight": 0.35,
        "ppm_efficiency_weight": 0.15,
        "market_value_trend_weight": 0.10,
    },
    # "Kurzeinsatz-Joker"-Sonderfall (Nutzer-Beispiel Ruoppi, 25.9.): begrenzter
    # EIN-Kategorie-Bonus (⚪->🟢) statt einer 5. Gewichtungssaeule, siehe
    # scoring.py::detect_efficient_substitute fuer die volle Begruendung.
    "efficient_substitute": {
        "min_appearances": 2,  # mind. 2 Einsaetze, kein Ein-Spiel-Zufallstreffer
        "max_avg_minutes_per_appearance": 30.0,  # nur echte Kurzeinsaetze, kein normaler Rotationsspieler
        "minutes_floor": 90.0,  # Shrinkage-Nenner gegen Kleinstichproben-Explosivitaet
        "min_points_per_minute": 0.55,  # Schwelle fuer "sehr effizient" auf den geshrinkten Wert
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
    # "Vergleichbar" (similarity.py) ist ein GEWICHTETER, kontinuierlicher
    # Similarity-Score (0..1) ueber mehrere Dimensionen -- kein binaeres
    # Marktwertfenster/Positions-Kriterium mehr (explizite Nutzervorgabe:
    # "keine groben Vergleichsgruppen mehr, Distanz statt Kategorien").
    # Gewichte: Startchance bildet ab, wie sicher der Spieler DAMALS spielte
    # (25%), Kauf-Rang die sportliche Gesamtattraktivitaet (20% -- kauf_rank
    # enthaelt bereits Form/Gegner/Restprogramm, siehe ranking/scoring.py,
    # "Teamstaerke" unten ist daher bewusst klein, keine Doppelgewichtung),
    # Marktwert-Klasse (20%, log-skaliert: 9 vs. 11 Mio. naeher als 9 vs.
    # 25 Mio.), MW-Trend (15%, reuse scoring.market_value_trend_score),
    # PPM-Effizienz (10%, reuse scoring.ppm_score), erwartete Performance
    # (5%, season_avg) und Teamstaerke/Rolle (5%, team_form). Summe = 1.0.
    "similarity_weights": {
        "start_probability": 0.25,
        "rank_tier": 0.20,
        "market_value": 0.20,
        "market_value_trend": 0.15,
        "ppm_efficiency": 0.10,
        "expected_performance": 0.05,
        "team_strength": 0.05,
    },
    # Mindest-Similarity (0..1, siehe similarity.similarity_score), unterhalb
    # derer ein historischer Transfer NICHT als Vergleich zaehlt -- verhindert,
    # dass bei wenigen Kandidaten schlechte Vergleiche "aufgefuellt" werden,
    # nur um eine Mindestanzahl zu erreichen. Startwert, zur Kalibrierung
    # anhand echter Ligadaten siehe backtest.py.
    "similarity_min_score": 0.55,
    # Harte Ausschlusskriterien (similarity.py), ZUSAETZLICH zur Distanz oben
    # -- manche Unterschiede sind so fundamental, dass kein Gewicht sie
    # aufwiegen darf (explizite Nutzervorgabe, siehe Modul-Docstring).
    "similarity_hard_cutoffs": {
        # Sicher/Erwartet (1/2) darf nie mit Unwahrscheinlich/Ausgeschlossen
        # (4/5) verglichen werden, unabhaengig von allen anderen Dimensionen.
        "exclude_start_probability_bucket_clash": True,
        # Maximales Marktwert-Verhaeltnis (Prozent des kleineren MW) je
        # Marktwertklasse (market_value_classes) -- deutlich weiter gefasst
        # als die fruehere similarity_mv_window_pct, weil hier nur noch die
        # absolute Notbremse gezogen wird; die eigentliche Feinabstufung
        # passiert ueber die kontinuierliche market_value-Distanz oben.
        "max_market_value_ratio_pct": [40, 50, 60, 75, 100, 120, 150, 200],
        # MW-Trend-Score (0..1, 0.5=flach) gilt oberhalb/unterhalb dieser
        # Schwellen als "stark steigend"/"stark fallend" -- ein stark
        # steigender und ein stark fallender Spieler duerfen sich nicht als
        # Hauptvergleich dienen.
        "trend_polarity_high": 0.75,
        "trend_polarity_low": 0.25,
        # Ein langfristig verletzter Spieler (Status "verletzt"/"Reha") darf
        # nicht mit einem fitten Spieler verglichen werden (und umgekehrt).
        "exclude_injury_mismatch": True,
    },
    # Ziel-/Obergrenze fuer die Anzahl beruecksichtigter Vergleichstransfers
    # (similarity.py): es werden bis zu max_k der aehnlichsten Transfers
    # oberhalb similarity_min_score verwendet -- NICHT zwangsweise
    # aufgefuellt, wenn weniger vorhanden sind (siehe Aufgabenstellung
    # "10-20, wenn nur 7 gut sind, dann 7"). target_n ist der Nenner der
    # Confidence-Berechnung (pricing._confidence): bei max_k erreichten,
    # validen Vergleichen ist das Vertrauen "voll eingeschwungen".
    "similar_transfers_target_n": 20,
    "similar_transfers_max_k": 20,
    # Halbwertszeit (Tage) fuer die Aktualitaets-Gewichtung eines Transfers
    # (stats.decay_weight) -- ersetzt die fruehere Stufenfunktion durch eine
    # kontinuierliche Kurve (explizite Nutzervorgabe: "keine starren
    # Stufen, sondern Halbwertszeit"). Bei 30 Tagen hat ein 30 Tage alter
    # Transfer noch 50% Gewicht, ein 60 Tage alter noch 25%, usw.
    "recency_half_life_days": 30.0,
    # Wenn ein Transfer laut Activity-Feed OHNE Konkurrenzgebot ("coc"/
    # bid_count == 0) gewonnen wurde, ist der gezahlte Preis eher ein
    # unkontrollierter Angebotspreis als ein echtes Wettbewerbsergebnis --
    # Kickbase liefert keine Gebotshoehen, nur die Anzahl der Gebote, ein
    # echtes "zweithoechstes Gebot" ist also nicht verfuegbar (siehe
    # transfers.py-Docstring). Solche Transfers fliessen mit reduziertem statt
    # vollem Gewicht ein.
    "bid_count_no_competition_weight": 0.85,
    # Ziel-Perzentil der (similarity- und zeitgewichteten) historischen
    # Overpay-Verteilung je Attraktivitaetskategorie -- ersetzt den fruehen
    # linearen Cold-Start-Blend (siehe pricing.py). Startwerte aus der
    # Aufgabenstellung (⚪~50., 🟢~60-65., ⭐~75-80., 🔥~85-90., hier als
    # Punktwerte), zur Kalibrierung anhand echter Ligadaten siehe backtest.py.
    # marktwert/ueber_marktwert am 25.9. angehoben (siehe backtest.py-Auswertung
    # nach 6-10 Mio.-Preisklasse): beim urspruenglichen 50./62.-Perzentil lag die
    # Trefferquote fuer 6-10 Mio.-Spieler dieser beiden Kategorien nur bei
    # 20-31% mit im Schnitt -6.6% bis -7.8% zu niedrigem Gebot -- der Median
    # (50. Perzentil per Definition) reicht dort nicht, weil die tatsaechlichen
    # Gewinnerpreise in der oberen Haelfte der Vergleichsverteilung liegen.
    # will_haben/all_in unveraendert, dort passte die Trefferquote bereits
    # (82-94%).
    "category_target_percentile": {
        "marktwert": 65,
        "ueber_marktwert": 68,
        "will_haben": 77,
        "all_in": 87,
    },
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
    # sportlichen Wert dominieren". Fallback fuer Kategorien ohne eigenen
    # Eintrag in trend_bonus_max_shift_pct_by_category.
    "trend_bonus_max_shift_pct": 3.0,
    # Kategorie-spezifische, ASYMMETRISCHE Ueberschreibung des obigen Werts
    # (Backtest + fresh-only Ligadaten, Sept. 2026): guenstige (<10 Mio.)
    # Spieler in den beiden untersten Kategorien mit klar steigendem
    # Marktwert wurden trotz ausgeschoepftem Cold-Start-Band + altem
    # symmetrischen Trend-Bonus (max. 3 Punkte) strukturell unterboten --
    # real beobachteter Overpay bei stark steigendem Trend lag deutlich
    # hoeher als altes Bandende + 3 Punkte erlaubten (marktwert/rising:
    # Median 6.6%/Ø 9.5% bei n=8 unverfaelschten Vergleichstransfers;
    # ueber_marktwert/rising: Median 8.0%/Ø 10.5% bei n=8). Fuer fallenden
    # Trend passte der ALTE, symmetrische Wert dagegen schon einigermassen
    # (fresh-only Median dort nahe 0%) -- ein rein symmetrisch erhoehter Bonus
    # haette also zusaetzlich fallende/flache guenstige Spieler faelschlich
    # noch staerker abgewertet (getestet: verschlechtert Trefferquote in
    # beiden Kategorien trotz korrekter Rising-Anpassung). Deshalb "up"
    # (steigender Trend) angehoben, "down" (fallender Trend) unveraendert bei
    # 3.0 belassen. will_haben/all_in unveraendert, dort passten Band und
    # Realdaten (auch bei teureren Spielern) schon zusammen.
    # "up" am 25.9. nochmal deutlich angehoben (6.0/5.0 -> 15.0/12.0): reichte
    # trotz der ersten Anhebung nicht aus, um die 6-10 Mio.-Trefferquote in
    # marktwert/ueber_marktwert zu retten (siehe category_target_percentile-
    # Kommentar oben fuer die Zahlen) -- Backtest-Sweep ueber mehrere Werte
    # zeigt hier ein Plateau: darueber hinaus wird v.a. bei 3-6 Mio. deutlich
    # ueberzahlt, ohne die 6-10 Mio.-Klasse nennenswert weiter zu verbessern.
    "trend_bonus_max_shift_pct_by_category": {
        "marktwert": {"up": 15.0, "down": 3.0},
        "ueber_marktwert": {"up": 12.0, "down": 3.0},
    },
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
