"""
organize_forms.py — one-time reorganizer: move loose individual form design
exports into data/<slug>/forms/<Form Name>/ folders, the canonical home for a
form's version history.

Dry-run by default (prints what it would do); pass --apply to perform the
moves. Only individual *form* design exports are candidates — whole-workspace
baselines and workflow exports are classified by content (parser.detect_format
via Workspace.workspace_exports()) and never touched. Files already nested in
a forms/ subfolder are left alone.

Moves are alias-safe: form_aliases.json keys off the filename *stem*, which a
move never changes. data/ is gitignored, so this only changes the local disk.

Usage:
    python scripts/organize_forms.py                 dry run, all workspaces
    python scripts/organize_forms.py --workspace X   dry run, one workspace
    python scripts/organize_forms.py --apply         perform the moves
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parser import Workspace, list_workspaces, detect_format

# Mirrors regenerate._brief_filename()'s stripping (regenerate imports the whole
# build stack, so the pattern is copied rather than imported).
_WINDOWS_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


def _folder_name(form_name):
    return _WINDOWS_ILLEGAL_CHARS.sub("", form_name).strip() or "_unnamed"


def organize(slug, apply_moves):
    ws = Workspace(slug)

    # Baseline field sets for name resolution, same as discover() builds them.
    # workspace_exports() also routes root JSONs by content, populating
    # _root_form_files (never baselines or workflow exports).
    baseline_fields = {}
    for _fname, parsed in ws.workspace_exports():
        for pf in parsed["forms"]:
            baseline_fields[pf["name"]] = {f["name"] for f in pf["fields"]
                                           if f.get("name")}

    candidates = list(ws._root_form_files)
    if ws.forms_dir.exists():
        # Flat files directly in forms/ only; anything already nested stays put.
        for p in sorted(ws.forms_dir.glob("*.json")):
            try:
                fmt = detect_format(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
            if fmt == "form":
                candidates.append(p)

    moved = skipped = 0
    for path in candidates:
        try:
            parsed = ws.parse_form(path, baseline_fields=baseline_fields)
        except Exception as exc:
            print(f"  ! {slug}/{path.name}: unreadable ({exc}) -- skipped")
            skipped += 1
            continue
        dest_dir = ws.forms_dir / _folder_name(parsed["name"])
        dest = dest_dir / path.name
        if dest == path:
            continue
        rel_src = path.relative_to(ws.dir)
        rel_dst = dest.relative_to(ws.dir)
        if dest.exists():
            print(f"  ! {slug}/{path.name}: destination already exists "
                  f"({rel_dst}) -- skipped, resolve by hand")
            skipped += 1
            continue
        if apply_moves:
            dest_dir.mkdir(parents=True, exist_ok=True)
            path.rename(dest)
            print(f"  moved: {rel_src} -> {rel_dst}")
        else:
            print(f"  would move: {rel_src} -> {rel_dst}")
        moved += 1
    return moved, skipped


def main():
    ap = argparse.ArgumentParser(
        description="Move loose form design exports into forms/<Form Name>/ folders.")
    ap.add_argument("--workspace", help="only this workspace slug")
    ap.add_argument("--apply", action="store_true",
                    help="perform the moves (default is a dry run)")
    args = ap.parse_args()

    slugs = [args.workspace] if args.workspace else list_workspaces()
    total_moved = total_skipped = 0
    for slug in slugs:
        print(f"[{slug}]")
        moved, skipped = organize(slug, args.apply)
        if not moved and not skipped:
            print("  nothing to organize")
        total_moved += moved
        total_skipped += skipped

    verb = "moved" if args.apply else "would move"
    print(f"\n{verb}: {total_moved} file(s); skipped: {total_skipped}")
    if not args.apply and total_moved:
        print("Re-run with --apply to perform these moves, "
              "then run: python scripts/regenerate.py --check")


if __name__ == "__main__":
    main()
