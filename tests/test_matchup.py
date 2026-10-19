from types import SimpleNamespace
from typing import List

from kickbase_tool.data.models import Fixture, MatchdayEntry, Player, TableEntry
from kickbase_tool.data.repository import Dataset
from kickbase_tool.metrics.matchup import (
    DEFAULT_THRESHOLDS,
    GOAL_WEIGHT_CANDIDATES,
    MatchupThresholds,
    _concordance_score,
    _walk_forward_diff_outcome_pairs,
    _weighted_value,
    build_team_strengths,
    calibrate_thresholds,
    classify_diff,
    compute_team_matchday_forecasts,
    normalize_min_max,
    points_multiplier,
    select_goal_weight,
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
    # Vergangene Heim-/Auswaertsspiele fuer A und C (Faktor 2 nutzt seit der
    # Nutzer-Korrektur team_venue_form() -- tatsaechliche KICKBASE-Punkte am
    # Spielort -- statt eines extern vorgegebenen Bundesliga-Tabellenrangs).
    # A spielt auf seinen staerksten Spieltagen (8/9 bzw. 6/7) zuhause bzw.
    # auswaerts, C (abfallende Form) auf seinen schwaechsten -- B bekommt
    # bewusst KEINE Venue-Fixtures (bleibt neutral/mittig, siehe Test unten).
    # "X" ist ein reiner Platzhalter-Gegner, kein Team dieses Datasets.
    venue_fixtures = [
        Fixture(matchday=6, home_team_id="X", away_team_id="A", finished=True),
        Fixture(matchday=7, home_team_id="X", away_team_id="A", finished=True),
        Fixture(matchday=8, home_team_id="A", away_team_id="X", finished=True),
        Fixture(matchday=9, home_team_id="A", away_team_id="X", finished=True),
        Fixture(matchday=6, home_team_id="X", away_team_id="C", finished=True),
        Fixture(matchday=7, home_team_id="X", away_team_id="C", finished=True),
        Fixture(matchday=8, home_team_id="C", away_team_id="X", finished=True),
        Fixture(matchday=9, home_team_id="C", away_team_id="X", finished=True),
    ]
    return Dataset(
        players=players, table=table, fixtures=venue_fixtures + future_fixtures,
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


def test_calibrate_thresholds_does_not_widen_ausgeglichen_past_draw_elevated_zone():
    # Nutzer-Vorgabe 3: "aehnliche Teamstaerke" darf NICHT automatisch mit
    # einer Unentschieden-Prognose gleichgesetzt werden. Hier draws nur bei
    # sehr kleinem |diff|, aber auch ein paar mittelgrosse |diff|-Spiele, die
    # TROTZDEM klar gewonnen werden (kein erhoehtes Unentschieden-Risiko dort)
    # -- ausgeglichen darf sich nicht bis zu diesen mittelgrossen diffs
    # ausdehnen, nur weil irgendwo im Datensatz (weit weg) ein einzelnes
    # Unentschieden mit groesserem |diff| vorkommt.
    strengths = {f"T{i}": {"home": i / 19.0, "away": i / 19.0} for i in range(20)}
    results = []
    for i in range(12):
        results.append({"home_team_id": f"T{i}", "away_team_id": f"T{i+1}", "outcome": "draw"})
    for i in range(0, 12, 2):
        results.append({"home_team_id": f"T{i+6}", "away_team_id": f"T{i}", "outcome": "home"})
    for _ in range(6):
        results.append({"home_team_id": "T19", "away_team_id": "T0", "outcome": "home"})
    dataset = SimpleNamespace(finished_results=results)

    thresholds = calibrate_thresholds(dataset, strengths)
    # Die vielen mittelgrossen, klar entschiedenen Spiele (diff ~6/19=0.316)
    # duerfen nicht in die "ausgeglichen"-Zone hineingezogen werden.
    assert thresholds.ausgeglichen < 0.316


def test_calibrate_thresholds_ausgeglichen_requires_draws_to_strictly_beat_favorite_hit_rate():
    # Regressionstest fuer einen frueheren Zwischenstand dieser Korrektur:
    # eine blosse GLEICHHEIT von Unentschieden- und Favorit-Trefferquote in
    # einem Bucket, der (durch Zufall der Bucket-Einteilung) sowohl sehr
    # kleine als auch sehr grosse |diff|-Werte mischt, durfte NICHT dazu
    # fuehren, dass "ausgeglichen" bis zur Obergrenze dieses Mischbuckets
    # (hier 19/19=1.0, ein eindeutiger Favoritensieg) hochgezogen wird.
    strengths = {f"T{i}": {"home": i / 19.0, "away": i / 19.0} for i in range(20)}
    results = []
    for i in range(10):
        results.append({"home_team_id": f"T{i}", "away_team_id": f"T{i+1}", "outcome": "draw"})
    for _ in range(10):
        results.append({"home_team_id": "T19", "away_team_id": "T0", "outcome": "home"})
    dataset = SimpleNamespace(finished_results=results)

    thresholds = calibrate_thresholds(dataset, strengths)
    assert thresholds.ausgeglichen < 0.2
    assert 0 <= thresholds.ausgeglichen <= thresholds.leicht <= thresholds.klar


def test_weighted_value_drops_missing_factor_and_renormalizes_remaining():
    # Nutzer-Vorgabe 4: ein fehlender Faktor (hier: raw=None, wie z.B.
    # Momentum vor Spieltag 7) wird herausgenommen statt neutral mit 0.5
    # aufgefuellt -- die uebrigen Gewichte werden proportional auf 100%
    # skaliert, nicht einfach das Gesamtergebnis um das fehlende Gewicht
    # verkleinert.
    components_with_missing = [
        (0.8, 0.8, 0.5),   # vorhanden, Gewicht 0.5
        (None, 0.5, 0.3),  # FEHLT (raw=None) -- muss herausfallen
        (0.2, 0.2, 0.2),   # vorhanden, Gewicht 0.2
    ]
    # Erwartet: (0.8*0.5 + 0.2*0.2) / (0.5+0.2) = 0.6286 -- NICHT 0.8*0.5+0.5*0.3+0.2*0.2=0.56
    result = _weighted_value(components_with_missing)
    assert abs(result - ((0.8 * 0.5 + 0.2 * 0.2) / 0.7)) < 1e-9

    # Alle Faktoren fehlen -> neutraler Fallback, analog normalize_min_max().
    assert _weighted_value([(None, 0.5, 0.5), (None, 0.5, 0.5)]) == 0.5


def test_compute_team_matchday_forecasts_is_mirror_symmetric_for_both_sides():
    # Nutzer-Vorgabe 6: fuer beide Teams EINER Begegnung muessen sich immer
    # spiegelbildliche Prognosen ergeben (Favorit auf der einen Seite <->
    # Aussenseiter mit gleichem Grad auf der anderen, exakt entgegengesetztes
    # diff-Vorzeichen und derselbe Betrag).
    dataset = _build_dataset()
    strengths = build_team_strengths(dataset)
    forecasts = compute_team_matchday_forecasts(dataset, strengths, DEFAULT_THRESHOLDS, window=5)

    for team_id, entries in forecasts.items():
        for entry in entries:
            opp_entries = forecasts[entry["opponent_team_id"]]
            mirror = next(e for e in opp_entries if e["matchday"] == entry["matchday"])
            assert mirror["opponent_team_id"] == team_id
            assert mirror["home"] != entry["home"]
            assert abs(mirror["diff"] + entry["diff"]) < 1e-9
            # Favorit auf der einen Seite <-> Aussenseiter gleichen Grades auf
            # der anderen (oder beide "Ausgeglichen").
            if "Favorit" in entry["label"]:
                assert "Außenseiter" in mirror["label"]
                assert entry["label"].split()[0] == mirror["label"].split()[0]  # "Klarer"/"Leichter"
            elif "Außenseiter" in entry["label"]:
                assert "Favorit" in mirror["label"]
            else:
                assert entry["label"] == mirror["label"] == "Ausgeglichen"


def _goal_dataset(n_matchdays: int) -> Dataset:
    """Synthetischer Dataset-Stand fuer die Tor-Faktor-Tests: 4 Teams (A, B,
    C, D) mit IDENTISCHEN (neutralen) KICKBASE-Teampunkten ueber alle
    Spieltage -- die 4 bestehenden Faktoren sind damit fuer alle 4 Teams
    bedeutungslos (keine Unterschiede), nur das reale Tor-Signal kann hier
    noch differenzieren. A gewinnt JEDES Spiel gegen D klar (3:0, egal an
    welchem Spielort), B und C spielen immer 1:1 -- gibt normalize_min_max()
    genug verschiedene Werte (A/D an den Raendern, B/C neutral in der Mitte),
    um ueberhaupt sinnvoll zu normalisieren (mit nur 2 Teams waere A der
    EINZIGE Heim-Datenpunkt -- normalize_min_max faellt dann auf den
    entarteten "alle Werte gleich"-Fall zurueck, siehe dortiger Docstring).
    Pro Spieltag abwechselnd A zuhause/auswaerts gegen D, damit A sowohl
    Heim- als auch Auswaertsdaten hat."""
    teams = ["A", "B", "C", "D"]
    both_points = {md: 5.0 for md in range(1, n_matchdays + 1)}
    players = [_player(tid, dict(both_points)) for tid in teams]
    table = [TableEntry(team_id=tid, team_name=tid, position=i + 1) for i, tid in enumerate(teams)]

    fixtures: List[Fixture] = []
    finished_results: List[dict] = []
    for md in range(1, n_matchdays + 1):
        is_finished = md < n_matchdays
        a_home = md % 2 == 1
        ad_home, ad_away = ("A", "D") if a_home else ("D", "A")
        ad_home_goals, ad_away_goals = (3, 0) if a_home else (0, 3)
        fixtures.append(Fixture(matchday=md, home_team_id=ad_home, away_team_id=ad_away, finished=is_finished))
        fixtures.append(Fixture(matchday=md, home_team_id="B", away_team_id="C", finished=is_finished))
        if is_finished:
            finished_results.append({
                "home_team_id": ad_home, "away_team_id": ad_away,
                "outcome": "home" if a_home else "away",
                "matchday": md, "home_goals": ad_home_goals, "away_goals": ad_away_goals,
            })
            finished_results.append({
                "home_team_id": "B", "away_team_id": "C", "outcome": "draw",
                "matchday": md, "home_goals": 1, "away_goals": 1,
            })
    return Dataset(players=players, table=table, fixtures=fixtures, finished_results=finished_results)


def test_select_goal_weight_falls_back_to_zero_with_too_few_walk_forward_matches():
    # Nur 6 Spieltage (5 bereits gespielt) -> 4 vorhersagbare Spieltage (2,3,
    # 4,5) x 2 Ergebnisse = 8 walk-forward-Paare -- klar unter
    # MIN_CALIBRATION_MATCHES, also Fallback auf 0.0.
    dataset = _goal_dataset(n_matchdays=6)
    assert select_goal_weight(dataset) == 0.0


def test_select_goal_weight_picks_a_positive_weight_when_goals_clearly_predict_outcome():
    # 14 Spieltage (13 bereits gespielt) -> 12 vorhersagbare Spieltage x 2 =
    # 24 walk-forward-Paare, genug Datenbasis. Die 4 bestehenden Faktoren
    # sind fuer alle 4 Teams identisch (siehe _goal_dataset), nur der
    # Tor-Faktor kann den klaren A>D/B==C-Zusammenhang abbilden -- die
    # Gewichtsauswahl sollte das erkennen und NICHT bei 0.0 landen.
    dataset = _goal_dataset(n_matchdays=14)
    weight = select_goal_weight(dataset)
    assert weight in GOAL_WEIGHT_CANDIDATES
    assert weight > 0.0

    all_team_ids = ["A", "B", "C", "D"]
    pairs_without_goals = _walk_forward_diff_outcome_pairs(dataset, all_team_ids, 0.0)
    pairs_with_goals = _walk_forward_diff_outcome_pairs(dataset, all_team_ids, weight)
    assert _concordance_score(pairs_with_goals) >= _concordance_score(pairs_without_goals)


def test_goal_diff_factor_breaks_ties_between_otherwise_identical_teams():
    # Mit identischen Kickbase-Punkten fuer alle 4 Teams (siehe _goal_dataset)
    # sollte ausschliesslich das reale Tor-Signal eine Staerke-Differenz
    # zugunsten des torhungrigen Teams A (vs. des chancenlosen D) erzeugen,
    # sobald der Tor-Faktor ueberhaupt Gewicht bekommt -- und B/C (immer
    # Unentschieden) bleiben dabei klar dazwischen.
    dataset = _goal_dataset(n_matchdays=14)
    strengths = build_team_strengths(dataset)
    assert strengths["A"]["home"] > strengths["B"]["home"] > strengths["D"]["home"]
    assert strengths["A"]["away"] > strengths["C"]["away"] > strengths["D"]["away"]
