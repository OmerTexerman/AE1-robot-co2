try:
    import louis as _LOUIS
except ImportError:
    _LOUIS = None


# Grade 1: try "{lang}.tbl" first, with overrides for mismatched table names.
_G1_OVERRIDES: dict[str, str] = {
    "en": "en-ueb-g1.ctb",
    "zh": "zh_CHN.tbl",
    "fr": "fr-bfu-comp6.utb",
    "de": "de-g0.utb",
    "he": "he-IL.utb",
    "ko": "ko-g1.ctb",
    "ja": "ja-kantenji.utb",
    "ru": "ru-litbrl.ctb",
    "nl": "nl-NL-g0.utb",
}

# Grade 2 is only available where liblouis ships a dedicated contracted table.
_G2_TABLE: dict[str, str] = {
    "en": "en-ueb-g2.ctb",
    "fr": "fr-bfu-g2.ctb",
    "de": "de-g2.ctb",
    "es": "es-g2.ctb",
    "pt": "pt-pt-g2.ctb",
    "ko": "ko-g2.ctb",
    "ar": "ar-ar-g2.ctb",
}

_DEFAULT_TABLE = "en_US.tbl"
SUPPORTED_GRADES = (1, 2)
BRAILLE_UNAVAILABLE_MESSAGE = (
    "Braille support is unavailable because the 'louis' Python module is not installed."
)
BRAILLE_TABLES_UNAVAILABLE_MESSAGE = (
    "Braille support is unavailable because compatible liblouis tables were not found."
)


class BrailleUnavailableError(RuntimeError):
    pass


def _require_louis():
    if _LOUIS is None:
        raise BrailleUnavailableError(BRAILLE_UNAVAILABLE_MESSAGE)
    return _LOUIS


def _grade1_table(language: str) -> str:
    table = _resolve_grade1_table(language)
    if table is None:
        raise BrailleUnavailableError(BRAILLE_TABLES_UNAVAILABLE_MESSAGE)
    return table


def get_braille_table(language: str, grade: int) -> str:
    grade = grade if grade in SUPPORTED_GRADES else 1
    if grade == 2:
        table = _resolve_grade2_table(language)
        if table is not None:
            return table
    return _grade1_table(language)


def translate_to_braille_text(text: str, language: str, grade: int) -> str:
    table = get_braille_table(language, grade)
    return _require_louis().translateString(["unicode.dis", table], text)


def translate_to_braille(text: str, language: str, grade: int) -> list[list[int]]:
    braille_string = translate_to_braille_text(text, language, grade)

    cells: list[list[int]] = []
    for char in braille_string:
        code_point = ord(char)
        if code_point == 0x20:
            cells.append([])
            continue

        if 0x2800 <= code_point <= 0x28FF:
            offset = code_point - 0x2800
            dots = [i + 1 for i in range(6) if offset & (1 << i)]
            cells.append(dots)
        else:
            cells.append([])

    return cells


def available_grades(language: str) -> list[int]:
    grade1_table = _resolve_grade1_table(language)
    if grade1_table is None:
        return []
    grades = [1]
    if _resolve_grade2_table(language) is not None:
        grades.append(2)
    return grades


def _resolve_grade1_table(language: str) -> str | None:
    candidates = []
    if language in _G1_OVERRIDES:
        candidates.append(_G1_OVERRIDES[language])
    candidates.append(f"{language}.tbl")
    candidates.append(_DEFAULT_TABLE)

    for table in candidates:
        if _table_exists(table):
            return table
    return None


def _resolve_grade2_table(language: str) -> str | None:
    table = _G2_TABLE.get(language)
    if table and _table_exists(table):
        return table
    return None


def _table_exists(table: str) -> bool:
    if _LOUIS is None:
        return False
    try:
        _LOUIS.checkTable([table])
        return True
    except RuntimeError:
        return False


def normalize_grade(value: object) -> int:
    try:
        grade = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return grade if grade in SUPPORTED_GRADES else 1
