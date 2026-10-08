#!/usr/bin/env python3
"""Open, update or close the "Nightly failing on main" issue after the nightly tier of ci.yml.

The nightly-report job in .github/workflows/ci.yml runs this once the nightly matrix is done, with the
workflow's own GITHUB_TOKEN (issues: write, actions: read) and no other secret:

  failed run   : comments the failed jobs, their failed steps and test files (and the tests inside them)
                 plus the run link on the open issue labelled `ci: nightly`, or opens that issue
  green run    : closes the open issue with "Green again: <run link>" (only a run that covered every OS
                 image closes it; a manual run on fewer images can report a failure but not close it)
  cancelled or skipped: does nothing

    python scripts/nightly_report.py --repo OWNER/NAME --run-id ID --result failure
    python scripts/nightly_report.py --repo OWNER/NAME --run-id ID --result success --full
    python scripts/nightly_report.py --repo OWNER/NAME --run-id ID --result failure --dry-run   # print only

The comment is built from the run's jobs (GitHub's API) and the failed jobs' logs: the test runner's
"[n/N] FAIL <file>" lines and the unittest "FAIL:" / "ERROR:" lines under each file's failure block. Only test
names, file names, step names and exception class names are copied from a log, never its other text.
Needs the gh command line (preinstalled on GitHub's runners) and GH_TOKEN.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Callable, Dict, List, Optional

TITLE = "Nightly failing on main"
LABEL = "ci: nightly"
BOT = "app/github-actions"      # the author of the issues this job opens (GITHUB_TOKEN)
EXTRA_LABELS = ["type: chore"]
JOB_PREFIX = "nightly ("
MAX_TESTS_PER_FILE = 10
MAX_FILES_PER_JOB = 20

_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ")
_LABEL = r"(test_\w+\.py(?:\[\d+/\d+\])?)"
# run_all.py -j N:  "[56/64] FAIL test_signatures.py   900.7s rc=124 timed out after 900s"
_PROGRESS = re.compile(r"^\[\s*\d+/\d+\] FAIL %s\s+([\d.]+)s\s*(.*)$" % _LABEL)
# run_all.py -j 1 streams each file between "=== test_x.py (--fast)" and "=== test_x.py FAIL (rc=1) in 3.2s note"
_START = re.compile(r"^=== %s(?: \(--fast\))?\s*$" % _LABEL)
_SERIAL = re.compile(r"^=== %s FAIL \(rc=(-?\d+)\) in ([\d.]+)s\s*(.*)$" % _LABEL)
# the block run_all.py prints for each failed file after a parallel run
_BLOCK = re.compile(r"^={10,} %s FAIL \(rc=-?\d+\)" % _LABEL)
_UNITTEST = re.compile(r"^(FAIL|ERROR): (\w+) \(")
_EXC = re.compile(r"^((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception|Expired|Exit|Interrupt|Failure))\b")
_RC = re.compile(r"^rc=-?\d+\s*")


Gh = Callable[[List[str], Optional[str]], str]


def run_gh(args: List[str], stdin: Optional[str] = None) -> str:
    """gh <args>; its stdout. Raises RuntimeError with gh's own error on failure."""
    cp = subprocess.run(["gh"] + args, input=stdin, capture_output=True, text=True, encoding="utf-8",
                        errors="replace")
    if cp.returncode != 0:
        raise RuntimeError("gh %s failed (%d): %s" % (" ".join(args[:3]), cp.returncode, cp.stderr.strip()[:500]))
    return cp.stdout


def clean_note(text: str) -> str:
    """A runner note ("timed out after 900s") kept short and inert in Markdown."""
    text = _RC.sub("", text.strip())
    text = re.sub(r"[`|<>\[\]*_\\]", "", text)
    return text[:120].strip()


