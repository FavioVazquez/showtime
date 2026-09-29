#!/usr/bin/env python3
"""Set up and audit the benchmark arms (isolated config dirs, isolated HOMEs, tool prefixes).

    python benchmarks/harness/arms.py setup  [--arms baseline,showtime] [--force]
    python benchmarks/harness/arms.py audit  [--arms ...]     # what each arm's session really loads
    python benchmarks/harness/arms.py auth                    # is a headless credential available?
    python benchmarks/harness/arms.py show

Layout under the benchmark home (never the repository, never ~/.claude):
    arms/<arm>/cfg-template/   CLAUDE_CONFIG_DIR template; each run gets a fresh copy
    arms/<arm>/home/           HOME for that arm (npm/uv/browser caches live here)
    arms/<arm>/prefix/         arm-only tools put first on PATH (a CLI, a Python venv)
    arms/<arm>/manifest.json   what was installed, with digests, for the report
    toolbin/                   ffmpeg + ffprobe shared by every arm (the same binaries)

Authentication for headless runs: CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) or
ANTHROPIC_API_KEY in the environment, or a token file named by BENCH_OAUTH_TOKEN_FILE
(default <bench home>/oauth-token, mode 600). The value is passed to the child process only.
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SYSTEM_DIRS = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"] if os.name != "nt" else []
PASS_ENV = ["USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "SHELL", "SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR"]
# Skills that ship inside Claude Code itself: present in every arm, never counted as "the arm's skill".
VIDEO_WORDS = ("video", "motion", "render", "caption", "footage", "animation", "showtime", "sting")


def arm_dir(arm_id: str) -> Path:
    """Opaque folder name so paths an agent might print (HOME, TMPDIR) do not reveal the arm."""
    return common.bench_home() / "arms" / common.opaque(arm_id)


def toolbin() -> Path:
    d = common.bench_home() / "toolbin"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        src = Path(common.ffmpeg(name))
        dst = d / src.name
        if dst.is_symlink() or dst.exists():
            if dst.resolve() == src.resolve():
                continue
            dst.unlink()
        try:
            dst.symlink_to(src)
        except FileExistsError:  # another run created it a moment ago
            continue
        except OSError:
            shutil.copy2(src, dst)
    return d


def base_path_dirs(tools: List[str]) -> List[str]:
    """Directories for the shared tools. BENCH_PATH_DIRS (os.pathsep list) overrides the lookup."""
    env = os.environ.get("BENCH_PATH_DIRS")
    if env:
        dirs = [d for d in env.split(os.pathsep) if d]
    else:
        dirs = []
        for t in tools:
            if t in ("ffmpeg", "ffprobe"):
                continue
            w = shutil.which(t)
            if w and str(Path(w).parent) not in dirs:
                dirs.append(str(Path(w).parent))
    return [str(toolbin())] + dirs + [d for d in SYSTEM_DIRS if d not in dirs]


def auth_env() -> Dict[str, str]:
    """Headless credential for the child process (never printed or written to a run folder)."""
    out = {}
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        out["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    else:
        tf = Path(os.environ.get("BENCH_OAUTH_TOKEN_FILE") or common.bench_home() / "oauth-token").expanduser()
        if tf.exists():
            mode = tf.stat().st_mode
            if os.name != "nt" and mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise SystemExit("%s is readable by others. FIX: chmod 600 %s" % (tf, tf))
            tok = tf.read_text(encoding="utf-8").strip()
            if tok:
                out["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    if os.environ.get("ANTHROPIC_API_KEY"):
        out["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    return out


def build_env(arm: Dict, common_cfg: Dict, cfg_dir: Path, tmp_dir: Path) -> Dict[str, str]:
    """A from-scratch environment: nothing from the operator's shell leaks in except locale/user basics."""
    d = arm_dir(arm["id"])
    manifest = common.read_json(d / "manifest.json", {}) or {}
    prefix = [p for p in manifest.get("path_prefix", []) if p]
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.update({
        "HOME": str(d / "home"),
        "PATH": os.pathsep.join(prefix + base_path_dirs(common_cfg["tools_on_path"])),
        "TMPDIR": str(tmp_dir),
        "CLAUDE_CONFIG_DIR": str(cfg_dir),
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
        "DISABLE_AUTOUPDATER": "1",
        "DO_NOT_TRACK": "1",
        "NO_UPDATE_NOTIFIER": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    if os.name == "nt":
        env["USERPROFILE"] = env["HOME"]
    env.update(manifest.get("env", {}))
    env.update(auth_env())
    return env


def claude_args(arm: Dict, common_cfg: Dict, prompt: str, budget_usd: float,
                model: Optional[str] = None, effort: Optional[str] = None, resume: Optional[str] = None) -> List[str]:
    args = [common.claude_bin(), "-p", prompt,
            "--model", model or common_cfg["model"],
            "--effort", effort or common_cfg["effort"],
            "--output-format", "stream-json", "--verbose",
            "--dangerously-skip-permissions",
            "--no-chrome",
            "--max-budget-usd", "%.2f" % budget_usd]
    if common_cfg.get("disallowed_tools"):
        args += ["--disallowedTools", " ".join(common_cfg["disallowed_tools"])]
    if arm["kind"] == "plugin":
        manifest = common.read_json(arm_dir(arm["id"]) / "manifest.json", {}) or {}
        args += ["--plugin-dir", manifest.get("plugin_dir") or str(common.REPO)]
    if resume:
        args += ["--resume", resume]
    return args


# ---------------------------------------------------------------- setup

def _copy_skill(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False,
                    ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".venv", "*.pyc"))


def snapshot_plugin(dst: Path, exclude: set) -> Path:
    """Frozen copy of the plugin as it would ship (git's file list), WITHOUT this benchmark folder, so the
    plugin arm cannot read the tasks' rubrics or the scoring. Real copies, except hard links for large example renders."""
    r = common.run(["git", "-C", str(common.REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    rels = [x for x in r.stdout.split("\0") if x] if r.returncode == 0 else []
    if not rels:
        raise SystemExit("cannot list the plugin's files with git (needed for the snapshot)")
    skip = {"benchmarks"} | set(exclude)
    if dst.exists():
        shutil.rmtree(dst)
    for rel in rels:
        parts = rel.split("/")
        if parts[0] in skip or set(parts) & common.SKIP_DIRS:
            continue
        src, out = common.REPO / rel, dst / rel
        if not src.is_file():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        big_media = parts[0] == "examples" and src.stat().st_size > 1_000_000
        try:
            if not big_media:
                raise OSError("copy")  # real copies, so an agent editing the snapshot never touches the repo
            os.link(src, out)  # large example renders only; read-only for the run in practice
        except OSError:
            shutil.copy2(src, out)
        if os.access(src, os.X_OK):
            out.chmod(src.stat().st_mode)
    return dst


OWN_ENTRIES = {"bin", "skill-path", "skill"}


def overlay_home(shared: Path, dst: Path, skill: Path) -> Path:
    """The arm's showtime home: every entry of the operator's home (tools, models, caches) linked in, but
    its own bin/ and skill-path, so `<home>/bin/showtime` runs THIS snapshot. A plain link to the shared
    home let the command run whatever skill another worker's launcher last recorded there (round 3 ran
    two tasks on another branch's code that way)."""
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for e in sorted(shared.iterdir()):
        if e.name in OWN_ENTRIES:
            continue
        (dst / e.name).symlink_to(e, target_is_directory=e.is_dir())
    (dst / "bin").mkdir()
    if (shared / "bin").is_dir():
        for e in sorted((shared / "bin").iterdir()):
            if e.name.split(".")[0] != "showtime":
                (dst / "bin" / e.name).symlink_to(e.resolve())
    import importlib.util
    spec = importlib.util.spec_from_file_location("_arm_shim", str(skill / "lib" / "st" / "shim.py"))
    shim = importlib.util.module_from_spec(spec)   # the snapshot's own code (stdlib only)
    spec.loader.exec_module(shim)
    code, detail = shim.install(dst, skill)
    if code != "ok":
        raise SystemExit("could not write the arm's showtime command: %s" % detail)
    return dst


def setup_arm(arm: Dict, common_cfg: Dict, force: bool = False) -> Dict:
    d = arm_dir(arm["id"])
    if force and d.exists():
        shutil.rmtree(d)
    cfg = d / "cfg-template"
    home = d / "home"
    prefix = d / "prefix"
    for p in (cfg / "skills", home, prefix):
        p.mkdir(parents=True, exist_ok=True)
    (home / ".gitconfig").write_text("[user]\n\tname = bench\n\temail = bench@example.invalid\n"
                                     "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    manifest = {"arm": arm["id"], "kind": arm["kind"], "created": common.now_iso(), "path_prefix": [], "env": {},
                "skills": [], "notes": []}
    local = arm.get("local") or {}
    if arm["kind"] == "skills" and not local:
        raise SystemExit("arm %s needs an entry in %s (see README > Arms)" % (arm["id"], common.local_arms_file()))

    if arm["kind"] == "plugin":
        snap = snapshot_plugin(prefix / "plugin", set(arm.get("snapshot_exclude", [])))
        manifest["plugin_dir"] = str(snap)
        manifest["plugin_files"] = sum(1 for p in snap.rglob("*") if p.is_file())
        overlay_home(common.showtime_home(), home / ".showtime", snap / "skills" / "showtime")
        manifest["plugin_dir_digest"] = common.tree_digest(snap / "skills")
        manifest["notes"].append("runtime home: the operator's showtime home linked read-write entry by entry, "
                                 "with the arm's own `showtime` command (bin/showtime -> this snapshot)")

    if arm["kind"] == "skills":
        src = Path(local["path"]).expanduser()
        sk = local.get("skills", {})
        if sk.get("include"):
            for name in sk["include"]:
                _copy_skill(src / sk.get("dir", "skills") / name, cfg / "skills" / name)
                manifest["skills"].append(name)
        else:
            name = sk.get("as_skill_dir") or src.name
            _copy_skill(src, cfg / "skills" / name)
            manifest["skills"].append(name)
        manifest["skills_digest"] = common.tree_digest(cfg / "skills")
        cli = local.get("cli")
        if cli:
            cli_dir = prefix / "cli"
            cli_dir.mkdir(exist_ok=True)
            env = build_env(arm, common_cfg, cfg, d)  # HOME = the arm's home: npm cache stays isolated
            r = common.run(["npm", "install", "--no-audit", "--no-fund", "--prefix", str(cli_dir), cli["npm"]], env=env)
            if r.returncode != 0:
                raise SystemExit("npm install %s failed:\n%s" % (cli["npm"], r.stderr[-2000:]))
            manifest["path_prefix"].append(str(cli_dir / "node_modules" / ".bin"))
            manifest["cli"] = cli["npm"]
        py = local.get("python")
        if py:
            venv = prefix / "venv"
            r = common.run(["uv", "venv", "--python", py["version"], str(venv)])
            if r.returncode != 0:
                raise SystemExit("uv venv failed: %s" % r.stderr[-1000:])
            vpy = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            r = common.run(["uv", "pip", "install", "--python", str(vpy)] + py["requirements"])
            if r.returncode != 0:
                raise SystemExit("uv pip install failed: %s" % r.stderr[-1000:])
            manifest["path_prefix"].append(str(vpy.parent))
            manifest["python"] = py
        for w in local.get("warmup", []):
            common.write_json(d / "manifest.json", manifest)
            r = common.run(w, env=build_env(arm, common_cfg, cfg, d), cwd=str(d))
            manifest["notes"].append("warmup %s -> exit %d" % (" ".join(w), r.returncode))
    common.write_json(d / "manifest.json", manifest)
    return manifest


# ---------------------------------------------------------------- audit

def session_init(arm: Dict, common_cfg: Dict, prompt: str = "Reply with the single word ok.") -> Dict:
    """Start one headless session for the arm and return its init message + result (auth status)."""
    d = arm_dir(arm["id"])
    work = common.ws_root() / ("audit-" + common.opaque(arm["id"]))
    if work.exists():
        shutil.rmtree(work)
    cfg = work / "cfg"
    shutil.copytree(d / "cfg-template", cfg)
    (work / "proj").mkdir(parents=True)
    (work / "tmp").mkdir()
    env = build_env(arm, common_cfg, cfg, work / "tmp")
    r = subprocess.run(claude_args(arm, common_cfg, prompt, 0.25), cwd=str(work / "proj"), env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    init, result = {}, {}
    for line in r.stdout.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("type") == "system" and m.get("subtype") == "init":
            init = m
        elif m.get("type") == "result":
            result = m
    return {"init": init, "result": result, "stderr": r.stderr[-800:]}


def videoish_all(init: Dict) -> List[str]:
    return [s for s in init.get("skills") or [] if any(w in s.lower() for w in VIDEO_WORDS)]


def audit(arms: List[Dict], common_cfg: Dict) -> Dict:
    report = {"created": common.now_iso(), "arms": {}}
    builtin = None
    raw = {}
    ids = [a["id"] for a in arms]
    if "baseline" not in ids:  # the baseline session defines what Claude Code itself ships
        arms = common.load_arms(["baseline"])["arms"] + list(arms)
    for arm in arms:
        raw[arm["id"]] = session_init(arm, common_cfg)
    base = raw.get("baseline", {}).get("init") or {}
    builtin = set(base.get("skills") or [])
    for arm in arms:
        v = raw[arm["id"]]
        init, res = v["init"], v["result"]
        skills = sorted(set(init.get("skills") or []) - builtin)
        entry = {
            "model": init.get("model"), "permission_mode": init.get("permissionMode"),
            "version": init.get("claude_code_version"),
            "arm_skills": skills,
            "plugins": [p.get("name") for p in init.get("plugins") or [] if p.get("path") != "builtin"],
            "mcp_servers": init.get("mcp_servers"),
            "arm_agents": [a for a in init.get("agents") or [] if ":" in a],
            "auth_ok": bool(res) and not res.get("is_error"),
            "result": (res.get("result") or "")[:200],
            "problems": [],
        }
        videoish = [s for s in skills if any(w in s.lower() for w in VIDEO_WORDS)]
        if arm["kind"] == "baseline" and (videoish_all(base) or entry["plugins"]):
            entry["problems"].append("baseline loads video skills/plugins: %s %s" % (videoish_all(base), entry["plugins"]))
        if arm["kind"] == "plugin" and not any(s.startswith("showtime:") for s in skills):
            entry["problems"].append("plugin skill not loaded")
        if arm["kind"] == "skills" and not skills:
            entry["problems"].append("arm skills not loaded")
        if not entry["auth_ok"]:
            entry["problems"].append("no headless credential: %s" % entry["result"])
        entry["video_skills"] = videoish
        report["arms"][arm["id"]] = entry
    report["builtin_skills"] = sorted(builtin)
    common.write_json(common.bench_home() / "audit" / "audit.json", report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["setup", "audit", "auth", "show"])
    ap.add_argument("--arms", help="comma list of arm ids (default: all)")
    ap.add_argument("--force", action="store_true", help="setup: rebuild the arm from scratch")
    a = ap.parse_args()
    cfg = common.load_arms(a.arms.split(",") if a.arms else None)
    if a.command == "setup":
        for arm in cfg["arms"]:
            common.log("setting up %s" % arm["id"])
            m = setup_arm(arm, cfg["common"], a.force)
            print("%-9s ok  skills=%s prefix=%d" % (arm["id"], m.get("skills"), len(m["path_prefix"])))
    elif a.command == "auth":
        has = auth_env()
        print("headless credential: %s" % (", ".join(sorted(has)) if has else "NONE"))
        if not has:
            print("FIX: run `claude setup-token` yourself, save the token to %s (chmod 600) or export "
                  "CLAUDE_CODE_OAUTH_TOKEN; or export ANTHROPIC_API_KEY." % (common.bench_home() / "oauth-token"))
            return 1
    elif a.command == "audit":
        rep = audit(cfg["arms"], cfg["common"])
        for k, v in rep["arms"].items():
            print("%-9s auth=%s skills=%s plugins=%s mcp=%s %s" % (
                k, "ok" if v["auth_ok"] else "NO", v["arm_skills"], v["plugins"],
                [m.get("name") + ":" + str(m.get("status")) for m in v["mcp_servers"] or []],
                ("PROBLEMS: " + "; ".join(v["problems"])) if v["problems"] else ""))
        print("built-in skills in every arm: %s" % ", ".join(rep["builtin_skills"]))
    else:
        print(json.dumps({"common": cfg["common"], "arms": [{k: v for k, v in x.items() if k != "local"}
                                                            for x in cfg["arms"]]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
