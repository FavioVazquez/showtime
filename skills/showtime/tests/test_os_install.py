#!/usr/bin/env python3
"""A new user's machine: what clean macOS, Windows and Ubuntu installs ran into.

  * uv and Node.js are checked before setup downloads anything: setup stops with the install line for this OS,
    and `setup --estimate` names what is missing;
  * Windows: a missing Visual C++ 2015-2022 runtime is named (with its download link) before onnxruntime's
    "DLL load failed", in setup, doctor and any command's error;
  * Windows `setup --force`: the launchers run setup with a Python outside the venv it replaces, and files of the
    old venv still in use are moved aside instead of failing with WinError 5;
  * ffmpeg too old for showtime (Ubuntu 22.04's 4.4.2): found by probing the options showtime uses, refused by
    setup's system-ffmpeg pick, warned by doctor;
  * the loudness meter: a run that failed (an ebur128 option an old ffmpeg rejects) is never read as 0 LUFS;
  * setup --estimate says what the install takes on disk, by component, and what grows later;
  * the preview window turns off Chrome's device discovery (the macOS local-network prompt), and every local
    server binds 127.0.0.1;
  * Windows paths: a clip's work folder no longer repeats its name, and temp names shrink near 260 characters.

Light: stdlib, Node for the meter test, no browser, no network (setup's downloads are stubbed out).
usage: python tests/test_os_install.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import argparse
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

from st import lazy  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH")) or shutil.which("node")
POSIX = os.name == "posix"


def setup_mod():
    return lazy._setup()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-os-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)


# ------------------------------------------------------------------ 1. uv / Node.js before any download

class TestPrereqsFirst(Tmp):
    def no_tool(self, missing):
        real = plat.find_tool
        return mock.patch.object(plat, "find_tool", lambda name, path=None: None if name in missing else real(name, path))

    def test_setup_stops_before_downloading(self):
        su = setup_mod()
        home = self.tmp / "home"
        out, err = io.StringIO(), io.StringIO()
        fetched = []
        env = {k: v for k, v in os.environ.items() if k not in ("SHOWTIME_UV", "SHOWTIME_NODE")}
        with mock.patch.dict(os.environ, env, clear=True), self.no_tool({"uv", "node"}), \
                mock.patch.object(su, "fetch", lambda *a, **k: fetched.append(a) or "fetched"), \
                mock.patch.object(su.Installer, "step_ffmpeg", lambda self: fetched.append("ffmpeg") or ("ok", "")), \
                redirect_stdout(out), redirect_stderr(err):
            rc = su.main(["--home", str(home), "--json"])
        self.assertEqual(rc, 1)
        self.assertEqual(fetched, [], "nothing is downloaded when uv or Node.js is missing")
        text = err.getvalue()
        self.assertIn("uv was not found", text)
        self.assertIn("Node.js was not found", text)
        self.assertIn("Nothing was downloaded", text)
        if os.name == "nt":
            self.assertIn("install.ps1", text)
        else:
            self.assertIn("curl -LsSf https://astral.sh/uv/install.sh | sh", text)
        rows = {r["component"]: r for r in json.loads(out.getvalue())["results"]}
        self.assertEqual(rows["uv"]["status"], "fail")
        self.assertEqual(rows["node"]["status"], "fail")
        self.assertNotIn("ffmpeg", rows)

    def test_estimate_names_what_is_missing(self):
        su = setup_mod()
        out = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != "SHOWTIME_UV"}
        with mock.patch.dict(os.environ, env, clear=True), self.no_tool({"uv"}), redirect_stdout(out):
            self.assertEqual(su.main(["--home", str(self.tmp / "h"), "--estimate"]), 0)
        self.assertIn("Install first", out.getvalue())
        self.assertIn("uv was not found", out.getvalue())
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), self.no_tool({"uv"}), redirect_stdout(out):
            su.main(["--home", str(self.tmp / "h"), "--estimate", "--json"])
        self.assertEqual(json.loads(out.getvalue())["missing"], ["uv"])
        # --skip python needs no uv
        self.assertEqual([m["tool"] for m in su.missing_prereqs(["python", "node"])], [])

    def test_old_node_is_named(self):
        su = setup_mod()
        with mock.patch.object(su, "find_node", lambda: ("/x/node", (18, 19, 0))), \
                mock.patch.object(su, "find_uv", lambda: "/x/uv"):
            miss = su.missing_prereqs()
        self.assertEqual([m["tool"] for m in miss], ["node"])
        self.assertIn("18.19.0 is too old", miss[0]["problem"])


# ------------------------------------------------------------------ 2. Windows: the Visual C++ runtime

class TestVcRuntime(Tmp):
    def test_nothing_to_say_off_windows(self):
        if os.name == "nt":
            self.skipTest("checks the other platforms")
        self.assertEqual(plat.missing_vc_runtime(), [])
        self.assertIsNone(plat.explain_dll_error("DLL load failed while importing onnxruntime_pybind11_state"))

    def test_dll_error_becomes_the_runtime_link(self):
        msg = "DLL load failed while importing onnxruntime_pybind11_state: The specified module could not be found."
        with mock.patch.object(plat, "IS_WINDOWS", True), \
                mock.patch.object(plat, "missing_vc_runtime", lambda python=None: ["msvcp140.dll"]):
            fix = plat.explain_dll_error(msg)
            from st import cli
            err = cli.explain(ImportError(msg, name="onnxruntime.capi.onnxruntime_pybind11_state"))
        self.assertIn(plat.VC_REDIST_URL, fix)
        self.assertIn("msvcp140.dll", fix)
        self.assertIn(plat.VC_REDIST_URL, err.format(color=False))
        self.assertIn("could not load its DLLs", err.format(color=False))
        self.assertIn("vcruntime140_1.dll", plat.VC_CHECK_CODE)

    def test_doctor_names_it_before_the_imports(self):
        from st import doctor
        d = doctor.Doctor(argparse.Namespace(verify=False, verbose=False, quick=True))
        d.p = dict(d.p, venv_python=Path(sys.executable))
        fake = json.dumps(dict({"python": "3.12.9"}, **{m: {"ok": m != "onnxruntime", "version": "1",
                                                            "error": "ImportError: DLL load failed while importing x"}
                                                        for m in doctor.REQUIRED_MODULES}))
        with mock.patch.object(plat, "IS_WINDOWS", True), \
                mock.patch.object(plat, "missing_vc_runtime", lambda python=None: ["msvcp140.dll"]), \
                mock.patch.object(d, "_run_streaming", lambda *a, **k: (fake, "")):
            d.check_python()
        rows = {r["check"]: r for r in d.rows}
        self.assertEqual(rows["vc++ runtime"]["status"], "fail")
        self.assertIn(plat.VC_REDIST_URL, rows["vc++ runtime"]["hint"])
        self.assertIn(plat.VC_REDIST_URL, rows["python packages"]["hint"], "the import failure points to the runtime")
        order = [r["check"] for r in d.rows]
        self.assertLess(order.index("vc++ runtime"), order.index("python packages"))


# ------------------------------------------------------------------ 3. Windows: setup --force and its own venv

class TestForceVenv(Tmp):
    def test_files_in_use_move_aside(self):
        su = setup_mod()
        venv = self.tmp / "venv"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "Lib" / "site-packages" / "numpy").mkdir(parents=True)
        busy = venv / "Scripts" / "python.exe"
        busy.write_bytes(b"MZ")
        (venv / "Lib" / "site-packages" / "numpy" / "core.pyd").write_bytes(b"x")
        (venv / "pyvenv.cfg").write_text("home = x\n")
        real_unlink = os.unlink

        def unlink(p, *a, **k):        # Windows: a running python.exe cannot be deleted (WinError 5)
            if os.path.basename(str(p)) == "python.exe":
                raise PermissionError(13, "Access is denied", str(p))
            return real_unlink(p, *a, **k)
        trash = self.tmp / "cache" / "trash"
        with mock.patch("os.unlink", unlink), mock.patch("os.remove", unlink):
            moved = su.rmtree_aside(venv, trash)
        self.assertFalse(venv.exists(), "the old venv is gone, so `uv venv` can make a new one")
        self.assertEqual([Path(m).name for m in moved], ["python.exe"])
        self.assertEqual(len(list(trash.iterdir())), 1)
        su.empty_trash(trash)            # a later setup deletes what was moved aside
        self.assertEqual(list(trash.iterdir()), [])

    def test_a_file_that_cannot_move_names_the_cause(self):
        su = setup_mod()
        home = self.tmp / "home"
        (home / "venv" / "Scripts").mkdir(parents=True)
        (home / "venv" / "Scripts" / "python.exe").write_bytes(b"MZ")
        args = su.parse_args(["--home", str(home), "--force"])
        inst = su.Installer(args)
        with mock.patch.object(su, "find_uv", lambda: "/x/uv"), \
                mock.patch.object(su, "rmtree_aside", mock.Mock(side_effect=PermissionError(13, "Access is denied"))), \
                redirect_stderr(io.StringIO()):
            status, detail = inst.step_python()
        self.assertEqual(status, "fail")
        self.assertIn("a running showtime process uses it", detail)
        self.assertIn("MCP server", detail)

    def test_a_venv_python_that_cannot_start_is_recreated_not_a_crash(self):
        # a half-deleted venv, or (Windows) a python.exe that is not a runnable binary: WinError 216
        su = setup_mod()
        home = self.tmp / "home"
        args = su.parse_args(["--home", str(home)])
        inst = su.Installer(args)
        inst.vpy.parent.mkdir(parents=True)
        inst.vpy.write_bytes(b"MZ")           # not executable on POSIX, not a valid image on Windows
        self.assertIsNone(inst._venv_says("print(1)"))

    def test_launchers_run_setup_outside_the_venv(self):
        cmd = (SKILL / "bin" / "showtime.cmd").read_text(encoding="utf-8")
        self.assertLess(cmd.index('if /i "%~1"=="setup" goto findpy'), cmd.index('goto venv'))
        self.assertIn(":findpy", cmd)
        ps1 = (SKILL / "bin" / "showtime.ps1").read_text(encoding="utf-8")
        self.assertIn("-not $isSetup", ps1)
        for f in ("showtime.cmd", "showtime.ps1"):
            self.assertIn(b"\r\n", (SKILL / "bin" / f).read_bytes(), "%s keeps CRLF line ends" % f)

    @unittest.skipUnless(POSIX and shutil.which("sh"), "runs the POSIX launcher")
    def test_posix_launcher_skips_the_windows_venv_for_setup(self):
        home = self.tmp / "home"
        fake = home / "venv" / "Scripts" / "python.exe"          # Git Bash on Windows: the venv's python.exe
        fake.parent.mkdir(parents=True)
        fake.write_text("#!/bin/sh\necho venv-python \"$@\"\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ, SHOWTIME_HOME=str(home))
        env.pop("SHOWTIME_PYTHON", None)
        run = lambda *a: subprocess.run(["sh", str(SKILL / "bin" / "showtime")] + list(a), env=env,  # noqa: E731
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertIn("venv-python", run("version").stdout, "other commands still take the venv's python")
        cp = run("setup", "--estimate")
        self.assertNotIn("venv-python", cp.stdout + cp.stderr, "setup runs with a Python outside the venv")
        self.assertIn("showtime setup --tier", cp.stdout)


# ------------------------------------------------------------------ 4. an ffmpeg too old for showtime

OLD_FFMPEG = r"""#!/bin/sh
# ffmpeg 4.4.2 as Ubuntu 22.04 ships it: the filters are there, the newer options are not
case "$*" in
  *-version*) echo "ffmpeg version 4.4.2-0ubuntu0.22.04.1 Copyright (c) 2000-2021 the FFmpeg developers"; exit 0;;
  *-filters*) for f in subtitles ass drawtext loudnorm ebur128 xfade scale overlay amix sidechaincompress silencedetect palettegen zscale arnndn; do echo " T.. $f   A->A  x"; done; exit 0;;
  *-encoders*) for e in libx264 aac; do echo " V..... $e   x"; done; exit 0;;
  *"bsf=setts"*) echo "setts_bsf AVOptions:"; echo "  -ts  <string>  ...VAS..B.. set expression"; exit 0;;
  *"filter=ebur128"*) echo "   framelog  <int>  ..FVA...... force frame logging level"; echo "     info  32"; echo "     verbose 40"; exit 0;;
  *"-h long"*) echo "-filter_complex graph"; exit 0;;
