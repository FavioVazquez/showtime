#!/usr/bin/env python3
"""Benchmark judge proof: a ranking only counts when the judge verifiably looked at the frames.

benchmarks/scoring/judge.py asks a blind judge (headless Claude Code, Read tool only) to rank or compare
finished videos from stills. Earlier rounds disclosed that on 3 rankings the judge never saw the images.
Two proofs are now required for every judgment (rank.py, pairwise.py, factcheck.py):
  1. every image of its packet was opened with Read, taken from the session's own stream (not its word);
  2. every image carries a random 5-digit number in a strip at the bottom, and the judge must report it.
A judgment without both is discarded and asked again in a fresh session.

Tests (stdlib + ffmpeg; no model, no network, nothing written into the repository):
  * the digit strip is a valid PNG and survives the round trip into a stamped JPEG (readable pixels);
  * stamping adds the strip to every image, numbers are distinct and reproducible from a seed;
  * check_seen: accepts full proof; rejects an unopened image, a whole unopened video, wrong or missing
    numbers, "could not see" statements and saw_frames=false;
  * judge.ask parses a stream with Read tool calls (fake CLI) and reports which files were opened;
  * ask_verified redoes a blind first attempt and gives up honestly after the last one.
Skipped where the repository's benchmarks/ folder is not present (a skill-only install).

usage: python tests/test_bench_judge.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import random
import stat
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
SCORING = REPO / "benchmarks" / "scoring"
sys.path.insert(0, str(SKILL / "lib"))

HAVE = SCORING.is_dir()
if HAVE:
    from st import ff  # noqa: E402

    os.environ["BENCH_FFMPEG_DIR"] = str(Path(ff.ffmpeg_path()).parent)
    os.environ["SHOWTIME_BENCH_HOME"] = tempfile.mkdtemp(prefix="bench-judge-home-")
    sys.path.insert(0, str(SCORING))
    sys.path.insert(0, str(REPO / "benchmarks" / "harness"))
    import judge  # noqa: E402


def run_ff(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def make_packet(root: Path, videos=2, per_video=3, size="320x180") -> Path:
    """A packet like the benchmark's: video-N/frames/NN.jpg (+ one png), INDEX.txt, metrics, transcript."""
    for v in range(1, videos + 1):
        d = root / ("video-%d" % v) / "frames"
        d.mkdir(parents=True)
        for i in range(per_video):
            run_ff("-f", "lavfi", "-i", "testsrc2=s=%s:r=1:d=1" % size, "-frames:v", "1", "-q:v", "3", d / ("%02d.jpg" % i))
        run_ff("-f", "lavfi", "-i", "smptebars=s=%s:r=1:d=1" % size, "-frames:v", "1", d / "shot.png")
        (d / "INDEX.txt").write_text("00.jpg contact sheet\n", encoding="utf-8")
        (root / ("video-%d" % v) / "metrics.json").write_text("{}", encoding="utf-8")
        (root / ("video-%d" % v) / "transcript.txt").write_text("hello\n", encoding="utf-8")
    return root


