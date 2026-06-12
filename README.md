# Workflow Inventory

Documentation system for the workflow automations and form architecture of platform workspaces. It ingests JSON exports of forms and workflows and regenerates a filterable spreadsheet and an interactive graph from them.

Two export formats are supported, and they can coexist in one workspace:

- **Whole-workspace export** — one JSON carrying the entire workspace (all forms, embedded workflows, relationships). Dropped at `data/<slug>/*.json`, it becomes the workspace's baseline. No manual name-mapping needed: form display names and workspace identity come from the export itself.
- **Individual form / workflow exports** — one JSON per form or workflow, under `data/<slug>/forms/` and `data/<slug>/workflows/`. When an individual export covers something also present in the workspace baseline, the **individual file always wins** — it's treated as a surgical update to that form. Each shadowing is warned about at rebuild time; re-baselining with a fresh workspace export is the moment to delete the stale individual files.

The project is **multi-workspace**: each workspace lives under `data/<slug>/` (slugs use hyphens, e.g. `sce-be`) and produces its own artifacts under `output/<slug>/`. A global aggregator combines every workspace into one cross-workspace view under `output/global/`. Current workspaces: `socal-whp` (SCE - ESA Whole Home (PP/D), individual-file format) and `sce-be` (SCE - Building Electrification, workspace-export format).

## Live explorer

The browsable explorers are published via GitHub Pages, served from the `docs/` folder:

**https://maroma-it.github.io/system-inventory/**

The landing page lists every view — the global cross-workspace explorer and each workspace's explorer. The published views are regenerated into `docs/` on every rebuild, so each push updates the live site. Spreadsheets are not published; pull the `.xlsx` files from `output/` in the repo directly.

## Purpose

The project answers questions about workflow automations and form architecture that the platform itself does not surface:

- **Impact analysis** — given a field, which workflows, validation rules, formulas, and downstream forms depend on it. "What breaks if I rename this field" gets answered before the change is made.
- **Discoverability** — given a process or task, which automations and forms already touch it. Keeps a duplicate flow from being built.
- **Cross-workspace pattern detection** — given a workflow pattern, whether an equivalent already exists in another workspace. Surfaces consolidation candidates and standardization gaps.
- **Architecture documentation** — a navigable map of the system for a new contributor or successor, without reading raw JSON.
- **Bus-factor mitigation** — externalizes system knowledge that otherwise lives only with the people who built or maintained the workspaces.

### Common questions this answers

- What forms exist in this workspace, and what does each capture?
- If field X is renamed or removed, which workflows and forms break?
- Which workflows fire on changes to the customer master record?
- Where is field X used — across forms, workflows, validation rules, and formulas?
- Do workflows in different workspaces duplicate each other's logic?
- Which automations run on a schedule, and when?

## Scope

**In scope:**

- Static metadata extraction from form and workflow JSON exports.
- Normalized inventory and dependency graph generation.
- Field-level "Where Is This Used?" inspection, cross-form and intra-form.
- Multi-workspace aggregation and cross-workspace pattern detection.
- Read-only consumption interfaces: Excel inventory, browser-based explorer, zero-knowledge launcher.

**Not in scope:**

- Real-time data inspection. The inventory captures architecture, not record values.
- Editing or write-back to the platform. Form and workflow changes happen in the platform; the inventory reflects them after re-export.
- Live or streaming ingestion. JSON exports are manual today; automated ingestion is a separate future track dependent on platform webhook availability.
- Operational analytics. The inventory feeds analytics but is not itself a reporting layer.
- Platform-side enforcement. The inventory documents what exists; it does not prevent changes it would flag as impactful.

Per workspace:

- **`output/<slug>/workflow_master_inventory.xlsx`** — normalized spreadsheet inventory. One row per form, field, relationship, workflow, action, and field-usage event. Field rows also carry validators, computed formulas, filter/visibility conditions, default values, and the same-form fields each references. Filterable for impact analysis ("what breaks if I rename field X").
- **`output/<slug>/workspace_explorer.html`** — interactive graph. Open in any browser. Zoom, pan, click forms to inspect fields, click the workflow node to see what it touches. Field detail answers "where is this used?" across forms and within the form. Light/dark toggle in the toolbar.

Across all workspaces:

- **`output/global/cross-workspace-inventory.xlsx`** — every workspace in one workbook, plus form-name collision and duplicate-flow analysis.
- **`output/global/global-explorer.html`** — single graph with each workspace as a cluster and duplicate form names linked across clusters. Form nodes link back into the per-workspace explorer.

## Quick start for read-only users

If you just want to see the latest inventory and have never touched Python or git, use the launcher for your platform — no terminal required.

- **Windows:** double-click **`refresh-and-open.bat`**
- **macOS / Linux:** double-click **`refresh-and-open.command`** (first time on macOS, right-click → **Open** to clear the security prompt)

The launcher:

1. Pulls the latest data and code (`git pull`) if git is available — and continues with the local copy if not.
2. Rebuilds the Excel and HTML artifacts.
3. Asks which view to open — a workspace by number, or the combined cross-workspace view (the default) — and opens it in your browser.

If something is missing it prints plain-English instructions instead of failing silently. The one thing it can't install for you is Python itself: get it from <https://www.python.org/downloads/> and check **Add Python to PATH** during install (Windows). Everything else — dependencies included — the launcher offers to set up.

## Folder structure

