"""Datums-Hilfen (Europe/Berlin)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
WOCHENTAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]


def wochentag_key(d: date) -> str:
    return WOCHENTAGE[d.weekday()]


def letzter_wochentag(heute: date, key: str) -> date:
    """Letzter zurückliegender Tag mit Wochentag `key` (strikt vor heute)."""
    target = WOCHENTAGE.index(key)
    delta = (heute.weekday() - target) % 7 or 7
    return heute - timedelta(days=delta)


def vorheriger_werktag(heute: date) -> date:
    d = heute - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def ist_erster_wochentag_im_monat(d: date) -> bool:
    return d.day <= 7


def wochen_grenzen(d: date) -> tuple[date, date]:
    """Montag und Freitag der Woche von d."""
    mo = d - timedelta(days=d.weekday())
    return mo, mo + timedelta(days=4)


def parse_dt(value: object) -> datetime | None:
    """Parst onOffice-Datumsangaben ('YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD', ISO mit Offset).

    Ergebnis ist timezone-aware in Europe/Berlin. Werte ohne Offset gelten als lokale Zeit.
    """
    if value in (None, "", "0000-00-00", "0000-00-00 00:00:00"):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip().replace("Z", "+00:00")
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y %H:%M"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
        if dt is None:
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def fmt_api(dt: datetime | date) -> str:
    """Format für onOffice-Filter (Maklerbuch/Adressen): 'YYYY-MM-DD HH:MM:SS'."""
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d 00:00:00")


def start_of_day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def end_of_day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)


def fmt_de(d: datetime | date | None, mit_zeit: bool = False) -> str:
    if d is None:
        return "–"
    if mit_zeit and isinstance(d, datetime):
        return d.strftime("%d.%m. %H:%M")
    return d.strftime("%d.%m.%Y")
