from kickbase_tool.bidding.snapshot_store import record_snapshot, trend_stats
from kickbase_tool.bidding import snapshot_store as snapshot_store_module


def test_record_snapshot_creates_one_entry_per_player(tmp_path):
    path = tmp_path / "snapshots.json"
    rows = [{"id": "1", "market_value": 1000.0, "kauf_rank": 5}]
    store = record_snapshot(rows, path=path)
    assert store["1"][-1]["market_value"] == 1000.0
    assert store["1"][-1]["kauf_rank"] == 5


def test_record_snapshot_same_day_updates_instead_of_duplicating(tmp_path, monkeypatch):
    path = tmp_path / "snapshots.json"
    monkeypatch.setattr(snapshot_store_module, "_today_str", lambda: "2026-09-14")

    record_snapshot([{"id": "1", "market_value": 1000.0}], path=path)
    store = record_snapshot([{"id": "1", "market_value": 1100.0}], path=path)

    assert len(store["1"]) == 1
    assert store["1"][0]["market_value"] == 1100.0


def test_record_snapshot_trims_to_max_history(tmp_path):
    path = tmp_path / "snapshots.json"
    store = {}
    for day in range(1, 15):
        store = record_snapshot(
            [{"id": "1", "market_value": float(day)}], path=path, max_history=10
        )
        # Force a distinct date per call so entries actually accumulate.
        import json

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["1"][-1]["date"] = f"2026-09-{day:02d}"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    with open(path, "r", encoding="utf-8") as f:
        final = __import__("json").load(f)
    assert len(final["1"]) == 10
    assert final["1"][-1]["market_value"] == 14.0


def test_trend_stats_none_when_no_history():
    stats = trend_stats([])
    assert stats["change_3d"] is None
    assert stats["samples"] == 0


def test_trend_stats_computes_change_over_3_and_7_days():
    history = [{"market_value": float(10_000_000 + i * 100_000)} for i in range(8)]
    stats = trend_stats(history)
    assert stats["change_3d"] == 300_000
    assert stats["change_7d"] == 700_000
    assert stats["samples"] == 8


def test_trend_stats_detects_acceleration():
    # Daily deltas: 100k for the first 3 gaps, then 300k for the next 3 gaps -> accelerating.
    values = [10_000_000, 10_100_000, 10_200_000, 10_300_000, 10_600_000, 10_900_000, 11_200_000]
    history = [{"market_value": v} for v in values]
    stats = trend_stats(history)
    assert stats["acceleration"] > 0


def test_trend_stats_detects_deceleration():
    values = [10_000_000, 10_400_000, 10_800_000, 11_200_000, 11_300_000, 11_400_000, 11_500_000]
    history = [{"market_value": v} for v in values]
    stats = trend_stats(history)
    assert stats["acceleration"] < 0
