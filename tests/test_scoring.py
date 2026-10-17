from kickbase_tool.data.models import Player
from kickbase_tool.metrics.calculations import PlayerMetrics
from kickbase_tool.metrics.fallback import RecentForm
from kickbase_tool.ranking.scoring import (
    AUFSTELLUNG_CATEGORIES,
    KAUF_CATEGORIES,
    VERKAUF_CATEGORIES,
    compute_kauf_verkauf_ranking,
    compute_ranking,
)
from kickbase_tool.util import rank_with_ties


def make_player_metrics(pid, season_avg, market_value, goals=0, assists=0, clean_sheets=0,
                         team_form=5.0, opponent_form=5.0, team_momentum=None):
    player = Player(
        id=pid, first_name="P", last_name=pid, team_id="T1", position=4,
        status=0, market_value=market_value, season_average_points=season_avg,
    )
    recent = RecentForm(games_used=5, average=season_avg, minimum=season_avg - 2, maximum=season_avg + 2,
                         min_max_average=season_avg)
    return PlayerMetrics(
        player=player, season_average=season_avg, recent_form=recent, market_value=market_value,
        points_per_market_value=(season_avg / market_value) if market_value else None,
        team_form=team_form, opponent_form=opponent_form, table_position_diff=0.0,
        own_venue_rank=5.0, opponent_venue_rank=5.0, venue_rank_diff=0.0,
        goals=goals, assists=assists, clean_sheets=clean_sheets,
        next_opponent_team_id="T2", next_opponent_name="Team2", next_match_is_home=True,
        upcoming_opponents=[], remaining_schedule_difficulty=None,
        opponent_remaining_schedule_difficulty=None,
        team_momentum=team_momentum, opponent_momentum=None,
    )


def test_rank_with_ties_higher_is_better():
    ranks = rank_with_ties({"a": 10, "b": 20, "c": 20}, higher_is_better=True)
    assert ranks["b"] == ranks["c"] == 1.5
    assert ranks["a"] == 3


def test_rank_with_ties_missing_value_gets_worst_rank():
    ranks = rank_with_ties({"a": 10, "b": None}, higher_is_better=True)
    assert ranks["a"] == 1
    assert ranks["b"] == 2


def test_rank_with_ties_missing_value_gets_neutral_rank_when_requested():
    # Nutzer-Vorgabe: fehlende Werte neutral behandeln statt kuenstlich
    # schlechtester Rang -- bei 3 Spielern ist der neutrale Rang (3+1)/2=2,
    # also die Mitte, nicht der schlechteste Platz (3).
    ranks = rank_with_ties({"a": 10, "b": 20, "c": None}, higher_is_better=True, missing_rank="neutral")
    assert ranks["a"] == 2
    assert ranks["b"] == 1
    assert ranks["c"] == 2.0


def test_best_season_average_gets_rank_one_in_that_category():
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000),
        "b": make_player_metrics("b", season_avg=5, market_value=1_000_000),
    }
    result = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES})
    assert result.category_ranks["season_avg"]["a"] == 1
    assert result.category_ranks["season_avg"]["b"] == 2
    assert result.order[0] == "a"


def test_aufstellung_includes_points_per_value():
    # Nutzer-Vorgabe 2026-10-17: Aufstellung ist nicht mehr "rein sportlich
    # ohne Marktwertbezug" -- Punkte pro Marktwert ist jetzt explizit mit
    # 4.5% Teil der Aufstellungsbewertung.
    assert "points_per_value" in AUFSTELLUNG_CATEGORIES
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=5_000_000),
        "b": make_player_metrics("b", season_avg=10, market_value=1_000_000),
    }
    result = compute_ranking(metrics, AUFSTELLUNG_CATEGORIES, weights={c: 1.0 for c in AUFSTELLUNG_CATEGORIES})
    # gleicher Saison-Schnitt, aber b hat den besseren Pkt/Mio-Wert (billiger)
    # -> b darf nicht mehr automatisch denselben Score wie a haben.
    assert result.scores["a"] != result.scores["b"]
    assert result.order[0] == "b"


def test_market_value_is_not_a_ranking_category_anywhere():
    assert "market_value" not in KAUF_CATEGORIES
    assert "market_value" not in AUFSTELLUNG_CATEGORIES
    assert "market_value" not in VERKAUF_CATEGORIES
    assert "points_per_value" in KAUF_CATEGORIES
    assert "points_per_value" in VERKAUF_CATEGORIES
    assert "points_per_value" in AUFSTELLUNG_CATEGORIES


