#!/usr/bin/env python3
"""capture & assets smoke tests.

Real runs against a local test site (tests/fixtures/capture served by a tiny HTTP server):
  - site capture (screenshots, sections, full-page tiles, dark variant, site.json, assets,
    contact sheet, inventory) and bot-wall detection (exit 3 + BLOCKED.md)
  - site component and site record (paced scroll frames + mp4)
  - --serve DIR (plain static server: the fixture is captured with its own title), a folder given
    as <url>, the wrong-page guard (showtime preview player, directory listings), output naming
  - assets sheet (EXIF rotation, near-duplicates, low-res, clips, paging, no-overwrite)
  - demo record of a ~5 s scripted walkthrough, then autozoom on it (frame count, size)
  - assets: icon (offline, from the installed npm package), license policy, credits, autozoom
    planner rules; with network: font, emoji, CC0 image search + fetch, example.com capture
Network tests are skipped (not failed) when offline or with --fast.

Stdlib only. usage: python tests/test_capture.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import http.server
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zlib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
FIXTURE = TESTS_DIR / "fixtures" / "capture"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-capture-"))


def showtime(*args, check=True, timeout=240, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def sj(cp):
    return json.loads(cp.stdout)


def png(path: Path, w: int, h: int, seed: int = 0) -> None:
    """Write a gradient PNG with stripes (stdlib only; big enough to pass asset size floors)."""
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            r = (x * 255 // w + seed * 40) % 256
            g = (y * 255 // h) % 256
            b = ((x ^ y) * 7 + seed * 90) % 256
            row += bytes((r, g, b))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 6)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


WALL = b"""<!doctype html><html><head><title>Just a moment...</title></head>
<body><div id="challenge-running">Checking your browser</div></body></html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path.startswith("/wall"):
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(WALL)))
            self.end_headers()
            self.wfile.write(WALL)
            return
        return super().do_GET()


def network_ok() -> bool:
    if FAST or os.environ.get("SHOWTIME_OFFLINE"):
        return False
    try:
        socket.create_connection(("cdn.jsdelivr.net", 443), timeout=4).close()
        return True
    except OSError:
        return False


NET = network_ok()
SITE = TMP / "site"


def setUpModule():
    shutil.copytree(FIXTURE, SITE)
    png(SITE / "hero.png", 480, 320, 1)
    png(SITE / "photo.jpg", 400, 260, 2)   # PNG bytes with a .jpg name: tests extension sniffing
    png(SITE / "og.png", 300, 158, 3)
    (SITE / "listing").mkdir()
    png(SITE / "listing" / "a.png", 64, 64, 4)       # a folder without index.html
    handler = lambda *a, **k: Handler(*a, directory=str(SITE), **k)  # noqa: E731
    global SERVER, BASE
    SERVER = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=SERVER.serve_forever, daemon=True).start()
    BASE = "http://127.0.0.1:%d/" % SERVER.server_address[1]


def tearDownModule():
    SERVER.shutdown()
    SERVER.server_close()
    if not os.environ.get("SHOWTIME_KEEP_TEST_OUTPUT"):
        shutil.rmtree(TMP, ignore_errors=True)
    else:
        print("kept test output in", TMP)


