# Plan 02 — Plain-English briefs: write for the program staffer, not the developer

**Status: EXECUTED 2026-07-02.** All steps implemented; acceptance checks pass (Desktop
Review card matches the worked example, description leads, no "(s)"/callsign prose, no
AND-garbage, JS mirror synced, narration byte-deterministic across hash seeds — a latent
nondeterminism in `build_form`'s set-union iteration was found and fixed with `sorted()`).
Deviations from the spec, deliberate:
- Description joins the role sentence as its own sentence (". ") rather than an em dash —
  form names contain " - " and an em-dash join misreads.
- Step 0 investigation: the empty condition children are `Comparison` record-metadata
  guards (LastModifierId vs user GUIDs, unverified operator enum). They are **filtered,
  not rendered** — 14 GUID clauses would drown the readable condition; tracked as a
  TODO candidate for compact rendering.
- The unmapped `?` operator renders as "compares to" in plain conditions (op 12's real
  meaning is unverifiable from exports; also a TODO candidate).
- Legacy scheduled triggers carry text ("Weekly · day-of-week 1"), not cron —
  `humanize_schedule` handles both shapes.

**Original spec below.** Priority: high (explicitly requested).
**Goal:** the per-form briefs (`docs/<slug>/forms/*.html`) and the explorer's narrative blocks
read like a colleague explaining the form — an average program user should understand every
sentence without knowing what a workflow, callsign, or API name is. All narration stays
**deterministic, pure, LLM-free** (`scripts/narrate.py` discipline is unchanged).

The exact wording below was drafted deliberately — implement it as written rather than
re-inventing phrasing. Where a template has a slot, the slot's fill rule is specified.

## What's wrong today (verified against `docs/socal-whp/forms/310 - Enrollment Intake.html`)

1. **Dev-speak counts**: "It links to 1 other form(s) and pulls reference data through 1
   relationship(s)." / "7 workflow(s) act on it" / "168 field(s)".
2. **Truncated callsigns as names**: "can change what workflow **DESKTOP_REVI** does". A
   callsign is an Excel primary key, not prose.
3. **Raw API names everywhere**: "UpdatedPrimaryPhoneNumber recalculates LatestPhoneNumber" —
   labels exist for most fields and are never used in the table.
4. **The form's own human description is never shown.** The workspace export carries a
   per-form `Description` (e.g. 300 - Account Management: "View and manage all Accounts within
   the ESA Whole Home Program (PP/D) for Southern California"). It's parsed into
   `form["description"]` (`parser.py` discover, line ~955) and rendered nowhere in the brief.
   That sentence is exactly what an average user wants first.
5. **Workflows are listed, not explained.** The user's request: describe what each form does
   *based on the workflows and what they do*, in their own breakouts. The data to do it is
   already parsed: trigger `databaseAction`/`condition`/`cron`, Notification actions carry
   `matchOn = "To: operations@maromaes.com · Subject: SoCal Whole Home | Enrollment Review for {ESAKey}"`,
   WFEngine actions carry `type`/`targetForm`/field assignments. None of it is narrated.
6. **Garbage condition strings** (prerequisite parser bug): `_expr_to_text()`
   (`scripts/parser.py:229-245`) joins child-expression texts with " AND "/" OR " without
   filtering empties, so unhandled sub-expression types yield
   `" AND  AND  AND … AND EnrollmentSubmissionStatus == 'Pending Review'"` — visible verbatim
   in briefs, the explorer, and Excel.

## Step 0 (prerequisite): fix `_expr_to_text`

- Filter empty parts before joining: `parts = [t for t in (…child texts…) if t.strip()]`.
- Investigate what the empty children actually are (dump `type` values of the Expressions on a
  few socal-whp Legacy triggers) and handle the common ones rather than dropping them —
  likely candidates: null/empty-check expressions, unresolved `FormFieldId`s. Anything still
  unhandled renders as nothing (filtered), never as a bare `AND`.
- This fix benefits Excel and both explorers, not just briefs.

## Step 1: plain-condition renderer (new, in `narrate.py`)

`condition_to_plain(condition_text, fields_for_form)` — takes the already-summarized condition
string (`Field == 'Value' AND …`) and rewrites it for humans:

- Operator map: `==` → "is", `!=` → "is not", `<` → "is below", `<=` → "is at most",
  `>` → "is above", `>=` → "is at least".
- Field tokens: replace an API name with its label when a matching field exists on the trigger
  form (`LatestPhoneNumber` → "Latest Phone Number"); otherwise **de-camel-case** the API name
  (insert spaces at case boundaries) so it still reads as words.
- ` AND ` → " and ", ` OR ` → " or ". Keep quoted values as-is.
- Example: `EnrollmentSubmissionStatus == 'Pending Review'` →
  "Enrollment Submission Status is 'Pending Review'".

Also add two tiny helpers used throughout:

- `count_phrase(n, singular, plural=None)` — spells out one–nine ("seven workflows"), digits
  from 10 ("18 required fields"), no "(s)" ever.
- `field_display(field)` — label if present and different from name, else de-camel-cased name.

## Step 2: rewrite the summary fragments (`narrate.form_summary`)

New wording, same fragment-dict structure (keys unchanged — `explorer_template.html`'s
`renderForm()` consumes `role_line` / `connects` / `workflows` / `fields` / `interactions`, so
keeping keys avoids a template contract break; only the strings improve).

**`role_line`** — replace `ROLE_PLAIN` with:

| role | text |
|---|---|
| Hub | "the central record — most other forms in {workspace} connect back to it" |
| Spoke | "a working form in the {workspace} process" |
| Lookup | "a reference list that other forms read from, like a rate sheet or ZIP-code table — it is rarely edited directly" |
| Subform | "a repeating table inside {parent}; each row is one entry" |

Prepend the platform description when present:
`"{description} — {name} is {role_text}."` (description sentence first; it's the purpose).

**`connects`** — "It connects to one other form and looks up reference data from one related
form." (counts via `count_phrase`; drop the words "relationship" and "pulls").

**`workflows`** — "Seven automated steps watch this form — most run when a saved record
changes." Fill rule: bucket the acting workflows by trigger (`on create` / `on update` /
`on a schedule`), name the dominant bucket; do **not** enumerate names here (the breakout
section below does that). Disabled workflows are excluded from the count but noted:
"(two more are currently switched off)".

**`fields`** — "There are 168 fields to work with; 18 must be filled in, and 15 only appear in
certain situations."

**`interactions`** — "As you fill it out, 35 fields automatically update, reveal, or check
other parts of the form."

## Step 3: workflow breakout cards (brief section "What happens automatically")

Replace the current flat `<ul>` in `_render_brief` (`scripts/regenerate.py:213-223`) with one
card per acting workflow. Add `narrate.workflow_story(w, fields_by_form)` returning
`{"title", "when", "then": [sentences], "disabled": bool}` so the explorer's workflow panel can
reuse it later. Composition rules:

- **Title**: the workflow **display name**, never the callsign. Callsign may appear as a muted
  small suffix for cross-reference to the Excel sheet, e.g. `Desktop Review · DESKTOP_REVI`.
- **"When" sentence**: `"Runs when a {trigger form} record is {created|updated}"` /
  `"Runs on a schedule ({humanized cron})"` + `", and only if {plain condition}"` when a
  condition exists (via Step 1). Cron humanizer: deterministic mapping for the common shapes
  (`0 H * * *` → "daily at H:00", `*/N …` → "every N minutes", day-of-week names); anything
  unmatched falls back to `"on a schedule (cron: …)"`.
- **"Then" sentences**, one per action:
  - Notification (`matchOn` parses as `To: X · Subject: Y`): `"Sends an email to {X} — subject
    “{Y}”."` Template tokens in the subject stay as-is but get de-braced where they match a
    field: `{ESAKey}` → "the record's ESA Key". Unparseable `matchOn` → `"Sends a notification."`
  - Record actions: `"Creates a new {targetForm} record"` / `"Updates the matching {targetForm}
    record"`, plus `", filling in {count_phrase(n, 'field')} automatically"` when there are
    field assignments. Mention `duplicatePolicy` only when set: `"(skips if one already exists)"`.
  - Unknown handler: `"Performs a step of type {type}."`
- **Disabled**: card is dimmed with the line `"Currently switched off — it will not run."`
  (matches the explorer's `(off)` treatment).

Worked example (real data, Desktop Review on 310 - Enrollment Intake), the target rendering:

> **Desktop Review**
> Runs when a 310 - Enrollment Intake record is updated, and only if Enrollment Submission
> Status is 'Pending Review'.
> Sends an email to operations@maromaes.com — subject "SoCal Whole Home | Enrollment Review
> for {the record's ESA Key}".

## Step 4: "What changes what" table — labels first

In the forward table (`regenerate.py:186-201`) and the explorer's forward block
(`fieldDetailHTML` in `explorer_template.html`):

- Left column: **label** primary, API name as a muted second line (matches the Required-fields
  list, which already does label-first).
- New `FORWARD_PHRASE` catalog (update `narrate.py` **and** its JS mirror in
  `explorer_template.html` — CLAUDE.md notes they must stay in sync):

| kind | old | new |
|---|---|---|
| visibility | shows or hides {t} | shows or hides **{t}** |
| formula | recalculates {t} | automatically updates **{t}** |
| validation | changes whether {t} is required / valid | changes whether **{t}** must be filled in |
| filter | re-filters the choices in {t} | changes which choices appear in **{t}** |
| wfCondition | can change what workflow {cs} does | helps decide whether the automated step "{workflow name}" runs |
| writtenBy | (muted note) | filled in automatically by "{workflow name}" — normally not edited by hand |

  `{t}` renders via `field_display()`. Workflow references need the name, so
  `workflow_field_effects()` should return `(callsign, name)` pairs (or the brief/template maps
  callsign→name from `data["workflows"]`).

## Step 5: brief page structure

Reorder `_render_brief` body to the reader's priority:

1. Title, workspace, badges (unchanged).
2. **What this form is for** — description + role_line + connects.
3. **What happens automatically** — workflows summary line + breakout cards (Step 3).
4. **Filling it out** — fields line + Required list (already label-first) + interactions line.
5. **What changes what** — the forward table (Step 4).
6. Footer (unchanged).

## Sync & docs obligations

- `explorer_template.html` consumes `DATA.narrative` — verify `renderForm()` and
  `fieldDetailHTML()` render the new strings correctly and keep the JS phrase mirror in sync.
- Regenerate **all five workspaces + global** and republish docs (standing `regenerate.py`
  behavior covers this).
- Update CLAUDE.md's *Plain-English narration* section (new `workflow_story`, phrase catalog,
  brief structure) and TODO.md.

## Acceptance criteria

1. `docs/socal-whp/forms/310 - Enrollment Intake.html` contains: the platform description (for
   forms that have one), zero occurrences of `"(s)"`, zero bare callsigns in prose, the Desktop
   Review card matching the worked example above, and no `" AND  AND "` anywhere.
2. Every acting workflow on a form gets a breakout card; disabled ones are labeled switched off.
3. `narrate.py` remains pure/filesystem-free; adding a workspace still requires no narration
   config; same input → byte-identical output (no timestamps/randomness).
4. Explorer narrative blocks show the new phrasing; forward badges/kinds still line up with the
   read-side view.
5. A non-developer test read: pick three briefs (a Hub, a Subform, a Lookup) and confirm every
   sentence survives the "would a program staffer understand this without asking?" check.
