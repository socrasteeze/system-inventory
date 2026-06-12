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
import sys, argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import Workspace, list_workspaces, OUTPUT_DIR
import build_inventory
import build_explorer
import build_global

DOCS_DIR = OUTPUT_DIR.parent / "docs"
WS_EXPLORER = "workspace_explorer.html"      # per-workspace source filename in output/
GLOBAL_EXPLORER = "global-explorer.html"     # global source filename in output/


def rebuild_workspace(slug):
    ws = Workspace(slug)
    print(f"[{slug}] {ws.name}")
    print("  Excel inventory")
    build_inventory.build(ws)
    print("  HTML explorer")
    build_explorer.build(ws)


def _html_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _write_landing(views, stamp):
    """views: list of (title, description, href). Minimal dark landing page that
    matches the explorer's palette and fonts."""
    cards = "\n".join(
        f'''    <a class="view" href="{_html_escape(href)}">
      <div class="name">{_html_escape(title)} <span class="arrow">&rarr;</span></div>
      <div class="desc">{_html_escape(desc)}</div>
    </a>'''
        for title, desc, href in views)
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
  a.view{{display:block;background:var(--bg2);border:1px solid var(--border);
         border-radius:8px;padding:16px 18px;text-decoration:none;color:var(--text);
         transition:border-color 120ms,background 120ms}}
  a.view:hover{{border-color:var(--accent);background:var(--bg3)}}
  a.view .name{{font-size:15px;font-weight:600}}
  a.view .name .arrow{{color:var(--accent)}}
  a.view .desc{{color:var(--muted);font-size:12px;margin-top:4px}}
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
    _write_landing(views, stamp)
    print(f"  docs/ -> {len(views)} view(s) + index.html  ({stamp})")


def main():
    ap = argparse.ArgumentParser(description="Rebuild workspace inventories and explorers.")
    ap.add_argument("--workspace", metavar="SLUG", help="rebuild only this workspace")
    ap.add_argument("--global", dest="global_only", action="store_true",
                    help="rebuild only the cross-workspace global aggregator")
    args = ap.parse_args()

    slugs = list_workspaces()
    if not slugs:
        print("No workspaces found under data/. Add data/<slug>/forms and /workflows.")
        return

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
