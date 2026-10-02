#!/usr/bin/env python3
"""The audio mirror: where a pinned music track, sound-effect pack or library file comes from when its
own host (opengameart.org, scottbuckley.com.au, incompetech.com, archive.org, upload.wikimedia.org,
bigsoundbank.com, kenney.nl ...) is blocked -- the music/sound-effect/sound-library counterpart of the
model mirror (see TestModelMirror in test_downloads.py).

Covered: the naming rule (st/mirror.py `audio_name`/`audio_sources`), a blocked primary falling back to
a SHOWTIME_AUDIO_MIRROR folder and to a mirror base URL (st/audio/library.py `download`, also used by
sound-effect packs through `install_source`), a checksum mismatch from any source being rejected and
never kept, SHOWTIME_AUDIO_MIRROR=off turning the fallback off entirely (folder and bases both), a seed
folder winning before any network, every source failing naming the blocked hosts and the mirror file,
and scripts/stage_audio_mirror.py's dry run (no --seed, no upload) against two fixture items.

No real network and no local port binding (an agent sandbox may forbid both): a "blocked primary" is a
real HTTP request to a 127.0.0.1 port nothing listens on -- refused exactly the way a sandboxed proxy
refuses an unlisted host (st/mirror.py `blocked_reason` already treats a refused connection as blocked,
the same code path a 403 takes) -- and a source that must actually serve bytes is a `file://` URL. Both
are real `urllib` fetches through the same code the feature uses, just without opening a socket to
listen on. The st/audio/music.py path (st/assets/net.py `download`, http(s) only) is covered too, with
its one test that needs a *live* HTTP server skipping gracefully if this sandbox forbids binding one
(the same "no sockets" skip the project already expects elsewhere).

usage: python tests/test_audio_mirror.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import contextlib
import copy
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parents[1]
sys.path.insert(0, str(SKILL / "lib"))

from st.common import ShowtimeError  # noqa: E402
from st import mirror  # noqa: E402
from st.audio import music  # noqa: E402

try:
    from st.audio import library  # needs numpy; music.py and packs.py (and most of this file) do not
except ImportError:
    library = None  # type: ignore[assignment]

SAM_PATH = REPO / "scripts" / "stage_audio_mirror.py"

# A port in this sandbox's "no network" regime refuses instantly (PermissionError) instead of hanging;
# on a normal machine with nothing bound there it refuses just as fast (ConnectionRefusedError). Both are
# "connection refused" to st/mirror.py `blocked_reason` -- see test_proxy_refusal_counts_as_blocked in
# test_downloads.py for the same equivalence used by the model mirror's own tests.
REFUSED = "http://127.0.0.1:1/"


def _load_stage_audio_mirror():
    spec = importlib.util.spec_from_file_location("showtime_stage_audio_mirror_test", str(SAM_PATH))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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


@contextlib.contextmanager
def audio_mirror_bases(*bases):
    """Swap mirror.json's `audio.mirrors` for `bases` (test sources instead of the real GitHub release)."""
    saved = mirror.load()
    mirror.reset()
    data = json.loads(json.dumps(saved))
    data.setdefault("audio", {})["mirrors"] = list(bases)
    data["audio"]["naming"] = "<kind>--<id>.<ext>"
    mirror.load(data)
    try:
        yield
    finally:
        mirror.reset()
        mirror.load(saved)


# ------------------------------------------------------------------------------------------ fixture HTTP server
# Only st/audio/music.py's fetch goes through st/assets/net.py, which fetches http(s) only (no file://), so
# its one "the mirror actually answers" test needs a real listener. Skip it, not fail it, where this sandbox
# forbids binding a local port (the same limit the project already expects: "no sockets" in CLAUDE.md).
class _Handler(http.server.BaseHTTPRequestHandler):
    files: dict = {}
    codes: dict = {}
    hits: list = []

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        _Handler.hits.append(self.path)
        if self.path in self.codes:
            self.send_response(self.codes[self.path])
            self.end_headers()
            return
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def fixture_server(files=None, codes=None):
    _Handler.files = dict(files or {})
    _Handler.codes = dict(codes or {})
    _Handler.hits = []
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except PermissionError:
        raise unittest.SkipTest("local port binding is disabled in this sandbox")
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1], _Handler.hits
    finally:
        srv.shutdown()
        srv.server_close()


