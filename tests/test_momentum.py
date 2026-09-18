from kickbase_tool.metrics.calculations import team_form, team_momentum

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


def build_flat_points(team_id, num_matchdays, points_per_match=10.0):
    return {(team_id, md): points_per_match for md in range(1, num_matchdays + 1)}


def test_team_form_uses_simple_average_before_first_full_window():
    # Only 4 completed matchdays exist -- transitional fallback (Schritt "vor
    # dem ersten vollstaendigen 5-Spiele-Fenster"): simple average of all
    # games played so far.
    points = {("T1", 1): 10, ("T1", 2): 20, ("T1", 3): 0, ("T1", 4): 6}
    assert team_form(points, "T1") == (10 + 20 + 0 + 6) / 4


def test_team_form_matches_spec_examples_across_matchdays():
    # A team with points [1..12] on matchdays 1..12 (points == matchday
    # number keeps every F_d value distinct and easy to check by hand).
    points = {("T1", md): float(md) for md in range(1, 13)}

    def form_through(latest_matchday):
        trimmed = {k: v for k, v in points.items() if k[1] <= latest_matchday}
        return team_form(trimmed, "T1")

    # F5 = mean(1..5) = 3
    assert form_through(5) == 3.0
    # nach ST6 -> mean(F5, F6); F6 = mean(2..6) = 4
    assert form_through(6) == (3.0 + 4.0) / 2
    # nach ST7 -> mean(F5, F6, F7); F7 = mean(3..7) = 5
    assert form_through(7) == (3.0 + 4.0 + 5.0) / 3
    # nach ST8 -> mean(F5, F6, F7, F8); F8 = mean(4..8) = 6
    assert form_through(8) == (3.0 + 4.0 + 5.0 + 6.0) / 4
    # ab ST9 -> immer die letzten 5 Formfenster; bei ST12:
    # F8=6, F9=mean(5..9)=7, F10=mean(6..10)=8, F11=mean(7..11)=9, F12=mean(8..12)=10
    assert form_through(12) == (6.0 + 7.0 + 8.0 + 9.0 + 10.0) / 5


def test_team_momentum_rewards_a_team_trending_up_and_penalizes_one_collapsing():
    points = build_points()
    # T1: F5=10 (mean 20,20,5,3,2), F7=2 (mean 5,3,2,0,0) -> collapsing -> negative momentum
    assert team_momentum(points, "T1") == 2.0 - 10.0
    # T3: F5=2 (mean 1,1,1,1,6), F7=10 (mean 1,1,6,21,21) -> surging -> positive momentum
    assert team_momentum(points, "T3") == 10.0 - 2.0
    # T2: perfectly steady -> zero momentum
    assert team_momentum(points, "T2") == 0.0

    # Higher momentum value = better now (raw points trend, not rank-based):
    # the surging team should beat the steady team, which should beat the
    # collapsing team.
    assert team_momentum(points, "T3") > team_momentum(points, "T2") > team_momentum(points, "T1")


def test_team_momentum_matches_first_possible_spec_example():
    # "Nach ST7 waere die erste moegliche Formsteigerung: F7 - F5"
    points = {("T1", md): float(md) for md in range(1, 8)}
    # F5 = mean(1..5) = 3, F7 = mean(3..7) = 5
    assert team_momentum(points, "T1") == 5.0 - 3.0


def test_team_momentum_is_none_without_enough_matchday_history():
    # Fewer than 3 rolling formwerte -> None (needs matchday >= window + trend_gap = 7)
    shallow_points = build_flat_points("T1", 6)
    assert team_momentum(shallow_points, "T1") is None
    assert team_momentum({}, "unknown-team") is None
