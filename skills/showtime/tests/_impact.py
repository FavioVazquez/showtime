"""Test impact map for `run_all.py --changed`: which test files a set of changed files can affect.

Two sources, combined per test file:

1. Recorded use (primary). While run_all.py runs a test file it records every repository file that the test's
   Python and Node processes import or open (tests/_trace/: an audit hook loaded through PYTHONPATH, an
   `--import` hook through NODE_OPTIONS). Each passing run adds its list to ~/.showtime/cache/test-impact.json
   (per mode: fast / full; a file stays listed until the test has not used it for TRACE_KEEP_RUNS runs, so a
   code path a warm cache skipped once is still known). This is what a test really runs: a test that only imports the launcher does not depend on everything `showtime doctor` checks.
2. Static scan (fallback, and for files no process opens: fixtures ffmpeg reads, templates by name). Built on
   the fly, nothing under test is imported:
   - Python imports (AST, including imports inside functions); dotted module names in strings (`-m st.cli`)
   - JavaScript imports (import/export ... from, import(), require()) resolved relative to the file
   - paths named in the source: "scripts/lib/chrome.mjs", `SKILL / "runtime" / "film.js"`,
     `path.join(SKILL, 'lib', 'st', 'launcher.py')`, "/_st/components/index.js" in HTML and CSS ...
     matched against the repository's files by their trailing folders and name
   - the CLI routing convention: `showtime <cmd>` runs scripts/<cmd>.mjs when it exists, else the
     lib/st/cli_<module>.py whose COMMANDS name it. A command name in a test file, a Node script's
     runPyCli(['audio', ...]) or a Python call next to the launcher is a use of that command; a template
     name in a test file ("dom", "film" ...) uses templates/<name>/
   - OVERRIDES below for what neither source sees (docs, manifests, CI files)

A test file is picked for a changed file when its recorded use contains it, when the test file names it
directly (one static step), or through an override. A test file with no recorded run for the mode uses the
whole static closure instead. A changed file no recorded run used falls back to the static closure of every
test; one that nothing reaches cannot be placed, and then every test runs (the safe default, reported with
the file that caused it). test_skill_structure (release hygiene: it scans every shipped file for names,
paths, links and versions) runs whenever anything changed.

Stdlib only. Per-file scan results are cached by size and mtime (~/.showtime/cache/test-impact-scan.json).
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import shutil
import subprocess
from collections import deque
from pathlib import Path, PurePosixPath

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
REPO = SKILL_DIR.parent.parent
TRACE_DIR = TESTS_DIR / "_trace"

SKILL = "skills/showtime"           # repository-relative, POSIX separators everywhere below
TESTS = SKILL + "/tests"

# integration branches, in order: the default base of --changed is the merge-base with the first that exists
BASE_REFS = ("v0.2.0", "origin/v0.2.0", "main", "origin/main")

# runs whenever anything changed (a few seconds): check_release.py scans every shipped file
HYGIENE_TEST = "test_skill_structure.py"

# Files and folders the scans do not reach, with the tests that cover them. A pattern matches a
# repository-relative path (fnmatch; "dir/**" = anything below dir, "dir/**/*.md" = those names below dir).
# An empty list places the file without adding tests: only the hygiene test (versions, banned names,
# machine paths, links) covers it. Every matching rule adds its tests.
OVERRIDES = [
    # the test runner itself
    (TESTS + "/run_all.py", ["test_run_all.py", "test_skill_structure.py"]),
    (TESTS + "/_impact.py", ["test_run_all.py"]),
    (TESTS + "/_split.py", ["test_run_all.py"]),
    (TESTS + "/_part.py", ["test_run_all.py"]),
    (TESTS + "/_trace/**", ["test_run_all.py"]),
    # skill instructions and references: link, command and frontmatter checks, plus the tests that read them
    (SKILL + "/SKILL.md", ["test_skill_structure.py", "test_mcp.py"]),
    (SKILL + "/references/**", ["test_skill_structure.py", "test_film.py"]),
    (SKILL + "/templates/**/*.md", ["test_film.py", "test_foundation.py"]),
    # commands are discovered by name (st.cli, launcher help, check_release): the help listing and the
    # command check
    (SKILL + "/lib/st/cli_*.py", ["test_foundation.py", "test_skill_structure.py"]),
    (SKILL + "/lib/st/cli.py", ["test_foundation.py"]),
    (SKILL + "/scripts/*.mjs", ["test_foundation.py", "test_skill_structure.py"]),
    # launch shims and setup: the shim tests and the setup manifest checks. A dependency bump
    # (requirements*, package*.json) only takes effect after `showtime setup`: re-run setup, then the suite.
    (SKILL + "/bin/**", ["test_foundation.py", "test_mcp.py"]),
    (SKILL + "/setup/**", ["test_foundation.py"]),
    # plugin wiring
    (".claude-plugin/**", ["test_mcp.py", "test_skill_structure.py"]),
    ("monitors/**", ["test_mcp.py"]),
    ("hooks/**", ["test_receipt.py"]),
    ("agents/**", ["test_skill_structure.py"]),
    ("scripts/check_release.py", ["test_skill_structure.py"]),
    ("scripts/publish_media.py", ["test_skill_structure.py"]),
    ("scripts/render_speed.py", ["test_render_speed.py"]),   # the before/after render timing script (run by hand)
    # MCP distribution packages (MCP Registry entry, npm wrapper, agent install guide)
    ("server.json", ["test_packages.py", "test_skill_structure.py"]),
    ("packages/**", ["test_packages.py"]),
    ("llms-install.md", ["test_packages.py"]),
    # repository files no test runs: hygiene only
    ("*.md", []),
    ("LICENSE", []),
    (".gitignore", []),
    (".gitattributes", ["test_skill_structure.py"]),
    (".out-of-scope/**", []),
    (".github/**", []),            # CI definitions: exercised by CI itself, not by the local suite
    ("docs/**", []),
    # the guides for people: their shape and sidebar, their search entries, their commands and links (check_release)
    ("docs/guides/**", ["test_site_build.py", "test_site_search.py", "test_skill_structure.py"]),
    ("site/**", ["test_site_search.py"]),   # the site build and its search (imports site/build.py by path)
    ("site/build.py", ["test_site_build.py"]),     # raw HTML in the docs and the build check
    ("examples/**", []),
    ("assets/readme/**", []),
    ("assets/brand/**", []),
    ("benchmarks/**", []),
    ("benchmarks/scoring/**", ["test_bench_judge.py"]),   # the judge's proof that it opened the frames
    # the behaviour scoreboard: the plugin-eval cases, their offline graders, scoreboard.py and the README block
    ("benchmarks/plugin-eval/**", ["test_bench_scoreboard.py"]),
    ("benchmarks/scoring/scoreboard.py", ["test_bench_scoreboard.py"]),
    ("benchmarks/scoring/eval_graders.py", ["test_bench_scoreboard.py"]),
    ("benchmarks/scoring/stream_cost.py", ["test_bench_scoreboard.py"]),
    ("README.md", ["test_bench_scoreboard.py"]),
]

# Override rules that replace the scans: a changed file matching one runs exactly these tests (plus any OVERRIDES
# rule it also matches, and the hygiene test), not every test whose recorded run or static closure contains it.
# For modules every CLI run loads but only a few tests exercise: st.cli imports each cli_*.py to build the parser
# (a module that fails to import becomes stub commands, so it cannot break the others), so every recorded run of
# any command "uses" cli_release.py.
OVERRIDES_ONLY = [
    (SKILL + "/lib/st/cli_release.py", ["test_release_video.py", "test_pr_video.py", "test_action.py"]),
    (SKILL + "/lib/st/release_video.py", ["test_release_video.py", "test_pr_video.py", "test_action.py"]),
    (SKILL + "/lib/st/pr_video.py", ["test_pr_video.py"]),
]

SCAN_EXT = (".py", ".mjs", ".js", ".cjs", ".html", ".css", ".json")
# the runner's own files: placed by OVERRIDES, never scanned (they name paths of every kind)
NOT_SCANNED = {TESTS + "/run_all.py", TESTS + "/_impact.py", TESTS + "/_split.py", TESTS + "/_part.py",
               TESTS + "/test_run_all.py"}
# The runner's machinery that every recorded run opens (the part runner, the recording hooks): recorded use
# of these says nothing about a test, so it is dropped; OVERRIDES places them.
def is_runner_file(rel: str) -> bool:
    return rel in NOT_SCANNED or rel.startswith(TESTS + "/_trace/")


# lazy imports that only route a command (`showtime doctor` -> st.doctor): the command rule models them,
# so a test that merely imports the launcher does not depend on everything the doctor checks
DISPATCH_ONLY = {SKILL + "/lib/st/launcher.py": {SKILL + "/lib/st/doctor.py", SKILL + "/setup/setup.py"}}
# what a scanned name can point at: the skill, the release scripts and the plugin wiring (examples, site and
# README art are never code a test runs)
TARGET_AREAS = (SKILL + "/", "scripts/", ".claude-plugin/", "monitors/")
# a lone file name (no folder) identifies only code; data and media names ("timeline.json", "poster.jpg")
# are output names every module mentions
LONE_NAME_EXT = (".py", ".mjs", ".js", ".cjs", ".css")
# code file names too common to identify a file without its folder
COMMON_NAMES = {"index.js", "index.mjs", "__init__.py", "episode.js", "scenes.js", "cues.js", "score.js", "kit.js",
                "app.js", "opener.js"}
PATH_RE = re.compile(r"(?<![\w@.$-])((?:[\w@.-]+/)*[\w@-][\w@.-]*\.(?:mjs|cjs|js|py|json|html|css|md|txt|wav|mp3|"
                     r"svg|png|jpg|woff2|ttf|onnx|sf2|srt|vtt|ass|pdf|mp4))(?![\w/])")
JS_IMPORT_RE = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*|new\s+URL\s*\(\s*)['"]([^'"\n]+)['"]""")
JS_JOIN_RE = re.compile(r"\bpath\.(?:join|resolve)\s*\(([^()]*)\)")
JS_STR_RE = re.compile(r"""['"]([^'"\n]*)['"]""")
JS_CMD_RE = re.compile(r"""\[\s*['"]([a-z][\w-]*)['"]""")
DOTTED_RE = re.compile(r"^(st|st_manim)(\.\w+)+$")
WORD_RE = re.compile(r"^[a-z][\w-]{0,30}$")
SCAN_VERSION = 1


