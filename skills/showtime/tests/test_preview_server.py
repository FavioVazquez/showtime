#!/usr/bin/env python3
"""Preview server session key: `showtime preview` and `showtime server` refuse requests without the key.

Light: Node + stdlib only, no browser, no render. Covers the library server (key via ?k=, cookie,
header; 403 text; cookie flags; per-port cookie names; keyless internal servers unchanged), the
`showtime server` CLI links and the `showtime preview` background server (link, --status, session
file permissions, --stop).

usage: python tests/test_preview_server.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from _listen import needs_listen

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with OPENER.open(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def make_project(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "showtime.json").write_text(json.dumps({"title": "key test", "width": 320, "height": 180, "duration": 2}),
                                     encoding="utf-8")
    (d / "index.html").write_text("<!doctype html><html><head><title>k</title></head><body>secret-body</body></html>",
                                  encoding="utf-8")
    (d / "notes.txt").write_text("private notes\n", encoding="utf-8")
    return d


# a tiny Node host: starts two library servers (one keyed, one keyless like render's) and prints them
HOST_JS = r"""
import { pathToFileURL } from 'node:url';
const imp = (p) => import(pathToFileURL(process.argv[2] + '/scripts/' + p).href);
const { startServer } = await imp('server.mjs');
const keyed = await startServer({ root: process.argv[3], port: 0, key: true });
const keyed2 = await startServer({ root: process.argv[3], port: 0, key: true });
const plain = await startServer({ root: process.argv[3], port: 0 });
console.log(JSON.stringify({ keyed: { url: keyed.url, key: keyed.key, port: keyed.port, link: keyed.link('/_st/preview?page=/index.html') },
  keyed2: { url: keyed2.url, key: keyed2.key, port: keyed2.port }, plain: { url: plain.url, key: plain.key, link: plain.link('/index.html') } }));
