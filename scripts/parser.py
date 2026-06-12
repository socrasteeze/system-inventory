"""
parser.py — shared JSON parser for form and workflow exports.

A workspace is a directory under data/<slug>/ holding forms/, workflows/, and
manual/ subfolders. Workspace(slug).discover() parses one workspace into a
normalized dict; list_workspaces() enumerates every workspace on disk. The
per-workspace builders (build_inventory, build_explorer) consume one workspace;
build_global aggregates across all of them.
"""
import json
import re
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR   = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Components that are pure layout containers (not data fields)
LAYOUT_TYPES = {"TwoWideLayout","ThreeWideLayout","FourWideLayout","StackedLayout",
                "FormSection","FormGrid","FormPage","Header","FormComponent"}

# ── field-level configuration extraction ────────────────────────────
# Form designs carry per-field logic that references other fields on the same
# form: computed formulas, conditional visibility/required rules, picklist
# filters, default values, and validators. Field references appear two ways —
# as a .Fields[].FieldName array on code-based (JS) rules, and as "@Field.X"
# tokens inside builder expressions (sometimes base64-encoded). _config_field_refs
# pulls both so we can build the intra-form "depends on" graph.

def _decode_b64_json(s):
    try:
        return json.loads(base64.b64decode(s).decode("utf-8"))
    except Exception:
        return None

