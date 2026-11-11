"""onOffice enterprise API-Client.

Verifiziert lt. apidoc.onoffice.de:
- POST JSON an https://api.onoffice.de/api/stable/api.php
- Envelope {"token": ..., "request": {"actions": [ {actionid, resourceid, identifier,
  resourcetype, timestamp, hmac, hmac_version: "2", parameters} ]}}
- HMAC v2 = base64( HMAC-SHA256( timestamp + token + resourcetype + actionid, key=secret ) )
- Antwort: status.code / status.errorcode, response.results[i].data.records[j].{id, elements}
- listlimit max. 500 (address, estate, agentslog, task)

Schutz Phase 1: nur read/get sind freigegeben. create/modify/delete/do werfen
WriteBlockedError, solange der Client nicht explizit mit allow_write=True erzeugt wird;
und auch dann gilt DRY_RUN (nur protokollieren, nichts senden).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .logger import get_logger

log = get_logger("onoffice")

URN = "urn:onoffice-de-ns:smart:2.5:smartml:action:"
ACTION_READ = URN + "read"
ACTION_CREATE = URN + "create"
ACTION_MODIFY = URN + "modify"
ACTION_DELETE = URN + "delete"
ACTION_GET = URN + "get"
ACTION_DO = URN + "do"

READ_ACTIONS = frozenset({ACTION_READ, ACTION_GET})
WRITE_ACTIONS = frozenset({ACTION_CREATE, ACTION_MODIFY, ACTION_DELETE, ACTION_DO})


class OnOfficeError(Exception):
    """Fehler aus der API (HTTP, Envelope-Status oder Action-Status)."""

    def __init__(self, message: str, errorcode: int | None = None, http_status: int | None = None):
        super().__init__(message)
        self.errorcode = errorcode
        self.http_status = http_status


class OnOfficeAuthError(OnOfficeError):
    pass


class WriteBlockedError(OnOfficeError):
    pass


@dataclass
class Action:
    actionid: str
    resourcetype: str
    parameters: dict[str, Any] = field(default_factory=dict)
    resourceid: str = ""
    identifier: str = ""


@dataclass
class Record:
    id: Any
    type: str
    elements: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.elements.get(key, default) if isinstance(self.elements, dict) else default


def compute_hmac_v2(secret: str, timestamp: str, token: str, resourcetype: str, actionid: str) -> str:
    msg = f"{timestamp}{token}{resourcetype}{actionid}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


class OnOfficeClient:
    def __init__(
        self,
        token: str,
        secret: str,
        url: str = "https://api.onoffice.de/api/stable/api.php",
        *,
        timeout: float = 30,
        max_retries: int = 3,
        min_interval: float = 0.4,
        page_size: int = 500,
        max_records: int = 5000,
        allow_write: bool = False,
        dry_run: bool = True,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._token = token
        self._secret = secret
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self.page_size = min(int(page_size), 500)
        self.max_records = max_records
        self.allow_write = allow_write
        self.dry_run = dry_run
        self.session = session or requests.Session()
        self._clock = clock
        self._sleep = sleep
        self._last_request = 0.0
        self.request_count = 0

    def __repr__(self) -> str:  # niemals Token/Secret ausgeben
        return f"OnOfficeClient(url={self.url!r}, allow_write={self.allow_write}, dry_run={self.dry_run})"

    # ------------------------------------------------------------------
    def _sign(self, action: Action) -> dict[str, Any]:
        ts = str(int(self._clock()))
        return {
            "actionid": action.actionid,
            "resourceid": action.resourceid,
            "identifier": action.identifier,
            "resourcetype": action.resourcetype,
            "timestamp": ts,
            "hmac": compute_hmac_v2(self._secret, ts, self._token, action.resourcetype, action.actionid),
            "hmac_version": "2",
            "parameters": action.parameters,
        }

    def _throttle(self) -> None:
        wait = self.min_interval - (self._clock() - self._last_request)
        if wait > 0:
            self._sleep(wait)

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body, ensure_ascii=False)
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self._last_request = self._clock()
            self.request_count += 1
            try:
                resp = self.session.post(
                    self.url, data=payload.encode("utf-8"),
                    headers={"Content-Type": "application/json"}, timeout=self.timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                log.warning("Verbindungsfehler (Versuch %d/%d): %s", attempt + 1,
                            self.max_retries + 1, type(exc).__name__)
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = OnOfficeError(f"HTTP {resp.status_code}", http_status=resp.status_code)
                    log.warning("HTTP %d (Versuch %d/%d)", resp.status_code, attempt + 1, self.max_retries + 1)
                elif resp.status_code in (400, 401, 403):
                    raise OnOfficeAuthError(
                        f"HTTP {resp.status_code}: nicht authentifiziert (Token/Secret/Rechte prüfen)",
                        http_status=resp.status_code)
                else:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise OnOfficeError("Antwort ist kein gültiges JSON") from exc
            if attempt < self.max_retries:
                self._sleep(min(2 ** attempt, 30))
        raise OnOfficeError(f"Anfrage nach {self.max_retries + 1} Versuchen fehlgeschlagen: {last_exc}")

    def execute(self, actions: list[Action]) -> list[dict[str, Any]]:
        """Führt Actions aus (mehrere pro Request möglich). Liefert die result-Objekte."""
        for a in actions:
            if a.actionid in WRITE_ACTIONS:
                self._guard_write(a)
            elif a.actionid not in READ_ACTIONS:
                raise OnOfficeError(f"Unbekannte actionid: {a.actionid}")
        body = {"token": self._token, "request": {"actions": [self._sign(a) for a in actions]}}
        t0 = time.monotonic()
        data = self._post(body)
        status = data.get("status") or {}
        code = status.get("code")
        if code not in (200, "200", None) or status.get("errorcode") not in (0, "0", None):
            msg = status.get("message") or "unbekannter Fehler"
            if code in (400, "400"):
                raise OnOfficeAuthError(f"API: {msg}", errorcode=status.get("errorcode"))
            raise OnOfficeError(f"API-Status {code}/{status.get('errorcode')}: {msg}",
                                errorcode=status.get("errorcode"))
        results = (data.get("response") or {}).get("results") or []
        for a, res in zip(actions, results):
            rs = res.get("status") or {}
            if rs.get("errorcode") not in (0, "0", None):
                raise OnOfficeError(
                    f"{a.resourcetype}: Fehler {rs.get('errorcode')}: {rs.get('message')}",
                    errorcode=rs.get("errorcode"))
        log.debug("%s in %.2fs (%d Action(s), Parameter: %s)",
                  ",".join(a.resourcetype for a in actions), time.monotonic() - t0,
                  len(actions), ",".join(sorted({k for a in actions for k in a.parameters})))
        return results

    @staticmethod
    def records_of(result: dict[str, Any]) -> list[Record]:
        recs = ((result.get("data") or {}).get("records")) or []
        out = []
        for r in recs:
            el = r.get("elements")
            out.append(Record(id=r.get("id"), type=r.get("type", ""), elements=el if isinstance(el, dict) else {}))
        return out

    @staticmethod
    def total_of(result: dict[str, Any]) -> int | None:
        meta = (result.get("data") or {}).get("meta") or {}
        val = meta.get("cntabsolute")
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    # --- Lesen ----------------------------------------------------------
    def read(self, resourcetype: str, parameters: dict[str, Any] | None = None,
             resourceid: str = "") -> list[Record]:
        res = self.execute([Action(ACTION_READ, resourcetype, parameters or {}, str(resourceid))])
        return self.records_of(res[0]) if res else []

    def read_all(self, resourcetype: str, parameters: dict[str, Any] | None = None) -> list[Record]:
        """Liest mit listlimit/listoffset seitenweise bis alles da ist (max. max_records)."""
        params = dict(parameters or {})
        out: list[Record] = []
        offset = 0
        while True:
            params["listlimit"] = self.page_size
            params["listoffset"] = offset
            res = self.execute([Action(ACTION_READ, resourcetype, params)])
            page = self.records_of(res[0]) if res else []
            total = self.total_of(res[0]) if res else None
            out.extend(page)
            offset += len(page)
            if len(page) < self.page_size or (total is not None and offset >= total):
                break
            if len(out) >= self.max_records:
                log.warning("%s: Abbruch bei %d Datensätzen (max_records)", resourcetype, len(out))
                break
        return out

    def get(self, resourcetype: str, parameters: dict[str, Any] | None = None,
            resourceid: str = "") -> list[Record]:
        res = self.execute([Action(ACTION_GET, resourcetype, parameters or {}, str(resourceid))])
        return self.records_of(res[0]) if res else []

    # --- Schreiben (Phase 1 gesperrt) -----------------------------------
    def _guard_write(self, action: Action) -> None:
        if not self.allow_write:
            raise WriteBlockedError(
                f"Schreibzugriff gesperrt (Phase 1 = nur lesen): {action.actionid.rsplit(':', 1)[-1]} "
                f"{action.resourcetype}")

    def write(self, action: Action) -> list[dict[str, Any]] | None:
        """Schreibende Action. Gesperrt ohne allow_write; mit DRY_RUN nur Protokoll."""
        if action.actionid not in WRITE_ACTIONS:
            raise OnOfficeError("write() nur für create/modify/delete/do")
        self._guard_write(action)
        if self.dry_run:
            log.info("DRY_RUN: %s %s nicht ausgeführt (Parameter: %s)",
                     action.actionid.rsplit(":", 1)[-1], action.resourcetype,
                     ",".join(sorted(action.parameters)))
            return None
        return self.execute([action])
