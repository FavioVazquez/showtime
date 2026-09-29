#!/usr/bin/env python3
"""MCP server, plugin settings, plugin executables and the progress monitor.

Real runs over stdio with a small Node client (tests/fixtures/mcp_client.mjs):
  * both protocol eras: `initialize` (2025-11-25) and per-request `_meta` (2026-07-28:
    server/discover, resultType, UnsupportedProtocolVersionError), unknown method/tool errors;
  * the tool list (names, schemas, annotations) and input validation (missing paths, unknown
    arguments, bad enums) returned as tool errors, never as crashes;
  * doctor -> new_project (2 s dom template at 640x360) -> render preview=true (progress
    notifications) -> qa on the rendered file, all through the server;
  * plugin settings: SHOWTIME_OPT_* (what plugin.json mcpServers passes from Claude Code's userConfig) are saved
    to the settings file, and the launcher turns them into SHOWTIME_VOICE / SHOWTIME_MAX_WORKERS ...
    (the environment still wins); the default voice then resolves to the configured one;
  * the manifest wiring: plugin.json mcpServers / monitors.json point at files that exist, every userConfig
    option reaches the server, there is no top-level bin/ (claude.ai/Cowork refuse it) and the
    skill's own shim runs;
  * progress-monitor.mjs on a synthetic progress log (quiet for short jobs, reports long ones).

The render + qa flow needs the browser tools (`showtime setup`); it is skipped when they are missing.
Stdlib only. usage: python tests/test_mcp.py [--fast] [-v]   (about 30-80 s)
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
SERVER = SKILL / "mcp" / "server.mjs"
MONITOR = SKILL / "mcp" / "progress-monitor.mjs"
CLIENT = TESTS_DIR / "fixtures" / "mcp_client.mjs"
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
NODE = shutil.which("node")
HOME = showtime_home()
EXPECTED_TOOLS = {"doctor", "status", "new_project", "render", "check", "snap", "qa", "voice_say", "voice_script",
                  "transcribe", "audio_compose", "audio_sfx", "audio_mix", "audio_search", "export_html",
                  "studio_open", "studio_feedback", "deliver_exports"}
SETTINGS_VARS = ("SHOWTIME_VOICE", "SHOWTIME_LANG", "SHOWTIME_OPEN_BROWSER", "SHOWTIME_MAX_WORKERS", "SHOWTIME_THREADS",
                 "SHOWTIME_SOUND")


def clean_env(**extra) -> dict:
    """The test environment without any user settings leaking in."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("SHOWTIME_OPT_") or k in SETTINGS_VARS:
            env.pop(k)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def mcp(steps, cwd, mode="legacy", env=None, timeout=300, client=None):
    plan = {"server": str(SERVER), "cwd": str(cwd), "mode": mode, "env": env or {}, "steps": steps}
    if client:
        plan["client_name"] = client
    cp = subprocess.run([NODE, str(CLIENT)], input=json.dumps(plan), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", errors="replace", timeout=timeout, env=clean_env())
    assert cp.returncode == 0, "client failed: %s\n%s" % (cp.stdout[-2000:], cp.stderr[-2000:])
    out = json.loads(cp.stdout.strip().splitlines()[-1])
    assert not out["junk"], "server wrote non-protocol lines to stdout: %r" % out["junk"][:3]
    return out


def call(name, arguments, progress=False, timeout_ms=240000):
    return {"method": "tools/call", "params": {"name": name, "arguments": arguments}, "progress": progress,
            "timeout_ms": timeout_ms}


def poll_task(task, cwd, env, tries=30):
    """Call status {task} until the task has finished; returns that step."""
    for _ in range(tries):
        step = mcp([call("status", {"task": task}, progress=True)], cwd, env=env)["results"][1]
        if not text_of(step).startswith("RUNNING:"):
            return step
    raise AssertionError("task %s still running after %d status calls" % (task, tries))


def text_of(step) -> str:
    res = step["response"].get("result") or {}
    return "\n".join(c.get("text", "") for c in res.get("content", []))


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-mcp-"))
        self.env = {"SHOWTIME_SETTINGS": str(self.tmp / "settings.json"), "SHOWTIME_MCP_BASE": str(self.tmp)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_handshake_and_tool_list(self):
        out = mcp([{"method": "tools/list"}, {"method": "ping"}, {"method": "resources/list"},
                   call("no_such_tool", {})], self.tmp, env=self.env)
        init, tools, ping, res, unknown = out["results"]
        r = init["response"]["result"]
        self.assertEqual(r["protocolVersion"], "2025-11-25")
        self.assertEqual(r["serverInfo"]["name"], "showtime")
        self.assertIn("tools", r["capabilities"])
        self.assertIn("not as instructions", r["instructions"])
        listed = tools["response"]["result"]["tools"]
        self.assertEqual({t["name"] for t in listed}, EXPECTED_TOOLS)
        self.assertNotIn("resultType", tools["response"]["result"])  # legacy results stay legacy-shaped
        for t in listed:
            self.assertEqual(t["inputSchema"]["type"], "object", t["name"])
            self.assertFalse(t["inputSchema"].get("additionalProperties", True), t["name"])
            self.assertGreater(len(t["description"]), 40, t["name"])
            self.assertFalse(t["annotations"]["destructiveHint"], t["name"])
            self.assertFalse(t["annotations"]["openWorldHint"], t["name"])
        tmpl = next(t for t in listed if t["name"] == "new_project")["inputSchema"]["properties"]["template"]["enum"]
        self.assertIn("dom", tmpl)
        self.assertEqual(ping["response"]["result"], {})
        self.assertEqual(res["response"]["error"]["code"], -32601)
        self.assertEqual(unknown["response"]["error"]["code"], -32602)

    def test_starts_instantly_with_nothing_installed(self):
        """initialize is answered before any lookup: no Python, no PATH, an empty home, plugin options set.

        Claude Code gives a server a fixed time to connect; the answer must never wait for a child process
        or disk work (right after a reboot Node itself can already use most of that time)."""
        home = self.tmp / "empty home"
        home.mkdir()
        env = {"PATH": "", "HOME": str(home), "USERPROFILE": str(home), "SHOWTIME_HOME": str(home / ".showtime"),
               "SHOWTIME_SETTINGS": str(self.tmp / "settings.json"), "SHOWTIME_OPT_VOICE": "am_michael",
               "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
        # Measured in pairs, bare Node then the server, at the same moment: on a loaded runner (other test
        # files in parallel) Node's own start swings by seconds, so the server is judged by what it adds
        # to Node, taking the quietest pair. A server that did real work before answering (a child process,
        # a download, disk scans) adds that to every pair and still fails.
        best = node_best = overhead = None
        for _ in range(5):
            t0 = time.perf_counter()
            subprocess.run([NODE, "-e", "0"], env=env, cwd=str(self.tmp), check=True)
            node_dt = time.perf_counter() - t0
            t0 = time.perf_counter()
            p = subprocess.Popen([NODE, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=env, cwd=str(self.tmp))
            try:
                p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-11-25"}}) + "\n").encode())
                p.stdin.flush()
                line = p.stdout.readline()
                dt = time.perf_counter() - t0
                p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n").encode())
                p.stdin.flush()
                tools = json.loads(p.stdout.readline())["result"]["tools"]
            finally:
                p.stdin.close()
                p.wait(timeout=30)
                err = p.stderr.read().decode("utf-8", "replace")
                p.stdout.close()
                p.stderr.close()
            r = json.loads(line)["result"]
            self.assertEqual(r["serverInfo"]["name"], "showtime")
            self.assertRegex(r["serverInfo"]["version"], r"^\d+\.\d+")
            self.assertEqual({t["name"] for t in tools}, EXPECTED_TOOLS)
            self.assertEqual(p.returncode, 0, err)
            best = dt if best is None else min(best, dt)
            node_best = node_dt if node_best is None else min(node_best, node_dt)
            overhead = dt - node_dt if overhead is None else min(overhead, dt - node_dt)
        # the server may add parsing its own file (a few ms) plus scheduling noise; more means it did work
        allowed = max(0.2, 0.25 * node_best)
        print("\n  MCP cold start: initialize answered %.0f ms after spawn (best of 5); bare node %.0f ms; the server "
              "adds %.0f ms (allowed %.0f ms)" % (best * 1000, node_best * 1000, overhead * 1000, allowed * 1000),
              file=sys.stderr)
        self.assertLess(overhead, allowed, "the server should answer initialize at once: it adds %.0f ms to Node's own "
                        "start (allowed %.0f ms)" % (overhead * 1000, allowed * 1000))
        if node_best < 0.5:   # an idle machine: the product promise itself
            self.assertLess(best, 2.0, "initialize must be answered within 2 s of spawn")
        # the plugin options were still saved (after the handshake)
        saved = json.loads((self.tmp / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.get("voice"), "am_michael")

    def test_modern_per_request_metadata(self):
        out = mcp([{"method": "server/discover"}, {"method": "tools/list"},
                   {"method": "tools/list", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01"}}}],
                  self.tmp, mode="modern", env=self.env)
        disc, tools, bad = out["results"]
        d = disc["response"]["result"]
        self.assertEqual(d["resultType"], "complete")
        self.assertIn("2026-07-28", d["supportedVersions"])
        self.assertIn("2025-11-25", d["supportedVersions"])
        self.assertEqual(d["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "showtime")
        self.assertEqual(tools["response"]["result"]["resultType"], "complete")
        for r in (d, tools["response"]["result"]):  # cacheable results carry caching hints
            self.assertGreaterEqual(r["ttlMs"], 0)
            self.assertIn(r["cacheScope"], ("public", "private"))
        self.assertEqual(len(tools["response"]["result"]["tools"]), len(EXPECTED_TOOLS))
        err = bad["response"]["error"]
        self.assertEqual(err["code"], -32022)
        self.assertEqual(err["data"]["requested"], "1900-01-01")
        self.assertIn("2026-07-28", err["data"]["supported"])

    def test_input_validation_is_a_tool_error(self):
        steps = [
            call("render", {"project": str(self.tmp / "missing")}),
            call("render", {"project": str(self.tmp), "colour": "red"}),
            call("new_project", {"template": "../../etc", "dir": "x"}),
            call("qa", {"platform": "myspace"}),
            call("voice_say", {"text": "   "}),
            call("audio_sfx", {"type": "whoosh; rm -rf ~"}),
            call("snap", {"target": str(self.tmp), "at": []}),
        ]
        out = mcp(steps, self.tmp, env=self.env)
        for step, want in zip(out["results"][1:], ["does not exist", "unknown argument", "one of", "one of", "empty",
                                                     "expected form", "non-empty"]):
            res = step["response"]["result"]
            self.assertTrue(res["isError"], step)
            self.assertIn(want, text_of(step))
        self.assertFalse(any(self.tmp.iterdir()), "a rejected call must not write anything")


    def test_audio_search_produced_catalog(self):
        """audio_search with catalog=true or a use searches the produced-music catalog (no download)."""
        out = mcp([call("audio_search", {"catalog": True, "words": "hands", "limit": 3}),
                   call("audio_search", {"use": "launch", "limit": 3}),
                   call("audio_search", {"use": "launch; rm -rf ~"})], self.tmp, env=self.env)["results"]
        self.assertIn("buckley-with-these-hands", text_of(out[1]))
        rows = [l for l in text_of(out[2]).splitlines() if re.match(r"^[a-z0-9]+(-[a-z0-9]+)+ +\d+:\d\d ", l)]
        self.assertEqual(len(rows), 3, text_of(out[2]))
        self.assertTrue(out[3]["response"]["result"]["isError"])

    def test_batch2_arguments_and_export_files(self):
        """20.12: render takes page/alpha, export_html controls/autoplay_muted/loop/folder/job, deliver_exports
        per-target caps and lufs; its Files: list names the files it wrote (loops included), not the master."""
        out = mcp([{"method": "tools/list"}], self.tmp, env=self.env)
        props = {t["name"]: t["inputSchema"]["properties"] for t in out["results"][1]["response"]["result"]["tools"]}
        self.assertTrue({"page", "alpha"} <= set(props["render"]))
        self.assertIn("animation", props["render"]["alpha"]["enum"])
        self.assertTrue({"controls", "autoplay_muted", "loop", "folder", "job"} <= set(props["export_html"]))
        self.assertTrue({"max_mb_per_target", "lufs"} <= set(props["deliver_exports"]))
        bad = mcp([call("render", {"project": str(self.tmp), "page": "../x.html"})], self.tmp, env=self.env)["results"][1]
        self.assertTrue(bad["response"]["result"]["isError"])
        from st import ff
        video = self.tmp / "m" / "final.mp4"
        video.parent.mkdir()
        ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       str(video)])
        step = mcp([call("deliver_exports", {"video": str(video), "targets": ["webp-small", "gif-small"],
                                             "max_mb_per_target": {"gif-small": 1}})], self.tmp, env=self.env)["results"][1]
        res = step["response"]["result"]
        self.assertFalse(res["isError"], text_of(step))
        files = res["_meta"]["showtime/result"]["files"]
        names = sorted(Path(f).name for f in files)
        self.assertEqual(names, ["final.loop-small-1mb.gif", "final.loop-small.webp"], text_of(step))
        self.assertNotIn(str(video), files)


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-mcp-set-"))
        self.file = self.tmp / "plugin-settings.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def launcher_settings(self, **env):
        cp = subprocess.run([sys.executable, str(LAUNCHER), "version", "--json"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=60,
                            env=clean_env(SHOWTIME_SETTINGS=self.file, **env))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout)["settings"]

    def test_user_config_reaches_the_cli(self):
        # what Claude Code substitutes into the plugin.json mcpServers "env" from the plugin's userConfig
        opts = {"SHOWTIME_OPT_VOICE": "am_michael", "SHOWTIME_OPT_LANGUAGE": "en", "SHOWTIME_OPT_OPEN_BROWSER": "true",
                "SHOWTIME_OPT_MAX_WORKERS": "2", "SHOWTIME_OPT_HOME": "${user_config.home}",
                "SHOWTIME_SETTINGS": str(self.file)}
        mcp([{"method": "ping"}], self.tmp, env=opts)
        saved = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in saved.items() if not k.startswith("_")},
                         {"voice": "am_michael", "language": "en", "open_browser": True, "max_workers": 2})
        eff = self.launcher_settings()["effective"]
        self.assertEqual(eff.get("SHOWTIME_VOICE"), "am_michael")
        self.assertEqual(eff.get("SHOWTIME_OPEN_BROWSER"), "1")
        self.assertEqual(eff.get("SHOWTIME_MAX_WORKERS"), "2")
        self.assertEqual(eff.get("SHOWTIME_THREADS"), "2")
        # an environment variable beats the saved setting
        self.assertEqual(self.launcher_settings(SHOWTIME_VOICE="bf_emma")["effective"]["SHOWTIME_VOICE"], "bf_emma")
        # the default voice follows the setting, and a request in another language keeps its own default
        code = ("import os,sys; sys.path.insert(0, %r); from st.launcher import build_env, showtime_home; "
                "os.environ.update(build_env(showtime_home())); from st.voice import voices; "
                "print(voices.resolve(None).name, voices.resolve(None, 'es').name, voices.resolve('bf_emma').name)"
                % str(SKILL / "lib"))
        cp = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=60, env=clean_env(SHOWTIME_SETTINGS=self.file))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stdout.split(), ["am_michael", "ef_dora", "bf_emma"])
        # clearing the options in /config clears them here too; unset placeholders never become values
        mcp([{"method": "ping"}], self.tmp, env={k: ("" if k != "SHOWTIME_SETTINGS" else v) for k, v in opts.items()})
        saved = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in saved.items() if not k.startswith("_")}, {})
        self.assertEqual(self.launcher_settings()["effective"], {})

    def test_home_setting_moves_the_home(self):
        other = self.tmp / "st home"
        mcp([{"method": "ping"}], self.tmp, env={"SHOWTIME_OPT_HOME": str(other), "SHOWTIME_SETTINGS": str(self.file)})
        cp = subprocess.run([sys.executable, str(LAUNCHER), "version", "--json"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=60,
                            env={k: v for k, v in clean_env(SHOWTIME_SETTINGS=self.file).items() if k != "SHOWTIME_HOME"})
        self.assertEqual(Path(json.loads(cp.stdout)["home"]), other)

    def test_other_clients_do_not_touch_settings(self):
        mcp([{"method": "ping"}], self.tmp, env={"SHOWTIME_SETTINGS": str(self.file)})
        self.assertFalse(self.file.exists(), "a server started without plugin options must not write settings")


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestFlow(unittest.TestCase):
    """doctor -> new_project -> render (preview) -> qa, through the MCP server."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st mcp flow-"))  # a space in the path on purpose
        # the one-call results below (a slow runner may need more than the default 20 s before a task id)
        self.env = {"SHOWTIME_SETTINGS": str(self.tmp / "settings.json"), "SHOWTIME_MCP_BASE": str(self.tmp),
                    "SHOWTIME_MCP_WAIT": "none"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_doctor_new_render_qa(self):
        ready = plat.venv_python(HOME / "venv").exists() and (HOME / "node" / "node_modules" / "playwright").is_dir()
        steps = [call("doctor", {}), call("new_project", {"template": "dom", "dir": "tiny", "duration": 2, "size": "640x360"})]
        if ready:
            steps.append(call("render", {"project": "tiny", "preview": True}, progress=True))
        out = mcp(steps, self.tmp, env=self.env)
        doctor, new = out["results"][1:3]
        dt = text_of(doctor)
        self.assertIn("showtime doctor", dt)
        self.assertRegex(dt, r"\d+ pass")
        self.assertIn("--quick", doctor["response"]["result"]["_meta"]["showtime/result"]["command"])
        if not ready:
            self.assertTrue(doctor["response"]["result"]["isError"] or "setup" in dt)
            print("  (render + qa skipped: run `showtime setup` for the browser tools)", file=sys.stderr)
            return
        self.assertFalse(new["response"]["result"]["isError"], text_of(new))
        proj = self.tmp / "tiny"
        cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["width"], cfg["height"], cfg["duration"]), (640, 360, 2.0))
        render = out["results"][3]
        res = render["response"]["result"]
        self.assertFalse(res["isError"], text_of(render))
        self.assertTrue(text_of(render).startswith("OK: showtime render"))
        self.assertNotIn("structuredContent", res, "the text summary is what the model should see")
        self.assertIn("Files:", text_of(render))
        videos = [f for f in res["_meta"]["showtime/result"]["files"] if f.endswith(".mp4")]
        self.assertTrue(videos, text_of(render))
        video = Path(videos[0])
        self.assertTrue(video.is_file() and video.stat().st_size > 10000)
        self.assertTrue(str(video.resolve()).startswith(str(self.tmp.resolve())), "outputs land in the project folder")
        self.assertGreaterEqual(len(render["progress"]), 2, "progress notifications while rendering")
        nums = [p["progress"] for p in render["progress"]]
        self.assertEqual(nums, sorted(set(nums)), "progress must increase")
        self.assertTrue(any("frames" in p.get("message", "") for p in render["progress"]), render["progress"])
        self.assertLess(len(text_of(render)), 9000, "tool text stays short")

        qa = mcp([call("qa", {"video": str(video)})], self.tmp, env=self.env)["results"][1]
        qt = text_of(qa)
        self.assertIn("verdict:", qt)
        self.assertNotIn("verdict: FAIL", qt)
        self.assertTrue(any(f.endswith("qa.json") for f in qa["response"]["result"]["_meta"]["showtime/result"]["files"]), qt)

        # README loops through the tool: from/to/width/fps reach `deliver exports`
        lp = mcp([call("deliver_exports", {"video": str(video), "targets": ["gif-small"], "from": 0.5, "to": 1.5,
                                           "width": 160, "fps": 10})], self.tmp, env=self.env)["results"][1]
        self.assertFalse(lp["response"]["result"]["isError"], text_of(lp))
        gif = video.parent / "exports" / (video.stem + ".loop-small.gif")
        self.assertTrue(gif.is_file(), text_of(lp))
        self.assertEqual(int.from_bytes(gif.read_bytes()[6:8], "little"), 160)

        # the same render as a task: a task id at once, then status until the result (any host)
        first = mcp([call("render", {"project": "tiny", "preview": True, "background": True}, progress=True)],
                    self.tmp, env=self.env)["results"][1]
        res = first["response"]["result"]
        self.assertTrue(text_of(first).startswith("RUNNING: showtime render"), text_of(first))
        task = res["_meta"]["showtime/result"]["task"]
        final = poll_task(task, self.tmp, self.env)
        fres = final["response"]["result"]
        self.assertFalse(fres["isError"], text_of(final))
        self.assertTrue(text_of(final).startswith("OK: showtime render"), text_of(final))
        self.assertEqual(fres["_meta"]["showtime/result"]["task"], task)
        self.assertTrue(any(f.endswith(".mp4") for f in fres["_meta"]["showtime/result"]["files"]), text_of(final))


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestAnyHost(unittest.TestCase):
    """What another host gets: unexpanded variables, a server started in the plugin folder, tool-call
    limits (task ids from long tools, the status tool), Claude Code keeping one-call results."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-mcp-any-")).resolve()
        self.env = {"SHOWTIME_SETTINGS": str(self.tmp / "settings.json"), "SHOWTIME_HOME": str(self.tmp / "home"),
                    "SHOWTIME_MCP_BASE": "${CLAUDE_PROJECT_DIR}", "CLAUDE_PROJECT_DIR": "${CLAUDE_PROJECT_DIR}",
                    "SHOWTIME_OPT_VOICE": "${user_config.voice}", "SHOWTIME_OPT_HOME": "${user_config.home}",
                    "SHOWTIME_OPT_MAX_WORKERS": "${user_config.max_workers}"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def node_eval(self, expr, cwd=None, **env):
        code = ("import(%s).then((m) => { process.stdout.write(JSON.stringify(%s)); })"
                % (json.dumps(SERVER.as_uri()), expr))
        cp = subprocess.run([NODE, "--input-type=module", "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=60, cwd=str(cwd or self.tmp), env=dict(clean_env(), **env))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout)

    def test_fallbacks(self):
        t = json.dumps(str(self.tmp))
        got = self.node_eval("[m.baseDir({SHOWTIME_MCP_BASE: '${CLAUDE_PROJECT_DIR}', CLAUDE_PROJECT_DIR: ''}, %s),"
                             " m.baseDir({SHOWTIME_MCP_BASE: %s}, '/'),"
                             " m.baseDir({PWD: %s}, %s),"
                             " m.waitLimitMs({}, false), m.waitLimitMs({}, true), m.waitLimitMs({SHOWTIME_MCP_WAIT: '0'}, true),"
                             " m.waitLimitMs({SHOWTIME_MCP_WAIT: 'none'}, false), m.waitLimitMs({SHOWTIME_MCP_WAIT: '${x}'}, false),"
                             " m.waitLimitMs({SHOWTIME_MCP_WAIT: '45'}, false)]"
                             % (t, t, t, json.dumps(str(REPO))))
        base_ph, base_env, base_plugin, w_def, w_claude, w0, w_none, w_ph, w45 = got
        self.assertEqual(Path(base_ph), self.tmp, "an unexpanded project variable falls back to the working folder")
        self.assertEqual(Path(base_env), self.tmp)
        self.assertEqual(Path(base_plugin), self.tmp, "started inside the plugin: the folder the host started from")
        self.assertEqual(w_def, 20000)
        self.assertIsNone(w_claude)            # Infinity: JSON null
        self.assertEqual((w0, w_ph, w45), (0, 20000, 45000))
        self.assertIsNone(w_none)

    def test_project_home_inside_the_user_folder(self):
        """Windows keeps temp folders inside the user's folder: a project's .showtime there is still found."""
        user = self.tmp / "user"
        proj = user / "AppData" / "Local" / "Temp" / "proj"
        (proj / ".showtime").mkdir(parents=True)
        (proj / ".showtime" / "skill-path").write_text(str(SKILL) + "\n", encoding="utf-8")
        (proj / "a").mkdir()
        (user / ".showtime").mkdir()
        (user / ".showtime" / "skill-path").write_text(str(SKILL) + "\n", encoding="utf-8")
        env = {"HOME": str(user), "USERPROFILE": str(user)}
        for k in ("SHOWTIME_HOME", "SHOWTIME_MCP_BASE", "CLAUDE_PROJECT_DIR"):
            env[k] = ""
        got = self.node_eval("m.showtimeHome()", cwd=proj / "a", SHOWTIME_SETTINGS=str(self.tmp / "s.json"), **env)
        self.assertEqual(Path(got).resolve(), (proj / ".showtime").resolve())
        got = self.node_eval("m.showtimeHome()", cwd=user / "AppData", SHOWTIME_SETTINGS=str(self.tmp / "s.json"), **env)
        self.assertEqual(Path(got).resolve(), (user / ".showtime").resolve())

    def test_placeholders_start_fast_and_write_nothing(self):
        env = dict(self.env, PATH="")
        t0 = time.perf_counter()
        p = subprocess.Popen([NODE, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(clean_env(), **env), cwd=str(self.tmp))
        try:
            p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                       "params": {"protocolVersion": "2025-11-25"}}) + "\n").encode())
            p.stdin.flush()
            line = p.stdout.readline()
            dt = time.perf_counter() - t0
        finally:
            p.stdin.close()
            p.wait(timeout=30)
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(json.loads(line)["result"]["serverInfo"]["name"], "showtime")
        self.assertLess(dt, 2.0, "an MCP server must answer within 2 s (some hosts allow 10 s in all)")
        self.assertFalse((self.tmp / "settings.json").exists(), "unexpanded options are not settings")
        self.assertFalse((self.tmp / "home").exists(), "starting downloads and writes nothing")

    def test_long_tool_task_ids(self):
        # background: true -> a task id at once; status {task} (or {job: id}) -> the full result
        out = mcp([{"method": "tools/list"}, call("doctor", {"full": True, "background": True}, progress=True)],
                  self.tmp, env=self.env)
        tools = {t["name"]: t for t in out["results"][1]["response"]["result"]["tools"]}
        self.assertIn("task", tools["status"]["inputSchema"]["properties"])
        for name in ("render", "transcribe", "audio_compose", "voice_script", "qa"):
            self.assertIn("background", tools[name]["inputSchema"]["properties"], name)
        first = out["results"][2]
        self.assertFalse(first["response"]["result"]["isError"], text_of(first))
        self.assertTrue(text_of(first).startswith("RUNNING: showtime doctor"), text_of(first))
        meta = first["response"]["result"]["_meta"]["showtime/result"]
        self.assertTrue(meta["running"])
        task = meta["task"]
        self.assertTrue((self.tmp / "home" / "runs" / task / "run.json").is_file())
        self.assertIn('{"task": "%s"}' % task, text_of(first))
        final = poll_task(task, self.tmp, self.env)
        self.assertIn("showtime doctor", text_of(final))
        self.assertRegex(text_of(final), r"^(OK|FAILED \(exit 1\)): showtime doctor")
        self.assertEqual(final["response"]["result"]["_meta"]["showtime/result"]["task"], task)
        again = mcp([call("status", {"job": task}), call("status", {"task": "render-20200101-000000-abcd"})],
                    self.tmp, env=self.env)["results"][1:]
        self.assertEqual(text_of(again[0]).splitlines()[0], text_of(final).splitlines()[0])
        self.assertTrue(again[1]["response"]["result"]["isError"])
        self.assertIn("no task", text_of(again[1]))
        # a host with a short limit: the call itself turns into a task (SHOWTIME_MCP_WAIT=0 here)
        step = mcp([call("doctor", {"full": True})], self.tmp, env=dict(self.env, SHOWTIME_MCP_WAIT="0"))["results"][1]
        self.assertTrue(text_of(step).startswith("RUNNING:"), text_of(step))
        poll_task(step["response"]["result"]["_meta"]["showtime/result"]["task"], self.tmp, self.env)
        # Claude Code waits as long as a tool needs: one call, one result, as before
        step = mcp([call("doctor", {"full": True})], self.tmp, env=dict(self.env, SHOWTIME_MCP_WAIT=""),
                   client="claude-code")["results"][1]
        self.assertFalse(text_of(step).startswith("RUNNING:"), text_of(step))
        self.assertIn("showtime doctor", text_of(step))


