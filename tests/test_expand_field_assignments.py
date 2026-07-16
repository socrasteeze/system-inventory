"""Tests for scripts/expand_field_assignments.py's pure logic (build_assignments,
read_mapping). No docs/field-index.json or network dependency -- field sets are
passed in directly."""
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import expand_field_assignments as efa


class BuildAssignmentsTests(unittest.TestCase):
    def setUp(self):
        self.trigger_fields = {"WaterHeaterSize", "EnrollmentStatus"}
        self.target_fields = {"ExistingWaterHeaterSize", "DesktopReviewStatus"}

    def test_from_trigger_and_constant(self):
        rows = [
            ("WaterHeaterSize", "From Trigger", "ExistingWaterHeaterSize"),
            ("Approved", "Constant", "DesktopReviewStatus"),
        ]
        assignments, lines, errors, warnings = efa.build_assignments(
            rows, self.trigger_fields, self.target_fields)
        self.assertEqual(errors, [])
        self.assertEqual(assignments, [
            {"FieldName": "ExistingWaterHeaterSize", "ValueType": "FromTrigger",
             "Value": "WaterHeaterSize"},
            {"FieldName": "DesktopReviewStatus", "ValueType": "Constant",
             "Value": "Approved"},
        ])
        self.assertEqual(len(lines), 2)

    def test_unsupported_expression_type_errors(self):
        rows = [("{{WaterHeaterSize}}", "Expression", "ExistingWaterHeaterSize")]
        assignments, _, errors, _ = efa.build_assignments(
            rows, self.trigger_fields, self.target_fields)
        self.assertEqual(assignments, [])
        self.assertIn("isn't supported yet", errors[0])

    def test_unsupported_clear_set_null_errors(self):
        rows = [("", "Clear/Set Null", "DesktopReviewStatus")]
        assignments, _, errors, _ = efa.build_assignments(
            rows, self.trigger_fields, self.target_fields)
        self.assertEqual(assignments, [])
        self.assertIn("isn't supported yet", errors[0])

    def test_unknown_trigger_field_errors(self):
        rows = [("NoSuchField", "From Trigger", "ExistingWaterHeaterSize")]
        _, _, errors, _ = efa.build_assignments(rows, self.trigger_fields, self.target_fields)
        self.assertIn("not found", errors[0])

    def test_unknown_target_field_errors(self):
        rows = [("x", "Constant", "NoSuchTargetField")]
        _, _, errors, _ = efa.build_assignments(rows, self.trigger_fields, self.target_fields)
        self.assertIn("is not on the target form", errors[0])

    def test_duplicate_target_errors(self):
        rows = [
            ("WaterHeaterSize", "From Trigger", "ExistingWaterHeaterSize"),
            ("y", "Constant", "ExistingWaterHeaterSize"),
        ]
        _, _, errors, _ = efa.build_assignments(rows, self.trigger_fields, self.target_fields)
        self.assertIn("duplicates row 2", errors[0])

    def test_constant_casing_typo_warns_not_errors(self):
        rows = [("waterheatersize", "Constant", "ExistingWaterHeaterSize")]
        assignments, _, errors, warnings = efa.build_assignments(
            rows, self.trigger_fields, self.target_fields)
        self.assertEqual(errors, [])
        self.assertEqual(len(assignments), 1)
        self.assertIn("did you mean FromTrigger", warnings[0])

    def test_blank_type_errors(self):
        rows = [("x", "", "DesktopReviewStatus")]
        _, _, errors, _ = efa.build_assignments(rows, self.trigger_fields, self.target_fields)
        self.assertIn("Field Assignment Type is blank", errors[0])

    def test_blank_target_errors(self):
        rows = [("x", "Constant", "")]
        _, _, errors, _ = efa.build_assignments(rows, self.trigger_fields, self.target_fields)
        self.assertIn("Resolution (Field Name) is blank", errors[0])

    def test_from_trigger_with_blank_source_errors(self):
        rows = [("", "From Trigger", "DesktopReviewStatus")]
        _, _, errors, _ = efa.build_assignments(rows, self.trigger_fields, self.target_fields)
        self.assertIn("Field Name (Current Form) is blank", errors[0])


class ReadMappingTests(unittest.TestCase):
    def test_reads_headers_and_skips_blank_rows(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "map.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Field Name (Current Form)", "Field Assignment Type",
                      "Resolution (Field Name)"])
            ws.append(["WaterHeaterSize", "From Trigger", "ExistingWaterHeaterSize"])
            ws.append([None, None, None])
            ws.append(["Approved", "Constant", "DesktopReviewStatus"])
            wb.save(path)

            title, rows, note = efa.read_mapping(path)
            self.assertEqual(title, "Sheet")
            self.assertIsNone(note)
            self.assertEqual(rows, [
                ("WaterHeaterSize", "From Trigger", "ExistingWaterHeaterSize"),
                ("Approved", "Constant", "DesktopReviewStatus"),
            ])

    def test_missing_column_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "map.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Field Name (Current Form)", "Resolution (Field Name)"])
            ws.append(["WaterHeaterSize", "ExistingWaterHeaterSize"])
            wb.save(path)

            with self.assertRaises(SystemExit):
                efa.read_mapping(path)

    def test_csv_with_positional_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "map.csv"
            path.write_text(
                "EnrollmentForm210,Type,InstallationForm255\n"
                "WaterHeaterSize,FromTrigger,ExistingWaterHeaterSize\n",
                encoding="utf-8")
            title, rows, note = efa.read_mapping(path)
            self.assertEqual(title, "map.csv")
            self.assertIn("positional order", note)
            self.assertEqual(rows, [
                ("WaterHeaterSize", "FromTrigger", "ExistingWaterHeaterSize")])


if __name__ == "__main__":
    unittest.main()
