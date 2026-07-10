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

Current workspaces (whole-workspace export baseline; all five also carry root-level individual design exports from 2026-06 that override their main forms):

- `socal-whp` — **Workspace A** (98 forms / 54 workflows)
- `sdge-whp` — **Workspace B** (46 forms / 25 workflows)
- `sce-be` — **Workspace C** (36 forms / 22 workflows)
- `liwp` — **Workspace D** (125 forms / 33 workflows)
- `nve-qar` — **Workspace E** (10 forms / 1 workflow)

`socal-whp` was originally ingested via the individual-file route, then **re-baselined** to a whole-workspace export (its old `forms/`/`workflows/` individual files were deleted as that reset). It has since gained individual `forms/` overrides again. As of 2026-07-10, all five workspaces' individual form exports live in the canonical per-form layout `forms/<Form Name>/<versioned export>.json` (moved there by `scripts/organize_forms.py`); name resolution is content-based, so `form_aliases.json` stem entries are only needed where field-overlap matching can't decide.

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

| Root shape | Format |
|---|---|
| `Forms` array + workspace metadata (`Name`/`DisplayName`) | **whole-workspace export** (the baseline) |
| `Components` tree | individual form design export (override) |
| `Triggers`/`Steps` | individual workflow export (override) |

**Placement doesn't matter — content decides.** Every JSON anywhere under `data/<slug>/` is routed by its detected format: workspace exports become the baseline; form/workflow exports become individual overrides whether they sit at the slug root or in the `forms/`/`workflows/` subfolders (both locations work; nothing requires the subfolders). Only an unrecognized JSON is warned about and skipped.

**Individual form exports are name-resolved by content, not filename.** A design export carries no form name or GUID of its own, and the platform's filename conventions drift (a 2026-06 export batch broke the old regex heuristic on every file). `Workspace._resolve_form_name()` resolves in order: (1) a `form_aliases.json` filename-stem entry — the explicit escape hatch; (2) **field-overlap match** against the workspace baseline — the baseline form sharing the most field names wins when it covers ≥80% of the export's fields with a ≥1.5× margin over the runner-up, near-ties broken by filename-token similarity (handles tiny lookup forms like Climate Zones); (3) the legacy filename regex heuristic, only when there is no baseline to match against (pure individual-file workspaces). Each resolution prints one line (`<file> -> '<form>' (matched N/M fields)`); a low-confidence match warns and names the alias escape hatch. Stale filename aliases (stems matching no file on disk) are warned about.

**Same-form version history.** Multiple exports resolving to the same form (e.g. `_v78` and `_v79` side by side) are **intentional version history**, not a mistake: the highest `_vNN_` filename token wins as the active design (tie → `forms/` placement wins, then filename order), and every export on file is kept as `versionHistory` on the form — a list of `{version, sourceFile, fieldDelta}` entries oldest→newest, where `fieldDelta` records fields added/removed/changed vs the previous version (labels captured at parse time; `None` on the oldest entry). The form also carries `version` (the active `_vNN` as an int, `None` when the token is absent or the form is baseline-only). Each multi-version form prints one changelog info line at rebuild (`[<slug>] <form>: v78 -> v79 active (+1 field)`), which does **not** count as a warning; a warning fires only when the winner *ties* another file on version (same `_vNN` or both tokenless) — that ambiguity needs a `_vNN` token or a deletion to resolve. The canonical drop workflow: export the new design, drop it into `data/<slug>/forms/<Form Name>/` next to the older versions, regenerate.

Version surfaces: `Version`/`PriorVersions` columns in the Forms sheet (active version + superseded list), a `Version` column in the global AllForms sheet, a `v79 · 2 versions on file` line in the explorer's form panel, and a newest-first **"Version history"** section in the per-form brief with plain-English per-version deltas ("Added County."). Snapshot compare reports `version: 78 -> 79` as a form meta change (`versionHistory` itself is deliberately not diffed). One nuance: `versionHistory` is serialized into snapshots, so deleting a superseded history file changes the snapshot fingerprint (a new auto-snapshot is written) while `--compare` reports no field-level differences.