class TestPluginWiring(unittest.TestCase):
    def test_manifest_files(self):
        manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        # declared inline in the manifest: a root .mcp.json would also be offered as a project server
        # to anyone who opens the repo itself, where ${CLAUDE_PLUGIN_ROOT} does not resolve
        self.assertFalse((REPO / ".mcp.json").exists(), "the MCP server lives in plugin.json, not a root .mcp.json")
        srv = manifest["mcpServers"]["showtime"]
        self.assertEqual(srv["command"], "node")
        self.assertEqual(srv.get("type", "stdio"), "stdio")
        self.assertEqual(srv["env"].get("SHOWTIME_MCP_BASE"), "${CLAUDE_PROJECT_DIR}")
        self.assertEqual(srv["args"], ["${CLAUDE_PLUGIN_ROOT}/skills/showtime/mcp/server.mjs"])
        self.assertTrue(SERVER.is_file())
        for key, opt in manifest["userConfig"].items():
            self.assertIn("default", opt, "every option has a default, so installing needs no answers: " + key)
            self.assertEqual(srv["env"].get("SHOWTIME_OPT_" + key.upper()), "${user_config.%s}" % key, key)
        monitors = json.loads((REPO / "monitors" / "monitors.json").read_text(encoding="utf-8"))
        self.assertEqual(len(monitors), 1)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/showtime/mcp/progress-monitor.mjs", monitors[0]["command"])
        self.assertNotIn("user_config", monitors[0]["command"])
        self.assertTrue(MONITOR.is_file())

    def test_skill_shim_and_no_plugin_bin(self):
        # claude.ai and Cowork refuse plugins with a top-level bin/; SKILL.md runs the skill's own shim
        self.assertFalse((REPO / "bin").exists(), "no top-level bin/ in the plugin")
        skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('"<folder>/bin/showtime" <cmd>', skill_md)   # any host (test_portable.py runs it)
        self.assertIn("`${CLAUDE_SKILL_DIR}`", skill_md)              # Claude Code fills the folder in
        if os.name == "nt":
            cmd = ["cmd", "/c", str(SKILL / "bin" / "showtime.cmd"), "version"]
        else:
            cmd = ["sh", str(SKILL / "bin" / "showtime"), "version"]
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=60,
                            env=build_env(HOME))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertRegex(cp.stdout, r"^showtime \d+\.\d+\.\d+")


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestMonitor(unittest.TestCase):
    def test_reports_long_jobs_only(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-mon-"))
        try:
            logs = tmp / "logs"
            logs.mkdir()
            now = int(time.time() * 1000)
            ev = []

            def add(pid, dt, **kw):
                ev.append(dict({"ts": now + dt, "pid": pid, "cmd": "showtime render", "cwd": str(tmp)}, **kw))
            add(11, 0, ev="start")                                     # a short job: silent
            add(11, 10, ev="progress", label="frames", done=60, total=60, pct=100)
            add(11, 2000, ev="end", code=0, seconds=2)
            add(22, 0, ev="start")                                     # a long job: reported
            add(22, 70000, ev="progress", label="frames", done=450, total=900, pct=50, eta_s=70)
            add(22, 140000, ev="output", path=str(tmp / "final.mp4"))
            add(22, 140010, ev="end", code=0, seconds=140)
            add(33, 0, ev="start", cmd="showtime transcribe")          # a long failure
            add(33, 90000, ev="end", code=1, seconds=90, error="model not installed")
            (logs / "progress.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev), encoding="utf-8")
            cp = subprocess.run([NODE, str(MONITOR), "--once", "--quiet-s", "45"], cwd=str(tmp), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", timeout=60, env=clean_env(SHOWTIME_HOME=tmp))
            self.assertEqual(cp.returncode, 0, cp.stderr)
            lines = cp.stdout.strip().splitlines()
            self.assertEqual(len(lines), 2, lines)
            self.assertIn("showtime render finished in 2 min 20 s", lines[0])
            self.assertIn("final.mp4", lines[0])
            self.assertIn("showtime transcribe failed after 1 min 30 s (exit 1): model not installed", lines[1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    t0 = time.time()
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_mcp: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
