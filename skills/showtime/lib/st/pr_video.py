"""A pull request -> a short video for its description, with no agent in the loop.

`showtime pr-video <N | URL>` reads the PR (`gh pr view` and `gh pr diff`; without gh: `--diff`/`--body`/
`--title`, or `git diff <base>...HEAD` on the local repo) and writes a project in the release-video look: a
hook (repo, number, title, author), the description's own lines, the evidence (the files changed as a small
tree with their +/- counts, one or two real hunks, the tests touched) and a closing card (what changes for
users when the description says so, the PR URL). Every word on screen comes from the PR or from a flag.
Lines that look like secrets (keys, tokens, .env values) are masked before anything is written, so they
never reach the screen or the project files.

Stdlib only (the render and the export are separate steps the CLI runs after writing the project).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import release_video as rv
from .common import ShowtimeError

GH_FIELDS = "title,body,number,author,headRefName,baseRefName,files,additions,deletions,commits,url,changedFiles"
GH_FILES_CAP = 100            # `gh pr view --json files` stops at about this many files
API_FILES_CAP = 3000          # the REST files endpoint lists at most this many
MASK = "\u2022" * 6

# ---------------------------------------------------------------------------
# the diff
# ---------------------------------------------------------------------------

_DIFF_GIT = re.compile(r"^diff --git a/(.*?) b/(.*)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def parse_diff(text: str) -> List[Dict[str, Any]]:
    """A unified diff (git or plain) -> [{path, old_path, status, binary, additions, deletions, hunks}]."""
    files: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    hunk: Optional[Dict[str, Any]] = None
    left = [0, 0]                            # old/new lines still expected in the open hunk

    def new_file(old: str, new: str) -> Dict[str, Any]:
        f = {"path": new, "old_path": old, "status": "modified", "binary": False, "additions": 0, "deletions": 0,
             "hunks": []}
        files.append(f)
        return f

    for raw in (text or "").splitlines():
        line = raw.rstrip("\r")
        if hunk is not None and (left[0] > 0 or left[1] > 0):
            tag = line[:1] if line[:1] in ("+", "-", " ", "\\") else (" " if line == "" else None)
            if tag is not None:
                if tag == "\\":
                    continue
                if tag in (" ", "-"):
                    left[0] -= 1
                if tag in (" ", "+"):
                    left[1] -= 1
                if tag == "+":
                    cur["additions"] += 1
                elif tag == "-":
                    cur["deletions"] += 1
                hunk["lines"].append([tag, line[1:]])
                continue
        hunk = None
        m = _DIFF_GIT.match(line)
        if m:
            cur = new_file(m.group(1), m.group(2))
            continue
        if line.startswith("--- ") and (cur is None or cur["hunks"]):
            old = line[4:].split("\t")[0]
            cur = new_file(re.sub(r"^a/", "", old), re.sub(r"^a/", "", old))
            continue
        if cur is None:
            continue
        m = _HUNK.match(line)
        if m:
            left = [int(m.group(2) if m.group(2) is not None else 1), int(m.group(4) if m.group(4) is not None else 1)]
            hunk = {"old_start": int(m.group(1)), "new_start": int(m.group(3)), "context": m.group(5).strip(),
                    "lines": []}
            cur["hunks"].append(hunk)
            continue
        if line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "removed"
        elif line.startswith("rename to "):
            cur["status"] = "renamed"
            cur["path"] = line[len("rename to "):]
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            cur["binary"] = True
        elif line.startswith("+++ "):
            p = line[4:].split("\t")[0]
            if p == "/dev/null":
                cur["status"] = "removed"
            else:
                cur["path"] = re.sub(r"^b/", "", p)
        elif line.startswith("--- /dev/null"):
            cur["status"] = "added"
    return files


# ---------------------------------------------------------------------------
# secrets: masked before anything is planned, shown or written
# ---------------------------------------------------------------------------

SECRET_FILE = re.compile(
    r"(^|/)(\.env(\.[\w.-]+)?|[\w.-]*\.env|\.npmrc|\.pypirc|\.netrc|\.htpasswd|\.git-credentials|credentials(\.\w+)?|"
    r"secrets?\.(ya?ml|json|toml|env)|id_(rsa|dsa|ecdsa|ed25519)|[^/]*\.(pem|key|p12|pfx|keystore|jks|ppk))$", re.I)
_TOKENS = [
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                          # AWS access key id
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})"),  # GitHub tokens
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),                             # GitLab
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),                        # Slack
    re.compile(r"\bsk-(?:[A-Za-z0-9]+-)*[A-Za-z0-9_-]{20,}"),              # OpenAI-style keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),                                # Google API key
    re.compile(r"\b[rsp]k_(?:live|test)_[0-9A-Za-z]{16,}"),                # Stripe
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),                                # npm
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),                        # user:password@ in a URL
]
_KEY_NAME = (r"[\w.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|passwd|pwd|auth[_-]?key|access[_-]?key|"
             r"private[_-]?key|client[_-]?secret|credentials?|signing[_-]?key|webhook[_-]?url|dsn)[\w.-]*")
# NAME = "literal" / NAME: 'literal' / "NAME": "literal" (a quoted value of 6+ characters)
_ASSIGN_QUOTED = re.compile(r"(?i)(\b%s[\"']?\s*(?::=|=>|[:=])\s*)([\"'])([^\"'\s]{6,})\2" % _KEY_NAME)
# NAME=value with an unquoted value that looks like a key (12+ characters, a digit, no call or path)
_ASSIGN_BARE = re.compile(r"(?i)(\b%s\s*(?:=|:\s)\s*)(?![\"'])([A-Za-z0-9_+/=.~-]{12,})(?=\s*(?:#.*)?$)" % _KEY_NAME)
_ENV_LINE = re.compile(r"^(\s*(?:export\s+)?[A-Za-z_][\w.-]*\s*[=:]\s*)(\S.*)$")
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")


def is_secret_file(path: str) -> bool:
    return bool(SECRET_FILE.search(path or ""))


def mask_line(text: str, *, env_file: bool = False) -> Tuple[str, bool]:
    """(the line with anything that looks like a secret replaced by dots, whether something was masked)."""
    out = text
    if env_file:
        m = _ENV_LINE.match(out)
        if m and not m.group(2).lstrip().startswith("#"):
            return m.group(1) + MASK, True
    for rx in _TOKENS:
        out = rx.sub(MASK, out)
    out = _ASSIGN_QUOTED.sub(lambda m: m.group(1) + m.group(2) + MASK + m.group(2), out)
    out = _ASSIGN_BARE.sub(lambda m: m.group(1) + MASK if re.search(r"\d", m.group(2)) else m.group(0), out)
    return out, out != text


def mask_text(text: str) -> Tuple[str, int]:
    """A description or title with secret-looking values masked; (text, lines masked)."""
    n = 0
    lines = []
    in_pem = False
    for line in (text or "").split("\n"):
        if in_pem or _PEM_BEGIN.search(line):
            in_pem = not _PEM_END.search(line)
            lines.append(MASK)
            n += 1
            continue
        m, hit = mask_line(line)
        n += hit
        lines.append(m)
    return "\n".join(lines), n


def mask_diff(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mask every secret-looking diff line in place; returns [{path, lines}] for the files that had some."""
    report = []
    for f in files:
        env = is_secret_file(f["path"])
        n = 0
        in_pem = False
        for h in f["hunks"]:
            for ln in h["lines"]:
                if in_pem or _PEM_BEGIN.search(ln[1]):
                    in_pem = not _PEM_END.search(ln[1])
                    ln[1], hit = MASK, True
                else:
                    ln[1], hit = mask_line(ln[1], env_file=env)
                n += hit
        f["masked"] = n
        if n:
            report.append({"path": f["path"], "lines": n})
    return report


