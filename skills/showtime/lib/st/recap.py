"""A Claude Code session -> a short narrated film of what the agent did (`showtime recap`).

Claude Code keeps every session as JSONL under ~/.claude/projects/<project>/<session>.jsonl (sub-agents under
<session>/subagents/). A transcript holds everything: assistant text, tool output, memory, system reminders,
keys printed by mistake, other projects. So recap reads it through an ALLOW-LIST and keeps only:

- a title and hook made from the facts; the request and a sub-agent's description only as commented
  suggestions in script.md (strictly cleaned; never kept in the facts), film text only if uncommented;
- tool NAMES and counts; file paths RELATIVE to the repository, for files inside it only;
- commands as a program name from ALLOWED_PROGRAMS (else "other") with the program's own subcommand
  (`git commit`, `npm test`); never a script or module path, never any other argument;
- test runs as counts (passed / failed) read from their output; commits whose printed hash is in this repository's
  history, and their diff stats from git; durations and timestamps.

Nothing else (assistant text, tool output, reminders, URLs, absolute paths, environment) is on the list: tool
output is read only to count test results and to find the commits made. A HARD FILTER then drops any line that
still looks like a key or token (vendor prefixes, long hex or key-like runs, a key name with its value), an
absolute path, a URL, a host or an e-mail address, before script.md is written and again when it is read back
(the user may edit it). Filters can miss things, so nothing is rendered until the person has read script.md.

Everything the film shows or speaks is in <out>/script.md, one keyed line each, written before anything is
rendered. Stdlib only.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shlex
import unicodedata
import subprocess
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from . import bed
from . import pr_video as pv
from . import release_video as rv
from .common import ShowtimeError

# ---------------------------------------------------------------------------
# finding a transcript
# ---------------------------------------------------------------------------


def claude_dir() -> Path:
    """Claude Code's config folder (CLAUDE_CONFIG_DIR, else ~/.claude)."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def project_slug(path: Path) -> str:
    """The folder name Claude Code gives a working directory under projects/ (every non-alphanumeric -> '-')."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def latest_session(cwd: Path) -> Path:
    """The newest top-level session transcript of this folder (or of the nearest parent that has one)."""
    base = claude_dir() / "projects"
    here = Path(cwd).resolve()
    for d in [here] + list(here.parents):
        folder = base / project_slug(d)
        if folder.is_dir():
            found = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            found = [f for f in found if is_transcript(f)]
            if found:
                return found[0]
    raise ShowtimeError("no Claude Code session found for %s" % here.name,
                        why="looked for transcripts under %s/projects/<this folder>/" % "~/.claude",
                        hint="pass the transcript: showtime recap <session.jsonl> (or a session id)")


def is_transcript(path: Path, probe: int = 200) -> bool:
    """Whether a file is a Claude Code transcript: a .jsonl whose first lines include a user or assistant event
    with a message and the session's ids (Claude Code writes sessionId and uuid on every event)."""
    path = Path(path)
    if path.suffix.lower() != ".jsonl" or not path.is_file():
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= probe:
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("type") in ("user", "assistant") and \
                        isinstance(d.get("message"), dict) and (d.get("sessionId") or d.get("uuid")):
                    return True
    except OSError:
        return False
    return False


def find_session(ref: str) -> Path:
    """A transcript path, or a session id (or an agent id) looked up under ~/.claude/projects. Anything that is
    not a Claude Code transcript is refused."""
    p = Path(ref).expanduser()
    if p.is_file():
        if not is_transcript(p):
            raise ShowtimeError("%s is not a Claude Code session transcript" % p.name,
                                why="recap reads only .jsonl transcripts with Claude Code's user/assistant events",
                                hint="pass a file from ~/.claude/projects/<project>/, a session id, or --latest")
        return p
    if re.fullmatch(r"[A-Za-z0-9-]{6,64}", ref or ""):
        base = claude_dir() / "projects"
        hits = list(base.glob("*/%s.jsonl" % ref)) + list(base.glob("*/*/subagents/%s.jsonl" % ref)) + \
            list(base.glob("*/*/subagents/agent-%s.jsonl" % ref))
        hits = [h for h in hits if is_transcript(h)]
        if hits:
            return hits[0]
    raise ShowtimeError("session transcript not found: %s" % (p.name or ref),
                        hint="pass a .jsonl file from ~/.claude/projects/<project>/, a session id, or --latest")


# ---------------------------------------------------------------------------
# reading: tolerant of unknown event types, versions and broken lines
# ---------------------------------------------------------------------------


def iter_events(path: Path) -> Iterator[Dict[str, Any]]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                yield d


def parse_ts(s: Any) -> Optional[float]:
    if isinstance(s, (int, float)):
        return float(s) / (1000.0 if s > 1e11 else 1.0)
    if not isinstance(s, str) or not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _blocks(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _result_text(block: Dict[str, Any]) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    return "\n".join(str(b.get("text") or "") for b in _blocks(c) if b.get("type") == "text")


RESULT_KEEP = 64 * 1024        # the end of a command's output is where runners print their counts
REQUEST_KEEP = 8 * 1024        # the request's head: everything recap offers from it is in its first sentences
REQUEST_SCAN = 512 * 1024      # how much of the first message is searched for tagged blocks before the cut
COMMAND_KEEP = 64 * 1024       # a command line longer than this is cut before it is tokenised
_NOT_A_REQUEST = re.compile(r"^\s*(<command-|<local-command|<bash-|<task-notification|Caveat:|\[Request interrupted)")


def parse_session(path: Path) -> Dict[str, Any]:
    """The raw material recap may use, kept in memory only (never written): timestamps, working folders, the
    first request, tool calls with their inputs, and tool results (read only to count tests and commits)."""
    path = Path(path)
    ses: Dict[str, Any] = {"path": str(path), "start": None, "end": None, "cwds": Counter(), "request": "",
                           "description": "", "turns": set(), "uses": [], "results": {}, "events": 0,
                           "kind": "session", "times": []}
    run_ids = set()                           # tool results are kept only for commands (tests, commits), cut short
    meta = path.with_name(path.name[:-len(".jsonl")] + ".meta.json") if path.name.endswith(".jsonl") else None
    if meta is not None and meta.is_file():
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            ses["description"] = str(m.get("description") or "") if isinstance(m, dict) else ""
        except (OSError, ValueError):
            pass
    if path.parent.name == "subagents":
        ses["kind"] = "sub-agent"
    for d in iter_events(path):
        ses["events"] += 1
        ts = parse_ts(d.get("timestamp"))
        if ts is not None:
            ses["start"] = ts if ses["start"] is None else min(ses["start"], ts)
            ses["end"] = ts if ses["end"] is None else max(ses["end"], ts)
            ses["times"].append(ts)
        cwd = d.get("cwd") if isinstance(d.get("cwd"), str) else ""
        if cwd:
            ses["cwds"][cwd] += 1
        if d.get("isSidechain") and ses["kind"] == "session" and path.parent.name == "subagents":
            ses["kind"] = "sub-agent"
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        typ = d.get("type")
        if typ == "user":
            texts = []
            for b in _blocks(msg.get("content")):
                if b.get("type") == "tool_result" and b.get("tool_use_id"):
                    if b["tool_use_id"] in run_ids:
                        ses["results"][b["tool_use_id"]] = {"ts": ts, "text": _result_text(b)[-RESULT_KEEP:],
                                                            "error": bool(b.get("is_error"))}
                    elif b["tool_use_id"]:
                        ses["results"][b["tool_use_id"]] = {"ts": ts, "text": "", "error": bool(b.get("is_error"))}
                elif b.get("type") == "text":
                    t = str(b.get("text") or "")
                    if t.strip() and not _NOT_A_REQUEST.match(t):
                        texts.append(t)
            # text blocks that are wrappers (they start with a block-style tag) go whole; then tagged blocks
            # (however long); then the cut: only the request's first sentences are offered
            texts = [x for x in texts if not _WRAPPER_BLOCK.match(x)]
            joined = _strip_tags("\n\n".join(texts))[:REQUEST_KEEP] if texts and not ses["request"] else ""
            if joined.strip() and not d.get("isMeta") and not d.get("isCompactSummary") and \
                    not d.get("isVisibleInTranscriptOnly"):
                ses["request"] = joined
        elif typ == "assistant":
            mid = msg.get("id") or d.get("requestId") or d.get("uuid")
            if mid:
                ses["turns"].add(mid)
            for b in _blocks(msg.get("content")):
                if b.get("type") in ("tool_use", "server_tool_use") and b.get("name"):
                    ses["uses"].append({"ts": ts, "id": b.get("id") or "", "name": str(b["name"]), "cwd": cwd,
                                        "input": b.get("input") if isinstance(b.get("input"), dict) else {}})
                    if str(b["name"]) in RUN_TOOLS and b.get("id"):
                        run_ids.add(b["id"])
    if not ses["events"]:
        raise ShowtimeError("%s has no readable events" % path.name,
                            hint="pass a Claude Code session transcript (.jsonl, one JSON event per line)")
    return ses


# ---------------------------------------------------------------------------
# the repository: which absolute paths are "inside", and their relative names
# ---------------------------------------------------------------------------


def _git(args: Sequence[str], cwd: Optional[str] = None, timeout: int = 60) -> Tuple[int, str]:
    try:
        cp = subprocess.run(["git"] + list(args), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return cp.returncode, cp.stdout


def git_toplevel(path: str) -> Optional[str]:
    if not path or not os.path.isdir(path):
        return None
    rc, out = _git(["rev-parse", "--show-toplevel"], cwd=path)
    return _norm(out.strip()) if rc == 0 and out.strip() else None


def _common_dir(top: str) -> str:
    rc, out = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=top)
    return _norm(out.strip()) if rc == 0 else ""


def _norm(p: str) -> str:
    p = (p or "").replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):
        p = p[0].lower() + p[1:]
    return os.path.normpath(p).replace("\\", "/") if p else p


_WORKTREE = re.compile(r"^(.*?/(?:\.claude/worktrees|\.worktrees|worktrees)/[^/]+)(?:/|$)")


def repo_roots(ses: Dict[str, Any], repo: Optional[str] = None) -> Tuple[str, List[str]]:
    """(the repository's top folder, every root a session path may sit under). The roots are the repository,
    and the session's own working trees when they belong to it (a git worktree of the same repository, or a
    worktree folder inside it that has since been removed)."""
    if repo:
        top = git_toplevel(os.path.abspath(os.path.expanduser(repo)))
        if not top:
            raise ShowtimeError("--repo %s is not a git repository" % Path(repo).name,
                                hint="pass the folder of the repository the session worked in")
    else:
        cwd = ses["cwds"].most_common(1)[0][0] if ses["cwds"] else ""
        top = git_toplevel(cwd)
        if not top:
            raise ShowtimeError("the session's working folder is not a git repository here (or no longer exists)",
                                why="recap shows only files inside one repository, as paths relative to it",
                                hint="pass --repo <the repository folder>")
    top = _real(top)                             # git echoes the folder it was given (an 8.3 short name on Windows)
    roots = [top]
    common = _common_dir(top)
    for cwd in ses["cwds"]:
        c = _real(cwd)
        if os.path.isdir(c):
            t = git_toplevel(c)
            t = _real(t) if t else t
            if t and t not in roots and common and _common_dir(t) == common:
                roots.append(t)
        elif c.startswith(top + "/"):
            m = _WORKTREE.match(c)               # a worktree under the repository that has since been removed
            if m and m.group(1) not in roots:
                roots.append(m.group(1))
    roots.sort(key=len, reverse=True)
    return top, roots


def _real(p: str) -> str:
    """The path with symlinked folders resolved (/tmp -> /private/tmp) and, on Windows, 8.3 short names
    (RUNNER~1) expanded, as git reports its folders."""
    p = _norm(p)
    if p.startswith("/") or (os.name == "nt" and re.match(r"^[a-z]:/", p)):
        try:
            return _norm(os.path.realpath(p))
        except (OSError, ValueError):
            return p
    return p


def inside(p: str, roots: Sequence[str]) -> bool:
    """Whether an absolute folder or file lies inside one of the roots (symlinks resolved)."""
    if not p:
        return False
    for q in {_norm(p), _real(p)}:
        if any(q == r or q.startswith(r + "/") for r in roots):
            return True
    return False


def rel_path(p: Any, roots: Sequence[str], cwd: str = "") -> Optional[str]:
    """The path relative to the repository when it is inside one of `roots`, else None. Secret files (.env,
    keys) and the .git folder count as outside."""
    if not isinstance(p, str) or not p.strip():
        return None
    p = p.strip().replace("\\", "/")
    if p.startswith("~"):
        return None
    if not (p.startswith("/") or re.match(r"^[A-Za-z]:/", p)):
        if not cwd:
            return None
        p = cwd.replace("\\", "/").rstrip("/") + "/" + p
    for q in dict.fromkeys([_norm(p), _real(p)]):
        for r in roots:
            if q.startswith(r + "/"):
                rel = q[len(r) + 1:]
                rel = re.sub(r"^(?:\.claude/worktrees|\.worktrees)/[^/]+/", "", rel)
                return rel if _repo_file_ok(rel) and rel != ".git" else None
    return None


_SAFE_REL = re.compile(r"^[\w.@+-]+(?:/[\w.@+ -]+)*$")


def _repo_file_ok(rel: str) -> bool:
    return bool(rel) and not rel.startswith(("../", ".git/")) and not pv.is_secret_file(rel) and bool(_SAFE_REL.match(rel))

# ---------------------------------------------------------------------------
# commands: program + subcommand, nothing else
# ---------------------------------------------------------------------------

# a program's own subcommands (never an alias, plugin, extension or target the user named)
_W = lambda s: set(s.split())  # noqa: E731
KNOWN_SUBCOMMANDS: Dict[str, set] = {
    "git": _W("add am apply archive bisect blame branch bundle checkout cherry-pick clean clone commit config describe "
              "diff fetch format-patch gc grep init log ls-files ls-remote ls-tree merge merge-base mv notes pull push "
              "range-diff rebase reflog remote reset restore rev-list rev-parse revert rm shortlog show show-ref stash "
              "status submodule switch tag worktree cat-file hash-object update-index for-each-ref name-rev"),
    "gh": _W("api auth browse cache codespace extension gist issue label pr release repo ruleset run search secret "
             "status variable workflow"),
    "npm": _W("ci install i uninstall update test run exec init pack publish version ls audit outdated start build "
              "link prune rebuild view"),
    "pnpm": _W("install i add remove update test run exec dlx build start"),
    "yarn": _W("install add remove upgrade test run exec dlx build start"),
    "bun": _W("install add remove update test run x build"),
    "pip": _W("install uninstall list show freeze download wheel check"),
    "pip3": _W("install uninstall list show freeze download wheel check"),
    "uv": _W("pip run sync lock add remove venv tool python init build"),
    "poetry": _W("install add remove update lock run build publish show check init"),
    "cargo": _W("build check test run bench clean doc fmt clippy add remove update install publish nextest tree"),
    "go": _W("build test run vet fmt get install mod generate clean list tool version env work"),
    "docker": _W("build run exec ps images pull push compose logs stop start rm rmi inspect tag network volume"),
    "brew": _W("install uninstall upgrade update list info search doctor"),
    "dotnet": _W("build test run restore publish new add clean pack"),
    "deno": _W("run test fmt lint check compile task cache"),
    "conda": _W("install create activate list env update remove"),
    "rustup": _W("update install default toolchain component target show"),
    "swift": _W("build test run package"),
    "kubectl": _W("get describe apply delete logs exec rollout create edit scale port-forward"),
    "helm": _W("install upgrade uninstall list template lint repo dependency"),
    "terraform": _W("init plan apply destroy validate fmt output state"),
}
# programs whose next word is the user's own (a make target, a rake task): only generic ones show
USER_TARGETS = {"make", "rake", "mix", "gradle", "mvn", "bundle", "just", "task"}
GENERIC_TARGETS = _W("test tests check build lint install clean all run exec format fmt dev release compile package "
                     "verify deps setup docs serve start")