def parse_log(text: str) -> Dict[str, dict]:
    """{file label: {"seconds": float|None, "note": str, "tests": [[kind, name, exception]]}} from a job log."""
    files: Dict[str, dict] = {}
    current: Optional[str] = None    # the file whose output the lines belong to
    tests: List[list] = []           # its unittest failures so far
    pending: Optional[list] = None   # the unittest entry waiting for its exception line

    def entry(label: str, seconds=None, note: str = "") -> dict:
        e = files.setdefault(label, {"seconds": seconds, "note": note, "tests": []})
        if e["seconds"] is None and seconds is not None:
            e["seconds"], e["note"] = seconds, note or e["note"]
        return e

    for raw in text.splitlines():
        line = _STAMP.sub("", raw.rstrip("\r"))
        m = _PROGRESS.match(line)
        if m:
            entry(m.group(1), float(m.group(2)), clean_note(m.group(3)))
            continue
        m = _BLOCK.match(line)
        if m:
            current, pending = m.group(1), None
            tests = entry(current)["tests"]
            continue
        m = _START.match(line)
        if m:
            current, tests, pending = m.group(1), [], None
            continue
        m = _SERIAL.match(line)
        if m:
            e = entry(m.group(1), float(m.group(3)), clean_note(m.group(4)))
            if current == m.group(1):
                e["tests"].extend(t for t in tests if t not in e["tests"])
            current, tests, pending = None, [], None
            continue
        if (line.startswith("test file ") and "result" in line) or line.startswith("=== "):
            # the summary table ends the failure blocks; a passing -j 1 file ends with "=== <file> PASS"
            current, tests, pending = None, [], None
            continue
        if current is None:
            continue
        m = _UNITTEST.match(line)
        if m:
            pending = [m.group(1), m.group(2), ""]
            if m.group(2) not in [t[1] for t in tests]:
                tests.append(pending)
            continue
        if pending is not None and not pending[2]:
            m = _EXC.match(line)
            if m:
                pending[2] = m.group(1)
    return files


def failed_steps(job: dict) -> List[str]:
    return [s.get("name", "?") for s in job.get("steps") or [] if s.get("conclusion") == "failure"]


def nightly_jobs(jobs: List[dict]) -> List[dict]:
    return [j for j in jobs if str(j.get("name", "")).startswith(JOB_PREFIX)]


def os_of(job: dict) -> str:
    name = str(job.get("name", ""))
    return name[len(JOB_PREFIX):].rstrip(")") if name.startswith(JOB_PREFIX) else name


def build_comment(jobs: List[dict], logs: Dict[int, str], run_url: str, commit_url: str = "") -> str:
    """The Markdown comment (or issue body) for a failed nightly run."""
    nj = nightly_jobs(jobs)
    bad = [j for j in nj if j.get("conclusion") not in ("success", "skipped")]
    good = [os_of(j) for j in nj if j.get("conclusion") == "success"]
    lines = ["The nightly run failed: %s" % run_url]
    if commit_url:
        lines.append("Commit: %s" % commit_url)
    lines.append("")
    if not bad:
        lines.append("No nightly job reported a failure (the run failed before or around them); see the run.")
    for j in bad:
        steps = failed_steps(j)
        head = "**%s**: %s" % (os_of(j), j.get("conclusion") or j.get("status") or "unknown")
        if steps:
            head += ", failed step%s: %s" % ("s" if len(steps) > 1 else "", ", ".join(steps))
        if j.get("html_url"):
            head += " ([log](%s))" % j["html_url"]
        lines.append(head)
        files = parse_log(logs.get(j.get("id"), "") or "")
        for i, (label, info) in enumerate(sorted(files.items())):
            if i == MAX_FILES_PER_JOB:
                lines.append("- ... and %d more test files" % (len(files) - MAX_FILES_PER_JOB))
                break
            bits = ["`%s`" % label]
            extra = [x for x in (info["note"], ("%.0f s" % info["seconds"]) if info["seconds"] is not None else "")
                     if x]
            if extra:
                bits.append("(%s)" % ", ".join(extra))
            tests = info["tests"]
            if tests:
                shown = ["`%s`%s" % (name, (" " + exc) if exc else (" " + kind.lower() if kind == "ERROR" else ""))
                         for kind, name, exc in tests[:MAX_TESTS_PER_FILE]]
                if len(tests) > MAX_TESTS_PER_FILE:
                    shown.append("and %d more" % (len(tests) - MAX_TESTS_PER_FILE))
                bits.append(": " + ", ".join(shown))
            lines.append("- " + " ".join(bits).replace(" : ", ": "))
        lines.append("")
    if good:
        lines.append("Passed: %s." % ", ".join(good))
    return "\n".join(lines).rstrip() + "\n"


