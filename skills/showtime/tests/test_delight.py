#!/usr/bin/env python3
"""Terminal touches: when the brand mark, completion card and sound may appear, and what they look like.

Covers st/delight.py and its Node twin scripts/lib/delight.mjs: the suppression rules (not a terminal,
--json, NO_COLOR, TERM=dumb, CI, SHOWTIME_COLOR=never, SHOWTIME_PROGRESS=json, Windows without VT), the
card and header formatters (plain, ASCII, 256-colour, truecolor; velvet never on text), the players per
OS, the opt-in sound gate, and the real `showtime --help` under a pseudo-terminal and a pipe.

Stdlib only; fast (no renders). usage: python tests/test_delight.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import delight  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

NODE = shutil.which("node")
ESC = re.compile(r"\x1b\[[0-9;]*m")
VELVET_24 = "38;2;179;18;31"
CLEAN_ENV = {"TERM": "xterm-256color"}


class FakeStream(io.StringIO):
    def __init__(self, tty=True, encoding="utf-8"):
        super().__init__()
        self._tty = tty
        self._enc = encoding

    def isatty(self):
        return self._tty

    @property
    def encoding(self):  # type: ignore[override]
        return self._enc


def vt_on(_stream):
    return True


class TestSuppression(unittest.TestCase):
    """decor_ok(): the one gate for the mark, the card and the sound."""

    def ok(self, env=None, argv=(), tty=True):
        with mock.patch("st.common._enable_windows_vt", vt_on):
            return delight.decor_ok(FakeStream(tty), list(argv), dict(CLEAN_ENV, **(env or {})))

    def test_matrix(self):
        self.assertTrue(self.ok())
        cases = {
            "not a terminal": dict(tty=False),
            "--json": dict(argv=["render", "x", "--json"]),
            "NO_COLOR": dict(env={"NO_COLOR": "1"}),
            "TERM=dumb": dict(env={"TERM": "dumb"}),
            "CI": dict(env={"CI": "true"}),
            "CI=1": dict(env={"CI": "1"}),
            "SHOWTIME_COLOR=never": dict(env={"SHOWTIME_COLOR": "never"}),
            "SHOWTIME_PROGRESS=json": dict(env={"SHOWTIME_PROGRESS": "json"}),
            "FORCE_COLOR on a pipe": dict(env={"FORCE_COLOR": "1"}, tty=False),
            "SHOWTIME_COLOR=always on a pipe": dict(env={"SHOWTIME_COLOR": "always"}, tty=False),
        }
        for why, kw in cases.items():
            with self.subTest(why):
                self.assertFalse(self.ok(**kw), why)
        # a CI variable that says "no" is not CI; an empty NO_COLOR is not set
        self.assertTrue(self.ok(env={"CI": "false"}))
        self.assertTrue(self.ok(env={"NO_COLOR": ""}))

    def test_windows_without_vt_is_plain(self):
        with mock.patch("st.common._enable_windows_vt", lambda s: False):
            self.assertFalse(delight.decor_ok(FakeStream(True), [], CLEAN_ENV))

    def test_broken_stream_is_plain(self):
        class Closed:
            def isatty(self):
                raise ValueError("closed")
        self.assertFalse(delight.decor_ok(Closed(), [], CLEAN_ENV))
        self.assertFalse(delight.decor_ok(object(), [], CLEAN_ENV))

    def test_color_depth(self):
        self.assertEqual(delight.color_depth({"COLORTERM": "truecolor"}, "linux"), 24)
        self.assertEqual(delight.color_depth({"COLORTERM": "24bit"}, "mac"), 24)
        self.assertEqual(delight.color_depth({}, "windows"), 24)
        self.assertEqual(delight.color_depth({"WT_SESSION": "x"}, "linux"), 24)
        self.assertEqual(delight.color_depth({"TERM_PROGRAM": "iTerm.app"}, "mac"), 24)
        self.assertEqual(delight.color_depth({"TERM": "xterm-256color", "TERM_PROGRAM": "Apple_Terminal"}, "mac"), 8)
        self.assertEqual(delight.color_depth({"TERM": "xterm"}, "linux"), 4)

    def test_unicode_ok(self):
        self.assertTrue(delight.unicode_ok(FakeStream(encoding="utf-8")))
        self.assertTrue(delight.unicode_ok(FakeStream(encoding="cp437")))   # the block glyphs are in CP437
        self.assertFalse(delight.unicode_ok(FakeStream(encoding="ascii")))
        self.assertFalse(delight.unicode_ok(FakeStream(encoding="no-such-codec")))

    def test_header_none_when_off(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertIsNone(delight.header("showtime 0.1.0", "x", FakeStream(True)))
        self.assertIsNone(delight.header("showtime 0.1.0", "x", FakeStream(False)))


class TestFormatters(unittest.TestCase):
    CWD = str(Path(tempfile.gettempdir()).resolve() / "st-card")

    def card(self, **kw):
        base = dict(title="final.mp4 is ready", path=os.path.join(self.CWD, "showtime-out", "demo", "final.mp4"),
                    facts=["20.0 s", "1920x1080", "4.2 MB"], next_step="showtime qa showtime-out/demo",
                    cwd=self.CWD)
        base.update(kw)
        return delight.format_card(**base)

    def test_plain_card(self):
        text = self.card(depth=0, qa="pass")
        rel = os.path.join("showtime-out", "demo", "final.mp4")
        self.assertEqual(text.splitlines(), [
            "\u2590\u2588\u2580\u2580\u2580\u2588\u258c  final.mp4 is ready  \u00b7  20.0 s  \u00b7  1920x1080  "
            "\u00b7  4.2 MB  \u00b7  qa PASS",
            "\u2590\u2588\u2584\u2584\u2584\u2588\u258c  " + rel,
            "         next  showtime qa showtime-out/demo",
        ])
        self.assertIsNone(ESC.search(text))

    def test_ascii_card(self):
        text = self.card(depth=0, unicode=False)
        text.encode("ascii")
        self.assertTrue(text.startswith('|"""""|  final.mp4 is ready  -  20.0 s'))
        self.assertEqual(text.splitlines()[1][:7], "|_===_|")

    def test_optional_parts(self):
        text = self.card(depth=0, facts=[None, "", "4.2 MB"], next_step=None)
        self.assertEqual(len(text.splitlines()), 2)
        self.assertIn("final.mp4 is ready  \u00b7  4.2 MB", text)
        self.assertNotIn("qa", text)
        self.assertEqual(text, "\n".join(line.rstrip() for line in text.splitlines()))

    def test_colours(self):
        tc = self.card(depth=24, qa="WARN")
        self.assertIn(VELVET_24, tc)
        self.assertIn("38;2;233;185;73", tc)                       # gold
        self.assertIn("\x1b[33mWARN", tc)
        self.assertEqual(ESC.sub("", tc), self.card(depth=0, qa="WARN"))
        c256 = self.card(depth=8)
        self.assertIn("38;5;124", c256)
        self.assertNotIn("38;2;", c256)
        c16 = self.card(depth=4)
        self.assertIn("\x1b[31m", c16)
        self.assertNotIn("38;5;", c16)
        # velvet is for shapes only: never wraps text
        for depth in (24, 8, 4):
            for text in (self.card(depth=depth), delight.format_header("showtime 0.1.0", "sub", depth)):
                for m in re.finditer(r"\x1b\[([0-9;]*)m([^\x1b]*)", text):
                    if m.group(1) in (VELVET_24, "38;5;124", "31"):
                        self.assertRegex(m.group(2), r"^[\u2580-\u259f|\"_]*$", "velvet on text: %r" % m.group(2))

    def test_header(self):
        h = delight.format_header("showtime doctor 0.1.0", "mac-x64  \u00b7  home ~/.showtime", depth=24)
        plain = ESC.sub("", h).splitlines()
        self.assertEqual(plain[0], "\u2590\u2588\u2580\u2580\u2580\u2588\u258c  showtime doctor 0.1.0")
        self.assertEqual(plain[1], "\u2590\u2588\u2584\u2584\u2584\u2588\u258c  mac-x64  \u00b7  home ~/.showtime")
        self.assertIn("\x1b[1;38;2;233;185;73mshowtime doctor", h)
        a = ESC.sub("", delight.format_header("showtime 0.1.0", "a \u00b7 b", depth=4, unicode=False))
        a.encode("ascii")

    def test_paths_and_hints(self):
        inside = os.path.join(self.CWD, "out", "my video.mp4")
        self.assertEqual(delight.display_path(inside, self.CWD), os.path.join("out", "my video.mp4"))
        outside = str(Path(self.CWD).parent / "elsewhere.mp4")
        self.assertEqual(delight.display_path(outside, self.CWD), outside)
        with mock.patch("os.getcwd", return_value=self.CWD):
            q = '"%s"' % os.path.join("out", "my video.mp4")
            self.assertEqual(delight.open_hint(inside, "mac"), "open " + q)
            self.assertEqual(delight.open_hint(inside, "linux"), "xdg-open " + q)
            self.assertEqual(delight.open_hint(inside, "windows"), 'start "" ' + q)
            plain = os.path.join(self.CWD, "final.mp4")
            self.assertEqual(delight.open_hint(plain, "windows"), 'start "" "final.mp4"')
            self.assertEqual(delight.shell_path(plain), "final.mp4")

    def test_fmt_len(self):
        self.assertEqual(delight.fmt_len(20), "20.0 s")
        self.assertEqual(delight.fmt_len(95.2), "1:35")
        self.assertIsNone(delight.fmt_len(None))
        self.assertIsNone(delight.fmt_len("x"))

    def test_qa_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            job = Path(d).resolve()
            final = job / "final.mp4"
            other = job / "exports" / "final.reels.mp4"
            (job / "job.json").write_text(json.dumps({
                "qa": {"verdict": "WARN", "video": str(job / "older.mp4")},
                "qa_files": {str(final): {"verdict": "PASS"}}}), encoding="utf-8")
            self.assertEqual(delight.qa_verdict(final), "PASS")
            self.assertIsNone(delight.qa_verdict(other, job))        # the job's verdict is about another file
            self.assertIsNone(delight.qa_verdict(job / "nope.mp4"))
            self.assertIsNone(delight.qa_verdict(Path(d) / "x" / "y" / "z.mp4"))

    def test_show_card_gate(self):
        tty = FakeStream(True)
        with mock.patch("st.common._enable_windows_vt", vt_on), \
                mock.patch.dict(os.environ, {"TERM": "xterm"}, clear=False), \
                mock.patch.object(sys, "argv", ["showtime", "render"]):
            for k in ("NO_COLOR", "CI", "SHOWTIME_COLOR", "SHOWTIME_PROGRESS"):
                os.environ.pop(k, None)
            self.assertTrue(delight.show_card("a.mp4 is ready", "a.mp4", ["1.0 s"], "showtime qa a.mp4", stream=tty))
            self.assertIn("a.mp4 is ready", tty.getvalue())
            pipe = FakeStream(False)
            self.assertFalse(delight.show_card("a.mp4 is ready", "a.mp4", stream=pipe))
            self.assertEqual(pipe.getvalue(), "")
            with mock.patch.object(sys, "argv", ["showtime", "render", "--json"]):
                quiet = FakeStream(True)
                self.assertFalse(delight.show_card("a.mp4 is ready", "a.mp4", stream=quiet))
                self.assertEqual(quiet.getvalue(), "")

    def test_exports_card(self):
        from st import cli_deliver
        out = FakeStream(True)
        rep = {"out_dir": os.path.join(self.CWD, "exports"), "exports": [
            {"target": "youtube", "output": os.path.join(self.CWD, "exports", "f.youtube.mp4"), "size_bytes": 3e6,
             "duration": 20, "width": 1920, "height": 1080},
            {"target": "reels", "output": os.path.join(self.CWD, "exports", "f.reels.mp4"), "size_bytes": 2e6,
             "duration": 20, "width": 1080, "height": 1920}]}
        with mock.patch("st.common._enable_windows_vt", vt_on), mock.patch.object(sys, "stdout", out), \
                mock.patch.dict(os.environ, {"TERM": "xterm"}, clear=False), mock.patch("os.getcwd", return_value=self.CWD), \
                mock.patch.object(sys, "argv", ["showtime", "deliver", "exports"]):
            for k in ("NO_COLOR", "CI", "SHOWTIME_COLOR", "SHOWTIME_PROGRESS"):
                os.environ.pop(k, None)
            cli_deliver._exports_card(rep)
        text = ESC.sub("", out.getvalue())
        self.assertIn("2 exports are ready  \u00b7  youtube, reels  \u00b7  5.0 MB in all", text)
        self.assertIn("exports", text.splitlines()[2])
        self.assertIn("next  ", text)


