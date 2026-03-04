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
    # Only keep the fields we actually use to reduce memory (~80% smaller)
    return [
        {"family": f["family"], "subsets": f.get("subsets", []), "category": f.get("category", "")}
        for f in resp.json().get("items", [])
    ]


def _get_cached_fonts() -> list[dict]:
    global _cached_fonts, _cache_timestamp

    with _cache_lock:
        if _cached_fonts is not None and (time.monotonic() - _cache_timestamp) < _CACHE_TTL:
            return _cached_fonts

        # Hold lock across fetch to prevent thundering herd
        try:
            fonts = _fetch_fonts()
        except Exception:
            logger.exception("Failed to fetch Google Fonts")
            return _cached_fonts if _cached_fonts is not None else []

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

    # Prefer first Noto Sans variant for the subset
    for font in fonts:
        if subset in font.get("subsets", []) and font["family"].startswith("Noto Sans"):
            return font["family"]

    # Fall back to most popular font for the subset (list is sorted by popularity)
    for font in fonts:
        if subset in font.get("subsets", []):
            return font["family"]

    return "Noto Sans"


def warm_cache() -> None:
    try:
        _get_cached_fonts()
        logger.info("Google Fonts cache warmed")
    except Exception:
        logger.warning("Google Fonts cache warm failed (will retry on first request)")
