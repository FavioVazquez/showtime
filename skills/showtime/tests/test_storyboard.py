#!/usr/bin/env python3
"""`showtime new <template> <dir> --from-storyboard FILE` (lib/st/storyboard.py): a storyboard table -> a project.

Pure Python unless noted: the table parser (the reference format in English, a Chinese table with a toolchain
table after it, odd and missing lengths, columns in another order, extra columns, an unknown header, a
storyboard.json whose vo names script lines), the copy rule (a card or title's quoted words and "text:" are
on-screen copy, every other Visual is a brief), the plan (estimated lengths, the narration fit in words or
characters per second), the project files (one scene per shot, narration.md in order with its pins, the plan),
the CLI (stdin, canvas templates and --duration refused), and `retime --from-voice` against the plan (a fake
voice timeline: the pins keep the planned lengths, a silent shot keeps its length, a long line is named).
With a browser (skipped with --fast): `showtime check` passes (0 errors) and warns about the briefs.

Fixtures: tests/fixtures/storyboard (two excerpts from understanding-ladder, MIT; see its README).

usage: python tests/test_storyboard.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
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
FIX = TESTS_DIR / "fixtures" / "storyboard"
sys.path.insert(0, str(SKILL / "lib"))

from st import storyboard as sb  # noqa: E402
from st.common import ShowtimeError  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
FAST = "--fast" in sys.argv


def showtime(*args, check=True, cwd=None, stdin=None, timeout=180):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd, input=stdin,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def scenes(page: str):
    """[(id, data-dur)] of the <section> scenes, in page order."""
    return [(m.group(1), float(m.group(2))) for m in
            re.finditer(r'<section class="scene" id="([^"]+)" data-start="[^"]+" data-dur="([\d.]+)"', page)]


def voice_lines(text: str):
    """narration.md as `showtime voice script` reads it (its own parser when numpy is there)."""
    try:
        from st.voice.script import parse_markdown
    except ImportError:
        return [{"id": k, "text": v} for k, v in sb._section_lines(text).items()]
    return parse_markdown(text)[1]


class TestParse(unittest.TestCase):
    def test_reference_table(self):
        p = sb.plan(sb.load(str(FIX / "level-4-en.md")))
        self.assertIsNone(p["lang"])
        self.assertEqual([s["shot"] for s in p["shots"]], ["1", "2", "3", "last"])    # the "… | …" row is left out
        self.assertEqual([s["dur"] for s in p["shots"]], [5, 10, 12, 6])
        self.assertEqual(p["duration"], 33)
        first = p["shots"][0]
        self.assertEqual(first["copy"], ["Why gradient descent goes downhill"])
        self.assertEqual(first["brief"], "Title card")
        self.assertEqual(p["title"], "Why gradient descent goes downhill")
        # a description is a brief, never on-screen copy; "Recap card: three points" has no quoted words
        self.assertEqual(p["shots"][1]["copy"], [])
        self.assertEqual(p["shots"][1]["brief"], "A bowl-shaped surface, a ball resting on its side")
        self.assertEqual(p["shots"][3]["copy"], [])
        self.assertEqual(p["shots"][2]["narration"], "The gradient points up the steepest slope.")
        self.assertTrue(all(s["fits"] for s in p["shots"]))

    def test_chinese_table(self):
        d = sb.load(str(FIX / "fourier-zh.md"))
        self.assertEqual(set(d["columns"].values()), {"shot", "length", "visual", "narration"})   # not the toolchain table
        p = sb.plan(d)
        self.assertEqual(p["lang"], "zh")
        self.assertEqual(p["unit"], "characters")
        self.assertEqual(len(p["shots"]), 9)
        self.assertEqual([s["dur"] for s in p["shots"]], [6, 8, 10, 12, 12, 10, 12, 10, 10])
        self.assertEqual(p["duration"], 90)
        self.assertEqual(p["shots"][0]["copy"], ["正弦波怎么叠出方波"])
        self.assertEqual(p["shots"][0]["brief"], "标题卡")
        self.assertEqual(p["shots"][6]["copy"], [])            # 标注「约 9%」 is a label to draw, not a card
        self.assertTrue(p["shots"][6]["brief"].startswith("镜头放大到跳变点"))
        self.assertEqual(p["shots"][0]["units"], 22)           # Han characters, punctuation left out
        # 22 characters in 6 s is over the 3.2 characters/s budget: named, with what to cut
        lines = sb.fit_lines(p)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("shot-1: 22 characters in 6 s"), lines[0])

    def test_lengths(self):
        cases = {"5 s": 5, "5s": 5, "5 sec": 5, "10 seconds": 10, "0:05": 5, "1:05": 65, "0:05-0:12": 7,
                 "5-7 s": 6, "5–7 s": 6, "2 to 4 s": 3, "~6秒": 6, "6 秒": 6, "1 分 30 秒": 90, "1m30s": 90,
                 "1.5 min": 90, "800 ms": 0.8, "3,5 s": 3.5, "8": 8, 4: 4}
        for text, want in cases.items():
            self.assertAlmostEqual(sb.parse_length(text), want, msg=repr(text))
        for text in ("", "…", "...", "-", "TBD", "?", "0 s", None):
            self.assertIsNone(sb.parse_length(text), repr(text))

    def test_reordered_extra_and_missing(self):
        d = sb.load(str(FIX / "odd.md"))
        self.assertEqual(d["columns"], {"Narration": "narration", "Visual": "visual", "On screen": "onscreen",
                                        "Length": "length", "Sound": "sound", "Shot": "shot"})
        p = sb.plan(d)
        s = p["shots"]
        self.assertEqual([x["dur"] for x in s[:4]], [5, 7, 6, 4])
        self.assertEqual(s[0]["copy"], ["Yeast + sugar"])                 # the On screen column
        self.assertEqual(s[0]["sound"], "soft pop")
        self.assertEqual((s[3]["copy"], s[3]["brief"], s[3]["narration"]), (["Rise time: about an hour"], "", ""))
        # no length: estimated from 9 words at 2.8 words/s + the 0.3 s lead + the 0.6 s tail, to the half second
        self.assertTrue(s[4]["estimated"])
        self.assertEqual(s[4]["dur"], 4.5)
        self.assertFalse(any(x["estimated"] for x in s[:4]))

    def test_unknown_header_and_errors(self):
        d = sb.parse_markdown("| A | B | C | D |\n|---|---|---|---|\n| 1 | 3 s | A red dot | Hello there. |\n")
        self.assertEqual(d["shots"][0]["visual"], "A red dot")
        self.assertEqual(d["shots"][0]["narration"], "Hello there.")
        self.assertTrue(d["notes"])
        # a two-column AV script: Audio is the voice when there is no narration column
        d = sb.parse_markdown("| Video | Audio |\n|---|---|\n| A cat | Meet the cat. |\n")
        self.assertEqual((d["shots"][0]["visual"], d["shots"][0]["narration"]), ("A cat", "Meet the cat."))
        with self.assertRaises(ShowtimeError):
            sb.parse_markdown("No table here, just words.")
        with self.assertRaises(ShowtimeError):
            sb.parse_markdown("| Need | Tool |\n|---|---|\n| voice | kokoro |\n")
        # pipes inside a cell and Markdown emphasis
        d = sb.parse_markdown("| Shot | Visual | Narration |\n|---|---|---|\n| 1 | **Bold** a \\| b | `x` is *one* |\n")
        self.assertEqual((d["shots"][0]["visual"], d["shots"][0]["narration"]), ("Bold a | b", "x is one"))

    def test_storyboard_json(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-sb-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "script.md").write_text("## hook\nMeet the cat.\n\n## nap\nIt naps all day.\n", encoding="utf-8")
        (tmp / "storyboard.json").write_text(json.dumps({"rows": [
            {"id": "s1-hook", "dur": 3, "visual": "A cat on a sofa", "onscreen": ["Meet Mo"], "vo": ["hook"]},
            {"id": "s2-nap", "dur": "4 s", "visual": "The cat asleep", "vo": ["nap", "missing"]}]}), encoding="utf-8")
        d = sb.load(str(tmp))                       # a folder: its storyboard.json
        p = sb.plan(d)
        self.assertEqual([s["id"] for s in p["shots"]], ["s1-hook", "s2-nap"])    # the artist's scene ids
        self.assertEqual([s["narration"] for s in p["shots"]], ["Meet the cat.", "It naps all day."])
        self.assertEqual(p["shots"][0]["copy"], ["Meet Mo"])
        self.assertTrue(any("missing" in n for n in p["notes"]))
        # what `new --from-storyboard` writes reads back the same
        again = sb.plan(sb.parse_json(sb.storyboard_json(p)))
        self.assertEqual([(s["id"], s["dur"], s["narration"]) for s in again["shots"]],
                         [(s["id"], s["dur"], s["narration"]) for s in p["shots"]])


class TestProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-sb-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_english_project(self):
        out = self.tmp / "gd"
        res = json.loads(showtime("new", "dom", out, "--from-storyboard", FIX / "level-4-en.md", "--json").stdout)
        self.assertEqual(res["storyboard"]["shots"], 4)
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["audio", "index.html", "narration.md", "showtime.json", "storyboard.json", "storyboard.md"])
        cfg = json.loads((out / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["duration"], cfg["poster"], cfg["title"]), (33, 0, "Why gradient descent goes downhill"))
        self.assertNotIn("subtitle", cfg)                                  # no template words left behind
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(scenes(page), [("shot-1", 5), ("shot-2", 10), ("shot-3", 12), ("shot-4", 6)])
        self.assertIn('href="/_st/themes/bold.css"', page)                 # the dom template's look
        self.assertIn('<p class="copy" style="--i:1">Why gradient descent goes downhill</p>', page)
        self.assertIn('data-storyboard-brief style="--i:1">A bowl-shaped surface, a ball resting on its side</p>', page)
        self.assertNotIn("Northwind", page)
        # the narration, in order, one line per shot, each pinned where its shot starts in the voice timeline
        lines = voice_lines((out / "narration.md").read_text(encoding="utf-8"))
        self.assertEqual([ln["id"] for ln in lines], ["shot-1", "shot-2", "shot-3", "shot-4"])
        self.assertEqual(lines[0]["text"], "This video explains one thing: how gradient descent finds the lowest point.")
        self.assertEqual(lines[3]["text"], "To recap…")
        if "at" in lines[1]:
            self.assertEqual([ln["at"] for ln in lines], [0, 4.7, 14.4, 26.1])
        plan = json.loads((out / "storyboard.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["generator"], sb.GENERATOR)
        self.assertEqual([r["planned"]["dur"] for r in plan["rows"]], [5, 10, 12, 6])
        mix = json.loads((out / "audio" / "mix.json").read_text(encoding="utf-8"))
        self.assertEqual(mix["tracks"][0]["compose"]["sections"], "0:intro,5:verse,15:verse,27:outro")

    def test_chinese_on_stdin_vertical(self):
        out = self.tmp / "zh"
        cp = showtime("new", "short", out, "--from-storyboard", "-",
                      stdin=(FIX / "fourier-zh.md").read_text(encoding="utf-8"))
        self.assertIn("9 shot(s), 90.0 s planned", cp.stderr)
        self.assertIn("shot-1: 22 characters in 6 s", cp.stderr)
        cfg = json.loads((out / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["width"], cfg["height"], cfg["lang"]), (1080, 1920, "zh"))
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="zh">', page)
        self.assertIn("/_st/themes/fonts/noto-sans-jp.css", page)
        nm = (out / "narration.md").read_text(encoding="utf-8")
        self.assertIn("lang: zh", nm)
        lines = voice_lines(nm)
        self.assertEqual(len(lines), 9)
        self.assertEqual(lines[8]["text"], "回顾：只用奇数倍频率；振幅是 1/n；跳变点旁总有约 9% 的尖角。")

    def test_refusals(self):
        cp = showtime("new", "film", self.tmp / "f", "--from-storyboard", FIX / "level-4-en.md", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("canvas template", cp.stderr)
        self.assertFalse((self.tmp / "f").exists())                       # refused before anything is written
        cp = showtime("new", "dom", self.tmp / "d", "--from-storyboard", FIX / "level-4-en.md", "-d", 20, check=False)
        self.assertIn("--duration and --from-storyboard", cp.stderr)
        cp = showtime("new", "dom", self.tmp / "m", "--from-storyboard", self.tmp / "nope.md", check=False)
        self.assertIn("storyboard not found", cp.stderr)
        cp = showtime("new", "dom", self.tmp / "e", "--from-storyboard", "-", stdin="", check=False)
        self.assertIn("no storyboard on stdin", cp.stderr)
        for c in (cp,):
            self.assertNotIn("Traceback", c.stderr)

    def test_retime_from_voice_keeps_the_plan(self):
        out = self.tmp / "bread"
        showtime("new", "dom", out, "--from-storyboard", FIX / "odd.md")
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="shot-4" data-start="#shot-3" data-dur="4.00" data-storyboard-shot="4" data-silent', page)
        lines = voice_lines((out / "narration.md").read_text(encoding="utf-8"))
        self.assertEqual([ln["id"] for ln in lines], ["shot-1", "shot-2", "shot-3", "shot-5"])   # shot 4 has no line

        # a voice timeline as `voice script` writes it from the pins (no TTS here): shot-2's line runs long and
        # pushes shot-3's line 1.2 s late
        def line(lid, start, end, nxt):
            return {"id": lid, "text": lid, "file": "lines/%s.wav" % lid, "start": start, "end": end,
                    "slot": {"start": start, "end": nxt, "duration": round(nxt - start, 3)}, "words": []}
        if "at" in lines[1]:
            # the pin after the silent shot counts its 4 s (pins win over data-silent: no drift)
            self.assertEqual([ln["at"] for ln in lines], [0, 4.7, 11.4, 21.1])
        tl = {"duration": 24.9, "lines": [line("shot-1", 0, 2.5, 4.7), line("shot-2", 4.7, 11.9, 12.6),
                                          line("shot-3", 12.6, 15.8, 21.1), line("shot-5", 21.1, 24.3, 24.9)]}
        tl["lines"][3]["at"] = 21.1
        (out / "voice").mkdir()
        (out / "voice" / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        rep = json.loads(showtime("retime", out, "--from-voice", out / "voice" / "timeline.json", "--json").stdout)
        got = scenes((out / "index.html").read_text(encoding="utf-8"))
        self.assertEqual([g[0] for g in got], ["shot-1", "shot-2", "shot-3", "shot-4", "shot-5"])
        durs = [g[1] for g in got]
        self.assertEqual(durs[0], 5)                     # fits: the planned length
        self.assertAlmostEqual(durs[1], 8.2, places=1)   # outgrew its 7 s
        self.assertAlmostEqual(durs[2], 4.8, places=1)   # started late, ends on its pin
        self.assertEqual(durs[3], 4)                     # silent: kept
        mapping = {m["line"]: m["at"] for m in rep["voice"]["mapping"]}
        self.assertAlmostEqual(mapping["shot-5"], 22.3, places=2)       # on the plan: shot 5 starts at 22
        notes = " ".join(rep["notes"])
        self.assertIn("the voice outgrew 1 shot(s): shot-2 8.2 s (planned 7 s, 8 words)", notes)
        self.assertIn("shot-3 4.8 s (planned 6 s)", notes)


QUESTION = """| Shot | Length | Visual | Narration |
|---|---|---|---|
| 1 | 5 s | Title card: "Which plane is red?" | Three planes take off. |
| 2 | 3.5 s | The three planes, a question mark | (pause) |
| 3 | 6 s | The red plane lit | *(silence)* |
| 4 | 5 s | The answer | The red one flies lowest. |
| 5 | 3 s | End card | — |
"""


def _line(lid, start, end, nxt, at=None):
    """A voice timeline line as `voice script` writes it (no TTS here)."""
    d = {"id": lid, "text": lid, "file": "lines/%s.wav" % lid, "start": start, "end": end,
         "duration": round(end - start, 3), "pause_after": 0.35,
         "slot": {"start": start, "end": nxt, "duration": round(nxt - start, 3)}, "words": []}
    if at is not None:
        d["at"] = at
    return d


class TestSilentShots(unittest.TestCase):
    """A narration cell that is a direction ("(pause)") is a silent shot, and pins win over data-silent."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-sb-silent-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_directions_are_silence(self):
        for cell in ("(pause)", "*(silence)*", "[beat]", "(pause) (music swells)", "（停顿）", "—", "", " - "):
            self.assertTrue(sb.stage_direction(cell), cell)
        for cell in ("Wait (pause) for it.", "Pause.", "1/n", "Is it red? (Yes.) It is."):
            self.assertFalse(sb.stage_direction(cell), cell)
        p = sb.plan(sb.parse_markdown(QUESTION))
        self.assertEqual([s["narration"] for s in p["shots"]],
                         ["Three planes take off.", "", "", "The red one flies lowest.", ""])
        self.assertEqual(p["shots"][1]["direction"], "(pause)")
        self.assertEqual([s["dur"] for s in p["shots"]], [5, 3.5, 6, 5, 3])           # the table's lengths
        nm = sb.narration_md(p)
        self.assertNotIn("pause", nm.split("-->")[1].lower())                         # never voiced
        lines = voice_lines(nm)
        self.assertEqual([ln["id"] for ln in lines], ["shot-1", "shot-4"])
        if "at" in lines[1]:
            # shot 4 starts at 14.5 s; one narrated shot before it gives 0.3 s of picture
            self.assertEqual([ln["at"] for ln in lines], [0, 14.2])
        self.assertIn("| (pause) |", sb.storyboard_md(p))
        self.assertEqual(sb.storyboard_json(p)["rows"][1]["direction"], "(pause)")
        # a silent opening shot: the first line's pin is a video time (its shot's start + the pad)
        p2 = sb.plan(sb.parse_markdown("| Shot | Length | Visual | Narration |\n|---|---|---|---|\n"
                                       "| 1 | 3 s | Logo | (music only) |\n| 2 | 4 s | A | One. |\n"
                                       "| 3 | 4 s | B | Two. |\n"))
        lines2 = voice_lines(sb.narration_md(p2))
        if "at" in lines2[0]:
            self.assertEqual([ln["at"] for ln in lines2], [3.3, 7])

    def _project(self):
        out = self.tmp / "planes"
        showtime("new", "dom", out, "--from-storyboard", "-", stdin=QUESTION)
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="shot-2" data-start="#shot-1" data-dur="3.50" data-storyboard-shot="2" data-silent', page)
        (out / "voice").mkdir()
        return out

    def _retime(self, out, tl):
        (out / "voice" / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        rep = json.loads(showtime("retime", out, "--from-voice", out / "voice" / "timeline.json", "--json").stdout)
        return rep, [g[1] for g in scenes((out / "index.html").read_text(encoding="utf-8"))]

    def test_pins_win_over_silent_shots(self):
        out = self._project()
        # line 2 pinned at 14.2 (as narration.md says): the two silent shots fill the gap, no drift
        rep, durs = self._retime(out, {"duration": 19.2, "lines": [
            _line("shot-1", 0, 2.4, 14.2), _line("shot-4", 14.2, 16.6, 17.2, at=14.2)]})
        self.assertEqual(durs[:3], [5, 3.5, 6])
        at = {m["line"]: m["at"] for m in rep["voice"]["mapping"]}
        self.assertAlmostEqual(at["shot-4"], 14.8, places=2)            # shot 4 starts at 14.5, + the pad
        self.assertFalse([n for n in rep["notes"] if "pinned" in n], rep["notes"])

    def test_short_gap_shrinks_the_silent_shots_with_a_note(self):
        out = self._project()
        # pinned 10 s in after a 2.4 s line: 7.25 s of gap for 9.5 s of silent shots; the pin still wins
        rep, durs = self._retime(out, {"duration": 13, "lines": [
            _line("shot-1", 0, 2.4, 10.0), _line("shot-4", 10.0, 12.4, 13.0, at=10.0)]})
        at = {m["line"]: m["at"] for m in rep["voice"]["mapping"]}
        self.assertAlmostEqual(at["shot-4"], 10.6, places=1)            # 10.0 + 2 pads
        self.assertAlmostEqual(sum(durs[1:3]), 7.25, delta=0.05)
        self.assertTrue(all(d >= 1.0 for d in durs[1:3]), durs)
        notes = " ".join(rep["notes"])
        self.assertIn("line shot-4 is pinned at 10.00s, which leaves 7.25s", notes)
        self.assertIn("shot-2, shot-3 (they want 9.50s)", notes)

    def test_a_gap_too_short_keeps_the_silent_shots(self):
        out = self._project()
        # pinned 5 s in: 2.25 s for 9.5 s would leave shot-2 under 1 s, so both keep their lengths
        rep, durs = self._retime(out, {"duration": 8, "lines": [
            _line("shot-1", 0, 2.4, 5.0), _line("shot-4", 5.0, 7.4, 8.0, at=5.0)]})
        self.assertEqual(durs[1:3], [3.5, 6])
        notes = " ".join(rep["notes"])
        self.assertIn("line shot-4 is pinned at 5.00s, which leaves 2.25s", notes)
        self.assertIn("so they keep their lengths", notes)

    def test_a_pin_the_voice_ran_past_keeps_the_silent_shots(self):
        # the reviewer's repro: shot-1's line is 14.5 s, so voice script starts shot-4 at 14.85, past its 14.2 pin;
        # the silent shots were squeezed to 0 s (the question beat vanished)
        out = self._project()
        rep, durs = self._retime(out, {"duration": 17.85, "lines": [
            _line("shot-1", 0, 14.5, 14.85), _line("shot-4", 14.85, 17.25, 17.85, at=14.2)]})
        self.assertEqual(durs[1:3], [3.5, 6])
        notes = " ".join(rep["notes"])
        self.assertIn("line shot-4 is pinned at 14.20s, but the voice starts it at 14.85s", notes)
        self.assertFalse([n for n in rep["notes"] if "only 0.00s" in n], rep["notes"])

    def test_040_pins_keep_the_silent_shots(self):
        # a narration.md from 0.4.0 pinned shot-4 at 4.7 (the silent shots left out), voiced again with 0.4.1
        out = self._project()
        rep, durs = self._retime(out, {"duration": 7.7, "lines": [
            _line("shot-1", 0, 2.4, 4.7), _line("shot-4", 4.7, 7.1, 7.7, at=4.7)]})
        self.assertEqual(durs[1:3], [3.5, 6])
        notes = " ".join(rep["notes"])
        self.assertIn("by a narration.md from showtime 0.4.0", notes)
        self.assertIn("Regenerate narration.md", notes)
        self.assertTrue(sb.legacy_pin(out, "shot-4", 4.7))
        self.assertFalse(sb.legacy_pin(out, "shot-4", 14.2))       # the 0.4.1 pin

    def test_unpinned_line_after_a_silent_shot_keeps_its_length(self):
        out = self._project()
        rep, durs = self._retime(out, {"duration": 6, "lines": [
            _line("shot-1", 0, 2.4, 2.75), _line("shot-4", 2.75, 5.15, 5.75)]})
        self.assertEqual(durs[1:3], [3.5, 6])                           # added on top, as before
        at = {m["line"]: m["at"] for m in rep["voice"]["mapping"]}
        self.assertAlmostEqual(at["shot-4"], 0.3 + 2.75 + 9.5 + 0.3, places=1)


@unittest.skipIf(FAST, "--fast (needs a browser)")
class TestCheck(unittest.TestCase):
    def test_check_passes_and_names_the_briefs(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-sb-check-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for tpl, src in (("dom", "level-4-en.md"), ("short", "fourier-zh.md")):
            out = tmp / tpl
            showtime("new", tpl, out, "--from-storyboard", FIX / src)
            cp = showtime("check", out, "--json", "--samples", 4, "--no-determinism", check=False, timeout=900)
            rep = json.loads(cp.stdout)
            errors = [f for f in rep["findings"] if f["severity"] == "error"]
            self.assertEqual(errors, [], "%s: %s" % (tpl, errors))
            self.assertEqual(cp.returncode, 0)
            brief = [f for f in rep["findings"] if f["code"] == "storyboard_brief"]
            self.assertEqual(len(brief), 1, rep["findings"])
            self.assertIn("shot-2", brief[0]["message"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