INTERPRETERS = {"python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl", "php", "tsx", "ts-node", "deno"}
WRAPPERS = {"sudo", "time", "nice", "nohup", "env", "command", "exec", "caffeinate", "xargs"}
NOT_COUNTED = {"cd", "export", "set", "unset", "source", ".", "true", "false", ":", "pushd", "popd", "wait", "local",
               "declare", "trap", "shopt", "alias", "then", "else", "fi", "do", "done", "esac", "if", "for", "while",
               "case", "in", "{", "}", "(", ")", "!", "function", "return", "break", "continue"}
_PROGRAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
_SUBCMD = re.compile(r"^[a-z][a-z0-9-]{0,24}$")
_HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_]\w*)\1")
_SEPARATORS = {"&&", "||", ";", "|", "&", ";;", "|&", "(", ")"}


def _showtime_commands() -> set:
    """showtime's own commands (read from the cli modules without importing them), for `showtime <command>`."""
    out = {"setup", "doctor", "version", "mcp", "help"}
    try:
        from .cli import discover, read_commands
        for _name, path in discover():
            out |= set(read_commands(path))
        scripts = Path(__file__).resolve().parents[2] / "scripts"      # the node commands (render, check, ...)
        out |= {f.stem for f in scripts.glob("*.mjs") if not f.name.startswith("_")}
    except Exception:  # noqa: BLE001 - a label is never worth a crash
        pass
    return out


def _strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies (inline scripts): they are data for the program, not commands."""
    out: List[str] = []
    lines = cmd.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC.search(line)
        out.append(line[:m.start()] if m else line)
        i += 1
        if m:
            end = m.group(2)
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1
    return "\n".join(out)


def _segments(cmd: str) -> List[List[str]]:
    text = _strip_heredocs((cmd or "")[:COMMAND_KEEP])
    # backslashes are kept (Windows paths), so a drive-letter folder is still recognisable as one
    text = text.replace("\\", "/")
    try:
        lex = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        toks = []
        for part in re.split(r"&&|\|\||[;|\n&]", text):
            toks += part.split() + [";"]
    segs: List[List[str]] = [[]]
    skip = False
    for t in toks:
        if skip:
            skip = False
            continue
        if t in _SEPARATORS:
            if segs[-1]:
                segs.append([])
            continue
        if t and set(t) <= set("&|;()<>"):            # a redirection: drop it and its target (2>/dev/null)
            if segs[-1] and segs[-1][-1].isdigit():
                segs[-1].pop()
            skip = not t.endswith("&") or t == ">&"
            continue
        segs[-1].append(t)
    return [s for s in segs if s]


def _strip_wrappers(toks: List[str]) -> List[str]:
    while toks and (re.match(r"^[A-Za-z_]\w*=", toks[0]) or toks[0] in WRAPPERS or toks[0] == "timeout"):
        if toks[0] == "timeout":
            toks = toks[1:]
            while toks and (toks[0].startswith("-") or re.match(r"^\d+(\.\d+)?[smhd]?$", toks[0])):
                toks = toks[1:]
            continue
        if toks[0] in ("sudo", "env", "nice"):         # their own options (sudo -u user, env -i, nice -n 10)
            rest = toks[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in ("-u", "-g", "-n", "-C", "-S") and len(rest) > 1 else rest[1:]
            toks = rest
            continue
        toks = toks[1:]
    return toks


# Programs whose names may be shown: the only place this list lives. Anything else counts as "other" (a client's
# CLI on PATH, a script of the user's own, a PowerShell function): a program's name can be private too.
COMMON_TOOLS = _W("ls cat grep egrep fgrep rg ag sed awk find fd curl wget jq yq ffmpeg ffprobe head tail wc sort uniq "
                  "cut tr tee xargs diff cmp echo printf mkdir rmdir rm cp mv ln touch chmod chown du df tar zip unzip "
                  "gzip gunzip which file stat basename dirname realpath readlink date sleep ps kill pkill pgrep top "
                  "ssh scp rsync open less more vim vi nano code tmux screen sqlite3 psql mysql redis-cli openssl "
                  "cmake ninja gcc g++ clang clang++ rustc javac java tsc eslint prettier ruff black mypy flake8 isort "
                  "pylint pyright hatch pdm pipenv rye pwsh powershell fish apt apt-get dnf yum pacman node npx pnpx "
                  "bunx gradlew ant sbt lein clj elixir erl ghc stack cabal zig nim crystal lua luajit julia R Rscript "
                  "xcodebuild xcrun swiftc adb emulator flutter dart kotlinc magick convert identify sox whisper "
                  "pandoc latexmk pdflatex dot gs exiftool watch timeout nc dig host ping traceroute lsof killall "
                  "base64 sha256sum shasum md5 md5sum xxd hexdump strings nm otool ldd")
RUNNER_MODULES = _W("pytest unittest pip venv doctest coverage tox nox build twine")   # python -m <these> only
ALLOWED_PROGRAMS = (set(KNOWN_SUBCOMMANDS) | INTERPRETERS | USER_TARGETS | COMMON_TOOLS | {"showtime"} |
                    {"pytest", "py.test", "jest", "vitest", "mocha", "rspec", "tox", "nox", "phpunit", "ctest", "ava",
                     "tap"})
OTHER = "other"


def _program(tok: str) -> str:
    prog = tok.replace("\\", "/").rsplit("/", 1)[-1]
    prog = re.sub(r"^(python3?)\.\d+$", r"\1", prog)
    return re.sub(r"\.(exe|cmd|bat)$", "", prog, flags=re.I)


def command_labels(cmd: str, *, cwd: str = "", roots: Sequence[str] = ()) -> List[str]:
    """`cd x && FOO=1 python3 tests/run_all.py -k y | tail -3` -> ['python3', 'tail'].

    A program's name only when it is on ALLOWED_PROGRAMS (by its file name: ~/.venv/bin/python3.12 is python3),
    a subcommand the program itself defines (`git commit`; never an alias, plugin or extension; a make target only
    when generic), and `-m <module>` only for the runner modules (python -m pytest). Never a script or module path
    of the user's own, whatever folder the command runs in; every other program counts as "other"."""
    labels: List[str] = []
    st_cmds = None
    for seg in _segments(cmd):
        toks = _strip_wrappers(_strip_builtins(list(seg)))
        if not toks or toks[0] in FOLDER_CHANGERS:
            continue
        prog = _program(toks[0])
        if prog in NOT_COUNTED:
            continue
        if prog not in ALLOWED_PROGRAMS or not _PROGRAM.match(prog):
            labels.append(OTHER)
            continue
        rest = toks[1:]
        label = prog
        if prog in KNOWN_SUBCOMMANDS or prog == "showtime":
            while rest and prog == "git" and rest[0] in ("-C", "-c", "--git-dir", "--work-tree") and len(rest) > 1:
                rest = rest[2:]
            while rest and rest[0] in ("--no-pager", "--paginate", "-P"):
                rest = rest[1:]
            if prog == "showtime" and st_cmds is None:
                st_cmds = _showtime_commands()
            known = st_cmds if prog == "showtime" else KNOWN_SUBCOMMANDS[prog]
            if rest and _SUBCMD.match(rest[0]) and rest[0] in known:
                label = "%s %s" % (prog, rest[0])
        elif prog in USER_TARGETS:
            if rest and rest[0] in GENERIC_TARGETS:
                label = "%s %s" % (prog, rest[0])
        elif prog in ("python", "python3"):
            args = [a for a in rest if a != "-u" and not re.match(r"^-[BIOEsSuWX]+$", a)]
            if len(args) >= 2 and args[0] == "-m" and args[1] in RUNNER_MODULES:
                label = "%s -m %s" % (prog, args[1])
        labels.append(label)
    return labels


# folder changes: not programs, never shown or counted
FOLDER_CHANGERS = {"cd", "pushd", "popd", "chdir", "Set-Location", "Push-Location", "Pop-Location", "sl", "z", "zoxide",
                   "j", "autojump"}


def _strip_builtins(toks: List[str]) -> List[str]:
    while toks and toks[0] in ("command", "builtin", "{", "}", "then", "do", "else", "!", "exec", "noglob"):
        toks = toks[1:]
    return toks


# ---------------------------------------------------------------------------
# tests: which commands ran tests, and their counts
# ---------------------------------------------------------------------------

RUNNERS = {"pytest", "py.test", "jest", "vitest", "mocha", "rspec", "tox", "nox", "phpunit", "ctest", "ava", "tap"}
_NOT_A_RUN = {"--version", "-V", "--help", "-h", "--collect-only", "--co", "--list", "--listTests"}
_LAUNCHERS = {"npx", "bunx", "pnpx"}                                 # npx <tool> ...
_RUN_VIA = {("uv", "run"), ("poetry", "run"), ("bundle", "exec"), ("pnpm", "exec"), ("yarn", "dlx"), ("pnpm", "dlx"),
            ("hatch", "run"), ("pdm", "run"), ("pipenv", "run"), ("rye", "run")}
_SSH_OPTS_WITH_ARG = set("bcDEeFIiJLlmOopQRSWw")


def _is_test_segment(toks: List[str], depth: int = 0) -> bool:
    """A test runner in the program position (after wrappers and launchers such as npx or uv run)."""
    toks = _strip_wrappers(list(toks))
    if not toks or depth > 4:
        return False
    prog = toks[0].rsplit("/", 1)[-1]
    prog = re.sub(r"^(python3?)\.\d+$", r"\1", prog)
    rest = toks[1:]
    if any(a in _NOT_A_RUN for a in rest):
        return False
    if prog in _LAUNCHERS:
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return _is_test_segment(rest, depth + 1)
    if rest and (prog, rest[0]) in _RUN_VIA:
        return _is_test_segment(rest[1:], depth + 1)
    if prog == "docker" and len(rest) >= 3 and rest[0] == "exec":
        i = 1
        while i < len(rest) and rest[i].startswith("-"):
            i += 1
        return _is_test_segment(rest[i + 1:], depth + 1)
    if prog in RUNNERS:
        return True
    if prog in ("python", "python3"):
        args = [a for a in rest if not re.match(r"^-[BIOEsSuWX]+$", a)]
        if len(args) >= 2 and args[0] == "-m":
            return args[1] in ("pytest", "unittest")
        return bool(args) and bool(re.search(r"(^|/)(run_all\.py|test_[\w-]+\.py|[\w-]+_test\.py)$", args[0]))
    if prog == "node":
        return "--test" in rest or bool(rest and re.search(r"(^|/)(test_[\w-]+|[\w-]+\.test)\.(js|mjs|cjs)$", rest[0]))
    if prog in ("npm", "pnpm", "yarn", "bun"):
        return bool(rest) and (rest[0] in ("test", "t") or (rest[0] == "run" and len(rest) > 1 and
                                                             rest[1].split(":")[0] == "test"))
    if prog in ("go", "deno", "dotnet", "swift", "mix") or prog in ("mvn", "gradle", "gradlew"):
        return bool(rest) and rest[0] == "test"
    if prog == "cargo":
        return bool(rest) and rest[0] in ("test", "nextest")
    if prog == "make":
        return bool(rest) and rest[0] in ("test", "tests", "check")
    return False


def _runner_texts(cmd: str, depth: int = 0) -> Iterator[List[str]]:
    """The command's segments, with the remote command of ssh and the script of bash -c opened."""
    for seg in _segments(cmd):
        toks = _strip_wrappers(list(seg))
        if not toks:
            continue
        prog = toks[0].rsplit("/", 1)[-1]
        if depth < 3 and prog == "ssh":
            rest, i = toks[1:], 0
            while i < len(rest) and rest[i].startswith("-"):
                i += 2 if (len(rest[i]) == 2 and rest[i][1] in _SSH_OPTS_WITH_ARG) else 1
            for x in _runner_texts(" ".join(rest[i + 1:]), depth + 1):
                yield x
            continue
        if depth < 3 and prog in ("bash", "sh", "zsh") and "-c" in toks[1:-1]:
            for x in _runner_texts(toks[toks.index("-c") + 1], depth + 1):
                yield x
            continue
        yield toks


def is_test_command(cmd: str) -> bool:
    return any(_is_test_segment(t) for t in _runner_texts(cmd or ""))


