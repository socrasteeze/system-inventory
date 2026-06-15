# TODO

## Active

1. Persist field-list state across node clicks. Optional toggle to keep filter applied
while switching forms.

## Backlog — ranked by impact

2. "No results" message with clear-filter action when field filter excludes everything.

3. Copy-to-clipboard on field names. Small copy icon next to each.

4. Pin a form to the side panel. Keep detail visible while clicking around.

5. Field-detail breadcrumb. "Where you've been" trail at the top of the panel.

6. Export current view. Copy field info as text or markdown for tickets.

7. Workflow trigger/action edges clickable to jump to the specific action/trigger. Only
the workflow node is clickable now. Granular but risks duplicating intent — evaluate after
relationship-edge clicks are in active use.

## Done

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
