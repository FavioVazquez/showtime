#!/usr/bin/env python3
"""Places where showtime's contract tripped agents in the 0.2.0 benchmark runs, fixed in 0.3.0.

  1  `retime --from-voice --total` with every scene narrated (the `short` template's narrated close):
     the last scene's hold after its last line absorbs the difference; a total that would cut into
     that line is an error naming the shortest total that works
  2  Manim: a narration.md with no lines (the stub's comment, "no voice-over") is a silent film, not
     an error; `--mix` is read from the current folder first, then the project; a mix track's file
     is found beside the spec, then in the Manim folder (render: needs the manim extra)
  3  doctor: <home>/bin/showtime running another showtime than the agent's (a newer one recorded, or
     a newer one installed while the command still runs this one) is a warning with the fix;
     `showtime new` with an unknown template names the running version
  4  check: characters the page's fonts lack are named exactly (the loaded faces' unicode-ranges),
     with the fix for each kind: <sub>/<sup> markup, an inline SVG arrow, an @font-face with that
     unicode-range (the page probe needs a browser)
usage: python tests/test_contract_fixes.py [--fast] [-v]
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
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import __version__, common, shim  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.manim_run import cues as cues_mod  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, env=None, cwd=None, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-contract-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)


# ------------------------------------------------------------------ 1. retime --total, narrated close

def voice_timeline(folder: Path, lines):
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


class RetimeNarratedClose(Tmp):
    def test_total_with_every_scene_narrated(self):
        d = self.tmp / "short"
        shutil.copytree(str(SKILL / "templates" / "short"), str(d))
        # hook, demo and the close are all narrated (the ids match the template's scenes)
        tl = voice_timeline(d / "voice", [("hook", 1.6, 0.35), ("demo", 3.0, 0.6), ("close", 1.2, 0.4)])
        rep = json.loads(showtime("retime", d, "--from-voice", tl, "--dry-run", "--json").stdout)
        self.assertEqual([s["to"] for s in rep["scenes"]], [[0.0, 2.25], [2.25, 6.15], [6.15, 8.05]])
        # longer: the close holds after its last line
        rep = json.loads(showtime("retime", d, "--from-voice", tl, "--total", "14", "--json").stdout)
        self.assertEqual(rep["to"], 14.0)
        self.assertEqual(rep["scenes"][-1]["to"], [6.15, 14.0])
        self.assertTrue(any("holds" in n and "close" in n for n in rep["notes"]), rep["notes"])
        self.assertEqual(common.read_json(d / "showtime.json")["duration"], 14.0)
        voice = [t for t in common.read_json(d / "audio" / "mix.json")["tracks"] if t.get("kind") == "voice"]
        self.assertEqual([t["start"] for t in voice], [0.3, 2.55, 6.45])       # the lines never move
        # shorter than the speech: an error that names the total that works (the close's line ends at 7.65 s)
        cp = showtime("retime", d, "--from-voice", tl, "--total", "7", check=False)
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("would cut the last line", cp.stderr)
        m = re.search(r"--total ([\d.]+) or more", cp.stderr)
        self.assertTrue(m, cp.stderr)
        self.assertEqual(float(m.group(1)), 7.7)
        rep = json.loads(showtime("retime", d, "--from-voice", tl, "--total", m.group(1), "--json").stdout)
        self.assertEqual(rep["scenes"][-1]["to"], [6.15, 7.7])


# ------------------------------------------------------------------ 2. Manim: silent film, mix paths

SILENT_SCENE = '''from st_manim import *

class Card(ShowScene):
    def construct(self):
        t = title("Odd numbers")
        place(t, "top")
        self.play(FadeIn(t), run_time=0.5)
        self.hold(0.5)
'''

STUB_ONLY = "<!-- No voice-over: this film is music and on-screen labels only. -->\n"


class ManimSilent(Tmp):
    def manim_project(self, narration=STUB_ONLY):
        job = self.tmp / "odd-squares"
        d = job / "manim"
        d.mkdir(parents=True)
        (d / "scenes.py").write_text(SILENT_SCENE, encoding="utf-8")
        common.write_json(d / "manim.json", {"title": "odd", "voice": "voice/timeline.json", "narration": "narration.md"})
        if narration is not None:
            (d / "narration.md").write_text(narration, encoding="utf-8")
        return job, d

    def test_comment_only_narration_is_no_narration(self):
        job, d = self.manim_project()
        self.assertIsNone(cues_mod.load(None, d, "voice/timeline.json", "narration.md", 30))
        # the template's own stub (a comment and one line) is still narration
        (d / "narration.md").write_text("<!-- note -->\n## intro\nFirst line.\n", encoding="utf-8")
        c = cues_mod.load(None, d, "voice/timeline.json", "narration.md", 30)
        self.assertEqual([ln["id"] for ln in c["lines"]], ["intro"])
        # an explicit --cues file with no lines is still an error (asked for, and empty)
        (d / "narration.md").write_text(STUB_ONLY, encoding="utf-8")
        with self.assertRaises(common.ShowtimeError):
            cues_mod.load("narration.md", d, None, None, 30)
        rep = json.loads(showtime("manim", "check", d, "--static", "--json").stdout)
        self.assertEqual(rep["errors"], 0, rep["findings"])
        self.assertFalse([f for f in rep["findings"] if "narration" in f["message"] and f["level"] == "ERROR"])
        cp = showtime("manim", "cues", d, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no narration.md with lines", cp.stderr)

    def test_mix_track_paths(self):
        from st.manim_run.render import _track_paths
        job, d = self.manim_project()
        (d / "audio").mkdir()
        (d / "audio" / "bed.wav").write_bytes(b"RIFF")
        (d / "sting.wav").write_bytes(b"RIFF")
        bases = [d / "audio", d, job]
        # relative to the Manim folder, to the spec's folder, absolute, missing (left for the mix to report)
        self.assertEqual(_track_paths({"file": "audio/bed.wav"}, bases)["file"], str((d / "audio" / "bed.wav").resolve()))
        self.assertEqual(_track_paths({"file": "bed.wav"}, bases)["file"], str((d / "audio" / "bed.wav").resolve()))
        self.assertEqual(_track_paths({"file": "sting.wav"}, bases)["file"], str((d / "sting.wav").resolve()))
        self.assertEqual(_track_paths({"file": "nope.wav"}, bases)["file"], "nope.wav")
        self.assertEqual(_track_paths({"compose": {"style": "x"}}, bases), {"compose": {"style": "x"}})

    @unittest.skipIf(FAST, "renders (needs the manim extra)")
    def test_silent_render_with_mix_from_the_job_folder(self):
        from st.manim_run.render import manim_installed
        if not manim_installed():
            self.skipTest("manim extra not installed: showtime setup --with manim")
        job, d = self.manim_project()
        (d / "audio").mkdir()
        showtime("audio", "compose", "--style", "ambient-pad", "--dur", "2", "--seed", "2", "-o", d / "audio" / "bed.wav")
        common.write_json(d / "audio" / "mix.json", {"tracks": [{"id": "bed", "kind": "music", "file": "audio/bed.wav"}]})
        # run from the job folder, the way the benchmark agent did: --mix relative to the current folder,
        # the track's file relative to the Manim folder
        r = json.loads(showtime("manim", "render", "manim", "--mix", "manim/audio/mix.json", "--size", "256x144",
                                "--fps", "10", "--json", cwd=job).stdout)
        self.assertIsNone(r["cues"])
        self.assertIn("mixed", r.get("audio_note") or "")
        from st import ff
        cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", r["output"]],
                            stdout=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertIn("audio", [s["codec_type"] for s in json.loads(cp.stdout)["streams"]])
        # a mix that is nowhere: the error says where it looked
        cp = showtime("manim", "render", "manim", "--mix", "audio/nope.json", "--size", "256x144", "--fps", "10",
                      cwd=job, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("current folder and in the project folder", cp.stderr)


# ------------------------------------------------------------------ 3. doctor: the command runs another showtime

HOST_VARS = ("CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHOWTIME_") and k not in HOST_VARS}
    env.update({k: str(v) for k, v in extra.items()})
    if "HOME" in extra:
        env["USERPROFILE"] = str(extra["HOME"])
    return env


class ShimDrift(Tmp):
    def copy_skill(self, dest: Path, version: str) -> Path:
        dest.mkdir(parents=True)
        for part in ("bin", "lib"):
            shutil.copytree(str(SKILL / part), str(dest / part), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        init = dest / "lib" / "st" / "__init__.py"
        init.write_text(re.sub(r'__version__ = "[^"]+"', '__version__ = "%s"' % version, init.read_text(encoding="utf-8")),
                        encoding="utf-8")
        return dest

    def doctor_row(self, env):
        cp = subprocess.run([sys.executable, str(LAUNCHER), "doctor", "--quick", "--json"], env=env, cwd=str(self.tmp),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        return {r["check"]: r for r in json.loads(cp.stdout)["checks"]}["showtime command"]

    def test_unit(self):
        home, user = self.tmp / "home", self.tmp / "user"
        user.mkdir()
        self.assertEqual(shim.install(home, SKILL)[0], "ok")
        self.assertIsNone(shim.drift(home, SKILL, user))
        newer = self.copy_skill(self.tmp / "newer" / "showtime", "9.9.9")
        shim.record(home, newer)
        d = shim.drift(home, SKILL, user)
        self.assertIn("9.9.9", d["problem"])
        self.assertIn("update showtime", d["fix"])
        shim.record(home, SKILL)
        self.copy_skill(user / ".claude" / "skills" / "showtime", "9.9.8")
        d = shim.drift(home, SKILL, user)
        self.assertIn("9.9.8", d["problem"])
        self.assertIn("doctor", d["fix"])
        self.assertIn(str(user / ".claude" / "skills" / "showtime"), d["fix"])

    def test_doctor_warns_on_a_newer_recorded_skill(self):
        home, user = self.tmp / "home", self.tmp / "user"
        user.mkdir()
        shim.install(home, SKILL)
        newer = self.copy_skill(self.tmp / "other-host" / "showtime", "9.9.9")
        shim.record(home, newer)                 # another agent host runs 9.9.9 through the same home
        row = self.doctor_row(clean_env(HOME=user, SHOWTIME_HOME=home, SHOWTIME_OFFLINE="1"))
        self.assertEqual(row["status"], "warn", row)
        self.assertIn("showtime 9.9.9 at %s" % newer, row["detail"])
        self.assertIn("showtime %s at %s" % (__version__, SKILL), row["detail"])
        self.assertIn("update showtime", row["hint"])
        self.assertEqual(shim.recorded_skill(home), newer, "doctor never points the command at an older skill")

    def test_doctor_warns_when_a_newer_skill_is_installed(self):
        home, user = self.tmp / "home", self.tmp / "user"
        user.mkdir()
        shim.install(home, SKILL)
        plugin = self.copy_skill(user / ".claude" / "plugins" / "cache" / "mk" / "showtime" / "9.9.9" / "skills" / "showtime", "9.9.9")
        row = self.doctor_row(clean_env(HOME=user, SHOWTIME_HOME=home, SHOWTIME_OFFLINE="1"))
        self.assertEqual(row["status"], "warn", row)
        self.assertIn("showtime 9.9.9 is installed at %s" % plugin, row["detail"])
        self.assertIn(str(plugin / "bin"), row["hint"])
        # running that one once re-points the command; then doctor is clean
        subprocess.run([sys.executable, str(plugin / "lib" / "st" / "launcher.py"), "version"],
                       env=clean_env(HOME=user, SHOWTIME_HOME=home), cwd=str(self.tmp), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=120)
        self.assertEqual(Path(shim.recorded_skill(home)).resolve(), plugin.resolve())
        self.assertIsNone(shim.drift(home, plugin, user))

    def test_same_skill_is_clean(self):
        home, user = self.tmp / "home", self.tmp / "user"
        user.mkdir()
        shim.install(home, SKILL)
        row = self.doctor_row(clean_env(HOME=user, SHOWTIME_HOME=home, SHOWTIME_OFFLINE="1"))
        self.assertEqual(row["status"], "pass", row)

    def test_unknown_template_names_the_version(self):
        cp = showtime("new", "no-such-template", self.tmp / "x", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("this is showtime %s at" % __version__, cp.stderr)
        self.assertIn("showtime doctor", cp.stderr)


# ------------------------------------------------------------------ 4. missing glyphs

GLYPHS_UNIT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const g = await import(pathToFileURL(path.join(process.argv[2], 'scripts', 'lib', 'glyphs.mjs')).href);
const faces = [{ family: 'Inter', unicodeRange: 'U+0000-00FF, U+2000-206F, U+2191, U+2193', status: 'loaded' },
               { family: 'Other', unicodeRange: 'U+2082', status: 'loaded' }];
console.log(JSON.stringify({
  narrowed: g.uncovered([...'—₂→↑★'], "'Inter', system-ui, sans-serif", faces),
  noFaces: g.uncovered([...'—₂'], "'Nope', sans-serif", faces),
  markup: g.asMarkup('CO₂ and H₂O, x²⁺'),
  fix: g.glyphFix([...'₂→★'], "'Inter', system-ui, sans-serif", 'Mauna Loa CO₂ → up ★'),
  ranges: g.parseRanges('U+0-FF, U+131, U+4??'),
}));
"""


