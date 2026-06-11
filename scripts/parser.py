"""
parser.py — shared JSON parser for form and workflow exports.

Auto-discovers JSON files in data/forms/ and data/workflows/ folders.
Returns structured data for downstream builders (inventory + explorer).
"""
import json
from pathlib import Path

# ── project paths (resolved relative to this script's parent) ──────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = ROOT / "data"
FORMS_DIR    = DATA_DIR / "forms"
WORKFLOWS_DIR = DATA_DIR / "workflows"
MANUAL_DIR   = DATA_DIR / "manual"
OUTPUT_DIR   = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Components that are pure layout containers (not data fields)
LAYOUT_TYPES = {"TwoWideLayout","ThreeWideLayout","FourWideLayout","StackedLayout",
                "FormSection","FormGrid","FormPage","Header","FormComponent"}

# ── form profile parser ────────────────────────────────────────────
def _walk(node, out):
    ep = node.get("ExtraProperties", {}) or {}
    name = ep.get("Name")
    ctype = node.get("ComponentType")
    if name and ctype not in LAYOUT_TYPES:
        meta = {
            "name": name,
            "label": ep.get("Label","") or "",
            "type": node.get("DataType") or "",
            "component": ctype,
            "required": {"1":"Yes","2":"No"}.get(str(ep.get("Required","")), ""),
            "hidden":   {"1":"Yes","2":"No"}.get(str(ep.get("Hidden","")), ""),
            "enabled":  {"1":"Yes","2":"No"}.get(str(ep.get("Enabled","")), ""),
            "relatedForm": "", "relatedField": "", "via": "",
        }
        if ctype == "FormRelationshipInput":
            try:
                rfn = json.loads(ep.get("RelatedFormNormalized","{}"))
                meta["relatedForm"]  = rfn.get("FormName","")
                meta["relatedField"] = rfn.get("FieldName","")
            except Exception: pass
        elif ctype == "FormRelationshipReferenceDataInput":
            try:
                rfn = json.loads(ep.get("ReferenceFieldNormalized","{}"))
                meta["via"]          = rfn.get("RelationshipFieldName","")
                meta["relatedField"] = rfn.get("ReferenceFieldName","")
            except Exception: pass
        out.append(meta)
    for c in node.get("Children", []):
        _walk(c, out)

def parse_form(json_path):
    """Parse a single form design JSON. Returns {name, fields, relationships, refPulls}."""
    d = json.loads(Path(json_path).read_text(encoding="utf-8"))
    fields = []
    _walk(d["Components"][0], fields)

    # form name guessed from filename — override via manual/form_aliases.json if needed
    form_name = _guess_form_name(json_path.stem)

    relationships = []
    ref_pulls = []
    for f in fields:
        if f["component"] == "FormRelationshipInput" and f["relatedForm"]:
            relationships.append({
                "source": form_name, "target": f["relatedForm"],
                "via": f["name"], "label": f["label"],
                "targetMatchField": f["relatedField"],
            })
        elif f["component"] == "FormRelationshipReferenceDataInput":
            ref_pulls.append({
                "destForm": form_name, "destField": f["name"],
                "destLabel": f["label"], "via": f["via"],
                "sourceField": f["relatedField"], "dataType": f["type"],
            })

    return {"name": form_name, "fields": fields,
            "relationships": relationships, "refPulls": ref_pulls}

# Heuristic mapping from filename to display name
NAME_OVERRIDES_FILE = MANUAL_DIR / "form_aliases.json"

def _load_overrides():
    if NAME_OVERRIDES_FILE.exists():
        try:
            return json.loads(NAME_OVERRIDES_FILE.read_text())
        except Exception:
            return {}
    return {}

def canonicalize_name(name):
    """Resolve a display name through the name_aliases section of form_aliases.json.

    Workflow JSON exports sometimes reference forms by an older or abbreviated name
    (e.g. "395X - Inspections") that doesn't match the canonical display name derived
    from the form file ("395 - Inspection Work Order").  Adding an entry to
    data/manual/form_aliases.json under the "name_aliases" key fixes the mismatch
    without touching either source JSON.
    """
    if not name:
        return name
    overrides = _load_overrides()
    aliases = overrides.get("name_aliases", {}) if isinstance(overrides, dict) else {}
    return aliases.get(name, name)

