import json
import time
from pathlib import Path
from typing import Callable


class JsonFileCache:
    """Simple TTL-based on-disk cache for raw API responses.

    Keeps the tool usable for a small (12-manager) league without hammering
    Kickbase's servers on every run: finished matchdays and full-season
    performance data barely change, so re-fetching them every time is wasted
    (and risks rate limiting).
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.directory / f"{safe}.json"

    def get_or_fetch(self, key: str, ttl_seconds: float, fetch_fn: Callable[[], object], force_refresh: bool = False):
        path = self._path(key)
        if not force_refresh and path.exists():
            age = time.time() - path.stat().st_mtime
            if age < ttl_seconds:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        data = fetch_fn()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data
