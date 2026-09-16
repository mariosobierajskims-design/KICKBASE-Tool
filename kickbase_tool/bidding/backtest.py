"""Look-ahead-freies Backtesting des Gebotsmodells gegen die echte
Transfer-Historie der Liga (siehe Aufgabenstellung Punkt 15/16/17).

Fuer jeden historischen Transfer wird simuliert, was das Modell VOR diesem
Transfer empfohlen haette -- ausschliesslich mit Daten, die zu diesem
Zeitpunkt bereits bekannt waren: alle STRENG FRUEHEREN Transfers desselben
Logs als Vergleichsbasis, `now` auf den Transferzeitpunkt selbst gesetzt
(statt auf heute), damit Aktualitaets-Gewichtung (decay_weight) und
Liga-Markt-Faktor (calibration.overall_market_factor) ebenfalls historisch
korrekt sind. Der zum Transferzeitpunkt bereits angereicherte Datensatz
(siehe transfers.py: market_value/kauf_rank/... zum Zeitpunkt des Kaufs, nicht
von heute) dient direkt als simuliertes Zielprofil -- eine erneute
Snapshot-Suche ist nicht noetig, das Feld ist schon historisch korrekt.

Bekannte Grenze (siehe Aufgabenstellung "Auktion vs. Marktwert"): Kickbase
liefert kein zweithoechstes Gebot, nur den tatsaechlichen Gewinnerpreis.
"Trefferquote" bedeutet hier daher IMMER "haette das empfohlene Gebot
(bid_upper) den beobachteten Gewinnerpreis erreicht/uebertroffen" -- eine
Naeherung fuer "haette den Spieler gewonnen", kein Beweis (der tatsaechlich
noetige Mindestpreis koennte niedriger gewesen sein, wenn es ein
Konkurrenzgebot unterhalb des Gewinnerpreises gab, das wir nicht sehen).

Aufrufbar per `python -m kickbase_tool.bidding.backtest`."""
from datetime import datetime
from typing import Dict, List, Optional

from kickbase_tool.bidding import calibration, pricing, scoring, similarity
from kickbase_tool.bidding.config import load_bidding_config
from kickbase_tool.bidding.stats import market_value_class_label, parse_iso_datetime
from kickbase_tool.bidding.transfers import DEFAULT_TRANSFER_LOG_PATH, load_transfer_log


def _simulate_one(target: dict, prior_log: List[dict], config: dict, now: Optional[datetime]) -> Optional[dict]:
    """Ein einzelner simulierter Modelllauf fuer `target` (ein historischer
    Transfer-Datensatz, siehe Modul-Docstring), ausschliesslich auf Basis von
    `prior_log` (alle STRENG frueheren Transfers). Keine Mehrtage-Trend-
    historie ist zu diesem vergangenen Zeitpunkt rekonstruierbar (dafuer
    muesste `snapshot_store` selbst zeitgereist werden) -- `trend`/
    `target_trend` bleiben leer, ein dokumentierter, bewusster
    Genauigkeitsverlust nur fuer das Backtesting, nicht fuer den Live-Betrieb
    (siehe pipeline.py, das echte snapshot_store-Historie nutzt)."""
    if target.get("market_value") is None or target.get("transfer_price") is None:
        return None
    attractiveness_result = scoring.attractiveness(target, snapshot_history=None, trend={}, config=config)
    similar_result = similarity.similar_transfers(target, prior_log, config, target_trend=None, now=now)
    market_factor = calibration.overall_market_factor(prior_log, config, now=now)
    class_tier_stats = calibration.market_stats_by_class_and_tier(prior_log, config, now=now)
    tier_stats = calibration.lookup_class_tier_stats(
        class_tier_stats, target.get("market_value"), target.get("kauf_rank"), config
    )
    bid = pricing.recommend_bid(target, attractiveness_result, similar_result, tier_stats, market_factor, config)
    return {"attractiveness": attractiveness_result, "bid": bid}


