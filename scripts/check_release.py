#!/usr/bin/env python3
"""Release checks for the showtime repository (stdlib only, any OS, Python 3.8+).

    python scripts/check_release.py --check        # report problems, change nothing (CI)
    python scripts/check_release.py                # also fix the mechanical ones (version lines)
    python scripts/check_release.py --set-version 0.2.0
    python scripts/check_release.py --check --json

Checks:
  versions    .claude-plugin/plugin.json, .claude-plugin/marketplace.json,
              skills/showtime/setup/package.json and st.__version__ agree
  skill       SKILL.md exists, has valid frontmatter (name, description <= 1024 chars)
              and a body within the word budget
  links       every relative link / `references/...` path in SKILL.md and references/ exists
  commands    every `showtime <cmd> [sub]` named in SKILL.md, references/ and agents/ exists in the CLI
  agents      plugin sub-agents in agents/*.md: valid frontmatter (name = file name, a short
              "showtime crew." description, an explicit tool list without the Agent tool, known
              model/effort/color values), every ${CLAUDE_PLUGIN_ROOT} path exists, each agent points at
              its brief in references/crew/ and carries the return contract, and every brief has an agent
  paths       no machine-specific paths (a developer's home folder, temp folders) in shipped files
  names       no names of outside projects this repo must not mention (list kept encoded below)
  terms       words CONTEXT.md says to avoid (warning only)
  media       committed videos under 20 MB, no render work folders, and large example media (over
              10 MB, every .mov) listed in examples/MEDIA.json and ignored by git: they ship as release
              assets (scripts/publish_media.py; skipped where the examples live in their own repository)
  directory   the plugin directory's limits for the published repository: under 10,000 files, 256 MiB
              unpacked and 50 MiB zipped, every file under 5 MiB, no symlinks, submodules or LFS, no OS
              junk files, names valid on Windows (no reserved characters or names, no case-only
              duplicates), no export-ignore/filter in .gitattributes, README of 40+ words, a LICENSE,
              plugin.json name/description/author/version, a default for every userConfig option, no
              top-level bin/. Warnings for what makes a review slower (over 512 files, non-image
              binaries over 256 KiB). Runs by default where there is no examples/ folder (the plugin
              repository); ask for it with --only directory elsewhere.

Exit code 0 = clean (warnings allowed), 1 = problems found, 2 = bad usage.
"""
from __future__ import annotations

import argparse
import ast
import codecs
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "showtime"
LIB = SKILL / "lib"

DESCRIPTION_MAX = 1024
BODY_WORDS_MAX = 1500

# Plugin sub-agents (the crew). Loaded by Claude Code from agents/*.md at the plugin root.
AGENTS_DIR = REPO / "agents"
CREW_DIR = SKILL / "references" / "crew"
AGENT_DESC_MAX = 300
AGENT_DESC_PREFIX = "showtime crew."
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
AGENT_TOOLS = {"Read", "Glob", "Grep", "LSP", "Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch",
               "WebSearch", "TodoWrite", "Skill", "ToolSearch", "Monitor", "TaskStop", "SendMessage"}
AGENT_SPAWN_TOOLS = {"Agent", "Task"}  # crew members never dispatch other agents
AGENT_MODELS = {"sonnet", "opus", "haiku", "fable", "inherit"}
AGENT_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
AGENT_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
# Fields plugin agents ignore silently: shipping them would promise a restriction that does not exist.
AGENT_IGNORED = {"permissionMode", "hooks", "mcpServers", "initialPrompt"}
AGENT_KNOWN = {"name", "description", "tools", "disallowedTools", "model", "effort", "maxTurns", "skills",
               "memory", "background", "omitClaudeMd", "isolation", "color", "experimental"}
