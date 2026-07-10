"""
regenerate.py — rebuild the Excel inventory and HTML explorer for every
workspace under data/, then rebuild the cross-workspace global aggregator.
Finally, mirror the HTML explorers into docs/ for GitHub Pages.

Usage:
    python scripts/regenerate.py                 rebuild all workspaces + global
    python scripts/regenerate.py --workspace X   rebuild only workspace X
    python scripts/regenerate.py --global        rebuild only the global aggregator
    python scripts/regenerate.py --check         discovery only: counts, orphans,
                                                 warnings; writes nothing
    python scripts/regenerate.py --snapshot [LABEL]
                                                 capture a version snapshot (no rebuild)
    python scripts/regenerate.py --list-snapshots
                                                 list saved snapshots (newest first)
    python scripts/regenerate.py --compare OLD NEW [--workspace SLUG]
                                                 diff two snapshots (refs: id, label,
                                                 latest, previous)

Every run refreshes docs/ from whatever explorers exist under output/, so a push
publishes the current views. Excel artifacts stay in output/ and are never copied
to docs/. Full rebuilds auto-save a snapshot after publish_docs().
"""
import sys, argparse, json, re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import Workspace, list_workspaces, discover_all, find_orphans, OUTPUT_DIR
import build_inventory
import build_explorer
import build_global
import narrate
import versioning

DOCS_DIR = OUTPUT_DIR.parent / "docs"
WS_EXPLORER = "workspace_explorer.html"      # per-workspace source filename in output/
GLOBAL_EXPLORER = "global-explorer.html"     # global source filename in output/
BRIEF_TEMPLATE = (Path(__file__).resolve().parent / "brief_template.html").read_text(encoding="utf-8")


_WINDOWS_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


def _brief_filename(form_name):
    """Form name -> filesystem-safe brief filename. Kept as the literal name
    (spaces, parens, etc. all pass through unescaped) so it matches what a
    browser resolves a plain href to — only characters illegal in a Windows
    filename are stripped. Do NOT percent-encode here: encoding the filename
    on disk while linking to it with encodeURIComponent double-encodes, since
    the browser decodes the href before doing the filesystem lookup."""
    return _WINDOWS_ILLEGAL_CHARS.sub("", form_name) + ".html"


def rebuild_workspace(slug):
    ws = Workspace(slug)
    print(f"[{slug}] {ws.name}")
    print("  Excel inventory")
    build_inventory.build(ws)
    print("  HTML explorer")
    build_explorer.build(ws)

    # Orphan check: forms/grids that render with no graph edge. A workspace export
    # can leave a subform's parent out, or a form unlinked; dropping that form's
    # individual JSON anywhere under data/<slug>/ usually supplies the missing links.
    d = ws.discover()                       # cached; no re-parse, no duplicate prints
    orphans = find_orphans(d)
    if orphans:
        print(f"  Orphans: {len(orphans)} form(s) with no graph edge "
              f"(import the individual form JSON to connect):")
        for o in orphans:
            print(f"    - {o['name']} [{o['role']}] -- {o['reason']}")
    else:
        print("  Orphans: none")
    return len(d["forms"]), len(d["workflows"])


def _print_summary(stats):
    """End-of-run block: what was built and every warning in one place.

    Warnings scroll past during a multi-workspace rebuild; start.bat users see
    this block right above the view-choice menu, so problems surface at the
    moment they're looking. parser.WARNINGS collects each distinct warning once
    per process.
    """
    from parser import WARNINGS
    print()
    print("=" * 64)
    if stats:
        total_f = sum(f for f, _ in stats.values())
        total_w = sum(w for _, w in stats.values())
        print(f"Rebuild summary: {len(stats)} workspace(s) - "
              f"{total_f} forms, {total_w} workflows")
    else:
        print("Rebuild summary:")
    if WARNINGS:
        print(f"{len(WARNINGS)} warning(s) to review:")
        for w in WARNINGS:
            print(w if w.startswith("  ") else "  " + w)
    else:
        print("No warnings.")
    print("=" * 64)


