"""Tests for scripts/versioning.py — snapshot capture and comparison."""
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import versioning as v


def _minimal_workspace(slug="demo", form_name="Customer Account"):
    return {
        "slug": slug,
        "workspaceName": f"Demo {slug}",
        "forms": [{"name": form_name, "role": "Hub", "fieldCount": 2,
                   "sourceFile": "base.json", "description": "Main account",
                   "subformOf": "", "duplicateRules": "", "savedFilters": []}],
        "fields": {
            form_name: [
                {"name": "AccountName", "label": "Account Name", "type": "Text",
                 "required": True, "hidden": False, "enabled": True},
                {"name": "Status", "label": "Status", "type": "Text",
                 "required": False, "hidden": False, "enabled": True},
            ],
        },
        "relationships": [],
        "refPulls": [],
        "workflows": [{
            "callsign": "WF1", "name": "On Update", "description": "",
            "workflowType": "Legacy", "enabled": True, "sourceFile": None,
            "trigger": {"form": form_name, "databaseAction": "Update",
                        "timing": "", "condition": "Status == 'Open'", "cron": ""},
            "actions": [{"type": "Notification", "targetForm": "", "name": "Email",
                         "matchOn": "{AccountEmail}"}],
            "fieldUsage": [{"form": form_name, "field": "Status",
                            "direction": "Condition", "context": ""}],
        }],
        "featured": [form_name],
    }


class VersioningTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_dir = v.SNAPSHOTS_DIR
        v.SNAPSHOTS_DIR = Path(self._tmpdir.name)

    def tearDown(self):
        v.SNAPSHOTS_DIR = self._orig_dir
        self._tmpdir.cleanup()

    def test_save_and_load_snapshot(self):
        data = {"demo": _minimal_workspace()}
        entry = v.save_snapshot(data, label="baseline")
        self.assertTrue(entry["id"])
        loaded = v.load_snapshot("latest")
        self.assertEqual(loaded["label"], "baseline")
        self.assertIn("demo", loaded["workspaces"])

    def test_resolve_latest_and_previous(self):
        data = {"demo": _minimal_workspace()}
        v.save_snapshot(data, label="v1")
        v.save_snapshot(data, label="v2")
        latest = v.load_snapshot("latest")
        previous = v.load_snapshot("previous")
        self.assertEqual(latest["label"], "v2")
        self.assertEqual(previous["label"], "v1")

    def test_compare_field_and_workflow_changes(self):
        old = _minimal_workspace()
        new = deepcopy(old)
        new["fields"]["Customer Account"].append(
            {"name": "ZipCode", "label": "ZIP", "type": "Text",
             "required": False, "hidden": False, "enabled": True})
        new["fields"]["Customer Account"][0]["label"] = "Account Name (renamed)"
        new["workflows"][0]["trigger"]["condition"] = "Status == 'Closed'"

        diff = v.compare_workspace(old, new)
        self.assertEqual(diff["forms"]["added"], [])
        self.assertEqual(diff["forms"]["removed"], [])
        self.assertEqual(len(diff["forms"]["modified"]), 1)
        fm = diff["forms"]["modified"][0]
        self.assertIn("ZipCode", fm["fields"]["added"])
        self.assertEqual(fm["fields"]["modified"][0]["key"], "AccountName")
        self.assertTrue(diff["workflows"]["modified"])

    def test_compare_snapshots_report(self):
        old_snap = v.build_snapshot({"demo": _minimal_workspace()}, label="before")
        new_ws = _minimal_workspace()
        new_ws["forms"].append({"name": "Invoice", "role": "Spoke", "fieldCount": 0,
                                "sourceFile": "inv.json", "description": "",
                                "subformOf": "", "duplicateRules": "", "savedFilters": []})
        new_ws["fields"]["Invoice"] = []
        new_snap = v.build_snapshot({"demo": new_ws}, label="after")
        result = v.compare_snapshots(old_snap, new_snap)
        self.assertEqual(result["summary"]["formsAdded"], 1)
        report = v.format_compare_report(result)
        self.assertIn("+ form: Invoice", report)

    def test_version_meta_change_surfaces_in_compare(self):
        old = _minimal_workspace()
        old["forms"][0]["version"] = 207
        new = deepcopy(old)
        new["forms"][0]["version"] = 208
        diff = v.compare_workspace(old, new)
        fm = diff["forms"]["modified"][0]
        self.assertIn({"attribute": "version", "from": 207, "to": 208},
                      fm["metaChanges"])

    def test_compare_survives_snapshot_without_version_key(self):
        # Old snapshots predate the version key entirely — .get() semantics
        # must yield a None -> N change, never a crash.
        old = _minimal_workspace()   # no "version" key at all
        new = deepcopy(old)
        new["forms"][0]["version"] = 208
        diff = v.compare_workspace(old, new)
        fm = diff["forms"]["modified"][0]
        self.assertIn({"attribute": "version", "from": None, "to": 208},
                      fm["metaChanges"])

    def test_snapshot_fingerprint_unchanged(self):
        data = {"demo": _minimal_workspace()}
        s1 = v.build_snapshot(data)
        s2 = v.build_snapshot(data)
        self.assertEqual(v.snapshot_fingerprint(s1), v.snapshot_fingerprint(s2))

    def test_write_compare_report(self):
        old_snap = v.build_snapshot({"demo": _minimal_workspace()})
        new_snap = v.build_snapshot({"demo": _minimal_workspace()})
        result = v.compare_snapshots(old_snap, new_snap)
        path = v.write_compare_report(result)
        self.assertTrue(path.exists())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("summary", payload)

    # ── prune ──────────────────────────────────────────────────────

    def _seed_snapshots(self, entries):
        """Write manifest entries (oldest -> newest) and matching stub files."""
        manifest = []
        for snap_id, label in entries:
            fname = f"{snap_id}.json"
            (v.SNAPSHOTS_DIR / fname).write_text("{}", encoding="utf-8")
            manifest.append({"id": snap_id, "label": label, "created": snap_id,
                             "file": fname, "workspaces": ["demo"],
                             "totals": {"forms": 1, "workflows": 1}})
        v._save_manifest(manifest)

    def test_prune_keeps_newest_unlabeled(self):
        self._seed_snapshots([(f"2026-07-0{i}T00-00-00", "") for i in range(1, 6)])
        removed, kept = v.prune_snapshots(keep=2)
        self.assertEqual([e["id"] for e in removed],
                         [f"2026-07-0{i}T00-00-00" for i in (1, 2, 3)])
        self.assertEqual([e["id"] for e in kept],
                         ["2026-07-04T00-00-00", "2026-07-05T00-00-00"])
        for e in removed:
            self.assertFalse((v.SNAPSHOTS_DIR / e["file"]).exists())
        for e in kept:
            self.assertTrue((v.SNAPSHOTS_DIR / e["file"]).exists())
        # 'previous' still resolves against the pruned manifest
        self.assertTrue(v.resolve_snapshot_ref("previous").name
                        .startswith("2026-07-04"))

    def test_prune_never_removes_labeled(self):
        self._seed_snapshots([
            ("2026-07-01T00-00-00", ""),
            ("2026-07-02T00-00-00_baseline", "baseline"),
            ("2026-07-03T00-00-00", ""),
            ("2026-07-04T00-00-00", ""),
        ])
        removed, kept = v.prune_snapshots(keep=1)
        self.assertEqual([e["id"] for e in removed],
                         ["2026-07-01T00-00-00", "2026-07-03T00-00-00"])
        self.assertEqual([e["id"] for e in kept],
                         ["2026-07-02T00-00-00_baseline", "2026-07-04T00-00-00"])
        self.assertTrue((v.SNAPSHOTS_DIR / "2026-07-02T00-00-00_baseline.json").exists())

    def test_prune_noop_when_under_limit(self):
        self._seed_snapshots([("2026-07-01T00-00-00", ""), ("2026-07-02T00-00-00", "")])
        removed, kept = v.prune_snapshots(keep=5)
        self.assertEqual(removed, [])
        self.assertEqual(len(kept), 2)

    def test_prune_rejects_keep_below_one(self):
        with self.assertRaises(ValueError):
            v.prune_snapshots(keep=0)


if __name__ == "__main__":
    unittest.main()
