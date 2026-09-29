#!/usr/bin/env python3
"""Produced-music catalog, lazy fetch + cache, credits pipeline and extra sound packs (runs in seconds).

- the shipped catalog validates: 150+ tracks, every shelf stocked (12+), only CC BY / CC0 / PD, exact
  credit formats (Scott Buckley, Kevin MacLeod), Content ID status, no refused hosts, no Jamendo
- the quality gate record: thresholds in the catalog, every track measured (intro, lead-in silence,
  highlight, ending) and inside the thresholds the catalog can show; the featured track leads `--for launch`
- validation catches bad entries (NC license, missing credit, foreign host, bad sha256 ...)
- selection: presets (launch, explainer ...), length ranking, vetoes, words
- fetch: announced download from a local HTTP server, sha256 verification, cache hits, corrupt cache,
  upstream change, offline with and without cache, seed folders
- credits: credits.txt, description block (upsert keeps the user's text), end card, Content ID note,
  a CC BY item without credit fails loudly, re-reading our own file does not duplicate lines
- mix: a {"catalog": id} track is fetched, mixed and credited (report credit_items, credits.txt);
  a CC BY file without credit stops the mix; a catalog track skips its lead-in silence by default and
  `"offset": "highlight"` starts at its highlight
- Openverse: Freesound + Wikimedia by default, Jamendo only on request (no network: a stub answers)
- sound packs: sfx_packs.json validates and covers the sounds videos need most; a pack is installed on
  first use by a mix reference
- CLI: `audio music search/pick/info/check/presets`, `audio credits`, `audio packs list`

No network: fixtures are served from 127.0.0.1. SHOWTIME_TEST_NETWORK=1 adds a few HEAD checks of real
catalog URLs and one Openverse query.

usage: python tests/test_music.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import contextlib
import copy
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402
from st.common import ShowtimeError  # noqa: E402
from st.audio import credits as cr  # noqa: E402
from st.audio import music, packs  # noqa: E402

NETWORK = os.environ.get("SHOWTIME_TEST_NETWORK") == "1"
FAST = "--fast" in sys.argv


# ------------------------------------------------------------------------------------------ fixtures
class _Handler(http.server.SimpleHTTPRequestHandler):
    hits: dict = {}

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        _Handler.hits[self.path] = _Handler.hits.get(self.path, 0) + 1
        return super().do_GET()


@contextlib.contextmanager
def serve(folder: Path):
    handler = lambda *a, **k: _Handler(*a, directory=str(folder), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def tone_wav(path: Path, seconds: float = 2.0, freq: float = 440.0) -> bytes:
    """A small 48 kHz stereo 16-bit WAV (stdlib only)."""
    import math
    import struct
    import wave
    n = int(48000 * seconds)
    frames = bytearray()
    for i in range(n):
        v = int(9000 * math.sin(2 * math.pi * freq * i / 48000) * min(1.0, i / 2400, (n - i) / 2400))
        frames += struct.pack("<hh", v, v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(frames))
    return path.read_bytes()


def fixture_catalog(base_url: str, blob: bytes) -> dict:
    cat = copy.deepcopy(music.load_catalog(music.CATALOG))
    sha = hashlib.sha256(blob).hexdigest()
    t = {"id": "buckley-fixture-hands", "title": "Fixture Hands", "artist": "Scott Buckley", "source": "buckley",
         "landing_url": "https://www.scottbuckley.com.au/library/fixture/", "file_url": base_url + "/fixture.wav",
         "format": "wav", "bytes": len(blob), "sha256": sha, "license": "CC-BY-4.0",
         "license_url": "https://creativecommons.org/licenses/by/4.0/",
         "attribution": "'Fixture Hands' by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au",
         "credit_optional": None, "placements": ["description", "credits_file", "end_card"],
         "content_id": "smart-cid-releasable", "duration": 2.0, "shelf": "inspiring", "moods": ["hopeful"],
         "energy": 0.5, "tempo": "slow", "uses": ["launch"], "vocals": "none", "instruments": ["sine"],
         "ending": "clean", "loops": None, "status": "active", "verified": "2026-09-28",
         "quiet_intro_s": 0.0, "lead_silence_s": 0.0, "highlight_s": 0.5}
    cc0 = dict(t, id="pd-fixture-calm", title="Fixture Calm", artist="Nobody", source="incompetech",
               license="CC0-1.0", license_url="https://creativecommons.org/publicdomain/zero/1.0/", attribution=None,
               credit_optional="Fixture Calm by Nobody (CC0)", content_id="none-known", shelf="ambient",
               file_url=base_url + "/calm.wav", uses=["explainer"], energy=0.2)
    cat["tracks"] = [t, cc0]
    return cat


class Env:
    """A throw-away SHOWTIME_HOME / music cache / catalog for one test."""

    def __init__(self, cat: dict):
        self.dir = Path(tempfile.mkdtemp(prefix="st-music-"))
        self.cat_path = self.dir / "catalog.json"
        self.cat_path.write_text(json.dumps(cat), encoding="utf-8")
        self.old = {k: os.environ.get(k) for k in ("SHOWTIME_MUSIC_CATALOG", "SHOWTIME_MUSIC_CACHE", "SHOWTIME_OFFLINE",
                                                   "SHOWTIME_SEED_DIRS", "SHOWTIME_LIBRARY", "SHOWTIME_SFX_PACKS")}

    def __enter__(self):
        os.environ["SHOWTIME_MUSIC_CATALOG"] = str(self.cat_path)
        os.environ["SHOWTIME_MUSIC_CACHE"] = str(self.dir / "cache")
        os.environ["SHOWTIME_LIBRARY"] = str(self.dir / "library")
        for k in ("SHOWTIME_OFFLINE", "SHOWTIME_SEED_DIRS", "SHOWTIME_SFX_PACKS"):
            os.environ.pop(k, None)
        music._CAT.clear()
        music._last_hit.clear()
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        music._CAT.clear()
        shutil.rmtree(self.dir, ignore_errors=True)


def launcher(*args, env=None, check=True):
    e = dict(build_env(showtime_home()))
    e.update(env or {})
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=e, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                   cp.stdout[-2000:], cp.stderr[-2000:]))
    return cp


# ------------------------------------------------------------------------------------------ tests
class CatalogTests(unittest.TestCase):
    def setUp(self):
        music._CAT.clear()
        os.environ.pop("SHOWTIME_MUSIC_CATALOG", None)
        self.cat = music.load_catalog()

    def test_01_shipped_catalog_validates(self):
        self.assertEqual(music.validate(self.cat), [])
        ts = self.cat["tracks"]
        self.assertGreaterEqual(len(ts), 150)
        shelves = {}
        for t in ts:
            shelves[t["shelf"]] = shelves.get(t["shelf"], 0) + 1
        self.assertEqual(set(shelves), set(music.SHELVES), shelves)
        for s, n in shelves.items():
            self.assertGreaterEqual(n, 12, "shelf %s has only %d tracks" % (s, n))
        self.assertNotIn("jamendo", self.cat["sources"])
        self.assertFalse([t["id"] for t in ts if "jamendo" in t["file_url"] or t["source"] == "jamendo"])

    def test_01b_quality_gate(self):
        """Every track was measured and admitted by the gate recorded in the catalog."""
        qg = self.cat["quality_gate"]
        f = qg["fail_if"]
        for k in ("sample_rate_hz_below", "bitrate_kbps_below", "bandwidth_khz_below", "stereo_side_db_below",
                  "clipped_runs_per_min_above", "steady_hiss_db_re_body_above", "offbeat_clicks_per_min_above",
                  "loudness_range_lu_above", "lead_silence_s_above", "internal_silence_s_above", "duration_s_below"):
            self.assertIn(k, f)
        self.assertTrue(qg["checked"] and qg["notes"])
        for t in self.cat["tracks"]:
            self.assertGreaterEqual(t["duration"], f["duration_s_below"], t["id"])
            self.assertLessEqual(t["lead_silence_s"], f["lead_silence_s_above"], t["id"])
            self.assertTrue(0 <= t["highlight_s"] < t["duration"], t["id"])
            self.assertTrue(0 <= t["quiet_intro_s"] < t["duration"], t["id"])
        # the measured fields are required
        cat = copy.deepcopy(self.cat)
        t = dict(cat["tracks"][0])
        del t["highlight_s"]
        cat["tracks"] = [t]
        self.assertTrue(any("highlight_s" in e for e in music.validate(cat)))
        cat = copy.deepcopy(self.cat)
        del cat["quality_gate"]
        self.assertTrue(any("quality_gate" in e for e in music.validate(cat)))
        # the featured track is kept, and leads a launch pick at typical lengths
        wth = music.get("buckley-with-these-hands", self.cat)
        self.assertTrue(wth.get("featured"))
        for dur in (30, 45, 90):
            self.assertEqual(music.pick("launch", dur=dur, cat=self.cat)["id"], "buckley-with-these-hands", dur)
        # short-form presets start quickly
        for use in ("launch", "explainer", "social", "promo"):
            lim = self.cat["presets"][use]["max_intro_s"]
            top = music.pick(use, dur=45, cat=self.cat)
            self.assertLessEqual(top["quiet_intro_s"], lim, (use, top["id"]))

    def test_02_license_rules(self):
        allowed = set(music.LICENSES)
        for t in self.cat["tracks"]:
            self.assertIn(t["license"], allowed, t["id"])
            self.assertNotRegex(t["license"], r"NC|ND|SA", t["id"])
            if t["license"].startswith("CC-BY"):
                self.assertTrue(t["attribution"], t["id"])
                self.assertIn("description", t["placements"], t["id"])
                self.assertIn("credits_file", t["placements"], t["id"])
            src = self.cat["sources"][t["source"]]
            self.assertEqual(t["content_id"], src["content_id"], t["id"])
        # exact credit formats the creators ask for
        b = music.get("buckley-with-these-hands", self.cat)
        self.assertEqual(b["attribution"], "'With These Hands' by Scott Buckley - released under CC-BY 4.0. "
                                           "www.scottbuckley.com.au")
        self.assertEqual(b["content_id"], "smart-cid-releasable")
        m = next(t for t in self.cat["tracks"] if t["source"] == "incompetech")
        self.assertEqual(m["attribution"].splitlines(), ["%s Kevin MacLeod (incompetech.com)" % m["title"],
                                                         "Licensed under Creative Commons: By Attribution 4.0",
                                                         "https://creativecommons.org/licenses/by/4.0/"])
        self.assertIn("jamendo.com", music.REFUSED_HOSTS)
        for t in self.cat["tracks"]:
            for host in music.REFUSED_HOSTS:
                self.assertNotIn(host, t["file_url"])

    def test_02b_doctor_knows_the_audio_hosts(self):
        """Sandboxed agents are told every host audio comes from (fix lines list them)."""
        from st import sandbox
        hosts = sandbox.download_hosts()
        for h in ("www.scottbuckley.com.au", "incompetech.com", "upload.wikimedia.org", "archive.org",
                  "api.openverse.org", "cdn.freesound.org", "opengameart.org", "kenney.nl", "bigsoundbank.com"):
            self.assertIn(h, hosts)
        self.assertFalse([h for h in hosts if "jamendo" in h], hosts)
        import urllib.parse
        for t in self.cat["tracks"]:
            self.assertIn(urllib.parse.urlparse(t["file_url"]).hostname, hosts, t["id"])

    def test_03_validation_catches_bad_entries(self):
        good = self.cat["tracks"][0]
        cases = {
            "license": ("CC-BY-NC-4.0", "not allowed"),
            "attribution": ("", "needs an attribution"),
            "file_url": ("https://example.com/x.mp3", "not one of source"),
            "sha256": ("abc", "sha256"),
            "shelf": ("vaporwave", "shelf"),
            "energy": (1.5, "energy"),
        }
        for field, (value, needle) in cases.items():
            cat = copy.deepcopy(self.cat)
            t = dict(good)
            t[field] = value
            cat["tracks"] = [t]
            errs = music.validate(cat)
            self.assertTrue(any(needle in e for e in errs), (field, errs))
        cat = copy.deepcopy(self.cat)
        cat["tracks"] = [dict(good, file_url="https://cdn.pixabay.com/audio/x.mp3")]
        self.assertTrue(any("not allowed" in e for e in music.validate(cat)))
        cat["tracks"] = [dict(good), dict(good)]
        self.assertTrue(any("duplicate id" in e for e in music.validate(cat)))

    def test_04_selection(self):
        launch = music.search(use="launch", limit=20, cat=self.cat)
        self.assertTrue(launch)
        pre = self.cat["presets"]["launch"]
        for r in launch:
            self.assertIn(r["track"]["shelf"], pre["shelves"])
            self.assertLessEqual(r["track"]["energy"], pre["energy"][1] + 0.1)
        ex = music.search(use="explainer", limit=30, cat=self.cat)
        self.assertTrue(ex)
        for r in ex:
            self.assertEqual(r["track"]["vocals"], "none")
            self.assertLessEqual(r["track"]["energy"], 0.55)
        # a 5-minute video prefers tracks that cover it
        long_ = music.search(use="documentary", dur=300, limit=5, cat=self.cat)
        self.assertTrue(all(r["track"]["duration"] >= 240 for r in long_[:3]), [r["track"]["duration"] for r in long_])
        words = music.search("hands", cat=self.cat)
        self.assertEqual(words[0]["track"]["id"], "buckley-with-these-hands")
        self.assertNotEqual(music.pick("launch", n=0, cat=self.cat)["id"], music.pick("launch", n=1, cat=self.cat)["id"])
        self.assertEqual(music.get("With These Hands", self.cat)["id"], "buckley-with-these-hands")
        with self.assertRaises(ShowtimeError):
            music.search(use="nonsense", cat=self.cat)

    def test_05_vetoes(self):
        with Env(self.cat):
            best = music.pick("launch")["id"]
            music.veto([best], reason="too loud")
            self.assertNotEqual(music.pick("launch")["id"], best)
            self.assertIn(best, [r["track"]["id"] for r in music.search(use="launch", include_vetoed=True, limit=50)])
            music.veto([best], undo=True)
            self.assertEqual(music.pick("launch")["id"], best)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.srv_dir = Path(tempfile.mkdtemp(prefix="st-music-srv-"))
        self.blob = tone_wav(self.srv_dir / "fixture.wav")
        (self.srv_dir / "calm.wav").write_bytes(self.blob)      # the fixture catalog pins both to the same bytes

    def tearDown(self):
        shutil.rmtree(self.srv_dir, ignore_errors=True)

    def test_10_fetch_cache_verify(self):
        from st import common
        logs = []
        orig = common.log
        with serve(self.srv_dir) as url, Env(fixture_catalog(url, self.blob)) as env:
            music.log = logs.append
            try:
                t = music.get("buckley-fixture-hands")
                self.assertFalse(music.is_cached(t))
                p = music.fetch(t, purpose="a test video")
                self.assertTrue(p.is_file() and music.is_cached(t))
                self.assertEqual(p.read_bytes(), self.blob)
                self.assertTrue(any("fetching Fixture Hands by Scott Buckley" in l and "for a test video" in l for l in logs), logs)
                side = json.loads(p.with_name(p.name + ".license.json").read_text(encoding="utf-8"))
                self.assertEqual(side["license"], "CC-BY-4.0")
                hits = dict(_Handler.hits)
                music.fetch(t)                                        # cached: no request
                self.assertEqual(_Handler.hits, hits)
                # offline with the cache works; without it fails with the fix
                os.environ["SHOWTIME_OFFLINE"] = "1"
                self.assertEqual(music.fetch(t), p)
                with self.assertRaises(ShowtimeError) as cm:
                    music.fetch("pd-fixture-calm")
                self.assertIn("audio music fetch pd-fixture-calm", cm.exception.hint or "")
                os.environ.pop("SHOWTIME_OFFLINE")
                # a corrupted cache is noticed and re-downloaded
                p.write_bytes(b"x" * len(self.blob))
                self.assertTrue(music.is_cached(t))                   # size + marker still match ...
                music._ok_marker(p).write_text("0" * 64, encoding="ascii")
                self.assertFalse(music.is_cached(t))                  # ... until the marker does not
                self.assertEqual(music.fetch(t).read_bytes(), self.blob)
                # the file changed upstream: refused, nothing left behind
                (self.srv_dir / "fixture.wav").write_bytes(self.blob[:-2] + b"\x01\x02")
                shutil.rmtree(env.dir / "cache")
                with self.assertRaises(ShowtimeError) as cm:
                    music.fetch(t)
                self.assertIn("changed upstream", str(cm.exception))
                self.assertFalse(music.cached_path(t).exists())
                self.assertEqual([x for x in music.cached_path(t).parent.iterdir() if x.name.endswith(".part")], [])
            finally:
                music.log = orig

    def test_11_seed_folder(self):
        seed = self.srv_dir / "seed"
        seed.mkdir()
        (seed / "fixture.wav").write_bytes(self.blob)
        with Env(fixture_catalog("http://127.0.0.1:9", self.blob)):     # nothing listens there
            os.environ["SHOWTIME_OFFLINE"] = "1"
            try:
                p = music.fetch("buckley-fixture-hands", seeds=[str(seed)])
                self.assertEqual(p.read_bytes(), self.blob)
            finally:
                os.environ.pop("SHOWTIME_OFFLINE", None)

    def test_12_mix_uses_and_credits_catalog_track(self):
        from st.audio import mix
        with serve(self.srv_dir) as url, Env(fixture_catalog(url, self.blob)) as env:
            d = env.dir / "proj"
            d.mkdir()
            spec = {"duration": 3.0, "tracks": [{"id": "bed", "kind": "music", "catalog": {"use": "launch"}, "fit": True},
                                                {"kind": "music", "catalog": "pd-fixture-calm", "start": 1.0, "gain_db": -6}],
                    "master": {"engine": "none"}}
            (d / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
            rep = mix.render(d / "mix.json", d / "mix.wav")
            self.assertEqual(rep["catalog_items"], ["buckley-fixture-hands", "pd-fixture-calm"])
            ids = [c["id"] for c in rep["credit_items"]]
            self.assertIn("music:buckley-fixture-hands", ids)
            self.assertEqual(rep["credits"], ["'Fixture Hands' by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au"])
            txt = (d / "credits.txt").read_text(encoding="utf-8")
            self.assertIn(rep["credits"][0], txt)
            self.assertIn("Fixture Calm by Nobody (CC0)", txt)        # courtesy credit, not required
            self.assertIn("Smart Content ID", txt)
            # `audio credits --report` (what render runs) writes credits.txt + the share.txt block
            job = env.dir / "job"
            job.mkdir()
            (job / "share.txt").write_text("Meet the new thing.\n", encoding="utf-8")
            res = cr.write(job, cr.items_from_report(d / "mix.report.json"))
            share = (job / "share.txt").read_text(encoding="utf-8")
            self.assertTrue(share.startswith("Meet the new thing.\n"))
            self.assertIn(cr.BLOCK_START, share)
            self.assertIn("Scott Buckley - released under CC-BY 4.0", share)
            self.assertTrue(res["notes"] and "description" in res["notes"][0])
            # the catalog file copied into the project and mixed as a plain file keeps its credit
            shutil.copyfile(str(music.cached_path(music.get("buckley-fixture-hands"))), str(d / "copied.wav"))
            spec3 = {"duration": 2.0, "tracks": [{"kind": "music", "file": "copied.wav"}], "master": {"engine": "none"}}
            (d / "mix3.json").write_text(json.dumps(spec3), encoding="utf-8")
            rep3 = mix.render(d / "mix3.json", d / "mix3.wav")
            self.assertEqual(rep3["credits"], rep["credits"])
            self.assertTrue(rep3["tracks"][0].get("matched_catalog"))
            # a CC BY file with no credit text stops the mix
            f = d / "cc-by.wav"
            f.write_bytes(self.blob)
            (d / "cc-by.wav.license.json").write_text(json.dumps({"license": "CC-BY-4.0", "attribution_required": True}),
                                                       encoding="utf-8")
            spec2 = {"duration": 2.0, "tracks": [{"kind": "music", "file": "cc-by.wav"}], "master": {"engine": "none"}}
            (d / "mix2.json").write_text(json.dumps(spec2), encoding="utf-8")
            with self.assertRaises(ShowtimeError) as cm:
                mix.render(d / "mix2.json", d / "mix2.wav")
            self.assertIn("need attribution", str(cm.exception))

    def test_12b_catalog_offsets(self):
        """Lead-in silence is skipped by default; "highlight" starts at the measured highlight."""
        from st.audio import mix
        with serve(self.srv_dir) as url:
            cat = fixture_catalog(url, self.blob)
            cat["tracks"][0]["lead_silence_s"] = 0.6
            with Env(cat) as env:
                d = env.dir / "proj"
                d.mkdir()
                runs = {"default": {}, "zero": {"offset": 0}, "highlight": {"offset": "highlight"},
                        "seconds": {"offset": 0.25}}
                got = {}
                for name, extra in runs.items():
                    spec = {"duration": 1.0, "tracks": [dict({"kind": "music", "catalog": "buckley-fixture-hands"}, **extra)],
                            "master": {"engine": "none"}}
                    (d / (name + ".json")).write_text(json.dumps(spec), encoding="utf-8")
                    rep = mix.render(d / (name + ".json"), d / (name + ".wav"))
                    got[name] = (rep["tracks"][0].get("offset"), rep["tracks"][0].get("offset_from"))
                self.assertEqual(got["default"], (0.5, "lead-in silence"))
                self.assertEqual(got["zero"], (None, None))
                self.assertEqual(got["highlight"], (0.5, "highlight"))     # no beat grid in a sine: not snapped
                self.assertEqual(got["seconds"], (0.25, None))
                spec = {"duration": 1.0, "tracks": [{"kind": "music", "file": "default.wav", "offset": "highlight"}],
                        "master": {"engine": "none"}}
                (d / "bad.json").write_text(json.dumps(spec), encoding="utf-8")
                with self.assertRaises(ShowtimeError) as cm:
                    mix.render(d / "bad.json", d / "bad.wav")
                self.assertIn("catalog music only", str(cm.exception))


    def test_13_render_writes_credits_share_and_note(self):
        """showtime render with a catalog track: credits.txt, the share.txt block (the user's copy kept) and the
        Content ID note; a preview does not touch share.txt."""
        if FAST:
            self.skipTest("--fast (renders in a browser)")
        with serve(self.srv_dir) as url, Env(fixture_catalog(url, self.blob)) as env:
            base = env.dir / "w"
            proj = base / "proj"
            proj.mkdir(parents=True)
            (proj / "showtime.json").write_text(json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 1.5,
                                                            "audio": "audio/mix.json"}), encoding="utf-8")
            (proj / "index.html").write_text("<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head>"
                                             "<body style=\"margin:0;background:#234\"></body></html>", encoding="utf-8")
            (proj / "audio").mkdir()
            (proj / "audio" / "mix.json").write_text(json.dumps({"tracks": [
                {"kind": "music", "catalog": "buckley-fixture-hands", "fit": True}]}), encoding="utf-8")
            menv = {k: os.environ[k] for k in ("SHOWTIME_MUSIC_CATALOG", "SHOWTIME_MUSIC_CACHE", "SHOWTIME_LIBRARY")}
            out = base / "job"
            out.mkdir()
            (out / "share.txt").write_text("Our new thing, in 20 seconds.\n", encoding="utf-8")
            cp = launcher("render", proj, "-o", out / "final.mp4", "--workers", 1, "--json", env=menv)
            r = json.loads(cp.stdout)
            self.assertEqual(Path(r["credits"]), out / "credits.txt")
            self.assertEqual(Path(r["share"]), out / "share.txt")
            self.assertTrue(any("Smart Content ID" in n for n in r["credit_notes"]), r)
            credits = (out / "credits.txt").read_text(encoding="utf-8")
            self.assertIn("'Fixture Hands' by Scott Buckley - released under CC-BY 4.0", credits)
            self.assertIn("End card", credits)
            share = (out / "share.txt").read_text(encoding="utf-8")
            self.assertTrue(share.startswith("Our new thing, in 20 seconds."))
            self.assertEqual(share.count(cr.BLOCK_START), 1)
            before = share
            launcher("render", proj, "-o", out / "preview.mp4", "--preview", "--workers", 1, "--json", env=menv)
            self.assertEqual((out / "share.txt").read_text(encoding="utf-8"), before)


    def test_14_setup_prefetches_for_offline(self):
        """`setup --with music-catalog` (part of the full tier) fetches every track; with --seed and no network it
        copies them from a folder of earlier downloads."""
        with serve(self.srv_dir) as url, Env(fixture_catalog(url, self.blob)) as env:
            def setup(home, *extra, offline=False):
                home.mkdir(parents=True)
                try:
                    os.symlink(str(showtime_home() / "venv"), str(home / "venv"), target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("no symlinks here (Windows without developer mode)")
                e = dict(os.environ)
                e.pop("SHOWTIME_MUSIC_CACHE", None)             # the default: <home>/music
                if offline:
                    e["SHOWTIME_OFFLINE"] = "1"
                cp = subprocess.run([sys.executable, str(SKILL / "setup" / "setup.py"), "--home", str(home), "--with",
                                     "music-catalog", "--skip", "ffmpeg", "--skip", "python", "--skip", "node", "--skip",
                                     "browser", "--skip", "models", "--json"] + list(extra), env=e, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, encoding="utf-8", timeout=600)
                rows = {r["component"]: r for r in json.loads(cp.stdout)["results"]}
                return rows["music-catalog"]
            r = setup(env.dir / "h1")
            self.assertEqual((r["status"], r["detail"]), ("ok", "2 downloaded, 0 already present"), r)
            self.assertEqual(len(list((env.dir / "h1" / "music").rglob("*.wav"))), 2)
            seed = env.dir / "h1" / "music"
            r = setup(env.dir / "h2", "--seed", str(seed / "buckley"), "--seed", str(seed / "incompetech"), offline=True)
            self.assertEqual(r["status"], "ok", r)
            self.assertEqual(len(list((env.dir / "h2" / "music").rglob("*.wav"))), 2)


class CreditsTests(unittest.TestCase):
    def items(self):
        cat = music.load_catalog(music.CATALOG)
        b = music.credit_item(music.get("buckley-with-these-hands", cat))
        m = music.credit_item(next(t for t in cat["tracks"] if t["source"] == "incompetech"))
        cc0 = {"id": "lib:kenney-ui/click", "title": "click", "license": "CC0-1.0", "attribution_required": False,
               "credit_optional": "Kenney (www.kenney.nl)"}
        return b, m, cc0

    def test_20_render(self):
        b, m, cc0 = self.items()
        r = cr.render([b, m, cc0, b], extra_lines=["“Mountain” by A. Person (CC BY 4.0) - https://example.org/m"])
        txt = r["credits_txt"]
        self.assertEqual(txt.count(b["attribution"]), 1)
        self.assertIn(m["attribution"], txt)
        self.assertIn("· Kenney (www.kenney.nl)", txt)
        self.assertIn("- “Mountain” by A. Person", txt)
        self.assertIn("Music: “With These Hands” by Scott Buckley (CC BY 4.0)", r["end_card"])
        self.assertEqual(len(r["notes"]), 1)
        self.assertIn(cr.CLAIMS_RELEASE, r["notes"][0])
        # MacLeod's three lines become one description line
        self.assertIn("Kevin MacLeod (incompetech.com) / Licensed under Creative Commons: By Attribution 4.0 / "
                      "https://creativecommons.org/licenses/by/4.0/", r["description"])
        # our own file read back adds nothing new
        tmp = Path(tempfile.mkdtemp(prefix="st-cred-"))
        try:
            (tmp / "credits.txt").write_text(txt, encoding="utf-8")
            again = cr.render([b, m, cc0], cr.lines_from_file(tmp / "credits.txt"))
            self.assertEqual(again["credits_txt"], txt)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_21_fail_loudly_and_upsert(self):
        with self.assertRaises(ShowtimeError):
            cr.render([{"id": "file:x", "title": "x.mp3", "license": "CC-BY-4.0"}])
        cr.render([{"id": "file:y", "title": "y.mp3", "license": "CC0-1.0"}])      # fine: no credit needed
        blk = "%s\nline\n%s" % (cr.BLOCK_START, cr.BLOCK_END)
        s1 = cr.upsert_block("Hello.\n", blk)
        self.assertEqual(s1, "Hello.\n\n" + blk + "\n")
        blk2 = blk.replace("line", "other")
        s2 = cr.upsert_block(s1 + "PS\n", blk2)
        self.assertIn("other", s2)
        self.assertNotIn("\nline\n", s2)
        self.assertTrue(s2.startswith("Hello.") and s2.rstrip().endswith("PS"))
        self.assertEqual(cr.upsert_block(s2, blk2), s2)                         # idempotent


    def test_22_qa_content_id_credit(self):
        """qa warns when a Content ID-protected track's credit is missing from share.txt (the description)."""
        from st.qa import video as qv
        b, m, cc0 = self.items()
        job = Path(tempfile.mkdtemp(prefix="st-qa-cid-"))
        try:
            (job / "work").mkdir()
            v = job / "final.mp4"
            v.write_bytes(b"\0")
            items = cr.normalize([b, m])
            (job / "work" / "mix.report.json").write_text(json.dumps(
                {"credits": [b["attribution"], m["attribution"]], "credit_items": items}), encoding="utf-8")
            cr.write(job, items, share=False)
            F = qv.Findings()
            qv._check_credits(F, v, None, {})
            self.assertTrue(F.has("content_id_credit"), F.items)
            self.assertFalse(F.has("missing_credits", "credits_incomplete"), F.items)
            cr.write(job, items)                                            # render's share.txt block
            F = qv.Findings()
            qv._check_credits(F, v, None, {})
            self.assertFalse(F.has("content_id_credit"), F.items)
        finally:
            shutil.rmtree(job, ignore_errors=True)


class PacksTests(unittest.TestCase):
    def test_30_packs_file(self):
        self.assertEqual(packs.validate(), [])
        doc = packs.load()
        self.assertGreaterEqual(len(doc["packs"]), 20)
        cats = {p["category"] for p in doc["packs"]}
        self.assertTrue({"foley", "ui", "impact", "ambience", "transition"} <= cats, cats)
        for p in doc["packs"]:
            if p["license"].startswith("CC-BY"):
                self.assertTrue(p["attribution"])
        self.assertTrue(packs.matching("typing"))
        # the sounds videos reach for most are each covered by at least one pack
        for need in ("applause", "cheer", "thunder", "rain", "mouse", "trackpad", "marker", "pencil", "vibration",
                     "shutter", "whoosh", "typing", "page", "cafe", "street"):
            self.assertTrue(packs.matching(need), need)
        for p in doc["packs"]:
            if p["source"] == "bigsoundbank":
                self.assertIn("License CC0", p["evidence"], p["id"])
        self.assertTrue(all(p["category"] == "ui" for p in packs.matching(None, "ui")))

    def test_31_pack_installed_on_first_use(self):
        from st.audio import library, mix
        srv = Path(tempfile.mkdtemp(prefix="st-pack-srv-"))
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("click_001.wav", tone_wav(srv / "a.wav", 0.3, 1200))
                z.writestr("click_002.wav", tone_wav(srv / "b.wav", 0.3, 1500))
            (srv / "pack.zip").write_bytes(buf.getvalue())
            blob = buf.getvalue()
            with serve(srv) as url, Env(music.load_catalog(music.CATALOG)) as env:
                doc = {"schema": packs.SCHEMA, "hosts": {"127.0.0.1": {"delay_s": 0, "rule": "test"}},
                       "packs": [{"id": "test-clicks", "title": "Test clicks", "author": "tests", "source": "test",
                                  "source_url": url, "url": url + "/pack.zip", "type": "zip", "bytes": len(blob),
                                  "sha256": hashlib.sha256(blob).hexdigest(), "license": "CC0-1.0", "evidence": "fixture",
                                  "attribution": None, "credit_optional": "tests", "kind": "sfx", "category": "ui",
                                  "tags": ["click", "ui"]}]}
                (env.dir / "packs.json").write_text(json.dumps(doc), encoding="utf-8")
                os.environ["SHOWTIME_SFX_PACKS"] = str(env.dir / "packs.json")
                self.assertEqual(packs.installed_ids(), [])
                d = env.dir / "p"
                d.mkdir()
                spec = {"duration": 1.0, "tracks": [{"kind": "sfx", "lib": "test-clicks/click-001", "at": 0.2}],
                        "master": {"engine": "none"}}
                (d / "mix.json").write_text(json.dumps(spec), encoding="utf-8")
                rep = mix.render(d / "mix.json", d / "mix.wav")
                self.assertEqual(rep["library_items"], ["test-clicks/click-001"])
                self.assertEqual(packs.installed_ids(), ["test-clicks"])
                self.assertEqual(len([i for i in library.load_catalog()["items"] if i["source_id"] == "test-clicks"]), 2)
                self.assertIsNone(packs.hint_for("ui", None))           # nothing left to suggest
        finally:
            shutil.rmtree(srv, ignore_errors=True)


class OpenverseTests(unittest.TestCase):
    """Live search without the network: a stub stands in for the API."""

    def _stub(self, results):
        from st.assets import net
        calls = []

        def fake(url, ttl=0, **kw):
            calls.append(url)
            return {"results": results}
        orig = net.get_json
        net.get_json = fake
        self.addCleanup(setattr, net, "get_json", orig)
        return calls

    @staticmethod
    def _r(i, source, lic="by", ver="4.0"):
        return {"id": "%08d-0000-0000-0000-000000000000" % i, "title": "T%d" % i, "creator": "C%d" % i,
                "license": lic, "license_version": ver, "source": source, "duration": 60000,
                "foreign_landing_url": "https://example.org/%d" % i, "url": "https://cdn.freesound.org/%d.mp3" % i,
                "license_url": "https://creativecommons.org/licenses/by/4.0/", "tags": []}

    def test_45_sources(self):
        from st.audio import openverse
        self.assertEqual(openverse.sources(None), ["freesound", "wikimedia_audio"])
        self.assertEqual(openverse.sources("wikimedia"), ["wikimedia_audio"])
        self.assertEqual(openverse.sources("freesound,jamendo"), ["freesound", "jamendo"])
        with self.assertRaises(ShowtimeError):
            openverse.sources("soundcloud")

    def test_46_jamendo_excluded_by_default(self):
        import urllib.parse
        from st.audio import openverse
        calls = self._stub([self._r(1, "freesound"), self._r(2, "jamendo"), self._r(3, "wikimedia_audio", "cc0", "1.0"),
                            self._r(4, "freesound", "by-nc", "4.0")])
        res = openverse.search("calm piano", category="music")
        self.assertEqual([r["source"] for r in res], ["freesound", "wikimedia_audio"])   # no Jamendo, no NC
        q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[-1]).query)
        self.assertEqual(q["source"], ["freesound,wikimedia_audio"])
        self.assertNotIn("category", q)            # Openverse only categorises Jamendo results
        res = openverse.search("calm piano", category="music", source="jamendo")
        self.assertEqual([r["source"] for r in res], ["jamendo"])
        q = urllib.parse.parse_qs(urllib.parse.urlparse(calls[-1]).query)
        self.assertEqual((q["source"], q["category"]), (["jamendo"], ["music"]))


