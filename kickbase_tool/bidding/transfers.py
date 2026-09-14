"""Liest die echten abgeschlossenen Transfers der eigenen Liga
(/v4/leagues/{id}/activitiesFeed, siehe api/endpoints.py fuer die
Live-Bestaetigung dieses bislang ungenutzten Endpunkts) und baut daraus einen
dauerhaften, wachsenden Transfer-Log auf -- die "wichtigste" Lernbasis fuer das
Gebotsmodell (siehe Aufgabenstellung).

Look-ahead-Bias: Ein frisch entdeckter Transfer wird mit den Spieler-Werten
von JETZT anreichert (Marktwert, Rang, Startchance, PPM, MW-Trend) -- das ist
bias-frei fuer alles, was AB Einfuehrung dieses Features passiert, weil der
Update-Zyklus ohnehin alle ~2h laeuft und ein neuer Transfer damit fast immer
innerhalb weniger Stunden entdeckt wird. Fuer die Erstbefuellung (die gesamte
bisherige Saison wird beim allerersten Lauf "auf einen Schlag" entdeckt) gibt
es dafuer keine Abhilfe ohne Zeitmaschine -- diese Datensaetze werden explizit
mit backfilled=True markiert und in calibration.py/similarity.py mit
reduziertem Gewicht einbezogen, statt sie zu verwerfen (siehe
bidding_config.yaml: backfilled_weight_factor)."""
import json
from pathlib import Path
from typing import Dict, List, Optional

from kickbase_tool.api import endpoints
from kickbase_tool.api.client import KickbaseAPIError, KickbaseClient
from kickbase_tool.config import Settings
from kickbase_tool.util import pick

DEFAULT_TRANSFER_LOG_PATH = Path("league_history/transfer_log.json")
ACTIVITY_FEED_MAX = 790  # Server-seitiges Maximum, live bestaetigt 2026-09-14 (siehe endpoints.py).

# Activity-Feed-Eintragstyp fuer Markttransfers; nested "data.t" unterscheidet
# einen echten Kauf durch einen Manager (1, mit "byr"/Kaeufername) von einem
# Verkauf zurueck an den Markt ohne Kaeufer (2, nur "slr"/Verkaeufername) --
# letzteres ist kein "jemand hat ueberboten"-Signal und wird nicht gelernt.
ACTIVITY_TYPE_TRANSFER = 15
TRANSFER_SUBTYPE_PURCHASE = 1


def fetch_raw_activity_feed(client: KickbaseClient, settings: Settings, max_entries: int = ACTIVITY_FEED_MAX) -> list:
    """Best-effort wie die uebrigen optionalen Liga-Integrationen in diesem
    Projekt (siehe repository._fetch_venue_points): jeder Fehler (kein
    KICKBASE_LEAGUE_ID, Netzwerkfehler, unerwartete Antwortform) degradiert zu
    einer leeren Liste statt die gesamte Pipeline zu brechen."""
    if not settings.league_id:
        return []
    try:
        raw = client.get(
            endpoints.LEAGUE_ACTIVITIES_FEED.format(league_id=settings.league_id),
            params={"max": max_entries},
        )
        activities = raw.get("af") if isinstance(raw, dict) else None
        return activities if isinstance(activities, list) else []
    except KickbaseAPIError:
        return []


def extract_purchase_events(raw_activities: list) -> List[dict]:
    events = []
    for entry in raw_activities:
        if not isinstance(entry, dict) or entry.get("t") != ACTIVITY_TYPE_TRANSFER:
            continue
        data = entry.get("data") or {}
        if data.get("t") != TRANSFER_SUBTYPE_PURCHASE:
            continue
        buyer = pick(data, "byr")
        player_id = pick(data, "pi")
        price = pick(data, "trp")
        if not buyer or player_id is None or price is None:
            continue
        events.append({
            "id": str(pick(entry, "i")),
            "player_id": str(player_id),
            "player_name": pick(data, "pn"),
            "team_id": pick(data, "tid"),
            "buyer": buyer,
            "transfer_price": float(price),
            "bid_count": pick(data, "coc"),
            "dt": pick(entry, "dt"),
        })
    return events


def load_transfer_log(path: Path = DEFAULT_TRANSFER_LOG_PATH) -> List[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_transfer_log(log: List[dict], path: Path = DEFAULT_TRANSFER_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False)


_SNAPSHOT_ROW_FIELDS = [
    "market_value", "kauf_rank", "start_probability", "points_per_value",
    "market_value_change_day", "position", "status",
]


def _enrich_event(event: dict, row: dict, backfilled: bool) -> dict:
    market_value = row.get("market_value")
    price = event["transfer_price"]
    overpay_abs = (price - market_value) if market_value is not None else None
    overpay_pct = (overpay_abs / market_value * 100.0) if market_value else None
    record = dict(event)
    record["backfilled"] = backfilled
    for field in _SNAPSHOT_ROW_FIELDS:
        record[field] = row.get(field)
    record["overpay_abs"] = overpay_abs
    record["overpay_pct"] = overpay_pct
    return record


def ingest_new_transfers(
    rows_by_pid: Dict[str, dict],
    client: KickbaseClient,
    settings: Settings,
    path: Path = DEFAULT_TRANSFER_LOG_PATH,
) -> List[dict]:
    """Holt den aktuellen Activity-Feed, ergaenzt den dauerhaften Transfer-Log
    um alle bislang unbekannten echten Kauf-Events (dedupliziert per Activity-
    Id) und persistiert das Ergebnis. Gibt IMMER den (ggf. unveraenderten) Log
    zurueck -- ein Fehler beim Abruf darf das bisher gelernte Wissen nie
    verwerfen."""
    existing = load_transfer_log(path)
    known_ids = {t.get("id") for t in existing}

    raw_activities = fetch_raw_activity_feed(client, settings)
    if not raw_activities:
        return existing

    events = extract_purchase_events(raw_activities)
    new_events = [e for e in events if e["id"] not in known_ids]
    if not new_events:
        return existing

    # Beim allerersten Lauf (noch kein Log vorhanden) wird die komplette
    # bisherige Saison "auf einen Schlag" entdeckt -- diese Datensaetze koennen
    # nicht bias-frei sein (siehe Modul-Docstring) und werden entsprechend
    # markiert.
    is_initial_backfill = len(existing) == 0

    enriched: List[dict] = []
    for event in new_events:
        row = rows_by_pid.get(event["player_id"])
        if row is None:
            continue  # Spieler nicht mehr im aktuellen Pool (z.B. Liga-Wechsel) -- ueberspringen statt raten.
        enriched.append(_enrich_event(event, row, backfilled=is_initial_backfill))

    if not enriched:
        return existing

    combined = existing + enriched
    combined.sort(key=lambda t: t.get("dt") or "")
    save_transfer_log(combined, path)
    return combined
