"""Near-copy guard and credit line for style references.

A reference lends its grammar; a render that reproduces its pictures is a copy. The guard compares a
render with each reference of its job (<job>/references/*/fingerprint.npz):

  frames   up to SAMPLES frames of the render (2 per second, evenly spread), each reduced to 64x36 grey,
           against every reference frame at 4 per second. A render frame is a near copy of a reference
           frame when their block SSIM (at 48x27, each frame normalised to one mean and contrast, so a
           grade does not hide a copy) is >= FRAME_SSIM and their 64-bit difference hashes differ in
           <= FRAME_HASH bits, or the SSIM alone is >= FRAME_SSIM_ALONE. Flat frames (a plain ground,
           grey spread < FLAT_STD) prove nothing and are not counted.
  rhythm   the render's cut positions against the reference's, both as a share of their length:
           the F1 score of cuts that line up within 2 % of the length (0 when the shot counts differ
           by more than a quarter). The rhythm alone is grammar and never fails.

  detail   when both videos are on disk, every frame the coarse test calls a near copy is confirmed at
           256x144: block SSIM over the textured blocks only (flat ground in both frames says nothing),
           at the best of a few small zooms and shifts (a crop or reframe does not hide a copy). It stays a
           copy at >= DETAIL_SSIM. The same layout with other words or pictures (a same-style video) scores
           about 0.3-0.45; a re-encode, grade or small crop of the reference about 0.8-0.95.

Verdict (documented in references/reference.md):
  FAIL reference_copy   >= COPY_FAIL of the counted render frames are near copies, or >= COPY_WITH_RHYTHM
                        of them are while the rhythm similarity is >= RHYTHM_HIGH
  WARN reference_close  >= COPY_WARN of the counted frames are near copies
  PASS                  otherwise; the line notes when the rhythm follows the reference closely
                        (similarity >= RHYTHM_NOTE): fine, rhythm is grammar
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, read_json

SAMPLES = 48
REF_FPS = 4.0
FLAT_STD = 10.0
FRAME_SSIM = 0.80
FRAME_HASH = 12
FRAME_SSIM_ALONE = 0.93
COPY_FAIL = 0.25
COPY_WITH_RHYTHM = 0.10
COPY_WARN = 0.05
RHYTHM_HIGH = 0.80
RHYTHM_NOTE = 0.90
MIN_COUNTED = 4
DETAIL_SSIM = 0.65
DETAIL_W = 256


# ------------------------------------------------------------------ fingerprints

def fingerprint_video(video: Path, max_seconds: float = 600.0, fps: float = 2.0, shots: bool = True) -> Dict[str, Any]:
    """{t, frames (N,36,64 uint8), shots (lengths), duration} of any video. References are sampled at 4 per
    second (REF_FPS) and renders at 2, so every render frame has a reference frame within 1/8 s."""
    import numpy as np
    from .. import ff
    from . import reference as R
    pr = ff.probe(video)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % Path(video).name)
    dur = min(float(pr.get("duration") or 0.0), max_seconds)
    W, H = int(pr.get("width") or 16), int(pr.get("height") or 9)
    aw = R.AW if W >= H else int(round(R.AW * W / float(H) / 2) * 2)
    ah = int(round(aw * H / float(W) / 2) * 2) if W >= H else R.AW
    t, frames = [], []
    for tt, rgb in R._decode(Path(video), dur, fps, aw, ah):
        t.append(tt)
        frames.append(R._resize(R._gray(rgb), R.FP_W, R.FP_H).astype(np.uint8))
    lengths: List[float] = []
    if shots:
        changes, _pic = R.scene_changes(Path(video), dur, float(pr.get("fps") or 30.0))
        b = [0.0] + [c["t"] for c in changes] + [dur]
        lengths = [y - x for x, y in zip(b[:-1], b[1:]) if y - x > 0.02]
    return {"t": np.asarray(t, np.float32), "frames": np.stack(frames) if frames else np.zeros((0, R.FP_H, R.FP_W), np.uint8),
            "shots": np.asarray(lengths, np.float32), "duration": float(dur)}


def load_fingerprint(path: Path) -> Dict[str, Any]:
    import numpy as np
    z = np.load(str(path))
    return {"t": z["t"], "frames": z["frames"], "shots": z["shots"], "duration": float(z["duration"])}


def _blocks(frames, b: int = 4):
    """(N, nblocks, b*b) float32 views of (N, 36, 64) frames."""
    import numpy as np
    f = frames.astype(np.float32)
    n, h, w = f.shape
    h2, w2 = h // b * b, w // b * b
    f = f[:, :h2, :w2].reshape(n, h2 // b, b, w2 // b, b).transpose(0, 1, 3, 2, 4).reshape(n, -1, b * b)
    return f


def _dhash(frames):
    """64-bit difference hash per frame: (N, 64) bool."""
    import numpy as np
    from .reference import _resize
    out = []
    for f in frames:
        s = _resize(f.astype(np.float32), 9, 8)
        out.append((s[:, 1:] > s[:, :-1]).ravel())
    return np.asarray(out, bool)


def _prep(frames):
    """Frames for SSIM: 48x27, each normalised to the same mean and contrast (a brightness or contrast grade
    does not hide a copy; the structure decides)."""
    import numpy as np
    from .reference import _resize
    out = []
    for f in frames:
        s = _resize(f.astype(np.float32), 48, 27)
        out.append((s - s.mean()) / (float(s.std()) + 1e-3) * 48.0 + 128.0)
    return np.stack(out) if out else np.zeros((0, 27, 48), np.float32)


def ssim_matrix(a, b):
    """Mean block SSIM of every frame in a (N) against every frame in b (M): (N, M)."""
    import numpy as np
    A, B = _blocks(a), _blocks(b)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = A.mean(axis=2), B.mean(axis=2)                      # (N, K), (M, K)
    va, vb = A.var(axis=2), B.var(axis=2)
    Ac, Bc = A - ma[..., None], B - mb[..., None]
    out = np.zeros((len(A), len(B)), np.float32)
    for i in range(len(A)):
        cov = (Ac[i][None, :, :] * Bc).mean(axis=2)              # (M, K)
        num = (2 * ma[i][None, :] * mb + C1) * (2 * cov + C2)
        den = (ma[i][None, :] ** 2 + mb ** 2 + C1) * (va[i][None, :] + vb + C2)
        out[i] = (num / den).mean(axis=1)
    return out


def rhythm_similarity(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """F1 of scene-change positions (as a share of each video's length) that line up within 2 %; None with
    fewer than 3 changes in either video."""
    na, nb = len(a) - 1, len(b) - 1          # cuts = shots - 1
    if na < 3 or nb < 3:
        return None
    if abs(na - nb) > 0.25 * max(na, nb):
        return 0.0

    def pos(shots: Sequence[float]) -> List[float]:
        tot = float(sum(shots)) or 1.0
        acc, out = 0.0, []
        for s in list(shots)[:-1]:
            acc += float(s)
            out.append(acc / tot)
        return out
    pa, pb = pos(a), pos(b)
    used = set()
    hits = 0
    for x in pa:
        j = min((k for k in range(len(pb)) if k not in used), key=lambda k: abs(pb[k] - x), default=None)
        if j is not None and abs(pb[j] - x) <= 0.02:
            used.add(j)
            hits += 1
    return round(2.0 * hits / (len(pa) + len(pb)), 3)


def grab(video: Path, t: float, w: int, h: int):
    """One grey frame of `video` at `t`, w x h (float32), or None."""
    import subprocess
    import numpy as np
    from .. import ff
    try:
        cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", "%.3f" % max(0.0, t),
                             "-i", str(video), "-frames:v", "1", "-vf", "scale=%d:%d:flags=area,format=gray" % (w, h),
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    except Exception:  # noqa: BLE001
        return None
    if len(cp.stdout) < w * h:
        return None
    return np.frombuffer(cp.stdout[:w * h], np.uint8).reshape(h, w).astype(np.float32)


def _textured_ssim(a, b, bs: int = 8) -> float:
    """Block SSIM over the blocks that have texture in either frame (1.0 when neither has any)."""
    import numpy as np
    h, w = a.shape
    A = a[:h // bs * bs, :w // bs * bs].reshape(h // bs, bs, w // bs, bs).transpose(0, 2, 1, 3).reshape(-1, bs * bs)
    B = b[:h // bs * bs, :w // bs * bs].reshape(h // bs, bs, w // bs, bs).transpose(0, 2, 1, 3).reshape(-1, bs * bs)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb, va, vb = A.mean(1), B.mean(1), A.var(1), B.var(1)
    cov = ((A - ma[:, None]) * (B - mb[:, None])).mean(1)
    m = (va > 100) | (vb > 100)
    if not m.any():
        return 1.0
    s = ((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma ** 2 + mb ** 2 + C1) * (va + vb + C2))
    return float(s[m].mean())


def detail_similarity(a, b) -> float:
    """The best textured-block SSIM of two grey frames over small zooms (0.94-1.06) and shifts (+-4 px)."""
    import numpy as np
    norm = lambda f: (f - f.mean()) / (float(f.std()) + 1e-3) * 48.0 + 128.0  # noqa: E731
    h, w = a.shape
    nb = norm(b)
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    best = -1.0
    for sc in (1.0, 0.97, 1.03, 0.94, 1.06):
        for dy in (0, -2, 2, -4, 4):
            for dx in (0, -2, 2, -4, 4):
                sy = np.clip(np.rint(cy + (yy - cy) / sc + dy), 0, h - 1).astype(int)
                sx = np.clip(np.rint(cx + (xx - cx) / sc + dx), 0, w - 1).astype(int)
                best = max(best, _textured_ssim(norm(a[sy, sx]), nb))
                if best >= 0.95:
                    return best
    return best


def _confirm(copies: List[Dict[str, Any]], render_video: Path, ref_video: Path, aspect: float) -> List[Dict[str, Any]]:
    """Keep the coarse near copies whose detail matches too (see the module doc)."""
    w = DETAIL_W if aspect >= 1 else int(round(DETAIL_W * aspect / 2) * 2)
    h = int(round(w / aspect / 2) * 2) if aspect >= 1 else DETAIL_W
    kept = []
    for c in copies:
        a, b = grab(render_video, c["t"], w, h), grab(ref_video, c["ref_t"], w, h)
        if a is None or b is None:
            kept.append(c)
            continue
        c["detail"] = round(detail_similarity(a, b), 3)
        if c["detail"] >= DETAIL_SSIM:
            kept.append(c)
    return kept


def compare(render_fp: Dict[str, Any], ref_fp: Dict[str, Any], render_video: Optional[Path] = None,
            ref_video: Optional[Path] = None) -> Dict[str, Any]:
    import numpy as np
    rf, xf = render_fp["frames"], ref_fp["frames"]
    res: Dict[str, Any] = {"thresholds": {"frame_ssim": FRAME_SSIM, "frame_hash_bits": FRAME_HASH,
                                          "frame_ssim_alone": FRAME_SSIM_ALONE, "copy_fail": COPY_FAIL,
                                          "copy_with_rhythm": COPY_WITH_RHYTHM, "rhythm_high": RHYTHM_HIGH,
                                          "copy_warn": COPY_WARN}}
    if len(rf) == 0 or len(xf) == 0:
        res.update(counted=0, copies=0, copy_share=0.0, rhythm=None, verdict="inconclusive")
        return res
    idx = np.unique(np.linspace(0, len(rf) - 1, min(SAMPLES, len(rf))).round().astype(int))
    sample = rf[idx]
    detailed = np.array([float(f.std()) >= FLAT_STD for f in sample])
    ref_detailed = np.array([float(f.std()) >= FLAT_STD for f in xf])
    counted = int(detailed.sum())
    copies: List[Dict[str, Any]] = []
    if counted and ref_detailed.any():
        S = ssim_matrix(_prep(sample[detailed]), _prep(xf[ref_detailed]))
        ha, hb = _dhash(sample[detailed]), _dhash(xf[ref_detailed])
        rt = np.asarray(render_fp["t"])[idx][detailed]
        xt = np.asarray(ref_fp["t"])[ref_detailed]
        for i in range(len(S)):
            j = int(np.argmax(S[i]))
            ham = int((ha[i] != hb[j]).sum())
            s = float(S[i, j])
            if (s >= FRAME_SSIM and ham <= FRAME_HASH) or s >= FRAME_SSIM_ALONE:
                copies.append({"t": round(float(rt[i]), 2), "ref_t": round(float(xt[j]), 2), "ssim": round(s, 3),
                               "hash_bits": ham})
        res["best_ssim_median"] = round(float(np.median(S.max(axis=1))), 3)
    if copies and render_video and ref_video and Path(render_video).is_file() and Path(ref_video).is_file():
        from .. import ff
        coarse = len(copies)
        pr = ff.probe(Path(render_video))
        aspect = float(pr.get("width") or 16) / float(pr.get("height") or 9)
        copies = _confirm(copies, Path(render_video), Path(ref_video), aspect)
        res["detail"] = {"checked": coarse, "kept": len(copies), "threshold": DETAIL_SSIM}
    share = len(copies) / float(counted) if counted else 0.0
    rh = rhythm_similarity(list(render_fp["shots"]), list(ref_fp["shots"]))
    res.update(counted=counted, copies=len(copies), copy_share=round(share, 3), rhythm=rh, matches=copies[:20])
    if counted < MIN_COUNTED:
        res["verdict"] = "inconclusive"
    elif share >= COPY_FAIL or (share >= COPY_WITH_RHYTHM and (rh or 0) >= RHYTHM_HIGH):
        res["verdict"] = "copy"
    elif share >= COPY_WARN:
        res["verdict"] = "close"
    else:
        res["verdict"] = "ok"
    res["rhythm_note"] = rh is not None and rh >= RHYTHM_NOTE
    return res


# ------------------------------------------------------------------ job integration

def job_references(job: Path) -> List[Dict[str, Any]]:
    """[{dir, title, credit, fingerprint, source}] for every reference analysed into the job."""
    out = []
    root = Path(job) / "references"
    if not root.is_dir():
        return out
    for rj in sorted(root.glob("*/reference.json")):
        r = read_json(rj, None)
        if not isinstance(r, dict):
            continue
        video = next((v for v in (r.get("kept_copy"), r.get("file")) if v and Path(v).is_file()), None)
        out.append({"dir": str(rj.parent), "title": r.get("title"), "credit": r.get("credit"),
                    "fingerprint": str(rj.parent / "fingerprint.npz") if (rj.parent / "fingerprint.npz").is_file() else None,
                    "source": r.get("source"), "video": video})
    return out


def check_video(video: Path, refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compare one video with each reference that has a fingerprint."""
    fp = None
    out = []
    for r in refs:
        if not r.get("fingerprint"):
            continue
        if fp is None:
            fp = fingerprint_video(video)
        res = compare(fp, load_fingerprint(Path(r["fingerprint"])), render_video=Path(video),
                      ref_video=Path(r["video"]) if r.get("video") else None)
        res["reference"] = r.get("title")
        res["reference_dir"] = r.get("dir")
        out.append(res)
    return out


def message(res: Dict[str, Any]) -> Tuple[str, str, str]:
    """(severity, rule, text) for one comparison, in qa's terms."""
    name = res.get("reference") or "the reference"
    rh = res.get("rhythm")
    rtxt = "rhythm similarity %.2f" % rh if rh is not None else "too few scene changes to compare the rhythm"
    ts = ", ".join("%.1fs" % m["t"] for m in (res.get("matches") or [])[:6])
    if res["verdict"] == "copy":
        return ("FAIL", "reference_copy",
                "the render copies the style reference \"%s\": %d of %d sampled frames (%d%%) match its frames "
                "(at %s), %s; the limit is %d%% of frames, or %d%% with a rhythm similarity of %.1f or more" % (
                    name, res["copies"], res["counted"], round(100 * res["copy_share"]), ts, rtxt,
                    round(100 * COPY_FAIL), round(100 * COPY_WITH_RHYTHM), RHYTHM_HIGH))
    if res["verdict"] == "close":
        return ("WARN", "reference_close",
                "%d of %d sampled frames (%d%%) look like frames of the style reference \"%s\" (at %s); %s" % (
                    res["copies"], res["counted"], round(100 * res["copy_share"]), name, ts, rtxt))
    if res["verdict"] == "inconclusive":
        return ("INFO", "reference_copy", "near-copy guard against \"%s\": too few detailed frames to compare" % name)
    note = "; the rhythm follows it closely (%.2f), which is fine: rhythm is grammar" % rh if res.get("rhythm_note") else ""
    return ("PASS", "reference_copy", "not a copy of the style reference \"%s\" (%d%% of %d sampled frames similar, %s)%s" % (
        name, round(100 * res["copy_share"]), res["counted"], rtxt, note))


FIX = ("rebuild the matching shots from your own material: a reference lends pace, shot lengths, type scale and "
       "transitions, never its pictures (references/reference.md)")


def credit_present(job: Path, video: Optional[Path], line: str) -> bool:
    key = line.lower()
    files = [job / "credits.txt", job / "share.txt"]
    if video is not None:
        files += [video.parent / "credits.txt", video.parent / (video.stem + ".credits.txt"), video.parent / "share.txt"]
    seen_c = seen_s = False
    for f in files:
        if f.is_file():
            txt = f.read_text(encoding="utf-8", errors="replace").lower()
            if key in txt:
                if f.name == "share.txt":
                    seen_s = True
                else:
                    seen_c = True
    return seen_c and seen_s


def qa_check(F: Any, vpath: Path, say: Any = None) -> Optional[List[Dict[str, Any]]]:
    """`showtime qa` hook: near-copy guard + credit line for the job's references (no-op without any)."""
    from ..job import ledger
    job = ledger.enclosing_job(vpath)
    if job is None:
        return None
    refs = job_references(job)
    if not refs:
        return None
    if say:
        say("qa: comparing with %d style reference(s)" % len(refs))
    results = check_video(vpath, refs)
    for res in results:
        sev, rule, text = message(res)
        if sev == "PASS":
            F.ok(text)
        elif sev == "INFO":
            F.add(rule, "INFO", text)
        else:
            m = (res.get("matches") or [{}])[0]
            F.add(rule, sev, text, t=m.get("t"), fix=FIX)
    for r in refs:
        line = r.get("credit")
        if line and not credit_present(job, vpath, line):
            F.add("reference_credit", "WARN", "the style reference credit \"%s\" is missing from credits.txt or share.txt" % line,
                  fix="showtime reference credit %s" % job.name)
    return results


# ------------------------------------------------------------------ credit line

def _add_line(path: Path, line: str, header: Optional[str] = None) -> bool:
    txt = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if line.lower() in txt.lower():
        return False
    if path.name == "share.txt":
        new = (txt.rstrip() + "\n\n" if txt.strip() else "") + line + "\n"
    elif not txt.strip():
        new = "Credits\n\nOther material:\n\n- %s\n" % line
    elif re.search(r"(?m)^Other material:\s*$", txt):
        new = re.sub(r"(?m)^(Other material:\s*\n\n?)", lambda m: m.group(1) + "- %s\n" % line, txt, count=1)
    else:
        new = txt.rstrip() + "\n\nOther material:\n\n- %s\n" % line
    path.write_text(new, encoding="utf-8", newline="\n")
    return True


def ensure_credit(job: Path, line: str) -> Dict[str, Any]:
    """Put `line` in the job's credits.txt and share.txt (idempotent). share.txt keeps it outside the
    auto-generated credits block, so a render never removes it; render adds it to credits.txt itself."""
    job = Path(job)
    changed = []
    for name in ("credits.txt", "share.txt"):
        p = job / name
        if _add_line(p, line):
            changed.append(str(p))
    return {"line": line, "changed": changed}
