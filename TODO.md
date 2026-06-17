# TODO

## Active

(none — backlog cleared 2026-06-16; the four items previously listed here were all
already shipped. Candidates for the next round below.)

## Candidates

- Workflow deep-linking (`#wf=<callsign>`). Forms get `#form=` deep links from the global
  view via `selectFromHash()`; workflows have no equivalent. Add a `wf` hash param so a
  workflow can be linked/centered the same way a form is. Note: value is reduced now that
  the global graph is forms-only — nothing links *out* to a workflow node anymore, so the
  remaining use is bookmarking/sharing a workflow URL by hand, not cross-view navigation.
- Action-index precision on workflow edges. `scrollToWfAction()` matches on target form, so
  a workflow with two actions to the same target form always scrolls to the first. Carry an
  action index on `wf-edge` data to scroll to the exact action card.
- Global sidebar: cross-workspace workflow-reuse panel. List workflows duplicated across
  workspaces from the registry's `workflowReuse` (`InstanceCount` / `Workspaces` /
  `DriftFlag` / `LiteralTwin`), not the coarse `dupFlows` signature. Data is already
  computed by `build_registry.compute_registries()`; it just isn't wired in — `_build_html()`
  in `build_global.py` never passes `reg` into the global `viz` dict. Pure sidebar metadata
  (no graph edges, so it honors "sameness is metadata, not topology"); fills the gap left
  when the global graph went forms-only.

## Done

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
