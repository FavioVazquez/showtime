#!/usr/bin/env python3
"""showtime outside Claude Code: skill paths, the stable command, background runs, heartbeat, sandboxes.

  * SKILL.md and the crew agents: paths relative to the skill folder, a `compatibility:` line, no
    command built from ${CLAUDE_SKILL_DIR} / ${CLAUDE_PLUGIN_ROOT} (an unexpanded one becomes
    /bin/showtime); the documented command runs with CLAUDE_SKILL_DIR and CLAUDE_PLUGIN_ROOT unset;
  * <home>/bin/showtime (st.shim): runs the recorded skill, sets its own home, works through a link,
    finds a moved skill in the usual folders, follows the newest version, `showtime doctor` repairs it,
    PATH advice never edits a shell file;
  * --background and `showtime status <run>` (st.runs): run ids, --wait (75 while running), --cancel,
    --runs, --json, a failing command, a supervisor that died ("lost");
  * the heartbeat (a "still running" line when stderr is not a terminal) and when it stays off;
  * SHOWTIME_HOME as the escape hatch: relative values, a project's `.showtime` found without any
    variable, unexpanded placeholders, uv/npm caches moved in when their folders are read-only;
  * `showtime doctor` in a sandbox: read-only home, no network, a read-only work folder, and the
    host-specific fix (Codex, Cursor, generic).

Stdlib only, no setup needed, no network except doctor's own probe (pointed at a closed local port).
usage: python tests/test_portable.py [--fast] [-v]   (about 20-40 s)
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import __version__, runs, sandbox, shim  # noqa: E402
from st import launcher as L  # noqa: E402

IS_WIN = os.name == "nt"
POSIX_ONLY = unittest.skipIf(IS_WIN, "POSIX shell shim")
NOT_ROOT = unittest.skipIf(not IS_WIN and os.geteuid() == 0, "root ignores file permissions")
HOST_VARS = ("CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def clean_env(**extra) -> dict:
    """No host variables, no showtime variables: what another agent's shell looks like."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SHOWTIME_", "CODEX_", "CURSOR_", "COPILOT_", "GEMINI_", "DEVIN_", "ANTIGRAVITY"))
           and k not in HOST_VARS}
    env.update({k: str(v) for k, v in extra.items()})
    if "HOME" in extra:
        # Windows: Python's expanduser and Node's os.homedir() read USERPROFILE (then HOMEDRIVE+HOMEPATH),
        # never HOME: a fake home folder has to be all of them
        if "USERPROFILE" not in extra:
            env["USERPROFILE"] = str(extra["HOME"])
        if IS_WIN:
            drive, rest = os.path.splitdrive(str(extra["HOME"]))
            env["HOMEDRIVE"], env["HOMEPATH"] = drive, rest
    return env


def run(cmd, env=None, cwd=None, timeout=120):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                          errors="replace", env=env if env is not None else clean_env(), cwd=str(cwd) if cwd else None,
                          timeout=timeout)


def launcher(*args, env=None, cwd=None, timeout=120):
    return run([sys.executable, LAUNCHER] + list(args), env=env, cwd=cwd, timeout=timeout)


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-port-")).resolve()

    def tearDown(self):
        for p in self.tmp.rglob("*"):   # read-only folders made by a test
            try:
                if p.is_dir():
                    os.chmod(str(p), 0o755)
            except OSError:
                pass
        shutil.rmtree(str(self.tmp), ignore_errors=True)


# ============================================================================ SKILL.md and agents

