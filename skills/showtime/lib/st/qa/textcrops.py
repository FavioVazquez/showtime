"""Full-resolution crops of the largest text lines in a frame, for the critic's type detail pass.

Contact sheets shrink frames to thumbnails, where a word and a formula on different baselines, a
size or weight jump inside one line, tight kerning or a lone last word all vanish. review-pack cuts
the biggest lines out of full-size frames so they can be judged at 100 %.

Detection is plain image processing (numpy + OpenCV, no OCR, works for any video): sharp edges ->
glyph-sized blobs -> blobs of similar height side by side grouped into lines -> the tallest lines,
padded. It finds text of every engine (DOM, canvas, Manim, burned captions) and never reads it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, "os.PathLike[str]"]
Box = Tuple[int, int, int, int]      # x, y, w, h in pixels

EDGE = 48            # morphological gradient that counts as a glyph edge (0-255)


def _edges(gray: Any) -> Any:
    """1 where a sharp edge is (glyph outlines), 0 elsewhere."""
    import cv2
    import numpy as np
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, k)
    return (grad > EDGE).astype(np.uint8)


def _glyphs(gray: Any) -> List[Box]:
    import cv2
    H, W = gray.shape[:2]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    bw = cv2.dilate(_edges(gray), k, iterations=1)
    n, _lab, stats, _c = cv2.connectedComponentsWithStats(bw, connectivity=8)
    out: List[Box] = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (0.012 * H <= h <= 0.22 * H) or w > 0.4 * W:
            continue
        # letters of bold or tightly set type touch after the dilation and come out as whole words:
        # keep word-shaped blobs too (a rule or strip is under the minimum height, an outline is sparse)
        if not (0.08 <= w / float(h) <= 14.0):
            continue                                   # rules, strips, long outlines
        if area < 0.12 * w * h:
            continue                                   # a thin curve (an arc, a ring edge), not a glyph
        out.append((x, y, w, h))
    return out


def _bbox(g: Sequence[Box]) -> Box:
    x0, y0 = min(b[0] for b in g), min(b[1] for b in g)
    return x0, y0, max(b[0] + b[2] for b in g) - x0, max(b[1] + b[3] for b in g) - y0


def _med(g: Sequence[Box]) -> int:
    hs = sorted(b[3] for b in g)
    return hs[len(hs) // 2]


def _lines(glyphs: Sequence[Box]) -> List[Dict[str, Any]]:
    """Group glyph boxes into lines: vertical overlap, a gap under one glyph height, similar sizes
    (a superscript may be half the height)."""
    n = len(glyphs)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: glyphs[i][0])
    for ii, i in enumerate(order):
        xi, yi, wi, hi = glyphs[i]
        for j in order[ii + 1:]:
            xj, yj, wj, hj = glyphs[j]
            gap = xj - (xi + wi)
            if gap > 1.0 * max(hi, hj):
                break
            ov = min(yi + hi, yj + hj) - max(yi, yj)
            if ov < 0.35 * min(hi, hj) or max(hi, hj) > 3.0 * min(hi, hj):
                continue
            parent[find(j)] = find(i)
    groups: Dict[int, List[Box]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(glyphs[i])
    # second pass: join neighbouring groups on one line (a misaligned part, a "?" after a superscript)
    gs = [list(g) for g in groups.values()]
    merged = True
    while merged:
        merged = False
        gs.sort(key=lambda g: min(b[0] for b in g))
        for a in range(len(gs)):
            for b in range(a + 1, len(gs)):
                A, B = _bbox(gs[a]), _bbox(gs[b])
                ha, hb = _med(gs[a]), _med(gs[b])
                gap = max(A[0], B[0]) - min(A[0] + A[2], B[0] + B[2])
                ov = min(A[1] + A[3], B[1] + B[3]) - max(A[1], B[1])
                if gap <= 0.9 * max(ha, hb) and ov >= 0.4 * min(A[3], B[3]) and max(ha, hb) <= 3.0 * min(ha, hb):
                    gs[a] += gs.pop(b)
                    merged = True
                    break
            if merged:
                break
    lines = []
    for g in gs:
        if len(g) < 2:
            continue
        x0, y0, w, h = _bbox(g)
        med = _med(g)
        if w < 1.2 * med:
            continue
        lines.append({"box": (x0, y0, w, h), "glyphs": len(g), "height": med})
    lines.sort(key=lambda l: (-l["height"], -l["glyphs"]))
    return lines


def _extend(mask: Any, box: Box, height: int) -> Box:
    """Grow a line box sideways over the rest of the line: columns whose edges fill part of the line's
    band, across gaps up to 1.3 line heights (a word the glyph filter missed, the far end of the sentence),
    so a crop never ends inside a word."""
    H, W = mask.shape[:2]
    x, y, w, h = box
    y0, y1 = max(0, y), min(H, y + h)
    if y1 <= y0:
        return box
    # a column is ink when edges fill a real part of the band (letters), not a speck (snow, dust, dots)
    cols = mask[y0:y1, :].sum(axis=0) >= max(3.0, 0.12 * (y1 - y0))
    gap_max = int(round(1.3 * height))
    x0, x1 = x, x + w          # [x0, x1)
    k, gap = x1, 0
    while k < W and gap <= gap_max:
        if cols[k]:
            x1, gap = k + 1, 0
        else:
            gap += 1
        k += 1
    k, gap = x0 - 1, 0
    while k >= 0 and gap <= gap_max:
        if cols[k]:
            x0, gap = k, 0
        else:
            gap += 1
        k -= 1
    return x0, y, x1 - x0, h


def find_lines(image: PathLike, limit: int = 3) -> List[Dict[str, Any]]:
    """The `limit` tallest text lines of an image: [{"box": (x, y, w, h), "height": px, "glyphs": n}]."""
    import cv2
    img = cv2.imread(os.fspath(image), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    return _lines(_glyphs(img))[:limit]


def _iou(a: Box, b: Box) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax1, bx1) - max(a[0], b[0]))
    ih = max(0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / float(union) if union else 0.0


def crops(frames: Sequence[Tuple[float, str, PathLike]], out_dir: PathLike, *, per_frame: int = 2,
          limit: int = 16) -> List[Dict[str, Any]]:
    """Crop the tallest lines of each (time, label, full-size frame) into out_dir/text-<t>-<k>.png.

    A line that sits in the same place with the same pixels as an earlier crop (a title held across
    scenes) is kept once. Returns [{"t", "label", "path", "box", "line_px"}]."""
    import cv2
    import numpy as np
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    kept: List[Tuple[Box, Any]] = []
    res: List[Dict[str, Any]] = []
    for t, label, src in frames:
        img = cv2.imread(os.fspath(src), cv2.IMREAD_COLOR)
        if img is None:
            continue
        H, W = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mask = _edges(gray)
        k = 0
        for ln in _lines(_glyphs(gray)):
            if k >= per_frame or len(res) >= limit:
                break
            x, y, w, h = _extend(mask, ln["box"], ln["height"])
            pad = int(round(0.6 * ln["height"]))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
            box = (x0, y0, x1 - x0, y1 - y0)
            crop = img[y0:y1, x0:x1]
            dup = False
            for kb, kc in kept:
                if _iou(kb, box) > 0.7 and kc.shape == crop.shape and \
                        float(np.mean(np.abs(kc.astype(np.int16) - crop.astype(np.int16)))) < 4.0:
                    dup = True
                    break
            if dup:
                continue
            k += 1
            dest = out / ("text-%08.3fs-%d.png" % (t, k))
            cv2.imwrite(os.fspath(dest), crop)
            kept.append((box, crop))
            res.append({"t": round(float(t), 3), "label": label, "path": str(dest), "box": list(box),
                        "line_px": int(ln["height"])})
        if len(res) >= limit:
            break
    return res
