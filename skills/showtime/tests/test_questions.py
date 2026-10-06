#!/usr/bin/env python3
"""Stop-and-ask questions: showtime.json "questions" (scripts/lib/questions.mjs, lib/st/questions.py).

  * the schema, no browser: voice cues resolved where the mix plays each line (`vo-<id>` tracks of retime
    --from-voice, tracks playing a line's own file at an offset, a late vo.wav, vo.wav from 0), the same
    placement as the hearing pass, seconds, offsets; ids unique, 2-9 choices, the answer index in range, cues that
    name a narration line, beats inside the video and apart; the mixer's Python resolver gives the
    same times; `retime -d` moves questions given in seconds;
  * the mix: a "questions" block ducks the music bed under every pause and think beat (measured) and
    adds a soft tick on each second of the countdown;
  * `showtime check` reports question problems with codes and fixes;
  * `showtime export html`: the questions travel in the player manifest and the page config (the video
    draws its own beat), socratic.json is written beside it, --no-questions and --controls none leave
    them out of the player; in headless Chrome the player pauses on the question's own frame (the
    question-beat component shows its countdown there), a key answers (right/wrong mark, the reply),
    Enter plays on from the end of the beat; seeking past a question passes it, seeking back before it
    asks it again; play (k) while it waits plays through the beat; on a phone held upright the card sits
    under the picture, which stays in view; an artifact export with minimal controls asks too.

Stdlib only. usage: python tests/test_questions.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from _listen import needs_listen

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
QMJS = SKILL / "scripts" / "lib" / "questions.mjs"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH")) or "node"
TMP = Path(tempfile.mkdtemp(prefix="st-questions-test-"))

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<script type="module" src="/_st/components/index.js"></script>
</head><body><div class="stage">
<section class="scene" data-start="0" data-dur="7"><div class="center fill"><div data-st="question-beat" data-id="q1"></div></div></section>
<section class="scene" data-start="7" data-dur="2"><div class="center fill"><div data-st="question-beat" data-id="q2" data-at="0"></div></div></section>
</div></body></html>
"""
TIMELINE = {"duration": 6, "file": "vo.wav", "lines": [
    {"id": "intro", "start": 0, "end": 1.6, "speech_start": 0.05, "speech_end": 1.5, "slot": {"start": 0, "end": 2, "duration": 2},
     "file": "lines/01-intro.wav"},
    {"id": "ask", "start": 2, "end": 3.2, "speech_start": 2.1, "speech_end": 3.1, "slot": {"start": 2, "end": 6, "duration": 4},
     "file": "lines/02-ask.wav"}]}
