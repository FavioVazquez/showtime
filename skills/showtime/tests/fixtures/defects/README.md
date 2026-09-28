# Planted-defect fixtures

Each folder is a tiny showtime project with exactly one known flaw. `tests/test_qa.py` runs the tool named in
its `DEFECT.json` and asserts that the rule fires at the stated severity ("prove it bites"). The clean
`templates/dom` project must pass the same tools.

`DEFECT.json`:
- `tool`: `check` (the project is checked in the browser) or `qa` (the project is rendered, then the MP4 is checked)
- `rule`: the rule id that must fire (`code` in check reports, `rule` in qa reports)
- `severity`: `FAIL`, `WARN` or `INFO` (check's error/warning/info map to FAIL/WARN/INFO)
- `render_args` (qa only): extra `showtime render` flags
- `check_args` (check only): extra `showtime check` flags
- `why`: what the defect is and how a real project ends up with it

When you add a lint to `check` or `qa`, add a fixture here first and watch the test fail.
