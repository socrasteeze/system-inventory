"""
regenerate.py — rebuild the Excel inventory and HTML explorer for every
workspace under data/, then rebuild the cross-workspace global aggregator.
Finally, mirror the HTML explorers into docs/ for GitHub Pages.

Usage:
    python scripts/regenerate.py                 rebuild all workspaces + global
    python scripts/regenerate.py --workspace X   rebuild only workspace X
    python scripts/regenerate.py --global        rebuild only the global aggregator

Every run refreshes docs/ from whatever explorers exist under output/, so a push
publishes the current views. Excel artifacts stay in output/ and are never copied
to docs/.
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
    # individual JSON into data/<slug>/forms/ usually supplies the missing links.
    orphans = find_orphans(ws.discover())   # cached; no re-parse, no duplicate prints
    if orphans:
        print(f"  Orphans: {len(orphans)} form(s) with no graph edge "
              f"(import the individual form JSON to connect):")
        for o in orphans:
            print(f"    - {o['name']} [{o['role']}] -- {o['reason']}")
    else:
        print("  Orphans: none")


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
        if chips:
            links = "".join(
                f'<a class="chip" href="{_html_escape(bhref)}">{_html_escape(fname)}</a>'
                for fname, bhref in chips)
            chip_html = f'\n      <div class="chips"><span class="chips-lbl">Featured:</span> {links}</div>'
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


def _render_brief(slug, ws_name, form, nar_form, data, featured):
    """Render one printable per-form brief (plain HTML, no JS)."""
    esc = _html_escape
    name = form["name"]
    role = form.get("role", "")
    s = nar_form["summary"]
    fwd = nar_form["forward"]

    parts = [(fn, e) for fn, e in fwd.items() if e["fields"] or e["wfCondition"]]
    if parts:
        rows = []
        for fn, e in parts:
            effects = []
            for x in e["fields"]:
                phrase = narrate.FORWARD_PHRASE.get(x["kind"], "{t}").format(t=esc(x["target"]))
                badge = narrate.KIND_BADGE.get(x["kind"], "DEP")
                effects.append(f'<div class="effect"><span class="chip {x["kind"]}">{badge}</span>{phrase}</div>')
            for cs in e["wfCondition"]:
                effects.append(f'<div class="effect"><span class="chip flow">FLOW</span>'
                               f'can change what workflow <b>{esc(cs)}</b> does</div>')
            rows.append(f'<tr><td class="field">{esc(fn)}</td><td>{"".join(effects)}</td></tr>')
        changes = ('<table><thead><tr><th>When you change&hellip;</th>'
                   '<th>&hellip;this happens</th></tr></thead><tbody>'
                   + "".join(rows) + "</tbody></table>")
    else:
        changes = '<div class="empty">No fields on this form trigger changes elsewhere.</div>'

    req = [f for f in data["fields"].get(name, []) if f.get("required") == "Yes"]
    if req:
        reqhtml = "<ul>" + "".join(
            f'<li>{esc(f.get("label") or f["name"])} '
            f'<span class="when">({esc(f["name"])})</span></li>' for f in req) + "</ul>"
    else:
        reqhtml = '<div class="empty">No required fields.</div>'

    acting = narrate._workflows_on(name, data.get("workflows", []))
    if acting:
        items = []
        for w in acting:
            cond = (w.get("trigger") or {}).get("condition")
            tail = f' &mdash; {esc(cond)}' if cond else ""
            items.append(f'<li><b>{esc(w.get("name") or w.get("callsign"))}</b> '
                         f'<span class="when">{esc(narrate._trigger_phrase(w))}{tail}</span></li>')
        wfhtml = "<ul>" + "".join(items) + "</ul>"
    else:
        wfhtml = '<div class="empty">No workflows act on this form.</div>'

    badges = f'<span class="badge {esc(role)}">{esc(role)}</span>'
    if featured:
        badges += '<span class="badge featured">Featured</span>'

    body = [
        f'  <a class="back" href="../explorer.html#form={quote(name)}">&larr; Back to {esc(ws_name)} explorer</a>',
        f'  <div class="badges" style="margin-top:14px">{badges}</div>',
        f'  <h1>{esc(name)}</h1>',
        f'  <div class="ws">{esc(ws_name)}</div>',
        f'  <p class="lead"><b>{esc(s["role_line"])}</b> {esc(s["connects"])}'
        + (f'<br>{esc(s["workflows"])}' if s["workflows"] else "")
        + f'<br><span class="muted">{esc(s["fields"])}'
        + (" " + esc(s["interactions"]) if s["interactions"] else "")
        + "</span></p>",
        f"  <h2>What changes what</h2>{changes}",
        f"  <h2>Required fields</h2>{reqhtml}",
        f"  <h2>Workflows acting on this form</h2>{wfhtml}",
        f'  <div class="foot">Generated by regenerate.py &middot; not hand-edited</div>',
    ]
    return (BRIEF_TEMPLATE
            .replace("__TITLE__", esc(name) + " — " + esc(ws_name))
            .replace("__BODY__", "\n".join(body)))


def emit_form_briefs():
    """Write a printable per-form brief for every form, into both
    output/<slug>/forms/ (so the local explorer's 'Open full brief' link resolves)
    and docs/<slug>/forms/ (for GitHub Pages). Returns {slug: [(name, docs_href)]}
    of featured forms for the landing page.

    Uses the same in-memory discover_all() source as emit_field_index(); the
    narrative is presentation-only and never touches field-index.json.
    """
    discovered = discover_all()
    featured_links = {}
    total = 0
    for slug, data in sorted(discovered.items()):
        ws_name = data.get("workspaceName", slug)
        nar = narrate.build_all(data)
        featured = set(data.get("featured", []))
        out_dir = OUTPUT_DIR / slug / "forms"
        docs_dir = DOCS_DIR / slug / "forms"
        out_dir.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        for form in data["forms"]:
            name = form["name"]
            html = _render_brief(slug, ws_name, form, nar[name], data, name in featured)
            fn = _brief_filename(name)
            (out_dir / fn).write_text(html, encoding="utf-8")
            (docs_dir / fn).write_text(html, encoding="utf-8")
            total += 1
        featured_links[slug] = [(n, f"{slug}/forms/{_brief_filename(n)}")
                                for n in data.get("featured", [])]
    print(f"  form briefs -> {total} page(s) (output/ + docs/)")
    return featured_links


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
    args = ap.parse_args()

    slugs = list_workspaces()
    if not slugs:
        print("No workspaces found under data/. Add data/<slug>/forms and /workflows,")
        print("or a whole-workspace export JSON at data/<slug>/*.json.")
        sys.exit(1)

    if args.global_only:
        print("[global]")
        build_global.build()
        print("\n[docs] publish")
        publish_docs()
        return

    if args.workspace:
        if args.workspace not in slugs:
            print(f"Unknown workspace '{args.workspace}'. Available: {', '.join(slugs)}")
            sys.exit(1)
        rebuild_workspace(args.workspace)
        print("\nGlobal aggregator not rebuilt (run with --global or no args to refresh it).")
        print("\n[docs] publish")
        publish_docs()
        return

    for slug in slugs:
        rebuild_workspace(slug)

    print("\n[global] cross-workspace aggregator")
    build_global.build()

    print("\n[docs] publish")
    publish_docs()

    print("\nDone. Output under output/<slug>/ and output/global/; browsable views mirrored to docs/.")


if __name__ == "__main__":
    main()
