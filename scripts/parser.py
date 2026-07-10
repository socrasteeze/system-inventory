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

# One rebuild run discovers each workspace several times (per-workspace build,
# global build, field index, briefs — each constructs fresh Workspace instances),
# so diagnostics dedupe at module level: each distinct line prints once per
# process. WARNINGS collects the warning subset for the end-of-run summary.
_PRINTED_ONCE = set()
WARNINGS = []

def _print_once(msg):
    if msg not in _PRINTED_ONCE:
        _PRINTED_ONCE.add(msg)
        print(msg)

def _file_version(stem):
    """The _vNN_ token platform export filenames carry; -1 when absent."""
    m = re.search(r"_v(\d+)", stem)
    return int(m.group(1)) if m else -1

# Field attributes compared between two parses of the same form — the canonical
# list, shared with versioning.py (which imports it; parser stays import-free).
FIELD_COMPARE_KEYS = (
    "label", "type", "component", "required", "hidden", "enabled",
    "relatedForm", "relatedField", "via", "validator", "formula",
    "filter", "visibility", "defaultValue",
)

def _field_delta(old_fields, new_fields):
    """added/removed/changed between two parsed field lists, keyed by field name.

    Labels are captured here because superseded parses are discarded afterward —
    a removed field's label exists only in the older parse. Output lists are
    sorted by name so version history is byte-deterministic.
    """
    old = {f["name"]: f for f in old_fields if f.get("name")}
    new = {f["name"]: f for f in new_fields if f.get("name")}
    added = [{"name": n, "label": new[n].get("label") or n}
             for n in sorted(new.keys() - old.keys())]
    removed = [{"name": n, "label": old[n].get("label") or n}
               for n in sorted(old.keys() - new.keys())]
    changed = []
    for n in sorted(old.keys() & new.keys()):
        attrs = [k for k in FIELD_COMPARE_KEYS if old[n].get(k) != new[n].get(k)]
        if (old[n].get("dependsOn") or {}) != (new[n].get("dependsOn") or {}):
            attrs.append("dependsOn")
        if attrs:
            changed.append({"name": n, "label": new[n].get("label") or n,
                            "attributes": attrs})
    return {"added": added, "removed": removed, "changed": changed}

def _vfmt(v):
    """'v208' for a real version, 'v?' when the filename had no _vNN token."""
    return f"v{v}" if v is not None and v >= 0 else "v?"

def _delta_phrase(delta):
    """Compact '+2 fields, -1 field, 3 changed' summary for log lines."""
    parts = []
    n = len(delta["added"])
    if n:
        parts.append(f"+{n} field" + ("s" if n != 1 else ""))
    n = len(delta["removed"])
    if n:
        parts.append(f"-{n} field" + ("s" if n != 1 else ""))
    n = len(delta["changed"])
    if n:
        parts.append(f"{n} changed")
    return ", ".join(parts) if parts else "no field changes"

# Components that are pure layout containers (not data fields)
LAYOUT_TYPES = {"TwoWideLayout","ThreeWideLayout","FourWideLayout","StackedLayout",
                "FormSection","FormGrid","FormPage","Header","FormComponent"}

# Default "main" forms surfaced first in the explorer and on the docs landing page
# when a workspace has no manual/featured_forms.json. Matched as case-insensitive
# substrings against each form's display name. Override per workspace via that file.
FEATURED_KEYWORDS = ("account", "enrollment", "assessment", "installation", "invoice")

# ── field-level configuration extraction ────────────────────────────
# Form designs carry per-field logic that references other fields on the same
# form: computed formulas, conditional visibility/required rules, picklist
# filters, default values, and validators. Field references appear two ways —
# as a .Fields[].FieldName array on code-based (JS) rules, and as "@Field.X"
# tokens inside builder expressions (sometimes base64-encoded). _config_field_refs
# pulls both so we can build the intra-form "depends on" graph.

def _decode_b64_json(s):
    try:
        # Encoders vary on whether the trailing '=' padding is included; add
        # what's missing rather than let b64decode reject an unpadded string.
        padded = s + "=" * (-len(s) % 4)
        return json.loads(base64.b64decode(padded).decode("utf-8"))
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

