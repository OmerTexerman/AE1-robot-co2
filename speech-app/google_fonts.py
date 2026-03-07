import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cached_fonts: list[dict] | None = None
_cache_timestamp: float = 0
_CACHE_TTL = 24 * 60 * 60  # 24 hours
DEFAULT_FONT_FAMILY = "Noto Sans"


def _fetch_fonts() -> list[dict]:
    api_key = os.getenv("GOOGLE_FONTS_API_KEY", "")
    if not api_key:
        logger.warning("GOOGLE_FONTS_API_KEY not set, font list unavailable")
        return []

    resp = requests.get(
        "https://www.googleapis.com/webfonts/v1/webfonts",
        params={"key": api_key, "sort": "popularity"},
        timeout=15,
    )
    resp.raise_for_status()
    # Keep fields we use: family, subsets, category, and TTF URL for font rendering
    return [
        {
            "family": f["family"],
            "subsets": f.get("subsets", []),
            "category": f.get("category", ""),
            "ttf_url": (f.get("files") or {}).get("regular", ""),
        }
        for f in resp.json().get("items", [])
    ]


def _get_cached_fonts() -> list[dict]:
    global _cached_fonts, _cache_timestamp

    with _cache_lock:
        if _cached_fonts is not None and (time.monotonic() - _cache_timestamp) < _CACHE_TTL:
            return _cached_fonts
        stale = _cached_fonts

    # Fetch outside the lock to avoid blocking concurrent requests for up to 15s
    try:
        fonts = _fetch_fonts()
    except Exception:
        logger.exception("Failed to fetch Google Fonts")
        return stale if stale is not None else []

    with _cache_lock:
        _cached_fonts = fonts
        _cache_timestamp = time.monotonic()

    return fonts


def get_fonts_for_subset(subset: str, limit: int = 40) -> list[dict]:
    fonts = _get_cached_fonts()
    results = []
    for font in fonts:
        if subset in font.get("subsets", []):
            results.append({"family": font["family"], "category": font.get("category", "")})
            if len(results) >= limit:
                break
    return results


def get_default_font(subset: str) -> str:
    fonts = _get_cached_fonts()
    first_match = None

    for font in fonts:
        if subset not in font.get("subsets", []):
            continue
        if font["family"].startswith("Noto Sans"):
            return font["family"]
        if first_match is None:
            first_match = font["family"]

    return first_match or DEFAULT_FONT_FAMILY


def get_ttf_url(font_family: str) -> str | None:
    fonts = _get_cached_fonts()
    for font in fonts:
        if font["family"] == font_family:
            url = font.get("ttf_url", "")
            return url if url else None
    return None


def warm_cache() -> None:
    try:
        _get_cached_fonts()
        logger.info("Google Fonts cache warmed")
    except Exception:
        logger.warning("Google Fonts cache warm failed (will retry on first request)")
