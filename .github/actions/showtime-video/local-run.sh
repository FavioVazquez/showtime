#!/usr/bin/env bash
# Run the showtime-video action's steps on this machine, without GitHub: the same three run.py calls
# action.yml makes (prepare, setup, run), with a made-up GITHUB_* environment and a throwaway sample
# repository. Nothing is uploaded (upload is a separate step in action.yml, not run here).
#
#   .github/actions/showtime-video/local-run.sh [--event release|pull_request] [--vertical] WORKROOT
#
# WORKROOT is a scratch folder (created; keep it outside the repository). Use a clean showtime home to
# see an install from nothing:  HOME=$WORKROOT/home SHOWTIME_HOME=$WORKROOT/st local-run.sh $WORKROOT
# Run it again with the same SHOWTIME_HOME to see the warm-cache path (CACHE_HIT=true is set when the
# home already has an installed runtime).
set -euo pipefail

event=release
vertical=false
while [ $# -gt 0 ]; do
  case "$1" in
    --event) event="$2"; shift 2 ;;
    --vertical) vertical=true; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) break ;;
  esac
done
root="${1:?usage: local-run.sh [--event release|pull_request] [--vertical] WORKROOT}"
here="$(cd "$(dirname "$0")" && pwd)"
runner="$here/run.py"
mkdir -p "$root"
root="$(cd "$root" && pwd)"

# a tiny sample repository with a CHANGELOG
ws="$root/sample"
mkdir -p "$ws"
cat > "$ws/CHANGELOG.md" <<'EOF'
# Changelog

## 1.4.0 - 2026-09-29

### Added
- Export a report as a single HTML file
- A `--dry-run` flag on every command

### Fixed
- Sync no longer stalls on a slow network

## 1.3.0 - 2026-09-01

### Added
- Dark theme
EOF

# the webhook payload of the event GitHub would send
events="$root/events"
mkdir -p "$events"
if [ "$event" = release ]; then
  cat > "$events/event.json" <<'EOF'
{"action": "published",
 "release": {"tag_name": "v1.4.0", "name": "Sample 1.4.0",
             "html_url": "https://github.com/example/sample/releases/tag/v1.4.0",
             "published_at": "2026-09-29T10:00:00Z",
             "body": "## Added\n\n- Export a report as a single HTML file\n- A `--dry-run` flag on every command\n- Faster start: the first screen shows in half the time\n\n## Fixed\n\n- Sync no longer stalls on a slow network\n- The date on exported reports uses the reader's locale\n\n## Contributors\n\nThanks @alice and @bob.\n"}}
EOF
else
  cat > "$events/event.json" <<'EOF'
{"action": "opened", "number": 42,
 "pull_request": {"number": 42, "title": "Add a dark theme",
                  "html_url": "https://github.com/example/sample/pull/42",
                  "body": "## Changes\n\n- A dark theme that follows the system setting\n- Theme choice is remembered between sessions\n- Charts and code blocks use the new palette\n"}}
EOF
fi

export GITHUB_ACTIONS=false
export GITHUB_EVENT_NAME="$event"
export GITHUB_EVENT_PATH="$events/event.json"
export GITHUB_WORKSPACE="$ws"
export GITHUB_REPOSITORY="example/sample"
export GITHUB_SERVER_URL="https://github.com"
export GITHUB_OUTPUT="$root/github-output.txt"
export GITHUB_STEP_SUMMARY="$root/step-summary.md"
export RUNNER_OS="${RUNNER_OS:-Linux}"
export RUNNER_ARCH="${RUNNER_ARCH:-X64}"
export RUNNER_TEMP="$root/runner-temp"
mkdir -p "$RUNNER_TEMP"
: > "$GITHUB_OUTPUT"
: > "$GITHUB_STEP_SUMMARY"

export INPUT_MODE=release
export INPUT_TIER=minimal
export INPUT_BROWSER_DEPS=true
export INPUT_VERTICAL="$vertical"
export INPUT_INSTALL="npm install -g sample@1.4.0"

home="${SHOWTIME_HOME:-$HOME/.showtime}"
if [ -x "$home/venv/bin/python" ] && [ -f "$home/state.json" ]; then export CACHE_HIT=true; else export CACHE_HIT=false; fi

now() { python3 -c 'import time; print(time.time())'; }
t0=$(now)
echo "== prepare"; python3 "$runner" prepare
t1=$(now)
echo "== setup (CACHE_HIT=$CACHE_HIT)"; python3 "$runner" setup
t2=$(now)
echo "== run"
set +e
python3 "$runner" run
code=$?
set -e
t3=$(now)
python3 - "$t0" "$t1" "$t2" "$t3" "$code" <<'EOF'
import sys
t = [float(x) for x in sys.argv[1:5]]
print("== timings: prepare %.1f s, setup %.1f s, run %.1f s; run.py exit %s" % (t[1]-t[0], t[2]-t[1], t[3]-t[2], sys.argv[5]))
EOF
echo "== step outputs ($GITHUB_OUTPUT)"; cat "$GITHUB_OUTPUT"
echo "== step summary"; cat "$GITHUB_STEP_SUMMARY"
if [ -d "$home" ]; then echo "== home size"; du -sh "$home" 2>/dev/null || true; fi
exit "$code"