`forms/` and `workflows/` are scanned **recursively** (`rglob`, not `glob`) — a file can sit directly in the folder or be organized one subfolder per form/workflow. **`forms/<Form Name>/` is the canonical home for a form's version history**: drop each new versioned export into the form's folder and the superseded ones stay there as history. Matching against the baseline is by parsed display name (forms) or `(trigger form, name)` (workflows), never by path, so subfolder nesting is purely organizational. `form_aliases.json`/`workflow_metadata.json` still key off the **filename stem**, unaffected by which folder it's nested in. `scripts/organize_forms.py` (dry-run by default, `--apply` to move) sweeps loose individual form exports into their per-form folders.

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

`WorkflowType` appears as a colored column in the Workflows and AllWorkflows sheets. In both explorers, workflow nodes — and their dashed trace edges — are red for Legacy and olive (`#9fae5a`) for WFEngine, colored from shared `--wf-legacy`/`--wf-engine` CSS vars; the legend reads "WF Engine". The Excel column fills (`build_inventory.py`) are light tints of the same palette (light red = Legacy, light olive = WFEngine), so the workbook and the graph read as one color scheme.

---

## Design principles

The two explorers are deliberately separate layers. Keep them that way.

- **Global view (`output/global/global-explorer.html`) — strategic / cross-workspace breadth.** Workspaces as clusters, form-name collisions, duplicate flows. It answers "what spans workspaces, what's duplicated, what does a rename touch." It does not show fields, field detail, or per-field workflow usage.
- **Per-workspace view (`output/<slug>/workspace_explorer.html`) — operational / field-level depth.** Form and field inspection, per-field workflow usage, trigger/action detail. It answers "what is inside this workspace."

The views complement each other; they do not duplicate capability. The bridge between them is one-directional: clicking a form node in the global view shows an **Open in per-workspace explorer** link that deep-links into the operational view (see below). Depth is reached by navigating *to* the per-workspace view, never by importing depth *into* the global view.

When a feature request would add operational detail (fields, field usage, per-record data) to the global view, or strategic cross-workspace rollups into a single workspace view, question it before implementing — it almost always means the work belongs in the other layer, or belongs in a link between them.

### Cross-view deep link

The global view's per-form link points at `../<slug>/workspace_explorer.html#form=<url-encoded form name>`. On load, the per-workspace explorer's `selectFromHash()` reads the `form` hash param, taps the matching node (`cy.$id(name).emit('tap')`), and centers on it — so the operational view opens with that form already selected. Form node IDs in both views are the plain display name, which is what makes the handoff work. A `#wf=<callsign>` hash param does the same for a workflow node (`WF:<callsign>`) — nothing links out to it, it exists for bookmarking/sharing a workflow URL.

### Per-workspace side-panel views

The per-workspace explorer's side panel has **three view categories**, one per click target:

- **Form-detail** — click a node. Shows the form's role, link counts, relationships, touching workflows, and its field list.
- **Edge-detail** — click a relationship edge. Shows every individual relationship the edge carries (its name, via-field, target-match-field, and pull count), even when the edge's graph label is an aggregate like "32 relationships · 87 pulls". Header names the source and target form; "View source/target form" buttons pivot to either endpoint. The active edge gets a teal glow (`edge.sel`) so it's clear which edge drives the panel. Each relationship edge carries its full relationship list on `edge.data('rels')`, populated when elements are built; the aggregated graph label is intentionally lossy, the edge data is not.
- **Field-detail** — click a field within a form's field list. Expands inline with validators, formulas, workflow usage, and the "where is this used?" cross- and intra-form references.

