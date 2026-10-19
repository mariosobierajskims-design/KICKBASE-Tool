"""Spielergebnis-Prognose (urspruengliche Nutzer-Vorgabe 2026-10-18, ueber-
arbeitet 2026-10-19 nach Nutzer-Korrektur): bewertet fuer jeden kommenden
Bundesliga-Spieltag die beiden gegnerischen Mannschaften und leitet daraus
eine qualitative Matchup-Einschaetzung ab (klarer/leichter Sieg, ausgeglichen/
Unentschieden, leichte/klare Niederlage) -- bewusst OHNE eine konkrete
Siegwahrscheinlichkeit zu erfinden. Die oeffentliche Schnittstelle (Funktions-
namen/-signaturen, Rueckgabeform von compute_team_matchday_forecasts, die 5
Label/Emoji-Stufen) ist UNVERAENDERT -- siehe export_artifact.py und das
Artifact-Frontend (Spalte "⚔️ Matchup"), die diese Form bereits konsumieren.

Nutzer-Korrektur 2026-10-19, fuenf Punkte (siehe jeweils markierte Stellen):

1) Faktor 2 "Heim-/Auswaertsstaerke" nutzt NICHT mehr den Rang in der echten
   Bundesliga-Heim-/Auswaerts-Tabelle (das bleibt Kennzahl 11 vorbehalten,
   siehe calculations.py::build_team_venue_ranks, UNVERAENDERT), sondern den
   tatsaechlichen DURCHSCHNITTLICHEN KICKBASE-Teampunktwert am jeweiligen
   Spielort (calculations.py::team_venue_form, bereits vorhanden, bisher nur
   als Kickbase-interner FALLBACK genutzt -- jetzt der PRIMAERE Pfad fuer
   diese Prognose). Min-Max-normalisiert wie alle anderen Faktoren, nicht
   mehr rang-basiert.

2) NEUER 5. Faktor "Tordifferenz": durchschnittliche erzielte minus kassierte
   Tore pro Spiel, getrennt nach Heim-/Auswaertsspielen, aus den echten
   OpenLigaDB-Saisonergebnissen (Dataset.finished_results, jetzt inkl.
   home_goals/away_goals, siehe data/openligadb.py). Das ist echtes
   Fussball-Ergebnis-Signal (nicht Kickbase-Fantasiepunkte) und zielt direkt
   auf Sieg/Unentschieden/Niederlage, nicht nur auf Punkteprognose. Sein
   Gewicht (GOAL_WEIGHT) wird NICHT willkuerlich festgelegt, sondern per
   echtem WALK-FORWARD-Backtest (siehe Punkt 5) aus einem kleinen Raster von
   Kandidatengewichten ausgewaehlt: fuer jeden Kandidaten wird die
   Konkordanz (siehe _concordance_score) zwischen prognostizierter
   Staerke-Differenz und echtem Saisonergebnis gemessen, der Kandidat mit der
   hoechsten Konkordanz gewinnt (select_goal_weight()). Die urspruenglichen
   vier Faktoren behalten dabei ihr relatives Verhaeltnis 35:30:20:15
   zueinander, ihr GEMEINSAMER Anteil schrumpft nur um genau den Anteil, der
   an den Tor-Faktor geht (legacy_scale = 1 - goal_weight).

3) classify_diff()/die 5 Stufen bleiben unveraendert (Nutzer-Vorgabe: Stufen
   beibehalten). Was sich aendert: calibrate_thresholds() leitet die
   "ausgeglichen"-Schwelle nicht mehr aus dem (bei wenigen/verrauschten
   Unentschieden potenziell irrefuehrenden) Median-|diff| ALLER Unentschieden
   ab, sondern aus dem |diff|-Bereich, in dem Unentschieden ECHT HAEUFIGER
   als im Saison-Durchschnitt vorkommen (bucket-weise, striktes Kriterium).
   "Aehnliche Teamstaerke" wird damit NICHT mehr automatisch mit einer
   Unentschieden-Prognose gleichgesetzt -- nur dort, wo die echten Ergebnisse
   das tatsaechlich stuetzen; sonst faellt die Prognose auf eine knappe
   Sieg-/Niederlage-Einstufung statt "Ausgeglichen". Die drei Schwellenwerte
   bleiben lueckenlos geordnet (ausgeglichen <= leicht <= klar, siehe die
   `max(..., ...)`-Sicherung).

4) Fehlende Einzelfaktoren (z.B. Momentum vor Spieltag 7, siehe
   team_momentum()) werden NICHT mehr neutral mit 0.5 aufgefuellt und bluten
   dabei wirkungslos ihr volles Gewicht ab, sondern aus der Gewichtung
   HERAUSGENOMMEN; die uebrigen vorhandenen Faktoren werden proportional auf
   100% ihres gemeinsamen Gewichts hochskaliert (siehe _weighted_value()).
   Betrifft generisch jeden der 5 Faktoren, nicht nur Momentum.

5) Echter WALK-FORWARD-Backtest fuer die Gewichtsauswahl (select_goal_weight)
   via _walk_forward_diff_outcome_pairs(): fuer jeden bereits gespielten
   Spieltag N wird die Prognose NUR aus Daten VOR Spieltag N gebildet (Team-
   punkte/Tore mit Spieltag < N gefiltert), dann mit dem ECHTEN Ergebnis von
   Spieltag N verglichen -- keine Daten aus der Zukunft dieses Spieltags.
   Das ersetzt fuer die Gewichtsauswahl die fruehere Vereinfachung (heutiger
   Staerke-Snapshot rueckwirkend auf die ganze Saison angewendet).
   calibrate_thresholds() selbst bleibt aus Kompatibilitaetsgruenden bei
   seiner bestehenden (dokumentierten, weiterhin akzeptablen) Snapshot-
   Methode fuer die drei Schwellenwerte -- siehe dortigen Docstring.

Wiederverwendete Bausteine (siehe metrics/calculations.py, UNVERAENDERT):
- team_form()          -> Faktor 1 "Teamform der letzten 5 Spiele"
- team_venue_form()    -> Faktor 2 "Heim-/Auswaertsstaerke" (siehe Punkt 1)
- team_momentum()      -> Faktor 3 "Formanstieg"
- team_season_average() -> Faktor 4 "langfristige Teamstaerke"
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from kickbase_tool.data.repository import Dataset
from kickbase_tool.metrics.calculations import (
    TeamPointsByMatchday,
    VenueMap,
    build_team_points_by_matchday,
    build_venue_map,
    next_n_fixtures_for_team,
    opponent_in_fixture,
    team_form,
    team_momentum,
    team_season_average,
    team_venue_form,
)
from kickbase_tool.util import mean

UPCOMING_MATCHUP_WINDOW = 5

# Gewichtung der vier urspruenglichen Faktoren UNTEREINANDER (Nutzer-Vorgabe
# Abschnitt 1, "grundsaetzlich beibehalten") -- ihr GEMEINSAMER Anteil an der
# Gesamtgewichtung ist nicht mehr fix 100%, sondern wird um den Anteil des
# neuen Tor-Faktors (siehe GOAL_WEIGHT_CANDIDATES/select_goal_weight) auf
# `legacy_scale = 1 - goal_weight` herunterskaliert, siehe _strengths_from_raw().
LEGACY_FORM_WEIGHT = 0.35
LEGACY_VENUE_WEIGHT = 0.30
LEGACY_MOMENTUM_WEIGHT = 0.20
LEGACY_SEASON_WEIGHT = 0.15

# Kandidaten-Raster fuer das Gewicht des neuen Tordifferenz-Faktors, per
# Walk-Forward-Backtest ausgewertet (siehe select_goal_weight()) -- 0.40 als
# Obergrenze, damit der Tor-Faktor die vier bestehenden, Kickbase-
# punktbasierten Faktoren nicht pauschal entwerten kann (die Vorgabe war,
# sie "grundsaetzlich beizubehalten", nicht sie zu ersetzen).
GOAL_WEIGHT_CANDIDATES = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]

# Mindestanzahl historischer (Walk-Forward- bzw. Kalibrierungs-)Ergebnisse,
# bevor sich select_goal_weight()/calibrate_thresholds() der echten Saison
# statt eines statischen Fallbacks bedienen (zu wenige Spiele fruehsaisonal
# wuerden sonst ein paar Zufallsergebnisse ueberinterpretieren).
MIN_CALIBRATION_MATCHES = 20
# Anzahl gleich grosser |diff|-Buckets fuer die Schwellenwert-Kalibrierung.
CALIBRATION_BUCKETS = 5
# Ab dieser Favoriten-Trefferquote innerhalb eines Buckets gilt der
# zugehoerige |diff|-Bereich als "klar" (kalibriert, kein fixer Prozentsatz
# ohne Bezug zu echten Ergebnissen -- siehe calibrate_thresholds()).
KLAR_WIN_RATE_THRESHOLD = 0.65

# Multiplikator-Spanne fuer die Punktprognose (expectedPoints * Multiplikator,
# siehe compute_team_matchday_forecasts) -- bewusst MILD: "ein starker
# Spieler kann trotz Niederlage viele KICKBASE-Punkte erzielen" (Nutzer-
# Vorgabe), das Matchup darf die Punkteprognose daher nur leicht verschieben,
# nicht dominieren. UNVERAENDERT durch die Nutzer-Korrektur.
POINTS_MULTIPLIER_SPAN = 0.15
POINTS_MULTIPLIER_MIN = 1.0 - POINTS_MULTIPLIER_SPAN
POINTS_MULTIPLIER_MAX = 1.0 + POINTS_MULTIPLIER_SPAN

# Die 5 Prognosestufen (Label/Emoji) -- UNVERAENDERT, Nutzer-Vorgabe
# "Prognosestufen beibehalten". Das Artifact-Frontend leitet daraus seine
# eigene Anzeige ab (siehe matchupResultTierFor() im Artifact), ueber das
# "Klar" in label bzw. das emoji -- beides bleibt identisch erhalten.
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
    Werte -- hoeherer Rohwert wird hoeherer normalisierter Wert (alle Faktoren
    sind bereits so orientiert, dass hoeher = staerker). Fehlende Werte und
    der entartete Fall "alle Werte gleich" werden neutral auf 0.5 gesetzt.
    UNVERAENDERT durch die Nutzer-Korrektur (weiterhin direkt getestet,
    siehe tests/test_matchup.py) -- die "fehlender Faktor"-Behandlung fuer
    die STAERKE-Berechnung selbst sitzt jetzt eine Ebene hoeher in
    _weighted_value() (Nutzer-Vorgabe 4, proportionale Neugewichtung statt
    neutralem Auffuellen)."""
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


