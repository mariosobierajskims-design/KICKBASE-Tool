"""Robuste Liga-Marktstatistik aus dem Transfer-Log (transfers.py): wie hoch
ist der Overpay aktuell realistisch je Marktwertklasse und Attraktivitaets-Tier,
und wird die Liga insgesamt gerade aggressiver oder zurueckhaltender? Beides
speist pricing.py -- KEINE festen Prozentsaetze, sondern laufend aus echten
Transfers abgeleitete Werte (siehe Aufgabenstellung "keine starren Prozentwerte").
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from kickbase_tool.bidding.scoring import rank_tier_index
from kickbase_tool.bidding.stats import (
    days_since,
    market_value_class_index,
    recency_weight,
    robust_weighted_stats,
)


def record_weight(record: dict, config: dict, now: Optional[datetime] = None) -> float:
    days_ago = days_since(record.get("dt"), now)
    weight = recency_weight(days_ago, config["recency_weight_days"])
    if record.get("backfilled"):
        weight *= config.get("backfilled_weight_factor", 1.0)
    return weight


def _weighted_overpay_points(records: List[dict], config: dict, now: Optional[datetime] = None) -> List[Tuple[float, float]]:
    points = []
    for r in records:
        overpay_pct = r.get("overpay_pct")
        if overpay_pct is None:
            continue
        points.append((overpay_pct, record_weight(r, config, now=now)))
    return points


def overall_market_factor(transfer_log: List[dict], config: dict, now: Optional[datetime] = None) -> dict:
    """Liga-weiter Marktfaktor: vergleicht den Overpay der letzten 7 Tage mit
    dem Overpay-Niveau ueber den gesamten geloggten Zeitraum, um zu erkennen,
    ob die Liga aktuell aggressiver oder ruhiger als "normal" bietet (siehe
    Aufgabenstellung: "Wenn die Liga ploetzlich ruhiger wird ... soll die
    Empfehlung sinken")."""
    now = now or datetime.now(timezone.utc)
    all_points = _weighted_overpay_points(transfer_log, config, now=now)
    all_stats = robust_weighted_stats(all_points)

    recent_records = [r for r in transfer_log if (days_since(r.get("dt"), now) or 999) <= 7]
    recent_points = _weighted_overpay_points(recent_records, config, now=now)
    recent_stats = robust_weighted_stats(recent_points)

    cap = config.get("market_factor_max_shift_pct", 4.0)
    shift = 0.0
    if all_stats["median"] is not None and recent_stats["median"] is not None and recent_stats["n"] >= 3:
        shift = recent_stats["median"] - all_stats["median"]
        shift = max(-cap, min(cap, shift))

    if shift > cap * 0.3:
        label = "aktuell aggressiv"
    elif shift < -cap * 0.3:
        label = "aktuell zurueckhaltend"
    else:
        label = "neutral"

    return {
        "overall_median_pct": all_stats["median"],
        "overall_n": all_stats["n"],
        "recent_median_pct": recent_stats["median"],
        "recent_n": recent_stats["n"],
        "shift_pct": shift,
        "label": label,
    }


def market_stats_by_class_and_tier(
    transfer_log: List[dict], config: dict, now: Optional[datetime] = None
) -> Dict[Tuple[Optional[int], Optional[int]], dict]:
    """Segmentiert den Transfer-Log nach (Marktwertklasse, Rang-Tier) und
    berechnet je Segment robuste Overpay-Statistik. Rang-Tier wird aus dem im
    Datensatz gespeicherten kauf_rank ZUM ZEITPUNKT DES TRANSFERS abgeleitet
    (nicht aus dem heutigen Rang) -- siehe transfers.py fuer die
    Anreicherung. Segmente mit zu wenigen Punkten liefern n=0 statt falscher
    Praezision."""
    bounds = config["market_value_classes"]
    buckets: Dict[Tuple[Optional[int], Optional[int]], List[dict]] = {}
    for record in transfer_log:
        key = (
            market_value_class_index(record.get("market_value"), bounds),
            rank_tier_index(record.get("kauf_rank"), config),
        )
        buckets.setdefault(key, []).append(record)

    return {
        key: robust_weighted_stats(_weighted_overpay_points(records, config, now=now))
        for key, records in buckets.items()
    }


def lookup_class_tier_stats(
    stats_by_key: Dict[Tuple[Optional[int], Optional[int]], dict],
    market_value: Optional[float],
    kauf_rank: Optional[float],
    config: dict,
) -> Optional[dict]:
    bounds = config["market_value_classes"]
    key = (market_value_class_index(market_value, bounds), rank_tier_index(kauf_rank, config))
    stats = stats_by_key.get(key)
    if stats and stats.get("n", 0) > 0:
        return stats
    return None
