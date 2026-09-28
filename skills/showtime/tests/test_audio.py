#!/usr/bin/env python3
"""Audio module smoke tests (runs in about a minute).

Drives the real CLI (`showtime audio ...`) through the launcher, like a user
or Claude would, and checks the numbers:

- styles / sfx-types list >= 12 styles and >= 30 effect types
- compose 3 styles (10 s): exact sample count, -14 +-0.5 LUFS, true peak <= -1 dBTP,
  every section marker on a downbeat, MIDI + stems + beats.json written
- 10 procedural effects: hit inside the file, peak <= -1 dBFS, sidecar JSON
- beats on a composed track recovers the tempo within 3 %
- fit loops a track to an exact length
- library: BYO index + search in a throw-away SHOWTIME_HOME, plus a read-only
  search of the real library when it is installed
- mix: composed music + speech-like voice (Kokoro via `showtime voice say` when
  available, else a synthetic formant voice) + file and synth SFX with hit
  alignment, ducking and carving -> -14 +-0.5 LUFS and TP <= -1 (checked by our
  meter AND ffmpeg ebur128), voice >= 8 dB above the music while speaking
- master brings a quiet file to -14 LUFS

usage: python tests/test_audio.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402
from st import platform as plat  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
VPY = str(plat.venv_python(showtime_home() / "venv"))
PY = VPY if Path(VPY).is_file() else sys.executable

VOICE_SNIPPET = r"""
import sys, numpy as np
sys.path.insert(0, sys.argv[3])
from st.audio import dsp, wav, SR
dur = float(sys.argv[2]); N = int(dur * SR); t = np.arange(N) / SR
r = np.random.default_rng(1)
f0 = 120 + 25 * np.sin(2 * np.pi * 0.7 * t) + 10 * np.sin(2 * np.pi * 3.1 * t)
src = dsp.osc("saw", f0, N)
F = [(730, 1090, 2440), (270, 2290, 3010), (530, 1840, 2480), (570, 840, 2410), (300, 870, 2240)]
out = np.zeros(N); env = np.zeros(N); syl = 0.18
for i in range(int(dur / syl) + 1):
    a, b = int(i * syl * SR), min(N, int((i + 1) * syl * SR))
    if b <= a: break
    f1, f2, f3 = F[r.integers(0, 5)]
    seg = src[a:b]
    out[a:b] = dsp.resonator(seg, f1, 6) + 0.6 * dsp.resonator(seg, f2, 8) + 0.3 * dsp.resonator(seg, f3, 10)
    env[a:b] = np.hanning(b - a)