process.stdin.on('data', () => {});
process.stdin.on('end', async () => { await keyed.close(); await keyed2.close(); await plain.close(); process.exit(0); });
"""


@needs_listen
class TestPreviewKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-pvkey-"))
        cls.proj = make_project(cls.tmp / "proj")
        host = cls.tmp / "host.mjs"
        host.write_text(HOST_JS, encoding="utf-8")
        cls.host = subprocess.Popen([NODE, str(host), str(SKILL), str(cls.proj)], env=ENV, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        line = cls.host.stdout.readline()
        if not line:
            raise AssertionError("server host did not start: " + cls.host.stderr.read())
        cls.s = json.loads(line)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.host.stdin.close()
            cls.host.wait(timeout=10)
        except Exception:
            cls.host.kill()
        for fh in (cls.host.stdout, cls.host.stderr):
            if fh:
                fh.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_01_no_key_is_refused_everywhere(self):
        k = self.s["keyed"]
        for p in ("/", "/index.html", "/notes.txt", "/_st/preview?page=/index.html", "/_st/project", "/_st/ping",
                  "/_st/stage.js", "/_st/events", "/favicon.ico"):
            st, h, body = fetch(k["url"] + p)
            self.assertEqual(st, 403, p)
            self.assertTrue(h.get("Content-Type", "").startswith("text/plain"), p)
            text = body.decode("utf-8")
            self.assertIn("needs its session key", text, p)
            self.assertIn("k=", text)
            self.assertNotIn("secret-body", text)
            self.assertNotIn(str(self.proj), text)          # no project path leaks either
        st, _, body = fetch(k["url"] + "/index.html", method="HEAD")
        self.assertEqual((st, body), (403, b""))

    def test_02_wrong_keys_are_refused(self):
        k = self.s["keyed"]
        wrong = ("0" * 64) if k["key"] != "0" * 64 else ("1" * 64)
        for how in ({"url": "/index.html?k=" + wrong}, {"url": "/index.html?k="}, {"url": "/index.html?k=" + k["key"][:-1]},
                    {"url": "/index.html", "h": {"X-Showtime-Key": wrong}},
                    {"url": "/index.html", "h": {"Cookie": "st_preview_%d=%s" % (k["port"], wrong)}},
                    # the right key under another port's cookie name does not count
                    {"url": "/index.html", "h": {"Cookie": "st_preview_%d=%s" % (self.s["keyed2"]["port"], k["key"])}}):
            st, _, _ = fetch(k["url"] + how["url"], how.get("h"))
            self.assertEqual(st, 403, how)
        # another server's key does not open this one
        st, _, _ = fetch(k["url"] + "/index.html?k=" + self.s["keyed2"]["key"])
        self.assertEqual(st, 403)

    def test_03_link_sets_a_strict_cookie_that_then_works(self):
        k = self.s["keyed"]
        self.assertRegex(k["key"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(k["key"], self.s["keyed2"]["key"])           # a fresh key per server
        self.assertTrue(k["link"].startswith(k["url"] + "/_st/preview?page=/index.html&k="), k["link"])
        st, h, body = fetch(k["link"])
        self.assertEqual(st, 200)
        self.assertIn(b"__ST_PLAYER__", body)
        cookie = h.get("Set-Cookie", "")
        self.assertTrue(cookie.startswith("st_preview_%d=%s;" % (k["port"], k["key"])), cookie)
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertEqual(h.get("Referrer-Policy"), "no-referrer")
        jar = {"Cookie": cookie.split(";")[0]}
        st, h, body = fetch(k["url"] + "/index.html", jar)
        self.assertEqual(st, 200)
        self.assertIn(b"secret-body", body)
        self.assertIsNone(h.get("Set-Cookie"))                              # set once, not on every response
        st, _, body = fetch(k["url"] + "/notes.txt", dict(jar, Range="bytes=0-6"))
        self.assertEqual((st, body), (206, b"private"))
        st, _, body = fetch(k["url"] + "/_st/ping", {"X-Showtime-Key": k["key"]})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["app"], "showtime")
        st, _, _ = fetch(k["url"] + "/%2e%2e/%2e%2e/etc/passwd", jar)
        self.assertIn(st, (403, 404))                                       # the key never widens the paths

    def test_04_keyless_internal_server_unchanged(self):
        pl = self.s["plain"]
        self.assertIsNone(pl["key"])
        self.assertEqual(pl["link"], pl["url"] + "/index.html")
        st, h, body = fetch(pl["url"] + "/index.html")
        self.assertEqual(st, 200)
        self.assertIn(b"secret-body", body)
        self.assertIsNone(h.get("Set-Cookie"))
        st, _, _ = fetch(pl["url"] + "/index.html", {"Host": "evil.example"})
        self.assertEqual(st, 403)                                           # DNS-rebinding guard still on

    def test_05_server_cli_prints_keyed_links(self):
        p = subprocess.Popen([NODE, str(SKILL / "scripts" / "server.mjs"), str(self.proj), "--port", "0", "--json"], env=ENV,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            info = json.loads(p.stdout.readline())
            self.assertRegex(info["key"], r"^[0-9a-f]{64}$")
            self.assertEqual(info["page"], "%s/index.html?k=%s" % (info["url"], info["key"]))
            self.assertEqual(info["preview"], "%s/_st/preview?page=/index.html&k=%s" % (info["url"], info["key"]))
            self.assertEqual(fetch(info["page"])[0], 200)
            self.assertEqual(fetch(info["url"] + "/index.html")[0], 403)
        finally:
            p.terminate()
            p.communicate(timeout=10)
        bad = subprocess.run([NODE, str(SKILL / "scripts" / "server.mjs"), str(self.proj), "--port", "0", "--key", "nope"],
                             env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=30)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("64 hex", bad.stderr)

    def test_06_preview_command_background_server(self):
        proj = make_project(self.tmp / "pv")

        def run(*args):
            cp = subprocess.run([sys.executable, str(LAUNCHER), "preview", str(proj), *args], env=ENV,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(cp.returncode, 0, cp.stderr + cp.stdout)
            return cp.stdout

        out = json.loads(run("--no-open", "--no-audio", "--port", "0", "--json"))
        try:
            url = out["url"]
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(q["page"], ["/index.html"])
            key = q["k"][0]
            self.assertRegex(key, r"^[0-9a-f]{64}$")
            base = url.split("/_st/")[0]
            st, _, body = fetch(url)
            self.assertEqual(st, 200)
            self.assertIn(b"__ST_PLAYER__", body)
            st, _, body = fetch(base + "/_st/preview?page=/index.html")
            self.assertEqual(st, 403)
            self.assertIn(b"showtime preview <project> --status", body)
            st, _, _ = fetch(base + "/index.html")
            self.assertEqual(st, 403)
            # --status gives the same link back; a second `preview` reuses the server and its key
            status = json.loads(run("--status", "--json"))
            self.assertTrue(status["running"])
            self.assertEqual(status["player"], url)
            again = json.loads(run("--no-open", "--json"))
            self.assertTrue(again.get("reused"))
            self.assertEqual(again["url"], url)
            self.assertIn("k=" + key, run("--status"))
            # the session file holds the key: owner-only on POSIX
            sess = [f for f in (Path(showtime_home()) / "cache" / "preview").glob("*.json")
                    if json.loads(f.read_text(encoding="utf-8")).get("key") == key]
            self.assertEqual(len(sess), 1)
            if os.name == "posix":
                self.assertEqual(sess[0].stat().st_mode & 0o077, 0, oct(sess[0].stat().st_mode))
        finally:
            stop = run("--stop")
        self.assertIn("stopped", stop)
        self.assertIn("not running", run("--status"))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
