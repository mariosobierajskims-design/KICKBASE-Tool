"""Diagnose-Hilfsmittel: speichert rohe JSON-Antworten der wichtigsten Endpunkte
lokal ab. Nuetzlich, falls die automatische Feldnamen-Erkennung (siehe
kickbase_tool.util.pick / kickbase_tool.data.normalize) bei deiner echten
API-Antwort daneben liegt -- die gespeicherten Dateien zeigen dir die exakten
Feldnamen, die du dann in kickbase_tool/data/normalize.py als zusaetzlichen
Alias ergaenzen kannst.

Nutzung: python -m kickbase_tool.dump_raw [--out-dir raw_samples]
"""
import argparse
import json
from pathlib import Path

from kickbase_tool.api import endpoints
from kickbase_tool.api.client import KickbaseClient
from kickbase_tool.config import authenticate, load_settings
from kickbase_tool.data.normalize import extract_player_list


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kickbase Rohdaten-Dump zur Feldnamen-Kalibrierung")
    parser.add_argument("--out-dir", type=str, default="raw_samples")
    args = parser.parse_args(argv)

    settings = load_settings()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = KickbaseClient(request_delay_seconds=settings.request_delay_seconds)

    def dump(name: str, data) -> None:
        path = out_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"geschrieben: {path}")

    authenticate(client, settings)
    print("Login/Token OK.")

    if settings.league_id:
        squad = client.get(endpoints.LEAGUE_SQUAD.format(league_id=settings.league_id))
        dump("league_squad", squad)

        market = client.get(endpoints.LEAGUE_MARKET.format(league_id=settings.league_id))
        dump("league_market", market)
    else:
        print("KICKBASE_LEAGUE_ID nicht gesetzt -- ueberspringe eigener Kader/Markt (nicht fuer die Kern-Datenbank noetig).")

    players = client.get(endpoints.COMPETITION_PLAYERS.format(competition_id=settings.competition_id))
    dump("competition_players", players)

    player_list = extract_player_list(players)
    if player_list:
        first_id = player_list[0].get("id") or player_list[0].get("i")
        if first_id is not None:
            perf = client.get(
                endpoints.COMPETITION_PLAYER_PERFORMANCE.format(
                    competition_id=settings.competition_id, player_id=first_id
                )
            )
            dump(f"player_performance_{first_id}", perf)

    table = client.get(endpoints.COMPETITION_TABLE.format(competition_id=settings.competition_id))
    dump("competition_table", table)

    matchdays = client.get(endpoints.COMPETITION_MATCHDAYS.format(competition_id=settings.competition_id))
    dump("competition_matchdays", matchdays)

    if settings.league_id:
        ranking = client.get(endpoints.LEAGUE_RANKING.format(league_id=settings.league_id))
        dump("league_ranking", ranking)

    print(f"\nFertig. Rohdaten liegen unter {out_dir}/ -- damit lassen sich die Feldnamen in "
          f"kickbase_tool/data/normalize.py bei Bedarf praezisieren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
