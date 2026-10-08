#!/usr/bin/env python3
"""Transcription pipeline unit tests (seconds, no network, no ASR model needed).

- model choice: auto -> Parakeet v3 for English/Spanish/unknown, Whisper outside its 25 languages;
  English-only models refuse other languages with a fix
- lazy model fetch (asr_models.ensure): manifest entries carry url/size/sha256; a seeded archive is
  verified and extracted into place; offline -> a clear error with the setup command
- token merge: punctuation pieces never stretch a word into the next pause
- filler gap scan (fillers.py) on synthetic audio with a fake decoder: an unlabelled voiced gap that
  re-decodes as "uh" becomes a filler word; one that re-decodes as a real word is never added; the
  acoustic check scores a held vowel above noise
- cut plan: fillers flagged by the scan are cut, the pause left is capped (0.2 s), discourse fillers
  ("o sea", "este") only on request, cut edges snap to the quietest point within 40 ms
- EDL audio crossfade bookkeeping and tail mixing keep the program length
- speech under music: background estimate gates separation; STFT/iSTFT of the separator round-trips;
  the dry narration stem of a showtime render is found (motion render and edit render reports); the
  mixer writes that stem when music plays under a voice
- CrisperWhisper opt-in: refused on Intel Macs, needs an explicit licence acceptance (remembered)
- first word: the first VAD chunk starts at 0 (a late onset keeps the word before it); language_source
  says given/model/detected/guessed/default; Parakeet v3's guess works on merged tokens. With Parakeet v3,
  the Silero VAD and Kokoro installed, real speech that starts at 0.05 s keeps its first word (else skipped)

usage: python tests/test_asr.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

import numpy as np  # noqa: E402

from st.common import ShowtimeError  # noqa: E402
from st.footage import asr_models, cuts, fillers as F, transcribe as T, util as U  # noqa: E402

SR = 16000


def tone(dur, f0=140.0, amp=0.3, harmonics=6):
    t = np.arange(int(dur * SR)) / SR
    y = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, harmonics + 1))
    return (amp * y / 2.0 * np.hanning(len(t))).astype(np.float32)


def word_like(dur, seed=0):
    """A 'word': pitched segments with changing pitch and noise bursts (consonants)."""
    rng = np.random.default_rng(seed)
    parts = []
    n = max(2, int(dur / 0.08))
    for k in range(n):
        if k % 2:
            parts.append((0.1 * rng.standard_normal(int(0.08 * SR))).astype(np.float32))
        else:
            parts.append(tone(0.08, 110 + 60 * rng.random(), 0.3))
    return np.concatenate(parts)[: int(dur * SR)]


def silence(d):
    return np.zeros(int(d * SR), np.float32) + (1e-4 * np.random.default_rng(1).standard_normal(int(d * SR))).astype(np.float32)


class Home:
    """A throwaway SHOWTIME_HOME."""

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="st-asr-home-"))
        self.old = os.environ.get("SHOWTIME_HOME")
        os.environ["SHOWTIME_HOME"] = str(self.dir)
        return self.dir

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop("SHOWTIME_HOME", None)
        else:
            os.environ["SHOWTIME_HOME"] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)


class ModelChoiceTest(unittest.TestCase):
    def test_auto_is_parakeet_v3(self):
        with mock.patch.dict(os.environ, {"SHOWTIME_ASR_MODEL": ""}):
            for lang in (None, "en", "es", "de"):
                eng, name = T.choose_model("auto", lang)
                self.assertEqual(eng, "parakeet", lang)
                self.assertTrue(name.endswith("v3-int8"), name)

    def test_auto_outside_parakeet_languages_uses_whisper(self):
        with mock.patch.object(T, "_installed", return_value=False):
            self.assertEqual(T.choose_model("auto", "ja"), ("whisper", "small"))
        with mock.patch.object(T, "_installed", side_effect=lambda e, n: n == "large-v3-turbo"):
            self.assertEqual(T.choose_model("auto", "ja"), ("whisper", "large-v3-turbo"))

    def test_explicit_models(self):
        self.assertEqual(T.choose_model("parakeet-v2", "en")[1], "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8")
        with self.assertRaises(ShowtimeError) as cm:
            T.choose_model("parakeet-v2", "es")
        self.assertIn("parakeet-v3", cm.exception.hint or "")
        self.assertEqual(T.choose_model("small.en", "es"), ("whisper", "small"))   # .en falls back, with a warning
        self.assertEqual(T.choose_model("crisper", None), ("crisper", "small"))
        with self.assertRaises(ShowtimeError):
            T.choose_model("nonsense", None)

    def test_setup_extras_exist(self):
        # the fix a missing model prints (`showtime setup --with <extra>`) names an extra setup knows
        man = json.loads((SKILL / "setup" / "manifest.json").read_text(encoding="utf-8"))
        for name, extra in T.SETUP_EXTRA.items():
            self.assertIn(extra, man["extras"], name)
        lazy = {it["id"] for it in man["items"] if it.get("tier") == "lazy"}
        for name, key in T.PARAKEET_ITEMS.items():
            item = asr_models.ITEMS[key]["item"]
            self.assertTrue(item in lazy or any(it["id"] == item and it.get("extra") in man["extras"] for it in man["items"]), name)

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"SHOWTIME_ASR_MODEL": "turbo"}):
            self.assertEqual(T.choose_model("auto", None), ("whisper", "large-v3-turbo"))


class FirstWordTest(unittest.TestCase):
    """Words before the first speech onset the VAD reports are still decoded; the language says where it came from."""

    def test_first_chunk_starts_at_zero(self):
        audio = silence(40.0)
        # the VAD heard the speech late (onset 0.8 s): the soft first word before it stays in the first chunk
        ch = T._speech_chunks(audio, SR, max_len=5.0, spans=[(0.8, 3.0), (6.0, 9.0), (12.0, 14.0), (30.0, 33.0)])
        self.assertEqual(ch[0][0], 0.0)
        self.assertAlmostEqual(ch[0][1], 3.3)
        # a long lead-in adds only 1.5 s before the (padded) onset, not the whole intro
        ch = T._speech_chunks(audio, SR, max_len=5.0, spans=[(20.0, 24.0), (30.0, 33.0)])
        self.assertAlmostEqual(ch[0][0], 18.2)
        self.assertAlmostEqual(ch[0][1], 24.3)
        self.assertAlmostEqual(ch[1][0], 29.7)

    def test_music_intro_is_not_decoded(self):
        """A 25 s music intro (tones and noise, which have energy) then speech: the VAD reports speech from
        25 s, and a recogniser that 'hears' words in anything loud must get no intro beyond the 1.5 s lead."""
        rng = np.random.default_rng(3)
        intro = np.concatenate([tone(0.5, 220.0 * (1 + (k % 5) / 4.0), 0.4) + (0.05 * rng.standard_normal(int(0.5 * SR))).astype(np.float32)
                                for k in range(50)])
        speech = np.concatenate([np.concatenate([word_like(0.4, k), silence(0.25)]) for k in range(38)])
        audio = np.concatenate([intro, speech]).astype(np.float32)
        onset = len(intro) / SR
        spans = [(onset + 0.2, onset + 8.0), (onset + 9.0, onset + 16.0), (onset + 17.0, onset + 24.0)]

        class Stream:
            def accept_waveform(self, sr, x):
                self.x = x

        class Rec:      # 'hears' a word in every loud 0.5 s, music or not
            def create_stream(self):
                return Stream()

            def decode_streams(self, streams):
                for st in streams:
                    n = int(0.5 * SR)
                    ts = [i / SR for i in range(0, len(st.x) - n + 1, n) if float(np.sqrt(np.mean(st.x[i:i + n] ** 2))) > 0.02]
                    st.result = type("R", (), {"tokens": ["▁la"] * len(ts), "timestamps": ts, "durations": [0.3] * len(ts)})()
        with mock.patch.object(T, "_parakeet_model", return_value=Rec()), mock.patch.object(T, "_progress"):
            toks, meta = T._run_parakeet(audio, SR, "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", 1, spans=spans)
        self.assertTrue(toks, "the fake recogniser heard the speech")
        early = [t["start"] for t in toks if t["start"] < onset - 0.3 - T.FIRST_LEAD - 0.01]
        self.assertEqual(early, [], "words decoded inside the music intro")

    def test_language_source(self):
        v3, v2 = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
        self.assertEqual(T.language_source("parakeet", v3, "es", {}), "given")
        self.assertEqual(T.language_source("parakeet", v2, None, {"language": "en"}), "model")
        self.assertEqual(T.language_source("whisper", "small.en", None, {"language": "en"}), "model")
        self.assertEqual(T.language_source("whisper", "large-v3-turbo", None, {"language": "de"}), "detected")
        self.assertEqual(T.language_source("parakeet", v3, None, {"language": None}), "default")
        # Parakeet v3's guess reads merged tokens, which have no type yet (it always said None, so "en")
        es = [{"text": w} for w in "y entonces el perro de la casa es para los niños que se van".split()]
        self.assertEqual(T._guess_language(es), "es")
        self.assertEqual(T._guess_language([{"text": w} for w in "so this is a test of the thing".split()]), "en")

    def test_speech_at_50ms_keeps_its_first_word(self):
        """Real speech (Kokoro) starting 0.05 s into the file, long enough to be cut into VAD chunks, through
        Parakeet v3: the first word is in the transcript, and the language is reported as guessed."""
        sherpa = Path(os.environ.get("SHOWTIME_HOME") or Path.home() / ".showtime") / "models" / "sherpa"
        if not (sherpa / "silero_vad_v5.onnx").is_file() or not (sherpa / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8").is_dir():
            self.skipTest("Parakeet v3 and the Silero VAD are not installed here")
        try:
            from st.voice import tts
            tmp = Path(tempfile.mkdtemp(prefix="st-asr-first-"))
            self.addCleanup(shutil.rmtree, tmp, True)
            tts.synthesize("Okay. So this is a quick test of the first word.", voice="am_michael").save(tmp / "p.wav")
        except Exception as e:  # noqa: BLE001
            self.skipTest("no Kokoro voice here (%s)" % e)
        import soundfile as sf
        x, sr = U.load_audio(tmp / "p.wav", sr=SR)
        db = U.frame_db(x, sr, 0.01)
        onset = int(np.argmax(db > U.voice_threshold(db)[0]))
        x = x[max(0, onset * 160 - 800):]          # the voice starts at 0.05 s
        full = np.concatenate([x, np.zeros(int(2.5 * SR), np.float32)] * 6 + [x])
        sf.write(str(tmp / "first.wav"), full, SR)
        with mock.patch.dict(os.environ, {"SHOWTIME_ASR_CHUNK": "5"}):
            doc, _ = T.transcribe(tmp / "first.wav", model="parakeet-v3", events="off", force=True,
                                  out_path=tmp / "first.json", separate="off", gap_scan=False, use_stem=False)
        words = [w for w in doc["words"] if w["type"] == "word"]
        self.assertTrue(words, "no words")
        self.assertEqual(U.bare(words[0]["text"]), "okay", [w["text"] for w in words[:4]])
        self.assertLess(words[0]["start"], 0.3)
        self.assertEqual(doc["language"], "en")
        self.assertEqual(doc["language_source"], "guessed")


class LazyFetchTest(unittest.TestCase):
    def test_manifest_entries(self):
        for name, meta in asr_models.ITEMS.items():
            it = asr_models.manifest_item(meta["item"])
            for f in it["files"]:
                self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$", name)
                self.assertGreater(f["size"], 1000, name)
                self.assertTrue(f["url"].startswith("https://"), name)
            self.assertTrue(it.get("license"), name)
        man = json.loads((SKILL / "setup" / "manifest.json").read_text(encoding="utf-8"))
        items = {it["id"]: it for it in man["items"]}
        for iid in ("parakeet-tdt-0.6b-v3-int8", "uvr-mdx-net-voc-ft"):
            self.assertEqual(items[iid].get("tier"), "lazy", iid)      # first use; `setup --full` installs it too
            self.assertTrue(items[iid].get("when") and items[iid].get("for"), iid)
        from st import lazy
        self.assertEqual(lazy.asr_components("parakeet", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"),
                         ("parakeet-tdt-0.6b-v3-int8",))
        self.assertIn("parakeet", man["full_extras"])

    def test_offline_error_names_the_fix(self):
        with Home(), mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1"}):
            self.assertFalse(asr_models.present("parakeet-v3"))
            with self.assertRaises(ShowtimeError) as cm:
                asr_models.ensure("parakeet-v3")
            self.assertIn("--fetch parakeet-tdt-0.6b-v3-int8", cm.exception.hint)
            self.assertIn("setup --full", cm.exception.hint)
            self.assertEqual(cm.exception.code, 3)

    def test_seeded_archive_is_verified_and_extracted(self):
        with Home() as h:
            seed = h / "seed"
            seed.mkdir()
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
                # (seed folders index files of 1 KB and more)
                for name, data in (("pk/encoder.int8.onnx", os.urandom(4096)), ("pk/tokens.txt", b"a 0\n"),
                                   ("pk/test_wavs/0.wav", b"RIFF")):
                    ti = tarfile.TarInfo(name)
                    ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
            arc = seed / "pk.tar.bz2"
            arc.write_bytes(buf.getvalue())
            item = {"id": "fake-pk", "extra": "parakeet-v3", "license": "test",
                    "files": [{"url": "https://example.invalid/pk.tar.bz2", "sha256": hashlib.sha256(arc.read_bytes()).hexdigest(),
                               "size": arc.stat().st_size, "archive": "tar.bz2", "dest": "models/sherpa",
                               "creates": "models/sherpa/pk", "include": ["*.onnx", "*tokens.txt"]}]}
            meta = {"item": "fake-pk", "path": "models/sherpa/pk", "check": "encoder.int8.onnx", "label": "fake"}
            from st import lazy
            with mock.patch.dict(asr_models.ITEMS, {"fake": meta}), \
                    mock.patch.object(lazy, "manifest", return_value={"items": [item]}), \
                    mock.patch.object(asr_models, "manifest_item", return_value=item), \
                    mock.patch.dict(os.environ, {"SHOWTIME_SEED_DIRS": str(seed), "SHOWTIME_OFFLINE": ""}):
                p = asr_models.ensure("fake")
            self.assertTrue((p / "encoder.int8.onnx").is_file())
            self.assertTrue((p / "tokens.txt").is_file())
            self.assertFalse((p / "test_wavs").exists(), "test clips are not extracted")
            self.assertEqual(p, h / "models" / "sherpa" / "pk")


class MergeTest(unittest.TestCase):
    def test_punctuation_does_not_stretch_words(self):
        toks = [{"raw": " was", "start": 24.64, "end": 24.96, "seg": 0},
                {"raw": ".", "start": 29.52, "end": 29.6, "seg": 0},
                {"raw": " We", "start": 30.08, "end": 30.3, "seg": 0}]
        w = T.merge_tokens(toks, "en", subword=True)
        self.assertEqual([x["text"] for x in w], ["was.", "We"])
        self.assertAlmostEqual(w[0]["end"], 24.96)

    def test_filler_pieces_merge(self):
        toks = [{"raw": " U", "start": 1.0, "end": 1.08, "seg": 0}, {"raw": "h", "start": 1.08, "end": 1.2, "seg": 0}]
        w = T.merge_tokens(toks, "en", subword=True)
        self.assertEqual(w[0]["text"], "Uh")
        self.assertTrue(U.is_filler(w[0]["text"], "en"))

    def test_backchannels_are_words(self):
        for t in ("mm-hmm", "Mmhmm,", "mhm", "uh-huh"):
            self.assertFalse(U.is_filler(t, "en"), t)
        for t in ("mm", "Hmm.", "uh", "Um,", "erm"):
            self.assertTrue(U.is_filler(t, "en"), t)
        self.assertTrue(U.is_hesitation("uh") and U.is_hesitation("Um") and U.is_hesitation("eh"))
        self.assertFalse(U.is_hesitation("mm") or U.is_hesitation("hmm"), "the gap scan adds only uh/um-type sounds")

    def test_spanish_fillers(self):
        self.assertTrue(U.is_filler("eh", "es"))
        self.assertTrue(U.is_filler("Em,", "es"))
        self.assertFalse(U.is_filler("este", "es"), "'este' is a real word by default")
        self.assertIn("o sea", U.DISCOURSE_FILLERS["es-discourse"])


def scene():
    """word(0.3-0.8) gap(0.8-1.2) HELD VOWEL(1.2-1.6) gap(1.6-2.0) word(2.0-2.5) gap word2(3.0-3.5) BURST(3.8-4.1) word(4.4-4.9)."""
    parts = [silence(0.3), word_like(0.5, 1), silence(0.4), tone(0.4, 120, 0.25), silence(0.4), word_like(0.5, 2),
             silence(0.5), word_like(0.5, 3), silence(0.3), word_like(0.3, 4), silence(0.3), word_like(0.5, 5),
             silence(0.4)]
    x = np.concatenate(parts)
    words = [{"text": "something", "start": 0.3, "end": 0.8, "type": "word"},
             {"text": "tomorrow", "start": 2.0, "end": 2.5, "type": "word"},
             {"text": "everyone", "start": 3.0, "end": 3.5, "type": "word"},
             {"text": "building", "start": 4.4, "end": 4.9, "type": "word"}]
    return x, words


class GapScanTest(unittest.TestCase):
    def test_candidates(self):
        x, words = scene()
        c = F.gap_candidates(words, x, SR)
        self.assertEqual(len(c), 2, c)
        self.assertAlmostEqual(c[0][0], 1.2, delta=0.12)
        self.assertAlmostEqual(c[1][0], 3.8, delta=0.12)
        # too short / too long regions are ignored
        self.assertEqual(F.gap_candidates(words, x, SR, min_len=0.5), [])

    def test_acoustic_prefers_held_vowel(self):
        x, _ = scene()
        rng = np.random.default_rng(0)
        noise = (0.2 * rng.standard_normal(int(0.4 * SR))).astype(np.float32)
        vowel = F.acoustic(x, SR, 1.25, 1.55)
        hiss = F.acoustic(np.concatenate([silence(0.1), noise, silence(0.1)]), SR, 0.1, 0.5)
        self.assertGreater(vowel["voiced"], 0.6)
        self.assertGreater(vowel["score"], hiss["score"])
        self.assertLess(hiss["voiced"], 0.3)

    def fake_decoder(self, table):
        """decode(arrays) -> pieces, by window length -> the words given for the region it contains."""
        calls = []

        def decode(arrays):
            out = []
            for a in arrays:
                calls.append(len(a) / SR)
                out.append(table.pop(0) if table else [])
            return out
        return decode, calls

    def test_scan_adds_decoded_filler_and_never_a_real_word(self):
        x, words = scene()
        # window 1 = [0.9, 1.9]: "uh" at 0.35 s in; window 2 = [3.5, 4.4]: the real word "really"
        decode, calls = self.fake_decoder([[("▁uh", 0.33, 0.2)], [("▁re", 0.3, 0.08), ("ally", 0.38, 0.16)]])
        st = F.scan(words, x, SR, "en", decode)
        self.assertEqual(st["candidates"], 2)
        self.assertEqual(st["added"], 1)
        self.assertEqual(st["missed_words"], 1)
        added = [w for w in words if w.get("detected") == "gap-scan"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["text"], "uh")
        self.assertTrue(added[0]["filler"])
        self.assertTrue(1.1 <= added[0]["start"] < added[0]["end"] <= 1.65, added[0])
        self.assertEqual([w["text"] for w in words], ["something", "uh", "tomorrow", "everyone", "building"])
        self.assertEqual(len(calls), 2)

    def test_filler_folded_into_an_odd_word(self):
        # "orbit. Uh we need" heard as "orbit." + "Une" (0.6 s for three letters)
        x = np.concatenate([silence(0.3), word_like(0.5, 1), silence(0.2), tone(0.3, 120, 0.25), word_like(0.3, 2),
                            silence(0.4)])
        words = [{"text": "orbit.", "start": 0.3, "end": 0.8, "type": "word"},
                 {"text": "Une", "start": 0.95, "end": 1.6, "type": "word"}]
        # window = [0.65, 1.9]: "Uh" at 0.35 s in (1.0), "we" at 0.66 (1.31), "need" at 0.8 (1.45)
        decode, _ = self.fake_decoder([[("\u2581U", 0.35, 0.08), ("h", 0.43, 0.08), ("\u2581we", 0.66, 0.08),
                                        ("\u2581need", 0.8, 0.16)]])
        st = F.scan(words, x, SR, "en", decode)
        self.assertEqual(st["elongated"], 1)
        self.assertEqual(st["added"], 1)
        uh = [w for w in words if w.get("filler")][0]
        self.assertEqual(uh["detected"], "long-word")
        self.assertLessEqual(uh["end"], 1.31 - 0.05)          # stops before the decoded "we"
        une = [w for w in words if w["text"] == "Une"][0]
        self.assertAlmostEqual(une["start"], uh["end"], places=3)   # the odd word now starts after the filler

    def test_scan_ignores_a_filler_the_transcript_already_has(self):
        x, words = scene()
        words.insert(1, {"text": "um", "start": 1.25, "end": 1.3, "type": "word"})   # a timing too short to cover it
        decode, _ = self.fake_decoder([[("▁um", 0.36, 0.2)], []])
        st = F.scan(words, x, SR, "en", decode)
        self.assertEqual(st["added"], 0)

    def test_asr_fillers_get_a_second_opinion(self):
        x, words = scene()
        words.insert(1, {"text": "uh", "start": 1.2, "end": 1.6, "type": "word"})
        words.insert(3, {"text": "um", "start": 2.6, "end": 2.9, "type": "word"})
        calls = []

        def decode(arrays):
            calls.append(len(arrays))
            if len(calls) == 1:          # the gap candidates (the burst at 3.8)
                return [[] for _ in arrays]
            return [[("\u2581uh", 0.36, 0.2)], [("\u2581so", 0.1, 0.1)]]   # confirms "uh", not "um"
        F.scan(words, x, SR, "en", decode)
        by = {w["text"]: w for w in words}
        self.assertTrue(by["uh"]["checked"])
        self.assertFalse(by["um"]["checked"])

    def test_no_decoder_no_acoustic_only_fillers_by_default(self):
        x, words = scene()
        st = F.scan(words, x, SR, "en", None)
        self.assertEqual(st["added"] + st["added_acoustic"], 0)


class CutPlanTest(unittest.TestCase):
    def doc(self, extra=()):
        ws = [("So", 0.5, 0.8), ("uh", 1.6, 1.9), ("today", 2.8, 3.2), ("we", 3.3, 3.5), ("ship", 3.6, 4.0),
              ("o", 4.4, 4.5), ("sea", 4.5, 4.7), ("este", 5.0, 5.3), ("libro", 5.4, 5.8)]
        words = [{"id": "w%d" % i, "text": t, "start": s, "end": e, "type": "word"} for i, (t, s, e) in enumerate(ws)]
        for w in extra:
            words.append(w)
        return {"language": "es", "duration": 7.0, "words": sorted(words, key=lambda w: w["start"])}

    def test_filler_pause_cap(self):
        p = cuts.plan_keep(self.doc())
        self.assertIn("uh", [r["text"] for r in p["removed"]])
        # the join around the removed "uh": what is left of 0.8-2.8 is at most 0.2 s of pause
        kept_between = sum(min(e, 2.8) - max(s, 0.8) for s, e in p["keep"] if e > 0.8 and s < 2.8)
        self.assertLessEqual(kept_between, 0.2 + 1e-6)
        wide = cuts.plan_keep(self.doc(), filler_pause=0.3, keep_pause=0.3)
        kept_wide = sum(min(e, 2.8) - max(s, 0.8) for s, e in wide["keep"] if e > 0.8 and s < 2.8)
        self.assertGreater(kept_wide, kept_between)

    def test_scan_flag_and_phrases(self):
        d = self.doc([{"id": "w99", "text": "mm-hm", "start": 4.1, "end": 4.3, "type": "word", "filler": True}])
        p = cuts.plan_keep(d)
        gone = [r["text"] for r in p["removed"]]
        self.assertIn("mm-hm", gone)                       # flagged by the gap scan
        self.assertNotIn("este", gone)                     # a real word by default
        self.assertNotIn("sea", gone)
        p2 = cuts.plan_keep(d, extra_fillers=U.DISCOURSE_FILLERS["es-discourse"])
        gone2 = [r["text"] for r in p2["removed"]]
        self.assertIn("o", gone2)
        self.assertIn("sea", gone2)
        self.assertIn("este", gone2)
        self.assertNotIn("libro", gone2)

    def test_strict_fillers_keep_unconfirmed(self):
        d = self.doc()
        for w in d["words"]:
            if w["text"] == "uh":
                w["checked"] = False
        self.assertIn("uh", [r["text"] for r in cuts.plan_keep(d)["removed"]])
        self.assertNotIn("uh", [r["text"] for r in cuts.plan_keep(d, strict_fillers=True)["removed"]])

    def test_snap_edges_to_quiet_frames(self):
        # loud everywhere except a 10 ms hole 30 ms after the planned edge
        x = (0.2 * np.random.default_rng(2).standard_normal(SR * 3)).astype(np.float32)
        x[int(1.53 * SR): int(1.54 * SR)] = 0.0
        keep = [(0.2, 1.5), (2.0, 2.9)]
        ws = [{"text": "a", "start": 0.3, "end": 1.4, "type": "word"}, {"text": "b", "start": 2.1, "end": 2.8, "type": "word"}]
        out, moved = F.snap_edges(keep, x, SR, ws)
        self.assertEqual(moved, 1)
        self.assertAlmostEqual(out[0][1], 1.535, delta=0.006)
        # never into a kept word
        ws2 = [{"text": "a", "start": 0.3, "end": 1.52, "type": "word"}]
        out2, _ = F.snap_edges([(0.2, 1.53), (2.0, 2.9)], x, SR, ws2)
        self.assertGreaterEqual(out2[0][1], 1.52)
        p = cuts.plan_keep({"language": "en", "duration": 3.0, "words": [
            {"id": "w0", "text": "a", "start": 0.3, "end": 1.4, "type": "word"},
            {"id": "w1", "text": "um", "start": 1.6, "end": 1.9, "type": "word"},
            {"id": "w2", "text": "b", "start": 2.1, "end": 2.8, "type": "word"}]}, snap_audio=(x, SR))
        self.assertIn("snapped_edges", p)


class CrossfadeTest(unittest.TestCase):
    def test_mark_and_mix_tails(self):
        import soundfile as sf
        from st.footage import render_edl as R
        segs = [{"i": 0, "audio_samples": 4800}, {"i": 1, "audio_samples": 4800, "join_in": True},
                {"i": 2, "audio_samples": 4800}]
        segs[0]["join_out"] = True
        R._mark_crossfades(segs, 0.02)
        self.assertNotIn("xf_out", segs[0])                # a continuous join is not a cut
        self.assertEqual(segs[1]["xf_out"], 0.02)
        self.assertEqual(segs[2]["xf_in"], 0.02)
        d = Path(tempfile.mkdtemp(prefix="st-xf-"))
        try:
            prog = d / "program.wav"
            sf.write(str(prog), np.zeros((14400, 2), np.float32), 48000, subtype="FLOAT")
            tail = d / "t.wav"
            sf.write(str(tail), np.ones((960, 2), np.float32), 48000, subtype="FLOAT")
            n = R._apply_tails(prog, segs, [{}, {"tail": str(tail)}, {}])
            self.assertEqual(n, 1)
            y, _ = sf.read(str(prog), dtype="float32", always_2d=True)
            self.assertEqual(len(y), 14400)
            self.assertAlmostEqual(float(y[9600, 0]), 1.0, places=3)      # tail starts at full level at the cut
            self.assertLess(float(y[9600 + 950, 0]), 0.05)                # and fades out
            self.assertEqual(float(np.abs(y[:9600]).max()), 0.0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class MusicTest(unittest.TestCase):
    def test_background_estimate_gates_separation(self):
        from st.footage import separate as S
        rng = np.random.default_rng(4)
        speech = np.concatenate([np.concatenate([word_like(0.6, k), silence(0.4)]) for k in range(8)])
        spans = [(k * 1.0, k * 1.0 + 0.6) for k in range(8)]
        clean = S.music_likely(speech, SR, spans)
        self.assertFalse(clean["separate"], clean)
        bed = (0.08 * np.sin(2 * np.pi * 220 * np.arange(len(speech)) / SR)).astype(np.float32)
        bed += (0.02 * rng.standard_normal(len(speech))).astype(np.float32)
        loud = S.music_likely(speech + bed, SR, spans)
        self.assertTrue(loud["separate"], loud)
        self.assertLess(loud["snr_db"], clean["snr_db"])

    def test_speech_time_ratio_sees_a_ducked_bed(self):
        from st.footage import separate as S
        v = np.concatenate([np.concatenate([word_like(0.6, k), silence(0.4)]) for k in range(6)])
        bed = (0.05 * np.sin(2 * np.pi * 330 * np.arange(len(v)) / SR)).astype(np.float32)
        active = np.abs(v) > 1e-3
        env = np.convolve(active.astype(float), np.ones(800) / 800, "same") > 0.05
        ducked = bed * np.where(env, 0.05, 1.0).astype(np.float32)      # -26 dB under the voice
        high = S.speech_time_snr_db(v + ducked, v, SR)
        low = S.speech_time_snr_db(v + bed, v, SR)
        self.assertGreater(high, S.SNR_GATE_DB)
        self.assertLess(low, high - 15)

    def test_stft_roundtrip(self):
        from st.footage import separate as S
        x = np.random.default_rng(5).standard_normal((2, 20000))
        n_fft, hop = 1024, 256
        w = np.hanning(n_fft + 1)[:-1]
        y = S._istft(S._stft(x, n_fft, hop, w), n_fft, hop, w, x.shape[1])
        self.assertLess(float(np.abs(y - x)[:, n_fft:-n_fft].max()), 1e-6)

    def test_dry_stem_of_a_motion_render(self):
        d = Path(tempfile.mkdtemp(prefix="st-stem-"))
        try:
            video = d / "final.mp4"
            video.write_bytes(b"x")
            (d / "work" / "audio").mkdir(parents=True)
            (d / "work" / "logs").mkdir()
            stem = d / "work" / "audio" / "mix.voice.wav"
            stem.write_bytes(b"RIFF")
            (d / "render.json").write_text(json.dumps({"output": str(video), "range": [2.5, 10.0],
                                                       "log": str(d / "work" / "logs" / "render.log")}))
            got = T.dry_stem(video.resolve())
            self.assertEqual(got[0], stem)
            self.assertEqual(got[1], 2.5)
            # `render -o clip.mp4` keeps its report in clip.work/
            clip = d / "clip.mp4"
            clip.write_bytes(b"x")
            (d / "clip.work" / "audio").mkdir(parents=True)
            (d / "clip.work" / "logs").mkdir()
            (d / "clip.work" / "audio" / "mix.voice.wav").write_bytes(b"RIFF")
            (d / "clip.work" / "render.json").write_text(json.dumps({"output": str(clip), "range": [0, 5],
                                                                   "log": str(d / "clip.work" / "logs" / "render.log")}))
            self.assertEqual(T.dry_stem(clip.resolve())[0], d / "clip.work" / "audio" / "mix.voice.wav")
            # another file's report is not ours
            other = d / "other.mp4"
            other.write_bytes(b"x")
            self.assertIsNone(T.dry_stem(other.resolve()))
            # an edit render: <video>.report.json -> audio.speech_stem
            ev = d / "edit.mp4"
            ev.write_bytes(b"x")
            prog = d / "program.wav"
            prog.write_bytes(b"RIFF")
            (d / "edit.report.json").write_text(json.dumps({"output": str(ev), "audio": {"speech_stem": str(prog)}}))
            self.assertEqual(T.dry_stem(ev.resolve())[:2], (prog, 0.0))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_mixer_writes_the_narration_stem(self):
        import soundfile as sf
        from st.audio import mix as M
        d = Path(tempfile.mkdtemp(prefix="st-mixstem-"))
        try:
            v = np.concatenate([silence(0.5), tone(1.0, 150, 0.3), silence(0.5)])
            sf.write(str(d / "vo.wav"), v, SR)
            m = (0.1 * np.sin(2 * np.pi * 330 * np.arange(2 * SR) / SR)).astype(np.float32)
            sf.write(str(d / "bed.wav"), m, SR)
            spec = {"duration": 2.0, "tracks": [{"kind": "voice", "file": "vo.wav"},
                                                {"kind": "music", "file": "bed.wav", "duck": True}]}
            rep = M.render(spec, d / "mix.wav", root=d)
            stem = d / "mix.voice.wav"
            self.assertTrue(stem.is_file(), rep.get("voice_stem"))
            y, sr = sf.read(str(stem), dtype="float32")
            self.assertEqual(sr, 16000)
            self.assertAlmostEqual(len(y) / sr, 2.0, delta=0.05)
            # the stem holds the voice only: nothing (no music) in the leading silence
            self.assertLess(float(np.abs(y[: int(0.4 * sr)]).max()), 1e-3)
            self.assertGreater(float(np.abs(y[int(0.9 * sr): int(1.1 * sr)]).max()), 0.01)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class CrisperTest(unittest.TestCase):
    def test_intel_mac_is_refused(self):
        from st.footage import crisper as C
        with mock.patch.object(C.plat, "platform_key", return_value="mac-x64"):
            self.assertIn("Intel Macs", C.unsupported_reason())
            with self.assertRaises(ShowtimeError) as cm:
                C.check(accept=True)
            self.assertIn("default model", cm.exception.hint)

    def test_bracketed_fillers_become_words(self):
        from st.footage import crisper as C
        self.assertEqual(C._unbracket("[UH]"), "uh")
        self.assertEqual(C._unbracket("[UM],"), "um,")
        self.assertEqual(C._unbracket("[LAUGHTER]"), "[LAUGHTER]")
        self.assertEqual(C._unbracket("moon"), "moon")

    def test_licence_needs_acceptance(self):
        from st.footage import crisper as C
        with Home() as h, mock.patch.object(C.plat, "platform_key", return_value="linux-x64"), \
                mock.patch.object(sys, "stdin", io.StringIO("")):
            with self.assertRaises(ShowtimeError) as cm:
                C.check(accept=False)
            self.assertIn("non-commercial", str(cm.exception).lower())
            self.assertIn("--accept-license", cm.exception.hint)
            C.check(accept=True)
            self.assertTrue(C.license_accepted())
            self.assertIn(C.LICENSE_ID, json.loads((h / "licenses.json").read_text()))
            C.check(accept=False)   # remembered


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
