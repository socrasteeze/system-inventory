# Workflow Inventory

Documentation system for the workflow automations and form architecture of platform workspaces. It ingests JSON exports of forms and workflows and regenerates a filterable spreadsheet and an interactive graph from them.

Two export formats are supported, and they can coexist in one workspace:

- **Whole-workspace export** — one JSON carrying the entire workspace (all forms, relationships, and workflows). It becomes the workspace's baseline. No manual name-mapping needed: form display names and workspace identity come from the export itself. Workflows arrive in whichever shape the platform used when the export was taken — the older Legacy system embeds them per form; the newer WF Engine carries them as a top-level array — and both are parsed into the same normalized model.
- **Individual form / workflow exports** — one JSON per form or workflow. When an individual export covers something also present in the workspace baseline, the **individual file always wins** — it's treated as a surgical update to that form. Each shadowing is warned about at rebuild time; re-baselining with a fresh workspace export is the moment to delete the stale individual files.

**Placement is automatic.** Drop any export JSON anywhere under `data/<slug>/` — the rebuild detects what each file is by its content and routes it (workspace export → baseline; form/workflow export → override). The `forms/` and `workflows/` subfolders still work (scanned recursively — flat, or one subfolder per form/workflow), but nothing requires them. Individual form exports are matched to their baseline form by **field overlap**, not filename, so no name-mapping is needed for overrides either.

The project is **multi-workspace**: each workspace lives under `data/<slug>/` (slugs use hyphens, e.g. `sce-be`) and produces its own artifacts under `output/<slug>/`. A global aggregator combines every workspace into one cross-workspace view under `output/global/`. Add workspaces by placing JSON exports under `data/<slug>/` and running the rebuild.

## Live explorer

The browsable explorers are published via GitHub Pages, served from the `docs/` folder:

**https://&lt;your-org&gt;.github.io/system-inventory/**

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
- **What changed since the last rebuild or baseline?** Version snapshots under `output/snapshots/` capture normalized discovery state; `--compare` reports form, field, workflow, and relationship deltas.
- **Do two workflows write the same field?** The explorer flags it directly on the workflow panel — a real race, since nothing guarantees which of two independently-triggered workflows runs last.

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
- **`output/<slug>/workspace_explorer.html`** — interactive graph. Open in any browser. Zoom, pan, click forms to inspect fields, click the workflow node to see what it touches. Field detail answers "where is this used?" across forms and within the form. The workflow panel also warns when it writes a field another workflow writes too, with a link to the other workflow. Light/dark toggle in the toolbar.

Across all workspaces:

- **`output/global/cross-workspace-inventory.xlsx`** — every workspace in one workbook, plus form-name collision and duplicate-flow analysis.
- **`output/global/global-explorer.html`** — single graph with each workspace as a cluster and duplicate form names linked across clusters. Form nodes link back into the per-workspace explorer.
- **`docs/field-index.json`** — machine-readable field index published to GitHub Pages on every rebuild. Maps `"<slug>/<FormDisplayName>"` to an array of `{"name", "label", "type"}` for every field on that form, across all workspaces. This is a stable integration interface — its structure is a contract for external tools (currently a PDF field-mapper). Do not change key format or field names without migrating consumers.

## Quick start for read-only users

If you just want to see the latest inventory and have never touched Python or git, use the launcher for your platform — no terminal required.

- **Windows:** double-click **`start.bat`**
- **macOS / Linux:** double-click **`refresh-and-open.command`** (first time on macOS, right-click → **Open** to clear the security prompt)

The launcher:

