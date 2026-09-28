"""PDF import: text with page numbers, embedded images, figures with captions and credit lines,
and page renders, so a paper, report or deck can become the source material of a video.

Everything runs locally through PDFium (the pypdfium2 wheel, Apache-2.0 / BSD-3-Clause).

Output folder:
  doc.json      everything below, machine-readable (pages, metadata, outline, images, figures, renders)
  text.md       the text, one "## Page N" section per page (N = the physical page, label in brackets)
  figures.md    each figure: page, caption, credit line(s) found, the image file and the page render
  images/       embedded images: p003-01.jpg (JPEGs copied as they are), p003-02.png (others decoded)
  pages/        page renders: page-003.png (default 1600 px wide)

Captions are lines that start like "Figure 3", "Fig. 3", "Table 2", "Chart 1", "Exhibit 4", "Plate 2",
"Image 1", "Photo 2" or "Illustration 5". A caption is tied to the embedded image it sits under (or
above) and overlaps horizontally; a caption with no image nearby is a vector figure: use the page
render. Credit lines are lines like "Photo: ...", "Credit: ...", "Source: ...", "Courtesy of ...",
"Image by ...", or anything with a copyright sign, found in or right after a caption or under an image.
They are what the PDF prints, not a license: check the rights before an image goes into a published
video.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .common import ShowtimeError, ensure_dir, log, warn, write_json

PathLike = Union[str, Path]

CAPTION_RE = re.compile(
    r"^\s*(?P<kind>fig(?:ure)?\.?|table|chart|graph|exhibit|plate|image|photo(?:graph)?|illustration|diagram|map)"
    r"\s*(?P<num>[0-9]+[a-z]?(?:[.\-][0-9]+)?|[ivxlc]+)\b\s*[:.\-–—|]?\s*(?P<rest>.*)$",
    re.IGNORECASE)
CREDIT_RE = re.compile(
    r"(©|\(c\)\s|copyright\b|\bcourtesy\b|\bcredits?\s*[:\-]|\bphoto(?:graph)?\s*(?:by|credit)?\s*[:\-]|"
    r"\bphoto(?:graph)?\s+by\b|\bimage\s*(?:by|credit|source)\s*[:\-]?|\bsource\s*[:\-]|\billustration\s+by\b|"
    r"\bpicture\s*(?:by|credit)\b|\blicen[cs]ed?\s+under\b|\bcc[\s-]?by\b|\bcc0\b|\bpublic domain\b)",
    re.IGNORECASE)
MIN_IMAGE_PX = 32          # smaller embedded images are rules, bullets and spacers
DEFAULT_RENDER_WIDTH = 1600


def _pdfium():
    try:
        import pypdfium2 as pdfium  # type: ignore
        return pdfium
    except ImportError as e:
        raise ShowtimeError("PDF import needs the pypdfium2 package (%s)" % e,
                            why="it is part of the core install; an install made before it was added lacks it",
                            hint="run `showtime setup` once to add it", code=3)


def parse_pages(spec: Optional[str], n: int) -> List[int]:
    """'1-3,7' -> [0, 1, 2, 6] (0-based); None -> every page."""
    if not spec:
        return list(range(n))
    out: List[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*(?:-\s*(\d*))?$", part)
        if not m:
            raise ShowtimeError("invalid page list %r" % spec, hint="use e.g. 1-3,7 or 5- (pages count from 1)")
        a = int(m.group(1))
        b = a if m.group(2) is None and "-" not in part else (int(m.group(2)) if m.group(2) else n)
        if a < 1 or a > n or b < a:
            raise ShowtimeError("page range %r is outside 1-%d" % (part, n))
        out += [i - 1 for i in range(a, min(b, n) + 1) if i - 1 not in out]
    return out


def _clean(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("￾", "").replace("\x00", "")
    s = re.sub(r"[ \t ]+\n", "\n", s)
    return s.strip("\n")


def _lines(textpage) -> List[Dict[str, Any]]:
    """Text lines with their boxes (PDF points, origin bottom-left).

    PDFium's text rects can be whole runs or single glyphs (browser-made PDFs), so the rects are joined
    by geometry (same band, a word gap apart; a column gutter is wider, so columns stay apart) and each
    line's text is read back from its box, in content order."""
    rects = []
    for i in range(textpage.count_rects()):
        l, b, r, t = textpage.get_rect(i)
        if r - l > 0 and t - b > 0:
            rects.append((l, b, r, t))
    rects.sort(key=lambda x: x[0])
    lines: List[List[float]] = []
    for l, b, r, t in rects:
        h = t - b
        best = None
        for ln in lines:
            lh = ln[3] - ln[1]
            ov = min(t, ln[3]) - max(b, ln[1])
            if ov >= 0.5 * min(h, lh) and -max(h, lh) <= l - ln[2] <= 1.0 * max(h, lh):
                best = ln
                break
        if best is None:
            lines.append([l, b, r, t])
        else:
            best[0], best[1], best[2], best[3] = min(best[0], l), min(best[1], b), max(best[2], r), max(best[3], t)
    out: List[Dict[str, Any]] = []
    for l, b, r, t in lines:
        txt = re.sub(r"\s+", " ", textpage.get_text_bounded(l - 0.5, b, r + 0.5, t) or "").strip()
        if txt:
            out.append({"l": l, "b": b, "r": r, "t": t, "text": txt})
    out.sort(key=lambda x: (-x["t"], x["l"]))
    return out


