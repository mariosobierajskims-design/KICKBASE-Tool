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


# Startelf-Wahrscheinlichkeit ("prob"), confirmed live 2026-09-14 against
# /v4/competitions/{id}/teams/{id}/teamprofile and /v4/leagues/{id}/squad
# responses -- NOT present on the per-player detail endpoint, which is why
# this is populated separately in data/repository.py from the roster call
# that's already being made (see _fetch_team_rosters). Values 1/2/3/5
# confirmed against real squad data (e.g. a backup goalkeeper = 5, an
# injured/angeschlagen starter = 5, an undisputed starter = 1); 4 is filled
# in by elimination (not observed live yet, but the only gap in the 1-5
# range and consistent with community reverse-engineering docs).
START_PROBABILITY_SICHER = 1
START_PROBABILITY_ERWARTET = 2
START_PROBABILITY_UNSICHER = 3
START_PROBABILITY_UNWAHRSCHEINLICH = 4
START_PROBABILITY_AUSGESCHLOSSEN = 5
START_PROBABILITY_LABELS = {
    1: "Sicher",
    2: "Erwartet",
    3: "Unsicher",
    4: "Unwahrscheinlich",
    5: "Ausgeschlossen",
}


def start_probability_label(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    return START_PROBABILITY_LABELS.get(value)


@dataclass
class MatchdayEntry:
    matchday: int
    played: bool
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
    image_url: Optional[str] = None
    team_logo_url: Optional[str] = None
    matchdays: List[MatchdayEntry] = field(default_factory=list)
    # Populated from the team-roster ("teamprofile") response in
    # data/repository.py, not from normalize_player_detail -- see
    # start_probability_label() above for why these live here as plain
    # optional fields rather than on a separate model.
    start_probability: Optional[int] = None
    # Raw Kickbase "mvt" direction flag (0=stable/1=up/2=down, best-effort --
    # market_value_change_day below is the actual signed € amount and should
    # be preferred wherever a magnitude is needed).
    market_value_trend_direction: Optional[int] = None
    market_value_change_day: Optional[float] = None

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.id

    @property
    def start_probability_text(self) -> Optional[str]:
        return start_probability_label(self.start_probability)

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
