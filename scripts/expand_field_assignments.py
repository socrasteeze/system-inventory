"""Mass-generate a WFEngine workflow's top-level FieldAssignments from Excel.

Sibling to expand_subform_ops.py, targeting the plain FieldAssignments
parameter of a BuiltIn.UpdateFormResponse action (not SubformOperations) --
the shape used by "copy field X from the trigger form onto field Y on the
target form" update workflows, e.g. "Update Existing Measures".

Takes an exported workflow JSON (Triggers/Steps) whose action carries a
FieldAssignments parameter (a template row or two is fine, or none -- the
mapping table is the sole source of truth for the generated array), plus an
Excel mapping with three columns: the source column (trigger-form field name
or literal value, depending on Assignment Type), the Assignment Type, and the
Resolution column (the target field on the form being updated). Field names
are validated against docs/field-index.json.

SUPPORTED Assignment Types (v1): Constant, FromTrigger ("From Trigger" also
accepted). Expression and Clear/Set Null are NOT yet supported -- their exact
platform ValueType string has no precedent anywhere in data/, so rather than
guess and silently produce a workflow that imports but misbehaves, a row
using either type is a hard error naming the row. See TODO.md.

Mapping format (.xlsx or .csv)
  - One header row with three columns. Standard labels are matched by name
    (any order, case/spacing-insensitive):
      "Field Name (Current Form)"   -- source: trigger field (FromTrigger)
                                        or literal value (Constant)
      "Field Assignment Type"       -- Constant | FromTrigger
      "Resolution (Field Name)"     -- target field on the form being updated
    When the labels aren't standard but the sheet has exactly three columns
    (real files often carry the form names as headers, e.g.
    "EnrollmentForm210,Type,InstallationForm255"), positional order
    source/type/target is used and a note is printed.
  - One data row per FieldAssignments entry. Blank rows are skipped;
    partially filled rows are an error.

Usage
  python scripts/expand_field_assignments.py TEMPLATE.json MAPPING.{xlsx|csv} --workspace SLUG
         [--sheet NAME] [--out PATH] [--step NAME] [--action NAME] [--apply]

Dry-run by default: prints the validation report and per-row resolution
table without writing. Pass --apply to write the output file.
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent

# Header text this script recognizes for each column role, matched after
# lowercasing and collapsing whitespace -- tolerant of the exact wording in
# the source workbook drifting slightly.
COLUMN_ALIASES = {
    "source": {"field name (current form)", "current form field", "source field",
               "field name"},
    "type": {"field assignment type", "assignment type", "type"},
    "target": {"resolution (field name)", "resolution field name",
               "resolution field", "target field", "resolution"},
}

TYPE_ALIASES = {
    "constant": "Constant",
    "fromtrigger": "FromTrigger",
    "from trigger": "FromTrigger",
}
UNSUPPORTED_TYPE_HINTS = {
    "expression": "Expression",
    "clear/set null": "Clear/Set Null",
    "clear / set null": "Clear/Set Null",
    "clear": "Clear/Set Null",
    "set null": "Clear/Set Null",
    "clearsetnull": "Clear/Set Null",
}


def _norm(s):
    return " ".join(str(s or "").strip().lower().split())


def load_field_index(repo_root):
    p = repo_root / "docs" / "field-index.json"
    if not p.exists():
        raise SystemExit(f"ERROR: {p} not found -- run 'python scripts/regenerate.py' first.")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def index_fields(field_index, slug, form_name):
    key = f"{slug}/{form_name}"
    if key not in field_index:
        close = difflib.get_close_matches(key, list(field_index), n=3, cutoff=0.6)
        hint = f" Closest keys: {', '.join(close)}" if close else ""
        raise SystemExit(f"ERROR: '{key}' not in docs/field-index.json.{hint}")
    return {f["name"] for f in field_index[key]}


def find_field_assignments_action(template, step_name, action_name):
    """-> (step, action, field_assignments_param)."""
    candidates = []
    for step in template.get("Steps", []):
        for action in step.get("Actions", []):
            for p in action.get("Parameters", []):
                if p.get("ParameterName") == "FieldAssignments":
                    candidates.append((step, action, p))
    if step_name:
        candidates = [c for c in candidates if c[0].get("Name") == step_name]
    if action_name:
        candidates = [c for c in candidates if c[1].get("DisplayName") == action_name]
    if not candidates:
        raise SystemExit("ERROR: no action with a FieldAssignments parameter matches "
                         "in the template.")
    if len(candidates) > 1:
        listing = "; ".join(f"step '{s.get('Name','')}' action '{a.get('DisplayName','')}'"
                            for s, a, _ in candidates)
        raise SystemExit(f"ERROR: multiple actions carry FieldAssignments -- "
                         f"disambiguate with --step/--action. Candidates: {listing}")
    return candidates[0]


def resolve_target_form(action, ref_by_id):
    """Same FormId/TargetResolution.TargetFormId fallback parser.py's
    _parse_wfengine uses, so this script and the inventory agree."""
    params = {p["ParameterName"]: p for p in action.get("Parameters", [])}
    target_form_id = (params.get("TargetResolution.TargetFormId", {}).get("StaticValue")
                      or params.get("FormId", {}).get("StaticValue"))
    return ref_by_id.get(target_form_id, {}).get("FormName", "")


def _resolve_columns(header):
    """Header row -> ({role: column index}, note-or-None). Known header labels
    (COLUMN_ALIASES) are matched first; when they don't resolve all three
    roles and the sheet has exactly three columns, fall back to positional
    order (source, type, target) — real mapping files often carry the actual
    form names as headers (e.g. 'EnrollmentForm210,Type,InstallationForm255')."""
    col_idx = {}
    for role, aliases in COLUMN_ALIASES.items():
        for i, cell in enumerate(header):
            if _norm(cell) in aliases:
                col_idx[role] = i
                break
    missing = [role for role in ("source", "type", "target") if role not in col_idx]
    if not missing:
        return col_idx, None
    non_empty = [c for c in header if c is not None and str(c).strip()]
    if len(non_empty) == 3:
        note = (f"headers {', '.join(repr(str(c)) for c in non_empty)} aren't the standard "
                f"labels -- using positional order: source, type, target")
        return {"source": 0, "type": 1, "target": 2}, note
    seen = ", ".join(repr(str(c)) for c in header if c is not None)
    raise SystemExit(f"ERROR: could not resolve column(s) for: {', '.join(missing)}. "
                     f"Headers found: {seen}. Either use the standard labels or "
                     f"exactly three columns in source/type/target order.")


def read_mapping(path, sheet_name=None):
    """-> (source label, rows, note-or-None). rows: list of (source_text,
    type_text, target_text), already stripped; fully blank rows omitted.
    Accepts .xlsx (openpyxl) or .csv (utf-8-sig for Excel BOMs)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        import csv as _csv
        with open(path, newline="", encoding="utf-8-sig") as f:
            all_rows = [tuple(r) for r in _csv.reader(f)]
        title = path.name
        if sheet_name:
            raise SystemExit("ERROR: --sheet only applies to .xlsx mappings.")
    else:
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[sheet_name] if sheet_name else wb.worksheets[0]
        all_rows = list(ws.iter_rows(values_only=True))
        title = ws.title
    if not all_rows:
        raise SystemExit(f"ERROR: '{title}' in {path} is empty.")
    col_idx, note = _resolve_columns(all_rows[0])

    def cell(row, role):
        i = col_idx[role]
        return str(row[i]).strip() if i < len(row) and row[i] is not None else ""

    rows = []
    for row in all_rows[1:]:
        s, t, r = cell(row, "source"), cell(row, "type"), cell(row, "target")
        if not s and not t and not r:
            continue
        rows.append((s, t, r))
    return title, rows, note


