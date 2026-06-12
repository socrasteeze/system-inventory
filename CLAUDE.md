# SoCal WHP Workflow Inventory — Architecture & Maintenance Notes

Reference for maintaining the inventory pipeline: architecture, data flow, override files, and the rebuild command. Read before modifying the parsers or build scripts.

## What this project is

A documentation system for platform forms and workflows. It ingests JSON exports, parses them into a normalized structure, and produces per-workspace and cross-workspace artifacts.

The project is **multi-workspace**. Each workspace lives under `data/<slug>/` and gets its own output under `output/<slug>/`:

- `output/<slug>/workflow_master_inventory.xlsx` — filterable Excel inventory (forms, fields, relationships, workflows, actions, field usage)
- `output/<slug>/workspace_explorer.html` — interactive browser graph (forms as nodes, relationships as edges, workflow node shows what it touches)

A global aggregator combines every workspace into one view under `output/global/`:

- `output/global/cross-workspace-inventory.xlsx` — all workspaces in one workbook, plus collision and duplicate-flow analysis
- `output/global/global-explorer.html` — single graph with each workspace as a cluster, duplicate form names linked across clusters

No output file is hand-edited. All are regenerated from the JSON exports in `data/`.

The first (and currently only) workspace is `socal-whp` — **SCE - ESA Whole Home (PP/D)**.

---

## Multi-workspace model

A workspace is a directory under `data/` containing `forms/`, `workflows/`, and `manual/`. The `parser.Workspace` class is the unit of work: `Workspace(slug).discover()` parses one workspace; `parser.list_workspaces()` enumerates every workspace on disk (any `data/*` dir holding a `forms/` or `workflows/` folder).

- Per-workspace builders (`build_inventory`, `build_explorer`) take a `Workspace` and write under `output/<slug>/`.
- The global builder (`build_global`) calls `parser.discover_all()` (returns `{slug: discovered}`) and writes under `output/global/`.

Nothing in the scripts is workspace-specific. Display name and graph layout live in the workspace's `manual/` folder (see below), so adding a workspace never means editing code.

---

## Design principles

The two explorers are deliberately separate layers. Keep them that way.

- **Global view (`output/global/global-explorer.html`) — strategic / cross-workspace breadth.** Workspaces as clusters, form-name collisions, duplicate flows. It answers "what spans workspaces, what's duplicated, what does a rename touch." It does not show fields, field detail, or per-field workflow usage.
- **Per-workspace view (`output/<slug>/workspace_explorer.html`) — operational / field-level depth.** Form and field inspection, per-field workflow usage, trigger/action detail. It answers "what is inside this workspace."

The views complement each other; they do not duplicate capability. The bridge between them is one-directional: clicking a form node in the global view shows an **Open in per-workspace explorer** link that deep-links into the operational view (see below). Depth is reached by navigating *to* the per-workspace view, never by importing depth *into* the global view.

When a feature request would add operational detail (fields, field usage, per-record data) to the global view, or strategic cross-workspace rollups into a single workspace view, question it before implementing — it almost always means the work belongs in the other layer, or belongs in a link between them.

### Cross-view deep link

The global view's per-form link points at `../<slug>/workspace_explorer.html#form=<url-encoded form name>`. On load, the per-workspace explorer's `selectFromHash()` reads the `form` hash param, taps the matching node (`cy.$id(name).emit('tap')`), and centers on it — so the operational view opens with that form already selected. Form node IDs in both views are the plain display name, which is what makes the handoff work.

### Per-workspace side-panel views

The per-workspace explorer's side panel has **three view categories**, one per click target:

- **Form-detail** — click a node. Shows the form's role, link counts, relationships, touching workflows, and its field list.
- **Edge-detail** — click a relationship edge. Shows every individual relationship the edge carries (its name, via-field, target-match-field, and pull count), even when the edge's graph label is an aggregate like "32 relationships · 87 pulls". Header names the source and target form; "View source/target form" buttons pivot to either endpoint. The active edge gets a teal glow (`edge.sel`) so it's clear which edge drives the panel. Each relationship edge carries its full relationship list on `edge.data('rels')`, populated when elements are built; the aggregated graph label is intentionally lossy, the edge data is not.
- **Field-detail** — click a field within a form's field list. Expands inline with validators, formulas, workflow usage, and the "where is this used?" cross- and intra-form references.

Workflow edges (the dashed trigger/action arrows) are deliberately **non-interactive** — the workflow node already opens full workflow detail, so its arrows carry only direction. The edge tap handler returns early for any edge whose `kind !== 'relationship'`. (Making workflow edges individually clickable is a deferred backlog item, not an omission.)

**View state is single.** Clicking anywhere replaces the side-panel content — it never stacks. A node click renders form-detail, an edge click renders edge-detail, a background click clears the panel; each switch first runs `clearHighlights()` (which also drops the `sel` edge class) so no stale selection or prior view survives. Field-detail is the one nested case: multiple field details expand *within* a single form-detail view, but they reset whenever a different form is opened.

