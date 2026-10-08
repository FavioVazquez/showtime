#!/usr/bin/env python3
"""Notes that know what they point at, and notes on a stretch of time (`showtime review notes`,
scripts/lib/review/where.mjs, scripts/lib/audit.mjs elementSnapshot, runtime/review/).

  * a spot resolves to the scene and the element under it at the note's time, read from the project the
    video was rendered from (its render.json), in a headless page; the same spot at another time is another
    scene and other elements; a box over two elements names both and not the cards around them; snapshots
    are cached per frame and a project edited after the render is said to be newer;
  * a video without a project (footage) says "footage frame" and gives the time only;
  * a note on a stretch (from t to `to`): saved through the page's server and the CLI, listed with the scenes
    it covers and the frames at both ends, checked (an end before its start, past the video), turned back
    into a frame note; open stretch notes are listed at delivery like other notes;
  * in a real browser: Shift + drag on the bar and [ ... ] write a stretch note, shown on the bar as a band;
    Play stretch stops at its end; a phone layout without sideways scrolling where Mark stretch works by tap.

Stdlib only. usage: python tests/test_review_notes_where.py [--fast] [-v]   (--fast: no page test)
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

from _listen import needs_listen

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-review-where-"))
ENV["SHOWTIME_OUT"] = str(TMP)
NODE = ENV.get("SHOWTIME_NODE") or shutil.which("node", path=ENV.get("PATH")) or "node"
FPS = 30
W, H = 640, 360

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<script type="module" src="/_st/components/index.js"></script>
<style>
body{margin:0;background:#101418;color:#fff;font:28px sans-serif;overflow:hidden}
section{position:absolute;inset:0;background:#101418}
#title{position:absolute;left:40px;top:40px;margin:0;font-size:40px;line-height:50px}
.logo{position:absolute;right:40px;top:40px;width:80px;height:80px;background:#e33;border-radius:12px}
.card{position:absolute;top:140px;width:220px;height:140px;background:#223;border-radius:12px;padding:16px;box-sizing:border-box}
.card.a{left:40px}.card.b{left:380px}
.big{font-size:44px;line-height:50px;font-weight:700}.lbl{font-size:18px;line-height:24px}
</style></head><body>
<section id="intro" data-start="0" data-dur="2"><h1 id="title">Hello <em>world</em></h1><div class="logo"></div>
  <div style="position:absolute;left:40px;top:150px;width:200px;height:180px"><div data-st="count-up" data-value="5" data-label="steps"></div></div></section>
<section id="stats" data-start="2" data-dur="2">
  <div class="card a"><div class="big">40%</div><div class="lbl">faster renders</div></div>
  <div class="card b"><div class="big">12 days</div><div class="lbl">to ship</div></div>
</section>
</body></html>
"""


def showtime(*args, check=True, timeout=240):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout, cwd=str(TMP))
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def sj(*args, **kw):
    return json.loads(showtime(*args, **kw).stdout)


def ffmpeg(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def make_job(name, project=False, seconds=4):
    """A job with a 4 s final.mp4; with project=True, a two-scene project and the render report naming it."""
    d = TMP / "showtime-out" / ("%s-20261007-100000" % name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({"schema": 1, "slug": name, "mode": "quick", "dir": str(d), "outputs": {}}),
                                encoding="utf-8")
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=%dx%d:r=%d:d=%d" % (W, H, FPS, seconds), "-c:v", "libx264",
           "-pix_fmt", "yuv420p", "-g", "15", d / "final.mp4")
    if project:
        proj = d / "proj"
        proj.mkdir(exist_ok=True)
        (proj / "showtime.json").write_text(json.dumps({"title": "Where", "width": W, "height": H, "fps": FPS,
                                                        "duration": seconds}), encoding="utf-8")
        (proj / "index.html").write_text(PAGE, encoding="utf-8")
        # the report `showtime render` leaves beside the video (the fields where.mjs reads)
        (d / "render.json").write_text(json.dumps({"ok": True, "output": str(d / "final.mp4"), "project": str(proj),
                                                   "page": "index.html", "width": W, "height": H, "fps": FPS,
                                                   "duration": seconds, "kind": "full"}), encoding="utf-8")
        old = time.time() - 60          # the project is older than its render
        for f in (proj / "showtime.json", proj / "index.html"):
            os.utime(f, (old, old))
    return d


