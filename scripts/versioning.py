"""
versioning.py — snapshot capture and comparison for discovered workspace state.

Serializes the normalized output of Workspace.discover() / discover_all() so
rebuilds can be compared over time. Snapshots live under output/snapshots/ and
are intended to be git-tracked alongside other build artifacts.

Comparison reports forms, fields, workflows, relationships, and ref-pulls at
a granularity suitable for impact review before or after a platform change.
"""
from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_registry import _exact_hash, _form_fingerprint
from parser import FIELD_COMPARE_KEYS as _FIELD_COMPARE_KEYS

SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "output" / "snapshots"
MANIFEST_NAME = "manifest.json"

# How many unlabeled snapshots to retain when pruning (labeled snapshots are
# always kept -- a label marks a deliberately pinned baseline).
DEFAULT_KEEP = 5

# Form metadata keys compared (excluding fieldCount — derived; versionHistory
# is deliberately absent — version bumps already surface as a `version` meta
# line plus field-level diffs, so diffing the history itself would be noise).
_FORM_META_KEYS = ("role", "description", "subformOf", "sourceFile",
                   "duplicateRules", "savedFilters", "version")

_WF_META_KEYS = ("callsign", "description", "workflowType", "enabled", "sourceFile")
_TRIGGER_KEYS = ("form", "databaseAction", "timing", "condition", "cron")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug_id(label: str | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    if not label:
        return stamp
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", label.strip()).strip("-")[:48]
    return f"{stamp}_{safe}" if safe else stamp


def _rel_key(r: dict) -> tuple:
    return (r.get("source", ""), r.get("target", ""), r.get("via", ""),
            r.get("label", ""), r.get("targetMatchField", ""))


def _pull_key(p: dict) -> tuple:
    return (p.get("destForm", ""), p.get("destField", ""),
            p.get("sourceField", ""), p.get("via", ""))


def _wf_key(wf: dict) -> tuple:
    tr = wf.get("trigger") or {}
    return (tr.get("form", "") or "", wf.get("name", "") or "")


def _fields_by_name(fields: list[dict]) -> dict[str, dict]:
    return {f["name"]: f for f in fields}


def _form_fingerprint_local(fields: list[dict]) -> str:
    return _form_fingerprint(fields)[0]


def _workflow_signature(wf: dict) -> str:
    return _exact_hash(wf)


def normalize_discovered(data: dict) -> dict:
    """Return a JSON-serializable copy of one workspace's discover() output."""
    out = {
        "slug": data["slug"],
        "workspaceName": data.get("workspaceName", data["slug"]),
        "forms": deepcopy(data["forms"]),
        "fields": deepcopy(data["fields"]),
        "relationships": deepcopy(data["relationships"]),
        "refPulls": deepcopy(data["refPulls"]),
        "workflows": deepcopy(data["workflows"]),
        "featured": list(data.get("featured") or []),
    }
    return out


def build_snapshot(discovered_all: dict[str, dict], label: str | None = None) -> dict:
    """Assemble a snapshot dict from discover_all() output."""
    workspaces = {slug: normalize_discovered(d) for slug, d in discovered_all.items()}
    counts = {}
    for slug, d in workspaces.items():
        counts[slug] = {
            "forms": len(d["forms"]),
            "workflows": len(d["workflows"]),
            "relationships": len(d["relationships"]),
            "refPulls": len(d["refPulls"]),
            "fields": sum(len(v) for v in d["fields"].values()),
        }
    snap_id = _slug_id(label)
    return {
        "id": snap_id,
        "label": label or "",
        "created": _utc_now(),
        "workspaces": workspaces,
        "counts": counts,
    }


def _load_manifest() -> list[dict]:
    path = SNAPSHOTS_DIR / MANIFEST_NAME
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(entries: list[dict]) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOTS_DIR / MANIFEST_NAME).write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def save_snapshot(discovered_all: dict[str, dict], label: str | None = None) -> dict:
    """Persist a snapshot file and update the manifest. Returns snapshot metadata."""
    snap = build_snapshot(discovered_all, label=label)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{snap['id']}.json"
    path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")

    manifest = _load_manifest()
    entry = {
        "id": snap["id"],
        "label": snap["label"],
        "created": snap["created"],
        "file": path.name,
        "workspaces": sorted(snap["workspaces"].keys()),
        "totals": {
            "forms": sum(c["forms"] for c in snap["counts"].values()),
            "workflows": sum(c["workflows"] for c in snap["counts"].values()),
        },
    }
    manifest.append(entry)
    _save_manifest(manifest)
    return entry