def test_counts(text: str) -> Optional[Dict[str, Any]]:
    """Counts from a test runner's output: {passed, failed, unit} (summed when one output holds several
    runs), or None when it shows none."""
    text = text or ""
    passed = failed = 0
    unit = ""
    for m in re.finditer(r"\b(\d+)/(\d+) test files passed\b", text):             # showtime's run_all.py
        p, n = int(m.group(1)), int(m.group(2))
        passed, failed, unit = passed + p, failed + max(0, n - p), "test files"
    if not unit:
        for m in re.finditer(r"^Ran (\d+) tests? in [\d.]+s\s*\n+\s*(OK|FAILED)\b(?:\s*\(([^)]*)\))?", text, re.M):
            n = int(m.group(1))
            f = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", m.group(3) or ""))
            s = sum(int(x) for x in re.findall(r"skipped=(\d+)", m.group(3) or ""))
            passed, failed, unit = passed + max(0, n - f - s), failed + f, "tests"
    if not unit:
        for m in re.finditer(r"^=+ ([^\n]{0,400}?\b(?:passed|failed|error|errors)\b[^\n]{0,400}?) in [\d.]+s",
                             text, re.M):                                         # pytest
            s = m.group(1)
            passed += sum(int(x) for x in re.findall(r"(\d+) passed", s))
            failed += sum(int(x) for x in re.findall(r"(\d+) (?:failed|errors?)\b", s))
            unit = "tests"
    if not unit:
        for m in re.finditer(r"^Tests:[ \t]+([^\n]{0,400}?)(\d+) total", text, re.M):   # jest / vitest
            passed += sum(int(x) for x in re.findall(r"(\d+) passed", m.group(1)))
            failed += sum(int(x) for x in re.findall(r"(\d+) failed", m.group(1)))
            unit = "tests"
    if not unit:
        for m in re.finditer(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed", text):    # cargo
            passed, failed, unit = passed + int(m.group(1)), failed + int(m.group(2)), "tests"
    if not unit:
        ps = re.findall(r"^(?:#|ℹ)\s*pass (\d+)", text, re.M)                  # node --test
        fs = re.findall(r"^(?:#|ℹ)\s*fail (\d+)", text, re.M)
        if ps or fs:
            passed, failed, unit = sum(map(int, ps)), sum(map(int, fs)), "tests"
    if not unit:
        oks = len(re.findall(r"^ok\s+\S+", text, re.M))                             # go test
        fails = len(re.findall(r"^FAIL\s+\S+", text, re.M))
        if oks or fails:
            passed, failed, unit = oks, fails, "packages"
    if not unit:
        for m in re.finditer(r"\bpass(?:ed)?[ :=]+(\d+)[,;]?\s+fail(?:ed|ures?)?[ :=]+(\d+)", text, re.I):
            passed, failed, unit = passed + int(m.group(1)), failed + int(m.group(2)), "runs"
    if not unit:
        oks = len(re.findall(r"^OK\b", text, re.M))                                 # unittest, its counts cut off
        bad = re.findall(r"^FAILED \(([^)]*)\)", text, re.M)
        if oks or bad:
            return {"passed": None, "failed": None, "unit": "", "status": "fail" if bad else "ok"}
        return None
    return {"passed": passed, "failed": failed, "unit": unit}


_COMMIT_SHA = re.compile(r"^\[[^\]\n]*?\s([0-9a-f]{7,40})\]", re.M)

# ---------------------------------------------------------------------------
# the hard filter: after the allow-list, on every line shown, spoken or written
# ---------------------------------------------------------------------------

_ABS_PATH = re.compile(
    r"(?:^|[\s\"'`=(\[{<,:;])(?:/[^\s/\"'`]+/|/(?:Users|home|private|var|tmp|etc|opt|usr|Volumes|mnt|root|srv|"
    r"Library|System|Applications|proc|dev|bin|sbin|nix|snap|workspace|workspaces|app|data)\b)"
    r"|(?:^|[^\w])~[/\\]|\b[A-Za-z]:[\\/]|\\\\[\w.$-]+\\|%[A-Z]+%[\\/]|\$(?:HOME|TMPDIR|USERPROFILE)\b", re.I)
# every pattern below is bounded (no unlimited run before a fixed character), so a 60 KB token costs linear time
_URL = re.compile(r"(?<![\w+.-])[A-Za-z][\w+.-]{0,30}://|\bwww\.[\w-]{1,63}\.\w", re.I)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}\b")
MAX_TOKEN = 120        # a single unbroken run longer than this is never film text: dropped without more matching
# prefixed key shapes (each vendor's documented prefix), whatever the rest of the line looks like
_PREFIXED = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[sr]k_(?:live|test)_[A-Za-z0-9]{8,}|pk_(?:live|test)_[A-Za-z0-9]{8,}|sk-(?:[A-Za-z0-9]+-)*[A-Za-z0-9_-]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[abposr]-[A-Za-z0-9-]{8,}|xapp-[A-Za-z0-9-]{8,}|"
    r"glpat-[A-Za-z0-9_-]{10,}|AIza[0-9A-Za-z_-]{20,}|(?:AKIA|ASIA)[0-9A-Z]{12,}|npm_[A-Za-z0-9]{20,}|"
    r"hf_[A-Za-z0-9]{20,}|SG\.[A-Za-z0-9_-]{16,}|shp(?:at|ss|ca|pa)_[A-Fa-f0-9]{16,}|dop_v1_[a-f0-9]{16,}|"
    r"ya29\.[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|pypi-[A-Za-z0-9_-]{16,}|"
    r"sq0[a-z]{3}-[A-Za-z0-9_-]{16,}|AC[a-f0-9]{32}|whsec_[A-Za-z0-9]{16,}|rk_[A-Za-z0-9]{16,})")
_HEX_RUN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{20,}(?![0-9A-Fa-f])")
_KEY_RUN = re.compile(r"[A-Za-z0-9+/=_-]{30,}")
_KEY_WORD = (r"(?:api[ _-]?keys?|access[ _-]?keys?|secret(?:[ _-]?keys?)?|secrets|tokens?|passw(?:or)?ds?|passwd|pwd|"
             r"pass ?phrase|credentials?|creds|auth(?:[ _-]?key)?|private[ _-]?key|client[ _-]?secret|bearer|"
             r"session[ _-]?(?:id|key)|cookie|otp|pin)")
_KEY_VALUE = re.compile(r"(?i)\b%s\s*[:=]\s*[\"']?\S{6,}" % _KEY_WORD)
_BEARER = re.compile(r"(?i)\bbearer\s+\S{12,}")
_IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|(?<![\w:])(?=[0-9A-Fa-f:]*[0-9A-Fa-f])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")
_HOST_TLDS = ("com|net|org|io|dev|app|ai|co|cloud|internal|local|lan|corp|intranet|home|private|xyz|tech|site|"
              "online|info|biz|me|tv|us|uk|ca|de|fr|es|mx|br|in|jp|cn|ru|nl|se|ch|au|eu")
_HOST = re.compile(r"(?i)(?<![\w./@-])[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*"
                   r"\.(?:%s)(?![\w-])" % _HOST_TLDS)
_HOME_USER = re.compile(r"(?:^|[^\w])~[A-Za-z_][\w.-]*")
_ROOT_PATH = re.compile(r"(?:^|[\s\"'`=(\[{<,:;])/[A-Za-z_][\w.-]{2,}(?![\w/])")


def _key_like(s: str) -> bool:
    """A 30+ character run of key characters with letters and digits that does not read as a path or a name:
    a piece of only lower-case letters (a folder, a word) makes it a path."""
    if not (re.search(r"\d", s) and re.search(r"[A-Za-z]", s)):
        return False
    pieces = [x for x in re.split(r"[/_-]", s) if x]
    return not any(re.fullmatch(r"[a-z]{3,}", x) for x in pieces)


_BIDI = set("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
# slash lookalikes NFKC does not fold (division slash, fraction slash, big solidus, set minus ...)
_SLASHES = str.maketrans({"\u2215": "/", "\u2044": "/", "\u29f8": "/", "\u27cb": "/", "\u2571": "/",
                          "\u2216": "\\", "\u29f9": "\\", "\u27cd": "\\", "\u2572": "\\"})


_EMOJI_MODS = set("\ufe0e\ufe0f") | {chr(c) for c in range(0x1F3FB, 0x1F400)}


def _pictograph(c: str) -> bool:
    return unicodedata.category(c) in ("So", "Sk") or 0x1F000 <= ord(c) <= 0x1FAFF


def _hidden_chars(s: str) -> bool:
    """A format (Cf) or bidi control character: invisible, and it splits a number or a key past every rule. A
    zero-width joiner between two pictographs (an emoji sequence such as a technologist or a flag) is fine."""
    if s.isascii():
        return False
    for i, c in enumerate(s):
        if c in _BIDI:
            return True
        if unicodedata.category(c) != "Cf":
            continue
        if c == "\u200d":
            a = i - 1
            while a >= 0 and s[a] in _EMOJI_MODS:
                a -= 1
            if a >= 0 and i + 1 < len(s) and _pictograph(s[a]) and _pictograph(s[i + 1]):
                continue
        return True
    return False


# invisible or blank characters that are not format characters: a combining grapheme joiner, Hangul fillers, the
# Braille blank, Khmer inherent vowels, Mongolian selectors, variation selectors
_IGNORABLE = set("\u034f\u115f\u1160\u3164\uffa0\u2800\u17b4\u17b5\u180b\u180c\u180d\u180e\u180f\u200d") | \
    {chr(c) for c in range(0xFE00, 0xFE10)} | {chr(c) for c in range(0xE0100, 0xE01F0)}


def _folded(s: str) -> str:
    """The copy every rule judges (the kept text is never rewritten): NFKC (full-width, circled and superscript
    digits, homoglyph punctuation), slash lookalikes as slashes, and without combining marks, unassigned,
    private-use and surrogate code points or other invisibles, so a number spread with them reads whole."""
    if (s or "").isascii():
        return s or ""                        # nothing to fold (the common case, and fast)
    t = unicodedata.normalize("NFKC", s).translate(_SLASHES)
    return "".join(c for c in t if c not in _IGNORABLE and unicodedata.category(c) not in ("Mn", "Me", "Cn", "Co", "Cs"))


def unsafe_reason(line: str) -> Optional[str]:
    """Why a line must not reach the film or a file ('hidden character', 'key', 'absolute path', 'URL', 'e-mail',
    'host'), or None. The line is judged NFKC-folded; one with a format or bidi control character is refused."""
    if _hidden_chars(line or ""):
        return "hidden character"
    s = _folded(line)
    if any(len(w) > MAX_TOKEN for w in s.split()):
        return "key"                          # a long unbroken run: never film text, and never matched further
    if _PREFIXED.search(s):
        return "key"
    if pv.mask_line(s)[1] or _HEX_RUN.search(s) or _KEY_VALUE.search(s) or _BEARER.search(s) or \
            any(_key_like(m.group(0)) for m in _KEY_RUN.finditer(s)):
        return "key"
    if _URL.search(s):
        return "URL"
    if _ABS_PATH.search(s) or _HOME_USER.search(s) or _ROOT_PATH.search(s):
        return "absolute path"
    if _EMAIL.search(s):
        return "e-mail"
    if _IP.search(s) or _HOST.search(s) or re.search(r"[\w.-]@[\w-]", s):
        return "host"
    return None


def hard_filter(lines: "OrderedDict[str, Dict[str, Any]]") -> Tuple["OrderedDict[str, Dict[str, Any]]", Counter]:
    kept: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    dropped: Counter = Counter()
    for k, ln in lines.items():
        why = unsafe_reason(ln["text"])
        if why:
            dropped[why] += 1
        else:
            kept[k] = ln
    return kept, dropped


# ---------------------------------------------------------------------------
# allow-list: the session -> facts (the only data recap keeps)
# ---------------------------------------------------------------------------


_WRAPPER_BLOCK = re.compile(r"\s*<[A-Za-z][\w]*[-_][\w-]*\b")
_OPEN_TAG = re.compile(r"<([A-Za-z][\w-]*)\b[^<>\n]{0,200}>")
_CLOSE_TAG = re.compile(r"</([A-Za-z][\w-]*)\s*>")


KNOWN_WRAPPERS = {"system-reminder", "user-prompt-submit-hook", "command-name", "command-message", "command-args",
                  "local-command-stdout", "local-command-stderr", "bash-input", "bash-stdout", "bash-stderr",
                  "task-notification"}


def _starts_line(text: str, at: int) -> bool:
    """Whether only whitespace sits between the line's start (or the text's) and `at`. It walks back over that
    whitespace only, so many tags cost linear time in all."""
    i = at - 1
    while i >= 0 and text[i] in " \t\r\u00a0\u2007\u202f\u3000":
        i -= 1
    return i < 0 or text[i] in "\n\u2028\u2029"


def _strip_tags(text: str) -> str:
    """Tagged blocks (system reminders, IDE selections, command wrappers) out, whole, however long, then stray tags.
    Linear: every closing tag is indexed once, and each opening tag looks up the next closing tag of its name. A
    block-style tag (a name with - or _) that is never closed ends the text there: what follows it is the block's
    body, not the request."""
    import bisect
    text = (text or "")[:REQUEST_SCAN]
    closes: Dict[str, List[Tuple[int, int]]] = {}
    for m in _CLOSE_TAG.finditer(text):
        closes.setdefault(m.group(1), []).append((m.start(), m.end()))
    starts = {k: [a for a, _b in v] for k, v in closes.items()}
    out: List[str] = []
    pos = 0
    for m in _OPEN_TAG.finditer(text):
        if m.start() < pos:
            continue
        name = m.group(1)
        lst = starts.get(name) or []
        i = bisect.bisect_left(lst, m.end())
        if i < len(lst):
            out.append(text[pos:m.start()])
            out.append(" ")
            pos = closes[name][i][1]
        elif name in KNOWN_WRAPPERS or name.startswith("ide_") or (("-" in name or "_" in name) and
                                                                   _starts_line(text, m.start())):
            out.append(text[pos:m.start()])       # a wrapper (a known one anywhere, else at a line start): its
            pos = len(text)                       # body runs to the end
            break
    out.append(text[pos:])
    return re.sub(r"</?[A-Za-z][^<>\n]{0,200}>", " ", "".join(out))


_FILE_EXTS = _W("py pyi js mjs cjs ts tsx jsx md mdx json yml yaml toml ini cfg sh bash zsh rs go rb java kt swift c h cc "
                "cpp hpp cs php css scss html htm txt csv lock xml sql ipynb vue svelte mp4 png jpg jpeg svg gif wav")
_KNOWN_DOTTED = _W("node.js next.js vue.js nuxt.js three.js d3.js chart.js express.js react.js asp.net vb.net .net "
                   "e.g. i.e. etc. vs.")
_KNOWN_SLASHED = _W("ci/cd and/or i/o a/b ui/ux tcp/ip w/o n/a input/output read/write client/server true/false "
                    "yes/no on/off pros/cons")
_VERSIONS = r"v?\d+(?:\.\d+)*[a-z]?(?:/v?\d+(?:\.\d+)*[a-z]?)*"
_GROUPED_KEY = re.compile(r"(?:[A-Za-z0-9]{4,}-){2,}[A-Za-z0-9]{4,}")
_VALUE_LIKE = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9+/=_.-]{8,}$")
_REQUEST_KEY_WORDS = _KEY_WORD[:-1] + r"|pass ?codes?|pass ?keys?|license ?keys?|pat|pats|api|apikey)"


