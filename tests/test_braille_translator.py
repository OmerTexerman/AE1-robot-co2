import sys
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "speech-app"))

from braille_translator import BrailleUnavailableError, available_grades, translate_to_braille_text  # noqa: E402


class AvailableGradesTests(unittest.TestCase):
    def test_unknown_language_still_reports_grade_one_fallback(self):
        with mock.patch("braille_translator._table_exists", side_effect=lambda table: table == "en_US.tbl"):
            self.assertEqual([1], available_grades("zz"))

    def test_contracted_language_reports_both_grades(self):
        with mock.patch(
            "braille_translator._table_exists",
            side_effect=lambda table: table in {"en_US.tbl", "es-g2.ctb"},
        ):
            self.assertEqual([1, 2], available_grades("es"))

    def test_missing_louis_disables_braille_grades(self):
        with mock.patch("braille_translator._LOUIS", None):
            self.assertEqual([], available_grades("en"))


class TranslationAvailabilityTests(unittest.TestCase):
    def test_missing_louis_raises_clear_error(self):
        with mock.patch("braille_translator._LOUIS", None):
            with self.assertRaises(BrailleUnavailableError):
                translate_to_braille_text("hello", "en", 1)


if __name__ == "__main__":
    unittest.main()