1. Checks out `main` and pulls the latest data and code (`git checkout main` + `git pull`) if git is available — and continues with the local copy if not.
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
│       │   └── <form name>/     ← one subfolder per form: drop each new _vNN version here;
│       │                          older versions stay as history (scanned recursively)
│       ├── workflows/           ← individual workflow exports (override the baseline)
│       │   └── <workflow name>/ ← optional: one subfolder per workflow, scanned recursively
│       └── manual/              ← human-maintained overrides
│           ├── workspace.json           (slug + display name)
│           ├── form_aliases.json        (filename → display name; plus name_aliases)
│           ├── form_roles.json          (explicit Lookup/Spoke role pins)
│           ├── workflow_metadata.json   (callsigns, criticality, owners)
│           ├── business_processes.json  (real-world process tagging)
│           └── explorer_layout.json     (optional preset graph positions)
├── output/
│   ├── <slug>/                  ← per-workspace Excel + HTML
│   ├── global/                  ← cross-workspace Excel + HTML
│   └── snapshots/               ← version snapshots (<id>.json + manifest.json)
├── scripts/
│   ├── parser.py                (Workspace class + shared JSON parser)
│   ├── narrate.py               (deterministic plain-English narration)
│   ├── build_inventory.py       (per-workspace Excel builder)
│   ├── build_explorer.py        (per-workspace HTML builder)
│   ├── build_global.py          (cross-workspace aggregator)
│   ├── build_registry.py        (cross-workspace reuse/sameness views)
│   ├── versioning.py            (snapshot capture + compare)
│   ├── organize_forms.py        (sweep loose form exports into forms/<Form Name>/ folders)
│   ├── expand_subform_ops.py    (generate a workflow import: mass-add SubformOperations from a CSV)
│   ├── explorer_template.html   (per-workspace HTML template)
│   ├── global_template.html     (global HTML template)
│   └── regenerate.py            (rebuild orchestrator)
├── start.bat                    (Windows read-only launcher)
├── refresh-and-open.command     (macOS/Linux read-only launcher)
├── requirements.txt
└── README.md
```

### Where each export goes

Anywhere under the workspace's slug directory (`data/<slug>/`, hyphenated — e.g. `data/sce-be/`). **The rebuild routes each JSON by its content, not its location:**

| You exported… | What the rebuild does with it |
|---|---|
| The **whole workspace** (one JSON, all forms + workflows) | Baseline. Sets the workspace name, all forms, embedded workflows, and relationships. |
| A **single form** design | Surgical override — matched to its baseline form by **field overlap** (no filename mapping needed), replaces that form's fields/relationships. **Always wins** over the baseline. |
| A **single workflow** | Surgical override, matched by `(trigger form, name)`. **Always wins** over the baseline. |

The `forms/` and `workflows/` subfolders still work, scanned recursively; the slug root works just as well. The canonical layout is **one subfolder per form** (`forms/300 - Account Management/…`) holding that form's versioned exports. Multiple versions of the same form (e.g. `_v78` and `_v79` side by side) are **version history, not a mistake**: the highest `_vNN` wins as the active design, older files stay as history, and the rebuild prints one changelog line per multi-version form (`395 - Inspection Work Order: v78 -> v79 active (+1 field)`). The active version and its predecessors show up in the Excel Forms sheet (`Version` / `PriorVersions`), the explorer's form panel (`v79 · 2 versions on file`), and a "Version history" section in the form's brief with plain-English per-version changes. A warning only fires when two files carry the *same* version number. The baseline and individual overrides can coexist; when both describe the same form/workflow, the individual file is treated as the newer surgical update, and each shadowing prints a `!` warning at rebuild so a stale override stays visible. When you re-export the whole workspace, delete the individual files (all versions). `python scripts/organize_forms.py` (dry-run; add `--apply`) sweeps loose form exports into their per-form folders.

For a brand-new workspace there's nothing to pre-create with the whole-workspace route — just make `data/<slug>/`, drop the export at its root, and regenerate. See **Adding a new workspace** below.

## Rebuild command

```
python scripts/regenerate.py                 # rebuild all workspaces + global
python scripts/regenerate.py --workspace X   # rebuild only workspace X
python scripts/regenerate.py --global        # rebuild only the global aggregator
python scripts/regenerate.py --check         # discovery only: counts, orphans, warnings; writes nothing
python scripts/regenerate.py --snapshot [LABEL]   # capture a version snapshot (no rebuild)
python scripts/regenerate.py --list-snapshots     # list saved snapshots
python scripts/regenerate.py --compare OLD NEW [--workspace SLUG] [--compare-json]
python scripts/regenerate.py --prune-snapshots [N]  # delete old unlabeled snapshots, keep newest N (default 5)
```

Full rebuilds auto-save a version snapshot after publish (skipped when unchanged vs `latest`, or when `--no-snapshot` is passed). Snapshots live in `output/snapshots/` and record the normalized discovery state — forms, fields, workflows, relationships — so you can diff two points in time even when `data/` is not in git. Compare with `previous latest`, snapshot ids, or labels; scope to one workspace with `--workspace`. Snapshots are large (~70 MB each), so each auto-snapshot is followed by an auto-prune down to the newest 5 unlabeled snapshots; **labeled snapshots are never pruned**, so pin anything worth keeping with `--snapshot LABEL`.

Run from the project root after adding or changing any JSON under `data/`, then open the relevant file in `output/<slug>/` (or `output/global/`) to confirm. Every run ends with a **Rebuild summary** block — totals plus every warning in one place, so nothing scrolls away unseen (`start.bat` shows it right above its view-choice menu). `start.bat` also remembers the last view you opened and offers it as the Enter-key default next time.

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
2. Drop it anywhere under `data/<slug>/` — the rebuild routes it by content (root, `forms/`/`workflows/` flat, or in their own subfolder, all scanned recursively). Give the file a clean, self-describing name — it makes the folder readable at a glance instead of carrying the platform's raw export filename.
3. Run the rebuild: `python scripts/regenerate.py` (or `--workspace <slug>` for just that one). Watch for `!` warnings — each one names an individual file that is shadowing the workspace baseline.
4. Read the per-workspace **`Orphans:`** line in the rebuild output (see below).
5. Open `output/<slug>/workspace_explorer.html` to confirm the new node/edge appears.
6. Commit + push.

**Orphan check.** After each workspace builds, the rebuild prints an `Orphans:` line listing any form or grid that renders with **no graph edge** — either an embedded grid whose parent form wasn't in the workspace export (`unparented grid`), or a form with no relationship or workflow link (`isolated …`). These show up as floating, disconnected nodes in the explorer (toggle the **Orphaned** filter to see them). The usual remedy is to export that form individually and drop its JSON anywhere under `data/<slug>/`, which supplies the relationships the whole-workspace export left out; re-run and the node connects. `Orphans: none` means every form is reachable in the graph. The check is read-only — it never changes the output, just surfaces what to look at.

Typical workspace-export lifecycle: baseline the workspace with one full export → drop each form's new versioned export into its `forms/<Form Name>/` folder as it changes (each shows a shadow warning, which is expected; older versions accumulate as history) → when drift accumulates, re-export the whole workspace and delete the individual files (all versions).

**Disabled workflows are surfaced, not hidden:** the Workflows sheet carries a Status column (Active/Disabled), and the explorers render disabled workflows dimmed with an `(off)` label and a Disabled badge — a configured-but-not-running automation is flagged, never drawn identically to a live one. Subforms (embedded grids from workspace exports) appear as their own slate-colored nodes linked to their parent form.

## Manual tagging

Files in `data/<slug>/manual/` override or annotate without touching the auto-discovered data. None are required; sensible defaults apply when absent.

- **`workspace.json`** — the workspace `slug` and `displayName` (used as the Excel title and graph heading).
- **`form_aliases.json`** — two escape hatches, both rarely needed. Filename-stem entries (keyed the same regardless of whether the file sits flat in `forms/` or in its own subfolder) force a display name when content-matching can't resolve one (form exports are normally matched to the baseline by field overlap automatically). The `name_aliases` section corrects stale form names that exports still reference (e.g. `"Account Management (200)" → "200 - Account"`), which would otherwise create phantom lookup nodes.
- **`form_roles.json`** — explicit role pins (form display name → role), applied last so it always wins. Escape hatch for reference tables the Lookup/Spoke heuristic can't resolve structurally (e.g. `Program`, `Income Thresholds`).
- **`workflow_metadata.json`** — assigns each workflow its callsign, criticality, owner, and business process.
- **`business_processes.json`** — defines the real-world processes workflows can be tagged against.
- **`explorer_layout.json`** — optional preset node positions for the graph; without it the explorer uses a force-directed layout.

Edit these in any editor, then re-run `regenerate.py`.

## Adding a new workspace

**With a whole-workspace export (preferred):** create `data/<slug>/` (hyphenated slug), drop the export JSON at its root, and regenerate. Workspace name, forms, workflows, and relationships all come from the export — no manual files needed.

**With individual files:**

1. Create `data/<slug>/` and add `data/<slug>/manual/workspace.json` with the `slug` and `displayName`.
2. Drop form and workflow JSON exports anywhere under `data/<slug>/`, and add `form_aliases.json` filename entries (with no baseline to content-match against, names come from the filename).
3. Run `python scripts/regenerate.py`. Output appears under `output/<slug>/`, and the global view picks the workspace up automatically.

## Adding a new workflow (individual export)

1. Build the workflow in the platform and export its JSON.
2. Give the file a clean, self-describing name and save it anywhere under `data/<slug>/` — root, or `workflows/` flat or in its own subfolder (recursive scan, path doesn't affect matching).
3. Optionally add an entry to that workspace's `workflow_metadata.json` with a callsign and criticality rating (key by filename stem; workflows embedded in a workspace export key by workflow name instead).
4. If the workflow references a form by a stale name, add a `name_aliases` entry in `form_aliases.json`.
5. Regenerate.

## Adding or updating a form / dropping a new version (individual export)

1. Export the form design JSON (the filename carries the `_vNN` version token — keep it).
2. Save it into `data/<slug>/forms/<Form Name>/` next to any previous versions — the canonical layout. (Anywhere under `data/<slug>/` also works; the recursive, content-routed scan doesn't care about the path.)
3. Regenerate. The rebuild matches the file to its baseline form by field overlap and prints the decision (`<file> -> '<form>' (matched N/M fields)`); if it warns of a low-confidence match, add a `form_aliases.json` filename entry naming the form exactly as the baseline spells it.
4. If the form now has more than one version on file, the rebuild prints a changelog line (`<form>: v78 -> v79 active (+1 field)`), the highest version becomes the active design, and the older files stay as history — feeding the brief's "Version history" section, the explorer's version line, and the `Version`/`PriorVersions` Excel columns. Don't delete old versions unless you're re-baselining.

## Data sensitivity

The `data/` directory (workspace JSON exports) is tracked in this repository. This repo is private — export files may contain embedded notification configurations with email addresses, so keep it that way; do not fork or mirror it to a public location without stripping that data first.

## License

Proprietary. All rights reserved. See NOTICE for full terms.
