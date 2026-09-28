"""Contact sheets for a folder of photos, screenshots or clips (`showtime assets sheet`).

One numbered grid image (paged when there are many) so a folder of 30 photos can be judged in
one look, plus a list with what matters for a slideshow: size after EXIF rotation, orientation,
date taken, low resolution, near-duplicates (bursts) and files that could not be read.

EXIF orientation is always applied (phone photos are stored sideways with a rotate tag), so
the sheet and the reported sizes show the photo the way it is meant to be seen. Formats Pillow
cannot open (HEIC on most installs) and video clips go through ffmpeg (which also applies the
clip's rotation); a clip is shown by one frame and labelled with its duration.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, debug, output_dir, slugify

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".jfif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
LABELS = ("none", "number", "name", "full")
LOW_RES = 1280          # long side in px below which a photo is flagged for a full-frame slideshow
SIMILAR = 5             # dHash distance (of 64 bits) at or below which two items may be near-duplicates
SIMILAR_COLOR = 14      # ... and mean |difference| of a 12x12 colour thumbnail (0-255) below this

EXIF_ORIENTATION = 0x0112
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132


def _natural_key(p: Path) -> List[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)] + [str(p).lower()]


def _kind(p: Path) -> Optional[str]:
    ext = p.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def collect(inputs: Sequence[str], recursive: bool = False) -> List[Path]:
    """Folders, files and glob patterns -> media files (deduplicated, input order kept).

    Globs are expanded here (Windows shells do not expand them); `**` recurses.
    Hidden files and our own sheet outputs are skipped.
    """
    out: List[Path] = []
    seen = set()

    def add(p: Path) -> None:
        if p.name.startswith(".") or not p.is_file() or _kind(p) is None:
            return
        k = os.path.normcase(str(p.resolve()))
        if k not in seen:
            seen.add(k)
            out.append(p)

    for raw in inputs:
        s = str(raw)
        p = Path(s).expanduser()
        if p.is_dir():
            it: Iterable[Path] = p.rglob("*") if recursive else p.iterdir()
            for f in sorted(it, key=_natural_key):
                if recursive and any(part.startswith(".") or part == "showtime-out" for part in f.relative_to(p).parts[:-1]):
                    continue
                add(f)
        elif p.is_file():
            add(p)
        elif any(ch in s for ch in "*?["):
            for f in sorted((Path(x) for x in glob.glob(os.path.expanduser(s), recursive=True)), key=_natural_key):
                add(f)
        else:
            raise ShowtimeError("not found: %s" % s, hint="pass a folder, image files, or a quoted glob like \"photos/*.jpg\"")
    return out


# ------------------------------------------------------------------ reading one item

def _exif_date(exif: Any) -> Optional[str]:
    try:
        v = None
        try:
            v = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL)
        except Exception:  # noqa: BLE001
            v = None
        v = v or exif.get(EXIF_DATETIME)
        if not v:
            return None
        m = re.match(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?", str(v).strip())
        if not m or m.group(1) == "0000":
            return None
        return "%s-%s-%s %s:%s:%s" % (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6) or "00")
    except Exception:  # noqa: BLE001
        return None


def dhash(im: Any) -> int:
    """64-bit difference hash of a PIL image (for near-duplicate detection)."""
    from PIL import Image
    g = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            # a small dead band keeps flat areas stable under JPEG noise (plain dHash flips there)
            bits = (bits << 1) | (1 if px[y * 9 + x] > px[y * 9 + x + 1] + 2 else 0)
    return bits


def colour_sig(im: Any) -> bytes:
    """12x12 RGB thumbnail bytes (dHash alone calls any two flat images identical)."""
    from PIL import Image
    return im.convert("RGB").resize((12, 12), Image.Resampling.BOX).tobytes()


def similar(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Near-duplicates: same shape, same structure (dHash) and same colours."""
    if a.get("hash") is None or b.get("hash") is None or not a.get("size") or not b.get("size"):
        return False
    ra, rb = a["size"][0] / float(a["size"][1] or 1), b["size"][0] / float(b["size"][1] or 1)
    if abs(ra - rb) > 0.05 * max(ra, rb):
        return False
    if bin(a["hash"] ^ b["hash"]).count("1") > SIMILAR:
        return False
    sa, sb = a["sig"], b["sig"]
    return sum(abs(x - y) for x, y in zip(sa, sb)) / float(len(sa)) < SIMILAR_COLOR