def build_assignments(rows, trigger_fields, target_fields):
    """-> (assignments, resolution_lines, errors, warnings)."""
    assignments, lines, errors, warnings = [], [], [], []
    seen_targets = {}
    lower_trigger = {f.lower(): f for f in trigger_fields}

    for i, (source, raw_type, target) in enumerate(rows, start=2):  # row 2 = first data row
        if not raw_type:
            errors.append(f"row {i}: Field Assignment Type is blank")
            continue
        if not target:
            errors.append(f"row {i}: Resolution (Field Name) is blank")
            continue
        norm_type = _norm(raw_type)
        if norm_type in UNSUPPORTED_TYPE_HINTS:
            errors.append(f"row {i}: Assignment Type '{raw_type}' "
                          f"({UNSUPPORTED_TYPE_HINTS[norm_type]}) isn't supported yet -- "
                          f"only Constant and FromTrigger are implemented. See TODO.md.")
            continue
        if norm_type not in TYPE_ALIASES:
            errors.append(f"row {i}: unrecognized Assignment Type '{raw_type}' -- "
                          f"supported: Constant, From Trigger")
            continue
        vt = TYPE_ALIASES[norm_type]

        if target not in target_fields:
            close = difflib.get_close_matches(target, sorted(target_fields), n=3, cutoff=0.6)
            hint = f" (closest: {', '.join(close)})" if close else ""
            errors.append(f"row {i}: Resolution field '{target}' is not on the target form{hint}")
            continue
        if target in seen_targets:
            errors.append(f"row {i}: Resolution field '{target}' duplicates row "
                          f"{seen_targets[target]}")
            continue

        if vt == "FromTrigger":
            if not source:
                errors.append(f"row {i}: Field Assignment Type is FromTrigger but "
                              f"Field Name (Current Form) is blank")
                continue
            if source not in trigger_fields:
                close = difflib.get_close_matches(source, sorted(trigger_fields), n=3, cutoff=0.6)
                hint = f" (closest: {', '.join(close)})" if close else ""
                errors.append(f"row {i}: trigger field '{source}' not found{hint}")
                continue
            value = source
        else:  # Constant
            value = source
            if source.lower() in lower_trigger:
                warnings.append(f"row {i}: constant '{source}' matches trigger field "
                                f"'{lower_trigger[source.lower()]}' except for casing -- "
                                f"did you mean FromTrigger?")

        seen_targets[target] = i
        assignments.append({"FieldName": target, "ValueType": vt, "Value": value})
        lines.append(f"  row {i}: {target} <- {vt}:{value!r}")

    return assignments, lines, errors, warnings


