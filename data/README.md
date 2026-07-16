# Where do I put this JSON?

Every workspace lives in its own folder here. Inside it, three kinds of platform
exports are recognized — **the rebuild detects which kind each file is by its
content, so a misplaced file still works** — but use the standard spots so
humans can find things too:

```
data/
  <workspace-slug>/                          e.g. sce-be, socal-whp (hyphens, never underscores)
    <workspace export>.json     ← 1. WHOLE-WORKSPACE export (the baseline) — at the slug root
    forms/                      ← 2. INDIVIDUAL FORM design exports (override the baseline)
      <Form Name>/                   one subfolder per form
        <export _v78>.json           drop each new version next to the old ones;
        <export _v79>.json           highest _vNN wins, older files stay as history
    workflows/                  ← 3. INDIVIDUAL WORKFLOW exports (override the baseline)
      <workflow name>.json           flat, or one subfolder per workflow
    manual/                     ← human-maintained overrides (names, roles, layout) — optional
```

## Which kind of file do I have?

Open the JSON and look at the top-level keys:

| You see...                                   | It is a...                  | Put it in...                        |
|----------------------------------------------|-----------------------------|--------------------------------------|
| `"Forms": [...]` + workspace `Name`          | whole-workspace export      | `data/<slug>/` (the root)            |
| `"Components": {...}` tree                   | individual form design      | `data/<slug>/forms/<Form Name>/`     |
| `"Triggers": [...]` + `"Steps": [...]`       | individual workflow         | `data/<slug>/workflows/`             |

## The three rules that matter

1. **Individual file always beats the baseline.** A form/workflow export that also
   exists in the workspace export is a surgical update — it wins, and the rebuild
   prints a warning so the override stays visible. Re-baselining with a fresh
   workspace export? Delete the individual files — that's the explicit reset.
2. **No renaming, no alias needed (usually).** Form exports are matched to their
   baseline form by comparing field names, not by filename. Only add a
   `manual/form_aliases.json` entry if the rebuild warns it can't decide.
3. **After any change:** run `python scripts/regenerate.py` from the repo root.
   `python scripts/regenerate.py --check` answers "is my data folder sane?"
   without writing anything.

Current workspaces: `liwp`, `nve-qar`, `sce-be`, `sdge-whp`, `socal-whp`.

Full details: *Ingestion formats & precedence* and *Adding a new workspace* in
[CLAUDE.md](../CLAUDE.md).
