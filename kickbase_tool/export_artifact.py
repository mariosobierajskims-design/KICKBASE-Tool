"""Baut eine flache JSON-Liste aller Spieler + Kennzahlen + Ranking-Scores +
"eigenes Team"-Flag, zum Einspielen in die Datenbank eines veroeffentlichten
Artifacts (siehe Skill artifact-capabilities, capability "db").

Dieses Skript selbst schreibt NICHT in die Artifact-Datenbank (das kann nur
der Artifact-Tool-Aufruf von Claude aus), es bereitet nur die Rohdaten aus
der Kickbase-API dafuer auf.

Nutzung: python -m kickbase_tool.export_artifact [--out artifact_data/players.json]
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from kickbase_tool.api.client import KickbaseAPIError, KickbaseClient
from kickbase_tool.config import authenticate, load_settings
from kickbase_tool.data.models import POSITION_LABELS
from kickbase_tool.data.repository import fetch_owned_player_ids, load_dataset
from kickbase_tool.metrics.calculations import compute_all_metrics
from kickbase_tool.ranking.scoring import compute_all_rankings


def build_rows(argv=None) -> list:
    settings = load_settings()
    client = KickbaseClient(request_delay_seconds=settings.request_delay_seconds)
    authenticate(client, settings)

    dataset = load_dataset(client, settings, force_refresh=False)
    metrics_by_id = compute_all_metrics(dataset)
    rankings = compute_all_rankings(metrics_by_id)

    try:
        owned_ids = fetch_owned_player_ids(client, settings)
    except KickbaseAPIError:
        owned_ids = set()

    team_names = {t.team_id: t.team_name for t in dataset.table}

    rank_position = {
        key: {pid: i + 1 for i, pid in enumerate(result.order)} for key, result in rankings.items()
    }

    rows = []
    for pid, pm in metrics_by_id.items():
        p = pm.player
        rows.append({
            "id": pid,
            "name": p.name,
            "position": POSITION_LABELS.get(p.position, "?"),
            "team_id": p.team_id,
            "team_name": team_names.get(p.team_id, p.team_id or "?"),
            "status": p.status_text,
            "unavailable": p.is_unavailable,
            "owned": pid in owned_ids,
            "season_avg": pm.season_average,
            "recent_avg": pm.recent_form.average,
            "recent_min": pm.recent_form.minimum,
            "recent_max": pm.recent_form.maximum,
            "market_value": pm.market_value,
            "points_per_value": pm.points_per_market_value,
            "team_form": pm.team_form,
            "opponent_form": pm.opponent_form,
            "table_position_diff": pm.table_position_diff,
            "venue_form_diff": pm.venue_form_diff,
            "next_opponent_name": pm.next_opponent_name,
            "next_match_is_home": pm.next_match_is_home,
            "upcoming_opponents": [
                {"team_name": o["team_name"], "position": o["position"], "home": o["home"]}
                for o in pm.upcoming_opponents
            ],
            "remaining_schedule_difficulty": pm.remaining_schedule_difficulty,
            "team_momentum": pm.team_momentum,
            "opponent_momentum": pm.opponent_momentum,
            "goals": pm.goals,
            "assists": pm.assists,
            "clean_sheets": pm.clean_sheets,
            "aufstellung_score": rankings["aufstellung"].scores.get(pid),
            "aufstellung_rank": rank_position["aufstellung"].get(pid),
            "kauf_score": rankings["kauf"].scores.get(pid),
            "kauf_rank": rank_position["kauf"].get(pid),
            "verkauf_score": rankings["verkauf"].scores.get(pid),
            "verkauf_rank": rank_position["verkauf"].get(pid),
        })
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export der Spieler-Datenbank fuer das Artifact")
    parser.add_argument("--out", type=str, default="artifact_data/players.json")
    args = parser.parse_args(argv)

    rows = build_rows()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)

    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "player_count": len(rows),
        "owned_count": sum(1 for r in rows if r["owned"]),
    }
    meta_path = out_path.with_name("meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f"{len(rows)} Spieler geschrieben nach {out_path}")
    print(f"Meta geschrieben nach {meta_path}: {meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