def notes_by_id(out):
    return {n["id"]: n for n in out["notes"]}


class WhereTest(unittest.TestCase):
    """Spots and boxes resolved against the project (one headless page per listing, then the cache)."""

    @classmethod
    def setUpClass(cls):
        cls.job = make_job("where", project=True)

    def test_spot_box_scene_and_cache(self):
        j = "where"
        title = (40 + 60) / W, (40 + 25) / H                       # on "Hello world"
        big_a = (40 + 16 + 30) / W, (140 + 16 + 25) / H            # on "40%"
        n1 = sj("review", "notes", j, "--add", "title too small", "--at", "0.517", "--region", "%.4f,%.4f" % title, "--json")["note"]
        n2 = sj("review", "notes", j, "--add", "same spot later", "--at", "3.0", "--region", "%.4f,%.4f" % title, "--json")["note"]
        n3 = sj("review", "notes", j, "--add", "make this pop", "--at", "3.0", "--region", "%.4f,%.4f" % big_a, "--json")["note"]
        # a box over the two big numbers (not their labels, not the whole cards)
        n4 = sj("review", "notes", j, "--add", "align these", "--at", "2.5", "--region", "0.03,%.4f,0.94,%.4f" % (150 / H, 58 / H),
                "--json")["note"]
        n5 = sj("review", "notes", j, "--add", "whole frame", "--at", "1", "--json")["note"]
        # a spot on a component: its part under the spot, then the component (data-st), by its source selector
        n6 = sj("review", "notes", j, "--add", "count slower", "--at", "1.5", "--region", "%.4f,%.4f" % (140 / W, 200 / H), "--json")["note"]
        out = sj("review", "notes", j, "--json", "--no-frames")
        by = notes_by_id(out)
        w1 = by[n1["id"]]["on_screen"]
        self.assertEqual(w1["kind"], "project", w1)
        self.assertEqual(w1["frame"], 15)                          # floor(0.517 * 30): the frame the video shows
        self.assertEqual([s["name"] for s in w1["scenes"]], ["#intro"])
        self.assertEqual(w1["elements"][0]["selector"], "#title")
        self.assertEqual(w1["elements"][0]["text"], "Hello world")  # the <em> counts for its heading
        self.assertEqual(w1["elements"][0]["kind"], "text")
        self.assertEqual(w1["elements"][0]["scene"], "#intro")
        # the same spot at 3 s: the second scene, and the title is gone (its scene is off)
        w2 = by[n2["id"]]["on_screen"]
        self.assertEqual([s["name"] for s in w2["scenes"]], ["#stats"])
        self.assertNotIn("#title", [e["selector"] for e in w2["elements"]])
        # a spot on "40%": the number first (most specific), then its card
        w3 = by[n3["id"]]["on_screen"]
        self.assertEqual(w3["elements"][0]["text"], "40%")
        self.assertIn("div.big", w3["elements"][0]["selector"])
        self.assertIn("div.card.a", w3["elements"][1]["selector"])
        self.assertEqual(w3["elements"][1]["kind"], "shape")
        # the box over two elements: both numbers, left to right, nothing else
        w4 = by[n4["id"]]["on_screen"]
        self.assertEqual([e["text"] for e in w4["elements"]], ["40%", "12 days"], w4)
        self.assertEqual([s["name"] for s in w4["scenes"]], ["#stats"])
        b = w4["elements"][0]["box"]
        self.assertTrue(50 <= b["x"] <= 60 and 150 <= b["y"] <= 160, b)
        # a whole-frame note: the scene, no elements
        w5 = by[n5["id"]]["on_screen"]
        self.assertEqual(([s["name"] for s in w5["scenes"]], w5["elements"]), (["#intro"], []))
        self.assertIsNone(w1["stale"])
        w6 = by[n6["id"]]["on_screen"]
        comp = [e for e in w6["elements"] if e["kind"] == "component"]
        self.assertEqual([(e["component"], e["selector"]) for e in comp], [("count-up", '#intro > div > div[data-st="count-up"]')], w6)
        self.assertIn("steps", comp[0]["text"])
        self.assertTrue(all(e["component"] == "count-up" for e in w6["elements"]), w6)
        # text: the scene and what is under the spot or box
        text = showtime("review", "notes", j, "--no-frames").stdout
        self.assertIn("scene: #intro (0:00.00-0:02.00)", text)
        self.assertIn('under it: #title  "Hello world"  text', text)
        self.assertIn('"12 days"', text)
        # cached per frame: one snapshot per distinct frame (15, 90, 75, 30, 45)
        cache = self.job / "review" / "notes" / ".state" / "where"
        self.assertEqual(len(list(cache.glob("*.json"))), 5)
        # the project edited after the render: new snapshots, and the listing says the project is newer
        page = self.job / "proj" / "index.html"
        page.write_text(PAGE.replace("Hello <em>world</em>", "Hello <em>there</em>"), encoding="utf-8")
        out = sj("review", "notes", j, "--json", "--no-frames")
        w1 = notes_by_id(out)[n1["id"]]["on_screen"]
        self.assertEqual(w1["elements"][0]["text"], "Hello there")
        self.assertEqual(w1["stale"], "index.html")
        self.assertEqual(len(list(cache.glob("*.json"))), 10)
        self.assertIn("the project changed after this render", showtime("review", "notes", j, "--no-frames").stdout)
        # --no-elements: no page at all
        out = sj("review", "notes", j, "--json", "--no-frames", "--no-elements")
        self.assertIsNone(notes_by_id(out)[n1["id"]]["on_screen"])


