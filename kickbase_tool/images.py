"""Fetches player photos / team logos from the Kickbase CDN and turns them into
small base64 data-URIs, so they can be embedded directly in the Artifact
database. The published Artifact page runs under a CSP that blocks image
requests to arbitrary external hosts (only certain CDNs may serve *scripts*),
so a plain <img src="https://kickbase.b-cdn.net/..."> would silently fail to
load -- a data: URI is not a network request and is unaffected by that.

Results are cached to disk (keyed by URL) so a daily refresh doesn't
re-download and re-encode every player photo each time.
"""
import base64
import hashlib
import io
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

try:
    import cairosvg
except ImportError:  # pragma: no cover - optional dependency
    cairosvg = None

CACHE_DIR = Path(".cache/thumbnails")
THUMB_SIZE = 48
LOGO_SIZE = 32
_TIMEOUT = 8.0


def _cache_path(cache_key: str) -> Path:
    h = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.txt"


def _read_cache(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    cached = path.read_text(encoding="utf-8").strip()
    return cached or None


def _write_cache(path: Path, data_uri: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(data_uri, encoding="utf-8")


def fetch_player_thumbnail(url: Optional[str], size: int = THUMB_SIZE) -> Optional[str]:
    """Downloads a player photo and returns a small square PNG data-URI."""
    if not url:
        return None
    cache_path = _cache_path(url)
    cached = _read_cache(cache_path)
    if cached is not None or cache_path.exists():
        return cached
    data_uri = ""
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img.thumbnail((size, size))
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = ((size - img.width) // 2, (size - img.height) // 2)
        canvas.paste(img, offset, img)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        data_uri = ""
    _write_cache(cache_path, data_uri)
    return data_uri or None


def fetch_team_logo(url: Optional[str], size: int = LOGO_SIZE) -> Optional[str]:
    """Downloads a team logo and returns a small PNG data-URI. Team crests are
    served as SVG by Kickbase; some of those SVGs are tens of KB (embedded
    detail that's invisible at the ~12px display size), and the same crest
    gets embedded in every player document of that team, so it's rasterized
    down to a small PNG here rather than stored as raw SVG."""
    if not url:
        return None
    cache_path = _cache_path(url + "::logo")
    cached = _read_cache(cache_path)
    if cached is not None or cache_path.exists():
        return cached
    data_uri = ""
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        is_svg = url.endswith(".svg") or b"<svg" in resp.content[:200]
        if is_svg and cairosvg is not None:
            png_bytes = cairosvg.svg2png(bytestring=resp.content, output_width=size, output_height=size)
            img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        elif is_svg:
            data_uri = "data:image/svg+xml;base64," + base64.b64encode(resp.content).decode("ascii")
        else:
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            img.thumbnail((size, size))
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        data_uri = ""
    _write_cache(cache_path, data_uri)
    return data_uri or None