def _advanced_config(value, own_name=None):
    """Decode an AdvancedConfiguration-shaped field config (formula / visibility /
    conditional-required / filter) into its authoring mode, human-readable text,
    and the same-form field names it references.

    Every such config carries a fixed key set (Configuration, Expression,
    ClearValueOnTrue/False, Key, Fields, ExpressionFieldReferences) with exactly
    one of two populated, never both:
    - Configuration (a JS string) = written in the platform's "Advanced" code
      editor. Text comes straight from the code; deps from _config_field_refs.
    - Expression (base64-encoded JSON) = built with the "Conditional" visual
      rule builder — a GroupingDto tree of field comparisons / context checks
      (e.g. IsInGroup). Its sibling ExpressionFieldReferences is a ready-made
      {FieldName: FieldGUID} map for every field the rule touches, which is
      also enough to resolve FormFieldId refs inside the tree to names without
      any external GUID index.
    """
    obj = _as_config_obj(value)
    if not isinstance(obj, dict):
        return {"mode": "", "text": "", "deps": []}
    if obj.get("Configuration"):
        return {
            "mode": "Advanced",
            "text": _clean_formula(obj["Configuration"]),
            "deps": _config_field_refs(value, own_name),
        }
    if obj.get("Expression"):
        expr = _as_config_obj(obj["Expression"])
        name_by_guid = {guid: {"FieldName": fname}
                        for fname, guid in (obj.get("ExpressionFieldReferences") or {}).items()}
        text = _expr_to_text(expr, name_by_guid) if isinstance(expr, dict) else ""
        deps = sorted(fn for fn in (obj.get("ExpressionFieldReferences") or {}) if fn != own_name)
        return {"mode": "Conditional", "text": text, "deps": deps}
    return {"mode": "", "text": "", "deps": []}

