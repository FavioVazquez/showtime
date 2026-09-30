#!/usr/bin/env python3
"""Build the style reference video for T10 ("make it like this reference") with ffmpeg only.

    python benchmarks/fixtures/make_reference.py            # writes media/style-reference.mp4 (ignored by git)
    python benchmarks/fixtures/make_reference.py --out x.mp4 --font /path/to/anton-latin-400-normal.ttf

The reference is original work made for this benchmark (no third-party footage, music or artwork): a 20 s,
1920x1080 poster-style announcement for a fictional evening run club. Everything is drawn by ffmpeg filters
(flat colour, one typeface, an animated wipe and a progress bar) and the sound is synthesised by `aevalsrc`
(a 120 BPM kick and off-beat tick, a bass line, a closing hit). Its style grammar is written out in
`tasks/t10-like-reference.md`, so judges can check a deliverable against it.

The typeface is Anton (SIL Open Font License 1.1), fetched once from the pinned Fontsource release below and
checked by SHA-256 (cached in <bench home>/cache/). Output bytes may differ between ffmpeg builds; the look
and timing do not.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harness"))
import common  # noqa: E402

OUT = HERE / "media" / "style-reference.mp4"
FONT_URL = "https://cdn.jsdelivr.net/fontsource/fonts/anton@5.3.0/latin-400-normal.ttf"
FONT_SHA256 = "56ff0da14df67cbdd38d47bd657c7bb65c3defe2af792472c895c21cb1c4e341"

W, H, FPS, DUR = 1920, 1080, 30, 20.0
BEAT = 0.5                       # 120 BPM
PAPER, INK, ACCENT = "0xF2EEE3", "0x141414", "0xE4412B"
MARGIN = 120

# The hook: one word per beat, hard cuts, the ground flips to ink on every other beat.
HOOK = ["THE", "CITY", "IS", "YOURS", "AFTER", "DARK."]
# Three information cards (4 s each), then the end card. (label, line 1, line 2)
CARDS = [("WHAT", "A 5 KM", "EVENING RUN"), ("WHEN", "THURSDAYS", "7 PM"), ("WHERE", "RIVER BRIDGE", "EAST SIDE")]
END = ("NIGHT RUN CLUB", "ALL PACES WELCOME")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def font_path(given: str = None) -> Path:
    if given:
        return Path(given)
    dst = common.bench_home() / "cache" / "anton-latin-400-normal-5.3.0.ttf"
    if dst.exists() and sha256(dst) == FONT_SHA256:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    with urllib.request.urlopen(FONT_URL, timeout=60) as r, open(tmp, "wb") as fh:
        fh.write(r.read())
    if sha256(tmp) != FONT_SHA256:
        tmp.unlink()
        raise SystemExit("font SHA-256 mismatch for %s: the pinned release changed; re-pin it on purpose" % FONT_URL)
    tmp.replace(dst)
    return dst


def esc_path(p: Path) -> str:
    """A path inside a filtergraph option value (quotes and colons escaped; forward slashes on Windows too)."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


class Graph:
    def __init__(self, font: Path, tmp: Path):
        self.font, self.tmp, self.n, self.chain = font, tmp, 0, []

    def text(self, s: str, size: int, color: str, x: str, y: str, start: float, end: float, alpha: str = "1") -> None:
        self.n += 1
        tf = self.tmp / ("t%02d.txt" % self.n)
        tf.write_text(s, encoding="utf-8")   # textfile= avoids escaping commas, colons and quotes in the words
        self.chain.append(
            "drawtext=fontfile='%s':textfile='%s':fontsize=%d:fontcolor=%s:x=%s:y=%s:alpha='%s':enable='between(t,%.3f,%.3f)'"
            % (esc_path(self.font), esc_path(tf), size, color, x, y, alpha, start, end - 0.001))


