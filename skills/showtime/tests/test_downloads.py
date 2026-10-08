#!/usr/bin/env python3
"""Download tiers and first-use fetches: the manifest's tiers and `setup --plan` table, the lazy-fetch
hook (announce, progress, resume, sha256, seeds, shared Hugging Face cache, offline errors) against a
local fixture server, the model mirror for blocked hosts, audio packs, icon cache, headless-shell discovery, and the fp16 Kokoro NaN guard.

No real network: every download comes from a 127.0.0.1 server started here.
usage: python tests/test_downloads.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import contextlib
import hashlib
import http.server
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from _listen import need_listen

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

from st import common, lazy  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

SETUP_PY = SKILL / "setup" / "setup.py"
MAN = json.loads((SKILL / "setup" / "manifest.json").read_text(encoding="utf-8"))
PLATFORMS = ["mac-arm64", "mac-x64", "win-x64", "linux-x64", "linux-arm64"]
ENV = build_env(showtime_home())


def setup_mod():
    return lazy._setup()


# ------------------------------------------------------------------ fixture server (Range-aware)

class _Handler(http.server.BaseHTTPRequestHandler):
    files: dict = {}
    hits: list = []
    codes: dict = {}          # path -> HTTP status to answer instead (403: a proxy refusing the host)

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        body = self.files.get(self.path)
        self.hits.append((self.path, self.headers.get("Range")))
        if self.path in self.codes:
            self.send_response(self.codes[self.path])
            self.end_headers()
            return
        if isinstance(body, str):          # a proxy's block page: 200, text/html
            page = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            chunk = body[start:]
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(body) - 1, len(body)))
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def fixture_server(files, codes=None):
    _Handler.files = dict(files)
    _Handler.hits = []
    _Handler.codes = dict(codes or {})
    need_listen()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1], _Handler.hits
    finally:
        srv.shutdown()
        srv.server_close()


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
def fake_skill(items, extra=None):
    """A skill folder whose setup/manifest.json holds `items` (the real setup.py next to it)."""
    root = Path(tempfile.mkdtemp(prefix="st-dl-skill-"))
    (root / "setup").mkdir()
    shutil.copyfile(str(SETUP_PY), str(root / "setup" / "setup.py"))
    man = {"schema": 1, "tiers": MAN["tiers"], "extras": {}, "ffmpeg": {}, "items": items}
    man.update(extra or {})
    (root / "setup" / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    home = root / "home"
    sys.modules.pop("showtime_setup_lazy", None)
    try:
        with env(SHOWTIME_SKILL=root, SHOWTIME_HOME=home, SHOWTIME_OFFLINE=None, SHOWTIME_SEED_DIRS=None,
                 SHOWTIME_SHARED_HF_CACHE="0", SHOWTIME_PROGRESS=None, SHOWTIME_USER_HF_HOME=None):
            yield root, home
    finally:
        sys.modules.pop("showtime_setup_lazy", None)
        shutil.rmtree(str(root), ignore_errors=True)


def item(iid, url, body, dest, tier="lazy"):
    return {"id": iid, "tier": tier, "group": "asr", "description": "fixture model (test)", "when": "first test",
            "files": [{"url": url, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "dest": dest}]}


def capture_stderr(fn):
    buf = io.StringIO()
    old = sys.stderr
    sys.stderr = buf
    try:
        out = fn()
    finally:
        sys.stderr = old
    return out, buf.getvalue()


# ------------------------------------------------------------------ tiers and plan

class TestTiersAndPlan(unittest.TestCase):
    def test_manifest_tiers(self):
        ids = {i["id"]: i for i in MAN["items"]}
        k = ids["kokoro-timestamped"]
        self.assertTrue(k["files"][0]["dest"].endswith("-fp16.onnx"))
        self.assertLess(k["files"][0]["size"], 200e6)
        self.assertNotIn("kokoro-v1.0", ids, "the stock fp32 Kokoro left the manifest (superseded)")
        self.assertEqual(ids["whisper-small.en"]["tier"], "lazy")
        self.assertTrue(any(s["dest"].endswith("kokoro-v1.0.onnx") for s in MAN["superseded"]))
        shell = ids["chromium-headless-shell"]
        self.assertEqual(shell["group"], "browser")
        for key in PLATFORMS:
            f = shell["platform_files"][key][0]
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(f["creates"].startswith("browsers/chromium_headless_shell-"), f)
            self.assertIn(key, MAN["packages"]["python"])
        for spec in MAN["lazy_pip"].values():
            self.assertTrue((SKILL / "setup" / spec["requirements"]).is_file(), spec["requirements"])
        req = (SKILL / "setup" / "requirements.txt").read_text(encoding="utf-8")
        for gone in ("faster-whisper==", "ctranslate2==", "imageio-ffmpeg=="):
            self.assertNotIn(gone, req, "%s moved to a first-use component" % gone)
        pkg = json.loads((SKILL / "setup" / "package.json").read_text(encoding="utf-8"))["dependencies"]
        for p in MAN["icon_packs"]:
            self.assertNotIn(p["package"], pkg, "icon sets are fetched per icon, not installed")
            self.assertRegex(p["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(MAN["extras"]["manim"]["auto"])
        self.assertEqual(MAN["ffmpeg"]["win-x64"][0]["id"], "btbn-n9.0.2-win64-gpl-shared")

    def test_select_items(self):
        su = setup_mod()
        core = {i["id"] for i in su.select_items(MAN, "core", [])}
        full = {i["id"] for i in su.select_items(MAN, "full", MAN["full_extras"])}
        self.assertIn("kokoro-timestamped", core)
        self.assertNotIn("whisper-small.en", core)
        self.assertNotIn("chromium-headless-shell", core, "the browser step owns the headless shell")
        self.assertIn("whisper-small.en", full)
        self.assertTrue(core < full)

    def test_plan_every_platform(self):
        for key in PLATFORMS:
            cp = subprocess.run([sys.executable, str(SETUP_PY), "--plan", "--platform", key, "--json"], env=ENV,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            d = json.loads(cp.stdout)
            rows = {r["component"]: r for r in d["rows"]}
            ff = [r for r in d["rows"] if r["component"].startswith("ffmpeg")][0]
            self.assertEqual(ff["tier"], "default")
            self.assertEqual(ff["files"][0]["url"], MAN["ffmpeg"][key][0]["files"][0]["url"])
            self.assertEqual(rows["kokoro-timestamped"]["tier"], "default")
            self.assertEqual(rows["whisper-small.en"]["tier"], "first-use")
            self.assertGreater(rows["Python packages"]["size"], 100e6)
            self.assertIn("library part starter", rows)
            self.assertEqual(rows["music-catalog"]["tier"], "first-use")
            self.assertEqual(rows["sfx-packs"]["tier"], "first-use")
            self.assertGreater(len(rows["music-catalog"]["files"]), 100)
            shell = [r for r in d["rows"] if r["component"].startswith("Chrome Headless Shell")][0]
            if key != plat.platform_key():
                self.assertEqual(shell["tier"], "default", "another platform: no system browser assumed")
            default = sum(r["size"] for r in d["rows"] if r["tier"] == "default")
            self.assertLess(default, 1.2e9, "%s default install %.0f MB" % (key, default / 1e6))
            for r in d["rows"]:
                for f in r["files"]:
                    self.assertTrue(f["url"].startswith("https://"), f)

    def test_plan_text_and_urls(self):
        cp = subprocess.run([sys.executable, str(SETUP_PY), "--plan"], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        for word in ("component", "tier", "sha256", "whisper-small.en", "first-use", "default install:", "--full"):
            self.assertIn(word, cp.stdout)
        cp = subprocess.run([sys.executable, str(SETUP_PY), "--plan", "--urls"], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        lines = cp.stdout.strip().splitlines()
        self.assertGreater(len(lines), 50)
        for ln in lines:
            sha, size, url = ln.split(None, 2)
            self.assertRegex(sha, r"^([0-9a-f]{64}|-{64})$")
            self.assertTrue(url.startswith("https://"))
        self.assertTrue(any("model_fp16.onnx" in ln for ln in lines))

    def test_estimate_and_bad_fetch(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-est-"))
        try:
            e = dict(ENV, SHOWTIME_HOME=str(tmp / "h"))
            est = json.loads(subprocess.run([sys.executable, str(SETUP_PY), "--estimate", "--json"], env=e,
                                            stdout=subprocess.PIPE, encoding="utf-8", timeout=120).stdout)
            full = json.loads(subprocess.run([sys.executable, str(SETUP_PY), "--estimate", "--full", "--json"], env=e,
                                             stdout=subprocess.PIPE, encoding="utf-8", timeout=120).stdout)
            self.assertLess(est["total_bytes"], 1.2e9)
            self.assertGreater(full["total_bytes"], est["total_bytes"] + 1e9)
            self.assertNotIn("whisper-small.en", est["items"])
            cp = subprocess.run([sys.executable, str(SETUP_PY), "--fetch", "no-such-thing"], env=e,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("unknown component", cp.stderr + cp.stdout)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_extract_pick_globs(self):
        import zipfile
        su = setup_mod()
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-zip-"))
        try:
            z = tmp / "a.zip"
            with zipfile.ZipFile(str(z), "w") as zf:
                for n in (plat.exe("ffmpeg"), plat.exe("ffprobe"), plat.exe("ffplay"), "avcodec-63.dll", "readme.txt"):
                    zf.writestr("pkg/bin/" + n, b"x")
            got = sorted(p.name for p in su.extract(z, "zip", tmp / "out", pick=["ffmpeg", "ffprobe", "*.dll"]))
            self.assertEqual(got, sorted(["avcodec-63.dll", plat.exe("ffmpeg"), plat.exe("ffprobe")]))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ------------------------------------------------------------------ lazy fetch hook

class TestLazyFetch(unittest.TestCase):
    def test_fetch_announce_progress_state_and_reuse(self):
        body = os.urandom(300_000)
        with fixture_server({"/m.bin": body}) as (base, hits):
            it = item("fixture-model", base + "/m.bin", body, "models/fixture/m.bin")
            with fake_skill([it]) as (root, home):
                with env(SHOWTIME_PROGRESS="auto"):
                    path, err = capture_stderr(lambda: lazy.ensure_item("fixture-model", "the test feature"))
                self.assertEqual(path, home / "models" / "fixture")
                self.assertEqual((home / "models/fixture/m.bin").read_bytes(), body)
                self.assertIn("fetching fixture-model (300.0 KB) for the test feature", err)
                self.assertRegex(err, r"fetching fixture-model\s+\d+/\d+\s+\d+%")   # the MCP server relays these
                st = json.loads((home / "state.json").read_text(encoding="utf-8"))
                self.assertTrue(st["items"]["fixture-model"]["lazy"])
                n = len(hits)
                lazy.ensure_item("fixture-model", "the test feature")
                self.assertEqual(len(hits), n, "a present component is not fetched again")
                self.assertTrue(lazy.item_ready("fixture-model"))

    def test_resume_and_checksum(self):
        body = os.urandom(200_000)
        with fixture_server({"/m.bin": body, "/bad.bin": b"x" * 1000}) as (base, hits):
            good = item("fixture-good", base + "/m.bin", body, "models/fx/m.bin")
            bad = item("fixture-bad", base + "/bad.bin", b"y" * 1000, "models/fx/bad.bin")
            with fake_skill([good, bad]) as (root, home):
                part = home / "models/fx/m.bin.part"
                part.parent.mkdir(parents=True)
                part.write_bytes(body[:50_000])
                lazy.ensure_item("fixture-good", "resume test")
                self.assertIn(("/m.bin", "bytes=50000-"), hits, "an interrupted download resumes with a Range request")
                self.assertEqual((home / "models/fx/m.bin").read_bytes(), body)
                su = setup_mod()
                old_sleep = su.time.sleep
                su.time.sleep = lambda s: None
                try:
                    with self.assertRaises(common.ShowtimeError) as cm:
                        lazy.ensure_item("fixture-bad", "checksum test")
                finally:
                    su.time.sleep = old_sleep
                self.assertIn("sha256", str(cm.exception))
                self.assertFalse((home / "models/fx/bad.bin").exists(), "a file that fails its checksum is never installed")

    def test_offline_error_and_seed(self):
        body = os.urandom(10_000)
        it = item("fixture-off", "https://example.invalid/m.bin", body, "models/off/m.bin")
        with fake_skill([it]) as (root, home):
            with env(SHOWTIME_OFFLINE="1"):
                with self.assertRaises(common.ShowtimeError) as cm:
                    lazy.ensure_item("fixture-off", "offline feature")
                e = cm.exception
                self.assertEqual(e.code, 3)
                self.assertIn("setup --full", e.hint)
                self.assertIn("--seed", e.hint)
                self.assertIn("fixture-off", e.hint)
                seed = root / "seed"
                seed.mkdir()
                (seed / "whatever-name.bin").write_bytes(body)
                with env(SHOWTIME_SEED_DIRS=seed):
                    lazy.ensure_item("fixture-off", "offline feature")
                self.assertEqual((home / "models/off/m.bin").read_bytes(), body)

    def test_shared_hf_cache(self):
        body = os.urandom(20_000)
        sha = hashlib.sha256(body).hexdigest()
        url = "https://huggingface.co/some-org/some-model/resolve/0123abcd/onnx/model.onnx"
        it = item("fixture-hf", url, body, "models/hf-fixture/model.onnx")
        with fake_skill([it]) as (root, home):
            hub = root / "userhf" / "hub" / "models--some-org--some-model"
            (hub / "blobs").mkdir(parents=True)
            (hub / "blobs" / sha).write_bytes(body)
            with env(SHOWTIME_OFFLINE="1", SHOWTIME_USER_HF_HOME=root / "userhf", SHOWTIME_SHARED_HF_CACHE="0"):
                with self.assertRaises(common.ShowtimeError):
                    lazy.ensure_item("fixture-hf", "opt-out test")   # opted out: the shared cache is not read
            with env(SHOWTIME_OFFLINE="1", SHOWTIME_USER_HF_HOME=root / "userhf", SHOWTIME_SHARED_HF_CACHE="1"):
                lazy.ensure_item("fixture-hf", "shared cache test")
            dest = home / "models/hf-fixture/model.onnx"
            self.assertEqual(dest.read_bytes(), body)
            if not plat.IS_WINDOWS:
                self.assertEqual(os.stat(str(dest)).st_ino, os.stat(str(hub / "blobs" / sha)).st_ino,
                                 "same file system: hard-linked, no second copy")
            # a blob that does not match its sha256 is never used
            (hub / "blobs" / sha).unlink()
            (hub / "blobs" / sha).write_bytes(b"z" * len(body))
            with env(SHOWTIME_USER_HF_HOME=root / "userhf", SHOWTIME_SHARED_HF_CACHE="1"):
                self.assertTrue(lazy._setup().hf_cache_dirs())
                self.assertIsNone(lazy._setup().hf_cache_find(url, sha, len(body)))

    def test_generic_asr_hook(self):
        body = os.urandom(5000)
        with fixture_server({"/asr.bin": body}) as (base, hits):
            it = item("fake-asr-model", base + "/asr.bin", body, "models/sherpa/fake/model.bin")
            with fake_skill([it]) as (root, home):
                old = dict(lazy.ASR_COMPONENTS)
                lazy.ASR_COMPONENTS["fake-engine"] = {"*": ("fake-asr-model",)}
                try:
                    self.assertEqual(lazy.asr_components("fake-engine", "anything"), ("fake-asr-model",))
                    lazy.ensure_asr("fake-engine", "anything", "a transcription")
                finally:
                    lazy.ASR_COMPONENTS.clear()
                    lazy.ASR_COMPONENTS.update(old)
                self.assertTrue((home / "models/sherpa/fake/model.bin").is_file())
        self.assertEqual(lazy.asr_components("whisper", "small.en"), ("whisper-engine", "whisper-small.en"))
        self.assertEqual(lazy.asr_components("whisper", "medium"), ("whisper-engine",))

    def test_pip_and_extra_offline(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-pip-"))
        try:
            with env(SHOWTIME_HOME=tmp / "h", SHOWTIME_OFFLINE="1"):
                with self.assertRaises(common.ShowtimeError) as cm:
                    lazy.ensure_pip("whisper-engine", "transcription")
                self.assertEqual(cm.exception.code, 3)
                self.assertIn("setup --full", cm.exception.hint)
                with self.assertRaises(common.ShowtimeError) as cm:
                    common.require_extra("manim", "a Manim scene", available=False)
                self.assertEqual(cm.exception.code, 3)
                self.assertIn("setup --full", cm.exception.hint)
            with self.assertRaises(common.ShowtimeError):
                lazy.ensure_pip("no-such-component", "x")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_components_status(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-st-"))
        try:
            with env(SHOWTIME_HOME=tmp / "h"):
                comps = lazy.components()
                ids = {c["id"] for c in comps}
                for want in ("whisper-small.en", "whisper-engine", "manim", "library:starter"):
                    self.assertIn(want, ids)
                self.assertNotIn("imageio-ffmpeg", ids, "fallback-only parts are not first-use components")
                line = lazy.status_line(comps)
                self.assertIn("not fetched yet", line)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ------------------------------------------------------------------ audio packs, icons, browser, kokoro

# ------------------------------------------------------------------ model mirror (blocked hosts)

@contextlib.contextmanager
def mirror_table(files, mirrors):
    """Swap mirror.json for `files` (primary url -> mirror file name) and `mirrors` (base URLs)."""
    from st import mirror
    saved = mirror.load()
    mirror.reset()
    mirror.load({"mirrors": list(mirrors), "files": [{"url": u, "file": n} for u, n in files.items()]})
    try:
        with env(SHOWTIME_MODEL_MIRROR=None):
            yield mirror
    finally:
        mirror.reset()
        mirror.load(saved)


class TestModelMirror(unittest.TestCase):
    def test_primary_403_falls_back_to_mirror_and_remembers_the_host(self):
        a, b = os.urandom(40_000), os.urandom(30_000)
        with fixture_server({"/mirror/m--a.bin": a, "/mirror/m--b.bin": b},
                            codes={"/hf/a.bin": 403, "/hf/b.bin": 403}) as (base, hits):
            it = item("fixture-mirror", base + "/hf/a.bin", a, "models/mm/a.bin")
            it["files"].append(item("x", base + "/hf/b.bin", b, "models/mm/b.bin")["files"][0])
            with fake_skill([it]) as (root, home), \
                    mirror_table({base + "/hf/a.bin": "m--a.bin", base + "/hf/b.bin": "m--b.bin"}, [base + "/mirror/"]):
                _, err = capture_stderr(lambda: lazy.ensure_item("fixture-mirror", "a blocked host"))
                self.assertEqual((home / "models/mm/a.bin").read_bytes(), a)
                self.assertEqual((home / "models/mm/b.bin").read_bytes(), b)
                paths = [p for p, _r in hits]
                self.assertEqual(paths, ["/hf/a.bin", "/mirror/m--a.bin", "/mirror/m--b.bin"],
                                 "one 403 from a host sends its later files straight to the mirror")
                self.assertIn("HTTP 403", err)

    def test_block_page_and_bad_mirror_checksum(self):
        good = os.urandom(20_000)
        with fixture_server({"/hf/m.bin": "<html>Access denied by proxy</html>", "/bad/m--m.bin": os.urandom(20_000),
                             "/good/m--m.bin": good}) as (base, hits):
            it = item("fixture-page", base + "/hf/m.bin", good, "models/pg/m.bin")
            with fake_skill([it]) as (root, home), \
                    mirror_table({base + "/hf/m.bin": "m--m.bin"}, [base + "/bad/", base + "/good/"]):
                lazy.ensure_item("fixture-page", "a proxy block page")
                self.assertEqual((home / "models/pg/m.bin").read_bytes(), good,
                                 "a 200 web page is a block, a wrong checksum moves on to the next mirror")
                self.assertEqual([p for p, _r in hits], ["/hf/m.bin", "/bad/m--m.bin", "/good/m--m.bin"])

    def test_checksum_mismatch_is_an_error_and_nothing_is_kept(self):
        want = os.urandom(10_000)
        with fixture_server({"/mirror/m--m.bin": os.urandom(10_000)}, codes={"/hf/m.bin": 403}) as (base, hits):
            it = item("fixture-sha", base + "/hf/m.bin", want, "models/sha/m.bin")
            with fake_skill([it]) as (root, home), \
                    mirror_table({base + "/hf/m.bin": "m--m.bin"}, [base + "/mirror/"]):
                with self.assertRaises(common.ShowtimeError) as cm:
                    lazy.ensure_item("fixture-sha", "checksum test")
                self.assertIn("sha256 mismatch", str(cm.exception))
                self.assertFalse((home / "models/sha/m.bin").exists())
                self.assertFalse((home / "models/sha/m.bin.part").exists(), "a file failing its checksum is not kept")

    def test_env_override_folder_and_url(self):
        body = os.urandom(15_000)
        with fixture_server({"/own/m--m.bin": body, "/mirror/m--m.bin": body}, codes={"/hf/m.bin": 403}) as (base, hits):
            it = item("fixture-env", base + "/hf/m.bin", body, "models/env/m.bin")
            with fake_skill([it]) as (root, home), \
                    mirror_table({base + "/hf/m.bin": "m--m.bin"}, [base + "/mirror/"]) as mirror:
                folder = root / "mirror-folder"
                folder.mkdir()
                (folder / "m--m.bin").write_bytes(body)
                with env(SHOWTIME_MODEL_MIRROR=folder):
                    lazy.ensure_item("fixture-env", "a local mirror")
                self.assertEqual((home / "models/env/m.bin").read_bytes(), body)
                self.assertEqual(hits, [], "a mirror folder is used before any network")
                (home / "models/env/m.bin").unlink()
                with env(SHOWTIME_MODEL_MIRROR=folder, SHOWTIME_OFFLINE="1"):
                    lazy.ensure_item("fixture-env", "a local mirror, offline")
                self.assertEqual((home / "models/env/m.bin").read_bytes(), body)
                (home / "models/env/m.bin").unlink()
                with env(SHOWTIME_MODEL_MIRROR=base + "/own"):
                    self.assertEqual(mirror.bases(), [base + "/own/", base + "/mirror/"])
                    lazy.ensure_item("fixture-env", "an own mirror")
                self.assertEqual([p for p, _r in hits], ["/hf/m.bin", "/own/m--m.bin"], "the override comes first")
                with env(SHOWTIME_MODEL_MIRROR="off"):
                    self.assertEqual((mirror.bases(), mirror.local_dirs()), ([], []))
                    self.assertEqual(mirror.sources(base + "/hf/m.bin"), [base + "/hf/m.bin"])

    def test_everything_blocked_names_hosts_and_the_override(self):
        body = os.urandom(5_000)
        with fixture_server({}, codes={"/hf/m.bin": 403, "/mirror/m--m.bin": 403}) as (base, hits):
            it = item("fixture-all", base + "/hf/m.bin", body, "models/all/m.bin")
            with fake_skill([it]) as (root, home), \
                    mirror_table({base + "/hf/m.bin": "m--m.bin"}, [base + "/mirror/"]):
                with self.assertRaises(common.ShowtimeError) as cm:
                    lazy.ensure_item("fixture-all", "everything blocked")
                msg = str(cm.exception)
                self.assertIn("127.0.0.1 (HTTP 403)", msg)
                self.assertIn("SHOWTIME_MODEL_MIRROR", msg)
                self.assertIn("m--m.bin", msg, "the file to put in a mirror folder is named")
                self.assertLess(len(msg), 600)

    def test_blocked_primary_and_missing_mirror_asset_say_which(self):
        # MODNet in 0.4.1: Hugging Face blocked in the sandbox, the asset not yet on the mirror release
        body = os.urandom(5_000)
        with fixture_server({}, codes={"/hf/m.bin": 403}) as (base, hits):
            it = item("fixture-gone", base + "/hf/m.bin", body, "models/gone/m.bin")
            with fake_skill([it]) as (root, home), \
                    mirror_table({base + "/hf/m.bin": "gone--m.bin"}, [base + "/mirror/"]):
                with self.assertRaises(common.ShowtimeError) as cm:
                    lazy.ensure_item("fixture-gone", "a missing mirror asset")
                msg = str(cm.exception)
                self.assertIn("127.0.0.1 (HTTP 403)", msg)
                self.assertIn("the mirror 127.0.0.1 has no gone--m.bin (HTTP 404 at %s/mirror/gone--m.bin)" % base, msg)
                self.assertIn("The mirror does not have gone--m.bin yet", msg)
                self.assertIn("SHOWTIME_MODEL_MIRROR", msg)
                self.assertNotIn("Allow one of these hosts", msg, "a missing file is not one more blocked host")

    def test_proxy_refusal_counts_as_blocked(self):
        import socket
        import urllib.error
        from st import mirror
        self.assertTrue(mirror.blocked_reason(urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))))
        self.assertTrue(mirror.blocked_reason(urllib.error.URLError(socket.gaierror(8, "nodename nor servname"))))
        self.assertIsNone(mirror.blocked_reason(urllib.error.URLError(ConnectionResetError("reset"))), "retried")
        self.assertIsNone(mirror.blocked_reason(IOError("size mismatch for x: got 1, expected 2")), "resumed")

    def test_probe_mirror_folder(self):
        from st import sandbox
        with env(SHOWTIME_MODEL_MIRROR=TESTS_DIR):
            ok, detail = sandbox.probe_mirror()
        self.assertTrue(ok)
        self.assertIn(str(TESTS_DIR), detail)

    def test_mirror_json_matches_the_pinned_files(self):
        """Every mirrored file is a pinned download (same url, size and sha256) with a license, and the names are
        valid release-asset names; the default install's Hugging Face and GitHub LFS files are all mirrored."""
        import re
        from st import mirror
        from st.voice import models as vm
        data = json.loads(mirror.MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(data["mirrors"][0], "https://github.com/FavioVazquez/showtime/releases/download/%s/" % data["tag"])
        pinned = {f["url"]: (f["size"], f["sha256"]) for it in MAN["items"] for f in it.get("files", [])}
        for remote, _local, size, sha in (vm.W2V_VARIANTS["q8"], vm.W2V_VOCAB):
            pinned[vm.W2V_BASE + remote] = (size, sha)
        names = [f["file"] for f in data["files"]]
        self.assertEqual(len(names), len(set(names)))
        for f in data["files"]:
            self.assertEqual((f["size"], f["sha256"]), pinned.get(f["url"]), f["file"])
            self.assertRegex(f["file"], r"^[A-Za-z0-9._-]+$")
            self.assertTrue(f["license"] and f["license_url"].startswith("https://") and f["attribution"], f["file"])
        mirrored = {f["url"] for f in data["files"]}
        for it in MAN["items"]:
            if it.get("tier") in ("minimal", "core", "lazy"):
                for f in it.get("files", []):
                    if re.match(r"https://(huggingface\.co|github\.com/[^/]+/[^/]+/raw/)", f["url"]):
                        self.assertIn(f["url"], mirrored, "%s is not mirrored" % f["url"])


class TestPacksIconsBrowser(unittest.TestCase):
    def test_library_parts_partition(self):
        from st.audio import libparts as packs
        man = packs._manifest()
        seen = {}
        for s in man["sources"]:
            seen[s["id"]] = packs.part_of(s)
        self.assertEqual(len(seen), len(man["sources"]))
        self.assertTrue(all(sid in seen for sid in packs.STARTER))
        starter = sum(int(s.get("bytes") or 0) for s in packs.sources("starter", man))
        self.assertTrue(30e6 <= starter <= 50e6, "starter part %.1f MB" % (starter / 1e6))
        kinds = {s["kind"] for s in packs.sources("starter", man)}
        self.assertTrue({"sfx", "music", "ambience", "stinger"} <= kinds)
        with env(SHOWTIME_LIBRARY=tempfile.mkdtemp(prefix="st-dl-lib-")):
            self.assertFalse(packs.managed())
            self.assertEqual(packs.parts_for_query(["epic"], ["music"], []), [], "a library of your own is left alone")
        self.assertIn("music-epic", packs.QUERY_PARTS)

    def test_audio_download_seed_and_offline(self):
        try:
            from st.audio import library
        except ImportError:
            self.skipTest("numpy not in this interpreter")
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-aud-"))
        try:
            body = os.urandom(4000)
            sha = hashlib.sha256(body).hexdigest()
            (tmp / "seed").mkdir()
            (tmp / "seed" / "pack.zip").write_bytes(body)
            library._SEED_INDEX = None
            with env(SHOWTIME_OFFLINE="1", SHOWTIME_SEED_DIRS=None):
                with self.assertRaises(common.ShowtimeError) as cm:
                    library.download("https://example.invalid/pack.zip", tmp / "out" / "a.zip", "ua", {}, sha, len(body))
                self.assertEqual(cm.exception.code, 3)
            library._SEED_INDEX = None
            with env(SHOWTIME_OFFLINE="1", SHOWTIME_SEED_DIRS=tmp / "seed"):
                got = library.download("https://example.invalid/pack.zip", tmp / "out" / "a.zip", "ua", {}, sha, len(body))
            self.assertEqual(got.read_bytes(), body)
        finally:
            library._SEED_INDEX = None
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_icon_cache_and_offline(self):
        from st.assets import icons
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-ic-"))
        try:
            with env(SHOWTIME_HOME=tmp / "h", SHOWTIME_NODE_MODULES=tmp / "nm", SHOWTIME_OFFLINE="1"):
                d = icons.cache_dir("lucide")
                self.assertTrue(str(d).endswith("lucide-static@1.48.0"))
                (d / "icons").mkdir(parents=True)
                (d / "icons" / "zap.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>')
                self.assertIn("<svg", icons.raw_svg("lucide", "zap"))
                with self.assertRaises(common.ShowtimeError) as cm:
                    icons.raw_svg("lucide", "rocket")
                self.assertEqual(cm.exception.code, 3)
                self.assertIn("setup --fetch icons", cm.exception.hint)
                node = shutil.which("node")
                if node:
                    js = ("import('%s').then(async (m) => { const a = await m.iconFile('lucide-static/icons/zap.svg');"
                          " const b = await m.iconFile('lucide-static/icons/rocket.svg');"
                          " const c = await m.iconFile('three/build/three.module.js');"
                          " console.log(JSON.stringify([a, b, c])); })") % (
                        (SKILL / "scripts" / "lib" / "iconcache.mjs").as_uri())
                    cp = subprocess.run([node, "--input-type=module", "-e", js], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, encoding="utf-8", timeout=60, env=dict(os.environ))
                    a, b, c = json.loads(cp.stdout.strip().splitlines()[-1])
                    self.assertTrue(a and a.endswith("zap.svg"), cp.stderr)
                    self.assertIsNone(b, "offline and not cached: no file")
                    self.assertIsNone(c, "not an icon package")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_headless_shell_discovery(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-br-"))
        try:
            exe = "chrome-headless-shell.exe" if plat.IS_WINDOWS else "chrome-headless-shell"
            p = tmp / "chromium_headless_shell-1243" / "chrome-headless-shell-test" / exe
            p.parent.mkdir(parents=True)
            p.write_bytes(b"")
            with env(SHOWTIME_SYSTEM_BROWSER="0", SHOWTIME_CHROME=None, CHROME_PATH=None):
                self.assertEqual(plat.playwright_headless_shell(tmp), p)
                found = plat.find_browsers(tmp)
                self.assertEqual([b["kind"] for b in found], ["headless-shell"])
                self.assertEqual(setup_mod().system_browsers(), [])
                node = shutil.which("node")
                if node:
                    js = "import('%s').then((m) => console.log(JSON.stringify([m.findHeadlessShell(%s), m.findSystemBrowsers()])))" % (
                        (SKILL / "scripts" / "lib" / "chrome.mjs").as_uri(), json.dumps(str(tmp)))
                    cp = subprocess.run([node, "--input-type=module", "-e", js], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, encoding="utf-8", timeout=60, env=dict(os.environ))
                    shell, system = json.loads(cp.stdout.strip().splitlines()[-1])
                    self.assertEqual(Path(shell), p, cp.stderr)
                    self.assertEqual(system, [])
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_kokoro_file_preference(self):
        from st.voice import models
        tmp = Path(tempfile.mkdtemp(prefix="st-dl-ko-"))
        try:
            with env(SHOWTIME_HOME=tmp, SHOWTIME_KOKORO_MODEL=None):
                d = tmp / "models" / "kokoro"
                d.mkdir(parents=True)
                (d / "voices-v1.0.bin").write_bytes(b"v")
                (d / "kokoro-v1.0.onnx").write_bytes(b"s")
                self.assertEqual(models.kokoro_files()["model"].name, "kokoro-v1.0.onnx")
                self.assertIsNone(models.kokoro_files()["timestamped"])
                (d / "kokoro-v1.0-timestamped.onnx").write_bytes(b"t")
                self.assertEqual(models.kokoro_files()["model"].name, "kokoro-v1.0-timestamped.onnx")
                (d / "kokoro-v1.0-timestamped-fp16.onnx").write_bytes(b"h")
                self.assertEqual(models.kokoro_files()["model"].name, "kokoro-v1.0-timestamped-fp16.onnx")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ------------------------------------------------------------------ upgrading a showtime 0.1 home

def _sparse(p, size):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "wb") as fh:
        fh.truncate(size)


class TestOldHome(unittest.TestCase):
    """A home laid out by showtime 0.1.0 keeps working with no action: fp32 Kokoro (timestamped + stock),
    Whisper small.en and the Whisper engine in the default install, Playwright's full Chromium, icon
    packages in node_modules, the whole core library. Doctor has no failure, setup upgrades, --prune
    removes only what is superseded and only once the replacement is here."""

    def make_home(self):
        home = Path(tempfile.mkdtemp(prefix="st-dl-old-"))
        self.addCleanup(shutil.rmtree, str(home), True)
        su = setup_mod()
        key = plat.platform_key()
        for it in su.select_items(MAN, "core", []):
            for f in su.item_files(it, key) or []:
                if it["id"] == "kokoro-timestamped":
                    continue
                _sparse(home / f["dest"], f["size"])
        _sparse(home / "models/kokoro/kokoro-v1.0-timestamped.onnx", 325532171)   # 0.1's fp32 timestamped
        _sparse(home / "models/kokoro/kokoro-v1.0.onnx", 325532387)               # 0.1's stock fp32
        wh = next(i for i in MAN["items"] if i["id"] == "whisper-small.en")
        for f in wh["files"]:
            _sparse(home / f["dest"], f["size"])
        exe = "chrome.exe" if plat.IS_WINDOWS else "chrome"
        _sparse(home / "browsers" / "chromium-1243" / ("chrome-win64" if plat.IS_WINDOWS else "chrome-linux64") / exe, 10)
        (home / "node" / "node_modules" / "lucide-static" / "icons").mkdir(parents=True)
        (home / "node" / "node_modules" / "lucide-static" / "icons" / "zap.svg").write_text("<svg/>")
        (home / "state.json").write_text(json.dumps({"showtime_version": "0.1.0", "items": {}, "installed": {
            "tier": "core", "extras": ["manim"], "platform": key}}), encoding="utf-8")
        return home

    def test_status_voice_and_doctor(self):
        from st import doctor
        from st.voice import models
        home = self.make_home()
        su = setup_mod()
        key = plat.platform_key()
        kok = next(i for i in MAN["items"] if i["id"] == "kokoro-timestamped")
        st, detail = su.item_status(kok, home, key)
        self.assertEqual(st, "legacy", detail)
        self.assertEqual(su.item_status(next(i for i in MAN["items"] if i["id"] == "whisper-small.en"), home, key)[0], "ok")
        with env(SHOWTIME_HOME=home, SHOWTIME_KOKORO_MODEL=None, SHOWTIME_NODE_MODULES=None):
            self.assertEqual(models.kokoro_files()["model"].name, "kokoro-v1.0-timestamped.onnx",
                             "voice keeps using the 0.1 model: nothing to download")
            import argparse
            d = doctor.Doctor(argparse.Namespace(verify=False, verbose=False))
            d.check_models()
            rows = {r["check"]: r for r in d.rows}
            self.assertEqual([r for r in d.rows if r["status"] == "fail"], [])
            self.assertEqual(rows["model kokoro-timestamped"]["status"], "warn")
            self.assertIn("setup --prune", rows["model kokoro-timestamped"]["hint"])
            self.assertEqual(rows["models"]["status"], "pass")
            found = plat.find_browsers(home / "browsers")
            self.assertIn("playwright", [b["kind"] for b in found], "0.1's full Chromium is still found")
            from st.assets import icons
            self.assertEqual(icons.raw_svg("lucide", "zap"), "<svg/>", "icons come from the old node_modules")
            est = su.install_estimate("core", [], home, MAN)
            self.assertIn("kokoro-timestamped", est["items"], "setup upgrades to the fp16 file")
            self.assertNotIn("whisper-small.en", est["items"])

    def test_prune_after_upgrade(self):
        home = self.make_home()
        su = setup_mod()
        args = su.parse_args(["--prune", "--home", str(home)])
        with env(SHOWTIME_HOME=home, SHOWTIME_KOKORO_MODEL=None):
            inst = su.Installer(args)
            self.assertEqual(inst.prune()[1], "nothing to remove", "never before the replacement is here")
            self.assertTrue((home / "models/kokoro/kokoro-v1.0-timestamped.onnx").is_file())
            kok = next(i for i in MAN["items"] if i["id"] == "kokoro-timestamped")
            _sparse(home / kok["files"][0]["dest"], kok["files"][0]["size"])      # as if `setup` fetched fp16
            status, detail = inst.prune()
            self.assertIn("kokoro-v1.0-timestamped.onnx", detail)
            self.assertFalse((home / "models/kokoro/kokoro-v1.0-timestamped.onnx").exists())
            self.assertFalse((home / "models/kokoro/kokoro-v1.0.onnx").exists())
            self.assertTrue((home / "models/whisper/small.en/model.bin").is_file(), "prune keeps what is still used")


# ------------------------------------------------------------------ fp16 NaN guard (onnx_patch)

def _tiny_div_atan_model(elem_type):
    """ModelProto bytes: y = Atan(a / b), a and b of shape [3] (FLOAT=1 or FLOAT16=10), opset 17."""
    from st.voice.onnx_patch import _enc_varint, _ld, _node
    def vi(name):
        dim = _ld(1, _enc_varint((1 << 3) | 0) + _enc_varint(3))           # Dimension.dim_value = 3
        tensor = _enc_varint((1 << 3) | 0) + _enc_varint(elem_type) + _ld(2, dim)
        return _ld(1, name.encode()) + _ld(2, _ld(1, tensor))
    graph = _ld(1, _node("Div", ["a", "b"], ["q"], "div")) + _ld(1, _node("Atan", ["q"], ["y"], "atan"))
    graph += _ld(2, b"g") + _ld(11, vi("a")) + _ld(11, vi("b")) + _ld(12, vi("y"))
    opset = _ld(1, b"") + _enc_varint((2 << 3) | 0) + _enc_varint(17)
    return _enc_varint((1 << 3) | 0) + _enc_varint(8) + _ld(7, graph) + _ld(8, opset)


class TestOnnxGuard(unittest.TestCase):
    def test_guard(self):
        from st.voice.onnx_patch import guard_nan_atan
        try:
            import numpy as np
            import onnxruntime as rt
        except ImportError:
            self.skipTest("numpy/onnxruntime not in this interpreter")
        for elem, dt in ((1, np.float32), (10, np.float16)):
            raw = _tiny_div_atan_model(elem)
            a = np.array([0, 1, -1], dtype=dt)
            b = np.array([0, 1, 1], dtype=dt)
            so = rt.SessionOptions()
            so.log_severity_level = 3
            y0 = rt.InferenceSession(raw, so, providers=["CPUExecutionProvider"]).run(None, {"a": a, "b": b})[0]
            self.assertTrue(np.isnan(y0[0]), "0/0 -> NaN before the guard")
            fixed, n = guard_nan_atan(raw)
            self.assertEqual(n, 1)
            y1 = rt.InferenceSession(fixed, so, providers=["CPUExecutionProvider"]).run(None, {"a": a, "b": b})[0]
            self.assertEqual(float(y1[0]), 0.0, "atan2(0, 0) = 0, as in PyTorch")
            self.assertAlmostEqual(float(y1[1]), float(np.arctan(1.0)), places=2)
            self.assertAlmostEqual(float(y1[2]), float(np.arctan(-1.0)), places=2)
            again, n2 = guard_nan_atan(fixed)
            self.assertEqual((again, n2), (fixed, 0), "idempotent")
        plain = b"\x08\x08"
        self.assertEqual(guard_nan_atan(plain), (plain, 0))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
