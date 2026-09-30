# Changelog

## 0.3.0 (2026-09-14)

- New `keelson init`: writes `.env.example` from `.env` with every value blanked (comments kept).
- New rule: duplicate keys in the same file are an error.
- `--strict` makes empty values errors instead of warnings.
- Reports now show the line number of every finding.

## 0.2.0 (2026-07-02)

- New `keelson diff A B`: lists the keys that differ between two env files, without printing values.
- `--format json` for CI.
- `export KEY=value` lines are understood.

## 0.1.0 (2026-05-20)

- First release: `keelson check` finds keys missing from `.env` and keys that are not in `.env.example`.
