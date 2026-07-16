"""Mass-expand a WFEngine workflow's SubformOperations from a CSV mapping.

Takes an exported workflow JSON (Triggers/Steps) that already contains one
BuiltIn.UpdateFormResponse action with a SubformOperations parameter holding
at least one op (the prototype), plus a CSV where each data row describes one
subform "Add" operation. Produces a full import-ready workflow JSON with the
SubformOperations array rebuilt as one op per CSV row.

Every field name is validated against docs/field-index.json (the repo's
stable inventory contract): CSV headers must be fields on the subform, and
FromTrigger sources must be fields on the trigger form.

CSV format
  - Header row: subform field API names (e.g. MeasureName,MeasureQty,...).
  - Each data row = one "Add" op; each non-empty cell = one FieldAssignment.
    Empty cell = that assignment omitted for that op.
  - A cell that exactly matches a trigger-form field API name becomes
    ValueType FromTrigger; anything else becomes Constant.
  - Prefix overrides: "=value" forces Constant, "@FieldName" forces
    FromTrigger (error if not a trigger-form field).

Usage
  python scripts/expand_subform_ops.py TEMPLATE.json MAPPING.csv --workspace SLUG
         [--out PATH] [--step NAME] [--action NAME] [--apply]

Dry-run by default: prints the validation report and per-row resolution
table without writing. Pass --apply to write the output file.
"""

import argparse
import csv
import difflib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_field_index(repo_root):
    p = repo_root / "docs" / "field-index.json"
    if not p.exists():
        raise SystemExit(f"ERROR: {p} not found -- run 'python scripts/regenerate.py' first.")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def index_fields(field_index, slug, form_name):
    """-> set of field API names for '<slug>/<form_name>', erroring loudly
    (with closest-key suggestions) when the key is absent."""
    key = f"{slug}/{form_name}"
    if key not in field_index:
        close = difflib.get_close_matches(key, list(field_index), n=3, cutoff=0.6)
        hint = f" Closest keys: {', '.join(close)}" if close else ""
        raise SystemExit(f"ERROR: '{key}' not in docs/field-index.json.{hint}")
    return {f["name"] for f in field_index[key]}


def find_subform_action(template, step_name, action_name):
    """-> (step, action, subform_param) for the single action carrying a
    SubformOperations parameter, honoring --step/--action disambiguators."""
    candidates = []
    for step in template.get("Steps", []):
        for action in step.get("Actions", []):
            for p in action.get("Parameters", []):
                if p.get("ParameterName") == "SubformOperations":
                    candidates.append((step, action, p))
    if step_name:
        candidates = [c for c in candidates if c[0].get("Name") == step_name]
    if action_name:
        candidates = [c for c in candidates if c[1].get("DisplayName") == action_name]
    if not candidates:
        raise SystemExit("ERROR: no action with a SubformOperations parameter matches "
                         "in the template.")
    if len(candidates) > 1:
        listing = "; ".join(f"step '{s.get('Name','')}' action '{a.get('DisplayName','')}'"
                            for s, a, _ in candidates)
        raise SystemExit(f"ERROR: multiple actions carry SubformOperations -- "
                         f"disambiguate with --step/--action. Candidates: {listing}")
    return candidates[0]


def classify_cell(text, trigger_fields):
    """CSV cell -> (ValueType, Value, warning-or-None)."""
    if text.startswith("="):
        return "Constant", text[1:], None
    if text.startswith("@"):
        name = text[1:]
        if name not in trigger_fields:
            raise ValueError(f"'@{name}' is not a field on the trigger form")
        return "FromTrigger", name, None
    if text in trigger_fields:
        return "FromTrigger", text, None
    warn = None
    lower = {f.lower(): f for f in trigger_fields}
    if text.lower() in lower:
        warn = (f"constant '{text}' matches trigger field '{lower[text.lower()]}' "
                f"except for casing -- did you mean FromTrigger?")
    return "Constant", text, warn


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    if not rows:
        raise SystemExit(f"ERROR: {path} is empty.")
    headers = [h.strip() for h in rows[0]]
    return headers, [[c.strip() for c in r] for r in rows[1:]]


