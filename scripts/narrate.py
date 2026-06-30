"""
narrate.py — deterministic, plain-English narration of a discovered workspace.

Pure and filesystem-free (same discipline as parser.py's module-level helpers):
every function takes already-parsed data and returns JSON-serializable dicts. No
LLM, no I/O. Two consumers:
  - build_explorer.py injects build_all(data) into the explorer as DATA.narrative;
  - regenerate.py renders the same output into standalone per-form brief pages.

The substrate is already parsed by parser.py — this module only narrates and
*forward-inverts* it. dependsOn is stored on the DEPENDENT field (field B records
"I depend on A for my visibility"); build_forward_index turns that around to answer
"what does changing field A activate?".
"""

# Ordering + forward (subject = the field being changed) phrasing for each kind of
# intra-form dependency. Mirrors parser.py's dependsOn categories and the read-side
# KIND_PHRASE in explorer_template.html, but voiced forward. Verb-first, lowercase,
# jargon-free so a first-time reader understands without knowing the platform.
KIND_ORDER = ("visibility", "formula", "validation", "filter")
FORWARD_PHRASE = {
    "visibility": "shows or hides {t}",
    "formula":    "recalculates {t}",
    "validation": "changes whether {t} is required / valid",
    "filter":     "re-filters the choices in {t}",
}
KIND_BADGE = {"visibility": "VISIBLE", "formula": "FX",
              "validation": "REQ", "filter": "FILTER"}

# role -> a plain-English description a non-user understands.
ROLE_PLAIN = {
    "Hub":     "central record that ties many forms together",
    "Spoke":   "record that belongs to a larger process",
    "Lookup":  "reference table other forms read from",
    "Subform": "repeating grid",
}


def build_forward_index(fields_for_form):
    """Invert dependsOn for one form.

    fields_for_form: list of field dicts (data["fields"][formName]).
    Returns { fieldName: [ {"target": <field>, "kind": <kind>}, ... ] } — for each
    field, the other fields its change activates. Deduped on (target, kind) and
    sorted by kind order then target. Fields that trigger nothing are absent.
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

    Returns { fieldName: {"condition": [callsign...], "writtenBy": [callsign...]} }.
    - condition: the field gates a workflow's trigger/branch (fieldUsage Condition) —
      changing it can change what that workflow does (forward-facing).
    - writtenBy: the field is set by a workflow action (fieldUsage Write) —
      reverse-facing, shown as a muted note.
    """
    eff = {}
    for w in workflows:
        cs = w.get("callsign", "")
        for u in w.get("fieldUsage", []) or []:
            if u.get("form") != form_name:
                continue
            field = u.get("field")
            if not field:
                continue
            slot = eff.setdefault(field, {"condition": [], "writtenBy": []})
            d = (u.get("direction") or "").lower()
            if d == "condition" and cs not in slot["condition"]:
                slot["condition"].append(cs)
            elif d == "write" and cs not in slot["writtenBy"]:
                slot["writtenBy"].append(cs)
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


def _trigger_phrase(w):
    """A short 'when …' clause from an already-summarized trigger."""
    trig = w.get("trigger") or {}
    action = (trig.get("databaseAction") or "").lower()
    cron = trig.get("cron")
    if action == "create":
        when = "on create"
    elif action == "update":
        when = "on update"
    elif cron:
        when = f"on schedule ({cron})"
    else:
        when = "when triggered"
    name = w.get("name") or w.get("callsign") or "(unnamed)"
    return f"{when}: “{name}”"


def form_summary(form, fields, relationships, ref_pulls, workflows, forward):
    """Build the plain-English summary fragments for one form.

    Returns a dict of short, independent sentence fragments so the UI can lay them
    out cleanly (NOT one frozen blob).
    """
    name = form["name"]
    role = form.get("role", "")
    plain = ROLE_PLAIN.get(role, "form")
    if role == "Subform" and form.get("subformOf"):
        plain = f"repeating grid inside {form['subformOf']}"
    role_line = f"{name} is a {plain}."

    out_targets = {r["target"] for r in relationships
                   if r.get("source") == name and r.get("via") != "(embedded grid)"}
    pull_sources = {r.get("via") for r in ref_pulls if r.get("destForm") == name}
    pull_sources.discard("")
    bits = []
    if out_targets:
        bits.append(f"links to {len(out_targets)} other form(s)")
    if pull_sources:
        bits.append(f"pulls reference data through {len(pull_sources)} relationship(s)")
    connects = ("It " + " and ".join(bits) + "."
                if bits else "It does not link out to other forms.")

    acting = _workflows_on(name, workflows)
    if acting:
        clauses = "; ".join(_trigger_phrase(w) for w in acting[:3])
        more = f" (+{len(acting) - 3} more)" if len(acting) > 3 else ""
        workflows_line = (f"{len(acting)} workflow(s) act on it — {clauses}{more}.")
    else:
        workflows_line = ""

    total = len(fields)
    required = sum(1 for f in fields if f.get("required") == "Yes")
    conditional = sum(1 for f in fields if f.get("visibility") == "Yes")
    fparts = [f"{total} field(s)"]
    if required:
        fparts.append(f"{required} required")
    if conditional:
        fparts.append(f"{conditional} conditionally shown")
    fields_line = "It has " + ", ".join(fparts) + "."

    triggering = sum(1 for v in forward.values() if v)
    interactions = (f"{triggering} field(s) change what happens elsewhere on the form "
                    f"when edited." if triggering else "")

    return {
        "role_line": role_line,
        "connects": connects,
        "workflows": workflows_line,
        "fields": fields_line,
        "interactions": interactions,
    }


def build_form(form, fields, relationships, ref_pulls, workflows):
    """Full narrative for one form: summary + forward trigger model."""
    forward_fields = build_forward_index(fields)
    wf_eff = workflow_field_effects(form["name"], workflows)
    forward = {}
    for fname in set(forward_fields) | set(wf_eff):
        entry = {
            "fields": forward_fields.get(fname, []),
            "wfCondition": wf_eff.get(fname, {}).get("condition", []),
            "writtenBy": wf_eff.get(fname, {}).get("writtenBy", []),
        }
        # Keep only fields that actually trigger or are written by something.
        if entry["fields"] or entry["wfCondition"] or entry["writtenBy"]:
            forward[fname] = entry
    summary = form_summary(form, fields, relationships, ref_pulls, workflows,
                           forward_fields)
    return {"summary": summary, "forward": forward}


def build_all(data):
    """Narrate every form in a discovered workspace dict.

    Returns { "<FormName>": {"summary": {...}, "forward": {...}} }.
    """
    fields_by_form = data.get("fields", {})
    relationships = data.get("relationships", [])
    ref_pulls = data.get("refPulls", [])
    workflows = data.get("workflows", [])
    out = {}
    for form in data.get("forms", []):
        name = form["name"]
        out[name] = build_form(form, fields_by_form.get(name, []),
                               relationships, ref_pulls, workflows)
    return out
