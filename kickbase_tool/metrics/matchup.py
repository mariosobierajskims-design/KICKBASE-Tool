"""Spielergebnis-Prognose (Nutzer-Vorgabe 2026-10-18): bewertet fuer jeden
kommenden Bundesliga-Spieltag die beiden gegnerischen Mannschaften anhand
von vier gewichteten, bereits an anderer Stelle berechneten Faktoren und
leitet daraus eine qualitative Matchup-Einschaetzung ab (klarer/leichter
Favorit, ausgeglichen, leichter/klarer Aussenseiter) -- bewusst OHNE eine
konkrete Siegwahrscheinlichkeit zu erfinden.

Wiederverwendete Bausteine (siehe metrics/calculations.py):
- team_form()          -> Faktor 1 "Teamform der letzten 5 Spiele" (35%)
- build_team_venue_ranks() -> Faktor 2 "Heim-/Auswaertsstaerke einschliess-
  lich der bestehenden Rangdifferenz" (30%) -- dieselbe Heim/Auswaerts-
  Rangberechnung, die auch Kennzahl 11 (own_venue_rank/opponent_venue_rank/
  venue_rank_diff) speist, hier nur fuer beliebige zukuenftige Spieltage
  statt nur den naechsten einzelnen angewendet.
- team_momentum()      -> Faktor 3 "Formanstieg" (20%)
- team_season_average() -> Faktor 4 "langfristige Teamstaerke anhand der
  Saisonleistung" (15%, neu, siehe calculations.py)

Alle vier Faktoren werden zuerst je ueber alle 18 Teams MIN-MAX-normalisiert
(0..1, "Alle Faktoren normalisieren" laut Vorgabe), dann gewichtet zu einem
Staerkewert pro Team UND Spielort (Heim-Staerke/Auswaerts-Staerke, da
Heim-/Auswaertsstaerke je nach Spielort unterschiedlich einfliesst) addiert.
Der Vergleich zweier Gegner ist einfach die Differenz ihrer beiden
Staerkewerte (eigene Staerke am jeweiligen Spielort minus Gegner-Staerke am
jeweiligen Spielort).

Kalibrierung (Nutzer-Vorgabe: "Schwellenwerte anhand historischer Ergebnisse
kalibrieren, keine erfundenen Siegwahrscheinlichkeiten"): die drei
Schwellenwerte (ausgeglichen/leicht/klar) werden aus den ECHTEN bisherigen
Saisonergebnissen dieser Liga abgeleitet (openligadb.extract_finished_results,
ueber Dataset.finished_results), nicht frei erfunden -- siehe
calibrate_thresholds(). Vereinfachung (dokumentiert, siehe dort): dafuer wird
der heutige (aktuelle) Staerke-Snapshot rueckwirkend auf bereits gespielte
Partien angewendet, statt fuer jeden historischen Spieltag eine eigene
Rueckwaerts-Momentaufnahme zu rekonstruieren -- bei zu wenigen bisherigen
Spielen (Saisonanfang) greift ein dokumentierter statischer Fallback.
"""
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

from kickbase_tool.data.repository import Dataset
from kickbase_tool.metrics.calculations import (
    build_team_points_by_matchday,
    build_team_venue_ranks,
    build_venue_map,
    next_n_fixtures_for_team,
    opponent_in_fixture,
    team_form,
    team_momentum,
    team_season_average,
)

UPCOMING_MATCHUP_WINDOW = 5

# Gewichtung laut Nutzer-Vorgabe, Abschnitt 1 "SPIELERGEBNISSE PROGNOSTIZIEREN".
FORM_WEIGHT = 0.35
VENUE_WEIGHT = 0.30
MOMENTUM_WEIGHT = 0.20
SEASON_WEIGHT = 0.15

# Mindestanzahl kalibrierbarer Ergebnisse, bevor calibrate_thresholds() der
# echten Saison statt dem statischen Fallback vertraut (zu wenige Spiele
# fruehsaisonal wuerden sonst ein paar Zufallsergebnisse ueberinterpretieren).
MIN_CALIBRATION_MATCHES = 20
# Anzahl gleich grosser |diff|-Buckets fuer die "klar"-Kalibrierung (siehe dort).
CALIBRATION_BUCKETS = 5
# Ab dieser Favoriten-Trefferquote innerhalb eines Buckets gilt der
# zugehoerige |diff|-Bereich als "klar" (kalibriert, kein fixer Prozentsatz
# ohne Bezug zu echten Ergebnissen -- siehe calibrate_thresholds()).
KLAR_WIN_RATE_THRESHOLD = 0.65

