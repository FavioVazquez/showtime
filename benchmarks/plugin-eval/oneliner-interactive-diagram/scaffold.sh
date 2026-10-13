#!/usr/bin/env bash
# Run by `claude plugin eval --scaffold` with the run's empty workspace ($HOME/cwd) as the current directory.
set -eu
# The eval gives each run a sealed HOME (the workspace is $HOME/cwd), so the agent would find no showtime setup
# and stop to ask for a 520 MB install. Clone the real one in (copy-on-write on APFS, a plain copy elsewhere).
real="${SHOWTIME_REAL_HOME:-$(eval echo "~$(id -un)")}"
if [ -d "$real/.showtime" ] && [ ! -e ../.showtime ]; then
  cp -cR "$real/.showtime" ../.showtime 2>/dev/null || cp -R "$real/.showtime" ../.showtime
fi
# The venv's interpreter is a symlink into the uv-managed Python under the real home, which the sandbox cannot
# read: clone that Python too and point the venv at the clone.
cfg=../.showtime/venv/pyvenv.cfg
if [ -f "$cfg" ]; then
  pyhome="$(sed -n 's/^home = //p' "$cfg")"
  case "$pyhome" in "$real"/*)
    pyroot="$(dirname "$pyhome")"
    cp -cR "$pyroot" ../.showtime/_python 2>/dev/null || cp -R "$pyroot" ../.showtime/_python
    sed -i.bak "s#^home = .*#home = $PWD/../.showtime/_python/bin#" "$cfg" && rm -f "$cfg.bak"
    for l in ../.showtime/venv/bin/python; do ln -sf "$(cd ../.showtime/_python/bin && pwd)/$(basename "$(readlink "$l")")" "$l"; done
  ;; esac
fi
