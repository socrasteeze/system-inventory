# SoCal WHP Workflow Inventory — Claude Standing Context

This file is loaded automatically on every session. It replaces the need to re-read the README or walk the repo.

## What this project is

A documentation system for the **SCE - ESA Whole Home (PP/D)** workspace.
It ingests JSON exports of platform forms and workflows, parses them into a normalized structure, and produces:

- `output/workflow_master_inventory.xlsx` — filterable Excel inventory (forms, fields, relationships, workflows, actions, field usage)
- `output/workspace_explorer.html` — interactive browser-based graph (forms as nodes, relationships as edges, workflow node shows what it touches)

Neither output file is hand-edited. Both are fully regenerated from the JSON exports in `data/`.

---

## Folder structure

```
data/
  forms/       ← form profile JSON exports (one file per form)
  workflows/   ← workflow JSON exports (one file per workflow)
  manual/      ← human-maintained overrides and metadata (see below)
output/        ← generated artifacts (Excel + HTML)
scripts/
  parser.py           shared parser (forms + workflows)
  build_inventory.py  Excel builder
  build_explorer.py   HTML builder
  explorer_template.html  HTML template injected with graph data
  regenerate.py       one-command rebuild (runs both builders in sequence)
```

---

## Rebuild command

```
python scripts/regenerate.py
```

Run this from the project root any time a JSON in `data/` is added or changed.
Then open `output/workspace_explorer.html` in a browser to confirm the graph.

---

## Data flow

```
data/forms/*.json  ──┐
                      ├─► parser.discover_all() ──► build_inventory.build() ──► output/*.xlsx
data/workflows/*.json ┤                         └──► build_explorer.build()  ──► output/*.html
data/manual/*.json  ──┘
```

### parser.py internals

**Form parsing** (`parse_form`):
- `_walk()` recursively visits the `Components` tree, skipping layout containers (`LAYOUT_TYPES`), collecting data fields.
- Each field extracts name, label, data type, component type, required/hidden/enabled flags.
- `FormRelationshipInput` fields produce `relationships` (form-to-form links).
- `FormRelationshipReferenceDataInput` fields produce `refPulls` (cross-form data pulls).
- Form display name is resolved by `_guess_form_name(stem)` which checks `form_aliases.json` first, then falls back to a regex heuristic.

**Workflow parsing** (`parse_workflow`):
- Resolves form/field names via `ExternalReferences` GUID→name lookup.
- **Before building `ref_by_id`**, all `FormName` values in `ExternalReferences` are normalized through `canonicalize_name()` so stale/abbreviated names in workflow exports are corrected.
- Extracts trigger (form, condition, timing) and steps/actions (target form, field assignments, duplicate policy).
- Produces `fieldUsage` rows for every field the workflow reads or writes.

**`discover_all()`** walks both folders, merges results, and auto-stubs any referenced-but-unprovisioned forms as role `"Lookup"`.

---

## Manual override files (`data/manual/`)

### `form_aliases.json`
Two sections in one file:

**Filename-to-display-name mapping** (top-level keys = filename stem without `.json`):
```json
{
  "so_cal-esa_whole_home_pp_d__395-inspection_work_order_v77_design__1_": "395 - Inspection Work Order",
  ...
}
```
Add an entry here whenever you add a new form JSON — otherwise the heuristic may guess wrong.

**`name_aliases` section** (maps wrong/stale display names to canonical ones):
```json
{
  "name_aliases": {
    "395X - Inspections": "395 - Inspection Work Order"
  }
}
```
Use this when a workflow JSON's `ExternalReferences` uses a form name that doesn't match the form's canonical display name. `canonicalize_name()` in `parser.py` consults this section when processing every workflow export.

### `workflow_metadata.json`
Keyed by workflow JSON filename stem (no `.json`). Provides:
- `callsign` — short alias used as PK in the Excel Workflows sheet
- `criticality` — High/Med/Low
- `businessProcess` — FK into `business_processes.json`
- `owner` — name and email

### `business_processes.json`
List of real-world process definitions (`ProcessID`, `ProcessName`, `OwnerArea`, `Description`). Loaded directly into the BusinessProcesses sheet of the Excel inventory. If the file is absent, a hardcoded default list is used.

---

## Known quirks / past fixes

**"395X - Inspections" mismatch** — The `create_inspection_workflow.json` export references the inspection form as `"395X - Inspections"` (old platform name) but the form JSON maps to `"395 - Inspection Work Order"`. Without canonicalization this caused a dangling edge in the graph that broke the HTML renderer. Fix: `name_aliases` entry in `form_aliases.json` + `canonicalize_name()` in `parser.py` normalizes the name before GUID→name lookups are built.

**Windows console encoding** — Print statements in `build_inventory.py` and `build_explorer.py` use `->` (ASCII) not `→` (U+2192) to avoid cp1252 encode errors on Windows.

---

## Adding a new form

1. Export the form design JSON from the platform.
2. Drop it in `data/forms/`.
3. Add an entry to `data/manual/form_aliases.json` mapping the filename stem to a clean display name.
4. Run `python scripts/regenerate.py`.

## Adding a new workflow

1. Export the workflow JSON from the platform.
2. Drop it in `data/workflows/`.
3. Optionally add an entry to `data/manual/workflow_metadata.json` with callsign, criticality, owner, businessProcess.
4. If the workflow references any form by a stale name, add a `name_aliases` entry in `form_aliases.json`.
5. Run `python scripts/regenerate.py`.

---

## Dependencies

- Python 3.9+
- `openpyxl` (install: `pip install openpyxl`)
- No other runtime dependencies.