def main():
    ap = argparse.ArgumentParser(description="Mass-generate a WFEngine workflow's "
                                             "top-level FieldAssignments from Excel.")
    ap.add_argument("template", help="exported workflow JSON (Triggers/Steps)")
    ap.add_argument("mapping", help="mapping file (.xlsx or .csv): source field / "
                                    "assignment type / target (Resolution) field")
    ap.add_argument("--workspace", required=True,
                    help="workspace slug for field-index validation (e.g. sce-be)")
    ap.add_argument("--sheet", help="worksheet name (default: first sheet)")
    ap.add_argument("--out", help="output path (default: <template>.expanded.json)")
    ap.add_argument("--step", help="step name, when multiple actions carry FieldAssignments")
    ap.add_argument("--action", help="action display name, same purpose as --step")
    ap.add_argument("--apply", action="store_true",
                    help="write the output file (default: dry run, print only)")
    args = ap.parse_args()

    template_path = Path(args.template)
    out_path = Path(args.out) if args.out else template_path.with_suffix(".expanded.json")
    if out_path.resolve() == template_path.resolve():
        raise SystemExit("ERROR: output path equals the template -- refusing to overwrite it.")

    with open(template_path, encoding="utf-8") as f:
        template = json.load(f)
    if "Triggers" not in template and "Steps" not in template:
        raise SystemExit(f"ERROR: {template_path} is not a WFEngine workflow export "
                         f"(no Triggers/Steps root).")

    ref_by_id = {r.get("RefId"): r for r in template.get("ExternalReferences", [])}
    triggers = template.get("Triggers", [])
    trigger_form = ref_by_id.get(triggers[0].get("FormId", ""), {}).get("FormName", "") \
        if triggers else ""
    if not trigger_form:
        raise SystemExit("ERROR: could not resolve the trigger form from the template's "
                         "ExternalReferences.")

    step, action, param = find_field_assignments_action(template, args.step, args.action)
    target_form = resolve_target_form(action, ref_by_id)
    if not target_form:
        raise SystemExit("ERROR: could not resolve the action's target form "
                         "(FormId / TargetResolution.TargetFormId unresolved).")

    field_index = load_field_index(REPO_ROOT)
    trigger_fields = index_fields(field_index, args.workspace, trigger_form)
    target_fields = index_fields(field_index, args.workspace, target_form)

    sheet_title, rows, note = read_mapping(args.mapping, sheet_name=args.sheet)
    if note:
        print(f"  note: {note}")
    if not rows:
        raise SystemExit(f"ERROR: '{sheet_title}' has no data rows.")

    assignments, lines, errors, warnings = build_assignments(rows, trigger_fields, target_fields)

    print(f"Template : {template_path}")
    print(f"Trigger form : {trigger_form}   Target form : {target_form}   "
          f"(validated against '{args.workspace}/...', sheet '{sheet_title}')")
    for w in warnings:
        print(f"  warning: {w}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print(f"\n{len(errors)} error(s) -- nothing written.")
        return 1

    print(f"Resolution ({len(assignments)} assignments on step '{step.get('Name','')}' / "
          f"action '{action.get('DisplayName','')}'):")
    for line in lines:
        print(line)

    param["StaticValue"] = json.dumps(assignments, separators=(",", ":"))
    out_text = json.dumps(template, indent=2)
    json.loads(out_text)  # round-trip self-check

    if not args.apply:
        print(f"\nDry run -- would write {out_path} ({len(assignments)} FieldAssignments). "
              f"Re-run with --apply to write it.")
        return 0
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    print(f"\nWrote {out_path} ({len(assignments)} FieldAssignments).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
