"""
narrate.py — deterministic, plain-English narration of a discovered workspace.

Pure and filesystem-free (same discipline as parser.py's module-level helpers):
every function takes already-parsed data and returns JSON-serializable dicts. No
LLM, no I/O. Two consumers:
  - build_explorer.py injects build_all(data) into the explorer as DATA.narrative
    and build_workflow_stories(data) as DATA.wfStories;
  - regenerate.py renders the same output into standalone per-form brief pages.

Voice: written for the program staffer, not the developer. Field labels over API
names, workflow display names over callsigns, no "(s)" pluralization, and every
workflow narrated as "when X happens, it does Y" (workflow_story).

The substrate is already parsed by parser.py — this module only narrates and
*forward-inverts* it. dependsOn is stored on the DEPENDENT field (field B records
"I depend on A for my visibility"); build_forward_index turns that around to answer
"what does changing field A activate?".
"""
import re

# Ordering + forward (subject = the field being changed) phrasing for each kind of
# intra-form dependency. Mirrors parser.py's dependsOn categories and the JS
# FORWARD_PHRASE in explorer_template.html (kept in sync — update both together).
# Verb-first, lowercase, jargon-free; {t} is the affected field's display name.
KIND_ORDER = ("visibility", "formula", "validation", "filter")
FORWARD_PHRASE = {
    "visibility": "shows or hides {t}",
    "formula":    "automatically updates {t}",
    "validation": "changes whether {t} must be filled in",
    "filter":     "changes which choices appear in {t}",
}
KIND_BADGE = {"visibility": "VISIBLE", "formula": "FX",
              "validation": "REQ", "filter": "FILTER"}

# role -> what the form *is*, in words a first-time reader understands.
# {ws} = workspace display name, {parent} = subform's parent form.
ROLE_PLAIN = {
    "Hub":     "the central record — most other forms in {ws} connect back to it",
    "Spoke":   "a working form in the {ws} process",
    "Lookup":  ("a reference list that other forms read from, like a rate sheet "
                "or ZIP-code table — it is rarely edited directly"),
    "Subform": "a repeating table inside {parent}; each row is one entry",
}
_SUBFORM_NO_PARENT = "a repeating table used inside another form; each row is one entry"

_SMALL_NUMBERS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four",
                  5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
_DAY_NAMES = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
              4: "Thursday", 5: "Friday", 6: "Saturday"}


# ── tiny language helpers ───────────────────────────────────────────

def num_word(n):
    """1-9 spelled out, digits from 10 up (0 -> 'no')."""
    return _SMALL_NUMBERS.get(n, str(n))

def count_phrase(n, singular, plural=None):
    """'one other form', 'seven automated steps', '18 fields' — never '(s)'."""
    plural = plural or singular + "s"
    return f"{num_word(n)} {singular if n == 1 else plural}"

def decamel(name):
    """API name -> readable words: 'ComputedHISR' -> 'Computed HISR',
    'UpdatedPrimaryPhoneNumber' -> 'Updated Primary Phone Number'."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s.replace("_", " ").strip()

def field_display(field):
    """A field dict's human name: label when present, else de-camel-cased API name."""
    label = (field.get("label") or "").strip()
    name = field.get("name") or ""
    return label if (label and label != name) else decamel(name)

def _display_map(fields):
    """{APIName: display} for one form's field list."""
    return {f["name"]: field_display(f) for f in fields or [] if f.get("name")}


# ── condition + schedule rendering ──────────────────────────────────

_CMP_RE = re.compile(r"(\w+)\s*(==|!=|<=|>=|<|>|\?)\s*'([^']*)'")
_OP_WORD = {"==": "is", "!=": "is not", "<": "is below",
            "<=": "is at most", ">": "is above", ">=": "is at least",
            "?": "compares to"}   # "?" = an operator the parser doesn't map

