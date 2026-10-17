from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from kickbase_tool.metrics.calculations import PlayerMetrics
from kickbase_tool.util import rank_with_ties

DEFAULT_WEIGHTS_PATH = Path(__file__).with_name("weights.yaml")

# category_key -> (extractor, higher_is_better)
# higher_is_better always describes what is good for the player
# ("Aufstellung"/"Kauf"/"Verkauf" all score "higher performance = better" on
# every category now -- see compute_kauf_verkauf_ranking for how Kauf and
# Verkauf are blended into one Gesamtscore, Nutzer-Vorgabe Abschnitt 4).
CATEGORY_DEFINITIONS = {
    "season_avg": (lambda pm: pm.season_average, True),
    "recent_avg": (lambda pm: pm.recent_form.average, True),
    "recent_min": (lambda pm: pm.recent_form.minimum, True),
    "recent_max": (lambda pm: pm.recent_form.maximum, True),
    "recent_min_max_avg": (lambda pm: pm.recent_form.min_max_average, True),
    "market_value": (lambda pm: pm.market_value, True),
    "points_per_value": (lambda pm: pm.points_per_market_value, True),
    "team_form": (lambda pm: pm.team_form, True),
    "opponent_form": (lambda pm: pm.opponent_form, False),  # weaker opponent = better for the player
    "table_position_diff": (lambda pm: pm.table_position_diff, True),
    # Heim/Auswaerts (Kennzahl 11), split into 3 independent categories --
    # see PlayerMetrics.own_venue_rank for the data-source caveat
    # (Kickbase-internal fantasy points, not an official real-world
    # home/away table).
    "own_venue_rank": (lambda pm: pm.own_venue_rank, False),  # own team's rank at that venue: 1 = best
    "opponent_venue_rank": (lambda pm: pm.opponent_venue_rank, True),  # opponent's rank: weak (high number) = better for us
    "venue_rank_diff": (lambda pm: pm.venue_rank_diff, True),
    # Nutzer-Vorgabe 2026-10-17: Tore/Vorlagen/Zu-null sind keine gebuendelte
    # Kennzahl mehr, sondern drei eigenstaendige, einzeln gewichtete
    # Kategorien (siehe AUFSTELLUNG/KAUF/VERKAUF_WEIGHTS) -- ihr Verhaeltnis
    # zueinander (ca. 4.5 : 1.75 : 1) bleibt dasselbe wie zuvor.
    "goals": (lambda pm: pm.goals, True),
    "assists": (lambda pm: pm.assists, True),
    "clean_sheets": (lambda pm: pm.clean_sheets, True),
    "opponent_remaining_schedule_difficulty": (lambda pm: pm.opponent_remaining_schedule_difficulty, False),
    # "Formanstieg" (Nutzer-Vorgabe 2026-10-17): die EIGENE Formsteigerung
    # (team_momentum, rohe Punktedifferenz des rollierenden Formwerts,
    # siehe metrics/calculations.py::team_momentum) -- nicht mehr die des
    # Gegners. Positiv = eigenes Team gewinnt an Form.
    "team_momentum": (lambda pm: pm.team_momentum, True),
    "opponent_momentum": (lambda pm: pm.opponent_momentum, False),
    # "Differenz zwischen eigener Teamform und Gegnerform" (Nutzer-Vorgabe
    # 2026-10-17, neu in Aufstellung): rohe Punktedifferenz der beiden
    # team_form-Werte -- NICHT zu verwechseln mit table_position_diff (das
    # ist eine Rang-, nicht eine Punktedifferenz). Positiv = eigenes Team in
    # besserer Form als der naechste Gegner.
    "team_opponent_form_diff": (
        lambda pm: (pm.team_form - pm.opponent_form) if pm.team_form is not None and pm.opponent_form is not None else None,
        True,
    ),
}

# Aufstellungsrang: rein sportlich, inkl. Punkte pro Marktwert (Nutzer-Vorgabe
# 2026-10-17 -- vorher war market_value/points_per_value komplett aussen vor;
# jetzt explizit mit 4.5% Gewicht Teil der Aufstellungsbewertung).
AUFSTELLUNG_CATEGORIES = [
    "season_avg", "goals", "assists", "clean_sheets", "recent_avg", "team_form",
    "table_position_diff", "recent_min_max_avg", "points_per_value", "opponent_form",
    "team_opponent_form_diff", "team_momentum", "own_venue_rank", "opponent_venue_rank",
]

KAUF_CATEGORIES = [
    "season_avg", "recent_avg", "points_per_value", "goals", "assists", "clean_sheets",
    "team_form", "team_momentum", "opponent_form", "own_venue_rank",
]

VERKAUF_CATEGORIES = [
    "season_avg", "recent_avg", "points_per_value", "team_form", "team_momentum",
    "goals", "assists", "clean_sheets",
]


@dataclass
class RankingResult:
    scores: Dict[str, float]  # player_id -> final score; see docstring of the producing function for direction
    category_ranks: Dict[str, Dict[str, float]]  # category -> player_id -> rank (1 = best in that category)
    order: List[str]  # player ids sorted best-first


