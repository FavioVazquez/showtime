#!/usr/bin/env python3
"""The read-back (st.voice.readback): the voice-over heard again and compared with the script.

- the matcher: "OpenAI", "open AI" and "Open A I" are the same name; "OpenI" and "open eye" are not; digits
  and number words, other spellings of one sound and case pass; a short name that changes a vowel fails
- what matters in a line (names, acronyms, numbers, lexicon words), a lone "A" told as the article
- the case that shipped (7 Oct): the maths explainer's line "Now Open A I says ..." (bm_george); the fixture
  is a 3 s cut of that render's own voice-over, in which the recognizer hears "open an eye" (when installed)
- qa: the `readback` item (WARN; FAIL for a title/brand/lexicon name only when a second recognizer also hears it
  differently; INFO when it cannot run, with the fetch hint only when the recognizer is missing), voice/readback.json
  reused for the same vo.wav, audio.txt's table, the receipt's QA line
- a right read respelled by the recognizer (review of 0.4.1: "JSON" written "JSO" by Parakeet, heard "JSON" by
  Whisper small.en, in a project titled "JSON for teams"): WARN, not FAIL; showtime.json "readback": {"ok": [...]}
  clears it for voice script and qa; the recognizer's name is in the cache key
- `voice script`'s "heard back" lines; lexicon precedence (project over the built-in list)
- without --fast, when Kokoro and the recognizer are here: `voice script` flags the bad line, passes the fix

usage: python tests/test_readback.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

FAST = "--fast" in sys.argv
FIXTURE = TESTS_DIR / "fixtures" / "readback" / "openai-swallowed.ogg"
BAD = "Now Open A I says its internal model showed five never work."
HEARD_BAD = "Now OpenI says its internal model showed five never work."   # what Parakeet wrote for the posted video


def words(text, step=0.3):
    return [{"text": w, "start": round(i * step, 3), "end": round(i * step + 0.2, 3)} for i, w in enumerate(text.split())]


def espeak_ok():
    try:
        from st.voice import espeak
        return bool(espeak.phonemize(["test"], "en-us")[0])
    except Exception:  # noqa: BLE001
        return False


ESPEAK = espeak_ok()


class Base(unittest.TestCase):
    def setUp(self):
        if not ESPEAK:
            self.skipTest("espeak-ng is not available here (showtime setup)")
        from st.voice import lexicon as lm
        from st.voice import readback as rb
        self.rb = rb
        self.lex = lm.load()

    def flagged(self, script, heard, lang="en-gb", **kw):
        r = self.rb.compare_line(script, words(heard), lang, self.lex, self.rb.capital_words([script]), **kw)
        return [(s["word"], s["heard"]) for s in r["suspects"]]


class MatcherTests(Base):
    def test_openai_spellings(self):
        good = "Now OpenAI says its internal model showed five."
        for heard in ("Now OpenAI says its internal model showed five.",
                      "Now open AI says its internal model showed five.",
                      "Now Open A I says its internal model showed five.",
                      "now openai says its internal model showed five"):
            self.assertEqual(self.flagged(good, heard), [], heard)
        for heard, got in (("Now OpenI says its internal model showed five.", "OpenI"),
                           ("Now open eye says its internal model showed five.", "open eye")):
            self.assertEqual(self.flagged(good, heard), [("OpenAI", got)], heard)

    def test_numbers(self):
        s = "Four to seven, for sixty-eight years. Then in twenty eighteen, a huge drawing ruled out four."
        self.assertEqual(self.flagged(s, "Four to seven, for 68 years. Then, in 2018, a huge drawing ruled out four."), [])
        self.assertEqual(self.flagged("It was 2018 when it began.", "It was two thousand eighteen when it began."), [])
        self.assertEqual(self.flagged("It is three point five times faster.", "It is 3.5 times faster."), [])
        self.assertEqual(self.flagged("The model showed nine.", "The model showed five."), [("nine", "five")])
        self.assertEqual(self.flagged("For sixty-eight years.", "For sixty years."), [("sixty-eight", "sixty")])
        nv = self.rb.number_value
        self.assertEqual(nv(["sixty-eight"], "en"), "68")
        self.assertEqual(nv(["twenty", "eighteen"], "en"), "2018")
        self.assertEqual(nv(["two", "thousand", "and", "eighteen"], "en"), "2018")
        self.assertEqual(nv(["nineteen", "ninety-nine"], "en"), "1999")
        self.assertEqual(nv(["three", "point", "five"], "en"), "3.5")
        self.assertEqual(nv(["1,000"], "en"), "1000")
        self.assertEqual(nv(["sesenta", "y", "ocho"], "es"), "68")
        self.assertEqual(nv(["dos", "mil", "dieciocho"], "es"), "2018")
        self.assertIsNone(nv(["sixty", "apples"], "en"))

    def test_harmless_noise_passes(self):
        cases = [("Colour the plane so points exactly one apart always differ.",
                  "Color the plane, so points exactly one apart always differ."),
                 ("If it holds up, it's six or seven. Which one? Still open.",
                  "If it holds up, it's six or seven, which one still open?"),
                 ("with a Lean proof a computer can check.", "with a lean proof a computer can check."),
                 ("Ask Claude about it.", "Ask clawed about it."),               # the same sound
                 ("This week CUDA is in the news.", "This week Cuta is in the news."),
                 ("This week JSON is in the news.", "This week Jason is in the news."),
                 ("Use the S Q L shell.", "Use the SQL shell.")]
        for s, h in cases:
            self.assertEqual(self.flagged(s, h), [], s)

    def test_short_names_keep_every_sound(self):
        self.assertEqual(self.flagged("Ask Claude about it.", "Ask cloud about it."), [("Claude", "cloud")])
        self.assertEqual(self.flagged("It runs on Nvidia chips.", "It runs on in video chips."),
                         [("Nvidia", "in video")])

    def test_what_matters(self):
        from st.voice.textnorm import normalize_tokens, tokenize
        text = "Colour the plane. Now Open A I and GitHub say I was right in 2018 with Lean."
        toks = tokenize(text)
        normalize_tokens(toks, "en")
        got = [(u["text"], u["kind"]) for u in self.rb.units(toks, "en", self.lex, self.rb.capital_words([text]))]
        self.assertEqual(got, [("Open A I", "name"), ("GitHub", "name"), ("2018", "number"), ("Lean", "name")])
        # a brand written in lower case counts when it is a title/brand name
        toks = tokenize("Made with showtime.")
        self.assertEqual([u["text"] for u in self.rb.units(toks, "en", None, set(), {"showtime"})], ["showtime"])

    def test_lone_a_is_told_as_the_article(self):
        r = self.rb.compare_line("Now Open A I says so.", words("Now Open a I says so."), "en-gb", self.lex)
        self.assertEqual(len(r["suspects"]), 1)
        s = r["suspects"][0]
        self.assertTrue(s["lone_a"])
        self.assertIn("one word (OpenAI)", self.rb.fix_for(s))
        # spelled-out letters the voice reads as letters are fine
        self.assertEqual(self.flagged("Use the S Q L shell.", "Use the S Q L shell."), [])

    def test_symbols(self):
        sym = self.rb.symbols
        self.assertEqual(sym("kˈʌlɚ"), sym("kʌlɚ"))
        self.assertEqual(sym("ˈɑːnɪks"), ["ɑ", "n", "ɪ", "k", "s"])
        self.assertEqual(sym("ɒŋŋks"), sym("ɒŋks"))
        self.assertEqual(sym("sjˈuːdoʊ"), sym("sˈuːdoʊ"))
        self.assertEqual(self.rb.letters("Open A I"), self.rb.letters("OpenAI"))


class FixtureTests(Base):
    """The posted video's line: the script respelled the name "Open A I", the voice swallowed the "A"."""

    def test_heard_text_of_the_posted_line_is_flagged(self):
        got = self.flagged(BAD, HEARD_BAD)
        self.assertEqual(got, [("Open A I", "OpenI")])

    def test_fixture_audio_is_flagged(self):
        ok, why = self.rb.asr_ready("en")
        if not ok:
            self.skipTest(why)
        self.assertTrue(FIXTURE.is_file())
        heard = self.rb.heard_words(FIXTURE, "en")
        self.assertTrue(heard, "nothing heard in the fixture")
        script = "Now Open A I says its internal model showed."      # the fixture: 3 s of that line
        r = self.rb.compare_line(script, heard, "en-gb", self.lex)
        self.assertEqual([s["word"] for s in r["suspects"]], ["Open A I"], r)
        self.assertNotIn("openai", self.rb.letters(r["heard"]))      # Parakeet hears "open an eye" here
        # judged on the sound alone (the name written as one word, no lone "A" to lint): still flagged
        r2 = self.rb.compare_line(script.replace("Open A I", "OpenAI"), heard, "en-gb", self.lex)
        self.assertEqual([s["word"] for s in r2["suspects"]], ["OpenAI"], r2)


