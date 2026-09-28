#!/usr/bin/env python3
"""PDF import smoke tests: `showtime doc extract` (lib/st/pdfdoc.py, PDFium through pypdfium2).

The fixture PDF is written by hand here (stdlib + Pillow for one JPEG), so nothing is downloaded:
  page 1: title, body text, a JPEG photo with "Figure 1: ..." under it and a "Photo: ..." credit
          line drawn one glyph at a time (as browsers write PDFs), a 10 px bullet image (skipped), a small logo (FlateDecode RGB)
  page 2: body text, a vector figure (drawn rectangle) captioned "Figure 2. ...", the same logo
          again (kept once), a sentence that mentions "Figure 1 shows" (not a caption), and a
          loose "(c)" line; page label "ii"
  page 3: an image with no text at all (a scan): listed in no_text_pages
Asserted: text by page (text.md sections, doc.json), the JPEG copied byte for byte, the logo kept
once, small images skipped, figure captions tied to the right image (or marked vector), credit
lines found, page renders at the asked width, --pages, the default output folder inside a job,
friendly errors for a missing file, a bad page list and a non-PDF.

usage: python tests/test_doc.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())


def showtime(*args, check=True, cwd=None, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def _jpeg(w=200, h=120) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // w, y * 255 // h, 140)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _text(x, y, size, s):
    s = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return "BT /F1 %d Tf %d %d Td (%s) Tj ET\n" % (size, x, y, s)


# Helvetica advance widths (1/1000 em) for the glyphs the fixture places one by one
HELVETICA = {"P": 667, "h": 556, "o": 556, "t": 278, ":": 278, " ": 278, "J": 500, "a": 556, "n": 556, "e": 556,
             "R": 722, "i": 222, "v": 500, "r": 333, "/": 278, "C": 722, "B": 667, "Y": 667, "4": 556, ".": 278,
             "0": 556}


def _glyphs(x, y, size, s):
    """One text object per character, the way browser-made PDFs often place text."""
    out, cx = [], float(x)
    for ch in s:
        if ch != " ":
            out.append(_text(0, 0, size, ch).replace("0 0 Td", "%.2f %d Td" % (cx, y)))
        cx += size * HELVETICA.get(ch, 556) / 1000.0
    return "".join(out)


def make_pdf(path: Path) -> bytes:
    """A 3-page PDF 1.4 with a JPEG, a Flate RGB logo, a tiny bullet image and a page label."""
    jpg = _jpeg()
    logo_raw = bytes([179, 18, 31] * (64 * 64))
    dot_raw = bytes([0, 0, 0] * (10 * 10))
    objs = {}
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R /PageLabels << /Nums [0 << /S /D >> 1 << /S /r /St 2 >> 2 << /S /D /St 3 >>] >> >>"
    objs[2] = b"<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>"
    res = b"/Resources << /Font << /F1 6 0 R >> /XObject << /Im1 7 0 R /Logo 8 0 R /Dot 9 0 R >> >>"
    for n, c in ((3, 10), (4, 11), (5, 12)):
        objs[n] = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] " + res + b" /Contents %d 0 R >>" % c
    objs[6] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    objs[7] = (b"<< /Type /XObject /Subtype /Image /Width 200 /Height 120 /ColorSpace /DeviceRGB "
               b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n" % len(jpg) + jpg + b"\nendstream")
    lz = zlib.compress(logo_raw)
    objs[8] = (b"<< /Type /XObject /Subtype /Image /Width 64 /Height 64 /ColorSpace /DeviceRGB "
               b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % len(lz) + lz + b"\nendstream")
    dz = zlib.compress(dot_raw)
    objs[9] = (b"<< /Type /XObject /Subtype /Image /Width 10 /Height 10 /ColorSpace /DeviceRGB "
               b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % len(dz) + dz + b"\nendstream")
    logo = "q 40 0 0 40 500 730 cm /Logo Do Q\n"
    p1 = (_text(72, 720, 20, "Solar Sails in Practice") + _text(72, 690, 12, "This report looks at light pressure on thin film.")
          + "q 300 0 0 180 72 450 cm /Im1 Do Q\n" + _text(72, 432, 10, "Figure 1: Sail deployment test rig.")
          + _glyphs(72, 419, 9, "Photo: Jane Rivera / CC BY 4.0") + "q 8 0 0 8 72 380 cm /Dot Do Q\n"
          + _text(84, 380, 12, "A bulleted point about thrust.") + logo)
    p2 = (_text(72, 720, 12, "Second page about orbits. Figure 1 shows the rig in the lab.")
          + "0.2 0.4 0.8 rg 100 450 250 150 re f\n" + _text(72, 430, 10, "Figure 2. Orbit diagram drawn as vectors.")
          + _text(72, 100, 8, "(c) 2026 Example Lab. All rights reserved.") + logo)
    p3 = "q 400 0 0 240 100 300 cm /Im1 Do Q\n"
    objs[13] = b"<< /Title (Solar Sails) /Producer (showtime test) >>"
    for n, body in ((10, p1), (11, p2), (12, p3)):
        b = body.encode("latin-1")
        objs[n] = b"<< /Length %d >>\nstream\n" % len(b) + b + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (max(objs) + 1)
    for n in range(1, max(objs) + 1):
        out += b"%010d 00000 n \n" % offs[n]
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 13 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        max(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return jpg


class DocExtractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-doc-"))
        cls.pdf = cls.tmp / "Solar Sails.pdf"
        cls.jpg = make_pdf(cls.pdf)
        cls.out = cls.tmp / "out"
        cp = showtime("doc", "extract", cls.pdf, "-o", cls.out, "--render-width", "600", "--json")
        cls.rep = json.loads(cp.stdout)
        cls.stderr = cp.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_text_by_page(self):
        r = self.rep
        self.assertEqual(r["pages"], 3)
        self.assertEqual(r["metadata"].get("Title"), "Solar Sails")
        md = (self.out / "text.md").read_text(encoding="utf-8")
        self.assertIn("## Page 1\n", md)
        self.assertIn("## Page 2 [ii]", md)
        self.assertLess(md.index("Solar Sails in Practice"), md.index("## Page 2"))
        self.assertGreater(md.index("Second page about orbits"), md.index("## Page 2"))
        info = {p["page"]: p for p in r["page_info"]}
        self.assertEqual(info[2]["label"], "ii")
        self.assertNotIn("text", info[1], "--json leaves the page text to text.md/doc.json")
        full = json.loads((self.out / "doc.json").read_text(encoding="utf-8"))
        self.assertIn("light pressure", full["page_info"][0]["text"])
        # page 3 is an image only: a scan, said so
        self.assertEqual(r["no_text_pages"], [3])
        self.assertIn("no text layer", self.stderr)

    def test_images(self):
        imgs = self.rep["images"]
        files = {i["file"] for i in imgs}
        # photo (p1, p3 reuse the same stream), logo on p1+p2: two unique files; the 10 px dot skipped
        self.assertEqual(self.rep["unique_images"], 2, imgs)
        self.assertEqual(len(files), 2, files)
        self.assertGreaterEqual(self.rep["skipped_small_images"], 1)
        photo = [i for i in imgs if i["page"] == 1 and i["width"] == 200][0]
        self.assertTrue(photo["file"].endswith(".jpg"), photo)
        self.assertEqual((self.out / photo["file"]).read_bytes(), self.jpg, "JPEGs are copied, not re-encoded")
        self.assertEqual(photo["bounds"], [72.0, 450.0, 372.0, 630.0])
        # where it sits in the 600 px render (scale 600/612, top-left origin)
        k = 600 / 612.0
        self.assertEqual(photo["render_box"], [int(72 * k), int((792 - 630) * k), int(372 * k), int((792 - 450) * k)])
        logos = [i for i in imgs if i["width"] == 64]
        self.assertEqual(len(logos), 2)
        self.assertEqual(logos[0]["file"], logos[1]["file"])
        self.assertIsNotNone(logos[1]["repeat_of"])
        self.assertTrue((self.out / logos[0]["file"]).is_file())

    def test_figures_and_credits(self):
        figs = {f["label"]: f for f in self.rep["figures"]}
        self.assertEqual(set(figs), {"Figure 1", "Figure 2"}, "'Figure 1 shows ...' is a mention, not a caption")
        f1, f2 = figs["Figure 1"], figs["Figure 2"]
        self.assertEqual(f1["page"], 1)
        self.assertIn("Sail deployment test rig", f1["caption"])
        self.assertTrue(f1["image"] and f1["image"].endswith(".jpg"), f1)
        self.assertFalse(f1["vector"])
        self.assertIn("Photo: Jane Rivera / CC BY 4.0", f1["credits"], f1)
        self.assertNotIn("Jane Rivera", f1["caption"])
        self.assertEqual(f2["page"], 2)
        self.assertTrue(f2["vector"])
        self.assertIsNone(f2["image"])
        self.assertEqual(f2["page_render"], "pages/page-002.png")
        self.assertTrue(any("Example Lab" in c["text"] and c["page"] == 2 for c in self.rep["other_credits"]))
        fm = (self.out / "figures.md").read_text(encoding="utf-8")
        self.assertIn("**Figure 1** (page 1)", fm)
        self.assertIn("not a license", fm)

    def test_renders(self):
        from PIL import Image
        self.assertEqual(self.rep["renders"], ["pages/page-001.png", "pages/page-002.png", "pages/page-003.png"])
        with Image.open(self.out / "pages" / "page-001.png") as im:
            self.assertEqual(im.width, 600)
            self.assertAlmostEqual(im.height, round(792 * 600 / 612.0), delta=1)

    def test_pages_and_default_folder_in_job(self):
        job = self.tmp / "showtime-out" / "sails-20260927-120000"
        job.mkdir(parents=True)
        (job / "job.json").write_text(json.dumps({"slug": "sails", "mode": "quick"}), encoding="utf-8")
        cp = showtime("doc", "extract", self.pdf, "--pages", "2", "--no-render", cwd=job)
        out = Path(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(out, (job / "sources" / "solar-sails").resolve())
        d = json.loads((out / "doc.json").read_text(encoding="utf-8"))
        self.assertEqual(d["extracted_pages"], [2])
        self.assertEqual(d["renders"], [])
        self.assertFalse((out / "pages").exists())
        self.assertNotIn("## Page 1\n", (out / "text.md").read_text(encoding="utf-8"))
        again = Path(showtime("doc", "extract", self.pdf, "--pages", "2", "--no-render", cwd=job).stdout.strip())
        self.assertEqual(again.name, "solar-sails-2", "an earlier import is never overwritten")

    def test_errors(self):
        cp = showtime("doc", "extract", self.tmp / "missing.pdf", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("file not found", cp.stderr)
        cp = showtime("doc", "extract", self.pdf, "--pages", "4-9", "-o", self.tmp / "bad", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("outside 1-3", cp.stderr)
        junk = self.tmp / "notes.pdf"
        junk.write_text("not a pdf", encoding="utf-8")
        cp = showtime("doc", "extract", junk, "-o", self.tmp / "bad2", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("not a readable PDF", cp.stderr)
        for c in (cp,):
            self.assertNotIn("Traceback", c.stderr)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