def dims(path: Path):
    cp = subprocess.run([ff.ffmpeg_path().replace("ffmpeg", "ffprobe"), "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    w, h = cp.stdout.strip().split(",")
    return int(w), int(h)


def decode_png_gray(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n = int.from_bytes(data[pos:pos + 4], "big")
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        crc = int.from_bytes(data[pos + 8 + n:pos + 12 + n], "big")
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, "bad crc in %r" % tag
        if tag == b"IHDR":
            w, h = int.from_bytes(body[:4], "big"), int.from_bytes(body[4:8], "big")
            assert body[8:10] == b"\x08\x00"          # 8-bit grayscale
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    assert len(raw) == h * (w + 1)
    return w, h, [raw[y * (w + 1) + 1:(y + 1) * (w + 1)] for y in range(h)]


def result(read, codes_said=None, **data):
    d = {"ranking": ["1", "2"], "reason": "ok", "saw_frames": True}
    d.update(data)
    if codes_said is not None:
        d["frame_codes"] = [{"file": f, "code": c} for f, c in codes_said.items()]
    return {"ok": True, "data": d, "read": list(read), "cost_usd": 0.1}


@unittest.skipUnless(HAVE, "benchmarks/ is not here (skill-only install)")
class TestStrip(unittest.TestCase):
    def test_png_is_valid_and_shows_the_digits(self):
        w, h, rows = decode_png_gray(judge.code_png("90417"))
        self.assertEqual(h, judge.STRIP_H)
        self.assertEqual(w, 5 * 6 * judge.GLYPH_SCALE + 2 * judge.STRIP_MARGIN)
        lit = sum(bytes(r).count(b"\xff") for r in rows)
        self.assertGreater(lit, 300)
        self.assertEqual(sum(bytes(r).count(b"\x00") for r in rows) + lit, w * h)     # only black and white
        # different numbers draw different pixels
        self.assertNotEqual(judge.code_png("90417"), judge.code_png("90418"))

    def test_every_digit_has_a_distinct_7x5_glyph(self):
        seen = set()
        for ch, g in judge.GLYPHS.items():
            self.assertEqual(len(g), 7, ch)
            self.assertTrue(all(len(r) == 5 and set(r) <= {".", "#"} for r in g), ch)
            seen.add(g)
        self.assertEqual(sorted(judge.GLYPHS), list("0123456789"))
        self.assertEqual(len(seen), 10)

    def test_codes_are_distinct_five_digits_and_seeded(self):
        files = ["video-1/frames/%02d.jpg" % i for i in range(40)]
        a = judge.new_codes(files, random.Random("x"))
        b = judge.new_codes(files, random.Random("x"))
        c = judge.new_codes(files, random.Random("y"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(set(a.values())), 40)
        self.assertTrue(all(len(v) == 5 and v.isdigit() and v[0] != "0" for v in a.values()))


@unittest.skipUnless(HAVE, "benchmarks/ is not here (skill-only install)")
class TestStamp(unittest.TestCase):
    def test_stamps_every_image_and_the_number_is_readable_from_the_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            pk = make_packet(Path(tmp) / "pk")
            before = {f: dims(pk / f) for f in judge.frame_list(pk)}
            self.assertEqual(len(before), 2 * 4)                                 # 3 jpg + 1 png per video
            codes = judge.stamp_packet(pk, random.Random(3))
            self.assertEqual(set(codes), set(before))
            self.assertEqual(len(set(codes.values())), len(codes))
            self.assertEqual(judge.frame_list(pk), sorted(before))              # same files, nothing added or lost
            self.assertFalse((pk / ".stamp").exists())
            self.assertFalse(any(str(c) in p.name for p in pk.rglob("*") for c in codes.values()),
                             "a number must not appear in any file name")
            for f, code in codes.items():
                w, h = before[f]
                self.assertEqual(dims(pk / f), (w, h + judge.STRIP_H), f)
                # crop the strip out of the stamped file and compare with the strip we drew
                sw, sh, rows = decode_png_gray(judge.code_png(code))
                raw = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-i", str(pk / f), "-vf",
                                      "crop=%d:%d:0:ih-%d,format=gray" % (sw, sh, sh), "-f", "rawvideo", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
                want = b"".join(rows)
                self.assertEqual(len(raw), len(want), f)
                agree = sum((a > 128) == (b > 128) for a, b in zip(raw, want)) / len(want)
                self.assertGreater(agree, 0.97, "%s: the stamped number is not readable (%.3f)" % (f, agree))
                # and no other image's number is what this strip shows
                other = [c for g, c in codes.items() if g != f][0]
                _, _, orows = decode_png_gray(judge.code_png(other))
                agree_other = sum((a > 128) == (b > 128) for a, b in zip(raw, b"".join(orows))) / len(want)
                self.assertLess(agree_other, agree)


@unittest.skipUnless(HAVE, "benchmarks/ is not here (skill-only install)")
class TestCheckSeen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pk = Path(self.tmp.name) / "pk"
        for v in (1, 2):
            d = self.pk / ("video-%d" % v) / "frames"
            d.mkdir(parents=True)
            for i in range(3):
                (d / ("%02d.jpg" % i)).write_bytes(b"jpg")
        self.files = judge.frame_list(self.pk)
        self.codes = judge.new_codes(self.files, random.Random(1))
        self.folders = ["video-1", "video-2"]

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, res, codes="default"):
        return judge.check_seen(res, self.pk, self.folders, self.codes if codes == "default" else codes)

    def test_full_proof_passes(self):
        self.assertEqual(len(self.files), 6)
        res = result(self.files, self.codes)
        self.assertIsNone(self.check(res))
        p = judge.proof(res, self.pk, self.codes)
        self.assertEqual((p["images_total"], p["images_opened"], p["codes_total"], p["codes_right"]), (6, 6, 6, 6))

    def test_absolute_read_paths_count(self):
        res = result([str(self.pk / f) for f in self.files], self.codes)
        self.assertIsNone(self.check(res))

    def test_an_unopened_image_fails_even_with_its_number_guessed(self):
        read = self.files[:-1]
        res = result(read, self.codes)
        why = self.check(res)
        self.assertIn("5 of 6", why)
        self.assertIn(self.files[-1], why)

    def test_a_whole_unopened_video_fails(self):
        read = [f for f in self.files if f.startswith("video-1/")]
        why = self.check(result(read, {f: self.codes[f] for f in read}))
        self.assertIsNotNone(why)
        self.assertIn("video-2", why)

    def test_wrong_numbers_fail_but_one_slip_in_ten_is_tolerated(self):
        said = dict(self.codes)
        said[self.files[0]] = "00000"
        self.assertIn("reading-check", self.check(result(self.files, said)))    # 1 of 6 wrong: over 10 percent
        many = judge.new_codes([("v/%d.jpg" % i) for i in range(20)], random.Random(2))
        big = {f: c for f, c in many.items()}
        packet = Path(self.tmp.name) / "big"
        (packet / "video-1" / "frames").mkdir(parents=True)
        for f in big:
            (packet / "video-1" / "frames" / Path(f).name).write_bytes(b"x")
        files = judge.frame_list(packet)
        codes = judge.new_codes(files, random.Random(4))
        said = dict(codes)
        said[files[0]] = "11111"
        said[files[1]] = "22222"
        self.assertIsNone(judge.check_seen(result(files, said), packet, ["video-1"], codes))     # 2 of 20 wrong
        said[files[2]] = "33333"
        self.assertIsNotNone(judge.check_seen(result(files, said), packet, ["video-1"], codes))  # 3 of 20 wrong

    def test_missing_or_garbled_codes_fail(self):
        self.assertIsNotNone(self.check(result(self.files)))                    # no frame_codes at all
        said = {f: "abc" for f in self.files}
        self.assertIsNotNone(self.check(result(self.files, said)))

    def test_number_with_spaces_or_dashes_is_read_as_digits(self):
        said = {f: " ".join(self.codes[f]) for f in self.files}
        self.assertIsNone(self.check(result(self.files, said)))

    def test_could_not_see_statements_fail(self):
        self.assertIn("could not see", self.check(result(self.files, self.codes, saw_frames=False)))
        for text in ("I could not open the images so this rests on the transcript",
                     "Unable to view the frames; ranked from the metrics",
                     "I couldn't open the contact sheet, ranking from numbers"):
            r = result(self.files, self.codes, reason=text)
            self.assertIsNotNone(self.check(r), text)

    def test_without_codes_the_read_log_is_still_required(self):
        self.assertIsNone(self.check(result(self.files), codes=None))
        self.assertIsNotNone(self.check(result(self.files[:3]), codes=None))

    def test_schema_requires_the_numbers(self):
        s = judge.with_codes({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})
        self.assertIn("frame_codes", s["properties"])
        self.assertEqual(s["required"], ["a", "frame_codes"])


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
mode = open(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "mode")).read().strip()
files = []
for root, _, names in os.walk("."):
    for n in names:
        if n.lower().endswith((".jpg", ".png")) and ".tmp" not in root:
            files.append(os.path.relpath(os.path.join(root, n), "."))
files.sort()
opened = files if mode == "read_all" else files[:1]
print(json.dumps({"type": "system", "subtype": "init"}))
for i, f in enumerate(opened):
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t%d" % i, "name": "Read", "input": {"file_path": os.path.abspath(f)}}]}}))
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "tx", "name": "Grep", "input": {"file_path": "/etc/passwd"}}]}}))
print(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.25, "structured_output":
                  {"ranking": ["1", "2"], "saw_frames": True, "reason": "fine"}}))
