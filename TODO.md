# TODO
# Numbered by priority (1 = next). Active = open/in-flight; Backlog = ranked, unscheduled.

## Active

1. Node filter toolbar (scripts/explorer_template.html). BUILT — pending in-browser
verify + push. Filters button after #theme-toggle, checkbox dropdown: Workflows·Legacy,
Workflows·WFEngine, Workflows·Disabled, Forms·Subforms, Forms·Lookups, Orphaned.
applyFilters() = 4 ordered passes: category → dangling-edge → filter-hygiene (always-on,
hides nodes left with zero visible edges by other filters) → Orphaned (degree-0 / orphaned
flag, toggle only). Per-slug localStorage, default all visible, no re-layout (Fit to
recenter). Verify: uncheck Subforms drops ~60 no dangling; uncheck Orphaned clears the 39
degree-0 ghosts (incl. WaterHeaterInformationPre1, ReviewTable, WxMHRGrid) while Program
stays; reload restores. Then commit + push.

2. Circuit-board edge routing. Bezier → round-taxi (orthogonal right-angle) so connectors
read like a circuit board and the field label sits on a horizontal jog. Both
explorer_template.html and global_template.html. Layout resolved: Hierarchy (breadthfirst)
is the working layout — route against it. Must coexist with the existing pair-fan logic
(shared node-pairs get bundled-bezier arcs). Dagre only if Hierarchy still crowds.

3. Toggle for displaying/sorting fields by Name vs Label. Both extracted; UI choice on
which is primary. Quick win — same code area as #4.

## Backlog — ranked by impact

4. Sort options beyond Name/Label. Dropdown: Required-first, Hidden-last,
ComponentType-grouped, Original-order. Extends #3.

5. Visual marker on fields with intra-form dependencies (formulas/validation referencing).

6. Dagre hierarchical layout. Upgrade from breadthfirst if dense views still crowd —
layered DAG, rank separation, cleaner edge routing. Pairs with #2. Conditional.

7. Keyboard navigation. Arrows through field list, Enter expand, Esc collapse, Tab between
search and list.

8. Persist field-list state across node clicks. Optional toggle to keep filter applied
while switching forms.

9. "No results" message with clear-filter action when field filter excludes everything.

10. Copy-to-clipboard on field names. Small copy icon next to each.

11. Pin a form to the side panel. Keep detail visible while clicking around.

12. Field-detail breadcrumb. "Where you've been" trail at the top of the panel.

13. Export current view. Copy field info as text or markdown for tickets.

14. Workflow trigger/action edges clickable to jump to the specific action/trigger. Only
the workflow node is clickable now. Granular but risks duplicating intent — evaluate after
relationship-edge clicks are in active use.

## Done

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
