import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "speech-app"))

from braille_translator import available_grades  # noqa: E402


class AvailableGradesTests(unittest.TestCase):
    def test_unknown_language_still_reports_grade_one_fallback(self):
        self.assertEqual([1], available_grades("zz"))

    def test_contracted_language_reports_both_grades(self):
        self.assertEqual([1, 2], available_grades("es"))


if __name__ == "__main__":
    unittest.main()
