# SoCal WHP Workflow Inventory

Documentation system for the workflow automations and form architecture across the SCE - ESA Whole Home (PP/D) workspace.

Provides two artifacts, both regenerated from raw JSON exports:

- **`output/workflow_master_inventory.xlsx`** — normalized spreadsheet inventory. One row per form, field, relationship, workflow, action, and field-usage event. Filterable for impact analysis ("what breaks if I rename field X").
- **`output/workspace_explorer.html`** — interactive graph view. Open in any browser. Zoom, pan, click forms to inspect fields, click the workflow node to see what it touches.

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
│   ├── forms/              ← drop form profile JSON exports here
│   ├── workflows/          ← drop workflow JSON exports here
│   └── manual/             ← human-maintained metadata
│       ├── form_aliases.json         (filename → clean display name)
│       ├── workflow_metadata.json    (callsigns, criticality, owners)
│       └── business_processes.json   (real-world process tagging)
├── output/                 ← generated artifacts (commit or .gitignore — your call)
├── scripts/
│   ├── parser.py           (shared JSON parser)
│   ├── build_inventory.py  (Excel builder)
│   ├── build_explorer.py   (HTML builder)
│   ├── explorer_template.html
│   └── regenerate.py       (one-command rebuild)
└── README.md
```

## Standing operating procedure

When new JSONs come from the platform:

1. Export the form profile or workflow JSON from the platform UI.
2. Drop it into the matching folder under `data/`.
3. Run the rebuild:
   ```
   python scripts/regenerate.py
   ```
4. Open `output/workspace_explorer.html` in a browser to confirm the new node/edge appears.
5. Commit + push.

## First-time setup

```bash
# Install Python deps
pip install openpyxl

# Generate artifacts from the JSONs already in data/
python scripts/regenerate.py
```

Python 3.9 or newer. No other dependencies.

## Manual tagging

Three files in `data/manual/` let you override or annotate without touching the auto-discovered data:

- **`form_aliases.json`** — maps the messy export filename to a clean display name (e.g. `so_cal-esa_whole_home_pp_d__300-account_management_v342_design` → `300 - Account Management`).
- **`workflow_metadata.json`** — assigns each workflow its callsign, criticality, owner, and which business process it serves.
- **`business_processes.json`** — defines the real-world processes workflows can be tagged against.

Edit these files in any editor. Re-run `regenerate.py` to apply changes.

## Adding a new workflow

1. Build the workflow in the platform.
2. Export its JSON.
3. Save into `data/workflows/`.
4. Optionally add an entry to `data/manual/workflow_metadata.json` with a callsign and criticality rating.
5. Regenerate.

## Adding a new form

1. Export the form design JSON.
2. Save into `data/forms/`.
3. Add an entry to `data/manual/form_aliases.json` mapping filename to display name.
4. Regenerate.

## Data sensitivity

This repository contains the schema and structure of utility company workflow and form configurations. It does **not** contain customer data or PII — only field NAMES and labels.

## License

Internal use only.