class CliTests(unittest.TestCase):
    def test_40_cli(self):
        r = json.loads(launcher("audio", "music", "search", "--for", "launch", "--limit", "3", "--json").stdout)
        self.assertEqual(len(r), 3)
        out = launcher("audio", "music", "pick", "--for", "explainer", "--dur", "60").stdout
        self.assertIn('"catalog": "', out)
        self.assertIn("credit:", out)
        out = launcher("audio", "music", "info", "buckley-with-these-hands").stdout
        self.assertIn("CREDIT REQUIRED", out)
        self.assertIn('"offset": "highlight"', out)
        self.assertIn("Smart Content ID", out)
        self.assertEqual(launcher("audio", "music", "check").returncode, 0)
        self.assertIn("launch", launcher("audio", "music", "presets").stdout)
        out = launcher("audio", "credits", "buckley-with-these-hands").stdout
        self.assertIn("'With These Hands' by Scott Buckley", out)
        self.assertIn("End card", out)
        self.assertIn("oga-keyboard-typing", launcher("audio", "packs", "list", "--category", "foley").stdout)
        st = json.loads(launcher("audio", "music", "stats", "--json").stdout)
        self.assertGreaterEqual(st["tracks"], 150)


@unittest.skipUnless(NETWORK, "set SHOWTIME_TEST_NETWORK=1 to check real URLs")
class NetworkTests(unittest.TestCase):
    def test_50_catalog_urls(self):
        import urllib.request
        from st.assets import net
        cat = music.load_catalog(music.CATALOG)
        picks = {}
        for t in cat["tracks"]:
            picks.setdefault(t["source"], t)
        for t in picks.values():
            req = urllib.request.Request(t["file_url"], method="HEAD", headers={"User-Agent": net.USER_AGENT})
            with urllib.request.urlopen(req, timeout=30, context=net._ssl_context()) as r:
                size = int(r.headers.get("Content-Length") or -1)
            self.assertIn(size, (-1, t["bytes"]), t["id"])
            time.sleep(2)

    def test_51_openverse(self):
        from st.audio import openverse
        res = openverse.search("calm piano", limit=5)
        self.assertTrue(res)
        self.assertFalse([r for r in res if r["source"] == "jamendo"])
        for r in res:
            self.assertIn(r["license"], ("CC-BY-4.0", "CC-BY-3.0", "CC0-1.0", "CC-PDM-1.0", "CC-BY-2.5", "CC-BY-2.0"))
            self.assertIn(r["creator"] or "", r["credit"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_music: %.1fs" % (time.time() - t0))
    sys.exit(0 if prog.result.wasSuccessful() else 1)
