"""The stable `showtime` command in <SHOWTIME_HOME>/bin (stdlib only, Python 3.8+).

The skill folder moves: a plugin update installs a new version folder, another agent host keeps its
skills somewhere else, a developer links a checkout. Scripts, agent configs and PATH need one path that
never changes, so setup writes three small launchers into <home>/bin:

  showtime        POSIX sh      showtime.cmd   Windows cmd      showtime.ps1   PowerShell

They hold no paths of their own. Each one runs the launcher of the skill folder named in
<home>/skill-path, and when that folder is gone it tries $SHOWTIME_SKILL, <home>/skill, then the usual
skill folders (SKILL_GLOBS), taking the last match. A skill that runs from npm's cache (npx) is never
recorded as it is: npm deletes that cache, so it is copied to <home>/skill first (stable_skill). Every run of any skill's launcher keeps skill-path current (`remember`): it
records itself when the recorded folder is missing or holds an older or the same showtime version, so a plugin
update is picked up by the first command the new version runs. `showtime doctor` rewrites damaged or
outdated launchers (`repair`).

Nothing here edits shell profiles or PATH. `path_hint` prints how to make `showtime` callable from any
terminal, for the user to run (or not).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SHIM_VERSION = 1
MARK = "showtime-shim %d" % SHIM_VERSION

# Where agent hosts keep installed skills, relative to the user's home folder. The launchers search
# these only when <home>/skill-path is missing or stale; any match that holds lib/st/launcher.py works.
# Claude Code plugins: cache/<marketplace>/<plugin>/<version>/ (a lexically later version wins).
SKILL_GLOBS = [
    ".claude/plugins/cache/*/showtime/*/skills/showtime",
    ".claude/skills/showtime",
    ".agents/skills/showtime",
    ".codex/skills/showtime",
    ".codex/plugins/cache/*/showtime/*/skills/showtime",
    ".cursor/skills/showtime",
    ".gemini/extensions/showtime/skills/showtime",
    ".gemini/skills/showtime",
    ".copilot/skills/showtime",
    ".kiro/skills/showtime",
    ".config/opencode/skills/showtime",
]


def names() -> List[str]:
    return ["showtime", "showtime.cmd", "showtime.ps1"] if os.name == "nt" else ["showtime"]


def shim_path(home: Path) -> Path:
    return Path(home) / "bin" / ("showtime.cmd" if os.name == "nt" else "showtime")


def record_file(home: Path) -> Path:
    return Path(home) / "skill-path"


def valid_skill(d: Optional[os.PathLike]) -> bool:
    if not d:
        return False
    p = Path(d)
    return (p / "lib" / "st" / "launcher.py").is_file() and (p / "bin").is_dir()


def skill_version(d: Path) -> Tuple[int, ...]:
    try:
        text = (Path(d) / "lib" / "st" / "__init__.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", text)
    return tuple(int(x) for x in re.findall(r"\d+", m.group(1))[:3]) if m else ()


def recorded_skill(home: Path) -> Optional[Path]:
    try:
        line = record_file(home).read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError, UnicodeDecodeError):
        return None
    return Path(line) if line else None


def _write_atomic(path: Path, text: str, newline: Optional[str] = None, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    with open(str(tmp), "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(str(tmp), mode)
    os.replace(str(tmp), str(path))


def record(home: Path, skill: Path) -> None:
    # CRLF on Windows: `set /p` in showtime.cmd reads the first line up to CR LF
    _write_atomic(record_file(home), str(Path(skill)) + "\n")


def remember(home: Path, skill: Path) -> bool:
    """Called on every launcher run: keep <home>/skill-path pointing at a live, newest skill.

    Only when the shim is installed (setup or doctor put it there); never raises. True when it wrote."""
    try:
        if not shim_path(home).is_file():
            return False
        return _update_record(Path(home), Path(skill))
    except OSError:
        return False


def _update_record(home: Path, skill: Path) -> bool:
    """Record the newer of the recorded skill and `skill` (a tie goes to `skill`), through a copy
    in <home>/skill when it lives somewhere that gets deleted (is_ephemeral). True when it wrote."""
    rec = recorded_skill(home)
    rec_ok = valid_skill(rec)
    if rec_ok and _same(rec, skill) and not is_ephemeral(rec):
        return False                                   # the common case: two small reads
    cands = ([rec] if rec_ok else []) + ([skill] if valid_skill(skill) else [])
    if not cands:
        return False
    # a tie goes to the skill running now: two folders of the same version can hold different code (a
    # plugin and a checkout, two agent hosts), and the command must run the one the agent is using
    best = max(cands, key=lambda p: (skill_version(p), p is not rec))
    target = stable_skill(home, best)
    if rec_ok and _same(target, rec):
        return False
    record(home, target)
    return True


# --------------------------------------------------------------------------- skills in caches

COPY_NAME = "skill"          # <home>/skill: the kept copy of a skill that ran from a cache
COPY_SKIP = ("tests", "__pycache__", "*.pyc", "*.pyo", "node_modules", "showtime-out", "work", ".DS_Store")


def _npm_caches() -> List[str]:
    out = []
    if os.environ.get("npm_config_cache"):
        out.append(os.environ["npm_config_cache"])
    out.append(os.path.join(os.path.expanduser("~"), ".npm"))
    if os.environ.get("LOCALAPPDATA"):
        out.append(os.path.join(os.environ["LOCALAPPDATA"], "npm-cache"))
    return [os.path.normcase(os.path.abspath(c)) for c in out]


def is_ephemeral(skill: Optional[os.PathLike]) -> bool:
    """A skill folder that its package manager may delete at any time: npx runs packages from npm's cache
    (`<cache>/_npx/<hash>/node_modules/...`), which npm prunes. Recording it would break the command."""
    if not skill:
        return False
    p = os.path.normcase(os.path.abspath(str(skill)))
    if "_npx" in Path(p).parts:
        return True
    return any(p == c or p.startswith(c.rstrip(os.sep) + os.sep) for c in _npm_caches())


def stable_skill(home: Path, skill: Path, force: bool = False) -> Path:
    """`skill` itself, or for a skill in a cache (is_ephemeral, or any skill with force=True) a copy in
    <home>/skill, refreshed when the given one is newer. The copy is about 6 MB (no tests). Falls back to
    `skill` if copying fails."""
    if not force and not is_ephemeral(skill):
        return Path(skill)
    if _same(Path(home) / COPY_NAME, skill):
        return Path(skill)
    dest = Path(home) / COPY_NAME
    if valid_skill(dest) and skill_version(dest) >= skill_version(skill):
        return dest
    import shutil
    tmp = Path(home) / (".%s-new-%d" % (COPY_NAME, os.getpid()))
    old = Path(home) / (".%s-old-%d" % (COPY_NAME, os.getpid()))
    try:
        shutil.rmtree(str(tmp), ignore_errors=True)
        shutil.copytree(str(skill), str(tmp), ignore=shutil.ignore_patterns(*COPY_SKIP))
        if dest.exists():
            os.replace(str(dest), str(old))
        os.replace(str(tmp), str(dest))
        shutil.rmtree(str(old), ignore_errors=True)
        return dest
    except OSError:
        shutil.rmtree(str(tmp), ignore_errors=True)
        if old.exists() and not dest.exists():
            try:
                os.replace(str(old), str(dest))
            except OSError:
                pass
        return dest if valid_skill(dest) else Path(skill)


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def find_skills(user_home: Optional[Path] = None) -> List[Path]:
    """Every installed showtime skill folder in the usual places, newest version first."""
    h = Path(user_home) if user_home else Path(os.path.expanduser("~"))
    found: List[Path] = []
    for pat in SKILL_GLOBS:
        try:
            for d in sorted(h.glob(pat)):
                if valid_skill(d) and not any(_same(d, x) for x in found):
                    found.append(d)
        except OSError:
            continue
    found.sort(key=lambda d: (skill_version(d), _mtime(d)), reverse=True)
    return found


def _mtime(d: Path) -> float:
    try:
        return (d / "lib" / "st" / "__init__.py").stat().st_mtime
    except OSError:
        return 0.0


# --------------------------------------------------------------------------- the three launchers

def _sh_text() -> str:
    globs = " ".join('"$HOME"/%s' % g for g in SKILL_GLOBS)
    return r"""#!/bin/sh