def build_ops(prototype, headers, rows, trigger_fields):
    """-> (ops, resolution_lines, errors, warnings)."""
    ops, lines, errors, warnings = [], [], [], []
    for i, row in enumerate(rows, start=1):
        assignments, parts = [], []
        for h, cell in zip(headers, row):
            if not cell:
                continue
            try:
                vt, v, warn = classify_cell(cell, trigger_fields)
            except ValueError as e:
                errors.append(f"row {i}: {e}")
                continue
            if warn:
                warnings.append(f"row {i}: {warn}")
            assignments.append({"FieldName": h, "ValueType": vt, "Value": v})
            parts.append(f"{h} <- {vt}:{v!r}" if vt == "Constant" else f"{h} <- {vt}:{v}")
        if not assignments:
            errors.append(f"row {i}: no assignments (all cells empty)")
            continue
        op = {k: v for k, v in prototype.items() if k != "FieldAssignments"}
        op["FieldAssignments"] = assignments
        ops.append(op)
        lines.append(f"  row {i}: " + ", ".join(parts))
    return ops, lines, errors, warnings


def main():
    ap = argparse.ArgumentParser(description="Mass-expand a WFEngine workflow's "
                                             "SubformOperations from a CSV mapping.")
    ap.add_argument("template", help="exported workflow JSON (Triggers/Steps)")
    ap.add_argument("csv_file", help="CSV mapping: header = subform field names, "
                                     "one row per Add op")
    ap.add_argument("--workspace", required=True,
                    help="workspace slug for field-index validation (e.g. liwp)")
    ap.add_argument("--out", help="output path (default: <template>.expanded.json)")
    ap.add_argument("--step", help="step name, when multiple actions carry SubformOperations")
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

    step, action, param = find_subform_action(template, args.step, args.action)
    try:
        ops_in = json.loads(param.get("StaticValue") or "")
    except Exception:
        raise SystemExit("ERROR: the template's SubformOperations StaticValue is not "
                         "valid JSON.")
    if not isinstance(ops_in, list) or not ops_in:
        raise SystemExit("ERROR: the template's SubformOperations holds no ops -- "
                         "need at least one as the prototype.")
    prototype = ops_in[0]
    subform = (ref_by_id.get(prototype.get("SubformFormId", ""), {}).get("FormName")
               or prototype.get("SubformFieldName", ""))
    if not subform:
        raise SystemExit("ERROR: prototype op names no subform (SubformFormId / "
                         "SubformFieldName both unresolved).")

    field_index = load_field_index(REPO_ROOT)
    trigger_fields = index_fields(field_index, args.workspace, trigger_form)
    subform_fields = index_fields(field_index, args.workspace, subform)

    headers, rows = read_csv(args.csv_file)
    errors = []
    if len(headers) != len(set(headers)):
        dupes = sorted({h for h in headers if headers.count(h) > 1})
        errors.append(f"duplicate CSV headers: {', '.join(dupes)}")
    for h in headers:
        if h not in subform_fields:
            close = difflib.get_close_matches(h, sorted(subform_fields), n=3, cutoff=0.6)
            hint = f" (closest: {', '.join(close)})" if close else ""
            errors.append(f"CSV header '{h}' is not a field on '{subform}'{hint}")
    if not rows:
        errors.append("CSV has no data rows")

    ops, lines, row_errors, warnings = build_ops(prototype, headers, rows, trigger_fields)
    errors.extend(row_errors)

    print(f"Template : {template_path}")
    print(f"Trigger form : {trigger_form}   Subform : {subform}   "
          f"(validated against '{args.workspace}/...')")
    for w in warnings:
        print(f"  warning: {w}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print(f"\n{len(errors)} error(s) -- nothing written.")
        return 1

    print(f"Resolution ({len(ops)} ops on step '{step.get('Name','')}' / "
          f"action '{action.get('DisplayName','')}'):")
    for line in lines:
        print(line)

    param["StaticValue"] = json.dumps(ops, separators=(",", ":"))
    out_text = json.dumps(template, indent=2)
    json.loads(out_text)  # round-trip self-check

    if not args.apply:
        print(f"\nDry run -- would write {out_path} ({len(ops)} SubformOperations). "
              f"Re-run with --apply to write it.")
        return 0
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    print(f"\nWrote {out_path} ({len(ops)} SubformOperations).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