- **Workflow-detail via edge** — click a workflow edge (the dashed trigger/action arrows). The edge tap handler's `kind === 'wf-edge'` branch resolves the workflow from the edge's source/target (`WF:<callsign>`), highlights it, and renders the same workflow-detail panel a workflow-node click produces. For an **action** edge it then calls `scrollToWfAction(targetForm, actionIndex)`, scrolling the matching action card into view and flashing its border. Action edges carry `actionIndex` (their position in the workflow's action list) and cards carry `data-action-idx`, so the exact action is targeted even when two actions share a target form; when the index is absent it falls back to the first card matching `data-action-form`. Trigger edges open the panel without scrolling (the trigger sits at the panel top). Relationship edges fall through to the `kind === 'relationship'` branch (edge-detail above); any other edge kind returns early.

  The workflow-detail panel opens with a **"What this does"** story block — the same `narrate.workflow_story()` prose the briefs use ("Runs when… / → Sends an email to…"), injected as `DATA.wfStories` keyed by callsign — followed by the raw trigger/action/field-usage sections.

**View state is single.** Clicking anywhere replaces the side-panel content — it never stacks. A form-node click renders form-detail, a workflow-node or workflow-edge click renders workflow-detail, a relationship-edge click renders edge-detail, a background click clears the panel; each switch first runs `clearHighlights()` (which also drops the `sel` edge class) so no stale selection or prior view survives. Field-detail is the one nested case: multiple field details expand *within* a single form-detail view, but they reset whenever a different form is opened.

Edge-detail lives only in the per-workspace explorer, not the global view — it is operational, relationship-level depth, which by the design principle above belongs in the operational layer.

---

## Folder structure

```
data/
  <slug>/
    *.json       ← whole-workspace export(s), if using that format (baseline)
    forms/       ← individual form design JSON exports (override the baseline)
                   scanned recursively -- flat, or one subfolder per form:
                   forms/300 - Account Management/300 - Account Management.json
    workflows/   ← individual workflow JSON exports (override the baseline)
                   same recursive scan; optional one subfolder per workflow
    manual/      ← human-maintained overrides and metadata (see below)
output/
  <slug>/        ← per-workspace Excel + HTML
    forms/       ← per-form printable briefs (generated; so the local explorer's "Open full brief" link resolves)
  global/        ← cross-workspace Excel + HTML
  snapshots/     ← version snapshots (<id>.json + manifest.json); git-tracked temporal history
docs/            ← GitHub Pages publish target (HTML only; generated, not hand-edited)
  index.html       landing page listing every view (+ featured-form quick-link chips)
  <slug>/explorer.html
  <slug>/forms/<form>.html   per-form plain-English briefs
  global/explorer.html
scripts/
  parser.py             Workspace class + shared parsing helpers
  narrate.py            deterministic plain-English narration (form summaries + forward field-trigger model)
  build_inventory.py    per-workspace Excel builder
  build_explorer.py     per-workspace HTML builder
  explorer_template.html    per-workspace HTML template (title + preset injected)
  brief_template.html       per-form printable brief shell (title + body injected)
  build_global.py       cross-workspace aggregator (Excel + HTML)
  build_registry.py     reuse/sameness views (WorkflowReuse, FormFamilies, FieldTemplates) + step-4 suppression
  versioning.py         snapshot capture + compare (temporal change tracking)
  organize_forms.py     one-time sweep of loose form exports into forms/<Form Name>/ folders (dry-run; --apply)
  global_template.html      global HTML template
  regenerate.py         rebuild orchestrator (CLI) + docs/ publish
```

---

## Rebuild command

```
python scripts/regenerate.py                 rebuild all workspaces + global
python scripts/regenerate.py --workspace X   rebuild only workspace X (skips global)
python scripts/regenerate.py --global        rebuild only the global aggregator
python scripts/regenerate.py --check         discovery only: counts, orphans, warnings; writes nothing
python scripts/regenerate.py --snapshot [LABEL]
                                             capture a version snapshot (no rebuild)
python scripts/regenerate.py --list-snapshots
                                             list saved snapshots (newest first)
python scripts/regenerate.py --compare OLD NEW [--workspace SLUG] [--compare-json]
                                             diff two snapshots (refs: id, label, latest, previous)
python scripts/regenerate.py --no-snapshot   skip auto-snapshot after a full rebuild
```

Run from the project root after adding or changing any JSON in `data/`. Open the relevant `output/<slug>/workspace_explorer.html` (or `output/global/global-explorer.html`) to confirm the graph.

`--workspace X` intentionally does not rebuild the global view; run with no args (or `--global`) to refresh it. `--check` is the fast "is my data folder sane?" answer — it parses everything and prints per-workspace counts, orphan counts, and all warnings without touching `output/` or `docs/`.

### Version snapshots and compare

Full rebuilds (no flags, or default path) auto-save a **version snapshot** after `publish_docs()` unless `--no-snapshot` is passed. Snapshots serialize the normalized `discover_all()` output — the same substrate the builders consume — under `output/snapshots/`:

- `<id>.json` — full snapshot (all workspaces, forms, fields, workflows, relationships, ref-pulls)
- `manifest.json` — index of snapshots (id, label, created timestamp, per-workspace counts)

If the discovered state is byte-identical to the latest snapshot, a duplicate is not written. Pin a meaningful baseline with a labeled capture: `python scripts/regenerate.py --snapshot pre-migration`.

Compare any two snapshots:

```
python scripts/regenerate.py --compare previous latest
python scripts/regenerate.py --compare 2026-07-01T10-00-00 2026-07-07T14-00-00 --workspace socal-whp
python scripts/regenerate.py --compare baseline pre-migration --compare-json
```

The console report lists forms added/removed/modified (with per-field attribute deltas), workflow trigger/action signature changes, and relationship/ref-pull deltas. `--compare-json` also writes `output/snapshots/compare_<from>_to_<to>.json` for tooling. Snapshot refs accept: full/partial id, exact label, `latest`, or `previous`.

Form design drift uses the same fingerprint as `build_registry._form_fingerprint()`; workflow logic drift uses `_exact_hash()`. Snapshots are intended to be git-tracked alongside `output/` so commit history carries inventory state even though `data/` is gitignored locally.

**Rebuild summary block.** Every run ends with a `Rebuild summary:` block — workspace/form/workflow totals plus every distinct warning collected during the run (`parser.WARNINGS`; each warning prints once per process via the module-level `_PRINTED_ONCE` dedupe, even though discovery runs several times per rebuild). start.bat users see this block directly above the view-choice menu.

### Orphan report

After each workspace's two builders run, `regenerate.rebuild_workspace()` prints an `Orphans:` line via `parser.find_orphans(discovered)` — a read-only diagnostic, no output-file effect. It lists forms that render with **zero graph edges**, computed to match the explorer's degree-0 reality exactly: an edge exists for a relationship whose target form is present, and for each workflow trigger-form / action-target-form. **`refPulls` are not counted** — they fold into relationship pull totals and don't connect a node on their own. Two reasons are distinguished: `unparented grid` (a `Subform` with empty `subformOf` — its parent wasn't in the workspace export, so no `"(embedded grid)"` containment edge was drawn) and `isolated <role>` (a form with no relationship or workflow link). The remedy is the precedence mechanism: drop the form's individual JSON anywhere under `data/<slug>/` to supply the missing links. `Orphans: none` = fully connected. (Acceptance baseline as of this writing: `sdge-whp` 0, `sce-be` 1, `socal-whp`/`liwp` ~39 each — mostly unparented grids those exports don't resolve a parent for.)

