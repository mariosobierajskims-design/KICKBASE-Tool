from dataclasses import dataclass
from typing import List, Optional

from kickbase_tool.data.models import MatchdayEntry
from kickbase_tool.util import mean


@dataclass
class RecentForm:
    games_used: int
    average: Optional[float]
    minimum: Optional[float]
    maximum: Optional[float]
    min_max_average: Optional[float]
    start_rate: Optional[float]


def compute_recent_form(entries_desc: List[MatchdayEntry]) -> RecentForm:
    """Punkte-Durchschnitt/Min/Max/Startquote der "letzten 5 Spiele" mit Fallback:

    - 5 von 5 der letzten 5 Spieltage gespielt  -> genau diese 5 Spiele
    - 4 von 5 gespielt                          -> genau diese 4 Spiele
    - 3 von 5 gespielt                          -> die letzten 4 tatsaechlich
      bestrittenen Spiele (auch wenn dafuer weiter zurueckgegangen wird)
    - 0-2 von 5 gespielt                        -> die letzten 5 tatsaechlich
      bestrittenen Spiele (unabhaengig davon wie weit das zurueckliegt)

    `entries_desc` muss chronologisch absteigend sortiert sein (neuestes Spiel zuerst)
    und alle Spieltage des Spielers enthalten (auch nicht gespielte), damit sich
    "wie viele der letzten 5 Spieltage wurden gespielt" bestimmen laesst.
    """
    last5 = entries_desc[:5]
    played_in_last5 = sum(1 for e in last5 if e.played)
    played_all = [e for e in entries_desc if e.played]

    if played_in_last5 in (4, 5):
        games_needed = played_in_last5
    elif played_in_last5 == 3:
        games_needed = 4
    else:
        games_needed = 5

    chosen = played_all[:games_needed]
    if not chosen:
        return RecentForm(games_used=0, average=None, minimum=None, maximum=None, min_max_average=None, start_rate=None)

    points = [e.points for e in chosen if e.points is not None]
    if not points:
        return RecentForm(games_used=len(chosen), average=None, minimum=None, maximum=None, min_max_average=None, start_rate=None)

    lo, hi = min(points), max(points)
    started = sum(1 for e in chosen if e.started)
    return RecentForm(
        games_used=len(chosen),
        average=mean(points),
        minimum=lo,
        maximum=hi,
        min_max_average=(lo + hi) / 2,
        start_rate=started / len(chosen),
    )
