Drop workspace data here to build the inventory / explorer.

Any platform export JSON goes anywhere under data\<slug>\ - the rebuild
detects what each file is (whole-workspace export, individual form design,
or individual workflow) and routes it automatically. No manual placement:
the forms\ and workflows\ subfolders still work but nothing requires them.

  data\<slug>\<any-name>.json    e.g. data\liwp\low-income_weatherization_program.json

An individual form/workflow export always overrides the same form/workflow
in the whole-workspace baseline (a surgical update).

Known slugs already published from this repo: liwp, nve-qar, sce-be, sdge-whp, socal-whp
Slugs use hyphens, not underscores.

Full details: see "Adding a new workspace" in CLAUDE.md.
