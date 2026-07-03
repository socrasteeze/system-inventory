# Plan 01 — Drop-anywhere ingestion (fix "individual exports belong in forms/ and workflows/")

**Status: EXECUTED 2026-07-02.** All parts implemented and verified: root JSONs route by
detected format; names resolve by field overlap (all 33 pending files matched correctly,
Climate Zones via the filename-token tiebreak); v79 beat v78 with a warning; stale socal-whp
aliases removed and an unused-alias warning added. One finding beyond the plan: the new design
exports reference three forms by stale names (`Account Management (200)`, `499 - SDGE Fee
Schedule`, `QAR Measures`), which auto-stubbed phantom Lookup nodes — fixed with `name_aliases`
entries in sce-be/sdge-whp/nve-qar `manual/form_aliases.json` (note: `data/` is gitignored, so
these live locally only, like all workspace data). Form counts verified back at baseline
(97/46/36/125/10) with zero stubs. Diagnostics now dedupe per process (module-level
`_PRINTED_ONCE`) and warnings collect in `parser.WARNINGS` for the plan-03 rebuild summary.

**Original spec below.** Priority: highest — this is the active user-facing bug.
**Goal:** any platform JSON dropped anywhere under `data/<slug>/` is ingested correctly by
`start.bat` / `regenerate.py` with zero manual file placement and zero alias maintenance.

## The bug, as observed (verified 2026-07-02)

All five workspaces currently have fresh individual form design exports sitting at the slug
**root** next to the whole-workspace export (33 `*_design.json` files total). On every rebuild,
`Workspace.workspace_exports()` (`scripts/parser.py:666-681`) detects them as `form` format and
prints, for each:

```
! socal-whp/so_cal-esa_whole_home(pp_d)_300-account_management_v358_design.json: not a
  workspace export (detected: form) -- skipped. Individual form/workflow exports belong
  in forms/ and workflows/.
```

They are then **silently excluded from the build** — the newer form designs never override the
baseline.

There is a second, worse latent bug: even if these files were moved into `forms/`, they would
**all mis-ingest**. `Workspace.guess_form_name()` (`parser.py:715-736`) assumes a `__` separator
between the workspace prefix and the form name (`so_cal-esa_whole_home_pp_d__300-...`), but the
platform's current export filenames keep parentheses and use a single underscore
(`so_cal-esa_whole_home(pp_d)_300-...`). Tested against every root design file in all five
workspaces: **0 of 33 filenames resolve to a baseline form name** — e.g. the heuristic produces
`'So Cal-Esa Whole Home(Pp D) 300-Account Management'` instead of `'300 - Account Management'`.
Each would therefore create a duplicate phantom form instead of shadowing the baseline. The
existing `form_aliases.json` entries in `data/socal-whp/manual/` are keyed by the **old** stems
(`..._pp_d__300-account_management_v342_design`) and match nothing on disk anymore.

## The fix — three parts

### Part A: route root-level JSONs by detected format, not by folder

`detect_format()` already classifies every JSON as `workspace` / `form` / `workflow`. Change
`Workspace.discover()` (`parser.py:887+`) so folder location stops mattering:

1. In `workspace_exports()`, instead of warn-and-skip non-workspace root JSONs, collect them
   into two new instance lists: `self._root_form_files` and `self._root_workflow_files`
   (store `Path`s). Keep a one-line info print, but make it friendly:
   `[socal-whp] 10 individual form export(s) found at the workspace root -- ingesting as overrides.`
2. In `discover()` step 2 (the `forms_dir` overlay loop at `parser.py:926-943`), iterate
   `sorted(self.forms_dir.glob("*.json")) + sorted(self._root_form_files)` — same code path,
   same precedence semantics (individual always wins over baseline), same shadow warning.
   Do the equivalent for workflows in the workflow overlay loop (`parser.py:~1040`).
3. `list_workspaces()` (`parser.py:629`) already admits any `data/*` dir with a root `*.json`,
   so no change needed there. Verify a slug containing *only* individual exports (no workspace
   export) still builds via this path.

Do **not** physically move or rename user files — ingest them in place. Git-tracked data must
not be shuffled by the build.

### Part B: content-based form-name matching (kill the filename heuristic's failure mode)

The design export JSON carries **no form name or GUID anywhere** — root component
`ExtraProperties` is empty (verified). But field-name overlap against the baseline is a
near-perfect fingerprint. Measured across all 33 pending files: the correct baseline form wins
by a landslide in every case (e.g. `300 - Account Management`: 353 of 357 design fields match
the right form; runner-up matches 31). The single ambiguous case is
`liwp/...climate_zones_v1_design.json` (4 fields, ties `Climate Zones` with `Inspections` at
4/4) — resolved by a filename-token tiebreak.

