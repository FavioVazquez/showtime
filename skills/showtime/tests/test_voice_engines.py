#!/usr/bin/env python3
"""Extra local TTS engines (issue #8): engines load by name, Kokoro stays the default.

- `engines.get("nope")` fails with a hint that lists the engines; a bad name is refused before any import
- an engine of your own in <home>/engines/ (or $SHOWTIME_ENGINE_PATH) loads by name, speaks through
  `tts.synthesize`, and `$SHOWTIME_VOICE=<engine>:<voice>` picks it like `piper:` and `supertonic:`
- built-in names always mean the built-in engine; Kokoro ids and blends still resolve to Kokoro; Piper unchanged
- doctor: missing Kokoro model files are SKIP when $SHOWTIME_VOICE names another engine, FAIL when it is
  unset; extra engines are listed with whether each imports

Seconds, no models: the test engines are tiny Python files that make a tone.

usage: python tests/test_voice_engines.py [-v]
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.common import ShowtimeError  # noqa: E402

TONE_ENGINE = textwrap.dedent('''
    import numpy as np
    from st.voice.engines.base import Engine, EngineResult

    class Tone(Engine):
        name = "%(name)s"
        has_timings = False
        default_voice = "low"
        where = "%(where)s"

        def available(self):
            return True, "a test tone"

        def voices(self):
            return ["low", "high"]

        def synth(self, tokens, spec, speed, lexicon, sentence_pause=0.3, clause_pause=0.12):
            sr = 24000
            t = np.arange(int(sr * 0.25 * max(1, len(tokens)))) / sr
            f = 220.0 if spec.name == "low" else 440.0
            return EngineResult(audio=(0.1 * np.sin(2 * np.pi * f * t)).astype("float32"), sample_rate=sr,
                                words=None, meta={"model": "tone-" + spec.name, "where": "%(where)s"})

    ENGINE = Tone()
''')

MARKER_ENGINE = textwrap.dedent('''
    from pathlib import Path
    Path(%(marker)r).write_text("imported")
    raise SystemExit("this module must never be imported")
''')


@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def fresh_engines():
    from st.voice import engines
    engines._CACHE.clear()
    for name in [m for m in sys.modules if m.startswith("st.voice.engines.")]:
        if name.rsplit(".", 1)[1] not in engines.NAMES + ("base",):
            del sys.modules[name]      # extra engines from an earlier test's folder
    return engines


class ExtraEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-engines-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.home = self.tmp / "home"
        (self.home / "engines").mkdir(parents=True)
        cm = env(SHOWTIME_HOME=self.home, SHOWTIME_ENGINE_PATH=None, SHOWTIME_VOICE=None, SHOWTIME_LANG=None)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.addCleanup(fresh_engines)
        fresh_engines()

    def put(self, folder: Path, name: str, where: str = "home") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / (name + ".py")
        p.write_text(TONE_ENGINE % {"name": name, "where": where}, encoding="utf-8")
        return p

    # ------------------------------------------------------------- loading by name
    def test_unknown_engine_lists_the_engines(self):
        engines = fresh_engines()
        self.put(self.home / "engines", "homelab")
        with self.assertRaises(ShowtimeError) as cm:
            engines.get("nope")
        hint = cm.exception.hint or ""
        for name in ("kokoro", "supertonic", "piper", "homelab"):
            self.assertIn(name, hint)
        self.assertIn(str(self.home / "engines"), hint, "the hint says where an engine of your own goes")

    def test_bad_name_is_refused_before_any_import(self):
        engines = fresh_engines()
        marker = self.tmp / "imported.txt"
        for bad in ("Loud", "1st"):
            (self.home / "engines" / (bad + ".py")).write_text(MARKER_ENGINE % {"marker": str(marker)})
        from st.voice import registry
        self.assertEqual(registry.discover(), {}, "files whose names are not engine names are not engines")
        for bad in ("Loud", "1st", "../engines/x", "a" * 33, "", "tone-2", "os.path"):
            with self.assertRaises(ShowtimeError, msg=bad) as cm:
                engines.get(bad)
            self.assertIn("bad TTS engine name", str(cm.exception), bad)
        self.assertFalse(marker.exists(), "nothing was imported for a refused name")
        from st.cli_voice import _engine_name
        self.assertEqual(_engine_name("auto"), "auto")
        self.assertEqual(_engine_name("St"), "supertonic")
        self.assertEqual(_engine_name("homelab"), "homelab")
        with self.assertRaises(argparse.ArgumentTypeError):
            _engine_name("../evil")

    def test_user_folder_engine_loads_and_speaks(self):
        engines = fresh_engines()
        self.put(self.home / "engines", "homelab")
        eng = engines.get("homelab")
        self.assertEqual(eng.available(), (True, "a test tone"))
        self.assertIs(engines.get("homelab"), eng, "loaded once")
        from st.voice import voices
        spec = voices.resolve("homelab:high")
        self.assertEqual((spec.engine, spec.name, spec.id, spec.lang), ("homelab", "high", "homelab:high", "en"))
        self.assertEqual(voices.resolve(None, engine="homelab").id, "homelab:low", "the engine's default voice")
        self.assertEqual(voices.resolve("high", "es", engine="homelab").lang, "es")
        with env(SHOWTIME_VOICE="homelab:high"):
            self.assertEqual(voices.configured_voice("es"), "homelab:high")
            self.assertEqual(voices.resolve(None, "en").id, "homelab:high", "SHOWTIME_VOICE picks the extra engine")
        try:
            from st.voice import tts
        except ImportError as e:  # the voice venv is not installed here
            self.skipTest("tts needs the venv: %s" % e)
        sp = tts.synthesize("Hello there [pause 0.2] friend.", voice="homelab:high", align_method="none",
                            use_cache=False)
        self.assertEqual((sp.engine, sp.voice, sp.timing), ("homelab", "homelab:high", "none"))
        self.assertGreater(sp.duration, 0.5)

    def test_a_copied_builtin_engine_loads_from_the_user_folder(self):
        """The docs say to copy piper.py: its relative imports (`from ...common`, `from .. import models`,
        `from .base`) must resolve when the copy is loaded from <home>/engines/."""
        engines = fresh_engines()
        src = SKILL / "lib" / "st" / "voice" / "engines" / "piper.py"
        shutil.copyfile(str(src), str(self.home / "engines" / "my_piper.py"))
        eng = engines.get("my_piper")
        self.assertEqual(type(eng).__name__, "PiperEngine")
        self.assertIsNot(eng, engines.get("piper"), "the copy is its own engine, not the built-in one")
        ok, why = eng.available()
        self.assertIsInstance(why, str)
        self.assertIn("st.voice.engines.my_piper", sys.modules)

    def test_engine_path_comes_first(self):
        engines = fresh_engines()
        self.put(self.home / "engines", "homelab", where="home")
        first = self.tmp / "mine"
        self.put(first, "homelab", where="path")
        self.put(self.tmp / "other", "lan_box", where="path2")
        with env(SHOWTIME_ENGINE_PATH=os.pathsep.join([str(first), str(self.tmp / "other")])):
            from st.voice import registry
            self.assertEqual(registry.discover()["homelab"], first / "homelab.py")
            self.assertIn("lan_box", registry.discover())
            self.assertEqual(engines.get("homelab").where, "path", "$SHOWTIME_ENGINE_PATH wins over <home>/engines")

    def test_builtins_cannot_be_shadowed_and_piper_is_unchanged(self):
        engines = fresh_engines()
        marker = self.tmp / "imported.txt"
        for name in ("kokoro", "piper", "base"):
            (self.home / "engines" / (name + ".py")).write_text(MARKER_ENGINE % {"marker": str(marker)})
        from st.voice import registry, voices
        self.assertEqual(registry.discover(), {})
        self.assertEqual(engines.get("piper").name, "piper")
        self.assertEqual(engines.get("kokoro").name, "kokoro")
        self.assertIs(engines.get("st"), engines.get("supertonic"))
        self.assertFalse(marker.exists())
        self.assertEqual(engines.NAMES, ("kokoro", "supertonic", "piper"))
        self.assertEqual(voices.resolve("piper:en_US-ljspeech-high").engine, "piper")
        self.assertEqual(voices.resolve("supertonic:F1").engine, "supertonic")
        spec = voices.resolve("af_heart:60+am_michael:40")
        self.assertEqual(spec.engine, "kokoro")
        self.assertEqual(voices.resolve("kokoro:af_heart").id, "af_heart")
        self.assertEqual(voices.resolve(None, "en").id, "af_heart", "an unset voice is still Kokoro")
        for v, want in (("", "kokoro"), ("af_heart", "kokoro"), ("af_heart:60+am_michael:40", "kokoro"),
                        ("af_heart:60", "kokoro"), ("st:F1", "supertonic"), ("Piper:x", "piper"),
                        ("homelab:x", "homelab"), ("my_tts:v1", "my_tts")):
            self.assertEqual(registry.engine_of(v), want, v)
        with self.assertRaises(ShowtimeError) as cm:
            voices.resolve("nope:voice")
        self.assertIn("unknown TTS engine", str(cm.exception))


class DoctorTests(unittest.TestCase):
    """Doctor with a home that has no Kokoro files: SKIP when the voice setting names another engine."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-engines-doctor-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.home = self.tmp / "home"
        (self.home / "engines").mkdir(parents=True)
        (self.home / "state.json").write_text('{"installed": {"tier": "core", "extras": []}}', encoding="utf-8")
        cm = env(SHOWTIME_HOME=self.home, SHOWTIME_ENGINE_PATH=None, SHOWTIME_VOICE=None, SHOWTIME_KOKORO_MODEL=None)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def doctor(self, venv_python=None):
        from st import doctor
        d = doctor.Doctor(argparse.Namespace(verify=False, verbose=False, quick=True))
        if venv_python:
            d.p["venv_python"] = Path(venv_python)
        return d

    def kokoro_rows(self, d):
        d.check_models()
        rows = [r for r in d.rows if r["check"].startswith("model kokoro-")]
        self.assertTrue(rows, "the core tier lists Kokoro's files")
        return rows

    def test_unset_voice_still_fails_on_missing_kokoro(self):
        self.assertEqual({r["status"] for r in self.kokoro_rows(self.doctor())}, {"fail"})

    def test_other_engine_skips_kokoro(self):
        for voice in ("piper:en_US-ljspeech-high", "supertonic:F1", "homelab:low"):
            with env(SHOWTIME_VOICE=voice):
                rows = self.kokoro_rows(self.doctor())
                self.assertEqual({r["status"] for r in rows}, {"skip"}, voice)
                self.assertIn("not needed", rows[0]["detail"])
        with env(SHOWTIME_VOICE="am_michael"):
            self.assertEqual({r["status"] for r in self.kokoro_rows(self.doctor())}, {"fail"},
                             "a Kokoro voice needs Kokoro")

    def test_extra_engines_are_listed(self):
        (self.home / "engines" / "homelab.py").write_text(TONE_ENGINE % {"name": "homelab", "where": "home"})
        (self.home / "engines" / "broken.py").write_text("import not_a_module_anywhere\n")
        shutil.copyfile(str(SKILL / "lib" / "st" / "voice" / "engines" / "piper.py"),
                        str(self.home / "engines" / "my_piper.py"))
        d = self.doctor(venv_python=self.tmp / "no-venv" / "python")
        d.check_voice_engines()
        self.assertEqual([(r["check"], r["status"]) for r in d.rows], [("voice engines", "warn")])
        vpy = plat.venv_python(Path(os.path.expanduser("~")) / ".showtime" / "venv")
        d = self.doctor(venv_python=vpy if vpy.exists() else sys.executable)
        d.check_voice_engines()
        rows = {r["check"]: r for r in d.rows}
        self.assertEqual(rows["voice engine homelab"]["status"], "pass", rows)
        self.assertEqual(rows["voice engine broken"]["status"], "warn", rows)
        self.assertIn("does not import", rows["voice engine broken"]["detail"])
        self.assertNotIn("does not import", rows["voice engine my_piper"]["detail"], "a copy of piper.py imports")
        with env(SHOWTIME_VOICE="broken:x"):
            d = self.doctor(venv_python=vpy if vpy.exists() else sys.executable)
            d.check_voice_engines()
            self.assertEqual({r["check"]: r["status"] for r in d.rows}["voice engine broken"], "fail",
                             "the configured engine not importing fails the install")
        with env(SHOWTIME_VOICE="missing:x"):
            d = self.doctor(venv_python=self.tmp / "no-venv" / "python")
            d.check_voice_engines()
            self.assertEqual({r["check"]: r["status"] for r in d.rows}["voice engine missing"], "fail")

    def test_no_extra_engines_no_row(self):
        d = self.doctor()
        d.check_voice_engines()
        self.assertEqual(d.rows, [], "the default install's doctor output is unchanged")


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])