def _ffmpeg_frame(path: Path, at: float, box: int) -> Any:
    """One frame (rotation applied by ffmpeg) as a PIL image scaled to fit `box`."""
    from PIL import Image
    from .. import ff
    with tempfile.TemporaryDirectory(prefix="st-sheet-") as td:
        png = Path(td) / "f.png"
        args: List[str] = []
        if at > 0:
            args += ["-ss", "%.3f" % at]
        args += ["-i", str(path), "-frames:v", "1", "-vf",
                 "scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos" % (box, box), str(png)]
        ff.run_ffmpeg(args, check=True, timeout=120)
        with Image.open(png) as im:
            return im.convert("RGB")


def load(path: Path, box: int = 512) -> Dict[str, Any]:
    """Read one file -> {file, kind, size [w, h] as displayed, orientation, rotated, date, bytes,
    duration (clips), via, thumb (PIL RGB image fitting box x box, EXIF-rotated), hash, error}."""
    from PIL import Image, ImageOps
    kind = _kind(path) or "image"
    item: Dict[str, Any] = {"file": str(path), "name": path.name, "kind": kind, "bytes": None, "size": None,
                            "orientation": None, "exif_orientation": 1, "rotated": False, "date": None,
                            "duration": None, "via": None, "thumb": None, "hash": None, "sig": None, "error": None}
    try:
        item["bytes"] = path.stat().st_size
    except OSError:
        pass
    if kind == "image":
        try:
            with Image.open(path) as im:
                w, h = im.size
                exif = im.getexif()
                o = int(exif.get(EXIF_ORIENTATION) or 1)
                item["exif_orientation"] = o if 1 <= o <= 8 else 1
                item["date"] = _exif_date(exif)
                if getattr(im, "n_frames", 1) > 1:
                    im.seek(0)
                try:
                    im.draft("RGB", (box * 2, box * 2))    # fast JPEG decode at a reduced scale
                except Exception:  # noqa: BLE001
                    pass
                t = ImageOps.exif_transpose(im)
                if t.mode in ("RGBA", "LA", "P") or "transparency" in t.info:
                    rgba = t.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, (38, 38, 44))
                    bg.paste(rgba, mask=rgba.split()[-1])
                    t = bg
                else:
                    t = t.convert("RGB")
                t.thumbnail((box, box), Image.Resampling.LANCZOS)
                if item["exif_orientation"] in (5, 6, 7, 8):
                    w, h = h, w
                item["rotated"] = item["exif_orientation"] != 1
                item.update(size=[w, h], thumb=t, via="pillow")
        except Exception as e:  # noqa: BLE001 - HEIC etc.: let ffmpeg try
            debug("pillow could not open %s: %s" % (path, e))
            try:
                t = _ffmpeg_frame(path, 0, box)
                from .. import ff
                info = ff.probe(path)
                w = info.get("display_width") or info.get("width") or t.width
                h = info.get("display_height") or info.get("height") or t.height
                item.update(size=[int(w), int(h)], thumb=t, via="ffmpeg")
            except Exception as e2:  # noqa: BLE001
                item["error"] = "cannot read this image (%s)" % str(e2).strip().splitlines()[-1][:120] if str(e2).strip() else "cannot read this image"
    else:
        try:
            from .. import ff
            info = ff.probe(path)
            dur = float(info.get("duration") or 0)
            w = info.get("display_width") or info.get("width")
            h = info.get("display_height") or info.get("height")
            if not info.get("has_video") or not w:
                raise ShowtimeError("no video stream")
            t = _ffmpeg_frame(path, min(3.0, dur * 0.1) if dur > 0.5 else 0, box)
            item.update(size=[int(w), int(h)], duration=round(dur, 2), thumb=t, via="ffmpeg",
                         rotated=bool(info.get("rotation")))
        except Exception as e:  # noqa: BLE001
            item["error"] = "cannot read this clip (%s)" % (str(e).strip().splitlines() or ["?"])[-1][:120]
    if item["size"]:
        w, h = item["size"]
        r = w / float(h) if h else 1
        item["orientation"] = "square" if 0.95 <= r <= 1.05 else ("landscape" if r > 1 else "portrait")
        item["low_res"] = max(w, h) < LOW_RES
    if item["thumb"] is not None:
        item["hash"] = dhash(item["thumb"])
        item["sig"] = colour_sig(item["thumb"])
    return item


def _mtime_str(p: Path) -> str:
    import time
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
    except OSError:
        return ""


# ------------------------------------------------------------------ drawing

