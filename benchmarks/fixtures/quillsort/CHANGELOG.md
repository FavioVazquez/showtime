# Changelog

## 2.0.0

- New: `--natural` sort order, so `file2` comes before `file10`.
- New: `-i` edits files in place and keeps a `.bak` backup next to the original.
- New: `--strip-blank` removes empty lines before sorting.
- Changed: `--unique` now keeps the first occurrence of a duplicate instead of the last.
- Removed: support for Python 3.7.

## 1.1.0

- New: `--ignore-case`.
- Fixed: a trailing newline was dropped when the input did not end with one.

## 1.0.0

- First release: sort lines, `--unique`, `--reverse`, stdin support.