# Multiplikator-Spanne fuer die Punktprognose (expectedPoints * Multiplikator,
# siehe compute_team_matchday_forecasts) -- bewusst MILD: "ein starker
# Spieler kann trotz Niederlage viele KICKBASE-Punkte erzielen" (Nutzer-
# Vorgabe), das Matchup darf die Punkteprognose daher nur leicht verschieben,
# nicht dominieren.
POINTS_MULTIPLIER_SPAN = 0.15
POINTS_MULTIPLIER_MIN = 1.0 - POINTS_MULTIPLIER_SPAN
POINTS_MULTIPLIER_MAX = 1.0 + POINTS_MULTIPLIER_SPAN

MATCHUP_LABELS = {
    "klarer_favorit": ("🟢", "Klarer Favorit"),
    "leichter_favorit": ("🟢", "Leichter Favorit"),
    "ausgeglichen": ("⚪", "Ausgeglichen"),
    "leichter_aussenseiter": ("🔴", "Leichter Außenseiter"),
    "klarer_aussenseiter": ("🔴", "Klarer Außenseiter"),
}


@dataclass
class MatchupThresholds:
    """Drei |diff|-Schwellenwerte (0 <= ausgeglichen <= leicht <= klar), aus
    echten Saisonergebnissen kalibriert (siehe calibrate_thresholds()) oder
    der statische Fallback (DEFAULT_THRESHOLDS) bei zu wenig Datenbasis."""
    ausgeglichen: float
    leicht: float
    klar: float


# Fallback fuer Saisonbeginn (siehe MIN_CALIBRATION_MATCHES) -- Staerkewerte
# liegen durch die Min-Max-Normalisierung je Faktor im Bereich 0..1, ein
# realistischer Gesamt-diff zwischen zwei Teams bewegt sich erfahrungsgemaess
# etwa zwischen 0 (ausgeglichen) und ~0.4 (sehr einseitig) -- diese Werte
# sind ein dokumentierter Startpunkt, keine erfundene Praezisionsangabe, und
# werden durch calibrate_thresholds() ersetzt, sobald genug echte Ergebnisse
# vorliegen.
DEFAULT_THRESHOLDS = MatchupThresholds(ausgeglichen=0.06, leicht=0.14, klar=0.24)

TeamStrengths = Dict[str, Dict[str, float]]  # team_id -> {"home": .., "away": ..}


def normalize_min_max(values: Dict[str, Optional[float]]) -> Dict[str, float]:
    """Min-Max-Normalisierung auf [0, 1] ueber alle vorhandenen (nicht-None)
    Werte ("Alle Faktoren normalisieren", Nutzer-Vorgabe) -- hoeherer Rohwert
    wird hoeherer normalisierter Wert (alle vier Faktoren sind bereits so
    orientiert, dass hoeher = staerker). Fehlende Werte (Team ohne
    gespieltes Saisonspiel) und der entartete Fall "alle Werte gleich"
    werden neutral auf 0.5 gesetzt, statt faelschlich 0 oder 1 zu vergeben."""
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return {k: 0.5 for k in values}
    lo, hi = min(present.values()), max(present.values())
    span = hi - lo
    result: Dict[str, float] = {}
    for key in values:
        v = values.get(key)
        if v is None:
            result[key] = 0.5
        elif span <= 0:
            result[key] = 0.5
        else:
            result[key] = (v - lo) / span
    return result


def build_team_strengths(dataset: Dataset) -> TeamStrengths:
    """Staerkewert je Team UND Spielort (Heim/Auswaerts), aus den vier
    gewichteten, normalisierten Faktoren (siehe Modul-Docstring). Wird
    einmal pro Export berechnet und fuer alle 5 kommenden Spieltage jedes
    Teams wiederverwendet (die Faktoren selbst sind "heutige" Momentaufnahmen,
    keine spieltagsspezifische Neuberechnung in die Zukunft -- echte
    zukuenftige Form gibt es nicht)."""
    team_points = build_team_points_by_matchday(dataset.players)
    venue_map = build_venue_map(dataset.fixtures)
    all_team_ids = list(dataset.table_by_team)
    n = len(all_team_ids)

    form_values = {tid: team_form(team_points, tid) for tid in all_team_ids}
    momentum_values = {tid: team_momentum(team_points, tid) for tid in all_team_ids}
    season_values = {tid: team_season_average(team_points, tid) for tid in all_team_ids}
    home_venue_ranks, away_venue_ranks = build_team_venue_ranks(
        team_points, venue_map, all_team_ids,
        official_home_points=dataset.home_venue_points, official_away_points=dataset.away_venue_points,
    )

    form_norm = normalize_min_max(form_values)
    momentum_norm = normalize_min_max(momentum_values)
    season_norm = normalize_min_max(season_values)
    # Rang 1 (bester) -> 1.0, Rang n (schlechtester) -> 0.0 -- dieselbe
    # Umrechnung wie percentileScore() im Artifact-Frontend, hier fuer die
    # BEREITS vorhandenen Heim-/Auswaerts-Raenge (own_venue_rank-Mechanik),
    # keine neue Venue-Berechnung ("einschliesslich der bestehenden
    # Rangdifferenz").
    def rank_norm(ranks: Dict[str, float]) -> Dict[str, float]:
        if n <= 1:
            return {tid: 0.5 for tid in ranks}
        return {tid: (n - r) / (n - 1) for tid, r in ranks.items()}

    venue_home_norm = rank_norm(home_venue_ranks)
    venue_away_norm = rank_norm(away_venue_ranks)

    strengths: TeamStrengths = {}
    for tid in all_team_ids:
        strengths[tid] = {
            "home": (
                FORM_WEIGHT * form_norm.get(tid, 0.5)
                + VENUE_WEIGHT * venue_home_norm.get(tid, 0.5)
                + MOMENTUM_WEIGHT * momentum_norm.get(tid, 0.5)
                + SEASON_WEIGHT * season_norm.get(tid, 0.5)
            ),
            "away": (
                FORM_WEIGHT * form_norm.get(tid, 0.5)
                + VENUE_WEIGHT * venue_away_norm.get(tid, 0.5)
                + MOMENTUM_WEIGHT * momentum_norm.get(tid, 0.5)
                + SEASON_WEIGHT * season_norm.get(tid, 0.5)
            ),
        }
    return strengths