# ------------------------------------------------------------------------------------------ naming / sources
class TestNaming(unittest.TestCase):
    def test_naming_rule(self):
        self.assertEqual(mirror.audio_name("music", "buckley-a-kind-of-hope", "mp3"),
                         "music--buckley-a-kind-of-hope.mp3")
        self.assertEqual(mirror.audio_name("sfx", "oga-100-cc0-metal-wood-sfx", "zip"),
                         "sfx--oga-100-cc0-metal-wood-sfx.zip")
        self.assertEqual(mirror.audio_name("lib", "kenney-ui-audio", ".zip"), "lib--kenney-ui-audio.zip")

    def test_sources_order_and_env_off(self):
        mirror.reset()
        try:
            with audio_mirror_bases("http://127.0.0.1:1/mirror/"):
                with env(SHOWTIME_AUDIO_MIRROR=None):
                    srcs = mirror.audio_sources("music", "x", "mp3", "https://example.invalid/x.mp3")
                    self.assertEqual(srcs, ["https://example.invalid/x.mp3", "http://127.0.0.1:1/mirror/music--x.mp3"])
                with env(SHOWTIME_AUDIO_MIRROR="off"):
                    self.assertEqual(mirror.audio_sources("music", "x", "mp3", "https://example.invalid/x.mp3"),
                                     ["https://example.invalid/x.mp3"])
                    self.assertEqual((mirror.audio_bases(), mirror.audio_local_dirs()), ([], []))
        finally:
            mirror.reset()

    def test_local_folder_copy_comes_before_the_primary_in_sources(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-audiomirror-src-"))
        try:
            (tmp / "lib--x.zip").write_bytes(b"abc")
            with audio_mirror_bases(), env(SHOWTIME_AUDIO_MIRROR=str(tmp)):
                srcs = mirror.audio_sources("lib", "x", "zip", "https://example.invalid/x.zip")
                self.assertEqual(len(srcs), 2, srcs)
                self.assertIsInstance(srcs[0], Path)
                self.assertEqual(srcs[0], tmp / "lib--x.zip")
                self.assertEqual(srcs[1], "https://example.invalid/x.zip")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ------------------------------------------------------------------------------------------ library.download
@unittest.skipIf(library is None, "numpy not in this interpreter (st.audio.library needs it)")
class TestLibraryDownloadMirror(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-audiomirror-lib-"))
        self.body = os.urandom(5000)
        self.sha = hashlib.sha256(self.body).hexdigest()
        mirror.reset()
        library._SEED_INDEX = None

    def tearDown(self):
        mirror.reset()
        library._SEED_INDEX = None
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_blocked_primary_falls_back_to_local_folder_mirror_and_verifies(self):
        folder = self.tmp / "audio-mirror-folder"
        folder.mkdir()
        (folder / "lib--test-item.zip").write_bytes(self.body)
        with env(SHOWTIME_AUDIO_MIRROR=str(folder)):
            dest = self.tmp / "out" / "a.zip"
            got = library.download(REFUSED + "pack.zip", dest, "ua", {}, self.sha, len(self.body),
                                   kind="lib", item_id="test-item", ext="zip")
            self.assertEqual(got.read_bytes(), self.body)

    def test_blocked_primary_falls_back_to_a_mirror_base_url(self):
        base = self.tmp / "mirror-base"
        base.mkdir()
        (base / "lib--test-item.zip").write_bytes(self.body)
        with audio_mirror_bases(base.as_uri() + "/"), env(SHOWTIME_AUDIO_MIRROR=None):
            dest = self.tmp / "out" / "a.zip"
            got = library.download(REFUSED + "pack.zip", dest, "ua", {}, self.sha, len(self.body),
                                   kind="lib", item_id="test-item", ext="zip")
            self.assertEqual(got.read_bytes(), self.body)
            self.assertIn("127.0.0.1", str(mirror._blocked), "the primary host is remembered as blocked")

    def test_sha_mismatch_is_rejected_and_not_kept(self):
        wrong_src = self.tmp / "wrong.zip"
        wrong_src.write_bytes(os.urandom(5000))
        with env(SHOWTIME_AUDIO_MIRROR="off"):
            dest = self.tmp / "out" / "a.zip"
            with self.assertRaises(ShowtimeError) as cm:
                library.download(wrong_src.as_uri(), dest, "ua", {}, self.sha, len(self.body),
                                 kind="lib", item_id="t", ext="zip")
            self.assertIn("sha256 mismatch", str(cm.exception))
            self.assertFalse(dest.exists())
            self.assertEqual(list(self.tmp.glob("out/*.part")), [], "a mismatched copy is never kept")

    def test_audio_mirror_off_disables_folder_and_bases(self):
        folder = self.tmp / "ignored-folder"
        folder.mkdir()
        (folder / "lib--test-item.zip").write_bytes(self.body)
        base = self.tmp / "ignored-base"
        base.mkdir()
        (base / "lib--test-item.zip").write_bytes(self.body)
        with audio_mirror_bases(base.as_uri() + "/"), env(SHOWTIME_AUDIO_MIRROR="off"):
            dest = self.tmp / "out" / "a.zip"
            with self.assertRaises(ShowtimeError) as cm:
                library.download(REFUSED + "pack.zip", dest, "ua", {}, self.sha, len(self.body),
                                 kind="lib", item_id="test-item", ext="zip")
            self.assertIn("SHOWTIME_AUDIO_MIRROR", str(cm.exception))
            self.assertFalse(dest.exists())
        # the same folder, mirror ON, now works -- proof the previous failure really was "off", not a typo
        with audio_mirror_bases(base.as_uri() + "/"), env(SHOWTIME_AUDIO_MIRROR=str(folder)):
            dest2 = self.tmp / "out2" / "a.zip"
            got = library.download(REFUSED + "pack.zip", dest2, "ua", {}, self.sha, len(self.body),
                                   kind="lib", item_id="test-item", ext="zip")
            self.assertEqual(got.read_bytes(), self.body)

    def test_seed_wins_before_any_network(self):
        seed_dir = self.tmp / "seed"
        seed_dir.mkdir()
        (seed_dir / "whatever.zip").write_bytes(self.body)
        with env(SHOWTIME_SEED_DIRS=str(seed_dir), SHOWTIME_AUDIO_MIRROR=None):
            dest = self.tmp / "out" / "a.zip"
            # the primary refuses instantly (nothing listens there): if the seed did not win first, this
            # raises instead of returning
            got = library.download(REFUSED + "pack.zip", dest, "ua", {}, self.sha, len(self.body),
                                   kind="lib", item_id="test-item", ext="zip", retries=1)
            self.assertEqual(got.read_bytes(), self.body)

    def test_every_source_blocked_names_hosts_and_the_mirror_file(self):
        with audio_mirror_bases(REFUSED + "mirror/"), env(SHOWTIME_AUDIO_MIRROR=None):
            dest = self.tmp / "out" / "a.zip"
            with self.assertRaises(ShowtimeError) as cm:
                library.download(REFUSED + "pack.zip", dest, "ua", {}, self.sha, len(self.body),
                                 kind="lib", item_id="test-item", ext="zip")
            msg = str(cm.exception)
            self.assertIn("127.0.0.1", msg)
            self.assertIn("SHOWTIME_AUDIO_MIRROR", msg)
            self.assertIn("lib--test-item.zip", msg)


# ------------------------------------------------------------------------------------------ music.py fetch
def _music_fixture(file_url: str, body: bytes) -> dict:
    sha = hashlib.sha256(body).hexdigest()
    cat = copy.deepcopy(music.load_catalog(music.CATALOG))
    t = {"id": "fixture-mirror-track", "title": "Fixture Mirror Track", "artist": "Scott Buckley", "source": "buckley",
        "landing_url": "https://www.scottbuckley.com.au/library/fixture-mirror/", "file_url": file_url,
        "format": "wav", "bytes": len(body), "sha256": sha, "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "'Fixture Mirror Track' by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au",
        "credit_optional": None, "placements": ["description", "credits_file", "end_card"],
        "content_id": "smart-cid-releasable", "duration": 2.0, "shelf": "inspiring", "moods": ["hopeful"],
        "energy": 0.5, "tempo": "slow", "uses": ["launch"], "vocals": "none", "instruments": ["sine"],
        "ending": "clean", "loops": None, "status": "active", "verified": "2026-09-28",
        "quiet_intro_s": 0.0, "lead_silence_s": 0.0, "highlight_s": 0.5}
    cat["tracks"] = [t]
    return cat


class TestMusicFetchMirror(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="st-audiomirror-music-"))
        self.old = {k: os.environ.get(k) for k in ("SHOWTIME_MUSIC_CATALOG", "SHOWTIME_MUSIC_CACHE",
                                                   "SHOWTIME_OFFLINE", "SHOWTIME_SEED_DIRS", "SHOWTIME_AUDIO_MIRROR")}
        mirror.reset()
        music._last_hit.clear()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        music._CAT.clear()
        mirror.reset()
        shutil.rmtree(str(self.dir), ignore_errors=True)

    def _env(self, cat_path):
        os.environ["SHOWTIME_MUSIC_CATALOG"] = str(cat_path)
        os.environ["SHOWTIME_MUSIC_CACHE"] = str(self.dir / "cache")
        os.environ.pop("SHOWTIME_OFFLINE", None)
        os.environ.pop("SHOWTIME_SEED_DIRS", None)
        music._CAT.clear()

    def test_blocked_primary_falls_back_to_mirror_base(self):
        """net.py (st/assets/net.py) fetches http(s) only, so this needs a real listener; skips if this
        sandbox forbids binding one (see fixture_server)."""
        body = os.urandom(8000)
        name = mirror.audio_name("music", "fixture-mirror-track", "wav")
        with fixture_server({"/mirror/" + name: body}, codes={"/track.wav": 403}) as (base, hits):
            cat_path = self.dir / "catalog.json"
            cat_path.write_text(json.dumps(_music_fixture(base + "/track.wav", body)), encoding="utf-8")
            self._env(cat_path)
            with audio_mirror_bases(base + "/mirror/"), env(SHOWTIME_AUDIO_MIRROR=None):
                t = music.get("fixture-mirror-track")
                p = music.fetch(t)
                self.assertEqual(p.read_bytes(), body)
                self.assertEqual(hits, ["/track.wav", "/mirror/" + name])
                side = json.loads(p.with_name(p.name + ".license.json").read_text(encoding="utf-8"))
                self.assertEqual(side["license"], "CC-BY-4.0")

    def test_every_source_blocked_names_hosts_and_the_mirror_file(self):
        """No live server needed: a refused connection is blocked the same way a 403 is (see REFUSED)."""
        body = os.urandom(4000)
        name = mirror.audio_name("music", "fixture-mirror-track", "wav")
        cat_path = self.dir / "catalog.json"
        cat_path.write_text(json.dumps(_music_fixture(REFUSED + "track.wav", body)), encoding="utf-8")
        self._env(cat_path)
        with audio_mirror_bases(REFUSED + "mirror/"), env(SHOWTIME_AUDIO_MIRROR=None):
            t = music.get("fixture-mirror-track")
            with self.assertRaises(ShowtimeError) as cm:
                music.fetch(t)
            msg = str(cm.exception)
            self.assertIn("127.0.0.1", msg)
            self.assertIn("SHOWTIME_AUDIO_MIRROR", msg)
            self.assertIn(name, msg)
            self.assertFalse(music.cached_path(t).exists())


# ------------------------------------------------------------------------------------------ stage_audio_mirror.py
class TestStageAudioMirror(unittest.TestCase):
    def test_dry_run_on_two_fixture_items_writes_licenses_and_shasums(self):
        """stdlib `urllib` fetches file:// URLs directly, so this fixture needs no server at all -- a
        faithful stand-in for the real script's http(s) downloads (same download function)."""
        sam = _load_stage_audio_mirror()
        src_dir = Path(tempfile.mkdtemp(prefix="st-audiomirror-stage-src-"))
        out = Path(tempfile.mkdtemp(prefix="st-audiomirror-stage-out-"))
        try:
            body_a, body_b = os.urandom(3000), os.urandom(4000)
            (src_dir / "a.mp3").write_bytes(body_a)
            (src_dir / "b.zip").write_bytes(body_b)
            items = [
                {"kind": "music", "id": "fixture-a", "title": "Fixture A", "author": "Tester",
                 "url": (src_dir / "a.mp3").as_uri(), "bytes": len(body_a),
                 "sha256": hashlib.sha256(body_a).hexdigest(), "ext": "mp3", "license": "CC0-1.0",
                 "license_url": sam.LICENSE_URLS["CC0-1.0"], "source_page": "https://example.org/a",
                 "attribution": "", "delay_s": 0.0, "bulk": True, "bulk_note": None},
                {"kind": "sfx", "id": "fixture-b", "title": "Fixture B", "author": "Tester",
                 "url": (src_dir / "b.zip").as_uri(), "bytes": len(body_b),
                 "sha256": hashlib.sha256(body_b).hexdigest(), "ext": "zip", "license": "CC-BY-4.0",
                 "license_url": sam.LICENSE_URLS["CC-BY-4.0"], "source_page": "https://example.org/b",
                 "attribution": "Tester (CC BY 4.0)", "delay_s": 0.0, "bulk": True, "bulk_note": None},
            ]
            for it in items:
                it["file"] = sam.mirror_name(it["kind"], it["id"], it["ext"])
            sam.all_items = lambda: items
            sam._license_text = lambda spdx: "(license text stubbed for the test)"
            rc = sam.main(["--out", str(out)])
            self.assertEqual(rc, 0)
            for it in items:
                p = out / it["file"]
                self.assertTrue(p.is_file(), it["file"])
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), it["sha256"])
            lic = (out / "LICENSES.txt").read_text(encoding="utf-8")
            self.assertIn("music--fixture-a.mp3", lic)
            self.assertIn("sfx--fixture-b.zip", lic)
            self.assertIn("CC0-1.0", lic)
            self.assertIn("CC-BY-4.0", lic)
            sums = (out / "SHA256SUMS").read_text(encoding="utf-8")
            for it in items:
                self.assertIn("%s  %s" % (it["sha256"], it["file"]), sums)
            self.assertFalse((out / "a.mp3").exists(), "staged under its mirror name, not the primary's")
        finally:
            shutil.rmtree(str(src_dir), ignore_errors=True)
            shutil.rmtree(str(out), ignore_errors=True)

    def test_naming_and_no_upload(self):
        sam = _load_stage_audio_mirror()
        self.assertEqual(sam.mirror_name("music", "buckley-a-kind-of-hope", "mp3"),
                         "music--buckley-a-kind-of-hope.mp3")
        cmds = sam.commands(Path("/tmp/x"), ["a.mp3", "LICENSES.txt", "SHA256SUMS"], "audio-v1")
        self.assertTrue(any(c.startswith("gh release create audio-v1") for c in cmds))
        self.assertTrue(any(c.startswith("gh release upload audio-v1") for c in cmds))

    def test_real_catalogs_are_fully_covered_or_explicitly_skipped(self):
        """Every pinned, sha256-complete item in the three catalogs gets a unique mirror name; unpinned
        library sources (no bytes/sha256 yet; `showtime audio lib pin` fills those in) are the only ones
        left out, and the script says so."""
        sam = _load_stage_audio_mirror()
        items = sam.all_items()
        self.assertGreater(len(items), 400)
        names = [it["file"] for it in items]
        self.assertEqual(len(names), len(set(names)), "every mirror name is unique")
        for it in items:
            self.assertTrue(it["bytes"] and it["sha256"], it["id"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
