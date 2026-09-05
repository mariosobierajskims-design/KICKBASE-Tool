import time
from typing import Any, Optional

import requests

from kickbase_tool.api import endpoints
from kickbase_tool.util import pick

BASE_URL = "https://api.kickbase.com"


class KickbaseAPIError(RuntimeError):
    pass


class KickbaseClient:
    def __init__(self, request_delay_seconds: float = 0.15):
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        self._token: Optional[str] = None
        self._request_delay = request_delay_seconds

    def login(self, email: str, password: str) -> dict:
        # Field names per the documented request example ("em"/"pass"); the
        # session's cookie jar picks up the "kkstrauth" auth cookie automatically
        # in case the API expects cookie auth instead of (or in addition to) a
        # bearer token in the response body.
        payload = {"em": email, "pass": password}
        data = self._request("POST", endpoints.LOGIN, json_body=payload, auth_required=False)
        token = pick(data, "tkn", "token", "accessToken", "access_token")
        if token:
            self._token = token
            self._session.headers["Authorization"] = f"Bearer {token}"
        return data

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        auth_required: bool = True,
    ) -> Any:
        url = f"{BASE_URL}{path}"
        resp = None
        for attempt in range(4):
            resp = self._session.request(method, url, params=params, json=json_body, timeout=20)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            break

        if resp.status_code == 401:
            raise KickbaseAPIError(
                f"Nicht autorisiert (401) fuer {path}. Login-Session abgelaufen oder "
                f"Zugangsdaten falsch."
            )
        if resp.status_code >= 400:
            raise KickbaseAPIError(f"Kickbase API Fehler {resp.status_code} fuer {path}: {resp.text[:300]}")

        if self._request_delay:
            time.sleep(self._request_delay)

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise KickbaseAPIError(f"Antwort von {path} war kein JSON: {resp.text[:300]}") from exc
