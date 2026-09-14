"""Findet je Spieler die aehnlichsten historischen Ligatransfers (gewichtete
Distanz ueber Marktwert, Rang, Startchance, PKT/MIO, MW-Trend, Position) und
leitet daraus einen erwarteten Overpay + Confidence-relevante Kennzahlen ab
(siehe Aufgabenstellung "Aehnliche Transfers").

Live-Spielerzeilen (export_artifact.build_rows) und angereicherte Transfer-
Records (transfers.py) tragen absichtlich dieselben Feldnamen fuer die hier
verglichenen Groessen (market_value, kauf_rank, start_probability,
points_per_value, market_value_change_day, position) -- ein Feature-Vektor
reicht fuer beide Seiten."""
import math
from datetime import datetime
from typing import Optional

from kickbase_tool.bidding.calibration import record_weight
from kickbase_tool.bidding.scoring import rank_tier_index
from kickbase_tool.bidding.stats import robust_weighted_stats

MAX_DISTANCE = 1.0  # Transfers jenseits dieser gewichteten Distanz gelten als nicht mehr vergleichbar.


def _market_value_trend_pct(row: dict) -> Optional[float]:
    mv = row.get("market_value")
    change = row.get("market_value_change_day")
    if not mv or change is None:
        return None
    return (change / mv) * 100.0


def _dim_distance(a, b, scale: float, cap: float = 1.0) -> Optional[float]:
    if a is None or b is None:
        return None
    return min(cap, abs(a - b) / scale) if scale else min(cap, abs(a - b))


def weighted_distance(target: dict, candidate: dict, config: dict) -> Optional[float]:
    weights = config["similarity_weights"]
    parts = []

    mv_a, mv_b = target.get("market_value"), candidate.get("market_value")
    if mv_a and mv_b and mv_a > 0 and mv_b > 0:
        dist = min(1.0, abs(math.log(mv_a) - math.log(mv_b)) / math.log(2))
        parts.append((dist, weights["market_value_log"]))

    tier_a = rank_tier_index(target.get("kauf_rank"), config)
    tier_b = rank_tier_index(candidate.get("kauf_rank"), config)
    if tier_a is not None and tier_b is not None:
        parts.append((abs(tier_a - tier_b) / 4.0, weights["rank_tier"]))

    sp_a, sp_b = target.get("start_probability"), candidate.get("start_probability")
    if sp_a is not None and sp_b is not None:
        parts.append((abs(sp_a - sp_b) / 4.0, weights["start_probability"]))

    ppm_a = target.get("points_per_value")
    ppm_b = candidate.get("points_per_value")
    ppm_a = ppm_a * 1_000_000 if ppm_a is not None else None
    ppm_b = ppm_b * 1_000_000 if ppm_b is not None else None
    dist = _dim_distance(ppm_a, ppm_b, scale=5.0)
    if dist is not None:
        parts.append((dist, weights["ppm"]))

    trend_a, trend_b = _market_value_trend_pct(target), _market_value_trend_pct(candidate)
    dist = _dim_distance(trend_a, trend_b, scale=10.0)
    if dist is not None:
        parts.append((dist, weights["market_value_trend_pct"]))

    pos_a, pos_b = target.get("position"), candidate.get("position")
    if pos_a and pos_b:
        parts.append((0.0 if pos_a == pos_b else 1.0, weights["position"]))

    if not parts:
        return None
    total_weight = sum(w for _, w in parts)
    if total_weight <= 0:
        return None
    return sum(d * w for d, w in parts) / total_weight


def similar_transfers(
    target_row: dict, transfer_log: list, config: dict, now: Optional[datetime] = None
) -> dict:
    candidates = []
    for record in transfer_log:
        if record.get("overpay_pct") is None:
            continue
        distance = weighted_distance(target_row, record, config)
        if distance is None or distance > MAX_DISTANCE:
            continue
        candidates.append((record, distance))

    candidates.sort(key=lambda rd: rd[1])
    top_k = candidates[: config["similar_transfers_max_k"]]

    weighted_points = []
    neighbor_summaries = []
    for record, distance in top_k:
        weight = record_weight(record, config, now=now) * max(0.15, 1.0 - distance)
        weighted_points.append((record["overpay_pct"], weight))
        neighbor_summaries.append({
            "player_name": record.get("player_name"),
            "buyer": record.get("buyer"),
            "overpay_pct": record.get("overpay_pct"),
            "dt": record.get("dt"),
            "distance": round(distance, 3),
            "backfilled": bool(record.get("backfilled")),
        })

    stats = robust_weighted_stats(weighted_points)
    return {
        "n": stats["n"],
        "n_considered": len(top_k),
        "median_pct": stats["median"],
        "p25_pct": stats["p25"],
        "p75_pct": stats["p75"],
        "neighbors": neighbor_summaries[:5],
    }
