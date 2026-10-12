#!/usr/bin/env bash
# Run by `claude plugin eval --scaffold` with the run's empty workspace as the current directory.
# Puts two tiny real clips there (take 1: 12 s, take 3: 18 s; test pattern plus a tone, 160x90, about 80 KB
# in all). take2.mp4 is left out on purpose: the user has not uploaded it.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p footage
cp "$here/footage/take1.mp4" "$here/footage/take3.mp4" footage/
