#!/usr/bin/env python3
"""The line that made an X-ray: `showtime new xray` records xray.made, the live export embeds a prompt and
placeholder commands, and the site's X-ray page builds the live buttons, prompts and embed snippets.

  * new: xray.made = {mechanism, layout, theme} and nothing else (no paths, job names or regions)
  * export: --prompt (else showtime.json xray.made.prompt, else none) and commands with placeholders in the page's
    config; no absolute path anywhere in them; the report states what was embedded; FIGURE_CSP has no frame-ancestors
  * site: build_xray with a live entry writes "Play it live", the prompt with its copy mechanism, the Embed snippet

Stdlib only (the site part needs markdown-it-py). usage: python tests/test_xray_made.py [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parents[1]
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-xray-made-"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def live_config(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="xl-cfg">(.*?)</script>', html, re.S)
    assert m, "the page has no xl-cfg block"
    return json.loads(m.group(1))["live"]


class TestMade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proj = TMP / "proj-split"
        showtime("new", "xray", cls.proj, "--layout", "split", "--theme", "light")
        cls.cfg = json.loads((cls.proj / "showtime.json").read_text(encoding="utf-8"))

    def test_new_records_three_words(self):
        self.assertEqual(self.cfg["xray"]["made"], {"mechanism": "typewriter", "layout": "split", "theme": "light"})

    def test_mechanism_is_recorded(self):
        proj = TMP / "proj-box"
        showtime("new", "xray", proj, "--mechanism", "musicbox")
        made = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))["xray"]["made"]
        self.assertEqual(made, {"mechanism": "musicbox", "layout": "through", "theme": "dark"})
        self.assertNotIn(str(TMP), json.dumps(made))

    def test_export_embeds_the_prompt_and_placeholder_commands(self):
        out = TMP / "live-prompt.html"
        cp = showtime("export", "html", self.proj, "--interactive", "-o", out, "--json",
                      "--prompt", "X-ray this clip of my typewriter.")
        report = json.loads(cp.stdout)
        self.assertEqual(report["made"]["prompt"], "X-ray this clip of my typewriter.")
        made = live_config(out.read_text(encoding="utf-8"))["made"]
        self.assertEqual(made["prompt"], "X-ray this clip of my typewriter.")
        self.assertEqual(made["commands"], [
            "showtime xray analyze clip.mp4 --job xray-typewriter --track",  # the sample is tracked
            "showtime new xray xray-typewriter/project --mechanism typewriter --layout split --theme light",
            "showtime render xray-typewriter/project --job xray-typewriter",
            "showtime xray verify xray-typewriter"])
        for line in made["commands"]:
            self.assertNotIn(str(TMP), line)
            self.assertNotRegex(line, r"(^|\s)(/|[A-Za-z]:\\)")

    def test_mechanism_comes_from_the_project_when_made_is_absent(self):
        proj = TMP / "proj-nomade"
        showtime("new", "xray", proj, "--mechanism", "musicbox")
        p = proj / "showtime.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        del cfg["xray"]["made"]
        p.write_text(json.dumps(cfg), encoding="utf-8")
        out = TMP / "live-nomade.html"
        report = json.loads(showtime("export", "html", proj, "--interactive", "-o", out, "--json").stdout)
        made = live_config(out.read_text(encoding="utf-8"))["made"]
        self.assertIn("--mechanism musicbox", made["commands"][1])
        self.assertIn("xray-musicbox/project", made["commands"][1])
        self.assertFalse(made["guessed"])
        self.assertFalse([w for w in report["warnings"] if "names no mechanism" in w])
        mj = proj / "mechanism.js"  # a name that cannot be read: the typewriter is a guess, and the report says so
        mj.write_text(re.sub(r"name:\s*'[^']*'", "name: 'No Name'", mj.read_text(encoding="utf-8"), count=1), encoding="utf-8")
        out2 = TMP / "live-guess.html"
        report = json.loads(showtime("export", "html", proj, "--interactive", "-o", out2, "--json").stdout)
        self.assertTrue(live_config(out2.read_text(encoding="utf-8"))["made"]["guessed"])
        self.assertTrue([w for w in report["warnings"] if "names no mechanism" in w])

    def test_no_prompt_means_none_and_the_report_says_so(self):
        out = TMP / "live-none.html"
        cp = showtime("export", "html", self.proj, "--interactive", "-o", out)
        self.assertIn("no prompt is embedded", cp.stdout + cp.stderr)
        self.assertEqual(live_config(out.read_text(encoding="utf-8"))["made"]["prompt"], "")

    def test_prompt_from_showtime_json_and_never_from_job_json(self):
        proj = TMP / "proj-cfgprompt"
        shutil.copytree(self.proj, proj)
        p = proj / "showtime.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg["xray"]["made"]["prompt"] = "From the project file."
        p.write_text(json.dumps(cfg), encoding="utf-8")
        (TMP / "job.json").write_text(json.dumps({"request": "SECRET job request"}), encoding="utf-8")
        out = TMP / "live-cfg.html"
        showtime("export", "html", proj, "--interactive", "-o", out)
        html = out.read_text(encoding="utf-8")
        self.assertEqual(live_config(html)["made"]["prompt"], "From the project file.")
        self.assertNotIn("SECRET job request", html)

    def test_framing_is_not_blocked(self):
        fig = (SKILL / "scripts" / "lib" / "export" / "figure.mjs").read_text(encoding="utf-8")
        csp = re.search(r"FIGURE_CSP = \"([^\"]*)\"", fig).group(1)
        self.assertNotIn("frame-ancestors", csp)
        self.assertNotIn("frame-ancestors", (SKILL / "scripts" / "lib" / "export" / "xray.mjs").read_text(encoding="utf-8"))


try:
    import markdown_it  # noqa: F401
    _spec = importlib.util.spec_from_file_location("site_build", REPO / "site" / "build.py")
    build = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(build)
except ImportError:  # pragma: no cover
    build = None


@unittest.skipIf(build is None, "needs markdown-it-py (showtime's venv has it)")
class TestSite(unittest.TestCase):
    def test_xray_page_has_live_prompt_and_embed(self):
        out, media = TMP / "site", TMP / "media" / "examples" / "_xray"
        media.mkdir(parents=True)
        hero = build.XRAY["hero"]
        entry = next(e for e in build.XRAY["entries"] if e["id"] == hero)
        for name in (entry["video"], entry["poster"], entry["live"]):
            (media / name).write_bytes(b"x")
        site = build.Site(out, [TMP / "media"], "owner/repo", None, "main")
        build.build_xray(site)
        text = (out / build.XRAY_PAGE).read_text(encoding="utf-8")
        self.assertIn('class="btn primary xlive xlive-hero"', text)
        self.assertIn('data-live="../media/xray/%s"' % entry["live"], text)
        self.assertEqual(text.count("Play it live"), 1, "only entries whose live page is in this build get a button")
        self.assertIn('<p class="ask">“%s”</p>' % build.esc(entry["prompt"]), text)
        self.assertIn("Make your own with one line", text)
        self.assertIn("&lt;showtime-xray src=&quot;%smedia/xray/%s&quot;" % (build.site_url("owner/repo"), entry["live"]), text)
        self.assertIn("%smedia/xray/%s#embed" % (build.site_url("owner/repo"), entry["live"]), text)
        self.assertTrue((out / "media" / "xray" / entry["live"]).is_file())

    def test_credit_links_are_http_only(self):
        e = {"credit": "Clip", "license": "CC BY", "license_url": "javascript:alert(1)", "credit_url": " data:text/html,x", "author": "showtime"}
        text = build.xray_credit(e)
        self.assertNotIn("javascript:", text)
        self.assertNotIn("data:", text)
        self.assertNotIn("<a href", text.split("posted by")[0])
        self.assertIn('<a href="HTTPS://example.org/l">', build.xray_credit(dict(e, license_url="HTTPS://example.org/l")))

    def test_credit_links_the_clip_and_states_the_film_license(self):
        e = {"credit": "Clip: A & B", "license": "CC BY-SA 3.0", "license_url": "https://example.org/l",
             "credit_url": "https://commons.wikimedia.org/wiki/File:A_<b>.webm", "film_license": "This film is under the same license (share-alike).",
             "author": "showtime"}
        text = build.xray_credit(e)
        self.assertIn('<a href="https://commons.wikimedia.org/wiki/File:A_&lt;b&gt;.webm">Source</a>', text)
        self.assertIn("This film is under the same license (share-alike).", text)
        plain = build.xray_credit({"credit": "Clip: C", "license": "CC BY 3.0", "author": "showtime"})
        self.assertNotIn("Source", plain)

    def test_every_clip_is_linked_and_share_alike_ones_state_the_film_license(self):
        for e in build.XRAY["entries"]:
            self.assertTrue(e["credit_url"].startswith("https://commons.wikimedia.org/wiki/File:"), e["id"])
            self.assertEqual("BY-SA" in e["license"], bool(e.get("film_license")), e["id"])

    def test_embed_frame_has_room_for_the_controls(self):
        src = (REPO / "site" / "build.py").read_text(encoding="utf-8")
        self.assertIn('width="960" height="860"', src)
        self.assertIn('width="420" height="1067"', src)
        self.assertIn('allow="autoplay; clipboard-write"', src)

    def test_every_entry_names_its_live_page_and_one_prompt(self):
        for e in build.XRAY["entries"]:
            self.assertEqual(e["live"], e["id"] + "-live.html")
            self.assertTrue(e["prompt"].strip().endswith((".", "?")), e["id"])
            if e["aspect"] == "9:16":
                self.assertTrue(e["id"].endswith("9x16"), e["id"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])