def _below(lines: List[Dict[str, Any]], cur: Dict[str, Any], used: set) -> Optional[int]:
    """Index of the line right under `cur` in the same column (None when there is none close by)."""
    h = max(1.0, cur["t"] - cur["b"])
    best, best_gap = None, None
    for k, nx in enumerate(lines):
        if k in used or nx["t"] > cur["b"] + 0.3 * h:
            continue
        gap = cur["b"] - nx["t"]
        if gap > 1.2 * h or min(nx["r"], cur["r"]) - max(nx["l"], cur["l"]) <= 0:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = k, gap
    return best


def _overlap_x(a: Dict[str, Any], img: Sequence[float]) -> float:
    return max(0.0, min(a["r"], img[2]) - max(a["l"], img[0]))


def _credits_in(text: str) -> List[str]:
    """Credit phrases inside a caption ('... Photo: Jane Doe / NASA.')."""
    out = []
    m = CREDIT_RE.search(text)
    if m and m.start() > 0:
        out.append(text[m.start():].strip(" .;"))
    return out


def _figures_on_page(lines: List[Dict[str, Any]], images: List[Dict[str, Any]], page_no: int,
                     page_h: float) -> Tuple[List[Dict[str, Any]], List[str]]:
    figs: List[Dict[str, Any]] = []
    used = set()
    for i, ln in enumerate(lines):
        m = CAPTION_RE.match(ln["text"])
        if not m or i in used:
            continue
        rest = m.group("rest")
        # a caption line is a label, not a sentence that mentions a figure ("Figure 3 shows ...")
        if re.match(r"^(shows?|illustrates?|compares?|presents?|and|in|on|of|is|are|was|were)\b", rest, re.I):
            continue
        h = max(1.0, ln["t"] - ln["b"])
        text = ln["text"]
        used.add(i)
        credits: List[str] = []
        block = [ln]
        # the caption continues on the lines right under it (same column, small gap)
        cur = ln
        for _ in range(6):
            k = _below(lines, cur, used)
            if k is None or CAPTION_RE.match(lines[k]["text"]):
                break
            nx = lines[k]
            if CREDIT_RE.match(nx["text"]) or CREDIT_RE.search(nx["text"][:40]):
                credits.append(nx["text"])
            else:
                text += " " + nx["text"]
            used.add(k)
            block.append(nx)
            cur = nx
        credits = _credits_in(text) + credits
        cap_box = [min(x["l"] for x in block), min(x["b"] for x in block), max(x["r"] for x in block), ln["t"]]
        # the image this caption belongs to: just above it (caption under the figure) or just below
        best, best_d = None, None
        for im in images:
            bx = im["bounds"]
            if _overlap_x({"l": cap_box[0], "r": cap_box[2]}, bx) <= 0:
                continue
            d_above = cap_box[3] - bx[1]      # image bottom over caption top: negative gap
            d_below = bx[3] - cap_box[1]      # image top under caption bottom
            gap = -d_above if d_above <= 2 else (-d_below if d_below <= 2 else None)
            if gap is None or gap > 6 * h:
                continue
            if best_d is None or gap < best_d:
                best, best_d = im, gap
        kind = m.group("kind").lower().rstrip(".")
        kind = "Figure" if kind.startswith("fig") else ("Photo" if kind.startswith("photo") else kind.capitalize())
        figs.append({
            "page": page_no, "label": "%s %s" % (kind, m.group("num")),
            "caption": re.sub(r"\s+", " ", text).strip(), "credits": credits,
            "image": best["file"] if best else None, "image_id": best["id"] if best else None,
            "caption_box": [round(v, 1) for v in cap_box], "vector": best is None,
        })
        if best:
            best.setdefault("figures", []).append(figs[-1]["label"])
    def _order(f: Dict[str, Any]) -> Tuple[int, float]:
        m2 = re.match(r"(\d+)", f["label"].split(" ", 1)[-1])
        return (0, float(m2.group(1))) if m2 else (1, -f["caption_box"][3])
    figs.sort(key=_order)
    # credit lines that are not part of a caption: tie them to the image right above them
    loose: List[str] = []
    for i, ln in enumerate(lines):
        if i in used or not CREDIT_RE.search(ln["text"]):
            continue
        h = max(1.0, ln["t"] - ln["b"])
        near = [im for im in images if _overlap_x(ln, im["bounds"]) > 0 and 0 <= im["bounds"][1] - ln["t"] <= 3 * h]
        if near:
            near[0].setdefault("credits", []).append(ln["text"])
            for f in figs:
                if f["image_id"] == near[0]["id"] and ln["text"] not in f["credits"]:
                    f["credits"].append(ln["text"])
        elif len(ln["text"]) <= 200:
            loose.append(ln["text"])
    return figs, loose


