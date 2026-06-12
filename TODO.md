# TODO

## Active

Field detail should expand inline beneath the clicked field row, not stack
below the field list. Currently each click appends — scrolling problem.

Toggle for displaying/sorting fields by Name vs Label. Both are extracted
already; just a UI choice on which is primary.

## Backlog — sorted roughly by impact

Group fields by section/page in the field list. Form JSONs preserve this
structure under FormSection/FormPage components. Reduces visual load on
large forms (325 has 814 fields).

Highlight workflow-touched fields in the field list. Currently shown only
in the workflow detail view. Marking them in the form's field list lets you
see "of these 353 fields, these 7 are what the workflow actually uses."

Sort options beyond Name/Label. Dropdown: Required-first, Hidden-last,
ComponentType-grouped, Original-order.

Visual marker on fields with intra-form dependencies (formulas/validation
referencing them).

Keyboard navigation. Arrow keys through field list, Enter to expand, Esc to
collapse, Tab between search and list.

Persist field-list state across node clicks. Optional toggle to keep filter
applied while switching forms.

Copy-to-clipboard on field names. Small copy icon next to each.

Pin a form to the side panel. Keep its detail visible while clicking around.

Field-detail breadcrumb. Small "where you've been" trail at the top of the
side panel.

"No results" message with clear-filter action when field filter excludes
everything.

Export current view. Copy field info as text or markdown for pasting into
tickets.

## Done

(move items here as they complete — useful for project history and for
articulating progress in conversations)
