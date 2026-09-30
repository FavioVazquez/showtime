# keelson

Catch configuration drift before it ships: keelson checks a `.env` file against the `.env.example`
your team commits, and tells you which keys are missing, extra, duplicated or empty.

keelson is a small Python package with no dependencies. It is meant for a pre-commit hook or a CI step:
it prints a short report and exits non-zero when something is wrong.

## Install

```bash
pip install keelson          # Python 3.8 or newer
```

## Use

```bash
keelson check                         # .env against .env.example in the current folder
keelson check --env prod.env          # another env file
keelson check --strict                # empty values are errors, not warnings
keelson check --format json           # machine-readable report for CI
keelson diff .env staging.env         # which keys differ between two env files (values are never printed)
keelson init                          # write .env.example from .env, with every value blanked
```

Example report:

```text
$ keelson check
.env vs .env.example
  error    missing    DATABASE_URL  (line 3 of .env.example)
  error    duplicate  API_TIMEOUT   (lines 3 and 6 of .env)
  warning  extra      DEBUG_SQL     (line 7 of .env, not in .env.example)
  warning  empty      SENTRY_DSN    (line 5 of .env)
2 errors, 2 warnings
```

(That is the report for the two files in `examples/`.)

## Exit codes

| code | meaning |
|---|---|
| 0 | no errors (warnings allowed) |
| 1 | at least one error |
| 2 | a file could not be read or parsed |

## How it works

1. `keelson/envfile.py` parses both files: `KEY=value` lines, `export KEY=value`, comments, blank lines,
   single- and double-quoted values. It keeps the line number of every key.
2. `keelson/rules.py` compares the two parsed files. Each rule (missing, extra, duplicate, empty) returns
   findings with a severity.
3. `keelson/report.py` prints the findings as text or JSON and picks the exit code.
4. `keelson/cli.py` wires the three together behind the `check`, `diff` and `init` commands.

Values are never printed by any command, so a report is safe to paste in a pull request.

## Develop

```bash
python -m unittest discover -s tests
```

## License

MIT
