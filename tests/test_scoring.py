from kickbase_tool.data.models import Player
from kickbase_tool.metrics.calculations import PlayerMetrics
from kickbase_tool.metrics.fallback import RecentForm
from kickbase_tool.ranking.scoring import KAUF_CATEGORIES, compute_ranking
from kickbase_tool.util import rank_with_ties


def make_player_metrics(pid, season_avg, market_value, goals=0, assists=0, clean_sheets=0):
    player = Player(
        id=pid, first_name="P", last_name=pid, team_id="T1", position=4,
        status=0, market_value=market_value, season_average_points=season_avg,
    )
    recent = RecentForm(games_used=5, average=season_avg, minimum=season_avg - 2, maximum=season_avg + 2,
                         min_max_average=season_avg, start_rate=1.0)
    return PlayerMetrics(
        player=player, season_average=season_avg, recent_form=recent, market_value=market_value,
        points_per_market_value=(season_avg / market_value) if market_value else None,
        team_form=5.0, opponent_form=5.0, table_position_diff=0.0,
        own_venue_form=5.0, opponent_venue_form=5.0, venue_form_diff=0.0,
        goals=goals, assists=assists, clean_sheets=clean_sheets,
        remaining_schedule_difficulty=10.0, next_opponent_team_id="T2", next_match_is_home=True,
    )


def test_rank_with_ties_higher_is_better():
    ranks = rank_with_ties({"a": 10, "b": 20, "c": 20}, higher_is_better=True)
    assert ranks["b"] == ranks["c"] == 1.5
    assert ranks["a"] == 3


def test_rank_with_ties_missing_value_gets_worst_rank():
    ranks = rank_with_ties({"a": 10, "b": None}, higher_is_better=True)
    assert ranks["a"] == 1
    assert ranks["b"] == 2


def test_best_season_average_gets_rank_one_in_that_category():
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000),
        "b": make_player_metrics("b", season_avg=5, market_value=1_000_000),
    }
    result = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES})
    assert result.category_ranks["season_avg"]["a"] == 1
    assert result.category_ranks["season_avg"]["b"] == 2
    assert result.order[0] == "a"


def test_cheaper_market_value_ranks_better_for_kauf():
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=5_000_000),
        "b": make_player_metrics("b", season_avg=10, market_value=1_000_000),
    }
    result = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES})
    assert result.category_ranks["market_value"]["b"] == 1
    assert result.category_ranks["market_value"]["a"] == 2


def test_verkauf_reverses_category_ranks():
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000),
        "b": make_player_metrics("b", season_avg=5, market_value=1_000_000),
    }
    kauf = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES}, reverse=False)
    verkauf = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES}, reverse=True)
    # the season-average winner for Kauf should be the loser for Verkauf, and vice versa
    assert kauf.order[0] == "a"
    assert verkauf.order[0] == "b"
    assert kauf.category_ranks["season_avg"]["a"] + verkauf.category_ranks["season_avg"]["a"] == len(metrics) + 1


def test_weights_change_final_order():
    metrics = {
        # a: great season average but very expensive; b: mediocre average but cheap
        "a": make_player_metrics("a", season_avg=15, market_value=10_000_000),
        "b": make_player_metrics("b", season_avg=8, market_value=500_000),
    }
    equal_weights = {c: 1.0 for c in KAUF_CATEGORIES}
    result_equal = compute_ranking(metrics, KAUF_CATEGORIES, equal_weights)

    value_focused_weights = dict(equal_weights)
    value_focused_weights["market_value"] = 20.0
    result_value_focused = compute_ranking(metrics, KAUF_CATEGORIES, value_focused_weights)

    assert result_value_focused.order[0] == "b"
    # sanity: at least one of the two weightings actually differs in outcome
    assert result_equal.order != result_value_focused.order or result_equal.scores != result_value_focused.scores


def test_goals_assists_cleansheets_combined_category_rewards_all_three_stats():
    metrics = {
        "a": make_player_metrics("a", season_avg=10, market_value=1_000_000, goals=10, assists=5, clean_sheets=3),
        "b": make_player_metrics("b", season_avg=10, market_value=1_000_000, goals=0, assists=0, clean_sheets=0),
    }
    result = compute_ranking(metrics, KAUF_CATEGORIES, weights={c: 1.0 for c in KAUF_CATEGORIES})
    assert result.category_ranks["goals_assists_cleansheets"]["a"] == 1
    assert result.category_ranks["goals_assists_cleansheets"]["b"] == 2
