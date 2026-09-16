"""Orchestriert das komplette Gebotsmodell zu einer einzigen Funktion
(compute_bids), die export_artifact.py pro Lauf einmal aufruft: taeglichen
Snapshot schreiben, neue echte Ligatransfers einlesen, Liga-Markt-Faktor und
Marktwertklassen/Rang-Tier-Statistik einmalig fuer alle Spieler berechnen,
dann je Spieler Attraktivitaet -> aehnliche Transfers -> Gebotsempfehlung.

Bewusst mit einem einzigen try/except um die GESAMTE Funktion (siehe
export_artifact.fetch_owned_player_ids fuer das gleiche Muster in diesem
Projekt): ein Fehler im Gebotsmodell (z.B. Liga-ID fehlt, Netzwerkfehler beim
Transfer-Feed, kaputte Konfigurationsdatei) darf niemals den Kernexport
(Spielerkartei ohne GEBOT-Spalte) verhindern -- dann bekommt jede Zeile
einfach kein "bid"-Feld."""
from pathlib import Path
from typing import Dict, Optional

from kickbase_tool.api.client import KickbaseClient
from kickbase_tool.bidding import calibration, pricing, scoring, similarity
from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.snapshot_store import DEFAULT_STORE_PATH, record_snapshot, trend_stats
from kickbase_tool.bidding.transfers import DEFAULT_TRANSFER_LOG_PATH, ingest_new_transfers
from kickbase_tool.config import Settings


def compute_bids(
    rows: list,
    client: KickbaseClient,
    settings: Settings,
    snapshot_path: Path = DEFAULT_STORE_PATH,
    transfer_log_path: Path = DEFAULT_TRANSFER_LOG_PATH,
) -> Dict[str, dict]:
    """Gibt eine Zuordnung player_id -> Gebotsempfehlung (siehe pricing.recommend_bid)
    zurueck. Bei jedem Fehler wird ein leeres Dict zurueckgegeben, statt eine
    Exception nach oben durchzureichen -- der Aufrufer fuegt dann einfach fuer
    keinen Spieler ein "bid"-Feld hinzu. `snapshot_path`/`transfer_log_path`
    sind ausschliesslich fuer Tests ueberschreibbar (siehe test_pipeline.py)."""
    try:
        return _compute_bids(rows, client, settings, snapshot_path, transfer_log_path)
    except Exception:
        return {}


def _compute_bids(
    rows: list, client: KickbaseClient, settings: Settings, snapshot_path: Path, transfer_log_path: Path
) -> Dict[str, dict]:
    config = load_bidding_config()

    rows_by_pid = {row["id"]: row for row in rows if row.get("id") is not None}

    snapshot_store = record_snapshot(rows, path=snapshot_path)
    transfer_log = ingest_new_transfers(rows_by_pid, client, settings, snapshot_store=snapshot_store, path=transfer_log_path)

    market_factor = calibration.overall_market_factor(transfer_log, config)
    class_tier_stats = calibration.market_stats_by_class_and_tier(transfer_log, config)

    results: Dict[str, dict] = {}
    for pid, row in rows_by_pid.items():
        history = snapshot_store.get(pid)
        trend = trend_stats(history)

        attractiveness_result = scoring.attractiveness(row, snapshot_history=history, trend=trend, config=config)
        similar_result = similarity.similar_transfers(row, transfer_log, config, target_trend=trend)
        tier_stats = calibration.lookup_class_tier_stats(
            class_tier_stats, row.get("market_value"), row.get("kauf_rank"), config
        )

        results[pid] = pricing.recommend_bid(
            row, attractiveness_result, similar_result, tier_stats, market_factor, config
        )

    return results