# %(mark)s: the stable `showtime` command, written by `showtime setup` (`showtime doctor` repairs it).
# It runs the launcher of the installed showtime skill: the folder in ../skill-path (every showtime
# run keeps it current), else $SHOWTIME_SKILL, else the usual skill folders. Put this folder on PATH, or
# link this file into one (ln -s <this file> ~/.local/bin/showtime), to type `showtime` anywhere.
self="$0"
while [ -h "$self" ]; do
  link=$(readlink "$self")
  case "$link" in
    /*) self="$link" ;;
    *) self="$(dirname "$self")/$link" ;;
  esac
done
st_home=$(cd "$(dirname "$self")/.." && pwd -P)
is_skill() { [ -n "$1" ] && [ -f "$1/lib/st/launcher.py" ] && [ -f "$1/bin/showtime" ]; }
skill=""
if [ -f "$st_home/skill-path" ]; then
  IFS= read -r rec < "$st_home/skill-path" || [ -n "$rec" ]
  rec=$(printf '%%s' "$rec" | tr -d '\r')
  if is_skill "$rec"; then skill="$rec"; fi
fi
if [ -z "$skill" ] && is_skill "${SHOWTIME_SKILL:-}"; then skill="$SHOWTIME_SKILL"; fi
if [ -z "$skill" ] && is_skill "$st_home/skill"; then skill="$st_home/skill"; fi
if [ -z "$skill" ]; then
  for cand in %(globs)s; do
    if is_skill "$cand"; then skill="$cand"; fi
  done
fi
if [ -z "$skill" ]; then
  echo "showtime: cannot find the showtime skill folder (recorded in $st_home/skill-path)." >&2
  echo "  fix: reinstall or update showtime in your agent, then run <skill folder>/bin/showtime doctor" >&2
  exit 127
fi
SHOWTIME_HOME="${SHOWTIME_HOME:-$st_home}"
export SHOWTIME_HOME
exec sh "$skill/bin/showtime" "$@"
""" % {"mark": MARK, "globs": globs}


def _cmd_text() -> str:
    lines = [
        "@echo off",
        "rem %s: the stable `showtime` command, written by `showtime setup` (`showtime doctor` repairs it)." % MARK,
        "rem It runs the launcher of the installed showtime skill: the folder in ..\\skill-path, else",
        "rem %SHOWTIME_SKILL%, else the usual skill folders. No parenthesised blocks around expanded paths.",
        "setlocal",
        'for %%I in ("%~dp0..") do set "ST_HOME=%%~fI"',
        'if not defined SHOWTIME_HOME set "SHOWTIME_HOME=%ST_HOME%"',
        'set "ST_SKILL="',
        'if exist "%ST_HOME%\\skill-path" set /p ST_SKILL=<"%ST_HOME%\\skill-path"',
        'if defined ST_SKILL if not exist "%ST_SKILL%\\lib\\st\\launcher.py" set "ST_SKILL="',
        'if not defined ST_SKILL if defined SHOWTIME_SKILL if exist "%SHOWTIME_SKILL%\\lib\\st\\launcher.py" '
        'set "ST_SKILL=%SHOWTIME_SKILL%"',
        'if not defined ST_SKILL if exist "%ST_HOME%\\skill\\lib\\st\\launcher.py" set "ST_SKILL=%ST_HOME%\\skill"',
    ]
    for g in SKILL_GLOBS:
        parts = g.replace("/", "\\").split("\\")
        if "*" not in g:
            lines.append('if not defined ST_SKILL if exist "%%USERPROFILE%%\\%s\\lib\\st\\launcher.py" '
                         'set "ST_SKILL=%%USERPROFILE%%\\%s"' % ("\\".join(parts), "\\".join(parts)))
            continue
        # nested `for /d` over each wildcard segment (the last match wins, like the sh shim)
        head, loops, var = "%USERPROFILE%", [], 0
        vars_ = "ABCDEFG"
        for seg in parts:
            if "*" in seg:
                v = vars_[var]
                var += 1
                loops.append('for /d %%%%%s in ("%s\\%s") do' % (v, head, seg))
                head = "%%%%~%s" % v
            else:
                head = head + "\\" + seg
        lines.append("if not defined ST_SKILL " + " ".join(loops) +
                     ' if exist "%s\\lib\\st\\launcher.py" set "ST_SKILL=%s"' % (head, head))
    lines += [
        "if not defined ST_SKILL goto missing",
        '"%ST_SKILL%\\bin\\showtime.cmd" %*',
        ":missing",
        "echo showtime: cannot find the showtime skill folder (recorded in %ST_HOME%\\skill-path). 1>&2",
        "echo   fix: reinstall or update showtime in your agent, then run its bin\\showtime.cmd doctor 1>&2",
        "exit /b 127",
    ]
    return "\r\n".join(lines) + "\r\n"


def _ps1_text() -> str:
    pats = ", ".join("'%s'" % g for g in SKILL_GLOBS)
    return """# %(mark)s: the stable `showtime` command, written by `showtime setup` (`showtime doctor` repairs it).
# It runs the launcher of the installed showtime skill: the folder in ..\\skill-path, else
# $env:SHOWTIME_SKILL, else the usual skill folders.
$stHome = Split-Path -Parent $PSScriptRoot
function Test-Skill([string]$d) { return ($d -and (Test-Path -LiteralPath (Join-Path $d 'lib/st/launcher.py'))) }
$skill = $null
$rec = Join-Path $stHome 'skill-path'
if (Test-Path -LiteralPath $rec) {
    $r = Get-Content -LiteralPath $rec -TotalCount 1
    if (Test-Skill $r) { $skill = $r.Trim() }
}
if (-not $skill -and (Test-Skill $env:SHOWTIME_SKILL)) { $skill = $env:SHOWTIME_SKILL }
if (-not $skill -and (Test-Skill (Join-Path $stHome 'skill'))) { $skill = Join-Path $stHome 'skill' }
if (-not $skill) {
    $userHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
    foreach ($pat in @(%(pats)s)) {
        $hit = Get-ChildItem -Path (Join-Path $userHome $pat) -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Skill $_.FullName } | Select-Object -Last 1
        if ($hit) { $skill = $hit.FullName }
    }
}
if (-not $skill) {
    Write-Error "showtime: cannot find the showtime skill folder (recorded in $rec). Reinstall or update showtime in your agent, then run its bin\\showtime.cmd doctor."
    exit 127
}
$prevHome = $env:SHOWTIME_HOME
if (-not $env:SHOWTIME_HOME) { $env:SHOWTIME_HOME = $stHome }
try {
    & (Join-Path $skill 'bin/showtime.cmd') @args
    $code = $LASTEXITCODE
} finally {
    $env:SHOWTIME_HOME = $prevHome
}
exit $code
""" % {"mark": MARK, "pats": pats}


def texts() -> Dict[str, Tuple[str, Optional[str]]]:
    """{file name: (content, newline mode for open())} for this OS."""
    out = {"showtime": (_sh_text(), "\n")}
    if os.name == "nt":
        out["showtime.cmd"] = (_cmd_text(), "")
        out["showtime.ps1"] = (_ps1_text(), "\r\n")
    return out


def status(home: Path) -> Dict[str, object]:
    """What is installed: {ok, missing, outdated, skill, skill_ok, on_path, shim}."""
    home = Path(home)
    missing, outdated = [], []
    for name, (text, nl) in texts().items():
        f = home / "bin" / name
        try:
            cur = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            missing.append(name)
            continue
        if cur.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
            outdated.append(name)
        elif os.name != "nt" and name == "showtime" and not os.access(str(f), os.X_OK):
            outdated.append(name)
    rec = recorded_skill(home)
    skill_ok = valid_skill(rec)
    cached = skill_ok and is_ephemeral(rec)
    return {"shim": str(shim_path(home)), "missing": missing, "outdated": outdated,
            "skill": str(rec) if rec else None, "skill_ok": skill_ok, "ephemeral": cached, "on_path": on_path(home),
            "ok": not missing and not outdated and skill_ok and not cached}


def install(home: Path, skill: Path) -> Tuple[str, str]:
    """Write (or rewrite) the launchers and record `skill`. ("ok"|"fail", detail); never raises."""
    home = Path(home)
    try:
        default = Path(os.path.expanduser("~")) / ".showtime"
        if not _same(home, default) and not (home / ".gitignore").exists():
            # a showtime folder inside a project (SHOWTIME_HOME=.showtime): keep its gigabytes out of git
            _write_atomic(home / ".gitignore", "# showtime's tools, models and caches (showtime setup)\n*\n")
        for name, (text, nl) in texts().items():
            _write_atomic(home / "bin" / name, text, newline=nl, mode=0o755 if name == "showtime" else None)
        _update_record(home, Path(skill))
        rec = recorded_skill(home)
    except OSError as e:
        return "fail", "could not write %s: %s" % (home / "bin", e)
    return "ok", "%s -> %s" % (shim_path(home), rec)


def repair(home: Path, skill: Path) -> Tuple[str, str]:
    """Doctor's fix: rewrite missing/outdated launchers and a dead record. ("ok"|"installed"|"repaired"|"fail", detail)."""
    st = status(home)
    if st["ok"]:
        return "ok", "%s -> %s" % (st["shim"], st["skill"])
    what = []
    if len(st["missing"]) == len(texts()):
        code, detail = install(home, skill)
        return ("installed", detail) if code == "ok" else (code, detail)
    if st["missing"]:
        what.append("wrote " + ", ".join(st["missing"]))
    if st["outdated"]:
        what.append("updated " + ", ".join(st["outdated"]))
    if not st["skill_ok"]:
        what.append("now points at %s" % skill if st["skill"] is None else
                    "%s was gone, now points at %s" % (st["skill"], skill))
    if st["ephemeral"]:
        what.append("%s is in npm's cache, which npm cleans: kept a copy in %s" % (st["skill"], Path(home) / COPY_NAME))
    code, detail = install(home, skill)
    if code != "ok":
        return code, detail
    return "repaired", "%s (%s)" % (shim_path(home), "; ".join(what))


# --------------------------------------------------------------------------- PATH advice (never applied)

def user_path() -> str:
    """PATH as the user has it: the launcher puts <home>/bin in front for its own children."""
    return os.environ.get("SHOWTIME_USER_PATH", os.environ.get("PATH", ""))


def _path_dirs() -> List[str]:
    return [os.path.normcase(os.path.abspath(p)) for p in user_path().split(os.pathsep) if p]


def on_path(home: Path) -> bool:
    """True when `showtime` on the user's PATH is this home's launcher (directly or through a link)."""
    import shutil
    found = shutil.which("showtime", path=user_path() or None)
    if not found:
        return False
    try:
        return _same(Path(found).resolve(), shim_path(home).resolve()) or \
            os.path.normcase(os.path.abspath(str(Path(found).parent))) == \
            os.path.normcase(os.path.abspath(str(Path(home) / "bin")))
    except OSError:
        return False


def path_hint(home: Path) -> List[str]:
    """Lines telling the user how to call `showtime` from anywhere (empty when it already works)."""
    home = Path(home)
    if on_path(home):
        return []
    shim = shim_path(home)
    if os.name == "nt":
        bin_dir = str(home / "bin")
        return [
            "`showtime` is not on PATH yet. The full path always works: %s" % shim,
            "  to type just `showtime` in new terminals, run this once in PowerShell (showtime never edits it for you):",
            "    [Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') "
            "+ ';%s', 'User')" % bin_dir,
        ]
    local_bin = Path(os.path.expanduser("~")) / ".local" / "bin"
    lines = ["`showtime` is not on PATH yet. The full path always works: %s" % shim]
    if os.path.normcase(str(local_bin)) in _path_dirs():
        lines.append("  to type just `showtime`, link it into ~/.local/bin (already on your PATH):")
        lines.append("    ln -sf '%s' ~/.local/bin/showtime" % shim)
        return lines
    shell = os.path.basename(os.environ.get("SHELL", ""))
    rc = {"zsh": "~/.zshrc", "bash": "~/.bash_profile" if sys.platform == "darwin" else "~/.bashrc"}.get(shell)
    bin_dir = str(home / "bin").replace(os.path.expanduser("~"), "$HOME", 1)
    lines.append("  to type just `showtime` in new terminals, add its folder to PATH (showtime never edits your "
                 "shell files):")
    if shell == "fish":
        lines.append("    fish_add_path '%s'" % (home / "bin"))
    else:
        lines.append("    echo 'export PATH=\"%s:$PATH\"' >> %s" % (bin_dir, rc or "~/.profile"))
    lines.append("  (that folder also holds showtime's own ffmpeg and ffprobe; to add only `showtime`, link it into a "
                 "folder already on PATH: ln -sf '%s' <folder>/showtime)" % shim)
    return lines