```
.
├── data/
│   └── <slug>/                  one directory per workspace, e.g. sce-be/ (hyphenated slugs)
│       ├── *.json               ← whole-workspace export(s) — the baseline, if using that format
│       ├── forms/               ← individual form design exports (override the baseline)
│       ├── workflows/           ← individual workflow exports (override the baseline)
│       └── manual/              ← human-maintained overrides
│           ├── workspace.json           (slug + display name)
│           ├── form_aliases.json        (filename → display name; plus name_aliases)
│           ├── workflow_metadata.json   (callsigns, criticality, owners)
│           ├── business_processes.json  (real-world process tagging)
│           └── explorer_layout.json     (optional preset graph positions)
├── output/
│   ├── <slug>/                  ← per-workspace Excel + HTML
│   └── global/                  ← cross-workspace Excel + HTML
├── scripts/
│   ├── parser.py                (Workspace class + shared JSON parser)
│   ├── build_inventory.py       (per-workspace Excel builder)
│   ├── build_explorer.py        (per-workspace HTML builder)
│   ├── build_global.py          (cross-workspace aggregator)
│   ├── explorer_template.html   (per-workspace HTML template)
│   ├── global_template.html     (global HTML template)
│   └── regenerate.py            (rebuild orchestrator)
├── refresh-and-open.bat         (Windows read-only launcher)
├── refresh-and-open.command     (macOS/Linux read-only launcher)
├── requirements.txt
└── README.md
```

## Rebuild command

```
python scripts/regenerate.py                 # rebuild all workspaces + global
python scripts/regenerate.py --workspace X   # rebuild only workspace X
python scripts/regenerate.py --global        # rebuild only the global aggregator
```

Run from the project root after adding or changing any JSON under `data/`, then open the relevant file in `output/<slug>/` (or `output/global/`) to confirm.

## First-time setup

```bash
# Install Python deps
pip install -r requirements.txt

# Generate artifacts from the JSONs already in data/
python scripts/regenerate.py
```

Python 3.9 or newer. `openpyxl` is the only runtime dependency.

## Standing operating procedure

When new JSONs come from the platform:

1. Export from the platform UI — either the whole workspace (one JSON) or an individual form/workflow.
2. Drop it in place: a workspace export goes at `data/<slug>/` (root); individual exports go into `data/<slug>/forms/` or `data/<slug>/workflows/`.
3. Run the rebuild: `python scripts/regenerate.py` (or `--workspace <slug>` for just that one). Watch for `!` warnings — each one names an individual file that is shadowing the workspace baseline.
4. Open `output/<slug>/workspace_explorer.html` to confirm the new node/edge appears.
5. Commit + push.

Typical workspace-export lifecycle: baseline the workspace with one full export → update individual forms surgically as they change (each shows a shadow warning, which is expected) → when drift accumulates, re-export the whole workspace and delete the stale individual files.

**Disabled workflows are surfaced, not hidden:** the Workflows sheet carries a Status column (Active/Disabled), and the explorers render disabled workflows dimmed with an `(off)` label and a Disabled badge — a configured-but-not-running automation is flagged, never drawn identically to a live one. Subforms (embedded grids from workspace exports) appear as their own slate-colored nodes linked to their parent form.

## Manual tagging

Files in `data/<slug>/manual/` override or annotate without touching the auto-discovered data. None are required; sensible defaults apply when absent.

- **`workspace.json`** — the workspace `slug` and `displayName` (used as the Excel title and graph heading).
- **`form_aliases.json`** — maps the messy export filename to a clean display name (e.g. `so_cal-esa_whole_home_pp_d__300-account_management_v342_design` → `300 - Account Management`). Its `name_aliases` section corrects stale form names that workflow exports still reference.
- **`workflow_metadata.json`** — assigns each workflow its callsign, criticality, owner, and business process.
- **`business_processes.json`** — defines the real-world processes workflows can be tagged against.
- **`explorer_layout.json`** — optional preset node positions for the graph; without it the explorer uses a force-directed layout.

Edit these in any editor, then re-run `regenerate.py`.

## Adding a new workspace

**With a whole-workspace export (preferred):** create `data/<slug>/` (hyphenated slug), drop the export JSON at its root, and regenerate. Workspace name, forms, workflows, and relationships all come from the export — no manual files needed.

**With individual files:**

1. Create `data/<slug>/forms/`, `data/<slug>/workflows/`, and `data/<slug>/manual/`.
2. Add `data/<slug>/manual/workspace.json` with the `slug` and `displayName`.
3. Drop form and workflow JSON exports into the respective folders, and add `form_aliases.json` entries as needed.
4. Run `python scripts/regenerate.py`. Output appears under `output/<slug>/`, and the global view picks the workspace up automatically.

## Adding a new workflow (individual export)

1. Build the workflow in the platform and export its JSON.
2. Save it into `data/<slug>/workflows/`.
3. Optionally add an entry to that workspace's `workflow_metadata.json` with a callsign and criticality rating (key by filename stem; workflows embedded in a workspace export key by workflow name instead).
4. If the workflow references a form by a stale name, add a `name_aliases` entry in `form_aliases.json`.
5. Regenerate.

## Adding or updating a form (individual export)

1. Export the form design JSON.
2. Save it into `data/<slug>/forms/`.
3. Add an entry to that workspace's `form_aliases.json` mapping the filename to a display name. If the form also exists in a workspace-export baseline, the display name must match the export's spelling exactly — that match is what makes the individual file override the baseline.
4. Regenerate.

## Data sensitivity

This repository contains the schema and structure of utility company workflow and form configurations. It does **not** contain customer data or PII — only field names and labels.

## License

Proprietary. All rights reserved. Internal use only — not for
distribution outside authorized personnel. See NOTICE for full terms.
