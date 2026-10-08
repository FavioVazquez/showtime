#!/usr/bin/env python3
"""Talking-head cards (EDL "cards", st.footage.cards) and their helpers (about 1-2 minutes).

A synthetic clip (test pattern + tone, 10 s) with a hand-written transcript and an EDL that cuts 3.0-5.0 s:

- phrase anchoring: number words fold ("twenty two thousand" = 22,000), a repeated phrase takes the match after
  the previous card, a phrase across a cut, a phrase cut out of the edit and one never said fail with the reason,
  `word` ids; times are output times (the frame-exact mapping), so a re-cut moves the cards
- check: reading time, overlap, the caption band, a box outside the 9:16 safe box, emphasis count
- panel framing: the ranges split at the panel's frames (same frame total, contiguous, joins), and the
  speaker's half is a face-tracked crop that keeps the face centred in it (face detector stubbed)
- captions: emphasis colours the words, a 9:16 panel moves captions under the seam (\\an8\\pos)
- suggest: stat, name, list markers, quote and chapter candidates
- every card type renders with alpha (one reel, QuickTime Animation): transparent corner, opaque card
- an `edit render --preview` with cards and a panel: frames, the report's cards block, qa's card check

usage: python tests/test_cards.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-cards-"))

WORDS = [  # (text, start, end) in source seconds; 3.0-5.0 is cut out by the EDL
    ("Hello", 0.20, 0.50), ("I'm", 0.55, 0.80), ("Ada", 0.85, 1.20), ("Park,", 1.25, 1.60), ("and", 1.70, 1.90),
    ("today", 1.95, 2.40),
    ("space", 3.20, 3.60), ("weather", 3.65, 4.00), ("matters.", 4.05, 4.60),
    ("space", 5.10, 5.40), ("weather", 5.45, 5.80), ("is", 5.85, 6.00), ("twenty", 6.05, 6.40), ("two", 6.45, 6.70),
    ("thousand", 6.75, 7.20), ("miles", 7.25, 7.60), ("away.", 7.65, 7.95),
    ("First,", 8.05, 8.40), ("satellites.", 8.45, 8.95), ("Second,", 9.00, 9.30), ("space", 9.35, 9.60),
    ("weather.", 9.62, 9.90),
]


def st(*args, check=True, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                      cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def make_clip(path: Path, size: str = "640x360") -> None:
    from st import ff
    ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=%s:rate=30:duration=10" % size, "-f", "lavfi", "-i",
                   "sine=frequency=220:sample_rate=48000:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-shortest", str(path)])


def make_edl(folder: Path, cards, **extra) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    clip = TMP / "clip.mp4"
    tr = folder / "transcripts" / "clip.json"
    tr.parent.mkdir(exist_ok=True)
    tr.write_text(json.dumps({"source": str(clip), "duration": 10.0, "language": "en",
                              "words": [{"id": "w%d" % i, "text": t, "start": a, "end": b, "type": "word"}
                                        for i, (t, a, b) in enumerate(WORDS)]}), encoding="utf-8")
    doc = {"sources": {"a": str(clip)}, "transcripts": {"a": "transcripts/clip.json"},
           "ranges": [{"source": "a", "start": 0.0, "end": 3.0}, {"source": "a", "start": 5.0, "end": 10.0}],
           "output": {"fps": 30}, "cards": cards, "look": "graphite"}
    doc.update(extra)
    p = folder / "edl.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def resolved(edl_path: Path, faces: bool = False, **kw):
    from st.footage import cards as CD
    from st.footage import edl as E
    ed = E.load(edl_path)
    segs = E.plan(ed)
    trs = E.load_transcripts(ed, required=True)
    words = E.map_words(segs, trs, include_events=False)
    return ed, segs, CD.resolve(ed, segs, words, trs, faces=faces, **kw)


def setUpModule():
    make_clip(TMP / "clip.mp4")


class AnchorTest(unittest.TestCase):
    def test_number_words_and_matching(self):
        from st.footage import cards as CD
        toks = [t for t, _a, _b in CD._canon(CD._toks("twenty two thousand miles, 22,000 and 40% one hundred and five"))]
        self.assertEqual(toks, ["22000", "miles", "22000", "and", "40", "percent", "105"])
        ws = [{"text": t, "start": a, "end": b} for t, a, b in WORDS]
        m = CD.Matcher(ws)
        self.assertEqual(m.find("22,000 miles"), (12, 15))
        self.assertEqual(m.find_all("space weather"), [(6, 7), (9, 10), (20, 21)])
        self.assertIsNone(m.find("banana"))

    def test_resolve_through_a_cut(self):
        p = make_edl(TMP / "anchor", [
            {"type": "lower-third", "say": "I'm Ada Park", "name": "Ada Park", "role": "Engineer"},
            {"type": "title", "say": "today space weather", "title": "Space weather", "dur": 3},   # across the cut
            {"type": "stat", "say": "twenty two thousand miles", "label": "away"},                 # value from words
            {"type": "quote", "say": "space weather"},             # the match after the previous card's anchor
            {"type": "chapter", "word": "w17", "title": "First"},
        ])
        ed, segs, cards = resolved(p)
        by = {c["type"]: c for c in cards}
        fps = 30.0
        # source 0.55 (I'm) - lead 0.12 = 0.43 -> frame 12 (floor)
        self.assertAlmostEqual(by["lower-third"]["start"], 12 / fps, places=4)
        # "today" (1.95) then "space weather" after the cut: the anchor spans both segments
        self.assertEqual(by["title"]["said"], "today space weather")
        self.assertEqual({segs[0]["i"], segs[1]["i"]}, {0, 1})
        # the stat's number comes from the words; times are output times (5.0 -> 3.0)
        self.assertEqual(by["stat"]["value"], 22000)
        self.assertAlmostEqual(by["stat"]["anchor_start"], 6.05 - 2.0, places=3)
        # the quote's "space weather" is the second one said in the edit (source 9.35 -> output 7.35)
        self.assertAlmostEqual(by["quote"]["anchor_start"], 7.35, places=3)
        self.assertEqual(by["quote"]["text"], "\u2026space weather.")    # starts mid-sentence: an ellipsis
        self.assertAlmostEqual(by["chapter"]["anchor_start"], 8.05 - 2.0, places=3)
        for c in cards:
            self.assertAlmostEqual(c["start"] * fps, round(c["start"] * fps), places=3)   # frame-snapped

    def test_recut_moves_cards(self):
        cards = [{"type": "stat", "say": "twenty two thousand miles", "value": 22000}]
        _e, _s, a = resolved(make_edl(TMP / "recut1", cards))
        p = make_edl(TMP / "recut2", cards)
        d = json.loads(p.read_text())
        d["ranges"] = [{"source": "a", "start": 0.0, "end": 2.5}, {"source": "a", "start": 6.0, "end": 10.0}]
        p.write_text(json.dumps(d))
        _e, _s, b = resolved(p)
        self.assertAlmostEqual(a[0]["anchor_start"] - b[0]["anchor_start"], 1.5, places=3)   # 2.0 s cut -> 3.5 s cut

    def test_not_found_reasons(self):
        from st.common import ShowtimeError
        with self.assertRaises(ShowtimeError) as cm:
            resolved(make_edl(TMP / "nf", [{"type": "stat", "say": "twenty two thousand", "value": 22000},
                                            {"type": "quote", "say": "space weather matters"},
                                            {"type": "quote", "say": "banana bread"},
                                            {"type": "stat", "say": "Hello", "value": 1},
                                            {"type": "stat", "word": "w7", "value": 1}]))
        msg = str(cm.exception)
        self.assertIn("cut out of this edit (source a at 3.20 s", msg)
        self.assertIn("never says it", msg)
        self.assertIn("only before the previous card", msg)
        self.assertIn("word 'w7' is not in this edit", msg)

    def test_spec_validation(self):
        from st.common import ShowtimeError
        from st.footage import edl as E
        p = make_edl(TMP / "bad", [{"type": "sparkle", "say": "x"}, {"type": "lower-third", "say": "Ada"},
                                   {"type": "stat", "name": "x"}, {"type": "quote", "say": "x", "colour": 1}])
        with self.assertRaises(ShowtimeError) as cm:
            E.load(p)
        msg = str(cm.exception)
        for part in ("not a card type", "needs 'name'", "needs \"say\"", "unknown key(s) colour"):
            self.assertIn(part, msg)


class CheckTest(unittest.TestCase):
    def test_problems(self):
        from st.footage import cards as CD
        p = make_edl(TMP / "chk", [
            {"type": "title", "say": "Hello", "title": "A long title that nobody can read in one second", "dur": 1.0},
            {"type": "quote", "say": "space weather is", "box": {"x": 0.06, "y": 0.80, "w": 0.5, "h": 0.15}},
            {"type": "stat", "say": "twenty two thousand", "value": 22000, "box": {"x": 0.3, "y": 0.75, "w": 0.4, "h": 0.15}},
        ], captions={"style": "clean"})
        ed, _s, cards = resolved(p)
        probs = "\n".join(CD.problems(cards, ed))
        self.assertIn("cards[0] title", probs)
        self.assertIn("need", probs)                                   # reading time
        self.assertIn("sits on the caption band", probs)
        self.assertIn("are on screen together", probs)
        # the same box in 9:16 leaves the safe box (platform UI covers y > 0.75)
        tall = CD.problems(cards, ed, 1080, 1920)
        self.assertTrue(any("safe box" in x for x in tall), tall)
        self.assertTrue(CD.emphasis_problems(7, 3, 60))
        self.assertTrue(CD.emphasis_problems(3, 12, 30))
        self.assertFalse(CD.emphasis_problems(4, 6, 54))

    def test_edit_check_cli(self):
        p = make_edl(TMP / "cli", [{"type": "stat", "say": "twenty two thousand miles", "value": 22000,
                                    "suffix": " miles", "label": "away"}],
                     captions={"style": "clean", "emphasis": ["space weather", "nowhere"]})
        out = json.loads(st("edit", "check", p, "--json").stdout)
        self.assertEqual(out["cards"][0]["type"], "stat")
        self.assertEqual(out["emphasis"]["said"], 2)
        self.assertTrue(any("never said in this edit: nowhere" in x for x in out["problems"]))
        cp = st("edit", "check", p)
        self.assertIn("cards (output times", cp.stdout)
        bad = make_edl(TMP / "cli-bad", [{"type": "quote", "say": "matters"}])
        cp = st("edit", "check", bad, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("cut out of this edit", cp.stderr + cp.stdout)


class PanelTest(unittest.TestCase):
    def test_splits_keep_frames(self):
        from st.footage import cards as CD
        from st.footage import edl as E
        p = make_edl(TMP / "panel", [{"type": "panel", "say": "today", "title": "Two halves",
                                      "until": "twenty two thousand", "side": "left"}])
        ed, segs, cards = resolved(p)
        ranges = CD.panel_splits(ed["ranges"], segs, cards, ed["output"]["fps"])
        ed2 = dict(ed, ranges=ranges)
        segs2 = E.plan(ed2)
        self.assertEqual(sum(s["frames"] for s in segs2), sum(s["frames"] for s in segs))
        self.assertEqual(len(segs2), 4)
        lay = [bool(s.get("layout")) for s in segs2]
        self.assertEqual(lay, [False, True, True, False])
        self.assertAlmostEqual(segs2[1]["out_start"], cards[0]["start"], places=4)
        self.assertAlmostEqual(segs2[3]["out_start"], cards[0]["end"], places=4)
        self.assertEqual(E.join_problems(segs2, 30), [])                  # contiguous, frame-aligned splits
        self.assertEqual(E.cut_times(segs2, 30), E.cut_times(segs, 30))   # splits are not cuts

    def test_face_stays_in_its_half(self):
        from st.footage import edl as E
        from st.footage import reframe as R
        from st.footage import render_edl as RE
        p = make_edl(TMP / "face", [{"type": "panel", "say": "today", "title": "x", "dur": 2, "side": "left"}],
                     output={"fps": 30, "width": 1280, "height": 720})
        ed, segs, cards = resolved(p)
        from st.footage import cards as CD
        ed = dict(ed, ranges=CD.panel_splits(ed["ranges"], segs, cards, ed["output"]["fps"]))
        seg = next(s for s in E.plan(ed) if s.get("layout"))
        old = (R.available, R.detect_track)
        R.available = lambda: (True, "")
        R.detect_track = lambda *a, **k: [(0.7, 0.4, 0.3)] * 20       # a face at 70 % across the frame
        try:
            ctx = RE.Ctx(ed, TMP / "x.mp4", TMP / "facework", False)
            graph, _cmd, meta = RE._video_graph(seg, ctx)
        finally:
            R.available, R.detect_track = old
        import re
        scw = int(re.search(r"scale=(\d+):(\d+):flags=lanczos", graph).group(1))
        rw, rh, x0, _y0 = map(int, re.search(r"crop@rf=(\d+):(\d+):(\d+):(\d+)", graph).groups())
        self.assertEqual((rw, rh), (640, 720))
        self.assertAlmostEqual((0.7 * scw - x0) / rw, 0.5, delta=0.02)    # the face is centred in its half
        self.assertIn("pad=1280:720:640:0", graph)                        # the speaker takes the right half
        self.assertEqual(meta["fit"], "panel")


class FaceTest(unittest.TestCase):
    """Captions never cover the tracked face; a tall card with no room beside the face becomes a split."""

    def stub(self, track):
        from st.footage import cards as CD
        from st.footage import reframe as R
        old = (R.available, R.detect_track)
        R.available = lambda: (True, "")
        R.detect_track = lambda *a, **k: list(track)
        CD._FACE_CACHE.clear()
        self.addCleanup(lambda: (setattr(R, "available", old[0]), setattr(R, "detect_track", old[1]),
                                 CD._FACE_CACHE.clear()))

    def test_captions_move_below_the_chin(self):
        from st.footage import cards as CD
        self.stub([(0.5, 0.30, 0.30)] * 10)          # eyes 0.21, chin 0.465 of the frame
        p = make_edl(TMP / "face916", [{"type": "lower-third", "say": "I'm Ada Park", "name": "Ada Park", "role": "Eng"}],
                     output={"fps": 30, "aspect": "9:16"}, captions={"style": "bold-pop", "position": "middle"})
        ed, segs, cards = resolved(p, faces=True)
        plan = ed["caption_plan"]
        self.assertTrue(plan["zones"])
        for z in plan["zones"]:
            self.assertEqual(z["align"], 8)
            self.assertGreater(z["y"], 0.465)                  # below the chin
        for _a, _b, (y0, y1) in plan["bands"]:
            self.assertTrue(y0 >= 0.465 or y1 <= 0.21)        # never between eyes and chin
        lt = cards[0]["box"]                                   # the name tag below the moved captions
        self.assertGreaterEqual(lt["y"], max(bd[1] for _a, _b, bd in plan["bands"]))
        self.assertEqual(CD.problems(cards, ed), [])
        zones = CD.caption_zones(cards, 1080, 1920, plan)
        self.assertEqual(len(zones), len(plan["zones"]))

    def test_no_room_is_a_problem(self):
        from st.footage import cards as CD
        self.stub([(0.5, 0.45, 0.9)] * 10)            # a face filling the frame: no room above or below
        p = make_edl(TMP / "face-big", [{"type": "chapter", "say": "First", "title": "x", "dur": 2}],
                     output={"fps": 30, "aspect": "9:16"}, captions={"style": "bold-pop", "position": "middle"})
        ed, _segs, cards = resolved(p, faces=True)
        probs = CD.problems(cards, ed)
        self.assertTrue(any("cover the speaker's face" in x for x in probs), probs)

    def test_tall_card_without_room_becomes_a_split(self):
        from st.footage import cards as CD
        from st.footage import edl as E
        self.stub([(0.5, 0.35, 0.40)] * 10)
        p = make_edl(TMP / "split", [{"type": "stat", "say": "twenty two thousand miles", "value": 22000,
                                      "layout": "overlay", "dur": 1.0},
                                     {"type": "list", "say": "First", "title": "Two things",
                                      "items": [{"text": "Satellites", "say": "satellites"},
                                                {"text": "Space weather", "say": "Second"}], "hold": 0.5}],
                     output={"fps": 30, "aspect": "9:16"}, captions={"style": "bold-pop", "position": "middle"})
        ed, segs, cards = resolved(p, faces=True)
        lst, stat = sorted(cards, key=lambda c: c["type"])
        self.assertTrue(lst["split"] and lst["region"]["h"] == CD.SEAM)
        self.assertTrue(stat.get("cramped") and not stat.get("split"))          # "overlay" keeps it on the frame
        self.assertTrue(any("free between the face and the captions" in x for x in CD.problems(cards, ed)))
        ranges = CD.panel_splits(ed["ranges"], segs, cards, ed["output"]["fps"])
        self.assertTrue(any(r.get("layout") for r in E.plan(dict(ed, ranges=ranges))))
        z = CD.caption_zones(cards, 1080, 1920)
        self.assertEqual((z[0]["align"], z[0]["y"]), (2, CD.SEAM_CAPTION_Y))
        html = CD._card_html(lst, 3.0, "tall")
        self.assertIn("panel-bg", html)
        self.assertIn("justify-content:center", html)

    def test_bridges_chapter_split_and_ending(self):
        from st.footage import cards as CD
        from st.footage import edl as E
        self.stub([(0.5, 0.35, 0.40)] * 10)
        p = make_edl(TMP / "bridge", [{"type": "panel", "say": "space weather is", "title": "A", "until": "is"},
                                      {"type": "panel", "say": "away", "title": "B", "dur": 0.35},
                                      {"type": "chapter", "say": "First", "title": "Next"},
                                      {"type": "quote", "say": "Second space weather"}],
                     output={"fps": 30, "aspect": "9:16"}, captions={"style": "bold-pop", "position": "middle"})
        d = json.loads(p.read_text())
        d["ranges"][-1]["hold"] = 1.0
        p.write_text(json.dumps(d))
        ed, segs, cards = resolved(p, faces=True)
        grounds = [c for c in cards if c["type"] == "ground"]
        a, b = [c for c in cards if c["type"] == "panel"]
        # the two panels 1.2 s apart share their ground (no flip to the full shot and back)
        self.assertIn((a["end"], b["start"]), [(g["start"], g["end"]) for g in grounds])
        self.assertNotIn("ground", [r["type"] for r in CD.summary_rows(cards)])
        chap = next(c for c in cards if c["type"] == "chapter")
        self.assertTrue(chap["split"])                          # no scrim over the face in 9:16
        self.assertNotIn('class="scrim"', CD._card_html(chap, 2.0, "tall"))
        quote = next(c for c in cards if c["type"] == "quote")
        self.assertTrue(quote["to_end"] and quote["end"] == segs[-1]["out_end"])   # stays to the last frame
        self.assertIn("--out:11.", CD._card_html(quote, 2.0, "tall"))              # its exit is after the end
        held = segs[-1]
        self.assertEqual(held["hold_frames"], 30)
        self.assertAlmostEqual(held["src_end"], 10.0, places=3)                     # words map to the moving part
        self.assertAlmostEqual(held["out_end"] - held["out_start"], 6.0, places=3)

    def test_hold_never_runs_over_a_cut(self):
        _ed, _segs, cards = resolved(make_edl(TMP / "cutclamp", [{"type": "list", "say": "Hello", "title": "x",
                                                                  "items": [{"text": "Ada", "say": "Ada"}]}]))
        self.assertAlmostEqual(cards[0]["end"], 3.0, places=3)  # hold 2.2 after "Park," would cross the 3.0 s cut

    def test_list_plate_grows_with_its_items(self):
        from st.footage import cards as CD
        css = CD.css()
        self.assertIn(".plate .li { overflow: hidden; max-height: 0;", css)
        self.assertIn("@keyframes liGrow", css)

    def test_qa_flags_caption_over_face(self):
        from st.qa import video as QV
        v = TMP / "qaface.mp4"
        v.write_bytes(b"")
        (TMP / "qaface.report.json").write_text(json.dumps({
            "edl": "x", "caption_face": {"problems": ["the captions cover the speaker's face at 3.0-6.0 s (eyes 0.1 "
                                                      "to chin 0.9 of the frame) and there is no room"]}}))
        F = QV.Findings()
        QV._check_cards(F, v)
        self.assertEqual([f["rule"] for f in F.items], ["caption_face"])
        self.assertEqual(F.items[0]["t"], 3.0)


class ReviewW1Test(unittest.TestCase):
    """Fixes from the independent review of the cards (findings S1, S3-S5, P2, P5, P6, P8)."""

    def test_caption_cut_at_a_split_edge(self):
        # S1: a caption group that starts before a 9:16 panel and ends inside it is cut at the panel's start;
        # no event sits below the seam (on the speaker's head) while the panel is up
        from st.footage import captions as C
        from st.footage import cards as CD
        from st.qa import captions as QC
        words = [{"text": t, "start": a, "end": b, "type": "word"} for t, a, b in WORDS[9:17]]   # 5.10-7.95
        out = TMP / "straddle.ass"
        zones = [{"start": 6.3, "end": 9.0, "align": 2, "y": CD.SEAM_CAPTION_Y},
                 {"start": 0.0, "end": 6.3, "align": 8, "y": 0.62}]
        C.build(words, out, style="bold-pop", width=1080, height=1920, options={"zones": zones})
        cues = QC.parse(out)["cues"]
        self.assertTrue(any(c["start"] < 6.3 < c["end"] or abs(c["start"] - 6.3) < 0.011 for c in cues))
        for c in cues:
            if c["end"] > 6.31 and c["start"] < 9.0:
                self.assertIsNotNone(c["pos"], c)
                self.assertLessEqual(c["pos"][1], CD.SEAM * 1920, c)                  # above the seam
            if c["end"] <= 6.31:
                self.assertGreater(c["pos"][1], CD.SEAM * 1920, c)                   # below the chin zone
        # a word said before the cut keeps its spoken colour in the second piece (no second pop or highlight)
        txt = out.read_text()
        self.assertIn("Dialogue: 0,0:00:06.30", txt)

    def test_spoken_numbers(self):
        from st.footage import cards as CD

        def fold(s):
            return [t for t, _a, _b in CD._canon(CD._toks(s))]
        self.assertEqual(fold("two point five percent"), ["2.5", "percent"])
        self.assertEqual(fold("nineteen ninety five"), ["1995"])
        self.assertEqual(fold("in twenty twenty four"), ["in", "2024"])
        self.assertEqual(fold("one and two percent"), ["1", "and", "2", "percent"])
        self.assertEqual(fold("five six"), ["5", "6"])
        self.assertEqual(fold("one hundred and five"), ["105"])
        self.assertEqual(fold("two thousand and twenty four"), ["2024"])
        self.assertEqual(fold("twenty two thousand miles"), ["22000", "miles"])

    def run_cards(self, text, specs, **out):
        from st.footage import cards as CD
        ws = []
        t = 0.0
        for i, x in enumerate(text.split()):
            ws.append({"id": "w%d" % i, "text": x, "start": round(t, 3), "end": round(t + 0.3, 3), "type": "word",
                       "segment": 0})
            t += 0.35
        total = ws[-1]["end"] + 2
        segs = [{"i": 0, "source": "a", "start": 0.0, "src_end": total, "out_start": 0.0, "out_end": total,
                 "frames": int(total * 30)}]
        errs = []
        edl = {"cards": CD.normalize_specs(specs, errs), "captions": None, "sources": {"a": {"path": "x", "probe": {}}},
               "output": dict({"fps": Fraction(30), "width": 1920, "height": 1080}, **out)}
        self.assertEqual(errs, [])
        return edl, CD.resolve(edl, segs, ws, {}, faces=False)

    def test_stat_value_only_from_one_clean_number(self):
        from st.common import ShowtimeError
        _e, cs = self.run_cards("growth was two point five percent last year and more",
                                [{"type": "stat", "say": "two point five percent", "label": "growth", "dur": 4}])
        self.assertEqual((cs[0]["value"], cs[0]["decimals"]), (2.5, 1))
        _e, cs = self.run_cards("it started in nineteen ninety five with one satellite",
                                [{"type": "stat", "say": "nineteen ninety five", "label": "founded", "dur": 4}])
        self.assertEqual(cs[0]["value"], 1995)
        with self.assertRaises(ShowtimeError) as cm:
            self.run_cards("one and two percent of them", [{"type": "stat", "say": "one and two percent", "dur": 4}])
        self.assertIn("2 numbers (1, 2)", str(cm.exception))

    def test_items_after_the_card_and_until_reason(self):
        from st.common import ShowtimeError
        from st.footage import cards as CD
        text = ("we have three goals first speed then a long pause in the talk about many many things and more words "
                "to fill the time so it runs on and on and on second cost")
        edl, cs = self.run_cards(text, [{"type": "list", "say": "three goals", "dur": 3,
                                         "items": [{"text": "Speed", "say": "first speed"},
                                                   {"text": "Cost", "say": "second cost"}]}])
        probs = CD.problems(cs, edl)
        self.assertTrue(any("item 2 (\"Cost\") is said at" in p for p in probs), probs)
        with self.assertRaises(ShowtimeError) as cm:
            self.run_cards("alpha beta gamma delta epsilon zeta", [{"type": "title", "say": "gamma delta", "title": "T",
                                                                    "until": "alpha"}])
        self.assertIn("said only before this card's anchor", str(cm.exception))

    def test_stat_figure_settles_long_enough(self):
        from st.footage import cards as CD
        edl, cs = self.run_cards("it sits twenty two thousand miles up there now", [
            {"type": "stat", "say": "twenty two thousand miles", "label": "up", "dur": 1.6}])
        self.assertTrue(any("counted figure" in p for p in CD.problems(cs, edl)))
        edl, cs = self.run_cards("it sits twenty two thousand miles up there now", [
            {"type": "stat", "say": "twenty two thousand miles", "label": "up", "dur": 3.0}])
        self.assertLessEqual(CD.count_dur(cs[0]), 3.0 - 0.1 - CD.STAT_SETTLED_S + 1e-6)
        self.assertFalse(any("counted figure" in p for p in CD.problems(cs, edl)))

    def test_face_box_follows_the_fit(self):
        # P5: a 16:9 source contained in a 9:16 frame is a band across the middle; the face maps into it
        from st.footage import cards as CD
        from st.footage import reframe as R
        old = (R.available, R.detect_track)
        R.available = lambda: (True, "")
        R.detect_track = lambda *a, **k: [(0.5, 0.4, 0.3)] * 10
        CD._FACE_CACHE.clear()
        try:
            seg = {"out_start": 0.0, "out_end": 5.0, "start": 0.0, "source": "a"}
            src = {"path": TMP / "clip.mp4", "probe": {"width": 1920, "height": 1080}}
            contain = CD.face_box({"sources": {"a": src}, "output": {"fit": "contain"}}, [seg], 0, 4, 1080, 1920)
            crop = CD.face_box({"sources": {"a": src}, "output": {"fit": "auto"}}, [seg], 0, 4, 1080, 1920)
        finally:
            R.available, R.detect_track = old
            CD._FACE_CACHE.clear()
        band = (1 - (1080 * 1080 / 1920.0) / 1920) / 2               # the picture's top in the 9:16 frame
        self.assertAlmostEqual(contain["eyes"], band + (0.4 - 0.09) * (1080 * 1080 / 1920.0) / 1920, places=2)
        self.assertAlmostEqual(crop["eyes"], 0.31, places=2)

    def test_suggest_reads_a_transcript_that_says_ranges(self):
        tr = TMP / "ranges-take.json"
        tr.write_text(json.dumps({"source": str(TMP / "clip.mp4"), "duration": 10.0, "language": "en", "words": [
            {"id": "w%d" % i, "text": t, "start": i * 0.4, "end": i * 0.4 + 0.3, "type": "word"}
            for i, t in enumerate("The price ranges from ten to forty dollars for most of the people".split())]}))
        out = json.loads(st("edit", "cards", "suggest", tr, "--json", "--no-audio").stdout)
        self.assertEqual(out["duration"], 10.0)
        self.assertIn("source", out["timeline"])

    def test_suggest_quality(self):
        from st.footage import card_suggest as S
        ws = [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.25, "type": "word", "src": "_"}
              for i, t in enumerate(("This mission will give scientists the most comprehensive view we have ever had of "
                                     "the upper atmosphere around our planet today.").split())]
        q = S.quotes(ws, S._sentences(ws), {}, 6)
        self.assertTrue(q and all(len(x["say"].split()) <= 14 for x in q), q)
        rep = S.suggest(ws, duration=30.0)
        self.assertEqual(rep["duration"], 30.0)


class CaptionTest(unittest.TestCase):
    def test_emphasis_and_zones(self):
        from st.footage import captions as C
        words = [{"text": t, "start": a, "end": b, "type": "word"} for t, a, b in WORDS[9:17]]
        out = TMP / "caps.ass"
        rep = C.build(words, out, style="clean", width=1080, height=1920,
                      options={"emphasis": ["twenty two thousand miles"], "emphasis_color": "#FF7F61",
                               "zones": [{"start": 5.0, "end": 8.0, "align": 8, "y": 0.515}]})
        self.assertEqual(rep["emphasis"]["said"], 1)
        self.assertEqual(rep["emphasis"]["words"], 4)
        txt = out.read_text()
        self.assertIn("{\\c&H00617FFF}twenty{\\c&H00FFFFFF}", txt)
        self.assertIn("\\an8\\pos(", txt)
        from st.qa import captions as QC
        cap = QC.parse(out)
        inside = [c for c in cap["cues"] if c["start"] < 8.0]
        self.assertTrue(inside and all(c["pos"] and abs(c["pos"][1] - 0.515 * 1920) < 2 for c in inside))
        self.assertTrue(all(c["pos"] is None for c in cap["cues"] if c["start"] >= 8.0))   # the zone has ended
        self.assertEqual(QC.check(cap, 10, 1080, 1920), [])     # the pieces read as one caption
        # karaoke styles keep the emphasis colour between the spoken-word highlights
        C.build(words, out, style="bold-pop", width=1080, height=1920,
                options={"emphasis": ["miles"], "emphasis_color": "#7CF3FF"})
        self.assertIn("\\c&H00FFF37C", out.read_text())


class SuggestTest(unittest.TestCase):
    def test_candidates(self):
        from st.footage import card_suggest as S
        ws = [{"text": t, "start": a, "end": b, "type": "word", "id": "w%d" % i} for i, (t, a, b) in enumerate(WORDS)]
        ws += [{"text": t, "start": 20 + i * 0.4, "end": 20.3 + i * 0.4, "type": "word"} for i, t in enumerate(
            "So this is the most important thing we have ever built for science.".split())]
        rep = S.suggest(ws)["suggestions"]
        self.assertEqual(rep["stat"][0]["card"]["value"], 22000)
        self.assertEqual(rep["stat"][0]["say"], "twenty two thousand miles")
        self.assertEqual(rep["lower-third"][0]["card"]["name"], "Ada Park")
        self.assertTrue(any(len(x["card"]["items"]) == 2 for x in rep["list"]), rep["list"])
        self.assertTrue(any("most important thing" in x["say"] for x in rep["quote"]), rep["quote"])
        self.assertTrue(any(x["why"].startswith("an opener") or "pause" in x["why"] for x in rep["chapter"]))
        self.assertTrue(rep["title"][0]["say"].startswith("Hello I'm Ada Park"))

    def test_cli(self):
        p = make_edl(TMP / "sug", [])
        out = json.loads(st("edit", "cards", "suggest", p, "--json", "--no-audio").stdout)
        self.assertEqual(out["suggestions"]["stat"][0]["at"], round(6.05 - 2.0, 2))   # output times for an EDL
        tr = TMP / "sug" / "transcripts" / "clip.json"
        cp = st("edit", "cards", "suggest", tr)
        self.assertIn("\"type\": \"stat\"", cp.stdout)


class ReelPlacementTest(unittest.TestCase):
    """The card reel lands on the output frame for frame: each card's first reel frame on the card's first output
    frame, its last on the frame before the card's cut (a behind card's plate is cut frame-exact, so a reel frame
    short left the speaker on a bare plate: example 23's 9:16, frame 1307 before the cut at 43.600 s)."""

    def placed(self, fps, starts):
        from st import ff
        from st.footage import cards as CD, render_edl as R
        FF, W, H = ff.ffmpeg_path(), 32, 32
        d = Path(tempfile.mkdtemp(prefix="reel-", dir=str(TMP)))
        reel, base = d / "reel.mov", d / "base.mp4"
        rate = "%d/%d" % (fps.numerator, fps.denominator)
        # reel frame i is gray (i mod 30) * 8, opaque, like the real reel (QuickTime Animation, argb)
        subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=%dx%d:r=%s:d=8,format=rgba" % (W, H, rate),
                        "-vf", "geq=r='mod(N,30)*8':g='mod(N,30)*8':b='mod(N,30)*8':a='255'", "-c:v", "qtrle",
                        "-pix_fmt", "argb", str(reel)], check=True)
        subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "color=white:s=%dx%d:r=%s:d=12" % (W, H, rate),
                        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(base)], check=True)
        cards = [{"index": i, "start": float(Fraction(f) / fps), "end": float(Fraction(f + 23 + 7 * i) / fps)}
                 for i, f in enumerate(starts)]
        plan = CD.reel_plan(cards, fps)

        class Ctx:
            pass
        ctx = Ctx()
        ctx.w, ctx.h, ctx.full_w, ctx.full_h, ctx.fps = W, H, W, H, fps
        ctx.edl = {"overlays": CD.overlays_for(reel, plan)}
        args, parts, cur = R._overlay_graph(ctx, 1)
        raw = subprocess.run([FF, "-v", "error", "-i", str(base)] + args + [
            "-filter_complex", ";".join(parts) + ";%sformat=rgb24[v]" % cur, "-map", "[v]", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE, check=True).stdout
        px = [raw[(k * W * H + (H // 2) * W + W // 2) * 3] for k in range(len(raw) // (W * H * 3))]
        vals = [v if v > 245 else int(round(v / 8.0)) for v in px]
        for p in plan:
            f0 = int(round(p["card"]["start"] * float(fps)))
            want = [255] + [i % 30 for i in range(p["offset_frames"], p["offset_frames"] + p["frames"])] + [255]
            self.assertEqual(vals[f0 - 1:f0 + p["frames"] + 1], want, "card %d at frame %d (%s fps)" % (
                p["card"]["index"], f0, rate))

    def test_every_reel_frame_on_its_output_frame(self):
        self.placed(Fraction(30), [13, 63, 123, 183])          # 13: start/TB came out 12.999..., truncated a frame early
        self.placed(Fraction(30000, 1001), [7, 50, 101, 170])


class RenderTest(unittest.TestCase):
    def test_every_card_type_renders_with_alpha(self):
        import numpy as np
        from st import ff
        from st.footage import cards as CD
        cards_spec = [
            {"type": "title", "say": "Hello", "title": "Title card", "kicker": "Kicker", "dur": 1.0},
            {"type": "lower-third", "say": "Ada", "name": "Ada Park", "role": "Engineer", "dur": 1.0},
            {"type": "quote", "say": "and today", "dur": 1.0},
            {"type": "stat", "say": "twenty two thousand miles", "value": 22000, "suffix": " miles", "dur": 1.0},
            {"type": "chapter", "say": "First", "title": "Chapter", "dur": 1.0},
            {"type": "list", "say": "First", "title": "List", "items": [{"text": "One", "say": "satellites"},
                                                                       {"text": "Two", "say": "Second"}], "dur": 1.0},
            {"type": "panel", "say": "space weather", "title": "Panel", "body": "Body", "dur": 1.0, "side": "left"},
            {"type": "behind", "say": "weather", "text": "Weather", "dur": 1.0},
        ]
        p = make_edl(TMP / "reel", cards_spec, output={"fps": 30, "width": 480, "height": 270})
        ed, segs, cards = resolved(p)
        self.assertEqual(sorted({c["type"] for c in cards}), sorted(CD.TYPES))
        look = CD.look_for(ed, TMP / "reel" / "work")
        reel, plan = CD.render_reel(cards, 480, 270, Fraction(30), look, TMP / "reel" / "work", workers=1)
        pr = ff.probe(reel)
        self.assertTrue(pr.get("has_alpha") or "argb" in str(pr.get("pix_fmt")) or "rgba" in str(pr.get("pix_fmt")), pr)
        total = sum(x["frames"] for x in plan)
        for x in plan:   # the middle of each card: some opaque pixels, a transparent corner (except the panel side)
            t = (x["offset_frames"] + x["frames"] * 0.6) / 30.0
            raw = ff.run([ff.ffmpeg_path(), "-v", "error", "-ss", "%.4f" % t, "-i", str(reel), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgba", "-"], check=True, text=False).stdout
            a = np.frombuffer(raw, dtype=np.uint8).reshape(270, 480, 4)[:, :, 3]
            self.assertGreater(int((a > 200).sum()), 300, x["card"]["type"])
            if x["card"]["type"] not in ("panel", "chapter"):
                self.assertEqual(int(a[-3:, -3:].max()), 0, x["card"]["type"])
        self.assertGreater(total, 6 * 30)
        again, _ = CD.render_reel(cards, 480, 270, Fraction(30), look, TMP / "reel" / "work", workers=1)
        self.assertEqual(again, reel)                                     # cached by content

    def test_edit_render_with_cards(self):
        p = make_edl(TMP / "full", [
            {"type": "lower-third", "say": "I'm Ada Park", "name": "Ada Park", "role": "Engineer", "hold": 1.0},
            {"type": "panel", "say": "twenty two thousand miles", "title": "A panel", "until": "away", "side": "left"},
        ], output={"fps": 30, "width": 640, "height": 360}, captions={"style": "clean", "emphasis": ["miles"]})
        rep = json.loads(st("edit", "render", p, "--preview", "--json").stdout)
        self.assertTrue(rep["frames_ok"], rep)
        self.assertEqual(len(rep["segments"]), 4)                         # the panel splits the second range in three
        self.assertEqual([m.get("fit") for m in rep["segment_meta"]].count("panel"), 1)
        self.assertEqual([c["type"] for c in rep["cards"]["items"]], ["lower-third", "panel"])
        self.assertEqual(rep["captions"]["emphasis"]["said"], 1)
        from st.qa import video as QV
        F = QV.Findings()
        QV._check_cards(F, Path(rep["output"]))
        self.assertTrue(F.passed or F.items)
        view = json.loads(st("edit", "view", p, "--json").stdout)
        self.assertTrue(any("-cards-" in x for x in view["pages"]), view)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
