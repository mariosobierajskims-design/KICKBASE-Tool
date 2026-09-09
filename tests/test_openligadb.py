from kickbase_tool.data.openligadb import (
    compute_venue_points,
    map_shortnames_to_kickbase_ids,
    points_per_game,
)


def make_match(team1, team2, points1, points2, finished=True):
    return {
        "matchIsFinished": finished,
        "team1": {"shortName": team1},
        "team2": {"shortName": team2},
        "matchResults": [
            {"resultTypeKind": "HalfTime", "pointsTeam1": 0, "pointsTeam2": 0, "resultOrderID": 1},
            {"resultTypeKind": "After90Minutes", "pointsTeam1": points1, "pointsTeam2": points2, "resultOrderID": 2},
        ],
    }


def test_compute_venue_points_awards_real_league_points_home_and_away():
    matches = [
        make_match("Bayern", "Stuttgart", 5, 1),  # Bayern win at home
        make_match("Koeln", "Bayern", 1, 1),  # Bayern draw away
    ]
    home, away = compute_venue_points(matches)
    assert home["Bayern"] == {"points": 3, "matches": 1}
    assert home["Koeln"] == {"points": 1, "matches": 1}
    assert away["Stuttgart"] == {"points": 0, "matches": 1}
    assert away["Bayern"] == {"points": 1, "matches": 1}


def test_unfinished_matches_are_ignored():
    matches = [make_match("Bayern", "Stuttgart", 5, 1, finished=False)]
    home, away = compute_venue_points(matches)
    assert home == {}
    assert away == {}


def test_points_per_game_averages_across_matches():
    stats = {"Bayern": {"points": 6, "matches": 2}}
    assert points_per_game(stats) == {"Bayern": 3.0}


def test_map_shortnames_to_kickbase_ids_applies_known_aliases():
    ppg = {"Bayern": 3.0, "S04": 1.0, "HSV": 0.0, "Gladbach": 1.5}
    team_name_by_id = {"2": "Bayern", "8": "Schalke", "6": "Hamburg", "15": "M'gladbach"}
    result = map_shortnames_to_kickbase_ids(ppg, team_name_by_id)
    assert result == {"2": 3.0, "8": 1.0, "6": 0.0, "15": 1.5}


def test_map_shortnames_to_kickbase_ids_drops_unmatched_teams():
    ppg = {"UnknownClub": 2.0}
    result = map_shortnames_to_kickbase_ids(ppg, {"2": "Bayern"})
    assert result == {}