class T1Site(unittest.TestCase):
    def test_capture_local(self):
        out = TMP / "cap"
        r = sj(showtime("site", "capture", BASE, out, "--dpr", "1", "--max-shots", "4", "--dark", "on", "--json"))
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["shots"]["16x9"], 3)
        self.assertGreaterEqual(r["sections"], 4)
        self.assertTrue(r["dark"])
        self.assertGreaterEqual(r["fullTiles"], 1)
        self.assertEqual(r["plate"], "full/plate.jpg")
        for f in ("inventory.md", "site.json", "contact-sheet.jpg", "assets-sheet.jpg", "full/plate.jpg",
                  "shots/16x9/scroll-000.png"):
            self.assertTrue((out / f).is_file(), f)
        s = json.loads((out / "site.json").read_text(encoding="utf-8"))
        self.assertEqual([h["text"] for h in s["headings"] if h["level"] == 1], ["Deploy previews in seconds"])
        self.assertIn("Start free", [c["text"] for c in s["ctas"]])
        self.assertEqual(s["colors"]["roles"]["primary"], "#6d28d9")
        self.assertEqual(s["tokens"]["colorVariables"].get("--brand"), "#6d28d9")
        self.assertEqual(len(s["testimonials"]), 1)
        self.assertIn("Ada Example", s["testimonials"][0]["author"])
        self.assertGreaterEqual(len([x for x in s["stats"] if x["value"] in ("40s", "12k+", "99.9%")]), 3)
        self.assertTrue(any(h.startswith("#chat (") for h in s["overlays"]["hidden"]), s["overlays"])  # hidden, with its size
        kinds = {a["kind"] for a in s["assets"]}
        self.assertTrue({"logo", "image", "og-image"} <= kinds, kinds)
        self.assertTrue(any(a["file"].endswith(".png") and "reviewing" in a["file"] for a in s["assets"]),
                        "photo.jpg must be saved as .png (sniffed)")
        # cookie banner handled (autoconsent or fallback) -> not visible in the hero
        self.assertTrue(s["consent"] or s["overlays"]["clicked"] or any(h.startswith("#cookie-banner") for h in s["overlays"]["hidden"]))
        inv = (out / "inventory.md").read_text(encoding="utf-8")
        self.assertIn("Deploy previews in seconds", inv)

    def test_bot_wall(self):
        out = TMP / "wall"
        cp = showtime("site", "capture", BASE + "wall", out, "--dpr", "1", "--json", check=False)
        self.assertEqual(cp.returncode, 3, cp.stderr[-1500:])
        self.assertTrue(sj(cp)["blocked"])
        self.assertTrue((out / "BLOCKED.md").is_file())

    def test_component_and_record(self):
        f = TMP / "comp" / "pricing.png"
        r = sj(showtime("site", "component", BASE, "#pricing", "-o", f, "--dpr", "1", "--json"))
        self.assertEqual(len(r["files"]), 1)
        self.assertTrue(f.is_file())
        out = TMP / "rec"
        r = sj(showtime("site", "record", BASE, out, "--duration", "1", "--fps", "12", "--hold", "0.2",
                        "--width", "640", "--json"))
        self.assertEqual(r["frames"], 12 + 2 * 2)
        self.assertTrue((out / "scroll.mp4").is_file())
        rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["scrollY"][0], 0)
        self.assertGreater(rec["scrollY"][-1], 1000)

    @unittest.skipUnless(NET, "network unavailable or --fast")
    def test_example_com(self):
        out = TMP / "example"
        r = sj(showtime("site", "capture", "https://example.com", out, "--max-shots", "1", "--no-full",
                        "--no-assets", "--dpr", "1", "--json"))
        self.assertTrue(r["ok"])
        s = json.loads((out / "site.json").read_text(encoding="utf-8"))
        # the live page's wording changes over time (its h1 was dropped in 2026); the title is the stable part
        texts = [(s.get("meta") or {}).get("title") or ""] + [h.get("text", "") for h in s.get("headings", [])]
        self.assertTrue(any("Example Domain" in t for t in texts), texts)


TITLE = "Nimbus - Deploy previews in seconds"


