"""Persistenter, taeglicher Spieler-Snapshot.

Zwei Zwecke:
1. Baut mit der Zeit einen echten Mehrtage-Marktwertverlauf auf (Kickbase
   liefert selbst keinen bestaetigten Verlaufs-Endpoint, siehe README dieses
   Projekts / bidding/__init__.py) -- ohne das koennten wir nur die taegliche
   Aenderung ("sdmvt"), aber keinen 3-7-Tage-Trend oder dessen Beschleunigung
   berechnen (siehe Aufgabenstellung "Marktwertentwicklung").
2. Ist die Grundlage dafuer, neu entdeckte Ligatransfers bias-frei mit den
   Werten von JETZT statt von HEUTE-IN-DER-ZUKUNFT anzureichern (siehe
   transfers.py) -- da wir ohnehin bei jedem Update-Zyklus einen Snapshot
   schreiben, kann ein frisch entdeckter Transfer den zeitlich naechstliegenden
   Snapshot verwenden statt spaeterer (verzerrter) Werte.

Speicherort bewusst ausserhalb von artifact_data/ (das bei jedem Lauf komplett
neu geschrieben wird) und ausserhalb von .cache/ (das eine TTL hat und verworfen
werden darf) -- dies hier ist absichtlich dauerhafter Zustand, siehe .gitignore
("league_history/").
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_STORE_PATH = Path("league_history/player_snapshots.json")
MAX_HISTORY_PER_PLAYER = 10

SNAPSHOT_FIELDS = [
    "market_value", "kauf_rank", "start_probability", "points_per_value", "market_value_change_day",
    # Ab hier nicht fuer trend_stats() genutzt, sondern damit transfers.py
    # (_historical_row) bei der Anreicherung frischer Transfers eine
    # vollstaendige historische Row zusammenstellen kann (siehe
    # transfers._SNAPSHOT_ROW_FIELDS/Modul-Docstring dort).
    "position", "status", "season_avg", "team_form",
]


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_snapshot_store(path: Path = DEFAULT_STORE_PATH) -> Dict[str, List[dict]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_snapshot_store(store: Dict[str, List[dict]], path: Path = DEFAULT_STORE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False)


def record_snapshot(
    rows: List[dict], path: Path = DEFAULT_STORE_PATH, max_history: int = MAX_HISTORY_PER_PLAYER
) -> Dict[str, List[dict]]:
    """Schreibt fuer jeden Spieler in `rows` einen Eintrag fuer HEUTE (per
    UTC-Datum). Laeuft dieselbe Kalenderdatum-Eintragung mehrfach am Tag
    (Update-Zyklus alle ~2h), wird der heutige Eintrag aktualisiert statt
    dupliziert -- ein "taeglicher" Snapshot bleibt also wirklich hoechstens
    einer pro Tag, unabhaengig davon wie oft export_artifact laeuft."""
    store = load_snapshot_store(path)
    today = _today_str()

    for row in rows:
        pid = row.get("id")
        if pid is None:
            continue
        entry = {"date": today, **{field: row.get(field) for field in SNAPSHOT_FIELDS}}
        history = store.get(pid, [])
        if history and history[-1].get("date") == today:
            history[-1] = entry
        else:
            history.append(entry)
        store[pid] = history[-max_history:]

    save_snapshot_store(store, path)
    return store


def _mean(values: List[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def trend_stats(history: Optional[List[dict]]) -> dict:
    """Best-effort MW-Trend aus dem gespeicherten Verlauf eines einzelnen
    Spielers (chronologisch aufsteigend, wie in record_snapshot() abgelegt).
    Alle Felder sind None, solange nicht genug Historie vorliegt -- das ist
    der erwartete Cold-Start-Zustand direkt nach Einfuehrung dieses Features
    und keine Fehlfunktion (siehe Aufgabenstellung "Cold Start")."""
    result = {
        "change_3d": None, "change_3d_pct": None,
        "change_7d": None, "change_7d_pct": None,
        "acceleration": None, "samples": len(history) if history else 0,
    }
    if not history:
        return result

    market_values = [h.get("market_value") for h in history]

    def change_over(n: int):
        if len(market_values) <= n:
            return None, None
        latest = market_values[-1]
        past = market_values[-1 - n]
        if latest is None or past is None:
            return None, None
        change = latest - past
        pct = (change / past * 100.0) if past else None
        return change, pct

    result["change_3d"], result["change_3d_pct"] = change_over(3)
    result["change_7d"], result["change_7d_pct"] = change_over(7)

    deltas = []
    for prev, curr in zip(market_values, market_values[1:]):
        if prev is not None and curr is not None:
            deltas.append(curr - prev)
        else:
            deltas.append(None)

    recent = [d for d in deltas[-3:] if d is not None]
    earlier = [d for d in deltas[-6:-3] if d is not None]
    if recent and earlier:
        result["acceleration"] = _mean(recent) - _mean(earlier)

    return result
