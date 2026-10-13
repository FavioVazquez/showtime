#!/usr/bin/env python3
"""st.bed: the bed and the effects of recap and repro films differ from film to film, and not by chance.

Checks (no network, no render): two different inputs get different music (a composed style or a catalog
track) and different effect seeds; the same input gets the same choice twice; with nothing cached and
SHOWTIME_OFFLINE=1 the bed is a composed style from the kind's calm list; a cached catalog track is preferred
and rotates away from the last jobs' styles; `pin` (--music) wins (a style, a catalog id, none); a catalog bed
whose fetch fails becomes its composed fallback in mix.json.

usage: python tests/test_bed.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import numpy as np  # noqa: E402

from st import bed  # noqa: E402
from st.audio import SR, compose, music, sfx  # noqa: E402
from st.common import ShowtimeError  # noqa: E402

SECTIONS = "0:intro,4:verse,9:outro"
KEYS = ["session-%02d" % i for i in range(12)]


def choose(kind, key, **kw):
    return bed.choose(kind, key, 40.0, SECTIONS, **kw)


def _env(x, w=0.005):
    """The 5 ms RMS envelope of a (stereo) clip."""
    k = int(w * SR)
    return np.convolve(np.abs(x).mean(axis=1) ** 2, np.ones(k) / k, "same") ** 0.5


class TestSoftTransitions(unittest.TestCase):
    """0.4.3: the transition sounds (whoosh, swoosh-in, swoosh-out) are soft by default: a slow attack, no hiss
    above 4 kHz, and an end-synced swoosh eases out instead of stopping at its peak. (3bec5d2: swoosh-out attacked in
    11 ms; 34-45% of every one's energy was above 4 kHz; swoosh-in stopped at 84% of its peak.)"""

    def test_attack_and_top_end(self):
        for name in ("whoosh", "swoosh-in", "swoosh-out"):
            for seed in (1, 2, 3):
                x, _ = sfx.render(name, seed=seed, intensity=0.35)
                e = _env(x)
                pk = e.max()
                attack = (int(np.argmax(e >= 0.9 * pk)) - int(np.argmax(e >= 0.1 * pk))) / SR
                self.assertGreaterEqual(attack, 0.08, (name, seed, attack))
                mono = x.mean(axis=1)
                spec = np.abs(np.fft.rfft(mono)) ** 2
                hi = spec[np.fft.rfftfreq(len(mono), 1 / SR) > 4000].sum() / spec.sum()
                self.assertLess(hi, 0.03, (name, seed, hi))

    def test_swoosh_in_eases_out(self):
        x, m = sfx.render("swoosh-in", seed=3, intensity=0.35)
        e = _env(x)
        self.assertLess(e[-int(0.01 * SR) - 1] / e.max(), 0.25)         # the last 10 ms are well under the peak
        self.assertEqual(m["hit"], m["duration"])                       # still end-synced

    def test_other_sounds_are_untouched(self):
        x, _ = sfx.render("click", seed=3)
        e = _env(x, 0.001)
        self.assertLess((int(np.argmax(e >= 0.9 * e.max())) - int(np.argmax(e >= 0.1 * e.max()))) / SR, 0.01)  # still a click

    def test_films_use_soft_cuts_far_under_the_bed(self):
        self.assertNotIn("whoosh", bed.CUT)
        self.assertEqual(bed.CUT, ("swoosh-in", "swoosh-out"))
        self.assertLessEqual(bed.CUT_GAIN_DB, -18.0)
        self.assertEqual(bed.synth("a", "cut", 1, 0.3, "Am")["key"], "Am")


class TestRerunsAndFallback(unittest.TestCase):
    """0.4.3 review: a job keeps its bed on a rerun, the catalog bed's credit is reported, the fallback keeps the
    bed's placement, and the wording of the mix says what was downloaded."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-bed-rerun-"))
        self.proj = self.tmp / "project"
        (self.proj / "audio").mkdir(parents=True)
        for p in (mock.patch.dict(os.environ, {"SHOWTIME_MUSIC_CACHE": str(self.tmp / "music"), "SHOWTIME_OFFLINE": "1"}),):
            p.start()
            self.addCleanup(p.stop)

    def look(self, **kw):
        return dict({"job": "j", "project": str(self.proj.resolve()), "music": []}, **kw)

    def history(self, looks):
        from st.variety import history
        for p in (mock.patch.object(history, "load", return_value=looks),
                  mock.patch.object(history, "enabled", return_value=(True, ""))):
            p.start()
            self.addCleanup(p.stop)

    def test_rerun_reuses_the_bed_in_the_project(self):
        first = bed.choose("recap", "hash-1", 40.0, SECTIONS, project=self.proj)
        (self.proj / "audio" / "mix.json").write_text(json.dumps({"tracks": [first["track"]]}), encoding="utf-8")
        again = bed.choose("recap", "another-hash", 40.0, "0:intro,9:outro", project=self.proj)
        self.assertEqual(again["style"], first["style"])
        self.assertEqual(again["track"]["compose"]["seed"], first["track"]["compose"]["seed"])
        self.assertEqual(again["track"]["compose"]["key"], first["track"]["compose"]["key"])
        self.assertEqual(again["track"]["compose"]["sections"], "0:intro,9:outro")      # the scenes are the new ones
        with mock.patch.object(music, "is_cached", return_value=True):
            cat = bed.choose("recap", "hash-1", 40.0, SECTIONS, project=self.tmp / "other")
        (self.proj / "audio" / "mix.json").write_text(json.dumps({"tracks": [cat["track"]]}), encoding="utf-8")
        self.assertEqual(bed.choose("recap", "x", 40.0, SECTIONS, project=self.proj)["id"], cat["id"])   # not cached now
        self.assertEqual(bed.choose("recap", "x", 40.0, SECTIONS, project=self.proj, pin="lofi-chill")["style"], "lofi-chill")

    def test_rerun_reuses_what_the_history_recorded(self):
        self.history([self.look(music=[{"ref": "compose:ambient-pad", "style": "ambient-pad", "seed": 42, "key": "Em"}])])
        c = bed.choose("repro", "any", 40.0, SECTIONS, project=self.proj)
        self.assertEqual((c["style"], c["track"]["compose"]["seed"], c["track"]["compose"]["key"]), ("ambient-pad", 42, "Em"))
        tid = music.tracks()[3]["id"]
        self.history([self.look(music=[{"ref": "catalog:" + tid}])])
        self.assertEqual(bed.choose("repro", "any", 40.0, SECTIONS, project=self.proj)["id"], tid)

    def test_the_job_itself_is_not_recent_and_rotation_off_is_honoured(self):
        base = choose("repro", "a")["style"]
        # the job's own entry (no seed to reuse) must not push its style out of the pool
        self.history([self.look(music=[{"ref": "compose:" + base, "style": base}])])
        self.assertEqual(bed.pick_style("repro", "a", self.proj), base)
        other = {"job": "other", "project": str(self.tmp / "other"), "music": [{"ref": "compose:" + base, "style": base}]}
        self.history([other])
        self.assertNotEqual(bed.pick_style("repro", "a", self.proj), base)
        with mock.patch.dict(os.environ, {"SHOWTIME_MUSIC_ROTATION": "off"}):
            self.assertEqual(bed.pick_style("repro", "a", self.proj), base)

    def test_a_cached_candidate_beats_a_download(self):
        q = bed.CATALOG["recap"]
        cands = [r["track"]["id"] for r in music.search(use=q["use"], energy=q["energy"], vocals="none", dur=40.0,
                                                         limit=bed.CANDIDATES, key=str(self.proj.resolve()))]
        want = cands[(bed.stable("a", "recap", "track") % len(cands) + 1) % len(cands)]
        with mock.patch.object(music, "is_cached", side_effect=lambda t: t["id"] == want), \
                mock.patch("st.assets.net.offline", return_value=False):
            self.assertEqual(bed.choose("recap", "a", 40.0, SECTIONS, fetch=True, project=self.proj)["id"], want)

    def catalog_choice(self):
        with mock.patch.object(music, "is_cached", return_value=True):
            return bed.choose("recap", "a", 40.0, SECTIONS, duck={"under": "voice"}, gain_db=-2)

    def test_fallback_keeps_the_placement_and_the_scenes(self):
        c = self.catalog_choice()
        tr = dict(c["track"], duck={"under": "voice", "depth_db": 9}, start=0.5, gain_points=[[0, 1], [2, 0]])
        (self.proj / "audio" / "mix.json").write_text(json.dumps({"_comment": "x", "tracks": [tr]}), encoding="utf-8")
        (self.proj / "index.html").write_text(
            '<section class="scene" id="a" data-start="0" data-dur="3.50"></section>'
            '<section class="scene" id="b" data-start="#a" data-dur="4.00"></section>'
            '<section class="scene" id="c" data-start="#b" data-dur="2.00"></section>', encoding="utf-8")
        for exc in (ShowtimeError("offline"), OSError("disk full")):
            (self.proj / "audio" / "mix.json").write_text(json.dumps({"_comment": "x", "tracks": [tr]}), encoding="utf-8")
            cc = dict(c)
            with mock.patch.object(music, "fetch", side_effect=exc):
                bed.ensure(self.proj / "audio" / "mix.json", cc)
            mix = json.loads((self.proj / "audio" / "mix.json").read_text(encoding="utf-8"))
            b = mix["tracks"][0]
            self.assertEqual((b["duck"], b["start"], b["gain_points"], b["gain_db"]),
                             ({"under": "voice", "depth_db": 9}, 0.5, [[0, 1], [2, 0]], -2))
            self.assertEqual(b["compose"]["sections"], "0:intro,3.5:verse,7.5:outro")
            self.assertIn("seed", cc["label"])
            self.assertIn("all made on this machine", mix["_comment"])

    def test_a_pinned_track_that_cannot_be_fetched_fails(self):
        tid = music.tracks()[0]["id"]
        c = bed.choose("recap", "a", 40.0, SECTIONS, pin=tid)
        self.assertTrue(c["pinned"])
        (self.proj / "audio" / "mix.json").write_text(json.dumps({"tracks": [c["track"]]}), encoding="utf-8")
        with mock.patch.object(music, "fetch", side_effect=OSError("read-only")):
            with self.assertRaises(ShowtimeError):
                bed.ensure(self.proj / "audio" / "mix.json", c)

    def test_credits_and_notes_are_reported(self):
        buckley = next(t for t in music.tracks() if t["source"] == "buckley" and t.get("content_id") == "smart-cid-releasable")
        c = bed.choose("recap", "a", 40.0, SECTIONS, pin=buckley["id"])
        video = self.tmp / "recap.mp4"
        (self.tmp / "recap.credits.txt").write_text("credit", encoding="utf-8")
        (self.tmp / "share.txt").write_text("share", encoding="utf-8")
        r = bed.credit_report(video, c)
        self.assertEqual((r["credits"], r["share"]), (str(self.tmp / "recap.credits.txt"), str(self.tmp / "share.txt")))
        self.assertIn("Content ID", " ".join(r["notes"]))
        self.assertIn(buckley["artist"], r["attribution"])
        self.assertEqual(bed.credit_report(video, choose("recap", "a")), {"credits": None, "share": None, "notes": [], "attribution": None})
        from st import repro as rp
        rep = {"failure": None, "test": {"title": "t", "location": ""}, "browser": "", "playwright": "", "steps": [],
               "console": []}
        self.assertIn("Music: " + r["attribution"], rp.markdown(rep, {"rerun": "", "viewer": ""}, "repro.mp4", r["attribution"]))

    def test_the_synth_cache_key_follows_the_synth_version(self):
        from st.audio import mix
        spec = {"t": "swoosh-in", "dur": None, "intensity": 0.35, "seed": 3, "key": "C"}
        before = mix.sfx_cache_key(spec)
        self.assertEqual(before, mix.sfx_cache_key(dict(spec)))
        with mock.patch.object(sfx, "SYNTH_VERSION", sfx.SYNTH_VERSION + 1):
            self.assertNotEqual(mix.sfx_cache_key(spec), before)
        self.assertGreaterEqual(sfx.SYNTH_VERSION, 2)                       # bumped with the softer transitions
        self.assertNotEqual(mix.sfx_cache_key(dict(spec, seed=4)), before)

    def test_the_comment_claims_sounds_only_when_there_are_any(self):
        self.assertNotIn("sounds", bed.comment(self.catalog_choice(), False))
        self.assertIn("soft sounds", bed.comment(self.catalog_choice(), True))
        self.assertNotIn("sounds", bed.comment(choose("recap", "a"), False))

    def test_the_comment_says_what_was_downloaded(self):
        self.assertIn("downloaded once", bed.comment(self.catalog_choice()))
        self.assertIn("all made on this machine", bed.comment(choose("recap", "a")))
        self.assertNotIn("deep-house", bed.STYLES["recap"])


class TestBed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-bed-"))
        patches = [mock.patch.dict(os.environ, {"SHOWTIME_MUSIC_CACHE": str(self.tmp / "music"),
                                                "SHOWTIME_OFFLINE": "1"}),
                   mock.patch.object(music, "recent_music", return_value=[])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_same_input_same_choice(self):
        for kind in bed.STYLES:
            self.assertEqual(choose(kind, "a"), choose(kind, "a"))
            self.assertEqual(bed.synth("a", "click", 3), bed.synth("a", "click", 3))

    def test_different_inputs_differ(self):
        for kind in bed.STYLES:
            beds = [json.dumps(choose(kind, k)["track"], sort_keys=True) for k in KEYS]
            styles = {choose(kind, k)["style"] for k in KEYS}
            self.assertGreaterEqual(len(styles), 3, (kind, styles))      # not the same style every time
            self.assertGreaterEqual(len(set(beds)), len(KEYS) - 1)       # and the seed and key move even in one style
            self.assertTrue(styles <= {compose.resolve_style(s) for s in bed.STYLES[kind]})
        cuts = [bed.synth(k, "cut", 4) for k in KEYS]
        self.assertGreaterEqual(len({c["type"] for c in cuts}), 2)
        self.assertEqual(len({c["seed"] for c in cuts}), len(KEYS))
        for role, fams in (("click", bed.CLICK), ("error", bed.ERROR), ("cut", bed.CUT)):
            for k in KEYS:
                self.assertIn(bed.synth(k, role, 1)["type"], fams)

    def test_offline_without_cache_is_composed(self):
        c = choose("recap", "a", fetch=True)
        self.assertEqual(c["how"], "compose")
        self.assertIsNone(c["fallback"])
        tr = c["track"]
        self.assertEqual((tr["id"], tr["kind"], tr["gain_db"], tr["fade_out"]), ("bed", "music", -3.0, 1.2))
        self.assertEqual(tr["compose"]["sections"], SECTIONS)
        self.assertEqual(tr["compose"]["key"], compose.auto_key(tr["compose"]["style"], tr["compose"]["seed"]))

    def test_cached_catalog_track_is_preferred_and_varies(self):
        with mock.patch.object(music, "is_cached", return_value=True):
            picks = {k: choose("recap", k, duck={"under": "voice", "depth_db": 12}) for k in KEYS}
            ids = {c["id"] for c in picks.values()}
            self.assertGreaterEqual(len(ids), 3, ids)
            again = choose("recap", KEYS[0], duck={"under": "voice", "depth_db": 12})
            self.assertEqual(again, picks[KEYS[0]])
            c = picks[KEYS[0]]
            self.assertEqual(c["how"], "catalog")
            self.assertEqual(c["track"]["catalog"], c["id"])
            self.assertTrue(c["track"]["fit"])
            self.assertEqual(c["track"]["duck"], {"under": "voice", "depth_db": 12})
            self.assertEqual(c["fallback"]["compose"]["sections"], SECTIONS)
            t = music.get(c["id"])
            self.assertEqual(t["vocals"], "none")
            self.assertLessEqual(float(t["energy"]), 0.6)

    def test_style_rotates_away_from_recent_jobs(self):
        first = choose("repro", "a")["style"]
        row = {"job": "j", "tracks": [], "families": [], "artists": [], "composed": [first]}
        with mock.patch.object(music, "recent_music", return_value=[row]):
            self.assertNotEqual(choose("repro", "a")["style"], first)

    def test_pin(self):
        c = choose("recap", "a", pin="lofi-chill")
        self.assertEqual((c["how"], c["style"]), ("compose", "lofi-chill"))
        self.assertEqual(choose("recap", "b", pin="lofi-chill")["style"], "lofi-chill")
        none = choose("repro", "a", pin="none")
        self.assertEqual((none["how"], none["track"]), ("none", None))
        tid = music.tracks()[0]["id"]
        c = choose("recap", "a", pin=tid)
        self.assertEqual((c["how"], c["id"], c["track"]["catalog"]), ("catalog", tid, tid))
        with self.assertRaises(ShowtimeError):
            choose("recap", "a", pin="no-such-style-or-track")

    def test_failed_fetch_falls_back_to_the_composed_bed(self):
        with mock.patch.object(music, "is_cached", return_value=True):
            c = choose("recap", "a")
        mix = self.tmp / "mix.json"
        mix.write_text(json.dumps({"tracks": [c["track"], {"kind": "sfx", "synth": {"type": "click"}}]}), encoding="utf-8")
        with mock.patch.object(music, "fetch", side_effect=ShowtimeError("offline")):
            bed.ensure(mix, c)
        tracks = json.loads(mix.read_text(encoding="utf-8"))["tracks"]
        self.assertIn("compose", tracks[0])
        self.assertEqual(tracks[1]["kind"], "sfx")
        self.assertEqual(c["how"], "compose")
        with mock.patch.object(music, "fetch", return_value=Path("x")) as f:
            bed.ensure(mix, c)                                      # composed already: nothing to fetch
            f.assert_not_called()


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])
