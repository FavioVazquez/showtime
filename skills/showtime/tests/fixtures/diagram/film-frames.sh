#!/bin/sh
# Rebuild film-frames.json (the film-parity baseline of tests/test_interactive.py) from the diagram engine of an
# older revision: today's template and examples, drawn by that revision's runtime/diagram.js.
#   sh tests/fixtures/diagram/film-frames.sh <rev>     # <rev>: the commit before live mode
# The test then checks that today's engine draws every film frame of the baseline identically.
set -eu
[ $# -eq 1 ] || { echo "usage: sh film-frames.sh <git revision>" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
tmp=$(mktemp -d)
cleanup() { git -C "$repo" worktree remove --force "$tmp/old" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
git -C "$repo" worktree add --detach "$tmp/old" "$1" >/dev/null 2>&1
python3 "$repo/skills/showtime/tests/test_interactive.py" TestFilmUntouched --write-golden --engine-from "$tmp/old/skills/showtime"
echo "film-frames.json rebuilt from $(git -C "$repo" rev-parse --short "$1")"