def list_snapshots() -> list[dict]:
    """Return manifest entries newest-first."""
    return list(reversed(_load_manifest()))


def prune_snapshots(keep: int = DEFAULT_KEEP) -> tuple[list[dict], list[dict]]:
    """Delete old unlabeled snapshots, keeping the newest `keep` of them.

    Labeled snapshots are never pruned -- a label marks a deliberately pinned
    baseline (e.g. 'pre-migration'). Deletes the snapshot files and drops
    their manifest entries so refs like 'previous' stay consistent.
    Returns (removed_entries, kept_entries).
    """
    if keep < 1:
        raise ValueError("keep must be >= 1")
    manifest = _load_manifest()  # oldest -> newest
    unlabeled = [e for e in manifest if not e.get("label")]
    doomed = unlabeled[:-keep] if len(unlabeled) > keep else []
    if not doomed:
        return [], manifest
    doomed_ids = {e["id"] for e in doomed}
    kept = [e for e in manifest if e["id"] not in doomed_ids]
    for e in doomed:
        path = SNAPSHOTS_DIR / e["file"]
        if path.exists():
            path.unlink()
    _save_manifest(kept)
    return doomed, kept


def resolve_snapshot_ref(ref: str) -> Path:
    """Resolve a snapshot reference (id, label, latest, previous) to a file path."""
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("snapshot reference is required")

    entries = list_snapshots()  # newest first
    if not entries:
        raise FileNotFoundError("no snapshots found under output/snapshots/")

    lowered = ref.casefold()
    if lowered == "latest":
        return SNAPSHOTS_DIR / entries[0]["file"]
    if lowered == "previous":
        if len(entries) < 2:
            raise FileNotFoundError("only one snapshot exists; 'previous' is unavailable")
        return SNAPSHOTS_DIR / entries[1]["file"]

    for e in entries:
        if e["id"] == ref or e["id"].startswith(ref):
            return SNAPSHOTS_DIR / e["file"]
        if e.get("label") and e["label"].casefold() == lowered:
            return SNAPSHOTS_DIR / e["file"]

    path = SNAPSHOTS_DIR / (ref if ref.endswith(".json") else f"{ref}.json")
    if path.exists():
        return path
    raise FileNotFoundError(f"snapshot not found: {ref}")


def load_snapshot(ref: str) -> dict:
    path = resolve_snapshot_ref(ref)
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_field(old: dict, new: dict) -> list[dict]:
    changes = []
    for key in _FIELD_COMPARE_KEYS:
        ov, nv = old.get(key), new.get(key)
        if ov != nv:
            changes.append({"attribute": key, "from": ov, "to": nv})
    old_dep = old.get("dependsOn") or {}
    new_dep = new.get("dependsOn") or {}
    if old_dep != new_dep:
        changes.append({"attribute": "dependsOn", "from": old_dep, "to": new_dep})
    return changes


def _compare_form_meta(old: dict, new: dict) -> list[dict]:
    changes = []
    for key in _FORM_META_KEYS:
        ov, nv = old.get(key), new.get(key)
        if ov != nv:
            changes.append({"attribute": key, "from": ov, "to": nv})
    return changes


def _compare_workflow(old: dict, new: dict) -> list[dict]:
    changes = []
    for key in _WF_META_KEYS:
        ov, nv = old.get(key), new.get(key)
        if ov != nv:
            changes.append({"attribute": key, "from": ov, "to": nv})
    otr, ntr = old.get("trigger") or {}, new.get("trigger") or {}
    for key in _TRIGGER_KEYS:
        ov, nv = otr.get(key), ntr.get(key)
        if ov != nv:
            changes.append({"attribute": f"trigger.{key}", "from": ov, "to": nv})
    if _workflow_signature(old) != _workflow_signature(new):
        changes.append({
            "attribute": "signature",
            "from": _workflow_signature(old)[:12],
            "to": _workflow_signature(new)[:12],
        })
    return changes


def _compare_list_items(old_items: list[dict], new_items: list[dict],
                        key_fn, compare_fn=None) -> dict:
    old_map = {key_fn(x): x for x in old_items}
    new_map = {key_fn(x): x for x in new_items}
    added = sorted(k for k in new_map if k not in old_map)
    removed = sorted(k for k in old_map if k not in new_map)
    modified = []
    for k in sorted(old_map.keys() & new_map.keys()):
        if compare_fn:
            ch = compare_fn(old_map[k], new_map[k])
            if ch:
                modified.append({"key": k, "changes": ch})
        elif old_map[k] != new_map[k]:
            modified.append({"key": k, "changes": [{"attribute": "value",
                                                    "from": old_map[k],
                                                    "to": new_map[k]}]})
    return {"added": added, "removed": removed, "modified": modified}


