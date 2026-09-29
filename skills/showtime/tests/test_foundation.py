#!/usr/bin/env python3
"""Foundation smoke tests: launcher, platform helpers, ffmpeg resolver and
escaping, probe/encode presets, deliver (poster/exports/thumb), setup
manifest integrity and `showtime doctor`.

Stdlib only (runs under the venv Python via tests/run_all.py, or any 3.8+).
usage: python tests/test_foundation.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path, PureWindowsPath

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import common, ff  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())


def showtime(*args, check=True, timeout=600):
    """Run the launcher like bin/showtime would, capturing output."""
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-2000:], cp.stderr[-2000:]))
    return cp


def make_clip(path, seconds=2.0, size="640x360", fps=30, audio=True, extra=()):
    args = ["-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d:duration=%s" % (size, fps, seconds)]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%s:sample_rate=48000" % seconds]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    ff.run_ffmpeg(args + list(extra) + [str(path)])
    return Path(path)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-found-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)


# --------------------------------------------------------------------------

class TestIsolation(unittest.TestCase):
    def test_tests_run_outside_the_repository(self):
        """Outputs that default to ./showtime-out must never land in the repository (tests/_isolate.py)."""
        cwd = Path.cwd().resolve()
        root = SKILL.resolve().parent.parent
        self.assertFalse(cwd == root or root in cwd.parents, "tests run from %s, inside the repository" % cwd)
        import run_all  # the runner gives every test file its own scratch folder too
        self.assertIn("cwd=scratch", Path(run_all.__file__).read_text(encoding="utf-8"))


class TestFilterPath(unittest.TestCase):
    """Pure escaping rules (Windows cases run on every OS)."""

    def test_windows_drive_path(self):
        self.assertEqual(plat.filter_path(r"C:\Users\me\subs.ass"), r"C\\:/Users/me/subs.ass")

    def test_windows_pure_path_object(self):
        p = PureWindowsPath(r"D:\clips\my video\a.srt")
        self.assertEqual(plat.filter_path(p), r"D\\:/clips/my video/a.srt")

    def test_windows_specials(self):
        got = plat.filter_path(r"C:\it's\[a],b;c=d.ass")
        # level 1 escapes \ ' : = ; level 2 escapes \ ' [ ] , ;
        self.assertEqual(got, r"C\\:/it\\\'s/\[a\]\,b\;c\\=d.ass")

    def test_unc_path(self):
        self.assertEqual(plat.filter_path(r"\\server\share\x.ass"), "//server/share/x.ass")

    def test_posix_path_with_colon(self):
        self.assertEqual(plat.filter_path("/tmp/a:b/c.srt", absolute=False), r"/tmp/a\\:b/c.srt")

    def test_edge_whitespace(self):
        self.assertEqual(plat.filter_value(" x "), r"\\ x\\\ ")

    def test_concat_list_quote(self):
        self.assertEqual(plat.concat_list_path(r"C:\a\it's.mp4"), r"'C:/a/it'\''s.mp4'")


class TestPlatform(unittest.TestCase):
    def test_key_and_exe(self):
        self.assertRegex(plat.platform_key(), r"^(mac|win|linux)-(x64|arm64|\w+)$")
        self.assertEqual(plat.exe("ffmpeg"), "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        self.assertEqual(plat.exe("x.exe"), "x.exe")

    def test_windows_on_arm_uses_x64_binaries(self):
        # Windows 11 on Arm runs x64 programs through its emulation: ffmpeg, tools and the venv come from win-x64
        self.assertEqual(plat.binary_key("win-arm64"), "win-x64")
        for key in ("win-x64", "mac-arm64", "mac-x64", "linux-x64", "linux-arm64"):
            self.assertEqual(plat.binary_key(key), key)
        table = {"win-x64": ["x64 build"], "mac-arm64": ["mac build"]}
        self.assertEqual(plat.pick_for_platform(table, "win-arm64"), ["x64 build"])
        self.assertEqual(plat.pick_for_platform(table, "mac-arm64"), ["mac build"])
        self.assertIsNone(plat.pick_for_platform(table, "linux-arm64"))   # no emulation fallback on Linux
        self.assertEqual(plat.pick_for_platform({"win-arm64": ["native"], "win-x64": ["x64"]}, "win-arm64"), ["native"])
        if os.name != "nt":
            self.assertFalse(plat._win_native_arm64())

    def test_ffmpeg_does_not_run_reason(self):
        # setup and doctor say why an ffmpeg does not start instead of "(does not run)"
        v, why = ff._run_version(str(Path(tempfile.gettempdir()) / "no-such-ffmpeg-w9.exe"))
        self.assertIsNone(v)
        self.assertIn("cannot start", why)
        self.assertEqual(ff.exit_reason(-1073741515, windows=True), "exit code 0xC0000135 (a DLL it needs is missing)")
        self.assertEqual(ff.exit_reason(3221225501, windows=True), "exit code 0xC000001D (illegal instruction: CPU too old)")
        self.assertEqual(ff.exit_reason(3, windows=True), "exit code 3")
        self.assertEqual(ff.exit_reason(-11, windows=False), "exit code -11")
        if os.name != "nt":
            d = Path(tempfile.mkdtemp(prefix="st-ffwhy-"))
            try:
                bad = d / "ffmpeg"
                bad.write_text("#!/bin/sh\necho 'cannot load libfoo' >&2\nexit 3\n")
                bad.chmod(0o755)
                v, why = ff._run_version(str(bad))
                self.assertIsNone(v)
                self.assertEqual(why, "exit code 3: cannot load libfoo")
                slow = d / "ffslow"
                slow.write_text("#!/bin/sh\nsleep 5\n")
                slow.chmod(0o755)
                self.assertIn("no answer within 1 s", ff._run_version(str(slow), timeout=1)[1])
            finally:
                shutil.rmtree(str(d), ignore_errors=True)

    def test_setup_on_windows_arm64(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("st_setup_w9", str(SKILL / "setup" / "setup.py"))
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        self.assertEqual(setup.python_request("win-arm64"), "cpython-%s-windows-x86_64-none" % setup.PY_VERSION)
        for key in ("win-x64", "mac-arm64", "linux-arm64", "linux-x64"):
            self.assertEqual(setup.python_request(key), setup.PY_VERSION)
        self.assertEqual(setup.VENV_PLATFORM.get("win-arm64"), "win-amd64")
        man = setup.load_manifest()
        # every platform the README lists gets an ffmpeg build (Windows on Arm has a native one)
        for key in ("mac-arm64", "mac-x64", "win-x64", "win-arm64", "linux-x64", "linux-arm64"):
            self.assertTrue(plat.pick_for_platform(man["ffmpeg"], key), key)
        item = {"id": "t", "platform_files": {"win-x64": [{"url": "https://x/y.exe", "size": 7, "dest": "bin/y.exe"}]}}
        self.assertEqual(setup.item_size(item, "win-arm64"), 7)
        self.assertEqual(man["ffmpeg"]["win-arm64"][0]["id"], plat.pick_for_platform(man["ffmpeg"], "win-arm64")[0]["id"])
        self.assertIsNone(setup.item_files(item, "linux-arm64"))
        # ffmpeg: Windows on Arm tries its native build first, then the x64 builds (run under emulation)
        ids = [c["id"] for c in setup.ffmpeg_candidates(man, "win-arm64")]
        self.assertEqual(ids[:len(man["ffmpeg"]["win-arm64"])], [c["id"] for c in man["ffmpeg"]["win-arm64"]])
        self.assertEqual(ids[len(man["ffmpeg"]["win-arm64"]):], [c["id"] for c in man["ffmpeg"]["win-x64"]])
        for key in ("win-x64", "linux-arm64", "mac-arm64"):
            self.assertEqual(setup.ffmpeg_candidates(man, key), man["ffmpeg"][key])
        # every default-tier item installs on every listed platform (no platform-only models in core)
        for key in ("mac-arm64", "mac-x64", "win-x64", "win-arm64", "linux-x64", "linux-arm64"):
            for it in setup.select_items(man, "core", []):
                self.assertIsNotNone(setup.item_files(it, key), "%s has no files for %s" % (it["id"], key))

    def test_chrome_flags(self):
        for mode in ("auto", "off"):
            flags = plat.chrome_flags(mode)
            self.assertIn("--force-color-profile=srgb", flags)
        self.assertIn("--use-angle=swiftshader", plat.chrome_flags("off"))
        self.assertIn("--use-angle=metal", plat.chrome_flags("auto", "mac"))
        self.assertIn("--use-angle=d3d11", plat.chrome_flags("auto", "windows"))

    def test_gl_display_prefix(self):
        """ManimGL needs a display: Linux servers get xvfb-run, or a fix line when it is missing."""
        self.assertEqual(plat.gl_display_prefix({}, "mac"), ([], None))
        self.assertEqual(plat.gl_display_prefix({}, "windows"), ([], None))
        self.assertEqual(plat.gl_display_prefix({"DISPLAY": ":0"}, "linux"), ([], None))
        self.assertEqual(plat.gl_display_prefix({"WAYLAND_DISPLAY": "wayland-0"}, "linux"), ([], None))
        with tempfile.TemporaryDirectory() as d:
            prefix, problem = plat.gl_display_prefix({"PATH": d}, "linux")
            self.assertEqual(prefix, [])
            self.assertIn("apt install xvfb", problem)
            if os.name != "nt":
                fake = Path(d) / "xvfb-run"
                fake.write_text("#!/bin/sh\nexec \"$@\"\n")
                fake.chmod(0o755)
                prefix, problem = plat.gl_display_prefix({"PATH": d}, "linux")
                self.assertIsNone(problem)
                self.assertEqual(prefix[:2], [str(fake), "-a"])

    def test_browsers_listing(self):
        for b in plat.find_browsers():
            self.assertTrue(os.path.isfile(b["path"]), b)


class TestCommon(TempDirCase):
    def test_output_dir_and_slug(self):
        self.assertEqual(common.slugify("Héllo, Wörld! 2026"), "hello-world-2026")
        d = common.output_dir("My Launch Video", base=self.tmp)
        self.assertRegex(d.name, r"^my-launch-video-\d{8}-\d{6}$")
        self.assertEqual(d.parent.name, "showtime-out")
        d2 = common.output_dir("My Launch Video", base=self.tmp)
        self.assertNotEqual(d, d2)

    def test_json_roundtrip_and_run(self):
        p = common.write_json(self.tmp / "a" / "x.json", {"k": [1, 2], "path": Path("/x")})
        self.assertEqual(common.read_json(p)["k"], [1, 2])
        with self.assertRaises(TypeError):
            common.run("echo hi")
        with self.assertRaises(common.RunError):
            common.run([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
        self.assertEqual(common.parse_time("1:02.5"), 62.5)


class TestWindowsText(TempDirCase):
    """Text that Windows produces: UTF-8 files with a byte-order mark (Windows PowerShell 5.1's
    Set-Content/Out-File -Encoding utf8, older Notepad) and ANSI-code-page pipes (cp1252)."""

    BOM = "﻿"

    def test_read_json_accepts_bom(self):
        p = self.tmp / "showtime.json"
        p.write_text(self.BOM + '{"width": 1920, "title": "Café"}', encoding="utf-8")
        self.assertEqual(common.read_json(p), {"width": 1920, "title": "Café"})

    def test_voice_script_heading_after_bom(self):
        from st.voice.script import load_script
        p = self.tmp / "narration.md"
        p.write_text(self.BOM + "## hero\nMeet Northwind.\n\n## features\nNaïve and simple.\n", encoding="utf-8")
        _cfg, lines = load_script(p)
        self.assertEqual([ln["id"] for ln in lines], ["hero", "features"])
        self.assertEqual(lines[0]["text"], "Meet Northwind.")
        j = self.tmp / "narration.json"
        j.write_text(self.BOM + json.dumps({"lines": [{"id": "hook", "text": "Hi."}]}), encoding="utf-8")
        self.assertEqual([ln["id"] for ln in load_script(j)[1]], ["hook"])

    def test_node_project_config_accepts_bom(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not found")
        proj = self.tmp / "proj"
        proj.mkdir()
        (proj / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
        (proj / "showtime.json").write_text(self.BOM + '{"width": 640, "height": 360, "fps": 30, "duration": 2}',
                                            encoding="utf-8")
        cli = (SKILL / "scripts" / "lib" / "cli.mjs").resolve().as_uri()
        js = ("import { resolveProject } from %r;\n"
              "const p = resolveProject(process.argv[1]);\n"
              "console.log(JSON.stringify({w: p.config.width, d: p.config.duration}));\n" % cli)
        cp = subprocess.run([node, "--input-type=module", "-e", js, str(proj)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        self.assertEqual(json.loads(cp.stdout.strip().splitlines()[-1]), {"w": 640, "d": 2})

    def test_utf8_stdio_reconfigures_ansi_pipes_on_windows(self):
        import io
        from unittest import mock
        from st import launcher
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(launcher.os, "name", "nt"):
            launcher.utf8_stdio([stream])
        self.assertEqual(stream.encoding, "utf-8")
        stream.write("→ 漢字 ±")
        stream.flush()
        self.assertEqual(stream.buffer.getvalue().decode("utf-8"), "→ 漢字 ±")
        # an explicit PYTHONIOENCODING is the user's choice
        other = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.dict(os.environ, {"PYTHONIOENCODING": "cp1252"}), mock.patch.object(launcher.os, "name", "nt"):
            launcher.utf8_stdio([other])
        self.assertEqual(other.encoding, "cp1252")

    def test_stopping_the_launcher_stops_its_child(self):
        """A host stops `showtime server` by killing the launcher. POSIX replaces the launcher with node
        (exec); on Windows node is a child and must die with it, or the server keeps its port."""
        import socket
        from urllib.parse import urlparse
        if not shutil.which("node"):
            self.skipTest("node not found")
        site = self.tmp / "site"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html><title>x</title><p>x</p>", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(LAUNCHER), "server", str(site), "--port", "0", "--json"], env=ENV,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8")
        try:
            u = urlparse(json.loads(p.stdout.readline())["url"])
            socket.create_connection((u.hostname, u.port), timeout=5).close()
        finally:
            p.terminate()
            p.wait(10)
            p.stdout.close()
        deadline = time.time() + 10
        while True:
            try:
                socket.create_connection((u.hostname, u.port), timeout=1).close()
            except OSError:
                break
            self.assertLess(time.time(), deadline, "the server outlived the launcher: port %d still open" % u.port)
            time.sleep(0.2)

    def test_null_stdin_is_not_a_terminal(self):
        """Windows reports isatty() for the NUL device: prompts must still see 'no terminal'."""
        code = "import sys; from st.common import is_terminal; print(sys.stdin.isatty(), is_terminal())"
        cp = subprocess.run([sys.executable, "-c", code], env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertTrue(cp.stdout.strip().endswith("False"), cp.stdout)

    def test_in_process_command_prints_utf8_to_a_pipe(self):
        """`showtime paths` runs inside the launcher process: with no PYTHONIOENCODING (a plain
        Windows shell) its output to a pipe must still be UTF-8, even for a non-Latin home."""
        home = self.tmp / "hé 漢字"
        env = {k: v for k, v in ENV.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
        env["SHOWTIME_HOME"] = str(home)
        cp = subprocess.run([sys.executable, str(LAUNCHER), "paths", "home"], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-2000:])
        self.assertEqual(cp.stdout.decode("utf-8").strip(), str(home))


class TestFF(TempDirCase):
    def test_resolver(self):
        info = ff.resolve(refresh=True)
        self.assertTrue(Path(info.ffmpeg).is_file())
        self.assertTrue(info.version)
        caps = ff.check_capabilities()
        self.assertEqual(caps["missing_required"], [], caps)

    def test_resolver_env_override_bad(self):
        code = ("import sys; sys.path.insert(0, %r)\nfrom st import ff\nfrom st.common import ShowtimeError\n"
                "try:\n    ff.resolve()\nexcept ShowtimeError as e:\n    print('ERR', e)\n" % str(SKILL / "lib"))
        env = dict(ENV, SHOWTIME_FFMPEG=str(self.tmp / "nope" / plat.exe("ffmpeg")))
        out = subprocess.run([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                             encoding="utf-8").stdout
        self.assertIn("ERR", out)

    def test_resolver_fallback_without_home_binary(self):
        """With an empty SHOWTIME_HOME the resolver must still find a *working* ffmpeg
        (a system one that runs, else imageio-ffmpeg) and never a broken one."""
        code = ("import sys; sys.path.insert(0, %r)\nfrom st import ff\n"
                "i = ff.resolve(); print(i.source, i.version)\n" % str(SKILL / "lib"))
        env = dict(ENV, SHOWTIME_HOME=str(self.tmp / "emptyhome"))
        env.pop("SHOWTIME_FFMPEG", None)
        cp = subprocess.run([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8")
        if cp.returncode != 0 and "no working ffmpeg" in cp.stderr:
            self.skipTest("no system ffmpeg and imageio-ffmpeg not importable in this interpreter")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertRegex(cp.stdout, r"^(system|imageio) \S+")

    def test_probe_and_rotation(self):
        clip = make_clip(self.tmp / "c.mp4", seconds=1.0, size="320x180")
        p = ff.probe(clip)
        self.assertAlmostEqual(p["duration"], 1.0, delta=0.1)
        self.assertEqual((p["width"], p["height"], p["fps"]), (320, 180, 30.0))
        self.assertTrue(p["has_audio"])
        self.assertEqual(p["audio_streams"][0]["sample_rate"], 48000)
        rot = self.tmp / "rot.mp4"
        ff.run_ffmpeg(["-display_rotation", "90", "-i", str(clip), "-c", "copy", str(rot)])
        r = ff.probe(rot)
        self.assertIn(r["rotation"], (90, 270))
        self.assertEqual((r["display_width"], r["display_height"]), (180, 320))

    def test_presets(self):
        clip = make_clip(self.tmp / "c.mp4", seconds=0.5, size="160x90")
        out = ff.encode(clip, self.tmp / "p.mp4", "preview")
        p = ff.probe(out)
        self.assertEqual(p["color_space"], "bt709")
        self.assertEqual(p["pix_fmt"], "yuv420p")
        g = ff.encode(clip, self.tmp / "p.gif", "gif", gif_width=120, gif_fps=10)
        self.assertGreater(g.stat().st_size, 1000)
        if not FAST:
            pr = ff.encode(clip, self.tmp / "a.mov", "alpha_prores")
            self.assertTrue(ff.probe(pr)["has_alpha"])
            if ff.has_encoder("libvpx-vp9"):
                ff.encode(clip, self.tmp / "a.webm", "alpha_webm")

    def test_filter_paths_with_real_ffmpeg(self):
        """subtitles=, ass=, movie= and lut3d= with a hostile directory name."""
        name = "it's [dir], a;b=c" + ("" if os.name == "nt" else ":d")
        d = self.tmp / name
        d.mkdir()
        srt = d / "sub title.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        cube = d / "id.cube"
        cube.write_text("LUT_3D_SIZE 2\n" + "".join("%d %d %d\n" % (r, g, b) for b in (0, 1) for g in (0, 1)
                                                      for r in (0, 1)), encoding="utf-8")
        png = d / "logo.png"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=16x16", "-frames:v", "1", str(png)])
        ass = d / "s.ass"
        ff.run_ffmpeg(["-i", str(srt), str(ass)])
        src = ["-f", "lavfi", "-i", "color=c=blue:s=128x72:d=0.5:r=10"]
        for vf in ("subtitles=filename=%s" % plat.filter_path(srt),
                   "subtitles=%s" % plat.filter_path(srt),
                   "ass=%s" % plat.filter_path(ass),
                   "lut3d=file=%s" % plat.filter_path(cube),
                   "movie=%s[m];[in][m]overlay" % plat.filter_path(png)):
            ff.run_ffmpeg(src + ["-vf", vf, "-f", "null", "-"])


class TestLauncher(TempDirCase):
    def test_help_version_paths(self):
        out = showtime("--help").stdout
        self.assertIn("usage: showtime", out)
        self.assertIn("doctor", out)
        self.assertIn("deliver", out)
        self.assertRegex(showtime("--version").stdout, r"^showtime \d+\.\d+\.\d+")
        paths = json.loads(showtime("paths", "--json").stdout)
        self.assertEqual(Path(paths["home"]), showtime_home())
        self.assertIn("venv_python", paths)
        bad = showtime("definitely-not-a-command", check=False)
        self.assertNotEqual(bad.returncode, 0)

    def test_posix_or_windows_shim(self):
        if os.name == "nt":
            cp = subprocess.run(["cmd", "/c", str(SKILL / "bin" / "showtime.cmd"), "--version"], env=ENV,
                                stdout=subprocess.PIPE, encoding="utf-8")
        else:
            cp = subprocess.run([str(SKILL / "bin" / "showtime"), "--version"], env=ENV,
                                stdout=subprocess.PIPE, encoding="utf-8")
        self.assertEqual(cp.returncode, 0)
        self.assertIn("showtime", cp.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX shim")
    def test_shim_finds_uv_in_its_default_folder(self):
        """No Python and uv not on PATH (installed after the app started): the shim uses ~/.local/bin/uv."""
        home = self.tmp / "fresh home"
        (home / ".local" / "bin").mkdir(parents=True)
        uv = home / ".local" / "bin" / "uv"
        uv.write_text('#!/bin/sh\necho "uv-stub $*"\n', encoding="utf-8")
        uv.chmod(0o755)
        tools = self.tmp / "tools"      # just what the shim itself needs, no python and no uv
        tools.mkdir()
        for t in ("dirname", "readlink"):
            os.symlink(shutil.which(t), str(tools / t))
        env = {"HOME": str(home), "PATH": str(tools), "SHOWTIME_HOME": str(self.tmp / "no-home")}
        cp = subprocess.run(["/bin/sh", str(SKILL / "bin" / "showtime"), "--version"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("uv-stub run --no-project --python 3.12 python", cp.stdout)
        self.assertIn("launcher.py --version", cp.stdout)
        uv.unlink()
        cp = subprocess.run(["/bin/sh", str(SKILL / "bin" / "showtime"), "--version"], env=dict(env, PATH=str(tools)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        if cp.returncode == 127:   # no uv in /opt/homebrew/bin or /usr/local/bin either
            self.assertIn("restart your coding agent", cp.stderr)

    def test_default_tool_dirs(self):
        from st import platform as plat
        home = self.tmp / "tool home"
        nvm = home / ".nvm" / "versions" / "node"
        for v in ("v18.20.7", "v22.3.0", "v9.2.0"):
            (nvm / v / "bin").mkdir(parents=True)
            f = nvm / v / "bin" / plat.exe("node")
            f.write_text("", encoding="utf-8")
            f.chmod(0o755)
        (home / ".cargo" / "bin").mkdir(parents=True)
        f = home / ".cargo" / "bin" / plat.exe("uv")
        f.write_text("", encoding="utf-8")
        f.chmod(0o755)
        old = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "NVM_DIR", "XDG_BIN_HOME")}
        try:
            os.environ.update({"HOME": str(home), "USERPROFILE": str(home)})
            for k in ("NVM_DIR", "XDG_BIN_HOME"):
                os.environ.pop(k, None)
            self.assertIn(home / ".cargo" / "bin", plat.default_tool_dirs("uv"))
            self.assertEqual(plat.find_tool("uv", path=str(self.tmp / "empty")), str(f))
            if os.name != "nt":   # nvm: the newest version, not the first listed
                self.assertIn(nvm / "v22.3.0" / "bin", plat.default_tool_dirs("node"))
                self.assertNotIn(nvm / "v18.20.7" / "bin", plat.default_tool_dirs("node"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_new_from_template(self):
        tpl = self.tmp / "templates" / "demo"
        tpl.mkdir(parents=True)
        (tpl / "README.md").write_text("# Demo template\n", encoding="utf-8")
        (tpl / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
        common.write_json(tpl / "showtime.json", {"width": 1920, "height": 1080, "fps": 30, "duration": 5,
                                                  "title": "Template"})
        env = dict(ENV, SHOWTIME_TEMPLATES=str(self.tmp / "templates"))
        run = lambda *a: subprocess.run([sys.executable, str(LAUNCHER)] + list(a), env=env,  # noqa: E731
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        lst = run("new", "--list")
        self.assertEqual(lst.returncode, 0, lst.stderr)
        self.assertIn("demo", lst.stdout)
        dest = self.tmp / "my-first-short"
        cp = run("new", "demo", str(dest), "--aspect", "9:16", "--duration", "12", "--json")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        cfg = common.read_json(dest / "showtime.json")
        self.assertEqual((cfg["width"], cfg["height"], cfg["duration"], cfg["title"]),
                         (1080, 1920, 12.0, "My First Short"))
        again = run("new", "demo", str(dest))
        self.assertNotEqual(again.returncode, 0)
        # the template's README stays in the skill (it would go stale and ship with the project)
        self.assertFalse((dest / "README.md").exists())
        self.assertTrue(json.loads(cp.stdout)["template_notes"].endswith("README.md"))
        # JSON files get normal permissions (not mkstemp's 0600)
        if os.name != "nt":
            self.assertEqual(os.stat(dest / "showtime.json").st_mode & 0o044, 0o044)

    def test_new_records_project_in_job(self):
        """ROUND3 (S7): `new <t> <dir> --job J` records the project in J; a <dir> inside a job folder is
        recorded without the flag; an unknown --job fails before anything is copied."""
        tpl = self.tmp / "templates" / "demo"
        tpl.mkdir(parents=True)
        (tpl / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
        common.write_json(tpl / "showtime.json", {"width": 1920, "height": 1080, "fps": 30, "duration": 5})
        env = dict(ENV, SHOWTIME_TEMPLATES=str(self.tmp / "templates"))
        base = self.tmp / "work"
        base.mkdir()
        run = lambda *a: subprocess.run([sys.executable, str(LAUNCHER)] + [str(x) for x in a], env=env,  # noqa: E731
                                        cwd=str(base), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        encoding="utf-8")
        cp = run("job", "init", "promo", "--json")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        job = Path(json.loads(cp.stdout)["job"])
        pointers = lambda: json.loads((job / "job.json").read_text(encoding="utf-8")).get("pointers", {})  # noqa: E731
        outside = self.tmp / "elsewhere" / "promo-project"
        cp = run("new", "demo", outside, "--job", "promo", "--json")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(Path(json.loads(cp.stdout)["job"]).resolve(), job.resolve())
        self.assertEqual(Path(pointers()["project"]).resolve(), outside.resolve())
        inside = job / "project"
        cp = run("new", "demo", inside)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("project ->", cp.stderr)
        self.assertEqual(Path(pointers()["project"]).resolve(), inside.resolve())
        self.assertIn("showtime check", (job / "SHOWTIME.md").read_text(encoding="utf-8"))
        cp = run("new", "demo", self.tmp / "never", "--job", "no-such-job")
        self.assertNotEqual(cp.returncode, 0)
        self.assertFalse((self.tmp / "never").exists())
        # outside any job and without --job: nothing to record, no complaint
        cp = run("new", "demo", self.tmp / "loose", "--json")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIsNone(json.loads(cp.stdout)["job"])

    def test_new_list_skips_non_project_folders(self):
        root = self.tmp / "templates"
        (root / "demo").mkdir(parents=True)
        common.write_json(root / "demo" / "showtime.json", {"width": 1280, "height": 720, "duration": 5})
        (root / "studio").mkdir()                                   # board files, no showtime.json
        (root / "studio" / "board.json").write_text("{}", encoding="utf-8")
        env = dict(ENV, SHOWTIME_TEMPLATES=str(root))
        run = lambda *a: subprocess.run([sys.executable, str(LAUNCHER)] + list(a), env=env,  # noqa: E731
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        lst = run("new", "--list")
        self.assertEqual(lst.returncode, 0, lst.stderr)
        self.assertIn("demo", lst.stdout)
        self.assertIn("1280x720", lst.stdout)
        self.assertNotIn("studio", lst.stdout)
        self.assertNotIn("?x?", lst.stdout)
        bad = run("new", "studio", str(self.tmp / "x"))
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("studio init", bad.stderr)
        self.assertFalse((self.tmp / "x").exists())

    def test_retime_moves_the_whole_timeline(self):
        """--duration rescales scenes, nested/absolute times, poster, mix and caption words together."""
        root = self.tmp / "templates" / "t"
        (root / "audio").mkdir(parents=True)
        common.write_json(root / "showtime.json", {"width": 640, "height": 360, "fps": 30, "duration": 10.0,
                                                   "poster": 8.5, "audio": "audio/mix.json"})
        (root / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script></head><body>\n'
            '<section id="a" data-start="0" data-dur="4"><img src="x.png">\n'
            '  <p data-st="kinetic-type" data-at="0.5">Hi</p>\n'
            '  <p data-st="typewriter" data-fit="3">typed</p><img data-st="ken-burns" data-fit="contain" src="x.png">\n'
            '  <div data-st="cursor" data-path=\'[{"at":1.5,"x":1,"y":2}]\' data-tilt="[6,-10]"></div>\n'
            '  <div data-start="+1" data-dur="2">nested</div></section>\n'
            '<section id="b" data-start="#a" data-dur="6" data-transition="push left 0.6">\n'
            '  <div data-st="steps" data-cues="[1, 2.5]"></div></section>\n'
            '<div data-st="caption-karaoke" data-src="words.json"></div>\n'
            '</body></html>\n', encoding="utf-8")
        common.write_json(root / "audio" / "mix.json", {"tracks": [
            {"kind": "music", "compose": {"style": "x", "sections": "0:intro,4:drop"}},
            {"kind": "sfx", "at": 5.0}, {"kind": "voice", "file": "v.wav", "start": 1.0}]})
        common.write_json(root / "words.json", {"words": [{"text": "a", "start": 4.2, "end": 4.6}]})
        env = dict(ENV, SHOWTIME_TEMPLATES=str(self.tmp / "templates"))
        run = lambda *a: subprocess.run([sys.executable, str(LAUNCHER)] + list(a), env=env,  # noqa: E731
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        # longer: scenes x2, times inside a scene keep their offset from the scene start
        cp = run("new", "t", str(self.tmp / "long"), "--duration", "20", "--json")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        d = self.tmp / "long"
        html = (d / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="a" data-start="0" data-dur="8"', html)
        self.assertIn('id="b" data-start="#a" data-dur="12" data-transition="push left 0.6"', html)
        self.assertIn('data-at="0.5"', html)                      # animation speed unchanged
        self.assertIn('data-start="+1" data-dur="2"', html)
        self.assertIn('data-tilt="[6,-10]"', html)                # not a time
        self.assertIn('data-fit="3"', html)                       # typing speed unchanged in a longer scene
        cfg = common.read_json(d / "showtime.json")
        self.assertEqual((cfg["duration"], cfg["poster"]), (20.0, 12.5))   # 8 + (8.5 - 4)
        mix = common.read_json(d / "audio" / "mix.json")
        self.assertEqual(mix["tracks"][0]["compose"]["sections"], "0:intro,8:drop")
        self.assertEqual(mix["tracks"][1]["at"], 9.0)             # scene b starts at 8, sfx was 1 s in
        self.assertEqual(mix["tracks"][2]["start"], 1.0)
        w = common.read_json(d / "words.json")["words"][0]
        self.assertEqual((w["start"], w["end"]), (8.2, 8.6))
        rep = json.loads(cp.stdout)["retime"]
        self.assertEqual([s["to"] for s in rep["scenes"]], [[0.0, 8.0], [8.0, 20.0]])
        # shorter: everything scales, including times inside scenes
        cp = run("new", "t", str(self.tmp / "short"), "-d", "5")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        html = (self.tmp / "short" / "index.html").read_text(encoding="utf-8")
        for frag in ('id="a" data-start="0" data-dur="2"', 'data-at="0.25"', '"at":0.75', 'data-start="+0.5" data-dur="1"',
                     # a transition shrinks with its scene, but never below 0.35 s (a handoff, not a jump cut)
                     'data-dur="3" data-transition="push left 0.35"', 'data-cues="[0.5, 1.25]"',
                     # typing that must finish within N s finishes within N/2 in a scene half as long
                     'data-st="typewriter" data-fit="1.5"', 'data-fit="contain"'):
            self.assertIn(frag, html)
        self.assertEqual(common.read_json(self.tmp / "short" / "showtime.json")["poster"], 4.25)
        # retime an existing project; --dry-run writes nothing
        before = (d / "index.html").read_text(encoding="utf-8")
        cp = showtime("retime", d, "-d", "10", "--dry-run", "--json")
        self.assertTrue(json.loads(cp.stdout)["dry_run"])
        self.assertEqual((d / "index.html").read_text(encoding="utf-8"), before)
        showtime("retime", d, "-d", "10")
        self.assertIn('id="a" data-start="0" data-dur="4"', (d / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(common.read_json(d / "showtime.json")["duration"], 10.0)

    def test_retime_canvas_cue_table(self):
        from st.cli_core import _retime_cues, _fit_bpm
        src = "var CUE = {\n  bpm: 80,\n  a: 3.0,   // cut\n  cps: 11,\n  duration: 12.0,\n};\nCUE.x = 1;\n"
        out, ch = _retime_cues(src, 12.0, 20.0)
        self.assertIn("bpm: 96,", out)                            # 3 s bars -> 2.5 s bars: cues stay on bar lines
        self.assertIn("a: 5,   // cut", out)
        self.assertIn("cps: 11,", out)
        self.assertIn("duration: 20,", out)
        self.assertTrue(out.endswith("CUE.x = 1;\n"))
        self.assertEqual(_fit_bpm(120, 1.0), 120)
        self.assertEqual(_fit_bpm(80, 0.75), 106.667)


class TestRetimeVoiceAndData(TempDirCase):
    """Round 3: `retime --from-voice`, the stretch warning, launcher groups and `data import`."""

    PAGE = ('<!doctype html><html><head><script src="/_st/stage.js"></script></head><body>\n'
            '<section id="hook" data-start="0" data-dur="3"><p data-st="kinetic-type" data-at="0.2">Hi</p></section>\n'
            '<section id="demo" data-start="#hook" data-dur="5" data-transition="push left 0.5">\n'
            '  <div data-start="+1" data-dur="2">nested</div></section>\n'
            '<section id="close" data-start="#demo" data-dur="2"><div data-st="end-card" data-text="x"></div></section>\n'
            '<div data-st="caption-karaoke" data-src="words.json" data-style="bold-pop"></div>\n'
            '</body></html>\n')

    def _project(self, name, page=None):
        d = self.tmp / name
        (d / "audio").mkdir(parents=True)
        common.write_json(d / "showtime.json", {"width": 640, "height": 360, "fps": 30, "duration": 10.0,
                                                "poster": 4.5, "audio": "audio/mix.json"})
        (d / "index.html").write_text(page or self.PAGE, encoding="utf-8")
        common.write_json(d / "audio" / "mix.json", {"duration": 10.0, "tracks": [
            {"id": "bed", "kind": "music", "compose": {"style": "x", "sections": "0:intro,3:drop,8:outro"}},
            {"kind": "sfx", "at": 3.5}, {"kind": "sfx", "at": 8.2}]})
        common.write_json(d / "words.json", {"words": [{"text": "old", "start": 0.5, "end": 0.9}]})
        return d

    @staticmethod
    def _timeline(folder, lines):
        """A voice-script timeline: [(id, speech seconds, pause after)]."""
        (folder / "lines").mkdir(parents=True, exist_ok=True)
        t, out = 0.0, []
        for i, (lid, dur, pause) in enumerate(lines):
            words = [{"text": "w%d" % k, "start": round(t + k * dur / 2, 3), "end": round(t + (k + 1) * dur / 2 - 0.05, 3),
                      "line": lid} for k in range(2)]
            out.append({"id": lid, "index": i + 1, "start": round(t, 3), "end": round(t + dur, 3), "duration": dur,
                        "slot": {"start": round(t, 3), "end": round(t + dur + pause, 3), "duration": round(dur + pause, 3)},
                        "file": "lines/%02d-%s.wav" % (i + 1, lid), "words": words})
            t += dur + pause
        common.write_json(folder / "timeline.json", {"version": 1, "file": "vo.wav", "duration": round(t, 3), "lines": out,
                                                     "words": [w for ln in out for w in ln["words"]]})
        return folder / "timeline.json"

    def test_from_voice_by_id(self):
        from st.cli_core import _Tags
        d = self._project("vo1")
        tl = self._timeline(d / "voice", [("hook", 1.6, 0.35), ("demo", 3.0, 0.6)])
        cp = showtime("retime", d, "--from-voice", tl, "--json")
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["voice"]["how"], "by id")
        html = (d / "index.html").read_text(encoding="utf-8")
        wins = [(round(c["t0"], 3), round(c["t1"], 3)) for c in _Tags(html).resolve() if c["parent"] is None]
        # hook = pad 0.3 + slot 1.95; demo = 0.3 + 3.6; the unnarrated end card keeps its 2 s
        self.assertEqual(wins, [(0.0, 2.25), (2.25, 6.15), (6.15, 8.15)])
        self.assertEqual(rep["to"], 8.15)
        self.assertEqual(common.read_json(d / "showtime.json")["duration"], 8.15)
        mix = common.read_json(d / "audio" / "mix.json")
        voice = [t for t in mix["tracks"] if t.get("kind") == "voice"]
        self.assertEqual([(t["file"], t["start"]) for t in voice],
                         [("voice/lines/01-hook.wav", 0.3), ("voice/lines/02-demo.wav", 2.55)])
        self.assertEqual(mix["tracks"][0]["compose"]["sections"], "0:intro,2.25:drop,6.15:outro")
        self.assertEqual(mix["tracks"][0]["duck"], {"under": "voice"})
        # sfx keep their place in their scene: demo shrank 5 -> 3.9 s (x0.78), the end card kept its length
        self.assertEqual([t["at"] for t in mix["tracks"] if t.get("kind") == "sfx"], [2.64, 6.35])
        self.assertEqual(mix["duration"], 8.15)
        # the caption layer reads the voice words at their video times
        self.assertIn('data-src="voice/captions.words.json"', html)
        words = common.read_json(d / "voice" / "captions.words.json")["words"]
        self.assertEqual((words[0]["start"], words[2]["start"]), (0.3, 2.55))
        self.assertEqual(common.read_json(d / "showtime.json")["poster"], 3.42)   # 1.5 s into demo, x0.78
        # running it again changes nothing (voice tracks are replaced, not added), and says so honestly
        cp = showtime("retime", d, "--from-voice", tl, "--json")
        mix2 = common.read_json(d / "audio" / "mix.json")
        self.assertEqual(len([t for t in mix2["tracks"] if t.get("kind") == "voice"]), 2)
        self.assertEqual(html, (d / "index.html").read_text(encoding="utf-8"))
        self.assertFalse([c for c in json.loads(cp.stdout)["changes"] if "value(s) changed" in c], cp.stdout)
        # `voice cues` turns the timeline into a JS table canvas cue tables can read
        cp = showtime("voice", "cues", tl, "-o", d / "voice" / "cues.js", "--offset", "0.5", "--json")
        js = (d / "voice" / "cues.js").read_text(encoding="utf-8")
        self.assertIn("var VO = ", js)
        vo = json.loads(js.split("var VO = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(vo["lines"]["demo"]["start"], 1.95 + 0.5)
        self.assertEqual(vo["words"]["hook"][0][0], "w0")
        # --total keeps the video length: the end card absorbs the difference
        rep = json.loads(showtime("retime", d, "--from-voice", tl, "--total", "10", "--json").stdout)
        self.assertEqual(rep["to"], 10.0)
        self.assertEqual(rep["scenes"][-1]["to"], [6.15, 10.0])
        cp = showtime("retime", d, "--from-voice", tl, "--total", "6.5", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("end card", cp.stderr)

    def test_from_voice_order_map_and_errors(self):
        d = self._project("vo2")
        tl = self._timeline(d / "voice", [("l1", 1.0, 0.35), ("l2", 1.0, 0.35), ("l3", 1.0, 0.6)])
        # by order: three lines, three scenes
        rep = json.loads(showtime("retime", d, "--from-voice", "voice/timeline.json", "--dry-run", "--json").stdout)
        self.assertEqual(rep["voice"]["how"], "by order")
        self.assertEqual([m["scene"] for m in rep["voice"]["mapping"]], ["hook", "demo", "close"])
        # --map: two lines share the first scene (l2 is left out, so it joins l1's scene)
        rep = json.loads(showtime("retime", d, "--from-voice", tl, "--map", "l1=hook,l3=demo", "--pad", "0.5",
                                  "--dry-run", "--json").stdout)
        self.assertEqual([m["scene"] for m in rep["voice"]["mapping"]], ["hook", "hook", "demo"])
        self.assertEqual([s["to"] for s in rep["scenes"]], [[0.0, 3.2], [3.2, 5.3], [5.3, 7.3]])
        mp = self.tmp / "map.json"
        common.write_json(mp, {"l1": "demo", "l2": "hook"})
        cp = showtime("retime", d, "--from-voice", tl, "--map", mp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("backwards", cp.stderr)
        cp = showtime("retime", d, "--from-voice", tl, "--map", "l1=hook,l3=close", check=False)
        self.assertIn("demo", cp.stderr)                      # a scene between narrated ones with no line
        self.assertIn("between narrated scenes", cp.stderr)
        cp = showtime("retime", d, "--from-voice", tl, "--map", "l1=nope", check=False)
        self.assertIn("hook", cp.stderr)                      # lists the scenes
        cp = showtime("retime", d, check=False)
        self.assertIn("--duration", cp.stderr)
        cp = showtime("retime", d, "--from-voice", self.tmp / "missing.json", check=False)
        self.assertIn("voice script", cp.stderr)
        self.assertEqual(common.read_json(d / "showtime.json")["duration"], 10.0)   # errors write nothing

    def test_stretch_warning_and_quiet_poster(self):
        d = self._project("st1")
        cp = showtime("retime", d, "-d", "20", "--json")
        notes = json.loads(cp.stdout)["notes"]
        self.assertTrue(any("stretched more than 1.5x" in n and "hook x2.0" in n for n in notes), notes)
        d2 = self._project("st2")
        cp = showtime("retime", d2, "-d", "13")
        self.assertNotIn("stretched", cp.stderr)
        # new --duration prints the same warning; an unchanged poster is not reported as retimed
        tpl = self.tmp / "templates" / "p"
        shutil.copytree(str(self._project("st3")), str(tpl))
        env = dict(ENV, SHOWTIME_TEMPLATES=str(self.tmp / "templates"))
        cp = subprocess.run([sys.executable, str(LAUNCHER), "new", "p", str(self.tmp / "p30"), "--duration", "30"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("stretched more than 1.5x", cp.stderr)
        cp = showtime("retime", self.tmp / "p30", "-d", "31")
        self.assertIn("poster", cp.stdout + cp.stderr)
        self.assertNotRegex(cp.stdout + cp.stderr, r"poster ([\d.]+) -> \1\b")

    def test_thresholds_shared_with_check(self):
        from st import cli_core
        th = json.loads((SKILL / "runtime" / "thresholds.json").read_text(encoding="utf-8"))
        self.assertEqual(cli_core.STILL_HOLD_S, th["still_hold_s"])
        self.assertEqual(cli_core.STRETCH_WARN, th["stretch_warn"])
        self.assertIn("thresholds.json", (SKILL / "scripts" / "check.mjs").read_text(encoding="utf-8"))
        self.assertIn("default %g s" % th["still_hold_s"], showtime("check", "--help").stdout)

    def test_launcher_make_group(self):
        from st import launcher
        self.assertIn("retime", launcher.STDLIB_CLI)
        self.assertIn("data", launcher.STDLIB_CLI)
        make = [g for g in launcher.GROUPS if g[0] == "make"][0][2]
        self.assertEqual(make[:3], ["new", "retime", "data"])
        out = showtime("--help").stdout
        make_block = out.split("\nmake ", 1)[1].split("\n\n", 1)[0]
        self.assertIn("retime", make_block)
        self.assertIn("data", make_block)

    def test_data_import(self):
        d = self._project("dt")
        (d / "index.html").write_text(
            '<!doctype html><html><body><section id="bars" data-start="0" data-dur="4">'
            '<div class="chart" data-st="chart" data-type="line" data-data=\'[{"label":"a","value":1}]\' data-at="0.2"></div>'
            '</section><section id="race" data-start="#bars" data-dur="3"><div data-st="chart"></div></section></body></html>',
            encoding="utf-8")
        csvf = self.tmp / "Sign Ups.csv"
        csvf.write_text('﻿month;signups;revenue\n2026-01;"1,200";$3.4k\n2026-02;1500;$4.1k\n2026-03;2100;$5k\n'
                        '2026-04;;$5.2k\n', encoding="utf-8")
        cp = showtime("data", "import", csvf, d, "--y", "signups", "--scene", "bars", "--title", "Signups grew",
                      "--highlight", "max", "--annotate", "launch", "--json")
        r = json.loads(cp.stdout)
        self.assertEqual(r["src"], "data/sign-ups.json")
        data = common.read_json(d / "data" / "sign-ups.json")
        self.assertEqual(data["data"], [{"label": "Jan", "value": 1200}, {"label": "Feb", "value": 1500},
                                        {"label": "Mar", "value": 2100}])        # the empty April cell is left out
        self.assertEqual((data["title"], data["highlight"], data["annotate"]), ("Signups grew", "Mar", {"label": "Mar", "text": "launch"}))
        self.assertTrue(any("left out" in n for n in r["notes"]))
        html = (d / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-type="bar"', html)
        self.assertIn('data-src="data/sign-ups.json"', html)
        self.assertNotIn("data-data", html)                   # inline data would win over the file
        # line chart of every numeric column; the $ prefix and k multiplier are read
        r = json.loads(showtime("data", "import", csvf, d, "--chart", "line", "--y", "revenue", "-o",
                                d / "data" / "rev.json", "--json").stdout)
        rev = common.read_json(d / "data" / "rev.json")
        self.assertEqual(rev["prefix"], "$")
        self.assertEqual(rev["data"]["series"][0]["values"], [3400, 4100, 5000, 5200])
        # race from a long table: one state per year, ranked bars, scene too short -> a note
        longf = self.tmp / "long.csv"
        longf.write_text("year,lang,share\n2020,Py,30\n2020,JS,40\n2021,Py,41\n2021,JS,38\n2022,Py,45\n2022,JS,36\n",
                         encoding="utf-8")
        r = json.loads(showtime("data", "import", longf, d, "--chart", "race", "--x", "year", "--y", "share",
                                "--series", "lang", "--scene", "race", "--step", "2", "--title", "Py leads", "--json").stdout)
        race = common.read_json(d / "data" / "long.json")
        self.assertEqual([st["at"] for st in race["states"]], [0, 2, 4])
        self.assertEqual(race["states"][2]["title"], "Py leads · 2022")
        self.assertEqual(race["states"][2]["data"], [{"label": "Py", "value": 45}, {"label": "JS", "value": 36}])
        self.assertEqual(r["type"], "hbar")
        self.assertTrue(any("race needs" in n for n in r["notes"]), r["notes"])
        self.assertIn('data-type="hbar"', (d / "index.html").read_text(encoding="utf-8"))
        # --top keeps source order for bar (chronology), --sort value ranks; --ref next marks the first row left out;
        # negative values are fine
        tf = self.tmp / "temps.csv"
        tf.write_text("year,anomaly\n1976,-0.49\n2014,0.75\n2015,0.9\n2016,1.01\n2024,1.29\n", encoding="utf-8")
        r = json.loads(showtime("data", "import", tf, d, "--top", "3", "--ref", "next", "-o", d / "data" / "t.json", "--json").stdout)
        t = common.read_json(d / "data" / "t.json")
        self.assertEqual([x["label"] for x in t["data"]], ["2015", "2016", "2024"])
        self.assertEqual(t["ref"]["value"], 0.75)
        showtime("data", "import", tf, d, "--top", "3", "--sort", "value", "-o", d / "data" / "t2.json")
        self.assertEqual([x["label"] for x in common.read_json(d / "data" / "t2.json")["data"]], ["2024", "2016", "2015"])
        r = json.loads(showtime("data", "import", tf, d, "-o", d / "data" / "t3.json", "--json").stdout)
        self.assertTrue(any("negative" in n for n in r["notes"]), r["notes"])
        # inspect, and friendly errors
        out = showtime("data", "inspect", csvf).stdout
        self.assertRegex(out, r"signups\s+number")
        cp = showtime("data", "import", csvf, d, "--y", "nope", check=False)
        self.assertIn("columns: month, signups, revenue", cp.stderr)
        cp = showtime("data", "import", csvf, d, "--scene", "nope", check=False)
        self.assertIn("scenes: bars, race", cp.stderr)
        cp = showtime("data", "import", csvf, d, "--highlight", "Dec", "--y", "signups", check=False)
        self.assertIn("Jan", cp.stderr)


class TestNodeHelpers(unittest.TestCase):
    """scripts/lib/deps.mjs resolves ESM and CJS packages from ~/.showtime/node."""

    def test_import_deps(self):
        node = shutil.which("node")
        if not node or not (showtime_home() / "node" / "node_modules" / "playwright").is_dir():
            self.skipTest("node packages not installed")
        deps = (SKILL / "scripts" / "lib" / "deps.mjs").resolve().as_uri()
        chrome = (SKILL / "scripts" / "lib" / "chrome.mjs").resolve().as_uri()
        js = ("import { importDep, requireDep, depVersion, depPath } from %r;\n"
              "import { chromeFlags, findSystemBrowsers } from %r;\n"
              "import fs from 'node:fs';\n"
              "const out = {};\n"
              "for (const n of ['playwright', 'animejs', 'shiki', 'd3', 'culori', 'three']) {\n"
              "  const m = await importDep(n); out[n] = Object.keys(m).length > 0; }\n"
              "out.katex = typeof requireDep('katex').renderToString === 'function';\n"
              "out.pw = depVersion('playwright');\n"
              "out.font = fs.existsSync(depPath('@fontsource-variable/inter', 'index.css'));\n"
              "out.flags = chromeFlags('off').includes('--use-angle=swiftshader');\n"
              "out.browsers = findSystemBrowsers().length;\n"
              "console.log(JSON.stringify(out));\n" % (deps, chrome))
        cp = subprocess.run([node, "--input-type=module", "-e", js], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        d = json.loads(cp.stdout.strip().splitlines()[-1])
        for k in ("playwright", "animejs", "shiki", "d3", "culori", "three", "katex", "font", "flags"):
            self.assertTrue(d[k], "%s failed: %s" % (k, d))
        self.assertRegex(d["pw"], r"^\d+\.\d+\.\d+$")


class TestDeliver(TempDirCase):
    def test_poster_bake_exports_thumb(self):
        from st.deliver import exports, poster, thumbs
        clip = make_clip(self.tmp / "master.mp4", seconds=2.0, size="640x360")
        before = ff.probe(clip)
        rep = poster.make_poster(clip, at=1.5)
        self.assertTrue(Path(rep["poster"]).is_file())
        baked = poster.bake(clip, self.tmp / "baked.mp4", image=rep["poster"])
        after = ff.probe(baked["output"])
        self.assertAlmostEqual(after["duration"], before["duration"], delta=0.05)

        def audio_md5(p):
            cp = ff.run_ffmpeg(["-i", str(p), "-map", "0:a", "-c", "copy", "-f", "md5", "-"], overwrite=False)
            return cp.stdout.strip()

        self.assertEqual(audio_md5(clip), audio_md5(baked["output"]))
        res = exports.export(clip, "reels,square" if FAST else "reels,square,youtube",
                             out_dir=self.tmp / "ex", preview=True)
        dims = {r["target"]: (r["width"], r["height"]) for r in res["exports"]}
        self.assertEqual(dims["reels"], (1080, 1920))
        self.assertEqual(dims["square"], (1080, 1080))
        for r in res["exports"]:
            self.assertAlmostEqual(r["loudness"]["output_lufs"], -14.0, delta=1.0)
            self.assertAlmostEqual(r["duration"], 2.0, delta=0.1)
            self.assertLessEqual(r["loudness"]["encoded_true_peak"], -1.0 + 0.1)
        th = thumbs.thumbnail(clip, self.tmp / "t.jpg", at=1.0)
        self.assertEqual((th["width"], th["height"]), (1280, 720))
        self.assertTrue(th["under_2mb"])
        self.assertEqual(ff.probe(th["output"])["width"], 1280)

    def test_image_loops(self):
        from st.deliver import exports, loops
        clip = make_clip(self.tmp / "master.mp4", seconds=3.0, size="640x360")
        res = exports.export(clip, "webp-small,gif-small", out_dir=self.tmp / "ex", start=0.5, end=2.5, width=320)
        by = {r["target"]: r for r in res["exports"]}
        self.assertEqual(Path(by["gif-small"]["output"]).name, "master.loop-small.gif")
        self.assertEqual(Path(by["webp-small"]["output"]).name, "master.loop-small.webp")
        for name, fmt in (("gif-small", "gif"), ("webp-small", "webp")):
            r = by[name]
            meta = loops.read_loop_info(r["output"])
            self.assertEqual(meta["format"], fmt)
            self.assertTrue(meta["loops_forever"], name)
            self.assertEqual((meta["width"], meta["height"]), (320, 180), name)
            # 2 s at ~12 fps: the window, not the whole clip
            self.assertAlmostEqual(meta["frames"], 2.0 * r["fps"], delta=3, msg=name)
            self.assertAlmostEqual(r["duration"], 2.0, delta=0.01)
            self.assertLessEqual(r["size_bytes"], 1.5e6)
        # GIF delays are whole hundredths: the rate keeps time exactly
        self.assertAlmostEqual(100.0 / by["gif-small"]["fps"], round(100.0 / by["gif-small"]["fps"]), places=6)
        # never enlarged; an over-cap loop is re-encoded smaller until it fits
        tight = exports.export(clip, "gif", out_dir=self.tmp / "ex2", end=1.5, width=2000, max_mb=0.25)["exports"][0]
        self.assertLessEqual(tight["size_bytes"], 0.25e6)
        self.assertLessEqual(tight["attempts"][0]["width"], 640)
        self.assertGreater(len(tight["attempts"]), 1, tight["attempts"])
        self.assertLess(tight["attempts"][-1]["width"] * tight["attempts"][-1]["fps"],
                        tight["attempts"][0]["width"] * tight["attempts"][0]["fps"])
        self.assertEqual(Path(tight["output"]).name, "master.loop-0.25mb.gif")
        # loop-only options are refused for MP4 targets; windows past the end are refused
        with self.assertRaises(Exception) as cm:
            exports.export(clip, "gif,github", out_dir=self.tmp / "ex3", start=1.0)
        self.assertIn("image loops", str(cm.exception))
        cp = showtime("deliver", "exports", str(clip), "--targets", "webp", "--from", "0:01", "--to", "0:09",
                      "--out-dir", str(self.tmp / "ex4"), check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("past the end", cp.stderr)

    def test_cli_targets(self):
        out = showtime("deliver", "targets", "--json").stdout
        names = [t["name"] for t in json.loads(out)]
        from st.deliver import exports
        # the CLI lists exactly the targets deliver defines (no duplicates), social platforms included
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), set(exports.TARGETS))
        self.assertTrue(set(exports.PLATFORM_TARGETS) <= set(names))
        self.assertTrue({"youtube", "x", "linkedin", "reels", "tiktok", "shorts", "square",
                         "original", "github", "chat", "web", "webp", "gif", "webp-small", "gif-small"} <= set(names))


class TestAudioPeakGuard(TempDirCase):
    def test_aac_256k_and_true_peak_repair(self):
        self.assertIn("256k", ff.PRESETS["final"].audio)
        for name in ("final", "preview"):
            self.assertIn("-aac_coder", ff.PRESETS[name].audio, name)
        self.assertEqual(ff.aac_args(coder="fast")[:4], ["-c:a", "aac", "-aac_coder", "fast"])
        src = self.tmp / "loud.mov"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=gray:s=160x90:r=10:d=1",
                       "-f", "lavfi", "-i", "anoisesrc=d=1:c=pink:a=0.9:r=48000,alimiter=limit=0.84:level=false",
                       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
                       "-shortest", str(src)])
        out = ff.encode(src, self.tmp / "final.mp4", "final")
        lv = ff.audio_levels(out)
        self.assertIsNotNone(lv["true_peak_dbtp"])
        # Prove the repair path bites: demand a ceiling 3 dB under the current peak.
        ceiling = lv["true_peak_dbtp"] - 3.0
        rep = ff.ensure_true_peak(out, ceiling)
        self.assertTrue(rep["fixed"], rep)
        self.assertLessEqual(rep["after"], ceiling + 0.1)
        p = ff.probe(out)
        self.assertTrue(p["has_video"] and p["has_audio"])
        self.assertAlmostEqual(p["duration"], 1.0, delta=0.1)
        self.assertEqual(ff.ensure_true_peak(out, 0.0)["attempts"], [])   # already under: untouched


class TestUX(TempDirCase):
    def test_grouped_help_with_examples(self):
        out = showtime("--help").stdout
        for group in ("make", "audio", "voice", "footage", "capture/assets", "deliver", "setup"):
            self.assertRegex(out, r"(?m)^%s\b" % group.replace("/", "/"))
        self.assertIn("$ showtime render", out)
        self.assertIn("$ showtime deliver exports", out)
        self.assertNotIn("\033[", out)   # not a TTY: no colour codes

    def test_version_json(self):
        d = json.loads(showtime("version", "--json").stdout)
        self.assertRegex(d["version"], r"^\d+\.\d+\.\d+")
        self.assertEqual(Path(d["skill"]).resolve(), SKILL.resolve())

    def test_friendly_errors(self):
        cp = showtime("deliver", "exports", str(self.tmp / "missing.mp4"), "--targets", "youtube", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("fix:", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        cp = showtime("deliver", "exports", "--bogus-flag", check=False)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("showtime deliver exports --help", cp.stderr)
        cp = showtime("rendr", check=False)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("render", cp.stderr)
        dbg = showtime("deliver", "exports", str(self.tmp / "missing.mp4"), "--targets", "youtube", "--debug",
                       check=False)
        self.assertIn("Traceback", dbg.stderr)

    def test_first_run_message(self):
        env = dict(ENV, SHOWTIME_HOME=str(self.tmp / "empty-home"))
        env.pop("SHOWTIME_PYTHON", None)
        for args in (["audio", "styles"], ["render", "some-project"]):
            cp = subprocess.run([sys.executable, str(LAUNCHER)] + args, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
            self.assertEqual(cp.returncode, 2, cp.stderr)
            self.assertIn("showtime setup", cp.stderr)
            self.assertRegex(cp.stderr, r"about [\d.]+ [MG]B")
            self.assertRegex(cp.stderr, r"\d+-\d+ min")
        est = subprocess.run([sys.executable, str(SKILL / "setup" / "setup.py"), "--estimate", "--json"], env=env,
                             stdout=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertEqual(est.returncode, 0)
        total = json.loads(est.stdout)["total_bytes"]
        self.assertGreater(total, 3 * 10 ** 8)          # ffmpeg, packages, Kokoro ...
        self.assertLess(total, 13 * 10 ** 8)            # ... but no longer 2.9 GB (first-use parts come later)

    def test_progress_and_estimate(self):
        import io
        buf = io.StringIO()
        pr = common.Progress(total=4, label="frames", unit="fps", every=0.0, stream=buf)
        for _ in range(4):
            pr.update()
        pr.close()
        lines = buf.getvalue().strip().splitlines()
        self.assertIn("4/4", lines[-1])
        self.assertEqual(sum("4/4" in ln for ln in lines), 1)
        self.assertEqual(common.fmt_duration(95), "1:35")
        self.assertEqual(common.fmt_duration(12.4), "12 s")

    def test_require_extra(self):
        env_home = self.tmp / "h"
        old = os.environ.get("SHOWTIME_HOME")
        os.environ["SHOWTIME_HOME"] = str(env_home)
        try:
            with self.assertRaises(common.ShowtimeError) as cm:
                common.require_extra("diarize", "speaker labels")
            e = cm.exception
            self.assertEqual(e.code, 3)
            self.assertIn("showtime setup --with diarize", e.hint)
            self.assertIn("fix:", e.format())
            common.require_extra("diarize", "speaker labels", available=True)   # caller's own check wins
        finally:
            if old is None:
                os.environ.pop("SHOWTIME_HOME", None)
            else:
                os.environ["SHOWTIME_HOME"] = old

    def test_doctor_live_progress(self):
        """A slow check never looks frozen: the restart note appears once, a TTY gets a live line that is
        cleared afterwards, and a pipe gets nothing for fast checks."""
        import io
        from st import doctor

        class Tty(io.StringIO):
            def isatty(self):
                return True

        old = doctor.SLOW_NOTE_AFTER, doctor.RECENT_BOOT
        doctor.SLOW_NOTE_AFTER, doctor.RECENT_BOOT = 0.3, -1  # never "just booted", note after 0.3 s
        try:
            tty = Tty()
            live = doctor.Live(stream=tty)
            live.start()
            live.step("python imports")
            live.detail = "cv2, 7/25"
            time.sleep(0.9)
            live.stop()
            out = tty.getvalue()
            self.assertIn("checking python imports (cv2, 7/25)", out)
            self.assertEqual(out.count("first run after a restart"), 1)
            self.assertTrue(out.endswith("\r"), "the live line is cleared at the end")
            pipe = io.StringIO()
            live = doctor.Live(stream=pipe)
            live.start()
            live.step("uv")
            time.sleep(0.1)
            live.stop()
            self.assertEqual(pipe.getvalue(), "")
        finally:
            doctor.SLOW_NOTE_AFTER, doctor.RECENT_BOOT = old

    def test_bug_report_redacts(self):
        from st import doctor
        job = self.tmp / "job"
        (job / "work" / "logs").mkdir(parents=True)
        home = str(plat.user_home())
        (job / "job.json").write_text('{"cmd": "render", "key": "sk-%s", "who": "someone@example.com"}' % ("a1" * 12),
                                      encoding="utf-8")
        (job / "work" / "logs" / "render.log").write_text("failed at %s/x.mp4\n" % home, encoding="utf-8")
        result = {"checks": [{"check": "ffmpeg", "status": "fail", "detail": "%s/.showtime/bin/ffmpeg" % home,
                              "hint": "run `showtime setup`"}]}
        out = doctor.write_report(str(job), result)
        text = out.read_text(encoding="utf-8")
        self.assertEqual(out.name, "bug-report.md")
        self.assertNotIn(home, text)
        self.assertNotIn("someone@example.com", text)
        self.assertNotIn("sk-a1a1", text)
        self.assertIn("render.log", text)
        self.assertIn("run `showtime setup`", text)


class TestSetupManifest(unittest.TestCase):
    def test_manifest_integrity(self):
        man = json.loads((SKILL / "setup" / "manifest.json").read_text(encoding="utf-8"))
        for key in ("mac-arm64", "mac-x64", "win-x64", "linux-x64", "linux-arm64"):
            self.assertTrue(man["ffmpeg"].get(key), "no ffmpeg for %s" % key)
        ids = [i["id"] for i in man["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        files = []
        for cands in man["ffmpeg"].values():
            for c in cands:
                files += c["files"]
        for it in man["items"]:
            self.assertTrue(it.get("tier") or it.get("extra") in man["extras"], it["id"])
            files += it.get("files", [])
            for fl in it.get("platform_files", {}).values():
                files += fl
        for f in files:
            self.assertTrue(f["url"].startswith("https://"), f)
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$", f["url"])
            self.assertGreater(f["size"], 0, f["url"])
            dest = f.get("dest", "bin")
            self.assertFalse(dest.startswith(("/", "\\")) or ".." in dest.split("/"), dest)

    def test_requirements_markers(self):
        req = (SKILL / "setup" / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(req, r"onnxruntime==1\.23\.2 ; platform_machine == 'x86_64' and sys_platform == 'darwin'")
        self.assertRegex(req, r"numba==0\.62\.1 ; ")
        self.assertIn("pyobjc-framework-vision", req.lower())
        self.assertNotRegex(req, r"(?m)^torch==")

    def test_setup_list_json(self):
        cp = subprocess.run([sys.executable, str(SKILL / "setup" / "setup.py"), "--list", "--json"], env=ENV,
                            stdout=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertEqual(cp.returncode, 0)
        d = json.loads(cp.stdout)
        self.assertEqual(set(d["tiers"]), {"minimal", "core", "full"})
        self.assertIn("asr-turbo", d["extras"])


class TestDoctor(unittest.TestCase):
    def test_doctor_passes(self):
        cp = showtime("doctor", "--json", check=False, timeout=900)
        try:
            d = json.loads(cp.stdout)
        except ValueError:
            raise AssertionError("doctor output is not JSON:\n%s\n%s" % (cp.stdout[-1500:], cp.stderr[-1500:]))
        fails = [c for c in d["checks"] if c["status"] == "fail"]
        self.assertEqual(fails, [], "doctor failures: %s" % json.dumps(fails, indent=1)[:3000])
        self.assertEqual(cp.returncode, 0)
        names = {c["check"]: c for c in d["checks"]}
        self.assertEqual(names["ffmpeg encode"]["status"], "pass")
        self.assertIn(names["browser launch"]["status"], ("pass", "warn"))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