# ------------------------------------------------------------------ repository files

def git(root: Path, *args, timeout=30):
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        cp = subprocess.run([exe, "-C", str(root)] + list(args), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


def repo_files(root: Path = REPO) -> list:
    """Repository-relative POSIX paths of every file git knows about (tracked + untracked, not ignored);
    a walk of the folder when git is missing."""
    out = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if out is not None:
        return sorted({f for f in out.split("\0") if f and (root / f).is_file()})
    files = []
    for d, dirs, names in os.walk(str(root)):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__")]
        for n in names:
            files.append(Path(d, n).relative_to(root).as_posix())
    return sorted(files)


# ------------------------------------------------------------------ per-file references (cacheable)

def extract(rel: str, text: str) -> list:
    """The references one source file makes, independent of the rest of the repository (so they can be
    cached by the file's size and mtime): [kind, value, ...] lists, resolved later by ImpactMap."""
    refs = [["p", m.group(1).split("/"), False] for m in PATH_RE.finditer(text)]
    if rel.endswith(".py"):
        refs += _extract_py(rel, text)
    elif rel.endswith((".mjs", ".js", ".cjs")):
        refs += _extract_js(rel, text)
    return refs


def _extract_py(rel: str, text: str) -> list:
    refs = []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return refs
    is_test = rel.startswith(TESTS + "/")
    pkg = _py_package(rel)
    names = _module_chains(tree)                # NAME = SKILL / "runtime" -> ["runtime"]
    nodes = list(ast.walk(tree))
    inner = set()                               # operands of a path chain: only whole chains count
    for node in nodes:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            inner.add(id(node.left))
            inner.add(id(node.right))
    words = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for a in node.names:
                refs.append(["m", a.name])
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".") if pkg else []
                if node.level > 1:
                    up = up[: len(up) - node.level + 1]
                base = ".".join(up + ([base] if base else []))
            if base:
                refs.append(["m", base])
                for a in node.names:
                    refs.append(["m", base + "." + a.name])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if DOTTED_RE.match(s):
                refs.append(["m", s])
            if is_test and WORD_RE.match(s):
                words.add(s)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and id(node) not in inner:
            chain = _chain(node, names)
            if chain:
                refs.append(["p", chain, True])
        elif isinstance(node, ast.Call):
            fn = _call_name(node.func)
            if fn in ("join", "joinpath", "Path", "PurePath", "PurePosixPath"):
                chain = []
                for a in node.args:
                    chain += _chain(a, names)
                if isinstance(node.func, ast.Attribute) and fn == "joinpath":
                    chain = _chain(node.func.value, names) + chain
                if chain:
                    refs.append(["p", chain, True])
        if not is_test and isinstance(node, (ast.List, ast.Tuple, ast.Call)):
            # ["python", LAUNCHER, "site", "capture", ...]: a command run through the launcher
            elts = node.elts if isinstance(node, (ast.List, ast.Tuple)) else node.args
            if any(not isinstance(e, ast.Constant) and ("launcher" in ast.dump(e).lower() or "st.cli" in ast.dump(e))
                   for e in elts):
                for e in elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str) and WORD_RE.match(e.value):
                        refs.append(["c", e.value])
    refs += [["w", w] for w in sorted(words)]
    return refs