def _private_word(w: str, nxt: str) -> bool:
    """Strict rules for one word of the request (a suggestion in script.md, never film text unless chosen)."""
    if len(w) > 200:
        return True                           # never matched further: long words are never request text
    bare = w.strip("\"'`,.;:!?()[]{}<>")
    low = bare.lower()
    if re.fullmatch(_REQUEST_KEY_WORDS, low) and nxt:
        return True                           # a key's name with anything after it (within the sentence)
    if len(w) >= 6 and re.search(r"[A-Za-z]", w) and re.search(r"\d", w) and \
            not re.fullmatch(_VERSIONS, low) and not ("." in low and low.rsplit(".", 1)[-1] in _FILE_EXTS):
        return True                           # letters mixed with digits, whatever punctuation is around them
    if re.search(r"\w:\S", w):
        return True                           # user:pass, scheme:value, key:value
    if re.search(r"(?i)%s\s*[:=]" % _REQUEST_KEY_WORDS, w):
        return True
    if _GROUPED_KEY.search(bare) or (_VALUE_LIKE.match(bare) and not re.fullmatch(_VERSIONS, low)
                                     and not (("." in low) and low.rsplit(".", 1)[-1] in _FILE_EXTS)):
        return True                           # a value-like word: digits mixed with letters
    if "/" in bare or "\\" in bare:
        if low not in _KNOWN_SLASHED and not re.fullmatch(_VERSIONS, low):
            return True
    if "@" in bare and not re.fullmatch(r"@[A-Za-z_]\w*", bare):
        return True
    if bare.startswith("~") and not re.match(r"~\d", bare):
        return True
    if "." in bare.strip(".") and low not in _KNOWN_DOTTED:
        last = low.rstrip(".").rsplit(".", 1)[-1]
        if re.fullmatch(r"[a-z]{2,}", last) and last not in _FILE_EXTS:
            return True                       # a host on any top-level domain (a file name keeps its extension)
    return bool(unsafe_reason(w) or unsafe_reason(" " + w))


# any separators, of any length (+ | – · _ -- ...), and a 1-digit lead group; a match starts only where a digit run
# starts, so long runs of digits or separators stay linear
_DIGIT_GROUPS = re.compile(r"(?<!\d)\d+(?:[\W_]+\d{2,}){2,}")


_NAME_KEYS = re.compile(r"(?:file|callout)\.\d+|files\.say")


def own_line(key: str, text: str, fresh: Dict[str, Any], facts: Dict[str, Any]) -> Optional[str]:
    """Whether a script.md line is recap's own, by comparison with what recap writes from the CURRENT facts (never
    erasing parts of the line and judging the rest, never trusting a file on disk):
    - "own": it is the line recap writes now; or, outside the lines that name a file, the same line with other
      counts (every standalone run of 1-5 digits, 12,345 included, read as #); or a file row or callout equal to
      one of the session's EDITED files exactly; or a files line whose file name is exactly one recap would speak
      for an edited file, with only the counts around that name compared by shape; or a "Most used" line made only
      of allow-listed labels with a count. A file's name is never shape-compared;
    - "stale": recap's line with a longer count in place of the current one: replaced by the current line,
      without a refusal;
    - None: the person's own line, judged by the strict rule on its original text."""
    cur = fresh[key]["text"] if key in fresh else None
    if cur is not None and cur == text:
        return "own"
    names = bool(_NAME_KEYS.fullmatch(key))
    if cur is not None and not names and _shape(cur) == _shape(text):
        return "own"
    edited = [f for f in facts.get("files") or [] if isinstance(f, dict) and f.get("edited")]
    one = lambda x: re.sub(r"\s+", " ", str(x or "")).strip()  # noqa: E731  (script.md lines are read this way)
    text1 = one(text)
    if re.fullmatch(r"file\.\d+", key) and text1 in {one(f.get("path")) for f in edited}:
        return "own"
    if re.fullmatch(r"callout\.\d+", key) and text1 in {one(str(f.get("path", "")).rsplit("/", 1)[-1]) for f in edited}:
        return "own"
    if key == "files.say":
        per = (facts.get("diff") or {}).get("per_file") or {}
        for f in edited:
            for p in (per, {}):                       # with git's line counts, and without (a commit since)
                say, name = files_say_parts(f, p, len(edited))
                say, name = one(say), one(name)
                if text1.count(name) == 1 and say.count(name) == 1:
                    a, b = text1.split(name), say.split(name)
                    if _shape(a[0]) == _shape(b[0]) and _shape(a[1]) == _shape(b[1]):
                        return "own"
    if key == "timeline.commands":
        body = re.sub(r"^Most used:\s*", "", text)
        parts = [x.strip() for x in body.split("\u00b7") if x.strip()]
        found = [re.fullmatch(r"(.+?) %s" % _COUNT, x) for x in parts]
        labels = [m.group(1) for m in found if m]
        if parts and len(parts) <= MOST_USED_PARTS and len(labels) == len(parts) and \
                len(set(labels)) == len(labels) and all(_allowed_label(x) for x in labels):
            return "own"
    if cur is not None and not names and _shape(cur, big=True) == _shape(text, big=True):
        return "stale"
    return None


_COUNT = r"\u00d7[1-9][0-9]{0,4}(?![0-9])"
MOST_USED_PARTS = 4
# a stale count: 1-5 digits in all, grouping included (12,345 yes; 123,456 no). Bounded, so linear on long runs
_SMALL_NUMBER = re.compile(r"(?<![0-9A-Za-z,])(?:[0-9]{1,2},[0-9]{3}|[0-9]{1,5})(?![0-9A-Za-z,])")
_ANY_NUMBER = re.compile(r"(?<![0-9A-Za-z])[0-9][0-9,]*(?![0-9A-Za-z])")


def _shape(text: str, big: bool = False) -> str:
    """The text with its standalone counts as # (1-5 digits in all, 12,345 included; any length when `big`) and
    plural words made singular, so a stale count compares equal and nothing else does. Never called on a file name
    (own_line compares those exactly). Linear: the patterns are bounded."""
    t = (_ANY_NUMBER if big else _SMALL_NUMBER).sub("#", text or "")
    return re.sub(r"\b(line|edit|file|commit|run|turn|call|command|test|path)s\b", r"\1", t)


def _allowed_label(label: str) -> bool:
    words = label.split()
    if not words or words[0] not in ALLOWED_PROGRAMS:
        return False
    if len(words) == 1:
        return True
    if len(words) == 2:
        prog, sub = words
        return sub in KNOWN_SUBCOMMANDS.get(prog, set()) or (prog in USER_TARGETS and sub in GENERIC_TARGETS) or \
            (prog == "showtime" and sub in _showtime_commands())
    return len(words) == 3 and words[0] in ("python", "python3") and words[1] == "-m" and words[2] in RUNNER_MODULES


MAX_LINE = 2000           # characters: a script.md line longer than this is refused outright


def free_text_refused(text: str) -> bool:
    """Whether a line the person wrote (any line of script.md that recap did not write, or an uncommented
    suggestion) fails the strict request rule or the hard filter."""
    if len(text or "") > MAX_LINE:
        return True                           # a line this long is never film text (and costs nothing to judge)
    if unsafe_reason(text):
        return True
    folded = _folded(text)
    if _digit_chain(folded):                  # the whole line: a number split across sentences is still one
        return True
    sents = pv._sentences(re.sub(r"\s+", " ", folded).strip()) or [text]
    return any(_clean_words(x) is None for x in sents)


_CHAIN_TOKENS = re.compile(r"v?\d+(?:\.\d+)+|\d+|[^\W\d_]+|\s+|[^\w\s]")
CHAIN_DIGITS = 9          # an SSN has 9 digits, a phone 10, a card 16


def _digit_chain(text: str) -> bool:
    """Digit groups that together make a long number (S1, S2), in one linear pass:
    - a chain of groups with only punctuation or 1-4 letter words between them that holds 9+ digits in all
      ("SSN 123 and 45 and 6789", "4111 x 1111 x 1111 x 1111", "4 1 1 1 ... 1");
    - two groups with only whitespace between when one has 4+ digits ("4111 1111", "55512 34567").
    A word of 5+ letters or a version (3.11, v1.2.3) ends a chain. Trade-off: "between 2024 and 2026", "From
    2024-2026", "1920×1080", "Node 18, 20 and 22" and "Python 3.11, 3.12 and 3.13" pass."""
    total = 0                 # digits in the current chain
    last = 0                  # length of the chain's last group (0: no chain)
    gap = ""                  # what sits since the last group: "" nothing, "space" only whitespace, "other"
    for m in _CHAIN_TOKENS.finditer(text):
        t = m.group(0)
        if t.isdigit():
            if last and gap == "space" and (last >= 4 or len(t) >= 4):
                return True
            total = (total if last else 0) + len(t)
            if total >= CHAIN_DIGITS:
                return True
            last, gap = len(t), ""
        elif t.isspace():
            if gap == "":
                gap = "space"
        elif t[0].isdigit() or t[0] in "vV" and len(t) > 1 and t[1].isdigit() or (t.isalpha() and len(t) > 4):
            total, last, gap = 0, 0, ""   # a version or a long word ends the chain
        else:
            gap = "other"                 # punctuation or a 1-4 letter word bridges it
    return False


def _clean_words(sent: str) -> Optional[str]:
    """The sentence as it is, or None when any word in it is private (_private_word): a key word with any of the
    next three words after it, three or more digit groups (a card or account number, an address)."""
    judged = _folded(sent)
    if _hidden_chars(sent) or _DIGIT_GROUPS.search(judged) or re.search(r"\d{6,}", judged) or \
            _digit_chain(judged):
        return None                           # digit groups or a long number (an account, a ticket, a card)
    jtoks = judged.split()
    for i, w in enumerate(jtoks):
        if _private_word(w, " ".join(jtoks[i + 1:i + 4])):
            return None
    toks = sent.split()
    out = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(toks)).strip(" ,;:-")
    return out or None


def clean_request(text: str, limit: int = 150) -> str:
    """The request's first sentences, with tagged blocks (reminders, commands), code and asides in brackets
    taken out, and every sentence that names a path, a host, an address, a URL or a key left out whole."""
    t = _strip_tags(text)[:REQUEST_KEEP]
    t = re.sub(r"```.*?(```|$)", " ", t, flags=re.S)
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    para = ""
    for p in paras:
        p = re.sub(r"^\s*(#+|[-*>]|\d+[.)])\s+", "", p, flags=re.M)
        if len(re.findall(r"[A-Za-z]{2,}", p)) >= 3:
            para = p
            break
    for _ in range(3):
        para = re.sub(r"\s*\([^()]*\)", "", para)
        para = re.sub(r"\s*\[[^\[\]]*\]", "", para)
    sents: List[str] = []
    for sent in pv._sentences(re.sub(r"\s+", " ", para).strip()):
        clean = _clean_words(sent)
        if clean is None or _digit_chain(_folded(" ".join(sents + [clean]))):
            break                             # something private (also a number split across sentences) ends
        sents.append(clean)                   # the suggestion; a later sentence is never promoted in its place
    out = ""
    for s in sents:
        if out and len(out) + 1 + len(s) > limit:
            break
        out = (out + " " + s).strip()
    out = rv.shorten(out, limit) if len(out) > limit else out
    return out if not unsafe_reason(out) else ""


BUILTIN_TOOLS = _W("Read Write Edit MultiEdit NotebookEdit NotebookRead Bash BashOutput KillShell KillBash PowerShell "
                   "Glob Grep LS WebFetch WebSearch Task Agent TodoWrite TodoRead ExitPlanMode EnterPlanMode ToolSearch "
                   "Monitor Skill SlashCommand AskUserQuestion TaskStop TaskOutput SendMessage EnterWorktree "
                   "ExitWorktree ListMcpResources ReadMcpResource advisor")


def tool_display(name: str) -> str:
    """A tool's name: Claude Code's own tools by name, any MCP tool as 'MCP tool', anything else 'other' (a tool's
    or an MCP server's name can be private too)."""
    if name.startswith("mcp__"):
        return "MCP tool"
    return name if name in BUILTIN_TOOLS else OTHER


READ_TOOLS = {"Read", "NotebookRead", "View"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Create", "Update"}
SEARCH_TOOLS = {"Grep", "Glob", "LS", "Search", "WebSearch", "WebFetch", "ToolSearch"}
RUN_TOOLS = {"Bash", "PowerShell", "Shell", "BashOutput", "Monitor"}


def _numstat(out: str, acc: Dict[str, List[int]]) -> None:
    for line in out.splitlines():
        m = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", line)
        if not m:
            continue
        path = m.group(3)
        if " => " in path:
            path = re.sub(r"\{[^{}]* => ([^{}]*)\}", r"\1", path)
            path = path.split(" => ")[-1]
        path = path.replace("//", "/")
        a = acc.setdefault(path, [0, 0])
        a[0] += int(m.group(1)) if m.group(1).isdigit() else 0
        a[1] += int(m.group(2)) if m.group(2).isdigit() else 0


def verified_commits(top: str, shas: Sequence[str]) -> List[str]:
    """The commit hashes (as printed by `git commit`) that exist in THIS repository and are part of its history
    (an ancestor of HEAD, or on any branch or tag). A hash that does not resolve here is not counted: a commit
    made in another repository, however the command reached it, never counts as the session's."""
    out = []
    for sha in dict.fromkeys(shas):
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha or ""):
            continue
        if _git(["cat-file", "-e", sha + "^{commit}"], cwd=top)[0] != 0:
            continue
        rc, full = _git(["rev-parse", "--verify", "--quiet", sha + "^{commit}"], cwd=top)
        full = full.strip()
        if rc != 0 or not full:
            continue
        if _git(["merge-base", "--is-ancestor", full, "HEAD"], cwd=top)[0] == 0 or \
                _git(["branch", "--all", "--contains", full], cwd=top)[1].strip() or \
                _git(["tag", "--contains", full], cwd=top)[1].strip():
            if full not in out:
                out.append(full)
    return out


def diff_stats(top: str, *, since: Optional[str], commits: Sequence[str], edited: Sequence[str]) -> Dict[str, Any]:
    """{files, additions, deletions, source, per_file}: from --since (git diff <ref>, the working tree
    included), else the session's own verified commits (verified_commits). None when git has no record."""
    acc: Dict[str, List[int]] = {}
    source = "none"
    if since:
        rc, _out = _git(["rev-parse", "--verify", "--quiet", "--end-of-options", since + "^{commit}"], cwd=top)
        if rc != 0 or since.startswith("-"):
            raise ShowtimeError("--since %s is not a commit of the repository" % since,
                                hint="--since takes a commit, branch or tag of that repository")
        rc, out = _git(["diff", "--numstat", "--no-renames", since, "--"], cwd=top)
        if rc != 0:
            raise ShowtimeError("git diff %s failed in the repository" % since,
                                hint="--since takes a commit, branch or tag of that repository")
        _numstat(out, acc)
        source = "since"
    else:
        for sha in commits:
            rc, out = _git(["show", "--numstat", "--no-renames", "--format=", sha], cwd=top)
            if rc == 0:
                _numstat(out, acc)
        source = "commits" if commits else source
    per = {p: v for p, v in acc.items() if _repo_file_ok(p)}
    return {"files": len(per), "additions": sum(v[0] for v in per.values()),
            "deletions": sum(v[1] for v in per.values()), "source": source if per else "none",
            "per_file": {p: v for p, v in per.items() if p in set(edited)}}


