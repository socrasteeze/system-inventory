# Plan 03 — General improvements backlog (user-experience review, 2026-07-02)

**Status: EXECUTED 2026-07-02** (same session as plans 01–02). All items shipped:
3.1 (the pending regeneration is committed together with these changes), 3.2 rebuild
summary + `parser.WARNINGS`, 3.3 `workflow_story` panel in the explorer via
`DATA.wfStories`, 3.4 `forms/index.html` per workspace + landing chips, 3.5 TriggerPlain
column + palette unified (Excel fills are now light tints of the graph's red/olive),
3.6 `--check` mode, 3.7 action-index precision, 3.8 global workflow-reuse sidebar panel,
3.9 `#wf=` deep link, 3.10 print page-break rules (a print stylesheet already existed;
extended it), 3.11 start.bat last-view memory (`output/last-view.txt`, gitignored).
Note on 3.5: the plan said Excel "amber/teal" — implemented as light red/olive tints so
the graph palette is canonical, per the plan's own instruction.

**Original spec below.** Items were independent and individually shippable.

## P1 — High value

### 3.1 Commit-hygiene: the working tree carries an unpublished regeneration
Not a code change — a repo state to resolve first. `docs/` has modified explorers/briefs and
`output/*/forms/` + `docs/*/forms/` for four workspaces are untracked (fallout from the last
regen after the panel-resize fix). Until committed and pushed, GitHub Pages and `git pull`-based
`start.bat` machines serve stale views. After plan 01 lands, regenerate once and commit data +
docs + output together.

### 3.2 Rebuild summary at the end of `regenerate.py`
Warnings currently scroll past one workspace at a time and `start.bat` users never scroll back.
Collect all `_warn()` output and orphan counts during the run and print a final block:
`=== Rebuild summary: 5 workspaces, 314 forms, 135 workflows · 2 warnings (listed) · docs/ published ===`.
In `start.bat`, show it right before the view-choice menu so problems are visible at the moment
the user is looking. Cheap to build (the `Workspace` instances already dedupe warnings in
`self._warned`; expose them).

### 3.3 Surface `workflow_story` narration in the explorer's workflow panel
Plan 02 builds plain-English workflow cards for the briefs. The explorer's workflow-detail
panel (workflow node / wf-edge click) still shows raw condition strings and action rows. Reuse
the same `narrate.workflow_story()` output (already injected via `DATA.narrative` — extend the
payload with a per-workflow section) so both surfaces tell the same story. Keeps the
"operational depth lives in the per-workspace view" principle; no global-view changes.

### 3.4 Per-workspace form index page (`docs/<slug>/forms/index.html`)
Briefs are only reachable via a form's explorer panel or a featured chip. Non-technical users
share links to briefs; give them a browsable list: one generated page per workspace listing
every form (grouped by role, featured first) linking to its brief. Add a link from
`docs/index.html` workspace cards ("All form briefs →"). Generated in `emit_form_briefs()`,
never hand-edited — same rules as the landing page.

## P2 — Worthwhile

### 3.5 Humanized cron + trigger phrasing in Excel
Plan 02's cron humanizer and `condition_to_plain` should also feed the Workflows /
AllWorkflows sheets (extra columns `TriggerPlain`, keep the raw ones — Excel consumers filter
on raw values). Amber/teal vs red/olive palette mismatch between Excel and graph (noted in
CLAUDE.md) can be unified in the same pass: pick the graph palette as canonical.

### 3.6 Unused-alias and stale-override hygiene report
Plan 01 adds an "unused alias" warning. Extend to a `--check` mode on `regenerate.py`:
runs discovery only (no writes), prints shadow warnings, unused aliases, orphan report, and
version-dedup decisions. Useful for CI and for a fast "is my data folder sane?" answer without
a 5-workspace rebuild.

### 3.7 Action-index precision on workflow edges *(carried from TODO)*
`scrollToWfAction()` matches on target form, so a workflow with two actions to the same form
always scrolls to the first card. Carry an action index on `wf-edge` data.

### 3.8 Global sidebar: cross-workspace workflow-reuse panel *(carried from TODO)*
`build_registry.compute_registries()` already computes `workflowReuse`
(InstanceCount/Workspaces/DriftFlag/LiteralTwin); `_build_html()` in `build_global.py` never
passes `reg` into the global `viz` dict. Pure sidebar metadata — honors "sameness is metadata,
not topology" and fills the gap left when the global graph went forms-only.

## P3 — Nice to have

### 3.9 Workflow deep-linking (`#wf=<callsign>`) *(carried from TODO)*
Forms have `#form=` deep links; workflows don't. Value is reduced now that the global graph is
forms-only (nothing links out to a workflow node), so this is bookmark/share convenience only.

### 3.10 Brief print stylesheet polish
Briefs are "printable" but have had no print-media pass. Add `@media print` rules: hide the
back-link, black-on-white palette, avoid page-breaks inside workflow cards and table rows.

### 3.11 start.bat: remember last-opened view
Persist the user's last view choice (a one-line file under `output/`) and offer it as the
default instead of always defaulting to global.

## Explicitly not planned (and why)

- **Fields or per-field usage in the global explorer** — violates the two-layer design
  principle in CLAUDE.md (operational depth belongs to the per-workspace view; the deep link is
  the bridge).
- **Auto-inferring a new slug from a bare JSON dropped in `data/` root** — a wrong slug guess
  creates a phantom workspace that pollutes the global view and Pages; the one folder-name
  decision left to the user is cheap and unambiguous.
- **LLM-generated brief prose** — narration must stay deterministic and reproducible on every
  machine that runs `start.bat` (no keys, no drift, stable diffs).
- **Copying `.xlsx` into `docs/`** — standing rule; Pages serves HTML only.

## Standing execution rules (apply to every item)

- After any code change: update CLAUDE.md / README.md / TODO.md in the same commit
  (user's standing instruction).
- Regenerate all workspaces + global and let `publish_docs()` refresh `docs/` before
  committing; never hand-edit anything under `docs/` or `output/`.
- `docs/field-index.json` is a versioned contract — additive changes only.
- ASCII-only in console prints (Windows cp1252).