class Glyphs(Tmp):
    def test_unit(self):
        f = self.tmp / "g.mjs"
        f.write_text(GLYPHS_UNIT, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(f), str(SKILL)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r = json.loads(cp.stdout)
        self.assertEqual(r["narrowed"], ["₂", "→", "★"])        # — and ↑ are in Inter's ranges; 'Other' is not in the stack
        self.assertEqual(r["noFaces"], ["—", "₂"])
        self.assertEqual(r["markup"], "CO<sub>2</sub> and H<sub>2</sub>O, x<sup>2+</sup>")
        self.assertIn("₂ (U+2082), → (U+2192), ★ (U+2605)", r["fix"]["chars"])
        fix = r["fix"]["fix"]
        self.assertIn('"CO<sub>2</sub>" for "CO₂"', fix)
        self.assertIn("vertical-align: baseline", fix)
        self.assertIn("arrow-right.svg", fix)
        self.assertIn("unicode-range: U+2605", fix)
        self.assertIn("font-family: 'Inter', 'Glyph Fallback', system-ui, sans-serif", fix)
        self.assertEqual(r["ranges"], [[0, 255], [305, 305], [1024, 1279]])

    @unittest.skipIf(FAST, "needs a browser")
    def test_check_names_the_missing_glyphs(self):
        proj = self.tmp / "co2"
        proj.mkdir()
        common.write_json(proj / "showtime.json", {"width": 960, "height": 540, "fps": 30, "duration": 2})
        (proj / "index.html").write_text(
            "<!doctype html><html><head><meta charset=\"utf-8\"><script src=\"/_st/stage.js\"></script>"
            "<link rel=\"stylesheet\" href=\"/_st/themes/fonts/inter.css\">"
            "<style>body{background:#10141c;color:#f3efe6;font-family:'Inter',system-ui,sans-serif}"
            "h1{position:absolute;left:60px;top:180px;margin:0;font-size:64px;font-weight:700}</style></head><body>"
            "<section data-start=\"0\" data-dur=\"2\"><h1>CO₂ is up — 1959–2025</h1></section></body></html>",
            encoding="utf-8")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "2",
                                  check=False).stdout)
        f = [x for x in rep["findings"] if x["code"] == "font_not_embedded"]
        self.assertEqual(len(f), 1, rep["findings"])
        self.assertIn("the page's fonts have no ₂ (U+2082)", f[0]["message"])
        self.assertNotIn("U+2014", f[0]["message"])           # the dashes are in Inter: not named any more
        self.assertIn("CO<sub>2</sub>", f[0]["fix"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])
