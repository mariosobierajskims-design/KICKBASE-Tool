from kickbase_tool.data.models import MatchdayEntry
from kickbase_tool.metrics.fallback import compute_recent_form


def entry(matchday, points, played=True):
    return MatchdayEntry(
        matchday=matchday, played=played, points=points, minutes=90 if played else 0,
        home=True, team_id="T1", opponent_team_id="T2",
    )


def test_all_five_played_uses_all_five():
    entries_desc = [entry(10, 8), entry(9, 4), entry(8, 6), entry(7, 2), entry(6, 10)]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 5
    assert form.average == (8 + 4 + 6 + 2 + 10) / 5
    assert form.minimum == 2
    assert form.maximum == 10
    assert form.min_max_average == 6


def test_four_of_five_played_uses_those_four():
    entries_desc = [
        entry(10, None, played=False),
        entry(9, 4),
        entry(8, 6),
        entry(7, 2),
        entry(6, 10),
    ]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 4
    assert form.average == (4 + 6 + 2 + 10) / 4
    assert form.minimum == 2
    assert form.maximum == 10


def test_three_of_five_played_falls_back_to_last_four_actually_played():
    entries_desc = [
        entry(12, None, played=False),
        entry(11, 5),
        entry(10, None, played=False),
        entry(9, 7),
        entry(8, 3),
        entry(7, 9),  # 4th actually-played game, further back than the "last 5" window
        entry(6, 1),  # should NOT be included (only last 4 played games)
    ]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 4
    assert form.average == (5 + 7 + 3 + 9) / 4
    assert form.minimum == 3
    assert form.maximum == 9


def test_two_of_five_played_falls_back_to_last_five_actually_played():
    entries_desc = [
        entry(12, None, played=False),
        entry(11, 5),
        entry(10, None, played=False),
        entry(9, None, played=False),
        entry(8, 3),
        entry(7, 9),
        entry(6, 1),
        entry(5, 4),
        entry(4, 2),  # 5th actually-played game further back
        entry(3, 100),  # should NOT be included
    ]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 5
    assert form.average == (5 + 3 + 9 + 1 + 4) / 5


def test_zero_played_uses_last_five_ever_played_regardless_of_age():
    entries_desc = [
        entry(20, None, played=False),
        entry(19, None, played=False),
        entry(18, None, played=False),
        entry(17, None, played=False),
        entry(16, None, played=False),
        entry(5, 6),
        entry(4, 8),
        entry(3, 2),
        entry(2, 4),
        entry(1, 10),
    ]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 5
    assert form.average == (6 + 8 + 2 + 4 + 10) / 5


def test_no_games_played_ever_returns_none_values():
    entries_desc = [entry(1, None, played=False)]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 0
    assert form.average is None
    assert form.minimum is None
    assert form.maximum is None
    assert form.min_max_average is None


def test_fewer_career_games_than_needed_degrades_gracefully():
    # Rookie with only 2 played games ever, 0 of the last 5 calendar slots played
    # -> needs 5, but only 2 exist.
    entries_desc = [
        entry(5, None, played=False),
        entry(4, None, played=False),
        entry(3, None, played=False),
        entry(2, 7),
        entry(1, 3),
    ]
    form = compute_recent_form(entries_desc)
    assert form.games_used == 2
    assert form.average == 5.0
