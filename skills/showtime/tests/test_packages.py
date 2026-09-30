#!/usr/bin/env python3
"""MCP distribution packages: server.json (MCP Registry), the npm package and the MCPB bundle.

Builds both with scripts/build_packages.py into a temporary folder (never into the repository) and
checks what a registry or client would: names and versions agree, the bundle's manifest points at a
file that exists and lists the server's real tools, tests and caches stay out, the shims keep their
executable bit, the recorded SHA-256 matches, and the packaged server answers `initialize`.
Light: Node + stdlib (npm only for --pack, skipped without it). Skipped where the repository's
scripts/ folder is not present (a skill-only install).

usage: python tests/test_packages.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
BUILD = REPO / "scripts" / "build_packages.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
NPM = shutil.which("npm", path=ENV.get("PATH"))


def lib_version() -> str:
    text = (SKILL / "lib" / "st" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text).group(1)


def handshake(cmd):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         encoding="utf-8", env=ENV)
    try:
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())
    finally:
        p.stdin.close()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        p.stdout.close()
        p.stderr.close()


def list_tools():
    """tools/list from the repository's MCP server (with each tool's annotations)."""
    p = subprocess.Popen([NODE, str(SKILL / "mcp" / "server.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, encoding="utf-8", env=ENV)
    try:
        for m in ({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                      "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
                  {"jsonrpc": "2.0", "method": "notifications/initialized"},
                  {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}):
            p.stdin.write(json.dumps(m) + "\n")
        p.stdin.flush()
        while True:
            msg = json.loads(p.stdout.readline())
            if msg.get("id") == 2:
                return msg["result"]["tools"]
    finally:
        p.stdin.close()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        p.stdout.close()
        p.stderr.close()


@unittest.skipUnless(BUILD.is_file(), "scripts/build_packages.py is not here (skill-only install)")
class TestPackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-pkg-"))
        args = [sys.executable, str(BUILD), "all", "--out", str(cls.tmp / "dist"), "--json"]
        if NPM:
            args.append("--pack")
        cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", env=ENV, timeout=300)
        if cp.returncode != 0:
            raise AssertionError("build_packages failed:\n" + cp.stderr[-3000:])
        cls.res = json.loads(cp.stdout)
        cls.server = json.loads((REPO / "server.json").read_text(encoding="utf-8"))
        cls.pkg = json.loads((REPO / "packages" / "npm" / "package.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_01_server_json(self):
        s, ver = self.server, lib_version()
        self.assertEqual(s["$schema"], "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json")
        self.assertRegex(s["name"], r"^io\.github\.FavioVazquez/[a-zA-Z0-9._-]+$")   # GitHub-auth namespace
        self.assertLessEqual(len(s["description"]), 100)
        self.assertEqual(s["version"], ver)
        npm = [p for p in s["packages"] if p["registryType"] == "npm"]
        self.assertEqual(len(npm), 1)
        self.assertEqual(npm[0]["identifier"], self.pkg["name"])
        self.assertEqual(npm[0]["version"], ver)
        self.assertEqual(npm[0]["transport"], {"type": "stdio"})
        self.assertEqual(self.pkg["mcpName"], s["name"])                               # ownership check
        self.assertEqual(self.pkg["version"], ver)
        for icon in s.get("icons", []):
            self.assertTrue(icon["src"].startswith("https://") and len(icon["src"]) <= 255, icon)
            rel = icon["src"].split("/main/", 1)[1]
            self.assertTrue((REPO / rel).is_file(), rel)                              # the linked file exists

    def test_02_npm_stage(self):
        stage = Path(self.res["npm"]["stage"])
        pkg = json.loads((stage / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["bin"]["showtime-mcp"], "skill/mcp/server.mjs")
        for rel in pkg["bin"].values():
            self.assertTrue((stage / rel).is_file(), rel)
            self.assertTrue((stage / rel).stat().st_mode & 0o111 or sys.platform == "win32", rel)
        self.assertTrue((stage / "skill" / "SKILL.md").is_file())
        self.assertTrue((stage / "skill" / "setup" / "setup.py").is_file())         # `showtime setup` works from it
        self.assertFalse((stage / "skill" / "tests").exists())
        self.assertFalse(list(stage.rglob("__pycache__")))
        self.assertTrue((stage / "LICENSE").is_file())
        self.assertIn(self.server["name"], (stage / "README.md").read_text(encoding="utf-8"))
        r = handshake([NODE, str(stage / "skill" / "mcp" / "server.mjs")])
        self.assertEqual(r["result"]["serverInfo"]["name"], "showtime")
        self.assertEqual(r["result"]["serverInfo"]["version"], lib_version())
        cp = subprocess.run([NODE, str(stage / "bin" / "showtime.mjs"), "version", "--json"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", env=ENV, timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        info = json.loads(cp.stdout)
        self.assertEqual(info["version"], lib_version())
        self.assertEqual(Path(info["skill"]).resolve(), (stage / "skill").resolve())   # the packaged copy runs

    @unittest.skipUnless(NPM, "npm is not on PATH")
    def test_03_npm_tarball(self):
        tgz = Path(self.res["npm"]["tarball"])
        with tarfile.open(str(tgz)) as t:
            names = t.getnames()
        self.assertIn("package/package.json", names)
        self.assertIn("package/skill/mcp/server.mjs", names)
        self.assertFalse([n for n in names if "/tests/" in n or n.endswith(".pyc")])
        self.assertLess(tgz.stat().st_size, 10 * 1024 * 1024)

    def test_04_mcpb_bundle(self):
        m = self.res["mcpb"]
        bundle = Path(m["bundle"])
        self.assertEqual(bundle.name, "showtime-%s.mcpb" % lib_version())
        self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), m["sha256"])
        with zipfile.ZipFile(str(bundle)) as z:
            names = z.namelist()
            manifest = json.loads(z.read("manifest.json"))
            modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
        self.assertIn("icon.png", names)
        self.assertFalse([n for n in names if n.startswith("server/tests/") or "__pycache__" in n])
        self.assertEqual(modes["server/bin/showtime"] & 0o111, 0o111)                # the POSIX shim stays executable
        self.assertEqual(manifest["manifest_version"], "0.3")
        self.assertEqual(manifest["version"], lib_version())
        self.assertIn(manifest["server"]["entry_point"], names)
        self.assertEqual(manifest["server"]["mcp_config"]["args"], ["${__dirname}/" + manifest["server"]["entry_point"]])
        env = manifest["server"]["mcp_config"]["env"]
        self.assertEqual(env["SHOWTIME_MCP_BASE"], "${user_config.projects}")
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        for key, spec in plugin["userConfig"].items():                                # every plugin setting carried over
            self.assertEqual(env["SHOWTIME_OPT_" + key.upper()], "${user_config.%s}" % key)
            self.assertEqual(manifest["user_config"][key].get("default"), spec.get("default"), key)
        tools = [t["name"] for t in manifest["tools"]]
        self.assertEqual(len(tools), len(set(tools)))
        self.assertIn("doctor", tools)
        self.assertIn("render", tools)
        self.assertTrue(all(t["description"] for t in manifest["tools"]))
        self.assertLessEqual(len(manifest["description"]), 100)

    def test_05_dist_server_json_adds_the_bundle(self):
        s = json.loads(Path(self.res["mcpb"]["server_json"]).read_text(encoding="utf-8"))
        kinds = [p["registryType"] for p in s["packages"]]
        self.assertEqual(kinds, ["npm", "mcpb"])
        mcpb = s["packages"][1]
        self.assertEqual(mcpb["fileSha256"], self.res["mcpb"]["sha256"])
        self.assertIn("mcp", mcpb["identifier"])                                         # registry rule for MCPB URLs
        self.assertTrue(mcpb["identifier"].endswith("/releases/download/v%s/showtime-%s.mcpb" % (lib_version(), lib_version())))

    def test_06_reproducible_and_refuses_repo_output(self):
        again = self.tmp / "again"
        cp = subprocess.run([sys.executable, str(BUILD), "mcpb", "--out", str(again), "--json"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", env=ENV, timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["mcpb"]["sha256"], self.res["mcpb"]["sha256"])   # same input, same bytes
        cp = subprocess.run([sys.executable, str(BUILD), "npm", "--out", str(REPO / "dist-test-should-not-exist")],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", env=ENV, timeout=60)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("inside the repository", cp.stderr)
        self.assertFalse((REPO / "dist-test-should-not-exist").exists())

    def test_07_openai_plugin_zip(self):
        """The OpenAI directory upload: one folder, the listing it needs, skills only (no hooks, no local MCP)."""
        import zipfile
        r = self.res["openai"]
        with zipfile.ZipFile(r["zip"]) as z:
            names = z.namelist()
            man = json.loads(z.read("showtime/plugin.json"))
        self.assertEqual({n.split("/")[0] for n in names}, {"showtime"})
        ui = man["extensions"]["com.openai"]["interface"]
        self.assertLessEqual(len(ui["displayName"]), 30)
        self.assertLessEqual(len(ui["shortDescription"]), 30)
        self.assertLessEqual(len(ui["defaultPrompt"]), 3)
        self.assertEqual(man["version"], self.pkg["version"])
        for key in ("logo", "composerIcon"):
            self.assertIn("showtime/" + ui[key][2:], names)
        self.assertIn("showtime/skills/showtime/SKILL.md", names)
        self.assertIn("showtime/skills/showtime/bin/showtime", names)
        bad = [n for n in names if n.startswith(("showtime/hooks/", "showtime/agents/", "showtime/commands/",
                                                   "showtime/skills/showtime/mcp/", "showtime/skills/showtime/tests/"))
               or n.endswith((".mcpb", "/mcp.json", "/.mcp.json"))]
        self.assertEqual(bad, [])


@unittest.skipUnless((REPO / "llms-install.md").is_file(), "llms-install.md is not here (skill-only install)")
class TestLlmsInstall(unittest.TestCase):
    """llms-install.md is what an agent follows to install the MCP server: its paths and JSON must be real."""

    def test_paths_and_snippet(self):
        text = (REPO / "llms-install.md").read_text(encoding="utf-8")
        for rel in set(re.findall(r"<showtime>/([\w./-]+)", text)):
            self.assertTrue((REPO / rel).exists(), rel)
        blocks = re.findall(r"```json\n(.*?)```", text, re.S)
        self.assertEqual(len(blocks), 1)
        entry = json.loads(blocks[0])["mcpServers"]["showtime"]
        self.assertEqual(entry["command"], "node")
        self.assertTrue(entry["args"][0].endswith("skills/showtime/mcp/server.mjs"))
        self.assertLessEqual(entry["timeout"], 3600)                    # Cline's maximum, in seconds
        for sub in re.findall(r"bin/showtime ([a-z]+)", text):
            self.assertIn(sub, ("setup", "doctor"), sub)
        read_only = re.search(r"`doctor`, `status`.*?only read", text, re.S).group(0)
        hints = {t["name"]: (t.get("annotations") or {}).get("readOnlyHint") for t in list_tools()}
        for tool in re.findall(r"`([a-z_]+)`", read_only):
            self.assertIs(hints.get(tool), True, tool)                  # the server itself marks it read-only


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