def compare_workspace(old: dict, new: dict) -> dict:
    """Compare two single-workspace discovered dicts."""
    old_forms = {f["name"]: f for f in old["forms"]}
    new_forms = {f["name"]: f for f in new["forms"]}
    old_fields = old["fields"]
    new_fields = new["fields"]

    forms_added = sorted(new_forms.keys() - old_forms.keys())
    forms_removed = sorted(old_forms.keys() - new_forms.keys())
    forms_modified = []

    for name in sorted(old_forms.keys() & new_forms.keys()):
        meta_changes = _compare_form_meta(old_forms[name], new_forms[name])
        fp_old = _form_fingerprint_local(old_fields.get(name, []))
        fp_new = _form_fingerprint_local(new_fields.get(name, []))
        field_diff = _compare_list_items(
            old_fields.get(name, []), new_fields.get(name, []),
            key_fn=lambda f: f["name"],
            compare_fn=_compare_field,
        )
        if meta_changes or fp_old != fp_new or any(
                field_diff[k] for k in ("added", "removed", "modified")):
            forms_modified.append({
                "name": name,
                "metaChanges": meta_changes,
                "fingerprintChanged": fp_old != fp_new,
                "fingerprint": {"from": fp_old[:12], "to": fp_new[:12]},
                "fields": field_diff,
            })

    workflows = _compare_list_items(
        old["workflows"], new["workflows"], key_fn=_wf_key, compare_fn=_compare_workflow)
    relationships = _compare_list_items(
        old["relationships"], new["relationships"], key_fn=_rel_key)
    ref_pulls = _compare_list_items(
        old["refPulls"], new["refPulls"], key_fn=_pull_key)

    return {
        "slug": new.get("slug", old.get("slug", "")),
        "workspaceName": new.get("workspaceName", old.get("workspaceName", "")),
        "forms": {
            "added": forms_added,
            "removed": forms_removed,
            "modified": forms_modified,
        },
        "workflows": workflows,
        "relationships": relationships,
        "refPulls": ref_pulls,
    }


def compare_snapshots(old_snap: dict, new_snap: dict,
                      workspace: str | None = None) -> dict:
    """Compare two full snapshots, optionally scoped to one workspace slug."""
    old_ws = old_snap["workspaces"]
    new_ws = new_snap["workspaces"]
    slugs = sorted(set(old_ws) | set(new_ws))
    if workspace:
        slugs = [workspace] if workspace in slugs else [workspace]

    result = {
        "from": {"id": old_snap["id"], "label": old_snap.get("label", ""),
                 "created": old_snap["created"]},
        "to": {"id": new_snap["id"], "label": new_snap.get("label", ""),
               "created": new_snap["created"]},
        "workspaces": {},
    }

    for slug in slugs:
        if slug not in old_ws:
            result["workspaces"][slug] = {"status": "added",
                                          "counts": new_snap["counts"].get(slug, {})}
            continue
        if slug not in new_ws:
            result["workspaces"][slug] = {"status": "removed",
                                          "counts": old_snap["counts"].get(slug, {})}
            continue
        diff = compare_workspace(old_ws[slug], new_ws[slug])
        if _workspace_has_changes(diff):
            result["workspaces"][slug] = {"status": "changed", "diff": diff}
        else:
            result["workspaces"][slug] = {"status": "unchanged"}

    result["summary"] = _summarize_compare(result)
    return result


def _workspace_has_changes(diff: dict) -> bool:
    if diff["forms"]["added"] or diff["forms"]["removed"] or diff["forms"]["modified"]:
        return True
    for section in ("workflows", "relationships", "refPulls"):
        d = diff[section]
        if d["added"] or d["removed"] or d["modified"]:
            return True
    return False


