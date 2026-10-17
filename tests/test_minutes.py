from kickbase_tool.data.models import Fixture, MatchdayEntry, Player
from kickbase_tool.metrics.calculations import (
    MINUTES_PER_MATCHDAY,
    compute_last5_minutes,
    minutes_window_matchdays,
)


def entry(matchday, minutes, played=True):
    return MatchdayEntry(
        matchday=matchday, played=played, points=5.0 if played else None, minutes=minutes,
        home=True, team_id="T1", opponent_team_id="T2",
    )


def player(matchdays):
    return Player(
        id="p1", first_name="Test", last_name="Player", team_id="T1", position=4,
        status=0, market_value=1_000_000, season_average_points=5.0, matchdays=matchdays,
    )


def fixture(matchday, finished=True, home="T1", away="T2"):
    return Fixture(matchday=matchday, home_team_id=home, away_team_id=away, finished=finished)


def test_minutes_window_uses_last_five_fully_finished_matchdays():
    fixtures = [fixture(md) for md in range(1, 15)]
    assert minutes_window_matchdays(fixtures) == [10, 11, 12, 13, 14]


def test_minutes_window_shrinks_when_season_is_young():
    # Erst 3 Spieltage abgeschlossen -> Fenster/Obergrenze automatisch
    # kleiner statt mit 2 Phantom-Spieltagen aufzufuellen.
    fixtures = [fixture(1), fixture(2), fixture(3)]
    window = minutes_window_matchdays(fixtures)
    assert window == [1, 2, 3]
    assert len(window) * MINUTES_PER_MATCHDAY == 270


def test_minutes_window_excludes_a_matchday_that_is_still_in_progress():
    # Nutzer-Vorgabe-Fix: ein Spieltag mit mehreren Partien gilt erst als
    # abgeschlossen, wenn ALLE seine Spiele finished=True sind -- sonst
    # haetten die Spieler der noch nicht gespielten Partien faelschlich
    # "Daten fehlen" statt korrekt "Spieltag laeuft noch, zaehlt nicht zum
    # Fenster".
    fixtures = [
        fixture(1, finished=True), fixture(2, finished=True), fixture(3, finished=True),
        fixture(4, finished=True),
        # Spieltag 5: Freitagsspiel schon vorbei, Sonntagsspiel noch nicht.
        fixture(5, finished=True, home="T1", away="T2"),
        fixture(5, finished=False, home="T3", away="T4"),
    ]
    assert minutes_window_matchdays(fixtures) == [1, 2, 3, 4]


def test_regular_starter_gets_near_max_ratio():
    p = player([entry(md, 90) for md in range(10, 15)])
    total, breakdown = compute_last5_minutes(p, [10, 11, 12, 13, 14])
    assert total == 450
    assert all(b["status"] == "played" and b["minutes"] == 90 for b in breakdown)


def test_joker_gets_partial_credit_proportional_to_minutes():
    # Kurzeinsaetze von der Bank statt volle 90 Minuten -- zaehlt trotzdem
    # als "played", nur mit weniger Minuten, keine zusaetzliche Startchance-
    # Doppelzaehlung.
    p = player([entry(md, 15) for md in range(10, 15)])
    total, breakdown = compute_last5_minutes(p, [10, 11, 12, 13, 14])
    assert total == 75
    assert all(b["status"] == "played" and b["minutes"] == 15 for b in breakdown)


def test_injured_player_recent_zeros_outweigh_high_season_minutes():
    # Grosse Saison-Gesamtminuten aus der Vergangenheit, aber in den letzten
    # 5 Spieltagen durchgehend verletzt/nicht im Kader -- last5_minutes_total
    # muss die aktuelle Verletzung zeigen (0), nicht die alte Normalform.
    old_games = [entry(md, 90) for md in range(1, 10)]
    injured_recent = [entry(md, None, played=False) for md in range(10, 15)]
    p = player(old_games + injured_recent)
    total, breakdown = compute_last5_minutes(p, [10, 11, 12, 13, 14])
    assert total == 0
    assert all(b["status"] == "not_played" and b["minutes"] == 0 for b in breakdown)
    # Saison-Gesamtminuten (nur Anzeige, siehe PlayerMetrics) bleiben davon
    # unberuehrt -- das ist hier nicht Teil von compute_last5_minutes, aber
    # die Eingabedaten zeigen den Kontrast: 9 x 90 = 810 Saisonminuten trotz
    # last5_minutes_total von 0.
    assert sum(e.minutes or 0 for e in old_games) == 810


def test_returnee_fully_rehabilitates_once_the_window_is_fresh_minutes():
    # Verletzung auf Spieltag 8-10, danach durchgehend wieder volle
    # Einsaetze auf 11-15 -- sobald das 5er-Fenster (11..15) komplett aus
    # neuen Einsaetzen besteht, duerfen die alten Ausfaelle (8-10, jetzt
    # ausserhalb des Fensters) keinen Einfluss mehr haben.
    injury = [entry(md, None, played=False) for md in range(8, 11)]
    comeback = [entry(md, 90) for md in range(11, 16)]
    p = player(injury + comeback)
    total, breakdown = compute_last5_minutes(p, [11, 12, 13, 14, 15])
    assert total == 450
    assert all(b["matchday"] >= 11 for b in breakdown)
    assert all(b["status"] == "played" for b in breakdown)


def test_not_played_matchday_counts_as_zero_not_missing():
    p = player([entry(10, None, played=False)])
    total, breakdown = compute_last5_minutes(p, [10])
    assert total == 0
    assert breakdown == [{"matchday": 10, "minutes": 0, "status": "not_played"}]


def test_missing_matchday_data_is_distinguished_from_not_played_and_nulls_the_total():
    # Spieltag 11 fehlt komplett (z.B. Wechsel aus einer anderen Liga, oder
    # echte Datenluecke) -- im Gegensatz zu Spieltag 10 (bestaetigt nicht
    # gespielt) darf das NICHT als 0 gewertet werden. Sobald auch nur ein
    # Spieltag im Fenster fehlt, bleibt der gesamte last5_minutes_total None
    # (neutral behandelt), statt eine verkuerzte Teilsumme zu bilden.
    p = player([entry(10, None, played=False), entry(12, 90)])
    total, breakdown = compute_last5_minutes(p, [10, 11, 12])
    assert total is None
    by_md = {b["matchday"]: b for b in breakdown}
    assert by_md[10] == {"matchday": 10, "minutes": 0, "status": "not_played"}
    assert by_md[11] == {"matchday": 11, "minutes": None, "status": "missing"}
    assert by_md[12] == {"matchday": 12, "minutes": 90, "status": "played"}


def test_played_matchday_without_minutes_data_also_counts_as_missing():
    # Punkte-Eintrag vorhanden (played=True), aber keine Minutenangabe --
    # ebenfalls eine Datenluecke, kein bestaetigtes "nicht gespielt".
    p = player([entry(10, None, played=True)])
    total, breakdown = compute_last5_minutes(p, [10])
    assert total is None
    assert breakdown == [{"matchday": 10, "minutes": None, "status": "missing"}]


def test_empty_window_before_any_matchday_is_finished():
    p = player([])
    assert minutes_window_matchdays([]) == []
    assert minutes_window_matchdays([fixture(1, finished=False)]) == []
    total, breakdown = compute_last5_minutes(p, [])
    assert total == 0
    assert breakdown == []
