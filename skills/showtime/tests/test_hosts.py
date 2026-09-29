#!/usr/bin/env python3
"""showtime in every agent: the manifests at the plugin root and `showtime install --agent <host>`.

  * the manifests: the Agent Plugins 1.0 root plugin.json + mcp.json (closed fields, name rules, a
    stdio server whose relative launch path exists), gemini-extension.json (${extensionPath}), the
    Antigravity mcp_config.json (${PLUGIN_ROOT}), the Copilot crew in com.github.copilot/agents/, versions
    equal to the skill's, and .claude-plugin/ unchanged in what it declares;
  * the crew generator: every host format parses, keeps name and description, drops Claude-only fields and
    model aliases, maps tool names (Copilot aliases, Gemini tool names, OpenCode switches), raises Gemini's
    timeout, and replaces ${CLAUDE_PLUGIN_ROOT} with the real skill folder;
  * install/uninstall into a scratch home for every host: the expected files, a second run changes
    nothing, other settings survive a merge (one backup), a file that is not plain JSON is left alone,
    Codex's config.toml gets one marked block, foreign files are never touched, a shared ~/.agents/skills
    link stays until its last host goes, --print writes nothing;
  * the command line: --print --json, --list, an unknown agent, and the MCP command a config gets really
    answers `initialize` (Node needed; skipped without it).

Stdlib only, no setup, no network. usage: python tests/test_hosts.py [--fast] [-v]   (a few seconds)
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import re
import shutil
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
sys.path.insert(0, str(REPO / "scripts"))

from st import __version__, hosts, shim  # noqa: E402

IS_WIN = os.name == "nt"
AP_PLUGIN = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AP_MCP = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
AP_FIELDS = {"$schema", "name", "version", "description", "author", "homepage", "repository", "license",
             "keywords", "extensions"}
AP_NAME = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
GEMINI_AGENT_KEYS = {"kind", "name", "description", "display_name", "tools", "mcp_servers", "model", "temperature",
                     "max_turns", "timeout_mins"}
GEMINI_TOOLS = {"read_file", "read_many_files", "list_directory", "glob", "grep_search", "write_file", "replace",
                "run_shell_command", "web_fetch", "google_web_search"}
COPILOT_TOOLS = {"read", "search", "edit", "execute", "web", "agent"}
CLAUDE_ONLY = ("effort", "maxTurns", "omitClaudeMd", "color")


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def frontmatter(text: str):
    meta, body = hosts.parse_agent(text)
    return meta, body


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-hosts-"))
        self.user = self.tmp / "user"
        self.user.mkdir()
        self.home = self.tmp / "showtime-home"
        self.where = hosts.Where(self.user, windows=False)

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def install(self, key, **kw):
        return hosts.install(hosts.HOSTS[key], kw.pop("where", self.where), self.home, SKILL, **kw)

    def uninstall(self, key, **kw):
        return hosts.uninstall(hosts.HOSTS[key], kw.pop("where", self.where), self.home, SKILL, **kw)

    def states(self, plan, kind=None):
        return [a["state"] for a in plan.actions if kind is None or a["kind"] == kind]

    def tree(self, root: Path):
        out = {}
        for p in sorted(root.rglob("*")):
            if p.is_symlink():
                out[str(p.relative_to(root))] = "->" + os.readlink(str(p))
            elif p.is_file():
                out[str(p.relative_to(root))] = p.read_bytes()
        return out


# --------------------------------------------------------------------------- manifests

class TestManifests(unittest.TestCase):
    def test_agent_plugins_manifest(self):
        m = load(REPO / "plugin.json")
        self.assertEqual(m["$schema"], AP_PLUGIN, "1.0.0: the version Codex, Cursor and Copilot all accept")
        self.assertLessEqual(set(m), AP_FIELDS, "the manifest schema is closed")
        self.assertRegex(m["name"], AP_NAME)
        self.assertEqual(m["name"], "showtime")
        self.assertEqual(m["version"], __version__)
        self.assertLessEqual(set(m.get("author", {})), {"name", "email", "url"})
        for k in ("description", "homepage", "repository", "license"):
            self.assertIsInstance(m[k], str)
        self.assertTrue(all(isinstance(k, str) for k in m["keywords"]))
        self.assertTrue((REPO / "skills" / "showtime" / "SKILL.md").is_file(), "skills/<name>/SKILL.md, one level")

    def test_agent_plugins_mcp(self):
        m = load(REPO / "mcp.json")
        self.assertEqual(set(m), {"$schema", "mcpServers"})
        self.assertEqual(m["$schema"], AP_MCP, "same spec version as plugin.json")
        srv = m["mcpServers"]["showtime"]
        self.assertLessEqual(set(srv), {"type", "command", "args", "env", "cwd"})
        self.assertEqual(srv["type"], "stdio")
        self.assertRegex(srv["command"], r"^[A-Za-z0-9_.-]+$", "one bare executable token, no shell string")
        self.assertNotIn("cwd", srv, "the default cwd is the plugin root, which the relative path needs")
        script = srv["args"][0]
        self.assertTrue(script.startswith("./"), "relative to the plugin root: Cursor does not expand ${PLUGIN_ROOT}")
        self.assertTrue((REPO / script).is_file(), script)
        for k in srv.get("env", {}):
            self.assertNotIn(k, ("PLUGIN_ROOT", "PLUGIN_DATA"), "reserved by the spec")

    def test_gemini_extension(self):
        m = load(REPO / "gemini-extension.json")
        self.assertEqual(m["name"], "showtime")
        self.assertEqual(m["version"], __version__)
        srv = m["mcpServers"]["showtime"]
        path = "".join(srv["args"]).replace("${extensionPath}", str(REPO)).replace("${/}", os.sep)
        self.assertTrue(Path(path).is_file(), path)
        self.assertGreaterEqual(srv.get("timeout", 0), 600000, "long renders: at least Gemini's own default")
        self.assertNotIn("contextFileName", m, "no GEMINI.md: the skill carries the behaviour")

    def test_antigravity_mcp_config(self):
        m = load(REPO / "mcp_config.json")
        srv = m["mcpServers"]["showtime"]
        path = srv["args"][0].replace("${PLUGIN_ROOT}", str(REPO))
        self.assertTrue(Path(path).is_file(), path)
        self.assertEqual(srv["command"], "node")

    def test_claude_plugin_unchanged(self):
        m = load(REPO / ".claude-plugin" / "plugin.json")
        self.assertEqual(m["mcpServers"]["showtime"]["args"], ["${CLAUDE_PLUGIN_ROOT}/skills/showtime/mcp/server.mjs"])
        self.assertNotIn("agents", m, "agents/ is found by default: Claude Code, Copilot, Devin, Cursor rely on it")
        self.assertEqual(len(list((REPO / "agents").glob("*.md"))), 10)

    def test_crew_copies_in_sync(self):
        import build_agents
        self.assertEqual(build_agents.stale(), [], "run: python scripts/build_agents.py")
        names = sorted(p.name for p in (REPO / "com.github.copilot" / "agents").glob("*.agent.md"))
        self.assertEqual(len(names), 10)
        for p in (REPO / "com.github.copilot" / "agents").glob("*.agent.md"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("${", text, p.name)
            self.assertIn("skills/showtime", text)


# --------------------------------------------------------------------------- the crew generator

class TestCrew(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.crew = hosts.load_crew(SKILL)
        cls.ref = "/opt/skills/showtime"

    def test_sources(self):
        self.assertEqual(len(self.crew), 10)
        self.assertEqual(hosts.crew_sources(SKILL)[0].parent, REPO / "agents", "a clone uses the plugin's own files")
        with tempfile.TemporaryDirectory() as d:          # a skill installed on its own carries a copy
            alone = Path(d) / "skills" / "showtime"
            shutil.copytree(str(SKILL / "setup" / "agents"), str(alone / "setup" / "agents"))
            self.assertEqual(len(hosts.load_crew(alone)), 10)

    def each(self, fmt):
        for meta, body in self.crew:
            name, text = hosts.render_agent(fmt, meta, body, self.ref)
            yield meta, name, text

    def common(self, fmt, text):
        self.assertIn(hosts.MARK, text, "uninstall finds its own files by this marker")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn(self.ref, text, "the body names the real skill folder")
        if fmt != "claude":
            self.assertNotRegex(text, r"(?m)^model:\s*(sonnet|opus|haiku)\s*$", "Claude model aliases dropped")

    def test_codex_toml(self):
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            tomllib = None
        for meta, name, text in self.each("codex"):
            self.assertEqual(name, meta["name"] + ".toml")
            self.common("codex", text)
            if tomllib:
                d = tomllib.loads(text)
                self.assertEqual(set(d), {"name", "description", "developer_instructions"})
                self.assertEqual(d["name"], meta["name"])
                self.assertIn("showtime crew", d["description"])
                self.assertIn("Return contract", d["developer_instructions"])

    def test_gemini(self):
        for meta, name, text in self.each("gemini"):
            fm, body = frontmatter(text)
            self.common("gemini", text)
            self.assertLessEqual(set(fm), GEMINI_AGENT_KEYS, "Gemini rejects unknown keys")
            self.assertRegex(fm["name"], r"^[a-z0-9-_]+$")
            tools = json.loads(fm["tools"])
            self.assertTrue(tools and set(tools) <= GEMINI_TOOLS, tools)
            self.assertGreaterEqual(int(fm["timeout_mins"]), 30, "default 10 stops a render supervisor")
            self.assertEqual(int(fm["max_turns"]), int(meta["maxTurns"]))
            self.assertIsInstance(json.loads(fm["description"]), str)
        critic = dict((m["name"], t) for m, _, t in self.each("gemini"))["critic"]
        self.assertNotIn("run_shell_command", critic, "the critic has no shell in Claude either")

    def test_copilot(self):
        for meta, name, text in self.each("copilot"):
            self.assertTrue(name.endswith(".agent.md"))
            fm, _ = frontmatter(text)
            self.assertEqual(set(fm), {"name", "description", "tools"})
            self.assertLessEqual(set(json.loads(fm["tools"])), COPILOT_TOOLS)
            self.common("copilot", text)

    def test_opencode(self):
        for meta, name, text in self.each("opencode"):
            fm, _ = frontmatter(text)
            self.assertEqual(fm["mode"], "subagent")
            self.assertIn("description", fm)
            self.common("opencode", text)
        critic = dict((m["name"], t) for m, _, t in self.each("opencode"))["critic"]
        self.assertIn("bash: false", critic)
        self.assertNotIn("write: false", critic, "the critic writes FINDINGS.md")

    def test_plain_markdown_hosts(self):
        for fmt in ("cursor", "devin", "antigravity", "factory", "qwen", "claude"):
            for meta, name, text in self.each(fmt):
                fm, body = frontmatter(text)
                self.assertEqual(fm["name"], meta["name"])
                self.assertIn("showtime crew", fm["description"])
                self.common(fmt, text)
                if fmt != "claude":
                    for k in CLAUDE_ONLY + ("tools",):
                        self.assertNotIn(k, fm, "%s: %s" % (fmt, k))
        claude = dict((m["name"], t) for m, _, t in self.each("claude"))["voice-director"]
        self.assertIn("model: sonnet", claude, "Claude Code keeps its own frontmatter")

    def test_kiro_json(self):
        for meta, name, text in self.each("kiro"):
            d = json.loads(text)
            self.assertEqual(d["name"], meta["name"])
            self.assertIn("Return contract" if meta["name"] != "critic" else "FINDINGS.md", d["prompt"])
            self.assertEqual(d["resources"], ["skill://%s/SKILL.md" % self.ref])
            self.assertIn(hosts.MARK, text)


# --------------------------------------------------------------------------- install / uninstall

EXPECT = {   # host: (skill link, crew dir, agent file of the editor, mcp config)
    "codex": (".agents/skills/showtime", ".codex/agents", "editor.toml", ".codex/config.toml"),
    "copilot": (".agents/skills/showtime", ".copilot/agents", "editor.agent.md", ".copilot/mcp-config.json"),
    "cursor": (".agents/skills/showtime", ".cursor/agents", "editor.md", ".cursor/mcp.json"),
    "devin": (".agents/skills/showtime", ".config/devin/agents", "editor.md", ".config/devin/mcp_config.json"),
    "gemini": (".agents/skills/showtime", ".gemini/agents", "editor.md", ".gemini/settings.json"),
    "antigravity": (".gemini/antigravity-cli/skills/showtime", ".gemini/config/agents", "editor.md",
                    ".gemini/config/mcp_config.json"),
    "opencode": (".agents/skills/showtime", ".config/opencode/agents", "editor.md", ".config/opencode/opencode.json"),
    "cline": (".cline/skills/showtime", None, None, ".cline/mcp.json"),
    "kilo": (".agents/skills/showtime", None, None, None),
    "kiro": (".kiro/skills/showtime", ".kiro/agents", "editor.json", ".kiro/settings/mcp.json"),
    "zed": (".agents/skills/showtime", None, None, ".config/zed/settings.json"),
    "goose": (".agents/skills/showtime", None, None, None),
    "amp": (".agents/skills/showtime", None, None, ".config/amp/settings.json"),
    "factory": (".factory/skills/showtime", ".factory/droids", "editor.md", ".factory/mcp.json"),
    "qwen": (".qwen/skills/showtime", ".qwen/agents", "editor.md", ".qwen/settings.json"),
    "claude": (".claude/skills/showtime", ".claude/agents", "editor.md", None),
}


@unittest.skipIf(IS_WIN, "symlinks need a privilege on Windows; the junction/copy path is covered in TestWindows")
class TestInstall(Tmp):
    def test_every_host_installs_and_uninstalls(self):
        self.assertEqual(set(EXPECT), set(hosts.HOSTS))
        for key, (link, crew, editor, cfg) in EXPECT.items():
            with self.subTest(host=key):
                plan = self.install(key)
                self.assertNotIn("failed", self.states(plan), plan.as_json())
                sk = self.user / link
                self.assertTrue(sk.is_symlink() and (sk / "SKILL.md").is_file(), link)
                self.assertTrue(shim._same(Path(os.path.realpath(str(sk))), SKILL))  # noqa: SLF001
                if crew:
                    files = sorted((self.user / crew).iterdir())
                    self.assertEqual(len(files), 10)
                    self.assertTrue((self.user / crew / editor).is_file())
                    text = (self.user / crew / editor).read_text(encoding="utf-8")
                    self.assertIn(str(sk), text, "agents point at the link, which survives updates")
                if cfg:
                    text = (self.user / cfg).read_text(encoding="utf-8")
                    self.assertIn(str(self.home / "bin" / "showtime"), text)
                    self.assertIn('"mcp"', text)
                self.assertTrue((self.home / "bin" / "showtime").is_file(), "the stable command is written")
                again = self.install(key)
                self.assertTrue(set(self.states(again)) <= {"unchanged", "done", "run", "paste"}, again.as_json())
        for key in EXPECT:
            with self.subTest(uninstall=key):
                self.uninstall(key)
        left = [str(p.relative_to(self.user)) for p in self.user.rglob("*")
                if p.is_file() and not p.name.endswith(".before-showtime")]
        # configs that held only the showtime entry end up as "{}"; everything else is gone
        for rel in left:
            self.assertEqual(json.loads((self.user / rel).read_text(encoding="utf-8") or "{}"), {}, rel)
        self.assertFalse((self.user / ".agents" / "skills" / "showtime").exists())
        self.assertEqual(hosts.installed(self.home), [])

    def test_merge_keeps_other_settings_and_backs_up_once(self):
        cfg = self.user / ".cursor" / "mcp.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
        self.install("cursor")
        d = load(cfg)
        self.assertEqual(d["mcpServers"]["other"], {"command": "x"})
        self.assertEqual(d["theme"], "dark")
        self.assertEqual(d["mcpServers"]["showtime"]["type"], "stdio")
        backup = cfg.with_name("mcp.json.before-showtime")
        self.assertEqual(load(backup), {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"})
        backup.write_text("first", encoding="utf-8")
        d["mcpServers"]["showtime"]["args"] = ["changed"]
        cfg.write_text(json.dumps(d), encoding="utf-8")
        self.install("cursor")
        self.assertEqual(backup.read_text(encoding="utf-8"), "first", "the backup is the original, kept once")
        self.uninstall("cursor")
        self.assertEqual(load(cfg), {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"})

    def test_hand_edited_entry_is_kept_on_uninstall(self):
        self.install("kiro")
        cfg = self.user / ".kiro" / "settings" / "mcp.json"
        d = load(cfg)
        d["mcpServers"]["showtime"]["env"] = {"X": "1"}
        cfg.write_text(json.dumps(d), encoding="utf-8")
        plan = self.uninstall("kiro")
        self.assertIn("kept", self.states(plan, "mcp"))
        self.assertIn("showtime", load(cfg)["mcpServers"])

    def test_json_with_comments_is_left_alone(self):
        cfg = self.user / ".config" / "zed" / "settings.json"
        cfg.parent.mkdir(parents=True)
        original = '// Zed settings\n{\n  "theme": "One Dark", // mine\n}\n'
        cfg.write_text(original, encoding="utf-8")
        plan = self.install("zed")
        self.assertEqual(cfg.read_text(encoding="utf-8"), original)
        mcp = [a for a in plan.actions if a["kind"] == "mcp"][0]
        self.assertEqual(mcp["state"], "paste")
        self.assertIn('"context_servers"', mcp["content"])
        self.assertFalse(cfg.with_name("settings.json.before-showtime").exists())

    def test_codex_block(self):
        cfg = self.user / ".codex" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('model = "gpt-6"\n\n[mcp_servers.other]\ncommand = "x"\n', encoding="utf-8")
        self.install("codex")
        text = cfg.read_text(encoding="utf-8")
        self.assertEqual(text.count(hosts.BLOCK_BEGIN), 1)
        self.assertIn('model = "gpt-6"', text)
        self.assertIn("[mcp_servers.other]", text)
        self.assertIn("tool_timeout_sec", text)
        try:
            import tomllib
            d = tomllib.loads(text)
            self.assertEqual(d["mcp_servers"]["showtime"]["args"], ["mcp"])
        except ImportError:
            pass
        self.install("codex")
        self.assertEqual(cfg.read_text(encoding="utf-8"), text, "idempotent")
        self.uninstall("codex")
        self.assertEqual(cfg.read_text(encoding="utf-8"), 'model = "gpt-6"\n\n[mcp_servers.other]\ncommand = "x"\n')

    def test_codex_foreign_table_is_left_alone(self):
        cfg = self.user / ".codex" / "config.toml"
        cfg.parent.mkdir(parents=True)
        mine = '[mcp_servers.showtime]\ncommand = "/my/own/showtime"\nargs = ["mcp"]\n'
        cfg.write_text(mine, encoding="utf-8")
        plan = self.install("codex")
        self.assertEqual(cfg.read_text(encoding="utf-8"), mine)
        self.assertIn("paste", self.states(plan, "mcp"))

    def test_foreign_files_are_never_touched(self):
        agents = self.user / ".cursor" / "agents"
        agents.mkdir(parents=True)
        (agents / "editor.md").write_text("---\nname: editor\ndescription: my own\n---\nmine\n", encoding="utf-8")
        own_skill = self.user / ".kiro" / "skills" / "showtime"
        own_skill.mkdir(parents=True)
        (own_skill / "notes.txt").write_text("not a skill", encoding="utf-8")
        p1, p2 = self.install("cursor"), self.install("kiro")
        self.assertEqual((agents / "editor.md").read_text(encoding="utf-8").splitlines()[-1], "mine")
        self.assertIn("skipped", self.states(p1, "crew"))
        self.assertIn("skipped", self.states(p2, "skill"))
        self.uninstall("cursor")
        self.uninstall("kiro")
        self.assertTrue((agents / "editor.md").is_file())
        self.assertEqual(len(list(agents.iterdir())), 1)
        self.assertTrue((own_skill / "notes.txt").is_file())

    def test_shared_skill_link_stays_until_the_last_host(self):
        self.install("codex")
        self.install("gemini")
        link = self.user / ".agents" / "skills" / "showtime"
        plan = self.uninstall("codex")
        self.assertTrue(link.is_symlink())
        self.assertIn("kept", self.states(plan, "skill"))
        self.uninstall("gemini")
        self.assertFalse(link.exists() or link.is_symlink())

    def test_existing_skill_install_is_reused(self):
        existing = self.user / ".agents" / "skills" / "showtime"
        existing.parent.mkdir(parents=True)
        shutil.copytree(str(SKILL), str(existing), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        plan = self.install("opencode")
        self.assertEqual(self.states(plan, "skill"), ["unchanged"])
        self.uninstall("opencode")
        self.assertTrue((existing / "SKILL.md").is_file(), "not made by this command: never removed")

    def test_print_writes_nothing(self):
        before = self.tree(self.user)
        for key in hosts.HOSTS:
            plan = self.install(key, write=False)
            self.assertTrue(plan.actions)
        self.assertEqual(self.tree(self.user), before)
        self.assertFalse(self.home.exists())

    def test_project_scope(self):
        proj = self.tmp / "proj"
        proj.mkdir()
        where = hosts.Where(self.user, proj, windows=False)
        self.install("cursor", where=where)
        self.assertTrue((proj / ".agents" / "skills" / "showtime" / "SKILL.md").is_file())
        self.assertEqual(len(list((proj / ".cursor" / "agents").iterdir())), 10)
        self.assertIn("showtime", load(proj / ".cursor" / "mcp.json")["mcpServers"])
        self.assertFalse((self.user / ".cursor").exists(), "the user's own config is untouched")
        plan = self.install("cline", where=where)
        self.assertIn("paste", self.states(plan, "mcp"), "Cline has no project MCP file")
        self.uninstall("cursor", where=where)
        self.assertFalse((proj / ".cursor" / "agents").exists() and any((proj / ".cursor" / "agents").iterdir()))

    def test_skill_in_a_versioned_cache_is_copied(self):
        cache = self.tmp / "u" / ".claude" / "plugins" / "cache" / "showtime" / "showtime" / "0.1.0" / "skills" / "showtime"
        shutil.copytree(str(SKILL), str(cache), ignore=shutil.ignore_patterns("tests", "__pycache__"))
        src = hosts.durable_skill(self.home, cache)
        self.assertEqual(src, self.home / "skill", "a plugin update deletes the versioned folder")
        self.assertTrue((src / "SKILL.md").is_file())


class TestWindows(Tmp):
    def test_paths(self):
        w = hosts.Where(self.user, windows=True, appdata=self.tmp / "Roaming")
        self.assertEqual(w.path("@devin/mcp_config.json", None), self.tmp / "Roaming" / "devin" / "mcp_config.json")
        self.assertEqual(w.path("@zed/settings.json", None), self.tmp / "Roaming" / "Zed" / "settings.json")
        self.assertEqual(hosts.mcp_command(self.home, windows=True)[0], str(self.home / "bin" / "showtime.cmd"))
        lin = hosts.Where(self.user, windows=False)
        self.assertEqual(lin.path("@devin/agents", None), self.user / ".config" / "devin" / "agents")

    def test_copy_fallback_is_marked_and_removed(self):
        dest = self.user / ".kiro" / "skills" / "showtime"
        real = os.symlink
        try:
            def no_symlink(*a, **k):
                raise OSError("no privilege")
            os.symlink = no_symlink
            if IS_WIN:
                self.skipTest("the junction path runs instead on Windows")
            self.install("kiro", parts=("skill",))
        finally:
            os.symlink = real
        self.assertTrue((dest / "SKILL.md").is_file() and (dest / hosts.SKILL_MARK_FILE).is_file())
        self.assertFalse((dest / "tests").exists())
        self.uninstall("kiro")
        self.assertFalse(dest.exists())


# --------------------------------------------------------------------------- command line

class TestCli(Tmp):
    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SHOWTIME_")}
        env.update(HOME=str(self.user), USERPROFILE=str(self.user), SHOWTIME_HOME=str(self.home), NO_COLOR="1",
                   APPDATA=str(self.user / "AppData" / "Roaming"))
        return env

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(LAUNCHER), "install"] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=self.env(), timeout=120)

    def test_print_json_and_list(self):
        r = self.run_cli("--agent", "codex,gemini", "--print", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertTrue(d["dry_run"])
        self.assertEqual([x["host"] for x in d["results"]], ["codex", "gemini"])
        self.assertEqual(list(self.user.iterdir()), [], "--print writes nothing")
        r = self.run_cli("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("antigravity", r.stdout)

    def test_unknown_agent(self):
        r = self.run_cli("--agent", "notepad")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown agent", r.stderr)
        self.assertIn("fix:", r.stderr)

    @unittest.skipIf(IS_WIN, "POSIX shim")
    def test_install_then_mcp_command_answers(self):
        r = self.run_cli("--agent", "cursor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("created", r.stdout)
        entry = load(self.user / ".cursor" / "mcp.json")["mcpServers"]["showtime"]
        if not shutil.which("node"):
            self.skipTest("no Node.js")
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
        p = subprocess.run([entry["command"]] + entry["args"], input=msg + "\n", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, encoding="utf-8", env=self.env(), timeout=60, cwd=str(self.tmp))
        first = json.loads(p.stdout.splitlines()[0])
        self.assertEqual(first["result"]["serverInfo"]["name"], "showtime")
        r = self.run_cli("--agent", "cursor", "--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(load(self.user / ".cursor" / "mcp.json"), {})


if __name__ == "__main__":
    t0 = time.time()
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_hosts: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