Edge-detail lives only in the per-workspace explorer, not the global view — it is operational, relationship-level depth, which by the design principle above belongs in the operational layer.

---

## Folder structure

```
data/
  <slug>/
    forms/       ← form profile JSON exports (one file per form)
    workflows/   ← workflow JSON exports (one file per workflow)
    manual/      ← human-maintained overrides and metadata (see below)
output/
  <slug>/        ← per-workspace Excel + HTML
  global/        ← cross-workspace Excel + HTML
docs/            ← GitHub Pages publish target (HTML only; generated, not hand-edited)
  index.html       landing page listing every view
  <slug>/explorer.html
  global/explorer.html
scripts/
  parser.py             Workspace class + shared parsing helpers
  build_inventory.py    per-workspace Excel builder
  build_explorer.py     per-workspace HTML builder
  explorer_template.html    per-workspace HTML template (title + preset injected)
  build_global.py       cross-workspace aggregator (Excel + HTML)
  global_template.html      global HTML template
  regenerate.py         rebuild orchestrator (CLI) + docs/ publish
```

---

## Rebuild command

```
python scripts/regenerate.py                 rebuild all workspaces + global
python scripts/regenerate.py --workspace X   rebuild only workspace X (skips global)
python scripts/regenerate.py --global        rebuild only the global aggregator
```

Run from the project root after adding or changing any JSON in `data/`. Open the relevant `output/<slug>/workspace_explorer.html` (or `output/global/global-explorer.html`) to confirm the graph.

`--workspace X` intentionally does not rebuild the global view; run with no args (or `--global`) to refresh it.

### Publishing to docs/ (GitHub Pages)

Every `regenerate.py` run ends with `publish_docs()`, which mirrors the built HTML explorers into `docs/` — the GitHub Pages source folder (Pages serves `main` branch `/docs`). This is part of the standing regenerate behavior, not a separate step: a push after regeneration publishes the current views.

- `publish_docs()` scans `output/` for whatever explorers exist and copies them, so `docs/` stays consistent regardless of which build path ran (full, `--workspace`, or `--global`). It also writes `docs/.nojekyll` so Pages serves files verbatim.
- File mapping: `output/<slug>/workspace_explorer.html` → `docs/<slug>/explorer.html`; `output/global/global-explorer.html` → `docs/global/explorer.html`.
- `docs/index.html` is a generated landing page (dark theme matching the explorer) listing the global view plus each workspace, with a one-line description and the last-regenerated timestamp. It is regenerated each run — never hand-edit it.
- **Filename rewrite:** the global explorer's cross-view deep links point at the per-workspace file by its `output/` name (`workspace_explorer.html`). Because the docs copy is renamed `explorer.html`, `publish_docs()` rewrites that string in the global copy so the deep links resolve under Pages. If the per-workspace docs filename ever changes, update that rewrite.
- **Excel stays out of `docs/`.** Pages publishes only the browsable HTML; spreadsheets are pulled from `output/` in the repo. Don't copy `.xlsx` into `docs/`.

---

## Data flow

```
data/<slug>/forms/*.json      ──┐
data/<slug>/workflows/*.json   ─┼─► Workspace.discover() ─┬─► build_inventory.build(ws) ─► output/<slug>/*.xlsx
data/<slug>/manual/*.json     ──┘                         └─► build_explorer.build(ws)  ─► output/<slug>/*.html

all workspaces ─► parser.discover_all() ─► build_global.build() ─► output/global/*.xlsx + *.html
```

### parser.py internals

Pure parsing helpers (`_walk`, `_expr_to_text`, `_summarize_*`, `_parse_field_assignments`, `_infer_role`) are module-level and filesystem-free. Everything path-dependent is a method on `Workspace`, which caches the workspace's `form_aliases.json`.

**Form parsing** (`Workspace.parse_form`):
- `_walk()` recursively visits the `Components` tree, skipping layout containers (`LAYOUT_TYPES`), collecting data fields.
- Each field extracts name, label, data type, component type, required/hidden/enabled flags.
- `FormRelationshipInput` fields produce `relationships` (form-to-form links).
- `FormRelationshipReferenceDataInput` fields produce `refPulls` (cross-form data pulls).
- `_extract_field_config()` pulls per-field logic: `validator` (node-level type), computed `formula` (Computed `AdvancedConfiguration` / DropDown `ValueAdvancedConfiguration`), `visibility` (`HiddenAdvancedConfiguration`), conditional-required (`RequiredAdvancedConfiguration`), picklist `filter` (node-level `Filter`), and `defaultValue`. Each yields a `dependsOn` map of the same-form fields it references. References come from a config's `.Fields[].FieldName` array (code-based JS rules) and from `@Field.X` tokens inside builder expressions (`_config_field_refs`, which base64-decodes encoded expressions). This is the intra-form half of the field "Where Is This Used?" view; `refPulls` is the cross-form half.
- Form display name is resolved by `Workspace.guess_form_name(stem)`, which checks the workspace's `form_aliases.json` first, then falls back to a regex heuristic.

