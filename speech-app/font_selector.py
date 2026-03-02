from collections import Counter
from urllib.parse import quote_plus


SCRIPT_FONTS = {
    "arabic": "Noto Naskh Arabic",
    "bengali": "Noto Sans Bengali",
    "cjk": "Noto Sans SC",
    "cyrillic": "Noto Sans",
    "devanagari": "Noto Sans Devanagari",
    "greek": "Noto Sans",
    "gujarati": "Noto Sans Gujarati",
    "gurmukhi": "Noto Sans Gurmukhi",
    "hebrew": "Noto Sans Hebrew",
    "japanese": "Noto Sans JP",
    "kannada": "Noto Sans Kannada",
    "korean": "Noto Sans KR",
    "latin": "Noto Sans",
    "malayalam": "Noto Sans Malayalam",
    "tamil": "Noto Sans Tamil",
    "telugu": "Noto Sans Telugu",
    "thai": "Noto Sans Thai",
}

LANGUAGE_SCRIPTS = {
    "ar": "arabic",
    "bg": "cyrillic",
    "bn": "bengali",
    "el": "greek",
    "gu": "gujarati",
    "he": "hebrew",
    "hi": "devanagari",
    "ja": "japanese",
    "kn": "kannada",
    "ko": "korean",
    "ml": "malayalam",
    "mr": "devanagari",
    "pa": "gurmukhi",
    "ru": "cyrillic",
    "ta": "tamil",
    "te": "telugu",
    "th": "thai",
    "uk": "cyrillic",
    "zh": "cjk",
}


def codepoint_in_ranges(codepoint: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= codepoint <= end for start, end in ranges)


SCRIPT_RANGES = {
    "arabic": [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF)],
    "bengali": [(0x0980, 0x09FF)],
    "cjk": [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)],
    "cyrillic": [(0x0400, 0x052F)],
    "devanagari": [(0x0900, 0x097F)],
    "greek": [(0x0370, 0x03FF), (0x1F00, 0x1FFF)],
    "gujarati": [(0x0A80, 0x0AFF)],
    "gurmukhi": [(0x0A00, 0x0A7F)],
    "hebrew": [(0x0590, 0x05FF)],
    "japanese": [(0x3040, 0x309F), (0x30A0, 0x30FF)],
    "kannada": [(0x0C80, 0x0CFF)],
    "korean": [(0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF)],
    "latin": [
        (0x0041, 0x005A),
        (0x0061, 0x007A),
        (0x00C0, 0x00FF),
        (0x0100, 0x017F),
        (0x0180, 0x024F),
        (0x1E00, 0x1EFF),
    ],
    "malayalam": [(0x0D00, 0x0D7F)],
    "tamil": [(0x0B80, 0x0BFF)],
    "telugu": [(0x0C00, 0x0C7F)],
    "thai": [(0x0E00, 0x0E7F)],
}


def detect_script(text: str) -> str:
    counts = Counter()

    for char in text:
        codepoint = ord(char)
        if char.isspace() or char.isdigit():
            continue

        for script, ranges in SCRIPT_RANGES.items():
            if codepoint_in_ranges(codepoint, ranges):
                counts[script] += 1
                break

    if not counts:
        return "latin"

    if counts["japanese"] > 0:
        return "japanese"
    if counts["korean"] > 0:
        return "korean"

    return counts.most_common(1)[0][0]


def normalize_language(language: str | None) -> str | None:
    if not language:
        return None
    return language.lower().split("-", 1)[0]


def fallback_script_for_language(language: str | None) -> str | None:
    normalized_language = normalize_language(language)
    if normalized_language is None:
        return None
    return LANGUAGE_SCRIPTS.get(normalized_language)


def build_google_fonts_url(font_family: str) -> str:
    return (
        "https://fonts.googleapis.com/css2?family="
        f"{quote_plus(font_family)}:wght@400;500;700&display=swap"
    )


def choose_font(text: str, language: str | None = None) -> dict[str, str]:
    detected_script = detect_script(text)
    fallback_script = fallback_script_for_language(language)
    script = fallback_script if detected_script == "latin" and fallback_script else detected_script
    font_family = SCRIPT_FONTS.get(script, SCRIPT_FONTS["latin"])
    return {
        "script": script,
        "font_family": font_family,
        "font_url": build_google_fonts_url(font_family),
    }
