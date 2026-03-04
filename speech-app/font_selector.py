import unicodedata
from collections import Counter
from urllib.parse import quote_plus

from google_fonts import get_default_font

_SUBSET_MAP = {
    "cjk": "chinese-simplified",
    "hangul": "korean",
    "hiragana": "japanese",
    "katakana": "japanese",
}


def _char_subset(char: str) -> str | None:
    try:
        name = unicodedata.name(char)
    except ValueError:
        return None

    prefix = name.split(" ", 1)[0].lower()
    return _SUBSET_MAP.get(prefix, prefix)


def detect_subset(text: str) -> str:
    counts: Counter[str] = Counter()

    for char in text:
        if char.isspace() or char.isdigit() or unicodedata.category(char).startswith("P"):
            continue

        subset = _char_subset(char)
        if subset:
            counts[subset] += 1

    if not counts:
        return "latin"

    # Japanese/Korean get priority when present (mixed CJK text)
    if counts["japanese"] > 0:
        return "japanese"
    if counts["korean"] > 0:
        return "korean"

    return counts.most_common(1)[0][0]


def build_google_fonts_url(font_family: str) -> str:
    return (
        "https://fonts.googleapis.com/css2?family="
        f"{quote_plus(font_family)}:wght@400;500;700&display=swap"
    )


def choose_font(text: str) -> dict[str, str]:
    subset = detect_subset(text)
    font_family = get_default_font(subset)
    return {
        "script": subset,
        "font_family": font_family,
        "font_url": build_google_fonts_url(font_family),
    }