class TestSkillDoc(Tmp):
    def text(self):
        return (SKILL / "SKILL.md").read_text(encoding="utf-8")

    def test_compatibility_and_relative_paths(self):
        text = self.text()
        front = text.split("---", 2)[1]
        m = re.search(r"^compatibility:\s*(.+)$", front, re.M)
        self.assertTrue(m, "SKILL.md frontmatter needs a compatibility: line (Agent Skills spec)")
        self.assertLessEqual(len(m.group(1).strip()), 500)
        self.assertIn("relative to the folder holding this SKILL.md", text)
        self.assertIn('"<folder>/bin/showtime" <cmd>', text)
        self.assertIn("`${CLAUDE_SKILL_DIR}`", text)   # kept, as the Claude Code form of the folder

    def test_no_command_is_built_from_a_host_variable(self):
        """"${CLAUDE_SKILL_DIR}/bin/showtime" in a shell without the variable is /bin/showtime."""
        bad = re.compile(r"\$\{(CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT)\}[^`\s\"']*bin[/\\]")
        docs = [SKILL / "SKILL.md"] + sorted((SKILL / "references").rglob("*.md")) + sorted((REPO / "agents").glob("*.md"))
        for doc in docs:
            hits = bad.findall(doc.read_text(encoding="utf-8"))
            self.assertFalse(hits, "%s builds a command path from a host variable" % doc.name)

    def documented_command(self, text: str, folder: Path) -> list:
        """The skill's documented launcher call, as an agent without CLAUDE_SKILL_DIR writes it."""
        if IS_WIN:
            m = re.search(r'`& "<folder>\\bin\\showtime\.cmd"`', text)
            self.assertTrue(m)
            return ["cmd", "/c", str(folder / "bin" / "showtime.cmd")]
        m = re.search(r'`"<folder>/bin/showtime" <cmd>`', text)
        self.assertTrue(m)
        return ["sh", "-c", '"%s/bin/showtime" "$@"' % folder, "sh"]

    def test_documented_command_runs_without_claude_variables(self):
        env = clean_env(SHOWTIME_HOME=self.tmp / "home")
        for k in HOST_VARS:
            self.assertNotIn(k, env)
        cp = run(self.documented_command(self.text(), SKILL) + ["version"], env=env, cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stdout.strip(), "showtime %s" % __version__)
        if not IS_WIN:
            # the naive copy of the old form fails; the new text never offers it
            cp = run(["sh", "-c", '"${CLAUDE_SKILL_DIR}/bin/showtime" version'], env=env, cwd=self.tmp)
            self.assertNotEqual(cp.returncode, 0)
            self.assertNotIn('"${CLAUDE_SKILL_DIR}/bin/showtime"', self.text())

    def test_agents_run_without_plugin_root(self):
        for f in sorted((REPO / "agents").glob("*.md")):
            body = f.read_text(encoding="utf-8")
            self.assertIn("references/crew/rules.md", body, f.name)
            self.assertIn("references/crew/%s.md" % f.stem, body, f.name)
            self.assertIn("`Skill:` line", body, f.name)
            if "Bash" in body.split("---")[1]:
                self.assertIn('"<skill folder>/bin/showtime"', body, f.name)
        # the folder an agent is pointed at: TASK.md's Skill: line (crew.md) and CRITIC.md's (review pack)
        self.assertIn("Skill: <absolute skill folder>", (SKILL / "references" / "crew.md").read_text(encoding="utf-8"))
        from st.qa import review
        self.assertEqual(Path(review._skill_dir()).resolve(), SKILL.resolve())  # noqa: SLF001


# ============================================================================ the stable command

