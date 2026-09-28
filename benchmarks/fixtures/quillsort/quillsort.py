#!/usr/bin/env python3
"""quillsort: sort, dedupe and tidy the lines of a text file."""
import argparse
import re
import shutil
import sys

__version__ = "2.0.0"


def natural_key(line, ignore_case=False):
    text = line.lower() if ignore_case else line
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def tidy(lines, natural=False, ignore_case=False, unique=False, reverse=False, strip_blank=False):
    if strip_blank:
        lines = [line for line in lines if line.strip()]
    if unique:
        seen, kept = set(), []
        for line in lines:
            key = line.lower() if ignore_case else line
            if key not in seen:
                seen.add(key)
                kept.append(line)
        lines = kept
    if natural:
        key = lambda line: natural_key(line, ignore_case)
    else:
        key = (lambda line: line.lower()) if ignore_case else None
    return sorted(lines, key=key, reverse=reverse)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quillsort", description=__doc__)
    ap.add_argument("file", nargs="?", help="input file (default: stdin)")
    ap.add_argument("--natural", action="store_true", help="numbers inside lines compare as numbers")
    ap.add_argument("--ignore-case", action="store_true")
    ap.add_argument("--unique", action="store_true", help="drop duplicates, keep the first")
    ap.add_argument("--reverse", action="store_true")
    ap.add_argument("--strip-blank", action="store_true", help="remove empty lines")
    ap.add_argument("-i", "--in-place", action="store_true", help="rewrite the file (keeps FILE.bak)")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)
    if a.in_place and not a.file:
        ap.error("-i needs a file")
    src = open(a.file, encoding="utf-8") if a.file else sys.stdin
    with src:
        lines = src.read().splitlines()
    out = tidy(lines, a.natural, a.ignore_case, a.unique, a.reverse, a.strip_blank)
    text = "\n".join(out) + ("\n" if out else "")
    if a.in_place:
        shutil.copyfile(a.file, a.file + ".bak")
        with open(a.file, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
