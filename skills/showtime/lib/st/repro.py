"""A failing browser test -> a short narrated video for a bug report or a pull request (`showtime repro`).

Reads a Playwright trace (the trace.zip `npx playwright test --trace on` or `pytest --tracing on` writes) and
writes a project in the release-video look: a title card (test name, file:line, FAILED), each action on the
screenshot the trace holds for it (a cursor and a click ripple at the action's target box, a step counter, a
one-line caption), the failing step slowed down (the assertion's source line, expected and received side by
side, the error, console errors) and an end card with the command that re-runs it. Long tests keep their first
step and the steps just before the failure; the passing steps in between become one "+ N passing steps" scene.

Privacy: values typed into password fields, or fields whose name, label, id, placeholder or autocomplete says
password, secret, token, key or OTP, are masked; URLs lose their query string and fragment; home folders show
as ~; secret-looking strings (the pr-video masks) and every `--redact` pattern are masked in every text the
film, the captions, steps.json and repro.md show. Network requests, headers, cookies and bodies are never read.
Screenshots are shown as they were captured.

Stdlib only (the voice, the render and qa are separate steps the CLI runs after writing the project).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import bed
from . import pr_video as pv
from . import release_video as rv
from .common import ShowtimeError

MASK = pv.MASK
MIN_SECONDS, MAX_SECONDS = 10.0, 40.0      # the title, the failure and the end card alone hold more than 10 s
LEAD, ENTER, OUT = pv.LEAD, pv.ENTER, pv.OUT
VOICE_PAD = 0.3              # picture before a scene's narration starts (retime --from-voice's default)
VOICE_TAIL = 0.4             # picture after it ends

# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------

# a field is secret when its name, label, id, placeholder, test id or autocomplete says so
SENSITIVE = re.compile(r"passw|passcode|passphrase|secret|token|(?:^|[^a-z])otp|one.?time|api.?key|private.?key|"
                       r"(?:^|[^a-z])keys?(?:$|[^a-z])", re.I)
SENSITIVE_CAMEL = re.compile(r"[a-z0-9](?:Key|Keys|Otp|OTP)(?![a-z])")
SECRET_AUTOCOMPLETE = ("current-password", "new-password", "one-time-code")
_URL = re.compile(r"\b(?:https?|wss?|file|ftp)://[^\s\"'<>`)\]]+")
# a bare path token (/login?next=...): matched whole, then cut at its first ? or # in Python (no backtracking)
_PATH_TOKEN = re.compile(r"(?<![\w:/])/[^\s\"'<>`)\]]*")
# a path on this machine (a home folder, a temp or system folder, a drive): shown as its last part only
_ABS_PATH = re.compile(r"(?<![\w.:/~\\-])(?:/(?:Users|home|root|private|var|tmp|opt|usr|Volumes|mnt|srv|etc|Library|"
                       r"System|nix|snap|builds|workspace)(?=/)|~(?=/)|[A-Za-z]:[\\/])[^\s\"'<>`|*?]*")
# secrets in free text (console lines, errors): auth headers, NAME=value / NAME: value, e-mail addresses
_AUTH = re.compile(r"(?i)\b(bearer|basic|token|bot)(\s+)([A-Za-z0-9._~+/=-]{12,})")
_KV = re.compile(r"(?i)(\b[\w-]{0,20}?(?:(?:access|refresh|id|auth|bearer|csrf|xsrf|session)[_-]?token|token|"
                 r"api[_ -]?key|apikey|secret|password|passwd|pwd|session(?:[_-]?id)?|sessid|sid|"
                 r"auth(?:orization)?|cookie|set-cookie|jwt|private[_-]?key)s?[\"']?\s*[=:]\s*[\"']?)"
                 r"([^\s&\"',;)\]}>]{3,})")
_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]{1,64}@([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,8})\b")
_USERINFO = re.compile(r"(?<![\w.%+-])[\w.%+-]{1,64}:[^\s@/:]{1,128}@(?=[\w-])")     # user:password@host
_TYPED_CALL = re.compile(r"\b(fill|type|pressSequentially|insertText)\((?:\"[^\"\n]{0,2000}\"|'[^'\n]{0,2000}')")
MAX_TEXT = 2000              # any text is cut to this before a pattern runs (more than any shown text)
MAX_WORD = 200               # a longer run without a space is cut before the shared secret masks run


def _bare(path: str) -> str:
    parts = [p for p in re.split(r"[\\/]", path) if p]
    return parts[-1] if parts else ""


def _drop_query(m: "re.Match[str]") -> str:
    t = m.group(0)
    cut = [i for i in (t.find("?"), t.find("#")) if i >= 0]
    return t[:min(cut)] if cut and re.fullmatch(r"(?:/[\w.~%@+-]*)+", t[:min(cut)]) else t


def is_sensitive(*texts: Optional[str]) -> bool:
    return any(t and (SENSITIVE.search(t) or SENSITIVE_CAMEL.search(t)) for t in texts)


def display_url(url: str) -> str:
    """What the film shows of a URL: no query string, no fragment, no credentials; a file URL shows its last two
    path parts (the rest is the machine's folders)."""
    u = (url or "").split("#", 1)[0].split("?", 1)[0]
    m = re.match(r"^([a-z][\w+.-]*)://(.*)$", u, re.I)
    if not m:
        return u
    scheme, rest = m.group(1).lower(), m.group(2)
    if scheme == "file":
        parts = [p for p in rest.split("/") if p]
        return "/".join(parts[-2:]) if parts else "file"
    rest = re.sub(r"^[^/@]*@", "", rest)                     # user:password@host
    return (rest if scheme in ("http", "https") else "%s://%s" % (scheme, rest)).rstrip("/") or rest


class Redactor:
    """The hard filter every shown or spoken text goes through: typed values (added as they are found), every
    --redact pattern, query strings and fragments of URLs, paths on the machine (shown as their last part),
    auth headers and NAME=value secrets, e-mail addresses (unless show_emails), and secret-looking strings."""

    def __init__(self, patterns: Sequence[str] = (), *, show_emails: bool = False) -> None:
        self.show_emails = show_emails
        self.patterns = []
        for p in patterns or ():
            try:
                self.patterns.append(re.compile(p))
            except re.error as e:
                raise ShowtimeError("--redact %r is not a valid regular expression: %s" % (p, e),
                                    hint="escape special characters, e.g. --redact 'acct-[0-9]+' or --redact 'a\\.b'")
        self.secrets: List[str] = []

    def add_secret(self, value: Optional[str]) -> None:
        v = (value or "").strip()
        if len(v) >= 3 and v not in self.secrets:
            self.secrets.append(v)
            self.secrets.sort(key=len, reverse=True)

    def __call__(self, text: Optional[str]) -> str:
        t = str(text or "")
        if len(t) > MAX_TEXT:
            t = t[:MAX_TEXT] + "\u2026"
        for s in self.secrets:
            t = t.replace(s, MASK)
        for rx in self.patterns:
            t = rx.sub(MASK, t)
        t = _URL.sub(lambda m: display_url(m.group(0)) if m.group(0).lower().startswith("file:")
                     else re.sub(r"(?<=://)[^/@\s]*@", "", m.group(0).split("#", 1)[0].split("?", 1)[0]), t)
        t = _USERINFO.sub(MASK + "@", t)
        t = _PATH_TOKEN.sub(_drop_query, t)
        t = _ABS_PATH.sub(lambda m: _bare(m.group(0)), t)
        t = _TYPED_CALL.sub(lambda m: '%s("%s"' % (m.group(1), MASK), t)
        t = _AUTH.sub(lambda m: m.group(1) + m.group(2) + MASK
                      if m.group(1).lower() != "token" or re.search(r"\d", m.group(3)) else m.group(0), t)
        t = _KV.sub(lambda m: m.group(1) + MASK, t)
        if not self.show_emails:
            t = _EMAIL.sub(lambda m: MASK + "@" + m.group(1), t)
        t = re.sub(r"\S{%d,}" % (MAX_WORD + 1), lambda m: m.group(0)[:MAX_WORD] + "\u2026", t)
        return "\n".join(pv.mask_line(x)[0] for x in t.split("\n"))


# ---------------------------------------------------------------------------
# reading a trace
# ---------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[([0-9;]*)m")


def strip_ansi(s: str) -> str:
    return _ANSI.sub("", s or "")


def ansi_segments(s: str) -> List[List[Any]]:
    """Text with ANSI codes -> [[text, marked]]: `marked` where Playwright shows a difference (inverse video)."""
    out: List[List[Any]] = []
    inv = False
    pos = 0
    for m in _ANSI.finditer(s or ""):
        if m.start() > pos:
            out.append([s[pos:m.start()], inv])
        codes = m.group(1).split(";")
        if "7" in codes:
            inv = True
        if "27" in codes or "0" in codes or codes == [""]:
            inv = False
        pos = m.end()
    if pos < len(s or ""):
        out.append([s[pos:], inv])
    merged: List[List[Any]] = []
    for t, f in out:
        if merged and merged[-1][1] == f:
            merged[-1][0] += t
        elif t:
            merged.append([t, f])
    return merged


MAX_MEMBERS = 20000                    # zip members in a trace
MAX_TOTAL = 1024 ** 3                  # uncompressed bytes of the event files
MAX_EVENTS = 500000                    # events kept
MAX_LINE = 4 * 1024 ** 2               # one event line kept whole; a longer one (a DOM snapshot) is skipped
MAX_ATTACHMENT = 1024 ** 2             # attachments read for the test's name and location
MAX_SOURCE = 2 * 1024 ** 2             # a source file the trace carries
MAX_SHOT = 20 * 1024 ** 2              # a screenshot
_SNAP_HEAD = re.compile(r'"(callId|frameUrl|frameId|phase|snapshotName)"\s*:\s*"((?:[^"\\]|\\.){0,4000})"')
MAX_DOM_ENTRIES = 1000000              # field summaries kept for the DOM snapshots (then the rest are unknown)


def _too_big(what: str) -> ShowtimeError:
    return ShowtimeError("the trace is too large to read safely (%s)" % what,
                         hint="film one test: run it alone with --trace on (pytest: --tracing on) and pass its trace.zip")


def _scroll(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _field_key(tag: str, attrs: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """A form field by its tag, id and name (None when it has neither: it cannot be followed)."""
    ce = attrs.get("contenteditable")
    if tag in ("INPUT", "TEXTAREA", "SELECT") or (ce is not None and str(ce).lower() != "false"):
        fid, name = str(attrs.get("id") or ""), str(attrs.get("name") or "")
        if fid or name:
            return (tag, fid, name)
    return None


def _join(a: Tuple[Any, Any, bool], b: Tuple[Any, Any, bool]) -> Tuple[Any, Any, bool]:
    """Two fields with the same key: their scroll only when it agrees, empty only when both are."""
    return (a[0] if a[0] == b[0] else None, a[1] if a[1] == b[1] else None, a[2] and b[2])


class DomIndex:
    """Which form fields each DOM snapshot holds, never what is in them: per field (tag, id, name), whether it
    is empty and how far the boxes around it are scrolled, and which field the call acted on. A snapshot keeps
    unchanged parts as references to nodes of an earlier snapshot of the same frame, so a summary is kept for
    every node with a field inside (only those). A snapshot that cannot be read (a line too long, a reference
    that cannot be followed, the cap reached) is unknown."""

    def __init__(self) -> None:
        self.frames: Dict[Tuple[str, str], List[Optional[Dict[int, Dict[Any, Any]]]]] = {}
        self.calls: Dict[str, List[Dict[str, Any]]] = {}
        self.entries = 0

    def add(self, member: str, snap: Dict[str, Any], readable: bool = True) -> None:
        frame = (member, str(snap.get("frameId") or ""))
        lst = self.frames.setdefault(frame, [])
        got = self._summary(snap.get("html"), lst) if readable and self.entries < MAX_DOM_ENTRIES else None
        lst.append(got[0] if got else None)
        if snap.get("callId"):
            phase = snap.get("phase") or str(snap.get("snapshotName") or "").split("@", 1)[0]
            self.calls.setdefault(str(snap["callId"]), []).append({
                "phase": phase, "frame": frame, "main": snap.get("isMainFrame", True) is not False,
                "fields": got[1] if got else None, "target": got[2] if got else None})

    def _summary(self, html: Any, lst: List[Optional[Dict[int, Dict[Any, Any]]]]) -> Optional[Tuple[Any, Any, Any]]:
        """(the summaries of its nodes by post-order index, the root's {field: (scroll top, scroll left,
        empty)}, the key of the element marked as the call's target), walked without recursion."""
        def ref_of(c: List[Any]) -> Optional[Dict[Any, Any]]:
            ref = c[0]
            if len(ref) < 2 or not all(isinstance(x, int) for x in ref[:2]) or ref[0] <= 0 or ref[0] > len(lst) \
                    or lst[len(lst) - ref[0]] is None:
                raise LookupError
            return lst[len(lst) - ref[0]].get(ref[1])
        if isinstance(html, list) and html and isinstance(html[0], list):          # the whole page unchanged
            try:
                return {}, ref_of(html) or {}, None
            except LookupError:
                return None
        if not isinstance(html, list) or not html or not isinstance(html[0], str):
            return None
        nodes: Dict[int, Dict[Any, Any]] = {}
        count, target, root = 0, None, None
        stack: List[List[Any]] = [[html, 2, None, False]]          # node, next child, fields below, owned

        def into(top: List[Any], m: Optional[Dict[Any, Any]]) -> None:
            if not m:
                return
            if top[2] is None:
                top[2], top[3] = m, False                          # shared until something changes it
                return
            if not top[3]:
                top[2], top[3] = dict(top[2]), True
            for k, v in m.items():
                top[2][k] = _join(top[2][k], v) if k in top[2] else v
        while stack:
            top = stack[-1]
            n = top[0]
            if top[1] < len(n):
                c = n[top[1]]
                top[1] += 1
                if isinstance(c, str):
                    count += 1
                elif isinstance(c, list) and c and isinstance(c[0], str):
                    stack.append([c, 2, None, False])
                elif isinstance(c, list) and c and isinstance(c[0], list):      # [[snapshots back, node index]]
                    try:
                        into(top, ref_of(c))
                    except LookupError:
                        return None
                continue
            stack.pop()
            tag = n[0].upper()
            attrs = n[1] if len(n) > 1 and isinstance(n[1], dict) else {}
            acc, owned = top[2], top[3]
            st, sl = _scroll(attrs.get("__playwright_scroll_top_")), _scroll(attrs.get("__playwright_scroll_left_"))
            if acc and (st or sl):
                acc = {k: (None if v[0] is None else v[0] + st, None if v[1] is None else v[1] + sl, v[2])
                       for k, v in acc.items()}
                owned = True
            key = _field_key(tag, attrs)
            if key:
                acc, owned = (dict(acc or {}), True) if not owned else (acc, owned)
                v = (0, 0, tag in ("INPUT", "TEXTAREA") and not attrs.get("__playwright_value_"))
                acc[key] = _join(acc[key], v) if key in acc else v
            if "__playwright_target__" in attrs:
                target = key or ("?", "", "")
            if acc:
                nodes[count] = acc
                if owned:
                    self.entries += len(acc)
            count += 1
            if stack:
                into(stack[-1], acc)
            else:
                root = acc or {}
        return nodes, root, target


def _jsonl(z: zipfile.ZipFile, name: str, stop: Optional[Any] = None,
           dom: Optional[DomIndex] = None) -> Iterable[Dict[str, Any]]:
    """The events of one .trace member, streamed: a line longer than MAX_LINE is not kept (a frame snapshot of
    a big page keeps only its callId and frameUrl), so memory stays bounded. A DOM snapshot is summed up into
    `dom` (which fields it holds), then dropped."""
    with z.open(name) as raw:
        f = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
        while True:
            line = f.readline(MAX_LINE)
            if not line:
                return
            if not line.endswith("\n") and len(line) >= MAX_LINE:
                head = line[:65536]
                while True:                                # the rest of the long line, not kept
                    more = f.readline(MAX_LINE)
                    if not more or more.endswith("\n"):
                        break
                if '"frame-snapshot"' in head[:200]:
                    got: Dict[str, str] = {}
                    for k, v in _SNAP_HEAD.findall(head):
                        got.setdefault(k, v)
                    if dom is not None:
                        dom.add(name, got, readable=False)
                    if got.get("callId"):
                        yield {"type": "frame-snapshot", "snapshot": {"callId": got["callId"],
                                                                      "frameUrl": got.get("frameUrl", "")}}
                continue
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if e.get("type") == "frame-snapshot":          # only what the parser uses: never the DOM
                snap = e.get("snapshot") or {}
                if dom is not None and isinstance(snap, dict):
                    dom.add(name, snap)
                e = {"type": "frame-snapshot", "snapshot": {k: snap.get(k) for k in ("callId", "frameUrl", "isMainFrame")}}
            yield e
            if stop is not None and stop(e):
                return


def _members(z: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS:
        raise _too_big("%d files inside, more than %d" % (len(infos), MAX_MEMBERS))
    total = sum(i.file_size for i in infos if i.filename.endswith((".trace", ".stacks")))
    if total > MAX_TOTAL:
        raise _too_big("%.1f GB of events" % (total / 1024 ** 3))
    return infos


def open_trace(path: Path) -> zipfile.ZipFile:
    path = Path(path)
    if not path.is_file():
        raise ShowtimeError("trace not found: %s" % path,
                            hint="pass the trace.zip a test run wrote (test-results/<test>/trace.zip), or a command: "
                                 "showtime repro -- npx playwright test")
    try:
        z = zipfile.ZipFile(str(path))
    except zipfile.BadZipFile:
        raise ShowtimeError("%s is not a zip file, so it is not a Playwright trace" % path.name,
                            hint="pass the trace.zip from test-results/ (written with --trace on, or pytest --tracing on)")
    if not any(n.endswith(".trace") for n in z.namelist()):
        z.close()
        raise ShowtimeError("%s holds no Playwright trace (no .trace file inside)" % path.name,
                            hint="pass the trace.zip from test-results/ (written with --trace on, or pytest --tracing on)")
    return z


def read_raw(z: zipfile.ZipFile) -> Dict[str, Any]:
    """The events of a trace: the test runner's (test.trace) and the library's (N-trace.trace), the stacks and
    the error-context attachment, and what the DOM snapshots say about the form fields (`dom`)."""
    infos = _members(z)
    names = [i.filename for i in infos]
    test: List[Dict[str, Any]] = []
    lib: List[Dict[str, Any]] = []
    stacks: Dict[int, Tuple[str, int]] = {}
    dom = DomIndex()
    for info in sorted(infos, key=lambda i: i.filename):
        n = info.filename
        base = n.rsplit("/", 1)[-1]
        if base.endswith(".trace"):
            into = test if base == "test.trace" else lib
            for e in _jsonl(z, n, dom=None if into is test else dom):
                into.append(e)
                if len(test) + len(lib) > MAX_EVENTS:            # counted as they are read
                    raise _too_big("more than %d events" % MAX_EVENTS)
        elif base.endswith(".stacks"):
            if info.file_size > 64 * 1024 ** 2:
                continue
            try:
                d = json.loads(z.read(n).decode("utf-8"))
                files = d.get("files") or []
                for cid, frames in d.get("stacks") or []:
                    if frames:
                        fi, line = frames[0][0], frames[0][1]
                        stacks[int(cid)] = (files[fi] if 0 <= fi < len(files) else "", int(line))
            except (ValueError, KeyError, IndexError, TypeError):
                pass
    context = ""
    for info in infos:                       # the error-context markdown: small text, its head is enough
        if info.filename.startswith("attachments/") and 0 < info.file_size <= MAX_ATTACHMENT:
            with z.open(info) as f:
                head = f.read(65536)
            if b"\x00" in head:
                continue
            text = head.decode("utf-8", "replace")
            if "# Test info" in text:
                context = text
                break
    return {"test": test, "lib": lib, "stacks": stacks, "context": context, "names": names,
            "sizes": {i.filename: i.file_size for i in infos}, "dom": dom}


def _attrs(tag: str) -> Dict[str, str]:
    return {k.lower(): v for k, v in re.findall(r"([\w:-]+)=\"([^\"]*)\"", tag or "")}


def _num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


_ROLE_NOUN = {"textbox": "field", "searchbox": "search field", "combobox": "dropdown", "img": "image",
              "menuitem": "menu item", "spinbutton": "number field", "listbox": "list", "gridcell": "cell",
              "columnheader": "column header", "rowheader": "row header"}


def human_locator(api: str) -> str:
    """`getByRole('button', { name: 'Sign in' })` -> "the 'Sign in' button" (the last link of a chain)."""
    s = (api or "").strip()
    s = re.sub(r"\.(first|last)\(\)$|\.nth\(\d+\)$", "", s)
    parts = re.findall(r"(?:^|\.)((?:getBy\w+|locator|frameLocator)\((?:[^()]|\([^()]*\))*\))", s)
    last = parts[-1] if parts else s
    m = re.match(r"(getBy\w+|locator|frameLocator)\((.*)\)$", last, re.S)
    if not m:
        return rv.shorten(s, 60) if s else ""
    fn, args = m.group(1), m.group(2)
    strs = re.findall(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|/((?:[^/\\]|\\.)+)/[a-z]*", args)
    first = next((a or b or c for a, b, c in strs), "") if strs else ""
    if fn == "getByRole":
        noun = _ROLE_NOUN.get(first, first or "element")
        name = re.search(r"name:\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|/((?:[^/\\]|\\.)+)/)", args)
        level = re.search(r"level:\s*(\d)", args)
        if name:
            return "the '%s' %s" % (name.group(1) or name.group(2) or name.group(3), noun)
        if level:
            return "the level-%s %s" % (level.group(1), noun)
        return "the %s" % noun
    if fn in ("getByLabel", "getByPlaceholder"):
        return "the '%s' field" % first
    if fn == "getByText":
        return "the text '%s'" % first
    if fn == "getByAltText":
        return "the '%s' image" % first
    if fn == "getByTitle":
        return "'%s'" % first
    if fn == "getByTestId":
        return "test id '%s'" % first
    return first or last


def _selector_api(sel: str) -> str:
    """A library selector (internal:role=button[name="Sign in"i]) -> the locator API form, for traces without
    the runner's step titles."""
    s = sel or ""
    m = re.match(r'^internal:role=(\w+)(.*)$', s)
    if m:
        name = re.search(r'\[name="((?:[^"\\]|\\.)*)"[is]?\]', m.group(2))
        level = re.search(r"\[level=(\d)\]", m.group(2))
        opts = ("{ name: '%s' }" % name.group(1)) if name else ("{ level: %s }" % level.group(1)) if level else ""
        return "getByRole('%s'%s)" % (m.group(1), ", " + opts if opts else "")
    for prefix, fn in (("label=", "getByLabel"), ("text=", "getByText"), (r"attr=\[placeholder=", "getByPlaceholder"),
                       (r"attr=\[alt=", "getByAltText"), (r"attr=\[title=", "getByTitle")):
        m = re.match(r'^internal:%s"((?:[^"\\]|\\.)*)"' % prefix, s)
        if m:
            return "%s('%s')" % (fn, m.group(1))
    m = re.match(r'^internal:testid=\[[\w-]+="((?:[^"\\]|\\.)*)"', s)
    if m:
        return "getByTestId('%s')" % m.group(1)
    return "locator('%s')" % s if s else ""


_METHOD_KIND = {"goto": "goto", "reload": "reload", "goBack": "back", "goForward": "forward", "click": "click",
                "dblclick": "dblclick", "tap": "click", "fill": "fill", "clear": "fill", "press": "press",
                "type": "type", "pressSequentially": "type", "check": "check", "uncheck": "uncheck",
                "setChecked": "check", "selectOption": "select", "hover": "hover", "setInputFiles": "upload",
                "expect": "expect", "waitForSelector": "wait", "waitForURL": "wait", "waitForLoadState": "wait",
                "waitForTimeout": "wait", "waitForFunction": "wait", "focus": "focus", "dragTo": "drag",
                "screenshot": "screenshot", "keyboardType": "type", "keyboardInsertText": "type", "insertText": "type",
                "keyboardPress": "press", "keyboardDown": "press", "keyboardUp": "press"}
_TITLE_KIND = [(r"^Navigate|^Go to|^Goto", "goto"), (r"^Reload", "reload"), (r"^Double click", "dblclick"),
               (r"^Click|^Tap", "click"), (r"^Fill|^Clear", "fill"), (r"^Press sequentially|^Type|^Insert", "type"),
               (r"^Press", "press"), (r"^Uncheck", "uncheck"), (r"^Check|^Set checked", "check"),
               (r"^Select", "select"), (r"^Hover", "hover"), (r"^Set input files|^Upload", "upload"),
               (r"^Expect|^expect", "expect"), (r"^Wait", "wait"), (r"^Focus", "focus"), (r"^Drag", "drag")]
POINTER_KINDS = ("click", "dblclick", "hover", "check", "uncheck", "drag")
VALUE_KINDS = ("fill", "type", "press", "select", "upload")
TYPED_KINDS = ("fill", "type")         # what was typed is never shown or spoken (only how many characters)
_KEY_NAME = re.compile(r"(?:(?:Control|Shift|Alt|Meta|ControlOrMeta)\+)*(?:[A-Z][A-Za-z0-9]+|F\d{1,2})")
_STAYS = re.compile(r"(?:Shift\+)?(?:.|Backspace|Delete|ArrowLeft|ArrowRight|Home|End|Space)", re.S)  # keeps focus
MAX_CONSOLE = 20                       # console lines kept (each cut to 300 characters)
SKIP_LIB = {"waitForEventInfo", "setDefaultTimeoutNoReply", "setDefaultNavigationTimeoutNoReply", "close",
            "newPage", "newContext", "tracingStart", "tracingStop", "tracingStartChunk", "tracingStopChunk",
            "addInitScript", "exposeBinding", "setExtraHTTPHeaders", "route", "unroute", "storageState",
            "cookies", "addCookies", "grantPermissions", "harStart", "harExport"}


def _kind(method: str, title: str) -> str:
    if method in _METHOD_KIND:
        return _METHOD_KIND[method]
    for rx, k in _TITLE_KIND:
        if re.search(rx, title or ""):
            return k
    return "action"


def _words(matcher: str) -> str:
    """toHaveText -> 'to have text'; not.toBeVisible -> 'not to be visible'."""
    m = (matcher or "").replace("expect.", "")
    neg = m.startswith("not.")
    m = m[4:] if neg else m
    w = re.sub(r"(?<!^)([A-Z])", r" \1", m).lower().strip()
    w = w.replace("u r l", "URL")
    return ("not " if neg else "") + w


def _expected_of(params: Dict[str, Any], lib_params: Dict[str, Any]) -> Optional[str]:
    if params.get("expected") is not None:
        e = params["expected"]
        return e if isinstance(e, str) else json.dumps(e)
    et = lib_params.get("expectedText")
    if isinstance(et, list) and et:
        x = et[0]
        if x.get("string") is not None:
            return x["string"]
        if x.get("regexSource") is not None:
            return "/%s/%s" % (x["regexSource"], x.get("regexFlags") or "")
    if lib_params.get("expectedNumber") is not None:
        return str(lib_params["expectedNumber"])
    return None


def parse(path: Path, redact: Optional[Redactor] = None, *, label: str = "", show_typed: bool = False) -> Dict[str, Any]:
    """trace.zip -> {test, steps, failure, console, viewport, ...}, every shown text redacted. Screenshots are
    named by their zip member (`shot`); keep_shots copies them out. Typed values are never shown (`show_typed`:
    the values typed into fields that are not secret are, filtered); their fields are covered on screen."""
    redact = redact or Redactor()
    z = open_trace(path)
    try:
        raw = read_raw(z)
        srcs = {n.rsplit("/", 1)[-1].split(".", 1)[0]: n for n in raw["names"]
                if n.startswith("src/") and raw["sizes"].get(n, 0) <= MAX_SOURCE}
        src_text = {}
        for h, n in list(srcs.items())[:200]:
            try:
                src_text[h] = z.read(n).decode("utf-8", "replace").splitlines()
            except KeyError:
                pass
    finally:
        z.close()
    lib_ctx = [e for e in raw["lib"] if e.get("type") == "context-options"]
    test_ctx = next((e for e in raw["test"] if e.get("type") == "context-options"), None)
    browser = next((e.get("browserName") for e in lib_ctx if e.get("browserName")), "") or ""
    version = next((e.get("playwrightVersion") for e in lib_ctx + ([test_ctx] if test_ctx else [])
                    if e.get("playwrightVersion")), "")
    sdk = next((e.get("sdkLanguage") for e in lib_ctx + ([test_ctx] if test_ctx else []) if e.get("sdkLanguage")), "")
    viewport = next(((e.get("options") or {}).get("viewport") for e in lib_ctx
                     if (e.get("options") or {}).get("viewport")), None)
    ctx_title = next((e.get("title") for e in lib_ctx if e.get("title")), "")
    wall = next((e.get("wallTime") for e in ([test_ctx] if test_ctx else []) + lib_ctx if e.get("wallTime")), None)

    # the library's calls: params, logs, the input box and point, errors
    calls: Dict[str, Dict[str, Any]] = {}
    frames: List[Dict[str, Any]] = []
    console: List[Dict[str, Any]] = []
    page_url: Dict[str, str] = {}                 # callId -> the main frame's URL in its last DOM snapshot
    for e in raw["lib"]:
        t = e.get("type")
        if t == "frame-snapshot":
            snap = e.get("snapshot") or {}
            if snap.get("callId") and snap.get("isMainFrame", True) and snap.get("frameUrl"):
                page_url[snap["callId"]] = snap["frameUrl"]
        elif t == "before":
            calls[e["callId"]] = {"id": e["callId"], "class": e.get("class", ""), "method": e.get("method", ""),
                                  "params": e.get("params") or {}, "start": _num(e.get("startTime")),
                                  "end": None, "step": e.get("stepId"), "title": e.get("title") or "",
                                  "logs": [], "box": None, "point": None, "error": None, "page": e.get("pageId")}
        elif t == "after" and e.get("callId") in calls:
            c = calls[e["callId"]]
            c["end"] = _num(e.get("endTime"), c["start"])
            if e.get("error"):
                c["error"] = e["error"]
        elif t == "input" and e.get("callId") in calls:
            calls[e["callId"]]["box"] = e.get("box") or calls[e["callId"]]["box"]
            calls[e["callId"]]["point"] = e.get("point") or calls[e["callId"]]["point"]
        elif t == "log" and e.get("callId") in calls:
            calls[e["callId"]]["logs"].append(str(e.get("message") or ""))
        elif t == "screencast-frame" and e.get("file"):
            frames.append({"t": _num(e.get("timestamp")), "file": e["file"], "page": e.get("pageId"),
                           "w": e.get("width"), "h": e.get("height")})
        elif t == "console" and e.get("messageType") == "error":
            console.append({"t": _num(e.get("time")), "text": str(e.get("text") or "")})
        elif t == "event" and e.get("method") == "pageError":
            err = (e.get("params") or {}).get("error") or {}
            err = err.get("error", err) if isinstance(err, dict) else {}
            msg = err.get("message") or (err.get("value") if isinstance(err.get("value"), str) else "") or "page error"
            console.append({"t": _num(e.get("time")), "text": "Uncaught " + str(msg)})
    frames.sort(key=lambda f: f["t"])
    if not viewport and frames:
        viewport = {"width": frames[0]["w"] or 1280, "height": frames[0]["h"] or 720}
    viewport = viewport or {"width": 1280, "height": 720}
    by_step: Dict[str, Dict[str, Any]] = {}
    for c in sorted(calls.values(), key=lambda c: c["start"]):
        if c["step"] and c["step"] not in by_step:
            by_step[c["step"]] = c

    # the steps: the runner's (titles, locators, stacks) when the trace has them, else the library's calls
    steps: List[Dict[str, Any]] = []
    test_error = None
    if raw["test"]:
        before = {e["stepId"]: e for e in raw["test"] if e.get("type") == "before" and e.get("stepId")}
        after = {e["callId"]: e for e in raw["test"] if e.get("type") == "after" and e.get("callId")}
        test_error = next((e for e in raw["test"] if e.get("type") == "error"), None)

        def hidden(e: Dict[str, Any]) -> bool:
            seen = 0
            p = e.get("parentId")
            while p and seen < 50:
                pe = before.get(p)
                if pe is None:
                    break
                if pe.get("method") in ("hook", "fixture", "pw:api", "expect"):
                    return True
                p = pe.get("parentId")
                seen += 1
            return False
        for e in sorted(before.values(), key=lambda e: _num(e.get("startTime"))):
            if e.get("method") not in ("pw:api", "expect") or hidden(e):
                continue
            a = after.get(e["stepId"], {})
            c = by_step.get(e["stepId"]) or {}
            st = (e.get("stack") or [{}])[0]
            steps.append({"title": e.get("title") or "", "api": e.get("subtitle") or (e.get("params") or {}).get("locator") or "",
                          "params": e.get("params") or {}, "lib": c, "method": c.get("method", ""),
                          "start": _num(c.get("start"), _num(e.get("startTime"))),
                          "end": _num(c.get("end"), _num(a.get("endTime"), _num(e.get("startTime")))),
                          "file": st.get("file") or "", "line": st.get("line"),
                          "error": a.get("error") or None})
    else:
        for c in sorted(calls.values(), key=lambda c: c["start"]):
            if c["class"] not in ("Frame", "Page", "ElementHandle", "Locator") or c["method"] in SKIP_LIB:
                continue
            cid = int(re.sub(r"\D", "", c["id"]) or 0)
            f, line = raw["stacks"].get(cid, ("", None))
            api = next((m[len("waiting for "):] for m in c["logs"] if m.startswith("waiting for ")), "") \
                or _selector_api(c["params"].get("selector", ""))
            steps.append({"title": c["title"], "api": api, "params": {}, "lib": c, "method": c["method"],
                          "start": c["start"], "end": c["end"] if c["end"] is not None else c["start"],
                          "file": f, "line": line, "error": c["error"]})
    if not steps:
        raise ShowtimeError("the trace has no test steps to show",
                            why="no page action or assertion was recorded (the test may have failed before it "
                                "opened a page)",
                            hint="check that the run used --trace on (pytest: --tracing on) and that the test opens "
                                 "a page; the trace viewer shows what it holds: npx playwright show-trace <trace.zip>")

    # test name and location
    name, loc_file, loc_line = "", "", None
    m = re.search(r"^- Name:\s*(.+)$", raw["context"], re.M)
    if m:
        name = m.group(1).split(" >> ", 1)[-1].strip().replace(" >> ", " \u203a ")
    m = re.search(r"^- Location:\s*(.+?):(\d+)(?::\d+)?\s*$", raw["context"], re.M)
    if m:
        loc_file, loc_line = m.group(1).strip(), int(m.group(2))
    if ctx_title and (not name or not loc_file):
        parts = [p.strip() for p in ctx_title.split("\u203a")]
        fm = re.match(r"^(.+?):(\d+)$", parts[0])
        if fm and len(parts) > 1:
            loc_file, loc_line = loc_file or fm.group(1), loc_line or int(fm.group(2))
            name = name or " \u203a ".join(parts[1:])
        else:
            name = name or ctx_title
    first_file = next((s["file"] for s in steps if s["file"]), "")
    if not loc_file and first_file:
        loc_file = os.path.basename(first_file)
    name = name or label or "Playwright test"

    def rel(f: str) -> str:
        if not f:
            return ""
        fs = f.replace("\\", "/")
        if loc_file and (fs == loc_file or fs.endswith("/" + loc_file.replace("\\", "/"))):
            return loc_file
        return os.path.basename(fs)

    # typed values first, so they are masked everywhere after (a typed value is never shown or spoken).
    # page.keyboard.type / insertText / press have no target: they type into the focused field, which is known
    # only right after a step that focused a field it names (a click, a fill, a focus); a Tab or another key, a
    # mouse click, a navigation or any step that could move the focus makes it unknown, and unknown is secret.
    focus: Optional[bool] = None             # the focused field is secret (True/False), or not known (None)
    focus_at: Optional[int] = None           # the step that focused it
    for i, s in enumerate(steps):
        c = s["lib"] or {}
        kind = _kind(s["method"], s["title"])
        s["kind"] = kind
        resolved = next((mm for mm in reversed(c.get("logs") or []) if "locator resolved to" in mm), "")
        tag = re.search(r"<\w+[^>]*>", resolved)
        at = _attrs(tag.group(0)) if tag else {}
        s["tag_key"] = _field_key(tag.group(0)[1:].split()[0].rstrip("/>").upper(), at) if tag else None
        has_target = bool(s["api"] or (c.get("params") or {}).get("selector") or tag)
        target_secret = bool(
            at.get("type", "").lower() == "password" or at.get("autocomplete", "").lower() in SECRET_AUTOCOMPLETE
            or is_sensitive(s["api"], (c.get("params") or {}).get("selector"), at.get("name"), at.get("id"),
                            at.get("aria-label"), at.get("placeholder"), at.get("data-testid"), at.get("autocomplete")))
        value = s["params"].get("value")
        if value is None:
            value = (c.get("params") or {}).get("value")
        if value is None and kind in ("press", "type"):
            value = (c.get("params") or {}).get("key") or (c.get("params") or {}).get("text")
            if value is None:
                tm = re.match(r'^\w[\w ]*?"(.*)"$', s["title"])
                value = tm.group(1) if tm else None
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        s["value"] = None if value is None else str(value)
        s["field_at"] = i if has_target else focus_at          # the step whose target this one typed into
        s["secret"] = bool(kind in VALUE_KINDS and (target_secret if has_target else focus is not False))
        moves = s["value"] is not None and bool(re.search(r"[\t\n\r]", s["value"]))      # a Tab or Enter typed
        if has_target and kind in ("click", "dblclick", "check", "uncheck", "focus", "fill", "type", "select") \
                and not moves:
            focus, focus_at = target_secret, i
        elif kind in ("expect", "wait", "screenshot", "hover"):
            pass                                                # these never move the focus
        elif kind in ("type", "press") and not has_target and s["value"] is not None and not moves and \
                (kind == "type" or _STAYS.fullmatch(s["value"])):
            pass                                                # characters typed into the same field
        else:
            focus, focus_at = None, None
        s["key_name"] = bool(kind == "press" and s["value"] and _KEY_NAME.fullmatch(s["value"]))
        s["shown"] = bool(show_typed and kind in TYPED_KINDS and not s["secret"])
        if kind in TYPED_KINDS and not s["shown"] or s["secret"] and kind != "press" or \
                kind == "press" and s["value"] and not s["key_name"]:
            redact.add_secret(s["value"])
    hidden_values = sum(1 for s in steps if s["value"] and (s["kind"] in TYPED_KINDS and not s["shown"] or s["secret"]
                                                          or s["kind"] == "press" and not s["key_name"]))

    t0 = min(s["start"] for s in steps)
    out_steps: List[Dict[str, Any]] = []
    prev_url = ""
    vw, vh = float(viewport.get("width") or 1280), float(viewport.get("height") or 720)
    for i, s in enumerate(steps):
        c = s["lib"] or {}
        lp = c.get("params") or {}
        kind = s["kind"]
        api = "" if kind in ("goto", "reload", "back", "forward") else \
            (s["api"] or (lp.get("selector") and _selector_api(lp["selector"])) or "")
        who = human_locator(api) if api else ""
        value = s["value"]
        if kind in TYPED_KINDS:
            shown_value = redact(value) if s["shown"] and value is not None else None
        elif kind == "press":
            shown_value = value if s["key_name"] else None
        elif kind == "upload":
            shown_value = None
        else:
            shown_value = MASK if s["secret"] else (redact(value) if value is not None else None)
        url = lp.get("url") or s["params"].get("url") or ""
        seen = page_url.get(c.get("id") or "")
        if seen and seen != "about:blank":
            prev_url = seen
        elif kind == "goto" and url:
            prev_url = url
        matcher = ""
        if kind == "expect":
            mm = re.search(r'"([\w.]+)"', s["title"])
            matcher = mm.group(1) if mm else (lp.get("expression") or "").replace("to.have.", "toHave")
            if lp.get("isNot") and not matcher.startswith("not."):
                matcher = "not." + matcher
        expected = _expected_of(s["params"], lp) if kind == "expect" else None
        cap = caption(kind, who, shown_value, display_url(url), matcher, redact(expected) if expected is not None else None,
                      re.sub(r"\"[^\"]*\"|'[^']*'", "\u201c\u2026\u201d", s["title"]), s["method"],
                      typed=len(value or "") if kind in TYPED_KINDS and not s["shown"] else None)
        box = c.get("box")
        point = c.get("point")
        pct = None
        if box:
            pct = {"x": round(100 * _num(box.get("x")) / vw, 2), "y": round(100 * _num(box.get("y")) / vh, 2),
                   "w": round(100 * _num(box.get("width")) / vw, 2), "h": round(100 * _num(box.get("height")) / vh, 2)}
        ppt = None
        if point:
            ppt = {"x": round(100 * _num(point.get("x")) / vw, 2), "y": round(100 * _num(point.get("y")) / vh, 2)}
        elif pct and kind in POINTER_KINDS + VALUE_KINDS:
            ppt = {"x": round(pct["x"] + pct["w"] / 2, 2), "y": round(pct["y"] + pct["h"] / 2, 2)}
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if kind in POINTER_KINDS and not s["error"]:
            shot = _frame_at(frames, s["start"] + 10)                       # where the click lands
        elif kind in ("goto", "reload", "back", "forward") and nxt:
            shot = _frame_after(frames, s["end"], nxt["end"]) or _frame_at(frames, s["end"] + 20)
        else:                       # what the step left on the page: a frame from after it (screencasts lag)
            until = nxt["end"] if nxt else float("inf")
            shot = _frame_after(frames, s["end"] + 100, until) or _frame_after(frames, s["end"], until) or \
                _frame_at(frames, nxt["start"] if nxt else s["end"] + 50)
        out_steps.append({
            "n": i + 1, "kind": kind, "caption": redact(cap), "locator": redact(api), "target": redact(who),
            "value": shown_value, "typed_chars": len(value or "") if kind in TYPED_KINDS else None,
            "masked": bool(kind in TYPED_KINDS and not s["shown"] or s["secret"]),
            "secret_field": s["secret"], "field_known": s["field_at"] is not None, "url": redact(display_url(prev_url)),
            "file": redact(rel(s["file"])), "line": s["line"],
            "start": round((s["start"] - t0) / 1000.0, 3), "duration_ms": int(round(max(0.0, s["end"] - s["start"]))),
            "status": "passed", "box": pct, "point": ppt, "shot": shot,
            "matcher": matcher, "expected": redact(expected) if expected is not None else None})

    place_covers(steps, out_steps, raw["dom"], {f["file"]: f["t"] for f in frames}, vw, vh)

    # the failure: the step whose error failed the test (an earlier error the test caught is not it)
    errored = [i for i, s in enumerate(steps) if s["error"]]
    fail_i = None
    if errored and test_error is not None:
        head = _first_line(test_error.get("message"))
        same = [i for i in errored if head and _first_line((steps[i]["error"] or {}).get("message")) == head]
        # one error event: the test ended on the last step that raised it (a retry loop catches the earlier
        # ones); several (expect.soft): the first one is the failure
        n_errors = sum(1 for e in raw["test"] if e.get("type") == "error")
        fail_i = (same[-1] if n_errors == 1 else same[0]) if same else None
        if fail_i is None and test_error.get("stack"):
            fr = test_error["stack"][0] or {}
            fail_i = next((i for i in errored if steps[i]["file"] and steps[i]["file"] == fr.get("file")
                           and steps[i]["line"] == fr.get("line")), None)
        if fail_i is None:
            fail_i = errored[-1]
    elif errored and not raw["test"]:
        fail_i = errored[-1]
    for i in errored:
        if i == fail_i:
            out_steps[i]["status"] = "failed"
        else:
            out_steps[i]["caught"] = True                     # an error the test caught: it went on
    err = steps[fail_i]["error"] if fail_i is not None else None
    raw_msg = (err or {}).get("message") or ""
    if test_error and (not raw_msg or fail_i is None):
        raw_msg = test_error.get("message") or raw_msg
    if fail_i is None and not raw_msg:
        failure = None
    else:
        failure = _failure(raw_msg, steps[fail_i] if fail_i is not None else None, redact)
        failure["step"] = fail_i + 1 if fail_i is not None else None
        st = steps[fail_i] if fail_i is not None else None
        if test_error and test_error.get("stack") and (st is None or not st["file"]):
            fr = test_error["stack"][0]
            failure["file"], failure["line"], abs_f = rel(fr.get("file", "")), fr.get("line"), fr.get("file", "")
        else:
            failure["file"], failure["line"], abs_f = (rel(st["file"]), st["line"], st["file"]) if st else ("", None, "")
        failure["file"] = redact(failure["file"])
        failure["source"] = _source_line(src_text, abs_f, failure["line"], redact)
        if fail_i is None:
            failure["shot"] = _frame_at(frames, steps[-1]["end"] + 60000)
            failure["covers"] = list(out_steps[-1]["covers"]) if out_steps else []
    end_t = steps[fail_i]["end"] if fail_i is not None else max(s["end"] for s in steps)
    shown_console = [c for c in console if c["t"] <= end_t + 100 and c["text"].strip()]
    cons = [{"at": round((c["t"] - t0) / 1000.0, 3), "text": redact(rv.shorten(" ".join(c["text"].split()), 300))}
            for c in shown_console[:MAX_CONSOLE]]
    dur = round((max(s["end"] for s in steps) - t0) / 1000.0, 2)
    return {"test": {"title": redact(name), "file": redact(loc_file), "line": loc_line,
                     "location": redact("%s:%s" % (loc_file, loc_line) if loc_line else loc_file)},
            "status": "failed" if failure else "passed", "browser": browser, "playwright": version,
            "language": sdk or "javascript", "started": wall, "duration_s": dur, "viewport": {"width": int(vw), "height": int(vh)},
            "steps": out_steps, "failure": failure, "console": cons,
            "console_more": max(0, len(shown_console) - len(cons)),
            "privacy": {"masked_values": hidden_values, "redact_patterns": len(redact.patterns),
                        "screenshots": "as captured"}}


def _overlap(a: Dict[str, float], b: Optional[Dict[str, float]]) -> bool:
    return bool(b) and min(a["x"] + a["w"], b["x"] + b["w"]) > max(a["x"], b["x"]) and \
        min(a["y"] + a["h"], b["y"] + b["h"]) > max(a["y"], b["y"])


def place_covers(steps: List[Dict[str, Any]], out: List[Dict[str, Any]], dom: DomIndex, shot_t: Dict[str, float],
                 vw: float, vh: float) -> None:
    """o["covers"]: the boxes of the fields a value was typed into, on each step's screenshot. A cover follows
    its field through the trace's DOM snapshots: shown while the field (its tag, id and name, in its frame) is
    on the page and not empty, moved by the scroll of the boxes around it, and re-anchored to a later step's
    box when that step acts on the same field. A move the scroll alone may not explain keeps a second cover at
    the old place too (a fixed header does not scroll), unless it would hide the step's own target. When the
    snapshots cannot tell, the cover stays where the field was until the page changes."""
    def cid(j: int) -> str:
        return str((steps[j]["lib"] or {}).get("id") or "")

    def entries(j: int, frame: Any, *, phases: Sequence[str] = ()) -> List[Dict[str, Any]]:
        es = [e for e in dom.calls.get(cid(j), []) if frame is None or e["frame"] == frame]
        return [e for e in es if e["phase"] in phases] or es if phases else es

    def target_of(j: int) -> Tuple[Any, Any]:
        for e in entries(j, None, phases=("action", "after", "before")):
            if e["target"] and e["target"][0] != "?":
                return e["target"], e["frame"]
        return None, None

    def scroll_at(j: int, key: Any, frame: Any, phases: Sequence[str]) -> Optional[Tuple[int, int]]:
        if frame is None:
            return None
        for e in entries(j, frame, phases=phases):
            v = (e["fields"] or {}).get(key)
            if v is not None and e["main"] and v[0] is not None and v[1] is not None:
                return v[0], v[1]
        return None

    def state(c: Dict[str, Any], j: int) -> str:
        es = entries(j, c["frame"])
        if j + 1 < len(steps) and shot_t.get(out[j]["shot"] or "", -1) > steps[j + 1]["start"]:
            es += entries(j + 1, c["frame"], phases=("before",))                 # the shot is from the next step
        if not es or any(e["fields"] is None for e in es):
            return "unknown"
        vals = [e["fields"].get(c["key"]) for e in es]
        return "present" if any(v is not None and not v[2] for v in vals) else \
            "empty" if any(v is not None for v in vals) else "absent"

    covers: List[Dict[str, Any]] = []
    own: Dict[int, Dict[str, float]] = {}
    prev_url = None
    for j, o in enumerate(out):
        kind = o["kind"]
        nav = kind in ("goto", "reload") or (prev_url is not None and o["url"] != prev_url
                                             and kind not in ("back", "forward"))
        prev_url = o["url"]
        tkey, tframe = target_of(j) if steps[j].get("field_at") == j else (None, None)
        shown: List[Tuple[Dict[str, float], int]] = []
        for c in covers:
            if not c["alive"]:
                continue
            if tkey is not None and tkey == c["key"] and tframe == c["frame"] and o["box"]:
                c["box"], c["ref"] = o["box"], scroll_at(j, c["key"], c["frame"], ("action", "before", "after"))
                shown.append((c["box"], c["n"]))                     # the same field, acted on again
                continue
            st = state(c, j) if c["seen"] else "unknown"
            if st == "unknown":
                if nav:
                    c["alive"] = False                               # a new page; the snapshots cannot tell
                else:
                    shown.append((c["box"], c["n"]))
                continue
            if st != "present":
                continue                                             # gone or emptied (it may come back)
            cur = scroll_at(j, c["key"], c["frame"], ("before",) if kind in POINTER_KINDS else ("after", "action"))
            b = c["box"]
            if c["ref"] is not None and cur is not None and cur != c["ref"]:
                moved = dict(b, x=round(b["x"] - 100 * (cur[1] - c["ref"][1]) / vw, 2),
                             y=round(b["y"] - 100 * (cur[0] - c["ref"][0]) / vh, 2))
                if _overlap(moved, {"x": 0, "y": 0, "w": 100, "h": 100}):
                    shown.append((moved, c["n"]))
                if not _overlap(b, o["box"]):
                    shown.append((b, c["n"]))
            else:
                shown.append((b, c["n"]))
        if o["masked"] and kind in TYPED_KINDS + ("press",):
            a = steps[j].get("field_at")
            box = out[a]["box"] if a is not None else None
            if box:
                key, frame = target_of(a)
                seen = key is not None
                if key is None and steps[a].get("tag_key"):
                    key = steps[a]["tag_key"]
                    seen = any(e["fields"] is not None and key in e["fields"] for e in entries(a, None) + entries(j, None))
                rec = {"n": o["n"], "key": key, "frame": frame, "box": box, "seen": seen, "alive": True,
                       "ref": scroll_at(a, key, frame, ("action", "after", "before"))}
                covers = [c for c in covers if not (key is not None and c["key"] == key and c["frame"] == frame
                                                    or c["box"] == box)] + [rec]
                shown = [x for x in shown if x[0] != box] + [(box, o["n"])]
                own[j] = box
            else:
                o["uncovered"] = True                                # the field it typed into is not known
        o["covers"] = []
        for b, n in shown:
            if not any(_same(b, x) for x in o["covers"]):
                o["covers"].append(dict(b, step=n))
    for j, o in enumerate(out):                 # a shot taken while the next step typed shows what it typed
        if j + 1 in own and shot_t.get(o["shot"] or "", -1) > steps[j + 1]["start"] and \
                not any(_same(own[j + 1], x) for x in o["covers"]):
            o["covers"].append(dict(own[j + 1], step=out[j + 1]["n"]))


def _same(a: Dict[str, float], b: Dict[str, float]) -> bool:
    return all(a.get(k) == b.get(k) for k in ("x", "y", "w", "h"))


def _first_line(msg: Optional[str]) -> str:
    return next((x.strip() for x in strip_ansi(msg or "").split("\n") if x.strip()), "")


def _frame_at(frames: List[Dict[str, Any]], t: float) -> Optional[str]:
    """The last screenshot taken by `t` (else the first one)."""
    if not frames:
        return None
    best = frames[0]
    for f in frames:
        if f["t"] > t:
            break
        best = f
    return best["file"]


def _frame_after(frames: List[Dict[str, Any]], t: float, until: float) -> Optional[str]:
    """The first screenshot after `t` and by `until` (a page that just loaded), or None."""
    return next((f["file"] for f in frames if t < f["t"] <= until), None)


def caption(kind: str, who: str, value: Optional[str], url: str, matcher: str, expected: Optional[str],
            title: str = "", method: str = "", typed: Optional[int] = None) -> str:
    """One line for a step: "Click the 'Sign in' button", "Type 16 characters into the 'Email' field" (`typed`:
    how many characters were typed, never what)."""
    q = (lambda v: "\u201c%s\u201d" % v if v != MASK else MASK)
    if kind in ("fill", "type") and typed is not None:
        if not typed:
            return "Clear" + ((" " + who) if who else " the field")
        return "Type %d character%s into %s" % (typed, "" if typed == 1 else "s", who or "the page")
    tgt = (" " + who) if who else ""
    if kind == "goto":
        return "Open %s" % (url or "the page")
    if kind == "reload":
        return "Reload the page"
    if kind in ("back", "forward"):
        return "Go %s" % kind
    if kind in ("click", "dblclick"):
        return ("Double-click" if kind == "dblclick" else "Click") + (tgt or " the page")
    if kind == "fill":
        return ("Fill%s with %s" % (tgt, q(value))) if value else ("Clear" + tgt)
    if kind == "type":
        return "Type %s into%s" % (q(value or ""), tgt or " the page")
    if kind == "press":
        return "Press %s%s" % (value if value and value != MASK else "a key", (" in" + tgt) if who else "")
    if kind in ("check", "uncheck"):
        return kind.capitalize() + (tgt or " the box")
    if kind == "select":
        return "Select %s in%s" % (q(value or ""), tgt or " the list")
    if kind == "hover":
        return "Hover over" + (tgt or " the page")
    if kind == "upload":
        return "Upload a file to" + (tgt or " the page")
    if kind == "expect":
        what = _words(matcher) if matcher else "to pass"
        subj = who or "the page"
        if re.search(r"toHaveURL|toHaveTitle", matcher or ""):
            what = what.replace("to have ", "to have the ")
        return ("Expect %s %s %s" % (subj, what, q(expected))).strip() if expected not in (None, "") else \
            "Expect %s %s" % (subj, what)
    if kind == "wait":
        return "Wait for" + (tgt or " the page")
    if kind == "focus":
        return "Focus" + (tgt or " the page")
    if kind == "drag":
        return "Drag" + (tgt or " an element")
    return (title or method or "Step").strip() + ((" \u00b7 " + who) if who else "")


_EXP = re.compile(r"^(Expected|Received)(?: (string|pattern|substring|value|number|length|count|text))?\s*:\s?(.*)$")


def _failure(raw_msg: str, step: Optional[Dict[str, Any]], redact: Redactor) -> Dict[str, Any]:
    """The error -> {headline, expected, received (with the parts Playwright marks as different), details,
    call_log}, redacted."""
    lines = raw_msg.split("\n")
    plain = [strip_ansi(x) for x in lines]
    head = next((x.strip() for x in plain if x.strip()), "") or "the test failed"
    head = re.sub(r"^(?:Error|TimeoutError|AssertionError|ExpectError):\s*", "", head)
    out: Dict[str, Any] = {"headline": "", "expected": None, "received": None, "details": [], "call_log": ""}
    in_log = False
    log: List[str] = []
    for r, p in zip(lines[1:], plain[1:]):
        if p.strip().lower().startswith("call log"):
            in_log = True
            continue
        if in_log:
            if p.strip():
                log.append(p.strip().lstrip("- ").strip())
            continue
        m = _EXP.match(p.strip())
        if m:
            key = m.group(1).lower()
            val_raw = r.split(":", 1)[1][1:] if ":" in r else ""
            val_plain = redact(m.group(3).strip())
            segs = ansi_segments(val_raw.strip())
            if "".join(t for t, _f in segs).strip() != val_plain:
                segs = [[val_plain, False]]                        # something was masked: no diff marks
            out[key] = {"text": val_plain, "parts": segs, "kind": m.group(2) or ""}
        elif p.strip() and not p.strip().startswith(("at ", "Locator:")) and len(out["details"]) < 3:
            out["details"].append(redact(rv.shorten(re.sub(r"\s+", " ", p.strip()), 140)))
    lc = (step or {}).get("lib") or {}
    if out["received"] is None and step is not None and step.get("kind") == "expect":
        got = next((re.search(r'unexpected value "(.*)"', x) for x in reversed(lc.get("logs") or [])
                    if "unexpected value" in x), None)
        if got:
            out["received"] = {"text": redact(got.group(1)), "parts": [[redact(got.group(1)), False]], "kind": ""}
    if out["expected"] is None and step is not None and step.get("kind") == "expect":
        e = _expected_of(step.get("params") or {}, lc.get("params") or {})
        if e is not None:
            out["expected"] = {"text": redact(e), "parts": [[redact(e), False]], "kind": ""}
    if head.lower() in ("expect failed", "") and step is not None:
        mm = re.search(r'"([\w.]+)"', step.get("title") or "")
        head = "expect%s failed" % ("(...)." + mm.group(1) + "()" if mm else "")
    if not log and lc.get("logs"):
        log = [x.strip() for x in lc["logs"] if x.strip()]
    out["headline"] = redact(rv.shorten(head, 120))
    uniq = [x for i, x in enumerate(log) if x not in log[:i]]
    out["call_log"] = redact(rv.shorten(uniq[-1], 120)) if uniq else ""
    return out


def _source_line(src: Dict[str, List[str]], abs_file: str, line: Optional[int], redact: Redactor) -> Optional[Dict[str, Any]]:
    """The failing line of the test's source (the trace carries the file), dedented and redacted."""
    if not line:
        return None
    lines = src.get(hashlib.sha1((abs_file or "").encode("utf-8")).hexdigest())
    if lines is None and len(src) == 1:
        lines = next(iter(src.values()))
    if not lines or not (1 <= int(line) <= len(lines)):
        return None
    return {"line": int(line), "text": redact(rv.shorten(lines[int(line) - 1].strip(), 180))}


def has_failure(path: Path) -> Tuple[bool, Optional[float], str]:
    """(the test failed, its wall-clock start, its test title), reading only until the answer is known: with
    the test runner's events, its `error` event (an error a test caught is no failure); else a library call's
    error."""
    try:
        z = open_trace(path)
    except ShowtimeError:
        return False, None, ""
    try:
        infos = _members(z)
        names = sorted(i.filename for i in infos if i.filename.endswith(".trace"))
        runner = [n for n in names if n.rsplit("/", 1)[-1] == "test.trace"]
        wall, title, err = None, "", False
        for n in runner or names:
            for e in _jsonl(z, n, stop=lambda e: e.get("type") == "error" or (not runner and e.get("type") == "after"
                                                                                and bool(e.get("error")))):
                if e.get("type") == "context-options":
                    wall = wall or e.get("wallTime")
                    title = title or e.get("title") or ""
                if e.get("type") == "error" or (not runner and e.get("type") == "after" and e.get("error")):
                    err = True
            if err:
                break
    finally:
        z.close()
    return err, wall, title or path.parent.name


# ---------------------------------------------------------------------------
# running a command with tracing on
# ---------------------------------------------------------------------------

def runner_of(cmd: Sequence[str]) -> str:
    """'playwright' for `npx playwright test ...` (and pnpm/yarn/bunx/node cli.js), 'pytest' for pytest, else ''."""
    toks = [os.path.basename(t).lower() for t in cmd]
    for i, t in enumerate(toks):
        if re.match(r"^playwright(\.cmd|\.exe)?$|^cli\.js$", t) and "test" in toks[i + 1:i + 3]:
            return "playwright"
        if re.match(r"^(py\.?test|pytest)(\.exe)?$", t) or (t == "-m" and toks[i + 1:i + 2] == ["pytest"]):
            return "pytest"
    return ""


def _flag_value(cmd: Sequence[str], flag: str) -> Optional[str]:
    for i, a in enumerate(cmd):
        if a == flag and i + 1 < len(cmd):
            return cmd[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def tracing_command(cmd: Sequence[str], out_dir: Path) -> Tuple[List[str], str]:
    """(the command with tracing on for failing tests and its output in out_dir, the runner). Flags the user
    gave win."""
    cmd = list(cmd)
    kind = runner_of(cmd)
    has = lambda flag: any(a == flag or a.startswith(flag + "=") for a in cmd)  # noqa: E731
    if kind == "playwright":
        if not has("--trace"):
            cmd += ["--trace", "retain-on-failure"]
        if not has("--output"):
            cmd += ["--output", str(out_dir)]
    elif kind == "pytest":
        if not has("--tracing"):
            cmd += ["--tracing", "retain-on-failure"]
        if not has("--output"):
            cmd += ["--output", str(out_dir)]
    return cmd, kind


PRUNE = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".hg", ".svn"}


def find_traces(roots: Iterable[Path], since: float, max_depth: int = 6) -> List[Path]:
    """trace.zip files written since `since` under the folders the runner was told to write into (never the
    whole working tree): at most `max_depth` levels down, skipping node_modules, .git and virtualenvs."""
    out: List[Path] = []
    for r in roots:
        r = Path(r)
        if not r.is_dir():
            continue
        base = len(r.parts)
        for dirpath, dirnames, filenames in os.walk(str(r)):
            depth = len(Path(dirpath).parts) - base
            dirnames[:] = [d for d in dirnames if d not in PRUNE and depth < max_depth]
            if "trace.zip" in filenames:
                p = Path(dirpath) / "trace.zip"
                try:
                    if p.stat().st_mtime >= since - 1:
                        out.append(p)
                except OSError:
                    continue
    return sorted(set(out))


# what the launcher sets for showtime's own tools, by name and the value it gives (home: SHOWTIME_HOME)
_OURS = (("IMAGEIO_FFMPEG_EXE", ("bin", "ffmpeg")), ("SUPERTONIC_CACHE_DIR", ("models", "supertonic3")),
         ("U2NET_HOME", ("models", "u2net")), ("PLAYWRIGHT_BROWSERS_PATH", ("browsers",)),
         ("HF_HOME", ("models", "hf")))


def user_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment the user's own test command runs in: PATH as the user has it, without what the launcher
    adds for showtime's own tools (its lib on PYTHONPATH, its node_modules on NODE_PATH, its browsers, its model
    caches and ffmpeg, its settings, the variables it set that the user had not), so `pytest` and
    `npx playwright` are the project's own, with the project's browsers."""
    e = dict(os.environ if env is None else env)
    if e.get("SHOWTIME_USER_PATH") is not None:
        e["PATH"] = e["SHOWTIME_USER_PATH"]
    norm = lambda x: os.path.normcase(os.path.normpath(x))  # noqa: E731
    lib = str(Path(__file__).resolve().parent.parent)
    for var, ours in (("PYTHONPATH", lib), ("NODE_PATH", e.get("SHOWTIME_NODE_MODULES") or "")):
        keep = [x for x in (e.get(var) or "").split(os.pathsep) if x and not (ours and norm(x) == norm(ours))]
        if keep:
            e[var] = os.pathsep.join(keep)
        else:
            e.pop(var, None)
    home = e.get("SHOWTIME_HOME")
    if home:
        for var, parts in _OURS:
            v, ours = e.get(var), os.path.join(home, *parts)
            if v and (v == ours or var == "IMAGEIO_FFMPEG_EXE" and v.startswith(ours)):
                e.pop(var)
    for var in (e.get("SHOWTIME_ADDED_ENV") or "").split(","):     # set by the launcher, not by the user
        if var and var not in ("PATH", "PYTHONPATH", "NODE_PATH") and var not in dict(_OURS):
            e.pop(var, None)
    if e.get("SHOWTIME_USER_HF_HOME"):
        e["HF_HOME"] = e["SHOWTIME_USER_HF_HOME"]
    for var in [k for k in e if k.startswith("SHOWTIME_")]:
        del e[var]
    return e


DEFAULT_TIMEOUT = 1800.0     # seconds the user's test command may run


def run_and_find(cmd: Sequence[str], out_dir: Path, *, cwd: Optional[Path] = None,
                 timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Run the test command with tracing on; return {rc, command, runner, trace, failing, traces}. Traces are
    looked for only where the runner was told to write (out_dir, or the --output the user gave). The runner's
    output goes to stderr (stdout stays the command's own result). Its stdin is empty, and Playwright's html
    reporter is told not to serve its report (it would wait for Ctrl+C in a terminal), unless the user said."""
    out_dir.mkdir(parents=True, exist_ok=True)
    full, kind = tracing_command(cmd, out_dir)
    cwd = Path(cwd or os.getcwd())
    env = user_env()
    if not env.get("PLAYWRIGHT_HTML_OPEN") and not env.get("PW_TEST_HTML_REPORT_OPEN"):
        env["PLAYWRIGHT_HTML_OPEN"] = "never"
    exe = shutil.which(full[0], path=env.get("PATH")) or full[0]
    start = time.time()
    posix = os.name != "nt"
    try:
        proc = subprocess.Popen([exe] + full[1:], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=sys.stderr,
                                stderr=sys.stderr, start_new_session=posix)
    except OSError as e:
        raise ShowtimeError("could not run %s: %s" % (full[0], e.strerror or e),
                            hint="check the command (it runs without a shell, from the current folder); e.g. "
                                 "showtime repro -- npx playwright test tests/login.spec.ts")
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc, posix)
        raise ShowtimeError("the test command ran longer than %d s and was stopped" % timeout,
                            hint="run one test (a watch or UI mode never ends), or give it more time: --timeout SECONDS")
    except KeyboardInterrupt:
        _kill_tree(proc, posix)
        raise
    user_out = _flag_value(full, "--output") if kind else None
    roots = [out_dir] + ([cwd / user_out] if user_out and (cwd / user_out).resolve() != out_dir.resolve() else [])
    traces = find_traces(roots, start)
    found = []
    for p in traces:
        err, wall, title = has_failure(p)
        if err:
            found.append((wall or p.stat().st_mtime * 1000, p, title))
    found.sort(key=lambda x: x[0])
    return {"rc": rc, "command": full, "runner": kind, "traces": [str(p) for p in traces],
            "failing": [{"trace": str(p), "title": t} for _w, p, t in found],
            "trace": str(found[0][1]) if found else None}


def _kill_tree(proc: "subprocess.Popen[Any]", posix: bool) -> None:
    try:
        if posix:
            os.killpg(proc.pid, 9)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def rerun_command(rep: Dict[str, Any], cmd: Optional[Sequence[str]], redact: Redactor) -> str:
    """What the end card says to run: the command given, else `npx playwright test <file>:<line>` for a test
    runner's trace (a library-only trace, such as pytest's, does not say how its test is selected)."""
    if cmd:
        return redact(" ".join(shlex.quote(c) for c in cmd))
    loc = rep["test"]["location"]
    if rep.get("language", "javascript") == "javascript" and rep["test"].get("line") and loc:
        return "npx playwright test %s" % loc
    return ""


def viewer_command(rep: Dict[str, Any], trace_name: str = "trace.zip") -> str:
    return ("playwright show-trace %s" if rep.get("language") == "python" else "npx playwright show-trace %s") % trace_name


# ---------------------------------------------------------------------------
# planning the film
# ---------------------------------------------------------------------------

def read_time(text: str) -> float:
    return pv.read_time(text)


def _step_texts(s: Dict[str, Any]) -> List[str]:
    return [s["caption"], s["locator"], s["url"], "%s:%s" % (s["file"], s["line"]) if s["file"] else ""]


def step_dur(s: Dict[str, Any]) -> float:
    need = max(read_time(t) for t in _step_texts(s) if t)
    extra = 0.5 if s["kind"] in POINTER_KINDS else 0.0          # the cursor travels before the click
    return round(min(4.2, max(2.2, LEAD + ENTER + extra + need + OUT)), 2)


def fail_dur(rep: Dict[str, Any]) -> float:
    f = rep["failure"] or {}
    beats = fail_beats(rep)
    last = max(beats.values()) if beats else 1.0
    texts = [f.get("headline", ""), (f.get("expected") or {}).get("text", "") + " " + (f.get("received") or {}).get("text", "")]
    texts += [c["text"] for c in rep["console"][:2]]
    need = last + ENTER + max(read_time(t) for t in texts if t.strip()) if any(t.strip() for t in texts) else last + 2
    return round(min(12.0, max(6.5, need + OUT)), 2)


def fail_beats(rep: Dict[str, Any]) -> Dict[str, float]:
    """When each part of the failure scene arrives (a beat about every second, so it never reads as a hold)."""
    f = rep["failure"] or {}
    at = 0.25
    out = {"caption": at}
    at += 0.9
    if f.get("source"):
        out["source"] = at
        at += 1.0
    if f.get("expected") or f.get("received"):
        out["vs"] = at
        at += 1.3
    out["error"] = at
    at += 1.0
    if rep["console"]:
        out["console"] = at
    return out


def title_meta(rep: Dict[str, Any]) -> str:
    n = len(rep["steps"])
    f = rep["failure"]
    return " \u00b7 ".join(x for x in ("Playwright %s" % rep["playwright"] if rep["playwright"] else "Playwright",
                                       rep["browser"], "%d step%s" % (n, "" if n == 1 else "s"),
                                       ("fails at step %d" % f["step"]) if f and f.get("step") else "") if x)


def title_dur(rep: Dict[str, Any]) -> float:
    need = max(read_time(rep["test"]["title"]), 0.5 + read_time(title_meta(rep)))      # the meta line rises at 0.5 s
    return round(max(3.0, LEAD + ENTER + need + 0.3 + OUT), 2)


def end_dur(rerun: str) -> float:
    return round(max(3.2, LEAD + ENTER + read_time(rerun or "") + OUT), 2)


def plan(rep: Dict[str, Any], *, rerun: str = "", max_seconds: float = MAX_SECONDS,
         speech: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Scenes and their lengths: the title, the steps (compressed to fit max_seconds: the first step, then the
    steps just before the failure; the ones between become one "+ N passing steps" scene), the failure and the
    end card. With `speech` ({scene id: seconds of narration}) a scene is at least as long as its line."""
    steps = rep["steps"]
    fail_n = (rep["failure"] or {}).get("step")
    passing = [s for s in steps if s["status"] == "passed" and (fail_n is None or s["n"] < fail_n)]
    shown_fail = [s for s in steps if fail_n is not None and s["n"] == fail_n]

    def spoken(sid: str, d: float) -> float:
        if speech and sid in speech:
            return round(max(d, VOICE_PAD + speech[sid] + VOICE_TAIL), 2)
        return d
    fixed = spoken("title", title_dur(rep)) + spoken("fail", fail_dur(rep) if rep["failure"] else 0) + \
        spoken("end", end_dur(rerun))
    durs = {s["n"]: spoken("step%d" % s["n"], step_dur(s)) for s in passing}
    budget = max_seconds - fixed
    keep = [s["n"] for s in passing]
    skipped: List[int] = []
    if sum(durs.values()) > budget and len(passing) > 2:
        skip_d = spoken("skip", 2.6)
        head = [passing[0]["n"]]
        tail: List[int] = []
        room = budget - durs[head[0]] - skip_d
        for s in reversed(passing[1:]):
            if durs[s["n"]] <= room:
                tail.insert(0, s["n"])
                room -= durs[s["n"]]
            else:
                break
        skipped = [s["n"] for s in passing if s["n"] not in head + tail]
        keep = head + tail
        if len(skipped) == 1:                 # one step is cheaper shown than summed up
            keep, skipped = sorted(keep + skipped), []
    scenes: List[Dict[str, Any]] = [{"id": "title", "kind": "title", "dur": spoken("title", title_dur(rep))}]
    for s in passing:
        if s["n"] in keep:
            scenes.append({"id": "step%d" % s["n"], "kind": "step", "dur": durs[s["n"]], "step": s["n"]})
        elif skipped and s["n"] == skipped[0]:
            scenes.append({"id": "skip", "kind": "skip", "dur": spoken("skip", 2.6), "skipped": list(skipped)})
    if shown_fail or rep["failure"]:
        scenes.append({"id": "fail", "kind": "fail", "dur": spoken("fail", fail_dur(rep)), "step": fail_n})
    scenes.append({"id": "end", "kind": "end", "dur": spoken("end", end_dur(rerun))})
    t = 0.0
    for sc in scenes:
        sc["start"] = round(t, 2)
        t += sc["dur"]
    return {"scenes": scenes, "duration": round(t, 2), "shown_steps": len(keep) + (1 if shown_fail else 0),
            "skipped_steps": skipped, "total_steps": len(steps), "rerun": rerun}


def _say(text: str) -> str:
    """A caption made speakable: quotes and the mask dots go, code-ish words stay as written."""
    t = re.sub(re.escape(MASK) + r"@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*", "a hidden email address", text)
    t = t.replace(MASK, "a hidden value").replace("\u201c", "").replace("\u201d", "")
    t = re.sub(r"'([^']+)'", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def step_line(s: Dict[str, Any]) -> str:
    """A step's spoken line: never a typed value (a fill, a typed text, a chosen option or an unnamed key is
    said without it)."""
    tgt = s.get("target") or ""
    k = s["kind"]
    if k in TYPED_KINDS:
        line = ("Clear %s" % (tgt or "the field")) if s.get("typed_chars") == 0 else "Type into %s" % (tgt or "the page")
    elif k == "select":
        line = "Choose an option in %s" % (tgt or "the list")
    elif k == "press":
        line = "Press %s" % (s["value"] if s.get("value") and s["value"] != MASK else "a key")
    elif k == "upload":
        line = "Upload a file"
    elif k == "goto":
        line = "Open the page"
    else:
        line = s["caption"]
    return _say(line).rstrip(".") + "."


def title_line(rep: Dict[str, Any]) -> str:
    f = rep["failure"]
    name = _say(rep["test"]["title"]).rstrip(".")
    return "%s. %s" % (name[:1].upper() + name[1:], "This test fails at step %d." % f["step"] if f and f.get("step")
                       else "This test fails." if f else "This test passes.")


def fail_line(rep: Dict[str, Any]) -> str:
    f = rep["failure"] or {}
    s = next((x for x in rep["steps"] if x["n"] == f.get("step")), None)
    exp, got = (f.get("expected") or {}).get("text"), (f.get("received") or {}).get("text")
    line = "Step %d fails. " % f["step"] if f.get("step") else "Here it fails. "
    if s and s["kind"] == "expect" and exp is not None and got is not None and len(exp) + len(got) < 90:
        line += "It expected %s, but got %s." % (_say(exp), _say(got))
    else:
        line += _say(f.get("headline") or "the test failed").rstrip(".") + "."
    n = len(rep["console"]) + int(rep.get("console_more") or 0)
    if n:
        line += " The console logged %s." % ("an error" if n == 1 else "%d errors" % n)
    return line


SKIP_LINE = "Then {n} more steps pass."


def end_line(rerun: str) -> str:
    return "Run the command on screen to see it fail." if rerun else "Open the trace to see every step."


def narration(rep: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, str]:
    """{scene id: line}. Values typed into fields are never spoken. The lines of script.md (rep["say"]) win:
    an empty one leaves its scene silent."""
    out: Dict[str, str] = {}
    steps = {s["n"]: s for s in rep["steps"]}
    say = rep.get("say") or {}
    for sc in p["scenes"]:
        sid = sc["id"]
        if sid == "title":
            line = title_line(rep)
        elif sc["kind"] == "step":
            line = step_line(steps[sc["step"]])
        elif sid == "skip":
            line = SKIP_LINE
        elif sid == "fail" and rep["failure"]:
            line = fail_line(rep)
        elif sid == "end":
            line = end_line(p.get("rerun") or "")
        else:
            continue
        line = say.get(sid, line)
        if line:
            out[sid] = line.replace("{n}", str(len(sc.get("skipped") or [])))
    return out


# ---------------------------------------------------------------------------
# captions (repro.srt)
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int = 42) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def _cue_chunks(text: str, width: int = 42) -> List[str]:
    """Text -> cues of at most two lines of `width` characters, split at sentences, then at words."""
    lines = _wrap(text, width)
    if len(lines) <= 2:
        return ["\n".join(lines)]
    out: List[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        ls = _wrap(sent, width)
        out += ["\n".join(ls[i:i + 2]) for i in range(0, len(ls), 2)]
    return out


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def build_srt(p: Dict[str, Any], lines: Dict[str, str], spans: Optional[Dict[str, Tuple[float, float]]] = None) -> str:
    """One cue (or a few) per scene: the narration while it is spoken (`spans`: {scene id: (start, end)} in the
    video), else across the scene."""
    from .captions_rules import MAX_CPS
    cues: List[Tuple[float, float, str]] = []
    for sc in p["scenes"]:
        text = lines.get(sc["id"])
        if not text:
            continue
        a, b = (spans or {}).get(sc["id"], (sc["start"] + LEAD, sc["start"] + sc["dur"] - OUT))
        b = max(b, min(sc["start"] + sc["dur"] - 0.05, a + len(text) / MAX_CPS + 0.05))
        parts = _cue_chunks(text)
        total = sum(len(x) for x in parts) or 1
        t = a
        for x in parts:
            d = (b - a) * len(x) / total
            cues.append((t, t + d, x))
            t += d
    return "".join("%d\n%s --> %s\n%s\n\n" % (i + 1, srt_time(a), srt_time(b), x) for i, (a, b, x) in enumerate(cues))


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------

CSS = rv.CSS + r"""
  .scene { --fail: #ff6b6b; --ok: #6fdc8c; --s-cap: 4.4cqh; --s-mono: 2.5cqh; --s-small: 2.4cqh; --s-kind: 2.4cqh; }
  .topbar { position: absolute; left: 5.5cqw; right: 5.5cqw; top: 5.6cqh; display: flex; align-items: center; gap: 2cqw; }
  .topbar .label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .counter { font: 600 2.8cqh/1 var(--font-mono); color: var(--fg); display: flex; align-items: center; gap: 1.2cqw; }
  .counter em { font-style: normal; color: var(--muted); font-weight: 500; }
  .pips { display: flex; gap: 0.5cqw; }
  .pips i { display: block; width: 1.3cqh; height: 1.3cqh; border-radius: 50%; background: var(--line); }
  .pips i.ok { background: color-mix(in oklab, var(--ok) 70%, transparent); }
  .pips i.now { background: var(--accent); box-shadow: 0 0 0 0.35cqh color-mix(in oklab, var(--accent) 35%, transparent); }
  .pips i.bad { background: var(--fail); }

  /* the browser window around a screenshot */
  .win { position: absolute; border-radius: 1.2cqh; overflow: hidden; background: #1b1f27;
         box-shadow: 0 2.4cqh 6cqh rgb(0 0 0 / 0.45), 0 0 0 max(1px, 0.12cqh) var(--line); }
  .win .bar { height: 4.6cqh; display: flex; align-items: center; gap: 1cqw; padding: 0 1.2cqw; background: #232833; }
  .win .bar .d { display: flex; gap: 0.5cqw; }
  .win .bar .d i { width: 1.2cqh; height: 1.2cqh; border-radius: 50%; background: #3a4150; display: block; }
  .win .bar .u { flex: 1; min-width: 0; font: 500 2.4cqh/1 var(--font-mono); color: var(--muted); background: #161a21;
                 border-radius: 0.8cqh; padding: 0.9cqh 1.2cqw; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .win .bar .u.typed { animation: reveal 0.7s steps(24, end) var(--at, 0.2s) both; }
  @keyframes reveal { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
  .shot { position: relative; }
  .shot { overflow: hidden; }
  .shot img { display: block; width: 100%; height: 100%; object-fit: fill; }
  .zoom { position: absolute; inset: 0; animation: zoomin 0.9s cubic-bezier(0.45, 0, 0.2, 1) 0.1s both; }
  @keyframes zoomin { from { transform: none; } to { transform: scale(var(--z)); } }
  .shot .none { position: absolute; inset: 0; display: grid; place-items: center; font: 500 2.4cqh/1.3 var(--font-mono);
                color: var(--muted); background: #12151b; }
  .box { position: absolute; border: max(2px, 0.3cqh) solid var(--accent); border-radius: 0.6cqh;
         box-shadow: 0 0 0 0.6cqh color-mix(in oklab, var(--accent) 22%, transparent);
         animation: boxin 0.45s cubic-bezier(0.16, 1, 0.3, 1) var(--at, 0.3s) both; }
  .box.bad { border-color: var(--fail); box-shadow: 0 0 0 0.6cqh color-mix(in oklab, var(--fail) 25%, transparent); }
  @keyframes boxin { from { opacity: 0; transform: scale(1.12); } to { opacity: 1; transform: none; } }
  .cursor { position: absolute; width: 3.4cqh; height: 3.4cqh; left: var(--x); top: var(--y); margin: -0.3cqh 0 0 -0.5cqh;
            animation: travel 0.6s cubic-bezier(0.45, 0, 0.2, 1) 0.15s both; filter: drop-shadow(0 0.3cqh 0.5cqh rgb(0 0 0 / 0.5)); }
  @keyframes travel { from { left: var(--x0); top: var(--y0); } to { left: var(--x); top: var(--y); } }
  .ripple { position: absolute; width: 7cqh; height: 7cqh; margin: -3.5cqh 0 0 -3.5cqh; border-radius: 50%;
            border: max(2px, 0.35cqh) solid var(--accent); opacity: 0; animation: ripple 0.7s ease-out var(--at, 0.8s) both; }
  @keyframes ripple { 0% { opacity: 0.95; transform: scale(0.15); } 100% { opacity: 0; transform: scale(1.5); } }
  .cover { position: absolute; background: #2b303b; border-radius: 0.5cqh; display: grid; place-items: center;
           box-shadow: 0 0 0 max(1px, 0.12cqh) #454c5a; overflow: hidden; }
  .cover::after { content: "hidden"; font: 600 1.5cqh/1 var(--font-mono); letter-spacing: 0.14em; color: #9aa3b2;
                  text-transform: uppercase; }
  .t .cover::after { content: none; }
  .t { position: relative; }
  .caret { position: absolute; width: max(2px, 0.25cqh); background: var(--accent); animation: blink 0.5s steps(1) 0.4s 6 both; }
  @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0; } }

  /* the side column of a step */
  .side { position: absolute; right: 5.5cqw; top: 50%; translate: 0 -50%; display: flex; flex-direction: column; gap: 2.2cqh; }
  .side > * { margin: 0; opacity: 0; animation: rise 0.45s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .kind { font: 600 var(--s-kind)/1 var(--font-mono); letter-spacing: 0.16em; text-transform: uppercase; color: var(--accent); }
  .kind.ok::after { content: "  \2713"; color: var(--ok); }
  .kind.bad { color: var(--fail); }
  .cap { font: 600 var(--s-cap)/1.18 var(--font-display); letter-spacing: -0.015em; color: var(--fg); overflow-wrap: anywhere; }
  .loc { font: 500 var(--s-mono)/1.35 var(--font-mono); color: var(--muted); overflow-wrap: anywhere; }
  .where { font: 500 var(--s-small)/1.3 var(--font-mono); color: var(--muted); opacity: 0.85; }

  /* title */
  .tcard { position: absolute; left: 8cqw; right: 8cqw; top: 50%; translate: 0 -50%; display: flex; flex-direction: column; gap: 2.6cqh; }
  .tcard .pill { align-self: flex-start; font: 700 3.4cqh/1 var(--font-mono); letter-spacing: 0.14em; color: #1a0d0d;
                 background: var(--fail); border-radius: 0.8cqh; padding: 1cqh 1.4cqw; }
  .tcard .tname { font: 700 9cqh/1.04 var(--font-display); letter-spacing: -0.03em; color: var(--fg); margin: 0; overflow-wrap: anywhere; }
  .tcard .tloc { font: 600 4.4cqh/1 var(--font-mono); color: var(--accent); margin: 0; }
  .tcard .tmeta { font: 500 3cqh/1.3 var(--font-mono); color: var(--muted); margin: 0;
                  animation: rise 0.6s cubic-bezier(0.16, 1, 0.3, 1) 0.5s both; }

  /* passing steps summed up */
  .skip { position: absolute; left: 8cqw; right: 8cqw; top: 50%; translate: 0 -50%; display: flex; flex-direction: column; gap: 3cqh; }
  .skip .head { font: 650 7cqh/1.04 var(--font-display); letter-spacing: -0.03em; color: var(--fg); margin: 0; }
  .skip .head em { font-style: normal; color: var(--ok); }
  .thumbs { display: flex; gap: 1.2cqw; }
  .thumbs .t { width: 13cqw; aspect-ratio: var(--ar); border-radius: 0.8cqh; overflow: hidden; background: #12151b;
               box-shadow: 0 0 0 max(1px, 0.12cqh) var(--line); opacity: 0; animation: rise 0.4s ease var(--at) both; }
  .thumbs .t img { width: 100%; height: 100%; display: block; object-fit: fill; }
  .skip .range { font: 500 2.8cqh/1.3 var(--font-mono); color: var(--muted); margin: 0; animation: rise 0.5s ease 0.6s both; }

  /* the failure */
  .fside { position: absolute; left: 50cqw; right: 5.5cqw; top: 13cqh; bottom: 6cqh; display: flex; flex-direction: column;
           justify-content: center; gap: 2.2cqh; }
  .fside > * { margin: 0; opacity: 0; animation: rise 0.5s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .fside .cap { font-size: 3.7cqh; }
  .src { font: 500 2.4cqh/1.45 var(--font-mono); color: var(--fg); background: var(--surface); border-radius: 0.8cqh;
         padding: 1.2cqh 1.2cqw; white-space: pre-wrap; overflow-wrap: anywhere;
         box-shadow: inset 0.5cqh 0 0 var(--fail), 0 0 0 max(1px, 0.12cqh) var(--line);
         background-image: linear-gradient(color-mix(in oklab, var(--fail) 16%, transparent), color-mix(in oklab, var(--fail) 16%, transparent)); }
  .src .n { color: var(--muted); margin-right: 1.2em; }
  .vs { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2cqw; }
  .vs > div { background: var(--surface); border-radius: 0.8cqh; padding: 1.4cqh 1.2cqw; box-shadow: 0 0 0 max(1px, 0.12cqh) var(--line); }
  .vs .k { font: 600 2.4cqh/1 var(--font-mono); letter-spacing: 0.14em; text-transform: uppercase; margin: 0 0 1.2cqh; }
  .vs .exp .k { color: var(--ok); } .vs .rec .k { color: var(--fail); }
  .vs .v { font: 600 3.3cqh/1.25 var(--font-mono); color: var(--fg); margin: 0; overflow-wrap: anywhere; }
  .vs .exp mark { background: color-mix(in oklab, var(--ok) 35%, transparent); color: var(--fg); border-radius: 0.3em; }
  .vs .rec mark { background: color-mix(in oklab, var(--fail) 40%, transparent); color: var(--fg); border-radius: 0.3em; }
  .ferr { font: 500 2.5cqh/1.4 var(--font-mono); color: var(--muted); overflow-wrap: anywhere; }
  .ferr b { color: var(--fail); font-weight: 600; }
  .cons { font: 500 2.4cqh/1.4 var(--font-mono); color: var(--fg); overflow-wrap: anywhere; display: flex; flex-direction: column; gap: 0.6cqh; }
  .cons b { color: #ffb86b; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; }
  .win.failwin { box-shadow: 0 2.4cqh 6cqh rgb(0 0 0 / 0.45), 0 0 0 max(2px, 0.3cqh) var(--fail); }

  /* end card */
  .end .label { margin: 0; }
  .end .viewer { font: 500 2.8cqh/1.3 var(--font-mono); color: var(--muted); margin: 0; }
"""

ARROW = ('<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M4 2 L4 19 L8.6 14.8 L11.6 21.4 L14.4 20.2 '
         'L11.5 13.7 L17.6 13.4 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>')


def _e(s: Any) -> str:
    return rv._e("" if s is None else str(s))


def _fit(ar: float, max_w: float, max_h: float, bar: float = 4.6) -> Tuple[float, float]:
    """(width in cqw, screenshot height in cqh) of a window of aspect `ar` that fits max_w cqw x max_h cqh (bar
    included), on a 16:9 frame."""
    w = max_w
    h = w * 16.0 / 9.0 / ar                  # cqw -> cqh on a 16:9 frame
    if h + bar > max_h:
        h = max_h - bar
        w = h * ar * 9.0 / 16.0
    return round(w, 2), round(h, 2)


def _zoom(box: Optional[Dict[str, float]], point: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
    """How far to push in on a step's target: its box about 45 % of the window wide, at most 1.6x."""
    if not box or box["w"] <= 0:
        return None
    pt = point or {"x": box["x"] + box["w"] / 2, "y": box["y"] + box["h"] / 2}
    z = round(min(1.6, max(1.0, 45.0 / box["w"])), 2)
    return {"x": pt["x"], "y": pt["y"], "z": z} if z > 1.05 else None


def _window(shot: Optional[str], url: str, ar: float, *, left: float, top: float, max_w: float, max_h: float,
            inner: str = "", cls: str = "", typed: bool = False, zoom: Optional[Dict[str, float]] = None) -> str:
    w, h = _fit(ar, max_w, max_h)
    img = '<img src="%s" alt="">' % _e(shot) if shot else '<div class="none">no screenshot in the trace</div>'
    if zoom:
        img = '<div class="zoom" style="transform-origin:%.2f%% %.2f%%;--z:%.2f">%s%s</div>' % (
            zoom["x"], zoom["y"], zoom["z"], img, inner)
        inner = ""
    return ('      <div class="win%s" style="left:%.2fcqw;top:%.2fcqh;width:%.2fcqw">\n'
            '        <div class="bar"><span class="d"><i></i><i></i><i></i></span><span class="u%s">%s</span></div>\n'
            '        <div class="shot" style="height:%.2fcqh">%s%s</div>\n      </div>'
            % (" " + cls if cls else "", left, top, w, " typed" if typed else "", _e(url or "about:blank"), h, img, inner))


def _covers(boxes: Optional[Sequence[Dict[str, float]]]) -> str:
    """Opaque chips over the fields a value was typed into (the screenshot would show it)."""
    return "".join('<div class="cover" style="left:%.2f%%;top:%.2f%%;width:%.2f%%;height:%.2f%%"></div>'
                   % (b["x"], b["y"], b["w"], b["h"]) for b in boxes or ())


def _pips(rep: Dict[str, Any], now: Optional[int]) -> str:
    steps = rep["steps"]
    if len(steps) > 24:
        return ""
    out = []
    for s in steps:
        c = "bad" if s["status"] == "failed" and (now is None or s["n"] <= now) else \
            "now" if s["n"] == now else "ok" if now is not None and s["n"] < now else ""
        out.append('<i class="%s"></i>' % c if c else "<i></i>")
    return '<span class="pips">%s</span>' % "".join(out)


def _marks(parts: Sequence[Sequence[Any]]) -> str:
    return "".join("<mark>%s</mark>" % _e(t) if f else _e(t) for t, f in parts)


def build_page(rep: Dict[str, Any], p: Dict[str, Any], shots: Dict[str, str]) -> str:
    """The film. `shots` maps a trace screenshot to its file in the project (shots/NN.jpeg)."""
    steps = {s["n"]: s for s in rep["steps"]}
    vp = rep["viewport"]
    ar = float(vp["width"]) / float(vp["height"] or 1)
    title = rep["test"]["title"]
    total = len(rep["steps"])
    head = rep["test"]["location"] or title
    out: List[str] = []
    prev = ""
    last_point = {"x": 50.0, "y": 92.0}
    for sc in p["scenes"]:
        sid = sc["id"]
        start = "0" if not prev else "#" + prev
        trans = "" if not prev else ' data-transition="dip %.1f"' % (2 * OUT)
        push = [{"at": 0, "zoom": 1}, {"at": 0.15, "dur": round(max(1.0, sc["dur"] - 0.3), 2), "zoom": 1.04,
                                       "focus": [50, 50], "to": "stay", "ease": "linear"}]
        out.append('  <section class="scene" id="%s" data-start="%s" data-dur="%.2f"%s>\n    <div class="cam" '
                   'data-st="camera" data-path=\'%s\'>' % (sid, start, sc["dur"], trans, json.dumps(push)))
        top = '      <div class="topbar"><p class="label">Repro <b>&middot;</b> %s</p><div class="counter">%s%s</div></div>'
        if sid == "title":
            meta = title_meta(rep)
            out.append('      <div class="tcard">\n        <span class="pill">%s</span>\n        <h1 class="tname">%s</h1>'
                       % ("FAILED" if rep["failure"] else "PASSED", _e(title)))
            if rep["test"]["location"]:
                out.append('        <p class="tloc">%s</p>' % _e(rep["test"]["location"]))
            out.append('        <p class="tmeta">%s</p>\n      </div>' % _e(meta))
        elif sc["kind"] == "step":
            s = steps[sc["step"]]
            out.append(top % (_e(head), '<span><b>%d</b> <em>/ %d</em></span>' % (s["n"], total), _pips(rep, s["n"])))
            inner = [_covers(s.get("covers"))]
            travel = s["kind"] in POINTER_KINDS
            if s["box"]:
                b = s["box"]
                inner.append('<div class="box" style="left:%.2f%%;top:%.2f%%;width:%.2f%%;height:%.2f%%;--at:%.2fs"></div>'
                             % (b["x"], b["y"], b["w"], b["h"], 0.75 if travel else 0.3))
                if s["kind"] in ("fill", "type"):
                    inner.append('<div class="caret" style="left:%.2f%%;top:%.2f%%;height:%.2f%%"></div>'
                                 % (b["x"] + 1.2, b["y"] + b["h"] * 0.22, b["h"] * 0.56))
            if s["point"] and travel:
                pt = s["point"]
                inner.append('<div class="ripple" style="left:%.2f%%;top:%.2f%%;--at:0.75s"></div>' % (pt["x"], pt["y"]))
                inner.append('<div class="cursor" style="--x0:%.2f%%;--y0:%.2f%%;--x:%.2f%%;--y:%.2f%%">%s</div>'
                             % (last_point["x"], last_point["y"], pt["x"], pt["y"], ARROW))
                last_point = dict(pt)
            out.append(_window(shots.get(s["shot"] or ""), s["url"], ar, left=5.5, top=14, max_w=57, max_h=80,
                               inner="".join(inner), typed=s["kind"] == "goto", zoom=_zoom(s["box"], s["point"])))
            kind_cls = " ok" if s["kind"] == "expect" else ""
            out.append('      <div class="side" style="left:%.2fcqw">' % (5.5 + _fit(ar, 57, 80)[0] + 3))
            out.append('        <p class="kind%s" style="--at:0.15s">%s</p>' % (kind_cls, _e(s["kind"])))
            out.append('        <p class="cap" style="--at:0.25s">%s</p>' % _e(s["caption"]))
            if s["locator"]:
                out.append('        <p class="loc" style="--at:0.4s">%s</p>' % _e(s["locator"]))
            where = " \u00b7 ".join(x for x in ("%s:%s" % (s["file"], s["line"]) if s["file"] else "",
                                                "%d ms" % s["duration_ms"]) if x)
            out.append('        <p class="where" style="--at:0.5s">%s</p>\n      </div>' % _e(where))
        elif sid == "skip":
            sk = [steps[n] for n in sc["skipped"]]
            out.append(top % (_e(head), '<span><b>%d&ndash;%d</b> <em>/ %d</em></span>' % (sk[0]["n"], sk[-1]["n"], total),
                              _pips(rep, sk[-1]["n"])))
            out.append('      <div class="skip">\n        <h2 class="head"><em>+ %d</em> passing steps</h2>\n'
                       '        <div class="thumbs" style="--ar:%.4f">' % (len(sk), ar))
            pick = sk if len(sk) <= 6 else [sk[int(round(i * (len(sk) - 1) / 5.0))] for i in range(6)]
            for i, s in enumerate(pick):
                src = shots.get(s["shot"] or "")
                out.append('          <div class="t" style="--at:%.2fs">%s</div>'
                           % (0.2 + 0.08 * i, ('<img src="%s" alt="">' % _e(src) + _covers(s.get("covers"))) if src else ""))
            out.append('        </div>\n        <p class="range">steps %d to %d: %s</p>\n      </div>'
                       % (sk[0]["n"], sk[-1]["n"], _e(", ".join(sorted({x["kind"] for x in sk})))))
        elif sid == "fail":
            f = rep["failure"]
            s = steps.get(f.get("step") or -1)
            beats = fail_beats(rep)
            n = f.get("step")
            out.append(top % (_e(head), ('<span><b>%d</b> <em>/ %d</em></span>' % (n, total)) if n else "",
                              _pips(rep, n)))
            inner = _covers((s or {}).get("covers") if s else f.get("covers"))
            if s and s["box"]:
                b = s["box"]
                inner += ('<div class="box bad" style="left:%.2f%%;top:%.2f%%;width:%.2f%%;height:%.2f%%;--at:0.4s"></div>'
                         % (b["x"], b["y"], b["w"], b["h"]))
            shot = shots.get((s or {}).get("shot") or f.get("shot") or "")
            out.append(_window(shot, (s or {}).get("url", ""), ar, left=5.5, top=14, max_w=41, max_h=80, inner=inner,
                               cls="failwin", zoom=_zoom((s or {}).get("box"), (s or {}).get("point"))))
            out.append('      <div class="fside">')
            where = " \u00b7 ".join(x for x in ("step %d" % n if n else "", "%s:%s" % (f["file"], f["line"]) if f.get("file") else "") if x)
            out.append('        <p class="kind bad" style="--at:0.1s">Failed%s</p>' % (" \u00b7 " + _e(where) if where else ""))
            out.append('        <p class="cap" style="--at:%.2fs">%s</p>' % (beats["caption"], _e(s["caption"] if s else f["headline"])))
            if f.get("source"):
                out.append('        <p class="src" style="--at:%.2fs"><span class="n">%d</span>%s</p>'
                           % (beats["source"], f["source"]["line"], _e(f["source"]["text"])))
            if "vs" in beats:
                exp, got = f.get("expected") or {"parts": [["\u2014", False]]}, f.get("received") or {"parts": [["\u2014", False]]}
                out.append('        <div class="vs" style="--at:%.2fs"><div class="exp"><p class="k">Expected</p><p class="v">%s</p>'
                           '</div><div class="rec"><p class="k">Received</p><p class="v">%s</p></div></div>'
                           % (beats["vs"], _marks(exp["parts"]), _marks(got["parts"])))
            err = " \u00b7 ".join(x for x in [f["headline"]] + f.get("details", [])[:1] if x)
            out.append('        <p class="ferr" style="--at:%.2fs"><b>Error</b> %s</p>' % (beats["error"], _e(err)))
            if rep["console"]:
                items = "".join("<span>%s</span>" % _e(rv.shorten(c["text"], 90)) for c in rep["console"][:2])
                more = len(rep["console"]) - 2
                out.append('        <p class="cons" style="--at:%.2fs"><b>Console error%s</b>%s%s</p>'
                           % (beats["console"], "s" if len(rep["console"]) > 1 else "", items,
                              "<span>+ %d more</span>" % more if more > 0 else ""))
            out.append("      </div>")
        else:
            out.append('      <div class="end">\n        <p class="label" style="--i:0">%s</p>'
                       % ("Re-run" if p["rerun"] else "Open the trace"))
            i = 1
            if p["rerun"]:
                out.append('        <div class="cta" data-st="fit" style="--i:1"><span class="ps">$ </span>%s</div>' % _e(p["rerun"]))
                i += 1
            if p.get("viewer"):
                out.append('        <p class="viewer" style="--i:%d">%s%s</p>' % (
                    i, "Trace: " if p["rerun"] else "$ ", _e(p["viewer"])))
                i += 1
            out.append('        <p class="thanks" style="--i:%d">%s</p>\n      </div>'
                       % (i, _e(" \u00b7 ".join(x for x in (title, rep["test"]["location"]) if x))))
        out.append("    </div>\n  </section>")
        prev = sid
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>%s</title>\n"
            "<script src=\"/_st/stage.js\"></script>\n<link rel=\"stylesheet\" href=\"/_st/themes/neutral.css\">\n"
            "<script type=\"module\" src=\"/_st/components/index.js\"></script>\n<!-- Written by `showtime repro` from a "
            "Playwright trace and the script.md you read: typed values, query strings, paths and --redact matches "
            "are masked; the screenshots are the trace's own (typed fields covered). Edit freely. -->\n"
            "<style>%s</style>\n</head>\n<body>\n<div class=\"stage\">\n  <div class=\"world\" data-st-decor><div class=\"key\">"
            "</div><div class=\"vig\"></div></div>\n%s\n</div>\n</body>\n</html>\n" % (_e("Repro: " + title), CSS, "\n".join(out)))


def bed_for(p: Dict[str, Any], rep: Dict[str, Any], voice_tracks: Sequence[Dict[str, Any]] = (),
            music: Optional[str] = None, fetch: bool = False, project: Optional[Path] = None) -> Dict[str, Any]:
    """This film's bed (st.bed): chosen from the test, so a rerun sounds the same and another test does not."""
    starts = [sc["start"] for sc in p["scenes"]]
    names = ["intro"] + ["verse"] * max(0, len(starts) - 2) + ["outro"]
    t = rep["test"]
    return bed.choose("repro", "%s|%s" % (t.get("title") or "", t.get("file") or ""), float(p.get("duration") or 0),
                      ",".join("%g:%s" % (s, n) for s, n in zip(starts, names)), pin=music,
                      project=project, gain_db=-6 if voice_tracks else -3,
                      duck={"under": "voice", "depth_db": bed.DUCK_DEPTH_DB, "carve": 0.4} if voice_tracks else None, fetch=fetch)


def build_mix(p: Dict[str, Any], rep: Dict[str, Any], voice_tracks: Sequence[Dict[str, Any]] = (),
              choice: Optional[Dict[str, Any]] = None, cut_sounds: bool = False) -> Dict[str, Any]:
    """A quiet bed (ducked under the voice), a click on each click, a soft error tone on the failure (sounds that
    mark what happens on screen; a soft swoosh on each cut only with cut_sounds); the bed and the sounds differ
    from test to test."""
    steps = {s["n"]: s for s in rep["steps"]}
    t = rep["test"]
    key = "%s|%s" % (t.get("title") or "", t.get("file") or "")
    choice = choice or bed_for(p, rep, voice_tracks)
    tracks: List[Dict[str, Any]] = [choice["track"]] if choice["track"] else []
    tone = choice.get("key")                                 # a composed bed's key: tonal effects stay in it
    cut_duck = {"duck": {"under": "voice", "depth_db": 6}} if voice_tracks else {}
    for sc in p["scenes"][1:]:
        if cut_sounds:
            tracks.append({"kind": "sfx", "synth": bed.synth(key, "cut", int(sc["start"]), 0.25, tone),
                           "at": sc["start"], "align": "hit", "gain_db": bed.CUT_GAIN_DB, **cut_duck})
        s = steps.get(sc.get("step") or -1)
        if sc["kind"] == "step" and s and s["kind"] in ("click", "dblclick", "check", "uncheck") and s["point"]:
            tracks.append({"kind": "sfx", "synth": bed.synth(key, "click", s["n"], 0.5, tone),
                           "at": round(sc["start"] + 0.75, 2), "align": "hit", "gain_db": -10})
        if sc["id"] == "fail":
            tracks.append({"kind": "sfx", "synth": bed.synth(key, "error", 9, 0.35, tone),
                           "at": round(sc["start"] + 0.3, 2), "align": "hit", "gain_db": -12})
    tracks += list(voice_tracks)
    return {"_comment": bed.comment(choice, any(t.get("kind") == "sfx" for t in tracks)),
            "sample_rate": 48000, "tracks": tracks, "master": {"lufs": -14, "true_peak": -1}}


SIZES = {"1080p": (1920, 1080), "720p": (1280, 720)}


def keep_shots(trace: Path, rep: Dict[str, Any], dest: Path) -> int:
    """Copy every screenshot the report points at out of the trace into dest (NN.<ext>) and point the report at
    them (`shots/NN.<ext>`), so the film can be made after the raw trace is gone."""
    names: List[str] = []
    for s in rep["steps"]:
        if s.get("shot") and s["shot"] not in names:
            names.append(s["shot"])
    f = rep["failure"]
    if f and f.get("shot") and f["shot"] not in names:
        names.append(f["shot"])
    got: Dict[str, str] = {}
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(trace)) as z:
        sizes = {i.filename: i.file_size for i in z.infolist()}
        for member in names:
            if member not in sizes or sizes[member] > MAX_SHOT:
                continue
            ext = os.path.splitext(member)[1].lower()
            ext = ext if ext in (".jpeg", ".jpg", ".png", ".webp") else ".jpeg"
            dst = "%02d%s" % (len(got) + 1, ext)
            with z.open(member) as src, open(str(dest / dst), "wb") as out:
                shutil.copyfileobj(src, out)
            got[member] = "shots/" + dst
    for s in rep["steps"]:
        s["shot"] = got.get(s.get("shot") or "")
    if f:
        f["shot"] = got.get(f.get("shot") or "")
    return len(got)


def write_project(out: Path, rep: Dict[str, Any], p: Dict[str, Any], job: Path, *, size: str = "1080p",
                  voice_tracks: Sequence[Dict[str, Any]] = (), force: bool = False, music: Optional[str] = None,
                  fetch: bool = False, cut_sounds: bool = False) -> Dict[str, Any]:
    """index.html, showtime.json, audio/mix.json, shots/ (the screenshots the film uses, from the job's shots/)
    and repro.json (what steps.json holds: no path on the machine)."""
    out = Path(out)
    if out.exists() and any(x for x in out.iterdir() if x.name != "voice") and not force:
        raise FileExistsError(str(out))
    used: List[str] = []
    steps = {s["n"]: s for s in rep["steps"]}
    for sc in p["scenes"]:
        for n in [sc.get("step")] + list(sc.get("skipped") or []):
            s = steps.get(n or -1)
            if s and s["shot"] and s["shot"] not in used:
                used.append(s["shot"])
    if rep["failure"] and rep["failure"].get("shot") and rep["failure"]["shot"] not in used:
        used.append(rep["failure"]["shot"])
    shots: Dict[str, str] = {}
    (out / "shots").mkdir(parents=True, exist_ok=True)
    for name in used:
        src = Path(job) / name
        if src.is_file():
            shutil.copyfile(str(src), str(out / name))
            shots[name] = name
    w, h = SIZES.get(size, SIZES["1080p"])
    fail = next((sc for sc in p["scenes"] if sc["id"] == "fail"), None)
    poster_t = round(fail["start"] + fail["dur"] - 1.0, 2) if fail else 0
    cfg = {"title": "Repro: %s" % rep["test"]["title"], "width": w, "height": h, "fps": 30, "duration": p["duration"],
           "background": "#0e1013", "poster": poster_t, "audio": "audio/mix.json",
           "subtitle": "A failing browser test, step by step.", "kicker": "Repro", "startTitle": False,
           "render": {"crf": 22, "poster_bake": "off"},
           "expect": {"duration": p["duration"], "audio": True, "must_show": ["FAILED" if rep["failure"] else "PASSED"]}}
    choice = bed_for(p, rep, voice_tracks, music, fetch, out)
    rv.write_files(out, page=build_page(rep, p, shots), cfg=cfg, mix=build_mix(p, rep, voice_tracks, choice, cut_sounds),
                   source_name="repro.json", source=steps_json(rep, p), force=True)
    return {"project": str(out), "duration": p["duration"], "scenes": len(p["scenes"]), "shots": len(shots),
            "poster_at": poster_t, "bed": choice}


def steps_json(rep: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
    """steps.json: the parsed timeline (redacted) and where each step is in the film."""
    at = {}
    for sc in p["scenes"]:
        for n in [sc.get("step")] + list(sc.get("skipped") or []):
            if n:
                at[n] = {"scene": sc["id"], "at": sc["start"], "dur": sc["dur"]}
    steps = []
    for s in rep["steps"]:
        d = {k: v for k, v in s.items() if k not in ("shot",)}
        d["film"] = at.get(s["n"])
        steps.append(d)
    fail = dict(rep["failure"]) if rep["failure"] else None
    if fail:
        fail.pop("shot", None)
    return {"generator": "showtime repro", "test": rep["test"], "status": rep["status"], "browser": rep["browser"],
            "playwright": rep["playwright"], "language": rep["language"], "duration_s": rep["duration_s"],
            "viewport": rep["viewport"], "steps": steps, "failure": fail, "console": rep["console"],
            "console_more": rep.get("console_more", 0), "rerun": p.get("rerun") or "", "privacy": rep["privacy"],
            "film": {"duration": p["duration"], "scenes": [{k: sc[k] for k in ("id", "start", "dur")} for sc in p["scenes"]],
                     "skipped_steps": p["skipped_steps"]}}


def markdown(rep: Dict[str, Any], p: Dict[str, Any], video_name: str = "repro.mp4", music_credit: str = "") -> str:
    """repro.md: the steps, the failure and how to re-run, to paste into an issue or a PR."""
    f = rep["failure"]
    t = rep["test"]
    lines = ["### Repro: %s (%s)" % (t["title"], "FAILED" if f else "PASSED"), ""]
    meta = " \u00b7 ".join(x for x in ("`%s`" % t["location"] if t["location"] else "", rep["browser"],
                                       "Playwright %s" % rep["playwright"] if rep["playwright"] else "") if x)
    if meta:
        lines += [meta, ""]
    lines += ["<!-- drag %s onto this line: GitHub uploads it and puts the video player here -->" % video_name, "",
              "**Steps**", ""]
    for s in rep["steps"]:
        where = " (`%s:%s`)" % (s["file"], s["line"]) if s["file"] and s["line"] else ""
        text = s["caption"].replace("`", "'")
        lines.append("%d. %s%s%s%s" % (s["n"], "**FAILED:** " if s["status"] == "failed" else "", text, where,
                                       " (an error the test caught)" if s.get("caught") else ""))
    if f:
        lines += ["", "**Failure**", "", "```"]
        lines.append(f["headline"])
        if f.get("expected"):
            lines.append("Expected: %s" % f["expected"]["text"])
        if f.get("received"):
            lines.append("Received: %s" % f["received"]["text"])
        for d in f.get("details") or []:
            lines.append(d)
        if f.get("call_log"):
            lines.append("Last log: %s" % f["call_log"])
        lines.append("```")
        if f.get("source"):
            lines += ["", "At `%s:%s`:" % (f["file"], f["source"]["line"]), "", "```", f["source"]["text"], "```"]
    if rep["console"]:
        lines += ["", "**Console errors**", ""] + ["- %s" % c["text"].replace("\n", " ") for c in rep["console"][:10]]
    run = [x for x in (p.get("rerun"), p.get("viewer")) if x]
    if run:
        lines += ["", "**Re-run**", "", "```"] + run + ["```"]
    if music_credit:
        lines += ["", "Music: %s" % music_credit.strip()]
    lines += ["", "<sub>Made with `showtime repro`: typed values are never shown; paths, query strings, secret-looking "
              "text, e-mail addresses and --redact matches are masked. Screenshots are shown as they were captured "
              "(typed fields covered); --redact does not touch pixels.</sub>", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# the review gate: script.md
# ---------------------------------------------------------------------------

SCRIPT_HEAD = """# showtime repro: the film's script

Every line the film will show or speak, from the trace, after the filters. Edit the text after a label, or
delete a line to leave it out, then run the same command again with --yes (or: showtime repro --yes <job>).
Every line goes through the filters again then. Filters can miss things: read every line before you render.
Screenshots are shown as captured (fields a value was typed into are covered); --redact does not touch
pixels. Watch the film before you post it.
"""

_SCRIPT_LINE = re.compile(r"^(show|say)\s+([a-z][\w.-]*)\s*:\s?(.*)$")


def _where(file: str, line: Any) -> str:
    return "%s:%s" % (file, line) if file and line else (file or "")


def script_fields(rep: Dict[str, Any], rerun: str, viewer: str) -> List[Tuple[str, str, str, str]]:
    """[(section, show|say, key, text)]: every text the film, the captions, steps.json and repro.md use."""
    t, f = rep["test"], rep["failure"]
    out = [("title", "show", "test.title", t["title"]), ("title", "show", "test.location", t["location"]),
           ("title", "say", "title", title_line(rep))]
    for s in rep["steps"]:
        sec = "step %d" % s["n"]
        out += [(sec, "show", "step%d.caption" % s["n"], s["caption"]),
                (sec, "show", "step%d.locator" % s["n"], s["locator"]),
                (sec, "show", "step%d.url" % s["n"], s["url"]),
                (sec, "show", "step%d.where" % s["n"], _where(s["file"], s["line"]))]
        if s.get("expected") is not None:
            out.append((sec, "show", "step%d.expected" % s["n"], s["expected"]))
        if s.get("value") is not None:
            out.append((sec, "show", "step%d.value" % s["n"], s["value"]))
        if s.get("matcher"):
            out.append((sec, "show", "step%d.matcher" % s["n"], s["matcher"]))
        out.append((sec, "say", "step%d" % s["n"], step_line(s)))
    out.append(("passing steps summed up (when the film is long)", "say", "skip", SKIP_LINE))
    if f:
        out += [("failure", "show", "fail.headline", f["headline"])]
        for k in ("expected", "received"):
            if f.get(k):
                out.append(("failure", "show", "fail.%s" % k, f[k]["text"]))
        out += [("failure", "show", "fail.detail%d" % (i + 1), d) for i, d in enumerate(f.get("details") or [])]
        if f.get("call_log"):
            out.append(("failure", "show", "fail.call_log", f["call_log"]))
        if f.get("source"):
            out.append(("failure", "show", "fail.source", f["source"]["text"]))
        out.append(("failure", "show", "fail.where", _where(f.get("file") or "", f.get("line"))))
    out += [("failure", "show", "console%d" % (i + 1), c["text"]) for i, c in enumerate(rep["console"])]
    if f:
        out.append(("failure", "say", "fail", fail_line(rep)))
    out += [("end", "show", "end.rerun", rerun), ("end", "show", "end.viewer", viewer),
            ("end", "say", "end", end_line(rerun))]
    return [x for x in out if x[3] or x[1] == "say"]


def write_script(rep: Dict[str, Any], rerun: str, viewer: str) -> str:
    """script.md: the keyed lines by section, then what was masked (comments)."""
    out = [SCRIPT_HEAD]
    sec = None
    for section, kind, key, text in script_fields(rep, rerun, viewer):
        if section != sec:
            sec = section
            out.append("\n## %s\n" % section)
            if section == "title":
                out.append("# also shown: FAILED, %s" % title_meta(rep))
        out.append("%s %s: %s" % (kind, key, " ".join(str(text).split())))
    masked = [s for s in rep["steps"] if s.get("masked") or s.get("covers") and s["kind"] in TYPED_KINDS]
    out.append("\n## masked\n")
    if not masked and not rep["privacy"].get("redact_patterns"):
        out.append("# nothing was typed into a field")
    for s in masked:
        on = [o["n"] for o in rep["steps"] if any(c.get("step") == s["n"] for c in o.get("covers") or [])]
        if s.get("field_known") is False:
            what = " (typed into a field showtime cannot name, so it counts as secret)"
        else:
            what = " (a secret field)" if s.get("secret_field") else ""
        out.append("# step %d: %s%s; the value is not shown or spoken; %s" % (
            s["n"], s["caption"], what, "its field is covered on screen in steps %s" % _ranges(on) if on else
            "it is NOT covered on screen (the field is not known): check the screenshots"))
    if masked:
        out.append("# a cover follows its field through the trace's page snapshots (shown while the field holds text, "
                   "moved with the scroll); a fixed or animated field can still slip out from under it")
    if rep["privacy"].get("redact_patterns"):
        out.append("# %d --redact pattern%s applied" % (rep["privacy"]["redact_patterns"],
                                                      "" if rep["privacy"]["redact_patterns"] == 1 else "s"))
    out.append("# screenshots are shown as captured; --redact does not touch pixels")
    return "\n".join(out) + "\n"


def _ranges(ns: Sequence[int]) -> str:
    """[2, 3, 4, 7] -> "2-4, 7"."""
    out: List[str] = []
    for n in sorted(set(ns)):
        if out and int(out[-1].split("-")[-1]) == n - 1:
            out[-1] = "%s-%d" % (out[-1].split("-")[0], n)
        else:
            out.append(str(n))
    return ", ".join(out)


def read_script(text: str) -> Dict[str, Tuple[str, str]]:
    """{key: (show|say, text)} from a script.md, edits included; unknown lines are ignored."""
    out: Dict[str, Tuple[str, str]] = {}
    for raw in (text or "").splitlines():
        m = _SCRIPT_LINE.match(raw.strip())
        if m:
            out[m.group(2)] = (m.group(1), " ".join(m.group(3).split()))
    return out


def apply_script(rep: Dict[str, Any], rerun: str, viewer: str, lines: Dict[str, Tuple[str, str]],
                 redact: "Redactor") -> Tuple[Dict[str, Any], str, str]:
    """The report as script.md leaves it: each listed text replaced by its line (a deleted line: empty), every
    text derived from one rebuilt from it (a step's target from its locator, the test's file and line from its
    location), and every text, edited or not, through the hard filter again."""
    rep = json.loads(json.dumps(rep))
    got = lambda key: redact(lines[key][1]) if key in lines else ""  # noqa: E731
    t, f = rep["test"], rep["failure"]
    t["title"], t["location"] = got("test.title"), got("test.location")
    t["file"], t["line"] = _split_where(t["location"])
    for k in ("browser", "playwright", "language"):
        rep[k] = redact(rep.get(k))
    for s in rep["steps"]:
        n = s["n"]
        was = redact(s["locator"])
        s["caption"], s["locator"], s["url"] = got("step%d.caption" % n), got("step%d.locator" % n), got("step%d.url" % n)
        s["target"] = redact(s.get("target")) if s["locator"] == was else redact(human_locator(s["locator"]))
        wf, wl = _split_where(got("step%d.where" % n))
        s["file"], s["line"] = wf, wl
        if s.get("expected") is not None:
            s["expected"] = got("step%d.expected" % n)
        s["value"] = (got("step%d.value" % n) or None) if s.get("value") is not None else None
        s["matcher"] = got("step%d.matcher" % n) if s.get("matcher") else ""
    if f:
        f["headline"] = got("fail.headline")
        for k in ("expected", "received"):
            if f.get(k):
                new = got("fail.%s" % k)
                if new != f[k]["text"] or redact(f[k]["text"]) != f[k]["text"] or \
                        "".join(str(x[0]) for x in f[k].get("parts") or []) != new:
                    f[k] = {"text": new, "parts": [[new, False]], "kind": f[k].get("kind", "")}
        f["details"] = [x for x in (got("fail.detail%d" % (i + 1)) for i in range(len(f.get("details") or []))) if x]
        f["call_log"] = got("fail.call_log")
        if f.get("source"):
            f["source"]["text"] = got("fail.source")
            if not f["source"]["text"]:
                f["source"] = None
        f["file"], f["line"] = _split_where(got("fail.where"))
    rep["console"] = [dict(c, text=got("console%d" % (i + 1))) for i, c in enumerate(rep["console"])]
    rep["console"] = [c for c in rep["console"] if c["text"]]
    rep["say"] = {key: redact(text) for key, (kind, text) in lines.items() if kind == "say"}
    for sid in ["title", "skip", "end"] + ["step%d" % s["n"] for s in rep["steps"]] + (["fail"] if f else []):
        rep["say"].setdefault(sid, "")                     # a deleted spoken line leaves its scene silent
    return rep, got("end.rerun"), got("end.viewer")


def _split_where(text: str) -> Tuple[str, Optional[int]]:
    m = re.match(r"^(.*?):(\d+)$", text or "")
    return (m.group(1), int(m.group(2))) if m else (text or "", None)
