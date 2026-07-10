"""Tests for parser.py form version history: _field_delta, helpers, and
discover()-level versionHistory collection / warning policy."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import parser


def _field(name, label=None, ftype="Text", **extra):
    f = {"name": name, "label": label or name, "type": ftype,
         "component": "TextInput", "required": "", "hidden": "", "enabled": ""}
    f.update(extra)
    return f


def _design_json(fields):
    """Minimal individual form design export ({'Components': [...]})."""
    children = [{"ComponentType": "TextInput", "DataType": f["type"],
                 "SortOrder": i,
                 "ExtraProperties": {"Name": f["name"], "Label": f["label"]},
                 "Children": []}
                for i, f in enumerate(fields)]
    return {"Components": [{"ComponentType": "FormComponent",
                            "ExtraProperties": {}, "Children": children}]}


class FieldDeltaTests(unittest.TestCase):
    def test_added_removed_changed(self):
        old = [_field("A"), _field("B", ftype="Text"), _field("C")]
        new = [_field("A"), _field("B", ftype="Integer"), _field("D", "Field D")]
        d = parser._field_delta(old, new)
        self.assertEqual(d["added"], [{"name": "D", "label": "Field D"}])
        self.assertEqual(d["removed"], [{"name": "C", "label": "C"}])
        self.assertEqual(len(d["changed"]), 1)
        self.assertEqual(d["changed"][0]["name"], "B")
        self.assertEqual(d["changed"][0]["attributes"], ["type"])

    def test_depends_on_counts_as_change(self):
        old = [_field("A")]
        new = [dict(_field("A"), dependsOn={"B": ["formula"]})]
        d = parser._field_delta(old, new)
        self.assertEqual(d["changed"][0]["attributes"], ["dependsOn"])

    def test_deterministic_ordering(self):
        old = [_field("Z"), _field("M")]
        new = [_field("A"), _field("B")]
        d = parser._field_delta(old, new)
        self.assertEqual([x["name"] for x in d["added"]], ["A", "B"])
        self.assertEqual([x["name"] for x in d["removed"]], ["M", "Z"])

    def test_no_changes(self):
        fields = [_field("A")]
        d = parser._field_delta(fields, fields)
        self.assertEqual(d, {"added": [], "removed": [], "changed": []})


class HelperTests(unittest.TestCase):
    def test_vfmt(self):
        self.assertEqual(parser._vfmt(208), "v208")
        self.assertEqual(parser._vfmt(-1), "v?")
        self.assertEqual(parser._vfmt(None), "v?")

    def test_delta_phrase(self):
        d = {"added": [1, 2], "removed": [1], "changed": [1, 2, 3]}
        self.assertEqual(parser._delta_phrase(d), "+2 fields, -1 field, 3 changed")
        self.assertEqual(parser._delta_phrase({"added": [], "removed": [], "changed": []}),
                         "no field changes")


class DiscoverHistoryTests(unittest.TestCase):
    """Sandbox workspace on a temp DATA_DIR exercising the version pipeline."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_data_dir = parser.DATA_DIR
        parser.DATA_DIR = Path(self._tmpdir.name)
        self._orig_warnings = list(parser.WARNINGS)
        parser.WARNINGS.clear()

    def tearDown(self):
        parser.DATA_DIR = self._orig_data_dir
        parser.WARNINGS.clear()
        parser.WARNINGS.extend(self._orig_warnings)
        self._tmpdir.cleanup()

    def _make_workspace(self, files):
        """files: {relative path under data/sandbox/: fields list}."""
        root = parser.DATA_DIR / "sandbox"
        aliases = {}
        for rel, fields in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_design_json(fields)), encoding="utf-8")
            aliases[path.stem] = "Test Form"
        manual = root / "manual"
        manual.mkdir(parents=True, exist_ok=True)
        (manual / "form_aliases.json").write_text(json.dumps(aliases),
                                                  encoding="utf-8")
        return parser.Workspace("sandbox")

    def test_version_history_latest_wins(self):
        ws = self._make_workspace({
            "forms/Test Form/test_form_v1_design.json": [_field("A"), _field("B")],
            "forms/Test Form/test_form_v2_design.json": [_field("A"), _field("C", "Field C")],
        })
        data = ws.discover()
        form = next(f for f in data["forms"] if f["name"] == "Test Form")
        self.assertEqual(form["version"], 2)
        hist = form["versionHistory"]
        self.assertEqual([h["version"] for h in hist], [1, 2])
        self.assertIsNone(hist[0]["fieldDelta"])
        self.assertEqual(hist[1]["fieldDelta"]["added"],
                         [{"name": "C", "label": "Field C"}])
        self.assertEqual(hist[1]["fieldDelta"]["removed"],
                         [{"name": "B", "label": "B"}])
        # Active fields are v2's.
        names = {f["name"] for f in data["fields"]["Test Form"]}
        self.assertEqual(names, {"A", "C"})
        # Intentional history: no "multiple exports" warning.
        self.assertFalse([w for w in parser.WARNINGS if "multiple exports" in w])

    def test_same_version_tie_warns(self):
        ws = self._make_workspace({
            "forms/Test Form/test_form_v2_design.json": [_field("A")],
            "forms/Test Form/test_form_v2_design__1_.json": [_field("A")],
        })
        ws.discover()
        ties = [w for w in parser.WARNINGS
                if "multiple exports with the same version" in w]
        self.assertTrue(ties)

    def test_single_version_form(self):
        ws = self._make_workspace({
            "forms/Test Form/test_form_v3_design.json": [_field("A")],
        })
        data = ws.discover()
        form = next(f for f in data["forms"] if f["name"] == "Test Form")
        self.assertEqual(form["version"], 3)
        self.assertEqual(len(form["versionHistory"]), 1)
        self.assertFalse([w for w in parser.WARNINGS if "multiple exports" in w])


if __name__ == "__main__":
    unittest.main()