**Workflow parsing** (`Workspace.parse_workflow`):
- Resolves form/field names via `ExternalReferences` GUID→name lookup.
- **Before building `ref_by_id`**, all `FormName` values in `ExternalReferences` are normalized through `Workspace.canonicalize_name()` so stale/abbreviated names in workflow exports are corrected.
- Extracts trigger (form, condition, timing) and steps/actions (target form, field assignments, duplicate policy).
- Produces `fieldUsage` rows for every field the workflow reads or writes.

**`Workspace.discover()`** walks the workspace's `forms/` and `workflows/`, merges results, and auto-stubs any referenced-but-unprovisioned form as role `"Lookup"`. Returns a dict that also carries `slug` and `workspaceName`.

### build_global.py internals

- **Form-name collisions** — display names carried by 2+ workspaces. These are the rename-impact targets (the `FormNameCollisions` sheet, teal dashed links in the global graph).
- **Duplicate flows** — workflows sharing a signature `"<trigger action> -> <sorted target forms>"`. Two workflows in different workspaces with the same signature are likely the same flow replicated (the `DuplicateFlows` sheet).

---

## Manual override files (`data/<slug>/manual/`)

Each workspace owns its overrides. None are required; sensible defaults apply when a file is absent.

### `workspace.json`
Workspace identity. `displayName` is used as the Excel title and the graph heading; falls back to the slug if absent.
```json
{ "slug": "socal-whp", "displayName": "SCE - ESA Whole Home (PP/D)" }
```

### `form_aliases.json`
Two sections in one file.

**Filename-to-display-name mapping** (top-level keys = filename stem without `.json`):
```json
{ "so_cal-esa_whole_home_pp_d__395-inspection_work_order_v77_design__1_": "395 - Inspection Work Order" }
```
Add an entry whenever you add a new form JSON — otherwise the heuristic may guess wrong.

**`name_aliases` section** (maps wrong/stale display names to canonical ones):
```json
{ "name_aliases": { "395X - Inspections": "395 - Inspection Work Order" } }
```
Use this when a workflow JSON's `ExternalReferences` uses a form name that doesn't match the form's canonical display name. `Workspace.canonicalize_name()` consults this section for every workflow export.

### `workflow_metadata.json`
Keyed by workflow JSON filename stem (no `.json`). Provides `callsign` (PK in the Excel Workflows sheet), `criticality` (High/Med/Low), `businessProcess` (FK into `business_processes.json`), `owner` (name and email).

### `business_processes.json`
Real-world process definitions (`ProcessID`, `ProcessName`, `OwnerArea`, `Description`). Loaded into the BusinessProcesses sheet. If absent, a hardcoded default list in `build_inventory.py` is used.

### `explorer_layout.json`
Optional preset node positions for the explorer graph: `{ "<form or WF:callsign>": {"x": N, "y": N} }`. When present the graph opens in this hub-and-spoke layout; when absent it falls back to force-directed (`cose`).

---

## Known quirks / past fixes

**"395X - Inspections" mismatch** — `socal-whp`'s `create_inspection_workflow.json` references the inspection form as `"395X - Inspections"` (old platform name); the form JSON maps to `"395 - Inspection Work Order"`. Without canonicalization this leaves a dangling edge that breaks the HTML renderer. Fix: `name_aliases` entry in the workspace's `form_aliases.json` + `Workspace.canonicalize_name()` normalizes the name before GUID→name lookups are built.

**Windows console encoding** — Print statements use `->` (ASCII) not `→` (U+2192) to avoid cp1252 encode errors on Windows. Unicode arrows in Excel cell text are fine (written via openpyxl, not printed).

**`build_inventory.build` parameter is `workspace`, not `ws`** — the function body uses `ws` as the local worksheet handle. Passing the `Workspace` in as `ws` would shadow it.

---

## Adding a new workspace

1. Create `data/<slug>/forms/`, `data/<slug>/workflows/`, `data/<slug>/manual/`.
2. Add `data/<slug>/manual/workspace.json` with `slug` and `displayName`.
3. Drop form and workflow JSON exports into the respective folders.
4. Add `form_aliases.json` (and other overrides) as needed.
5. Run `python scripts/regenerate.py`. Output appears under `output/<slug>/`, and the global view picks the workspace up automatically.

## Adding a new form

1. Export the form design JSON from the platform.
2. Drop it in `data/<slug>/forms/`.
3. Add an entry to that workspace's `form_aliases.json` mapping the filename stem to a clean display name.
4. Run `python scripts/regenerate.py` (or `--workspace <slug>`).

## Adding a new workflow

1. Export the workflow JSON from the platform.
2. Drop it in `data/<slug>/workflows/`.
3. Optionally add an entry to that workspace's `workflow_metadata.json` with callsign, criticality, owner, businessProcess.
4. If the workflow references any form by a stale name, add a `name_aliases` entry in `form_aliases.json`.
5. Run `python scripts/regenerate.py` (or `--workspace <slug>`).

---

## Dependencies

- Python 3.9+
- `openpyxl` (install: `pip install openpyxl`)
- No other runtime dependencies.
