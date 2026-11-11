"""Fake onOffice-API für Tests: wertet Requests aus wie der echte Endpoint (vereinfachte Filter)
und prüft dabei Envelope + HMAC v2. Daten kommen aus tests/fixtures/*.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.onoffice_client import READ_ACTIONS, compute_hmac_v2

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "test-token-123456"
SECRET = "test-secret-abcdef"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, data: Any, status: int = 200):
        self._data = data
        self.status_code = status

    def json(self) -> Any:
        return self._data


def _cmp(val: Any, op: str, target: Any) -> bool:
    op = op.lower()
    if isinstance(val, list):
        return any(_cmp(v, op, target) for v in val)
    s = "" if val is None else str(val)
    if op in ("=", "is"):
        return s == str(target)
    if op in ("!=", "<>"):
        return s != str(target)
    if op == "in":
        return s in {str(t) for t in target}
    if op == "not in":
        return s not in {str(t) for t in target}
    if op == "between":
        return str(target[0]) <= s <= str(target[1])
    if op == ">=":
        return s >= str(target)
    if op == "<=":
        return s <= str(target)
    if op == ">":
        return s > str(target)
    if op == "<":
        return s < str(target)
    if op == "like":
        needle = str(target).strip("%").lower()
        return needle in s.lower()
    raise ValueError(op)


def _apply_filter(records: list[dict], flt: dict) -> list[dict]:
    out = []
    for r in records:
        ok = True
        for feld, bedingungen in (flt or {}).items():
            for b in bedingungen:
                if not _cmp(r["elements"].get(feld) if feld != "Id" else r["id"], b["op"], b["val"]):
                    ok = False
        if ok:
            out.append(r)
    return out


class FakeSession:
    def __init__(self, data: dict[str, list[dict]] | None = None, fail_times: int = 0, fail_status: int = 500):
        self.data = data if data is not None else {
            "address": load("address.json"), "estate": load("estate.json"),
            "agentslog": load("agentslog.json"), "appointmentList": load("appointments.json"),
            "task": load("task.json"),
        }
        self.calls: list[dict] = []
        self.fail_times = fail_times
        self.fail_status = fail_status

    def post(self, url, data=None, headers=None, timeout=None):
        body = json.loads(data.decode("utf-8"))
        self.calls.append(body)
        if self.fail_times > 0:
            self.fail_times -= 1
            return FakeResponse({}, self.fail_status)
        assert body["token"] == TOKEN
        results = []
        for a in body["request"]["actions"]:
            assert a["hmac_version"] == "2"
            expected = compute_hmac_v2(SECRET, a["timestamp"], TOKEN, a["resourcetype"], a["actionid"])
            assert a["hmac"] == expected, "HMAC falsch"
            assert a["actionid"] in READ_ACTIONS, f"Schreibende Action gesendet: {a['actionid']}"
            records = self._handle(a["resourcetype"], a["parameters"], a["resourceid"])
            results.append({"actionid": a["actionid"], "resourcetype": a["resourcetype"],
                            "identifier": a["identifier"], "resourceid": a["resourceid"],
                            "data": {"meta": {"cntabsolute": records[1]}, "records": records[0]},
                            "status": {"errorcode": 0, "message": "OK"}})
        return FakeResponse({"status": {"code": 200, "errorcode": 0, "message": "OK"},
                             "response": {"results": results}})

    def _handle(self, rt: str, p: dict, resourceid: str) -> tuple[list[dict], int]:
        if rt == "actionkindtypes":
            recs = load("actionkindtypes.json")
            return recs, len(recs)
        if rt == "fields":
            recs = load("fields.json")
            return recs, len(recs)
        recs = list(self.data.get(rt, []))
        if rt == "appointmentList":
            f = p.get("filter", {})
            recs = [r for r in recs if f["startDate"] <= r["elements"]["date"]["start"][:10] <= f["endDate"]]
            return recs, len(recs)
        if rt == "task":
            aid = str(p.get("relatedAddressId"))
            recs = [r for r in recs if aid in r["elements"].get("relatedAddressId", [])]
            return recs, len(recs)
        if rt == "agentslog":
            if p.get("addressid"):
                ids = {str(i) for i in p["addressid"]}
                recs = [r for r in recs if ids & set(r["elements"].get("Adress_nr", []))]
            if p.get("estateid"):
                ids = {str(i) for i in p["estateid"]}
                recs = [r for r in recs if ids & set(r["elements"].get("Objekt_nr", []))]
            recs.sort(key=lambda r: r["elements"]["Datum"], reverse=True)
        if rt == "address" and p.get("recordids"):
            ids = {int(i) for i in p["recordids"]}
            recs = [r for r in recs if int(r["id"]) in ids]
        recs = _apply_filter(recs, p.get("filter") or {})
        total = len(recs)
        off, lim = int(p.get("listoffset", 0)), int(p.get("listlimit", 20))
        return recs[off:off + lim], total