esac
exit 0
"""


@unittest.skipUnless(POSIX, "uses a shell-script stand-in for ffmpeg")
class TestOldFfmpeg(Tmp):
    def fake(self):
        f = self.tmp / "bin" / "ffmpeg"
        f.parent.mkdir(parents=True)
        f.write_text(OLD_FFMPEG)
        f.chmod(0o755)
        (self.tmp / "bin" / "ffprobe").write_text("#!/bin/sh\nexit 0\n")
        (self.tmp / "bin" / "ffprobe").chmod(0o755)
        return str(f)

    def test_probe_and_verdict(self):
        from st import ff
        exe = self.fake()
        feats = ff.probe_features(exe)
        self.assertEqual(feats, {"setts duration": False, "display_rotation": False, "ebur128 framelog=quiet": False})
        old = ff.too_old("4.4.2-0ubuntu0.22.04.1", feats)
        self.assertEqual(old[0], "version 4.4.2-0ubuntu0.22.04.1 < 6.0")
        self.assertIn("display_rotation", old)
        self.assertEqual(ff.too_old("N-112345-gabc", feats)[:1], ["setts duration"], "a git build: the probes decide")
        self.assertEqual(ff.too_old("7.1", {"setts duration": True, "display_rotation": True}), [])
        real = ff.resolve().ffmpeg
        self.assertEqual(ff.too_old(ff._version_of(real), ff.probe_features(real)), [], "showtime's own ffmpeg is fine")

    def test_setup_refuses_it_and_doctor_warns(self):
        su = setup_mod()
        exe = self.fake()
        args = su.parse_args(["--home", str(self.tmp / "home"), "--ffmpeg", "system"])
        inst = su.Installer(args)
        ok, req, _rec, v = inst._ff_check(exe)
        self.assertFalse(ok)
        self.assertTrue(req[0].startswith("too old: version 4.4.2"), req)
        with mock.patch("st.ff._system_candidates", lambda name: [exe]), redirect_stderr(io.StringIO()):
            status, detail = inst.step_ffmpeg()
        self.assertEqual(status, "fail")
        self.assertIn("showtime setup --ffmpeg static", detail)
        from st import ff, doctor
        with mock.patch.dict(os.environ, {"SHOWTIME_FFMPEG": exe, "SHOWTIME_HOME": str(self.tmp / "home")}):
            ff._cached = None
            try:
                d = doctor.Doctor(argparse.Namespace(verify=False, verbose=False, quick=True))
                d.check_ffmpeg()
            finally:
                ff._cached = None
        rows = {r["check"]: r for r in d.rows}
        self.assertEqual(rows["ffmpeg version"]["status"], "warn")
        self.assertIn("showtime setup --ffmpeg static", rows["ffmpeg version"]["hint"])


# ------------------------------------------------------------------ 5. a failed loudness reading is not 0 LUFS

# ffmpeg 4.x rejects `framelog=quiet` and still prints a Summary of zeros ("I: 0.0 LUFS"): the stand-in does the same
# and passes every other call to the real ffmpeg
METER_WRAPPER = r"""#!/bin/sh
for a in "$@"; do
  case "$a" in
    *framelog=quiet*|*%s*)
      echo "[ebur128 @ 0x1] Unable to parse option value \"quiet\"" >&2
      echo "[AVFilterGraph @ 0x2] Error initializing filter 'ebur128' with args '$a'" >&2
      printf '[Parsed_ebur128_0 @ 0x3] Summary:\n\n  Integrated loudness:\n    I:           0.0 LUFS\n    Threshold:   0.0 LUFS\n\n  Loudness range:\n    LRA:         0.0 LU\n\n  True peak:\n    Peak:       -inf dBFS\n' >&2
      echo "Conversion failed!" >&2
      exit 1;;
  esac