def _summarize_compare(result: dict) -> dict:
    ws = result["workspaces"]
    return {
        "workspacesAdded": sum(1 for v in ws.values() if v["status"] == "added"),
        "workspacesRemoved": sum(1 for v in ws.values() if v["status"] == "removed"),
        "workspacesChanged": sum(1 for v in ws.values() if v["status"] == "changed"),
        "workspacesUnchanged": sum(1 for v in ws.values() if v["status"] == "unchanged"),
        "formsAdded": sum(len(v.get("diff", {}).get("forms", {}).get("added", []))
                          for v in ws.values() if v["status"] == "changed"),
        "formsRemoved": sum(len(v.get("diff", {}).get("forms", {}).get("removed", []))
                            for v in ws.values() if v["status"] == "changed"),
        "formsModified": sum(len(v.get("diff", {}).get("forms", {}).get("modified", []))
                             for v in ws.values() if v["status"] == "changed"),
        "workflowsChanged": sum(
            len(v.get("diff", {}).get("workflows", {}).get("added", [])) +
            len(v.get("diff", {}).get("workflows", {}).get("removed", [])) +
            len(v.get("diff", {}).get("workflows", {}).get("modified", []))
            for v in ws.values() if v["status"] == "changed"),
    }


def _fmt_key(key) -> str:
    if isinstance(key, tuple):
        return " / ".join(str(p) for p in key if p != "")
    return str(key)


def format_compare_report(result: dict) -> str:
    """Render a human-readable comparison report for the console."""
    lines = []
    fr, to = result["from"], result["to"]
    lines.append(f"Comparing snapshot '{fr['id']}' ({fr['created']})")
    if fr.get("label"):
        lines.append(f"  label: {fr['label']}")
    lines.append(f"       -> '{to['id']}' ({to['created']})")
    if to.get("label"):
        lines.append(f"  label: {to['label']}")
    lines.append("")

    s = result["summary"]
    lines.append(
        f"Summary: {s['workspacesChanged']} workspace(s) changed, "
        f"{s['workspacesAdded']} added, {s['workspacesRemoved']} removed, "
        f"{s['workspacesUnchanged']} unchanged"
    )
    if s["workspacesChanged"]:
        lines.append(
            f"  Forms: +{s['formsAdded']} -{s['formsRemoved']} "
            f"~{s['formsModified']} modified | "
            f"Workflow deltas: {s['workflowsChanged']}"
        )
    lines.append("")

    for slug, info in sorted(result["workspaces"].items()):
        status = info["status"]
        if status == "unchanged":
            continue
        if status == "added":
            c = info.get("counts", {})
            lines.append(f"[{slug}] NEW workspace "
                         f"({c.get('forms', 0)} forms, {c.get('workflows', 0)} workflows)")
            continue
        if status == "removed":
            c = info.get("counts", {})
            lines.append(f"[{slug}] REMOVED workspace "
                         f"(was {c.get('forms', 0)} forms, {c.get('workflows', 0)} workflows)")
            continue

        diff = info["diff"]
        lines.append(f"[{slug}] {diff.get('workspaceName', slug)}")
        for name in diff["forms"]["added"]:
            lines.append(f"  + form: {name}")
        for name in diff["forms"]["removed"]:
            lines.append(f"  - form: {name}")
        for fm in diff["forms"]["modified"]:
            lines.append(f"  ~ form: {fm['name']}")
            for ch in fm.get("metaChanges", []):
                lines.append(f"      {ch['attribute']}: {ch['from']!r} -> {ch['to']!r}")
            fd = fm["fields"]
            for fname in fd["added"]:
                lines.append(f"      + field: {fname}")
            for fname in fd["removed"]:
                lines.append(f"      - field: {fname}")
            for mod in fd["modified"]:
                attrs = ", ".join(c["attribute"] for c in mod["changes"])
                lines.append(f"      ~ field: {mod['key']} ({attrs})")

        for section, label in (("workflows", "workflow"), ("relationships", "relationship"),
                               ("refPulls", "ref pull")):
            d = diff[section]
            for key in d["added"]:
                lines.append(f"  + {label}: {_fmt_key(key)}")
            for key in d["removed"]:
                lines.append(f"  - {label}: {_fmt_key(key)}")
            for mod in d["modified"]:
                attrs = ", ".join(c["attribute"] for c in mod["changes"])
                lines.append(f"  ~ {label}: {_fmt_key(mod['key'])} ({attrs})")
        lines.append("")

    if s["workspacesChanged"] == 0 and s["workspacesAdded"] == 0 and s["workspacesRemoved"] == 0:
        lines.append("No differences found.")

    return "\n".join(lines).rstrip() + "\n"


def write_compare_report(result: dict, path: Path | None = None) -> Path:
    """Write JSON compare result; default path under output/snapshots/."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if path is None:
        fr, to = result["from"]["id"], result["to"]["id"]
        path = SNAPSHOTS_DIR / f"compare_{fr}_to_{to}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def snapshot_fingerprint(snap: dict) -> str:
    """Stable hash of entire snapshot content (for quick equality checks)."""
    blob = json.dumps(snap["workspaces"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()
