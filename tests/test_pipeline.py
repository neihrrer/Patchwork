import unittest
import sys
sys.path.insert(0, "src")

from gmic.pipeline import _serialize_param
from models.filter import ParamDef


class TestSerializeParam(unittest.TestCase):
    def test_none_no_default(self):
        self.assertEqual(_serialize_param(None), "0")

    def test_none_with_default(self):
        p = ParamDef("x", "X", kind="int", default=42)
        self.assertEqual(_serialize_param(None, p), "42")

    def test_none_with_string_default(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        self.assertEqual(_serialize_param(None, p), ".oO0")

    def test_empty_string(self):
        self.assertEqual(_serialize_param(""), "0")

    def test_empty_string_with_default(self):
        p = ParamDef("x", "X", kind="text", default=" .oO0")
        self.assertEqual(_serialize_param("", p), ".oO0")

    def test_bool_true(self):
        self.assertEqual(_serialize_param(True), "1")

    def test_bool_false(self):
        self.assertEqual(_serialize_param(False), "0")

    def test_int(self):
        self.assertEqual(_serialize_param(42), "42")

    def test_float(self):
        self.assertEqual(_serialize_param(3.14), "3.14")

    def test_list(self):
        self.assertEqual(_serialize_param([255, 0, 0, 255]), "255,0,0,255")

    def test_string_strips_leading_whitespace(self):
        self.assertEqual(_serialize_param(" .oO0"), ".oO0")

    def test_string_strips_trailing_whitespace(self):
        self.assertEqual(_serialize_param("abc  "), "abc")

    def test_string_strips_both(self):
        self.assertEqual(_serialize_param("  hello  "), "hello")

    def test_string_no_whitespace_unchanged(self):
        self.assertEqual(_serialize_param("hello"), "hello")


if __name__ == "__main__":
    unittest.main()
