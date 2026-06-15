"""
build_registry.py — three reuse/sameness views for the global build.

Called from build_global.build(). Adds three sheets to
output/global/cross-workspace-inventory.xlsx and supplies the
reference-replication classification the global explorer uses to suppress
collision links between pure lookup-table forms.

Governing rule — sameness is metadata, not topology. Every view classifies
into flat rows. No view here creates instance->instance or form->shared-field
edges. The only graph effect is the suppression filter consumed by
build_global._build_html (step 4), which *removes* links, never adds them.

Field substrate: the per-field arrays come from agg["discovered"][slug]["fields"]
(the same source regenerate.emit_field_index() reshapes into
docs/field-index.json). We read it in-memory rather than the published JSON
because build_global runs *before* publish_docs() rewrites that file, so the
on-disk copy is one run stale; the in-memory source is current and identical
in content.
"""
import re
import hashlib

from build_inventory import sheet


# {AnyEmailToken} -> recipient role. \w*[Ee]mail\w* matches Email,
# InstallationContractorEmail, CustomerEmailAddress, etc.
_EMAIL_TOK = re.compile(r"\{(\w*[Ee]mail\w*)\}")


# ---------------------------------------------------------------------------
# field substrate
# ---------------------------------------------------------------------------

def _field_substrate(discovered):
    """{ "<slug>/<FormName>": [{"name","type"}, ...] } — same content as
    docs/field-index.json, sourced from the live discover_all() result."""
    sub = {}
    forms_meta = []   # [{slug, name, role, key}]
    for slug, data in discovered.items():
        fbf = data["fields"]
        for form in data["forms"]:
            key = f"{slug}/{form['name']}"
            sub[key] = [{"name": f["name"], "type": f.get("type", "")}
                        for f in fbf.get(form["name"], [])]
            forms_meta.append({"slug": slug, "name": form["name"],
                               "role": form["role"], "key": key})
    return sub, forms_meta


# ---------------------------------------------------------------------------
# view 1 — workflow reuse registry
# ---------------------------------------------------------------------------

def _recipient_roles(wf):
    """Sorted distinct {...Email} tokens across all actions' matchOn.
    Empty -> ("(static/other)",)."""
    toks = set()
    for a in wf["actions"]:
        toks.update(_EMAIL_TOK.findall(a.get("matchOn") or ""))
    return tuple(sorted(toks)) if toks else ("(static/other)",)


def _pattern_key(wf):
    tr = wf["trigger"] or {}
    form = (tr.get("form") or "") or "(none)"
    action = (tr.get("databaseAction") or "") or "(none)"
    return (form, action, _recipient_roles(wf))


def _exact_hash(wf):
    """sha1 over {databaseAction, timing, condition, sorted action tuples,
    sorted Write field usages}. Identifies literal twins within a pattern."""
    tr = wf["trigger"] or {}
    acts = sorted(
        f"{a.get('type','')}|{a.get('targetForm','')}|{a.get('name','')}|{a.get('matchOn','')}"
        for a in wf["actions"])
    writes = sorted(f"{u['form']}.{u['field']}"
                    for u in wf["fieldUsage"] if u["direction"] == "Write")
    blob = "\n".join([
        tr.get("databaseAction", "") or "",
        tr.get("timing", "") or "",
        tr.get("condition", "") or "",
        "##".join(acts),
        "##".join(writes),
    ])
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _workflow_reuse(discovered):
    patterns = {}   # key -> {hashes, workspaces, count}
    hash_count = {}   # exact-hash -> total workflows carrying it (any pattern)
    for slug, data in discovered.items():
        for wf in data["workflows"]:
            key = _pattern_key(wf)
            h = _exact_hash(wf)
            p = patterns.setdefault(key, {"hashes": set(), "workspaces": set(),
                                          "count": 0})
            p["hashes"].add(h)
            p["workspaces"].add(slug)
            p["count"] += 1
            hash_count[h] = hash_count.get(h, 0) + 1

    # A literal exact-twin is one exact-hash shared by >=2 workflows. Because the
    # hash deliberately excludes the trigger form, twins are found even when each
    # utility names its trigger form differently (Customer Interest Receipt fires
    # on "Account Management (400)" in sdge-whp but "300 - Account Management" in
    # socal-whp) — so the twin spans two pattern keys and per-pattern
    # ExactTwinGroups cannot see it. Each shared hash gets a stable group id.
    twin_ids = {h: f"T{i+1}" for i, h in
                enumerate(sorted(h for h, c in hash_count.items() if c >= 2))}

    rows = []
    for (form, action, roles), p in patterns.items():
        twin_groups = len(p["hashes"])
        count = p["count"]
        if count < 2:
            drift = "Single"                      # nothing to be twin/drift with
        elif twin_groups > 1:
            drift = "Drift"                        # same pattern, divergent implementations
        else:
            drift = "Twin"                         # same pattern, identical implementations
        literal = ", ".join(sorted({twin_ids[h] for h in p["hashes"] if h in twin_ids}))
        rows.append({
            "PatternKey": f"{form} · {action} · [{'+'.join(roles)}]",
            "TriggerForm": form,
            "Action": action,
            "RecipientRoles": ", ".join(roles),
            "InstanceCount": count,
            "Workspaces": ", ".join(sorted(p["workspaces"])),
            "ExactTwinGroups": twin_groups,
            "DriftFlag": drift,
            "LiteralTwin": literal,               # cross-pattern exact-hash twin id, else ""
        })
    rows.sort(key=lambda r: (-r["InstanceCount"], r["PatternKey"]))
    return rows