def _extract_js(rel: str, text: str) -> list:
    refs = []
    here = PurePosixPath(rel).parent
    for m in JS_IMPORT_RE.finditer(text):
        spec = m.group(1)
        if spec.startswith("."):
            refs.append(["f", _normpath(str(here / spec))])
        elif spec.startswith("/"):
            refs.append(["p", spec.split("/"), False])
    for m in JS_JOIN_RE.finditer(text):
        parts = JS_STR_RE.findall(m.group(1))
        if parts:
            refs.append(["p", parts, True])
    if rel.startswith((SKILL + "/scripts/", SKILL + "/mcp/")):
        for m in JS_CMD_RE.finditer(text):
            refs.append(["c", m.group(1)])
    return refs


# ------------------------------------------------------------------ the static graph

class ImpactMap:
    """Static edges file -> files it uses, over the repository's files."""

    def __init__(self, files: list, root: Path = REPO, reader=None, cache: Path = None):
        self.root = root
        self.files = sorted(set(files))
        self.fileset = set(self.files)
        self.read = reader or (lambda rel: (root / rel).read_text(encoding="utf-8", errors="replace"))
        self.by_name: dict = {}
        self.dirs: dict = {}                    # dir -> files below it (any depth)
        for f in self.files:
            if not f.startswith(TARGET_AREAS):
                continue
            self.by_name.setdefault(PurePosixPath(f).name.lower(), []).append(f)
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.setdefault("/".join(parts[:i]), []).append(f)
        scanned = [f for f in self.files
                   if f.endswith(SCAN_EXT) and f.startswith((SKILL + "/", "scripts/")) and f not in NOT_SCANNED]
        self.refs = self._load_refs(scanned, cache, use_stat=reader is None)
        self.commands = self._commands()
        self.templates = sorted({f.split("/")[3] for f in self.files
                                 if f.startswith(SKILL + "/templates/") and f.count("/") >= 4})
        self.edges: dict = {}
        for f in scanned:
            out = self._resolve(f, self.refs.get(f, [])) - {f} - DISPATCH_ONLY.get(f, set())
            if not f.startswith(TESTS + "/"):     # only tests (and their helpers) use test files
                out = {g for g in out if not g.startswith(TESTS + "/") or g.startswith(TESTS + "/fixtures/")}
            # a test file is never something another file uses, and the runner's own files are placed by
            # OVERRIDES (a test that names one in a comment does not run it)
            out = {g for g in out if not is_runner_file(g) and not (g.startswith(TESTS + "/test_")
                                                                   and "/" not in g[len(TESTS) + 1:])}
            self.edges[f] = out

    def _load_refs(self, scanned: list, cache, use_stat: bool) -> dict:
        old = {}
        if cache is not None:
            try:
                d = json.loads(Path(cache).read_text(encoding="utf-8"))
                if d.get("version") == SCAN_VERSION and d.get("root") == str(self.root):
                    old = d.get("files", {})
            except (OSError, ValueError, AttributeError):
                old = {}
        out, new, dirty = {}, {}, False
        for f in scanned:
            key = None
            if use_stat:
                try:
                    st = (self.root / f).stat()
                except OSError:
                    continue
                key = [st.st_size, st.st_mtime_ns]
                hit = old.get(f)
                if hit and hit[0] == key:
                    out[f] = hit[1]
                    new[f] = hit
                    continue
            try:
                text = self.read(f)
            except OSError:
                continue
            out[f] = extract(f, text)
            new[f] = [key, out[f]]
            dirty = True
        if cache is not None and use_stat and (dirty or set(new) != set(old)):
            _atomic_write(Path(cache), {"version": SCAN_VERSION, "root": str(self.root), "files": new})
        return out

    # -------------------------------------------------------------- CLI routing
    def _commands(self) -> dict:
        """{command: [handler files]}: scripts/<cmd>.mjs, else the cli_<module>.py whose COMMANDS name it."""
        out: dict = {}
        for f in self.files:
            p = PurePosixPath(f)
            if str(p.parent) == SKILL + "/scripts" and p.suffix == ".mjs" and not p.name.startswith("_"):
                out.setdefault(p.stem, []).append(f)
        for f in self.files:
            p = PurePosixPath(f)
            if str(p.parent) == SKILL + "/lib/st" and p.name.startswith("cli_") and p.suffix == ".py":
                try:
                    text = self.read(f)
                except OSError:
                    continue
                for cmd in _literal_commands(text):
                    if cmd not in out:           # a Node script of the same name wins, as in the launcher
                        out.setdefault(cmd, []).append(f)
        special = {"setup": SKILL + "/setup/setup.py", "doctor": SKILL + "/lib/st/doctor.py"}
        for cmd, f in special.items():
            if f in self.fileset:
                out.setdefault(cmd, []).append(f)
        return out

    # -------------------------------------------------------------- resolving references
    def _resolve(self, rel: str, refs: list) -> set:
        out = set()
        for r in refs:
            kind = r[0]
            if kind == "p":
                out |= self.match_path(r[1], allow_dir=r[2])
            elif kind == "m":
                out |= self.module_files(r[1], rel)
            elif kind == "c":
                out.update(self.commands.get(r[1], ()))
            elif kind == "w":
                out.update(self.commands.get(r[1], ()))
                if r[1] in self.templates:
                    out.update(self.dirs.get(SKILL + "/templates/" + r[1], ()))
            elif kind == "f":
                for cand in (r[1], r[1] + ".mjs", r[1] + ".js", r[1] + ".cjs", r[1] + "/index.js", r[1] + "/index.mjs"):
                    if cand in self.fileset:
                        out.add(cand)
                        break
        return out

    def match_path(self, parts: list, allow_dir: bool = False) -> set:
        """Files named by trailing path parts ('runtime', 'film.js'). Leading parts that match nothing are
        dropped ('/_st/stage.js' -> runtime/stage.js). A lone data or media name ('poster.jpg') or a very
        common code name ('index.js') matches nothing; with allow_dir, 2+ parts may name a folder."""
        parts = [q for p in parts if isinstance(p, str) for q in p.strip().split("/") if q and q != "."]
        while parts and parts[0] == "..":
            parts = parts[1:]
        for start in range(len(parts)):
            tail = parts[start:]
            name = tail[-1].lower()
            if len(tail) == 1 and (name in COMMON_NAMES or not name.endswith(LONE_NAME_EXT)):
                return set()
            suffix = "/".join(tail)
            low = suffix.lower()
            hits = {f for f in self.by_name.get(name, ()) if f.lower() == low or f.lower().endswith("/" + low)}
            if hits:
                return hits
            if allow_dir and len(tail) >= 2:
                for d, fs in self.dirs.items():
                    if d == suffix or d.endswith("/" + suffix):
                        hits.update(fs)
                if hits:
                    return hits
        return set()

    def module_files(self, dotted: str, here: str = "") -> set:
        """Files a Python import of `dotted` runs: the module (or package __init__) and its parent packages."""
        out = set()
        parts = dotted.split(".")
        bases = [SKILL + "/lib"]
        if here.startswith(TESTS + "/"):
            bases.append(TESTS)
        for base in bases:
            for i in range(1, len(parts) + 1):
                stem = base + "/" + "/".join(parts[:i])
                for cand in (stem + "/__init__.py", stem + ".py"):
                    if cand in self.fileset:
                        out.add(cand)
        return out

    # -------------------------------------------------------------- queries
    def reach(self, start: str) -> dict:
        """{file: parent} for every file reachable from start (BFS, so the parent chain is a shortest path)."""
        seen = {start: None}
        q = deque([start])
        while q:
            f = q.popleft()
            for g in sorted(self.edges.get(f, ())):
                if g not in seen:
                    seen[g] = f
                    q.append(g)
        return seen

    def direct(self, start: str) -> dict:
        """{file: parent} for the start file and what it names itself (one step)."""
        out = {start: None}
        for g in sorted(self.edges.get(start, ())):
            out.setdefault(g, start)
        return out


