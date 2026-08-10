"""Turn a map link (or a raw "lat, lon" paste) into coordinates.

Admins paste a Google/Yandex Maps link when adding or editing a store and we
pull the coordinates out of it automatically — no need to share a live Telegram
location. Handles the many link shapes those apps produce (?q=, ?ll=, @lat,lon,
!3d!4d, /search/, DMS) and follows short links (maps.app.goo.gl) to their real
URL. This is the single source of truth reused by scripts/import_sheet.py.
"""

import asyncio
import re
import urllib.parse
import urllib.request

_DMS = re.compile(r'(\d+)°(\d+)\'([\d.]+)"([NS]).{0,4}?(\d+)°(\d+)\'([\d.]+)"([EW])')

# A bare "41.311081, 69.240562" paste (optionally with surrounding spaces).
_PLAIN = re.compile(r'^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$')

# The first http(s) URL inside a longer message.
_URL = re.compile(r'https?://\S+')


def _dms(d: str, m: str, s: str, hemi: str) -> float:
    v = float(d) + float(m) / 60 + float(s) / 3600
    return -v if hemi in ("S", "W") else v


def extract_coords(url: str) -> tuple[float, float] | None:
    """Pull (lat, lon) out of any of the map-link formats we've seen."""
    if not url:
        return None
    u = urllib.parse.unquote(url)
    m = re.search(r'[?&](?:q|ll)=(-?\d+\.\d+),\s*(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r'/search/(-?\d+\.\d+),\s*\+?(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _DMS.search(u)
    if m:
        return _dms(*m.group(1, 2, 3, 4)), _dms(*m.group(5, 6, 7, 8))
    m = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', u)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def resolve(url: str) -> str:
    """Follow redirects so a short link becomes its full coordinate-bearing URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.geturl()
    except Exception:  # noqa: BLE001 — any network error just means "can't resolve"
        return url


def valid_coords(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def coords_from_text(text: str) -> tuple[float, float] | None:
    """Synchronous parse that does NOT hit the network (safe on the event loop)."""
    if not text:
        return None
    text = text.strip()
    m = _PLAIN.match(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return (lat, lon) if valid_coords(lat, lon) else None
    return extract_coords(text)


async def coords_from_link(text: str) -> tuple[float, float] | None:
    """Full parse: try the text as-is, else follow a short link off-thread.

    urllib is blocking, so the redirect resolve runs in a worker thread to keep
    the bot's event loop responsive.
    """
    coords = coords_from_text(text)
    if coords:
        return coords
    match = _URL.search(text or "")
    if not match:
        return None
    resolved = await asyncio.to_thread(resolve, match.group(0))
    coords = extract_coords(resolved)
    if coords and valid_coords(*coords):
        return coords
    return None