def _strength_diff(team_strengths: TeamStrengths, home_team_id: str, away_team_id: str) -> Optional[float]:
    home = team_strengths.get(home_team_id)
    away = team_strengths.get(away_team_id)
    if home is None or away is None:
        return None
    return home["home"] - away["away"]


def calibrate_thresholds(dataset: Dataset, team_strengths: TeamStrengths) -> MatchupThresholds:
    """Leitet die drei Schwellenwerte aus den ECHTEN bisherigen Saison-
    ergebnissen ab (dataset.finished_results, siehe
    openligadb.extract_finished_results) -- keine erfundenen Zahlen.

    Vereinfachung (dokumentiert): verwendet dafuer den HEUTIGEN
    Staerke-Snapshot rueckwirkend auf jedes bereits gespielte Spiel, statt
    fuer jeden vergangenen Spieltag eine eigene Momentaufnahme der damaligen
    Form/Tabellenlage zu rekonstruieren -- ein spuerbarer, aber fuer eine
    Kalibrierung von Schwellenwerten (nicht von Einzelprognosen) akzeptabler
    Kompromiss, da die relative Reihenfolge der Teams sich innerhalb einer
    Saison nur langsam verschiebt.

    - "ausgeglichen": Median des |diff| aller UNENTSCHIEDEN (daraus leitet
      sich ab, in welchem Naehebereich reale Unentschieden tatsaechlich
      vorkommen) -- faellt bei zu wenigen Unentschieden auf das 25.
      Perzentil aller |diff|-Werte zurueck.
    - "klar": |diff| wird in CALIBRATION_BUCKETS gleich grosse Gruppen
      sortiert; "klar" ist die untere Grenze der kleinsten Gruppe, in der
      der Favorit (die durch diff vorne liegende Seite) tatsaechlich in
      mindestens KLAR_WIN_RATE_THRESHOLD der Faelle gewinnt -- findet sich
      keine solche Gruppe, faellt "klar" auf das 80. Perzentil zurueck.
    - "leicht": Mittelwert aus "ausgeglichen" und "klar".

    Bei weniger als MIN_CALIBRATION_MATCHES verwertbaren Ergebnissen
    (Saisonanfang, oder dataset.finished_results leer weil der
    OpenLigaDB-Abruf fehlschlug) wird DEFAULT_THRESHOLDS zurueckgegeben.
    """
    pairs: List[tuple] = []
    for result in dataset.finished_results:
        diff = _strength_diff(team_strengths, result["home_team_id"], result["away_team_id"])
        if diff is None:
            continue
        pairs.append((diff, result["outcome"]))

    if len(pairs) < MIN_CALIBRATION_MATCHES:
        return DEFAULT_THRESHOLDS

    abs_diffs = sorted(abs(d) for d, _ in pairs)

    draw_abs_diffs = sorted(abs(d) for d, o in pairs if o == "draw")
    ausgeglichen = statistics.median(draw_abs_diffs) if draw_abs_diffs else _percentile(abs_diffs, 0.25)

    by_abs = sorted(pairs, key=lambda p: abs(p[0]))
    bucket_size = max(1, len(by_abs) // CALIBRATION_BUCKETS)
    klar = None
    for i in range(0, len(by_abs), bucket_size):
        bucket = by_abs[i:i + bucket_size]
        if not bucket:
            continue
        favorite_wins = sum(
            1 for d, o in bucket if (o == "home" and d > 0) or (o == "away" and d < 0)
        )
        win_rate = favorite_wins / len(bucket)
        if win_rate >= KLAR_WIN_RATE_THRESHOLD:
            klar = min(abs(d) for d, _ in bucket)
            break
    if klar is None:
        klar = _percentile(abs_diffs, 0.80)
    klar = max(klar, ausgeglichen * 1.5, 1e-6)

    leicht = (ausgeglichen + klar) / 2
    return MatchupThresholds(ausgeglichen=ausgeglichen, leicht=leicht, klar=klar)


def _percentile(sorted_values: List[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[idx]


def classify_diff(diff: float, thresholds: MatchupThresholds) -> dict:
    """Ordnet eine Staerke-Differenz (eigenes Team minus Gegner, am
    jeweiligen Spielort) einer der 5 Prognose-Stufen zu (Nutzer-Vorgabe,
    Abschnitt 1) -- Unentschieden wird ausdrueckluch ueber die
    "ausgeglichen"-Stufe abgebildet. Die Abstaende zwischen den Mannschaften
    (|diff| vs. die kalibrierten Schwellenwerte) bestimmen, wie eindeutig die
    Prognose ausfaellt."""
    abs_diff = abs(diff)
    if abs_diff <= thresholds.ausgeglichen:
        key = "ausgeglichen"
    elif diff > 0:
        key = "klarer_favorit" if abs_diff >= thresholds.klar else "leichter_favorit"
    else:
        key = "klarer_aussenseiter" if abs_diff >= thresholds.klar else "leichter_aussenseiter"
    emoji, label = MATCHUP_LABELS[key]
    return {"key": key, "emoji": emoji, "label": label}


def matchup_quality(diff: float) -> float:
    """0..1-Qualitaetswert fuer die Spieltagsbewertung (70% Aufstellungsrang
    + 30% Matchup-Score, siehe ranking/scoring.py-Pendant im Artifact-
    Frontend) -- diff liegt ueblicherweise in [-1, 1], wird zur Sicherheit
    trotzdem geklemmt."""
    return max(0.0, min(1.0, (diff + 1.0) / 2.0))


def points_multiplier(diff: float) -> float:
    """Milder Multiplikator fuer die Punktprognose (siehe POINTS_MULTIPLIER_SPAN
    oben) -- bewusst klein, damit ein starker Spieler trotz schwerem Gegner
    weiterhin eine hohe Punktprognose behalten kann."""
    raw = 1.0 + POINTS_MULTIPLIER_SPAN * max(-1.0, min(1.0, diff))
    return max(POINTS_MULTIPLIER_MIN, min(POINTS_MULTIPLIER_MAX, raw))


def compute_team_matchday_forecasts(
    dataset: Dataset,
    team_strengths: TeamStrengths,
    thresholds: MatchupThresholds,
    window: int = UPCOMING_MATCHUP_WINDOW,
) -> Dict[str, List[dict]]:
    """Fuer jedes Team: die naechsten `window` Spieltage mit Gegner,
    Spielort, Matchup-Einstufung und den daraus abgeleiteten Werten fuer
    Spieltagsbewertung (quality) und Punktprognose (points_multiplier) im
    Artifact-Frontend. Wird 1:1 in jeden Spieler-Export uebernommen (ueber
    sein team_id, siehe export_artifact.py) -- Spieler desselben Teams
    teilen sich denselben Forecast."""
    all_team_ids = list(dataset.table_by_team)
    result: Dict[str, List[dict]] = {}
    for team_id in all_team_ids:
        upcoming = next_n_fixtures_for_team(dataset.fixtures, team_id, window)
        forecasts = []
        for fixture in upcoming:
            opponent_id = opponent_in_fixture(fixture, team_id)
            is_home = fixture.home_team_id == team_id
            own_strength = team_strengths.get(team_id, {}).get("home" if is_home else "away")
            opponent_strength = team_strengths.get(opponent_id, {}).get("away" if is_home else "home")
            if own_strength is None or opponent_strength is None:
                diff = 0.0
            else:
                diff = own_strength - opponent_strength
            classification = classify_diff(diff, thresholds)
            opponent_entry = dataset.table_by_team.get(opponent_id)
            forecasts.append({
                "matchday": fixture.matchday,
                "opponent_team_id": opponent_id,
                "opponent_name": opponent_entry.team_name if opponent_entry else opponent_id,
                "home": is_home,
                "diff": diff,
                "label": classification["label"],
                "emoji": classification["emoji"],
                "quality": matchup_quality(diff),
                "points_multiplier": points_multiplier(diff),
            })
        result[team_id] = forecasts
    return result