Implement in `parser.py` as a new `Workspace.resolve_form_name(json_path, parsed_fields)`:

1. **Alias first** (unchanged): if the (copy-marker-stripped) stem is in `form_aliases.json`,
   use it. Manual mapping stays the ultimate escape hatch.
2. **Field-overlap match**: compute `design_fields = {f["name"] for f in parsed_fields}`;
   score every baseline form by `|design_fields ∩ baseline_fields|`. Compute
   `coverage = best_score / len(design_fields)`.
   - Accept the best match when `coverage >= 0.8` **and** the best score is at least 1.5× the
     runner-up score.
   - **Tie/low-margin fallback**: normalize the filename stem (lowercase, strip the workspace
     prefix by removing the longest common prefix shared with sibling files, strip
     `_v\d+_design`, split on `[_\-\s()]+`) and pick the candidate form whose normalized
     display name shares the most tokens. This resolves the Climate Zones tie.
3. **Heuristic last**: only if there is no workspace baseline at all (pure individual-file
   workspace — nothing to match against), fall back to the existing `guess_form_name()` regex.
4. Print what was decided, once per file:
   `[socal-whp] so_cal-...v358_design.json -> '300 - Account Management' (matched 353/357 fields)`.
   If nothing clears the bar, print a clear actionable warning naming the `form_aliases.json`
   escape hatch, and ingest the form under the heuristic name rather than dropping it.

Note the ordering constraint: overlap matching needs the baseline field sets, so resolution for
override files must happen inside `discover()` **after** step 1 builds `merged`, not inside
`parse_form()`. Refactor: let `parse_form()` accept an optional pre-resolved name, or return
fields first and resolve the name in `discover()`.

Workflow exports are unaffected — they carry names internally (`ExternalReferences`), no
filename guessing involved.

### Part C: same-form version dedup

`data/socal-whp/` currently holds **both** `..._395-inspection_work_order_v78_design.json` and
`..._v79_design.json`; both resolve to `395 - Inspection Work Order`. Today the last-sorted file
silently wins. Make it deliberate:

- When two or more individual files resolve to the same form name, pick the one with the
  highest `_v(\d+)_` in its filename (fall back to filename sort if no version token), and
  warn: `! 395 - Inspection Work Order: two exports found; using v79 (..._v79_design.json), ignoring v78`.
- Do the same across locations (root + `forms/`): if the same form has a root export and a
  `forms/` export, highest version wins; tie → `forms/` wins (it was placed deliberately).

## Cleanup & docs (in scope for this plan)

- **Delete or update stale aliases**: the socal-whp `form_aliases.json` filename-stem entries
  reference stems that no longer exist on disk. After Part B they're harmless but misleading;
  remove the dead stems, keep `name_aliases`. Add a rebuild-time notice for alias entries whose
  stem matches no file (`unused alias` hygiene warning).
- **`data/README.txt` generator in `start.bat` (lines 84-102)**: rewrite to the new truth —
  "drop any export JSON (workspace, form, or workflow) anywhere under `data\<slug>\`; the
  rebuild sorts out what each file is."
- **`start.bat` error text (lines 109-121)**: remove the implication that placement matters.
- **CLAUDE.md**: update *Ingestion formats & precedence* (root non-workspace JSONs are now
  routed, not skipped), *guess_form_name* description (now a last resort behind content
  matching), the *surgical update* how-to (step 2 "map its filename stem in form_aliases.json"
  is no longer required), and the *Orphan report* remedy wording. Update README.md if it
  repeats placement instructions.
- **TODO.md**: move this item to Done when shipped.

## Acceptance criteria

1. `python scripts/regenerate.py` on the current repo state ingests all 33 root design files as
   overrides — every one shadows its correct baseline form (spot-check: socal-whp
   `325 - SoCal Installation` field count changes to the v103 design's), with zero
   "belongs in forms/ and workflows/" warnings and zero new duplicate/phantom form nodes in any
   explorer (form counts stay 97/46/36/125/10 apart from intentional design deltas).
2. The v78/v79 pair produces exactly one override (v79) and one warning.
3. The liwp Climate Zones file matches `Climate Zones`, not `Inspections`.
4. A file dropped in `forms/` still behaves exactly as before (regression guard); a
   workspace-export JSON at root still parses as baseline; multiple workspace exports still
   merge in filename order.
5. `docs/field-index.json` keys unchanged in format (contract), values reflect the new designs.
6. Global build (`--global`) runs clean; orphan counts don't regress unexpectedly (individual
   overrides may legitimately *reduce* orphans by supplying missing links — that's the
   documented remedy working).
7. Run `start.bat` end-to-end on a clean clone to confirm the zero-manual-placement flow.