done
exec "%s" "$@"
"""


@unittest.skipUnless(POSIX and NODE, "a shell-script ffmpeg stand-in and Node.js")
class TestLoudnessReading(Tmp):
    def wrapper(self, name, also_reject):
        from st import ff
        f = self.tmp / name / "ffmpeg"
        f.parent.mkdir(parents=True)
        f.write_text(METER_WRAPPER % (also_reject, ff.resolve().ffmpeg))
        f.chmod(0o755)
        return str(f)

    def meter(self, ffmpeg_exe, wav):
        js = ("import { ebur128 } from %s; import { master } from %s;\n"
              "const m = await ebur128(%s);\n"
              "const r = await master(%s, %s, { target: -14, tp: -1, useModule: false });\n"
              "console.log(JSON.stringify({ m, r }));" % (
                  json.dumps((SKILL / "scripts" / "lib" / "ff.mjs").as_uri()),
                  json.dumps((SKILL / "scripts" / "lib" / "audio.mjs").as_uri()),
                  json.dumps(str(wav)), json.dumps(str(wav)), json.dumps(str(self.tmp / ("out-%s.wav" % Path(ffmpeg_exe).parent.name)))))
        cp = subprocess.run([NODE, "--input-type=module", "-e", js], env=dict(ENV, SHOWTIME_FFMPEG=ffmpeg_exe),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=180)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        return json.loads(cp.stdout.strip().splitlines()[-1])

    def test_old_ffmpeg_falls_back_and_a_failed_meter_is_null(self):
        from st import ff
        wav = self.tmp / "tone.wav"
        subprocess.run([ff.resolve().ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=3",
                        "-af", "volume=-12dB", "-ac", "2", str(wav)], check=True, timeout=60)
        # 1) the option is rejected: the meter reads again without it and gets the real level
        got = self.meter(self.wrapper("old", "never-matches"), wav)
        self.assertIsNotNone(got["m"]["I"])
        self.assertLess(got["m"]["I"], -10, got["m"])
        self.assertNotIn("error", got["m"])
        self.assertEqual(got["r"]["mode"] in ("linear", "limited"), True, got["r"])
        # 2) every form fails: null and a reason, never 0 LUFS; the master keeps the sound as mixed and says why
        got = self.meter(self.wrapper("broken", "ebur128="), wav)
        self.assertIsNone(got["m"]["I"])
        self.assertIsNone(got["m"]["TP"])
        self.assertIn("ebur128", got["m"]["error"])
        self.assertEqual(got["r"]["mode"], "unmeasured")
        self.assertIsNone(got["r"]["lufs"])
        self.assertIn("error", got["r"])

    def test_python_readers_ignore_a_failed_run(self):
        from st import ff
        from st.audio import meter
        exe = self.wrapper("broken-py", "ebur128=")
        wav = self.tmp / "t.wav"
        subprocess.run([ff.resolve().ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1", str(wav)],
                       check=True, timeout=60)
        with mock.patch.dict(os.environ, {"SHOWTIME_FFMPEG": exe}):
            ff._cached = None
            try:
                self.assertEqual(ff.audio_levels(wav), {"integrated_lufs": None, "true_peak_dbtp": None})
                self.assertEqual(meter.ffmpeg_ebur128(wav)["integrated_lufs"], None)
            finally:
                ff._cached = None


# ------------------------------------------------------------------ 9. what the install takes on disk

class TestDiskEstimate(Tmp):
    def test_estimate_has_the_installed_size(self):
        su = setup_mod()
        man = su.load_manifest()
        with mock.patch.object(su, "system_browsers", lambda: []):
            est = su.install_estimate("core", [], self.tmp / "empty", man)
        for part in ("python", "node", "ffmpeg", "models", "browser"):
            self.assertIn(part, est["disk"], est["disk"])
        self.assertEqual(est["disk_bytes"], sum(est["disk"].values()))
        self.assertGreater(est["disk_bytes"], 1.15e9, "unpacked, the install is well over its download")
        self.assertGreater(est["disk_bytes"], 2 * est["total_bytes"])
        self.assertIn("on disk", su.describe_estimate(est))
        self.assertIn("Python packages", su.describe_disk(est))
        for key in ("mac-arm64", "mac-x64", "win-x64", "linux-x64", "linux-arm64"):
            self.assertGreater(su.packages_bytes(man, "python", key, "disk"), 5e8, key)
            self.assertGreater(su.packages_bytes(man, "node", key, "disk"), 2e8, key)
        ids = {c["id"] for cands in man["ffmpeg"].values() if isinstance(cands, list) for c in cands}
        self.assertEqual(ids - set(man["disk"]["ffmpeg"]), set(), "every ffmpeg build has its installed size")
        # an installed home has nothing left to take
        out = io.StringIO()
        with redirect_stdout(out):
            su.main(["--home", str(self.tmp / "empty"), "--estimate"])
        self.assertIn("on disk once installed", out.getvalue())
        self.assertIn("Later:", out.getvalue())


# ------------------------------------------------------------------ 10. the macOS local-network prompt

class TestLocalOnly(unittest.TestCase):
    def test_preview_window_has_no_device_discovery(self):
        src = (SKILL / "scripts" / "preview.mjs").read_text(encoding="utf-8")
        m = re.search(r"PREVIEW_DISABLED_FEATURES = '([^']+)'", src)
        self.assertTrue(m)
        for feat in ("MediaRouter", "DialMediaRouteProvider"):
            self.assertIn(feat, m.group(1).split(","))
        self.assertIn("--disable-features=${PREVIEW_DISABLED_FEATURES}", src)

    def test_servers_bind_loopback(self):
        for rel, pat in (("scripts/server.mjs", r"const host = o\.host \|\| '127\.0\.0\.1'"),
                         ("scripts/lib/review/server.mjs", r"listen\(pt, '127\.0\.0\.1'\)"),
                         ("scripts/lib/studio/server.mjs", r"listen\(p, '127\.0\.0\.1'\)"),
                         ("scripts/lib/capture.mjs", r"listen\(0, '127\.0\.0\.1'")):
            self.assertRegex((SKILL / rel).read_text(encoding="utf-8"), pat, rel)
        for p in (SKILL / "lib" / "st").rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\.bind\(\(\s*['\"](0\.0\.0\.0)?['\"]", p.name)


# ------------------------------------------------------------------ 7. Windows paths near 260 characters

class TestWindowsPaths(Tmp):
    def test_long_temp_names_shrink(self):
        from st import common
        deep = self.tmp / ("d" * 200) / "program_norm.wav"
        with mock.patch.object(common, "_WINDOWS", True):
            tmp = common.part_path(deep)
        self.assertLess(len(str(tmp)), len(str(deep)) + 20)
        self.assertTrue(tmp.name.endswith(".part.wav"), tmp.name)
        self.assertNotIn("program_norm", tmp.name)
        short = common.part_path(self.tmp / "program_norm.wav")
        self.assertIn("program_norm", short.name, "short paths keep the readable name")

    def test_clip_work_folder_does_not_repeat_its_name(self):
        src = (SKILL / "lib" / "st" / "footage" / "render_edl.py").read_text(encoding="utf-8")
        self.assertIn('shared / (out.stem if out.stem != edl_path.stem else "render")', src)


# ------------------------------------------------------------------ 11. the dom template at 10 s

class TestDomTemplateCopy(unittest.TestCase):
    """`showtime new dom x --duration 10` scales every beat by 2/3: the hook is then on screen about 2 s, its
    supporting line and the feature lines under 2 s, so they stay short enough for the phone check's reading time
    (17 characters/s or 3 words/s, plus 0.3 s). Verified with `showtime check` on 10 s projects in four looks."""

    def test_lines_fit_their_time_at_10_s(self):
        html = (SKILL / "templates" / "dom" / "index.html").read_text(encoding="utf-8")

        def text(pattern):
            m = re.search(pattern, html, re.S)
            self.assertTrue(m, pattern)
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()

        def need(s):
            return 0.3 + max(len(s) / 17.0, len(s.split()) / 3.0)
        # on screen at 10 s (measured by check with the cobalt look), less a margin for slower motion styles
        for pattern, held in ((r'<h1 class="t-hero headline"[^>]*>(.*?)</h1>', 2.1), (r'<p class="sub"[^>]*>(.*?)</p>', 1.8),
                              (r'<h2 class="t-display head"[^>]*>(.*?)</h2>', 2.1)):
            s = text(pattern)
            self.assertLessEqual(need(s), held - 0.25, "%r needs %.2f s" % (s, need(s)))
        cards = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r'<div class="txt"><h3>[^<]*</h3><p>(.*?)</p>', html)]
        self.assertEqual(len(cards), 3)
        for s in cards:
            self.assertLessEqual(need(s), 1.8 - 0.15, "%r needs %.2f s" % (s, need(s)))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