def collect(ses: Dict[str, Any], top: str, roots: Sequence[str], *, since: Optional[str] = None,
            use_git: bool = True) -> Dict[str, Any]:
    """The allow-listed facts of a session. This dict is all recap keeps; it is written as facts.json."""
    t0 = ses["start"] or 0.0
    t1 = ses["end"] or t0
    files: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    outside = set()
    tools: Counter = Counter()
    commands: Counter = Counter()
    timeline: List[Dict[str, Any]] = []
    tests: List[Dict[str, Any]] = []
    shas: List[str] = []
    n_cmds = 0
    main_cwd = _norm(ses["cwds"].most_common(1)[0][0]) if ses["cwds"] else ""
    for u in ses["uses"]:
        name, inp = u["name"], u["input"]
        res = ses["results"].get(u["id"]) or {}
        t = round(max(0.0, (u["ts"] or t0) - t0), 1)
        tools[tool_display(name)] += 1
        kind = "other"
        if name in READ_TOOLS or name in EDIT_TOOLS:
            kind = "read" if name in READ_TOOLS else "edit"
            rel = rel_path(inp.get("file_path") or inp.get("notebook_path") or inp.get("path"), roots,
                           u.get("cwd") or main_cwd)
            if kind == "edit" and res.get("error"):
                kind = "other"                    # an edit that did not apply
            if rel is None:
                p = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
                if isinstance(p, str) and p:
                    outside.add(hashlib.sha256(p.encode("utf-8", "replace")).hexdigest())   # counted, never shown
            elif kind in ("read", "edit"):
                f = files.setdefault(rel, {"path": rel, "read": 0, "edited": 0, "first": t, "first_edit": None})
                f[kind if kind == "read" else "edited"] += 1
                if kind == "edit" and f["first_edit"] is None:
                    f["first_edit"] = t
        elif name in SEARCH_TOOLS:
            kind = "read"
        elif name in RUN_TOOLS and name != "Monitor":
            cmd = inp.get("command") if isinstance(inp.get("command"), str) else ""
            labels = command_labels(cmd)
            n_cmds += 1
            for lab in labels:
                commands[lab] += 1
            kind = "run"
            if cmd and is_test_command(cmd):
                kind = "test"
                c = test_counts(res.get("text") or "")
                ok = None
                if c is not None and c.get("status"):
                    ok = c.pop("status") == "ok" and not res.get("error")
                elif c is not None:
                    ok = c["failed"] == 0 and not res.get("error")
                elif res:
                    ok = False if res.get("error") else None
                tests.append(dict(c or {"passed": None, "failed": None, "unit": ""}, t=t, ok=ok))
            if "git commit" in labels and res:          # a failing later step (a rejected push) does not undo it
                shas += _COMMIT_SHA.findall(res.get("text") or "")      # verified against the repository below
        timeline.append({"t": t, "k": kind})
    edited = [f["path"] for f in files.values() if f["edited"]]
    mine = verified_commits(top, shas) if use_git else []
    commits = len(mine)                       # only hashes git knows in this repository's history
    if use_git:
        diff = diff_stats(top, since=since, commits=mine, edited=edited)
    else:
        diff = {"files": 0, "additions": 0, "deletions": 0, "source": "none", "per_file": {}}
    start_local = _dt.datetime.fromtimestamp(t0) if t0 else None
    ref = hashlib.sha1(("%s|%s" % (Path(ses["path"]).name, t0)).encode()).hexdigest()[:10]
    facts = {
        "generator": "showtime recap", "version": 1, "ref": ref, "kind": ses["kind"],
        "date": start_local.strftime("%Y-%m-%d") if start_local else "",
        "started": _dt.datetime.fromtimestamp(t0, _dt.timezone.utc).isoformat() if t0 else "",
        "ended": _dt.datetime.fromtimestamp(t1, _dt.timezone.utc).isoformat() if t1 else "",
        "duration": active_seconds(ses.get("times") or []), "span": round(max(0.0, t1 - t0), 1),
        "turns": len(ses["turns"]), "tool_calls": len(ses["uses"]),
        "tools": [[k, v] for k, v in tools.most_common()],
        "files": list(files.values()), "files_outside": len(outside),
        "commands": [[k, v] for k, v in commands.most_common(12)], "commands_total": n_cmds,
        "tests": tests, "commits": commits, "diff": diff, "timeline": timeline,
    }
    return scrub_facts(facts)


IDLE_GAP = 600.0       # a pause longer than this (a session left open overnight) is not counted as work


def active_seconds(times: Sequence[float]) -> float:
    """The session's active time: the gaps between consecutive events, leaving out any gap of IDLE_GAP or more."""
    ts = sorted(times)
    return round(sum(b - a for a, b in zip(ts, ts[1:]) if b - a < IDLE_GAP), 1)


