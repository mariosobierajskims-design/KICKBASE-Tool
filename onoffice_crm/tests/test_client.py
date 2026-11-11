import base64
import hashlib
import hmac

import pytest
import requests

from core.onoffice_client import (ACTION_CREATE, ACTION_DO, Action, OnOfficeAuthError, OnOfficeClient,
                                  OnOfficeError, WriteBlockedError, compute_hmac_v2)
from fake_api import SECRET, TOKEN, FakeResponse, FakeSession


def test_hmac_v2_matches_doc_formula():
    ts, rt, aid = "1700000000", "address", "urn:onoffice-de-ns:smart:2.5:smartml:action:read"
    expected = base64.b64encode(hmac.new(SECRET.encode(), f"{ts}{TOKEN}{rt}{aid}".encode(),
                                         hashlib.sha256).digest()).decode()
    assert compute_hmac_v2(SECRET, ts, TOKEN, rt, aid) == expected


def test_read_envelope_and_records(client, session):
    recs = client.read("address", {"data": ["Name"], "listlimit": 1})
    assert len(recs) == 1 and recs[0].get("Name") == "Albers"
    action = session.calls[0]["request"]["actions"][0]
    assert action["resourceid"] == "" and action["identifier"] == "" and action["hmac_version"] == "2"


def test_read_all_paginates(client, session):
    client.page_size = 3
    recs = client.read_all("agentslog", {"data": ["Datum"]})
    assert len(recs) == len(session.data["agentslog"])
    assert len(session.calls) == 6  # 16 Einträge / 3 je Seite


def test_write_blocked_in_phase1(client, session):
    with pytest.raises(WriteBlockedError):
        client.write(Action(ACTION_CREATE, "agentslog", {"note": "x"}))
    with pytest.raises(WriteBlockedError):
        client.execute([Action(ACTION_DO, "sendmail", {})])
    assert session.calls == []


def test_write_dry_run_sends_nothing(session):
    c = OnOfficeClient(TOKEN, SECRET, session=session, allow_write=True, dry_run=True, min_interval=0)
    assert c.write(Action(ACTION_CREATE, "agentslog", {"note": "x"})) is None
    assert session.calls == []


def test_retry_on_server_error():
    s = FakeSession(fail_times=2)
    slept = []
    c = OnOfficeClient(TOKEN, SECRET, session=s, min_interval=0, sleep=slept.append, max_retries=3)
    assert c.read("estate", {"data": ["objekttitel"]})
    assert len(s.calls) == 3 and slept == [1, 2]


def test_retry_exhausted_raises():
    s = FakeSession(fail_times=10)
    c = OnOfficeClient(TOKEN, SECRET, session=s, min_interval=0, sleep=lambda x: None, max_retries=2)
    with pytest.raises(OnOfficeError):
        c.read("estate", {})
    assert len(s.calls) == 3


def test_auth_error_not_retried():
    s = FakeSession(fail_times=5, fail_status=400)
    c = OnOfficeClient(TOKEN, SECRET, session=s, min_interval=0, sleep=lambda x: None)
    with pytest.raises(OnOfficeAuthError):
        c.read("address", {})
    assert len(s.calls) == 1


def test_connection_error_retried():
    class Flaky(FakeSession):
        n = 0

        def post(self, *a, **kw):
            self.n += 1
            if self.n == 1:
                raise requests.ConnectionError("boom")
            return super().post(*a, **kw)
    s = Flaky()
    c = OnOfficeClient(TOKEN, SECRET, session=s, min_interval=0, sleep=lambda x: None)
    assert c.read("estate", {"data": []})


def test_action_error_raises(client):
    class Err:
        def post(self, *a, **kw):
            return FakeResponse({"status": {"code": 200, "errorcode": 0, "message": "OK"},
                                 "response": {"results": [{"status": {"errorcode": 97, "message": "x"}}]}})
    client.session = Err()
    with pytest.raises(OnOfficeError) as e:
        client.read("address", {})
    assert e.value.errorcode == 97


def test_rate_limit_waits():
    t = [100.0]
    slept = []
    c = OnOfficeClient(TOKEN, SECRET, session=FakeSession(), min_interval=0.5,
                       clock=lambda: t[0], sleep=lambda s: slept.append(s))
    c.read("estate", {})
    c.read("estate", {})
    assert slept and abs(slept[-1] - 0.5) < 1e-9


def test_repr_hides_secrets(client):
    assert SECRET not in repr(client) and TOKEN not in repr(client)