# ---------------------------------------------------------------------------
# the description
# ---------------------------------------------------------------------------

# sections of a PR template that are not the change itself (the evidence scenes show the tests)
SKIP_HEAD = re.compile(r"\b(test(s|ing|ed)?|checklist|check ?list|screenshots?|screen ?recordings?|videos?|demo|"
                       r"how (to|did you|was)|reviewers?|review notes|authorship|follow[- ]?up|related|issues?|"
                       r"tickets?|todo|to do|pre-?merge|type of change|ai|disclosure|contributor|license|"
                       r"acknowledg|thanks|references?|links?|deploy|rollout|rollback|appendix|metadata)\b", re.I)
IMPACT_HEAD = re.compile(r"(user[- ]?facing|for users|users? impact|what changes for|impact|release notes?|"
                         r"changelog|breaking|migration|upgrad|behaviou?r change|what's new|whats new)", re.I)
_REF_LINE = re.compile(r"^\s*(?:[-*+]\s+)?\**((?:fix(?:es|ed)?|close[sd]?|resolve[sd]?|refs?|part of|related to)"
                       r"\s*:?\s+(?:[\w.-]+/[\w.-]+)?#\d+(?:\s*(?:,|and)\s*(?:[\w.-]+/[\w.-]+)?#\d+)*)\**\.?\s*$", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(\[])")


def _sentences(par: str) -> List[str]:
    return [s.strip() for s in _SENTENCE.split(par) if s.strip()]


def parse_body(md: str) -> Dict[str, Any]:
    """A PR description -> {summary: [lines], impact: {title, lines} or None, refs: ["Fixes #12"]}.

    The summary is the description's own prose (one sentence per line) and top-level bullets, from the
    opening text and from sections that are not template chrome (test plans, checklists, reviewer notes)."""
    md = re.sub(r"<!--.*?-->", "", md or "", flags=re.S)
    md = re.sub(r"<!--.*$", "", md, flags=re.S)                 # an unclosed comment hides the rest
    md = re.sub(r"```.*?```", "", md, flags=re.S)
    md = re.sub(r"<details>.*?</details>", "", md, flags=re.S | re.I)
    refs: List[str] = []
    sections: List[Dict[str, Any]] = [{"title": "", "kind": "summary", "lines": []}]
    para: List[str] = []

    def flush() -> None:
        if para:
            text = rv._plain(" ".join(para))
            if text and not re.fullmatch(r"\W*", text):
                sections[-1]["lines"] += _sentences(text)
            del para[:]

    for line in rv._join_continuations(md.splitlines()):
        s = line.rstrip()
        h = (re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", s)
             or re.match(r"^\s*(?:\*\*|__)([^*_]{2,60}?):?(?:\*\*|__):?\s*$", s))
        if h:
            flush()
            title = rv._plain(h.group(1)).strip(" :")
            kind = "impact" if IMPACT_HEAD.search(title) else ("skip" if SKIP_HEAD.search(title) else "summary")
            sections.append({"title": title, "kind": kind, "lines": []})
            continue
        r = _REF_LINE.match(s)
        if r:
            flush()
            refs.append(rv._plain(r.group(1)))
            continue
        if not s.strip() or re.match(r"^\s*(\||>|!\[|<img|<video|-{3,}|\*{3,}|_{3,})", s):
            flush()
            continue
        b = re.match(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$", s)
        if b:
            flush()
            if len(b.group(1).expandtabs(4)) >= 2 or re.match(r"^\[[ xX]\]", b.group(2)):
                continue                     # nested bullets and checkboxes are detail or chrome
            text = rv._plain(b.group(2))
            text = rv._URL.sub("", text).strip(" -:;")
            if len(text) >= 3:
                sections[-1]["lines"].append(text)
            continue
        if re.fullmatch(r"\s*<?https?://\S+>?\s*", s) or re.fullmatch(r"\s*[^.!?]{1,60}:\s*", s):
            flush()                          # a bare link (an uploaded video) or a "Label:" line
            continue
        para.append(s.strip())
    flush()
    summary: List[str] = []
    impact = None
    for sec in sections:
        lines = [x for x in sec["lines"] if len(x) >= 3]
        if sec["kind"] == "summary":
            summary += lines
        elif sec["kind"] == "impact" and lines and impact is None:
            impact = {"title": rv.shorten(sec["title"], 40), "lines": lines}
    return {"summary": summary, "impact": impact, "refs": list(dict.fromkeys(refs))}


# ---------------------------------------------------------------------------
# metadata: gh's JSON, the REST API's, or flags
# ---------------------------------------------------------------------------

_PR_URL = re.compile(r"https?://[^/\s]+/([\w.-]+)/([\w.-]+)/pull/(\d+)")


def parse_pr_ref(ref: str) -> Tuple[str, Optional[int]]:
    """'482', '#482' or a PR URL -> (owner/repo or '', number or None)."""
    ref = (ref or "").strip()
    m = _PR_URL.match(ref)
    if m:
        return "%s/%s" % (m.group(1), m.group(2)), int(m.group(3))
    m = re.fullmatch(r"#?(\d+)", ref)
    return ("", int(m.group(1))) if m else ("", None)


def normalize_meta(d: Dict[str, Any]) -> Dict[str, Any]:
    """`gh pr view --json ...` output or a REST `pulls/N` object -> one shape."""
    author = d.get("author") or d.get("user") or {}
    url = d.get("url") or d.get("html_url") or ""
    if "api.github.com" in url:
        url = d.get("html_url") or ""
    repo, number = parse_pr_ref(url)
    files = []
    for f in d.get("files") or []:
        path = f.get("path") or f.get("filename")
        if path:
            files.append({"path": path, "additions": int(f.get("additions") or 0),
                          "deletions": int(f.get("deletions") or 0)})
    commits = d.get("commits")
    return {"number": d.get("number") or number, "title": (d.get("title") or "").strip(), "body": d.get("body") or "",
            "author": (author.get("login") if isinstance(author, dict) else str(author or "")) or "",
            "url": url, "repo": repo,
            "head": d.get("headRefName") or (d.get("head") or {}).get("ref") or "",
            "base": d.get("baseRefName") or (d.get("base") or {}).get("ref") or "",
            "additions": d.get("additions"), "deletions": d.get("deletions"),
            "changed_files": d.get("changedFiles") or d.get("changed_files"),
            "commits": len(commits) if isinstance(commits, list) else commits, "files": files}


def parse_json_stream(text: str) -> List[Any]:
    """`gh api --paginate` prints one JSON array per page back to back: [..][..] -> one flat list."""
    dec = json.JSONDecoder()
    out: List[Any] = []
    i, n = 0, len(text or "")
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        val, i = dec.raw_decode(text, i)
        out += val if isinstance(val, list) else [val]
    return out


# ---------------------------------------------------------------------------
# without gh: a public PR from GitHub's REST API (read-only, no token is ever sent)
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"     # SHOWTIME_GITHUB_API overrides it (tests, GitHub Enterprise)
API_PAGES = 30                            # files pages of 100: the API lists at most 3000 files


def _api(path: str, accept: str = "application/vnd.github+json", timeout: float = 30.0,
         raw: Sequence[int] = ()) -> bytes:
    """GET <api><path> without credentials. Errors become ShowtimeErrors that say what to do, except the HTTP
    codes in `raw`, which are raised as they are for the caller to handle."""
    import urllib.error
    import urllib.request
    base = os.environ.get("SHOWTIME_GITHUB_API") or GITHUB_API
    req = urllib.request.Request(base.rstrip("/") + path, headers={
        "Accept": accept, "User-Agent": "showtime-pr-video", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        hdr = e.headers or {}
        if e.code in (403, 429) and (hdr.get("x-ratelimit-remaining") == "0" or e.code == 429):
            reset = hdr.get("x-ratelimit-reset")
            when = time.strftime("%H:%M", time.localtime(int(reset))) if reset and reset.isdigit() else "within the hour"
            raise ShowtimeError("GitHub's rate limit for requests without sign-in (60 an hour) is used up",
                                why="without gh, pr-video reads public PRs from the REST API anonymously",
                                hint="try again after %s, or sign in with gh auth login (5000 an hour)" % when)
        if e.code == 404:
            raise ShowtimeError("GitHub has no public pull request at %s" % path.replace("/repos/", "", 1),
                                why="the repository is private, or the number or repository is wrong",
                                hint="for a private repository: gh auth login; or pass the PR yourself with --diff "
                                     "pr.diff --body pr.md --title '<title>'")
        if e.code in raw:
            raise
        raise ShowtimeError("GitHub's API answered HTTP %d for %s" % (e.code, path),
                            hint="try again later, or pass the PR yourself with --diff pr.diff --body pr.md "
                                 "--title '<title>'")
    except (urllib.error.URLError, OSError) as e:
        raise ShowtimeError("could not reach GitHub's API: %s" % getattr(e, "reason", e),
                            hint="check the network (HTTPS_PROXY is used when set), or pass the PR yourself "
                                 "with --diff pr.diff --body pr.md --title '<title>'")


def rest_pr(repo: str, number: int) -> Tuple[Dict[str, Any], str, List[str]]:
    """(meta, diff, notes) for a public PR, read from the REST API without signing in: the PR, its diff, and the
    file list only when GitHub will not send the diff (too large)."""
    import urllib.error
    meta = normalize_meta(json.loads(_api("/repos/%s/pulls/%d" % (repo, number)).decode("utf-8")))
    meta["repo"] = meta.get("repo") or repo
    notes: List[str] = []
    try:
        diff = _api("/repos/%s/pulls/%d" % (repo, number), accept="application/vnd.github.diff",
                    timeout=120, raw=(406, 422)).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        diff = ""
        files: List[Any] = []
        for page in range(1, API_PAGES + 1):
            got = json.loads(_api("/repos/%s/pulls/%d/files?per_page=100&page=%d" % (repo, number, page)).decode())
            files += got
            if len(got) < 100:
                break
        meta["files"] = normalize_meta({"files": files})["files"]
        notes.append("this PR is too big to show in full: GitHub would not send its diff (HTTP %d); the video shows "
                     "the files changed, without hunks" % e.code)
    cf = meta.get("changed_files")
    if meta["files"] and isinstance(cf, int) and cf > len(meta["files"]):
        notes.append("this PR is too big to show in full: it changes %d files and GitHub lists %d; the count on screen "
                     "is %d, the tree comes from the files listed" % (cf, len(meta["files"]), cf))
    return meta, diff, notes


def files_look_capped(meta: Dict[str, Any]) -> bool:
    n = len(meta.get("files") or [])
    cf = meta.get("changed_files")
    return n >= GH_FILES_CAP or (isinstance(cf, int) and cf > n)


# ---------------------------------------------------------------------------
# picking the evidence
# ---------------------------------------------------------------------------

LOCKFILE = re.compile(r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|"
                      r"poetry\.lock|Pipfile\.lock|uv\.lock|Cargo\.lock|go\.sum|composer\.lock|Gemfile\.lock|"
                      r"flake\.lock|[^/]+\.lock)$")
GENERATED = re.compile(r"(\.min\.(js|css)$|\.map$|(^|/)(dist|build|vendor|node_modules|third_party|__snapshots__|"
                       r"__generated__)/|\.snap$|\.pb\.go$|_pb2(_grpc)?\.py$|\.generated\.|\.svg$|\.ipynb$)")
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|specs?|testdata|e2e)/|(^|/)test_[^/]+$|_test\.\w+$|"
                       r"\.(test|spec)\.\w+$|Tests?\.\w+$|_spec\.rb$")
DOC_FILE = re.compile(r"(\.(md|mdx|rst|txt|adoc)$|(^|/)docs?/)", re.I)
CODE_EXT = set("py pyi js mjs cjs ts tsx jsx go rs java kt kts swift c h cc cpp cxx hpp cs rb php scala sh bash zsh "
               "fish lua dart ex exs erl clj vue svelte zig m mm sql r jl hs ml elm nim cr pl ps1 sol".split())
CONFIG_EXT = set("json yaml yml toml ini cfg conf xml gradle mk cmake properties".split())
_TRIVIAL = re.compile(r"^\s*($|#|//|/\*|\*|--|import\b|from\s+\S+\s+import\b|#include\b|use\s|require\b|package\s)")

# characters per code row and rows per hunk for each frame (the CSS sizes below set what fits)
CODE_FIT = {"16:9": (46, 8), "1:1": (30, 10), "4:5": (30, 12), "9:16": (23, 11)}
# files in the tree, rows in all (files and their folders), and the characters a folder or a file name may take
TREE_FIT = {"16:9": {"max_files": 5, "max_rows": 6, "dir_chars": 40, "name_chars": 24},
            "1:1": {"max_files": 5, "max_rows": 6, "dir_chars": 28, "name_chars": 20},
            "4:5": {"max_files": 6, "max_rows": 8, "dir_chars": 28, "name_chars": 20},
            "9:16": {"max_files": 5, "max_rows": 7, "dir_chars": 24, "name_chars": 16}}


def is_test(path: str) -> bool:
    return bool(TEST_FILE.search(path or ""))


def file_weight(path: str) -> float:
    """How much a file's hunks say about the change (0 = never shown)."""
    if LOCKFILE.search(path) or GENERATED.search(path) or is_secret_file(path):
        return 0.0
    if is_test(path):
        return 1.0
    if DOC_FILE.search(path):
        return 1.2
    ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if ext in CODE_EXT:
        return 3.0
    if ext in CONFIG_EXT:
        return 1.5
    return 1.0


def hunk_score(f: Dict[str, Any], h: Dict[str, Any]) -> float:
    w = file_weight(f["path"])
    if not w or f.get("binary"):
        return 0.0
    changed = [t for t in h["lines"] if t[0] != " "]
    if not changed:
        return 0.0
    adds = sum(1 for t in changed if t[0] == "+")
    dels = len(changed) - adds
    size = min(len(changed), 10) / 10.0 + (0.4 if 2 <= len(changed) <= 12 else (0.25 if len(changed) == 1 else 0.0))
    s = w * (0.5 + size) * (1.25 if adds and dels else 1.0)
    if all(_TRIVIAL.match(t[1]) for t in changed):
        s *= 0.2                             # imports, comments and blank lines alone
    if any(MASK in t[1] for t in h["lines"]):
        s *= 0.3
    return s


def _rows(text: str, cols: int) -> int:
    return max(1, int(math.ceil(len(text) / float(cols))))


def excerpt(f: Dict[str, Any], h: Dict[str, Any], *, cols: int = 60, rows: int = 10) -> Dict[str, Any]:
    """The readable part of a hunk: its first block of changes with a line of context around it, dedented,
    cut to `rows` wrapped rows of `cols` characters (cut lines end with an ellipsis; dropped lines are counted)."""
    lines = [[t, x.expandtabs(4).rstrip()] for t, x in h["lines"]]
    idx = [i for i, (t, _x) in enumerate(lines) if t != " "]
    first = last = idx[0]
    for i in idx[1:]:                        # the first block: stop at a gap of more than 3 context lines
        if i - last > 4:
            break
        last = i
    lo, hi = max(0, first - 1), min(len(lines), last + 2)
    win = lines[lo:hi]
    while win and win[0][0] == " " and not win[0][1].strip():
        win.pop(0)
    while win and win[-1][0] == " " and not win[-1][1].strip():
        win.pop()
    hidden = 0
    long_cap = cols * 3
    win = [[t, rv.shorten(x, long_cap) if len(x) > long_cap else x] for t, x in win]

    def need(ls: Sequence[Sequence[str]]) -> int:
        ind = _indent(ls)
        return sum(_rows(x[ind:], cols) for _t, x in ls)

    while win and need(win) > rows:
        if win[0][0] == " ":
            win.pop(0)
        elif win[-1][0] == " ":
            win.pop()
        else:
            win.pop()
            hidden += 1
    ind = _indent(win)
    shown = [[t, x[ind:]] for t, x in win]
    rest = sum(1 for t, _x in lines[hi:] if t != " ")
    return {"path": f["path"], "context": rv.shorten(h.get("context") or "", cols), "lines": shown,
            "hidden": hidden + rest, "line": h.get("new_start")}


def _indent(lines: Sequence[Sequence[str]]) -> int:
    ws = [len(x) - len(x.lstrip(" ")) for _t, x in lines if x.strip()]
    return min(ws) if ws else 0


def pick_hunks(files: List[Dict[str, Any]], *, limit: int = 2, aspect: str = "16:9") -> List[Dict[str, Any]]:
    """The one or two hunks that say most about the change, from different files."""
    cols, rows = CODE_FIT.get(aspect, CODE_FIT["16:9"])
    scored = sorted(((hunk_score(f, h), i, f, h) for i, f in enumerate(files) for h in f["hunks"]),
                    key=lambda x: (-x[0], x[1]))
    out: List[Dict[str, Any]] = []
    used: List[str] = []
    best = 0.0
    for s, _i, f, h in scored:
        if s <= 0 or len(out) >= limit:
            break
        if f["path"] in used or (out and s < 0.4 * best):
            continue
        best = best or s
        out.append(dict(excerpt(f, h, cols=cols, rows=rows), score=round(s, 2)))
        used.append(f["path"])
    return out


def file_stats(diff_files: List[Dict[str, Any]], meta_files: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """[{path, additions, deletions, test}]: gh's or the API's counts when given (they cover binary files and
    diffs GitHub would not send), else the diff's."""
    src = list(meta_files) or [{"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
                               for f in diff_files]
    return [{"path": f["path"], "additions": int(f.get("additions") or 0), "deletions": int(f.get("deletions") or 0),
             "test": is_test(f["path"])} for f in src]


def tree_rows(stats: List[Dict[str, Any]], *, max_files: int = 6, max_rows: int = 99, dir_chars: int = 34,
              name_chars: int = 30) -> Tuple[List[Dict[str, Any]], int]:
    """The files with the most changed lines (at most `max_files`, and at most `max_rows` rows counting their
    folders), grouped under their folders, in path order. Returns (rows, files left out)."""
    top: List[Dict[str, Any]] = []
    for f in sorted(stats, key=lambda f: (-(f["additions"] + f["deletions"]), f["path"])):
        dirs = {g["path"].rpartition("/")[0] for g in top + [f]} - {""}
        if len(top) >= max_files or (top and len(top) + 1 + len(dirs) > max_rows):
            break
        top.append(f)
    top.sort(key=lambda f: f["path"])
    rows: List[Dict[str, Any]] = []
    last_dir = None
    for f in top:
        d, _, name = f["path"].rpartition("/")
        if d != last_dir:
            if d:
                shown = d + "/"
                if len(shown) > dir_chars:
                    shown = "\u2026" + shown[-(dir_chars - 1):]
                    shown = "\u2026/" + shown.split("/", 1)[1] if "/" in shown[1:-1] else shown
                rows.append({"dir": shown})
            last_dir = d
        rows.append({"name": rv.shorten(name, name_chars), "additions": f["additions"], "deletions": f["deletions"],
                     "test": f["test"], "nested": bool(d), "path": f["path"]})
    return rows, max(0, len(stats) - len(top))


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------

CHUNK_CHARS = (64, 88)       # a phrase on screen: aim for 64 characters, never split one of 88 or fewer
_JOINERS = set("when while because so but and or which that matching by for with without if after before instead "
               "from into until unless since where whereas rather than so then".split())


def chunks(sentence: str, aim: int = CHUNK_CHARS[0], most: int = CHUNK_CHARS[1]) -> List[str]:
    """A long sentence -> phrases of about `aim` characters, one per frame, cut at a clause: after a comma, colon or
    semicolon first, else before a joining word (when, while, because, which, ...), never inside a code span. The
    words are the sentence's own, in order; nothing is added or dropped."""
    s = sentence.strip()
    if len(s) <= most:
        return [s]
    best: Optional[Tuple[float, int]] = None
    for m in re.finditer(r" ", s):
        i = m.start()
        left, right = s[:i], s[i + 1:]
        if len(left) < 18 or len(right) < 14 or left.count("`") % 2:
            continue
        w = re.match(r"[A-Za-z]+", right)
        cost = abs(len(left) - len(right)) + max(0, len(left) - aim) + max(0, len(right) - aim)
        cost += -40 if left[-1] in ",;:" else (-20 if w and w.group(0).lower() in _JOINERS else 30)
        if best is None or cost < best[0]:
            best = (cost, i)
    if best is None:
        return [s]
    i = best[1]
    return chunks(s[:i], aim, most) + chunks(s[i + 1:], aim, most)


def read_time(text: str) -> float:
    """Seconds a line needs once it has settled: the phone check's lead and reading speed (references/qa.md:
    0.3 s, then 17 characters or 3 words a second, the longer; at least 1 s)."""
    t = re.sub(r"`", "", text or "")
    return max(1.0, 0.3 + max(len(t) / 17.0, len(t.split()) / 3.0))


LEAD = 0.15          # when a scene's first line starts to rise (the dip in covers the rest)
ENTER = 0.3          # a line's rise until it reads (the CSS animations settle in about this)
OUT = 0.25           # half of the 0.5 s dip between scenes


def length_budget(files: int, changed_lines: int) -> float:
    """How long the video may run, from the size of the PR: about 16-20 s for a small one, up to 45 s for a big one."""
    return round(min(45.0, max(16.0, 15.0 + 3.0 * math.log2(max(1, files)) + 2.0 * math.log2(1 + changed_lines / 20.0))),
                 1)


def plan(meta: Dict[str, Any], body: Dict[str, Any], stats: List[Dict[str, Any]], hunks: List[Dict[str, Any]], *,
         max_items: int = 4, max_seconds: Optional[float] = None, aspect: str = "16:9") -> Dict[str, Any]:
    """Pick what goes on screen and how long each scene holds. One phrase of the description per frame (long
    sentences are cut at a clause, chunks()); holds follow the phone check's reading speed (read_time()); the
    length scales with the PR (length_budget()) and drops description lines, then the second hunk, to fit."""
    adds = meta.get("additions") if isinstance(meta.get("additions"), int) else sum(f["additions"] for f in stats)
    dels = meta.get("deletions") if isinstance(meta.get("deletions"), int) else sum(f["deletions"] for f in stats)
    cf = meta.get("changed_files")
    n_files = max(cf, len(stats)) if isinstance(cf, int) else len(stats)
    if max_seconds is None:
        max_seconds = length_budget(n_files, adds + dels)
    total_lines = len(body["summary"])
    sentences = [chunks(rv.shorten(x, 200)) for x in body["summary"][:max(0, max_items)]]
    hunks = list(hunks)
    impact = None
    if body.get("impact"):
        impact = {"title": body["impact"]["title"], "lines": [rv.shorten(x, 90) for x in body["impact"]["lines"][:2]]}
    rows, files_more = tree_rows(stats, **TREE_FIT.get(aspect, TREE_FIT["16:9"]))
    # the tests touched: tagged in the tree; listed under it too when some are not in the tree, or in tall
    # frames (where the tag is hidden for room)
    in_tree = {r["path"] for r in rows if "path" in r}
    tests = [f["path"].rsplit("/", 1)[-1] for f in stats if f["test"]]
    if aspect != "9:16" and all(f["path"] in in_tree for f in stats if f["test"]):
        tests = []
    tests_line = "Tests " + ", ".join(tests[:3]) + (" + %d more" % (len(tests) - 3) if len(tests) > 3 else "")
    title = rv.shorten(meta["title"], 90)

    def hook_dur() -> float:
        return round(max(2.8, read_time(title) + OUT), 2)

    def chunk_dur(text: str) -> float:
        return round(max(2.0, LEAD + ENTER + read_time(text) + OUT), 2)

    def files_dur() -> float:
        n = len(rows) + (1 if files_more else 0)
        head = "%d files changed +%d -%d" % (n_files, adds, dels)
        last_row = LEAD + 0.1 * n
        need = max(ENTER + read_time(head), last_row + ENTER + 1.0,
                   (last_row + 0.1 + ENTER + read_time(tests_line)) if tests else 0.0)
        return round(max(2.6, need + OUT), 2)

    def diff_dur(h: Dict[str, Any]) -> float:
        # every line readable before the cut: it rises at `at` (as build_page staggers them) and needs read_time()
        at, need = LEAD, read_time(h["path"]) + ENTER
        for _t, x in h["lines"]:
            need = max(need, at + ENTER + read_time(x))
            at += 0.05
        return round(max(3.0, need + OUT), 2)

    def end_dur() -> float:
        if not impact:
            return 2.8
        return round(max(2.8, LEAD + ENTER + sum(read_time(x) for x in impact["lines"]) + 0.3 + OUT), 2)

    def length() -> float:
        return (hook_dur() + sum(chunk_dur(c) for sent in sentences for c in sent) + (files_dur() if stats else 0)
                + sum(diff_dur(h) for h in hunks) + end_dur())

    while length() > max_seconds:
        if len(sentences) > 2:
            sentences.pop()
        elif len(hunks) > 1:
            hunks.pop()
        elif len(sentences) > 1:
            sentences.pop()
        else:
            break
    more = max(0, total_lines - len(sentences))
    scenes: List[Dict[str, Any]] = [{"id": "hook", "dur": hook_dur()}]
    k = 0
    for i, sent in enumerate(sentences):
        for j, c in enumerate(sent):
            k += 1
            last = i == len(sentences) - 1 and j == len(sent) - 1
            scenes.append({"id": "sum%d" % k, "dur": chunk_dur(c), "text": c, "cont": j > 0,
                           "more": more if last else 0})
    if stats:
        scenes.append({"id": "files", "dur": files_dur(), "rows": rows, "files_more": files_more, "tests": tests,
                       "tests_line": tests_line})
    for i, h in enumerate(hunks):
        scenes.append({"id": "diff%d" % (i + 1), "dur": diff_dur(h), "hunk": h})
    scenes.append({"id": "end", "dur": end_dur(), "impact": impact})
    return {"name": meta.get("repo") or "", "version": "#%d" % meta["number"] if meta.get("number") else "",
            "kind": "pr", "title": title, "author": meta.get("author") or "", "url": meta.get("url") or "",
            "refs": body.get("refs") or [], "scenes": scenes, "aspect": aspect, "budget": max_seconds,
            "additions": adds, "deletions": dels, "files": n_files,
            "shown": len(sentences), "total": total_lines, "more": more, "hunks": len(hunks)}


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

CSS = rv.CSS + r"""
  .scene { --s-title: 10.5cqh; --s-line: 7.6cqh; --s-code: 4.8cqh; --s-tree: 5.4cqh; --s-impact: 6cqh;
           --s-label: 3.2cqh; --s-ref: 3.8cqh; --s-url: 4.4cqh; --s-thanks: 4cqh; --s-ver: 6.8cqh; --s-head: 9cqh; }
  .hook .title { font: 700 var(--s-title)/1.04 var(--font-display); letter-spacing: -0.03em; color: var(--fg); margin: 0;
                 max-width: 22em; overflow-wrap: anywhere; }
  .hook .title code { font: 600 0.88em/1 var(--font-mono); color: var(--accent); }
  .lines { gap: 3.6cqh; }
  .lines .item { padding-left: 4.2cqh; }
  .lines .item::before { width: 0.8cqh; }
  .lines .item .t { font-size: var(--s-line); line-height: 1.22; font-weight: 500; letter-spacing: -0.01em;
                    max-width: 24em; }
  .lines .more { font-size: var(--s-ref); margin-left: 4.2cqh; }
  .lines .item, .lines .more { animation-duration: 0.35s; }
  .end > * { animation-duration: 0.45s; animation-delay: calc(0.1s + var(--i, 0) * 0.1s); }

  /* files: a small tree with +/- counts */
  .files .head { font-size: calc(var(--s-head) * 0.8); }
  .files .head em { font-family: var(--font-mono); font-size: 0.72em; letter-spacing: 0; margin-left: 0.4em; }
  .tree { list-style: none; margin: 0.4cqh 0 0; padding: 0; display: flex; flex-direction: column; gap: 1cqh;
          font: 500 var(--s-tree)/1.2 var(--font-mono); }
  .tree li { display: flex; align-items: baseline; gap: 0.8em; opacity: 0;
             animation: rise 0.35s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .tree .dir { color: var(--muted); }
  .tree .f.nested { padding-left: 1.4em; }
  .tree .n { color: var(--fg); white-space: nowrap; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .tree .tag { font-size: var(--s-label); letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent);
               border: max(1px, 0.12cqh) solid color-mix(in oklab, var(--accent) 60%, transparent); border-radius: 0.5em;
               padding: 0.1em 0.5em; }
  .tree .c { margin-left: auto; white-space: nowrap; display: flex; gap: 0.6em; }
  .tree .bar { display: inline-flex; width: 5em; height: 0.5em; align-self: center; }
  .tree .bar i { display: block; height: 100%; transform-origin: left; animation: growx 0.7s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .a { color: #6fdc8c; } .d { color: #ff8a80; }
  .tree .bar .a { background: #6fdc8c; } .tree .bar .d { background: #ff8a80; }
  @keyframes growx { from { transform: scaleX(0); } to { transform: scaleX(1); } }
  .tests { font: 500 max(var(--s-ref), calc(var(--s-tree) * 0.82))/1.3 var(--font-mono); color: var(--muted); margin: 1.2cqh 0 0;
           animation: rise 0.35s ease var(--at) both; }
  .tests b { color: var(--accent); font-weight: 500; }

  /* one hunk, readable on a phone */
  .diffs { position: absolute; left: 7cqw; right: 7cqw; top: 50%; translate: 0 -50%; display: flex;
           flex-direction: column; gap: 1.6cqh; }
  .diffs .path { font: 500 var(--s-ref)/1.3 var(--font-mono); color: var(--muted); margin: 0; overflow-wrap: anywhere; }
  .diffs .path b { color: var(--fg); font-weight: 600; }
  .diffs .ctx { font: 500 var(--s-ref)/1.3 var(--font-mono); color: var(--muted); margin: 0; opacity: 0.85; }
  .code { background: var(--surface); border-radius: 0.4em; padding: 0.6em 0.7em; margin: 0.4cqh 0 0;
          box-shadow: 0 0 0 max(1px, 0.12cqh) var(--line); font: 450 var(--s-code)/1.42 var(--font-mono); }
  .ln { position: relative; padding: 0 0.6em 0 1.6em; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--muted);
        border-radius: 0.3em; opacity: 0; animation: rise 0.35s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .ln::before { content: attr(data-s); position: absolute; left: 0.4em; top: 0; }
  .ln.add { color: var(--fg); background: color-mix(in oklab, #2ea043 22%, transparent); }
  .ln.add::before { color: #6fdc8c; }
  .ln.del { color: color-mix(in oklab, var(--fg) 80%, transparent); background: color-mix(in oklab, #f85149 18%, transparent); }
  .ln.del::before { color: #ff8a80; }
  .diffs .more { margin-left: 0; }

  .end .impact-label { margin: 0; }
  .end .impact { font: 500 var(--s-impact)/1.3 var(--font-display); color: var(--fg); margin: 0; max-width: 100%; }
  span.nw { white-space: nowrap; }
  .end .refs { font: 500 var(--s-thanks)/1.3 var(--font-mono); color: var(--muted); margin: 0; }

  @container (max-aspect-ratio: 5/4) {
    .scene { --s-title: 8.6cqw; --s-line: 6cqw; --s-code: 4.2cqw; --s-tree: 4.6cqw; --s-impact: 5.4cqw;
             --s-label: 3.2cqw; --s-ref: 3.8cqw; --s-url: 4cqw; --s-thanks: 3.8cqw; --s-ver: 6cqw; --s-head: 8cqw; }
    .lines .item { padding-left: 3.6cqw; }
    .diffs { left: 6cqw; right: 6cqw; }
    .tree .bar { display: none; }
  }
  @container (max-aspect-ratio: 3/4) {
    .scene { --s-title: 10cqw; --s-line: 7.4cqw; --s-code: 4.6cqw; --s-tree: 4.6cqw; --s-impact: 5.2cqw;
             --s-label: 4.2cqw; --s-ref: 4.6cqw; --s-url: 4.6cqw; --s-thanks: 4.6cqw; --s-ver: 7cqw; --s-head: 9cqw; }
    .lines .item { padding-left: 4cqw; }
    .lines .more { margin-left: 4cqw; }
    .diffs { left: 11cqw; right: 11cqw; top: 48%; }
    .files { left: 9cqw; right: 18cqw; top: 47%; }
    .tree .tag { display: none; }
    .tree .f.nested { padding-left: 1em; }
  }
"""


def _inline(s: str) -> str:
    """rv._inline, plus: command-line flags outside code spans (--max-mb) never break at their hyphens."""
    parts = re.split(r"(<code[^>]*>.*?</code>)", rv._inline(s))
    return "".join(x if x.startswith("<code") else
                   re.sub(r"(?<![\w&;-])(--?[A-Za-z][\w-]*)", r'<span class="nw">\1</span>', x) for x in parts)


def _path_html(path: str) -> str:
    d, _, name = (path or "").rpartition("/")
    return "%s<b>%s</b>" % (rv._e(d + "/") if d else "", rv._e(name))


def build_page(p: Dict[str, Any]) -> str:
    name, ver = p["name"], p["version"]
    meta_line = " \u00b7 ".join(x for x in (ver, "@" + p["author"] if p["author"] else "") if x)
    tag = " \u00b7 ".join(x for x in (name, ver) if x)
    wide = p.get("aspect", "16:9") == "16:9"
    out: List[str] = []
    prev = ""
    for sc in p["scenes"]:
        start = "0" if not prev else "#" + prev
        trans = "" if not prev else ' data-transition="dip %.1f"' % (2 * OUT)
        push = [{"at": 0, "zoom": 1}, {"at": 0.15, "dur": round(max(1.0, sc["dur"] - 0.3), 2), "zoom": 1.06,
                                       "focus": [50, 50] if sc["id"] in ("hook", "end") or not wide else [30, 50],
                                       "to": "stay", "ease": "linear"}]
        out.append('  <section class="scene" id="%s" data-start="%s" data-dur="%.2f"%s>\n    <div class="cam" '
                   'data-st="camera" data-path=\'%s\'>' % (sc["id"], start, sc["dur"], trans, json.dumps(push)))
        sid = sc["id"]
        if sid == "hook":
            out.append('      <div class="hook">\n        <p class="label">Pull request%s</p>\n'
                       '        <h1 class="title">%s</h1>' % (" <b>&middot;</b> " + rv._e(name) if name else "",
                                                             _inline(p["title"])))
            if meta_line:
                out.append('        <p class="ver">%s</p>' % rv._e(meta_line))
            out.append("      </div>")
        elif sid.startswith("sum"):
            out.append('      <div class="list lines">\n        <p class="label">%s</p>\n        <ul class="items">\n'
                       '          <li class="item" style="--at:%.2fs"><p class="t">%s</p></li>\n        </ul>'
                       % (rv._e(tag or "Pull request"), LEAD, _inline(sc["text"])))
            if sc.get("more"):
                out.append('        <p class="more" style="--at:%.2fs">+ %d more in the description</p>'
                           % (LEAD, sc["more"]))
            out.append("      </div>")
        elif sid == "files":
            n = p["files"]
            out.append('      <div class="list files">\n        <p class="label">%s</p>\n'
                       '        <h2 class="head">%d file%s changed<em><span class="a">+%d</span> <span class="d">'
                       '\u2212%d</span></em></h2>\n        <ul class="tree">'
                       % (rv._e(tag or "Pull request"), n, "" if n == 1 else "s", p["additions"], p["deletions"]))
            biggest = max([r["additions"] + r["deletions"] for r in sc["rows"] if "name" in r] or [1]) or 1
            at = LEAD
            for r in sc["rows"]:
                if "dir" in r:
                    out.append('          <li class="dir" style="--at:%.2fs">%s</li>' % (at, rv._e(r["dir"])))
                else:
                    wa = 100.0 * r["additions"] / biggest
                    wd = 100.0 * r["deletions"] / biggest
                    out.append('          <li class="f%s" style="--at:%.2fs"><span class="n">%s</span>%s'
                               '<span class="c"><span class="a">+%d</span><span class="d">\u2212%d</span>'
                               '<span class="bar"><i class="a" style="width:%.1f%%"></i><i class="d" style="width:%.1f%%">'
                               '</i></span></span></li>'
                               % (" nested" if r["nested"] else "", at, rv._e(r["name"]),
                                  ' <span class="tag">test</span>' if r["test"] else "", r["additions"],
                                  r["deletions"], wa, wd))
                at += 0.1
            out.append("        </ul>")
            if sc["files_more"]:
                out.append('        <p class="more" style="--at:%.2fs">+ %d more file%s</p>'
                           % (at, sc["files_more"], "" if sc["files_more"] == 1 else "s"))
            if sc["tests"]:
                shown = sc["tests"][:3]
                rest = len(sc["tests"]) - len(shown)
                out.append('        <p class="tests" style="--at:%.2fs"><b>Tests</b> %s%s</p>' % (
                    at + 0.1, rv._e(", ".join(shown)), " + %d more" % rest if rest else ""))
            out.append("      </div>")
        elif sid.startswith("diff"):
            h = sc["hunk"]
            out.append('      <div class="diffs">\n        <p class="path">%s</p>' % _path_html(h["path"]))
            if h.get("context"):
                out.append('        <p class="ctx">%s</p>' % rv._e(h["context"]))
            out.append('        <div class="code">')
            at = LEAD
            for t, x in h["lines"]:
                cls = {"+": " add", "-": " del"}.get(t, "")
                sign = {"+": "+", "-": "\u2212"}.get(t, "")
                out.append('          <div class="ln%s" data-s="%s" style="--at:%.2fs">%s</div>'
                           % (cls, sign, at, rv._e(x) or "&#8203;"))
                at += 0.05
            out.append("        </div>")
            if h.get("hidden"):
                out.append('        <p class="more" style="--at:%.2fs">+ %d more changed line%s</p>'
                           % (at, h["hidden"], "" if h["hidden"] == 1 else "s"))
            out.append("      </div>")
        else:
            out.append('      <div class="end">')
            i = 0
            imp = sc.get("impact")
            if imp:
                out.append('        <p class="label impact-label" style="--i:%d">%s</p>' % (i, rv._e(imp["title"])))
                i += 1
                for line in imp["lines"]:
                    out.append('        <p class="impact" style="--i:%d">%s</p>' % (i, _inline(line)))
                    i += 1
            if name or ver:
                out.append('        <h2 class="name" style="--i:%d">%s%s</h2>' % (
                    i, rv._inline(name), "<em>%s</em>" % rv._e(ver) if ver else ""))
                i += 1
            if p["url"]:
                out.append('        <p class="url" data-st="fit" style="--i:%d">%s</p>'
                           % (i, rv._e(re.sub(r"^https?://", "", p["url"]))))
                i += 1
            if p["refs"]:
                out.append('        <p class="refs" style="--i:%d">%s</p>' % (i, rv._e(" \u00b7 ".join(p["refs"][:2]))))
                i += 1
            if p["author"]:
                out.append('        <p class="thanks" style="--i:%d">Thanks to @%s</p>' % (i, rv._e(p["author"])))
            out.append("      </div>")
        out.append("    </div>\n  </section>")
        prev = sid
    title = " ".join(x for x in (name, ver) if x) or p["title"]
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>%s</title>\n"
            "<script src=\"/_st/stage.js\"></script>\n<link rel=\"stylesheet\" href=\"/_st/themes/neutral.css\">\n"
            "<script type=\"module\" src=\"/_st/components/index.js\"></script>\n<!-- Written by `showtime pr-video` "
            "from a pull request: every line on screen is from its title, description or diff, or from a flag; "
            "secret-looking values are masked. Edit freely; `showtime retime . -d <s>` changes the length. -->\n"
            "<style>%s</style>\n</head>\n<body>\n"
            "<div class=\"stage\">\n  <div class=\"world\" data-st-decor><div class=\"key\"></div><div class=\"vig\">"
            "</div></div>\n%s\n</div>\n</body>\n</html>\n"
            % (rv._e(title), CSS, "\n".join(out)))


def write_project(out: Path, p: Dict[str, Any], meta: Dict[str, Any], *, masked: Sequence[Dict[str, Any]] = (),
                  notes: Sequence[str] = (), fps: int = 30, force: bool = False) -> Dict[str, Any]:
    """index.html, showtime.json, audio/mix.json and pr.json (what the video was made from, secrets masked)."""
    title = " ".join(x for x in (p["name"], p["version"]) if x) or p["title"]
    cfg = rv.project_config(p, title=title, aspect=p.get("aspect", "16:9"), fps=fps)
    cfg["expect"]["must_show"] = [p["name"] or p["title"]]
    # flat text and code: CRF 22 looks the same as the default 16 at a third of the size, so the GitHub copy is a
    # quality encode well under 10 MB instead of a file padded to the cap
    cfg["render"] = {"crf": 22}
    mix = rv.build_mix(p)
    mix["_comment"] = ("Generated by showtime pr-video: a composed bed on the scene starts and a soft swoosh on each "
                       "cut; everything is made on this machine.")
    src = {"generator": "showtime pr-video",
           "pr": {k: v for k, v in meta.items() if k != "files"},
           "plan": {k: v for k, v in p.items() if k != "scenes"},
           "scenes": [{k: v for k, v in s.items()} for s in p["scenes"]],
           "masked": list(masked), "notes": list(notes)}
    rv.write_files(out, page=build_page(p), cfg=cfg, mix=mix, source_name="pr.json", source=src, force=force)
    return {"project": str(out), "duration": cfg["duration"], "scenes": len(p["scenes"]), "title": title,
            "shown": p["shown"], "total": p["total"], "more": p["more"], "hunks": p["hunks"]}


GITHUB_MAX_MB = 10.0


def deliver_github(video: Path, out_dir: Path, export: Any = None) -> Dict[str, Any]:
    """`showtime deliver exports <video> --targets github`: a copy under GitHub's 10 MB attachment limit, as
    <stem>.github.mp4 in `out_dir`. `export` stands in for deliver.exports.export (tests)."""
    if export is None:
        from .deliver.exports import export
    rep = export(str(video), "github", str(out_dir))
    r = rep["exports"][0]
    size = int(r.get("size_bytes") or Path(r["output"]).stat().st_size)
    if size >= GITHUB_MAX_MB * 1e6:
        raise ShowtimeError("the GitHub copy is %.1f MB, over the %g MB attachment limit" % (size / 1e6, GITHUB_MAX_MB),
                            hint="shorten the video (--max-items 2), or export a smaller size: showtime deliver "
                                 "exports %s --targets github --max-mb 9" % video)
    return {"output": str(r["output"]), "size_bytes": size, "size_mb": round(size / 1e6, 2),
            "width": r.get("width"), "height": r.get("height"), "duration": r.get("duration")}


def remove_work(video: Path) -> Optional[Path]:
    """Delete the render's <stem>.work folder beside the video (audio stems, the intermediate video) once the
    export is done; only a folder the render wrote (it holds render.json). Returns the folder removed."""
    import shutil
    work = Path(video).with_name(Path(video).stem + ".work")
    if work.is_dir() and (work / "render.json").is_file():
        shutil.rmtree(str(work), ignore_errors=True)
        return work
    return None


def markdown_line(video_name: str, seconds: float, size_mb: Optional[float] = None) -> str:
    """Two lines for the PR description: a heading, and where to drop the file (GitHub replaces the comment)."""
    size = " (%.1f MB)" % size_mb if size_mb else ""
    return ("### What this pull request changes, in %d s\n<!-- drag %s%s onto this line: GitHub uploads it and "
            "puts the video player here -->" % (int(round(seconds)), video_name, size))