def _guess_form_name(stem):
    """Map a filename stem to a clean display name. Manual overrides take precedence."""
    overrides = _load_overrides()
    if stem in overrides:
        return overrides[stem]
    # Heuristic: strip workspace prefix, version, and design suffix
    # e.g., "so_cal-esa_whole_home_pp_d__300-account_management_v342_design"
    #        →  "300 - Account Management"
    s = stem
    if "__" in s:
        s = s.split("__", 1)[1]
    # drop trailing _vNNN_design or similar
    import re
    s = re.sub(r"_v\d+(_design)?(_+\d*)?$", "", s)
    s = re.sub(r"_design.*$", "", s)
    s = s.replace("_", " ").strip()
    # title-case while preserving leading code
    parts = s.split(" - ", 1) if " - " in s else s.split(" ", 1)
    if len(parts) == 2 and parts[0].rstrip("-").rstrip().isdigit():
        return f"{parts[0].strip()} - {parts[1].title()}"
    return s.title()

# ── workflow parser ────────────────────────────────────────────────
def parse_workflow(json_path, manual_meta=None):
    """Parse a workflow JSON export. Returns structured workflow record."""
    d = json.loads(Path(json_path).read_text(encoding="utf-8"))
    manual_meta = manual_meta or {}

    wf = {
        "callsign": manual_meta.get("callsign", d.get("Name","")[:12].upper().replace(" ","_")),
        "name": d.get("Name",""),
        "description": d.get("Description",""),
        "staging_guid": "",  # populate from triggers below
        "trigger": None,
        "actions": [],
        "fieldUsage": [],
        "externalRefs": d.get("ExternalReferences", []),
    }

    # Normalize form names through name_aliases before building the lookup table so
    # every downstream ref_by_id.get(...).get("FormName") returns the canonical name.
    for ref in wf["externalRefs"]:
        if ref.get("FormName"):
            ref["FormName"] = canonicalize_name(ref["FormName"])

    # Lookup helper for ExternalReferences (turn GUIDs into names)
    ref_by_id = {r.get("RefId"): r for r in wf["externalRefs"]}

    # Triggers (typically one)
    triggers = d.get("Triggers", [])
    if triggers:
        t = triggers[0]
        wf["staging_guid"] = t.get("Id","")
        form_ref = ref_by_id.get(t.get("FormId",""), {})
        cond_summary = _summarize_condition(t.get("ConditionExpression",""), ref_by_id)
        wf["trigger"] = {
            "type": t.get("WorkflowEngineTriggerType",""),
            "form": form_ref.get("FormName", ""),
            "workspace": form_ref.get("WorkspaceName", ""),
            "databaseAction": t.get("WorkflowEngineDatabaseActionType",""),
            "timing": t.get("WorkflowEngineDatabaseActionTiming",""),
            "conditionMode": t.get("WorkflowEngineConditionMode",""),
            "condition": cond_summary,
            "cron": t.get("CronExpression"),
            "timezone": t.get("TimeZoneId"),
        }
        # Condition fields → field usage
        for fld_ref in _extract_condition_fields(t.get("ConditionExpression",""), ref_by_id):
            wf["fieldUsage"].append({
                "form": fld_ref["form"], "field": fld_ref["field"],
                "direction": "Condition", "context": "Trigger condition",
                "stepName": "",
            })

    # Steps + Actions
    for step in d.get("Steps", []):
        for action in step.get("Actions", []):
            params = {p["ParameterName"]: p for p in action.get("Parameters", [])}
            target_form_id = (params.get("TargetResolution.TargetFormId", {}).get("StaticValue")
                              or params.get("FormId", {}).get("StaticValue"))
            target_form = ref_by_id.get(target_form_id, {}).get("FormName", "")
            target_ws   = ref_by_id.get(target_form_id, {}).get("WorkspaceName", "")
            match_summary = _summarize_target_resolution(params, ref_by_id, target_form)
            assignments = _parse_field_assignments(
                params.get("FieldAssignments", {}).get("StaticValue"), target_form)

            wf["actions"].append({
                "stepName": step.get("Name",""),
                "name": action.get("DisplayName",""),
                "type": action.get("ActionType",""),
                "targetForm": target_form,
                "targetWorkspace": target_ws,
                "duplicatePolicy": params.get("DuplicateMatchPolicy", {}).get("StaticValue",""),
                "resolutionType":  params.get("TargetResolution.ResolutionType", {}).get("StaticValue",""),
                "matchOn": match_summary,
                "continueOnError": action.get("ContinueOnError"),
            })
            # Each assignment → write usage row
            for a in assignments:
                wf["fieldUsage"].append({
                    "form": target_form, "field": a["field"],
                    "direction": "Write",
                    "context": a["sourceDesc"],
                    "stepName": step.get("Name",""),
                })

    return wf

def _summarize_condition(expr_json, ref_by_id):
    if not expr_json: return ""
    try:
        e = json.loads(expr_json)
        return _expr_to_text(e, ref_by_id)
    except Exception:
        return "(unparseable)"

