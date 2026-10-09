#!/usr/bin/env python3
"""Extra local TTS engines: module load, user folder, name rules, Kokoro doctor skip."""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

from st.common import ShowtimeError  # noqa: E402
from st.doctor import showtime_voice_skips_kokoro_models  # noqa: E402
from st.voice.engines import (  # noqa: E402
    bundled_names,
    clear_cache,
    get,
    names,
    probe_extras,
    user_engine_dirs,
)
from st.voice import voices  # noqa: E402

_TOY = textwrap.dedent("""\
    from st.voice.engines.base import Engine, EngineResult

    class ToyEngine(Engine):
        name = "toyeng"
        has_timings = False
        speed_range = (0.5, 2.0)

        def available(self):
            return True, "test toy"

        def synthesize(self, text, voice, speed=1.0, **kw):
            raise NotImplementedError("toy")

    ENGINE = ToyEngine()
""")


class ExtraEngineTests(unittest.TestCase):
    def setUp(self):
        clear_cache()
        self._engine_path = os.environ.pop("SHOWTIME_ENGINE_PATH", None)
        self._home = os.environ.pop("SHOWTIME_HOME", None)

    def tearDown(self):
        clear_cache()
        if self._engine_path is None:
            os.environ.pop("SHOWTIME_ENGINE_PATH", None)
        else:
            os.environ["SHOWTIME_ENGINE_PATH"] = self._engine_path
        if self._home is None:
            os.environ.pop("SHOWTIME_HOME", None)
        else:
            os.environ["SHOWTIME_HOME"] = self._home

    def test_bundled_names_stable(self):
        self.assertEqual(bundled_names(), ("kokoro", "supertonic", "piper"))
        self.assertTrue(set(bundled_names()).issubset(set(names())))

    def test_unknown_engine_errors(self):
        with self.assertRaises(ShowtimeError) as ctx:
            get("definitely_not_an_engine_zzz")
        msg = str(ctx.exception).lower()
        self.assertIn("unknown tts engine", msg)
        hint = (getattr(ctx.exception, "hint", None) or "").lower()
        self.assertIn("engines found", hint)
        self.assertIn("kokoro", hint)

    def test_rejected_engine_name(self):
        with self.assertRaises(ShowtimeError) as ctx:
            get("Bad-Name")
        hint = (getattr(ctx.exception, "hint", None) or "")
        self.assertIn("[a-z][a-z0-9_]{0,31}", hint)
        with self.assertRaises(ShowtimeError):
            get("a" * 33)

    def test_user_folder_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eng_dir = root / "engines"
            eng_dir.mkdir()
            (eng_dir / "toyeng.py").write_text(_TOY, encoding="utf-8")
            os.environ["SHOWTIME_HOME"] = str(root)
            os.environ.pop("SHOWTIME_ENGINE_PATH", None)
            clear_cache()
            self.assertIn(eng_dir.resolve(), [p.resolve() for p in user_engine_dirs()])
            self.assertIn("toyeng", names())
            eng = get("toyeng")
            self.assertEqual(getattr(eng, "name", None), "toyeng")
            ok_rows = [r for r in probe_extras() if r["name"] == "toyeng"]
            self.assertEqual(len(ok_rows), 1)
            self.assertTrue(ok_rows[0]["ok"])

    def test_engine_path_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng_dir = Path(tmp)
            (eng_dir / "patheng.py").write_text(
                _TOY.replace("toyeng", "patheng"), encoding="utf-8"
            )
            os.environ["SHOWTIME_ENGINE_PATH"] = str(eng_dir)
            clear_cache()
            eng = get("patheng")
            self.assertEqual(getattr(eng, "name", None), "patheng")

    def test_resolve_unknown_prefix_errors(self):
        with self.assertRaises(ShowtimeError):
            voices.resolve("zzzengine:voice")

    def test_kokoro_still_resolves(self):
        spec = voices.resolve("af_heart")
        self.assertEqual(spec.engine, "kokoro")
        self.assertEqual(spec.name, "af_heart")


class DoctorKokoroSkipTests(unittest.TestCase):
    def setUp(self):
        self._voice = os.environ.pop("SHOWTIME_VOICE", None)
        self._skip = os.environ.pop("SHOWTIME_SKIP_KOKORO", None)

    def tearDown(self):
        if self._voice is None:
            os.environ.pop("SHOWTIME_VOICE", None)
        else:
            os.environ["SHOWTIME_VOICE"] = self._voice
        if self._skip is None:
            os.environ.pop("SHOWTIME_SKIP_KOKORO", None)
        else:
            os.environ["SHOWTIME_SKIP_KOKORO"] = self._skip

    def test_default_requires_kokoro(self):
        self.assertFalse(showtime_voice_skips_kokoro_models())

    def test_bare_kokoro_id_requires_models(self):
        os.environ["SHOWTIME_VOICE"] = "af_heart"
        self.assertFalse(showtime_voice_skips_kokoro_models())

    def test_piper_prefix_skips_kokoro_models(self):
        os.environ["SHOWTIME_VOICE"] = "piper:en_US-ljspeech-high"
        self.assertTrue(showtime_voice_skips_kokoro_models())

    def test_explicit_skip_flag(self):
        os.environ["SHOWTIME_SKIP_KOKORO"] = "1"
        self.assertTrue(showtime_voice_skips_kokoro_models())


if __name__ == "__main__":
    unittest.main()