'''


@unittest.skipUnless(HAVE and os.name != "nt", "benchmarks/ is not here, or no POSIX shebang launcher")
class TestAskStream(unittest.TestCase):
    """judge.ask against a fake `claude` that streams tool calls: the read log comes from the stream."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = Path(self.tmp.name) / "claude"
        self.fake.write_text("#!%s\n" % sys.executable + FAKE_CLAUDE.split("\n", 1)[1], encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        self.old = {k: os.environ.get(k) for k in ("BENCH_CLAUDE",)}
        os.environ["BENCH_CLAUDE"] = str(self.fake)
        self.pk = make_packet(Path(self.tmp.name) / "pk", videos=2, per_video=2)

    def mode(self, name):
        (Path(self.tmp.name) / "mode").write_text(name, encoding="utf-8")   # the child's env is scrubbed: use a file

    def tearDown(self):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def test_read_log_lists_the_opened_images_only(self):
        self.mode("read_all")
        res = judge.ask(self.pk, "p", {"type": "object"})
        self.assertTrue(res["ok"])
        self.assertEqual(sorted(res["read"]), judge.frame_list(self.pk))          # Grep call is not a Read
        self.mode("read_one")
        res = judge.ask(self.pk, "p", {"type": "object"})
        self.assertEqual(len(res["read"]), 1)
        self.assertIn("opened 1 of 6", judge.check_seen(res, self.pk, ["video-1", "video-2"]))

    def test_ask_verified_needs_the_codes_a_fake_cannot_read(self):
        """The fake opens every image but cannot read the numbers: every attempt fails and none is accepted."""
        self.mode("read_all")
        builds = []

        def build():
            builds.append(1)
            return make_packet(Path(self.tmp.name) / ("pk%d" % len(builds)), videos=2, per_video=2)

        res, log = judge.ask_verified(build, lambda pk: "p", {"type": "object", "properties": {}, "required": []},
                                      ["video-1", "video-2"], attempts=2, seed="t")
        self.assertFalse(res["ok"])
        self.assertIn("reading-check", res["error"])
        self.assertEqual(len(log), 2)
        self.assertEqual(len(builds), 2)                                          # fresh packet per attempt
        self.assertTrue(all(a["images_opened"] == a["images_total"] == 6 for a in log))
        self.assertTrue(all(a["codes_right"] == 0 for a in log))
        self.assertNotEqual(log[0]["frame_codes"], log[1]["frame_codes"])         # fresh numbers per attempt


@unittest.skipUnless(HAVE, "benchmarks/ is not here (skill-only install)")
class TestAskVerified(unittest.TestCase):
    """The redo rule with judge.ask replaced: blind first attempt -> asked again; last failure is reported."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_ask = judge.ask
        self.n = 0
        self.stamped = []
        self.orig_stamp = judge.stamp_packet

        def fake_stamp(pk, rng=None):
            codes = judge.new_codes(judge.frame_list(pk), rng or random.Random())
            self.stamped.append(codes)
            return codes

        judge.stamp_packet = fake_stamp

    def tearDown(self):
        judge.ask = self.orig_ask
        judge.stamp_packet = self.orig_stamp
        self.tmp.cleanup()

    def build(self):
        self.n += 1
        pk = Path(self.tmp.name) / ("pk%d" % self.n)
        for v in (1, 2):
            d = pk / ("video-%d" % v) / "frames"
            d.mkdir(parents=True)
            (d / "00.jpg").write_bytes(b"x")
            (d / "01.jpg").write_bytes(b"x")
        return pk

    def test_blind_then_good_is_accepted_on_the_second_attempt(self):
        calls = []

        def ask(pk, prompt, schema, **kw):
            calls.append(prompt)
            files = judge.frame_list(pk)
            self.assertIn("frame_codes", schema["properties"])                    # the schema demands the numbers
            self.assertIn("Reading check", prompt)
            if len(calls) == 1:
                return result([], None, saw_frames=False, reason="I could not open the images")
            return result(files, self.stamped[-1])

        judge.ask = ask
        res, log = judge.ask_verified(self.build, lambda pk: "rank these", {"type": "object", "properties": {}, "required": []},
                                      ["video-1", "video-2"], attempts=3, seed="s")
        self.assertTrue(res["ok"])
        self.assertEqual([a["ok"] for a in log], [False, True])
        self.assertEqual(len(calls), 2)
        self.assertIn("could not see", log[0]["error"])
        self.assertEqual((log[1]["images_opened"], log[1]["codes_right"]), (4, 4))

    def test_all_attempts_blind_is_reported_not_accepted(self):
        judge.ask = lambda pk, prompt, schema, **kw: result([], None)
        res, log = judge.ask_verified(self.build, lambda pk: "p", {"type": "object", "properties": {}, "required": []},
                                      ["video-1", "video-2"], attempts=3, seed="s")
        self.assertFalse(res["ok"])
        self.assertEqual(len(log), 3)
        self.assertIn("opened 0 of 4", res["error"])

    def test_infrastructure_failure_is_retried_and_timeouts_are_not(self):
        seq = [{"ok": False, "error": "boom"}, {"ok": False, "error": "timeout"}, result([], None)]
        judge.ask = lambda pk, prompt, schema, **kw: seq.pop(0)
        res, log = judge.ask_verified(self.build, lambda pk: "p", {"type": "object", "properties": {}, "required": []},
                                      ["video-1", "video-2"], attempts=3, seed="s")
        self.assertFalse(res["ok"])
        self.assertEqual(len(log), 2)                                             # stops at the timeout

    def test_pairwise_both_orders(self):
        """An arm wins a pair only when it won with either arm shown first; else split or tie."""
        import pairwise
        rec = lambda a, b, first, w: {"task": "t1", "a": a, "b": b, "first": first, "winner": w}  # noqa: E731
        recs = [rec("p", "q", "p", "p"), rec("p", "q", "q", "p"), rec("p", "q", "p", "p"),        # p both orders
                rec("p", "r", "p", "p"), rec("p", "r", "r", "r"),                                   # first wins: split
                rec("q", "r", "q", "tie"), rec("q", "r", "r", "tie"),
                rec("q", "s", "q", "q")]                                                             # one order
        self.assertEqual(pairwise.both_orders(recs)["t1"], {"p vs q": "p", "p vs r": "split", "q vs r": "tie",
                                                            "q vs s": "one order only"})

    def test_rank_and_pairwise_use_the_proof(self):
        for name in ("rank.py", "pairwise.py", "factcheck.py"):
            text = (SCORING / name).read_text(encoding="utf-8")
            self.assertIn("ask_verified", text, name)
            self.assertNotIn("judge.ask(", text, name + " must not ask without the proof")


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