def _font(size: int, bold: bool = False) -> Any:
    from PIL import ImageFont
    try:
        from ..footage.fontfiles import find_font
        return ImageFont.truetype(str(find_font("inter", bold=bold).path), size)
    except Exception:  # noqa: BLE001 - no installed font: Pillow's bundled one
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # very old Pillow
            return ImageFont.load_default()


def _fit_text(draw: Any, text: str, font: Any, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


def _fmt_dur(s: float) -> str:
    s = int(round(s))
    return "%d:%02d" % (s // 60, s % 60)


def draw_page(items: Sequence[Dict[str, Any]], cols: int, cell: int, labels: str, title: str = "") -> Any:
    from PIL import Image, ImageDraw
    gap, pad = 10, 14
    cap_lines = {"none": 0, "number": 0, "name": 1, "full": 2}[labels]
    line_h = max(14, cell // 18)
    cap_h = cap_lines * (line_h + 4) + (6 if cap_lines else 0)
    title_h = (line_h + 16) if title else 0
    rows = max(1, -(-len(items) // cols))
    W = pad * 2 + cols * cell + (cols - 1) * gap
    H = pad * 2 + title_h + rows * (cell + cap_h) + (rows - 1) * gap
    sheet = Image.new("RGB", (W, H), (20, 20, 23))
    d = ImageDraw.Draw(sheet)
    f_cap = _font(line_h)
    f_badge = _font(max(16, cell // 11), bold=True)
    if title:
        d.text((pad, pad), _fit_text(d, title, _font(line_h + 2, bold=True), W - 2 * pad), fill=(236, 236, 240),
               font=_font(line_h + 2, bold=True))
    for i, it in enumerate(items):
        x = pad + (i % cols) * (cell + gap)
        y = pad + title_h + (i // cols) * (cell + cap_h + gap)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(36, 36, 42))
        th = it.get("thumb")
        if th is not None:
            t = th if max(th.size) <= cell else th.copy()
            if t is not th:
                t.thumbnail((cell, cell))
            sheet.paste(t, (x + (cell - t.width) // 2, y + (cell - t.height) // 2))
        else:
            d.text((x + 10, y + cell // 2 - line_h), _fit_text(d, "cannot read", f_cap, cell - 20), fill=(240, 120, 110), font=f_cap)
        if labels != "none":
            num = str(it["n"])
            bw = int(d.textlength(num, font=f_badge)) + 14
            bh = max(16, cell // 11) + 10
            d.rounded_rectangle([x + 6, y + 6, x + 6 + bw, y + 6 + bh], radius=6, fill=(0, 0, 0))
            d.text((x + 13, y + 9), num, fill=(255, 255, 255), font=f_badge)
            tags = []
            if it.get("duration") is not None:
                tags.append(("clip " + _fmt_dur(it["duration"]), (40, 40, 48)))
            if it.get("low_res"):
                tags.append(("low-res", (170, 40, 40)))
            if it.get("similar_to"):
                tags.append(("~%d" % it["similar_to"], (150, 110, 20)))
            tx = x + cell - 6
            for text, col in tags:
                tw = int(d.textlength(text, font=f_cap)) + 12
                d.rounded_rectangle([tx - tw, y + 6, tx, y + 10 + line_h + 4], radius=5, fill=col)
                d.text((tx - tw + 6, y + 8), text, fill=(255, 255, 255), font=f_cap)
                tx -= tw + 4
        if cap_lines:
            cy = y + cell + 5
            d.text((x + 2, cy), _fit_text(d, it["name"], f_cap, cell - 4), fill=(226, 226, 232), font=f_cap)
            if cap_lines > 1:
                if it.get("size"):
                    meta = "%dx%d %s" % (it["size"][0], it["size"][1], it.get("orientation") or "")
                    if it.get("date"):
                        meta += "  " + it["date"][:10]
                else:
                    meta = it.get("error") or ""
                d.text((x + 2, cy + line_h + 4), _fit_text(d, meta, f_cap, cell - 4), fill=(150, 150, 160), font=f_cap)
    return sheet


# ------------------------------------------------------------------ the command

def build(inputs: Sequence[str], out: Optional[Path] = None, cols: Optional[int] = None, cell: int = 300,
          labels: str = "full", per_page: int = 36, sort: str = "name", recursive: bool = False,
          overwrite: bool = False, title: Optional[str] = None, workers: int = 4) -> Dict[str, Any]:
    """Build the sheet(s). Returns {sheets: [...], json, out_dir, items: [...], counts, warnings}."""
    try:
        import PIL  # noqa: F401
    except ImportError:  # pragma: no cover
        raise ShowtimeError("Pillow is missing from the showtime environment", hint="run `showtime setup`")
    if labels not in LABELS:
        raise ShowtimeError("--labels must be one of %s" % ", ".join(LABELS))
    files = collect(inputs, recursive=recursive)
    if not files:
        raise ShowtimeError("no images or clips found in %s" % ", ".join(map(str, inputs)),
                            hint="supported: %s" % " ".join(sorted(e.lstrip(".") for e in IMAGE_EXTS | VIDEO_EXTS)))
    cell = max(96, min(1024, int(cell)))
    per_page = max(1, int(per_page))
    box = cell * 2 if cell <= 400 else cell
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
        items = list(ex.map(lambda p: load(p, box), files))
    if sort == "date":
        items.sort(key=lambda it: (it.get("date") or _mtime_str(Path(it["file"])), _natural_key(Path(it["file"]))))
    elif sort == "name":
        items.sort(key=lambda it: _natural_key(Path(it["file"])))
    elif sort != "none":
        raise ShowtimeError("--sort must be name, date or none")
    for i, it in enumerate(items, 1):
        it["n"] = i
    # near-duplicates: compare with every earlier item (n is small: this is a folder of photos)
    for i, it in enumerate(items):
        for prev in items[:i]:
            if similar(it, prev):
                it["similar_to"] = prev["n"]
                break
    # outputs
    first = Path(str(inputs[0])).expanduser()
    stem_name = first.name if first.is_dir() else (first.parent.name or "images")
    if out is None:
        out = output_dir("%s-sheet" % slugify(stem_name, default="images")) / "sheet.jpg"
    out = Path(out)
    if out.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        out = out / "sheet.jpg" if (out.is_dir() or not out.suffix) else out.with_suffix(".jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: List[str] = []
    if out.exists() and not overwrite:
        n = 2
        base = out.with_suffix("")
        while Path("%s-%d%s" % (base, n, out.suffix)).exists():
            n += 1
        fresh = Path("%s-%d%s" % (base, n, out.suffix))
        warnings.append("%s exists; wrote %s (pass --overwrite to replace)" % (out.name, fresh.name))
        out = fresh
    n_items = len(items)
    if cols is None:
        k = min(n_items, per_page)
        cols = max(1, min(8, int(round((k * 1.0) ** 0.5 + 0.49))))
    cols = max(1, min(16, int(cols)))
    pages = [items[i:i + per_page] for i in range(0, n_items, per_page)]
    sheets: List[str] = []
    for pi, chunk in enumerate(pages, 1):
        page_file = out if pi == 1 else out.with_name("%s-p%d%s" % (out.stem, pi, out.suffix))
        t = title if title is not None else "%s  (%d item%s%s)" % (stem_name, n_items, "" if n_items == 1 else "s",
                                                                  ", page %d of %d" % (pi, len(pages)) if len(pages) > 1 else "")
        img = draw_page(chunk, cols, cell, labels, t if labels != "none" else "")
        kw = {"quality": 85, "optimize": True} if page_file.suffix.lower() in (".jpg", ".jpeg") else {}
        img.save(page_file, **kw)
        sheets.append(str(page_file))
    public = []
    for it in items:
        d = {k: v for k, v in it.items() if k not in ("thumb", "hash", "sig")}
        d["page"] = (it["n"] - 1) // per_page + 1
        public.append(d)
    counts = {
        "items": n_items,
        "images": sum(1 for i in items if i["kind"] == "image"),
        "clips": sum(1 for i in items if i["kind"] == "video"),
        "landscape": sum(1 for i in items if i.get("orientation") == "landscape"),
        "portrait": sum(1 for i in items if i.get("orientation") == "portrait"),
        "square": sum(1 for i in items if i.get("orientation") == "square"),
        "rotated_by_exif": sum(1 for i in items if i["kind"] == "image" and i.get("rotated")),
        "low_res": sum(1 for i in items if i.get("low_res")),
        "similar": sum(1 for i in items if i.get("similar_to")),
        "unreadable": sum(1 for i in items if i.get("error")),
    }
    if counts["unreadable"]:
        warnings.append("%d file(s) could not be read: %s" % (counts["unreadable"], ", ".join(
            i["name"] for i in items if i.get("error"))[:300]))
    import json
    js = out.with_suffix(".json")
    report = {"sheets": sheets, "cols": cols, "cell": cell, "per_page": per_page, "labels": labels, "sort": sort,
              "counts": counts, "warnings": warnings, "items": public}
    js.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    report["json"] = str(js)
    report["out_dir"] = str(out.parent)
    return report