class TestSound(unittest.TestCase):
    def test_players(self):
        found = {"afplay": "/usr/bin/afplay", "powershell": r"C:\Windows\powershell.exe", "aplay": "/usr/bin/aplay",
                 "paplay": None, "pw-play": None, "ffplay": None}
        which = lambda n: found.get(n)  # noqa: E731
        with tempfile.TemporaryDirectory() as h, mock.patch.dict(os.environ, {"SHOWTIME_HOME": h}):
            self.assertEqual(delight.player_command("s.wav", "mac", which), ["afplay", "s.wav"])
            win = delight.player_command("C:\\it's\\s.wav", "windows", which)
            self.assertEqual(win[0], r"C:\Windows\powershell.exe")
            self.assertIn("SoundPlayer 'C:\\it''s\\s.wav').PlaySync()", win[-1])
            self.assertEqual(delight.player_command("s.wav", "linux", which), ["/usr/bin/aplay", "-q", "s.wav"])
            self.assertIsNone(delight.player_command("s.wav", "linux", lambda n: None))
            self.assertEqual(delight.player_command("s.wav", "linux", lambda n: "/x/ffplay" if n == "ffplay" else None)[:2],
                             ["/x/ffplay", "-nodisp"])
            # showtime's own ffplay comes first when the install has one
            (Path(h) / "bin").mkdir()
            own = Path(h) / "bin" / "ffplay"
            own.write_text("")
            self.assertEqual(delight.player_command("s.wav", "mac", which)[0], str(own))

    def test_sound_file_ships(self):
        f = delight.SOUND_FILE
        self.assertTrue(f.is_file(), f)
        self.assertLess(f.stat().st_size, 200_000)
        self.assertEqual(f.read_bytes()[:4], b"RIFF")

    def test_gate(self):
        env = dict(CLEAN_ENV, SHOWTIME_SOUND="1")
        with mock.patch("st.delight.play_sound", return_value=True) as play:
            # the test's own stdout is a pipe: never plays here
            self.assertFalse(delight.maybe_chime(60, env=env, argv=[]))
            with mock.patch("st.delight.decor_ok", return_value=True):
                self.assertTrue(delight.maybe_chime(60, env=env, argv=[]))
                self.assertFalse(delight.maybe_chime(5, env=env, argv=[]))            # short job
                self.assertFalse(delight.maybe_chime(60, ok=False, env=env, argv=[]))  # failed job
                self.assertFalse(delight.maybe_chime(60, env=dict(CLEAN_ENV), argv=[]))  # off by default
                self.assertFalse(delight.maybe_chime(60, env=dict(CLEAN_ENV, SHOWTIME_SOUND="0"), argv=[]))
            self.assertEqual(play.call_count, 1)

    def test_play_never_raises(self):
        with mock.patch("st.delight.player_command", return_value=["/no/such/player", "x"]):
            self.assertFalse(delight.play_sound())
        with mock.patch("st.delight.player_command", return_value=None):
            self.assertFalse(delight.play_sound())
        self.assertFalse(delight.play_sound(Path(tempfile.gettempdir()) / "st-missing-sound.wav"))
        with mock.patch("st.delight.player_command", return_value=["x"]), \
                mock.patch("subprocess.Popen", side_effect=OSError("boom")):
            self.assertFalse(delight.play_sound())
        calls = []
        with mock.patch("st.delight.player_command", return_value=["player", "f.wav"]), \
                mock.patch("subprocess.Popen", side_effect=lambda *a, **k: calls.append((a, k))):
            self.assertTrue(delight.play_sound())
        self.assertEqual(calls[0][0][0], ["player", "f.wav"])
        self.assertIs(calls[0][1]["stdout"], subprocess.DEVNULL)

    def test_setting_reaches_env(self):
        from st import launcher
        self.assertEqual(launcher.SETTINGS_ENV["sound"], "SHOWTIME_SOUND")
        self.assertEqual(launcher.settings_env({"sound": True}), {"SHOWTIME_SOUND": "1"})
        self.assertEqual(launcher.settings_env({"sound": False}), {"SHOWTIME_SOUND": "0"})