@POSIX_ONLY
class TestShim(Tmp):
    def install(self, home: Path, skill: Path = SKILL):
        code, detail = shim.install(home, skill)
        self.assertEqual(code, "ok", detail)
        return home / "bin" / "showtime"

    def fake_home(self) -> Path:
        h = self.tmp / "user"
        h.mkdir(exist_ok=True)
        return h

    def copy_skill(self, dest: Path, version: str = None) -> Path:
        dest.mkdir(parents=True)
        for part in ("bin", "lib"):
            shutil.copytree(str(SKILL / part), str(dest / part),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if version:
            init = dest / "lib" / "st" / "__init__.py"
            init.write_text(re.sub(r'__version__ = "[^"]+"', '__version__ = "%s"' % version,
                                   init.read_text(encoding="utf-8")), encoding="utf-8")
        return dest

    def test_runs_the_recorded_skill_with_its_own_home(self):
        home = self.tmp / "st home"   # a space on purpose
        cmd = self.install(home)
        self.assertTrue(os.access(str(cmd), os.X_OK))
        self.assertEqual(shim.recorded_skill(home).resolve(), SKILL.resolve())
        self.assertTrue(shim.status(home)["ok"])
        env = clean_env(HOME=self.fake_home())
        cp = run([cmd, "version", "--json"], env=env, cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        info = json.loads(cp.stdout)
        self.assertEqual(Path(info["home"]).resolve(), home.resolve(), "the shim sets SHOWTIME_HOME to its own home")
        self.assertEqual(Path(info["skill"]).resolve(), SKILL.resolve())
        # through a link in another folder (ln -s <shim> ~/.local/bin/showtime)
        link_dir = self.tmp / "links"
        link_dir.mkdir()
        os.symlink(str(cmd), str(link_dir / "showtime"))
        cp = run([link_dir / "showtime", "version"], env=env, cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stdout.strip(), "showtime %s" % __version__)
        # an explicit SHOWTIME_HOME wins over the shim's own
        other = self.tmp / "other"
        cp = run([cmd, "version", "--json"], env=clean_env(HOME=self.fake_home(), SHOWTIME_HOME=other), cwd=self.tmp)
        self.assertEqual(Path(json.loads(cp.stdout)["home"]).resolve(), other.resolve())
        # a non-default home keeps itself out of git
        self.assertEqual((home / ".gitignore").read_text(encoding="utf-8").splitlines()[-1], "*")

    def test_finds_a_moved_skill_and_rerecords_it(self):
        user = self.fake_home()
        moved = self.copy_skill(user / ".claude" / "plugins" / "cache" / "mk" / "showtime" / "0.9.9" / "skills" / "showtime")
        home = self.tmp / "home"
        cmd = self.install(home)
        shim.record(home, self.tmp / "gone" / "skills" / "showtime")   # the old plugin version was removed
        cp = run([cmd, "version", "--json"], env=clean_env(HOME=user), cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(Path(json.loads(cp.stdout)["skill"]).resolve(), moved.resolve())
        self.assertEqual(shim.recorded_skill(home).resolve(), moved.resolve(), "the launcher repairs skill-path")
        # nothing anywhere: a clear error, never a traceback
        shutil.rmtree(str(user / ".claude"))
        shim.record(home, self.tmp / "gone")
        cp = run([cmd, "version"], env=clean_env(HOME=user), cwd=self.tmp)
        self.assertEqual(cp.returncode, 127)
        self.assertIn("cannot find the showtime skill folder", cp.stderr)

    def test_newest_skill_wins(self):
        home = self.tmp / "home"
        self.install(home)
        newer = self.copy_skill(self.tmp / "newer" / "showtime", version="9.9.9")
        env = clean_env(HOME=self.fake_home(), SHOWTIME_HOME=home)
        cp = run([sys.executable, newer / "lib" / "st" / "launcher.py", "version"], env=env, cwd=self.tmp)
        self.assertEqual(cp.stdout.strip(), "showtime 9.9.9", cp.stderr)
        self.assertEqual(shim.recorded_skill(home).resolve(), newer.resolve())
        launcher("version", env=env, cwd=self.tmp)   # an older skill running does not take it back
        self.assertEqual(shim.recorded_skill(home).resolve(), newer.resolve())
        cp = run([home / "bin" / "showtime", "version"], env=clean_env(HOME=self.fake_home()), cwd=self.tmp)
        self.assertEqual(cp.stdout.strip(), "showtime 9.9.9")

    def test_same_version_follows_the_running_skill(self):
        """Two folders of the same version (a plugin and a checkout, two hosts sharing one home) can hold
        different code: the command runs the one used last, never a stale one another host recorded."""
        home = self.tmp / "home-tie"
        self.install(home)
        other = self.copy_skill(self.tmp / "other-host" / "showtime")
        env = clean_env(HOME=self.fake_home(), SHOWTIME_HOME=home)
        run([sys.executable, other / "lib" / "st" / "launcher.py", "version"], env=env, cwd=self.tmp)
        self.assertEqual(shim.recorded_skill(home).resolve(), other.resolve())
        launcher("version", env=env, cwd=self.tmp)   # this skill runs: the command follows it back
        self.assertEqual(shim.recorded_skill(home).resolve(), SKILL.resolve())

    def test_skill_in_npm_cache_is_kept_as_a_copy(self):
        """npx runs the npm package from npm's cache, which npm prunes: the command must not depend on it."""
        user = self.fake_home()
        npx = self.copy_skill(user / ".npm" / "_npx" / "3f2a9c" / "node_modules" / "@faviovazquez" / "showtime-mcp" / "skill")
        self.assertTrue(shim.is_ephemeral(npx))
        self.assertFalse(shim.is_ephemeral(SKILL))
        home = self.tmp / "home"
        self.install(home, npx)                       # setup run through npx
        kept = home / "skill"
        self.assertEqual(shim.recorded_skill(home), kept)
        self.assertTrue(shim.valid_skill(kept))
        self.assertFalse((kept / "tests").exists())
        shutil.rmtree(str(user / ".npm"))             # npm cleans its cache
        cp = run([home / "bin" / "showtime", "version", "--json"], env=clean_env(HOME=user), cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(Path(json.loads(cp.stdout)["skill"]).resolve(), kept.resolve())
        # a newer version through npx refreshes the copy (the record stays <home>/skill)
        npx2 = self.copy_skill(user / ".npm" / "_npx" / "9d1e" / "node_modules" / "@faviovazquez" / "showtime-mcp" / "skill",
                               version="9.9.9")
        env = clean_env(HOME=user, SHOWTIME_HOME=home)
        cp = run([sys.executable, npx2 / "lib" / "st" / "launcher.py", "version"], env=env, cwd=self.tmp)
        self.assertEqual(cp.stdout.strip(), "showtime 9.9.9", cp.stderr)
        self.assertEqual(shim.recorded_skill(home), kept)
        self.assertEqual(shim.skill_version(kept), (9, 9, 9))
        # a record an older showtime left pointing into the cache: the next run (or doctor) keeps a copy instead
        shutil.rmtree(str(kept))
        shim.record(home, npx2)
        self.assertFalse(shim.status(home)["ok"])
        code, detail = shim.repair(home, SKILL)
        self.assertEqual(code, "repaired")
        self.assertIn("npm's cache", detail)
        self.assertEqual(shim.recorded_skill(home), kept)
        self.assertEqual(shim.skill_version(kept), (9, 9, 9), "the newer cached one is what gets kept")
        shutil.rmtree(str(kept))
        shim.record(home, npx2)
        cp = launcher("doctor", "--quick", "--json", env=clean_env(HOME=user, SHOWTIME_HOME=home, SHOWTIME_OFFLINE="1"),
                      cwd=self.tmp, timeout=300)
        row = {r["check"]: r for r in json.loads(cp.stdout)["checks"]}["showtime command"]
        # repaired (by the launcher's first run), and a warning that the command runs the newer kept copy
        # (9.9.9), not this skill
        self.assertEqual(row["status"], "warn", row)
        self.assertIn("showtime 9.9.9 at %s" % kept, row["detail"])
        self.assertEqual(shim.recorded_skill(home), kept)
        self.assertTrue(shim.status(home)["ok"])

    def test_no_shim_no_record(self):
        home = self.tmp / "home"
        launcher("version", env=clean_env(SHOWTIME_HOME=home), cwd=self.tmp)
        self.assertFalse((home / "skill-path").exists(), "only an installed command gets a record")

    def test_doctor_repairs_it(self):
        home = self.tmp / "home"
        cmd = self.install(home)
        cmd.write_text("#!/bin/sh\necho broken\n", encoding="utf-8")
        shim.record(home, self.tmp / "gone")
        env = clean_env(SHOWTIME_HOME=home, HOME=self.fake_home(), SHOWTIME_OFFLINE="1")
        cp = launcher("doctor", "--quick", "--json", env=env, cwd=self.tmp, timeout=300)
        rows = {r["check"]: r for r in json.loads(cp.stdout)["checks"]}
        row = rows["showtime command"]
        self.assertEqual(row["status"], "pass", row)
        self.assertIn("repaired", row["detail"])
        self.assertTrue(shim.status(home)["ok"])
        self.assertTrue(os.access(str(cmd), os.X_OK))
        self.assertEqual(run([cmd, "version"], env=clean_env(HOME=self.fake_home()), cwd=self.tmp).stdout.strip(),
                         "showtime %s" % __version__)
        self.assertIn("not on PATH", row.get("note", ""))
        # a home without the command: doctor installs it
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        cp = launcher("doctor", "--quick", "--json", env=dict(env, SHOWTIME_HOME=str(fresh)), cwd=self.tmp, timeout=300)
        row = {r["check"]: r for r in json.loads(cp.stdout)["checks"]}["showtime command"]
        self.assertTrue(row["detail"].startswith("installed: "), row)
        self.assertTrue((fresh / "bin" / "showtime").is_file())
        # a home setup never made: no command is written there
        none = self.tmp / "none"
        cp = launcher("doctor", "--quick", "--json", env=dict(env, SHOWTIME_HOME=str(none)), cwd=self.tmp, timeout=300)
        row = {r["check"]: r for r in json.loads(cp.stdout)["checks"]}["showtime command"]
        self.assertEqual(row["status"], "skip", row)
        self.assertFalse((none / "bin" / "showtime").exists())
        self.assertFalse((none / "skill-path").exists())

    def test_path_advice_edits_nothing(self):
        user = self.fake_home()
        home = self.tmp / "home"
        self.install(home)
        old = dict(os.environ)
        try:
            os.environ.update({"HOME": str(user), "SHELL": "/bin/zsh", "PATH": "/usr/bin:/bin"})
            os.environ.pop("SHOWTIME_USER_PATH", None)
            lines = shim.path_hint(home)
            self.assertTrue(any("export PATH=" in x and "~/.zshrc" in x for x in lines), lines)
            os.environ["PATH"] = "%s:/usr/bin:/bin" % (user / ".local" / "bin")
            lines = shim.path_hint(home)
            self.assertTrue(any("ln -sf" in x for x in lines), lines)
            os.environ["PATH"] = "%s:/usr/bin:/bin" % (home / "bin")
            self.assertEqual(shim.path_hint(home), [], "already on PATH: nothing to say")
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertEqual(sorted(p.name for p in user.iterdir()), [], "no shell file was written")


# ============================================================================ background runs

class TestBackground(Tmp):
    def env(self, **kw):
        return clean_env(SHOWTIME_HOME=self.tmp / "home", **kw)

    def test_background_then_status(self):
        cp = launcher("paths", "home", "--background", env=self.env(), cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        m = re.search(r"started in the background: (\S+)", cp.stdout)
        self.assertTrue(m, cp.stdout)
        rid = m.group(1)
        self.assertRegex(rid, runs.ID_RE)
        self.assertIn("showtime status %s" % rid, cp.stdout)
        cp = launcher("status", rid, "--wait", "60", env=self.env(), cwd=self.tmp)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("finished OK", cp.stdout)
        self.assertIn(str(self.tmp / "home"), cp.stdout, "the command's own output")
        cp = launcher("status", rid, "--json", env=self.env(), cwd=self.tmp)
        info = json.loads(cp.stdout)
        self.assertEqual((info["state"], info["exit_code"], info["command"]), ("done", 0, "showtime paths home"))
        self.assertEqual(Path(info["cwd"]).resolve(), self.tmp)
        cp = launcher("status", "--runs", env=self.env(), cwd=self.tmp)
        self.assertIn(rid, cp.stdout)
        # --json start (what the MCP server reads)
        cp = launcher("--background", "paths", "home", env=self.env(SHOWTIME_BACKGROUND_FORMAT="json"), cwd=self.tmp)
        started = json.loads(cp.stdout)
        self.assertTrue(Path(started["dir"], "run.json").is_file())
        self.assertEqual(started["status"], "showtime status %s" % started["id"])
        launcher("status", started["id"], "--wait", "60", env=self.env(), cwd=self.tmp)

    def test_failure_is_reported(self):
        cp = launcher("paths", "no-such-path", "--background", env=self.env(), cwd=self.tmp)
        rid = re.search(r"background: (\S+)", cp.stdout).group(1)
        cp = launcher("status", rid, "--wait", "60", env=self.env(), cwd=self.tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("FAILED", cp.stdout)
        self.assertIn("unknown path", cp.stdout)

    def test_running_wait_cancel_and_lost(self):
        os.environ["SHOWTIME_HOME"] = str(self.tmp / "home")
        try:
            prog = [sys.executable, "-c", "import sys, time\nprint('frames 3/30  10%  ETA 20 s', flush=True)\n"
                    "time.sleep(60)\n"]
            data = runs.start(["render", "x"], cwd=str(self.tmp), source="test", program=prog)
            rid = data["id"]
            self.assertTrue(rid.startswith("render-"))
            t_end = time.time() + 20
            while time.time() < t_end and "frames" not in runs.summary(runs.load(Path(data["dir"])))["latest"]:
                time.sleep(0.2)
        finally:
            os.environ.pop("SHOWTIME_HOME", None)
        cp = launcher("status", rid, env=self.env(), cwd=self.tmp)
        self.assertEqual(cp.returncode, 0)
        self.assertIn("running for", cp.stdout)
        self.assertIn("latest:  frames 3/30", cp.stdout)
        t0 = time.time()
        cp = launcher("status", rid, "--wait", "1.5", env=self.env(), cwd=self.tmp)
        self.assertEqual(cp.returncode, runs.STILL_RUNNING, cp.stdout)
        self.assertLess(time.time() - t0, 15)
        pid = runs.load(Path(data["dir"]))["pid"]
        cp = launcher("status", rid, "--cancel", env=self.env(), cwd=self.tmp, timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("cancelled", cp.stdout)
        time.sleep(0.5)
        self.assertFalse(runs.pid_alive(pid), "cancel stops the command")
        # a supervisor that died without writing an end
        d = Path(data["dir"])
        rec = json.loads((d / "run.json").read_text(encoding="utf-8"))
        rec.update(state="running", supervisor_pid=self.dead_pid())
        (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        cp = launcher("status", rid, env=self.env(), cwd=self.tmp)
        self.assertIn("lost", cp.stdout)

    def dead_pid(self) -> int:
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def test_unknown_run(self):
        cp = launcher("status", "render-20200101-000000-abcd", "--wait", "1", env=self.env(), cwd=self.tmp)
        self.assertNotEqual(cp.returncode, 0)

    def test_background_is_not_for_quick_builtins(self):
        cp = launcher("version", "--background", env=self.env(), cwd=self.tmp)
        self.assertEqual(cp.stdout.strip(), "showtime %s" % __version__)
        self.assertFalse((self.tmp / "home" / "runs").exists())


# ============================================================================ heartbeat

class TestHeartbeat(Tmp):
    @POSIX_ONLY
    def test_lines_while_the_command_runs_and_none_after(self):
        code = ("import os, sys; sys.path.insert(0, %r)\n"
                "from st.launcher import start_heartbeat\n"
                "start_heartbeat('render', 0.4)\n"
                "os.execv(%r, [%r, '-c', 'import time; time.sleep(1.5)'])\n" % (str(SKILL / "lib"), sys.executable,
                                                                               sys.executable))
        t0 = time.time()
        cp = run([sys.executable, "-c", code], env=clean_env(), cwd=self.tmp, timeout=60)
        took = time.time() - t0
        lines = [x for x in cp.stderr.splitlines() if "still running" in x]
        self.assertGreaterEqual(len(lines), 2, cp.stderr)
        self.assertTrue(all(x.startswith("showtime: render still running (") for x in lines), lines)
        self.assertLess(took, 1.5 + 1.2, "the watcher must not hold the pipe open after the command ends")

    def test_when_it_is_on(self):
        old = dict(os.environ)
        try:
            for k in ("SHOWTIME_HEARTBEAT", "SHOWTIME_MCP", "SHOWTIME_RUN_ID", "SHOWTIME_PROGRESS"):
                os.environ.pop(k, None)
            tty = sys.stderr.isatty()
            self.assertEqual(L.heartbeat_interval("render", []), 0.0 if tty else L.HEARTBEAT_DEFAULT)
            self.assertEqual(L.heartbeat_interval("version", []), 0.0)
            self.assertEqual(L.heartbeat_interval("status", []), 0.0)
            self.assertEqual(L.heartbeat_interval("render", ["--help"]), 0.0)
            os.environ["SHOWTIME_HEARTBEAT"] = "5"
            self.assertEqual(L.heartbeat_interval("render", []), 5.0)
            os.environ["SHOWTIME_MCP"] = "1"
            self.assertEqual(L.heartbeat_interval("render", []), 0.0, "the MCP server reports progress itself")
            del os.environ["SHOWTIME_MCP"]
            os.environ["SHOWTIME_HEARTBEAT"] = "0"
            self.assertEqual(L.heartbeat_interval("render", []), 0.0)
            os.environ["SHOWTIME_PROGRESS"] = "json"
            self.assertEqual(json.loads(L.heartbeat_line("transcribe", 90)), {"heartbeat": "transcribe", "seconds": 90})
            del os.environ["SHOWTIME_PROGRESS"]
            self.assertEqual(L.heartbeat_line("render", 125), "showtime: render still running (2 min 5 s)\n")
        finally:
            os.environ.clear()
            os.environ.update(old)


# ============================================================================ SHOWTIME_HOME

HOME_VARS = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SHOWTIME_HOME", "SHOWTIME_SETTINGS", "USERNAME",
             "SystemDrive")


class TestHome(Tmp):
    def home_of(self, env, cwd):
        cp = launcher("version", "--json", env=env, cwd=cwd)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.last = json.loads(cp.stdout)
        self.last_env = {k: env.get(k) for k in HOME_VARS if k in env}
        self.last_cwd = cwd
        return Path(self.last["home"])

    def assertHome(self, env, cwd, want, why=""):
        """The launcher's home, with everything that chose it in the message when it is not `want`."""
        got = self.home_of(env, cwd)
        if Path(os.path.normcase(str(got))) != Path(os.path.normcase(str(want))):
            self.fail("%s\n  got:  %s\n  want: %s\n  cwd:  %s\n  how:  %s\n  home folders the search stops at: %s\n"
                      "  env:  %s" % (why or "wrong home", got, want, cwd, self.last.get("home_source"),
                                      self.last.get("home_folders"), json.dumps(self.last_env, indent=None)))

    def test_relative_and_placeholder_values(self):
        user = self.tmp / "user"
        user.mkdir()
        self.assertHome(clean_env(SHOWTIME_HOME=".showtime", HOME=user), self.tmp, self.tmp / ".showtime")
        self.assertHome(clean_env(SHOWTIME_HOME="${user_config.home}", HOME=user,
                                                SHOWTIME_SETTINGS=self.tmp / "s.json"), self.tmp, user / ".showtime", "an unexpanded placeholder is no value")

    def test_project_showtime_found_without_a_variable(self):
        user = self.tmp / "user"
        user.mkdir()
        proj = self.tmp / "proj"
        shim.install(proj / ".showtime", SKILL)     # what `SHOWTIME_HOME=.showtime showtime setup` leaves
        deep = proj / "src" / "videos"
        deep.mkdir(parents=True)
        env = clean_env(HOME=user, SHOWTIME_SETTINGS=self.tmp / "s.json")
        self.assertHome(env, deep, proj / ".showtime")
        self.assertHome(env, self.tmp, user / ".showtime", "only inside that project")
        # an explicit variable still wins
        self.assertHome(dict(env, SHOWTIME_HOME=str(self.tmp / "x")), deep, self.tmp / "x")
        # right after `SHOWTIME_HOME=.showtime showtime <cmd> --background` (a first setup): found at once
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        cp = launcher("paths", "home", "--background", env=dict(env, SHOWTIME_HOME=".showtime"), cwd=fresh)
        rid = re.search(r"background: (\S+)", cp.stdout).group(1)
        cp = launcher("status", rid, "--wait", "60", env=env, cwd=fresh)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn(str(fresh / ".showtime"), cp.stdout)
        # Windows keeps the temp folder inside the user's folder: a project there is still found first,
        # and the search stops at the user's folder (whose own .showtime is the default anyway)
        inner = user / "AppData" / "Local" / "Temp" / "proj2"
        shim.install(inner / ".showtime", SKILL)
        (inner / "a" / "b").mkdir(parents=True)
        self.assertHome(env, inner / "a" / "b", inner / ".showtime")
        self.assertHome(env, user / "AppData", user / ".showtime")
        # a stray .showtime folder that setup never used is not a home
        stray = self.tmp / "stray"
        (stray / ".showtime").mkdir(parents=True)
        self.assertHome(env, stray, user / ".showtime")

    def test_search_stops_at_every_home_folder(self):
        """The Windows CI layout: the temp folder (and so a test's fake home) lies inside the real user
        folder, which has a real ~/.showtime. With only the fake home as the stopping point the search
        climbs past it into the real one; every home folder must stop it."""
        real = self.tmp / "real-user"
        (real / ".showtime").mkdir(parents=True)
        (real / ".showtime" / "state.json").write_text("{}", encoding="utf-8")
        work = real / "AppData" / "Local" / "Temp" / "st-x"
        fake = work / "user"
        fake.mkdir(parents=True)
        self.assertEqual(L.workspace_home(work, homes=[fake]), real / ".showtime", "what went wrong before")
        self.assertIsNone(L.workspace_home(work, homes=[fake, real]))
        # and every variable that names a home counts (here HOME is the fake one, the account's is real)
        cp = launcher("version", "--json", env=clean_env(HOME=fake, SHOWTIME_SETTINGS=self.tmp / "s.json"), cwd=work)
        info = json.loads(cp.stdout)
        folders = [os.path.normcase(str(Path(p))) for p in info["home_folders"]]
        self.assertIn(os.path.normcase(str(fake.resolve())), folders, info)
        self.assertGreaterEqual(len(folders), 2 if not IS_WIN else 1, info)   # the account's own home too
        self.assertTrue(info["home_source"], info)   # says how the home was chosen

    @NOT_ROOT
    @POSIX_ONLY
    def test_caches_move_in_when_their_folders_are_read_only(self):
        user = self.tmp / "user"
        user.mkdir()
        home = self.tmp / "ws" / ".showtime"
        home.mkdir(parents=True)
        old = dict(os.environ)
        try:
            os.environ["HOME"] = str(user)
            for k in ("XDG_CACHE_HOME", "XDG_DATA_HOME"):
                os.environ.pop(k, None)
            self.assertEqual(L.cache_redirects(home, {}), {}, "writable defaults stay as they are")
            os.chmod(str(user), 0o555)
            red = L.cache_redirects(home, {})
            self.assertEqual(red.get("UV_CACHE_DIR"), str(home / "cache" / "uv"))
            self.assertEqual(red.get("UV_PYTHON_INSTALL_DIR"), str(home / "python"))
            self.assertEqual(red.get("npm_config_cache"), str(home / "cache" / "npm"))
            self.assertEqual(L.cache_redirects(home, {"UV_CACHE_DIR": "/elsewhere"}).get("UV_CACHE_DIR"), None)
        finally:
            os.chmod(str(user), 0o755)
            os.environ.clear()
            os.environ.update(old)


# ============================================================================ doctor in a sandbox

class TestDoctorSandbox(Tmp):
    def doctor(self, env, cwd=None):
        cp = launcher("doctor", "--quick", "--json", env=env, cwd=cwd or self.tmp, timeout=300)
        self.assertIn(cp.returncode, (0, 1), cp.stderr)
        return {r["check"]: r for r in json.loads(cp.stdout)["checks"]}, cp

    def test_host_detection(self):
        self.assertEqual(sandbox.detect_host({"CODEX_SANDBOX": "seatbelt"}), "codex")
        self.assertEqual(sandbox.detect_host({"CURSOR_AGENT": "1"}), "cursor")
        self.assertEqual(sandbox.detect_host({"GITHUB_ACTIONS": "true", "GITHUB_WORKFLOW": "Copilot"}), "copilot-cloud")
        self.assertEqual(sandbox.detect_host({"GEMINI_CLI": "1"}), "gemini")
        self.assertEqual(sandbox.detect_host({"CLAUDECODE": "1"}), "claude")
        self.assertEqual(sandbox.detect_host({"SHOWTIME_HOST": "antigravity", "CLAUDECODE": "1"}), "antigravity")
        self.assertEqual(sandbox.detect_host({}), "generic")
        hosts = sandbox.download_hosts()
        for h in ("huggingface.co", "github.com", "pypi.org", "registry.npmjs.org"):
            self.assertIn(h, hosts)

    def test_skill_row_is_host_neutral(self):
        """A Codex (or any other agent's) plugin folder is never reported as a Claude Code plugin."""
        from st import doctor
        cases = [("/home/you/.codex/plugins/cache/showtime/showtime/0.2.0/skills/showtime", "Codex"),
                 ("/home/you/.cursor/plugins/local/showtime/skills/showtime", "Cursor"),
                 ("C:\\Users\\you\\.devin\\plugins\\showtime\\skills\\showtime", "Devin"),
                 ("/Users/you/.claude/plugins/cache/showtime/showtime/0.2.0/skills/showtime", "Claude Code")]
        for path, who in cases:
            status, msg = doctor.skill_install_line(path, False, "", False, "generic")
            self.assertEqual(status, "pass", msg)
            self.assertIn("plugin for %s" % who, msg)
            if who != "Claude Code":
                self.assertNotIn("Claude", msg)
        # an unknown plugin folder: the running agent names it, else the message stays generic
        status, msg = doctor.skill_install_line("/opt/x/plugins/showtime/skills/showtime", False, "", False, "gemini")
        self.assertIn("plugin for Gemini CLI", msg)
        status, msg = doctor.skill_install_line("/opt/x/plugins/showtime/skills/showtime", False, "", False, "generic")
        self.assertEqual((status, "Claude" in msg), ("pass", False))
        self.assertIn("agent plugin", msg)
        # not a plugin at all: a hint that names no particular agent
        status, msg = doctor.skill_install_line("/home/you/showtime/skills/showtime", False, "", False, "generic")
        self.assertEqual(status, "skip")
        self.assertNotIn("Claude", msg)
        self.assertIn("docs/agents.md", msg)

    def test_no_network(self):
        env = clean_env(SHOWTIME_HOME=self.tmp / "home", SHOWTIME_NET_PROBE="http://127.0.0.1:%d/" % closed_port(),
                        CODEX_SANDBOX="seatbelt", CODEX_SANDBOX_NETWORK_DISABLED="1")
        rows, _ = self.doctor(env)
        net = rows["network"]
        self.assertEqual(net["status"], "fail", net)   # setup has not run here: it needs the network
        self.assertIn("no network", net["detail"])
        self.assertIn("CODEX_SANDBOX_NETWORK_DISABLED=1", net["detail"])
        self.assertIn("network_access = true", net["hint"])
        self.assertIn("normal terminal", net["hint"])
        rows, _ = self.doctor(dict(env, SHOWTIME_HOST="cursor"))
        self.assertIn("sandbox.json", rows["network"]["hint"])
        self.assertIn("huggingface.co", rows["network"]["hint"])
        rows, _ = self.doctor(dict(env, SHOWTIME_OFFLINE="1"))
        self.assertEqual(rows["network"]["status"], "skip")

    @NOT_ROOT
    @POSIX_ONLY
    def test_read_only_home_and_work_folder(self):
        ro = self.tmp / "ro"
        ro.mkdir()
        os.chmod(str(ro), 0o555)
        env = clean_env(SHOWTIME_HOME=ro / "home", SHOWTIME_OFFLINE="1", SHOWTIME_HOST="codex")
        rows, cp = self.doctor(env, cwd=ro)
        self.assertEqual(cp.returncode, 1)
        hw = rows["home writable"]
        self.assertEqual(hw["status"], "fail", hw)
        self.assertIn("writable_roots", hw["hint"])
        self.assertIn(str(ro / "home"), hw["hint"])
        self.assertIn("SHOWTIME_HOME", hw["hint"], "the escape hatch is named")
        self.assertEqual(rows["work folder"]["status"], "warn")
        self.assertEqual(rows["showtime command"]["status"], "skip", "nothing is written where it cannot be")
        text = launcher("doctor", "--quick", env=env, cwd=ro, timeout=300).stdout
        self.assertIn("fix:", text)
        self.assertNotIn("Traceback", text)

    def test_writable_home_passes(self):
        rows, _ = self.doctor(clean_env(SHOWTIME_HOME=self.tmp / "home", SHOWTIME_OFFLINE="1"))
        self.assertEqual(rows["home writable"]["status"], "pass")
        self.assertNotIn("work folder", rows)


if __name__ == "__main__":
    t0 = time.time()
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_portable: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