def _extract_field_config(node, own_name):
    """Field-level config + the fields each piece references (the intra-form depends-on)."""
    ep = node.get("ExtraProperties", {}) or {}
    deps = {"validation": [], "formula": [], "filter": [], "visibility": []}

    validator = node.get("Validator") if isinstance(node.get("Validator"), str) else ""
    dv = ep.get("DefaultValue")
    default_value = str(dv) if dv not in (None, "") else ""

    modes = {"formula": "", "filter": "", "visibility": "", "validation": ""}

    formula = ""
    formula_cfg = ep.get("AdvancedConfiguration") or ep.get("ValueAdvancedConfiguration")
    if formula_cfg:
        r = _advanced_config(formula_cfg, own_name)
        formula, modes["formula"], deps["formula"] = r["text"], r["mode"], r["deps"]

    visibility = ""
    visibility_expr = ""
    if ep.get("HiddenAdvancedConfiguration"):
        visibility = "Yes"
        r = _advanced_config(ep["HiddenAdvancedConfiguration"], own_name)
        visibility_expr, modes["visibility"], deps["visibility"] = r["text"], r["mode"], r["deps"]

    validation_expr = ""
    if ep.get("RequiredAdvancedConfiguration"):
        r = _advanced_config(ep["RequiredAdvancedConfiguration"], own_name)
        validation_expr, modes["validation"], deps["validation"] = r["text"], r["mode"], r["deps"]

    filt = ""
    filter_expr = ""
    filter_node = node.get("Filter")
    if isinstance(filter_node, str) and filter_node:
        filt = "Yes"
        r = _advanced_config(filter_node, own_name)
        filter_expr, modes["filter"], deps["filter"] = r["text"], r["mode"], r["deps"]
    elif isinstance(filter_node, dict) and filter_node:
        # Workspace exports carry the filter as a parsed expression dict whose
        # field refs are GUIDs; the caller resolves those (needs the GUID index).
        filt = "Yes"
    elif ep.get("HasFilter") == "True":
        filt = "Yes"

    return {
        "validator": validator,
        "formula": formula, "formulaMode": modes["formula"],
        "filter": filt, "filterExpr": filter_expr, "filterMode": modes["filter"],
        "visibility": visibility, "visibilityExpr": visibility_expr, "visibilityMode": modes["visibility"],
        "validationExpr": validation_expr, "validationMode": modes["validation"],
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

def _ancestor_page_section(comp_id, by_id):
    """Walk the ParentId chain from comp_id to find the nearest FormPage and
    FormSection ancestors.  Returns (page_title, section_title, page_sort,
    section_sort); any value may be None / 0 if no ancestor of that type
    exists.  Used only by _ws_parse_form (workspace-export flat list)."""
    page_title = section_title = None
    page_sort = section_sort = 0
    cur = by_id.get(comp_id, {}).get("ParentId")
    while cur and cur in by_id:
        c = by_id[cur]
        ctype = c.get("FormDesignComponentType", "")
        ep = c.get("ExtraProperties") or {}
        title = ep.get("Label") or ep.get("Name") or None
        if ctype == "FormPage" and page_title is None:
            page_title = title
            page_sort = c.get("SortOrder", 0) or 0
        elif ctype == "FormSection" and section_title is None:
            section_title = title
            section_sort = c.get("SortOrder", 0) or 0
        if page_title is not None and section_title is not None:
            break
        cur = c.get("ParentId")
    return page_title, section_title, page_sort, section_sort


def _walk(node, out, page=None, section=None):
    """Recursively walk the individual-export nested design tree.

    page / section track the nearest FormPage / FormSection ancestor titles
    so every field meta carries them without a separate ParentId walk.
    """
    ep = node.get("ExtraProperties", {}) or {}
    name = ep.get("Name")
    ctype = node.get("ComponentType")

    # Compute context for this node's children before recursing.
    child_page = page
    child_section = section
    if ctype == "FormPage":
        child_page = ep.get("Label") or ep.get("Name") or page
        child_section = None          # entering a new page resets section
    elif ctype == "FormSection":
        child_section = ep.get("Label") or ep.get("Name") or section

    if name and ctype not in LAYOUT_TYPES:
        meta = _node_to_field(node, ctype)
        meta["page"] = page
        meta["section"] = section
        meta["sort_order"] = node.get("SortOrder", 0) or 0
        out.append(meta)
    for c in node.get("Children", []):
        _walk(c, out, child_page, child_section)

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
    op_map = {1:"==", 2:"!=", 3:"<", 4:"<=", 5:">", 6:">="}
    if t.startswith("Grouping"):
        op = {1:" AND ", 2:" OR "}.get(node.get("Operation"), " ")
        # A child can render empty (an expression type we don't handle);
        # joining empties produces " AND  AND ..." garbage — filter them.
        parts = [txt for txt in (_expr_to_text(e, ref_by_id)
                                 for e in node.get("Expressions",[])) if txt.strip()]
        return op.join(parts)
    if t.startswith("FormFieldComparisonExpression"):
        fld = ref_by_id.get(node.get("FormFieldId",""), {})
        fld_name = fld.get("FieldName", "?")
        val = node.get("ResponseFieldValue") or {}
        val_text = val.get("Value","?") if str(val.get("type","")).startswith("ConstantTerm") else val.get("ContextName","?")
        op = op_map.get(node.get("Operation"), "?")
        return f"{fld_name} {op} '{val_text}'"
    if t.startswith("FormContextExpression"):
        # Context checks from the visual rule builder, e.g. IsInGroup("Admin") —
        # ContextOption is the function name; Term(s)Value hold its argument(s).
        opt = node.get("ContextOption", "?")
        term = node.get("TermValue") or {}
        terms = node.get("TermValues") or []
        args = [str(t["Value"]) for t in [term] + list(terms) if t.get("Value") not in (None, "")]
        return f"{opt}({', '.join(repr(a) for a in args)})"
    # "Comparison" nodes (record-metadata guards like LastModifierId vs a user
    # GUID) are deliberately NOT rendered: their operation enum is unverified
    # and a dozen GUID clauses drown the readable part of a condition. They
    # fall through to "" and the Grouping join filters them out.
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
            "dependsOnAll": [],
            "page": None, "section": None, "sort_order": 0}

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

    # GUID->component map for the ParentId ancestry walk (page/section grouping).
    by_id = {c["Id"]: c for c in components if c.get("Id")}

    for node in components:
        ctype = node.get("FormDesignComponentType")
        ep = node.get("ExtraProperties") or {}
        if not ep.get("Name") or ctype in LAYOUT_TYPES:
            continue
        meta = _node_to_field(node, ctype)

        # Attach page / section from the nearest FormPage / FormSection ancestor.
        pg, sec, pg_sort, sec_sort = _ancestor_page_section(node.get("Id"), by_id)
        meta["page"] = pg
        meta["section"] = sec
        meta["sort_order"] = node.get("SortOrder", 0) or 0
        meta["_pg_sort"] = pg_sort
        meta["_sec_sort"] = sec_sort

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

    # Sort design-tree fields into platform visual order before the minimal-field
    # backfill, then strip the internal sort keys used only here.
    fields.sort(key=lambda f: (f.get("_pg_sort", 0), f.get("_sec_sort", 0), f.get("sort_order", 0)))
    for f in fields:
        f.pop("_pg_sort", None)
        f.pop("_sec_sort", None)

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

