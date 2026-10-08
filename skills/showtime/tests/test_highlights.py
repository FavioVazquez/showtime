#!/usr/bin/env python3
"""A long recording's best moments as short clips: `edit moments` and `edit clips` (about 1-2 minutes).

A synthetic panel (fixture built here): three topics with their own words (rockets, a garden, music), two
speakers, a question hook, a number hook, a strong claim, a continuation start ("And then ..."), replies
("Yeah."), an introduction with applause after it, a punchline with laughter after it, fillers, a 4 s pause,
a two-word diarization blip, and tone-burst "speech" (lively: louder with a moving pitch; flat: quiet and
monotone) over a test pattern. Then:

- sentences, clean starts and ends, smoothed turns, word-boundary snapping (an edge inside a word keeps it
  whole, an edge in a pause moves to the next word), clip edges (no sliver of a neighbouring word, a lead-in
  dropped, a laugh kept with a trailing "So" dropped), the output size rule
- ranking signals: the question opens the top moment, a laugh and applause count, the lively passage has more
  energy than the flat one, introductions rank lower, no moment starts on "And" or a reply or spans the long
  pause, every moment lasts --min..--max and none overlap, the topic segments follow the vocabulary
- moments.json and its table from the CLI (the JSON shape)
- three clips from one job in one go (`edit clips --count 3 --preview`): one EDL each (whole words, fillers
  out, 9:16, bold-pop captions kept off the face), rendered in parallel, each through qa, audio as long as the
  picture, clips.json and the contact sheet; --pick makes one

usage: python tests/test_highlights.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-highlights-"))
SR = 16000

# (speaker, text, style, pause after in s, event after: (kind, seconds) or None)
# styles: n = normal, l = lively (loud, moving pitch), f = flat (quiet, monotone)
SCRIPT = [
    # an introduction: housekeeping, applause for the person
    ("S0", "Good evening and welcome to the show.", "n", 0.5, None),
    ("S0", "Please join me in welcoming our first guest, the rocket engineer Ada Park.", "n", 0.3, ("applause", 3.0)),
    ("S1", "Thank you for having me.", "n", 0.8, None),
    # topic A: rockets, with a question hook
    ("S0", "What would you do if the engines failed at liftoff?", "n", 0.8, None),
    ("S1", "The engines never fail at liftoff because we test every valve twice.", "l", 0.4, None),
    ("S1", "The launch team watches the engines, the valves and the fuel pumps for hours.", "l", 0.4, None),
    ("S1", "When the rocket clears the tower, the engines carry the whole mission.", "l", 0.4, None),
    ("S1", "That is the moment every engineer remembers.", "l", 0.8, None),
    ("S0", "Yeah.", "n", 0.6, None),
    ("S1", "And then the pumps kept running for hours after the rocket left the tower.", "n", 0.4, None),
    ("S1", "The valves stayed open and the engines stayed hot.", "n", 0.4, None),
    ("S1", "Um, the tower crew watched the rocket climb.", "n", 1.6, None),
    # topic B: a garden, a number hook, a punchline and laughter
    ("S0", "Twenty two thousand tomatoes grew in your garden last summer?", "n", 0.8, None),
    ("S1", "Right.", "n", 0.5, None),
    ("S1", "My garden soil is rich, the tomatoes love the sun, and the beans climb the fence.", "n", 0.4, None),
    ("S1", "Every morning I water the tomatoes and pull the weeds from the beans.", "n", 0.4, None),
    ("S1", "One night my neighbor's goat jumped the fence and ate every single tomato.", "l", 0.3, ("laughter", 2.5)),
    ("S1", "So the garden got a taller fence and the goat got a new home.", "l", 4.0, None),
    # topic C: music, flat delivery
    ("S1", "I also play guitar in a small band on weekends.", "f", 0.4, None),
    ("S1", "We practice songs in a garage and the chords are simple.", "f", 0.4, None),
    ("S1", "The drummer keeps time and the bass player tunes the strings.", "f", 0.4, None),
    ("S1", "Our songs are short and the melodies repeat a lot.", "f", 0.4, None),
    ("S1", "The band plays the same songs at every small concert.", "f", 0.4, None),
    ("S1", "The guitar strings need new tuning before each concert.", "f", 1.0, None),
]
FILLERS = {"um,", "um", "uh", "uh,"}


def build_fixture(folder: Path):
    """Write transcript.json, speech.wav (16 kHz) and talk.mp4 (test pattern + the speech); return their paths and
    the word list."""
    import numpy as np
    words, events, sent_bounds = [], [], []
    t, wid = 0.6, 0
    prev_spk = None
    for si, (spk, text, style, pause, ev) in enumerate(SCRIPT):
        if prev_spk is not None and spk != prev_spk:
            t += 0.3
        prev_spk = spk
        first = len(words)
        for k, tok in enumerate(text.split()):
            d = 0.14 + 0.045 * len(tok.strip(".,?!"))
            w = {"id": "w%d" % wid, "text": tok, "start": round(t, 3), "end": round(t + d, 3), "type": "word",
                 "speaker": spk, "style": style}
            if tok.lower() in FILLERS:
                w["filler"] = True
            words.append(w)
            wid += 1
            t += d + 0.07
        sent_bounds.append((first, len(words) - 1))
        t += pause
        if ev:
            events.append({"id": "w%d" % wid, "text": "(%s)" % ev[0], "start": round(t - pause + 0.2, 3),
                           "end": round(t - pause + 0.2 + ev[1], 3), "type": "audio_event"})
            wid += 1
            t += ev[1]
    # a diarization blip: two words of one sentence labelled as another speaker
    blip = sent_bounds[14][0] + 4
    words[blip]["speaker"] = words[blip + 1]["speaker"] = "S7"
    dur = t + 0.8
    x = np.zeros(int(dur * SR) + 1, dtype=np.float32)
    rng = np.random.default_rng(7)
    x += rng.normal(0.0, 0.0005, len(x)).astype(np.float32)
    for k, w in enumerate(words):
        a, b = int(w["start"] * SR), int(w["end"] * SR)
        n = b - a
        tt = np.arange(n) / SR
        if w["style"] == "l":
            amp, f0 = 0.45, 150.0 + 110.0 * ((k * 7) % 5) / 4.0
        elif w["style"] == "f":
            amp, f0 = 0.12, 140.0
        else:
            amp, f0 = 0.25, 175.0 + 15.0 * (k % 3)
        if w.get("filler"):
            amp, f0 = 0.15, 160.0
        sig = amp * (np.sin(2 * np.pi * f0 * tt) + 0.35 * np.sin(4 * np.pi * f0 * tt))
        fade = min(n // 4, int(0.01 * SR))
        env = np.ones(n, dtype=np.float32)
        if fade:
            env[:fade] = np.linspace(0, 1, fade)
            env[-fade:] = np.linspace(1, 0, fade)
        x[a:b] += (sig * env).astype(np.float32)
    for e in events:   # broadband noise for a laugh or applause
        a, b = int(e["start"] * SR), int(e["end"] * SR)
        x[a:b] += rng.normal(0.0, 0.08, b - a).astype(np.float32)
    x = np.clip(x, -0.99, 0.99)
    wav = folder / "speech.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((x * 32767).astype("<i2").tobytes())
    from st import ff
    video = folder / "talk.mp4"
    ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=%.3f" % dur, "-i", str(wav),
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                   "-shortest", str(video)])
    allw = []
    for w in words:
        allw.append({k: v for k, v in w.items() if k != "style"})
    allw += events
    allw.sort(key=lambda w: w["start"])
    tr = {"source": str(video), "duration": round(dur, 3), "language": "en", "model": "fixture", "words": allw}
    tp = folder / "edit" / "transcripts" / "talk.json"
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(json.dumps(tr), encoding="utf-8")
    return tp, video, words, events, sent_bounds


def st(*args, check=True, timeout=900, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                      cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def setUpModule():
    global TP, VIDEO, WORDS, EVENTS, SENTS
    TP, VIDEO, WORDS, EVENTS, SENTS = build_fixture(TMP)


def sent_text(i):
    return " ".join(w["text"] for w in WORDS[SENTS[i][0]:SENTS[i][1] + 1])


class UnitTest(unittest.TestCase):
    def test_snap_keeps_whole_words(self):
        from st.footage import moments as M
        ws = [{"text": "a", "start": 1.0, "end": 1.4}, {"text": "b", "start": 1.6, "end": 2.0},
              {"text": "c", "start": 2.5, "end": 3.0}]
        self.assertEqual(M.snap(ws, 1.2, 2.7), (0, 2))        # inside a, inside c: both stay whole
        self.assertEqual(M.snap(ws, 1.45, 2.2), (1, 1))       # in pauses: moves in to the words
        self.assertEqual(M.snap(ws, 1.4, 2.5), (1, 1))        # exactly on the boundaries: nothing cut
        self.assertEqual(M.snap(ws, 0.0, 9.0), (0, 2))
        with self.assertRaises(Exception):
            M.snap(ws, 2.05, 2.45)                            # no word in a pause

    def test_turns_smooth_a_blip(self):
        from st.footage import moments as M
        lab = M.turns(WORDS)
        b = SENTS[14][0] + 4
        self.assertEqual(lab[b], "S1")                        # the two-word blip takes the turn's label
        self.assertEqual(lab[SENTS[3][0]], "S0")              # a real turn stays
        self.assertEqual(lab[SENTS[4][0]], "S1")

    def test_sentences(self):
        from st.footage import moments as M
        ws = [w for w in WORDS]
        ss = M.sentences(ws, lang="en")
        texts = [" ".join(w["text"] for w in ws[s["a"]:s["b"] + 1]) for s in ss]
        self.assertIn(sent_text(3), texts)                    # the question is one sentence
        self.assertIn(sent_text(14), texts)                   # not split by the blip
        lower = [{"text": "We", "start": 0.0, "end": 0.3}, {"text": "went", "start": 0.35, "end": 0.6},
                 {"text": "home", "start": 1.8, "end": 2.1}, {"text": "and", "start": 2.15, "end": 2.3},
                 {"text": "slept.", "start": 2.35, "end": 2.7}, {"text": "Then", "start": 3.0, "end": 3.2},
                 {"text": "we", "start": 3.25, "end": 3.4}, {"text": "woke.", "start": 3.45, "end": 3.8}] * 1
        ss = M.sentences(lower, lang="en")
        starts = {lower[s["a"]]["text"]: s["clean_start"] for s in ss}
        self.assertFalse(starts["home"])                      # after a pause, but lower case: mid-sentence
        self.assertTrue(starts["Then"])

    def test_edges_tighten_and_trailing_so(self):
        from st.footage import clips as K
        ws = [{"id": "w0", "text": "before.", "start": 0.0, "end": 0.95},
              {"id": "w1", "text": "Yeah,", "start": 1.0, "end": 1.2}, {"id": "w2", "text": "um,", "start": 1.25, "end": 1.5},
              {"id": "w3", "text": "Goats", "start": 1.55, "end": 1.9}, {"id": "w4", "text": "ate", "start": 1.95, "end": 2.2},
              {"id": "w5", "text": "everything.", "start": 2.25, "end": 2.8},
              {"id": "w6", "text": "So", "start": 2.85, "end": 3.1}, {"id": "w7", "text": "anyway", "start": 9.0, "end": 9.4}]
        f, l, dropped = K.tighten(ws, 1, 5, "en")
        self.assertEqual((f, l), (3, 5))
        self.assertEqual(dropped, ["Yeah,", "um,"])
        head, tail, kept, drop = K.edges(ws, f, l)
        self.assertGreaterEqual(head, 1.5 + K.GUARD - 1e-6)   # never a sliver of the dropped "um"
        self.assertLessEqual(tail, 2.85 - K.GUARD + 1e-6)     # nor of the "So" after
        self.assertIsNone(kept)
        laugh = [{"text": "(laughter)", "start": 4.0, "end": 7.5, "type": "audio_event"}]
        head, tail, kept, drop = K.edges(ws, f, l, laugh)
        self.assertEqual(kept["type"], "laughter")
        self.assertAlmostEqual(tail, 2.8 + K.EVENT_TAIL, places=3)
        self.assertEqual(drop, [6])                           # the trailing "So" goes, the laugh stays

    def test_plan_clip_ends_on_the_laugh_and_cuts_inside(self):
        from st.footage import clips as K
        from st.footage import util as U
        tr = U.load_transcript(TP)
        goat = SENTS[16]
        m = {"id": "mx", "start": WORDS[SENTS[15][0]]["start"], "end": WORDS[goat[1]]["end"],
             "remove": ["%s-%s" % (WORDS[SENTS[15][0]]["id"], WORDS[SENTS[15][0] + 2]["id"])]}
        p = K.plan_clip(m, tr, TP, edl_dir=TMP / "plan", aspect="9:16", captions="bold-pop")
        d = p["doc"]
        self.assertEqual(p["event"]["type"], "laughter")
        self.assertIn("fade_out", d["ranges"][-1])                           # the laugh fades out, no abrupt end
        self.assertGreater(d["ranges"][-1]["end"], WORDS[goat[1]]["end"] + 1.0)
        cut = {r["id"] for r in d["cut_summary"]["removed"] if r["why"] == "word range"}
        self.assertEqual(cut, {WORDS[SENTS[15][0] + k]["id"] for k in range(3)})
        first_kept = WORDS[SENTS[15][0] + 3]
        self.assertLessEqual(d["ranges"][0]["start"], first_kept["start"])
        self.assertGreater(d["ranges"][0]["start"], WORDS[SENTS[15][0] + 2]["end"])   # the cut words are gone
        from st.footage import edl as E
        TMP.joinpath("plan").mkdir(exist_ok=True)
        q = TMP / "plan" / "x.json"
        q.write_text(json.dumps(d), encoding="utf-8")
        E.load(q)                                                             # a valid EDL

    def test_generated_edl_updates_in_place_hand_edit_kept(self):
        from st.footage import clips as K
        d = TMP / "gen"
        d.mkdir(exist_ok=True)
        doc = {"sources": {"a": "x.mp4"}, "ranges": [{"source": "a", "start": 0, "end": 1}]}
        p1 = K._edl_file(d / "01-a.json", doc, False)
        p2 = K._edl_file(d / "01-a.json", dict(doc, title="new"), False)      # untouched: updated in place
        self.assertEqual(p1, p2)
        self.assertEqual(json.loads(p2.read_text(encoding="utf-8"))["title"], "new")
        hand = json.loads(p2.read_text(encoding="utf-8"))
        hand["ranges"][0]["end"] = 0.8                                        # an edit by hand
        p2.write_text(json.dumps(hand), encoding="utf-8")
        p3 = K._edl_file(d / "01-a.json", dict(doc, title="newer"), False)
        self.assertEqual(p3.name, "01-a-2.json")                              # the hand edit is kept
        self.assertEqual(json.loads(p2.read_text(encoding="utf-8"))["ranges"][0]["end"], 0.8)

    def test_captions_shrink_rather_than_jump_above_the_eyes(self):
        from st.footage import cards as CD
        from st.footage import clips as K
        folder = TMP / "fit"
        folder.mkdir(exist_ok=True)
        doc = {"sources": {"a": str(VIDEO)}, "transcripts": {"a": str(TP)},
               "ranges": [{"source": "a", "start": 1.0, "end": 9.0}], "output": {"width": 360, "height": 640},
               "captions": {"style": "bold-pop", "avoid_face": True, "size": K.TALL_CAPTION_SIZE}}
        p = folder / "edl.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        sb = CD._safe(360, 640)[3]
        band = lambda size: CD.caption_band(dict(doc["captions"], size=size), 360, 640)    # noqa: E731
        bh_big, bh_small = (b[1] - b[0] for b in (band(K.TALL_CAPTION_SIZE), band(K.TALL_CAPTION_MIN)))
        real = CD.face_box
        try:
            chin = sb - bh_small - 0.008 - 0.002                     # fits under the chin only at the smaller size
            self.assertGreater(chin + 0.008 + bh_big, sb)
            CD.face_box = lambda *a, **k: {"x": 0.5, "top": 0.2, "bottom": chin + 0.02, "eyes": 0.4, "chin": chin}
            self.assertEqual(K.fit_captions(p), (K.TALL_CAPTION_MIN, []))
            CD.face_box = lambda *a, **k: {"x": 0.5, "top": 0.2, "bottom": 0.76, "eyes": 0.45, "chin": 0.74}
            size, above = K.fit_captions(p)                          # no room under it at either size
            self.assertIsNone(size)
            self.assertTrue(above)
        finally:
            CD.face_box = real

    def test_out_size(self):
        from st.footage import clips as K
        self.assertEqual(K.out_size("9:16", 1920, 1080), {"aspect": "9:16", "allow_upscale": True})
        self.assertEqual(K.out_size("9:16", 1280, 720), {"width": 720, "height": 1280, "allow_upscale": True})
        self.assertEqual(K.out_size("9:16", 3840, 2160), {"aspect": "9:16"})
        self.assertEqual(K.out_size("16:9", 1920, 1080), {"aspect": "16:9"})


class RankTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from st.footage import moments as M
        cls.doc = M.rank([TP], count=40, min_len=8.0, max_len=20.0)
        cls.ms = cls.doc["moments"]

    def first_sentence(self, m):
        return next((i for i, (a, b) in enumerate(SENTS) if abs(WORDS[a]["start"] - m["start"]) < 1e-3), None)

    def test_every_moment_is_whole_sentences_in_range(self):
        self.assertGreaterEqual(len(self.ms), 3)
        starts = {round(WORDS[a]["start"], 3) for a, b in SENTS}
        ends = {round(WORDS[b]["end"], 3) for a, b in SENTS}
        long_pause_at = WORDS[SENTS[17][1]]["end"]
        for m in self.ms:
            self.assertIn(round(m["start"], 3), starts, m)
            self.assertIn(round(m["end"], 3), ends, m)
            self.assertTrue(8.0 <= m["duration"] <= 20.0, m)
            self.assertFalse(m["start"] < long_pause_at < m["end"], m)       # never across the 4 s pause
            self.assertFalse(m["text"].startswith(("And ", "Yeah.", "Right.", "Thank you")), m["text"])
        spans = sorted((m["start"], m["end"]) for m in self.ms)
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            self.assertLessEqual(b1, a2)                                     # no overlap

    def test_question_hook_ranks_first(self):
        top = self.ms[0]
        self.assertEqual(self.first_sentence(top), 3, top)
        self.assertIn("opens with a question", top["why"])
        self.assertGreaterEqual(top["signals"]["hook"], 0.4)
        self.assertEqual(top["title"], "What would you do if the engines failed at liftoff?")

    def test_laughter_counts_and_music_band_is_flat(self):
        goat = next(m for m in self.ms if "goat jumped the fence" in m["text"])
        self.assertTrue(any(e["type"] == "laughter" for e in goat["events"]), goat)
        self.assertGreater(goat["signals"]["events"], 0.0)
        flat = [m for m in self.ms if "guitar" in m["text"] or "songs" in m["text"]]
        self.assertTrue(flat)
        for f in flat:
            self.assertLess(f["signals"]["energy"], goat["signals"]["energy"])
            self.assertLess(f["score"], goat["score"])

    def test_introduction_ranks_lower(self):
        intro = [m for m in self.ms if "welcoming" in m["text"]]
        for m in intro:
            self.assertTrue(m["housekeeping"], m)
            self.assertTrue(any("housekeeping" in w for w in m["why"]), m)
            self.assertGreater(m["rank"], 2)

    def test_topics_follow_the_vocabulary(self):
        tops = self.doc["sources"]["talk"]["topics"]
        self.assertGreaterEqual(len(tops), 2)
        bounds = [t["start"] for t in tops[1:]]
        garden = WORDS[SENTS[12][0]]["start"]
        music = WORDS[SENTS[18][0]]["start"]
        self.assertTrue(any(abs(b - garden) < 8.0 for b in bounds) or any(abs(b - music) < 8.0 for b in bounds), tops)
        kw = " ".join(" ".join(t["keywords"]) for t in tops)
        self.assertTrue(any(k in kw for k in ("tomato", "garden", "songs", "guitar", "engines", "rocket")), tops)

    def test_signals_measured(self):
        m = self.doc["signals"]["measured"]
        for k in ("hook", "complete", "energy", "events", "lines", "topic", "flow", "length"):
            self.assertTrue(m[k], k)
        no_audio = __import__("st.footage.moments", fromlist=["rank"]).rank([TP], count=3, min_len=8, max_len=20,
                                                                             audio=False)
        self.assertFalse(no_audio["signals"]["measured"]["energy"])
        self.assertIsNone(no_audio["moments"][0]["signals"]["energy"])


class CliTest(unittest.TestCase):
    def test_json_shape_and_table(self):
        out = TMP / "m.json"
        doc = json.loads(st("edit", "moments", TP, "--min", "8", "--max", "20", "--count", "4", "-o", out,
                            "--json").stdout)
        self.assertTrue(out.is_file())
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["moments"], doc["moments"])
        for k in ("version", "created", "params", "sources", "signals", "candidates", "notes", "moments"):
            self.assertIn(k, doc)
        self.assertEqual(doc["params"], {"count": 4, "min": 8.0, "max": 20.0, "audio": True})
        self.assertEqual(len(doc["moments"]), 4)
        m = doc["moments"][0]
        types = {"id": str, "rank": int, "score": float, "source": str, "transcript": str, "start": float,
                 "end": float, "span": float, "duration": float, "words": list, "title": str, "opening": str,
                 "closing": str, "keywords": list, "signals": dict, "why": list, "speakers": dict, "events": list,
                 "topic": int, "fillers": int, "housekeeping": list, "text": str}
        for k, t in types.items():
            self.assertIsInstance(m[k], t, k)
        self.assertEqual(sorted(m["signals"]), sorted(["hook", "complete", "energy", "events", "lines", "topic",
                                                       "flow", "length"]))
        self.assertEqual([x["rank"] for x in doc["moments"]], [1, 2, 3, 4])
        self.assertEqual([x["id"] for x in doc["moments"]], ["m1", "m2", "m3", "m4"])
        cp = st("edit", "moments", TP, "--min", "8", "--max", "20", "--count", "3", "-o", out)
        self.assertIn("m-2.json", cp.stdout)                                   # never overwrites: m-2.json
        self.assertIn(" m1 ", cp.stdout)
        self.assertIn("opens: ", cp.stdout)

    def test_two_recordings_rank_together(self):
        other = TMP / "edit" / "transcripts" / "talk-day2.json"
        other.write_text(TP.read_text(encoding="utf-8"), encoding="utf-8")
        doc = json.loads(st("edit", "moments", TP, other, "--min", "8", "--max", "20", "--count", "6", "-o",
                            TMP / "two.json", "--json").stdout)
        self.assertEqual(sorted(doc["sources"]), ["talk", "talk2"])
        self.assertEqual({m["source"] for m in doc["moments"]}, {"talk", "talk2"})
        for m in doc["moments"]:
            self.assertEqual(Path(m["transcript"]).name, "talk.json" if m["source"] == "talk" else "talk-day2.json")
        other.unlink()

    def test_bad_lengths(self):
        cp = st("edit", "moments", TP, "--min", "30", "--max", "20", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("--min", cp.stderr)


class ClipsTest(unittest.TestCase):
    """Three clips from one job: the moments of the fixture, rendered as drafts in parallel, each through qa."""

    @classmethod
    def setUpClass(cls):
        work = TMP / "jobs"
        work.mkdir(exist_ok=True)
        cls.cwd = work
        cp = st("job", "init", "clips-test", "--platform", "shorts", cwd=work)
        cls.job = Path(cp.stdout.strip().splitlines()[-1])
        if not cls.job.is_absolute():
            cls.job = (work / cls.job).resolve()
        tdir = cls.job / "edit" / "transcripts"
        tdir.mkdir(parents=True, exist_ok=True)
        tr = json.loads(TP.read_text(encoding="utf-8"))
        (tdir / "talk.json").write_text(json.dumps(tr), encoding="utf-8")
        st("edit", "moments", cls.job, "--min", "8", "--max", "20", "--count", "5", cwd=work)
        cls.rep = json.loads(st("edit", "clips", cls.job, "--count", "3", "--preview", "--json", cwd=work).stdout)

    def test_three_clips_rendered_and_checked(self):
        from st import ff
        rep = self.rep
        self.assertEqual(len(rep["clips"]), 3)
        self.assertEqual(rep["parallel"], min(3, max(1, __import__("os").cpu_count() // 4)))
        for c in rep["clips"]:
            self.assertNotIn("error", c)
            v = Path(c["video"])
            self.assertTrue(v.is_file(), c)
            self.assertEqual(v.parent, self.job / "clips" / "preview")
            self.assertTrue(v.name.startswith("%02d-" % c["n"]))
            pr = ff.probe(v)
            self.assertEqual((pr["width"], pr["height"]), (360, 640))          # 9:16 from 360p, no more than 1.78x
            self.assertAlmostEqual(pr["duration"], c["duration"], delta=0.05)
            self.assertIn(c["qa"]["verdict"], ("PASS", "WARN"), c["qa"])
            self.assertIsNotNone(c["qa"]["lufs"])
            raw = json.loads(ff.run([ff.ffprobe_path(), "-v", "error", "-show_entries", "stream=codec_type,duration",
                                     "-of", "json", str(v)], check=True).stdout)["streams"]
            durs = {s["codec_type"]: float(s["duration"]) for s in raw}
            self.assertAlmostEqual(durs["audio"], durs["video"], delta=0.025)  # the sound never ends early
        for c in rep["clips"]:                                                 # each segment: sound as long as picture
            segs = sorted((Path(c["edl"]).parent / "work" / Path(c["edl"]).stem / "segments").glob("seg*.mov"))
            self.assertTrue(segs, c)
            # the clip's own intermediates: work/<name>/render, not work/<name>/<name> (Windows' 260-character
            # limit with long paths off failed opening the temp WAV there)
            shared = Path(c["edl"]).parent / "work" / Path(c["edl"]).stem
            self.assertTrue((shared / "render").is_dir(), sorted(p.name for p in shared.iterdir()))
            self.assertFalse((shared / Path(c["edl"]).stem).exists())
            for sp in segs:
                raw = json.loads(ff.run([ff.ffprobe_path(), "-v", "error", "-show_entries",
                                         "stream=codec_type,duration", "-of", "json", str(sp)], check=True).stdout)
                durs = {x["codec_type"]: float(x["duration"]) for x in raw["streams"]}
                self.assertAlmostEqual(durs["audio"], durs["video"], delta=0.002, msg=sp.name)
        self.assertTrue(Path(rep["sheet"]).is_file())
        man = json.loads(Path(rep["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual([c["moment"] for c in man["clips"]], ["m1", "m2", "m3"])
        for k in ("version", "job", "moments", "preview", "aspect", "captions", "clips", "sheet", "parallel", "seconds"):
            self.assertIn(k, man)
        job = json.loads((self.job / "job.json").read_text(encoding="utf-8"))
        self.assertTrue(any("edit clips: 3 clip(s)" in h["event"] for h in job["history"]))
        self.assertIsNone((job.get("outputs") or {}).get("final"))            # a clip never becomes the job's final

    def test_clip_edls_cut_whole_words(self):
        moments = json.loads(sorted((self.job / "edit").glob("moments*.json"))[-1].read_text(encoding="utf-8"))
        for c in self.rep["clips"]:
            edl = json.loads(Path(c["edl"]).read_text(encoding="utf-8"))
            m = next(x for x in moments["moments"] if x["id"] == c["moment"])
            self.assertEqual(edl["output"], {"width": 360, "height": 640, "allow_upscale": True})
            self.assertEqual(edl["captions"], {"style": "bold-pop", "avoid_face": True, "size": 0.09})
            words = [w for w in WORDS if m["start"] - 1e-3 <= w["start"] and w["end"] <= m["end"] + 1e-3]
            for w in words:
                inside = [r for r in edl["ranges"] if r["start"] - 1e-3 <= w["start"] and w["end"] <= r["end"] + 1e-3]
                cut = [r for r in edl["ranges"] if r["start"] < w["end"] and r["end"] > w["start"]]
                if w.get("filler"):
                    continue
                self.assertTrue(inside, (w, edl["ranges"]))                    # every word is whole in one range
                self.assertEqual(len(cut), 1, (w, edl["ranges"]))
            for r in edl["ranges"]:
                for w in WORDS:
                    if w.get("filler"):
                        self.assertFalse(r["start"] < (w["start"] + w["end"]) / 2 < r["end"], (w, r))
            prev = [w for w in WORDS if w["end"] <= m["start"]]
            if prev:
                self.assertGreaterEqual(edl["ranges"][0]["start"], prev[-1]["end"])   # no sliver of the word before

    def test_pick_one_with_a_hand_edited_edge(self):
        mp = sorted((self.job / "edit").glob("moments*.json"))[-1]
        doc = json.loads(mp.read_text(encoding="utf-8"))
        m = doc["moments"][1]
        w = next(x for x in WORDS if x["start"] >= m["start"] + 0.5)
        m["start"] = round((w["start"] + w["end"]) / 2, 3)                      # inside a word: it stays whole
        hand = self.job / "edit" / "moments-hand.json"
        hand.write_text(json.dumps(doc), encoding="utf-8")
        rep = json.loads(st("edit", "clips", self.job, "--moments", hand, "--pick", m["id"], "--preview", "--no-qa",
                            "--json", cwd=self.cwd).stdout)
        self.assertEqual(len(rep["clips"]), 1)
        c = rep["clips"][0]
        self.assertTrue(any("snapped to whole words" in n for n in c["notes"]), c["notes"])
        self.assertTrue(any("mid-sentence" in n for n in c["notes"]), c["notes"])
        edl = json.loads(Path(c["edl"]).read_text(encoding="utf-8"))
        self.assertLessEqual(edl["ranges"][0]["start"], w["start"])
        self.assertTrue(Path(c["video"]).is_file())
        self.assertNotIn("qa", c)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