# ------------------------------------------------------------------ AST helpers

def _literal_commands(text: str) -> list:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMMANDS" for t in node.targets):
            try:
                val = ast.literal_eval(node.value)
            except ValueError:
                return []
            return [str(k) for k in val] if isinstance(val, dict) else []
    return []


def _py_package(rel: str) -> str:
    """Dotted package of a file under lib/ ('skills/showtime/lib/st/voice/tts.py' -> 'st.voice')."""
    lib = SKILL + "/lib/"
    if not rel.startswith(lib):
        return ""
    return ".".join(rel[len(lib):].split("/")[:-1])


def _call_name(fn) -> str:
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _chain(node, names: dict) -> list:
    """String parts of a path expression: SKILL / "a" / "b" -> ["a", "b"]; paths()["templates"] / "x" ->
    ["templates", "x"]; a module-level NAME assigned from such a chain expands to its parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value] if node.value and len(node.value) < 200 and "\n" not in node.value else []
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _chain(node.left, names) + _chain(node.right, names)
    if isinstance(node, ast.Name):
        return list(names.get(node.id, []))
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, getattr(ast, "Index", ())):   # Python 3.8
            key = key.value
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return [key.value]
    return []


def _module_chains(tree) -> dict:
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Div):
                names[node.targets[0].id] = _chain(node.value, names)
    return names


def _normpath(p: str) -> str:
    out = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def _atomic_write(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(".%s.%d.part" % (path.name, os.getpid()))
        tmp.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass


# ------------------------------------------------------------------ recorded use (traces)

def trace_env(env: dict, trace_dir: Path, root: Path = REPO, node: bool = True) -> dict:
    """The environment that makes a test's Python and Node processes record the repository files they use.
    node=False leaves NODE_OPTIONS alone (a Node too old for --import, see node_can_trace)."""
    env = dict(env)
    env["ST_TRACE_DIR"] = str(trace_dir)
    env["ST_TRACE_ROOT"] = str(root)
    pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(TRACE_DIR) + ((os.pathsep + pp) if pp else "")
    if node:
        hook = (TRACE_DIR / "hook.mjs").resolve().as_uri()
        env["NODE_OPTIONS"] = ((env.get("NODE_OPTIONS") or "") + " --import=" + hook).strip()
    return env


def node_can_trace(node) -> bool:
    """Node 20+ (showtime's minimum) takes --import in NODE_OPTIONS; an older one would refuse to start."""
    if not node:
        return False
    try:
        cp = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20)
        major = int(cp.stdout.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return False
    return major >= 20


def read_trace(trace_dir: Path, root: Path = REPO) -> set:
    """Repository-relative files recorded in a trace folder (dependencies under node_modules left out)."""
    out = set()
    bases = sorted({os.path.normcase(os.path.abspath(str(root))), os.path.normcase(os.path.realpath(str(root)))},
                   key=len, reverse=True)
    try:
        logs = list(Path(trace_dir).glob("*.txt"))
    except OSError:
        return out
    for log in logs:
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            raw = line.strip()
            p = os.path.normcase(raw)
            for b in bases:
                if p.startswith(b + os.sep):
                    rel = raw[len(b) + 1:].replace("\\", "/")
                    if "node_modules/" not in rel and "__pycache__" not in rel and not is_runner_file(rel):
                        out.add(rel)
                    break
    return out


# a file a test has not used in its last TRACE_KEEP_RUNS passing runs drops out of its recorded use
TRACE_KEEP_RUNS = 5


def _load_store(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict) or d.get("version") != 2 or not isinstance(d.get("tests"), dict):
        return {}
    return d["tests"]


def load_traces(path: Path) -> dict:
    """{"fast:test_render.py": set(files), ...}: what each test used in its last TRACE_KEEP_RUNS passing runs."""
    out = {}
    for k, v in _load_store(path).items():
        if isinstance(v, dict) and isinstance(v.get("files"), dict):
            out[k] = set(v["files"])
    return out


def save_traces(path: Path, new: dict) -> None:
    """Add one passing run per test: {"fast:test_x.py": set(files)}. The store keeps, per test, the run
    number each file was last used in; files unused for TRACE_KEEP_RUNS runs are dropped (so a code path seen
    once stays known for a while, and a dependency that is gone ages out)."""
    store = _load_store(path)
    for k, used in new.items():
        e = store.get(k) if isinstance(store.get(k), dict) else {}
        n = int(e.get("runs", 0)) + 1
        files = {f: i for f, i in (e.get("files") or {}).items() if isinstance(i, int) and i > n - TRACE_KEEP_RUNS}
        for f in used:
            files[f] = n
        store[k] = {"runs": n, "files": dict(sorted(files.items()))}
    _atomic_write(Path(path), {"version": 2, "tests": dict(sorted(store.items()))})


# ------------------------------------------------------------------ changes

def default_base(root: Path = REPO):
    """The integration branch to compare with: of the BASE_REFS that exist, the one whose merge-base with HEAD
    is nearest (a local branch or its remote copy, whichever is newer), preferring the first family listed."""
    for family in (BASE_REFS[:2], BASE_REFS[2:]):
        best = None
        for ref in family:
            if git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is None:
                continue
            mb = (git(root, "merge-base", "HEAD", ref) or "").strip()
            n = (git(root, "rev-list", "--count", "%s..HEAD" % mb) or "").strip() if mb else ""
            dist = int(n) if n.isdigit() else 10 ** 9
            if best is None or dist < best[0]:
                best = (dist, ref)
        if best:
            return best[1]
    return None


def changed_files(ref=None, root: Path = REPO) -> tuple:
    """(changed, deleted, description): files changed since the merge-base of HEAD and ref (default: the
    first of BASE_REFS that exists), plus uncommitted and untracked changes. Raises RuntimeError without git."""
    if git(root, "rev-parse", "--git-dir") is None:
        raise RuntimeError("not a git checkout (or git is not installed): --changed needs git")
    base = ref or default_base(root)
    if not base:
        raise RuntimeError("none of %s exists here; name the base: --changed <ref>" % ", ".join(BASE_REFS))
    if git(root, "rev-parse", "--verify", "--quiet", base + "^{commit}") is None:
        raise RuntimeError("unknown git ref %r (in CI, fetch it first: git fetch origin <branch>)" % base)
    mb = (git(root, "merge-base", "HEAD", base) or "").strip()
    if not mb:
        raise RuntimeError("no common history between HEAD and %s (a shallow clone? fetch more history)" % base)
    diff = git(root, "diff", "--name-status", "-M", mb, "--") or ""
    changed, deleted = set(), set()
    for line in diff.splitlines():
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        st = cols[0][:1]
        if st == "D":
            deleted.add(cols[1])
        elif st in ("R", "C") and len(cols) >= 3:
            changed.add(cols[2])
        else:
            changed.add(cols[1])
    untracked = git(root, "ls-files", "--others", "--exclude-standard") or ""
    changed.update(x for x in untracked.splitlines() if x.strip())
    return sorted(changed), sorted(deleted - changed), "%s (merge-base %s)" % (base, mb[:10])


# ------------------------------------------------------------------ selection

def overrides_for(path: str) -> list:
    """[(pattern, tests)] of every override matching a repository-relative path."""
    return [(pat, tests) for pat, tests in OVERRIDES if match_pattern(path, pat)]


def only_overrides_for(path: str) -> list:
    """[(pattern, tests)] of every OVERRIDES_ONLY rule matching a repository-relative path."""
    return [(pat, tests) for pat, tests in OVERRIDES_ONLY if match_pattern(path, pat)]


def match_pattern(path: str, pat: str) -> bool:
    if "**" in pat:
        prefix, rest = pat.split("**", 1)
        rest = rest.lstrip("/")
        if not path.startswith(prefix):
            return False
        return not rest or fnmatch.fnmatchcase(PurePosixPath(path).name, rest)
    if "/" not in pat:
        return "/" not in path and fnmatch.fnmatchcase(path, pat)
    return path.count("/") == pat.count("/") and fnmatch.fnmatchcase(path, pat)


def select(test_names: list, changed: list, deleted: list = (), imap: ImpactMap = None, traces: dict = None,
           mode: str = "fast") -> dict:
    """Which tests the changes affect.

    traces: {"<mode>:<test file>": set(files)} (recorded use). -> {"all": bool, "unplaced": [(file, why)],
    "tests": {test: [(changed file, [chain ...], how)]}, "notes": [...]}. With "all", run every test."""
    imap = imap if imap is not None else ImpactMap(repo_files())
    traces = traces or {}
    names = sorted(set(test_names))
    uses, static, recorded = {}, {}, {}
    for t in names:
        start = TESTS + "/" + t
        static[t] = imap.reach(start)
        rec = traces.get("%s:%s" % (mode, t))
        recorded[t] = bool(rec)
        if rec:
            u = imap.direct(start)
            for f in sorted(rec):
                if not is_runner_file(f):
                    u.setdefault(f, "(recorded)")
            uses[t] = u
        else:
            uses[t] = static[t]
    picked: dict = {}
    unplaced, notes = [], []

    def chain_of(seen, t, f):
        out, g = [], seen.get(f)
        while g is not None and g not in (TESTS + "/" + t, "(recorded)"):
            out.append(g)
            g = seen.get(g)
        return list(reversed(out))

    for f in list(changed) + list(deleted):
        name = PurePosixPath(f).name
        hit = False
        only = only_overrides_for(f)
        if only:
            for pat, tests in only + overrides_for(f):
                for t in tests:
                    if t in names:
                        picked.setdefault(t, []).append((f, [], "override %s%s" % (pat, " (only)" if (pat, tests)
                                                                                     in only else "")))
            continue
        if f.startswith(TESTS + "/test_") and name in names:
            picked.setdefault(name, []).append((f, [], "the test file itself"))
            hit = True
        for t in names:
            if f in uses[t] and f != TESTS + "/" + t:
                if uses[t][f] == "(recorded)":
                    how = "a recorded %s run used it" % mode
                elif recorded[t]:
                    how = "the test names it"
                else:
                    how = "static scan (no recorded %s run of this test yet)" % mode
                picked.setdefault(t, []).append((f, chain_of(uses[t], t, f), how))
                hit = True
        for pat, tests in overrides_for(f):
            for t in tests:
                if t in names:
                    picked.setdefault(t, []).append((f, [], "override %s" % pat))
            hit = True
        if not hit and f.startswith(TESTS + "/test_"):
            hit = True                        # a test outside this selection (-k), or a deleted test
        if not hit:
            fallback = [t for t in names if f in static[t]]
            if fallback:
                notes.append("%s: no recorded %s run used it; the static scan picks %d test file(s)"
                             % (f, mode, len(fallback)))
                for t in fallback:
                    picked.setdefault(t, []).append((f, chain_of(static[t], t, f),
                                                     "static scan (no recorded %s run used it)" % mode))
                hit = True
        if not hit:
            if f in deleted:
                unplaced.append((f, "deleted, and no test or override names it"))
            elif f not in imap.fileset:
                unplaced.append((f, "not in the repository's file list"))
            else:
                unplaced.append((f, "no test reaches it and no override names it"))
    if (changed or deleted) and HYGIENE_TEST in names:
        picked.setdefault(HYGIENE_TEST, []).append(("(any change)", [], "release hygiene scans every shipped file"))
    return {"all": bool(unplaced), "unplaced": unplaced, "tests": picked, "notes": notes}


def explain_lines(sel: dict, max_per_test: int = 6) -> list:
    lines = []
    for t in sorted(sel["tests"]):
        why = sel["tests"][t]
        lines.append(t)
        for f, chain, how in why[:max_per_test]:
            via = (" via " + " -> ".join(_short(c) for c in chain)) if chain else ""
            lines.append("    %s: %s%s" % (_short(f), how, via))
        if len(why) > max_per_test:
            lines.append("    ... and %d more changed files" % (len(why) - max_per_test))
    return lines


def _short(p: str) -> str:
    return p[len(SKILL) + 1:] if p.startswith(SKILL + "/") else p