def _wf_form_prefix(form_name):
    """Short, deterministic token for namespacing a workflow callsign by its
    parent form (e.g. '310 - Enrollment Intake' -> '310', 'Invoice' -> 'INVOICE').
    Same-named workflows nested under different forms need distinct, stable
    callsigns that don't depend on parse order.
    """
    m = re.match(r"\s*(\d+)\s*-", form_name or "")
    if m:
        return m.group(1)
    first_word = (form_name or "").split(" - ")[0].split()
    token = re.sub(r"[^A-Za-z0-9]", "", first_word[0]) if first_word else ""
    return token[:10].upper() or "WF"

def _wf_name_token(name, maxlen=20):
    """Workflow name -> callsign token, truncated on word boundaries (never
    mid-word) with no trailing underscore -- e.g. 'Review Notification
    (Operations)' -> 'REVIEW_NOTIFICATION', not 'REVIEW_NOTIF'."""
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    if not words:
        return "WF"
    kept, length = [], 0
    for w in words:
        w = w.upper()
        added = len(w) + (1 if kept else 0)
        if kept and length + added > maxlen:
            break
        kept.append(w)
        length += added
    return "_".join(kept)[:maxlen].rstrip("_") or words[0].upper()[:maxlen]

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
        "callsign": f"{_wf_form_prefix(host_form)}_{_wf_name_token(name)}",
        "name": name,
        "description": "",
        "workflowType": "Legacy",
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
        self._ws_exports = None         # cached parsed workspace exports
        self._discovered = None         # cached discover() result (files don't change mid-run)
        self._root_form_files = []      # individual form exports found at the slug root
        self._root_workflow_files = []  # individual workflow exports found at the slug root

    def _read_json(self, path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return default
        return default

    def _warn(self, msg):
        if msg not in _PRINTED_ONCE:
            WARNINGS.append(msg)
        _print_once(msg)

    def _info(self, msg):
        _print_once(msg)

    def workspace_exports(self):
        """Parsed whole-workspace exports from data/<slug>/*.json, cached.
        Returns [(filename, parsed)] in filename order.

        Root JSONs are routed by detected content, not by folder: workspace
        exports become the baseline; individual form/workflow exports found at
        the root are collected for discover() to ingest as overrides, exactly
        as if they lived in forms/ or workflows/. Dropping a file anywhere
        under data/<slug>/ therefore just works."""
        if self._ws_exports is None:
            self._ws_exports = []
            self._root_form_files = []
            self._root_workflow_files = []
            for path in sorted(self.dir.glob("*.json")):
                d = self._read_json(path, None)
                fmt = detect_format(d)
                if fmt == "workspace":
                    self._ws_exports.append((path.name, parse_workspace_export(d)))
                elif fmt == "form":
                    self._root_form_files.append(path)
                elif fmt == "workflow":
                    self._root_workflow_files.append(path)
                else:
                    self._warn(f"  ! {self.slug}/{path.name}: not a recognized "
                               f"export JSON -- skipped")
            n_f, n_w = len(self._root_form_files), len(self._root_workflow_files)
            if n_f or n_w:
                bits = [b for b in (f"{n_f} form export(s)" if n_f else "",
                                    f"{n_w} workflow export(s)" if n_w else "") if b]
                self._info(f"  [{self.slug}] {' and '.join(bits)} at the workspace "
                           f"root -- ingesting as individual overrides")
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

    def _resolve_form_name(self, json_path, fields, baseline_fields):
        """Display name for an individual form export.

        The export carries no form name or GUID of its own, and the platform's
        filename conventions drift (the old regex heuristic mis-names every
        current export), so resolution is content-first:

        1. manual/form_aliases.json filename-stem entry — the explicit escape hatch;
        2. field-overlap match against the workspace baseline — the baseline form
           sharing the most field names wins when it covers >=80% of the export's
           fields with a clear margin; near-ties fall back to filename-token
           similarity (handles tiny lookup forms like Climate Zones);
        3. the legacy filename heuristic — only when there is no baseline to
           match against (pure individual-file workspaces).
        """
        stem = re.sub(r'(__\d+_?)+$', '', json_path.stem)
        overrides = self._load_overrides()
        if stem in overrides:
            return overrides[stem]

        design = {f["name"] for f in fields if f.get("name")}
        if baseline_fields and design:
            scored = sorted(((len(fns & design), name)
                             for name, fns in baseline_fields.items()), reverse=True)
            best_score, best_name = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0
            coverage = best_score / len(design)
            if best_score and coverage >= 0.8:
                if best_score >= 1.5 * max(1, second_score):
                    self._info(f"  [{self.slug}] {json_path.name} -> '{best_name}' "
                               f"(matched {best_score}/{len(design)} fields)")
                    return best_name
                # Near-tie: break it on filename tokens vs candidate form names.
                stem_tokens = set(re.split(r"[\s_\-().&/]+",
                                           re.sub(r"_v\d+(_design)?$", "", stem).lower())) - {""}
                close = [name for score, name in scored
                         if score >= max(1, int(0.8 * best_score))]
                tok = lambda name: len(stem_tokens &
                                       (set(re.split(r"[\s_\-().&/]+", name.lower())) - {""}))
                ranked = sorted(close, key=tok, reverse=True)
                if len(ranked) == 1 or tok(ranked[0]) > tok(ranked[1]):
                    self._info(f"  [{self.slug}] {json_path.name} -> '{ranked[0]}' "
                               f"(matched {best_score}/{len(design)} fields + filename)")
                    return ranked[0]
            self._warn(f"  ! {self.slug}/{json_path.name}: no confident baseline match "
                       f"(best: '{best_name}' {best_score}/{len(design)} fields) -- using the "
                       f"filename heuristic; add a form_aliases.json entry if it guesses wrong")
        return self.guess_form_name(json_path.stem)

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

    def parse_form(self, json_path, baseline_fields=None):
        """Parse a single form design JSON. Returns {name, fields, relationships, refPulls}.

        baseline_fields ({form name: set of field names}) enables content-based
        name resolution against the workspace baseline; without it the name
        falls back to alias/heuristic resolution from the filename."""
        d = json.loads(Path(json_path).read_text(encoding="utf-8"))
        fields = []
        _walk(d["Components"][0], fields)

        form_name = self._resolve_form_name(json_path, fields, baseline_fields or {})

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
            "workflowType": "WFEngine",
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

    def featured_forms(self, form_names):
        """Resolve the set of 'main' forms to feature (highlight first).

        Resolution order:
        - data/<slug>/manual/featured_forms.json {"featured": [names]} — explicit
          per-workspace list (exact display-name match); only names that actually
          exist in this workspace are kept.
        - otherwise the keyword default: any form whose display name contains
          (case-insensitive) one of FEATURED_KEYWORDS.

        Returns the featured names in discovery order (the order of form_names).
        """
        cfg = self._read_json(self.manual_dir / "featured_forms.json", {})
        explicit = cfg.get("featured") if isinstance(cfg, dict) else None
        if explicit:
            wanted = set(explicit)
            return [n for n in form_names if n in wanted]
        return [n for n in form_names
                if any(kw in n.lower() for kw in FEATURED_KEYWORDS)]

    def discover(self):
        """Parse every form and workflow in this workspace into a unified dict.

        Two ingestion formats coexist:
        - whole-workspace exports at data/<slug>/*.json provide the baseline
          (every form + embedded workflows at once);
        - individual exports under forms/ and workflows/ layer on top, and
          ALWAYS take precedence over the baseline for the same form/workflow
          (treated as surgical updates). Each shadowing is warned about at
          rebuild time so a stale override stays visible.

        Result is memoized per instance: build_inventory and build_explorer each
        call this on the same Workspace, and the orphan report calls it once more.
        Files don't change within a single rebuild, so the parse runs once and the
        one-time prints (reclassification, role pins) aren't repeated.
        """
        if self._discovered is not None:
            return self._discovered
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

        # 2. Individual form exports override the baseline form-by-form. Files in
        #    forms/ (scanned recursively — flat, or one subfolder per form) and
        #    form-format JSONs at the slug root (routed by content in
        #    workspace_exports()) go through the same pipeline — location never
        #    matters. Names resolve by field overlap against the baseline.
        baseline_fields = {n: {f["name"] for f in pf["fields"] if f.get("name")}
                           for n, pf in merged.items()}
        override_files = []
        if self.forms_dir.exists():
            override_files += [(p, True) for p in sorted(self.forms_dir.rglob("*.json"))]
        override_files += [(p, False) for p in self._root_form_files]

        candidates = []   # (resolved name, version, in forms/, path, parsed)
        for json_file, in_forms in override_files:
            try:
                parsed = self.parse_form(json_file, baseline_fields=baseline_fields)
            except Exception as exc:
                self._warn(f"  ! {self.slug}/{json_file.name}: unreadable form export "
                           f"({exc}) -- skipped")
                continue
            candidates.append((parsed["name"], _file_version(json_file.stem),
                               in_forms, json_file, parsed))

        # Same form exported more than once (e.g. _v78 and _v79 side by side):
        # intentional version history, not a mistake. Highest _vNN wins as the
        # active design; ties prefer forms/ placement (deliberate), then
        # filename order. Superseded exports are kept as versionHistory (with
        # per-version field deltas) and summarized in one changelog info line;
        # a warning only fires when the winner ties another file on version —
        # that ambiguity needs a _vNN token or a deletion to resolve.
        by_name = {}
        for cand in candidates:
            by_name.setdefault(cand[0], []).append(cand)
        winners = []
        histories = {}   # resolved name -> versionHistory list, oldest -> newest
        for name, group in by_name.items():
            group.sort(key=lambda c: (c[1], c[2], c[3].name))
            winner = group[-1]
            hist = []
            for i, (_nm, ver, _inf, path, parsed) in enumerate(group):
                delta = _field_delta(group[i - 1][4]["fields"],
                                     parsed["fields"]) if i else None
                hist.append({"version": ver if ver >= 0 else None,
                             "sourceFile": path.name,
                             "fieldDelta": delta})
            histories[name] = hist
            if len(group) > 1:
                prev = group[-2]
                if prev[1] == winner[1]:
                    for loser in (c for c in group[:-1] if c[1] == winner[1]):
                        self._warn(f"  ! {name}: multiple exports with the same "
                                   f"version; using {winner[3].name}, ignoring "
                                   f"{loser[3].name} -- add a _vNN filename "
                                   f"token or delete one")
                self._info(f"  [{self.slug}] {name}: {_vfmt(prev[1])} -> "
                           f"{_vfmt(winner[1])} active "
                           f"({_delta_phrase(hist[-1]['fieldDelta'])})")
            winners.append(winner)

        for name, _ver, _in_forms, json_file, parsed in sorted(winners, key=lambda c: c[3].name):
            version = _ver if _ver >= 0 else None
            if name in merged:
                self._warn(f"  ! {name}: individual export ({json_file.name}) "
                           f"overrides workspace baseline ({merged[name]['sourceFile']})")
                base = merged[name]
                # Structure comes from the individual file; workspace-only
                # extras (description, saved filters, dup rules) are kept.
                base.update({"fields": parsed["fields"],
                             "relationships": parsed["relationships"],
                             "refPulls": parsed["refPulls"],
                             "sourceFile": json_file.name,
                             "version": version,
                             "versionHistory": histories[name]})
            else:
                merged[name] = dict(parsed, sourceFile=json_file.name,
                                    version=version,
                                    versionHistory=histories[name])
                order.append(name)

        # Alias hygiene: a filename-stem alias whose file no longer exists is a
        # stale leftover from a previous export batch — flag it for cleanup.
        overrides_map = self._load_overrides()
        alias_stems = {k for k in overrides_map if k != "name_aliases"} \
            if isinstance(overrides_map, dict) else set()
        if alias_stems:
            present = {re.sub(r'(__\d+_?)+$', '', p.stem) for p, _ in override_files}
            stale = sorted(alias_stems - present)
            if stale:
                self._warn(f"  ! [{self.slug}] form_aliases.json: {len(stale)} filename "
                           f"alias(es) match no file on disk (e.g. {stale[0]}) -- "
                           f"remove them or re-add the files")

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
                          "savedFilters": pf.get("savedFilters", []),
                          "version": pf.get("version"),
                          "versionHistory": pf.get("versionHistory", [])})
            fields_by_form[name] = pf["fields"]
            relationships.extend(pf["relationships"])
            ref_pulls.extend(pf["refPulls"])

        # Auto-add referenced forms that don't have a JSON profile yet
        known = {f["name"] for f in forms}
        referenced = {r["target"] for r in relationships} | {r["source"] for r in relationships}
        for name in sorted(referenced - known):
            forms.append({"name": name, "role": "Lookup", "fieldCount": 0,
                          "sourceFile": None, "version": None,
                          "versionHistory": []})
            fields_by_form.setdefault(name, [])

        # Reclassification: _infer_role tags any form with no outgoing relationships
        # as Lookup, but real leaf forms (surveys, inspections, inventory records) are
        # structurally identical to reference tables — no outgoing relationships. Two
        # structural signals distinguish genuine reference/lookup tables:
        #
        #   (a) Pull targets — forms that other forms draw field data FROM via
        #       FormRelationshipReferenceDataInput. Join: refPull["via"] is the
        #       relationship-field name on the consumer; the matching relationship entry
        #       (source=consumer, via=field) resolves the target form name. Both formats
        #       store via as a display name so the join works without extra GUID resolution.
        #
        #   (b) Incoming-relationship targets — forms that other forms have a
        #       FormRelationshipInput *pointing to* (FK-like links). Some reference tables
        #       (e.g. Climate Zones) are linked-to but never explicitly pulled from;
        #       they show up here, not in pull_targets.
        #
        # Subform containment edges (via == "(embedded grid)") are excluded from (b)
        # because subforms are already tagged Subform and must not influence Lookup
        # reclassification.
        #
        # A Lookup form stays Lookup if it is in either set, or if it is an
        # auto-stub (sourceFile=None, referenced-but-not-in-export). Anything else —
        # including 0-field workspace-export forms that have their own source file but
        # no design yet — promotes to Spoke as a real (if empty) form.
        _rel_by_src_via = {}
        for r in relationships:
            _rel_by_src_via[(r["source"], r["via"])] = r["target"]
        pull_targets = set()
        for rp in ref_pulls:
            t = _rel_by_src_via.get((rp["destForm"], rp["via"]))
            if t:
                pull_targets.add(t)
        incoming_rel_targets = {r["target"] for r in relationships
                                if r.get("via") != "(embedded grid)"}
        reference_forms = pull_targets | incoming_rel_targets
        reclassified = 0
        for f in forms:
            if f["role"] != "Lookup":
                continue
            is_auto_stub = f.get("sourceFile") is None
            if not is_auto_stub and f["name"] not in reference_forms:
                f["role"] = "Spoke"
                reclassified += 1
        if reclassified:
            self._info(f"  [{self.slug}] {reclassified} form(s) reclassified Lookup->Spoke "
                       f"(not a reference target or pull target)")

        # Manual role pins — data/<slug>/manual/form_roles.json is the final word.
        # Keyed by form display name → role string. Applied after all heuristics so
        # manual/ remains the authoritative override layer (consistent with precedence
        # rules elsewhere in discover()). Both directions work: pin Lookup→Spoke or
        # Spoke→Lookup (or any role). Missing file = no-op.
        form_role_pins = self._read_json(self.manual_dir / "form_roles.json", {})
        if form_role_pins:
            forms_by_name = {f["name"]: f for f in forms}
            for form_name, pinned_role in form_role_pins.items():
                f = forms_by_name.get(form_name)
                if f is None:
                    self._warn(f"  ! [{self.slug}] form_roles.json: '{form_name}' not found, skipping")
                    continue
                if f["role"] != pinned_role:
                    self._info(f"  [{self.slug}] pinned '{form_name}' role {f['role']} -> {pinned_role}")
                    f["role"] = pinned_role

        # 3. Workflows: embedded baseline already loaded; individual exports
        # override by workflow name. Manual metadata keys by filename stem for
        # individual exports and by workflow name for embedded ones.
        workflow_manual = self._manual_workflow_meta()
        for wf in workflows:
            manual = workflow_manual.get(wf["name"], {})
            if manual.get("callsign"):
                wf["callsign"] = manual["callsign"]
        # Recursive: optional one-subfolder-per-workflow organization is
        # matched by workflow name, not path, same as forms/ above.
        wf_files = []
        if self.workflows_dir.exists():
            wf_files += sorted(self.workflows_dir.rglob("*.json"))
        wf_files += self._root_workflow_files   # routed by content, same pipeline
        for json_file in wf_files:
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

        self._discovered = {
            "slug": self.slug,
            "workspaceName": self.name,
            "forms": forms,
            "fields": fields_by_form,
            "relationships": relationships,
            "refPulls": ref_pulls,
            "workflows": workflows,
            "featured": self.featured_forms([f["name"] for f in forms]),
        }
        return self._discovered