QUESTIONS = [
    {"id": "q1", "at": "ask", "prompt": "Which is bigger?", "choices": ["2", "3", "4"], "answer": 2,
     "reply": {"0": "Too small.", "2": "Yes: 4 is the biggest."}},
    {"id": "q2", "at": 7.0, "prompt": "Done?", "choices": ["Yes", "No"], "answer": 0, "reply": "Done.", "think": 1.5},
]
# q1: the line "ask" is placed at 2.6 s (vo-ask) and its speech ends 1.1 s into it -> 3.7 s; beat to 6.7 s
Q1_T, Q1_RESUME, Q2_T, Q2_RESUME = 3.7, 6.7, 7.0, 8.5


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                     cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def make_project(root: Path, questions=None, page=PAGE, mix=True) -> Path:
    d = root
    (d / "voice").mkdir(parents=True, exist_ok=True)
    (d / "audio").mkdir(parents=True, exist_ok=True)
    (d / "voice" / "timeline.json").write_text(json.dumps(TIMELINE), encoding="utf-8")
    cfg = {"title": "Questions fixture", "width": 640, "height": 360, "fps": 30, "duration": 9, "background": "#101418",
           "questions": QUESTIONS if questions is None else questions}
    if mix:
        (d / "audio" / "mix.json").write_text(json.dumps({"tracks": [
            {"id": "vo-intro", "kind": "voice", "file": "voice/lines/01-intro.wav", "start": 0.3},
            {"id": "vo-ask", "kind": "voice", "file": "voice/lines/02-ask.wav", "start": 2.6}]}), encoding="utf-8")
        cfg["audio"] = "audio/mix.json"
    (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
    (d / "index.html").write_text(page, encoding="utf-8")
    return d


def resolve(cfg: dict, project: Path, duration=None) -> dict:
    """readQuestions() from scripts/lib/questions.mjs, run by node."""
    js = TMP / "resolve.mjs"
    js.write_text("const m = await import(process.argv[2]);\n"
                  "const o = JSON.parse(process.argv[3]);\n"
                  "console.log(JSON.stringify(m.readQuestions(o.dir, o.cfg, {fps: 30, duration: o.duration})));\n", encoding="utf-8")
    cp = subprocess.run([NODE, str(js), QMJS.as_uri(), json.dumps({"dir": str(project), "cfg": cfg, "duration": duration})],
                        env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
    assert cp.returncode == 0, cp.stderr
    return json.loads(cp.stdout)


class SchemaTest(unittest.TestCase):
    """The questions schema and its time resolution (no browser)."""

    @classmethod
    def setUpClass(cls):
        cls.proj = make_project(TMP / "schema")
        cls.cfg = json.loads((cls.proj / "showtime.json").read_text(encoding="utf-8"))

    def codes(self, questions, duration=9):
        r = resolve(dict(self.cfg, questions=questions), self.proj, duration)
        return {i["code"] for i in r["issues"]}, r

    def test_cues_follow_the_voice(self):
        r = resolve(self.cfg, self.proj, 9)
        self.assertEqual(r["issues"], [])
        q1, q2 = r["list"]
        self.assertEqual((q1["t"], q1["resume"], q1["think"], q1["from"]), (Q1_T, Q1_RESUME, 3, 2.6))
        self.assertEqual((q2["t"], q2["resume"]), (Q2_T, Q2_RESUME))
        self.assertEqual(q1["reply"], ["Too small.", "", "Yes: 4 is the biggest."])   # per choice
        self.assertEqual(q2["reply"], ["Done.", "Done."])                              # one line for all
        at = lambda a: resolve(dict(self.cfg, questions=[dict(QUESTIONS[0], at=a)]), self.proj)["list"][0]["t"]  # noqa: E731
        self.assertEqual(at("ask.start"), 2.7)          # speech start 2.1 + 0.6
        self.assertEqual(at("ask.end+0.5"), 4.2)
        self.assertEqual(at("intro"), 1.8)              # 1.5 + its own track's 0.3
        self.assertEqual(at("4.5"), 4.5)
        # without the per-line tracks the voice runs from the vo.wav track's start (here: none -> 0)
        bare = make_project(TMP / "bare", mix=False)
        r = resolve(json.loads((bare / "showtime.json").read_text(encoding="utf-8")), bare)
        self.assertEqual(r["list"][0]["t"], 3.1)

    def test_python_resolver_matches(self):
        from st import questions
        py = questions.beats(self.proj)
        js = resolve(self.cfg, self.proj)["list"]
        self.assertEqual([(b["id"], b["t"], b["resume"]) for b in py], [(q["id"], q["t"], q["resume"]) for q in js])

    def test_cues_follow_the_mix(self):
        """timeline.json times are vo.wav times: the cues land where the mix plays each line, in both resolvers
        and as the hearing pass places them."""
        from st import questions
        from st.qa.hearing import line_offsets
        mixes = {
            # each line's own file at an offset, no vo-<id> ids (one has no id at all)
            "files": ([{"kind": "voice", "file": "voice/lines/01-intro.wav", "start": 0.3},
                       {"id": "narr-ask", "kind": "voice", "file": "voice/lines/02-ask.wav", "start": 2.6}],
                      {"intro": 0.3, "ask": 0.6}, {"ask": 3.7, "ask.start": 2.7, "ask.end+0.5": 4.2, "intro": 1.8}),
            # the whole vo.wav, started late
            "late": ([{"id": "vo", "kind": "voice", "file": "voice/vo.wav", "start": 0.5}],
                     {"intro": 0.5, "ask": 0.5}, {"ask": 3.6, "ask.start": 2.6, "intro": 2.0}),
            # vo.wav from 0: the timeline's own times
            "zero": ([{"id": "vo", "kind": "voice", "file": "voice/vo.wav", "start": 0}],
                     {"intro": 0.0, "ask": 0.0}, {"ask": 3.1, "ask.start": 2.1, "intro": 1.5}),
        }
        for name, (tracks, offs, want) in mixes.items():
            with self.subTest(mix=name):
                proj = make_project(TMP / ("mix-" + name))
                (proj / "voice" / "lines").mkdir(exist_ok=True)
                for f in ("vo.wav", "lines/01-intro.wav", "lines/02-ask.wav"):
                    (proj / "voice" / f).write_bytes(b"")
                (proj / "audio" / "mix.json").write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
                cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
                tl = json.loads((proj / "voice" / "timeline.json").read_text(encoding="utf-8"))
                self.assertEqual({k: round(v, 4) for k, v in line_offsets(proj, tl).items()}, offs)
                qs = [dict(QUESTIONS[0], id="c%d" % i, at=at, think=0.1) for i, at in enumerate(want)]
                cfg["questions"] = qs
                (proj / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
                js = {q["at"]: q["t"] for q in resolve(cfg, proj)["list"]}
                py = {qs[int(b["id"][1:])]["at"]: b["t"] for b in questions.beats(proj)}
                self.assertEqual(js, want)
                self.assertEqual(py, want)

    def test_problems_are_named(self):
        q1 = QUESTIONS[0]
        cases = [
            ([q1, dict(q1)], "question_duplicate_id"),
            ([dict(q1, answer=3)], "question_answer_range"),
            ([dict(q1, answer="2")], "question_answer_range"),
            ([dict(q1, choices=["only one"])], "question_invalid"),
            ([dict(q1, at="nope")], "question_cue"),
            ([dict(q1, at="ask.middle")], "question_cue"),
            ([dict(q1, at=8.0)], "question_time"),                       # beat runs past the end (9 s)
            ([dict(q1, at=-1)], "question_time"),
            ([q1, dict(QUESTIONS[1], at=5.0)], "question_overlap"),      # inside q1's beat (3.7-6.7)
            ([dict(q1, think=0)], "question_invalid"),
            ([dict(q1, prompt="")], "question_invalid"),
            ([dict(q1, choices=list("ABCDE"))], "question_many_choices"),
            ([dict(q1, reply={"7": "x"})], "question_reply"),
        ]
        for qs, code in cases:
            codes, r = self.codes(qs)
            self.assertIn(code, codes, "%s: %s" % (code, r["issues"]))
            for i in r["issues"]:
                self.assertTrue(i["message"] and i["fix"], i)
        codes, _ = self.codes({"q1": q1})
        self.assertEqual(codes, {"questions_invalid"})
        self.assertEqual(resolve(dict(self.cfg, questions=False), self.proj), {"list": [], "issues": [], "off": True})
        missing = resolve(dict(self.cfg, questions=[dict(q1, at="nope")]), self.proj)["issues"][0]["message"]
        self.assertIn("intro, ask", missing)             # the lines it could have named

    def test_retime_moves_questions_in_seconds(self):
        proj = make_project(TMP / "retime")
        rep = json.loads(showtime("retime", proj, "-d", "18", "--json").stdout)
        self.assertTrue(any("question q2 at 7 -> 14" in c for c in rep["changes"]), rep["changes"])
        cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["questions"][1]["at"], 14)
        self.assertEqual(cfg["questions"][0]["at"], "ask")   # a voice cue follows the voice instead


class MixTest(unittest.TestCase):
    """A mix's "questions" block ducks the bed under every pause and think beat and can tick through it."""

    def level(self, wav: Path, t0: float, dur: float) -> float:
        cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-ss", str(t0), "-t", str(dur), "-i", str(wav),
                             "-af", "volumedetect", "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=60)
        return float(re.search(r"mean_volume: (-?[\d.]+) dB", cp.stderr).group(1))

    def test_duck_and_ticks(self):
        proj = make_project(TMP / "mix")
        tone = proj / "audio" / "tone.wav"
        subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=f=330:d=9", "-ac", "2", "-ar", "48000", str(tone)], check=True, timeout=60)
        spec = {"duration": 9, "tracks": [{"id": "bed", "kind": "music", "file": "audio/tone.wav", "level": "raw"}],
                "questions": {"duck_db": 12}, "master": {"engine": "none"}}
        (proj / "audio" / "bed.json").write_text(json.dumps(spec), encoding="utf-8")
        out = proj / "audio" / "bed.wav"
        rep = json.loads(showtime("audio", "mix", proj / "audio" / "bed.json", "-o", out, "--json").stdout)
        self.assertEqual([b["t"] for b in rep["questions"]["beats"]], [Q1_T, Q2_T])
        self.assertEqual(rep["questions"]["ticks"], 0)
        before, during = self.level(out, 1.0, 2.0), self.level(out, 4.2, 2.0)
        self.assertAlmostEqual(before - during, 12.0, delta=1.0)
        self.assertAlmostEqual(self.level(out, 7.2, 1.0), during, delta=1.0)   # q2's beat too
        spec["questions"] = {"tick": True}
        (proj / "audio" / "bed.json").write_text(json.dumps(spec), encoding="utf-8")
        rep = json.loads(showtime("audio", "mix", proj / "audio" / "bed.json", "-o", out, "--json").stdout)
        self.assertEqual(rep["questions"]["ticks"], 3 + 2)                       # think 3 s and 1.5 s
        ticks = sorted(t["id"] for t in rep["tracks"] if str(t["id"]).startswith("q-tick-"))
        self.assertEqual(ticks, ["q-tick-q1-1", "q-tick-q1-2", "q-tick-q1-3", "q-tick-q2-1", "q-tick-q2-2"])


@needs_listen
class CheckTest(unittest.TestCase):
    def test_check_reports_question_problems(self):
        bad = [dict(QUESTIONS[0], answer=4), dict(QUESTIONS[1], at="missing-line"), dict(QUESTIONS[1], id="q3", at=8.0)]
        proj = make_project(TMP / "check", questions=bad)
        cp = showtime("check", proj, "--json", "--no-timeline", "--no-determinism", "-n", "1", "--no-history", check=False)
        self.assertEqual(cp.returncode, 1, cp.stderr[-2000:])
        rep = json.loads(cp.stdout)
        got = {(f["code"], f.get("question")) for f in rep["findings"] if f["code"].startswith("question")}
        self.assertIn(("question_answer_range", "q1"), got)
        self.assertIn(("question_cue", "q2"), got)
        self.assertIn(("question_time", "q3"), got)       # 8 + 3 s runs past 9 s
        for f in rep["findings"]:
            if f["code"].startswith("question"):
                self.assertEqual(f["severity"], "error")
                self.assertTrue(f.get("fix"))


LONG_Q = [{"id": "q1", "at": 1.5, "prompt": "Where do the questions live?", "think": 3, "answer": 0,
           "choices": ["showtime.json", "skills/showtime/references/html-export.md", "index.html"], "reply": "In showtime.json."}]
LONG_FILM = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<script src="/_st/stage.js"></script><script src="/_st/film.js"></script>
</head><body><script>
Film.start({ look: '%s', fonts: ['600 1em "Inter Variable"', '750 1em "Inter Variable"'],
  scenes: function (T, g, F) { F.questionBeat(T, 'q1'); } });
</script></body></html>
"""
LONG_PAGE = PAGE.replace('data-dur="7"', 'data-dur="9"').replace(
    '<section class="scene" data-start="7" data-dur="2"><div class="center fill"><div data-st="question-beat" data-id="q2" data-at="0"></div></div></section>\n', "")


def long_pages() -> dict:
    """The beat on a light and a dark theme, a light and a dark look signature, and two canvas looks."""
    from st.variety import signatures as sig  # noqa: E402
    theme = lambda name, extra="": LONG_PAGE.replace("/_st/themes/neutral.css", "/_st/themes/%s.css" % name).replace(  # noqa: E731
        "</head>", extra + "</head>")
    return {"neutral.html": theme("neutral"), "bold.html": theme("bold"),
            "gallery.html": theme("neutral", sig.block(sig.get("gallery"), "dom")),
            "nocturne.html": theme("bold", sig.block(sig.get("nocturne"), "dom")),
            "film-paper.html": LONG_FILM % "paper", "film-dark.html": LONG_FILM % "dark"}


@needs_listen
class LongChoiceTest(unittest.TestCase):
    """A choice that is one long word ("showtime.json" in a third of the frame) or a long path wraps or
    shrinks inside its own box, in the DOM component and on canvas, wide and upright: nothing spills
    into the next choice, off the frame or out of the phone's safe zone (it once ran into choice C).
    The revealed answer's key letter clears 4.5:1 on light and dark themes, signatures and looks (a light
    theme's paper on its mid green once read 3.17:1), and upright the key letters, the label and the reply
    meet the phone minimum (they were 34-39 px of the 42 px needed at 1080x1920)."""

    def test_long_choices_fit_their_boxes(self):
        proj = make_project(TMP / "long", questions=LONG_Q, page=LONG_PAGE, mix=False)
        pages = long_pages()
        for name, html in pages.items():
            (proj / name).write_text(html, encoding="utf-8")
        codes = {"text_off_canvas", "text_clipped", "text_overlap", "safe_zone", "overflow", "low_contrast", "tiny_text"}
        for page in pages:
            for size in ("1920x1080", "1080x1920"):
                with self.subTest(page=page, size=size):
                    cp = showtime("check", proj, "--page", page, "--size", size, "--json", "--no-timeline", "--no-determinism",
                                  "-n", "1", "--at", "2.5,4,6", "--no-history", check=False)
                    rep = json.loads(cp.stdout)
                    bad = [f for f in rep["findings"] if f["code"] in codes
                           or (f["code"] == "small_text" and "skills/" in f.get("message", ""))]
                    self.assertEqual(bad, [], cp.stderr[-1500:])
                    texts = " ".join(str(t.get("text", "")) for t in rep.get("texts", []))
                    self.assertIn("showtime.json", texts)


# Browser driver: each case opens an export with the network blocked and plays a scenario.
DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const SKILL = process.argv[2];
const job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const { launchBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'chrome.mjs')).href);
const { browser } = await launchBrowser({ gpu: 'auto', headless: true, args: ['--proxy-server=http://127.0.0.1:9'] });
const out = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (const c of job.cases) {
    const ctx = await browser.newContext({ viewport: { width: c.width, height: c.height }, deviceScaleFactor: 1, isMobile: !!c.mobile, hasTouch: !!c.mobile });
    const page = await ctx.newPage();
    const r = { name: c.name, requests: [], errors: [], steps: {} };
    page.on('request', (q) => { const u = q.url(); if (!/^(data|blob|about|file):/.test(u)) r.requests.push(u); });
    page.on('pageerror', (e) => r.errors.push(String(e.message || e).slice(0, 300)));
    await page.goto(pathToFileURL(c.file).href, { waitUntil: 'load', timeout: 60000 });
    const P = (fn, arg) => page.evaluate(fn, arg);
    const waitFor = async (fn, arg, ms = 25000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await P(fn, arg)) return true; await sleep(40); } return false; };
    const state = () => P(() => {
      const p = window.showtimePlayer, card = document.querySelector('.stp-q'), box = (el) => { const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; };
      return { t: p.currentTime, paused: p.paused, question: p.question, questions: p.questions.map((q) => ({ id: q.id, choice: q.choice, passed: q.passed })),
        card: card && !card.hidden ? { text: card.innerText, box: box(card), inInfo: !!card.closest('.stp-info'), reply: (card.querySelector('.stp-q-reply') || {}).className || '' } : null,
        holder: box(document.querySelector('.stp-holder')), marks: document.querySelectorAll('.stp-qmarks i').length,
        stacked: document.getElementById('stp').classList.contains('is-stacked') };
    });
    // what the video itself draws at this frame (the question-beat component in the stage frame)
    const beat = async () => {
      const f = page.frames().find((x) => x !== page.mainFrame());
      return f ? f.evaluate(() => ({ num: [...document.querySelectorAll('.st-qb-num')].map((e) => e.textContent),
        right: [...document.querySelectorAll('.st-question-beat')].map((b) => b.querySelectorAll('.st-qb-choice[data-state="right"]').length) })) : null;
    };
    const events = [];
    try {
      await P(() => window.showtimePlayer.ready);
      await page.exposeFunction('__qlog', (e) => events.push(e));
      await P(() => ['question', 'answer', 'continue'].forEach((n) => window.showtimePlayer.on(n, (d) => window.__qlog(Object.assign({ ev: n }, d)))));
      r.manifestQuestions = await P(() => (JSON.parse(document.getElementById('st-manifest').textContent).questions || []).length);
      const start = async () => { await page.click('.stp-go'); };
      const asked = (id) => waitFor((x) => window.showtimePlayer.question === x, id);
      if (c.kind === 'answer') {
        await start();
        r.steps.asked1 = await asked('q1');
        r.steps.at1 = await state();
        r.steps.beat1 = await beat();
        if (c.shot) await page.screenshot({ path: c.shot });
        await page.keyboard.press('3');
        await waitFor(() => !!document.querySelector('.stp-q-reply'));
        r.steps.answered1 = await state();
        if (c.shot) await page.screenshot({ path: c.shot.replace(/\.png$/, '-answered.png') });
        await page.keyboard.press('Enter');
        await waitFor(() => !window.showtimePlayer.paused && window.showtimePlayer.question === null);
        r.steps.resumed1 = await state();
        r.steps.asked2 = await asked('q2');
        r.steps.at2 = await state();
        await page.keyboard.press('b');
        await waitFor(() => !!document.querySelector('.stp-q-reply'));
        r.steps.answered2 = await state();
        await page.click('.stp-q-go');
        await waitFor(() => window.showtimePlayer.question === null && window.showtimePlayer.currentTime >= 8.5);
        r.steps.resumed2 = await state();
        await waitFor(() => window.showtimePlayer.currentTime >= 8.7 || window.showtimePlayer.ended);
        await sleep(200);
        r.steps.beat2 = await beat();
      } else if (c.kind === 'seek') {
        await start();
        await waitFor(() => !window.showtimePlayer.paused);
        await P(() => window.showtimePlayer.seek(5.0));            // past q1, inside its beat: passed
        r.steps.afterSeek = await state();
        r.steps.asked2 = await asked('q2');
        await P(() => window.showtimePlayer.seek(6.0));            // back before q2: asked again
        r.steps.rearmed = await state();
        await P(() => window.showtimePlayer.play());
        r.steps.asked2again = await asked('q2');
        await P(() => window.showtimePlayer.seek(1.0));            // back before q1: asked again
        await P(() => window.showtimePlayer.play());
        r.steps.asked1 = await asked('q1');
        await page.keyboard.press('k');                            // play while it waits: through the beat
        await waitFor(() => !window.showtimePlayer.paused);
        r.steps.played = await state();
        await waitFor(() => window.showtimePlayer.currentTime > 4.6, null, 8000);
        r.steps.inBeat = await state();
      } else if (c.kind === 'phone') {
        await page.tap('.stp-go');
        r.steps.asked1 = await asked('q1');
        r.steps.at1 = await state();
        if (c.shot) await page.screenshot({ path: c.shot });
        await page.tap('.stp-q-choice >> nth=0');
        await waitFor(() => !!document.querySelector('.stp-q-reply'));
        r.steps.answered1 = await state();
      } else if (c.kind === 'plain') {
        await start();
        await waitFor(() => window.showtimePlayer.currentTime > 4.5, null, 15000);
        r.steps.past = await state();
      }
    } catch (e) { r.fatal = String(e.message || e).slice(0, 500); }
    r.events = events;
    out.push(r);
    await ctx.close();
  }
} finally { await browser.close(); }
fs.writeFileSync(job.result, JSON.stringify(out, null, 2));
"""


def drive(cases):
    job = TMP / ("job-%d.json" % int(time.time() * 1000))
    res = TMP / (job.stem + ".out.json")
    job.write_text(json.dumps({"cases": cases, "result": str(res)}), encoding="utf-8")
    drv = TMP / "driver.mjs"
    drv.write_text(DRIVER, encoding="utf-8")
    cp = subprocess.run([NODE, str(drv), str(SKILL), str(job)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", errors="replace", timeout=300)
    assert cp.returncode == 0 and res.exists(), "driver failed:\n%s\n%s" % (cp.stdout[-2000:], cp.stderr[-3000:])
    return {r["name"]: r for r in json.loads(res.read_text(encoding="utf-8"))}


def manifest(html: Path) -> dict:
    m = re.search(r'<script type="application/json" id="st-manifest">(.*?)</script>', html.read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1))


@needs_listen
class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proj = make_project(TMP / "export")
        out = TMP / "out"
        ex = lambda name, *a: json.loads(showtime("export", "html", cls.proj, "-o", out / name, "--audio", "none", "--json", "-q", *a).stdout)  # noqa: E731
        cls.rep = ex("main/q.html")
        cls.plain = ex("plain/q.html", "--no-questions")
        cls.bare = ex("bare/q.html", "--controls", "none")
        cls.art = ex("art/q.html", "--target", "artifact", "--controls", "minimal")
        cls.shots = TMP / "shots"
        cls.shots.mkdir(exist_ok=True)
        cls.res = drive([
            {"name": "answer", "kind": "answer", "file": cls.rep["output"], "width": 1280, "height": 720, "shot": str(cls.shots / "desktop.png")},
            {"name": "seek", "kind": "seek", "file": cls.rep["output"], "width": 1280, "height": 720},
            {"name": "phone", "kind": "phone", "file": cls.rep["output"], "width": 390, "height": 844, "mobile": True, "shot": str(cls.shots / "phone.png")},
            {"name": "plain", "kind": "plain", "file": cls.plain["output"], "width": 960, "height": 540},
            {"name": "artifact", "kind": "phone", "file": cls.art["output"], "width": 900, "height": 600, "mobile": True},
        ])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def ok(self, name):
        r = self.res[name]
        self.assertNotIn("fatal", r, r.get("fatal"))
        self.assertEqual(r["errors"], [], r["errors"])
        self.assertEqual(r["requests"], [], r["requests"])
        return r

    def test_export_carries_questions(self):
        self.assertEqual([(q["id"], q["t"], q["resume"]) for q in self.rep["questions"]], [("q1", Q1_T, Q1_RESUME), ("q2", Q2_T, Q2_RESUME)])
        m = manifest(Path(self.rep["output"]))
        self.assertEqual([q["id"] for q in m["questions"]], ["q1", "q2"])
        self.assertEqual(m["questions"][0]["reply"][2], "Yes: 4 is the biggest.")
        self.assertEqual([q["t"] for q in m["config"]["questions"]], [Q1_T, Q2_T])   # ST.questions in the page
        soc = json.loads(Path(self.rep["socratic"]).read_text(encoding="utf-8"))
        self.assertEqual(Path(self.rep["socratic"]).name, "socratic.json")
        self.assertEqual(soc["title"], "Questions fixture")
        self.assertEqual(soc["questions"][0], {"id": "q1", "pause": Q1_T, "resume": Q1_RESUME, "prompt": "Which is bigger?",
                                              "choices": ["2", "3", "4"], "answer": 2, "feedback": ["Too small.", "", "Yes: 4 is the biggest."]})
        # --no-questions: a plain player, the page still draws its beats; --controls none: the embedding page asks
        mp = manifest(Path(self.plain["output"]))
        self.assertNotIn("questions", mp)
        self.assertEqual(len(mp["config"]["questions"]), 2)
        self.assertIsNone(self.plain["socratic"])
        self.assertNotIn("questions", manifest(Path(self.bare["output"])))
        self.assertTrue(Path(self.bare["socratic"]).is_file())
        # a broken question stops the export, and says how to get a plain player
        bad = make_project(TMP / "bad", questions=[dict(QUESTIONS[0], answer=9)])
        cp = showtime("export", "html", bad, "-o", TMP / "out" / "bad.html", "--audio", "none", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn('"answer" must be the index', cp.stderr)
        self.assertIn("--no-questions", cp.stderr)

    def test_pause_answer_continue(self):
        r = self.ok("answer")
        s = r["steps"]
        self.assertTrue(s["asked1"])
        at = s["at1"]
        self.assertTrue(at["paused"])
        self.assertAlmostEqual(at["t"], Q1_T, places=3)                 # the question's own frame
        self.assertIn("Which is bigger?", at["card"]["text"])
        self.assertIn("question 1 of 2", at["card"]["text"].lower())
        self.assertEqual(s["beat1"]["num"][0], "3")                     # the video's countdown starts at 3
        self.assertEqual(s["beat1"]["right"], [0, 0])                   # and has not revealed anything yet
        self.assertEqual(at["marks"], 2)
        # the card floats over the bottom of the picture: the top of the frame stays in view
        self.assertGreater(at["card"]["box"][1], at["holder"][1] + 0.25 * at["holder"][3])
        self.assertIn("is-right", s["answered1"]["card"]["reply"])
        self.assertIn("Yes: 4 is the biggest.", s["answered1"]["card"]["text"])
        self.assertIn("1 of 1 right", s["answered1"]["card"]["text"])
        self.assertFalse(s["resumed1"]["paused"])
        self.assertGreaterEqual(s["resumed1"]["t"], Q1_RESUME - 1e-6)    # on from the end of the beat
        self.assertTrue(s["asked2"])
        self.assertAlmostEqual(s["at2"]["t"], Q2_T, places=3)
        self.assertIn("is-wrong", s["answered2"]["card"]["reply"])
        self.assertIn("Done.", s["answered2"]["card"]["text"])
        self.assertGreaterEqual(s["resumed2"]["t"], Q2_RESUME - 1e-6)
        self.assertEqual(s["beat2"]["right"][1], 1)                      # q2's beat reveals the answer after it
        ev = [(e["ev"], e.get("id"), e.get("choice"), e.get("right")) for e in r["events"]]
        self.assertEqual(ev, [("question", "q1", None, None), ("answer", "q1", 2, True), ("continue", "q1", None, None),
                              ("question", "q2", None, None), ("answer", "q2", 1, False), ("continue", "q2", None, None)])

    def test_seek_passes_and_rearms(self):
        r = self.ok("seek")
        s = r["steps"]
        self.assertEqual(s["afterSeek"]["questions"][0]["passed"], True)
        self.assertTrue(s["asked2"])
        asked = [e["id"] for e in r["events"] if e["ev"] == "question"]
        self.assertEqual(asked[0], "q2")                                  # q1 was skipped by the seek past it
        self.assertIsNone(s["rearmed"]["card"])
        self.assertEqual(s["rearmed"]["questions"][1]["passed"], False)
        self.assertTrue(s["asked2again"])
        self.assertTrue(s["asked1"])
        self.assertEqual(asked, ["q2", "q2", "q1"])
        self.assertFalse(s["played"]["paused"])                           # space: plays through the video's own beat
        self.assertIsNone(s["played"]["question"])
        self.assertLess(s["inBeat"]["t"], Q1_RESUME)
        self.assertGreater(s["inBeat"]["t"], Q1_T)

    def test_phone_keeps_the_frame_in_view(self):
        r = self.ok("phone")
        s = r["steps"]
        self.assertTrue(s["asked1"])
        at = s["at1"]
        self.assertTrue(at["stacked"])
        self.assertTrue(at["card"]["inInfo"])
        hx, hy, hw, hh = at["holder"]
        self.assertGreaterEqual(at["card"]["box"][1], hy + hh - 1)       # under the picture, not over it
        self.assertGreaterEqual(hy, 0)
        self.assertIn("is-wrong", s["answered1"]["card"]["reply"])
        self.assertIn("Too small.", s["answered1"]["card"]["text"])

    def test_plain_player_does_not_stop(self):
        r = self.ok("plain")
        self.assertEqual(r["manifestQuestions"], 0)
        self.assertGreater(r["steps"]["past"]["t"], 4.5)
        self.assertFalse(r["steps"]["past"]["paused"])
        self.assertEqual(r["events"], [])

    def test_artifact_minimal_asks(self):
        r = self.ok("artifact")
        self.assertTrue(r["steps"]["asked1"])
        self.assertIn("Too small.", r["steps"]["answered1"]["card"]["text"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])