def scrub_facts(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The hard filter on the facts themselves (they are written to facts.json)."""
    facts["files"] = [f for f in facts["files"] if not unsafe_reason(f["path"])]
    facts["commands"] = [c for c in facts["commands"] if not unsafe_reason(c[0])]
    facts["tools"] = [c for c in facts["tools"] if not unsafe_reason(c[0])]
    d = facts.get("diff") or {}
    d["per_file"] = {p: v for p, v in (d.get("per_file") or {}).items() if not unsafe_reason(p)}
    return facts


# ---------------------------------------------------------------------------
# the script: every line shown (show) or spoken (say), keyed
# ---------------------------------------------------------------------------


def fmt_duration(s: float) -> str:
    s = max(0.0, float(s or 0))
    if s < 90:
        return "%d s" % round(s)
    m = int(round(s / 60.0))
    if m < 90:
        return "%d min" % m
    h, m = divmod(m, 60)
    return "%d h %02d min" % (h, m) if m else "%d h" % h


def say_duration(s: float) -> str:
    s = max(0.0, float(s or 0))
    if s < 90:
        return "%d seconds" % round(s)
    m = int(round(s / 60.0))
    if m < 90:
        return "%d minutes" % m
    h, m = divmod(m, 60)
    return ("%d hours" % h if h > 1 else "an hour") + (" and %d minutes" % m if m else "")


def _plural(n: int, word: str, many: str = "") -> str:
    return "%s %s" % ("{:,}".format(n), word if n == 1 else (many or word + "s"))


def _human_date(iso_day: str) -> str:
    try:
        d = _dt.date.fromisoformat(iso_day)
    except ValueError:
        return ""
    return "%d %s %d" % (d.day, d.strftime("%b"), d.year)


def _speakable(text: str) -> str:
    """A title for the voice: code spans lose their backticks, snake_case reads as words."""
    t = re.sub(r"`([^`]*)`", r"\1", text or "")
    t = re.sub(r"^\s*v?\d+(?:\.\d+)+\s*:\s*", "", t)            # a leading "0.4.0:" release tag
    t = t[:1].upper() + t[1:]
    t = re.sub(r"(?<=[A-Za-z])_(?=[A-Za-z])", " ", t)
    return t.strip().rstrip(".")


def scenes_for(facts: Dict[str, Any]) -> List[str]:
    sc = ["hook", "numbers", "timeline"]
    if any(f["edited"] for f in facts["files"]):
        sc.append("files")
    if facts["tests"]:
        sc.append("tests")
    if facts["diff"]["files"] or facts["commits"]:
        sc.append("diff")
    return sc + ["end"]


MAX_FILE_ROWS = 5
MAX_CALLOUTS = 4


def test_story(tests: List[Dict[str, Any]]) -> Dict[str, Any]:
    known = [x for x in tests if x["ok"] is not None]
    last = next((x for x in reversed(tests) if x.get("unit")), None)
    first_red = next((i for i, x in enumerate(known) if x["ok"] is False), None)
    green_after = first_red is not None and any(x["ok"] for x in known[first_red + 1:])
    return {"runs": len(tests), "red": sum(1 for x in known if x["ok"] is False),
            "green": sum(1 for x in known if x["ok"]), "last": last,
            "red_to_green": bool(green_after and known and known[-1]["ok"]),
            "ends_red": bool(known and known[-1]["ok"] is False)}


def files_say_parts(big: Optional[Dict[str, Any]], per: Dict[str, Any], n_edited: int) -> Tuple[str, str]:
    """(the files scene's line about the file with the most change, the file name as it sits in that line). recap
    knows where the name sits, so a comparison can match the name exactly and read counts only around it."""
    base = re.sub(r"\.[A-Za-z0-9]+$", "", big["path"].rsplit("/", 1)[-1]) if big else ""
    name = _speakable(base)
    name = (base[:1] + name[1:]) if base[:1].islower() else name      # a file name keeps its own case
    kind = ", a test file" if big and pv.is_test(big["path"]) else ""
    if big and big["path"] in per and n_edited > 1:
        return "Most of the change is in %s%s: %s added." % (name, kind, _plural(per[big["path"]][0], "line")), name
    if big and n_edited > 1:
        fname = big["path"].rsplit("/", 1)[-1]          # spoken: the stem's words, then its extension
        stem, dot, ext = fname.rpartition(".")
        spoken = (_speakable(stem) if stem else fname) + ("." + ext if stem and dot else "")
        spoken = (stem[:1] + spoken[1:]) if stem[:1].islower() else spoken
        return "Most edits went into %s%s: %d of them." % (spoken, kind, big["edited"]), spoken
    return "Every edit went into %s%s." % (name or "one file", kind), name or "one file"


def files_say(big: Optional[Dict[str, Any]], per: Dict[str, Any], n_edited: int) -> str:
    """The files scene's line about the file with the most change (one of the edited files)."""
    return files_say_parts(big, per, n_edited)[0]


def _outcome(facts: Dict[str, Any]) -> str:
    st = test_story(facts["tests"]) if facts["tests"] else None
    if st and st["red_to_green"]:
        return "red to green"
    if st and st["ends_red"]:
        return "still red"
    if st and st["last"]:
        return "tests green"
    if facts["commits"]:
        return _plural(facts["commits"], "commit")
    return ""


def facts_title(facts: Dict[str, Any]) -> str:
    """The film's title from the facts alone: '42 min · 6 files · red to green'."""
    edited = sum(1 for f in facts["files"] if f["edited"])
    files = _plural(edited, "file") + " edited" if edited else _plural(len(facts["files"]), "file") + " read"
    return " · ".join(x for x in (fmt_duration(facts["duration"]), files, _outcome(facts)) if x)


def hook_sentence(facts: Dict[str, Any]) -> str:
    """The hook's narration from the facts alone."""
    who = "a sub-agent" if facts["kind"] == "sub-agent" else "an agent"
    edited = sum(1 for f in facts["files"] if f["edited"])
    did = "edited %s" % _plural(edited, "file") if edited else "read %s" % _plural(len(facts["files"]), "file")
    out = _outcome(facts)
    tail = {"red to green": " and took the tests from red to green", "still red": ", and the tests were still red",
            "tests green": " and kept the tests green"}.get(out, "")
    return "In %s, %s %s%s." % (say_duration(facts["duration"]), who, did, tail)


def script_lines(facts: Dict[str, Any]) -> "OrderedDict[str, Dict[str, Any]]":
    """Every line of the film, keyed: {key: {scene, kind: show|say, text}}. The page and the narration are built
    from these lines only (read back from script.md after the user's edits)."""
    L: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def add(scene: str, kind: str, key: str, text: str) -> None:
        text = re.sub(r"\s+", " ", text or "").strip()
        if text:
            L[key] = {"scene": scene, "kind": kind, "text": text}

    title = facts_title(facts)
    dur = facts["duration"]
    files = facts["files"]
    edited = [f for f in files if f["edited"]]
    read_only = [f for f in files if f["read"] and not f["edited"]]
    n_tests = len(facts["tests"])
    who = "sub-agent" if facts["kind"] == "sub-agent" else "agent"
    scenes = scenes_for(facts)

    # hook
    day = _human_date(facts["date"])
    add("hook", "show", "hook.kicker", "Recap · Claude Code %s%s" % ("sub-agent" if who == "sub-agent" else "session",
                                                                        " · " + day if day else ""))
    add("hook", "show", "hook.title", title)       # from the facts only; the request is a commented suggestion
    add("hook", "show", "hook.meta", " · ".join([_plural(facts["turns"], "turn"), _plural(facts["tool_calls"], "tool call"),
                                                      _plural(facts["commands_total"], "command")]))
    add("hook", "say", "hook.say", hook_sentence(facts))

    # numbers
    stats = [("time", fmt_duration(dur), "of work"), ("turns", "{:,}".format(facts["turns"]), "turns"),
             ("calls", "{:,}".format(facts["tool_calls"]), "tool calls"),
             ("files", "{:,}".format(len(files)), "repo files touched")]
    if n_tests:
        stats.append(("tests", "{:,}".format(n_tests), "test runs"))
    add("numbers", "show", "numbers.kicker", "The session in numbers")
    for k, v, lab in stats:
        add("numbers", "show", "stat.%s.value" % k, v)
        add("numbers", "show", "stat.%s.label" % k, lab)
    add("numbers", "say", "numbers.say", "%s and %s, across %s in the repository." % (
        _plural(facts["turns"], "turn"), _plural(facts["tool_calls"], "tool call"), _plural(len(files), "file")))

    # timeline
    kinds = Counter(e["k"] for e in facts["timeline"])
    add("timeline", "show", "timeline.kicker", "Minute by minute")
    for k, lab in (("read", "Read"), ("edit", "Edit"), ("run", "Run"), ("test", "Test")):
        if kinds.get(k) or k in ("read", "edit", "run"):
            add("timeline", "show", "lane.%s" % k, "%s %d" % (lab, kinds.get(k, 0)))
    add("timeline", "show", "axis.start", "0")
    add("timeline", "show", "axis.end", fmt_duration(facts.get("span") or dur))
    for i, f in enumerate(sorted(edited, key=lambda f: f["first_edit"] or 0)[:MAX_CALLOUTS]):
        add("timeline", "show", "callout.%d" % (i + 1), f["path"].rsplit("/", 1)[-1])
    top = [c for c in facts["commands"] if c[0] not in ("echo", "sleep", "printf", OTHER)][:4]
    if top:
        # a command line can run several programs, so these are the programs most used, not a share of the runs
        add("timeline", "show", "timeline.commands", "Most used:  " + "  ·  ".join("%s ×%d" % (c, n) for c, n in top))
    runs = kinds.get("run", 0)                # the lanes' own counts, so the voice and the screen agree
    parts = []
    if read_only:
        parts.append("read %s" % (_plural(len(read_only), "other file") if edited else _plural(len(read_only), "file")))
    if edited:
        parts.append("edited %s" % _plural(len(edited), "file"))
    parts.append("ran %s" % _plural(runs, "command") + (" and %s" % _plural(n_tests, "test run") if n_tests else ""))
    if len(parts) > 1 and " and " not in parts[-1]:
        say = "It " + ", ".join(parts[:-1]) + " and " + parts[-1] + "."
    else:
        say = "It " + ", ".join(parts) + "."
    add("timeline", "say", "timeline.say", say)

    # files
    if "files" in scenes:
        per = facts["diff"].get("per_file") or {}
        add("files", "show", "files.kicker", "Where the edits landed")
        add("files", "show", "files.head", _plural(len(edited), "file") + " edited")
        rows = sorted(edited, key=lambda f: (-(sum(per.get(f["path"], [0, 0])) or f["edited"]), f["path"]))
        for i, f in enumerate(rows[:MAX_FILE_ROWS]):
            add("files", "show", "file.%d" % (i + 1), f["path"])
            if f["path"] in per:
                a, d = per[f["path"]]
                add("files", "show", "file.%d.stat" % (i + 1), "+%d −%d" % (a, d))
            else:
                add("files", "show", "file.%d.stat" % (i + 1), "edited %d×" % f["edited"])
        if len(rows) > MAX_FILE_ROWS:
            add("files", "show", "files.more", "+ %d more" % (len(rows) - MAX_FILE_ROWS))
        # new information, not the count again: where most of the change is
        say = files_say(rows[0] if rows else None, per, len(edited))
        add("files", "say", "files.say", say)

    # tests
    if "tests" in scenes:
        st = test_story(facts["tests"])
        last = st["last"]
        add("tests", "show", "tests.kicker", "%s, in order" % _plural(st["runs"], "test run"))
        add("tests", "show", "tests.head", "Red to green" if st["red_to_green"] else
            ("Still red" if st["ends_red"] else "Tests"))
        if last:
            total = (last["passed"] or 0) + (last["failed"] or 0)
            add("tests", "show", "tests.value", "%d/%d" % (last["passed"] or 0, total))
            add("tests", "show", "tests.label", "%s passed, last run with a count" % last["unit"])
        if st["red"]:
            add("tests", "show", "tests.note", "%s failed before the last one" % _plural(st["red"], "run")
                if not st["ends_red"] else "%s failed" % _plural(st["red"], "run"))
        known = [x["ok"] for x in facts["tests"]]
        legend = ["red failed"] * (False in known) + ["green passed"] * (True in known) + \
            ["grey not counted"] * (None in known)
        if len(legend) > 1:
            add("tests", "show", "tests.legend", " · ".join(legend))
        if st["red_to_green"] and last:
            say = "The tests went red %s, then green: %d of %d %s passed." % (
                "once" if st["red"] == 1 else "%d times" % st["red"], last["passed"] or 0, total, last["unit"])
        elif st["ends_red"] and last:
            say = "The last test run still failed: %d of %d %s." % (last["failed"] or 0, total, last["unit"])
        elif last:
            say = "Every counted test run passed: %d of %d %s on the last one." % (last["passed"] or 0, total,
                                                                                 last["unit"])
        else:
            say = "It ran the tests %s." % ("once" if st["runs"] == 1 else "%d times" % st["runs"])
        add("tests", "say", "tests.say", say)

    # diff
    if "diff" in scenes:
        d = facts["diff"]
        add("diff", "show", "diff.kicker", "The change, from git")
        if d["files"]:
            add("diff", "show", "diff.adds", "+{:,}".format(d["additions"]))
            add("diff", "show", "diff.dels", "−{:,}".format(d["deletions"]))
            if facts["commits"] and d["files"] != len(edited):
                detail = "%s in %s · %d edited in this session" % (_plural(d["files"], "file"),
                                                                 _plural(facts["commits"], "commit"), len(edited))
            else:
                detail = " · ".join(x for x in (_plural(d["files"], "file"), _plural(facts["commits"], "commit")
                                                if facts["commits"] else "") if x)
            add("diff", "show", "diff.detail", detail)
            say = ("%s: " % (_plural(facts["commits"], "commit").replace("1 commit", "One commit")
                             if facts["commits"] else "In all")) + \
                "%s lines added, %s removed." % ("{:,}".format(d["additions"]), "{:,}".format(d["deletions"]))
            add("diff", "say", "diff.say", say[0].upper() + say[1:])
        else:
            add("diff", "show", "diff.detail", _plural(facts["commits"], "commit"))
            add("diff", "say", "diff.say", "It made %s." % _plural(facts["commits"], "commit"))

    # end
    add("end", "show", "end.kicker", "showtime recap")
    # the outcome, from the facts only (the cause of a fix is in the assistant's text, which recap never reads)
    st = test_story(facts["tests"]) if facts["tests"] else None
    last = st["last"] if st else None
    commits = (" · " + _plural(facts["commits"], "commit")) if facts["commits"] else ""
    if st and last and not st["ends_red"] and (st["red_to_green"] or st["red"] == 0):
        total = (last["passed"] or 0) + (last["failed"] or 0)
        add("end", "show", "end.outcome", "Ended green: %d/%d %s passed%s" % (last["passed"] or 0, total, last["unit"],
                                                                           commits))
        add("end", "say", "end.say", "It ended green%s." % (", in %s" % _plural(facts["commits"], "commit")
                                                            if facts["commits"] else ""))
    elif st and last and st["ends_red"]:
        add("end", "show", "end.outcome", "Ended red: %d of %d %s failed%s" % (
            last["failed"] or 0, (last["passed"] or 0) + (last["failed"] or 0), last["unit"], commits))
    add("end", "show", "end.note", "Made on this machine from the session log · nothing uploaded")
    return L


SCRIPT_HEAD = """# Recap script

<!-- recap of session {ref} -->
Every line below is shown on screen (show) or spoken (say); the film is built from these lines only, and
lines starting with # are not used. The lines come from an allow-list of facts (counts, file paths inside the
repository, program names, test counts, git stats); free text from the session is only offered as a # suggestion.
Edit the text after a label, or delete a line to leave it out, then run the same command again with --yes.
Lines that look like keys, tokens, absolute paths, URLs, hosts or e-mail addresses are dropped, also after your
edits. Filters can miss things: read every line before you render.
"""


def write_script(lines: "OrderedDict[str, Dict[str, Any]]", ref: str,
                 suggestions: Sequence[Tuple[str, str]] = ()) -> str:
    """script.md: the keyed lines by scene; after the hook's title, free-text suggestions as comments (used only
    when the person uncomments one, and then through the hard filter like every line)."""
    out = [SCRIPT_HEAD.format(ref=ref)]
    scene = None
    for key, ln in lines.items():
        if ln["scene"] != scene:
            scene = ln["scene"]
            out.append("\n## %s\n" % scene)
        out.append("%s %s: %s" % (ln["kind"], key, ln["text"]))
        if key == "hook.title":
            for what, text in suggestions:
                if text and not unsafe_reason(text):
                    as_title = what.endswith("description")
                    out.append("# from %s; uncomment to %s:" % (what, "use it as the title (it replaces the line above)"
                                                                if as_title else "show it under the title"))
                    out.append("# show %s: %s" % ("hook.title" if as_title else "hook.request", text))
    return "\n".join(out) + "\n"


def suggestions_for(ses: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Free text offered in script.md as commented suggestions (strictly cleaned); never kept in facts.json or the
    project: script.md is the only file they appear in."""
    out = []
    title = clean_request(ses.get("description") or "", limit=70)
    if title:
        out.append(("the sub-agent's description", title))
    request = clean_request(ses.get("request") or "")
    if request:
        out.append(("your first message", request))
    return out


_LINE = re.compile(r"^(show|say)\s+([a-z][\w.-]*)\s*:\s?(.*)$")


def read_script(text: str) -> Tuple[str, "OrderedDict[str, Dict[str, Any]]"]:
    """(ref, lines) from a script.md, edits included; unknown lines are ignored."""
    m = re.search(r"<!-- recap of session ([0-9a-f]{6,40}) -->", text or "")
    lines: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    scene = ""
    for raw in (text or "").splitlines():
        h = re.match(r"^##\s+([a-z]+)\s*$", raw.strip())
        if h:
            scene = h.group(1)
            continue
        mm = _LINE.match(raw.strip())
        if mm and scene:
            t = re.sub(r"\s+", " ", mm.group(3)).strip()
            if t:
                lines[mm.group(2)] = {"scene": scene, "kind": mm.group(1), "text": t}
    return (m.group(1) if m else ""), lines


# ---------------------------------------------------------------------------
# timing and the page
# ---------------------------------------------------------------------------

PAD = 0.3          # picture before a scene's first spoken word (retime --from-voice uses the same)
END_HOLD = 3.4


def visual_need(scene: str, facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]") -> float:
    """Seconds a scene needs on screen for its pictures and text, without a voice."""
    if scene == "hook":                       # the title is spoken; the request line is read
        req = lines["hook.request"]["text"] if "hook.request" in lines else ""
        return max(3.6, 0.8 + (pv.read_time(req) if req else 1.5))
    if scene == "numbers":
        return max(4.2, 0.4 + 0.18 * 5 + 2.6)
    if scene == "timeline":
        return 7.5
    if scene == "files":
        n = sum(1 for k in lines if k.startswith("file.") and not k.endswith(".stat"))
        return max(4.0, 0.5 + 0.15 * n + 0.4 * n + 1.5)
    if scene == "tests":
        return max(4.5, 0.5 + min(40, len(facts["tests"])) * 0.06 + 3.0)
    if scene == "diff":
        return 3.8
    return END_HOLD


def durations(facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]", scenes: Sequence[str],
              slots: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Each scene's length: with a voice, PAD + its line's slot (the slot holds the pause after it); a scene
    without a line (the end card) holds END_HOLD. Without a voice, what its pictures and text need."""
    out = {}
    for s in scenes:
        if slots and s in slots:
            out[s] = round(PAD + slots[s], 2)
        elif slots:
            out[s] = END_HOLD if s == "end" else round(visual_need(s, facts, lines), 2)
        else:
            say = next((ln["text"] for ln in lines.values() if ln["scene"] == s and ln["kind"] == "say"), "")
            out[s] = round(max(visual_need(s, facts, lines), (len(say.split()) / 2.6 + 0.8) if say else 0), 2)
    return out


def extra_pauses(facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]", scenes: Sequence[str],
                 speech: Dict[str, float]) -> Dict[str, float]:
    """Seconds of silence to add after a scene's line so its pictures have time (the narration sets the
    lengths, so a scene that needs longer than its line gets a pause)."""
    out = {}
    for s in scenes:
        if s in speech:
            need = visual_need(s, facts, lines) - (PAD + speech[s])
            if need > 0.05:
                out[s] = round(need, 2)
    return out


def narration_md(lines: "OrderedDict[str, Dict[str, Any]]", scenes: Sequence[str], *, voice: str = "af_heart",
                 pauses: Optional[Dict[str, float]] = None, speed: float = 1.0) -> str:
    out = ["---", "voice: %s" % voice, "gap: 0.45", "---", "",
           "<!-- written by showtime recap from script.md: one line per scene -->", ""]
    for s in scenes:
        say = next((ln["text"] for ln in lines.values() if ln["scene"] == s and ln["kind"] == "say"), "")
        if not say:
            continue
        opts = []
        if pauses and pauses.get(s):
            opts.append("pause_after=%.2f" % (0.45 + pauses[s]))
        if speed != 1.0:
            opts.append("speed=%.2f" % speed)
        out.append("## %s%s" % (s, " {%s}" % " ".join(opts) if opts else ""))
        out.append(say.replace("`", ""))
        out.append("")
    return "\n".join(out)


GROUND, INK, INK2, HAIR, ACCENT, ACCENT_TEXT, GREEN = ("#F4F3EF", "#1E2024", "#4A4C50", "#B9B6AE", "#B8431D",
                                                      "#A23A17", "#2A6E45")

CSS = r"""
  :root {
    --bg: #F4F3EF; --fg: #1E2024; --muted: #4A4C50; --hair: #B9B6AE; --accent: #B8431D; --accent-text: #A23A17;
    --good: #2A6E45; --surface: #FBFAF7; --line: rgb(30 32 36 / 0.14);
    --font-display: 'Instrument Serif', Georgia, serif; --font-sans: 'Geist', 'Inter', sans-serif;
    --font-mono: 'Geist Mono', 'JetBrains Mono', monospace; --font-body: var(--font-sans);
    --cap-font: 'Geist', sans-serif; --cap-weight: 600; --cap-case: none; --cap-ink: #1E2024; --cap-outline: #F4F3EF;
    --cap-accent: #A23A17; --cap-active-ink: #F4F3EF; --cap-plate: rgb(244 243 239 / 0.94);
    --scene-bg: transparent; color-scheme: light;
  }
  html, body { background: var(--bg); }
  .stage { background: var(--bg); }
  .scene { --x: 6.2cqw; --mid: 47cqh; --k: 2.6cqh; --title: 12.4cqh; --dek: 3.9cqh; --meta: 3cqh; --stat: 14.5cqh;
           --lab: 2.7cqh; --lane: 3cqh; --tag: 2.7cqh; --row: 3.7cqh; --head: 9.4cqh; --big: 24cqh; padding: 0; }
  .paper { position: absolute; inset: 0; pointer-events: none; }
  .paper .frame { position: absolute; inset: 4cqh; border: max(1px, 0.14cqh) solid var(--hair); border-radius: 0.4cqh; }
  .paper .grid { position: absolute; inset: 4cqh; opacity: 0.55;
    background-image: linear-gradient(to right, rgb(185 182 174 / 0.2) 1px, transparent 1px),
                      linear-gradient(to bottom, rgb(185 182 174 / 0.2) 1px, transparent 1px);
    background-size: 6cqh 6cqh; }
  .cam { position: absolute; inset: 0; }
  .kicker { position: absolute; left: var(--x); top: 9cqh; margin: 0; font: 500 var(--k)/1.2 var(--font-mono);
            letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
  .kicker b { color: var(--accent-text); font-weight: 500; }
  .aside { position: absolute; right: var(--x); top: 9cqh; margin: 0; font: 500 var(--k)/1.2 var(--font-mono);
           letter-spacing: 0.04em; color: var(--muted); white-space: nowrap; }
  .mid { position: absolute; left: var(--x); right: var(--x); top: var(--mid); translate: 0 -50%; }
  @keyframes rise { from { opacity: 0; transform: translateY(0.5em); } to { opacity: 1; transform: none; } }
  @keyframes draw { from { transform: scaleX(0); } to { transform: scaleX(1); } }
  @keyframes pop { 0% { opacity: 0; transform: scale(0.2); } 70% { opacity: 1; transform: scale(1.25); } 100% { opacity: 1; transform: scale(1); } }
  @keyframes tick { from { opacity: 0; transform: scaleY(0); } to { opacity: 1; transform: scaleY(1); } }
  @keyframes sweep { from { left: 0%; } to { left: 100%; } }
  .r { opacity: 0; animation: rise 0.6s cubic-bezier(0.16, 1, 0.3, 1) var(--at, 0s) both; }

  /* hook: complete at frame 0 (the poster); a playhead runs over the session's strip */
  .hook { display: flex; flex-direction: column; gap: 3.2cqh; right: 10cqw; }
  .hook .title { margin: 0; font: 400 var(--title)/0.98 var(--font-display); letter-spacing: -0.012em; color: var(--fg);
                 max-width: 14em; text-wrap: balance; overflow-wrap: anywhere; }
  .hook .title code, .end .title code { font-family: var(--font-display); font-style: italic; color: var(--accent-text); }
  .hook .dek { margin: 0; font: 400 var(--dek)/1.34 var(--font-sans); color: var(--muted); max-width: 34em; text-wrap: pretty; }
  .hook .meta { margin: 0.6cqh 0 0; font: 500 var(--meta)/1.2 var(--font-mono); letter-spacing: 0.04em; color: var(--fg); }
  .strip { position: absolute; left: var(--x); right: var(--x); top: 75cqh; height: 3.2cqh;
           border-top: max(1px, 0.12cqh) solid var(--hair); }
  .strip i { position: absolute; top: 0.6cqh; width: max(2px, 0.16cqw); height: 2.2cqh; background: var(--hair); }
  .strip i.e { background: var(--accent); height: 2.6cqh; } .strip i.t { background: var(--good); }
  .strip span { position: absolute; top: 3.6cqh; font: 500 var(--tag)/1 var(--font-mono); color: var(--muted); }
  .strip .s0 { left: 0; } .strip .s1 { right: 0; }
  .strip b { position: absolute; top: -1.2cqh; bottom: -0.6cqh; left: 0; width: max(2px, 0.16cqw); background: var(--accent);
             animation: sweep var(--sweep) linear var(--at) both; }

  /* numbers */
  .stats { display: flex; flex-wrap: wrap; column-gap: 4.2cqw; row-gap: 5cqh; }
  .stat { border-top: max(1px, 0.14cqh) solid var(--hair); padding-top: 2.6cqh; min-width: 9cqw; }
  .stat .v { display: block; font: 400 var(--stat)/0.95 var(--font-display); color: var(--fg); letter-spacing: -0.02em;
             white-space: nowrap; }
  .stat .l { display: block; margin-top: 1.8cqh; font: 500 var(--lab)/1.25 var(--font-mono); letter-spacing: 0.08em;
             text-transform: uppercase; color: var(--muted); white-space: nowrap; }
  .stat:first-child .v { color: var(--accent-text); font-style: italic; }

  /* timeline: lanes, ticks, a playhead */
  .tl { position: absolute; left: var(--x); right: var(--x); top: 17cqh; height: 60cqh; --label: 15cqw; --lead: 16.3cqh; }
  .tl .co { position: absolute; left: var(--label); right: 0; top: 0; height: 12cqh; }
  .tl .co span { position: absolute; bottom: calc(var(--tier) * 5.2cqh); white-space: nowrap; font: 500 var(--tag)/1 var(--font-mono);
                 color: var(--accent-text); padding: 0 0 0.3cqh 0.9cqw; border-left: max(2px, 0.18cqh) solid var(--accent);
                 opacity: 0; animation: rise 0.45s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .tl .co span::after { content: ""; position: absolute; left: calc(-1 * max(2px, 0.18cqh)); top: 100%;
                        height: calc(var(--lead) + var(--tier) * 5.2cqh); border-left: max(1px, 0.12cqh) dashed var(--accent); opacity: 0.55; }
  .tl .lanes { position: absolute; left: 0; right: 0; top: 15cqh; bottom: 8cqh; display: flex; flex-direction: column;
               justify-content: space-between; }
  .tl .lane { position: relative; height: 6cqh; }
  .tl .lane .name { position: absolute; left: 0; top: 50%; translate: 0 -50%; font: 500 var(--lane)/1 var(--font-mono);
                    letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
  .tl .lane .name b { color: var(--fg); font-weight: 600; margin-left: 0.5em; }
  .tl .track { position: absolute; left: var(--label); right: 0; top: 50%; height: 0; border-top: max(1px, 0.12cqh) solid var(--hair); }
  .tl .tk { position: absolute; top: -2.3cqh; width: max(2px, 0.2cqw); height: 4.6cqh; margin-left: -0.1cqw;
            background: var(--fg); opacity: 0; transform-origin: 50% 100%; animation: tick 0.2s ease-out var(--at) both; }
  .tl .edit .tk { background: var(--accent); width: max(3px, 0.3cqw); }
  .tl .test .tk { top: -1.3cqh; width: 2.6cqh; height: 2.6cqh; margin-left: -1.3cqh; border-radius: 50%;
                  background: var(--hair); animation-name: pop; animation-duration: 0.35s; }
  .tl .test .tk.ok { background: var(--good); } .tl .test .tk.bad { background: var(--accent); }
  .tl .ph { position: absolute; left: var(--label); right: 0; top: 13cqh; bottom: 6cqh; pointer-events: none; }
  .tl .ph i { position: absolute; top: 0; bottom: 0; left: 0; width: max(2px, 0.16cqw); background: var(--accent);
              animation: sweep var(--sweep) linear var(--at) both; }
  .tl .axis { position: absolute; left: var(--label); right: 0; bottom: 0; display: flex; justify-content: space-between;
              font: 500 var(--tag)/1 var(--font-mono); color: var(--muted); letter-spacing: 0.04em; }

  /* files */
  .files .head, .tests .head { margin: 0 0 3.6cqh; font: 400 var(--head)/1 var(--font-display); color: var(--fg); letter-spacing: -0.015em; }
  .files ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1.7cqh; }
  .files li { display: flex; align-items: baseline; gap: 2cqw; border-bottom: max(1px, 0.12cqh) solid var(--line);
              padding-bottom: 1.5cqh; font: 500 var(--row)/1.2 var(--font-mono); }
  .files .p { color: var(--muted); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .files .p b { color: var(--fg); font-weight: 600; }
  .files .p i { font-style: normal; }
  .files .s { margin-left: auto; white-space: nowrap; color: var(--muted); }
  .files .s .a { color: var(--good); } .files .s .d { color: var(--accent-text); }
  .files .more { margin: 2cqh 0 0; font: 500 var(--tag)/1 var(--font-mono); color: var(--muted); }

  /* tests */
  .dots { display: flex; flex-wrap: wrap; gap: 1.8cqh; margin: 0 0 4.6cqh; max-width: 86cqw; }
  .dots i { display: block; width: 4.6cqh; height: 4.6cqh; border-radius: 50%; background: var(--hair); opacity: 0;
            animation: dotin 0.5s cubic-bezier(0.22, 1, 0.36, 1) var(--at) both; }
  @keyframes dotin { from { opacity: 0; transform: scale(0.55); } to { opacity: 1; transform: none; } }
  .dots i.ok { background: var(--good); } .dots i.bad { background: var(--accent); }
  .tests .res { display: flex; align-items: baseline; gap: 2.6cqw; }
  .tests .v { font: 400 var(--big)/0.86 var(--font-display); color: var(--good); letter-spacing: -0.02em; white-space: nowrap; }
  .tests .v.bad { color: var(--accent-text); }
  .tests .l { font: 500 var(--lab)/1.35 var(--font-mono); text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); max-width: 16em; }
  .tests .note { margin: 3cqh 0 0; font: 400 var(--dek)/1.3 var(--font-sans); color: var(--muted); }
  .tests .legend { margin: 1.6cqh 0 0; font: 500 var(--tag)/1.3 var(--font-mono); color: var(--muted); display: flex;
                   flex-wrap: wrap; column-gap: 2.4cqw; row-gap: 0.6cqh; }
  .tests .legend i { display: inline-block; width: 1.6cqh; height: 1.6cqh; border-radius: 50%; margin-right: 0.6em;
                     background: var(--hair); vertical-align: -0.1em; }
  .tests .legend i.ok { background: var(--good); } .tests .legend i.bad { background: var(--accent); }

  /* diff */
  .diff { display: flex; flex-direction: column; gap: 3.4cqh; }
  .diff .nums { display: flex; gap: 6cqw; align-items: baseline; }
  .diff .a, .diff .d { font: 400 calc(var(--big) * 1.25)/0.86 var(--font-display); letter-spacing: -0.02em; white-space: nowrap; }
  .diff .a { color: var(--good); } .diff .d { color: var(--accent-text); }
  .diff .detail { margin: 0; font: 500 var(--row)/1.2 var(--font-mono); color: var(--fg); letter-spacing: 0.02em; }
  .diff .bar { height: 1.6cqh; display: flex; width: 64cqw; max-width: 100%; border-radius: 0.8cqh; overflow: hidden; }
  .diff .bar i { display: block; height: 100%; transform-origin: left; animation: draw 0.9s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .diff .bar .ga { background: var(--good); } .diff .bar .gd { background: var(--accent); }

  /* end */
  .end { display: flex; flex-direction: column; gap: 3.2cqh; right: 10cqw; }
  .end .title { margin: 0; font: 400 calc(var(--title) * 0.86)/1 var(--font-display); color: var(--fg); max-width: 15em; text-wrap: balance; }
  .end .outcome { margin: 0; font: 500 var(--row)/1.3 var(--font-mono); color: var(--good); letter-spacing: 0.02em; }
  .end .note { margin: 0; font: 500 var(--tag)/1.3 var(--font-mono); color: var(--muted); letter-spacing: 0.04em; }

  /* tall frames (--aspect 9:16): captions hang from 62 % of the height and the platform's buttons cover the
     right edge, so the content sits above the captions and left of the buttons, in phone-sized type */
  @container (max-aspect-ratio: 3/4) {
    .scene { --x: 8cqw; --mid: 37.4cqh; --k: 4.1cqw; --title: 11cqw; --dek: 4.7cqw; --meta: 4.2cqw; --stat: 10.5cqw;
             --lab: 4.1cqw; --lane: 4.1cqw; --tag: 4.1cqw; --row: 4.1cqw; --head: 10cqw; --big: 22cqw; }
    .paper .frame, .paper .grid { inset: 2.2cqh 3.6cqw; }
    .kicker { top: 12.8cqh; right: 16cqw; white-space: normal; letter-spacing: 0.06em; }
    .mid, .hook, .end { right: 16cqw; }
    .aside { left: var(--x); right: 16cqw; top: 16.6cqh; white-space: normal; letter-spacing: 0; }
    .strip { top: 56cqh; right: 16cqw; }
    .stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 6cqw; row-gap: 3cqh; }
    .stat { min-width: 0; padding-top: 1.6cqh; }
    .stat .l { white-space: normal; }
    .tl { top: 23cqh; height: 34cqh; right: 16cqw; --label: 24cqw; }
    .tl .co { display: none; }
    .tl .lanes { top: 2cqh; bottom: 5cqh; }
    .tl .ph { top: 1cqh; bottom: 4cqh; }
    .files .p i { display: none; }
    .tests { top: 21cqh; translate: 0 0; }        /* anchored under the kicker: the dots and legend make it tall */
    .tests .head { margin-bottom: 2.4cqh; }
    .dots { max-width: none; gap: 2.2cqw; margin-bottom: 2.6cqh; }
    .dots i { width: 6cqw; height: 6cqw; }
    .tests .res { --big: 17cqw; gap: 3cqw; }
    .diff .nums { flex-direction: column; gap: 1cqh; }
    .diff .bar { width: 100%; }
  }
"""


def _e(s: str) -> str:
    return rv._e(s)


def _title_html(s: str) -> str:
    return rv._inline(s)


def _path_html(path: str) -> str:
    d, _, name = path.rpartition("/")
    return "%s<b>%s</b>" % ("<i>%s</i>" % _e(d + "/") if d else "", _e(name))


def _lane_html(text: str) -> str:
    m = re.match(r"^(.*?)\s+([\d,]+)$", text)
    return "%s<b>%s</b>" % (_e(m.group(1)), _e(m.group(2))) if m else _e(text)


def _callout_tiers(items: List[Tuple[float, str]], width_cqw: float = 72.6) -> List[Tuple[float, int]]:
    """(x in %, tier) per callout: two tiers, labels pushed right (and clamped) so none overlap."""
    ends = [-1.0, -1.0]
    out = []
    for x, text in items:
        w = (len(text) * 0.95 + 1.8) / width_cqw * 100.0       # a label's width, in % of the track
        x = min(x, max(0.0, 100.0 - w))
        tier = 0 if x >= ends[0] else (1 if x >= ends[1] else (0 if ends[0] <= ends[1] else 1))
        x = max(x, ends[tier])
        x = min(x, max(0.0, 100.0 - w))
        ends[tier] = x + w + 0.8
        out.append((round(x, 2), tier))
    return out


def build_page(facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]", scenes: Sequence[str],
               durs: Dict[str, float], *, captions: bool = False, aspect: str = "16:9") -> str:
    T = lambda k: lines[k]["text"] if k in lines else ""  # noqa: E731
    tall = aspect == "9:16"
    out: List[str] = []
    prev = ""
    dur_total = max(1.0, facts.get("span") or facts["duration"] or 1.0)   # positions: wall-clock
    for sid in scenes:
        d = durs[sid]
        start = "0" if not prev else "#" + prev
        trans = "" if not prev else ' data-transition="dip 0.5"'
        push = [{"at": 0, "zoom": 1}, {"at": 0.15, "dur": round(max(1.0, d - 0.3), 2), "zoom": 1.025 if tall else 1.035,
                                       "focus": [50, 36] if tall else [42, 46], "to": "stay", "ease": "linear"}]
        out.append('  <section class="scene" id="%s" data-start="%s" data-dur="%.2f"%s>\n    <div class="cam" '
                   'data-st="camera" data-path=\'%s\'>' % (sid, start, d, trans, json.dumps(push)))
        if sid == "hook":
            if T("hook.kicker"):
                out.append('      <p class="kicker">%s</p>' % _kicker_html(T("hook.kicker")))
            out.append('      <div class="mid hook">')
            if T("hook.title"):
                out.append('        <h1 class="title">%s</h1>' % _title_html(T("hook.title")))
            if T("hook.request"):
                out.append('        <p class="dek">%s</p>' % _e(T("hook.request")))
            if T("hook.meta"):
                out.append('        <p class="meta">%s</p>' % _e(T("hook.meta")))
            out.append("      </div>")
            out.append(_strip_html(facts, d, lines))
        elif sid == "numbers":
            if T("numbers.kicker"):
                out.append('      <p class="kicker r" style="--at:0.1s">%s</p>' % _e(T("numbers.kicker")))
            keys = [k[5:-6] for k in lines if k.startswith("stat.") and k.endswith(".value")]
            out.append('      <div class="mid stats">')
            for i, k in enumerate(keys):
                out.append('        <div class="stat r" style="--at:%.2fs"><span class="v">%s</span><span class="l">%s'
                           '</span></div>' % (0.25 + 0.18 * i, _e(T("stat.%s.value" % k)), _e(T("stat.%s.label" % k))))
            out.append("      </div>")
        elif sid == "timeline":
            out.append(_timeline_html(facts, lines, d, dur_total))
        elif sid == "files":
            if T("files.kicker"):
                out.append('      <p class="kicker r" style="--at:0.1s">%s</p>' % _e(T("files.kicker")))
            out.append('      <div class="mid files">')
            if T("files.head"):
                out.append('        <h2 class="head r" style="--at:0.2s">%s</h2>' % _e(T("files.head")))
            out.append("        <ul>")
            i = 0
            for k in lines:
                if re.fullmatch(r"file\.\d+", k):
                    stat = T(k + ".stat")
                    m = re.match(r"^\+([\d,]+)\s+[−-]([\d,]+)$", stat)
                    stat_html = ('<span class="a">+%s</span> <span class="d">−%s</span>' % (m.group(1), m.group(2))
                                 if m else _e(stat))
                    out.append('          <li class="r" style="--at:%.2fs"><span class="p">%s</span><span class="s">%s'
                               '</span></li>' % (0.45 + 0.15 * i, _path_html(T(k)), stat_html))
                    i += 1
            out.append("        </ul>")
            if T("files.more"):
                out.append('        <p class="more r" style="--at:%.2fs">%s</p>' % (0.45 + 0.15 * i, _e(T("files.more"))))
            out.append("      </div>")
        elif sid == "tests":
            out.append(_tests_html(facts, lines))
        elif sid == "diff":
            if T("diff.kicker"):
                out.append('      <p class="kicker r" style="--at:0.1s">%s</p>' % _e(T("diff.kicker")))
            out.append('      <div class="mid diff">')
            if T("diff.adds") or T("diff.dels"):
                out.append('        <div class="nums r" style="--at:0.25s"><span class="a">%s</span><span class="d">%s</span>'
                           '</div>' % (_e(T("diff.adds")), _e(T("diff.dels"))))
                a, dl = facts["diff"]["additions"], facts["diff"]["deletions"]
                tot = max(1, a + dl)
                out.append('        <div class="bar"><i class="ga" style="width:%.1f%%;--at:0.6s"></i><i class="gd" '
                           'style="width:%.1f%%;--at:0.9s"></i></div>' % (100.0 * a / tot, 100.0 * dl / tot))
            if T("diff.detail"):
                out.append('        <p class="detail r" style="--at:0.7s">%s</p>' % _e(T("diff.detail")))
            out.append("      </div>")
        else:
            if T("end.kicker"):
                out.append('      <p class="kicker r" style="--at:0.1s"><b>%s</b></p>' % _e(T("end.kicker")))
            out.append('      <div class="mid end">')
            if T("hook.title"):
                out.append('        <h2 class="title r" style="--at:0.25s">%s</h2>' % _title_html(T("hook.title")))
            if T("end.outcome"):
                out.append('        <p class="outcome r" style="--at:0.5s">%s</p>' % _e(T("end.outcome")))
            if T("end.note"):
                out.append('        <p class="note r" style="--at:0.8s">%s</p>' % _e(T("end.note")))
            out.append("      </div>")
        out.append("    </div>\n  </section>")
        prev = sid
    cap = ('\n  <div data-st="caption-karaoke" data-src="voice/captions.words.json" data-style="clean-pop" '
           'data-at="0"></div>' if captions else "")
    title = T("hook.title") or "Session recap"
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>%s</title>\n"
            "<script src=\"/_st/stage.js\"></script>\n<link rel=\"stylesheet\" href=\"/_st/themes/base.css\">\n"
            "<link rel=\"stylesheet\" href=\"/_st/themes/fonts/geist.css\">\n"
            "<link rel=\"stylesheet\" href=\"/_st/themes/fonts/geist-mono.css\">\n"
            "<link rel=\"stylesheet\" href=\"/_st/themes/fonts/instrument-serif.css\">\n"
            "<script type=\"module\" src=\"/_st/components/index.js\"></script>\n<!-- Written by `showtime recap` "
            "from script.md: every word on screen is a line of that script (the session's allow-listed facts). "
            "Edit script.md and rerun recap rather than this page. -->\n<style>%s</style>\n</head>\n<body>\n"
            "<div class=\"stage\">\n  <div class=\"paper\" data-st-decor><div class=\"grid\"></div><div class=\"frame\">"
            "</div></div>\n%s%s\n</div>\n</body>\n</html>\n" % (_e(title), CSS, "\n".join(out), cap))


