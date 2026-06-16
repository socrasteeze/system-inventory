# Inventory — Architecture & Maintenance Notes

Reference for maintaining the inventory pipeline: architecture, data flow, override files, and the rebuild command. Read before modifying the parsers or build scripts.

## What this project is

A documentation system for platform forms and workflows. It ingests JSON exports (two supported formats — see *Ingestion formats* below), parses them into a normalized structure, and produces per-workspace and cross-workspace artifacts.

The project is **multi-workspace**. Each workspace lives under `data/<slug>/` and gets its own output under `output/<slug>/`:

- `output/<slug>/workflow_master_inventory.xlsx` — filterable Excel inventory (forms, fields, relationships, workflows, actions, field usage)
- `output/<slug>/workspace_explorer.html` — interactive browser graph (forms as nodes, relationships as edges, workflow node shows what it touches). Fields are grouped by section/page and badged R/W/C where a workflow reads/writes/branches on them. A node filter toolbar toggles workflow types, subforms, lookups, and orphans; a layout dropdown switches between Hierarchy, Dagre, and force-directed.

A global aggregator combines every workspace into one view under `output/global/`:

- `output/global/cross-workspace-inventory.xlsx` — all workspaces in one workbook, plus collision and duplicate-flow analysis, and a cross-workspace reuse registry (WorkflowReuse, FormFamilies, FieldTemplates)
- `output/global/global-explorer.html` — single graph with each workspace as a cluster, duplicate form names linked across clusters

No output file is hand-edited. All are regenerated from the JSON exports in `data/`.

Current workspaces (all whole-workspace export format):

- `socal-whp` — **SCE - ESA Whole Home (PP/D)** (Southern California Edison; 97 forms / 54 workflows)
- `sdge-whp` — **SDGE - ESA Whole Home (PP/D)** (San Diego Gas & Electric; 46 forms / 25 workflows)
- `sce-be` — **SCE - Building Electrification** (36 forms / 22 workflows)
- `liwp` — **Low-Income Weatherization Program** (125 forms / 33 workflows)
- `nve-qar` — **Qualified Appliance Replacement** (10 forms / 1 workflow)