def _summarize(groups: Dict[str, List[dict]]) -> Dict[str, dict]:
    summary = {}
    for key, group_rows in groups.items():
        n = len(group_rows)
        if not n:
            summary[key] = {"n": 0, "hit_rate": None, "avg_delta_pct": None}
            continue
        hits = sum(1 for r in group_rows if r["would_have_won"])
        avg_delta = sum(r["delta_pct"] for r in group_rows) / n
        summary[key] = {"n": n, "hit_rate": round(hits / n, 3), "avg_delta_pct": round(avg_delta, 1)}
    return summary


def run_backtest(transfer_log: List[dict], config: Optional[dict] = None) -> dict:
    """Fuehrt das Backtesting ueber den gesamten (chronologisch sortierten)
    `transfer_log` durch. Gibt Trefferquote + durchschnittliche Abweichung
    (empfohlenes Gebot vs. tatsaechlicher Gewinnerpreis) auf, aufgeschluesselt
    nach Attraktivitaetskategorie UND Marktwertklasse (Aufgabenstellung Punkt
    15), plus die rohen Einzelergebnisse (`rows`) fuer eigene Auswertungen
    (z.B. Fabio-Silva-/Dinkci-Kontrollfaelle, siehe Punkt 16/17)."""
    config = config or load_bidding_config()
    ordered = sorted(
        (r for r in transfer_log if r.get("dt") and r.get("overpay_pct") is not None),
        key=lambda r: r["dt"],
    )

    per_category: Dict[str, List[dict]] = {}
    per_mv_class: Dict[str, List[dict]] = {}
    rows: List[dict] = []

    for i, record in enumerate(ordered):
        now = parse_iso_datetime(record["dt"])
        prior_log = ordered[:i]  # streng FRUEHER als dieser Transfer -- kein Look-ahead

        simulation = _simulate_one(record, prior_log, config, now=now)
        if simulation is None:
            continue
        bid = simulation["bid"]
        if bid["no_bid"] or bid["bid_upper"] is None:
            continue  # "kein Gebot" laesst sich nicht sinnvoll als Trefferquote werten

        actual_price = record["transfer_price"]
        delta_pct = (bid["bid_upper"] - actual_price) / actual_price * 100.0
        row = {
            "player_id": record.get("player_id"),
            "player_name": record.get("player_name"),
            "dt": record["dt"],
            "category": bid["category"],
            "market_value": record.get("market_value"),
            "actual_price": actual_price,
            "recommended_bid_upper": bid["bid_upper"],
            "would_have_won": bid["bid_upper"] >= actual_price,
            "delta_pct": round(delta_pct, 1),
            "n_similar": (bid.get("similar_transfers") or {}).get("n", 0),
        }
        rows.append(row)
        per_category.setdefault(bid["category"], []).append(row)
        mv_class = market_value_class_label(record.get("market_value"), config["market_value_classes"]) or "unbekannt"
        per_mv_class.setdefault(mv_class, []).append(row)

    return {
        "n_total": len(rows),
        "n_skipped_no_bid_or_missing_data": len(ordered) - len(rows),
        "by_category": _summarize(per_category),
        "by_market_value_class": _summarize(per_mv_class),
        "rows": rows,
    }


def _print_report(result: dict) -> None:
    print(f"Backtest ueber {result['n_total']} historische Transfers "
          f"({result['n_skipped_no_bid_or_missing_data']} ohne Gebot/Daten uebersprungen)\n")
    print("Nach Attraktivitaetskategorie:")
    for category, stats in result["by_category"].items():
        print(f"  {category:>16}: n={stats['n']:3d}  Trefferquote={stats['hit_rate']}  Ø-Abweichung={stats['avg_delta_pct']}%")
    print("\nNach Marktwertklasse:")
    for mv_class, stats in result["by_market_value_class"].items():
        print(f"  {mv_class:>10}: n={stats['n']:3d}  Trefferquote={stats['hit_rate']}  Ø-Abweichung={stats['avg_delta_pct']}%")


def main() -> None:
    transfer_log = load_transfer_log(DEFAULT_TRANSFER_LOG_PATH)
    result = run_backtest(transfer_log)
    _print_report(result)


if __name__ == "__main__":
    main()
