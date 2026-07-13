# TODO

## Active

(none — plans/01–03 executed 2026-07-02, see Done below and the status headers in
each `plans/*.md` file.)

## Candidates

- Verify the Legacy condition operator enum. Workspace-export trigger conditions render
  some text-field comparisons as `>=` (e.g. "Review Status is at least 'Corrections
  Required'") where equality is almost certainly meant, and operation 12 renders as `?`
  ("compares to" in plain English). The op map in `parser._expr_to_text` was built for
  WFEngine exports; the Legacy enum may differ. Needs platform documentation or a
  controlled experiment — do not guess-change the mapping.
- Render record-metadata `Comparison` guards (LastModifierId vs user GUIDs) compactly
  instead of dropping them — e.g. one "(plus N system-user rules)" suffix. They're
  currently filtered out of condition text deliberately (14 GUID clauses drown the
  readable part, and their operator enum is unverified).
- `regenerate.py` discovers every workspace up to 4× per full rebuild (per-workspace
  builds + global + field index + briefs construct fresh `Workspace` instances). Share
  one `discover_all()` result across the run to cut rebuild time roughly in half.

## Done

**WFEngine workspace-export parsing + workflow write-conflict detection (2026-07-13).**
All five workspace baselines were re-exported by the platform's new workflow engine, which
carries workflows as a top-level `Workflows[]` array (`Triggers`/`Steps` shape) instead of
the old per-form embedded `WorkflowConfigs`. The parser only read the old shape, so every
workspace was silently reporting 0 workflows (111 dropped fleet-wide: liwp 28, nve-qar 1,
sce-be 16, sdge-whp 23, socal-whp 43). `parse_workspace_export` now parses both shapes
through a shared `_parse_wfengine()` helper (also used by individual workflow-file
exports, so the two paths can't drift), normalizes WFEngine's numeric enums
(`WorkflowEngineTriggerType`/`DatabaseActionType`/`...Timing`) to the plain strings the
rest of the pipeline expects, and summarizes `BuiltIn.SendEmail` actions into the same
`"To: … · Subject: …"` shape Legacy notifications use so narration covers both. Fixed a
real bug the one scheduled workflow surfaced: a leftover `databaseAction` value on cron
triggers was overriding the schedule phrasing in `workflow_story` — cron now wins.

Also added a field-write conflict check: the workflow-detail panel now shows a "⚠ Write
conflicts" block when a workflow writes a field another workflow in the same workspace
also writes — a real race with no guaranteed run order — linking to the other workflow.
Scoped to write collisions only, not shared triggers (two workflows firing on the same
event is common and usually intentional). `narrate.build_workflow_conflicts()`, injected
as `DATA.wfConflicts`. Zero conflicts exist in current data; the check guards against
future regressions. All 5 workspaces regenerated.

**Form version history (2026-07-10).** Multiple `_vNN` exports of one form are now
first-class history instead of warned-about duplicates: highest version wins as the
active design, every export on file lands in a per-form `versionHistory` (with
field-level deltas vs the previous version), and the rebuild prints one changelog line
per multi-version form (`395 - Inspection Work Order: v78 -> v79 active (+1 field)`).
Warnings only fire on same-version ties. Surfaces: `Version`/`PriorVersions` columns
(Forms sheet), `Version` (global AllForms), `v79 · 2 versions on file` in the explorer
form panel, newest-first "Version history" section in briefs, and `version` as a
compared meta key in snapshot diffs. `scripts/organize_forms.py` (dry-run/--apply)
swept all 33 loose root-level form exports into canonical `forms/<Form Name>/` folders
across the five workspaces (local-only; data/ is gitignored). Field-compare keys now
live in `parser.FIELD_COMPARE_KEYS` (versioning.py imports them). Tests:
`tests/test_parser_history.py` + two new snapshot-compare cases.

**Version snapshots and compare (2026-07-07).** `scripts/versioning.py` serializes
`discover_all()` output to `output/snapshots/` with a manifest index. Full rebuilds
auto-save when state changes; `--snapshot [LABEL]` captures on demand; `--compare OLD NEW`
reports form/field/workflow/relationship deltas (console + optional JSON). Reuses
`build_registry` fingerprints for design and workflow logic drift. Unit tests in
`tests/test_versioning.py`.

Plans 01–03 executed (2026-07-02) — one working session, all verified end-to-end:

**Drop-anywhere ingestion (plans/01).** Root-level JSONs are routed by detected content
(workspace export → baseline; form/workflow export → override), so file placement no
longer matters. Individual form exports match their baseline form by **field overlap**
(all 33 pending 2026-06 design files resolved correctly; Climate Zones via the
filename-token tiebreak) with `form_aliases.json` as the escape hatch; the filename
regex heuristic survives only for no-baseline workspaces. Same-form version dedup
(v79 beat v78, warned). Stale socal-whp filename aliases removed; unused-alias warning
added. Three stale-name phantom stubs (`Account Management (200)`, `499 - SDGE Fee
Schedule`, `QAR Measures`) fixed with `name_aliases` entries (local-only — data/ is
gitignored). start.bat README.txt/error text rewritten.

**Plain-English briefs (plans/02).** narrate.py rewritten for the program staffer:
platform Description leads each brief, workflow story cards ("Runs when a 310 -
Enrollment Intake record is updated, and only if Enrollment Status is 'Pending
Review'. → Sends an email to operations@maromaes.com — subject …"), labels over API
names, workflow names over callsigns, count_phrase (no "(s)"), plain conditions
(`condition_to_plain`), humanized schedules ("weekly on Monday"), de-braced template
tokens ("{the record's ESA Key}"). Fixed `_expr_to_text` empty-operand joins (the
" AND  AND …" garbage); unrenderable `Comparison` guards are filtered, not shown as
noise. Fixed narrative key-order nondeterminism (sorted set union). Brief page
restructured (What this form is for / What happens automatically / Filling it out /
What changes what + Filled-in-automatically). Explorer JS phrase mirror synced;
narrative wfCondition/writtenBy now carry `{callsign, name}`.

**General improvements (plans/03).** Rebuild summary block (totals + all warnings,
collected once per process in `parser.WARNINGS`); `--check` discovery-only mode;
workflow story panel ("What this does") atop the explorer's workflow detail via
`DATA.wfStories`; per-workspace `forms/index.html` brief indexes + "All form briefs"
landing chips; `TriggerPlain` column in Workflows/AllWorkflows sheets; Excel
WorkflowType fills unified to the graph palette (light red/olive); global sidebar
workflow-reuse panel (pattern/DriftFlag/LiteralTwin from the registry); action-index
precision on wf-edges (`actionIndex` → `data-action-idx`); `#wf=<callsign>` deep link;
brief print page-break rules; start.bat remembers the last-opened view
(`output/last-view.txt`, gitignored).

Graph search box — both explorers. Per-workspace: `runSearch()` (#search input) matches
forms, fields, and workflows by name, prints a match count, tiers results by hop distance
from the match set, and fits to the matches. Global: a `#search` box matches forms and
workspaces and fits to hits. Covers the "find and jump to a form/field on a large graph"
need (socal-whp is 97 forms / 54 workflows).

Workflow trigger/action edges clickable. The edge tap handler's `wf-edge` branch resolves
the workflow from the edge's `WF:<callsign>` endpoint, highlights it, and renders the
workflow-detail panel; action edges then call `scrollToWfAction(targetForm)` to scroll the
matching action card into view and flash its border. Trigger edges open the panel without
scrolling. (Known limitation: scroll matches by target form, not action index — tracked
under Candidates.)

Export button copies form fields as markdown table to clipboard. Columns: API Name,
Label, Type, Required, WF (R/W/C). Respects active filter and sort. All 5 workspaces
regenerated.

Field-detail breadcrumb. Navigation trail above the form heading once two+ forms visited
(A › B › Current). Clicking ancestor back-navigates and truncates forward history. Capped
at 5 entries; clears on panel close. All 5 workspaces regenerated.

Pin a form to the side panel. 'Pin' button in form header locks the panel while clicking
nodes/edges/background updates graph highlights normally. Background tap while pinned
clears highlights only. × or 'Pinned' releases it. All 5 workspaces regenerated.

Copy-to-clipboard on field names. Hover any field row to reveal a ⧉ button next to the
name; click copies the API name and flashes ✓ for 1.5s. Always copies API name regardless
of Name/Label display toggle. navigator.clipboard with execCommand fallback. All 5
workspaces regenerated.

No results message with clear-filter action. Empty state names the query ("No fields
match 'zip'") and offers a 'Clear filter' button that resets the input, refocuses
#field-search, and re-renders the list. All 5 workspaces regenerated.

Persist field-list state across node clicks. formFieldState map keyed by form name;
save on every panel transition (renderForm/renderWorkflow/renderEdge/renderEmpty);
restore on form open. "Lock" button next to #field-search carries the active filter
into unvisited forms. Lock persists in localStorage. All 5 workspaces regenerated.

Dagre hierarchical layout. Added cytoscape-dagre plugin (rankDir:TB, nodeSep:50,
rankSep:100). New "Layout: Dagre" option in the toolbar dropdown alongside existing
layouts. All 5 workspaces regenerated.

Keyboard navigation for field list. Roving-tabindex: Tab from #field-search enters the
list (one tab stop), Tab again leaves. ArrowDown/Up move across group boundaries, clamping
at ends; Home/End jump to first/last. Enter/Space toggle inline detail; Esc collapses
expanded row or returns focus to search. restoreRoving() silently updates tabindexes after
every re-render without stealing focus during filtering. a11y: role=listbox / role=option.
All 5 workspaces regenerated.

Visual marker for intra-form field dependencies. Two badges on field rows: DEP (teal, this
field's formula/visibility/validation references other fields) and REF'D (lime, other fields
on this form reference this one). Precomputed per form render via buildUsedBySet(). Tooltip
text clarifies the direction. All 5 workspaces regenerated.

Sort options for field list. Second dropdown "Sort: Original / Required first / Hidden last /
By type" in the toolbar alongside the Name/Label display toggle. Sorts within each
section/page group; persisted per-browser via localStorage.

Node filter toolbar (scripts/explorer_template.html). Filters button after #theme-toggle,
checkbox dropdown: Workflows·Legacy, Workflows·WFEngine, Workflows·Disabled, Forms·Subforms,
Forms·Lookups, Orphaned. applyFilters() = 4 ordered passes: category → dangling-edge →
filter-hygiene (always-on, hides nodes left with zero visible edges) → Orphaned (degree-0 /
orphaned flag, toggle only). Per-slug localStorage, default all visible, no re-layout.
Regenerated + published across all 5 workspaces.

Circuit-board edge routing. Bezier → round-taxi (orthogonal right-angle) in both
explorer_template.html and global_template.html; field label sits on a horizontal jog.
Coexists with pair-fan logic — shared node-pairs fall back to bundled-bezier arcs so their
labels don't garble. Routes against the Hierarchy (breadthfirst) layout.

Name/Label toggle for field list display. Both name and label extracted; UI toggle picks
which is primary. Persisted per-browser.

Workflow-type colors. Legacy = red, WF Engine = olive (#9fae5a); nodes and trace edges
colored by type from shared --wf-legacy / --wf-engine vars; legend reads "WF Engine".

Cross-workspace reuse registry. WorkflowReuse (pattern-keyed, Invoice chain surfaced),
FormFamilies (design-fingerprint families, reference-replication tagged), FieldTemplates.
Global collision-link suppression: 21 of 47 dropped.

Group fields by section/page. ParentId-chain reconstruction (workspace-flat + nested walk);
fields carry page/section/sort_order. 325 collapses from an 814-field wall to 31 named
measure-groups (~806/808 design fields resolved).

Highlight workflow-touched fields, with direction. Binary .touched highlight plus R/W/C
badges from fieldUsage.

Field detail expands inline beneath the clicked field row. Multiple expand at once; sticky
control bar with Collapse all / Expand all (confirms above 20); chevron marks state; resets
on form change; filter hides non-matching rows without collapsing.