def _expr_to_text(node, ref_by_id):
    if not isinstance(node, dict): return ""
    t = node.get("type","")
    if t == "GroupingDto":
        op = {1:" AND ", 2:" OR "}.get(node.get("Operation"), " ")
        return op.join(_expr_to_text(e, ref_by_id) for e in node.get("Expressions",[]))
    if t == "FormFieldComparisonExpressionDto":
        fld = ref_by_id.get(node.get("FormFieldId",""), {})
        fld_name = fld.get("FieldName", "?")
        val = node.get("ResponseFieldValue", {})
        val_text = val.get("Value","?") if val.get("type")=="ConstantTermDto" else val.get("ContextName","?")
        op_map = {1:"==", 2:"!=", 3:"<", 4:"<=", 5:">", 6:">="}
        op = op_map.get(node.get("Operation"), "?")
        return f"{fld_name} {op} '{val_text}'"
    return ""

def _extract_condition_fields(expr_json, ref_by_id):
    """Yield (form, field) pairs referenced in a condition expression."""
    out = []
    if not expr_json: return out
    try:
        e = json.loads(expr_json)
    except Exception:
        return out
    def walk(n):
        if not isinstance(n, dict): return
        if n.get("type") == "FormFieldComparisonExpressionDto":
            fld = ref_by_id.get(n.get("FormFieldId",""), {})
            if fld.get("FieldName"):
                out.append({"form": fld.get("FormName",""), "field": fld.get("FieldName","")})
        for v in n.values():
            if isinstance(v, dict): walk(v)
            elif isinstance(v, list):
                for x in v: walk(x)
    walk(e)
    return out

def _summarize_target_resolution(params, ref_by_id, target_form):
    res = params.get("TargetResolution.FilterExpression", {}).get("StaticValue")
    if not res: return ""
    try:
        e = json.loads(res)
        return _expr_to_text(e, ref_by_id) + (f"  (on {target_form})" if target_form else "")
    except Exception:
        return "(unparseable filter)"

def _parse_field_assignments(json_str, target_form):
    if not json_str: return []
    try:
        items = json.loads(json_str)
    except Exception:
        return []
    out = []
    for it in items:
        fld = it.get("FieldName")
        vt  = it.get("ValueType","")
        v   = it.get("Value","")
        if vt == "FromTrigger":
            desc = f"FromTrigger.{v}"
        elif vt == "TriggerRecordId":
            desc = "TriggerRecordId"
        elif vt == "Static":
            desc = f"Static: {v}"
        else:
            desc = f"{vt}: {v}"
        out.append({"field": fld, "sourceDesc": desc})
    return out

# ── high-level discovery ───────────────────────────────────────────
def discover_all():
    """Walk data folders, parse everything, return a unified dict."""
    forms = []
    fields_by_form = {}
    relationships = []
    ref_pulls = []

    # Forms with parseable JSON
    for json_file in sorted(FORMS_DIR.glob("*.json")):
        parsed = parse_form(json_file)
        forms.append({"name": parsed["name"], "role": _infer_role(parsed),
                      "fieldCount": len(parsed["fields"]),
                      "sourceFile": json_file.name})
        fields_by_form[parsed["name"]] = parsed["fields"]
        relationships.extend(parsed["relationships"])
        ref_pulls.extend(parsed["refPulls"])

    # Auto-add referenced forms that don't have a JSON profile yet
    known = {f["name"] for f in forms}
    referenced = {r["target"] for r in relationships} | {r["source"] for r in relationships}
    for name in sorted(referenced - known):
        forms.append({"name": name, "role": "Lookup", "fieldCount": 0,
                      "sourceFile": None})
        fields_by_form.setdefault(name, [])

    # Workflows
    workflows = []
    workflow_manual = _load_manual_workflow_meta()
    for json_file in sorted(WORKFLOWS_DIR.glob("*.json")):
        manual = workflow_manual.get(json_file.stem, {})
        wf = parse_workflow(json_file, manual)
        wf["sourceFile"] = json_file.name
        workflows.append(wf)

    return {
        "forms": forms,
        "fields": fields_by_form,
        "relationships": relationships,
        "refPulls": ref_pulls,
        "workflows": workflows,
    }

def _infer_role(parsed_form):
    """Hub = has reverse relationships back to multiple spokes. Spoke = has ESAKey. Lookup = no relationships."""
    rels = parsed_form["relationships"]
    if not rels: return "Lookup"
    if any(r["via"].lower() in ("esakey","esa_key") for r in rels):
        return "Spoke"
    if len(rels) >= 4:
        return "Hub"
    return "Spoke"

def _load_manual_workflow_meta():
    f = MANUAL_DIR / "workflow_metadata.json"
    if f.exists():
        try: return json.loads(f.read_text())
        except Exception: return {}
    return {}