`discover()` is **memoized per `Workspace` instance** (`self._discovered`) so the inventory build, explorer build, and orphan report share one parse and the one-time prints (reclassification, role pins) aren't repeated. `discover_all()` constructs fresh instances, so the global build is unaffected.

### Publishing to docs/ (GitHub Pages)

Every `regenerate.py` run ends with `publish_docs()`, which mirrors the built HTML explorers into `docs/` — the GitHub Pages source folder (Pages serves `main` branch `/docs`). This is part of the standing regenerate behavior, not a separate step: a push after regeneration publishes the current views.

- `publish_docs()` scans `output/` for whatever explorers exist and copies them, so `docs/` stays consistent regardless of which build path ran (full, `--workspace`, or `--global`). It also writes `docs/.nojekyll` so Pages serves files verbatim.
- File mapping: `output/<slug>/workspace_explorer.html` → `docs/<slug>/explorer.html`; `output/global/global-explorer.html` → `docs/global/explorer.html`.
- `docs/index.html` is a generated landing page (dark theme matching the explorer) listing the global view plus each workspace, with a one-line description and the last-regenerated timestamp. It is regenerated each run — never hand-edit it.
- **Filename rewrite:** the global explorer's cross-view deep links point at the per-workspace file by its `output/` name (`workspace_explorer.html`). Because the docs copy is renamed `explorer.html`, `publish_docs()` rewrites that string in the global copy so the deep links resolve under Pages. If the per-workspace docs filename ever changes, update that rewrite.
- **Excel stays out of `docs/`.** Pages publishes only the browsable HTML; spreadsheets are pulled from `output/` in the repo. Don't copy `.xlsx` into `docs/`.
- **`docs/field-index.json`** — machine-readable field index published alongside the explorers. See *Field index* below.
- **Per-form briefs** — `emit_form_briefs()` writes a printable plain-English brief per form into **both** `output/<slug>/forms/<form>.html` (so the local explorer's "Open full brief" link resolves when opened from `output/`) and `docs/<slug>/forms/<form>.html` (for Pages), plus a per-workspace **`forms/index.html`** listing every brief grouped by role (featured first). The landing page's workspace cards link to it ("All form briefs →"). Filenames are Windows-illegal-char-stripped form names (`_brief_filename()` mirrors what a browser resolves a plain href to). Briefs are presentation-only — they never touch `field-index.json`. See *Plain-English narration* below.

---

## Plain-English narration (form briefs + workflow stories + "what triggers what")

`scripts/narrate.py` is a **pure, deterministic, filesystem-free** module (no LLM) that turns the discovered data into plain English. **Voice rule: written for the program staffer, not the developer** — field labels over API names (`field_display`/`decamel`), workflow display names over callsigns, spelled-out small numbers and real plurals (`count_phrase`; never "(s)"). `build_explorer.build()` injects `narrate.build_all(data)` as `DATA.narrative` and `narrate.build_workflow_stories(data)` as `DATA.wfStories`; `regenerate.emit_form_briefs()` renders the same output into standalone brief pages. Output shape per form: `{"summary": {role_line, collects, connects, workflows, fields, interactions}, "forward": {<field>: {fields:[{target,kind}], wfCondition:[{callsign,name}], writtenBy:[{callsign,name}]}}}` (wfCondition/writtenBy entries are objects — renderers show the name, keep the callsign for cross-reference). `build_form` iterates a **sorted** field-set union so output is byte-identical across processes (hash randomization would otherwise reorder keys).

- **Workflow stories.** `workflow_story(w, fields_by_form)` → `{title, callsign, when, then:[…], disabled}`: one "Runs when a X record is updated, and only if <plain condition>." sentence plus one sentence per action ("Sends an email to <to> — subject "…"", "Creates a new <form> record, filling in five fields automatically"). Supporting renderers: `condition_to_plain` (operator words: is / is not / is at least / "compares to" for the unmapped `?` op; API names → labels; `== ''` → "is blank"), `humanize_schedule` (Legacy text like `Weekly · day-of-week 1` → "weekly on Monday", plus real 5-part cron), `_debrace` (`{ESAKey}` → `{the record's ESA Key}`). Rendered as cards in the brief ("What happens automatically") and as the "What this does" block atop the explorer's workflow panel; disabled workflows get a "Currently switched off" note. The `TriggerPlain` column in the Workflows/AllWorkflows sheets is `story["when"]`.
- **"What does it collect?" (`collects_line`).** A deterministic one-sentence answer to the high-level "what does this form gather" question, derived from the form's own structure — never hand-written. For a form whose fields carry `section` metadata (individual design exports do; workspace-export subforms don't), it names the section titles ranked by field count: `"It captures A, B, and C."` when ≤4 sections, else `"It is organized into N sections, covering areas such as <top four>."`. `_ADMIN_SECTION_RE` de-prioritizes plumbing sections (Notes, Attachments, Deprecated, Acknowledgement…) so real content leads; a lone section that just echoes the form name (or "Overview") yields `""`. For a **sectionless** embedded grid it falls back to a sample of distinct field labels: `"Each row captures details such as X, Y, and Z."`. Rendered between `role_line` and `connects` in both the brief lead paragraph and the explorer's "What this form does" block. Ranking by count self-prioritizes substantive sections, so no manual section list is needed.
- **Brief page structure** (`regenerate._render_brief`): What this form is for (platform `Description` first, then the role sentence, then the `collects` sentence) → What happens automatically (story cards) → Filling it out (field counts + required list) → What changes what (labels first, API name muted, plus a "Filled in automatically" list from `writtenBy`).
- **Forward inversion is the core idea.** `dependsOn` is stored on the *dependent* field (B records "I depend on A for my visibility"). `build_forward_index()` inverts this once per form to answer "what does changing field A activate" — the exact inverse of the read-side loop in `fieldDetailHTML()` (`explorer_template.html`), reusing the same four kinds (`visibility/formula/validation/filter`). Workflow consequences come from `fieldUsage`: `direction==Condition` ⇒ "helps decide whether the automated step runs"; `direction==Write` ⇒ "filled in automatically by … — normally not edited by hand". `FORWARD_PHRASE`/`KIND_BADGE` are the phrasing catalog; the explorer template keeps a small JS mirror of them in sync (update both together).
- **Where it shows in the explorer:** a "What this form does" prose section + a "Featured" badge in `renderForm()`; a "Changing this field affects" forward block in `fieldDetailHTML()` (capped at 6 + overflow); a collapsed-by-default "Field interactions" rollup listing only fields that actually trigger something; and an opt-in, lazily-mounted **interaction mini-diagram** (a second Cytoscape instance, ≤25 nodes, destroyed on panel switch via `clearHighlights()`). Anti-clutter is deliberate: nothing appears for fields that trigger nothing, and the diagram is off-screen until toggled.
- **Featured forms** are highlighted (gold node ring + "Featured" badge) and surfaced first as quick-link chips on `docs/index.html`. The set is resolved by `Workspace.featured_forms()`: `data/<slug>/manual/featured_forms.json` `{"featured": [names]}` if present, else the `FEATURED_KEYWORDS` default (name-substring match on account/enrollment/assessment/installation/invoice). Exposed as `data["featured"]`.

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