def condition_to_plain(condition_text, fields):
    """'EnrollmentSubmissionStatus == 'Pending Review' AND ...' ->
    "Enrollment Submission Status is 'Pending Review' and ..." """
    if not condition_text:
        return ""
    disp = _display_map(fields)

    def _one(m):
        fld, op, val = m.group(1), m.group(2), m.group(3)
        name = disp.get(fld, decamel(fld))
        if val == "":
            return f"{name} is blank" if op == "==" else (
                f"{name} is filled in" if op == "!=" else f"{name} {_OP_WORD[op]} ''")
        return f"{name} {_OP_WORD[op]} '{val}'"

    text = _CMP_RE.sub(_one, condition_text)
    text = text.replace(" AND ", " and ").replace(" OR ", " or ")
    return text.strip()

def humanize_schedule(schedule):
    """Deterministic humanizer for both shapes a trigger schedule takes:
    Legacy text ('Weekly · day-of-week 1 · limit 1') and real cron ('0 6 * * 1').
    Returns None when unrecognized (caller falls back to the raw string)."""
    s = str(schedule or "").strip()
    if not s:
        return None

    # Legacy workspace-export schedule text.
    m = re.match(r"^(Daily|Weekly|Monthly|Yearly)(.*)$", s, re.I)
    if m:
        out = m.group(1).lower()
        rest = m.group(2)
        d = re.search(r"day-of-week\s+(\d)", rest)
        if d and int(d.group(1)) in _DAY_NAMES:
            out += f" on {_DAY_NAMES[int(d.group(1))]}"
        lim = re.search(r"limit\s+(\d+)", rest)
        if lim:
            out += f" (limit {lim.group(1)})"
        return out

    # Real cron expressions (WFEngine CronExpression).
    parts = s.split()
    if len(parts) == 5:
        minute, hour, dom, _mon, dow = parts
        def _t(h, mi):
            return f"{int(h)}:{int(mi):02d}"
        if re.match(r"^\*/(\d+)$", minute) and hour == "*":
            return f"every {re.match(r'^\*/(\d+)$', minute).group(1)} minutes"
        if minute.isdigit() and re.match(r"^\*/(\d+)$", hour):
            return f"every {re.match(r'^\*/(\d+)$', hour).group(1)} hours"
        if minute.isdigit() and hour.isdigit():
            if dom == "*" and dow == "*":
                return f"daily at {_t(hour, minute)}"
            if dom == "*" and dow.isdigit() and int(dow) % 7 in _DAY_NAMES:
                return f"every {_DAY_NAMES[int(dow) % 7]} at {_t(hour, minute)}"
            if dom.isdigit() and dow == "*":
                return f"monthly on day {int(dom)} at {_t(hour, minute)}"
    return None


# ── forward inversion (what does changing field X activate) ─────────

def build_forward_index(fields_for_form):
    """Invert dependsOn for one form.

    fields_for_form: list of field dicts (data["fields"][formName]).
    Returns { fieldName: [ {"target": <field>, "kind": <kind>}, ... ] } — for each
    field, the other fields its change activates. Deduped on (target, kind) and
    sorted by kind order then target. Fields that trigger nothing are absent.
    Targets stay API names (they're keys into the field list); renderers map
    them to labels for display.
    """
    fwd = {}
    for g in fields_for_form:                       # g = the DEPENDENT field
        dep = g.get("dependsOn") or {}
        for kind in KIND_ORDER:
            for src in dep.get(kind, []) or []:     # src triggers g when changed
                if src == g.get("name"):
                    continue                        # ignore self-reference
                fwd.setdefault(src, set()).add((g["name"], kind))
    out = {}
    kind_rank = {k: i for i, k in enumerate(KIND_ORDER)}
    for src, pairs in fwd.items():
        rows = sorted(pairs, key=lambda p: (kind_rank.get(p[1], 99), p[0]))
        out[src] = [{"target": t, "kind": k} for t, k in rows]
    return out


