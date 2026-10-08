#!/usr/bin/env python3
"""The read-back (st.voice.readback): the voice-over heard again and compared with the script.

- the matcher: "OpenAI", "open AI" and "Open A I" are the same name; "OpenI" and "open eye" are not; digits
  and number words, other spellings of one sound and case pass; a short name that changes a vowel fails
- what matters in a line (names, acronyms, numbers, lexicon words), a lone "A" told as the article
- the case that shipped (7 Oct): the maths explainer's line "Now Open A I says ..." (bm_george); the fixture
  is a 3 s cut of that render's own voice-over, in which the recognizer hears "open an eye" (when installed)
- qa: the `readback` item (WARN, FAIL for a title/brand/lexicon name, INFO when it cannot run),
  voice/readback.json reused for the same vo.wav, audio.txt's table, the receipt's QA line
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

        def fake(wav, lang, key=None):
            calls.append(Path(wav).name)
            return heard
        orig = self.rb.heard_words
        orig_ready = self.rb.asr_ready
        self.rb.heard_words, self.rb.asr_ready = fake, (lambda lang: (True, ""))
        self.rb._READY.clear()
        try:
            rep = self.rb.for_project(d)
        finally:
            self.rb.heard_words, self.rb.asr_ready = orig, orig_ready
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
        orig = self.rb.heard_words
        self.rb.heard_words = boom
        try:
            rep = self.rb.for_project(d)
        finally:
            self.rb.heard_words = orig
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
        hearing.check_readback(F, rep)
        self.assertEqual(F.items[0]["severity"], "FAIL")
        F = Findings()
        hearing.check_readback(F, {"skipped": "the speech recognizer is not installed", "suspects": []})
        self.assertEqual(F.items[0]["severity"], "INFO")
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


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped),
                                                      time.time() - t0))
    sys.exit(0 if res.wasSuccessful() else 1)