def _wav(path, seconds=1.0):
    import numpy as np
    from st.voice import audio_io as aio
    path.parent.mkdir(parents=True, exist_ok=True)
    aio.write(path, (0.01 * np.sin(np.arange(int(48000 * seconds)) / 9.0)).astype("float32"), 48000, bits=16)


class QaTests(Base):
    def project(self, title="Six or seven: the colours of the plane", brand=None, lexicon=None):
        d = Path(tempfile.mkdtemp(prefix="st-rb-"))
        (d / "showtime.json").write_text(json.dumps({"title": title, "duration": 10}), encoding="utf-8")
        if brand:
            (d / "brand.json").write_text(json.dumps({"name": brand}), encoding="utf-8")
        if lexicon:
            (d / "lexicon.json").write_text(json.dumps(lexicon), encoding="utf-8")
        (d / "narration.md").write_text("## shot-1\nColour the plane.\n\n## shot-6\n%s\n" % BAD, encoding="utf-8")
        tl = {"file": "vo.wav", "script": "../narration.md", "lines": [
            {"id": "shot-1", "text": "Colour the plane.", "source_text": "Colour the plane.", "lang": "en-gb",
             "start": 0.0, "end": 1.4, "speech_start": 0.05, "speech_end": 1.3, "file": "lines/01-shot-1.wav"},
            {"id": "shot-6", "text": BAD, "source_text": BAD, "lang": "en-gb", "start": 2.0, "end": 6.0,
             "speech_start": 2.05, "speech_end": 5.9, "file": "lines/02-shot-6.wav"}]}
        (d / "voice").mkdir()
        (d / "voice" / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        _wav(d / "voice" / "vo.wav", 6.5)
        return d

    def test_vo_wav_split_by_line_and_critical_names(self):
        d = self.project(brand="OpenAI")
        heard = words("Colour the plane.", 0.3) + [dict(w, start=w["start"] + 2.1, end=w["end"] + 2.1)
                                                   for w in words(HEARD_BAD, 0.4)]
        calls = []

        def fake(wav, lang, key=None, model="auto"):
            calls.append(Path(wav).name)
            return heard
        orig = self.rb.heard_words, self.rb.asr_ready, self.rb.second_recognizer
        self.rb.heard_words, self.rb.asr_ready = fake, (lambda lang: (True, ""))
        self.rb.second_recognizer = lambda lang: None
        self.rb._READY.clear()
        try:
            rep = self.rb.for_project(d)
        finally:
            self.rb.heard_words, self.rb.asr_ready, self.rb.second_recognizer = orig
            self.rb._READY.clear()
        self.assertEqual(calls, ["vo.wav"])                  # no line clips: the whole vo.wav, split by line
        self.assertEqual(rep["source"], "voice/vo.wav")
        self.assertEqual([(s["line"], s["word"], s["heard"]) for s in rep["suspects"]], [("shot-6", "Open A I", "OpenI")])
        s = rep["suspects"][0]
        self.assertTrue(s["critical"])                       # the brand is OpenAI
        self.assertAlmostEqual(s["t"], 2.5, places=2)        # voice time: line start + heard time
        self.assertEqual(rep["lines"][0]["heard"], "Colour the plane.")

    def test_stored_readback_is_reused_for_the_same_vo(self):
        from st.footage.util import quick_hash
        d = self.project(title="Meet OpenAI")
        stored = {"version": self.rb.READBACK_VERSION, "vo_hash": quick_hash(d / "voice" / "vo.wav"),
                  "lines": [], "checked": 2, "suspects": [{"line": "shot-6", "word": "Open A I", "heard": "OpenI",
                                                           "keys": ["open", "openai"], "critical": False, "t": 2.5}]}
        (d / "voice" / "readback.json").write_text(json.dumps(stored), encoding="utf-8")

        def boom(*a, **k):
            raise AssertionError("the recognizer ran although readback.json belongs to this vo.wav")
        orig = self.rb.heard_words, self.rb.second_recognizer
        self.rb.heard_words, self.rb.second_recognizer = boom, (lambda lang: None)
        try:
            rep = self.rb.for_project(d)
        finally:
            self.rb.heard_words, self.rb.second_recognizer = orig
        self.assertIn("readback.json", rep["source"])
        self.assertTrue(rep["suspects"][0]["critical"])      # "OpenAI" is a name in the title
        # a timeline newer than the video is not what the video plays
        vid = d / "final.mp4"
        vid.write_bytes(b"x")
        old = time.time() - 100
        os.utime(vid, (old, old))
        self.assertIsNone(self.rb.for_project(d, vid))

    def test_qa_items(self):
        from st.qa import hearing
        from st.qa.video import Findings
        rep = {"summary": "read-back: 1 word heard differently", "suspects": [
            {"line": "shot-6", "word": "Open A I", "heard": "OpenI", "t": 26.66, "critical": False, "kind": "name",
             "lone_a": True, "clip": "voice/vo.wav"}]}
        F = Findings()
        hearing.check_readback(F, rep)
        self.assertEqual([(f["rule"], f["severity"], f["t"]) for f in F.items], [("readback", "WARN", 26.66)])
        self.assertIn('"Open A I"', F.items[0]["message"])
        self.assertIn("OpenI", F.items[0]["message"])
        self.assertIn("one word", F.items[0]["fix"])
        rep["suspects"][0]["critical"] = True
        F = Findings()
        hearing.check_readback(F, rep)              # a title/brand name heard by one recognizer only: WARN
        self.assertEqual(F.items[0]["severity"], "WARN")
        self.assertIn("a name in the title, brand or lexicon", F.items[0]["message"])
        rep["suspects"][0].update(confirmed=True, second={"by": "Whisper small.en", "heard": "OpenI"})
        F = Findings()
        hearing.check_readback(F, rep)              # a second recognizer heard it wrong too: FAIL
        self.assertEqual(F.items[0]["severity"], "FAIL")
        self.assertIn('Whisper small.en also hears "OpenI"', F.items[0]["message"])
        F = Findings()
        hearing.check_readback(F, {"skipped": "the speech recognizer is not installed (showtime setup --fetch x)",
                                   "suspects": []})
        self.assertEqual(F.items[0]["severity"], "INFO")
        self.assertIn("setup --fetch", F.items[0]["fix"])
        F = Findings()                              # installing changes nothing for a language it does not cover
        hearing.check_readback(F, {"skipped": "the local recognizer (Parakeet) does not cover language 'zh'",
                                   "suspects": []})
        self.assertEqual(F.items[0]["severity"], "INFO")
        self.assertNotIn("fix", F.items[0])
        F = Findings()
        hearing.check_readback(F, {"summary": "read-back: 7 lines heard back", "suspects": []})
        self.assertEqual((F.items, F.passed), ([], ["read-back: 7 lines heard back"]))
        self.assertIn("readback", hearing.RULES)

    def test_audio_txt_and_receipt(self):
        from st.job import receipt
        from st.qa import hearing
        rep = {"summary": "read-back: 1 word heard differently in 2 lines", "suspects": [
            {"line": "shot-6", "word": "Open A I", "heard": "OpenI", "t": 26.66, "critical": False}],
            "lines": [{"id": "shot-6", "start": 26.4, "video_start": 26.4, "script": BAD, "heard": HEARD_BAD,
                       "suspects": ["Open A I"]}]}
        txt = "\n".join(hearing.readback_text(rep))
        self.assertIn("script: Open A I / heard: OpenI", txt)
        self.assertIn("heard:  " + HEARD_BAD, txt)
        self.assertIn("not run", "\n".join(hearing.readback_text({"skipped": "no recognizer"})))
        rec = {"delivery": {"final": "final.mp4", "qa": "WARN", "qa_fail": 0, "qa_warn": 1, "readback": {
            "summary": rep["summary"], "words": [{"word": "Open A I", "heard": "OpenI", "t": 26.66}]}}}
        qa_line = [ln for ln in receipt.card_facts(rec) if ln.startswith("QA:")][0]
        self.assertEqual(qa_line, 'QA: WARN (0 fail, 1 warn) on final.mp4; read-back: "Open A I" heard as "OpenI" at 26.7s')


JSON_LINE = "Open the JSON file in Visual Studio Code, then press the Enter key twice."
JSON_PARAKEET = "Open the JSO file in Visual Studio Code, then press the Enter key twice."   # the review's l5
JSON_WHISPER = "Open the JSON file in Visual Studio Code, then press the Enter key twice."


class RespelledNameTests(Base):
    """A right read the first recognizer respells: one recognizer is not enough to FAIL qa, a person can clear it."""

    def json_project(self, ok=None, note=None):
        d = Path(tempfile.mkdtemp(prefix="st-rb-json-"))
        cfg = {"title": "JSON for teams", "duration": 10}
        if ok is not None:
            cfg["readback"] = {"ok": ok}
        if note is not None:
            cfg.setdefault("readback", {})["note"] = note
        (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        (d / "narration.md").write_text("## l5\n%s\n" % JSON_LINE, encoding="utf-8")
        tl = {"file": "vo.wav", "script": "../narration.md", "lines": [
            {"id": "l5", "text": JSON_LINE, "source_text": JSON_LINE, "lang": "en-us", "start": 1.0, "end": 5.8,
             "speech_start": 1.05, "speech_end": 5.7, "file": "lines/01-l5.wav", "audio_key": "k5"}]}
        (d / "voice").mkdir()
        (d / "voice" / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        _wav(d / "voice" / "vo.wav", 6.0)
        _wav(d / "voice" / "lines" / "01-l5.wav", 4.8)
        return d

    def run_project(self, d, second_hears=JSON_WHISPER, second=True):
        calls = []

        def fake(wav, lang, key=None, model="auto"):
            calls.append(model)
            return words(JSON_PARAKEET if model == "auto" else second_hears, 0.32)
        orig = self.rb.heard_words, self.rb.asr_ready, self.rb.second_recognizer
        self.rb.heard_words, self.rb.asr_ready = fake, (lambda lang: (True, ""))
        self.rb.second_recognizer = ((lambda lang: {"model": "small.en", "label": "Whisper small.en"}) if second
                                     else (lambda lang: None))
        self.rb._READY.clear()
        try:
            return self.rb.for_project(d), calls
        finally:
            self.rb.heard_words, self.rb.asr_ready, self.rb.second_recognizer = orig
            self.rb._READY.clear()

    def qa(self, rep):
        from st.qa import hearing
        from st.qa.video import Findings
        F = Findings()
        hearing.check_readback(F, rep)
        return F

    def test_matcher_flags_the_respelling_only(self):
        self.assertEqual(self.flagged(JSON_LINE, JSON_PARAKEET, "en-us"), [("JSON", "JSO")])
        self.assertEqual(self.flagged(JSON_LINE, JSON_WHISPER, "en-us"), [])

    def test_title_name_heard_right_by_the_second_recognizer_is_a_warn(self):
        d = self.json_project()
        rep, calls = self.run_project(d)
        self.assertEqual(calls, ["auto", "small.en"])          # the second recognizer hears only the flagged line
        s = rep["suspects"][0]
        self.assertEqual((s["word"], s["heard"], s["critical"], s["confirmed"]), ("JSON", "JSO", True, False))
        F = self.qa(rep)
        self.assertEqual([(f["rule"], f["severity"]) for f in F.items], [("readback", "WARN")])
        self.assertIn("Whisper small.en hears it as written", F.items[0]["message"])
        self.assertIn('"readback": {"ok": ["JSON"]}', F.items[0]["fix"])
        self.assertIn("listen to lines/01-l5.wav", F.items[0]["fix"])

    def test_title_name_heard_wrong_by_both_is_a_fail(self):
        rep, _ = self.run_project(self.json_project(), second_hears=JSON_PARAKEET)
        self.assertTrue(rep["suspects"][0]["confirmed"])
        F = self.qa(rep)
        self.assertEqual(F.items[0]["severity"], "FAIL")
        self.assertIn('Whisper small.en also hears "JSO"', F.items[0]["message"])

    def test_no_second_recognizer_is_a_warn(self):
        rep, calls = self.run_project(self.json_project(), second=False)
        self.assertEqual(calls, ["auto"])
        self.assertNotIn("confirmed", rep["suspects"][0])
        self.assertEqual(self.qa(rep).items[0]["severity"], "WARN")

    def test_a_noted_word_is_a_note_never_a_fail(self):
        # note vs ok vs neither: both recognizers hear "JSO", so with nothing listed it is a FAIL
        rep, _ = self.run_project(self.json_project(), second_hears=JSON_PARAKEET)
        self.assertEqual(self.qa(rep).items[0]["severity"], "FAIL")
        rep, _ = self.run_project(self.json_project(note=["json"]), second_hears=JSON_PARAKEET)
        s = rep["suspects"][0]
        self.assertTrue(s["noted"] and s["confirmed"] and s["critical"])
        self.assertFalse(self.rb.is_fail(s))
        F = self.qa(rep)
        self.assertEqual([(f["rule"], f["severity"]) for f in F.items], [("readback", "INFO")])
        self.assertIn("listed in readback.note", F.items[0]["message"])
        self.assertFalse(F.items[0].get("fix"))
        lines = "\n".join(self.rb.report_lines(rep))
        self.assertIn("NOTE", lines)
        self.assertNotIn("fix:", lines)
        self.assertNotIn("cleared", rep)
        # ok clears it altogether, and wins over note
        rep, _ = self.run_project(self.json_project(ok=["JSON"], note=["JSON"]), second_hears=JSON_PARAKEET)
        self.assertEqual(rep["suspects"], [])
        self.assertEqual([s["word"] for s in rep["cleared"]], ["JSON"])

    def test_note_matches_whole_words_in_a_phrase(self):
        rep = {"lines": [{"id": "l1"}], "checked": 3, "suspects": [
            {"word": "Qwen Image", "heard": "QN image", "kind": "name", "line": "l1", "t": 1.0, "critical": True, "confirmed": True},
            {"word": "Quenched", "heard": "x", "kind": "name", "line": "l1", "t": 2.0, "critical": True, "confirmed": True},
            {"word": "Qwen Edit", "heard": "QN edict", "kind": "name", "line": "l1", "t": 3.0, "critical": True, "confirmed": True}]}
        out = self.rb.apply_cleared(rep, [], ["Qwen"])
        self.assertEqual([(s["word"], bool(s.get("noted")), self.rb.is_fail(s)) for s in out["suspects"]],
                         [("Qwen Image", True, False), ("Quenched", False, True), ("Qwen Edit", False, True)])
        self.assertIn("(1 noted)", out["summary"])
        self.assertIn("by the project", self.rb.tag(out["suspects"][0]))

    def test_a_word_cleared_after_listening(self):
        rep, _ = self.run_project(self.json_project(ok=["json"]), second_hears=JSON_PARAKEET)
        self.assertEqual(rep["suspects"], [])
        self.assertEqual([s["word"] for s in rep["cleared"]], ["JSON"])
        self.assertIn('cleared after listening (showtime.json readback.ok): "JSON"', rep["summary"])
        F = self.qa(rep)
        self.assertEqual(F.items, [])
        self.assertIn("cleared after listening", F.passed[0])
        from st.qa import hearing
        self.assertIn("cleared after listening", "\n".join(hearing.readback_text(rep)))

    def test_stored_readback_gets_the_second_opinion_and_the_clearance(self):
        from st.footage.util import quick_hash
        d = self.json_project()
        stored = {"version": self.rb.READBACK_VERSION, "vo_hash": quick_hash(d / "voice" / "vo.wav"), "checked": 4,
                  "lines": [{"id": "l5", "start": 1.0, "script": JSON_LINE, "heard": JSON_PARAKEET,
                             "suspects": ["JSON"]}],
                  "suspects": [{"line": "l5", "word": "JSON", "heard": "JSO", "keys": ["json"], "critical": False,
                                "kind": "lexicon", "t": 1.64, "clip": "lines/01-l5.wav"}]}
        (d / "voice" / "readback.json").write_text(json.dumps(stored), encoding="utf-8")
        rep, calls = self.run_project(d)
        self.assertEqual(calls, ["small.en"])                  # only the second opinion: the first is reused
        self.assertEqual(rep["suspects"][0]["confirmed"], False)
        self.assertEqual(self.qa(rep).items[0]["severity"], "WARN")
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        cfg["readback"] = {"ok": ["JSON"]}                     # cleared after voice script ran: qa honours it
        (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        rep, _ = self.run_project(d)
        self.assertEqual((rep["suspects"], rep["lines"][0]["suspects"]), ([], []))
        self.assertEqual(self.qa(rep).items, [])

    def test_voice_script_lines_and_cleared_words(self):
        lines = [{"id": "l5", "text": JSON_LINE, "lang": "en-us", "start": 27.237, "heard": words(JSON_PARAKEET)}]
        rep = self.rb.check_lines(lines, self.lex, {"json"},
                                  second={"label": "Whisper small.en", "hear": lambda ln: words(JSON_WHISPER)})
        out = self.rb.report_lines(rep)
        self.assertIn('WARN', out[1])
        self.assertIn("[a name in the title, brand or lexicon; Whisper small.en hears it as written]", out[1])
        d = Path(tempfile.mkdtemp(prefix="st-rb-ok-"))
        (d / "showtime.json").write_text(json.dumps({"readback": {"ok": ["JSON", 3, ""]}}), encoding="utf-8")
        self.assertEqual(self.rb.cleared_words(d), ["JSON"])
        self.rb.apply_cleared(rep, self.rb.cleared_words(d))
        self.assertEqual(rep["suspects"], [])
        self.assertIn("cleared after listening", self.rb.report_lines(rep)[0])

    def test_cache_key_names_the_recognizer(self):
        from st.footage import transcribe as T
        cache = Path(tempfile.mkdtemp(prefix="st-rb-cache-"))
        ran = []

        def fake_transcribe(wav, model="auto", **kw):
            ran.append(model)
            return {"model": model, "words": [{"type": "word", "text": "hi", "start": 0.0, "end": 0.2}]}, None
        orig = self.rb._cache_dir, T.transcribe
        self.rb._cache_dir, T.transcribe = (lambda: cache), fake_transcribe
        old_env = os.environ.pop("SHOWTIME_ASR_MODEL", None)
        try:
            wav = cache / "x.wav"
            wav.write_bytes(b"0")
            self.rb.heard_words(wav, "en", "k1")
            self.rb.heard_words(wav, "en", "k1")               # cached
            os.environ["SHOWTIME_ASR_MODEL"] = "turbo"         # another recognizer: heard again
            self.rb.heard_words(wav, "en", "k1")
            del os.environ["SHOWTIME_ASR_MODEL"]
            self.rb.heard_words(wav, "en", "k1", model="small.en")
        finally:
            self.rb._cache_dir, T.transcribe = orig
            os.environ.pop("SHOWTIME_ASR_MODEL", None)
            if old_env is not None:
                os.environ["SHOWTIME_ASR_MODEL"] = old_env
        self.assertEqual(ran, ["auto", "auto", "small.en"])
        names = sorted(p.name for p in cache.glob("k1-*.json"))
        self.assertEqual(names, ["k1-en-large-v3-turbo.json", "k1-en-sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.json",
                                 "k1-en-small.en.json"])


class VoiceScriptTests(Base):
    def test_heard_back_lines(self):
        rep = {"summary": "read-back: 1 word heard differently in 7 lines (\"Open A I\" as \"OpenI\")", "suspects": [
            {"line": "shot-6", "word": "Open A I", "heard": "OpenI", "t": 26.66, "kind": "name", "lone_a": True,
             "clip": "lines/05-shot-6.wav"}]}
        out = self.rb.report_lines(rep)
        self.assertEqual(out[0], rep["summary"])
        self.assertIn('WARN  26.66s  shot-6: "Open A I" heard as "OpenI"', out[1])
        self.assertTrue(out[2].strip().startswith("fix: "))
        self.assertIn("write the name as one word (OpenAI)", out[2])
        s = dict(rep["suspects"][0], word="Qwen", heard="Kuen", lone_a=False)
        self.assertIn("lexicon.json", self.rb.fix_for(s, "lines/02-x.wav"))
        self.assertIn("voice ipa", self.rb.fix_for(s))
        self.assertEqual(self.rb.report_lines({"skipped": "no recognizer"}), ["read-back skipped: no recognizer"])

    def test_cli_has_the_switch(self):
        from st.launcher import build_env, showtime_home
        cp = subprocess.run([sys.executable, str(SKILL / "lib" / "st" / "launcher.py"), "voice", "script", "--help"],
                            env=build_env(showtime_home()), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=120)
        self.assertIn("--no-readback", cp.stdout)
        self.assertIn("readback.json", cp.stdout)

    def test_voice_script_end_to_end(self):
        if FAST:
            self.skipTest("--fast: no speech synthesis")
        ok, why = self.rb.asr_ready("en")
        if not ok:
            self.skipTest(why)
        from st.voice import tts
        try:
            tts.get_engine("kokoro").available()[0] or self.skipTest("Kokoro is not installed")
        except Exception as e:  # noqa: BLE001
            self.skipTest("Kokoro: %s" % e)
        from st.launcher import build_env, showtime_home
        d = Path(tempfile.mkdtemp(prefix="st-rb-vs-"))
        line = "its internal model showed five never work, for any colouring, with a Lean proof a computer can check."
        (d / "narration.md").write_text("---\nvoice: bm_george\n---\n## bad\nNow Open A I says %s\n\n## good\nNow OpenAI "
                                        "says %s\n" % (line, line), encoding="utf-8")
        env = dict(build_env(showtime_home()), SHOWTIME_READBACK="1")
        cp = subprocess.run([sys.executable, str(SKILL / "lib" / "st" / "launcher.py"), "voice", "script",
                             str(d / "narration.md"), "-o", str(d / "voice"), "--json"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                            timeout=900)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        tl = json.loads(cp.stdout)
        sus = tl["readback"]["suspects"]
        self.assertEqual([(s["line"], s["word"]) for s in sus], [("bad", "Open A I")], cp.stderr[-2000:])
        self.assertIn("read-back: 1 word heard differently", cp.stderr)
        rb = json.loads((d / "voice" / "readback.json").read_text(encoding="utf-8"))
        self.assertEqual([ln["id"] for ln in rb["lines"]], ["bad", "good"])
        self.assertIn("OpenAI", rb["lines"][1]["heard"])
        self.assertTrue(all(ln.get("audio_key") for ln in tl["lines"]))


class LexiconTests(Base):
    def test_project_lexicon_overrides_the_built_in_one(self):
        from st.voice import lexicon as lm
        d = Path(tempfile.mkdtemp(prefix="st-rb-lex-"))
        builtin = lm.load()
        self.assertTrue(builtin.ipa("LaTeX", "en"), "LaTeX is in the starter list")
        (d / "lexicon.json").write_text(json.dumps({"LaTeX": {"say": "lah tek"}, "Acme": {"say": "ak mee"}}),
                                        encoding="utf-8")
        lex = lm.load(project_dir=d)
        self.assertEqual(lex.say("LaTeX", "en"), "lah tek")
        self.assertIsNone(lex.ipa("LaTeX", "en"))
        names = self.rb.critical_names(d, lex)
        self.assertIn("latex", names)                  # the project's own entries are its names
        self.assertIn("acme", names)
        self.assertNotIn("kubectl", names)             # the built-in list is not
        # a lexicon word is checked even at a sentence start
        r = self.rb.compare_line("Acme ships today.", words("Akme ships today."), "en-us", lex)
        self.assertEqual(r["checked"], 1)

    def test_starter_entries(self):
        from st.voice import lexicon as lm
        data = json.loads(lm.BUILTIN.read_text(encoding="utf-8"))
        for w, e in data.items():
            if w.startswith("_"):
                continue
            self.assertTrue(isinstance(e, (str, dict)) and (isinstance(e, str) or {"ipa", "say"} & set(e)), w)


class ClearedPhraseTests(unittest.TestCase):
    """A cleared name also clears the name as whole words inside a longer phrase, but only when the phrase's other
    words were heard as written (issue #46)."""

    def rep(self, *items):
        return {"lines": [{"id": "l1"}], "checked": len(items), "suspects": [
            dict({"word": w, "heard": h, "kind": "name", "line": "l1", "t": float(i)}, **(x[2] if len(x) > 2 else {}))
            for i, x in enumerate(items) for w, h in [x[:2]]]}

    def test_a_name_clears_the_phrases_that_contain_it(self):
        from st.voice import readback as rb
        out = rb.apply_cleared(self.rep(("Qwen", "QN"), ("Qwen Image", "QN image"), ("the Qwen Image Edit", "the QN image edit"),
                                        ("Quenched", "x")), ["Qwen"])
        self.assertEqual([s["word"] for s in out["cleared"]], ["Qwen", "Qwen Image", "the Qwen Image Edit"])
        self.assertEqual([s["word"] for s in out["suspects"]], ["Quenched"], "only whole words clear, not pieces of a word")

    def test_words_nobody_listened_to_are_not_cleared(self):
        from st.voice import readback as rb
        out = rb.apply_cleared(self.rep(("Hugging Face Hub", "hugging face hob"), ("GPT 4o", "GPT for oh"),
                                        ("Open A I", "open eye", {"lone_a": True}), ("Hugging Face Hub", "hugging face hub")),
                               ["Hugging Face", "GPT", "AI", "I"])
        self.assertEqual([(s["word"], s["heard"]) for s in out["cleared"]], [("Hugging Face Hub", "hugging face hub")])
        self.assertEqual([s["word"] for s in out["suspects"]], ["Hugging Face Hub", "GPT 4o", "Open A I"])

    def test_a_phrase_and_a_respelling_still_clear(self):
        from st.voice import readback as rb
        out = rb.apply_cleared(self.rep(("Hugging Face", "hugging faced"), ("Open A I", "open eye"), ("Face", "x")),
                               ["Hugging Face", "OpenAI"])
        self.assertEqual([s["word"] for s in out["cleared"]], ["Hugging Face", "Open A I"])
        self.assertEqual([s["word"] for s in out["suspects"]], ["Face"])

    def test_accents_match_inside_a_phrase(self):
        from st.voice import readback as rb
        out = rb.apply_cleared(self.rep(("Caf\u00e9 Image", "cafe image")), ["Cafe"])
        self.assertEqual([s["word"] for s in out["cleared"]], ["Caf\u00e9 Image"])

    def test_a_stale_noted_flag_is_dropped_once_cleared(self):
        from st.voice import readback as rb
        out = rb.apply_cleared(self.rep(("Qwen", "QN")), [], ["Qwen"])
        self.assertTrue(out["suspects"][0]["noted"])
        out = rb.apply_cleared(out, ["Qwen"], ["Qwen"])
        self.assertNotIn("noted", out["cleared"][0])


class NotedWordsShowEverywhere(unittest.TestCase):
    """readback.note: a NOTE in the overflow line, the receipt and the summary, never a FAIL or WARN (issue #46)."""

    def sus(self, n, noted=True):
        return [{"word": "Qwen%d" % i, "heard": "QN", "kind": "name", "line": "l1", "t": float(i), "critical": True,
                 "confirmed": True, "noted": noted} for i in range(n)]

    def test_overflow_counts_only_the_words_not_noted(self):
        from st.qa import hearing
        from st.qa.video import Findings
        sus = self.sus(10)
        F = Findings()
        hearing.check_readback(F, {"lines": [{"id": "l1"}], "checked": 10, "suspects": sus, "summary": "s"})
        self.assertEqual({f["severity"] for f in F.items}, {"INFO"})
        sus[9]["noted"] = False
        F = Findings()
        hearing.check_readback(F, {"lines": [{"id": "l1"}], "checked": 10, "suspects": sus, "summary": "s"})
        self.assertEqual(F.items[-1]["severity"], "WARN", "an un-noted word past the 8th still warns")

    def test_the_receipt_marks_a_noted_word(self):
        from st.job import receipt
        rec = {"delivery": {"final": "final.mp4", "qa": "WARN", "readback": {"summary": "s", "words": [
            {"word": "Qwen", "heard": "QN", "t": 1.0, "noted": True}, {"word": "Hub", "heard": "hob", "t": 2.0}]}}}
        qa = [l for l in receipt.card_facts(rec) if l.startswith("QA:")][0]
        self.assertIn('"Qwen" heard as "QN" at 1.0s (noted: listed in readback.note)', qa)
        self.assertIn('"Hub" heard as "hob" at 2.0s', qa)
        self.assertNotIn('"hob" at 2.0s (noted', qa)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped),
                                                      time.time() - t0))
    sys.exit(0 if res.wasSuccessful() else 1)