def workflow_field_effects(form_name, workflows):
    """For one form, the workflow consequences of each field.

    Returns { fieldName: {"condition": [...], "writtenBy": [...]} } where each
    entry is {"callsign", "name"} — callsign for cross-reference, name for prose
    (never show a bare callsign to a reader).
    - condition: the field gates a workflow's trigger/branch (fieldUsage Condition) —
      changing it can change whether/what that workflow does (forward-facing).
    - writtenBy: the field is set by a workflow action (fieldUsage Write) —
      reverse-facing, shown as a muted note.
    """
    eff = {}
    for w in workflows:
        ref = {"callsign": w.get("callsign", ""),
               "name": w.get("name") or w.get("callsign", "")}
        for u in w.get("fieldUsage", []) or []:
            if u.get("form") != form_name:
                continue
            field = u.get("field")
            if not field:
                continue
            slot = eff.setdefault(field, {"condition": [], "writtenBy": []})
            d = (u.get("direction") or "").lower()
            if d == "condition" and ref not in slot["condition"]:
                slot["condition"].append(ref)
            elif d == "write" and ref not in slot["writtenBy"]:
                slot["writtenBy"].append(ref)
    return eff


def _workflows_on(form_name, workflows):
    """Workflows that trigger on, target, or touch a field of this form."""
    out = []
    for w in workflows:
        trig = w.get("trigger") or {}
        if (trig.get("form") == form_name
                or any(a.get("targetForm") == form_name for a in w.get("actions", []))
                or any(u.get("form") == form_name for u in w.get("fieldUsage", []))):
            out.append(w)
    return out


# ── the workflow story ("when X happens, it does Y") ────────────────

_NOTIF_RE = re.compile(r"^To:\s*(.+?)\s*·\s*Subject:\s*(.+)$", re.S)
_TOKEN_RE = re.compile(r"\{(\w+)\}")

def _debrace(template_text, fields):
    """'... for {ESAKey}' -> '... for {the record's ESA Key}' — template tokens
    that match a trigger-form field read as what they are: per-record values."""
    disp = _display_map(fields)
    def _one(m):
        token = m.group(1)
        if token in disp:
            return "{the record's " + disp[token] + "}"
        return m.group(0)
    return _TOKEN_RE.sub(_one, template_text)

def _action_sentence(action, workflow, trigger_fields):
    """One plain sentence per workflow action."""
    atype = (action.get("type") or "").lower()
    if "notification" in atype:
        m = _NOTIF_RE.match(action.get("matchOn") or "")
        if m:
            to, subject = m.group(1).strip(), _debrace(m.group(2).strip(), trigger_fields)
            return f"Sends an email to {to} — subject “{subject}”."
        return "Sends a notification."

    tgt = action.get("targetForm") or ""
    if "create" in atype:
        s = f"Creates a new {tgt} record" if tgt else "Creates a new record"
    elif "update" in atype or "upsert" in atype:
        s = f"Updates the matching {tgt} record" if tgt else "Updates a record"
    else:
        pretty = (action.get("type") or "(unknown)").replace("BuiltIn.", "")
        return f"Performs a step of type {pretty}" + (f" on {tgt}." if tgt else ".")

    n_writes = sum(1 for u in workflow.get("fieldUsage") or []
                   if u.get("direction") == "Write"
                   and u.get("stepName", "") == action.get("stepName", "")
                   and (not tgt or u.get("form") == tgt))
    if n_writes:
        s += f", filling in {count_phrase(n_writes, 'field')} automatically"
    policy = action.get("duplicatePolicy") or ""
    if policy:
        s += (" (skips if one already exists)" if "skip" in policy.lower()
              else f" (duplicates: {policy})")
    return s + "."

