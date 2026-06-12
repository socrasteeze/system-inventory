"""
regenerate.py — rebuild the Excel inventory and HTML explorer for every
workspace under data/, then rebuild the cross-workspace global aggregator.

Usage:
    python scripts/regenerate.py                 rebuild all workspaces + global
    python scripts/regenerate.py --workspace X   rebuild only workspace X
    python scripts/regenerate.py --global        rebuild only the global aggregator
"""
import sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import Workspace, list_workspaces
import build_inventory
import build_explorer
import build_global


def rebuild_workspace(slug):
    ws = Workspace(slug)
    print(f"[{slug}] {ws.name}")
    print("  Excel inventory")
    build_inventory.build(ws)
    print("  HTML explorer")
    build_explorer.build(ws)


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
        return

    if args.workspace:
        if args.workspace not in slugs:
            print(f"Unknown workspace '{args.workspace}'. Available: {', '.join(slugs)}")
            sys.exit(1)
        rebuild_workspace(args.workspace)
        print("\nGlobal aggregator not rebuilt (run with --global or no args to refresh it).")
        return

    for slug in slugs:
        rebuild_workspace(slug)

    print("\n[global] cross-workspace aggregator")
    build_global.build()

    print("\nDone. Per-workspace output under output/<slug>/, combined view under output/global/.")


if __name__ == "__main__":
    main()
