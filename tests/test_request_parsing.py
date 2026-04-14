import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "speech-app"))

from request_parsing import (  # noqa: E402
    parse_int,
    parse_pairing_request,
    parse_render_mode,
    parse_toolpath_request,
    validate_operations,
)


class ParsePairingRequestTests(unittest.TestCase):
    def test_null_host_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Robot host or IP is required."):
            parse_pairing_request({"host": None, "pairing_code": "123456"})

    def test_null_pairing_code_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Pairing code is required."):
            parse_pairing_request({"host": "robot.local", "pairing_code": None})


class ParseToolpathRequestTests(unittest.TestCase):
    def test_invalid_font_size_is_a_client_error(self):
        with self.assertRaisesRegex(ValueError, "Font size must be a number."):
            parse_toolpath_request({"text": "hello", "font_size_mm": "large"})

    def test_invalid_margin_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Margins must be an object."):
            parse_toolpath_request({"text": "hello", "margins": 10})

    def test_custom_paper_requires_both_dimensions(self):
        with self.assertRaisesRegex(ValueError, "Both custom paper dimensions are required."):
            parse_toolpath_request({"text": "hello", "paper_size": "Custom", "paper_width": 210})

    def test_invalid_render_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Render mode must be 'outline', 'filled', or 'centerline'."):
            parse_render_mode("sketch")


class ValidateOperationsTests(unittest.TestCase):
    def test_invalid_operation_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Operation 1 has an invalid type."):
            validate_operations([{"type": "erase", "points": [[0, 0], [1, 1]]}])

    def test_single_point_travel_is_allowed(self):
        validate_operations([{"type": "travel", "points": [[0, 0]]}])

    def test_valid_operations_pass(self):
        validate_operations(
            [
                {"type": "travel", "points": [[0, 0], [1, 1]]},
                {"type": "draw", "points": [[1, 1], [2, 2]]},
                {"type": "punch", "point": [2, 2]},
            ]
        )


class ParseIntTests(unittest.TestCase):
    def test_parse_int_rejects_float_strings(self):
        with self.assertRaisesRegex(ValueError, "duty must be a number"):
            parse_int("12.5", "duty must be a number")


if __name__ == "__main__":
    unittest.main()
