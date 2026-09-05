from kickbase_tool.metrics.calculations import build_team_rolling_form_ranks, team_momentum

ALL_TEAMS = ["T1", "T2", "T3"]


def build_points():
    points = {}
    # T1: strong early (md1-5 sum=50), collapses later (md3-7 sum=10)
    for md, pts in {1: 20, 2: 20, 3: 5, 4: 3, 5: 2, 6: 0, 7: 0}.items():
        points[("T1", md)] = pts
    # T2: perfectly steady throughout
    for md in range(1, 8):
        points[("T2", md)] = 6
    # T3: weak early (md1-5 sum=10), surges late (md3-7 sum=50)
    for md, pts in {1: 1, 2: 1, 3: 1, 4: 1, 5: 6, 6: 21, 7: 21}.items():
        points[("T3", md)] = pts
    return points


def test_rolling_form_ranks_reflect_the_trailing_five_game_window():
    ranks = build_team_rolling_form_ranks(build_points(), ALL_TEAMS, window=5)
    # matchday 5 window = md1-5: T1=50 (best), T2=30, T3=10 (worst)
    assert ranks["T1"][5] == 1
    assert ranks["T2"][5] == 2
    assert ranks["T3"][5] == 3
    # matchday 7 window = md3-7: T3=50 (best), T2=30, T1=10 (worst)
    assert ranks["T3"][7] == 1
    assert ranks["T2"][7] == 2
    assert ranks["T1"][7] == 3


def test_momentum_rewards_a_team_trending_up_and_penalizes_one_collapsing():
    ranks = build_team_rolling_form_ranks(build_points(), ALL_TEAMS, window=5)
    # T1: was rank 1 two matchdays ago, now rank 3 -> collapsing -> high (bad) momentum value
    assert team_momentum(ranks, "T1") == 3 + (3 - 1)
    # T3: was rank 3, now rank 1 -> surging -> low (good) momentum value
    assert team_momentum(ranks, "T3") == 1 + (1 - 3)
    # T2: unchanged rank -> momentum equals its current rank
    assert team_momentum(ranks, "T2") == 2

    # Lower momentum value = better: the surging team should beat the steady
    # team, which should beat the collapsing team.
    assert team_momentum(ranks, "T3") < team_momentum(ranks, "T2") < team_momentum(ranks, "T1")


def test_momentum_is_none_without_enough_matchday_history():
    shallow_points = {("T1", 1): 10, ("T1", 2): 10}
    ranks = build_team_rolling_form_ranks(shallow_points, ["T1"], window=5)
    assert team_momentum(ranks, "T1") is None
    assert team_momentum({}, "unknown-team") is None