def test_weights_change_final_order():
    metrics = {
        # a: great season average but very expensive (so poor points-per-value);
        # b: mediocre average but cheap (so much better points-per-value)
        "a": make_player_metrics("a", season_avg=15, market_value=10_000_000),
        "b": make_player_metrics("b", season_avg=8, market_value=500_000),
    }
    equal_weights = {c: 1.0 for c in KAUF_CATEGORIES}
    result_equal = compute_ranking(metrics, KAUF_CATEGORIES, equal_weights)

    value_focused_weights = dict(equal_weights)
    value_focused_weights["points_per_value"] = 20.0
    result_value_focused = compute_ranking(metrics, KAUF_CATEGORIES, value_focused_weights)

    assert result_value_focused.order[0] == "b"
    # sanity: at least one of the two weightings actually differs in outcome
    assert result_equal.order != result_value_focused.order or result_equal.scores != result_value_focused.scores


def test_goals_assists_clean_sheets_are_independent_categories():
    # Nutzer-Vorgabe 2026-10-17: Tore/Vorlagen/Zu-null sind keine gebuendelte
    # "goals_assists_cleansheets"-Kennzahl mehr, sondern drei eigenstaendige
    # Kategorien, jede mit eigenem Prozentgewicht.
    for cats in (AUFSTELLUNG_CATEGORIES, KAUF_CATEGORIES, VERKAUF_CATEGORIES):
        assert "goals" in cats
        assert "assists" in cats
        assert "clean_sheets" in cats
        assert "goals_assists_cleansheets" not in cats

    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000, goals=10, assists=5, clean_sheets=3),
        "b": make_player_metrics("b", season_avg=10, market_value=1_000_000, goals=0, assists=0, clean_sheets=0),
    }
    result = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES})
    assert result.category_ranks["goals"]["a"] == 1
    assert result.category_ranks["assists"]["a"] == 1
    assert result.category_ranks["clean_sheets"]["a"] == 1
    assert result.order[0] == "a"


def test_aufstellung_has_team_opponent_form_diff_and_team_momentum():
    # Neue Kategorien aus der Nutzer-Vorgabe: "Differenz zwischen eigener
    # Teamform und Gegnerform" und "Formanstieg" (eigene Formsteigerung,
    # team_momentum -- nicht mehr opponent_momentum).
    assert "team_opponent_form_diff" in AUFSTELLUNG_CATEGORIES
    assert "team_momentum" in AUFSTELLUNG_CATEGORIES
    assert "opponent_momentum" not in AUFSTELLUNG_CATEGORIES

    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000, team_form=8.0, opponent_form=3.0, team_momentum=2.0),
        "b": make_player_metrics("b", season_avg=10, market_value=1_000_000, team_form=3.0, opponent_form=8.0, team_momentum=-2.0),
    }
    result = compute_ranking(metrics, AUFSTELLUNG_CATEGORIES, weights={c: 1.0 for c in AUFSTELLUNG_CATEGORIES})
    assert result.category_ranks["team_opponent_form_diff"]["a"] == 1
    assert result.category_ranks["team_momentum"]["a"] == 1
    assert result.order[0] == "a"


def test_compute_kauf_verkauf_ranking_combines_both_with_higher_is_better_scores():
    metrics = {
        "a": make_player_metrics("a", season_avg=15, market_value=1_000_000, team_momentum=1.0),
        "b": make_player_metrics("b", season_avg=5, market_value=1_000_000, team_momentum=-1.0),
    }
    kauf_weights = {c: 1.0 for c in KAUF_CATEGORIES}
    verkauf_weights = {c: 1.0 for c in VERKAUF_CATEGORIES}
    result = compute_kauf_verkauf_ranking(metrics, kauf_weights, verkauf_weights)

    # Nutzer-Vorgabe: hoechster Score = Rang #1 (higher-is-better), nicht wie
    # bei compute_ranking() niedrigster Score.
    assert result.scores["a"] > result.scores["b"]
    assert result.order[0] == "a"
    assert result.order[1] == "b"


def test_compute_kauf_verkauf_ranking_replaces_separate_kauf_and_verkauf_ranks():
    # Nutzer-Vorgabe Abschnitt 4: EIN gemeinsamer Rang statt zwei getrennter.
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000),
        "b": make_player_metrics("b", season_avg=5, market_value=1_000_000),
        "c": make_player_metrics("c", season_avg=7, market_value=1_000_000),
    }
    kauf_weights = {c: 1.0 for c in KAUF_CATEGORIES}
    verkauf_weights = {c: 1.0 for c in VERKAUF_CATEGORIES}
    result = compute_kauf_verkauf_ranking(metrics, kauf_weights, verkauf_weights)
    assert set(result.scores.keys()) == {"a", "b", "c"}
    assert len(result.order) == 3
    # aufsteigend sortiert (umgedrehtes order) zeigt den schwaechsten/besten
    # Verkaufskandidaten zuerst -- dieselbe Spalte, nur andere Sortierrichtung.
    assert list(reversed(result.order))[0] == result.order[-1]
