"""
build_explorer.py — generate a workspace's interactive HTML map.
Outputs to output/<workspace-slug>/workspace_explorer.html.
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import Workspace, list_workspaces, OUTPUT_DIR

TEMPLATE = (Path(__file__).resolve().parent / "explorer_template.html").read_text(encoding="utf-8")

def build(ws):
    data = ws.discover()

    # Reshape for the viewer (it expects a specific shape)
    viz_data = {
        "forms": [{"name": f["name"], "role": f["role"], "fieldCount": f["fieldCount"],
                   "description": f.get("description", ""),
                   "subformOf": f.get("subformOf", "")}
                  for f in data["forms"]],
        "fields": data["fields"],
        "relationships": [{"source": r["source"], "target": r["target"],
                           "via": r["via"], "label": r["label"],
                           "targetMatchField": r.get("targetMatchField", "")}
                          for r in data["relationships"]],
        "refPulls": [{"destForm": r["destForm"], "destField": r["destField"],
                      "via": r["via"], "sourceField": r["sourceField"]}
                     for r in data["refPulls"]],
        "workflows": [{
            "callsign": w["callsign"], "name": w["name"],
            "enabled": w.get("enabled", True),
            "trigger": {
                "form": w["trigger"]["form"] if w["trigger"] else "",
                "field": "",  # legacy field, unused
                # Type · action, plus the schedule text for scheduled workflows.
                "type": " · ".join(x for x in (w["trigger"]["type"],
                                               w["trigger"]["databaseAction"],
                                               w["trigger"]["cron"] or "") if x) if w["trigger"] else "",
                "condition": w["trigger"]["condition"] if w["trigger"] else "",
            } if w["trigger"] else None,
            "actions": [{
                "name": a["name"], "type": a["type"],
                "targetForm": a["targetForm"], "duplicatePolicy": a["duplicatePolicy"],
                "matchOn": a["matchOn"],
            } for a in w["actions"]],
            "fieldUsage": [{"form": u["form"], "field": u["field"],
                            "direction": u["direction"], "context": u["context"]}
                           for u in w["fieldUsage"]],
        } for w in data["workflows"] if w["trigger"]]
    }

    data_json = json.dumps(viz_data, separators=(",", ":")).replace("</", "<\\/")
    preset_json = json.dumps(ws.explorer_layout(), separators=(",", ":"))
    html = (TEMPLATE
            .replace("__DATA__", data_json)
            .replace("__PRESET__", preset_json)
            .replace("__TITLE__", data["workspaceName"]))

    out_dir = OUTPUT_DIR / ws.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "workspace_explorer.html"
    out.write_text(html, encoding="utf-8")
    print(f"  Saved -> {out.relative_to(OUTPUT_DIR.parent)}  ({out.stat().st_size/1024:.1f} KB)")

if __name__ == "__main__":
    for slug in list_workspaces():
        print(f"[{slug}]")
        build(Workspace(slug))
