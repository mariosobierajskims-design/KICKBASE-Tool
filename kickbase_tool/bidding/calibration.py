"""Robuste Liga-Marktstatistik aus dem Transfer-Log (transfers.py): wie hoch
ist der Overpay aktuell realistisch je Marktwertklasse und Attraktivitaets-Tier,
und wird die Liga insgesamt gerade aggressiver oder zurueckhaltender? Beides
speist pricing.py -- KEINE festen Prozentsaetze, sondern laufend aus echten
Transfers abgeleitete Werte (siehe Aufgabenstellung "keine starren Prozentwerte").

Ausserdem: die zentrale Zuordnung Attraktivitaetskategorie -> Ziel-Perzentil
der (similarity- und zeitgewichteten) historischen Overpay-Verteilung
(`category_target_value`) -- ersetzt den fruehen linearen Cold-Start-Blend in
pricing.py (Aufgabenstellung Punkt 11: "Attraktivitaetskategorie bestimmt das
Zielperzentil, nicht den Median")."""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from kickbase_tool.bidding.scoring import rank_tier_index
from kickbase_tool.bidding.stats import (
    days_since,
    decay_weight,
    market_value_class_index,
    robust_weighted_stats,
    target_percentile_value,
)


def record_weight(record: dict, config: dict, now: Optional[datetime] = None) -> float:
    """Gesamtgewicht eines historischen Transfers fuer jede Statistik in
    diesem Modul UND in similarity.py: Aktualitaet (Exponential-Decay,
    `recency_half_life_days`) x Backfilled-Abschlag x Wettbewerbssignal.
    Letzteres: Kickbase liefert keine Gebotshoehen, nur die Anzahl
    abgegebener Gebote ("coc"/bid_count) -- ein Transfer OHNE jedes
    Konkurrenzgebot (`bid_count == 0`) ist eher ein unkontrollierter
    Angebotspreis als ein belastbares Wettbewerbsergebnis und zaehlt daher
    mit reduziertem Gewicht (siehe Aufgabenstellung "Auktion vs. Marktwert":
    ein echtes zweithoechstes Gebot ist mit den verfuegbaren Daten nicht
    rekonstruierbar, das ist die naechstbeste verfuegbare Naeherung)."""
    days_ago = days_since(record.get("dt"), now)
    weight = decay_weight(days_ago, config.get("recency_half_life_days", 30.0))
    if record.get("backfilled"):
        weight *= config.get("backfilled_weight_factor", 1.0)
    if record.get("bid_count") == 0:
        weight *= config.get("bid_count_no_competition_weight", 1.0)
    return weight


def category_target_value(stats_result: dict, category: str, config: dict) -> Optional[float]:
    """Liest aus einer bereits berechneten Overpay-Verteilung
    (robust_weighted_stats-Ergebnis, z.B. similarity.similar_transfers()
    oder market_stats_by_class_and_tier()) das fuer `category` konfigurierte
    Ziel-Perzentil (category_target_percentile in bidding_config.yaml) --
    ⚪ ungefaehr das typische Marktniveau (~50.), 🟢/⭐/🔥 zunehmend
    aggressiver (~62./77./87.). Das ist die methodische Umsetzung von Punkt
    11 der Aufgabenstellung: die Kategorie entscheidet, WO in der Verteilung
    das Gebot ansetzt, nicht ob ueberhaupt geboten wird (das entscheidet
    weiterhin ausschliesslich scoring.attractiveness)."""
    if not stats_result or stats_result.get("n", 0) <= 0:
        return None
    percentile = config.get("category_target_percentile", {}).get(category)
    if percentile is not None:
        value = target_percentile_value(stats_result, float(percentile))
        if value is not None:
            return value
    # Fallback fuer Aufrufer, die keine volle Perzentil-Palette/cleaned_points
    # mitliefern (z.B. handgebaute Vergleichs-Dicts in Tests, oder ein
    # class_tier_stats-Segment mit zu wenigen Punkten fuer eine belastbare
    # Perzentilberechnung) -- degradiert auf den Median statt None/Fehler.
    # similarity.similar_transfers() nennt das Feld "median_pct",
    # market_stats_by_class_and_tier()/robust_weighted_stats() "median".
    return stats_result.get("median_pct", stats_result.get("median"))


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

    result = {}
    for key, records in buckets.items():
        stats = robust_weighted_stats(_weighted_overpay_points(records, config, now=now))
        # Wie viele Transfers in diesem Segment NICHT von der Erstbefuellung
        # betroffen sind (siehe similarity.py fuer dieselbe Ueberlegung) --
        # pricing.py darf diesem Fallback nur vertrauen, wenn genug davon
        # tatsaechlich zeitpunktgenau erfasst wurden.
        stats["n_fresh"] = sum(1 for r in records if not r.get("backfilled"))
        result[key] = stats
    return result


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