def workflow_story(w, fields_by_form):
    """One workflow -> {"title", "callsign", "when", "then": [...], "disabled"}.

    "when" is a single sentence (trigger + plain-English condition); "then" is
    one sentence per action. Both surfaces (brief cards, explorer panel) render
    from this so they tell the same story.
    """
    trig = w.get("trigger") or {}
    tf = trig.get("form", "")
    trigger_fields = fields_by_form.get(tf, [])
    action = (trig.get("databaseAction") or "").lower()
    cron = trig.get("cron")

    if action == "create":
        when = f"Runs when a new {tf} record is created" if tf else "Runs when a record is created"
    elif action == "update":
        when = f"Runs when a {tf} record is updated" if tf else "Runs when a record is updated"
    elif cron:
        h = humanize_schedule(cron)
        when = f"Runs on a schedule ({h or cron})"
        if tf:
            when += f", checking {tf} records"
    else:
        when = f"Runs when triggered on {tf}" if tf else "Runs when triggered"

    plain = condition_to_plain(trig.get("condition", ""), trigger_fields)
    if plain:
        when += f", and only if {plain}"
    when += "."

    then = [_action_sentence(a, w, trigger_fields) for a in (w.get("actions") or [])]
    if not then:
        then = ["No actions are configured."]

    return {"title": w.get("name") or w.get("callsign", ""),
            "callsign": w.get("callsign", ""),
            "when": when,
            "then": then,
            "disabled": not w.get("enabled", True)}

def build_workflow_stories(data):
    """{callsign: workflow_story} for every workflow in a discovered workspace."""
    fields_by_form = data.get("fields", {})
    return {w.get("callsign", ""): workflow_story(w, fields_by_form)
            for w in data.get("workflows", [])}


# ── per-form summary fragments ──────────────────────────────────────

def form_summary(form, fields, relationships, ref_pulls, workflows, forward,
                 ws_name=""):
    """Build the plain-English summary fragments for one form.

    Returns a dict of short, independent sentence fragments so the UI can lay them
    out cleanly (NOT one frozen blob). Keys are a template contract
    (explorer_template.html renderForm): role_line, connects, workflows, fields,
    interactions.
    """
    name = form["name"]
    role = form.get("role", "")
    ws = ws_name or "this workspace"
    role_text = ROLE_PLAIN.get(role, "a form in {ws}").format(
        ws=ws, parent=form.get("subformOf", ""))
    if role == "Subform" and not form.get("subformOf"):
        role_text = _SUBFORM_NO_PARENT
    role_line = f"{name} is {role_text}."
    # The platform's own description is the purpose statement — lead with it.
    desc = (form.get("description") or "").strip()
    if desc:
        if not desc.endswith((".", "!", "?")):
            desc += "."
        role_line = f"{desc} {role_line}"

    out_targets = {r["target"] for r in relationships
                   if r.get("source") == name and r.get("via") != "(embedded grid)"}
    pull_sources = {r.get("via") for r in ref_pulls if r.get("destForm") == name}
    pull_sources.discard("")
    bits = []
    if out_targets:
        bits.append(f"connects to {count_phrase(len(out_targets), 'other form')}")
    if pull_sources:
        bits.append(f"looks up reference data from {count_phrase(len(pull_sources), 'related form')}")
    connects = ("It " + " and ".join(bits) + "."
                if bits else "It does not link out to any other form.")

    acting = _workflows_on(name, workflows)
    active = [w for w in acting if w.get("enabled", True)]
    disabled_n = len(acting) - len(active)
    if active:
        buckets = {"update": 0, "create": 0, "schedule": 0, "other": 0}
        for w in active:
            trig = w.get("trigger") or {}
            a = (trig.get("databaseAction") or "").lower()
            if a in buckets:
                buckets[a] += 1
            elif trig.get("cron"):
                buckets["schedule"] += 1
            else:
                buckets["other"] += 1
        top = max(buckets, key=buckets.get)
        when_map = {"update": "when a saved record changes",
                    "create": "when a new record is created",
                    "schedule": "on a schedule",
                    "other": "when triggered"}
        n = len(active)
        subject = count_phrase(n, "automated step").capitalize()
        if n == 1:
            wf_line = f"{subject} watches this form — it runs {when_map[top]}"
        elif buckets[top] == n:
            wf_line = f"{subject} watch this form — they run {when_map[top]}"
        else:
            wf_line = f"{subject} watch this form — most run {when_map[top]}"
        if disabled_n:
            more = "more is" if disabled_n == 1 else "more are"
            wf_line += f" ({num_word(disabled_n)} {more} currently switched off)"
        workflows_line = wf_line + "."
    elif disabled_n:
        workflows_line = (f"No automated steps are currently active on this form "
                          f"({num_word(disabled_n)} "
                          f"{'is' if disabled_n == 1 else 'are'} switched off).")
    else:
        workflows_line = ""

    total = len(fields)
    required = sum(1 for f in fields if f.get("required") == "Yes")
    conditional = sum(1 for f in fields if f.get("visibility") == "Yes")
    verb = "is" if total == 1 else "are"
    fields_line = f"There {verb} {count_phrase(total, 'field')} to work with"
    clauses = []
    if required:
        clauses.append(f"{num_word(required)} must be filled in")
    if conditional:
        clauses.append(f"{num_word(conditional)} only "
                       f"{'appears' if conditional == 1 else 'appear'} in certain situations")
    if clauses:
        fields_line += "; " + (clauses[0] if len(clauses) == 1
                               else f"{clauses[0]}, and {clauses[1]}")
    fields_line += "."

    triggering = sum(1 for v in forward.values() if v)
    if triggering:
        if triggering == 1:
            interactions = ("As you fill it out, one field automatically updates, "
                            "reveals, or checks other parts of the form.")
        else:
            interactions = (f"As you fill it out, {num_word(triggering)} fields "
                            f"automatically update, reveal, or check other parts "
                            f"of the form.")
    else:
        interactions = ""

    return {
        "role_line": role_line,
        "connects": connects,
        "workflows": workflows_line,
        "fields": fields_line,
        "interactions": interactions,
    }