phrase = ((t % 2.1) < 1.6).astype(float)
x = dsp.normalize_peak((out * env * phrase).astype(np.float32), -3)
wav.save(sys.argv[1], dsp.to_stereo(x))
"""


def st(*args, check=True, timeout=600, env=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def js(*args, **kw):
    cp = st(*args, **kw)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        raise AssertionError("not JSON from showtime %s:\n%s\n%s" % (" ".join(map(str, args)), cp.stdout[-2000:], cp.stderr[-2000:]))


def wav_frames(path: Path) -> int:
    """Frame count from the RIFF header (works for PCM and WAVE_FORMAT_EXTENSIBLE on any Python)."""
    import struct
    with open(str(path), "rb") as f:
        riff, _, wave_id = struct.unpack("<4sI4s", f.read(12))
        assert riff == b"RIFF" and wave_id == b"WAVE", path
        block_align = None
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                raise AssertionError("no data chunk in %s" % path)
            cid, size = struct.unpack("<4sI", hdr)
            if cid == b"fmt ":
                fmt = f.read(size)
                block_align = struct.unpack("<H", fmt[12:14])[0]
                if size % 2:
                    f.read(1)
            elif cid == b"data":
                return size // block_align
            else:
                f.seek(size + (size % 2), 1)


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-audio-"))
        cls.t0 = time.time()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    # ------------------------------------------------------------------ catalogs
    def test_01_lists(self):
        styles = js("audio", "styles", "--json")
        self.assertGreaterEqual(len(styles), 12)
        for want in ("upbeat-tech", "corporate-minimal", "cinematic-build", "epic-trailer", "lofi-chill", "synthwave",
                     "ambient-pad", "playful-pizzicato", "deep-house", "hip-hop-beat", "acoustic-folk",
                     "piano-emotional", "dark-tension", "retro-8bit", "news-bumper"):
            self.assertIn(want, [s["style"] for s in styles])
        types = js("audio", "sfx-types", "--json")
        self.assertGreaterEqual(len(types), 30)
        st("audio", "--help")
        for sub in ("compose", "sfx", "mix", "meter", "master", "beats", "fit", "musicgen"):
            self.assertIn("usage", st("audio", sub, "--help").stdout)
        for sub in ("fetch", "search", "info", "index", "credits", "stats", "sources", "generate"):
            self.assertIn("usage", st("audio", "lib", sub, "--help").stdout)

    # ------------------------------------------------------------------ compose
    def test_02_compose(self):
        for style, backend in (("upbeat-tech", "auto"), ("corporate-minimal", "auto"), ("lofi-chill", "auto")):
            out = self.tmp / ("%s.wav" % style)
            r = js("audio", "compose", "--style", style, "--dur", "10", "--sections", "0:intro,3:build,6:drop",
                   "--backend", backend, "--seed", "1", "-o", out, "--json")
            self.assertEqual(wav_frames(out), 480000, style)
            m = js("audio", "meter", out, "--json")
            self.assertAlmostEqual(m["integrated_lufs"], -14.0, delta=0.5, msg=style)
            self.assertLessEqual(m["true_peak_dbtp"], -1.0 + 1e-6, style)
            b = json.loads(out.with_name(out.stem + ".beats.json").read_text(encoding="utf-8"))
            downs = [round(t, 3) for t in b["downbeats"]]
            for sec in b["sections"]:
                self.assertIn(round(sec["start"], 3), downs, "%s: section %s not on a downbeat" % (style, sec["name"]))
            self.assertTrue(out.with_suffix(".mid").is_file())
            self.assertTrue((out.parent / (out.stem + ".stems")).is_dir())
            self.assertGreater(r["end_hit"], 6.0)
            self.assertLess(r["end_hit"], 10.0)
        # beat tracker recovers the composed tempo
        a = js("audio", "beats", self.tmp / "corporate-minimal.wav", "-o", "-", "--json")
        comp = json.loads((self.tmp / "corporate-minimal.beats.json").read_text(encoding="utf-8"))
        self.assertLess(abs(a["bpm"] - comp["bpm"]) / comp["bpm"], 0.03, (a["bpm"], comp["bpm"]))
        # fit: loop a 10 s track to exactly 25 s
        f = js("audio", "fit", self.tmp / "corporate-minimal.wav", "--dur", "25", "-o", self.tmp / "fit.wav", "--json")
        self.assertEqual(wav_frames(self.tmp / "fit.wav"), 25 * 48000)
        self.assertEqual(f["mode"], "loop")

    def test_02b_restrained_styles(self):
        """Benchmark r1: beds under a data report and a math explainer sounded like "the Sims" and "a DIY
        YouTube video" (corporate-minimal: glockenspiel motif, snare roll into a drop, crashes, tom fills,
        reverse cymbals). The calm styles add none of those gestures, `underscore` is the CLI default, and
        a chord held for two bars really lasts two bars (ambient-pad used to drop to silence every other bar)."""
        from st.audio import compose
        self.assertEqual(compose.resolve_style("documentary"), "underscore")
        secs = "0:intro,5:build,15:drop,24:outro"                  # the section map the data template used to ship
        for name in ("underscore", "minimal-pulse", "corporate-minimal", "ambient-pad", "piano-emotional"):
            st_ = compose.STYLES[name]
            self.assertTrue(st_.get("restrained"), name)
            self.assertNotIn(9, [r[0] for r in st_["roles"].values()], "%s: no glockenspiel" % name)
            C = compose.Composer(name, None, None, 32.0, compose.parse_sections(secs, 32.0), seed=1)
            C.compose()
            self.assertEqual([e for e in C.events if e["type"] != "end_hit"], [], name)   # no crash / riser / impact
            self.assertEqual(C.sfx, [], name)                                               # no transition SFX
            drums = {p for _, _, p, _ in C.notes["drums"]}
            G = compose.GM_DRUM
            self.assertFalse(drums & {G["crash"], G["snare"], G["tom_lo"], G["tom_mid"], G["tom_hi"]}, (name, drums))
        for name in ("underscore", "ambient-pad", "cinematic-build"):       # two bars per chord
            C = compose.Composer(name, None, None, 30.0, compose.parse_sections("0:intro,6:verse,20:outro", 30.0), seed=0)
            C.compose()
            covered = sorted((s, e) for s, e, _, _ in C.notes["pad"])
            t, gaps = 0.0, []
            for s, e in covered:
                if s > t + 0.05:
                    gaps.append((round(t, 2), round(s, 2)))
                t = max(t, e)
            self.assertEqual(gaps, [], "%s: the pad drops out between chords" % name)
        # the CLI default is the calm bed; a short render stays exact and mastered
        out = self.tmp / "default-style.wav"
        r = js("audio", "compose", "--dur", "8", "--backend", "synth", "-o", out, "--json")
        self.assertEqual(r["style"], "underscore")
        self.assertEqual(wav_frames(out), 8 * 48000)
        m = js("audio", "meter", out, "--json")
        self.assertAlmostEqual(m["integrated_lufs"], -14.0, delta=0.5)

    # ------------------------------------------------------------------ sfx
    def test_03_sfx(self):
        d = self.tmp / "sfx"
        d.mkdir(exist_ok=True)
        for t in ("whoosh", "riser", "impact", "click", "pop", "success", "glitch", "reverse-cymbal", "typing", "logo-sting"):
            m = js("audio", "sfx", t, "--key", "Am", "--seed", "2", "-o", d / ("%s.wav" % t))
            self.assertTrue((d / ("%s.wav" % t)).is_file())
            self.assertTrue((d / ("%s.sfx.json" % t)).is_file())
            self.assertGreaterEqual(m["hit"], 0.0)
            self.assertLessEqual(m["hit"], m["duration"] + 1e-6)
            self.assertLessEqual(m["peak_dbfs"], -1.0 + 1e-3, t)
            if m["kind"] == "end":
                self.assertAlmostEqual(m["hit"], m["duration"], delta=0.002)

    # ------------------------------------------------------------------ library
    def test_04_library_search(self):
        env = dict(ENV)
        env["SHOWTIME_LIBRARY"] = str(self.tmp / "library")      # throw-away library
        pack = self.tmp / "sfx"
        if not any(pack.glob("*.wav")):
            self.test_03_sfx()
        st("audio", "lib", "index", pack, "--name", "testpack", "--license", "CC0-1.0", env=env)
        res = js("audio", "lib", "search", "whoosh", "--json", env=env)
        self.assertTrue(res and "whoosh" in res[0]["id"], res[:1])
        res = js("audio", "lib", "search", "--kind", "sfx", "--license", "cc0", "--limit", "50", "--json", env=env)
        self.assertGreaterEqual(len(res), 10)
        info = js("audio", "lib", "info", res[0]["id"], "--json", env=env)
        self.assertTrue(info["exists"])
        # the real library, when installed (read-only)
        if (showtime_home() / "library" / "catalog.json").is_file():
            r = js("audio", "lib", "search", "--kind", "music", "--mood", "calm", "--min-dur", "20", "--json")
            self.assertTrue(r, "no calm music in the installed library")
            r = js("audio", "lib", "search", "whoosh", "--kind", "sfx", "--distinct", "--json")
            self.assertTrue(r, "no whoosh in the installed library")

    # ------------------------------------------------------------------ mix
    def test_05_mix(self):
        proj = self.tmp / "proj"
        (proj / "audio").mkdir(parents=True, exist_ok=True)
        (proj / "voice").mkdir(parents=True, exist_ok=True)
        (proj / "showtime.json").write_text('{"width": 1280, "height": 720, "fps": 30, "duration": 10}', encoding="utf-8")
        vo = proj / "voice" / "vo.wav"
        said = False
        if not FAST:
            cp = st("voice", "say", "Showtime mixes music, voice and effects on your machine. Every level is measured.",
                    "-o", vo, check=False, timeout=300)
            said = cp.returncode == 0 and vo.is_file()
        if not said:
            subprocess.run([PY, "-c", VOICE_SNIPPET, str(vo), "6.5", str(SKILL / "lib")], check=True, env=ENV)
        js("audio", "sfx", "whoosh", "--seed", "4", "-o", proj / "audio" / "whoosh.wav")
        spec = {
            "duration": 10.0,
            "tracks": [
                {"id": "bed", "kind": "music", "compose": {"style": "corporate-minimal", "sections": "0:intro,3:build,6:drop"},
                 "duck": {"under": "voice", "depth_db": 10, "carve": 0.4}},
                {"kind": "voice", "file": "voice/vo.wav", "start": 0.8},
                {"kind": "sfx", "file": "audio/whoosh.wav", "at": 3.0, "align": "hit"},
                {"kind": "sfx", "synth": {"type": "impact", "key": "G", "seed": 3}, "at": 6.0},
                {"kind": "sfx", "synth": {"type": "riser", "dur": 2.0, "key": "G"}, "at": 6.0, "gain_db": -3},
            ],
            "master": {"lufs": -14, "true_peak": -1},
        }
        (proj / "audio" / "mix.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
        rep = js("audio", "mix", proj / "audio" / "mix.json", "-o", proj / "audio" / "mix.wav", "--check", "--json")
        out = proj / "audio" / "mix.wav"
        self.assertEqual(wav_frames(out), 480000)
        self.assertAlmostEqual(rep["integrated_lufs"], -14.0, delta=0.5)
        self.assertLessEqual(rep["true_peak_dbtp"], -1.0 + 1e-6)
        ff = rep["ffmpeg_ebur128"]
        self.assertAlmostEqual(ff["integrated_lufs"], -14.0, delta=0.5)
        self.assertLessEqual(ff["true_peak_dbtp"], -1.0 + 1e-6)
        self.assertTrue((proj / "audio" / "mix.report.json").is_file())
        bed = next(t for t in rep["tracks"] if t["id"] == "bed")
        self.assertGreater(bed["duck"]["max_reduction_db"], 8)
        self.assertTrue(bed["carve"]["bands"])
        self.assertGreaterEqual(rep["voice_to_music_db"], 8.0)
        wh = next(t for t in rep["tracks"] if t.get("path", "").endswith("whoosh.wav"))
        sc = json.loads((proj / "audio" / "whoosh.sfx.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(wh["start"] + sc["hit"], 3.0, delta=0.002)   # the whoosh peak lands on 3.0 s
        self.assertGreaterEqual(len(rep["sections"]), 3)
        # musical landmarks of the composed bed are on the output timeline; sfx get an audibility figure
        self.assertIn("end_hit", bed)
        self.assertEqual([x["name"] for x in bed["music_sections"]][:3], ["intro", "build", "drop"])
        self.assertIn("soundfont_file", bed["compose"])      # the SoundFont actually used, for the license line
        self.assertIsNotNone(next(t for t in rep["tracks"] if t["kind"] == "sfx").get("above_bed_db"))
        # paths in the report are portable (relative to the report), never absolute
        saved = json.loads((proj / "audio" / "mix.report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["output"], "mix.wav")
        self.assertFalse(any(str(t.get("path") or "").startswith(("/", "\\")) or ":\\" in str(t.get("path") or "")
                             for t in saved["tracks"]), [t.get("path") for t in saved["tracks"]])
        # section_gain lifts one named section of a composed bed; gain_points automate any track
        spec["tracks"][0]["section_gain"] = {"intro": 6}
        spec["tracks"][2]["gain_points"] = [[0, -40], [10, -40]]
        spec["master"] = {"engine": "none"}
        (proj / "audio" / "mix2.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
        spec_plain = json.loads(json.dumps(spec))
        del spec_plain["tracks"][0]["section_gain"]
        (proj / "audio" / "mix3.json").write_text(json.dumps(spec_plain, indent=1), encoding="utf-8")
        r2 = js("audio", "mix", proj / "audio" / "mix2.json", "-o", proj / "audio" / "mix2.wav", "--json")
        r3 = js("audio", "mix", proj / "audio" / "mix3.json", "-o", proj / "audio" / "mix3.wav", "--json")
        m2 = next(x for x in r2["sections"] if x["name"] == "intro")["buses_rms_dbfs"]["music"]
        m3 = next(x for x in r3["sections"] if x["name"] == "intro")["buses_rms_dbfs"]["music"]
        self.assertAlmostEqual(m2 - m3, 6.0, delta=1.5)
        d2 = next(x for x in r2["sections"] if x["name"] == "drop")["buses_rms_dbfs"]["music"]
        d3 = next(x for x in r3["sections"] if x["name"] == "drop")["buses_rms_dbfs"]["music"]
        self.assertAlmostEqual(d2, d3, delta=0.5)
        wh2 = next(t for t in r2["tracks"] if str(t.get("path", "")).endswith("whoosh.wav"))
        self.assertEqual(wh2["gain_points"][0], [0.0, -40.0])
        self.assertTrue(any("masked" in w for w in r2["warnings"]), r2["warnings"])

    def test_05c_fit_from_offset(self):
        """08: `audio fit --from` starts on the nearest downbeat, and a fitted mix track with an `offset`
        uses a beat grid shifted by that offset (it used the file's own grid before)."""
        from st.audio import fit
        doc = {"downbeats": [0.0, 2.0, 4.0, 6.0, 8.0], "beats": [0.0, 0.5, 1.0, 2.0], "rhythmic": True,
               "sections": [{"name": "a", "start": 0, "end": 4}, {"name": "b", "start": 4, "end": 8}], "end_hit": 7.5}
        self.assertEqual(fit.snap_to_downbeat(doc, 4.7), 4.0)
        sh = fit.shift_beats(doc, 4.0)
        self.assertEqual(sh["downbeats"], [0.0, 2.0, 4.0])
        self.assertEqual([x["name"] for x in sh["sections"]], ["b"])
        self.assertEqual(sh["end_hit"], 3.5)
        bed = self.tmp / "bed-fit.wav"
        st("audio", "compose", "--style", "corporate-minimal", "--dur", "12", "-o", bed)
        r = js("audio", "fit", bed, "--dur", "5", "--from", "4.3", "--json")
        self.assertIn("from", r)
        self.assertAlmostEqual(r["target"], 5.0, places=2)

    def test_05d_keystroke_track(self):
        """01: a `keystrokes` track clicks once per typed character / key combo of a demo recording, mapped
        through rec_offset and rate onto the video timeline."""
        from st.audio import mix
        ev = {"events": [{"t": 8.0, "end": 8.5, "type": "type", "text": "abcde"}, {"t": 9.0, "type": "key", "keys": "Enter"}]}
        times = mix.keystroke_times(ev, offset=7.85, rate=1.75)
        self.assertEqual(len(times), 6)
        self.assertAlmostEqual(times[-1], (9.0 - 7.85) / 1.75, places=3)
        d = self.tmp / "keys"
        d.mkdir()
        (d / "events.json").write_text(json.dumps(ev), encoding="utf-8")
        spec = {"duration": 3.0, "tracks": [{"id": "keys", "kind": "sfx", "keystrokes": "events.json", "start": 0.5,
                                            "rec_offset": 7.85, "rate": 1.75}], "master": {"engine": "none"}}
        (d / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
        rep = js("audio", "mix", d / "mix.json", "-o", d / "mix.wav", "--json")
        tr = rep["tracks"][0]
        self.assertEqual(tr["source"], "keystrokes")
        self.assertGreater(rep["sections"][0]["rms_dbfs"], -80)

    def test_05e_masking_designed_layers(self):
        """Designed layers do not flood the masking check: keyclicks of one family never mask each other,
        a riser whose hit is its end is judged before its end, `texture` silences a track, and masked
        tracks of one family are one warning line."""
        d = self.tmp / "masking"
        d.mkdir(exist_ok=True)
        clicks = [{"id": "key-%02d" % k, "kind": "sfx", "synth": {"type": "keyclick", "seed": k % 6 + 1},
                   "at": round(0.4 + k * 0.055, 3)} for k in range(20)]
        riser = [{"id": "rise", "kind": "sfx", "synth": {"type": "riser", "dur": 1.5, "key": "G"}, "at": 2.5},
                 {"id": "boom", "kind": "sfx", "synth": {"type": "impact", "key": "G", "seed": 3}, "at": 2.5,
                  "gain_db": 6}]

        def mix(name, tracks):
            spec = {"duration": 3.5, "tracks": tracks, "master": {"engine": "none"}}
            (d / (name + ".json")).write_text(json.dumps(spec), encoding="utf-8")
            return js("audio", "mix", d / (name + ".json"), "-o", d / (name + ".wav"), "--json")
        r = mix("clicks", clicks + riser)
        self.assertFalse([w for w in r["warnings"] if "masked" in w], r["warnings"])
        # under a loud voice-like bed the clicks are masked: one grouped line, not 20
        vo = d / "vo.wav"
        subprocess.run([PY, "-c", VOICE_SNIPPET, str(vo), "3.5", str(SKILL / "lib")], check=True, env=ENV)
        bed = [{"id": "vo", "kind": "voice", "file": str(vo), "gain_db": 6}]
        quiet = [dict(c, gain_db=-24) for c in clicks]
        r = mix("under", bed + quiet)
        masked = [w for w in r["warnings"] if "masked" in w]
        self.assertEqual(len(masked), 1, masked)
        self.assertIn("texture", masked[0])
        r = mix("texture", bed + [dict(c, texture=True) for c in quiet])
        self.assertFalse([w for w in r["warnings"] if "masked" in w], r["warnings"])
        self.assertTrue(all(t.get("texture") for t in r["tracks"] if t["kind"] == "sfx"))

    def test_05f_typewriter_clicks(self):
        """15.4: a `typewriter` mix track clicks on the page component's own key times (same rng and cadence:
        checked against the component's JS when node is available)."""
        from st.audio import mix
        ops = [{"type": "npm create showtime\nok"}, {"pause": 0.3}, {"back": 3}, {"type": "yes"}]
        times, end = mix.typing_timeline(ops, cadence="human", cps=18, seed=7)
        self.assertEqual(len(times), len("npm create showtime\nok") + 3 + 3)
        uni, _ = mix.typing_timeline([{"type": "ab c"}], cadence="uniform", cps=10)
        self.assertEqual([round(t, 4) for t in uni], [0.1, 0.2, 0.42, 0.52])
        node = plat.find_tool("node", ENV.get("PATH"))
        if node:
            js_src = SKILL / "runtime" / "components" / "typewriter.js"
            code = ("import('%s').then(m => { const tl = m.typingTimeline(%s, {cadence: 'human', cps: 18, seed: 7});"
                    " console.log(JSON.stringify(tl.states.slice(1).map(s => s.t))); })"
                    % (js_src.as_uri(), json.dumps(ops)))
            cp = subprocess.run([node, "--input-type=module", "-e", code], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
            if cp.returncode == 0 and cp.stdout.strip():
                ref = json.loads(cp.stdout)
                self.assertEqual(len(ref), len(times))
                self.assertLess(max(abs(a - b) for a, b in zip(ref, times)), 1e-9)
        d = self.tmp / "tw"
        d.mkdir(exist_ok=True)
        spec = {"duration": 3.0, "tracks": [{"id": "keys", "kind": "sfx", "start": 0.5,
                                            "typewriter": {"text": "hello world", "cps": 14}}],
                "master": {"engine": "none"}}
        (d / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
        rep = js("audio", "mix", d / "mix.json", "-o", d / "mix.wav", "--json")
        self.assertEqual(rep["tracks"][0]["source"], "typewriter")
        self.assertGreater(rep["sections"][0]["rms_dbfs"], -80)

    def test_05g_licenses_search_fit_compose_notes(self):
        """19.6 a copied library file keeps its license (matched by content), a music file with no license
        info warns; 19.10 an ambience search also finds sfx loops, ranked lower; 19.5 fit says where it
        ends and --ending song keeps the track's ending; 17.2/18.7 compose notes; 22.12 the SoundFont used."""
        from st.audio import search
        env = dict(ENV)
        lib = self.tmp / "lib-lic"
        env["SHOWTIME_LIBRARY"] = str(lib)
        pack = self.tmp / "musicpack"
        pack.mkdir(exist_ok=True)
        st("audio", "compose", "--style", "lofi-chill", "--dur", "6", "--no-stems", "-o", pack / "calm-bed.wav")
        for p in pack.glob("calm-bed.*"):
            if p.suffix != ".wav":
                p.unlink() if p.is_file() else shutil.rmtree(str(p))
        st("audio", "lib", "index", pack, "--name", "bytest", "--kind", "music", "--license", "CC-BY-4.0",
           "--attribution", "Calm Bed by Test Artist (CC BY 4.0)", env=env)
        proj = self.tmp / "lic-proj"
        (proj / "audio").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(pack / "calm-bed.wav"), str(proj / "audio" / "copied.wav"))
        st("audio", "compose", "--style", "lofi-chill", "--dur", "6", "--seed", "9", "--no-stems",
           "-o", proj / "audio" / "mystery.wav")
        for side in ("mystery.wav.license.json", "mystery.beats.json", "mystery.mid"):   # a bare file of unknown origin
            (proj / "audio" / side).unlink(missing_ok=True)
        spec = {"duration": 5.0, "tracks": [{"id": "bed", "kind": "music", "file": "copied.wav"}],
                "master": {"engine": "none"}}
        (proj / "audio" / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
        rep = js("audio", "mix", proj / "audio" / "mix.json", "-o", proj / "audio" / "mix.wav", "--json", env=env)
        self.assertTrue(rep["tracks"][0].get("matched_library"), rep["tracks"][0])
        self.assertIn("Calm Bed by Test Artist (CC BY 4.0)", rep["credits"])
        spec["tracks"][0]["file"] = "mystery.wav"
        (proj / "audio" / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
        rep = js("audio", "mix", proj / "audio" / "mix.json", "-o", proj / "audio" / "mix.wav", "--json", env=env)
        self.assertTrue(any("no license information" in w for w in rep["warnings"]), rep["warnings"])
        # a license sidecar next to the file is enough
        (proj / "audio" / "mystery.wav.license.json").write_text(json.dumps(
            {"license": "CC0-1.0", "attribution_required": False}), encoding="utf-8")
        rep = js("audio", "mix", proj / "audio" / "mix.json", "-o", proj / "audio" / "mix.wav", "--json", env=env)
        self.assertFalse(any("no license information" in w for w in rep["warnings"]), rep["warnings"])
        self.assertEqual(rep["tracks"][0]["license"], "CC0-1.0")
        # ambience search: an sfx loop is found, below a real ambience item
        cat = {"items": [
            {"id": "a/rain-ambience", "kind": "ambience", "title": "rain", "tags": ["rain"], "duration": 10.0},
            {"id": "b/loop-rain-02", "kind": "sfx", "title": "loop rain 02", "tags": ["foley"], "duration": 7.0},
            {"id": "b/rain-drop", "kind": "sfx", "title": "rain drop", "tags": ["foley"], "duration": 0.4}]}
        res = [r["id"] for r in search.search("rain", kind="ambience", catalog=cat)]
        self.assertEqual(res, ["a/rain-ambience", "b/loop-rain-02"])
        # fit: where it ends, and the song's own ending
        long = self.tmp / "long.wav"
        st("audio", "compose", "--style", "corporate-minimal", "--dur", "30", "--no-stems", "-o", long)
        a = js("audio", "fit", long, "--dur", "13", "-o", self.tmp / "fa.wav", "--json")
        self.assertEqual(a["ending"], "downbeat")
        self.assertIn("bars", a)
        b = js("audio", "fit", long, "--dur", "13", "--ending", "song", "-o", self.tmp / "fb.wav", "--json")
        self.assertEqual(b["ending"], "song")
        self.assertEqual(wav_frames(self.tmp / "fb.wav"), 13 * 48000)
        self.assertLess(b["end_hit"], 13.0)
        # compose: a marker inside the ring-out is reported; the SoundFont used is recorded
        r = js("audio", "compose", "--style", "epic-trailer", "--dur", "12", "--sections", "0:intro,5:drop,11.5:outro",
               "--no-stems", "-o", self.tmp / "notes.wav", "--json")
        self.assertTrue(any("outro" in n and "ending" in n for n in r["plan_notes"]), r["plan_notes"])
        bj = json.loads((self.tmp / "notes.beats.json").read_text(encoding="utf-8"))
        self.assertEqual(bj["soundfont"], r["soundfont"])
        self.assertIn("backend", bj)

    # ------------------------------------------------------------------ master
    def test_06_master(self):
        src = self.tmp / "quiet.wav"
        subprocess.run([PY, "-c", VOICE_SNIPPET, str(src), "4", str(SKILL / "lib")], check=True, env=ENV)
        rep = js("audio", "master", src, "-o", self.tmp / "loud.wav", "--preset", "voice", "--json")
        self.assertAlmostEqual(rep["after"]["integrated_lufs"], -14.0, delta=0.3)
        self.assertLessEqual(rep["after"]["true_peak_dbtp"], -1.0 + 1e-6)

    # ------------------------------------------------------------------ round-3 polish
    def test_07_credits_name_and_help(self):
        """Mix credits are always `credits.txt` (render/qa's name; one file on case-sensitive systems);
        every audio listing command has --help examples."""
        out = subprocess.run([PY, "-c", r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from st.audio.mix import credits_file
d = Path(sys.argv[1])
d.mkdir(parents=True, exist_ok=True)
(d / "CREDITS.txt").write_text("old", encoding="utf-8")
p = credits_file(d)
print(json.dumps({"path": p.name, "names": sorted(x.name for x in d.iterdir()), "text": p.read_text(encoding="utf-8")}))
""", str(self.tmp / "cred"), str(SKILL / "lib")], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             encoding="utf-8", check=True).stdout
        d = json.loads(out)
        self.assertEqual(d["path"], "credits.txt")
        self.assertEqual(d["names"], ["credits.txt"])      # renamed, not duplicated
        self.assertEqual(d["text"], "old")
        src = (SKILL / "lib" / "st" / "audio" / "mix.py").read_text(encoding="utf-8")
        self.assertNotIn('"CREDITS.txt"', src)
        for sub in (["styles"], ["sfx-types"], ["lib", "info"], ["lib", "credits"], ["lib", "stats"],
                    ["lib", "sources"], ["lib", "generate"]):
            h = st("audio", *sub, "--help").stdout
            self.assertIn("Example", h, sub)
            self.assertIn("showtime audio " + " ".join(sub), h, sub)


    # ------------------------------------------------------------------ final pass: parallel renders, license
    def test_08_parallel_mixes_share_the_cache(self):
        """Three renders of one project (16:9, 1:1, 9:16) mix at the same moment: synth hits, a typewriter and
        a composed bed land in the shared cache without a collision (a per-process temp name + atomic
        rename, a lock per entry), every mix succeeds and they are identical. No temp or lock file is left."""
        import numpy as np
        import soundfile as sf
        d = self.tmp / "par"
        d.mkdir(exist_ok=True)
        seed = int(time.time() * 1000) % 1000000 + 11          # new cache entries: the race really happens
        spec = {"duration": 6.0, "tracks": [
            {"id": "bed", "kind": "music", "compose": {"style": "underscore", "seed": seed, "backend": "synth"}},
            {"id": "keys", "kind": "sfx", "start": 0.5, "typewriter": {"text": "parallel %d" % seed, "cps": 14}}]
            + [{"id": "s%d" % k, "kind": "sfx", "synth": {"type": t, "seed": seed + k, "intensity": 0.6},
                "at": 1.0 + 0.7 * k, "align": "hit"}
               for k, t in enumerate(("whoosh", "impact", "pop", "click", "riser", "success"))],
            "master": {"lufs": -14}}
        (d / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
        cache = showtime_home() / "cache" / "audio"
        t_start = time.time() - 2
        procs = [subprocess.Popen([sys.executable, str(LAUNCHER), "audio", "mix", str(d / "mix.json"), "-o",
                                   str(d / ("out%d.wav" % i)), "--json"], env=ENV, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, encoding="utf-8", errors="replace") for i in range(3)]
        outs = [p.communicate(timeout=600) for p in procs]
        for p, (o, e) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, e[-2000:])
        a = [sf.read(str(d / ("out%d.wav" % i)), dtype="float32")[0] for i in range(3)]
        self.assertEqual(a[0].shape, (6 * 48000, 2))
        for x in a[1:]:
            self.assertTrue(np.array_equal(a[0], x), "parallel mixes differ")
        # temp/lock files these mixes made (after t_start) must be gone. Under run_all -j another test file
        # may be filling its own cache entry right now: its temp/lock is transient, so wait for it to go.
        def leftovers():
            out = []
            for q in cache.rglob("*"):
                try:
                    if (".part" in q.name or q.name.endswith(".lock")) and q.stat().st_mtime >= t_start:
                        out.append(q.name)
                except OSError:  # removed while we looked: transient
                    pass
            return out
        deadline = time.time() + 180
        left = leftovers()
        while left and time.time() < deadline:
            time.sleep(1)
            left = leftovers()
        self.assertEqual(left, [])

    def test_09_simple_mixer_and_loud_fallback(self):
        """The built-in mixer (used when the audio module fails on a files-only mix) renders every track as its
        own aligned stem: parallel runs of a 4-file mix that uses one file twice, 45 s apart, never hang (one
        ffmpeg graph with all the files deadlocked in ffmpeg 9). A mix with synth tracks that fails is an
        error, not a silent fallback that drops the synthesized sounds."""
        node = plat.find_tool("node", ENV.get("PATH"))
        if not node:
            self.skipTest("node not found")
        d = self.tmp / "simple"
        (d / "a").mkdir(parents=True, exist_ok=True)
        st("audio", "sfx", "logo-sting", "--seed", "3", "-o", d / "a" / "sting.wav")
        st("audio", "compose", "--dur", "12", "--backend", "synth", "--seed", "4", "--no-stems", "-o", d / "a" / "bed.wav")
        spec = {"duration": 50.0, "tracks": [
            {"kind": "music", "file": "a/sting.wav", "start": 0, "dur": 1.2, "fade_out": 0.3},
            {"kind": "music", "file": "a/bed.wav", "start": 1.0, "loop": True, "fade_in": 0.3, "duck": {"under": ["x"]}},
            {"kind": "music", "file": "a/bed.wav", "start": 20.0, "offset": 2.0, "dur": 5, "gain_db": -6},
            {"kind": "music", "file": "a/sting.wav", "start": 46.5, "gain_db": -3}]}
        lib = (SKILL / "scripts" / "lib" / "audio.mjs").as_uri()
        code = ("const m = await import(%s); const fs = await import('node:fs');"
                "const spec = JSON.parse(process.argv[1]); const w = [];"
                "const r = await m.simpleMix(spec, process.argv[2], 50, process.argv[3], (x) => w.push(x));"
                "console.log(JSON.stringify({r, w, size: fs.statSync(process.argv[3]).size}));") % json.dumps(lib)
        for rnd in range(4):
            procs = [subprocess.Popen([node, "--input-type=module", "-e", code, json.dumps(spec), str(d),
                                       str(d / ("simple-%d-%d.wav" % (rnd, i)))], env=ENV, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, encoding="utf-8") for i in range(3)]
            for p in procs:
                try:
                    o, e = p.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    p.kill()
                    self.fail("the simple mixer hung (round %d)" % rnd)
                self.assertEqual(p.returncode, 0, e[-1500:])
                res = json.loads(o.strip().splitlines()[-1])
                self.assertEqual(res["r"]["kind"], "mix(4 files)")
                self.assertTrue(any("duck" in x for x in res["w"]), res["w"])
                self.assertEqual(wav_frames(Path(d / ("simple-%d-%d.wav" % (rnd, 0)))), 50 * 48000)
        self.assertEqual([p.name for p in d.glob(".simple-*")], [])       # stems are cleaned up
        # the stems line up with the timeline: the closing sting plays at 46.5 s
        import soundfile as sf
        import numpy as np
        x, _ = sf.read(str(d / "simple-0-0.wav"), dtype="float32")
        self.assertGreater(np.abs(x[int(46.6 * 48000):int(47.5 * 48000)]).max(), 0.01)   # the late sting plays
        # a failed mix that has synth tracks stops the render instead of shipping a different soundtrack
        bad = {"duration": 3.0, "tracks": [{"kind": "sfx", "synth": {"type": "no-such-sfx"}, "at": 1}]}
        code2 = ("const m = await import(%s);"
                 "try { await m.mixFromConfig(JSON.parse(process.argv[1]), process.argv[2], 3, process.argv[3], process.argv[2], (x) => console.log('WARN ' + x));"
                 "console.log('NO-ERROR'); } catch (e) { console.log('ERROR ' + e.message + ' | ' + (e.hint || '')); }") % json.dumps(lib)
        cp = subprocess.run([node, "--input-type=module", "-e", code2, json.dumps(bad), str(d), str(d / "bad.wav")], env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=300)
        self.assertIn("ERROR the audio mix failed", cp.stdout, cp.stdout + cp.stderr)
        self.assertIn("synth/compose track", cp.stdout)
        self.assertIn("sfx", cp.stdout.split("|")[0])                      # the real error, not the fix line
        self.assertNotIn("WARN", cp.stdout)

    def test_10_composed_bed_has_a_license(self):
        """`audio compose` writes <file>.license.json (generated, no attribution): a mix that uses the composed
        file directly does not warn about missing license information (older beds: via their beats.json)."""
        d = self.tmp / "lic"
        d.mkdir(exist_ok=True)
        r = js("audio", "compose", "--dur", "6", "--backend", "synth", "--no-stems", "-o", d / "bed.wav", "--json")
        side = d / "bed.wav.license.json"
        self.assertEqual(r["outputs"]["license"], str(side))
        lic = json.loads(side.read_text(encoding="utf-8"))
        self.assertEqual((lic["license"], lic["attribution_required"]), ("generated", False))
        from st.assets import licenses
        self.assertEqual(licenses.classify("generated"), licenses.FREE)
        spec = {"duration": 6.0, "tracks": [{"id": "bed", "kind": "music", "file": "bed.wav"}], "master": {"engine": "none"}}
        (d / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
        for rnd in ("sidecar", "beats.json"):
            rep = js("audio", "mix", d / "mix.json", "-o", d / "mix.wav", "--json")
            self.assertFalse([w for w in rep.get("warnings", []) if "license" in w], (rnd, rep.get("warnings")))
            self.assertEqual(rep["tracks"][0].get("license"), "generated", rnd)
            side.unlink(missing_ok=True)

if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_audio: %.1fs" % (time.time() - t0))
    sys.exit(0 if prog.result.wasSuccessful() else 1)