def decide(result: str, full: bool, open_issue: Optional[int]) -> str:
    """create | comment | close | none."""
    if result == "failure":
        return "comment" if open_issue else "create"
    if result == "success" and full and open_issue:
        return "close"
    return "none"


def find_issue(repo: str, gh: Gh) -> Optional[int]:
    out = gh(["issue", "list", "-R", repo, "--label", LABEL, "--state", "open", "--json", "number,title",
              "--limit", "20"], None)
    items = json.loads(out or "[]")
    if not items:   # opened without its label (the label was missing): match the title, on issues this job opened
        out = gh(["issue", "list", "-R", repo, "--state", "open", "--author", BOT, "--search", '"%s" in:title' % TITLE,
                  "--json", "number,title", "--limit", "20"], None)
        items = [i for i in json.loads(out or "[]") if i.get("title") == TITLE]
    return min(i["number"] for i in items) if items else None


def fetch_jobs(repo: str, run_id: str, gh: Gh) -> List[dict]:
    out = gh(["api", "repos/%s/actions/runs/%s/jobs?per_page=100&filter=latest" % (repo, run_id)], None)
    return json.loads(out or "{}").get("jobs", [])


def fetch_logs(repo: str, jobs: List[dict], gh: Gh) -> Dict[int, str]:
    logs: Dict[int, str] = {}
    for j in nightly_jobs(jobs):
        if j.get("conclusion") in ("success", "skipped") or not j.get("id"):
            continue
        try:
            logs[j["id"]] = gh(["api", "repos/%s/actions/jobs/%s/logs" % (repo, j["id"])], None)
        except RuntimeError as e:   # logs can expire or be missing; the job line still says what failed
            print("note: no log for job %s: %s" % (j["id"], e), file=sys.stderr)
    return logs


def main(argv: Optional[List[str]] = None, gh: Gh = run_gh) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Examples:\n"
                                        "  python scripts/nightly_report.py --repo FavioVazquez/showtime "
                                        "--run-id 123 --result failure --dry-run")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="OWNER/NAME")
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"), help="the workflow run")
    ap.add_argument("--result", required=True, help="needs.nightly.result: success, failure, cancelled or skipped")
    ap.add_argument("--full", action="store_true", help="the run covered every OS image (a green one may close)")
    ap.add_argument("--server", default=os.environ.get("GITHUB_SERVER_URL", "https://github.com"))
    ap.add_argument("--dry-run", action="store_true", help="print what would be posted; write nothing")
    args = ap.parse_args(argv)
    if not args.repo or not args.run_id:
        ap.error("--repo and --run-id are needed (or GITHUB_REPOSITORY and GITHUB_RUN_ID)")
    run_url = "%s/%s/actions/runs/%s" % (args.server, args.repo, args.run_id)
    issue = find_issue(args.repo, gh)
    action = decide(args.result, args.full, issue)
    print("nightly result %s, full=%s, open issue %s: %s" % (args.result, args.full, issue or "none", action))
    if action == "none":
        return 0
    if action == "close":
        text = "Green again: %s\n" % run_url
        cmd = ["issue", "close", str(issue), "-R", args.repo, "--comment", text]
        if args.dry_run:
            print("would run: gh " + " ".join(cmd[:5]) + "\n" + text)
        else:
            gh(cmd, None)
        return 0
    jobs = fetch_jobs(args.repo, args.run_id, gh)
    logs = fetch_logs(args.repo, jobs, gh)
    sha = next((j.get("head_sha") for j in jobs if j.get("head_sha")), "")
    commit_url = "%s/%s/commit/%s" % (args.server, args.repo, sha) if sha else ""
    body = build_comment(jobs, logs, run_url, commit_url)
    if action == "comment":
        cmd = ["issue", "comment", str(issue), "-R", args.repo, "--body-file", "-"]
    else:
        cmd = ["issue", "create", "-R", args.repo, "--title", TITLE, "--body-file", "-", "--label", LABEL]
        for lab in EXTRA_LABELS:
            cmd += ["--label", lab]
    if args.dry_run:
        print("would run: gh " + " ".join(cmd) + "\n---\n" + body)
        return 0
    try:
        print(gh(cmd, body).strip())
    except RuntimeError:
        if action != "create":
            raise
        # a label that does not exist fails the create: open it without labels (found again by its title)
        print(gh(["issue", "create", "-R", args.repo, "--title", TITLE, "--body-file", "-"], body).strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)
