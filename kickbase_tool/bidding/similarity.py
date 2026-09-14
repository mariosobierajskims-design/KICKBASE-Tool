"""Findet je Spieler die letzten (chronologisch juengsten) vergleichbaren
Ligatransfers und leitet daraus einen erwarteten Overpay + Confidence-
relevante Kennzahlen ab (siehe Aufgabenstellung "Aehnliche Transfers").

"Vergleichbar" ist auf ausdruecklichen Nutzerwunsch hart auf zwei Kriterien
reduziert: 1) Marktwert liegt innerhalb eines Fensters um den Marktwert des
Zielspielers, dessen Breite mit dem Marktwert waechst -- je niedriger der
Marktwert, desto enger das Fenster (ein 2-Mio.-Spieler soll nicht mit einem
4-Mio.-Spieler verglichen werden), je hoeher der Marktwert, desto weiter darf
der Vergleich auseinanderliegen (bei einem 30-Mio.-Spieler ist auch ein
deutlich teurerer/guenstigerer Transfer noch aussagekraeftig, siehe
similarity_mv_window_pct). 2) gleiche Position. Rang, Startchance, PKT/MIO und
MW-Trend beeinflussen NICHT mehr, ob ein Transfer als vergleichbar gilt --
diese fliessen weiterhin in den regelbasierten Attraktivitaets-Score
(scoring.py) ein, aber nicht mehr zusaetzlich in die Aehnlichkeitssuche
(fruehere gewichtete Distanz ueber alle Dimensionen ist entfallen).

Von allen so gefundenen Kandidaten zaehlen nur die zeitlich JUENGSTEN
`similar_transfers_max_k` (Default 10, "die letzten zehn vergleichbaren
Transfers") -- rein chronologisch sortiert, NICHT nach (Un-)Aehnlichkeit. Das
haelt das Modell aktuell (alte, laengst nicht mehr repraesentative Transfers
fallen automatisch aus dem Fenster) UND stabil (ein einzelner neuer
Ausreisser-Transfer ist nur einer von zehn Datenpunkten und kann das Ergebnis
nicht alleine kippen)."""
from datetime import datetime, timezone
from typing import Optional

from kickbase_tool.bidding.calibration import record_weight
from kickbase_tool.bidding.stats import (
    market_value_class_index,
    parse_iso_datetime,
    robust_weighted_stats,
)

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def market_value_window_pct(market_value: Optional[float], config: dict) -> Optional[float]:
    """Fensterbreite in Prozent des Marktwerts fuer die Marktwertklasse, in
    die `market_value` faellt (siehe similarity_mv_window_pct/Modul-Docstring)."""
    if market_value is None:
        return None
    windows = config.get("similarity_mv_window_pct")
    if not windows:
        return None
    idx = market_value_class_index(market_value, config["market_value_classes"])
    if idx is None:
        return None
    return windows[min(idx, len(windows) - 1)]


def is_comparable(target: dict, candidate: dict, config: dict) -> bool:
    """Hartes Kriterium (keine graduelle Distanz): Marktwert innerhalb des
    marktwertabhaengigen Fensters um den Zielmarktwert UND gleiche Position,
    falls beide Positionen bekannt sind (fehlende Positionsangabe disqualifiziert
    nicht, sie wird einfach nicht geprueft)."""
    target_mv = target.get("market_value")
    candidate_mv = candidate.get("market_value")
    if not target_mv or not candidate_mv or target_mv <= 0 or candidate_mv <= 0:
        return False

    window_pct = market_value_window_pct(target_mv, config)
    if window_pct is None:
        return False
    lower = target_mv * (1.0 - window_pct / 100.0)
    upper = target_mv * (1.0 + window_pct / 100.0)
    if candidate_mv < lower or candidate_mv > upper:
        return False

    target_pos, candidate_pos = target.get("position"), candidate.get("position")
    if target_pos and candidate_pos and target_pos != candidate_pos:
        return False

    return True


def similar_transfers(
    target_row: dict, transfer_log: list, config: dict, now: Optional[datetime] = None
) -> dict:
    max_k = config.get("similar_transfers_max_k", 10)
    candidates = [
        record
        for record in transfer_log
        if record.get("overpay_pct") is not None and is_comparable(target_row, record, config)
    ]

    # Rein chronologisch (juengste zuerst) statt nach Aehnlichkeit sortiert --
    # explizite Nutzervorgabe fuer Aktualitaet + Stabilitaet, siehe Modul-Docstring.
    candidates.sort(key=lambda r: parse_iso_datetime(r.get("dt")) or _EPOCH, reverse=True)
    top_k = candidates[:max_k]

    # Wie viele der herangezogenen Vergleichstransfers sind NICHT von der
    # Erstbefuellung betroffen (siehe transfers.py-Docstring: backfilled=True
    # heisst, Marktwert/Rang/etc. wurden mit den Werten von HEUTE statt vom
    # echten Transferzeitpunkt angereichert -- Look-ahead-Bias). Nur diese
    # "frischen" Treffer duerfen das regelbasierte Grundmodell in pricing.py
    # nennenswert verdraengen; siehe n_fresh dort.
    n_fresh = sum(1 for record in top_k if not record.get("backfilled"))

    target_mv = target_row.get("market_value")
    weighted_points = []
    neighbor_summaries = []
    for record in top_k:
        weight = record_weight(record, config, now=now)
        weighted_points.append((record["overpay_pct"], weight))
        record_mv = record.get("market_value")
        mv_diff_pct = (
            round(abs(record_mv - target_mv) / target_mv * 100.0, 1)
            if record_mv and target_mv
            else None
        )
        neighbor_summaries.append({
            "player_name": record.get("player_name"),
            "buyer": record.get("buyer"),
            "overpay_pct": record.get("overpay_pct"),
            "dt": record.get("dt"),
            "mv_diff_pct": mv_diff_pct,
            "backfilled": bool(record.get("backfilled")),
        })

    stats = robust_weighted_stats(weighted_points)
    return {
        "n": stats["n"],
        "n_considered": len(top_k),
        "n_fresh": n_fresh,
        "median_pct": stats["median"],
        "p25_pct": stats["p25"],
        "p75_pct": stats["p75"],
        "neighbors": neighbor_summaries[:5],
    }