`socal-whp` and `sdge-whp` are the same ESA Whole Home (PP/D) program run by two different utilities — largely parallel forms/workflows with real divergence, so they drive most of the cross-workspace name collisions in the global view. `socal-whp` was originally ingested via the individual-file route, then **re-baselined** to a whole-workspace export (its `forms/`/`workflows/` individual files were deleted as the reset; only `manual/` overrides remain — `manual/workspace.json` keeps its display name as "SCE - ESA Whole Home (PP/D)" even though the export's own `DisplayName` is "SoCal - ESA Whole Home (PP/D)").

**Slug naming convention: hyphens**, not underscores (`sce-be`, `socal-whp`).

---

## Multi-workspace model

A workspace is a directory under `data/` containing any of: `forms/`, `workflows/`, `manual/`, and/or one or more root-level whole-workspace export JSONs. The `parser.Workspace` class is the unit of work: `Workspace(slug).discover()` parses one workspace; `parser.list_workspaces()` enumerates every workspace on disk (any `data/*` dir holding a `forms/` or `workflows/` folder, or a root-level `*.json`).

- Per-workspace builders (`build_inventory`, `build_explorer`) take a `Workspace` and write under `output/<slug>/`.
- The global builder (`build_global`) calls `parser.discover_all()` (returns `{slug: discovered}`) and writes under `output/global/`.

Nothing in the scripts is workspace-specific. Display name and graph layout live in the workspace's `manual/` folder (see below), so adding a workspace never means editing code.

---

## Ingestion formats & precedence

Two export formats are supported, detected per file by root shape (`parser.detect_format`):

| Root shape | Format | Where it lives |
|---|---|---|
| `Forms` array + workspace metadata (`Name`/`DisplayName`) | **whole-workspace export** | `data/<slug>/*.json` (slug root) |
| `Components` tree | individual form design export | `data/<slug>/forms/` |
| `Triggers`/`Steps` | individual workflow export | `data/<slug>/workflows/` |

A non-workspace JSON dropped at the slug root is warned about and skipped — individual exports belong in `forms/` and `workflows/`.

### Whole-workspace export

One JSON carries the entire workspace: metadata, all forms (design tree under `FormDesign.Components` — a *flat* list typed by `FormDesignComponentType`, unlike the individual export's nested tree typed by `ComponentType`), a flattened `Fields` array per form, embedded workflows per form (`WorkflowConfigs`), and `FormRelationships`. Key differences from the individual format, all normalized inside `parser.py` so downstream builders are format-agnostic:

- **GUID-based, not name-based.** Relationships, reference pulls, and trigger conditions point at `FormId`/`FieldId` GUIDs that resolve within the file. `parse_workspace_export()` builds a workspace-wide GUID→name index first. Consequence: **no `form_aliases.json` and no `name_aliases` are needed** for workspace-export data — `DisplayName` is carried per form and GUID links can't go stale.
- **Workflows are embedded per-form** under `WorkflowConfigs` (`EventTrigger` like `WorkflowUpsertEventConsts:Create|Update|Scheduled`, dict-shaped `TriggerCondition` with type names *without* the `Dto` suffix, `Actions` with handler-specific `Configuration`). `_ws_parse_workflow()` maps these onto the same internal model `parse_workflow` produces. Notification actions (`NotificationActionHandler`) contribute `Read` field-usage rows for every `{FieldName}` template token that matches a host-form field. Unknown handlers degrade to a generic action row.
- **Workflow identity is `(trigger form, name)`** — two embedded workflows on different forms can share a name (e.g. "Pending Reviews"). Callsigns are de-duped within a workspace (`_2`, `_3` suffixes) since they're node IDs and Excel PKs.
- **Subforms.** Most forms in a workspace export are embedded grids (`FormDesign: null`, `TopLevelFormId` ≠ own `Id`). They get role **`Subform`**, fields from the flattened `Fields` array, and a containment relationship `parent → subform` via `"(embedded grid)"` so they stay connected in the graph. Duplicate display names get parent-qualified (`HouseholdMemberInformation (210 - …)`); an orphan grid whose parent isn't in the export is still a `Subform`, just with no containment edge.
- **Disabled workflows** (`IsEnabled: false`) are surfaced, not hidden: `Status` column (Active/Disabled) in the Workflows and AllWorkflows sheets, and a dimmed, dash-bordered node with an `(off)` label plus a "Disabled" badge in both explorers. Individual workflow exports carry no enabled flag and default to Active.
- **Extras captured:** form `Description`, `AutoIncrementFormFields` (per-field prefix/counter, Fields sheet + field detail), `DuplicateResponseConfiguration` (summarized rules, Forms sheet), `SavedFilters` (names/count only, Forms sheet). `SecurityPolicy` is deliberately not captured.

### Precedence: individual file always wins

Both formats can coexist in one workspace. The workspace export is the **baseline** (all forms at once); an individual form/workflow export for something that also exists in the baseline **always takes precedence** — it's treated as a surgical update. The tiebreaker is *presence*, never file mtime: **git does not preserve mtimes**, so newest-file-wins would resolve differently on every clone (the read-only launcher distributes via `git pull`). Individual-always-wins is deterministic from the file listing alone.

- Form override replaces fields/relationships/refPulls; workspace-only extras (description, saved filters, dup rules) are kept from the baseline.
- Workflow override matches on `(trigger form, name)`.
- Every shadowing prints a rebuild-time warning (`! <form>: individual export (...) overrides workspace baseline (...)`) so stale overrides stay visible. When you re-baseline with a fresh workspace export, delete the stale individual files — that's the explicit reset.
- Multiple workspace exports in one slug root merge in filename order (later wins) before individual files are applied.

---

## WorkflowType

Every workflow carries a `workflowType` field derived from its export format — no manual tagging needed:

- **`Legacy`** — embedded in a workspace export (`WorkflowConfigs` format). This is the older form-notification system.
- **`WFEngine`** — individual workflow export (`Triggers`/`Steps` format). This is the newer workflow engine.

`WorkflowType` appears as a colored column in the Workflows and AllWorkflows sheets (amber = Legacy, teal = WFEngine). In both explorers, workflow nodes — and their dashed trace edges — are red for Legacy and olive (`#9fae5a`) for WFEngine, colored from shared `--wf-legacy`/`--wf-engine` CSS vars; the legend reads "WF Engine". (Note: the graph palette (red/olive) and the Excel-column palette (amber/teal, set in `build_inventory.py`) are not aligned — same `WorkflowType`, two color schemes.)

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
    *.json       ← whole-workspace export(s), if using that format (baseline)
    forms/       ← individual form design JSON exports (override the baseline)
    workflows/   ← individual workflow JSON exports (override the baseline)
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
  build_registry.py     reuse/sameness views (WorkflowReuse, FormFamilies, FieldTemplates) + step-4 suppression
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
- **`docs/field-index.json`** — machine-readable field index published alongside the explorers. See *Field index* below.

---

## Field index (integration artifact)

`publish_docs()` also writes `docs/field-index.json` on every run. This file is a **stable integration interface** consumed by external tools (currently: a PDF field-mapper). Treat its structure as a contract — do not rename keys, remove fields from the per-field objects, or change the key format without versioning or migrating known consumers.

**Structure:**

```json
{
  "<slug>/<FormDisplayName>": [
    {"name": "FieldApiName", "label": "Display Label", "type": "DataType"},
    ...
  ]
}
```

- Keys are workspace-qualified (`"<slug>/<FormDisplayName>"`) so forms that share a display name across workspaces are distinct entries. Example: `"sce-be/Customer Account"` vs `"socal-whp/Customer Account"`.
- Field arrays follow discovery order (design-tree order for individual exports; definition order for workspace exports).
- Lookup stubs (forms referenced but not exported) have an empty field array `[]`.
- The file is generated by `emit_field_index()` in `regenerate.py`, which calls `discover_all()` and pulls `name`, `label`, and `type` from each field dict. Adding new keys to the per-field object is additive and safe; removing or renaming existing keys is a breaking change.

---

## Data flow

```
data/<slug>/*.json (workspace) ──┐
data/<slug>/forms/*.json       ──┤
data/<slug>/workflows/*.json    ─┼─► Workspace.discover() ─┬─► build_inventory.build(ws) ─► output/<slug>/*.xlsx
data/<slug>/manual/*.json      ──┘   (baseline + override   └─► build_explorer.build(ws)  ─► output/<slug>/*.html
                                      merge happens here)

all workspaces ─► parser.discover_all() ─► build_global.build() ─┬─► build_registry.compute_registries(agg)
                                                                │     (WorkflowReuse, FormFamilies, FieldTemplates,
                                                                │      formFingerprints for step-4 suppression)
                                                                └─► output/global/*.xlsx + *.html
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

**Workspace-export parsing** (`parse_workspace_export`, module-level): builds the GUID→name index, resolves display names (with subform parent-qualification for duplicates), parses each form's flat component list through the shared `_node_to_field()` (the same per-node extraction `_walk` uses for nested trees), backfills design-less subforms from the flattened `Fields` arrays, and maps embedded `WorkflowConfigs` onto the internal workflow model. The expression helpers (`_expr_to_text`, `_extract_condition_fields`) accept both JSON-string and dict conditions and match type names by prefix (`Grouping` vs `GroupingDto`).

**`Workspace.discover()`** loads the workspace-export baseline (cached on the instance), overlays individual `forms/` and `workflows/` exports per the precedence rule (warning on each shadow), auto-stubs any referenced-but-unprovisioned form as role `"Lookup"`, and de-dupes workflow callsigns. It then runs two role passes. (1) **Lookup→Spoke reclassification** — `_infer_role` alone tags any form with *no relationship fields* as `Lookup`, which wrongly catches real leaf forms (surveys, inspections, inventory) that simply don't link out. The pass promotes a `Lookup`-tagged form to `Spoke` unless it shows a reference signal: it is a **pull-target** (a `FormRelationshipReferenceDataInput` destination), an **incoming-relationship target** (some form has an FK-like `FormRelationshipInput` edge into it; `"(embedded grid)"` containment edges excluded), or a **0-field auto-stub** (referenced-but-not-exported). Forms with none of those signals are structurally indistinguishable from real standalone forms, so they are promoted. (2) **`form_roles.json` manual override** (see below) runs last and wins in both directions — the escape hatch for irreducibly-ambiguous reference tables the heuristic can't detect (`Program`, `Income Thresholds`, `Project Breakdown Backup`), which have no structural connection of any kind in the export and would otherwise be promoted. Returns a dict that also carries `slug` and `workspaceName`.

### build_global.py internals

- **Form-name collisions** — display names carried by 2+ workspaces. These are the rename-impact targets (the `FormNameCollisions` sheet, teal dashed links in the global graph).
- **Duplicate flows** — workflows sharing a signature `"<trigger action> -> <sorted target forms>"`. Two workflows in different workspaces with the same signature are likely the same flow replicated (the `DuplicateFlows` sheet).

`build()` also calls `build_registry.compute_registries(agg)` (see below). The three registry sheets are appended to the workbook by `build_registry.add_sheets(wb, reg)` inside `_build_excel`, and `_build_html` consumes `reg["formFingerprints"]` for the collision-link suppression filter (view 4).

### build_registry.py internals (reuse / sameness views)

`scripts/build_registry.py` adds three **flat, classifying** views to the global build. Governing rule: **sameness is metadata, not topology** — no view creates instance→instance or form→shared-field edges. The only graph effect is the suppression filter in view 4, which *removes* links, never adds them.

**Field substrate.** The per-field arrays come from `agg["discovered"][slug]["fields"]` (the same source `regenerate.emit_field_index()` reshapes into `docs/field-index.json`), read **in-memory, not from the published JSON**. `build_global` runs *before* `publish_docs()` rewrites that file, so the on-disk copy is one run stale; the in-memory source is current and identical in content. `compute_registries(agg)` is the entry point; `add_sheets(wb, reg)` writes the sheets.

- **`WorkflowReuse`** — workflows keyed by **pattern**, not by `_flow_signature` (which degenerates: all Legacy actions are Notifications with empty `targetForm`, collapsing ~65 workflows into one bucket). Pattern key = `(trigger.form, trigger.databaseAction, recipient_roles)`, where `recipient_roles` = sorted `{...Email}` tokens pulled from each `action.matchOn` via `re.findall(r'\{(\w*[Ee]mail\w*)\}', …)`; empty → `("(static/other)",)`. An **exact-hash** per workflow (`sha1` over `databaseAction`, `timing`, `condition`, sorted action tuples, sorted `Write` field usages — deliberately **excluding the trigger form**) detects literal twins. `ExactTwinGroups`/`DriftFlag` measure drift *within* a pattern (`Single` = 1 instance; `Twin` = ≥2 instances, 1 hash; `Drift` = ≥2 instances, >1 hash). The `LiteralTwin` column surfaces **cross-pattern** twins — because the hash excludes the trigger form, two workflows that fire on differently-named forms in each utility (e.g. Customer Interest Receipt on `Account Management (400)` vs `300 - Account Management`) share a hash but land in different pattern keys, which the per-pattern columns structurally cannot see.
- **`FormFamilies`** — forms grouped by design **fingerprint** = `sha1` over the deduped, **case-folded-name + type** set from the field substrate. Case-folding collapses case-variant duplicates (`Zipcode`/`ZipCode`/`ZIPCode`); type is **kept**, so a field re-typed in one workspace (socal-whp's ZIP as `Integer` vs `Text` elsewhere) splits the fingerprint — that is real design drift and isn't hidden. Sheet shows families with `MemberCount ≥ 2` only. `IntentTag` is **role-based per spec**: all members `role==Lookup` → `reference-replication (intentional)`, else `divergence-candidate`. (Consequence of the type-sensitive fingerprint: Climate Zones resolves as a **3-member** Lookup family `liwp`/`sce-be`/`sdge-whp`, with `socal-whp` a separate singleton, because socal types ZIP as `Integer`.)
- **`FieldTemplates`** — every field keyed by `(name, type)` (literal, not case-folded), recording **spread** across forms (`FormCount`, capped `Forms` list with overflow count). Records spread; never unifies.

**View 4 — explorer anti-spaghetti filter** (`build_global._build_html`). A form-name collision link is suppressed when the collision is reference-replication rather than divergence: suppress when **either** every instance is `role=Lookup` **or** every instance shares one design fingerprint (`reg["formFingerprints"]`). Divergence collisions (same name, differing designs — Invoice, and the divergent subform grids) keep their links. This is **broader than the view-2 role-based `IntentTag`**: the role branch covers Lookup tables whose designs differ slightly across utilities (Climate Zones — suppressed via role since its fingerprints differ), the fingerprint branch covers design-identical replicated grids. Acceptance: suppression drops **21 of 47** collision links (4 all-Lookup + 17 design-identical subform grids), not "most"; the 24 divergent subform grids, Invoice, and any other non-reference-replication collisions remain.

All three sheets are **additive**; nothing here changes the `docs/field-index.json` structure (it's a downstream contract).

---

## Manual override files (`data/<slug>/manual/`)

Each workspace owns its overrides. None are required; sensible defaults apply when a file is absent.

### `workspace.json`
Workspace identity. `displayName` is used as the Excel title and the graph heading. Resolution order: this file → the workspace export's own `DisplayName` → the slug. Workspaces ingested via a whole-workspace export don't need this file; if present anyway, it wins (manual = override layer).
```json
{ "slug": "socal-whp", "displayName": "SCE - ESA Whole Home (PP/D)" }
```

### `form_aliases.json`
Two sections in one file.

**Filename-to-display-name mapping** (top-level keys = filename stem without `.json`):
```json
{ "so_cal-esa_whole_home_pp_d__395-inspection_work_order_v77_design__1_": "395 - Inspection Work Order" }
```
Add an entry whenever you add a new *individual* form JSON — otherwise the heuristic may guess wrong. Not needed for workspace-export forms (they carry `DisplayName`), **but**: when an individual file overrides a baseline form, its alias entry must resolve to the same display name the export uses, or the override won't match and you'll get two forms.

**`name_aliases` section** (maps wrong/stale display names to canonical ones):
```json
{ "name_aliases": { "395X - Inspections": "395 - Inspection Work Order" } }
```
Use this when a workflow JSON's `ExternalReferences` uses a form name that doesn't match the form's canonical display name. `Workspace.canonicalize_name()` consults this section for every workflow export.

### `form_roles.json`
Explicit role pins (form display name → role string), applied as the **final step** of `Workspace.discover()` after the Lookup→Spoke reclassification pass. Keyed by form display name; the file is optional and absent = no-op. Pinned roles override the inferred role in both directions (promote or demote). This is the escape hatch for reference tables the role heuristic can't detect structurally (e.g., `Program`, `Income Thresholds`, which have zero structural connections yet should remain Lookup).

```json
{ "Program": "Lookup", "Income Thresholds": "Lookup", "Project Breakdown Backup": "Lookup" }
```

### `workflow_metadata.json`
Provides `callsign` (PK in the Excel Workflows sheet), `criticality` (High/Med/Low), `businessProcess` (FK into `business_processes.json`), `owner` (name and email). Keying: **filename stem** (no `.json`) for individual workflow exports; **workflow display name** for workflows embedded in a workspace export (they have no file of their own).

### `business_processes.json`
Real-world process definitions (`ProcessID`, `ProcessName`, `OwnerArea`, `Description`). Loaded into the BusinessProcesses sheet. If absent, a hardcoded default list in `build_inventory.py` is used.

### `explorer_layout.json`
Optional preset node positions for the explorer graph: `{ "<form or WF:callsign>": {"x": N, "y": N} }`. When present the graph opens in this hub-and-spoke layout; when absent it falls back to force-directed (`cose`).

### `form_roles.json`
Optional explicit role pins, keyed by form display name → role. Consulted as the **final step** in `Workspace.discover()`, after the Lookup→Spoke reclassification pass, so manual always wins (consistent with `manual/` being the override layer). Works in both directions (force `Lookup`→ or →`Lookup`). Use it for the irreducibly-ambiguous cases the role heuristic can't resolve — reference tables with no structural connection in the export, which would otherwise be promoted to `Spoke`. Missing file = no-op; unrecognized form names warn and skip; each applied pin prints `[<slug>] pinned '<form>' role <from> -> <to>`.
```json
{ "Program": "Lookup", "Project Breakdown Backup": "Lookup" }
```
---

## Known quirks / past fixes

**"395X - Inspections" mismatch** (now historical — `socal-whp` was re-baselined to a workspace export, so `create_inspection_workflow.json` no longer exists and this path isn't triggered; kept as a reference example of the `name_aliases` mechanism) — `socal-whp`'s `create_inspection_workflow.json` referenced the inspection form as `"395X - Inspections"` (old platform name); the form JSON mapped to `"395 - Inspection Work Order"`. Without canonicalization this left a dangling edge that broke the HTML renderer. Fix: `name_aliases` entry in the workspace's `form_aliases.json` + `Workspace.canonicalize_name()` normalizes the name before GUID→name lookups are built.

**Windows console encoding** — Print statements use `->` (ASCII) not `→` (U+2192) to avoid cp1252 encode errors on Windows. Unicode arrows in Excel cell text are fine (written via openpyxl, not printed).

**`build_inventory.build` parameter is `workspace`, not `ws`** — the function body uses `ws` as the local worksheet handle. Passing the `Workspace` in as `ws` would shadow it.

---

## Adding a new workspace

Slug convention: **hyphens** (`sce-be`), never underscores.

**Preferred — whole-workspace export:**
1. Create `data/<slug>/` and drop the workspace export JSON at its root.
2. Run `python scripts/regenerate.py`. That's it — workspace name, form names, workflows, and relationships all come from the export; no manual files required.
3. Optionally add `manual/` overrides (workflow callsigns/owners, explorer layout).

**Individual-file route (when no workspace export is available):**
1. Create `data/<slug>/forms/`, `data/<slug>/workflows/`, `data/<slug>/manual/`.
2. Add `data/<slug>/manual/workspace.json` with `slug` and `displayName`.
3. Drop form and workflow JSON exports into the respective folders.
4. Add `form_aliases.json` (and other overrides) as needed.
5. Run `python scripts/regenerate.py`. Output appears under `output/<slug>/`, and the global view picks the workspace up automatically.

## Updating a form in a workspace-export workspace (surgical update)

1. Export just that form's design JSON from the platform.
2. Drop it in `data/<slug>/forms/` and map its filename stem in `form_aliases.json` to the form's display name *exactly as the workspace export spells it*.
3. Regenerate — the rebuild log warns that the individual file now shadows the baseline. That warning is expected and stays until you either delete the file or re-baseline.
4. When you re-export the whole workspace, delete the now-stale individual files.

## Adding a new form (individual-file workspace)

1. Export the form design JSON from the platform.
2. Drop it in `data/<slug>/forms/`.
3. Add an entry to that workspace's `form_aliases.json` mapping the filename stem to a clean display name.
4. Run `python scripts/regenerate.py` (or `--workspace <slug>`).

## Adding a new workflow (individual-file workspace)

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