def build_form(form, fields, relationships, ref_pulls, workflows, ws_name=""):
    """Full narrative for one form: summary + forward trigger model."""
    forward_fields = build_forward_index(fields)
    wf_eff = workflow_field_effects(form["name"], workflows)
    forward = {}
    # sorted(): set iteration order varies per process (hash randomization);
    # narrative output must be byte-identical for identical input.
    for fname in sorted(set(forward_fields) | set(wf_eff)):
        entry = {
            "fields": forward_fields.get(fname, []),
            "wfCondition": wf_eff.get(fname, {}).get("condition", []),
            "writtenBy": wf_eff.get(fname, {}).get("writtenBy", []),
        }
        # Keep only fields that actually trigger or are written by something.
        if entry["fields"] or entry["wfCondition"] or entry["writtenBy"]:
            forward[fname] = entry
    summary = form_summary(form, fields, relationships, ref_pulls, workflows,
                           forward_fields, ws_name)
    return {"summary": summary, "forward": forward}


def build_all(data):
    """Narrate every form in a discovered workspace dict.

    Returns { "<FormName>": {"summary": {...}, "forward": {...}} }.
    forward.wfCondition / forward.writtenBy entries are {"callsign", "name"}
    objects (renderers show the name; the callsign is for cross-reference).
    """
    fields_by_form = data.get("fields", {})
    relationships = data.get("relationships", [])
    ref_pulls = data.get("refPulls", [])
    workflows = data.get("workflows", [])
    ws_name = data.get("workspaceName", "")
    out = {}
    for form in data.get("forms", []):
        name = form["name"]
        out[name] = build_form(form, fields_by_form.get(name, []),
                               relationships, ref_pulls, workflows, ws_name)
    return out