@dataclass
class RawFactors:
    """Die (noch nicht gewichteten) 0..1-normalisierten Werte aller 5
    Faktoren je Team, getrennt nach Heim-/Auswaertsrolle wo zutreffend --
    Zwischenergebnis zwischen "Rohdaten einsammeln" (_compute_raw_factors)
    und "zu einer Staerke gewichten" (_strengths_from_raw), damit letzteres
    fuer verschiedene goal_weight-Kandidaten wiederholt aufgerufen werden
    kann, ohne die (unveraenderlichen) Rohdaten neu einsammeln zu muessen."""
    form: Dict[str, Optional[float]]
    venue_home: Dict[str, Optional[float]]
    venue_away: Dict[str, Optional[float]]
    momentum: Dict[str, Optional[float]]
    season: Dict[str, Optional[float]]
    goal_home: Dict[str, Optional[float]]
    goal_away: Dict[str, Optional[float]]


def _goal_diff_by_team_venue(
    finished_results: List[dict], max_matchday: Optional[int]
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """NEUER Faktor (Nutzer-Vorgabe 2): durchschnittliche Tordifferenz
    (erzielt minus kassiert) pro Spiel, getrennt nach Heim-/Auswaertsspielen,
    aus den echten OpenLigaDB-Ergebnissen (Dataset.finished_results, inkl.
    home_goals/away_goals -- siehe data/openligadb.py::extract_finished_results).
    max_matchday=None nutzt alle vorliegenden Ergebnisse (fuer die LIVE-
    Prognose); ein gesetzter Wert beschraenkt auf Ergebnisse VOR diesem
    Spieltag (fuer den walk-forward-Backtest, siehe
    _walk_forward_diff_outcome_pairs() -- "ohne Daten zukuenftiger
    Spieltage"). Ergebnisse ohne Tordaten oder (bei gesetztem max_matchday)
    ohne bekannte Spieltagsnummer werden uebersprungen statt zu raten."""
    home_vals: Dict[str, List[float]] = {}
    away_vals: Dict[str, List[float]] = {}
    for r in finished_results:
        home_goals, away_goals = r.get("home_goals"), r.get("away_goals")
        if home_goals is None or away_goals is None:
            continue
        if max_matchday is not None:
            matchday = r.get("matchday")
            if matchday is None or matchday > max_matchday:
                continue
        home_vals.setdefault(r["home_team_id"], []).append(float(home_goals - away_goals))
        away_vals.setdefault(r["away_team_id"], []).append(float(away_goals - home_goals))
    return (
        {tid: mean(vals) for tid, vals in home_vals.items()},
        {tid: mean(vals) for tid, vals in away_vals.items()},
    )


def _compute_raw_factors(
    team_points: TeamPointsByMatchday,
    venue_map: VenueMap,
    finished_results: List[dict],
    all_team_ids: List[str],
    max_matchday: Optional[int],
) -> RawFactors:
    """Sammelt die 5 Rohfaktoren je Team ein. `team_points` wird vom Aufrufer
    bereits passend zugeschnitten uebergeben (voller Saisonstand fuer die
    LIVE-Prognose, oder auf Spieltage < N fuer den walk-forward-Backtest --
    team_form()/team_momentum()/team_season_average()/team_venue_form()
    leiten "aktuellster Spieltag" direkt aus den in `team_points`
    VORHANDENEN Spieltagen ab, eine Einschraenkung dort wirkt sich also
    automatisch hier aus). `max_matchday` steuert nur zusaetzlich den
    Tor-Faktor (siehe _goal_diff_by_team_venue()), der seine eigene Zeitachse
    (Dataset.finished_results) hat."""
    goal_home_raw, goal_away_raw = _goal_diff_by_team_venue(finished_results, max_matchday)
    return RawFactors(
        form={tid: team_form(team_points, tid) for tid in all_team_ids},
        venue_home={tid: team_venue_form(team_points, venue_map, tid, home=True) for tid in all_team_ids},
        venue_away={tid: team_venue_form(team_points, venue_map, tid, home=False) for tid in all_team_ids},
        momentum={tid: team_momentum(team_points, tid) for tid in all_team_ids},
        season={tid: team_season_average(team_points, tid) for tid in all_team_ids},
        goal_home={tid: goal_home_raw.get(tid) for tid in all_team_ids},
        goal_away={tid: goal_away_raw.get(tid) for tid in all_team_ids},
    )


def _weighted_value(components: List[Tuple[Optional[float], float, float]]) -> float:
    """Gewichtete Summe normalisierter 0..1-Faktorwerte eines Teams
    (Komponenten: (ROHwert-oder-None, normalisierter Wert, Gewicht)).
    Nutzer-Vorgabe 4: ein Faktor, dessen ROHWERT fuer dieses Team fehlt
    (None -- z.B. Momentum vor Spieltag 7, oder Tordifferenz fuer ein Team
    ohne bisheriges Heimspiel), wird HERAUSGENOMMEN statt neutral mit 0.5
    aufgefuellt zu werden; die uebrigen vorhandenen Faktoren werden
    proportional auf 100% ihres gemeinsamen Gewichts hochskaliert. Fehlen
    ALLE Faktoren, bleibt 0.5 (neutral) als letzter Ausweg, analog
    normalize_min_max()."""
    present = [(norm, weight) for raw_value, norm, weight in components if raw_value is not None and weight > 0]
    weight_sum = sum(w for _, w in present)
    if not present or weight_sum <= 0:
        return 0.5
    return sum(v * w for v, w in present) / weight_sum


def _strengths_from_raw(raw: RawFactors, all_team_ids: List[str], goal_weight: float) -> TeamStrengths:
    """Gewichtet die 5 (bereits eingesammelten) Rohfaktoren zu einer
    Heim-/Auswaerts-Staerke je Team, fuer ein gegebenes `goal_weight`
    (siehe select_goal_weight() fuer dessen Herkunft). Getrennt von
    _compute_raw_factors(), damit der Walk-Forward-Backtest viele
    goal_weight-Kandidaten gegen DIESELBEN Rohdaten durchrechnen kann, ohne
    sie jedes Mal neu aus team_points/venue_map/finished_results
    abzuleiten."""
    legacy_scale = 1.0 - goal_weight
    w_form = LEGACY_FORM_WEIGHT * legacy_scale
    w_venue = LEGACY_VENUE_WEIGHT * legacy_scale
    w_momentum = LEGACY_MOMENTUM_WEIGHT * legacy_scale
    w_season = LEGACY_SEASON_WEIGHT * legacy_scale
    w_goal = goal_weight

    form_norm = normalize_min_max(raw.form)
    venue_home_norm = normalize_min_max(raw.venue_home)
    venue_away_norm = normalize_min_max(raw.venue_away)
    momentum_norm = normalize_min_max(raw.momentum)
    season_norm = normalize_min_max(raw.season)
    goal_home_norm = normalize_min_max(raw.goal_home)
    goal_away_norm = normalize_min_max(raw.goal_away)

    strengths: TeamStrengths = {}
    for tid in all_team_ids:
        home_components = [
            (raw.form.get(tid), form_norm.get(tid, 0.5), w_form),
            (raw.venue_home.get(tid), venue_home_norm.get(tid, 0.5), w_venue),
            (raw.momentum.get(tid), momentum_norm.get(tid, 0.5), w_momentum),
            (raw.season.get(tid), season_norm.get(tid, 0.5), w_season),
            (raw.goal_home.get(tid), goal_home_norm.get(tid, 0.5), w_goal),
        ]
        away_components = [
            (raw.form.get(tid), form_norm.get(tid, 0.5), w_form),
            (raw.venue_away.get(tid), venue_away_norm.get(tid, 0.5), w_venue),
            (raw.momentum.get(tid), momentum_norm.get(tid, 0.5), w_momentum),
            (raw.season.get(tid), season_norm.get(tid, 0.5), w_season),
            (raw.goal_away.get(tid), goal_away_norm.get(tid, 0.5), w_goal),
        ]
        strengths[tid] = {
            "home": _weighted_value(home_components),
            "away": _weighted_value(away_components),
        }
    return strengths


def _walk_forward_diff_outcome_pairs(
    dataset: Dataset, all_team_ids: List[str], goal_weight: float
) -> List[Tuple[float, str]]:
    """Echter Walk-Forward-Backtest (Nutzer-Vorgabe 5): fuer jeden bereits
    gespielten Spieltag N wird die Staerke-Differenz NUR aus Team-
    punkten/Toren VOR Spieltag N berechnet (cutoff = N-1), dann mit dem
    ECHTEN Ergebnis von Spieltag N verglichen -- keine Daten aus der Zukunft
    dieses Spieltags fliessen ein. Spieltag 1 hat keine Vorgeschichte und
    wird uebersprungen. Ergebnisse ohne bekannte Spieltagsnummer (siehe
    openligadb.extract_finished_results) koennen nicht einsortiert werden
    und werden ebenfalls uebersprungen."""
    results = [r for r in dataset.finished_results if r.get("matchday") is not None]
    if not results:
        return []
    full_team_points = build_team_points_by_matchday(dataset.players)
    venue_map = build_venue_map(dataset.fixtures)
    played_matchdays = sorted({r["matchday"] for r in results})

    pairs: List[Tuple[float, str]] = []
    for matchday in played_matchdays:
        cutoff = matchday - 1
        if cutoff < 1:
            continue
        cutoff_points = {key: value for key, value in full_team_points.items() if key[1] <= cutoff}
        raw = _compute_raw_factors(cutoff_points, venue_map, results, all_team_ids, max_matchday=cutoff)
        strengths = _strengths_from_raw(raw, all_team_ids, goal_weight)
        for result in results:
            if result["matchday"] != matchday:
                continue
            diff = _strength_diff(strengths, result["home_team_id"], result["away_team_id"])
            if diff is not None:
                pairs.append((diff, result["outcome"]))
    return pairs


def _concordance_score(pairs: List[Tuple[float, str]]) -> float:
    """Schwellenwert-freies Qualitaetsmass (0.5 = Zufall, 1.0 = perfekt), ob
    groessere Staerke-Differenzen tatsaechlich mit eindeutigeren Ergebnissen
    fuer die favorisierte Seite einhergehen -- eine verallgemeinerte
    Konkordanz (Somers'-D-Idee) ueber alle Paare von Spielen mit
    UNTERSCHIEDLICHEM Ausgang. Damit laesst sich die Qualitaet eines
    goal_weight-Kandidaten bewerten, OHNE schon vorher auf konkrete
    Schwellenwerte committen zu muessen (siehe select_goal_weight(), Nutzer-
    Vorgabe 2: Gewichtung anhand echter Prognosequalitaet, nicht
    willkuerlich)."""
    outcome_value = {"home": 1, "draw": 0, "away": -1}
    n = len(pairs)
    if n < 2:
        return 0.5
    concordant = discordant = tied = 0
    for i in range(n):
        diff_i, outcome_i = pairs[i]
        y_i = outcome_value[outcome_i]
        for j in range(i + 1, n):
            diff_j, outcome_j = pairs[j]
            y_j = outcome_value[outcome_j]
            if y_i == y_j:
                continue
            d_sign = (diff_i > diff_j) - (diff_i < diff_j)
            y_sign = (y_i > y_j) - (y_i < y_j)
            if d_sign == 0:
                tied += 1
            elif d_sign == y_sign:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant + tied
    if total == 0:
        return 0.5
    return (concordant + 0.5 * tied) / total


def select_goal_weight(dataset: Dataset) -> float:
    """Waehlt das Gewicht des neuen Tordifferenz-Faktors aus
    GOAL_WEIGHT_CANDIDATES per echtem Walk-Forward-Backtest (Nutzer-Vorgabe
    2+5): fuer jeden Kandidaten wird _walk_forward_diff_outcome_pairs()
    neu berechnet (die Staerke-Differenzen haengen vom Kandidatengewicht ab)
    und per _concordance_score() bewertet; der Kandidat mit der hoechsten
    Konkordanz gewinnt. Oeffentlich (nicht "_"-praefixiert), damit ein
    Analyse-/Debug-Lauf nachvollziehen kann, welches Gewicht die Liga-Daten
    gerade stuetzen. Faellt auf 0.0 zurueck (= Tor-Faktor hat keinen
    Einfluss, Verhalten wie vor dieser Korrektur), wenn weniger als
    MIN_CALIBRATION_MATCHES walk-forward-Ergebnispaare vorliegen (Saison-
    anfang, oder Dataset.finished_results leer/ohne Spieltagsnummer)."""
    all_team_ids = list(dataset.table_by_team)
    baseline_pairs = _walk_forward_diff_outcome_pairs(dataset, all_team_ids, GOAL_WEIGHT_CANDIDATES[0])
    if len(baseline_pairs) < MIN_CALIBRATION_MATCHES:
        return 0.0

    best_weight, best_score = 0.0, -1.0
    for candidate in GOAL_WEIGHT_CANDIDATES:
        pairs = _walk_forward_diff_outcome_pairs(dataset, all_team_ids, candidate)
        score = _concordance_score(pairs)
        if score > best_score:
            best_score, best_weight = score, candidate
    return best_weight


def build_team_strengths(dataset: Dataset) -> TeamStrengths:
    """Staerkewert je Team UND Spielort (Heim/Auswaerts), aus den 5
    gewichteten, normalisierten Faktoren (siehe Modul-Docstring). Wird
    einmal pro Export berechnet und fuer alle 5 kommenden Spieltage jedes
    Teams wiederverwendet. Oeffentliche Signatur UNVERAENDERT (ein Dataset-
    Argument) -- die Auswahl des Tor-Faktor-Gewichts (select_goal_weight)
    passiert intern, siehe Modul-Docstring Punkt 2."""
    all_team_ids = list(dataset.table_by_team)
    full_team_points = build_team_points_by_matchday(dataset.players)
    venue_map = build_venue_map(dataset.fixtures)
    goal_weight = select_goal_weight(dataset)
    raw = _compute_raw_factors(full_team_points, venue_map, dataset.finished_results, all_team_ids, max_matchday=None)
    return _strengths_from_raw(raw, all_team_ids, goal_weight)


def _strength_diff(team_strengths: TeamStrengths, home_team_id: str, away_team_id: str) -> Optional[float]:
    """Staerke-Differenz aus Sicht des HEIMTEAMS (positiv = Heimteam-Vorteil).
    Fuer das Auswaertsteam ergibt sich am selben Spiel rechnerisch IMMER
    exakt der negierte Wert (strengths[away]['away'] - strengths[home]['home']
    == -(strengths[home]['home'] - strengths[away]['away'])) -- das ist die
    Grundlage fuer die in Nutzer-Vorgabe 6 verlangte Spiegelsymmetrie
    zwischen den Prognosen beider Teams (siehe
    test_compute_team_matchday_forecasts_is_mirror_symmetric_for_both_sides)."""
    home = team_strengths.get(home_team_id)
    away = team_strengths.get(away_team_id)
    if home is None or away is None:
        return None
    return home["home"] - away["away"]


def calibrate_thresholds(dataset: Dataset, team_strengths: TeamStrengths) -> MatchupThresholds:
    """Leitet die drei Schwellenwerte aus den ECHTEN bisherigen Saison-
    ergebnissen ab (dataset.finished_results, siehe
    openligadb.extract_finished_results) -- keine erfundenen Zahlen.

    Vereinfachung (dokumentiert, UNVERAENDERT durch die Nutzer-Korrektur):
    verwendet dafuer den HEUTIGEN Staerke-Snapshot rueckwirkend auf jedes
    bereits gespielte Spiel, statt fuer jeden vergangenen Spieltag eine
    eigene Momentaufnahme der damaligen Form/Tabellenlage zu rekonstruieren
    -- ein spuerbarer, aber fuer eine Kalibrierung von SCHWELLENWERTEN
    (nicht von Einzelprognosen, und nicht von der Faktor-GEWICHTUNG, die
    seit der Nutzer-Korrektur per echtem Walk-Forward-Backtest in
    select_goal_weight() laeuft) akzeptabler Kompromiss, da die relative
    Reihenfolge der Teams sich innerhalb einer Saison nur langsam verschiebt.
    Bewusst beibehalten (statt ebenfalls auf Walk-Forward umgestellt), weil
    diese Funktion bestehende Aufrufer/Tests mit synthetischen, nicht aus
    einem echten Dataset stammenden `team_strengths` bedient (siehe
    tests/test_matchup.py) -- eine Walk-Forward-Rekonstruktion braeuchte
    dagegen Zugriff auf dataset.players/fixtures.

    - "ausgeglichen" (Nutzer-Vorgabe 3, ueberarbeitet): NICHT mehr der
      Median-|diff| ALLER Unentschieden (bei wenigen/verrauschten
      Unentschieden kann der zufaellig weit draussen liegen und dann viele
      tatsaechlich knappe Sieg/Niederlage-Faelle faelschlich als
      "ausgeglichen" einziehen) und AUCH NICHT mehr "Unentschieden-Quote
      ueber dem Saisondurchschnitt" (das kippte in einem ersten Anlauf
      dieser Korrektur, siehe Commit-Historie, in die andere Richtung: eine
      schon winzige, statistisch kaum belastbare Elevation -- hier: 23%
      statt 20% Saisonschnitt -- reichte, um fast die Haelfte aller Spiele
      als "ausgeglichen" einzustufen, obwohl in JEDEM |diff|-Bereich
      Unentschieden nur eine MINDERHEIT der Ergebnisse waren). Jetzt gilt
      ein strengeres, direkt interpretierbares Kriterium: |diff| wird in
      CALIBRATION_BUCKETS Gruppen eingeteilt; getrennt je-Bucket per
      Pool-Adjacent-Violators (siehe _isotonic_non_increasing()/
      _isotonic_non_decreasing()) zu zwei GLAETTEN Kurven zusammengefasst --
      der Unentschieden-Quote (nicht-steigend erwartet: je aehnlicher die
      Teams, desto eher ein Remis) und der "Favorit liegt richtig"-Quote
      (nicht-fallend erwartet: je groesser der Abstand, desto sicherer der
      Favoritensieg, siehe auch "klar" unten). "Ausgeglichen" ist die obere
      |diff|-Grenze des letzten (groessten) zusammenhaengenden Blocks vom
      Anfang an, in dem die geglaettete Unentschieden-Quote STRIKT hoeher
      ist als die geglaettete Favorit-Trefferquote (eine blosse Gleichheit
      reicht nicht -- sonst koennte ein Bucket, der zufaellig sowohl kleine
      als auch sehr grosse |diff|-Werte mischt, seine Ober-grenze an
      "ausgeglichen" weiterreichen, siehe Regressionstest dazu) -- also
      dort, wo ein
      Unentschieden tatsaechlich die EINZELN wahrscheinlichste der drei
      Optionen ist (statt nur "etwas haeufiger als im Saisonschnitt"), nicht
      bloss eine Minderheits-Moeglichkeit neben zwei noch wahrscheinlicheren
      Sieg-Varianten. "Aehnliche Teamstaerke" wird so nur dort mit
      Unentschieden gleichgesetzt, wo ein Unentschieden wirklich die beste
      Einzelwette ist; findet sich (noch) kein solcher Block -- bei wenigen
      Saisonspieltagen durchaus der Normalfall, siehe Validierungslauf --
      bleibt "ausgeglichen" bei 0.0 (nur ein exaktes Patt zaehlt dann noch
      dazu) und ein kleiner, aber von Null verschiedener diff fuehrt zu
      einer knappen Sieg-/Niederlage-Einstufung statt "Ausgeglichen".
    - "klar": nutzt dieselbe geglaettete Favorit-Trefferquote wie oben (statt
      einer eigenen, ungeglaetteten Bucket-Schleife -- ein Kriterium, robust
      berechnet, fuer beide Schwellen); "klar" ist die untere |diff|-Grenze
      des ERSTEN Blocks (von unten/klein nach oben/gross), in dem diese
      geglaettete Quote KLAR_WIN_RATE_THRESHOLD erreicht -- findet sich
      keiner, faellt "klar" auf das 80. Perzentil aller |diff|-Werte zurueck.
    - "leicht": Mittelwert aus "ausgeglichen" und "klar" (liegt dank der
      Sicherung unten immer dazwischen -- lueckenlos geordnete Stufen,
      Nutzer-Vorgabe 3).

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
    by_abs = sorted(pairs, key=lambda p: abs(p[0]))
    bucket_size = max(1, len(by_abs) // CALIBRATION_BUCKETS)

    buckets = [by_abs[i:i + bucket_size] for i in range(0, len(by_abs), bucket_size) if by_abs[i:i + bucket_size]]
    bucket_weights = [len(b) for b in buckets]
    bucket_upper = [max(abs(d) for d, _ in b) for b in buckets]
    bucket_lower = [min(abs(d) for d, _ in b) for b in buckets]
    bucket_draw_rates = [sum(1 for _, o in b if o == "draw") / len(b) for b in buckets]
    bucket_hit_rates = [
        sum(1 for d, o in b if (o == "home" and d > 0) or (o == "away" and d < 0)) / len(b)
        for b in buckets
    ]

    smoothed_draw = _isotonic_non_increasing(bucket_draw_rates, bucket_weights)
    smoothed_hit = _isotonic_non_decreasing(bucket_hit_rates, bucket_weights)
    # Flacht beide geglaetteten Kurven (Bloecke aus ggf. mehreren Original-
    # Buckets) wieder auf Ursprungs-Bucket-Ebene aus, damit sich "ausgeglichen"
    # und "klar" beide praezise auf eine einzelne |diff|-Bucket-Grenze
    # beziehen koennen.
    draw_rate_by_bucket = [0.0] * len(buckets)
    start = 0
    for value, _weight, end_index in smoothed_draw:
        for idx in range(start, end_index + 1):
            draw_rate_by_bucket[idx] = value
        start = end_index + 1
    hit_rate_by_bucket = [0.0] * len(buckets)
    start = 0
    for value, _weight, end_index in smoothed_hit:
        for idx in range(start, end_index + 1):
            hit_rate_by_bucket[idx] = value
        start = end_index + 1

    ausgeglichen = 0.0
    for idx in range(len(buckets)):
        if draw_rate_by_bucket[idx] > hit_rate_by_bucket[idx]:
            ausgeglichen = bucket_upper[idx]
        else:
            break

    klar = None
    for idx in range(len(buckets)):
        if hit_rate_by_bucket[idx] >= KLAR_WIN_RATE_THRESHOLD:
            klar = bucket_lower[idx]
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


def _isotonic_non_increasing(values: List[float], weights: List[float]) -> List[Tuple[float, float, int]]:
    """Pool-Adjacent-Violators-Algorithmus (Isotonic Regression): glaettet
    `values` (z.B. je-Bucket-Unentschieden-Quoten in aufsteigender |diff|-
    Reihenfolge) zur groesstmoeglichen NICHT-STEIGENDEN Kurve, gewichtet nach
    `weights` (Bucket-Groesse). Verhindert, dass calibrate_thresholds() eine
    einzelne verrauschte Bucket-Quote (z.B. 2/10 statt im Schnitt erwarteter
    ~2.04/10 -- blosses Zufallsrauschen bei dieser noch kleinen Datenbasis)
    als "Unentschieden werden hier NICHT mehr ueberdurchschnittlich haeufig"
    fehlinterpretiert; benachbarte Buckets, die dieser (fussballerisch
    plausiblen: je aehnlicher die Teams, desto eher ein Unentschieden)
    Monotonie-Annahme widersprechen, werden gewichtet gemittelt statt die
    Kalibrierung an einem einzelnen Ausreisser abbrechen zu lassen.

    Gibt eine Liste von (gegl. Wert, Gesamtgewicht, End-Index) zurueck, in
    urspruenglicher Reihenfolge -- End-Index ist der hoechste urspruengliche
    Bucket-Index, der in diesen (ggf. gemittelten) Block zusammengefasst
    wurde, zum Zurueckfinden der zugehoerigen |diff|-Obergrenze."""
    blocks: List[List[float]] = [[v, w, i] for i, (v, w) in enumerate(zip(values, weights))]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0]:
            v0, w0, _ = blocks[i]
            v1, w1, end1 = blocks[i + 1]
            merged_weight = w0 + w1
            merged_value = (v0 * w0 + v1 * w1) / merged_weight
            blocks[i] = [merged_value, merged_weight, end1]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    return [(v, w, e) for v, w, e in blocks]


def _isotonic_non_decreasing(values: List[float], weights: List[float]) -> List[Tuple[float, float, int]]:
    """Spiegelbild von _isotonic_non_increasing() fuer Kurven, die mit
    steigendem |diff| eher STEIGEN sollen (z.B. "Favorit liegt richtig"-
    Quote -- je groesser der Staerke-Abstand, desto sicherer der
    Favoritensieg). Negiert die Werte, glaettet nicht-steigend, negiert
    zurueck -- spart eine zweite, separat zu pflegende PAVA-Implementierung."""
    negated = [-v for v in values]
    smoothed = _isotonic_non_increasing(negated, weights)
    return [(-v, w, e) for v, w, e in smoothed]


def classify_diff(diff: float, thresholds: MatchupThresholds) -> dict:
    """Ordnet eine Staerke-Differenz (eigenes Team minus Gegner, am
    jeweiligen Spielort) einer der 5 Prognose-Stufen zu -- UNVERAENDERT
    durch die Nutzer-Korrektur (Vorgabe: "Prognosestufen beibehalten").
    Unentschieden wird ausdruecklich ueber die "ausgeglichen"-Stufe
    abgebildet; wie breit/eng dieser Bereich ist, entscheidet jetzt die
    ueberarbeitete calibrate_thresholds() (siehe dort, Nutzer-Vorgabe 3)."""
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
    trotzdem geklemmt. UNVERAENDERT durch die Nutzer-Korrektur."""
    return max(0.0, min(1.0, (diff + 1.0) / 2.0))


def points_multiplier(diff: float) -> float:
    """Milder Multiplikator fuer die Punktprognose (siehe POINTS_MULTIPLIER_SPAN
    oben) -- bewusst klein, damit ein starker Spieler trotz schwerem Gegner
    weiterhin eine hohe Punktprognose behalten kann. UNVERAENDERT durch die
    Nutzer-Korrektur."""
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
    Artifact-Frontend. UNVERAENDERT durch die Nutzer-Korrektur (Signatur und
    Rueckgabeform identisch) -- wird 1:1 in jeden Spieler-Export uebernommen.

    Spiegelsymmetrie (Nutzer-Vorgabe 6): fuer ein und dasselbe Spiel liefert
    _strength_diff() fuer das Heimteam IMMER exakt den negierten Wert
    dessen, was fuer das Auswaertsteam herauskommt (siehe dortiger
    Docstring) -- Favorit/Aussenseiter-Einstufung und deren Grad (leicht/
    klar) sind damit zwischen beiden Seiten einer Begegnung automatisch
    spiegelbildlich, unabhaengig davon, welche Faktoren/Gewichte diff
    speisen. Siehe
    test_compute_team_matchday_forecasts_is_mirror_symmetric_for_both_sides
    fuer die explizite Regressionsabsicherung."""
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
