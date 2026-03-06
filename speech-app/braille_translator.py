import louis


# Grade 1: try "{lang}.tbl" dynamically; override where the
# ISO 639-1 code doesn't match an available .tbl filename.
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

# Grade 2: only languages that ship a dedicated contracted table.
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


def _grade1_table(language: str) -> str:
    if language in _G1_OVERRIDES:
        return _G1_OVERRIDES[language]
    if _try_dynamic_table(language):
        return f"{language}.tbl"
    return _DEFAULT_TABLE


def get_braille_table(language: str, grade: int) -> str:
    grade = grade if grade in SUPPORTED_GRADES else 1
    if grade == 2 and language in _G2_TABLE:
        return _G2_TABLE[language]
    return _grade1_table(language)


def translate_to_braille_text(text: str, language: str, grade: int) -> str:
    table = get_braille_table(language, grade)
    return louis.translateString(["unicode.dis", table], text)


def translate_to_braille(text: str, language: str, grade: int) -> list[list[int]]:
    table = get_braille_table(language, grade)
    braille_string = louis.translateString(["unicode.dis", table], text)

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
    has_g1 = language in _G1_OVERRIDES or _try_dynamic_table(language)
    has_g2 = language in _G2_TABLE
    grades: list[int] = []
    if has_g1:
        grades.append(1)
    if has_g2:
        grades.append(2)
    return grades


def _try_dynamic_table(language: str) -> bool:
    table = f"{language}.tbl"
    try:
        louis.checkTable([table])
        return True
    except RuntimeError:
        return False


def normalize_grade(value: object) -> int:
    try:
        grade = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return grade if grade in SUPPORTED_GRADES else 1