def _run_in_pty(argv, env, timeout=60):
    """Run argv with stdout/stderr on a pseudo-terminal; return the output text (POSIX only)."""
    import pty
    import select
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
    finally:
        os.close(slave)
    chunks = []
    try:
        while True:
            r, _, _ = select.select([master], [], [], timeout)
            if not r:
                break
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master)
        proc.wait(timeout=timeout)
    return b"".join(chunks).decode("utf-8", "replace")


class TestRealCommand(unittest.TestCase):
    """The real `showtime --help`: the mark at a terminal, the old first line everywhere else."""

    def env(self, **extra):
        env = build_env(showtime_home())
        for k in ("NO_COLOR", "CI", "SHOWTIME_COLOR", "SHOWTIME_PROGRESS", "FORCE_COLOR"):
            env.pop(k, None)
        env["TERM"] = "xterm-256color"
        env.update(extra)
        return env

    def test_piped_help_unchanged(self):
        cp = subprocess.run([sys.executable, str(LAUNCHER), "--help"], env=self.env(), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertEqual(cp.returncode, 0)
        self.assertTrue(cp.stdout.startswith("showtime "), cp.stdout[:80])
        self.assertIn(": make videos on your own machine", cp.stdout.splitlines()[0])
        self.assertIsNone(ESC.search(cp.stdout))
        self.assertNotIn("\u2588", cp.stdout)

    @unittest.skipIf(os.name == "nt", "pseudo-terminals are POSIX-only")
    def test_terminal_help_has_mark(self):
        out = _run_in_pty([sys.executable, str(LAUNCHER), "--help"], self.env(COLORTERM="truecolor"))
        lines = ESC.sub("", out).replace("\r", "").splitlines()
        first = [ln for ln in lines if ln.strip()][:2]
        self.assertTrue(first[0].startswith("\u2590\u2588\u2580\u2580\u2580\u2588\u258c  showtime "), first)
        self.assertIn("make videos on your own machine", first[1])
        self.assertIn(VELVET_24, out)
        for extra in ({"NO_COLOR": "1"}, {"CI": "true"}, {"TERM": "dumb"}):
            with self.subTest(**extra):
                plain = _run_in_pty([sys.executable, str(LAUNCHER), "--help"], self.env(**extra))
                self.assertNotIn("\u2588", plain)
                self.assertIn("showtime ", plain)


@unittest.skipUnless(NODE, "node not found")
class TestNodeTwin(unittest.TestCase):
    """scripts/lib/delight.mjs prints the same card and follows the same rules."""

    def node(self, code):
        mod = (SKILL / "scripts" / "lib" / "delight.mjs").as_uri()
        src = "import * as d from %s;\n%s" % (json.dumps(mod), code)
        cp = subprocess.run([NODE, "--input-type=module", "-e", src], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=60, env=dict(os.environ, SHOWTIME_HOME=tempfile.gettempdir()))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout)

    def test_same_card(self):
        cwd = TestFormatters.CWD
        path = os.path.join(cwd, "showtime-out", "demo", "final.mp4")
        for depth, uni in ((0, True), (24, True), (8, False), (4, True)):
            with self.subTest(depth=depth, unicode=uni):
                js = self.node("console.log(JSON.stringify(d.formatCard({title: 'final.mp4 is ready', file: %s, "
                               "facts: ['20.0 s', null, '4.2 MB'], next: 'showtime qa x', qa: 'pass', depth: %d, "
                               "unicode: %s, cwd: %s})));" % (json.dumps(path), depth, "true" if uni else "false",
                                                              json.dumps(cwd)))
                py = delight.format_card("final.mp4 is ready", path, ["20.0 s", None, "4.2 MB"], "showtime qa x",
                                         qa="pass", depth=depth, unicode=uni, cwd=cwd)
                self.assertEqual(js, py)

    def test_same_rules(self):
        res = self.node(
            "const tty = {isTTY: true}, pipe = {isTTY: false}, E = {TERM: 'xterm-256color'};\n"
            "console.log(JSON.stringify({\n"
            " on: d.decorOk(tty, [], E), pipe: d.decorOk(pipe, [], E), json: d.decorOk(tty, ['--json'], E),\n"
            " nocolor: d.decorOk(tty, [], {...E, NO_COLOR: '1'}), dumb: d.decorOk(tty, [], {TERM: 'dumb'}),\n"
            " ci: d.decorOk(tty, [], {...E, CI: 'true'}), cifalse: d.decorOk(tty, [], {...E, CI: 'false'}),\n"
            " never: d.decorOk(tty, [], {...E, SHOWTIME_COLOR: 'never'}),\n"
            " pjson: d.decorOk(tty, [], {...E, SHOWTIME_PROGRESS: 'json'}),\n"
            " depth: [d.colorDepth({COLORTERM: 'truecolor'}, 'linux'), d.colorDepth({}, 'win32'),\n"
            "         d.colorDepth({TERM: 'xterm-256color'}, 'darwin'), d.colorDepth({TERM: 'xterm'}, 'linux')],\n"
            " uni: [d.unicodeOk({LANG: 'en_US.UTF-8'}, 'linux'), d.unicodeOk({LANG: 'C'}, 'linux'), d.unicodeOk({}, 'win32')],\n"
            " win: d.openHint('/tmp/a b.mp4', 'win32'), mac: d.playerCommand('s.wav', 'darwin', (n) => n === 'afplay' ? '/usr/bin/afplay' : null),\n"
            " lin: d.playerCommand('s.wav', 'linux', (n) => n === 'pw-play' ? '/usr/bin/pw-play' : null),\n"
            " none: d.playerCommand('s.wav', 'linux', () => null), sound: d.SOUND_FILE,\n"
            " chime: d.maybeChime(60000), long: d.LONG_JOB_MS,\n"
            "}));")
        self.assertTrue(res["on"])
        for k in ("pipe", "json", "nocolor", "dumb", "ci", "never", "pjson"):
            self.assertFalse(res[k], k)
        self.assertTrue(res["cifalse"])
        self.assertEqual(res["depth"], [24, 24, 8, 4])
        self.assertEqual(res["uni"], [True, False, True])
        self.assertTrue(res["win"].startswith('start "" "'), res["win"])
        self.assertEqual(res["mac"], ["afplay", "s.wav"])
        self.assertEqual(res["lin"], ["/usr/bin/pw-play", "s.wav"])
        self.assertIsNone(res["none"])
        self.assertEqual(Path(res["sound"]).resolve(), delight.SOUND_FILE)
        self.assertFalse(res["chime"])            # SHOWTIME_SOUND unset and not a terminal
        self.assertEqual(res["long"], delight.LONG_JOB_S * 1000)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
