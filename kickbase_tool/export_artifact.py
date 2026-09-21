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
from kickbase_tool.bidding.pipeline import compute_bids
from kickbase_tool.config import authenticate, load_settings
from kickbase_tool.data.models import POSITION_LABELS
from kickbase_tool.data.repository import (
    fetch_all_rostered_player_ids,
    fetch_cash_balance,
    fetch_market_players,
    fetch_owned_player_ids,
    load_dataset,
)
from kickbase_tool.images import fetch_player_thumbnail, fetch_team_logo
from kickbase_tool.metrics.calculations import compute_all_metrics
from kickbase_tool.ranking.scoring import compute_all_rankings


def build_rows(argv=None) -> tuple:
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

    # Kontostand fuers "Beste 11"-Budget im Artifact (siehe Aufgabenstellung
    # "BUDGET: Gesamtbudget = aktueller Kontostand + Marktwert aller meiner
    # eigenen Spieler") -- wie owned_ids oben defensiv: jeder Fehler (fehlende
    # KICKBASE_LEAGUE_ID, Netzwerkfehler) degradiert zu None statt den
    # Kernexport zu gefaehrden; das Frontend zeigt dann "Budget nicht
    # verfuegbar" statt zu rechnen.
    try:
        cash_balance = fetch_cash_balance(client, settings)
    except KickbaseAPIError:
        cash_balance = None

    # "Markt" (Nutzer-Korrektur): jeder Spieler, der NICHT bei einem anderen
    # Liga-Mitglied im Kader steht, PLUS die von Kollegen explizit
    # angebotenen -- nicht nur der kleine rotierende Ausschnitt aus
    # fetch_market_players. rostered_ids = Kader ALLER Manager (eigener
    # eingeschlossen); market_prices = Angebotspreise (freie Spieler + von
    # Kollegen gelistete). Gleiches defensives Degradieren wie
    # owned_ids/cash_balance oben -- bei Fehlschlag lieber ein leerer Pool
    # als ein kaputter Kernexport.
    try:
        rostered_ids = fetch_all_rostered_player_ids(client, settings)
    except KickbaseAPIError:
        rostered_ids = None  # unbekannt -- siehe Fallback unten, NICHT als "niemand hat ihn" werten
    try:
        market_prices = fetch_market_players(client, settings)
    except KickbaseAPIError:
        market_prices = {}

    team_names = {t.team_id: t.team_name for t in dataset.table}

    rank_position = {
        key: {pid: i + 1 for i, pid in enumerate(result.order)} for key, result in rankings.items()
    }

    # Eigener Rang nur fuer den Punkteschnitt der letzten 5 Spiele (fuers
    # "Beste 11"-Scoring im Artifact: Mix aus Kauf-Rang, Aufstellungs-Rang und
    # diesem Rang -- siehe besteElfScoreOf) -- kein Eintrag in `rankings`
    # oben, da diese Rangfolge nirgendwo sonst gebraucht wird. Fehlender
    # Formwert (noch keine Einsaetze) landet ganz hinten, nicht neutral in
    # der Mitte, da "keine Punkte" sportlich der schlechteste Fall ist.
    recent_avg_order = sorted(
        metrics_by_id.keys(),
        key=lambda pid: (
            metrics_by_id[pid].recent_form.average
            if metrics_by_id[pid].recent_form.average is not None
            else float("-inf")
        ),
        reverse=True,
    )
    recent_form_rank = {pid: i + 1 for i, pid in enumerate(recent_avg_order)}

    rows = []
    for pid, pm in metrics_by_id.items():
        p = pm.player

        # on_market/market_price (Nutzer-Korrektur): eigene Spieler brauchen
        # beides nicht (siehe "owned" + Marktwert). Ein Spieler, der bei
        # KEINEM Manager im Kader steht, ist ein freier Spieler -- sofort zum
        # Marktwert kaufbar, auch wenn er gerade nicht im rotierenden
        # Marktausschnitt (market_prices) auftaucht. Ein Spieler bei einem
        # ANDEREN Manager ist nur kaufbar, wenn dieser ihn explizit gelistet
        # hat (dann steht er in market_prices, zum dort gesetzten Preis).
        if pid in owned_ids:
            is_on_market = False
            market_price = None
        elif rostered_ids is None:
            # Kader-Abfrage fehlgeschlagen: sicherer Fallback ist der enge,
            # aber garantiert korrekte Marktausschnitt statt faelschlich
            # ALLE Nicht-Eigenen als frei zu behandeln.
            is_on_market = pid in market_prices
            market_price = market_prices.get(pid)
        elif pid not in rostered_ids:
            is_on_market = True
            market_price = market_prices.get(pid, pm.market_value)
        else:
            is_on_market = pid in market_prices
            market_price = market_prices.get(pid)

        rows.append({
            "id": pid,
            "name": p.name,
            "position": POSITION_LABELS.get(p.position, "?"),
            "team_id": p.team_id,
            "team_name": team_names.get(p.team_id, p.team_id or "?"),
            "image_data": fetch_player_thumbnail(p.image_url),
            "team_logo_data": fetch_team_logo(p.team_logo_url),
            "status": p.status_text,
            "unavailable": p.is_unavailable,
            "owned": pid in owned_ids,
            "on_market": is_on_market,
            "market_price": market_price,
            "season_avg": pm.season_average,
            "recent_form_rank": recent_form_rank.get(pid),
            "recent_avg": pm.recent_form.average,
            "recent_min": pm.recent_form.minimum,
            "recent_max": pm.recent_form.maximum,
            "market_value": pm.market_value,
            "points_per_value": pm.points_per_market_value,
            "start_probability": pm.start_probability,
            "market_value_change_day": pm.market_value_change_day,
            "team_form": pm.team_form,
            "opponent_form": pm.opponent_form,
            "table_position_diff": pm.table_position_diff,
            "own_venue_rank": pm.own_venue_rank,
            "opponent_venue_rank": pm.opponent_venue_rank,
            "venue_rank_diff": pm.venue_rank_diff,
            "next_opponent_name": pm.next_opponent_name,
            "next_match_is_home": pm.next_match_is_home,
            "upcoming_opponents": [
                {"team_name": o["team_name"], "position": o["position"], "home": o["home"]}
                for o in pm.upcoming_opponents
            ],
            "remaining_schedule_difficulty": pm.remaining_schedule_difficulty,
            "opponent_remaining_schedule_difficulty": pm.opponent_remaining_schedule_difficulty,
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

    # Gebotsmodell (kickbase_tool/bidding/): eigenkapselt und defensiv --
    # compute_bids() faengt jeden eigenen Fehler ab und liefert dann {} statt
    # den Kernexport zu gefaehrden (siehe fetch_owned_player_ids oben fuer das
    # gleiche Muster in diesem Modul).
    bids_by_pid = compute_bids(rows, client, settings)
    for row in rows:
        row["bid"] = bids_by_pid.get(row["id"])

    return rows, cash_balance


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export der Spieler-Datenbank fuer das Artifact")
    parser.add_argument("--out", type=str, default="artifact_data/players.json")
    args = parser.parse_args(argv)

    rows, cash_balance = build_rows()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)

    meta = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "player_count": len(rows),
        "owned_count": sum(1 for r in rows if r["owned"]),
        "cash_balance": cash_balance,
    }
    meta_path = out_path.with_name("meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f"{len(rows)} Spieler geschrieben nach {out_path}")
    print(f"Meta geschrieben nach {meta_path}: {meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