class FootageTest(unittest.TestCase):
    def test_footage_frame(self):
        make_job("foot")
        n = sj("review", "notes", "foot", "--add", "cut the um", "--at", "1", "--region", "0.5,0.5", "--json")["note"]
        out = sj("review", "notes", "foot", "--json", "--no-frames")
        self.assertEqual(notes_by_id(out)[n["id"]]["on_screen"], {"kind": "footage", "t": 1})
        text = showtime("review", "notes", "foot", "--no-frames").stdout
        self.assertIn("on screen: footage frame (no project), at 0:01.00", text)

    def test_project_moved_after_the_render(self):
        d = make_job("moved", project=True)
        os.rename(str(d / "proj"), str(d / "proj-old"))
        n = sj("review", "notes", "moved", "--add", "the logo", "--at", "1", "--json")["note"]
        out = sj("review", "notes", "moved", "--json", "--no-frames")
        self.assertEqual(notes_by_id(out)[n["id"]]["on_screen"], {"kind": "footage", "t": 1, "missing": str(d / "proj")})
        text = showtime("review", "notes", "moved", "--no-frames").stdout
        self.assertIn("on screen: project not found at %s (moved or deleted since this render), at 0:01.00" % (d / "proj"), text)


def request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": "127.0.0.1:%d" % port}
    h.update(headers or {})
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