PLUGIN_ROOT_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}([/\\][^\s`'\")]+)")

# Names that must never appear in shipped files. Stored rot13-encoded so this
# file does not itself contain them.
_BANNED_ROT13 = ["oent", "ivqrb-hfr", "ivqrbfxvyy", "ulcresenzrf", "znggcbpbpx", "fhcrecbjref",
                 "erzbgvba", "pvarzngvp-rkcynvare", "3oyhr1oebja", "3o1o", "tenag fnaqrefba"]
BANNED = [codecs.decode(n, "rot13") for n in _BANNED_ROT13]

# Folders that are never part of the product (local reference material).
_LOCAL_ROT13 = ["oent", "ivqrb-hfr", "ivqrbfxvyy", "ulcresenzrf", "znggcbpbpx-fxvyyf", "fhcrecbjref"]
LOCAL_DIRS = {codecs.decode(n, "rot13") for n in _LOCAL_ROT13}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "showtime-out", "work", ".pytest_cache"}
# Example renders are committed (small by design); anything bigger belongs in a release asset.
MAX_MEDIA_BYTES = 20 * 1000 * 1000
MEDIA_EXT = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
TEXT_EXT = {".md", ".py", ".mjs", ".js", ".cjs", ".json", ".html", ".css", ".yml", ".yaml", ".txt", ".toml",
            ".sh", ".cmd", ".ps1", ".svg", ".in", ".cfg", ".ini", ""}

# Placeholder user names allowed in example paths (docs and tests show C:\Users\me\...).
_PLACEHOLDERS = r"(?:me|you|name|user|username|example|runner|someone|alice|bob|<[^>]+>|\{[^}]+\}|\$[A-Za-z_]+|%[A-Za-z_]+%)"
MACHINE_PATTERNS = [
    ("home folder", re.compile(r"/Users/(?!%s(?:/|\b))[A-Za-z0-9._-]+/" % _PLACEHOLDERS)),
    ("home folder", re.compile(r"/home/(?!%s(?:/|\b))[a-z0-9._-]+/" % _PLACEHOLDERS)),
    ("home folder", re.compile(r"[A-Za-z]:\\\\?Users\\\\?(?!%s(?:\\|\b))[A-Za-z0-9._ -]+\\" % _PLACEHOLDERS)),
    ("temp folder", re.compile("/pri" + r"vate/(?:tmp|var)/")),
    ("temp folder", re.compile("/var/" + r"folders/")),
    ("session folder", re.compile("scratch" + "pad/")),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class Findings:
    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []

    def add(self, check: str, level: str, message: str, where: str = "") -> None:
        self.items.append({"check": check, "level": level, "message": message, "where": where})

    def errors(self) -> List[Dict[str, str]]:
        return [i for i in self.items if i["level"] == "error"]


def shipped_files() -> List[Path]:
    """Files that would be published: git's view when available, else a filtered walk."""
    try:
        cp = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        if cp.returncode == 0 and cp.stdout:
            out = []
            for rel in cp.stdout.decode("utf-8", "replace").split("\0"):
                if not rel:
                    continue
                parts = rel.split("/")
                if parts[0] in LOCAL_DIRS or any(p in SKIP_DIRS for p in parts):
                    continue
                p = REPO / rel
                if p.is_file():
                    out.append(p)
            return sorted(out)
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for root, dirs, files in os.walk(str(REPO)):
        rel_root = Path(root).relative_to(REPO)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (rel_root == Path(".") and d in LOCAL_DIRS)]
        for f in files:
            out.append(Path(root) / f)
    return sorted(out)


def is_text(p: Path) -> bool:
    if p.suffix.lower() not in TEXT_EXT:
        return False
    try:
        return p.stat().st_size < 4 * 1024 * 1024
    except OSError:
        return False


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def rel(p: Path) -> str:
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------

VERSION_RE = re.compile(r'("version"\s*:\s*")([^"]+)(")')


def lib_version() -> str:
    text = read(LIB / "st" / "__init__.py")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else "?"


def version_sources() -> List[Tuple[str, Path, Optional[str]]]:
    out: List[Tuple[str, Path, Optional[str]]] = [("st.__version__", LIB / "st" / "__init__.py", lib_version())]
    for label, path, getter in (
            ("plugin.json", REPO / ".claude-plugin" / "plugin.json", lambda d: d.get("version")),
            ("marketplace.json metadata", REPO / ".claude-plugin" / "marketplace.json",
             lambda d: (d.get("metadata") or {}).get("version")),
            ("marketplace.json plugin", REPO / ".claude-plugin" / "marketplace.json",
             lambda d: next((p.get("version") for p in d.get("plugins", []) if p.get("name") == "showtime"), None)),
            ("setup/package.json", SKILL / "setup" / "package.json", lambda d: d.get("version"))):
        try:
            out.append((label, path, getter(json.loads(read(path)))))
        except (OSError, ValueError):
            out.append((label, path, None))
    return out


def check_versions(f: Findings, fix: bool, set_version: Optional[str]) -> None:
    want = set_version or lib_version()
    if set_version:
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", set_version):
            raise SystemExit("--set-version needs a semantic version like 0.2.0")
        init = LIB / "st" / "__init__.py"
        text = read(init)
        new = re.sub(r'(__version__\s*=\s*["\'])([^"\']+)(["\'])', lambda m: m.group(1) + want + m.group(3), text)
        if new != text and fix:
            init.write_text(new, encoding="utf-8", newline="\n")
    drift = []
    for label, path, have in version_sources():
        if have is None:
            f.add("versions", "error", "no version found in %s" % label, rel(path))
        elif have != want:
            drift.append((label, path, have))
    if drift and fix:
        for path in sorted({p for _l, p, _h in drift if p.suffix == ".json"}):
            text = read(path)
            new = VERSION_RE.sub(lambda m: m.group(1) + want + m.group(3), text)
            path.write_text(new, encoding="utf-8", newline="\n")
        drift = [(l, p, h) for l, p, h in drift if p.suffix != ".json"]
    for label, path, have in drift:
        f.add("versions", "error", "%s says %s, expected %s (run scripts/check_release.py to sync)"
              % (label, have, want), rel(path))


# ---------------------------------------------------------------------------
# SKILL.md
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> Tuple[Optional[Dict[str, str]], str, str]:
    """(fields or None, body, error). Supports `key: value` and folded `key: >` blocks."""
    if not text.startswith("---"):
        return None, text, "SKILL.md must start with a '---' frontmatter block"
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not m:
        return None, text, "frontmatter is not closed with '---'"
    fields: Dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        km = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if km and not line.startswith((" ", "\t")):
            key = km.group(1)
            val = km.group(2).strip()
            fields[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
        elif key is not None:
            fields[key] = (fields[key] + " " + line.strip()).strip()
        else:
            return None, m.group(2), "cannot parse frontmatter line: %r" % line
    return fields, m.group(2), ""


def word_count(md: str) -> int:
    md = re.sub(r"```.*?```", lambda m: " ".join(["w"] * len(m.group(0).split())), md, flags=re.S)
    return len(re.findall(r"[A-Za-z0-9][\w'./-]*", md))


def check_skill(f: Findings) -> Optional[str]:
    path = SKILL / "SKILL.md"
    if not path.is_file():
        f.add("skill", "error", "SKILL.md is missing (the router Claude reads first)", rel(path))
        return None
    text = read(path)
    fields, body, err = parse_frontmatter(text)
    if fields is None:
        f.add("skill", "error", err, rel(path))
        return body
    if fields.get("name") != "showtime":
        f.add("skill", "error", "frontmatter name must be 'showtime' (got %r)" % fields.get("name"), rel(path))
    desc = fields.get("description", "")
    if not desc:
        f.add("skill", "error", "frontmatter needs a description", rel(path))
    elif len(desc) > DESCRIPTION_MAX:
        f.add("skill", "error", "description is %d characters (max %d)" % (len(desc), DESCRIPTION_MAX), rel(path))
    elif not desc.lower().startswith("use when"):
        f.add("skill", "warning", "description should start with 'Use when' (triggers, not a pipeline summary)",
              rel(path))
    words = word_count(body)
    if words > BODY_WORDS_MAX:
        f.add("skill", "error", "SKILL.md body is %d words (budget %d; move detail into references/)"
              % (words, BODY_WORDS_MAX), rel(path))
    return body


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REF_PATH_RE = re.compile(r"`((?:references|templates|scripts|runtime|examples|setup|bin)/[\w./-]+?)`")


def doc_files() -> List[Path]:
    out = []
    if (SKILL / "SKILL.md").is_file():
        out.append(SKILL / "SKILL.md")
    ref = SKILL / "references"
    if ref.is_dir():
        out += sorted(ref.rglob("*.md"))
    return out


def check_links(f: Findings) -> None:
    for doc in doc_files():
        text = read(doc)
        text_nocode = re.sub(r"```.*?```", "", text, flags=re.S)
        prose = re.sub(r"`[^`\n]*`", "", text_nocode)
        targets: Set[Tuple[str, Path]] = set()
        for m in LINK_RE.finditer(prose):
            t = m.group(1)
            if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("#"):
                continue
            t = t.split("#", 1)[0]
            if t:
                targets.add((t, (doc.parent / t)))
        for m in REF_PATH_RE.finditer(text_nocode):
            t = m.group(1).rstrip(".")
            if any(ch in t for ch in "*<>{}") or t.endswith("/"):
                continue
            targets.add((t, SKILL / t))
        for t, p in sorted(targets):
            if not p.exists():
                f.add("links", "error", "broken link: %s" % t, rel(doc))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _literal_commands(path: Path) -> Dict[str, str]:
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMMANDS" for t in node.targets):
            try:
                val = ast.literal_eval(node.value)
                return {str(k): str(v) for k, v in val.items()} if isinstance(val, dict) else {}
            except ValueError:
                return {}
    return {}


def cli_commands() -> Dict[str, Optional[Set[str]]]:
    """{top-level command: set of sub-commands, or None when it takes free arguments}."""
    cmds: Dict[str, Optional[Set[str]]] = {"setup": None, "doctor": None, "help": None, "version": None}
    st_dir = LIB / "st"
    for py in sorted(st_dir.glob("cli_*.py")):
        for name in _literal_commands(py):
            cmds.setdefault(name, None)
    for mjs in sorted((SKILL / "scripts").glob("*.mjs")):
        if mjs.name.startswith("_"):
            continue
        subs: Optional[Set[str]] = None
        m = re.search(r"showtime\s+%s\s+<([a-z][a-z0-9-]*(?:\|[a-z][a-z0-9-]*)+)>" % re.escape(mjs.stem), read(mjs))
        if m:
            subs = set(m.group(1).split("|"))
        cmds[mjs.stem] = subs
    # Python sub-commands, when the CLI can be built here (imports are lazy and guarded).
    try:
        sys.path.insert(0, str(LIB))
        from st.cli import build_parser  # type: ignore
        import argparse as _ap
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            parser = build_parser()
        top = next(a for a in parser._actions if isinstance(a, _ap._SubParsersAction))  # noqa: SLF001
        for name, sp in top.choices.items():
            subs = None
            for act in sp._actions:  # noqa: SLF001
                if isinstance(act, _ap._SubParsersAction):  # noqa: SLF001
                    subs = set(act.choices)
                    break
                if act.option_strings or act.dest == "help":
                    continue
                if act.choices and all(isinstance(c, str) for c in act.choices):
                    subs = set(act.choices)
                break
            if name in cmds and cmds[name] is None:
                cmds[name] = subs
            elif name not in cmds:
                cmds[name] = subs
    except Exception:  # noqa: BLE001 - sub-command checks are best effort
        pass
    return cmds


MENTION_RE = re.compile(r"(?:^|[`\s$(])showtime ([a-z][a-z0-9-]*)(?:[ \t]+([a-z][a-z0-9-]*))?")


def command_mentions(text: str) -> List[Tuple[str, Optional[str], int]]:
    """`showtime cmd [sub]` inside inline code spans and fenced code blocks."""
    out = []
    spans: List[Tuple[str, int]] = []
    for m in re.finditer(r"```[^\n]*\n(.*?)```", text, re.S):
        base = text.count("\n", 0, m.start(1)) + 1
        for i, line in enumerate(m.group(1).splitlines()):
            spans.append((line, base + i))
    no_fence = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    for m in re.finditer(r"`([^`\n]+)`", no_fence):
        spans.append((m.group(1), no_fence.count("\n", 0, m.start()) + 1))
    for span, line in spans:
        s = span.strip()
        s = re.sub(r"^\$\s+", "", s)
        for mm in MENTION_RE.finditer(" " + s):
            out.append((mm.group(1), mm.group(2), line))
    return out


def agent_files(agents_dir: Optional[Path] = None) -> List[Path]:
    d = agents_dir or AGENTS_DIR
    return sorted(d.glob("*.md")) if d.is_dir() else []


def check_commands(f: Findings) -> None:
    cmds = cli_commands()
    for doc in doc_files() + agent_files():
        for cmd, sub, line in command_mentions(read(doc)):
            where = "%s:%d" % (rel(doc), line)
            if cmd not in cmds:
                f.add("commands", "error", "`showtime %s` is not a command" % cmd, where)
                continue
            subs = cmds[cmd]
            if subs and sub and sub not in subs:
                f.add("commands", "error", "`showtime %s %s`: unknown sub-command (known: %s)"
                      % (cmd, sub, ", ".join(sorted(subs))), where)


# ---------------------------------------------------------------------------
# agents (the crew)
# ---------------------------------------------------------------------------

def check_agents(f: Findings, agents_dir: Optional[Path] = None, crew_dir: Optional[Path] = None,
                 root: Optional[Path] = None) -> None:
    """Plugin sub-agents: frontmatter, tool allowlist, pointers to their briefs, return contract."""
    agents_dir = agents_dir or AGENTS_DIR
    crew_dir = crew_dir or CREW_DIR
    root = root or REPO
    if not agents_dir.is_dir():
        return
    for sub in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
        f.add("agents", "error", "keep agents/ flat (a subfolder changes the agent's name)", rel(sub))
    names = set()
    for path in agent_files(agents_dir):
        where = rel(path)
        fields, body, err = parse_frontmatter(read(path))
        if fields is None:
            f.add("agents", "error", err.replace("SKILL.md", "an agent file"), where)
            continue
        name = fields.get("name", "")
        names.add(name or path.stem)
        if name != path.stem:
            f.add("agents", "error", "name %r must match the file name %r" % (name, path.stem), where)
        if not AGENT_NAME_RE.match(name or ""):
            f.add("agents", "error", "name %r: use lowercase letters, digits and hyphens" % name, where)
        desc = fields.get("description", "")
        if not desc:
            f.add("agents", "error", "frontmatter needs a description (when to dispatch it)", where)
        elif len(desc) > AGENT_DESC_MAX:
            f.add("agents", "error", "description is %d characters (max %d)" % (len(desc), AGENT_DESC_MAX), where)
        elif not desc.startswith(AGENT_DESC_PREFIX):
            f.add("agents", "error", "description must start with %r so general requests are not delegated to it"
                  % AGENT_DESC_PREFIX, where)
        for key in sorted(set(fields) - AGENT_KNOWN):
            why = "ignored for plugin agents" if key in AGENT_IGNORED else "not a sub-agent field"
            f.add("agents", "error", "frontmatter %r is %s" % (key, why), where)
        tools = [t.strip() for t in fields.get("tools", "").split(",") if t.strip()]
        if not tools:
            f.add("agents", "error", "list the tools explicitly (an omitted list inherits the Agent tool)", where)
        for tool in tools:
            base = tool.split("(", 1)[0]
            if base in AGENT_SPAWN_TOOLS:
                f.add("agents", "error", "tool %r lets a crew member dispatch agents; remove it" % tool, where)
            elif base not in AGENT_TOOLS:
                f.add("agents", "error", "unknown tool %r" % tool, where)
        model = fields.get("model", "")
        if model and model not in AGENT_MODELS and not model.startswith("claude-"):
            f.add("agents", "error", "model %r (use %s or a full model id)" % (model, ", ".join(sorted(AGENT_MODELS))),
                  where)
        if fields.get("effort") and fields["effort"] not in AGENT_EFFORTS:
            f.add("agents", "error", "effort %r (use %s)" % (fields["effort"], ", ".join(sorted(AGENT_EFFORTS))),
                  where)
        if fields.get("color") and fields["color"] not in AGENT_COLORS:
            f.add("agents", "error", "color %r (use %s)" % (fields["color"], ", ".join(sorted(AGENT_COLORS))), where)
        if fields.get("maxTurns") and not re.fullmatch(r"[1-9]\d*", fields["maxTurns"]):
            f.add("agents", "error", "maxTurns must be a positive integer", where)
        for key in ("omitClaudeMd", "background"):
            if key in fields and fields[key] not in ("true", "false"):
                f.add("agents", "error", "%s must be true or false" % key, where)
        targets = [m.group(1).lstrip("/\\").rstrip(".,;:") for m in PLUGIN_ROOT_RE.finditer(body)]
        for t in targets:
            if not (root / t.replace("\\", "/")).exists():
                f.add("agents", "error", "${CLAUDE_PLUGIN_ROOT}/%s does not exist" % t, where)
        brief = crew_dir / (path.stem + ".md")
        want = {(crew_dir / "rules.md").relative_to(root).as_posix(), brief.relative_to(root).as_posix()}
        missing = want - {t.replace("\\", "/") for t in targets}
        if missing:
            f.add("agents", "error", "body must point at %s via ${CLAUDE_PLUGIN_ROOT}" % ", ".join(sorted(missing)),
                  where)
        if not brief.is_file():
            f.add("agents", "error", "no role brief %s" % rel(brief), where)
        if "STATUS:" not in body or "NEEDS_INPUT" not in body:
            f.add("agents", "error", "body must end with the return contract (STATUS: ... NEEDS_INPUT ...)", where)
    if crew_dir.is_dir():
        for brief in sorted(crew_dir.glob("*.md")):
            if brief.stem != "rules" and brief.stem not in names:
                f.add("agents", "error", "role brief has no agent file agents/%s.md" % brief.stem, rel(brief))


# ---------------------------------------------------------------------------
# machine paths, banned names, terms
# ---------------------------------------------------------------------------

def check_paths_and_names(f: Findings, files: Sequence[Path]) -> None:
    banned_re = re.compile(r"(?<![A-Za-z0-9_-])(%s)(?![A-Za-z0-9_])" % "|".join(re.escape(b) for b in BANNED),
                           re.I)
    for p in files:
        if not is_text(p):
            continue
        text = read(p)
        for i, line in enumerate(text.splitlines(), 1):
            for label, rx in MACHINE_PATTERNS:
                m = rx.search(line)
                if m:
                    f.add("paths", "error", "machine-specific %s: %s" % (label, m.group(0)), "%s:%d" % (rel(p), i))
            m = banned_re.search(line)
            if m:
                f.add("names", "error", "mentions an outside project this repo must not name (%s)"
                      % codecs.encode(m.group(1).lower(), "rot13") + " [rot13]", "%s:%d" % (rel(p), i))
        low = rel(p).lower()
        for b in BANNED:
            if re.search(r"(^|/)%s(/|\.|$)" % re.escape(b), low):
                f.add("names", "error", "file name mentions a banned project", rel(p))


def avoid_terms() -> Dict[str, str]:
    """{avoid-word: preferred term} from the `backticked` words of CONTEXT.md `_Avoid_:` lines."""
    ctx = REPO / "CONTEXT.md"
    out: Dict[str, str] = {}
    if not ctx.is_file():
        return out
    term = None
    for line in read(ctx).splitlines():
        h = re.match(r"^#{2,4}\s+(.+?)\s*$", line) or re.match(r"^\*\*(.+?)\*\*", line)
        if h:
            term = h.group(1).strip()
        m = re.match(r"^\s*[-*]?\s*_?Avoid_?:\s*(.+)$", line)
        if m and term:
            avoid = re.sub(r"\([^)]*\)", "", m.group(1))  # parenthetical notes are not avoid-words
            for w in re.findall(r"`([^`]+)`", avoid):
                if len(w) > 2:
                    out[w.lower()] = term
    return out


def check_terms(f: Findings) -> None:
    terms = avoid_terms()
    if not terms:
        return
    for doc in doc_files():
        text = re.sub(r"```.*?```", "", read(doc), flags=re.S).lower()
        for w, pref in terms.items():
            n = len(re.findall(r"(?<![a-z-])%s(?![a-z-])" % re.escape(w), text))
            if n:
                f.add("terms", "warning", "uses '%s' %dx; see '%s' in CONTEXT.md" % (w, n, pref), rel(doc))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# directory (the published plugin repository)
# ---------------------------------------------------------------------------

MIB = 1024 * 1024
DIR_MAX_FILES = 10000
DIR_REVIEW_FILES = 512
DIR_MAX_UNPACKED = 256 * MIB
DIR_MAX_ZIPPED = 50 * MIB
DIR_MAX_FILE = 5 * MIB
DIR_REVIEW_BINARY = 256 * 1024
README_MIN_WORDS = 40
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif", ".bmp"}
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "._.ds_store", ".localized", "ehthumbs.db"}
WIN_RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}
WIN_BAD_CHARS = set('<>:"|?*') | {chr(i) for i in range(32)}
USER_CONFIG_RE = re.compile(r"\$\{user_config\.([A-Za-z0-9_]+)\}")


def zipped_size(files: Sequence[Path]) -> int:
    """Bytes of a deflate zip of the files (what an archive download of the repository weighs)."""
    import tempfile
    import zipfile
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in files:
                z.write(str(p), rel(p))
        return os.path.getsize(tmp)
    finally:
        os.unlink(tmp)


def is_binary(p: Path) -> bool:
    try:
        with open(str(p), "rb") as fh:
            return b"\0" in fh.read(8192)
    except OSError:
        return False


def directory_stats(files: Sequence[Path]) -> Dict[str, Any]:
    sizes = {p: p.stat().st_size for p in files}
    return {"files": len(files), "bytes": sum(sizes.values()), "zipped": zipped_size(files),
            "largest": max(sizes.items(), key=lambda kv: kv[1]) if sizes else (None, 0), "sizes": sizes}


def check_directory(f: Findings, files: Sequence[Path]) -> Dict[str, Any]:
    """The plugin directory's submission limits, on the files git would publish."""
    st = directory_stats(files)
    if st["files"] >= DIR_MAX_FILES:
        f.add("directory", "error", "%d files (limit %d)" % (st["files"], DIR_MAX_FILES))
    elif st["files"] > DIR_REVIEW_FILES:
        f.add("directory", "warning", "%d files: over %d means a manual review" % (st["files"], DIR_REVIEW_FILES))
    if st["bytes"] >= DIR_MAX_UNPACKED:
        f.add("directory", "error", "%.1f MiB unpacked (limit 256 MiB)" % (st["bytes"] / MIB))
    if st["zipped"] >= DIR_MAX_ZIPPED:
        f.add("directory", "error", "%.1f MiB zipped (limit 50 MiB)" % (st["zipped"] / MIB))
    seen: Dict[str, str] = {}
    for p, size in sorted(st["sizes"].items()):
        r = rel(p)
        if size >= DIR_MAX_FILE:
            f.add("directory", "error", "%.2f MiB (every file stays under 5 MiB)" % (size / MIB), r)
        elif size > DIR_REVIEW_BINARY and p.suffix.lower() not in IMAGE_EXT and is_binary(p):
            f.add("directory", "warning", "non-image binary of %d KiB (over 256 KiB means a manual review)" % (size // 1024), r)
        if p.is_symlink():
            f.add("directory", "error", "symlink", r)
        for part in r.split("/"):
            low = part.lower()
            if low in JUNK_NAMES:
                f.add("directory", "error", "OS junk file", r)
            stem = low.split(".", 1)[0]
            if stem in WIN_RESERVED or any(c in WIN_BAD_CHARS for c in part) or part.endswith((".", " ")):
                f.add("directory", "error", "name %r is not valid on Windows" % part, r)
        key = r.lower()
        if key in seen and seen[key] != r:
            f.add("directory", "error", "differs from %s only in case (breaks on Windows and macOS)" % seen[key], r)
        seen.setdefault(key, r)
    for d, _dirs, _files in os.walk(str(REPO)):
        if ".git" in Path(d).relative_to(REPO).parts:
            continue
        for n in _dirs + _files:
            if (Path(d) / n).is_symlink():
                f.add("directory", "error", "symlink", rel(Path(d) / n))
    if (REPO / ".gitmodules").exists():
        f.add("directory", "error", "git submodules are not allowed", ".gitmodules")
    ga = REPO / ".gitattributes"
    if ga.is_file():
        for i, line in enumerate(read(ga).splitlines(), 1):
            if re.search(r"(?:^|\s)(export-ignore|export-subst|filter=|-?filter\b)", line.split("#", 1)[0]):
                f.add("directory", "error", "no export-ignore/filter (LFS) attributes: %s" % line.strip(), ".gitattributes:%d" % i)
    readme = REPO / "README.md"
    if not readme.is_file():
        f.add("directory", "error", "README.md is missing")
    else:
        words = len(re.findall(r"[A-Za-z]{2,}", re.sub(r"<[^>]+>|```.*?```", " ", read(readme), flags=re.S)))
        if words < README_MIN_WORDS:
            f.add("directory", "error", "README.md has %d words (at least %d)" % (words, README_MIN_WORDS), "README.md")
    if not any((REPO / n).is_file() for n in ("LICENSE", "LICENSE.md", "LICENSE.txt")):
        f.add("directory", "error", "no LICENSE file")
    if (REPO / "bin").exists():
        f.add("directory", "error", "no top-level bin/ in a plugin")
    pj = REPO / ".claude-plugin" / "plugin.json"
    try:
        plugin = json.loads(read(pj))
    except (OSError, ValueError) as e:
        f.add("directory", "error", "plugin.json unreadable: %s" % e, rel(pj))
        return st
    for key in ("name", "description", "version"):
        if not str(plugin.get(key) or "").strip():
            f.add("directory", "error", "plugin.json needs %r" % key, rel(pj))
    author = plugin.get("author")
    if not (isinstance(author, dict) and str(author.get("name") or "").strip()) and not (isinstance(author, str) and author.strip()):
        f.add("directory", "error", "plugin.json needs an author name", rel(pj))
    opts = plugin.get("userConfig") or {}
    for name, spec in sorted(opts.items()):
        if not isinstance(spec, dict) or "default" not in spec:
            f.add("directory", "error", "userConfig %r has no default (Cowork ignores MCP servers that use it)" % name, rel(pj))
    used = set(USER_CONFIG_RE.findall(json.dumps(plugin)))
    mcp = REPO / ".mcp.json"
    if mcp.is_file():
        used |= set(USER_CONFIG_RE.findall(read(mcp)))
    for name in sorted(used - set(opts)):
        f.add("directory", "error", "${user_config.%s} is used but not declared in userConfig" % name, rel(pj))
    return st


def run_checks(fix: bool = False, set_version: Optional[str] = None,
               only: Optional[Iterable[str]] = None) -> Findings:
    f = Findings()
    default = ["versions", "skill", "links", "commands", "agents", "paths", "names", "terms", "media"]
    if not (REPO / "examples").is_dir():
        default.append("directory")   # the plugin repository (the examples have their own)
    want = set(only or default)
    if "versions" in want:
        check_versions(f, fix, set_version)
    if "skill" in want:
        check_skill(f)
    if "links" in want:
        check_links(f)
    if "commands" in want:
        check_commands(f)
    if "agents" in want:
        check_agents(f)
    if want & {"paths", "names"}:
        check_paths_and_names(f, shipped_files())
    if "terms" in want:
        check_terms(f)
    if "media" in want:
        check_media(f, shipped_files())
    if "directory" in want:
        check_directory(f, shipped_files())
    return f


def load_publish_media():
    """scripts/publish_media.py as a module (None when it is missing)."""
    path = REPO / "scripts" / "publish_media.py"
    if not path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("publish_media", str(path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def check_media(f: Findings, files: Sequence[Path]) -> None:
    """Committed videos stay under 20 MB each (decimal), and no *.work/ render folder ships. Large example
    media (over 10 MB, every .mov) are release assets: listed in examples/MEDIA.json and ignored by git
    (scripts/publish_media.py)."""
    pm = load_publish_media()
    if pm is not None and (REPO / "examples").is_dir():
        gi = REPO / ".gitignore"
        res = pm.verify(pm.load_manifest(), gi.read_text(encoding="utf-8") if gi.is_file() else "")
        for m in res["errors"]:
            f.add("media", "error", m, "examples/MEDIA.json")
        for m in res["warnings"]:
            f.add("media", "warning", m, "examples/MEDIA.json")
    for p in files:
        if p.suffix.lower() in MEDIA_EXT:
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > MAX_MEDIA_BYTES:
                f.add("media", "error", "%s is %.1f MB; committed videos stay under %d MB (showtime deliver exports "
                      "<file> --targets original --max-mb 20)" % (p.name, size / 1e6, MAX_MEDIA_BYTES // 1000000), rel(p))
        if any(part.endswith(".work") for part in p.relative_to(REPO).parts[:-1]):
            f.add("media", "error", "render work folder would be published", rel(p))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="showtime release checks (see the module docstring).",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Examples:\n  python scripts/check_release.py --check\n"
                                        "  python scripts/check_release.py --set-version 0.2.0\n"
                                        "  python scripts/check_release.py --check --only commands,links")
    ap.add_argument("--check", action="store_true", help="report only; never modify files")
    ap.add_argument("--set-version", metavar="X.Y.Z", help="bump every version field to X.Y.Z")
    ap.add_argument("--only", help="comma list: versions,skill,links,commands,agents,paths,names,terms,media,directory")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args(argv)
    if args.check and args.set_version:
        ap.error("--set-version changes files; drop --check")
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    f = run_checks(fix=not args.check, set_version=args.set_version, only=only)
    errs = f.errors()
    if args.json:
        print(json.dumps({"ok": not errs, "version": args.set_version or lib_version(), "findings": f.items},
                         indent=2))
    else:
        for it in f.items:
            print("%-7s %-9s %s%s" % (it["level"].upper(), it["check"], it["message"],
                                      ("  (%s)" % it["where"]) if it["where"] else ""))
        warns = len(f.items) - len(errs)
        print("check_release: %d error(s), %d warning(s), version %s" % (len(errs), warns,
                                                                         args.set_version or lib_version()))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