def build_graph(font: Path, tmp: Path) -> str:
    g = Graph(font, tmp)
    # inputs: 0 paper ground, 1 ink ground, 2 accent wipe panel, 3 accent progress bar
    pre = [
        # the hook flips to an ink ground on odd beats; the end card is ink from 16 s
        "[0:v][1:v]overlay=enable='lt(t,3)*eq(mod(floor(t*2),2),1)+gte(t,16)'[g0]",
        # a progress bar along the bottom fills over each 4 s card
        "[g0][3:v]overlay=x='-W+W*mod(t,4)/4':y=H-h:enable='between(t,4,15.999)'[g1]",
    ]
    for i, word in enumerate(HOOK):
        t0 = i * BEAT
        g.text(word, 440, PAPER if i % 2 else INK, str(MARGIN), "(h-text_h)/2", t0, t0 + BEAT)
    g.text("NIGHT", 300, ACCENT, str(MARGIN), "(h/2)-text_h-10", 3.0, 4.0)
    g.text("RUN CLUB", 300, INK, str(MARGIN), "(h/2)+10", 3.5, 4.0)
    for k, (label, l1, l2) in enumerate(CARDS):
        s = 4.0 + 4.0 * k
        g.text("%02d/04" % (k + 1), 56, INK, str(MARGIN), "96", s, s + 4)
        g.text(label, 72, ACCENT, str(MARGIN), "330", s, s + 4)
        g.text(l1, 230, INK, str(MARGIN), "'430+60*max(0\\,1-(t-%.3f)/0.25)'" % s, s, s + 4,
               alpha="min(1\\,(t-%.3f)/0.25)" % s)
        g.text(l2, 230, INK, str(MARGIN), "'690+60*max(0\\,1-(t-%.3f)/0.25)'" % (s + BEAT), s + BEAT, s + 4,
               alpha="min(1\\,(t-%.3f)/0.25)" % (s + BEAT))
    g.text("04/04", 56, PAPER, str(MARGIN), "96", 16.0, DUR)
    g.text(END[0], 250, ACCENT, str(MARGIN), "'380+60*max(0\\,1-(t-16)/0.25)'", 16.0, DUR, alpha="min(1\\,(t-16)/0.25)")
    g.text(END[1], 96, PAPER, str(MARGIN), "700", 16.5, DUR, alpha="min(1\\,(t-16.5)/0.25)")
    post = ["[g1]" + ",".join(g.chain) + "[g2]",
            # the section wipe: an accent panel sweeps in over the last beat quarter and out over the next one
            "[g2][2:v]overlay=x='if(gte(mod(t\\,4)\\,3.75)\\,-W+W*(mod(t\\,4)-3.75)/0.25\\,W*mod(t\\,4)/0.25)'"
            ":enable='between(t,3.75,16.25)*(gte(mod(t,4),3.75)+lt(mod(t,4),0.25))',format=yuv420p[v]"]
    return ";".join(pre + post)


AUDIO = (
    # kick on every beat until the end card (pitch falls fast), quieter on the cards' off-bars
    "0.9*lt(t\\,16)*sin(2*PI*(48+140*exp(-30*mod(t\\,0.5)))*mod(t\\,0.5))*exp(-14*mod(t\\,0.5))"
    # an off-beat tick
    "+0.12*lt(t\\,16)*sin(2*PI*6200*mod(t+0.25\\,0.5))*exp(-90*mod(t+0.25\\,0.5))"
    # a bass line under the cards, one note per 2 s: A1 D2 C2 E2
    "+0.22*between(t\\,4\\,16)*sin(2*PI*(55*eq(mod(floor(t/2)\\,4)\\,0)+73.42*eq(mod(floor(t/2)\\,4)\\,1)"
    "+65.41*eq(mod(floor(t/2)\\,4)\\,2)+82.41*eq(mod(floor(t/2)\\,4)\\,3))*t)"
    # one closing hit on the end card, then silence for the last second
    "+0.9*between(t\\,16\\,19)*sin(2*PI*44*(t-16))*exp(-2.2*(t-16))"
)


def build(out: Path = OUT, font: str = None) -> Path:
    ff = common.ffmpeg()
    f = font_path(font)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="stref-"))
    try:
        graph = build_graph(f, tmp)
        src = lambda c, s: ["-f", "lavfi", "-i", "color=c=%s:s=%s:r=%d:d=%.1f" % (c, s, FPS, DUR)]  # noqa: E731
        cmd = ([ff, "-hide_banner", "-loglevel", "error", "-y"] + src(PAPER, "%dx%d" % (W, H)) + src(INK, "%dx%d" % (W, H))
               + src(ACCENT, "%dx%d" % (W, H)) + src(ACCENT, "%dx18" % W)
               + ["-f", "lavfi", "-i", "aevalsrc='%s':s=48000:d=%.1f" % (AUDIO, DUR),
                  "-filter_complex", graph + ";[4:a]loudnorm=I=-16:TP=-1.5:LRA=7,aformat=channel_layouts=stereo[a]",
                  "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                  "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", "%.1f" % DUR, "-map_metadata", "-1",
                  "-movflags", "+faststart", str(out)])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("ffmpeg failed building the reference:\n%s" % r.stderr[-2000:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--font", help="a local copy of Anton Regular (default: the pinned download)")
    a = ap.parse_args()
    p = build(Path(a.out), a.font)
    pr = common.probe(p)
    print("style-reference ready: %s (%.1f s, %sx%s, %.1f MB)" % (p, pr.get("duration") or 0, (pr.get("video") or {}).get("width"),
                                                               (pr.get("video") or {}).get("height"), p.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
