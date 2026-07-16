# Individual WORKFLOW exports go here

Workflow JSONs exported from the platform (the ones with `Triggers` / `Steps`
at the top) — flat, or one subfolder per workflow:

```
workflows/
  Update Existing Measures.json
```

- An export here **overrides** the same workflow (matched by trigger form +
  name) in the whole-workspace baseline.
- Generated a workflow import with `scripts/expand_field_assignments.py` or
  `scripts/expand_subform_ops.py`? Drop the same file here so the inventory
  shows what you imported into the platform.

Then run `python scripts/regenerate.py` from the repo root.