@needs_listen
class RangeTest(unittest.TestCase):
    """A note on a stretch: save (page server, CLI), list (scenes covered, both ends' frames), gate."""

    @classmethod
    def setUpClass(cls):
        cls.job = make_job("range", project=True)
        cls.info = sj("review", "open", "range", "--json")
        cls.key = urllib.parse.parse_qs(urllib.parse.urlparse(cls.info["url"]).query)["k"][0]

    @classmethod
    def tearDownClass(cls):
        showtime("review", "stop", "range", check=False)

    def post(self, body):
        st, data = request(self.info["port"], "POST", "/api/note", {"X-Review-Key": self.key, "Content-Type": "application/json"},
                           json.dumps(body))
        return st, json.loads(data or b"{}")

    def test_round_trip(self):
        # saved by the page (the person), checked on the way in
        st, r = self.post({"op": "add", "t": 1.517, "to": 3.25, "text": "too slow from here to the numbers"})
        self.assertEqual(st, 200, r)
        nid = r["note"]["id"]
        self.assertEqual((r["note"]["t"], r["note"]["to"], r["note"]["region"]), (1.517, 3.25, None))
        st, r2 = self.post({"op": "add", "t": 2, "to": 1.5, "text": "backwards"})
        self.assertEqual(st, 400)
        self.assertIn("ends after it starts", r2["error"])
        st, r2 = self.post({"op": "add", "t": 2, "to": 9, "text": "past the end"})
        self.assertEqual(st, 400)
        stored = json.loads((self.job / "review" / "notes" / "notes.json").read_text(encoding="utf-8"))["notes"]
        self.assertEqual([(n["t"], n.get("to")) for n in stored], [(1.517, 3.25)])
        # listed: the span, the scenes it covers with the part of each, the frames at both ends
        new = sj("review", "notes", "range", "--new", "--json")
        n = notes_by_id(new)[nid]
        self.assertEqual((n["from"], n["to"], n["length"]), (1.517, 3.25, 1.733))
        self.assertEqual(n["span"], "from 0:01.52 to 0:03.25 (1.7 s)")
        sc = n["on_screen"]["scenes"]
        self.assertEqual([(s["name"], s["covered"]) for s in sc], [("#intro", [1.517, 2]), ("#stats", [2, 3.25])])
        self.assertTrue(Path(n["frame"]).is_file() and Path(n["frame_end"]).is_file())
        self.assertNotEqual(Path(n["frame"]).read_bytes(), Path(n["frame_end"]).read_bytes())
        text = showtime("review", "notes", "range").stdout
        self.assertIn("from 0:01.52 to 0:03.25 (1.7 s)  the whole stretch", text)
        self.assertIn("scenes: #intro (0:00.00-0:02.00; the note covers 0:01.52-0:02.00), #stats (0:02.00-0:04.00; the note covers 0:02.00-0:03.25)", text)
        self.assertIn("last frame: ", text)
        # the gate: an open stretch note is listed at delivery like any other
        cp = showtime("job", "note", str(self.job), "--stage", "deliver")
        self.assertEqual(cp.returncode, 0)
        self.assertIn("still open", cp.stderr)
        self.assertIn("%s from 0:01.52 to 0:03.25: \"too slow from here to the numbers\"" % nid, " ".join(cp.stderr.split()))
        # the agent's own stretch note and its checks; --to none makes it a frame note again
        cp = showtime("review", "notes", "range", "--add", "is the pause long enough?", "--at", "0:02.5", "--to", "0:03.9")
        self.assertIn("added from 0:02.50 to 0:03.90 (1.4 s)", cp.stdout)
        a = sj("review", "notes", "range", "--json", "--no-frames", "--no-elements")["notes"][-1]
        self.assertEqual((a["t"], a["to"], a["author"]), (2.5, 3.9, "agent"))
        cp = showtime("review", "notes", "range", "--edit", a["id"], "--at", "3.85", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("ends after it starts", cp.stderr)
        cp = showtime("review", "notes", "range", "--reply", nid, "tightened", "--to", "3", check=False)
        self.assertNotEqual(cp.returncode, 0)
        e = sj("review", "notes", "range", "--edit", a["id"], "--to", "none", "--json")["note"]
        self.assertNotIn("to", e)
        # answered: no longer listed at delivery
        showtime("review", "notes", "range", "--reply", nid, "cut 0.8 s from the intro hold", "--done")
        cp = showtime("job", "note", str(self.job), "--stage", "deliver")
        self.assertNotIn("still open", cp.stderr)


# ------------------------------------------------------------------ the page in a browser
DRIVER = r"""
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const [chromeLib, jobFile] = process.argv.slice(2);
const job = JSON.parse(fs.readFileSync(jobFile, 'utf8'));
const { launchBrowser } = await import(pathToFileURL(chromeLib).href);
const R = { ok: {}, errors: [], info: {} };
const ok = (name, v) => { R.ok[name] = !!v; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const notes = () => { try { return JSON.parse(fs.readFileSync(job.notesFile, 'utf8')).notes; } catch { return []; } };
async function until(fn, ms = 8000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { const v = await fn(); if (v) return v; } catch {} await sleep(60); } return null; }
const { browser } = await launchBrowser({ args: ['--autoplay-policy=no-user-gesture-required'] });
try {
  for (const scheme of ['light', 'dark']) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 }, colorScheme: scheme });
    const p = await ctx.newPage();
    p.on('pageerror', (e) => R.errors.push(scheme + ': ' + e.message));
    await p.goto(job.url);
    ok(scheme + ': video ready', await until(() => p.evaluate(() => window.reviewPage && document.querySelector('video').readyState >= 2)));
    if (scheme === 'light') {
      // Shift + drag on the bar from 25 % to 75 %: a stretch note
      const r = await p.evaluate(() => { const b = document.querySelector('#scrub').getBoundingClientRect(); return { x: b.left, y: b.top + b.height / 2, w: b.width }; });
      await p.keyboard.down('Shift');
      await p.mouse.move(r.x + 0.25 * r.w, r.y);
      await p.mouse.down();
      await p.mouse.move(r.x + 0.5 * r.w, r.y, { steps: 4 });
      ok('drag draws a dashed band', await p.evaluate(() => { const d = document.querySelector('#ticks .band.draft'); return d && !d.hidden && d.getBoundingClientRect().width > 50; }));
      await p.mouse.move(r.x + 0.75 * r.w, r.y, { steps: 4 });
      await p.mouse.up();
      await p.keyboard.up('Shift');
      ok('composer opens on a stretch', await until(() => p.evaluate(() => !document.querySelector('#composer').hidden && /a stretch of 2\.0 s/.test(document.querySelector('#cWhere').textContent) && /from 0:01\.0 to 0:03\.0/.test(document.querySelector('#cTitle').textContent))));
      await p.keyboard.type('Too slow here');
      await p.keyboard.press('Enter');
      ok('stretch saved', await until(() => notes().some((n) => n.text === 'Too slow here' && Math.abs(n.t - (30.5 / 30)) < 0.02 && Math.abs(n.to - (90.5 / 30)) < 0.02 && n.region === null)));
      R.info.drag = notes().find((n) => n.text === 'Too slow here');
      ok('band on the bar', await until(() => p.evaluate(() => document.querySelectorAll('#ticks .band:not(.draft)').length === 1)));
      ok('listed as a stretch', await p.evaluate(() => /0:01\.0–0:03\.0/.test(document.querySelector('#list .note').textContent) && /a stretch of 2\.0 s/.test(document.querySelector('#list .note').textContent)));
      // the keyboard: [ at 0.5 s, ] at 1.5 s
      await p.click('#title');
      await p.evaluate(() => window.reviewPage.seek(0.5));
      await sleep(150);
      await p.keyboard.press('[');
      ok('[ marks the start', await until(() => p.evaluate(() => window.reviewPage.marking !== null && document.querySelector('#rangeBtn').textContent === 'End stretch')));
      await p.evaluate(() => { document.activeElement.blur(); window.reviewPage.seek(1.5); });
      await sleep(150);
      await p.keyboard.press(']');
      ok('] opens the composer', await until(() => p.evaluate(() => !document.querySelector('#composer').hidden && /a stretch/.test(document.querySelector('#cWhere').textContent))));
      await p.keyboard.type('Cut this pause');
      await p.keyboard.press('Enter');
      ok('keyboard stretch saved', await until(() => notes().some((n) => n.text === 'Cut this pause' && Math.abs(n.t - (15.5 / 30)) < 0.02 && Math.abs(n.to - (45.5 / 30)) < 0.02)));
      // Esc drops a marked start
      await p.click('#title');
      await p.keyboard.press('[');
      await p.keyboard.press('Escape');
      ok('Esc drops the mark', await until(() => p.evaluate(() => window.reviewPage.marking === null && document.querySelector('#rangeBtn').textContent === 'Mark stretch')));
      // marking while it plays: it plays on, ] pauses and opens the composer; Esc leaves it unsaved
      await p.evaluate(() => window.reviewPage.seek(0.2));
      await p.click('#title');
      await p.keyboard.press(' ');
      await until(() => p.evaluate(() => !window.reviewPage.paused));
      await p.keyboard.press('[');
      ok('[ while playing plays on', await p.evaluate(() => !window.reviewPage.paused && window.reviewPage.marking !== null));
      await sleep(700);
      await p.keyboard.press(']');
      ok('] pauses on the stretch', await until(() => p.evaluate(() => window.reviewPage.paused && !document.querySelector('#composer').hidden && /a stretch/.test(document.querySelector('#cWhere').textContent))));
      await p.keyboard.press('Escape');
      ok('Esc closes it unsaved', await until(() => p.evaluate(() => document.querySelector('#composer').hidden)) && notes().length === 2);
      // Play stretch: plays from its start and stops at its end
      const id = notes().find((n) => n.text === 'Cut this pause').id;
      await p.click(`#list [data-id="${id}"] [data-act="play-range"]`);
      ok('play stretch plays', await until(() => p.evaluate(() => !window.reviewPage.paused)));
      ok('play stretch stops at the end', await until(() => p.evaluate(() => window.reviewPage.paused && window.reviewPage.time > 1.3 && window.reviewPage.time < 1.75), 10000));
      R.info.stopAt = await p.evaluate(() => window.reviewPage.time);
      ok('accessible names', await p.evaluate(() => [...document.querySelectorAll('button')].every((x) => (x.getAttribute('aria-label') || x.textContent).trim().length > 0)));
      ok('keys listed', await p.evaluate(() => /Shift \+ drag/.test(document.querySelector('#keysDlg').textContent) && /\[ \/ \]/.test(document.querySelector('#keysDlg').textContent)));
    } else {
      ok('dark: bands drawn', await until(() => p.evaluate(() => document.querySelectorAll('#ticks .band:not(.draft)').length === 2)));
      ok('dark: theme on', await p.evaluate(() => getComputedStyle(document.body).backgroundColor !== 'rgb(245, 243, 238)'));
    }
    if (job.shots) await p.screenshot({ path: job.shots + '/range-' + scheme + '.png' });
    await ctx.close();
  }
  // a phone held upright: no sideways scroll; Mark stretch by tap, then End stretch
  const ph = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const q = await ph.newPage();
  q.on('pageerror', (e) => R.errors.push('phone: ' + e.message));
  await q.goto(job.url);
  ok('phone ready', await until(() => q.evaluate(() => window.reviewPage && document.querySelector('video').readyState >= 1)));
  ok('phone: no sideways scroll', await q.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
  ok('phone: bands drawn', await until(() => q.evaluate(() => document.querySelectorAll('#ticks .band:not(.draft)').length === 2)));
  await q.evaluate(() => window.reviewPage.seek(2.2));
  await sleep(200);
  await q.tap('#rangeBtn');
  ok('phone: start marked', await until(() => q.evaluate(() => window.reviewPage.marking !== null)));
  await q.evaluate(() => window.reviewPage.seek(3.4));
  await sleep(200);
  await q.tap('#rangeBtn');
  ok('phone: composer on the stretch', await until(() => q.evaluate(() => !document.querySelector('#composer').hidden && /a stretch of 1\.2 s/.test(document.querySelector('#cWhere').textContent))));
  await q.fill('#cText', 'Numbers land too late');
  await q.tap('#cSave');
  ok('phone: saved', await until(() => notes().some((n) => n.text === 'Numbers land too late' && n.to > n.t)));
  ok('phone: still no sideways scroll', await q.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
  if (job.shots) await q.screenshot({ path: job.shots + '/range-phone.png', fullPage: true });
} catch (e) { R.errors.push('driver: ' + (e.stack || e)); }
finally { await browser.close(); fs.writeFileSync(job.out, JSON.stringify(R, null, 2)); }
"""


@needs_listen
@unittest.skipIf(FAST, "needs a browser")
class PageTest(unittest.TestCase):
    def test_stretch_in_the_page(self):
        job = make_job("rpage")
        info = sj("review", "open", "rpage", "--json")
        cases = {"url": info["url"], "notesFile": str(job / "review" / "notes" / "notes.json"), "out": str(TMP / "rdriver.json")}
        if os.environ.get("SHOWTIME_TEST_SHOTS"):
            cases["shots"] = os.environ["SHOWTIME_TEST_SHOTS"]
        drv, jf = TMP / "rdriver.mjs", TMP / "rdriver-job.json"
        drv.write_text(DRIVER, encoding="utf-8")
        jf.write_text(json.dumps(cases), encoding="utf-8")
        try:
            cp = subprocess.run([NODE, str(drv), str(SKILL / "scripts" / "lib" / "chrome.mjs"), str(jf)], env=ENV,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=300)
            out = Path(cases["out"])
            self.assertTrue(out.exists(), cp.stdout + cp.stderr)
            r = json.loads(out.read_text(encoding="utf-8"))
            failed = [k for k, v in r["ok"].items() if not v]
            self.assertEqual(failed, [], json.dumps(r, indent=1)[:4000])
            self.assertEqual(r["errors"], [])
            self.assertGreaterEqual(len(r["ok"]), 27)
            # what the agent then reads: a footage video, so the stretches give their times
            text = showtime("review", "notes", "rpage", "--no-frames").stdout
            self.assertIn("from 0:01.02 to 0:03.02 (2.0 s)", text)
            self.assertIn("on screen: footage frame (no project), from 0:01.02 to 0:03.02", text)
        finally:
            showtime("review", "stop", "rpage", check=False)


def tearDownModule():
    for j in ("range", "rpage"):
        showtime("review", "stop", j, check=False)
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