def _html_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _write_landing(views, stamp, featured_links=None):
    """views: list of (title, description, href). Minimal dark landing page that
    matches the explorer's palette and fonts. featured_links: optional
    {slug: [(formName, brief_href)]} rendered as quick-link chips on each
    workspace card so the main forms are one click from the landing page."""
    featured_links = featured_links or {}

    def card(title, desc, href):
        slug = href.split("/")[0]
        chips = featured_links.get(slug) or []
        chip_html = ""
        # Any workspace with briefs gets an "All form briefs" chip; featured
        # forms (if any) come first as their own quick links.
        if slug in featured_links:
            links = "".join(
                f'<a class="chip" href="{_html_escape(bhref)}">{_html_escape(fname)}</a>'
                for fname, bhref in chips)
            links += (f'<a class="chip all" href="{_html_escape(slug + "/forms/index.html")}">'
                      f'All form briefs &rarr;</a>')
            lbl = "Featured:" if chips else "Briefs:"
            chip_html = f'\n      <div class="chips"><span class="chips-lbl">{lbl}</span> {links}</div>'
        return f'''    <div class="view">
      <a class="view-main" href="{_html_escape(href)}">
        <div class="name">{_html_escape(title)} <span class="arrow">&rarr;</span></div>
        <div class="desc">{_html_escape(desc)}</div>
      </a>{chip_html}
    </div>'''

    cards = "\n".join(card(title, desc, href) for title, desc, href in views)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Workflow Inventory</title>
