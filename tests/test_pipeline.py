from pathlib import Path

from kickbase_tool.bidding.pipeline import compute_bids
from kickbase_tool.config import Settings


def make_settings(league_id=None):
    return Settings(
        email=None, password=None, auth_token=None, league_id=league_id,
        competition_id="bl1", cache_dir=Path("/tmp/unused-cache"),
        request_delay_seconds=0, max_workers=1,
        cache_ttl_volatile_seconds=3600, cache_ttl_performance_seconds=3600,
        openligadb_league_shortcut="bl1", openligadb_season="2026",
    )


def make_row(pid, market_value=10_000_000, kauf_rank=50, start_probability=1,
             points_per_value=8e-6, market_value_change_day=0, position="MF",
             status="fit", season_avg=6.0):
    return {
        "id": pid, "market_value": market_value, "kauf_rank": kauf_rank,
        "start_probability": start_probability, "points_per_value": points_per_value,
        "market_value_change_day": market_value_change_day, "position": position,
        "status": status, "season_avg": season_avg,
    }


def test_compute_bids_returns_one_recommendation_per_row_without_league_id(tmp_path):
    # Ohne KICKBASE_LEAGUE_ID kann kein Activity-Feed abgerufen werden --
    # das Modell muss trotzdem vollstaendig cold-start-basiert funktionieren
    # (siehe transfers.fetch_raw_activity_feed: leere Liste statt Fehler).
    rows = [make_row("1"), make_row("2", start_probability=5, kauf_rank=400, points_per_value=0.0)]
    settings = make_settings(league_id=None)

    results = compute_bids(
        rows, client=None, settings=settings,
        snapshot_path=tmp_path / "snapshots.json",
        transfer_log_path=tmp_path / "transfers.json",
    )

    assert set(results.keys()) == {"1", "2"}
    for pid, result in results.items():
        assert "category" in result
        assert "no_bid" in result
        assert "reasons" in result


def test_compute_bids_never_raises_and_degrades_to_empty_dict(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("simulierter Fehler in der Gebotspipeline")

    monkeypatch.setattr("kickbase_tool.bidding.pipeline.record_snapshot", boom)

    rows = [make_row("1")]
    settings = make_settings(league_id=None)
    results = compute_bids(
        rows, client=None, settings=settings,
        snapshot_path=tmp_path / "snapshots.json",
        transfer_log_path=tmp_path / "transfers.json",
    )
    assert results == {}


def test_compute_bids_writes_persistent_snapshot_file(tmp_path):
    rows = [make_row("1")]
    settings = make_settings(league_id=None)
    snapshot_path = tmp_path / "snapshots.json"

    compute_bids(
        rows, client=None, settings=settings,
        snapshot_path=snapshot_path, transfer_log_path=tmp_path / "transfers.json",
    )
    assert snapshot_path.exists()


def test_compute_bids_skips_rows_without_id(tmp_path):
    rows = [make_row("1"), {"market_value": 5_000_000}]
    settings = make_settings(league_id=None)

    results = compute_bids(
        rows, client=None, settings=settings,
        snapshot_path=tmp_path / "snapshots.json",
        transfer_log_path=tmp_path / "transfers.json",
    )
    assert set(results.keys()) == {"1"}
