"""
build_explorer.py — generate the interactive HTML map from parsed data.
Outputs to output/workspace_explorer.html.
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import discover_all, OUTPUT_DIR

TEMPLATE = (Path(__file__).resolve().parent / "explorer_template.html").read_text(encoding="utf-8")

def build():
    data = discover_all()

    # Reshape for the viewer (it expects a specific shape)
    viz_data = {
        "forms": [{"name": f["name"], "role": f["role"], "fieldCount": f["fieldCount"]}
                  for f in data["forms"]],
        "fields": data["fields"],
        "relationships": [{"source": r["source"], "target": r["target"],
                           "via": r["via"], "label": r["label"]}
                          for r in data["relationships"]],
        "refPulls": [{"destForm": r["destForm"], "destField": r["destField"],
                      "via": r["via"], "sourceField": r["sourceField"]}
                     for r in data["refPulls"]],
        "workflows": [{
            "callsign": w["callsign"], "name": w["name"],
            "trigger": {
                "form": w["trigger"]["form"] if w["trigger"] else "",
                "field": "",  # legacy field, unused
                "type": (w["trigger"]["type"] + " · " + w["trigger"]["databaseAction"]) if w["trigger"] else "",
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
    html = TEMPLATE.replace("__DATA__", data_json)
    out = OUTPUT_DIR / "workspace_explorer.html"
    out.write_text(html, encoding="utf-8")
    print(f"  Saved -> {out.relative_to(OUTPUT_DIR.parent)}  ({out.stat().st_size/1024:.1f} KB)")

if __name__ == "__main__":
    build()
