import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List

from tabulate import tabulate

from kickbase_tool.api.client import KickbaseAPIError, KickbaseClient
from kickbase_tool.config import authenticate, load_settings
from kickbase_tool.data.models import POSITION_LABELS
from kickbase_tool.data.repository import load_dataset
from kickbase_tool.metrics.calculations import PlayerMetrics, compute_all_metrics
from kickbase_tool.ranking.scoring import DEFAULT_WEIGHTS_PATH, compute_all_rankings

RANKING_TITLES = {
    "aufstellung": "Aufstellung (aktuelle Spieltag-Performance)",
    "kauf": "Kauf-Empfehlung",
    "verkauf": "Verkaufs-Kandidaten",
}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kickbase Spieleranalyse")
    parser.add_argument("--top", type=int, default=20, help="Anzahl Spieler pro Ranking in der Konsolen-Ausgabe")
    parser.add_argument("--refresh", action="store_true", help="Cache ignorieren, alle Daten neu von Kickbase laden")
    parser.add_argument("--csv-out", type=str, default=None, help="Verzeichnis fuer den vollstaendigen CSV-Export je Ranking")
    parser.add_argument("--weights", type=str, default=None, help="Pfad zu einer eigenen weights.yaml")
    parser.add_argument(
        "--position", choices=["TW", "ABW", "MF", "ST"], default=None, help="Nur eine Position anzeigen"
    )
    return parser.parse_args(argv)


def _position_matches(metrics: PlayerMetrics, label: str) -> bool:
    pos = metrics.player.position
    return POSITION_LABELS.get(pos) == label


def _row_for(pid: str, metrics_by_id: Dict[str, PlayerMetrics], score: float, rank_index: int) -> list:
    pm = metrics_by_id[pid]
    p = pm.player
    return [
        rank_index,
        p.name,
        POSITION_LABELS.get(p.position, "?"),
        round(score, 2),
        round(pm.season_average, 1) if pm.season_average is not None else "-",
        round(pm.recent_form.average, 1) if pm.recent_form.average is not None else "-",
        int(pm.market_value) if pm.market_value is not None else "-",
    ]


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_settings()

    client = KickbaseClient(request_delay_seconds=settings.request_delay_seconds)
    try:
        authenticate(client, settings)
    except KickbaseAPIError as exc:
        print(f"Login fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    dataset = load_dataset(client, settings, force_refresh=args.refresh)
    if not dataset.players:
        print("Keine Spieler geladen -- Antwortformat der Kickbase-API weicht vermutlich vom erwarteten Schema ab.", file=sys.stderr)
        print("Siehe README Abschnitt 'Feldnamen kalibrieren'.", file=sys.stderr)
        return 1

    metrics_by_id = compute_all_metrics(dataset)

    unavailable = [pm.player.name for pm in metrics_by_id.values() if pm.player.is_unavailable]
    if unavailable:
        print(f"{len(unavailable)} verletzte/gesperrte/nicht verfuegbare Spieler ausgeschlossen: "
              f"{', '.join(sorted(unavailable)[:10])}{' ...' if len(unavailable) > 10 else ''}")

    weights_path = Path(args.weights) if args.weights else DEFAULT_WEIGHTS_PATH
    rankings = compute_all_rankings(metrics_by_id, weights_path=weights_path)

    for key, result in rankings.items():
        order = result.order
        if args.position:
            order = [pid for pid in order if _position_matches(metrics_by_id[pid], args.position)]

        print(f"\n=== {RANKING_TITLES[key]} ===")
        headers = ["#", "Spieler", "Pos", "Score", "Saison-Ø", "Letzte-5-Ø", "Marktwert"]
        rows = [
            _row_for(pid, metrics_by_id, result.scores[pid], i + 1)
            for i, pid in enumerate(order[: args.top])
        ]
        print(tabulate(rows, headers=headers))

        if args.csv_out:
            _export_csv(Path(args.csv_out), key, order, metrics_by_id, result.scores)

    return 0


def _export_csv(out_dir: Path, ranking_key: str, order: List[str], metrics_by_id: Dict[str, PlayerMetrics], scores: Dict[str, float]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ranking_key}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rang", "spieler", "position", "team_id", "score",
            "saison_avg", "letzte5_avg", "letzte5_min", "letzte5_max", "letzte5_min_max_avg",
            "marktwert", "punkte_pro_marktwert", "team_form", "gegner_form",
            "tabellenplatz_diff", "venue_form_diff", "tore", "vorlagen", "zu_null", "status",
        ])
        for i, pid in enumerate(order):
            pm = metrics_by_id[pid]
            p = pm.player
            writer.writerow([
                i + 1, p.name, POSITION_LABELS.get(p.position, "?"), p.team_id, round(scores[pid], 3),
                pm.season_average, pm.recent_form.average, pm.recent_form.minimum, pm.recent_form.maximum,
                pm.recent_form.min_max_average, pm.market_value, pm.points_per_market_value,
                pm.team_form, pm.opponent_form, pm.table_position_diff, pm.venue_form_diff,
                pm.goals, pm.assists, pm.clean_sheets, p.status_text,
            ])
    print(f"CSV geschrieben: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