# ---------------------------------------------------------------------------
# view 2 — form design-family registry
# ---------------------------------------------------------------------------

def _form_fingerprint(fields):
    """sha1 over the deduped, case-folded-name + type set.

    Case-fold collapses case-variant duplicates (Zipcode/ZipCode/ZIPCode);
    type is kept, so a field re-typed in one workspace (e.g. socal-whp's ZIP
    as Integer vs Text elsewhere) splits the fingerprint — that is real design
    drift and should not be hidden."""
    sig = sorted({(f["name"].casefold(), f["type"]) for f in fields})
    blob = "##".join(f"{n}|{t}" for n, t in sig)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest(), sig


def _form_families(substrate, forms_meta):
    fam = {}   # fingerprint -> {members, sig}
    fingerprints = {}   # (slug, name) -> fingerprint, for step-4 design-identity test
    for fm in forms_meta:
        fp, sig = _form_fingerprint(substrate[fm["key"]])
        fingerprints[(fm["slug"], fm["name"])] = fp
        f = fam.setdefault(fp, {"members": [], "sig": sig})
        f["members"].append(fm)

    rows = []
    for fp, f in fam.items():
        members = f["members"]
        if len(members) < 2:
            continue   # a family of one is not reuse — sheet shows shared designs only
        roles = sorted({m["role"] for m in members})
        names = [n for n, _ in f["sig"]]
        sample = ", ".join(names[:5]) + (" …" if len(names) > 5 else "")
        intent = ("reference-replication (intentional)"
                  if all(m["role"] == "Lookup" for m in members)
                  else "divergence-candidate")
        rows.append({
            "FamilyId": fp[:8],
            "FieldSignature": f"{len(f['sig'])} fields: {sample}",
            "MemberCount": len(members),
            "Members": ", ".join(f"{m['slug']}/{m['name']}"
                                 for m in sorted(members, key=lambda x: (x["slug"], x["name"]))),
            "Roles": ", ".join(roles),
            "IntentTag": intent,
        })
    rows.sort(key=lambda r: (-r["MemberCount"], r["FamilyId"]))
    return rows, fingerprints


# ---------------------------------------------------------------------------
# view 3 — field template index
# ---------------------------------------------------------------------------

_FORMS_CAP = 15


def _field_templates(substrate):
    tmpl = {}   # (name, type) -> set("slug/FormName")
    for key, fields in substrate.items():
        for f in fields:
            tmpl.setdefault((f["name"], f["type"]), set()).add(key)

    rows = []
    for (name, typ), forms in tmpl.items():
        if len(forms) < 2:
            continue   # present in one form only = not spread
        shown = sorted(forms)
        over = len(shown) - _FORMS_CAP
        forms_txt = ", ".join(shown[:_FORMS_CAP]) + (f"  (+{over} more)" if over > 0 else "")
        rows.append({
            "FieldName": name,
            "Type": typ,
            "FormCount": len(forms),
            "Forms": forms_txt,
        })
    rows.sort(key=lambda r: (-r["FormCount"], r["FieldName"], r["Type"]))
    return rows


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def compute_registries(agg):
    discovered = agg["discovered"]
    substrate, forms_meta = _field_substrate(discovered)

    workflow_reuse = _workflow_reuse(discovered)
    form_families, fingerprints = _form_families(substrate, forms_meta)
    field_templates = _field_templates(substrate)

    return {
        "workflowReuse": workflow_reuse,
        "formFamilies": form_families,
        "fieldTemplates": field_templates,
        "formFingerprints": fingerprints,   # (slug, name) -> design fingerprint, step-4 suppression
    }


def add_sheets(wb, reg):
    """Append the three registry sheets to an existing workbook (before save)."""
    sheet(wb.create_sheet("WorkflowReuse"),
          "WorkflowReuse · workflows keyed by pattern (trigger form + action + recipient roles)",
          [("PatternKey", 54, "TriggerForm · Action · [recipient roles]"),
           ("TriggerForm", 28, "Form that fires it"),
           ("Action", 12, "Create/Update/Delete/Scheduled"),
           ("RecipientRoles", 30, "{...Email} tokens, or (static/other)"),
           ("InstanceCount", 14, "Workflows sharing this pattern"),
           ("Workspaces", 30, "Workspaces the pattern spans"),
           ("ExactTwinGroups", 16, "Distinct exact-hashes under the pattern"),
           ("DriftFlag", 10, "Single (1 instance) | Twin (>=2, 1 hash) | Drift (>=2, >1 hash)"),
           ("LiteralTwin", 12, "Cross-pattern exact-hash twin id (form-independent); blank if unique")],
          reg["workflowReuse"], pk="PatternKey")

    sheet(wb.create_sheet("FormFamilies"),
          "FormFamilies · forms sharing a field-design fingerprint (case-folded name + type)",
          [("FamilyId", 12, "Fingerprint prefix"),
           ("FieldSignature", 50, "Field count + sample names"),
           ("MemberCount", 14, "Forms in the family"),
           ("Members", 60, "slug/FormName"),
           ("Roles", 24, "Roles across members"),
           ("IntentTag", 34, "reference-replication (intentional) | divergence-candidate")],
          reg["formFamilies"], pk="FamilyId")

    sheet(wb.create_sheet("FieldTemplates"),
          "FieldTemplates · (name, type) spread across forms — records spread, does not unify",
          [("FieldName", 30, "Field API name"),
           ("Type", 16, "Data type"),
           ("FormCount", 12, "Distinct forms carrying it"),
           ("Forms", 80, f"slug/FormName (capped at {_FORMS_CAP}, with overflow count)")],
          reg["fieldTemplates"])