def _kicker_html(text: str) -> str:
    parts = text.split(" · ", 1)
    return "<b>%s</b>%s" % (_e(parts[0]), (" &nbsp;·&nbsp; " + _e(parts[1])) if len(parts) > 1 else "")


def _timeline_html(facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]", d: float, dur_total: float) -> str:
    T = lambda k: lines[k]["text"] if k in lines else ""  # noqa: E731
    sweep_at = 0.5
    sweep = max(2.0, d - sweep_at - 1.2)
    at = lambda t: sweep_at + sweep * min(1.0, max(0.0, t / dur_total))  # noqa: E731
    o = []
    if T("timeline.kicker"):
        o.append('      <p class="kicker r" style="--at:0.1s">%s</p>' % _e(T("timeline.kicker")))
    o.append('      <div class="tl">')
    # edited files as callouts above the lanes, at their first edit
    edited = sorted([f for f in facts["files"] if f["edited"]], key=lambda f: f["first_edit"] or 0)
    items = []
    for i, f in enumerate(edited[:MAX_CALLOUTS]):
        k = "callout.%d" % (i + 1)
        if T(k):
            items.append(((f["first_edit"] or 0) / dur_total * 100.0, T(k), f["first_edit"] or 0))
    if items:
        o.append('        <div class="co">')
        for (x, tier), (_x, text, t) in zip(_callout_tiers([(x, s) for x, s, _t in items]), items):
            o.append('          <span style="left:%.2f%%;--tier:%d;--at:%.2fs">%s</span>' % (x, tier, at(t) + 0.1, _e(text)))
        o.append("        </div>")
    o.append('        <div class="lanes">')
    events = facts["timeline"]
    for k in ("read", "edit", "run", "test"):
        key = "lane.%s" % k
        if key not in lines:
            continue
        o.append('          <div class="lane %s"><span class="name">%s</span><div class="track">' % (k, _lane_html(T(key))))
        if k == "test":
            for x in facts["tests"][:120]:
                cls = " ok" if x["ok"] else (" bad" if x["ok"] is False else "")
                o.append('            <i class="tk%s" style="left:%.2f%%;--at:%.2fs"></i>' % (
                    cls, 100.0 * min(1.0, x["t"] / dur_total), at(x["t"])))
        else:
            ts = [e["t"] for e in events if e["k"] == k]
            # at most ~140 ticks a lane: nearby events merge into one
            step = dur_total / 140.0
            seen = set()
            for t in ts:
                b = int(t / step) if step > 0 else 0
                if b in seen:
                    continue
                seen.add(b)
                o.append('            <i class="tk" style="left:%.2f%%;--at:%.2fs"></i>' % (
                    100.0 * min(1.0, t / dur_total), at(t)))
        o.append("          </div></div>")
    o.append("        </div>")
    o.append('        <div class="ph"><i style="--at:%.2fs;--sweep:%.2fs"></i></div>' % (sweep_at, sweep))
    if T("axis.start") or T("axis.end"):
        o.append('        <div class="axis r" style="--at:0.3s"><span>%s</span><span>%s</span></div>' % (
            _e(T("axis.start")), _e(T("axis.end"))))
    o.append("      </div>")
    if T("timeline.commands"):
        o.append('      <p class="aside r" style="--at:0.4s">%s</p>' % _e(T("timeline.commands")))
    return "\n".join(o)