def load_weights(path: Path = DEFAULT_WEIGHTS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_ranking(
    metrics_by_id: Dict[str, PlayerMetrics],
    categories: List[str],
    weights: Dict[str, float],
    reverse: bool = False,
) -> RankingResult:
    """scores: weighted average of per-category ranks, LOWER = better (rank
    1 = best player), consistent across every category since every category
    in CATEGORY_DEFINITIONS already encodes "higher_is_better" from the
    player's own perspective. `reverse` flips every per-category rank
    (n + 1 - r) before weighting, kept for backward compatibility/tests; the
    live Kauf/Verkauf blend (see compute_kauf_verkauf_ranking) no longer
    needs it since Verkauf uses its own category/weight set instead of
    reversing Kauf's.

    Missing values are treated NEUTRALLY (average rank, see
    util.rank_with_ties missing_rank="neutral") -- a player missing one
    metric (e.g. "Formanstieg" before enough matchdays exist) is neither
    rewarded nor punished for that one category, per explicit user request.
    """
    n = len(metrics_by_id)

    category_ranks: Dict[str, Dict[str, float]] = {}
    for category in categories:
        extractor, higher_is_better = CATEGORY_DEFINITIONS[category]
        values = {pid: extractor(pm) for pid, pm in metrics_by_id.items()}
        ranks = rank_with_ties(values, higher_is_better=higher_is_better, missing_rank="neutral")
        if reverse:
            ranks = {pid: (n + 1 - r) for pid, r in ranks.items()}
        category_ranks[category] = ranks

    total_weight = sum(weights.get(c, 1.0) for c in categories) or 1.0
    scores: Dict[str, float] = {}
    for pid in metrics_by_id:
        scores[pid] = sum(weights.get(c, 1.0) * category_ranks[c][pid] for c in categories) / total_weight

    order = sorted(scores, key=lambda pid: scores[pid])
    return RankingResult(scores=scores, category_ranks=category_ranks, order=order)


def compute_kauf_verkauf_ranking(
    metrics_by_id: Dict[str, PlayerMetrics],
    kauf_weights: Dict[str, float],
    verkauf_weights: Dict[str, float],
) -> RankingResult:
    """Gemeinsamer Kauf-/Verkaufsrang (Nutzer-Vorgabe Abschnitt 4): ersetzt
    die frueher getrennten Kauf- und Verkaufsraenge durch EINEN Rang.

    Gesamtscore = 50% Kaufwertung + 50% Verkaufswertung, wobei beide
    Teilwertungen (wie jede Kategorie) "hoehere Leistung = besser" sind --
    Verkauf ist KEINE umgekehrte Kauf-Bewertung mehr, sondern eine eigene
    Gewichtung derselben Idee ("wie stark ist dieser Spieler"), nur mit
    anderem Fokus (z.B. staerker auf Saison-Ø/Konstanz als auf Momentum).

    `scores` hier ist bewusst higher = better (Nutzer-Vorgabe: "Alle Faktoren
    positiv bewerten: hoehere Leistung = hoeherer Score", "Hoechster Score
    erhaelt Rang #1") -- anders als compute_ranking()'s lower-is-better
    Konvention. `order` ist entsprechend absteigend nach Score sortiert
    (bester Kaufkandidat zuerst); fuer "schwaechste Spieler/Verkaufs-
    kandidaten zuerst" reicht es, dieselbe Rangspalte aufsteigend statt
    absteigend zu sortieren -- dafuer ist keine zweite Spalte/kein zweiter
    Rang mehr noetig.
    """
    kauf_result = compute_ranking(metrics_by_id, KAUF_CATEGORIES, kauf_weights)
    verkauf_result = compute_ranking(metrics_by_id, VERKAUF_CATEGORIES, verkauf_weights)

    n = len(metrics_by_id)
    scores: Dict[str, float] = {}
    for pid in metrics_by_id:
        # Flip each rank-like (lower=better) sub-score to a quality value
        # (higher=better) before blending 50/50, per the Nutzer-Vorgabe
        # convention for this one combined ranking.
        kauf_quality = (n + 1) - kauf_result.scores[pid]
        verkauf_quality = (n + 1) - verkauf_result.scores[pid]
        scores[pid] = 0.5 * kauf_quality + 0.5 * verkauf_quality

    order = sorted(scores, key=lambda pid: scores[pid], reverse=True)
    category_ranks = {**kauf_result.category_ranks, **verkauf_result.category_ranks}
    return RankingResult(scores=scores, category_ranks=category_ranks, order=order)


def compute_all_rankings(
    metrics_by_id: Dict[str, PlayerMetrics], weights_path: Path = DEFAULT_WEIGHTS_PATH
) -> Dict[str, RankingResult]:
    """Verletzte/gesperrte/angeschlagene Spieler werden NICHT aus den
    Rankings ausgeschlossen -- sie fliessen ganz normal mit ihren echten
    Werten ein, damit sie nicht aus Versehen uebersehen werden, falls sie am
    naechsten Spieltag doch spielen. Der Status bleibt nur eine
    Anzeige-Spalte; die Entscheidung, ob so ein Spieler trotzdem
    beruecksichtigt wird, trifft der Nutzer manuell.

    Gibt genau zwei Rankings zurueck (Nutzer-Vorgabe Abschnitt 4/6): den
    sportlichen Aufstellungsrang und den gemeinsamen Kauf-/Verkaufsrang --
    getrennte "kauf"/"verkauf"-Eintraege gibt es nicht mehr.
    """
    weights = load_weights(weights_path)
    return {
        "aufstellung": compute_ranking(metrics_by_id, AUFSTELLUNG_CATEGORIES, weights.get("aufstellung", {})),
        "kauf_verkauf": compute_kauf_verkauf_ranking(
            metrics_by_id, weights.get("kauf", {}), weights.get("verkauf", {})
        ),
    }
