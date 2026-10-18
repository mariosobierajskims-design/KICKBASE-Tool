from types import SimpleNamespace

from kickbase_tool.data.models import Fixture, MatchdayEntry, Player, TableEntry
from kickbase_tool.data.repository import Dataset
from kickbase_tool.metrics.matchup import (
    DEFAULT_THRESHOLDS,
    MatchupThresholds,
    build_team_strengths,
    calibrate_thresholds,
    classify_diff,
    compute_team_matchday_forecasts,
    normalize_min_max,
    points_multiplier,
)


def test_normalize_min_max_basic_range():
    values = {"a": 0.0, "b": 5.0, "c": 10.0}
    result = normalize_min_max(values)
    assert result["a"] == 0.0
    assert result["b"] == 0.5
    assert result["c"] == 1.0


def test_normalize_min_max_treats_missing_and_constant_as_neutral():
    assert normalize_min_max({"a": None, "b": None}) == {"a": 0.5, "b": 0.5}
    assert normalize_min_max({"a": 3.0, "b": 3.0}) == {"a": 0.5, "b": 0.5}
    # a missing value among present ones also lands neutral, not 0/1.
    result = normalize_min_max({"a": None, "b": 0.0, "c": 10.0})
    assert result["a"] == 0.5
    assert result["b"] == 0.0
    assert result["c"] == 1.0


def _player(team_id, points_by_matchday):
    matchdays = [
        MatchdayEntry(matchday=md, played=True, points=pts, minutes=90, home=None, team_id=team_id, opponent_team_id=None)
        for md, pts in points_by_matchday.items()
    ]
    return Player(
        id=f"p-{team_id}", first_name="X", last_name=team_id, team_id=team_id, position=3,
        status=0, market_value=1_000_000, season_average_points=None, matchdays=matchdays,
    )


def _build_dataset():
    # A: rising form, clearly strongest venue numbers.
    a_points = {md: float(md) for md in range(1, 10)}  # 1..9, season mean 5
    # B: flat/steady, mid venue numbers.
    b_points = {md: 5.0 for md in range(1, 10)}  # season mean 5
    # C: declining form, weakest venue numbers.
    c_points = {md: float(10 - md) for md in range(1, 10)}  # 9..1, season mean 5

    players = [_player("A", a_points), _player("B", b_points), _player("C", c_points)]
    table = [
        TableEntry(team_id="A", team_name="Team A", position=1),
        TableEntry(team_id="B", team_name="Team B", position=2),
        TableEntry(team_id="C", team_name="Team C", position=3),
    ]
    future_fixtures = [
        Fixture(matchday=10, home_team_id="A", away_team_id="B", finished=False),
        Fixture(matchday=11, home_team_id="C", away_team_id="A", finished=False),
        Fixture(matchday=12, home_team_id="B", away_team_id="C", finished=False),
        Fixture(matchday=13, home_team_id="A", away_team_id="C", finished=False),
        Fixture(matchday=14, home_team_id="B", away_team_id="A", finished=False),
    ]
    home_venue_points = {"A": 2.4, "B": 1.5, "C": 0.6}
    away_venue_points = {"A": 2.1, "B": 1.4, "C": 0.5}
    return Dataset(
        players=players, table=table, fixtures=future_fixtures,
        home_venue_points=home_venue_points, away_venue_points=away_venue_points,
        finished_results=[],
    )


def test_build_team_strengths_orders_teams_by_form_venue_and_momentum():
    dataset = _build_dataset()
    strengths = build_team_strengths(dataset)
    # Season average is identical for all three teams by construction, so
    # the ordering here is driven entirely by form/venue/momentum -- A should
    # clearly beat B, which should clearly beat C, at both venues.
    assert strengths["A"]["home"] > strengths["B"]["home"] > strengths["C"]["home"]
    assert strengths["A"]["away"] > strengths["B"]["away"] > strengths["C"]["away"]
    for tid in ("A", "B", "C"):
        assert 0.0 <= strengths[tid]["home"] <= 1.0
        assert 0.0 <= strengths[tid]["away"] <= 1.0