def _save_image(obj, dest_stem: Path, pdfium) -> Tuple[Path, int, int]:
    """Write one embedded image: JPEG/JPEG 2000 streams copied as they are, the rest as PNG."""
    try:
        filters = [f for f in (obj.get_filters() or [])]
    except Exception:  # noqa: BLE001
        filters = []
    w, h = obj.get_px_size()
    if filters and filters[-1] in ("DCTDecode", "JPXDecode"):
        try:
            obj.extract(str(dest_stem))
            for ext in ("jpg", "jpeg", "jp2", "jpx"):
                p = dest_stem.with_name(dest_stem.name + "." + ext)
                if p.is_file():
                    return p, w, h
        except Exception:  # noqa: BLE001 - fall through to a decoded copy
            pass
    # render=True applies the image's mask and colour space the way the page shows it
    bm = obj.get_bitmap(render=True)
    pil = bm.to_pil()
    p = dest_stem.with_name(dest_stem.name + ".png")
    pil.save(str(p))
    return p, pil.width, pil.height


def extract(pdf: PathLike, out_dir: PathLike, *, pages: Optional[str] = None, render: bool = True,
            render_width: int = DEFAULT_RENDER_WIDTH, images: bool = True, password: Optional[str] = None,
            min_image: int = MIN_IMAGE_PX) -> Dict[str, Any]:
    """Extract text, images, figures and page renders from `pdf` into `out_dir`. Returns doc.json's content."""
    pdfium = _pdfium()
    import pypdfium2.raw as pdfium_c  # type: ignore
    src = Path(pdf).expanduser()
    if not src.is_file():
        raise ShowtimeError("file not found: %s" % src)
    try:
        doc = pdfium.PdfDocument(str(src), password=password)
    except pdfium.PdfiumError as e:
        msg = str(e)
        if "password" in msg.lower():
            raise ShowtimeError("%s is password-protected" % src.name, hint="pass --password (it stays on this machine)")
        raise ShowtimeError("%s is not a readable PDF (%s)" % (src.name, msg))
    out = ensure_dir(out_dir)
    n = len(doc)
    sel = parse_pages(pages, n)
    meta = {k: v for k, v in (doc.get_metadata_dict() or {}).items() if v}
    toc = []
    try:
        for it in doc.get_toc():
            pg = it.page_index
            toc.append({"level": it.level, "title": it.title, "page": (pg + 1) if pg is not None else None})
    except Exception:  # noqa: BLE001 - outlines are optional
        pass
    img_dir, page_dir = out / "images", out / "pages"
    page_rep: List[Dict[str, Any]] = []
    all_images: List[Dict[str, Any]] = []
    figures: List[Dict[str, Any]] = []
    loose_credits: List[Dict[str, Any]] = []
    renders: List[str] = []
    seen: Dict[str, str] = {}
    skipped_small = 0
    md = ["# %s" % (meta.get("Title") or src.stem), "",
          "Source: %s (%d pages%s)" % (src.name, n, "; pages %s" % pages if pages else ""), ""]
    for pi in sel:
        page = doc[pi]
        pw, ph = page.get_size()
        tp = page.get_textpage()
        text = _clean(tp.get_text_range())
        try:
            label = doc.get_page_label(pi) or None
        except Exception:  # noqa: BLE001
            label = None
        lines = _lines(tp)
        page_imgs: List[Dict[str, Any]] = []
        if images:
            k = 0
            for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=4):
                try:
                    bx = [float(v) for v in obj.get_bounds()]
                    wpx, hpx = obj.get_px_size()
                except Exception:  # noqa: BLE001
                    continue
                if min(wpx, hpx) < min_image or min(bx[2] - bx[0], bx[3] - bx[1]) < 8:
                    skipped_small += 1
                    continue
                k += 1
                ensure_dir(img_dir)
                stem = img_dir / ("p%03d-%02d" % (pi + 1, k))
                try:
                    path, iw, ih = _save_image(obj, stem, pdfium)
                except Exception as e:  # noqa: BLE001 - one bad image never stops the import
                    warn("page %d: could not extract image %d (%s)" % (pi + 1, k, e))
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                rel = path.relative_to(out).as_posix()
                repeat = seen.get(digest)
                if repeat:
                    path.unlink()        # the same logo on every page: keep one file
                    rel = repeat
                else:
                    seen[digest] = rel
                rec = {"id": "p%d-%d" % (pi + 1, k), "page": pi + 1, "file": rel, "width": iw, "height": ih,
                       "bounds": [round(v, 1) for v in bx], "repeat_of": repeat or None}
                page_imgs.append(rec)
        figs, loose = _figures_on_page(lines, page_imgs, pi + 1, ph)
        figures += figs
        loose_credits += [{"page": pi + 1, "text": t} for t in loose]
        all_images += page_imgs
        rpath = None
        if render:
            ensure_dir(page_dir)
            scale = max(0.1, render_width / float(pw or 612))
            pil = page.render(scale=scale).to_pil()
            rp = page_dir / ("page-%03d.png" % (pi + 1))
            pil.convert("RGB").save(str(rp))
            rpath = rp.relative_to(out).as_posix()
            renders.append(rpath)
            for f in figs:
                f["page_render"] = rpath
            for im in page_imgs:
                # where the image sits in the render (px, top-left origin): crop from here for vector overlays
                l, b, r, t = im["bounds"]
                im["render_box"] = [int(l * scale), int((ph - t) * scale), int(r * scale), int((ph - b) * scale)]
        page_rep.append({"page": pi + 1, "label": label, "size_pt": [round(pw, 1), round(ph, 1)],
                         "chars": len(text), "images": len(page_imgs), "render": rpath, "text": text})
        md += ["## Page %d%s" % (pi + 1, (" [%s]" % label) if label and label != str(pi + 1) else ""), "",
               text if text.strip() else "_(no text layer on this page: it is probably a scan; see the page render)_", ""]
        tp.close()
        page.close()
    doc.close()
    (out / "text.md").write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    fm = ["# Figures in %s" % src.name, "",
          "Captions and credit lines as the PDF prints them. A credit line is not a license: check the "
          "rights before an image goes into a published video.", ""]
    if not figures:
        fm.append("_No captioned figures found._")
    for f in figures:
        fm.append("- **%s** (page %d): %s" % (f["label"], f["page"], f["caption"]))
        fm.append("  - credit: %s" % ("; ".join(f["credits"]) if f["credits"] else "none printed"))
        fm.append("  - image: %s" % (f["image"] or "vector or not embedded: crop it from %s" % f.get("page_render", "the page render")))
    if loose_credits:
        fm += ["", "## Other credit lines", ""] + ["- page %d: %s" % (c["page"], c["text"]) for c in loose_credits]
    (out / "figures.md").write_text("\n".join(fm) + "\n", encoding="utf-8")
    scanned = [p["page"] for p in page_rep if p["chars"] < 20 and (p["images"] or render)]
    rep: Dict[str, Any] = {
        "source": str(src.resolve()), "pages": n, "extracted_pages": [i + 1 for i in sel], "metadata": meta,
        "outline": toc, "text_file": "text.md", "figures_file": "figures.md", "out_dir": str(out.resolve()),
        "images": all_images, "unique_images": len(seen), "skipped_small_images": skipped_small,
        "figures": figures, "other_credits": loose_credits, "renders": renders,
        "no_text_pages": scanned, "page_info": page_rep,
    }
    write_json(out / "doc.json", rep)
    if scanned:
        warn("%d page(s) have no text layer (scans?): %s; read them from the page renders" % (
            len(scanned), ", ".join(map(str, scanned[:12])) + (" ..." if len(scanned) > 12 else "")))
    log("%s: %d page(s), %d chars, %d image(s) (%d unique), %d figure(s), %d render(s) -> %s" % (
        src.name, len(sel), sum(p["chars"] for p in page_rep), len(all_images), len(seen), len(figures),
        len(renders), out))
    return rep