- Keys are workspace-qualified (`"<slug>/<FormDisplayName>"`) so forms that share a display name across workspaces are distinct entries. Example: `"workspace-a/Customer Account"` vs `"workspace-b/Customer Account"`.
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
- Form display name is resolved by `Workspace._resolve_form_name()`: alias entry → field-overlap match against the baseline → filename regex heuristic (`guess_form_name`, kept only as the no-baseline fallback). Relationship targets from `RelatedFormNormalized` payloads are canonicalized through `name_aliases`.

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

- **`WorkflowReuse`** — workflows keyed by **pattern**, not by `_flow_signature` (which degenerates: all Legacy actions are Notifications with empty `targetForm`, collapsing ~65 workflows into one bucket). Pattern key = `(trigger.form, trigger.databaseAction, recipient_roles)`, where `recipient_roles` = sorted `{...Email}` tokens pulled from each `action.matchOn` via `re.findall(r'\{(\w*[Ee]mail\w*)\}', …)`; empty → `("(static/other)",)`. An **exact-hash** per workflow (`sha1` over `databaseAction`, `timing`, `condition`, sorted action tuples, sorted `Write` field usages — deliberately **excluding the trigger form**) detects literal twins. `ExactTwinGroups`/`DriftFlag` measure drift *within* a pattern (`Single` = 1 instance; `Twin` = ≥2 instances, 1 hash; `Drift` = ≥2 instances, >1 hash). The `LiteralTwin` column surfaces **cross-pattern** twins — because the hash excludes the trigger form, two workflows that fire on differently-named forms in different workspaces (e.g. the same logic on `Form A (v2)` in one workspace vs `v1 - Form A` in another) share a hash but land in different pattern keys, which the per-pattern columns structurally cannot see.
- **`FormFamilies`** — forms grouped by design **fingerprint** = `sha1` over the deduped, **case-folded-name + type** set from the field substrate. Case-folding collapses case-variant duplicates (`Zipcode`/`ZipCode`/`ZIPCode`); type is **kept**, so a field re-typed in one workspace (socal-whp's ZIP as `Integer` vs `Text` elsewhere) splits the fingerprint — that is real design drift and isn't hidden. Sheet shows families with `MemberCount ≥ 2` only. `IntentTag` is **role-based per spec**: all members `role==Lookup` → `reference-replication (intentional)`, else `divergence-candidate`. (Consequence of the type-sensitive fingerprint: a shared Lookup table present in three workspaces may form a 3-member family while a fourth workspace is a separate singleton if it typed a key field differently — e.g. as `Integer` vs `Text`.)
- **`FieldTemplates`** — every field keyed by `(name, type)` (literal, not case-folded), recording **spread** across forms (`FormCount`, capped `Forms` list with overflow count). Records spread; never unifies.

**View 4 — explorer anti-spaghetti filter** (`build_global._build_html`). A form-name collision link is suppressed when the collision is reference-replication rather than divergence: suppress when **either** every instance is `role=Lookup` **or** every instance shares one design fingerprint (`reg["formFingerprints"]`). Divergence collisions (same name, differing designs — Invoice, and the divergent subform grids) keep their links. This is **broader than the view-2 role-based `IntentTag`**: the role branch covers Lookup tables whose designs differ slightly across workspaces (a shared reference table with per-workspace field variations — suppressed via role since its fingerprints differ), the fingerprint branch covers design-identical replicated grids. Acceptance: suppression drops a **minority, not "most"** of collision links — 21 of 47 at first ship, **20 of 47 after the 2026-07 design-override re-ingest** (new form versions shifted a fingerprint); divergent subform grids, Invoice, and any other non-reference-replication collisions remain. The kept/suppressed split prints on every global build (`Collision links: N kept, M suppressed`).

All three sheets are **additive**; nothing here changes the `docs/field-index.json` structure (it's a downstream contract).

---

## Manual override files (`data/<slug>/manual/`)

Each workspace owns its overrides. None are required; sensible defaults apply when a file is absent.

### `workspace.json`
Workspace identity. `displayName` is used as the Excel title and the graph heading. Resolution order: this file → the workspace export's own `DisplayName` → the slug. Workspaces ingested via a whole-workspace export don't need this file; if present anyway, it wins (manual = override layer).
```json
{ "slug": "my-workspace", "displayName": "My Workspace Name" }
```

### `featured_forms.json`
Optional. Names the "main" forms to feature — highlighted (gold node ring + "Featured" badge) in the explorer and surfaced first as quick-link chips on `docs/index.html`. Resolved by `Workspace.featured_forms()`. Absent = the keyword default (`FEATURED_KEYWORDS` in `parser.py`: any form whose display name contains account/enrollment/assessment/installation/invoice). Only names that exist in the workspace are kept.
```json
{ "featured": ["Customer Account", "Program Enrollment", "Site Assessment"] }
```

### `form_aliases.json`
Two sections in one file.

**Filename-to-display-name mapping** (top-level keys = filename stem without `.json`):
```json
{ "my_workspace__form_name_v1_design__1_": "Form Display Name" }
```
An **escape hatch, rarely needed**: individual form exports are name-resolved by field overlap against the workspace baseline (see *Ingestion formats*), so no alias entry is required for override files. Add one only when resolution warns it has no confident match (a genuinely new form with no baseline, or a pathological tie). A stale entry whose stem matches no file on disk triggers a rebuild warning — delete those.

**`name_aliases` section** (maps wrong/stale display names to canonical ones):
```json
{ "name_aliases": { "Form Old Name": "Form Canonical Name" } }
```
Use this when an export references a form by a name that doesn't match the form's canonical display name. Two producers of stale names: a workflow JSON's `ExternalReferences` (`Workspace.canonicalize_name()` consults this section for every workflow export), and an individual form export's `RelatedFormNormalized` relationship payloads (canonicalized in `parse_form`). Live examples: sce-be maps `"Account Management (200)" → "200 - Account"`, sdge-whp maps `"499 - SDGE Fee Schedule" → "499 - Fee Schedule"`, nve-qar maps `"QAR Measures" → "Measures"` — all names the 2026-06 design exports use that don't match the baseline; without the alias each would auto-stub a phantom Lookup node.

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

**Stale form name in workflow export** (now historical — `socal-whp` was re-baselined to a workspace export so the affected individual workflow file no longer exists; kept as a reference example of the `name_aliases` mechanism) — a workflow export in `socal-whp` referenced a form by an old platform name that no longer matched the form's canonical display name. Without canonicalization this left a dangling edge that broke the HTML renderer. Fix: `name_aliases` entry in the workspace's `form_aliases.json` + `Workspace.canonicalize_name()` normalizes the name before GUID→name lookups are built.

**Windows console encoding** — Print statements use `->` (ASCII) not `→` (U+2192) to avoid cp1252 encode errors on Windows. Unicode arrows in Excel cell text are fine (written via openpyxl, not printed).

**`build_inventory.build` parameter is `workspace`, not `ws`** — the function body uses `ws` as the local worksheet handle. Passing the `Workspace` in as `ws` would shadow it.

---

## Adding a new workspace

Slug convention: **hyphens** (e.g. `my-workspace`), never underscores.

**Preferred — whole-workspace export:**
1. Create `data/<slug>/` and drop the workspace export JSON at its root.
2. Run `python scripts/regenerate.py`. That's it — workspace name, form names, workflows, and relationships all come from the export; no manual files required.
3. Optionally add `manual/` overrides (workflow callsigns/owners, explorer layout).

**Individual-file route (when no workspace export is available):**
1. Create `data/<slug>/` and add `data/<slug>/manual/workspace.json` with `slug` and `displayName`.
2. Drop form and workflow JSON exports anywhere under `data/<slug>/` (the root works; `forms/`/`workflows/` subfolders also work).
3. Add `form_aliases.json` filename-stem entries — with no workspace baseline to content-match against, names fall back to the filename heuristic, which the platform's current filenames defeat.
4. Run `python scripts/regenerate.py`. Output appears under `output/<slug>/`, and the global view picks the workspace up automatically.

## Updating a form / dropping a new version (surgical update)

1. Export just that form's design JSON from the platform (the filename carries the `_vNN` version token).
2. Drop it into `data/<slug>/forms/<Form Name>/` next to the previous versions — the canonical layout. (Anywhere under `data/<slug>/` also works: content routing sorts it out.) No alias entry needed: the file is matched to its baseline form by field overlap.
3. Regenerate — the rebuild log prints the match decision, one changelog line (`<form>: v78 -> v79 active (+1 field)`), and warns that the individual file now shadows the baseline. Those lines are expected. Older version files **stay in the folder as history** — they feed the brief's "Version history" section and the `PriorVersions` Excel column; no need to delete them.
4. If the new design references a form by a renamed/stale name (rebuild shows a new phantom Lookup node or an auto-stub), add a `name_aliases` entry mapping the stale name to the canonical one.
5. When you re-baseline with a fresh whole-workspace export, delete the individual files (all versions) — that's the explicit reset.

## Adding a new workflow

1. Export the workflow JSON from the platform.
2. Drop it anywhere under `data/<slug>/` (root, `workflows/` flat, or `workflows/<workflow name>/`).
3. Optionally add an entry to that workspace's `workflow_metadata.json` with callsign, criticality, owner, businessProcess.
4. If the workflow references any form by a stale name, add a `name_aliases` entry in `form_aliases.json`.
5. Run `python scripts/regenerate.py` (or `--workspace <slug>`).

---

## Dependencies

- Python 3.9+
- `openpyxl` (install: `pip install openpyxl`)
- No other runtime dependencies.