def _legend_html(text: str) -> str:
    """'red failed · green passed · grey not counted' with a dot of the colour before each part."""
    out = []
    for part in text.split(" · "):
        w = part.split(" ", 1)[0].lower()
        cls = {"red": "bad", "green": "ok", "grey": "", "gray": ""}.get(w)
        out.append(('<span><i class="%s"></i>%s</span>' % (cls, _e(part))) if cls is not None else _e(part))
    return " ".join(out)


def _strip_html(facts: Dict[str, Any], d: float, lines: Optional["OrderedDict[str, Dict[str, Any]]"] = None) -> str:
    """The hook's strip: the whole session as ticks (complete at frame 0), a playhead running over it."""
    dur_total = max(1.0, facts.get("span") or facts["duration"] or 1.0)   # positions: wall-clock
    step = dur_total / 160.0
    seen = set()
    ticks = []
    for e in facts["timeline"]:
        if e["k"] not in ("read", "edit", "run", "test"):
            continue
        b = (int(e["t"] / step), e["k"] == "edit")
        if b in seen:
            continue
        seen.add(b)
        ticks.append('<i%s style="left:%.2f%%"></i>' % ({"edit": ' class="e"', "test": ' class="t"'}.get(e["k"], ""),
                                                       100.0 * min(1.0, e["t"] / dur_total)))
    axis = ""
    if lines and ("axis.start" in lines or "axis.end" in lines):
        axis = '<span class="s0">%s</span><span class="s1">%s</span>' % (
            _e(lines["axis.start"]["text"] if "axis.start" in lines else ""),
            _e(lines["axis.end"]["text"] if "axis.end" in lines else ""))
    return ('      <div class="strip">%s<b style="--at:0.3s;--sweep:%.2fs"></b>%s</div>'
            % ("".join(ticks), max(1.0, d - 0.8), axis))


DOTS_AT = 0.95          # after the cut's dip and the heading's rise: nothing starts while the scene settles


def _tests_html(facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]") -> str:
    T = lambda k: lines[k]["text"] if k in lines else ""  # noqa: E731
    o = []
    if T("tests.kicker"):
        o.append('      <p class="kicker r" style="--at:0.1s">%s</p>' % _e(T("tests.kicker")))
    o.append('      <div class="mid tests">')
    if T("tests.head"):
        o.append('        <h2 class="head r" style="--at:0.2s">%s</h2>' % _e(T("tests.head")))
    runs = facts["tests"][-40:]
    o.append('        <div class="dots">%s</div>' % "".join(
        '<i class="%s" style="--at:%.2fs"></i>' % ("ok" if x["ok"] else ("bad" if x["ok"] is False else ""),
                                                  DOTS_AT + 0.07 * i)
        for i, x in enumerate(runs)))
    t_res = DOTS_AT + 0.07 * len(runs) + 0.2
    st = test_story(facts["tests"])
    if T("tests.value") or T("tests.label"):
        o.append('        <div class="res r" style="--at:%.2fs"><span class="v%s">%s</span><span class="l">%s</span></div>'
                 % (t_res, " bad" if st["ends_red"] else "", _e(T("tests.value")), _e(T("tests.label"))))
    if T("tests.note"):
        o.append('        <p class="note r" style="--at:%.2fs">%s</p>' % (t_res + 0.4, _e(T("tests.note"))))
    if T("tests.legend"):
        o.append('        <p class="legend r" style="--at:%.2fs">%s</p>' % (t_res + 0.6, _legend_html(T("tests.legend"))))
    o.append("      </div>")
    return "\n".join(o)


SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920)}


def project_files(facts: Dict[str, Any], lines: "OrderedDict[str, Dict[str, Any]]", scenes: Sequence[str],
                  durs: Dict[str, float], *, aspect: str = "16:9", captions: bool = False,
                  fps: int = 30, music: Optional[str] = None, fetch: bool = False,
                  project: Optional[Path] = None, cut_sounds: bool = False) -> Dict[str, Any]:
    """{index.html, showtime.json, audio/mix.json, recap.json} contents for a project. The bed and the effects
    come from the session (st.bed: the same session sounds the same, another one does not); `music` pins the bed."""
    w, h = SIZES[aspect]
    total = round(sum(durs[s] for s in scenes), 2)
    title = lines["hook.title"]["text"] if "hook.title" in lines else "Session recap"
    p = {"scenes": [{"id": s, "dur": durs[s]} for s in scenes], "kind": "recap"}
    starts, t = [], 0.0
    for s_ in scenes:
        starts.append(round(t, 2))
        t += durs[s_]
    names = ["intro"] + ["verse"] * max(0, len(starts) - 2) + ["outro"]
    key = str(facts.get("ref") or title)
    choice = bed.choose("recap", key, total, ",".join("%g:%s" % (a, b) for a, b in zip(starts, names)), pin=music,
                        gain_db=-2, fetch=fetch, project=project,
                        duck={"under": "voice", "depth_db": bed.DUCK_DEPTH_DB} if captions else None)
    tracks: List[Dict[str, Any]] = [choice["track"]] if choice["track"] else []
    for a in starts[1:] if cut_sounds else ():       # opt-in (--cut-sounds): a soft swoosh as the picture visibly changes
        tracks.append({"kind": "sfx", "synth": bed.synth(key, "cut", int(a), 0.35, choice.get("key")), "at": round(a + 0.15, 2),
                       "align": "hit", "gain_db": bed.CUT_GAIN_DB})
    mix = {"_comment": bed.comment(choice, bool(len(starts) > 1 and cut_sounds)),
           "sample_rate": 48000, "tracks": tracks, "master": {"lufs": -14, "true_peak": -1}}
    cfg = {"title": title, "width": w, "height": h, "fps": fps, "duration": total, "background": GROUND,
           "poster": 0, "audio": "audio/mix.json", "subtitle": "What the agent did, from the session log.",
           "kicker": "Recap", "startTitle": False, "render": {"crf": 22},
           "expect": {"duration": total, "audio": True}}
    src = {"generator": "showtime recap", "note": "the allow-listed facts this film was made from (no transcript "
           "text, no tool output, no absolute paths)", "facts": facts,
           "scenes": [{"id": s, "dur": durs[s]} for s in scenes]}
    return {"index.html": build_page(facts, lines, scenes, durs, captions=captions, aspect=aspect),
            "showtime.json": json.dumps(cfg, indent=2) + "\n", "audio/mix.json": json.dumps(mix, indent=2) + "\n",
            "recap.json": json.dumps(src, indent=2) + "\n", "duration": total, "bed": choice}


def write_project(out: Path, files: Dict[str, Any]) -> None:
    out = Path(out)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "showtime.json", "audio/mix.json", "recap.json"):
        (out / name).write_text(files[name], encoding="utf-8")


def summary(facts: Dict[str, Any]) -> str:
    st = test_story(facts["tests"]) if facts["tests"] else None
    parts = [fmt_duration(facts["duration"]), _plural(facts["turns"], "turn"), _plural(facts["tool_calls"], "tool call"),
             _plural(len(facts["files"]), "repo file"), "%d edited" % sum(1 for f in facts["files"] if f["edited"])]
    if st:
        parts.append(_plural(st["runs"], "test run") + (" (red to green)" if st["red_to_green"] else ""))
    if facts["diff"]["files"]:
        parts.append("+%d -%d in %s" % (facts["diff"]["additions"], facts["diff"]["deletions"],
                                        _plural(facts["diff"]["files"], "file")))
    if facts["files_outside"]:
        parts.append("%s outside the repo left out" % _plural(facts["files_outside"], "path"))
    return ", ".join(parts)