def test_compute_team_matchday_forecasts_shape_and_favourite_labelling():
    dataset = _build_dataset()
    strengths = build_team_strengths(dataset)
    forecasts = compute_team_matchday_forecasts(dataset, strengths, DEFAULT_THRESHOLDS, window=5)

    assert set(forecasts.keys()) == {"A", "B", "C"}
    # A has fixtures on matchdays 10, 11, 13, 14 (home or away) within the window.
    a_matchdays = [f["matchday"] for f in forecasts["A"]]
    assert a_matchdays == sorted(a_matchdays)
    for entry in forecasts["A"]:
        assert "label" in entry and "emoji" in entry
        assert 0.0 <= entry["quality"] <= 1.0
        assert 0.90 <= entry["points_multiplier"] <= 1.10  # within POINTS_MULTIPLIER span

    # A vs C on matchday 13 (A home): A is clearly the stronger team, so this
    # should never be classified as the underdog's favour.
    md13 = next(f for f in forecasts["A"] if f["matchday"] == 13)
    assert md13["opponent_team_id"] == "C"
    assert md13["diff"] > 0
    assert "Favorit" in md13["label"] or md13["label"] == "Ausgeglichen"


def test_classify_diff_respects_calibrated_boundaries():
    thresholds = MatchupThresholds(ausgeglichen=0.05, leicht=0.10, klar=0.20)
    assert classify_diff(0.0, thresholds)["key"] == "ausgeglichen"
    assert classify_diff(0.04, thresholds)["key"] == "ausgeglichen"
    assert classify_diff(-0.04, thresholds)["key"] == "ausgeglichen"
    assert classify_diff(0.12, thresholds)["key"] == "leichter_favorit"
    assert classify_diff(-0.12, thresholds)["key"] == "leichter_aussenseiter"
    assert classify_diff(0.25, thresholds)["key"] == "klarer_favorit"
    assert classify_diff(-0.25, thresholds)["key"] == "klarer_aussenseiter"


def test_points_multiplier_is_mild_and_monotonic():
    assert points_multiplier(0.0) == 1.0
    assert points_multiplier(1.0) == 1.15
    assert points_multiplier(-1.0) == 0.85
    # Clamped even for out-of-range diffs (defensive, shouldn't happen live).
    assert points_multiplier(5.0) == 1.15
    assert points_multiplier(-5.0) == 0.85


def test_calibrate_thresholds_falls_back_with_too_few_matches():
    dataset = SimpleNamespace(finished_results=[])
    assert calibrate_thresholds(dataset, {}) == DEFAULT_THRESHOLDS


def test_calibrate_thresholds_uses_real_results_when_enough_data():
    # Fake team strengths spread evenly so diffs are easy to reason about:
    # T0 is weakest, T19 is strongest (diff ~ (i - j) / 19 at most).
    strengths = {f"T{i}": {"home": i / 19.0, "away": i / 19.0} for i in range(20)}

    results = []
    # Close matchups (small |diff|) mostly end in draws.
    for i in range(10):
        results.append({"home_team_id": f"T{i}", "away_team_id": f"T{i+1}", "outcome": "draw"})
    # Lopsided matchups (large |diff|) are won by the favourite.
    for i in range(10):
        results.append({"home_team_id": "T19", "away_team_id": "T0", "outcome": "home"})
    dataset = SimpleNamespace(finished_results=results)

    thresholds = calibrate_thresholds(dataset, strengths)
    assert 0 <= thresholds.ausgeglichen <= thresholds.leicht <= thresholds.klar
    # The calibration should have picked up that tiny diffs (~1/19) correlate
    # with draws, and the single huge diff (19/19) correlates with a clear win.
    assert thresholds.ausgeglichen < 0.2
    assert thresholds.klar > thresholds.ausgeglichen