def _as_config_obj(value):
    """A config value may be a dict, a JSON string, or a base64-encoded expression."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        s = value.strip()
        if s.startswith("{"):
            try:
                return json.loads(s)
            except Exception:
                return None
        return _decode_b64_json(s)
    return None

def _config_field_refs(value, own_name=None):
    """Local field names a config references: .Fields[].FieldName plus @Field.X tokens."""
    refs = set()
    obj = _as_config_obj(value)
    if isinstance(obj, dict):
        for fr in obj.get("Fields") or []:
            fn = fr.get("FieldName")
            if fn:
                refs.add(fn)
        refs |= set(re.findall(r"@Field\.([A-Za-z0-9_]+)", json.dumps(obj)))
    if isinstance(value, str):
        refs |= set(re.findall(r"@Field\.([A-Za-z0-9_]+)", value))
    refs.discard(own_name)
    return sorted(refs)

def _clean_formula(code):
    """Drop the boilerplate JSDoc header and collapse whitespace from a JS formula."""
    code = re.sub(r"/\*\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"\s+", " ", code).strip()

def _extract_field_config(node, own_name):
    """Field-level config + the fields each piece references (the intra-form depends-on)."""
    ep = node.get("ExtraProperties", {}) or {}
    deps = {"validation": [], "formula": [], "filter": [], "visibility": []}

    validator = node.get("Validator") if isinstance(node.get("Validator"), str) else ""
    dv = ep.get("DefaultValue")
    default_value = str(dv) if dv not in (None, "") else ""

    formula = ""
    formula_cfg = ep.get("AdvancedConfiguration") or ep.get("ValueAdvancedConfiguration")
    if formula_cfg:
        obj = _as_config_obj(formula_cfg)
        if isinstance(obj, dict) and obj.get("Configuration"):
            formula = _clean_formula(obj["Configuration"])
        deps["formula"] = _config_field_refs(formula_cfg, own_name)

    visibility = ""
    if ep.get("HiddenAdvancedConfiguration"):
        visibility = "Yes"
        deps["visibility"] = _config_field_refs(ep["HiddenAdvancedConfiguration"], own_name)

    if ep.get("RequiredAdvancedConfiguration"):
        deps["validation"] = _config_field_refs(ep["RequiredAdvancedConfiguration"], own_name)

    filt = ""
    filter_node = node.get("Filter")
    if isinstance(filter_node, str) and filter_node:
        filt = "Yes"
        deps["filter"] = _config_field_refs(filter_node, own_name)
    elif isinstance(filter_node, dict) and filter_node:
        # Workspace exports carry the filter as a parsed expression dict whose
        # field refs are GUIDs; the caller resolves those (needs the GUID index).
        filt = "Yes"
    elif ep.get("HasFilter") == "True":
        filt = "Yes"

    return {
        "validator": validator,
        "formula": formula,
        "filter": filt,
        "visibility": visibility,
        "defaultValue": default_value,
        "dependsOn": deps,
        "dependsOnAll": sorted({f for lst in deps.values() for f in lst}),
    }

# ── pure parsing helpers (no filesystem access) ─────────────────────
def _node_to_field(node, ctype):
    """One design component -> one field meta dict. Shared by both formats:
    the individual-export tree walk (_walk) and the workspace-export flat list.
    Resolves the name-based (Normalized) relationship payloads here; the
    workspace export's GUID-based payloads are resolved by the caller, which
    owns the GUID->name index."""
    ep = node.get("ExtraProperties", {}) or {}
    name = ep.get("Name")
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
    meta.update(_extract_field_config(node, name))
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
    return meta

def _walk(node, out):
    ep = node.get("ExtraProperties", {}) or {}
    name = ep.get("Name")
    ctype = node.get("ComponentType")
    if name and ctype not in LAYOUT_TYPES:
        out.append(_node_to_field(node, ctype))
    for c in node.get("Children", []):
        _walk(c, out)

def _as_expr(expr):
    """Condition expressions arrive as JSON strings (individual exports) or as
    already-parsed dicts (workspace exports). Normalize to a dict or None."""
    if isinstance(expr, dict):
        return expr
    if isinstance(expr, str) and expr.strip():
        try:
            return json.loads(expr)
        except Exception:
            return "(unparseable)"
    return None

def _summarize_condition(expr_json, ref_by_id):
    e = _as_expr(expr_json)
    if e == "(unparseable)": return "(unparseable)"
    if not e: return ""
    return _expr_to_text(e, ref_by_id)

def _expr_to_text(node, ref_by_id):
    # Type names carry a "Dto" suffix in individual exports ("GroupingDto") but
    # not in workspace exports ("Grouping") — match on the prefix.
    if not isinstance(node, dict): return ""
    t = node.get("type","") or ""
    if t.startswith("Grouping"):
        op = {1:" AND ", 2:" OR "}.get(node.get("Operation"), " ")
        return op.join(_expr_to_text(e, ref_by_id) for e in node.get("Expressions",[]))
    if t.startswith("FormFieldComparisonExpression"):
        fld = ref_by_id.get(node.get("FormFieldId",""), {})
        fld_name = fld.get("FieldName", "?")
        val = node.get("ResponseFieldValue") or {}
        val_text = val.get("Value","?") if str(val.get("type","")).startswith("ConstantTerm") else val.get("ContextName","?")
        op_map = {1:"==", 2:"!=", 3:"<", 4:"<=", 5:">", 6:">="}
        op = op_map.get(node.get("Operation"), "?")
        return f"{fld_name} {op} '{val_text}'"
    return ""

def _extract_condition_fields(expr_json, ref_by_id):
    """Yield (form, field) pairs referenced in a condition expression."""
    out = []
    e = _as_expr(expr_json)
    if not isinstance(e, dict): return out
    def walk(n):
        if not isinstance(n, dict): return
        if (n.get("type") or "").startswith("FormFieldComparisonExpression"):
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

def _infer_role(parsed_form):
    """Hub = has reverse relationships back to multiple spokes. Spoke = has ESAKey. Lookup = no relationships."""
    rels = parsed_form["relationships"]
    if not rels: return "Lookup"
    if any(r["via"].lower() in ("esakey","esa_key") for r in rels):
        return "Spoke"
    if len(rels) >= 4:
        return "Hub"
    return "Spoke"

# ── export-format detection ─────────────────────────────────────────
def detect_format(d):
    """Classify an export JSON by its root shape.

    - workspace : whole-workspace export (root Forms array + workspace metadata)
    - form      : individual form design export (root Components tree)
    - workflow  : individual workflow export (root Triggers/Steps)
    """
    if not isinstance(d, dict):
        return "unknown"
    if isinstance(d.get("Forms"), list) and ("Name" in d or "DisplayName" in d):
        return "workspace"
    if "Components" in d:
        return "form"
    if "Triggers" in d or "Steps" in d:
        return "workflow"
    return "unknown"

# ── workspace-export parsing ────────────────────────────────────────
# The whole-workspace export is GUID-based where the individual exports are
# name-based: relationships, reference pulls, and trigger conditions all point
# at FormId / FieldId GUIDs that resolve within the same file. Everything below
# normalizes that into the exact internal shapes parse_form / parse_workflow
# produce, so downstream builders never know which format the data came from.

SCHEDULE_FREQ = {1: "Daily", 2: "Weekly", 3: "Monthly", 4: "Yearly"}

def _loads_maybe(s):
    """Parse a value that may be a JSON string or already a dict."""
    if isinstance(s, dict): return s
    if isinstance(s, str) and s.strip():
        try: return json.loads(s)
        except Exception: return None
    return None

def _expr_field_ids(expr):
    """All FormFieldId GUIDs referenced anywhere in an expression dict."""
    ids = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("FormFieldId"): ids.append(n["FormFieldId"])
            for v in n.values(): walk(v)
        elif isinstance(n, list):
            for x in n: walk(x)
    walk(expr)
    return ids

def _minimal_field(name, label, dtype):
    """Field meta for fields known only from the flattened Fields array
    (subforms have no design tree; some fields exist off-design)."""
    return {"name": name, "label": label or "", "type": dtype or "", "component": "",
            "required": "", "hidden": "", "enabled": "",
            "relatedForm": "", "relatedField": "", "via": "",
            "validator": "", "formula": "", "filter": "", "visibility": "",
            "defaultValue": "",
            "dependsOn": {"validation": [], "formula": [], "filter": [], "visibility": []},
            "dependsOnAll": []}

def _ws_display_names(raw_forms):
    """Resolve each form entry to a unique display name.

    DisplayName is taken as-is; duplicates (the export can carry two grids with
    the same name under different parents) get parent-qualified, and anything
    still colliding gets a numeric suffix. Returns {form Id: display name}."""
    base = {f["Id"]: (f.get("DisplayName") or f.get("Name") or f.get("ReportingName") or f["Id"])
            for f in raw_forms}
    counts = {}
    for n in base.values():
        counts[n] = counts.get(n, 0) + 1
    resolved, used = {}, set()
    for f in raw_forms:
        name = base[f["Id"]]
        if counts[name] > 1 and f.get("TopLevelFormId") and f["TopLevelFormId"] != f["Id"]:
            parent = base.get(f["TopLevelFormId"])
            if parent:
                name = f"{name} ({parent})"
        i = 2
        while name in used:
            name = f"{base[f['Id']]} #{i}"; i += 1
        used.add(name)
        resolved[f["Id"]] = name
    return resolved

def _ws_parse_form(raw, display, form_name_by_id, field_index, subform_of):
    """One Forms[] entry -> the parse_form shape (+ workspace-only extras).

    field_index: {field Id: (form display name, field name)} across the export.
    """
    fields, relationships, ref_pulls = [], [], []
    components = (raw.get("FormDesign") or {}).get("Components") or []

    for node in components:
        ctype = node.get("FormDesignComponentType")
        ep = node.get("ExtraProperties") or {}
        if not ep.get("Name") or ctype in LAYOUT_TYPES:
            continue
        meta = _node_to_field(node, ctype)

        if ctype == "FormRelationshipInput":
            rel = _loads_maybe(ep.get("RelatedForm")) or {}
            meta["relatedForm"]  = form_name_by_id.get(rel.get("FormId"), "")
            meta["relatedField"] = field_index.get(rel.get("FieldId"), ("", ""))[1]
        elif ctype == "FormRelationshipReferenceDataInput":
            ref = _loads_maybe(ep.get("ReferenceField")) or {}
            meta["via"]          = ref.get("RelationshipFieldName", "")
            meta["relatedField"] = field_index.get(ref.get("ReferenceFieldId"), ("", ""))[1]

        # Dict-shaped picklist filters reference fields by GUID; keep the
        # same-form ones as the filter's depends-on set.
        filter_node = node.get("Filter")
        if isinstance(filter_node, dict) and filter_node:
            own = [field_index[i][1] for i in _expr_field_ids(filter_node)
                   if i in field_index and field_index[i][0] == display
                   and field_index[i][1] != meta["name"]]
            meta["dependsOn"]["filter"] = sorted(set(own))
            meta["dependsOnAll"] = sorted({f for lst in meta["dependsOn"].values() for f in lst})
        fields.append(meta)

    # Fields present in the flattened Fields array but absent from the design
    # (subforms have no design at all; a few fields live off-design).
    known = {f["name"] for f in fields}
    for fl in raw.get("Fields") or []:
        if fl.get("Name") and fl["Name"] not in known:
            fields.append(_minimal_field(fl["Name"], fl.get("Label"), fl.get("DataType")))
            known.add(fl["Name"])

    # Auto-increment config attaches to its field.
    for ai in raw.get("AutoIncrementFormFields") or []:
        fname = field_index.get(ai.get("FormFieldId"), ("", ""))[1]
        if fname:
            desc = f"{ai.get('Prefix') or ''}<counter from {ai.get('StartValue')}>{ai.get('Suffix') or ''}"
            for f in fields:
                if f["name"] == fname:
                    f["autoIncrement"] = desc
                    break

    for f in fields:
        if f["component"] == "FormRelationshipInput" and f["relatedForm"]:
            relationships.append({
                "source": display, "target": f["relatedForm"],
                "via": f["name"], "label": f["label"],
                "targetMatchField": f["relatedField"],
            })
        elif f["component"] == "FormRelationshipReferenceDataInput" and f["via"]:
            ref_pulls.append({
                "destForm": display, "destField": f["name"],
                "destLabel": f["label"], "via": f["via"],
                "sourceField": f["relatedField"], "dataType": f["type"],
            })

    # A subform is an embedded grid of its parent — keep it on the graph via a
    # containment relationship so the 28 grids don't float disconnected.
    if subform_of:
        relationships.append({
            "source": subform_of, "target": display,
            "via": "(embedded grid)", "label": "embedded grid",
            "targetMatchField": "",
        })

    return {
        "name": display, "fields": fields,
        "relationships": relationships, "refPulls": ref_pulls,
        "description": raw.get("Description") or "",
        "subformOf": subform_of or "",
        "savedFilters": [sf.get("Name", "") for sf in raw.get("SavedFilters") or []],
        "duplicateRules": "",   # filled by caller (needs the cross-form ref map)
        "role": "Subform" if subform_of else None,
    }

def _ws_parse_workflow(cfg, host_form, ws_display, ref_map, host_field_names):
    """One WorkflowConfigs[] entry -> the parse_workflow shape.

    ref_map: {field Id: {"FieldName":..., "FormName":...}} across the export —
    the same shape ExternalReferences lookups give the individual parser.
    """
    name = cfg.get("Name", "")
    event = (cfg.get("EventTrigger") or "").split(":")[-1]   # Create / Update / Scheduled
    scheduled = event == "Scheduled"

    schedule = ""
    if scheduled:
        freq = cfg.get("ScheduleFrequency")
        parts = [SCHEDULE_FREQ.get(freq, f"frequency {freq}")]
        if cfg.get("DayOfWeek") is not None:  parts.append(f"day-of-week {cfg['DayOfWeek']}")
        if freq in (3, 4) and cfg.get("DayOfMonth") is not None: parts.append(f"day-of-month {cfg['DayOfMonth']}")
        if cfg.get("DayOfYear") is not None:  parts.append(f"day-of-year {cfg['DayOfYear']}")
        if cfg.get("TriggerLimit"):           parts.append(f"limit {cfg['TriggerLimit']}")
        schedule = " · ".join(parts)

    wf = {
        "callsign": name[:12].upper().replace(" ", "_"),
        "name": name,
        "description": "",
        "staging_guid": "",
        "trigger": {
            "type": "Scheduled" if scheduled else "FormResponse",
            "form": host_form,
            "workspace": ws_display,
            "databaseAction": "" if scheduled else event,
            "timing": "",
            "conditionMode": "",
            "condition": _summarize_condition(cfg.get("TriggerCondition"), ref_map),
            "cron": schedule or None,
            "timezone": None,
        },
        "actions": [],
        "fieldUsage": [],
        "externalRefs": [],
        "enabled": bool(cfg.get("IsEnabled", True)),
    }

    for fld_ref in _extract_condition_fields(cfg.get("TriggerCondition"), ref_map):
        wf["fieldUsage"].append({
            "form": fld_ref["form"], "field": fld_ref["field"],
            "direction": "Condition", "context": "Trigger condition",
            "stepName": "",
        })

    for action in cfg.get("Actions") or []:
        handler = action.get("Name", "")
        conf = action.get("Configuration") or {}
        atype = handler.replace("ActionHandler", "") or handler

        target_form = ""
        summary = ""
        if handler == "NotificationActionHandler":
            bits = [f"To: {conf.get('To','')}"]
            if conf.get("Subject"): bits.append(f"Subject: {conf['Subject']}")
            summary = " · ".join(bits)
            # {FieldName} tokens in the template read host-form fields.
            blob = " ".join(str(conf.get(k, "")) for k in ("To", "BCC", "Subject", "Message"))
            for tok in sorted(set(re.findall(r"\{([A-Za-z0-9_]+)\}", blob))):
                if tok in host_field_names:
                    wf["fieldUsage"].append({
                        "form": host_form, "field": tok,
                        "direction": "Read", "context": "Notification template",
                        "stepName": "",
                    })
        else:
            # Unknown handler: degrade gracefully; resolve a target form if the
            # config carries one.
            target_form = ref_map.get(conf.get("FormId"), {}).get("FormName", "") \
                          if isinstance(conf.get("FormId"), str) else ""

        wf["actions"].append({
            "stepName": "",
            "name": conf.get("Subject") or atype,
            "type": atype,
            "targetForm": target_form,
            "targetWorkspace": ws_display if target_form else "",
            "duplicatePolicy": "",
            "resolutionType": "",
            "matchOn": summary,
            "continueOnError": None,
        })

    return wf

def parse_workspace_export(d):
    """Parse a whole-workspace export dict into normalized parts:
    {workspaceName, forms: [parse_form-shaped + extras], workflows: [parse_workflow-shaped]}.
    """
    raw_forms = d.get("Forms") or []
    display_by_id = _ws_display_names(raw_forms)

    # GUID indexes across the whole export.
    field_index = {}    # field Id -> (form display, field name)
    ref_map = {}        # field Id -> {"FieldName", "FormName"} (expression lookups)
    for rf in raw_forms:
        disp = display_by_id[rf["Id"]]
        for fl in rf.get("Fields") or []:
            field_index[fl["Id"]] = (disp, fl["Name"])
            ref_map[fl["Id"]] = {"FieldName": fl["Name"], "FormName": disp}

    forms, workflows = [], []
    for rf in raw_forms:
        disp = display_by_id[rf["Id"]]
        parent_id = rf.get("TopLevelFormId")
        is_sub = bool(parent_id and parent_id != rf["Id"])
        subform_of = display_by_id.get(parent_id) if is_sub else None
        parsed = _ws_parse_form(rf, disp, display_by_id, field_index, subform_of)
        if is_sub and not subform_of:
            # Embedded grid whose parent form isn't in the export — still a
            # subform, just with no containment edge to draw.
            parsed["role"] = "Subform"

        dup = rf.get("DuplicateResponseConfiguration") or {}
        rules = [_expr_to_text(r.get("Expression"), ref_map) for r in dup.get("Rules") or []]
        parsed["duplicateRules"] = "  OR  ".join(r for r in rules if r)
        forms.append(parsed)

        host_fields = {fl["Name"] for fl in rf.get("Fields") or []} | {f["name"] for f in parsed["fields"]}
        for cfg in rf.get("WorkflowConfigs") or []:
            workflows.append(_ws_parse_workflow(cfg, disp, d.get("DisplayName") or d.get("Name") or "",
                                                ref_map, host_fields))

    return {
        "workspaceName": d.get("DisplayName") or d.get("Name") or "",
        "forms": forms,
        "workflows": workflows,
    }

# ── workspace discovery ─────────────────────────────────────────────
def list_workspaces():
    """Workspace slugs = subdirectories of data/ that hold forms/ or workflows/
    subfolders, or a root-level whole-workspace export (*.json)."""
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir()
                  if p.is_dir() and ((p / "forms").exists() or (p / "workflows").exists()
                                     or any(p.glob("*.json"))))


class Workspace:
    """One workspace rooted at data/<slug>/ with forms/, workflows/, manual/ subfolders."""

    def __init__(self, slug):
        self.slug = slug
        self.dir = DATA_DIR / slug
        self.forms_dir = self.dir / "forms"
        self.workflows_dir = self.dir / "workflows"
        self.manual_dir = self.dir / "manual"
        self._overrides = None
        self._ws_exports = None   # cached parsed workspace exports
        self._warned = set()      # shadow warnings already printed (once per instance)

    def _read_json(self, path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return default
        return default

    def _warn(self, msg):
        if msg not in self._warned:
            self._warned.add(msg)
            print(msg)

    def workspace_exports(self):
        """Parsed whole-workspace exports from data/<slug>/*.json, cached.
        Returns [(filename, parsed)] in filename order; non-workspace JSONs at
        the root are warned about and skipped."""
        if self._ws_exports is None:
            self._ws_exports = []
            for path in sorted(self.dir.glob("*.json")):
                d = self._read_json(path, None)
                fmt = detect_format(d)
                if fmt != "workspace":
                    self._warn(f"  ! {self.slug}/{path.name}: not a workspace export "
                               f"(detected: {fmt}) -- skipped. Individual form/workflow "
                               f"exports belong in forms/ and workflows/.")
                    continue
                self._ws_exports.append((path.name, parse_workspace_export(d)))
        return self._ws_exports

    @property
    def name(self):
        """Display name: manual/workspace.json override, else the workspace
        export's own DisplayName, else the slug."""
        meta = self._read_json(self.manual_dir / "workspace.json", {})
        if meta.get("displayName"):
            return meta["displayName"]
        for _fname, parsed in self.workspace_exports():
            if parsed["workspaceName"]:
                return parsed["workspaceName"]
        return self.slug

    def _load_overrides(self):
        if self._overrides is None:
            self._overrides = self._read_json(self.manual_dir / "form_aliases.json", {})
        return self._overrides

    def canonicalize_name(self, name):
        """Resolve a display name through the name_aliases section of form_aliases.json.

        Workflow JSON exports sometimes reference forms by an older or abbreviated name
        (e.g. "395X - Inspections") that doesn't match the canonical display name derived
        from the form file ("395 - Inspection Work Order").  Adding an entry under the
        "name_aliases" key in the workspace's form_aliases.json fixes the mismatch without
        touching either source JSON.
        """
        if not name:
            return name
        overrides = self._load_overrides()
        aliases = overrides.get("name_aliases", {}) if isinstance(overrides, dict) else {}
        return aliases.get(name, name)

    def guess_form_name(self, stem):
        """Map a filename stem to a clean display name. Manual overrides take precedence."""
        import re
        # Strip platform copy-marker suffixes (__1_, __2_, etc.) before any lookup.
        # The platform appends these when a form is duplicated; the copy is the real form.
        stem = re.sub(r'(__\d+_?)+$', '', stem)
        overrides = self._load_overrides()
        if stem in overrides:
            return overrides[stem]
        # Heuristic: strip workspace prefix, version, and design suffix
        # e.g., "so_cal-esa_whole_home_pp_d__300-account_management_v342_design"
        #        ->  "300 - Account Management"
        s = stem
        if "__" in s:
            s = s.split("__", 1)[1]
        s = re.sub(r"_v\d+(_design)?(_+\d*)?$", "", s)
        s = re.sub(r"_design.*$", "", s)
        s = s.replace("_", " ").strip()
        parts = s.split(" - ", 1) if " - " in s else s.split(" ", 1)
        if len(parts) == 2 and parts[0].rstrip("-").rstrip().isdigit():
            return f"{parts[0].strip()} - {parts[1].title()}"
        return s.title()

    def parse_form(self, json_path):
        """Parse a single form design JSON. Returns {name, fields, relationships, refPulls}."""
        d = json.loads(Path(json_path).read_text(encoding="utf-8"))
        fields = []
        _walk(d["Components"][0], fields)

        # form name guessed from filename — override via manual/form_aliases.json if needed
        form_name = self.guess_form_name(json_path.stem)

        relationships = []
        ref_pulls = []
        for f in fields:
            if f["component"] == "FormRelationshipInput" and f["relatedForm"]:
                # The related form name stored on the field can be stale/abbreviated
                # (e.g. "310 - WH Enrollment"); canonicalize so the edge resolves to a
                # real form node instead of stubbing a phantom Lookup.
                relationships.append({
                    "source": form_name,
                    "target": self.canonicalize_name(f["relatedForm"]),
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

    def parse_workflow(self, json_path, manual_meta=None):
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
            # Individual workflow exports carry no enabled flag; treat as active.
            "enabled": bool(d.get("IsEnabled", True)),
        }

        # Normalize form names through name_aliases before building the lookup table so
        # every downstream ref_by_id.get(...).get("FormName") returns the canonical name.
        for ref in wf["externalRefs"]:
            if ref.get("FormName"):
                ref["FormName"] = self.canonicalize_name(ref["FormName"])

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
                for a in assignments:
                    wf["fieldUsage"].append({
                        "form": target_form, "field": a["field"],
                        "direction": "Write",
                        "context": a["sourceDesc"],
                        "stepName": step.get("Name",""),
                    })

        return wf

    def _manual_workflow_meta(self):
        return self._read_json(self.manual_dir / "workflow_metadata.json", {})

    def business_processes(self):
        """Manual business-process list, or None to let the builder use its default."""
        return self._read_json(self.manual_dir / "business_processes.json", None)

    def explorer_layout(self):
        """Optional preset node positions for the explorer graph (form name -> {x,y})."""
        return self._read_json(self.manual_dir / "explorer_layout.json", {})

    def discover(self):
        """Parse every form and workflow in this workspace into a unified dict.

        Two ingestion formats coexist:
        - whole-workspace exports at data/<slug>/*.json provide the baseline
          (every form + embedded workflows at once);
        - individual exports under forms/ and workflows/ layer on top, and
          ALWAYS take precedence over the baseline for the same form/workflow
          (treated as surgical updates). Each shadowing is warned about at
          rebuild time so a stale override stays visible.
        """
        # 1. Baseline from workspace export(s); later files merge over earlier.
        merged = {}        # form display name -> parsed form dict (+sourceFile)
        order = []
        workflows = []     # wf dicts in encounter order
        # Workflow identity = (trigger form, name): two embedded workflows on
        # different forms can legitimately share a name ("Pending Reviews").
        wf_key = lambda w: ((w["trigger"] or {}).get("form", ""), w["name"])
        wf_index = {}      # (trigger form, name) -> position in workflows
        for fname, parsed in self.workspace_exports():
            for pf in parsed["forms"]:
                if pf["name"] not in merged:
                    order.append(pf["name"])
                merged[pf["name"]] = dict(pf, sourceFile=fname)
            for wf in parsed["workflows"]:
                wf = dict(wf, sourceFile=fname)
                if wf_key(wf) in wf_index:
                    workflows[wf_index[wf_key(wf)]] = wf
                else:
                    wf_index[wf_key(wf)] = len(workflows)
                    workflows.append(wf)

        # 2. Individual form exports override the baseline form-by-form.
        if self.forms_dir.exists():
            for json_file in sorted(self.forms_dir.glob("*.json")):
                parsed = self.parse_form(json_file)
                name = parsed["name"]
                if name in merged:
                    self._warn(f"  ! {name}: individual export ({json_file.name}) "
                               f"overrides workspace baseline ({merged[name]['sourceFile']})")
                    base = merged[name]
                    # Structure comes from the individual file; workspace-only
                    # extras (description, saved filters, dup rules) are kept.
                    base.update({"fields": parsed["fields"],
                                 "relationships": parsed["relationships"],
                                 "refPulls": parsed["refPulls"],
                                 "sourceFile": json_file.name})
                else:
                    merged[name] = dict(parsed, sourceFile=json_file.name)
                    order.append(name)

        forms = []
        fields_by_form = {}
        relationships = []
        ref_pulls = []
        for name in order:
            pf = merged[name]
            forms.append({"name": name,
                          "role": pf.get("role") or _infer_role(pf),
                          "fieldCount": len(pf["fields"]),
                          "sourceFile": pf["sourceFile"],
                          "description": pf.get("description", ""),
                          "subformOf": pf.get("subformOf", ""),
                          "duplicateRules": pf.get("duplicateRules", ""),
                          "savedFilters": pf.get("savedFilters", [])})
            fields_by_form[name] = pf["fields"]
            relationships.extend(pf["relationships"])
            ref_pulls.extend(pf["refPulls"])

        # Auto-add referenced forms that don't have a JSON profile yet
        known = {f["name"] for f in forms}
        referenced = {r["target"] for r in relationships} | {r["source"] for r in relationships}
        for name in sorted(referenced - known):
            forms.append({"name": name, "role": "Lookup", "fieldCount": 0,
                          "sourceFile": None})
            fields_by_form.setdefault(name, [])

        # 3. Workflows: embedded baseline already loaded; individual exports
        # override by workflow name. Manual metadata keys by filename stem for
        # individual exports and by workflow name for embedded ones.
        workflow_manual = self._manual_workflow_meta()
        for wf in workflows:
            manual = workflow_manual.get(wf["name"], {})
            if manual.get("callsign"):
                wf["callsign"] = manual["callsign"]
        if self.workflows_dir.exists():
            for json_file in sorted(self.workflows_dir.glob("*.json")):
                manual = workflow_manual.get(json_file.stem, {})
                wf = self.parse_workflow(json_file, manual)
                wf["sourceFile"] = json_file.name
                if wf_key(wf) in wf_index:
                    self._warn(f"  ! workflow '{wf['name']}': individual export ({json_file.name}) "
                               f"overrides embedded workspace-export version")
                    workflows[wf_index[wf_key(wf)]] = wf
                else:
                    wf_index[wf_key(wf)] = len(workflows)
                    workflows.append(wf)

        # Callsigns are node IDs and Excel PKs — de-dupe within the workspace
        # (two embedded workflows can share a name, e.g. "Pending Reviews").
        used = set()
        for wf in workflows:
            cs, i = wf["callsign"], 2
            while cs in used:
                cs = f"{wf['callsign']}_{i}"; i += 1
            wf["callsign"] = cs
            used.add(cs)

        return {
            "slug": self.slug,
            "workspaceName": self.name,
            "forms": forms,
            "fields": fields_by_form,
            "relationships": relationships,
            "refPulls": ref_pulls,
            "workflows": workflows,
        }


def discover_all():
    """Discover every workspace. Returns {slug: discovered_dict}."""
    return {slug: Workspace(slug).discover() for slug in list_workspaces()}