<style>
  :root{{--bg:#0f1115;--bg2:#1a1d24;--bg3:#252932;--border:#2e3340;
        --text:#e8ebf0;--muted:#8a92a3;--accent:#5eead4;}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  html,body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            background:var(--bg);color:var(--text);min-height:100%}}
  body{{max-width:760px;margin:0 auto;padding:56px 24px}}
  h1{{font-size:20px;font-weight:600;letter-spacing:0.3px}}
  .sub{{color:var(--muted);font-size:13px;margin-top:6px}}
  .views{{margin-top:32px;display:flex;flex-direction:column;gap:12px}}
  .view{{background:var(--bg2);border:1px solid var(--border);
         border-radius:8px;padding:16px 18px;
         transition:border-color 120ms,background 120ms}}
  .view:hover{{border-color:var(--accent);background:var(--bg3)}}
  a.view-main{{display:block;text-decoration:none;color:var(--text)}}
  .view .name{{font-size:15px;font-weight:600}}
  .view .name .arrow{{color:var(--accent)}}
  .view .desc{{color:var(--muted);font-size:12px;margin-top:4px}}
  .chips{{margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
  .chips-lbl{{color:var(--muted);font-size:11px}}
  a.chip{{font-size:11px;background:#4a3a12;color:#fcd34d;border-radius:4px;
         padding:2px 9px;text-decoration:none}}
  a.chip:hover{{background:#5c4715}}
  a.chip.all{{background:var(--bg3);color:var(--accent)}}
  a.chip.all:hover{{background:#2e3340}}
  .ts{{color:var(--muted);font-size:12px;margin-top:36px;font-family:monospace}}
</style>
</head>
<body>
  <h1>Workflow Inventory</h1>
  <div class="sub">Interactive form &amp; workflow explorers</div>
  <div class="views">
{cards}
  </div>
  <div class="ts">Last regenerated: {stamp}</div>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def emit_field_index():
    """Write docs/field-index.json — a machine-readable field index for external tools.

    CONTRACT: This file is a stable integration interface. Do not rename keys,
    remove fields from the per-field objects, or change the key format without
    versioning or migrating known consumers (e.g. the PDF field-mapper).

    Structure:
        {
          "<slug>/<FormDisplayName>": [
            {"name": "FieldApiName", "label": "Display Label", "type": "DataType"},
            ...
          ]
        }

    Keys are workspace-qualified ("<slug>/<FormDisplayName>") so forms that share
    a display name across workspaces are distinct entries. Fields appear in
    discovery order (design-tree order for individual exports; definition order
    for workspace exports). Lookup stubs (role="Lookup") carry an empty field
    array because they have no export of their own.
    """
    discovered = discover_all()
    index = {}
    for slug, data in sorted(discovered.items()):
        fields_by_form = data["fields"]
        for form in data["forms"]:
            key = f"{slug}/{form['name']}"
            index[key] = [
                {"name": f["name"], "label": f.get("label", ""), "type": f.get("type", "")}
                for f in fields_by_form.get(form["name"], [])
            ]
    out = DOCS_DIR / "field-index.json"
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(v) for v in index.values())
    print(f"  docs/field-index.json -> {len(index)} forms, {total} fields")


def _brief_field_cross_refs(form_name, fields, data):
    """Precompute, for one form, the same per-field cross-references the
    workspace explorer resolves at click-time (referencedBy via refPulls +
    relationships, and fieldUsage from workflows) -- baked in ahead of time
    since a brief is scoped to a single form and has no live graph to query."""
    rel_by_src_via = {}
    for r in data.get("relationships", []):
        rel_by_src_via[(r["source"], r["via"])] = r["target"]
    field_names = {f["name"] for f in fields}

    referenced_by = {}
    for rp in data.get("refPulls", []):
        if rp["sourceField"] not in field_names:
            continue
        if rel_by_src_via.get((rp["destForm"], rp["via"])) == form_name:
            referenced_by.setdefault(rp["sourceField"], []).append(
                {"form": rp["destForm"], "via": rp["via"], "localField": rp["destField"]})

    field_usage = {}
    for w in data.get("workflows", []):
        for u in w.get("fieldUsage", []):
            if u["form"] != form_name:
                continue
            field_usage.setdefault(u["field"], []).append(
                {"callsign": w["callsign"], "name": w["name"],
                 "direction": u["direction"], "context": u["context"]})

    return referenced_by, field_usage


def _render_brief(slug, ws_name, form, nar_form, data, featured, stories):
    """Render one printable per-form brief.

    Voice: plain English for a program staffer. Field labels lead (API names
    muted), workflow display names only (callsigns as muted cross-references),
    and every workflow gets a story card (when it runs / what it does) from
    narrate.workflow_story. The brief also carries a full field browser (search,
    mode filter, expand-to-detail) mirroring the workspace explorer's field
    panel, baked into a small inline DATA blob since the page has no server."""
    esc = _html_escape
    name = form["name"]
    role = form.get("role", "")
    s = nar_form["summary"]
    fwd = nar_form["forward"]
    fields = data["fields"].get(name, [])
    disp = {f["name"]: narrate.field_display(f) for f in fields if f.get("name")}
    label_of = lambda fn: disp.get(fn) or narrate.decamel(fn)

    # ── What changes what: labels first, API name as the muted second line.
    parts = sorted(((fn, e) for fn, e in fwd.items()
                    if e["fields"] or e["wfCondition"]),
                   key=lambda p: label_of(p[0]).lower())
    if parts:
        rows = []
        for fn, e in parts:
            effects = []
            for x in e["fields"]:
                phrase = narrate.FORWARD_PHRASE.get(x["kind"], "{t}").format(
                    t=f"<b>{esc(label_of(x['target']))}</b>")
                badge = narrate.KIND_BADGE.get(x["kind"], "DEP")
                effects.append(f'<div class="effect"><span class="chip {x["kind"]}">{badge}</span>{phrase}</div>')
            for ref in e["wfCondition"]:
                effects.append(f'<div class="effect"><span class="chip flow">FLOW</span>'
                               f'helps decide whether the automated step '
                               f'&ldquo;<b>{esc(ref["name"])}</b>&rdquo; runs</div>')
            rows.append(f'<tr><td class="field">{esc(label_of(fn))}'
                        f'<div class="api">{esc(fn)}</div></td>'
                        f'<td>{"".join(effects)}</td></tr>')
        changes = ('<table><thead><tr><th>When you change&hellip;</th>'
                   '<th>&hellip;this happens</th></tr></thead><tbody>'
                   + "".join(rows) + "</tbody></table>")
    else:
        changes = '<div class="empty">No fields on this form trigger changes elsewhere.</div>'

    # ── Written-by notes: fields the automation fills in (normally not edited).
    written = sorted(((fn, e["writtenBy"]) for fn, e in fwd.items() if e["writtenBy"]),
                     key=lambda p: label_of(p[0]).lower())
    if written:
        wr_rows = "".join(
            f'<li><b>{esc(label_of(fn))}</b> <span class="when">— filled in automatically by '
            + ", ".join(f'&ldquo;{esc(r["name"])}&rdquo;' for r in refs)
            + '; normally not edited by hand</span></li>'
            for fn, refs in written)
        changes += f'<h3>Filled in automatically</h3><ul>{wr_rows}</ul>'

    # ── Required fields (label first, API name muted).
    req = [f for f in fields if f.get("required") == "Yes"]
    if req:
        reqhtml = "<ul>" + "".join(
            f'<li>{esc(narrate.field_display(f))} '
            f'<span class="when">({esc(f["name"])})</span></li>' for f in req) + "</ul>"
    else:
        reqhtml = '<div class="empty">No required fields.</div>'

    # ── Workflow story cards.
    acting = narrate._workflows_on(name, data.get("workflows", []))
    if acting:
        cards = []
        for w in acting:
            st = stories.get(w.get("callsign", "")) or narrate.workflow_story(w, data["fields"])
            off = st["disabled"]
            then_html = "".join(f'<div class="then">{esc(t)}</div>' for t in st["then"])
            offnote = ('<div class="offnote">Currently switched off &mdash; it will not run.</div>'
                       if off else "")
            cards.append(
                f'<div class="wf-story{" off" if off else ""}">'
                f'<div class="wf-title">{esc(st["title"])}'
                f'<span class="cs">{esc(st["callsign"])}</span></div>'
                f'<div class="when-line">{esc(st["when"])}</div>'
                f'{then_html}{offnote}</div>')
        lead = f'<p class="lead">{esc(s["workflows"])}</p>' if s["workflows"] else ""
        wfhtml = lead + "".join(cards)
    else:
        wfhtml = '<div class="empty">Nothing runs automatically on this form.</div>'

    badges = f'<span class="badge {esc(role)}">{esc(role)}</span>'
    if featured:
        badges += '<span class="badge featured">Featured</span>'

    filling = f'<p class="lead">{esc(s["fields"])}' \
              + (" " + esc(s["interactions"]) if s["interactions"] else "") + "</p>"

    # ── Version history: one entry per design export on file, newest first.
    # Only rendered when there is actual history (>= 2 versions); the delta
    # sentences use the labels captured at parse time (narrate voice).
    version_html = ""
    history = form.get("versionHistory") or []
    if len(history) >= 2:
        attr_words = {"type": "type", "label": "label", "component": "component",
                      "required": "whether it is required", "hidden": "visibility",
                      "enabled": "whether it is editable", "relatedForm": "linked form",
                      "relatedField": "linked field", "via": "link field",
                      "validator": "validation", "formula": "formula",
                      "filter": "list filter", "visibility": "visibility rule",
                      "defaultValue": "default value", "dependsOn": "field dependencies"}
        entries = []
        for i, h in enumerate(reversed(history)):
            vlabel = f"v{h['version']}" if h["version"] is not None else "v?"
            delta = h.get("fieldDelta")
            if delta is None:
                sentence = "Earliest export on file."
            else:
                bits = []
                if delta["added"]:
                    bits.append("Added " + narrate.and_join(
                        [esc(d["label"]) for d in delta["added"]]))
                if delta["removed"]:
                    bits.append(("removed " if bits else "Removed ") + narrate.and_join(
                        [esc(d["label"]) for d in delta["removed"]]))
                if delta["changed"]:
                    ch = [f'{esc(d["label"])} ({esc(", ".join(attr_words.get(a, a) for a in d["attributes"]))})'
                          for d in delta["changed"]]
                    bits.append(("changed " if bits else "Changed ") + narrate.and_join(ch))
                sentence = "; ".join(bits) + "." if bits \
                    else "No field changes from the previous export."
            active = ' <span class="badge Hub">Active</span>' if i == 0 else ""
            entries.append(
                f'<li><b>{esc(vlabel)}</b>{active} '
                f'<span class="when">({esc(h["sourceFile"])})</span>'
                f'<div>{sentence}</div></li>')
        version_html = f'  <h2>Version history</h2><ul>{"".join(entries)}</ul>'

    # All-fields browser: search + mode filter + expand-to-detail, same
    # capability as the workspace explorer's field panel (see brief_template.html
    # for the shared render/toggle JS this DATA blob feeds).
    referenced_by, field_usage = _brief_field_cross_refs(name, fields, data)
    field_browser_data = {
        "fields": fields, "forward": fwd,
        "referencedBy": referenced_by, "fieldUsage": field_usage,
    }
    field_browser = (
        f'  <h2>All fields ({len(fields)})</h2>'
        f'  <div class="field-tools">'
        f'<input class="field-search" placeholder="filter fields..." oninput="__briefFilterInput(this.value)">'
        f'<select class="field-mode-filter" onchange="__briefModeFilter(this.value)">'
        f'<option value="">All configuration</option>'
        f'<option value="Advanced">Advanced (code) only</option>'
        f'<option value="Conditional">Conditional (rule builder) only</option>'
        f'</select></div>'
        f'  <div class="field-controls"><span class="exp-count" id="brief-exp-count">0 expanded</span>'
        f'<span class="spacer"></span>'
        f'<button class="mini-btn" onclick="__briefCollapseAll()">Collapse all</button>'
        f'<button class="mini-btn" onclick="__briefExpandAll()">Expand all</button></div>'
        f'  <div class="field-list" id="brief-field-list"></div>'
    )

    body = [
        # WS_EXPLORER (output/'s filename) here, not docs/'s "explorer.html" --
        # this same HTML is written to both output/<slug>/forms/ and
        # docs/<slug>/forms/, and only the docs/ copy gets that name rewritten
        # (see emit_form_briefs()), mirroring how publish_docs() already does
        # this for the global explorer's cross-view deep links.
        f'  <a class="back" href="../{WS_EXPLORER}#form={quote(name)}">&larr; Back to {esc(ws_name)} explorer</a>',
        f'  <div class="badges" style="margin-top:14px">{badges}</div>',
        f'  <h1>{esc(name)}</h1>',
        f'  <div class="ws">{esc(ws_name)}</div>',
        f'  <h2>What this form is for</h2>',
        f'  <p class="lead">{esc(s["role_line"])}'
        f'{(" " + esc(s["collects"])) if s.get("collects") else ""}'
        f' {esc(s["connects"])}</p>',
        f'  <h2>What happens automatically</h2>{wfhtml}',
        f'  <h2>Filling it out</h2>{filling}'
        f'  <h3>Required fields</h3>{reqhtml}',
        f'  <h2>What changes what</h2>{changes}',
        version_html,
        field_browser,
        f'  <div class="foot">Generated by regenerate.py &middot; not hand-edited</div>',
    ]
    field_data_json = json.dumps(field_browser_data, separators=(",", ":")).replace("</", "<\\/")
    return (BRIEF_TEMPLATE
            .replace("__TITLE__", esc(name) + " — " + esc(ws_name))
            .replace("__BODY__", "\n".join(body))
            .replace("__FIELD_DATA__", f"window.__BRIEF_FIELDS__ = {field_data_json};"))


def _render_brief_index(slug, ws_name, data, featured):
    """One browsable index page per workspace listing every form brief,
    grouped by role (featured first within each group). Written next to the
    briefs so relative links stay trivial."""
    esc = _html_escape
    role_order = ["Hub", "Spoke", "Lookup", "Subform"]
    role_title = {"Hub": "Central records", "Spoke": "Working forms",
                  "Lookup": "Reference lists", "Subform": "Repeating tables (grids)"}
    groups = {}
    for f in data["forms"]:
        groups.setdefault(f.get("role") or "Spoke", []).append(f)
    sections = []
    for role in role_order + sorted(set(groups) - set(role_order)):
        forms = groups.get(role)
        if not forms:
            continue
        forms = sorted(forms, key=lambda f: (f["name"] not in featured, f["name"].lower()))
        items = "".join(
            f'<li><a href="{esc(_brief_filename(f["name"]))}">{esc(f["name"])}</a>'
            + ('<span class="badge featured">Featured</span>' if f["name"] in featured else "")
            + (f' <span class="when">{esc(f.get("description") or "")}</span>'
               if f.get("description") else "")
            + "</li>"
            for f in forms)
        sections.append(f'<h2>{esc(role_title.get(role, role))} ({len(forms)})</h2><ul>{items}</ul>')
    body = [
        f'  <a class="back" href="../{WS_EXPLORER}">&larr; Back to {esc(ws_name)} explorer</a>',
        f'  <h1>{esc(ws_name)} &mdash; form briefs</h1>',
        f'  <div class="ws">One printable plain-English page per form</div>',
        "".join(sections),
        f'  <div class="foot">Generated by regenerate.py &middot; not hand-edited</div>',
    ]
    return (BRIEF_TEMPLATE
            .replace("__TITLE__", esc(ws_name) + " — form briefs")
            .replace("__BODY__", "\n".join(body)))


def emit_form_briefs():
    """Write a printable per-form brief for every form, into both
    output/<slug>/forms/ (so the local explorer's 'Open full brief' link resolves)
    and docs/<slug>/forms/ (for GitHub Pages), plus a per-workspace index.html
    listing every brief. Returns {slug: [(name, docs_href)]} of featured forms
    for the landing page.

    Uses the same in-memory discover_all() source as emit_field_index(); the
    narrative is presentation-only and never touches field-index.json.
    """
    discovered = discover_all()
    featured_links = {}
    total = 0
    for slug, data in sorted(discovered.items()):
        ws_name = data.get("workspaceName", slug)
        nar = narrate.build_all(data)
        stories = narrate.build_workflow_stories(data)
        featured = set(data.get("featured", []))
        out_dir = OUTPUT_DIR / slug / "forms"
        docs_dir = DOCS_DIR / slug / "forms"
        out_dir.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        for form in data["forms"]:
            name = form["name"]
            html = _render_brief(slug, ws_name, form, nar[name], data,
                                 name in featured, stories)
            fn = _brief_filename(name)
            (out_dir / fn).write_text(html, encoding="utf-8")
            # docs/'s explorer copy is renamed to explorer.html (see publish_docs());
            # the brief's back-link was rendered against output/'s WS_EXPLORER name,
            # so the docs/ copy needs the same rewrite to resolve on Pages.
            (docs_dir / fn).write_text(html.replace(WS_EXPLORER, "explorer.html"), encoding="utf-8")
            total += 1
        idx = _render_brief_index(slug, ws_name, data, featured)
        (out_dir / "index.html").write_text(idx, encoding="utf-8")
        (docs_dir / "index.html").write_text(idx.replace(WS_EXPLORER, "explorer.html"), encoding="utf-8")
        featured_links[slug] = [(n, f"{slug}/forms/{_brief_filename(n)}")
                                for n in data.get("featured", [])]
    print(f"  form briefs -> {total} page(s) + {len(discovered)} index page(s) (output/ + docs/)")
    return featured_links


def _auto_snapshot(discovered_all, label=None):
    """Save a snapshot after rebuild; skip when nothing changed vs latest."""
    existing = versioning.list_snapshots()
    snap = versioning.build_snapshot(discovered_all, label=label)
    if existing:
        try:
            latest = versioning.load_snapshot("latest")
            if versioning.snapshot_fingerprint(latest) == versioning.snapshot_fingerprint(snap):
                print("  Snapshot: unchanged from latest (not saved)")
                return None
        except FileNotFoundError:
            pass
    entry = versioning.save_snapshot(discovered_all, label=label)
    print(f"  Snapshot: {entry['id']}"
          + (f" ({entry['label']})" if entry.get("label") else ""))
    return entry


def _run_snapshot(label=None):
    discovered = discover_all()
    if not discovered:
        print("No workspaces found under data/.")
        sys.exit(1)
    entry = versioning.save_snapshot(discovered, label=label)
    print(f"Snapshot saved: {entry['id']}"
          + (f" ({entry['label']})" if entry.get("label") else ""))
    print(f"  {entry['totals']['forms']} forms, "
          f"{entry['totals']['workflows']} workflows across "
          f"{len(entry['workspaces'])} workspace(s)")
    return entry


def _run_compare(old_ref, new_ref, workspace=None, write_json=False):
    try:
        old_snap = versioning.load_snapshot(old_ref)
        new_snap = versioning.load_snapshot(new_ref)
    except (FileNotFoundError, ValueError) as e:
        print(str(e))
        sys.exit(1)
    if workspace and workspace not in old_snap["workspaces"] and workspace not in new_snap["workspaces"]:
        print(f"Workspace '{workspace}' not found in either snapshot.")
        sys.exit(1)
    result = versioning.compare_snapshots(old_snap, new_snap, workspace=workspace)
    print(versioning.format_compare_report(result))
    if write_json:
        path = versioning.write_compare_report(result)
        print(f"JSON report: {path}")
    return result


def _list_snapshots():
    entries = versioning.list_snapshots()
    if not entries:
        print("No snapshots yet. Run a full rebuild or --snapshot to create one.")
        return
    print(f"{len(entries)} snapshot(s), newest first:\n")
    for i, e in enumerate(entries):
        tag = "latest" if i == 0 else ("previous" if i == 1 else "")
        label = f"  label={e['label']}" if e.get("label") else ""
        hint = f"  ({tag})" if tag else ""
        print(f"  {e['id']}{label}{hint}")
        print(f"    {e['created']}  |  {e['totals']['forms']} forms, "
              f"{e['totals']['workflows']} workflows  |  "
              f"{', '.join(e['workspaces'])}")


def publish_docs():
    """Mirror the built HTML explorers into docs/ and write the landing page.

    Scans output/ for whatever explorers currently exist, so the result is
    consistent regardless of which build path ran. Excel files are not copied.
    """
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Serve files verbatim — no Jekyll build step on the Pages side.
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    views = []

    # Global explorer first — the strategic entry point. Its cross-view links
    # reference the per-workspace file by name (workspace_explorer.html); rewrite
    # that to the docs filename (explorer.html) so the deep links work on Pages.
    gsrc = OUTPUT_DIR / "global" / GLOBAL_EXPLORER
    if gsrc.exists():
        gdest = DOCS_DIR / "global"
        gdest.mkdir(parents=True, exist_ok=True)
        html = gsrc.read_text(encoding="utf-8").replace(WS_EXPLORER, "explorer.html")
        (gdest / "explorer.html").write_text(html, encoding="utf-8")
        views.append(("Global cross-workspace view",
                      "Strategic overview - every workspace as a cluster, with shared form names and duplicate flows.",
                      "global/explorer.html"))

    # Per-workspace explorers — operational depth.
    for slug in list_workspaces():
        src = OUTPUT_DIR / slug / WS_EXPLORER
        if not src.exists():
            continue
        dest = DOCS_DIR / slug
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "explorer.html").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        views.append((Workspace(slug).name,
                      "Operational explorer - forms, fields, relationships, and workflow detail.",
                      f"{slug}/explorer.html"))

    if not views:
        print("  docs/ not updated (no explorers found under output/).")
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    emit_field_index()
    featured_links = emit_form_briefs()
    _write_landing(views, stamp, featured_links)
    print(f"  docs/ -> {len(views)} view(s) + index.html + field-index.json + form briefs  ({stamp})")


def main():
    ap = argparse.ArgumentParser(description="Rebuild workspace inventories and explorers.")
    ap.add_argument("--workspace", metavar="SLUG", help="rebuild only this workspace")
    ap.add_argument("--global", dest="global_only", action="store_true",
                    help="rebuild only the cross-workspace global aggregator")
    ap.add_argument("--check", action="store_true",
                    help="discovery only: parse everything, print counts, orphans, "
                         "and warnings; write nothing")
    ap.add_argument("--snapshot", nargs="?", const="", metavar="LABEL",
                    help="capture a version snapshot without rebuilding (optional label)")
    ap.add_argument("--list-snapshots", action="store_true",
                    help="list saved snapshots under output/snapshots/")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"),
                    help="compare two snapshots (id, label, latest, or previous)")
    ap.add_argument("--compare-json", action="store_true",
                    help="with --compare, also write a JSON report file")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="skip auto-snapshot after a full rebuild")
    args = ap.parse_args()

    if args.list_snapshots:
        _list_snapshots()
        return

    if args.compare:
        _run_compare(args.compare[0], args.compare[1],
                     workspace=args.workspace, write_json=args.compare_json)
        return

    if args.snapshot is not None:
        label = args.snapshot or None
        _run_snapshot(label=label)
        return

    slugs = list_workspaces()
    if not slugs:
        print("No workspaces found under data/. Drop any export JSON under data/<slug>/")
        print("(whole-workspace export, or individual form/workflow exports).")
        sys.exit(1)

    if args.check:
        print("Check mode: discovery only, nothing written.\n")
        stats = {}
        for slug in slugs:
            ws = Workspace(slug)
            d = ws.discover()
            stats[slug] = (len(d["forms"]), len(d["workflows"]))
            orphans = find_orphans(d)
            print(f"[{slug}] {ws.name}: {len(d['forms'])} forms, "
                  f"{len(d['workflows'])} workflows, {len(orphans)} orphan(s)")
        _print_summary(stats)
        return

    if args.global_only:
        print("[global]")
        build_global.build()
        print("\n[docs] publish")
        publish_docs()
        _print_summary({})
        return

    if args.workspace:
        if args.workspace not in slugs:
            print(f"Unknown workspace '{args.workspace}'. Available: {', '.join(slugs)}")
            sys.exit(1)
        stats = {args.workspace: rebuild_workspace(args.workspace)}
        print("\nGlobal aggregator not rebuilt (run with --global or no args to refresh it).")
        print("\n[docs] publish")
        publish_docs()
        _print_summary(stats)
        return

    stats = {}
    for slug in slugs:
        stats[slug] = rebuild_workspace(slug)

    print("\n[global] cross-workspace aggregator")
    build_global.build()

    print("\n[docs] publish")
    publish_docs()

    if not args.no_snapshot:
        print("\n[snapshots]")
        _auto_snapshot(discover_all())

    print("\nDone. Output under output/<slug>/ and output/global/; browsable views mirrored to docs/.")
    _print_summary(stats)


if __name__ == "__main__":
    main()