def discover_all():
    """Discover every workspace. Returns {slug: discovered_dict}."""
    return {slug: Workspace(slug).discover() for slug in list_workspaces()}


def find_orphans(discovered):
    """Forms that render with zero edges in the explorer graph — true orphans.

    Matches the explorer's degree-0 reality (explorer_template.html): an edge is
    drawn for a relationship whose target form exists, and for each workflow
    trigger form / action target form. refPulls are NOT separate edges (they fold
    into relationship pull counts), so they don't connect a node on their own.

    A parented subform stays connected via its parent's "(embedded grid)"
    containment relationship; only a subform whose parent isn't in the export
    (subformOf == "") loses that edge. Returns a list of
    {"name", "role", "reason"} dicts, ordered as forms appear in discovery.
    """
    forms = discovered["forms"]
    names = {f["name"] for f in forms}
    connected = set()
    for r in discovered["relationships"]:
        if r["target"] in names:          # explorer skips edges to a missing target
            connected.add(r["source"])
            connected.add(r["target"])
    for w in discovered["workflows"]:
        trig = w.get("trigger") or {}
        if trig.get("form") in names:
            connected.add(trig["form"])
        for a in w.get("actions") or []:
            if a.get("targetForm") in names:
                connected.add(a["targetForm"])

    orphans = []
    for f in forms:
        if f["name"] in connected:
            continue
        if f.get("role") == "Subform" and not f.get("subformOf"):
            reason = "unparented grid (parent form not in export)"
        else:
            reason = "isolated %s (no relationship or workflow edge)" % (
                (f.get("role") or "form").lower())
        orphans.append({"name": f["name"], "role": f.get("role"), "reason": reason})
    return orphans