def port_open(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(url)
    try:
        socket.create_connection((u.hostname, u.port), timeout=1).close()
        return True
    except OSError:
        return False


class T1bServe(unittest.TestCase):
    """--serve DIR and the wrong-page guard (audit B1)."""

    def test_capture_serve(self):
        out = TMP / "served"
        r = sj(showtime("site", "capture", "--serve", SITE, out, "--dpr", "1", "--max-shots", "2", "--no-full",
                        "--no-sections", "--dark", "off", "--json"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["title"], TITLE)                       # the site, not the preview player
        self.assertEqual(Path(r["served"]).resolve(), SITE.resolve())
        self.assertTrue(r["finalUrl"].startswith("http://127.0.0.1:"), r["finalUrl"])
        self.assertNotIn("/_st/", r["finalUrl"])
        s = json.loads((out / "site.json").read_text(encoding="utf-8"))
        self.assertEqual(s["meta"]["title"], TITLE)
        self.assertEqual([h["text"] for h in s["headings"] if h["level"] == 1], ["Deploy previews in seconds"])
        self.assertEqual(s["colors"]["roles"]["primary"], "#6d28d9")
        self.assertTrue(any(a["kind"] == "logo" for a in s["assets"]))   # /logo.svg resolved from the served root
        inv = (out / "inventory.md").read_text(encoding="utf-8")
        self.assertIn("static folder", inv)
        self.assertIn("system font stack", inv)                   # ui-sans-serif -> use Inter and say so
        self.assertIn("--serve", inv)
        self.assertFalse(port_open(r["finalUrl"]), "the static server must be stopped after the capture")

    def test_folder_as_url_and_default_names(self):
        work = TMP / "names"
        work.mkdir()
        cp = showtime("site", "capture", SITE, "--dpr", "1", "--max-shots", "1", "--no-full", "--no-sections",
                      "--no-assets", "--dark", "off", cwd=work)
        lines = [ln for ln in cp.stdout.splitlines() if ln.strip()]
        out = Path(lines[0])                                      # the output folder is printed first
        self.assertTrue(out.is_dir(), cp.stdout)
        self.assertEqual(out.parent.resolve(), (work / "showtime-out").resolve())
        self.assertRegex(out.name, r"-site-\d{8}-\d{6}$")
        self.assertIn("serving", cp.stderr)
        s = json.loads((out / "site.json").read_text(encoding="utf-8"))
        self.assertEqual(s["meta"]["title"], TITLE)
        # component: default output lives in a <name>-component-<time>/ job folder, never in the cwd
        cp = showtime("site", "component", "--serve", SITE, "h1", "--dpr", "1", cwd=work)
        f = Path(cp.stdout.strip().splitlines()[-1])
        self.assertTrue(f.is_file())
        self.assertRegex(f.parent.name, r"-component-\d{8}-\d{6}$")
        self.assertFalse(list(work.glob("*.png")))
        # -o never overwrites
        o = TMP / "comp2" / "h.png"
        showtime("site", "component", "--serve", SITE, "h1", "-o", o, "--dpr", "1")
        r = sj(showtime("site", "component", "--serve", SITE, "h1", "-o", o, "--dpr", "1", "--json"))
        self.assertEqual(Path(r["files"][0]["file"]).name, "h-2.png")

    def test_record_serve_clears_stale_frames(self):
        out = TMP / "rec-serve"
        a = sj(showtime("site", "record", "--serve", SITE, out, "--duration", "1", "--fps", "8", "--hold", "0",
                        "--width", "480", "--no-mp4", "--json"))
        self.assertEqual(a["frames"], 8)
        b = sj(showtime("site", "record", "--serve", SITE, out, "--duration", "0.5", "--fps", "8", "--hold", "0",
                        "--width", "480", "--no-mp4", "--json"))
        self.assertEqual(b["frames"], 4)
        self.assertEqual(len(list((out / "frames").glob("*.jpg"))), 4)
        rec = json.loads((out / "record.json").read_text(encoding="utf-8"))
        self.assertTrue(rec["served"])

    def test_wrong_page_guard(self):
        # showtime's own server wraps the page in the preview player: capture must refuse it
        env = dict(ENV)
        p = subprocess.Popen([sys.executable, str(LAUNCHER), "server", SITE, "--port", "0", "--json"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8")
        try:
            info = json.loads(p.stdout.readline())
            url = info["page"]                                     # the printed link (it carries the session key)
            cp = showtime("site", "capture", url, TMP / "wrong", "--dpr", "1", "--max-shots", "1", "--no-full",
                          "--no-sections", "--no-assets", "--dark", "off", check=False)
            self.assertNotEqual(cp.returncode, 0, cp.stdout[-800:])
            self.assertIn("preview player", cp.stderr)
            self.assertIn("--serve", cp.stderr)
            # the bare address (no key) gets the server's 403: still named as showtime's server, not a bot check
            cp = showtime("site", "capture", info["url"] + "/", TMP / "wrong-nokey", "--dpr", "1", "--max-shots", "1",
                          "--no-full", "--no-sections", "--no-assets", "--dark", "off", check=False)
            self.assertNotEqual(cp.returncode, 0, cp.stdout[-800:])
            self.assertIn("session key", cp.stderr)
            self.assertIn("--serve", cp.stderr)
            self.assertNotIn("bot check", cp.stderr)
            cp = showtime("site", "record", url, TMP / "wrong-rec", "--duration", "0.2", "--fps", "5", "--hold", "0",
                          "--no-mp4", "--force", "--json")
            self.assertGreaterEqual(sj(cp)["frames"], 1)           # --force keeps going (with a warning)
            self.assertIn("preview player", cp.stderr)
        finally:
            p.terminate()
            p.wait(10)
            p.stdout.close()
        # a bare directory listing is not a site either
        cp = showtime("site", "component", BASE + "listing/", "h1", "--dpr", "1", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("directory listing", cp.stderr)
        # --serve and a URL together is a usage error
        cp = showtime("site", "capture", "--serve", SITE, "https://example.com", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("either a URL or --serve", cp.stderr)

    def test_static_server_rules(self):
        """The --serve server is a plain static host: no listings, no showtime runtime, SPA fallback."""
        js = r"""
import { serveStatic } from %s;
const srv = await serveStatic(%s);
const http = await import('node:http');
const raw = (p, headers = {}) => new Promise((res) => http.get({ host: '127.0.0.1', port: srv.port, path: p, headers }, (r) => { r.resume(); res([r.statusCode]); }));
const get = async (p, h = {}) => { const r = await fetch(srv.url + p, { headers: h }); const t = await r.text(); return [r.status, t.includes('<title>Nimbus')]; };
const out = {
  root: await get('/'), deep: await get('/app/settings'), missing: await get('/missing.png'),
  listing: await get('/listing/'), runtime: await get('/_st/stage.js'), dotdot: await raw('/..%%2f..%%2f..%%2fetc%%2fhosts'),
  host: await raw('/', { Host: 'evil.example' }), range: (await fetch(srv.url + '/logo.svg', { headers: { Range: 'bytes=0-9' } })).status,
};
await srv.close();
console.log(JSON.stringify(out));
""" % (json.dumps((SKILL / "scripts" / "lib" / "capture.mjs").as_uri()), json.dumps(str(SITE)))
        node = shutil.which("node", path=ENV.get("PATH")) or "node"
        cp = subprocess.run([node, "--input-type=module", "-e", js], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr[-1500:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(r["root"], [200, True])
        self.assertEqual(r["deep"], [200, True])                 # single-page-app fallback to index.html
        self.assertEqual(r["missing"][0], 404)
        self.assertEqual(r["listing"][0], 404)                   # a folder without index.html: 404, never a listing
        self.assertEqual(r["runtime"][0], 404)                   # no showtime runtime mounted
        self.assertIn(r["dotdot"][0], (403, 404))
        self.assertEqual(r["host"][0], 403)
        self.assertEqual(r["range"], 206)


class T2Demo(unittest.TestCase):
    def test_demo_and_autozoom(self):
        out = TMP / "demo"
        r = sj(showtime("demo", "record", FIXTURE / "demo.mjs", out, "--serve", SITE, "--dpr", "1.5", "--json"))
        ev = json.loads((out / "events.json").read_text(encoding="utf-8"))
        # frames are really captured at size x dpr (some Chrome builds ignore the dpr otherwise)
        fi = ff.probe(sorted((out / "frames").glob("*.jpg"))[-1])
        self.assertEqual((fi["width"], fi["height"]), (ev["frame_size"]["width"], ev["frame_size"]["height"]))
        self.assertEqual(ev["frame_size"], {"width": 1440, "height": 810})
        self.assertEqual(ev["fps"], 24)
        self.assertEqual(ev["frames"], len(list((out / "frames").glob("*.jpg"))))
        self.assertEqual(len(ev["cursor"]), ev["frames"])
        self.assertTrue(4.0 <= ev["duration"] <= 6.5, ev["duration"])
        types = [e["type"] for e in ev["events"]]
        for t in ("click", "type", "key", "scroll", "chapter"):
            self.assertIn(t, types)
        typed = next(e for e in ev["events"] if e["type"] == "type")
        self.assertEqual(typed["text"], "acme/web")
        self.assertAlmostEqual(typed["end"] - typed["t"], 8 / 16.0, delta=0.25)   # 16 chars/s pacing
        # type(text, {opts}) with no target types into the focused field and logs its box
        typed2 = [e for e in ev["events"] if e["type"] == "type"][1]
        self.assertEqual(typed2["text"], "-x")
        self.assertIsNone(typed2["target"])
        self.assertTrue(typed2["bbox"], typed2)
        self.assertTrue((out / "demo.mp4").is_file())
        self.assertEqual(r["clicks"], 2)
        z = sj(showtime("autozoom", out, "--size", "1280x720", "--keys", "all", "--json"))
        self.assertGreaterEqual(z["shots"], 1)
        self.assertEqual(z["frames_written"], ev["frames"])
        info = ff.probe(z["output"])
        self.assertEqual((info["width"], info["height"]), (1280, 720))
        cam = json.loads(Path(z["camera"]).read_text(encoding="utf-8"))
        self.assertEqual(len(cam["camera"]), ev["frames"])
        self.assertGreater(max(c[1] for c in cam["camera"]), 1.15)       # it zoomed in
        self.assertLess(abs(cam["camera"][0][1] - 1.0), 1e-3)            # and started wide
        # plain + cover vertical follow-cam, plan only (fast)
        z2 = sj(showtime("autozoom", out, "--plan", "--look", "plain", "--size", "1080x1920", "--fit", "cover", "--json"))
        self.assertEqual(z2["size"], [1080, 1920])
        self.assertEqual(len(z2["shot_list"]), z2["shots"])             # the plan's shots in the JSON
        keys = json.loads(Path(z2["keys"]).read_text(encoding="utf-8"))  # keycap timeline for compositions
        self.assertTrue(any(k["kind"] == "keys" and "\u2318" in k["label"] for k in keys["items"]), keys)
        # rendered vertical cover: a zoomed shot outside the canvas centre still shows the window, never
        # the background colour (the window mask used to stop at the canvas edge)
        z3 = sj(showtime("autozoom", out, "--look", "plain", "--size", "540x960", "--fit", "cover",
                         "--bg", "#ff00ff", "--keys", "off", "-o", TMP / "vcover.mp4", "--json"))
        import cv2
        cap = cv2.VideoCapture(str(z3["output"]))
        worst = 0.0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            b, g, r_ = fr[..., 0].astype(int), fr[..., 1].astype(int), fr[..., 2].astype(int)
            worst = max(worst, float(((r_ > 200) & (b > 200) & (g < 60)).mean()))
        cap.release()
        self.assertLess(worst, 0.01, "background shows through a cover follow-cam")


class T3Assets(unittest.TestCase):
    def test_icon_offline(self):
        out = TMP / "icons" / "rocket.svg"
        r = sj(showtime("assets", "icon", "lucide", "rocket", "--color", "#ff0066", "--size", "64", "-o", out, "--json"))
        svg = out.read_text(encoding="utf-8")
        self.assertIn('stroke="#ff0066"', svg)
        self.assertIn('width="64"', svg)
        self.assertTrue(Path(str(out) + ".license.json").is_file())
        self.assertEqual(r["license"], "ISC")
        cp = showtime("assets", "icon", "lucide", "rockt", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("rocket", cp.stderr)   # suggestion

    def test_assets_sheet(self):
        """Contact sheet of a photo folder: EXIF rotation, date, near-duplicates, low-res, clips, paging."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        import random
        d = TMP / "photos"
        (d / "sub").mkdir(parents=True)

        def photo(w, h, seed):
            im = Image.new("RGB", (w, h))
            px = im.load()
            r = random.Random(seed)
            blobs = [(r.randrange(w), r.randrange(h), r.randrange(40, 200), tuple(r.randrange(256) for _ in range(3)))
                     for _ in range(12)]
            for y in range(0, h, 4):
                for x in range(0, w, 4):
                    c = (x * 255 // w, y * 255 // h, 90)
                    for bx, by, rad, col in blobs:
                        if (x - bx) ** 2 + (y - by) ** 2 < rad * rad:
                            c = col
                    for yy in range(y, min(h, y + 4)):
                        for xx in range(x, min(w, x + 4)):
                            px[xx, yy] = c
            return im
        base = photo(1500, 1000, 1)
        # stored landscape with "rotate 90 CW" (EXIF 6): left half red -> displayed portrait, red on top
        rot = base.copy()
        rot.paste((230, 20, 20), (0, 0, 750, 1000))
        ex = Image.Exif()
        ex[0x0112] = 6
        ex.get_ifd(0x8769)[0x9003] = "2024:06:01 10:22:33"
        rot.save(d / "IMG_0002.jpg", quality=90, exif=ex.tobytes())
        base.save(d / "IMG_0010.jpg", quality=92)
        base.save(d / "IMG_0011.jpg", quality=55)                   # a burst twin of IMG_0010
        photo(600, 400, 3).save(d / "small.png")
        photo(1400, 1400, 4).save(d / "sub" / "deep.jpg")
        (d / "notes.txt").write_text("not an image", encoding="utf-8")
        ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=1", "-pix_fmt", "yuv420p",
                       d / "clip.mp4"])
        out = TMP / "sheet" / "sheet.jpg"
        r = sj(showtime("assets", "sheet", d, "-o", out, "--cols", "3", "--json"))
        names = [i["name"] for i in r["items"]]
        self.assertEqual(names, ["clip.mp4", "IMG_0002.jpg", "IMG_0010.jpg", "IMG_0011.jpg", "small.png"])  # natural order
        it = {i["name"]: i for i in r["items"]}
        self.assertEqual(it["IMG_0002.jpg"]["size"], [1000, 1500])
        self.assertEqual(it["IMG_0002.jpg"]["orientation"], "portrait")
        self.assertTrue(it["IMG_0002.jpg"]["rotated"])
        self.assertEqual(it["IMG_0002.jpg"]["date"], "2024-06-01 10:22:33")
        self.assertEqual(it["IMG_0011.jpg"].get("similar_to"), it["IMG_0010.jpg"]["n"])
        self.assertFalse(it["IMG_0010.jpg"].get("similar_to"))
        self.assertFalse(it["IMG_0002.jpg"].get("similar_to"))
        self.assertTrue(it["small.png"]["low_res"])
        self.assertFalse(it["IMG_0010.jpg"]["low_res"])
        self.assertEqual(it["clip.mp4"]["kind"], "video")
        self.assertAlmostEqual(it["clip.mp4"]["duration"], 1.0, delta=0.15)
        self.assertEqual(r["counts"]["rotated_by_exif"], 1)
        self.assertEqual(r["sheets"], [str(out)])
        self.assertTrue(Path(r["json"]).is_file())
        sheet = Image.open(out).convert("RGB")
        self.assertEqual(sheet.width, 2 * 14 + 3 * 300 + 2 * 10)
        # item 2 (IMG_0002) is the 2nd cell of row 1: the red half must be on TOP (EXIF applied)
        x0, y0 = 14 + 310, 14 + 32
        top, bottom = sheet.getpixel((x0 + 150, y0 + 40)), sheet.getpixel((x0 + 150, y0 + 260))
        self.assertTrue(top[0] > 180 and top[1] < 80 and top[2] < 80, top)
        self.assertFalse(bottom[0] > 180 and bottom[1] < 80 and bottom[2] < 80, bottom)
        # never overwrites; paging; globs; recursion
        mtime = out.stat().st_mtime
        r2 = sj(showtime("assets", "sheet", d, "-o", out, "--per-page", "2", "--labels", "number", "--json"))
        self.assertEqual(out.stat().st_mtime, mtime)
        self.assertEqual([Path(p).name for p in r2["sheets"]], ["sheet-2.jpg", "sheet-2-p2.jpg", "sheet-2-p3.jpg"])
        self.assertTrue(r2["warnings"])
        r3 = sj(showtime("assets", "sheet", str(d / "*.jpg"), "-r", "-o", TMP / "sheet" / "g.jpg", "--json"))
        self.assertEqual(len(r3["items"]), 3)
        r4 = sj(showtime("assets", "sheet", d, "-r", "--sort", "date", "-o", TMP / "sheet" / "all.jpg", "--json"))
        self.assertIn("deep.jpg", [i["name"] for i in r4["items"]])
        self.assertEqual(r4["items"][0]["name"], "IMG_0002.jpg")    # 2024 EXIF date sorts before file times
        cp = showtime("assets", "sheet", TMP / "nope", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("not found", cp.stderr)

    def test_nasa_third_party_notices(self):
        """08: NASA items whose author/description credits third-party processing are not public domain."""
        from st.assets import media, licenses
        cases = {"Image processing by Tanya Oleksuik CC BY NC SA 3.0": licenses.EXCLUDED,
                 "Enhanced image by Roman Tkachenko (CC-BY)": licenses.ATTRIBUTION,
                 "Enhanced image by Gerald Eichstaedt": licenses.EXCLUDED,
                 "ESA/Hubble & NASA": licenses.EXCLUDED,
                 "The Carina Nebula seen by NASA's Webb telescope.": licenses.FREE}
        for text, want in cases.items():
            lic, notice = media.nasa_license("", text)
            self.assertEqual(licenses.classify(lic), want, (text, lic))
            self.assertEqual(notice is None, want == licenses.FREE, text)
        self.assertEqual(media.nasa_license("CC BY NC SA 3.0")[0].split(" (")[0], "CC BY-NC-SA 3.0")

    def test_license_policy_and_credits(self):
        from st.assets import licenses
        self.assertEqual(licenses.classify("CC0 1.0"), licenses.FREE)
        self.assertEqual(licenses.classify("Public Domain Mark 1.0"), licenses.FREE)
        self.assertEqual(licenses.classify("OFL-1.1"), licenses.FREE)
        self.assertEqual(licenses.classify("CC BY 4.0"), licenses.ATTRIBUTION)
        self.assertEqual(licenses.classify("CC BY-SA 4.0"), licenses.SHARE_ALIKE)
        self.assertEqual(licenses.classify("CC BY-NC 4.0"), licenses.EXCLUDED)
        self.assertEqual(licenses.classify("CC BY-ND 2.0"), licenses.EXCLUDED)
        self.assertEqual(licenses.classify(""), licenses.EXCLUDED)
        proj = TMP / "proj"
        img = proj / "assets" / "a.jpg"
        img.parent.mkdir(parents=True)
        img.write_bytes(b"x")
        licenses.write_sidecar(img, {"title": "Sunset", "author": "Jo", "license": "CC BY 4.0",
                                     "landing_url": "https://example.org/sunset"})
        (proj / "assets" / "b.jpg").write_bytes(b"x")
        licenses.write_sidecar(proj / "assets" / "b.jpg", {"title": "Free", "license": "CC0 1.0"})
        r = sj(showtime("assets", "credits", proj, "--json"))
        self.assertEqual(len(r["items"]), 1)
        text = (proj / "CREDITS.txt").read_text(encoding="utf-8")
        self.assertIn('"Sunset" by Jo (CC BY 4.0)', text)
        self.assertNotIn("Free", text)

    def test_font_internal_names(self):
        """Static font files get the family/style names libass and Pillow match on (some upstream
        static cuts call every weight "<Family> Light"; non-RIBBI weights need their own ID 1)."""
        from st.assets import sfnt
        from st.footage.fontfiles import find_font
        src = find_font("anton").path            # any TTF from setup (converted from the Fontsource package)
        data = src.read_bytes()
        for w, fam1, sub in ((400, "Test Grotesk", "Regular"), (700, "Test Grotesk", "Bold"),
                             (600, "Test Grotesk SemiBold", "Regular")):
            out = sfnt.set_style_names(data, "Test Grotesk", w)
            n = sfnt.names(out)
            self.assertEqual((n[1], n[2], n[16]), (fam1, sub, "Test Grotesk"), n)
            self.assertEqual(sfnt.weight_class(out), w)
            self.assertFalse(sfnt.needs_names(out, "Test Grotesk", w))
            f = TMP / ("tg-%d.ttf" % w)
            f.write_bytes(out)
            try:
                from PIL import ImageFont
            except ImportError:
                continue
            self.assertEqual(ImageFont.truetype(str(f), 20).getname()[0], "Test Grotesk")
        self.assertEqual(sfnt.set_style_names(data, "Test Grotesk", 700), sfnt.set_style_names(data, "Test Grotesk", 700))

    def test_autozoom_planner_rules(self):
        from st.footage.autozoom import Action, plan_shots, make_layout, _clamp_axis
        zooms = {"click": 1.8, "type": 1.6}
        acts = [Action(1.0, 1.0, "click", 300, 300), Action(1.8, 1.8, "click", 330, 320),     # merged
                Action(9.0, 9.0, "click", 1500, 900)]                                         # separate
        shots = plan_shots(acts, 1920, 1080, max_zoom=2.0, zooms=zooms)
        self.assertEqual(len(shots), 2)
        self.assertAlmostEqual(shots[0].start, 1.0 - 0.15)
        self.assertGreaterEqual(shots[0].end, 1.8 + 1.6 - 1e-6)
        self.assertEqual(shots[0].zoom, 1.8)
        big = plan_shots([Action(1, 1, "click", 500, 500, (0, 400, 1800, 200))], 1920, 1080, max_zoom=2.0, zooms=zooms)
        self.assertLess(big[0].zoom, 1.8)   # a wide element limits the zoom
        lay = make_layout(1920, 1080, 1920, 1080, "plain", "contain", 0)
        self.assertEqual(_clamp_axis(0, 480, lay.wx, lay.ww, 1920), 480)   # view stays inside the frame
        # 04: two close shots are bridged, but not across a chapter change; a wide event ends a shot
        acts = [Action(1.0, 1.0, "click", 300, 300), Action(4.0, 4.0, "click", 1500, 900)]
        self.assertEqual(plan_shots(acts, 1920, 1080, max_zoom=2.0, zooms=zooms)[0].end, 4.0 - 0.15)
        split = plan_shots(acts, 1920, 1080, max_zoom=2.0, zooms=zooms, chapters=[3.6])
        self.assertLess(split[0].end, 3.0)
        cut = plan_shots(acts[:1], 1920, 1080, max_zoom=2.0, zooms=zooms, wides=[1.5])
        self.assertAlmostEqual(cut[0].end, 1.5)
        # a chapter or wide marker between two close actions keeps them in separate shots, and a wide
        # during a shot's hold stops it from bridging into the next one
        near = [Action(1.0, 1.0, "click", 300, 300), Action(2.2, 2.2, "click", 320, 310)]
        self.assertEqual(len(plan_shots(near, 1920, 1080, max_zoom=2.0, zooms=zooms)), 1)
        self.assertEqual(len(plan_shots(near, 1920, 1080, max_zoom=2.0, zooms=zooms, chapters=[1.6])), 2)
        sep = plan_shots(near, 1920, 1080, max_zoom=2.0, zooms=zooms, wides=[1.6])
        self.assertEqual(len(sep), 2)
        self.assertAlmostEqual(sep[0].end, 1.6)
        # hints: drop an action span, add a focus; cursor offsets ease in and out
        from st.footage.autozoom import merge_hints, apply_cursor_offsets
        ev = merge_hints({"events": [{"t": 1.0, "type": "click", "x": 1, "y": 1}, {"t": 5.0, "type": "click", "x": 2, "y": 2}]},
                         [{"type": "drop", "t": 0.5, "end": 1.5}, {"type": "focus", "t": 3.0, "end": 4.0, "x": 9, "y": 9}])
        self.assertEqual([e["t"] for e in ev["events"]], [3.0, 5.0])
        samples = [(i / 10.0, 100.0, 100.0, 0) for i in range(60)]
        moved = apply_cursor_offsets(samples, ["2-3:36,12"], 2.0)
        self.assertEqual(moved[25][1:3], (172.0, 124.0))     # fully offset inside the span (x dpr 2)
        self.assertEqual(moved[10][1:3], (100.0, 100.0))     # untouched well before it
        self.assertTrue(100.0 < moved[18][1] < 172.0)        # eased in
        # keycaps: a lone punctuation key carries its name; a key event's `label` is drawn as one cap
        from st.footage.autozoom import Keycaps, keystroke_timeline
        kc = Keycaps.__new__(Keycaps)
        kc.glyphs = False
        self.assertEqual(kc.label("."), [". Period"])
        self.assertEqual(kc.label("Control+Enter"), ["Ctrl", "Enter"])
        self.assertEqual(kc.label("l"), ["L"])
        tl = keystroke_timeline({"events": [{"t": 1.0, "type": "key", "keys": "."},
                                            {"t": 4.0, "type": "key", "keys": ".", "label": ". full stop"}]}, "keys")
        self.assertEqual([(k, tx) for _, _, k, tx in tl], [("keys", "."), ("cap", ". full stop")])
        # an explicit focus wins over typing inside its span (typing logs the whole editor box, whose fit
        # zoom is ~1.15): the author's x1.7 push-in stays one shot at x1.7 on the focus point
        acts = [Action(2.0, 8.0, "focus", 700, 400, None, 1.7),
                Action(2.6, 2.6, "type", 900, 500, (400, 100, 700, 1200)), Action(5.0, 5.0, "type", 950, 520, (400, 100, 700, 1200))]
        fs = plan_shots(acts, 1920, 1080, max_zoom=2.0, zooms={"type": 1.6, "focus": 1.6})
        self.assertEqual(len(fs), 1)
        self.assertEqual((fs[0].zoom, fs[0].x, fs[0].y), (1.7, 700, 400))
        self.assertGreaterEqual(fs[0].end, 8.0)

    @unittest.skipUnless(NET, "network unavailable or --fast")
    def test_font_emoji_media_online(self):
        r = sj(showtime("assets", "font", "Space Grotesk", "--weights", "700", "--formats", "ttf",
                        "--no-variable", "--json"))
        ttf = [f for f in r["files"] if f["format"] == "ttf" and f["weight"] == 700]
        self.assertTrue(ttf)
        head = (Path(r["dir"]) / ttf[0]["file"]).read_bytes()[:4]
        self.assertIn(head, (b"\x00\x01\x00\x00", b"true", b"OTTO"))
        self.assertTrue((Path(r["dir"]) / "LICENSE.txt").is_file())
        p = Path(showtime("assets", "font", "space grotesk", "--path", "--weight", "700").stdout.strip())
        self.assertTrue(p.is_file())
        from st.assets import sfnt
        n = sfnt.names(p.read_bytes())
        self.assertEqual((n.get(1), n.get(2)), ("Space Grotesk", "Bold"), n)   # not "Space Grotesk Light"
        c = sj(showtime("assets", "font", "Space Grotesk", "--weights", "700", "--formats", "ttf", "--no-variable",
                        "--copy-to", TMP / "fproj" / "fonts", "--json"))
        self.assertEqual(c["link"]["href"], "fonts/space-grotesk/font.css")
        self.assertTrue((TMP / "fproj" / c["link"]["href"]).is_file())
        self.assertIn("Space Grotesk", c["link"]["css"])
        e = sj(showtime("assets", "emoji", "rocket", "-o", TMP / "emoji", "--json"))
        self.assertIn("<svg", Path(e["path"]).read_text(encoding="utf-8", errors="replace")[:4000])
        cp = showtime("assets", "emoji", "rocket", "--set", "twemoji", check=False)
        self.assertNotEqual(cp.returncode, 0)   # CC-BY needs --allow-attribution
        s = sj(showtime("assets", "media", "search", "mountain", "--source", "openverse,cma", "--limit", "4",
                        "--json", check=False))
        if not s.get("results"):
            self.skipTest("media sources returned nothing: %s" % s.get("errors"))
        first = s["results"][0]
        self.assertIn(first["license_class"], ("free",))
        f = sj(showtime("assets", "media", "fetch", first["id"], "--project", TMP / "mproj", "--json"))
        self.assertTrue(Path(f["path"]).is_file())
        side = json.loads(Path(f["path"] + ".license.json").read_text(encoding="utf-8"))
        self.assertFalse(side["attribution_required"])
        self.assertTrue(side["sha256"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
