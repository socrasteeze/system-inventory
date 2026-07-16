# Individual FORM design exports go here

One subfolder per form, named after the form:

```
forms/
  210 - Enrollment & Assessment Form/
    ..._210-enrollment&assessment_form_v70_design.json
    ..._210-enrollment&assessment_form_v71_design.json   ← just drop the new version in
```

- **New version of a form?** Drop it next to the old ones — the highest `_vNN`
  in the filename becomes active, older files stay as version history (they feed
  the "Version history" section in the form's brief). Don't delete them.
- The file is matched to its form by **field content**, not filename — no
  renaming or alias needed unless the rebuild says so.
- An export here **overrides** that form in the whole-workspace baseline.

Then run `python scripts/regenerate.py` from the repo root.
