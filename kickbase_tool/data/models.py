from dataclasses import dataclass, field
from typing import List, Optional

# Status codes confirmed against live /v4/competitions/1/players/{id} and
# /teams/{id}/teamprofile responses: st=0 was seen for healthy players, st=2
# for a player with a minor issue (Gnabry). Other codes are carried over from
# older community reverse-engineering and unverified live -- see README
# "Annahmen". Any status other than NONE (0) is treated as "player
# unavailable" for ranking purposes, per explicit instruction: unavailable
# players are filtered out entirely rather than down-ranked.
STATUS_NONE = 0
STATUS_LABELS = {
    0: "fit",
    1: "verletzt",
    2: "angeschlagen",
    4: "Reha",
    8: "rote Karte",
    16: "Gelb-Rot",
    32: "5. Gelbe Karte",
    64: "nicht im Kader",
    128: "nicht in der Liga",
    256: "abwesend",
}


def status_label(status: Optional[int]) -> str:
    if status is None:
        return "unbekannt"
    return STATUS_LABELS.get(status, f"Status {status}")


@dataclass
class MatchdayEntry:
    matchday: int
    played: bool
    started: bool
    points: Optional[float]
    minutes: Optional[int]
    home: Optional[bool]
    team_id: Optional[str]
    opponent_team_id: Optional[str]


@dataclass
class Player:
    id: str
    first_name: str
    last_name: str
    team_id: Optional[str]
    position: Optional[int]  # 1=TW, 2=ABW, 3=MF, 4=ST
    status: Optional[int]
    market_value: Optional[float]
    season_average_points: Optional[float]
    # Season totals for Kennzahl 12 -- confirmed live as top-level "g"/"a"/"cs"
    # fields on /v4/competitions/{id}/players/{id}, not derivable per-matchday
    # (the performance endpoint's per-match entries carry no goal/assist/
    # clean-sheet breakdown, only the running points total).
    season_goals: int = 0
    season_assists: int = 0
    season_clean_sheets: int = 0
    matchdays: List[MatchdayEntry] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.id

    @property
    def is_unavailable(self) -> bool:
        return self.status is not None and self.status != STATUS_NONE

    @property
    def status_text(self) -> str:
        return status_label(self.status)

    def matchdays_desc(self) -> List[MatchdayEntry]:
        return sorted(self.matchdays, key=lambda e: e.matchday, reverse=True)


POSITION_LABELS = {1: "TW", 2: "ABW", 3: "MF", 4: "ST"}


@dataclass
class TableEntry:
    team_id: str
    team_name: str
    position: int


@dataclass
class Fixture:
    matchday: int
    home_team_id: str
    away_team_id: str
    finished: bool
