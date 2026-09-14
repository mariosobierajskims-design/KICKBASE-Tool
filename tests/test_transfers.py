from kickbase_tool.bidding.transfers import (
    extract_purchase_events,
    ingest_new_transfers,
    load_transfer_log,
)
from kickbase_tool.config import Settings


def make_settings(league_id="123"):
    return Settings(
        email=None, password=None, auth_token="tok", league_id=league_id, competition_id="1",
        cache_dir=None, request_delay_seconds=0.0, max_workers=1,
        cache_ttl_volatile_seconds=0, cache_ttl_performance_seconds=0,
        openligadb_league_shortcut="bl1", openligadb_season="2026",
    )


class FakeClient:
    def __init__(self, activities):
        self.activities = activities
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return {"af": self.activities}


def purchase_activity(activity_id, player_id, buyer, price, coc=0, dt="2026-09-14T12:00:00Z"):
    return {
        "i": activity_id, "t": 15, "coc": coc,
        "data": {"byr": buyer, "pi": player_id, "pn": f"Player{player_id}", "tid": "5", "t": 1, "trp": price},
        "dt": dt,
    }


def sale_to_market_activity(activity_id, player_id, seller, price):
    return {
        "i": activity_id, "t": 15, "coc": 0,
        "data": {"slr": seller, "pi": player_id, "pn": f"Player{player_id}", "tid": "5", "t": 2, "trp": price},
        "dt": "2026-09-14T12:00:00Z",
    }


def test_extract_purchase_events_ignores_sales_without_buyer():
    raw = [purchase_activity("a1", "100", "Kurti", 5_000_000), sale_to_market_activity("a2", "101", "Kurti", 1_000_000)]
    events = extract_purchase_events(raw)
    assert len(events) == 1
    assert events[0]["id"] == "a1"
    assert events[0]["buyer"] == "Kurti"
    assert events[0]["transfer_price"] == 5_000_000.0


def test_extract_purchase_events_ignores_non_transfer_activity_types():
    raw = [{"i": "a3", "t": 3, "data": {"pi": "100"}, "dt": "2026-09-14T12:00:00Z"}]
    assert extract_purchase_events(raw) == []


def test_extract_purchase_events_reads_bid_count_from_top_level_coc():
    # Regressionstest: "coc" (Anzahl Gebote) liegt live auf der obersten
    # Ebene des Activity-Eintrags (entry["coc"]), NICHT in entry["data"] --
    # die urspruengliche Implementierung las aus data["coc"] und bekam deshalb
    # immer None zurueck, unabhaengig vom tatsaechlichen Wert.
    raw = [purchase_activity("a1", "100", "Kurti", 5_000_000, coc=7)]
    events = extract_purchase_events(raw)
    assert events[0]["bid_count"] == 7


def test_ingest_new_transfers_enriches_with_current_row_and_computes_overpay(tmp_path):
    path = tmp_path / "transfers.json"
    activities = [purchase_activity("a1", "2939", "AymenJakob", 9_261_111, coc=2)]
    client = FakeClient(activities)
    rows_by_pid = {"2939": {
        "market_value": 7_199_000, "kauf_rank": 245, "start_probability": 1,
        "points_per_value": 1.5e-6, "market_value_change_day": 267_000, "position": "ST", "status": "fit",
    }}

    log = ingest_new_transfers(rows_by_pid, client, make_settings(), path=path)

    assert len(log) == 1
    record = log[0]
    assert record["player_id"] == "2939"
    assert record["buyer"] == "AymenJakob"
    assert record["market_value"] == 7_199_000
    assert round(record["overpay_abs"]) == 2_062_111
    assert round(record["overpay_pct"], 1) == 28.6
    assert record["backfilled"] is True  # first-ever ingest -> whole batch flagged


def test_ingest_new_transfers_does_not_duplicate_already_known_activity(tmp_path):
    path = tmp_path / "transfers.json"
    activities = [purchase_activity("a1", "100", "Kurti", 5_000_000)]
    rows_by_pid = {"100": {"market_value": 4_000_000, "kauf_rank": 50, "start_probability": 1,
                            "points_per_value": 1e-6, "market_value_change_day": 0, "position": "MF", "status": "fit"}}

    client1 = FakeClient(activities)
    log1 = ingest_new_transfers(rows_by_pid, client1, make_settings(), path=path)
    assert len(log1) == 1

    client2 = FakeClient(activities)  # same activity feed returned again
    log2 = ingest_new_transfers(rows_by_pid, client2, make_settings(), path=path)
    assert len(log2) == 1
    assert log2 == load_transfer_log(path)


def test_ingest_new_transfers_second_batch_is_not_flagged_backfilled(tmp_path):
    path = tmp_path / "transfers.json"
    rows_by_pid = {"100": {"market_value": 4_000_000, "kauf_rank": 50, "start_probability": 1,
                            "points_per_value": 1e-6, "market_value_change_day": 0, "position": "MF", "status": "fit"},
                   "200": {"market_value": 4_000_000, "kauf_rank": 50, "start_probability": 1,
                           "points_per_value": 1e-6, "market_value_change_day": 0, "position": "MF", "status": "fit"}}

    client1 = FakeClient([purchase_activity("a1", "100", "Kurti", 5_000_000)])
    ingest_new_transfers(rows_by_pid, client1, make_settings(), path=path)

    client2 = FakeClient([purchase_activity("a1", "100", "Kurti", 5_000_000), purchase_activity("a2", "200", "houston", 4_500_000)])
    log2 = ingest_new_transfers(rows_by_pid, client2, make_settings(), path=path)

    assert len(log2) == 2
    new_record = next(r for r in log2 if r["id"] == "a2")
    assert new_record["backfilled"] is False


def test_ingest_new_transfers_skips_player_not_in_current_pool(tmp_path):
    path = tmp_path / "transfers.json"
    client = FakeClient([purchase_activity("a1", "999", "Kurti", 5_000_000)])
    log = ingest_new_transfers({}, client, make_settings(), path=path)
    assert log == []


def test_ingest_new_transfers_no_league_id_returns_existing_log_unchanged(tmp_path):
    path = tmp_path / "transfers.json"
    client = FakeClient([purchase_activity("a1", "100", "Kurti", 5_000_000)])
    log = ingest_new_transfers({}, client, make_settings(league_id=None), path=path)
    assert log == []
    assert client.calls == []  # never even attempted the request
