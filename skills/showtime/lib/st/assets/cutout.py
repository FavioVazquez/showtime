"""Foreground cutout (background removal) for stills.

    showtime assets cutout product.jpg                   # -> product.cutout.png (RGBA)
    showtime assets cutout photo.jpg --mask mask.png --crop
    showtime assets cutout art.jpg --engine rembg --model birefnet-general-lite

Engines (auto = first that works):
    vision   macOS 14+ Vision "foreground instance mask" through PyObjC. No download, ~0.2 s.
    rembg    ONNX models on CPU (Windows, Linux, older macOS, or when Vision finds no subject).
             Installed on first use into the showtime venv (a one-line notice is printed);
             models are downloaded once to ~/.showtime/models/rembg.
             Models: isnet-general-use (default, 170 MB), u2netp (5 MB, rough),
             u2net (170 MB), birefnet-general-lite (220 MB, most robust, slow).

Vision returns nothing for pictures without a clear subject (e.g. a landscape);
that is reported as "no subject found" rather than an empty cutout.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..common import ShowtimeError, debug, log, paths, skill_dir
from ..platform import IS_MAC

REMBG_SPEC = "rembg==2.0.85"
REMBG_MODELS = ["isnet-general-use", "u2netp", "u2net", "silueta", "birefnet-general-lite", "birefnet-general"]


class NoSubject(ShowtimeError):
    pass


def _mac_version() -> tuple:
    import platform as _p
    try:
        return tuple(int(x) for x in _p.mac_ver()[0].split(".")[:2])
    except ValueError:
        return (0, 0)


def vision_available() -> bool:
    if not IS_MAC or _mac_version() < (14, 0):
        return False
    try:
        import Vision  # noqa: F401  # type: ignore
        import Quartz  # noqa: F401  # type: ignore
        return True
    except Exception:  # noqa: BLE001
        return False


def rembg_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("rembg") is not None
    except Exception:  # noqa: BLE001
        return False


def _vision_cut(src: Path, dst: Path) -> Dict[str, Any]:
    import Quartz  # type: ignore
    import Vision  # type: ignore
    from Foundation import NSURL  # type: ignore

    ci = Quartz.CIImage.imageWithContentsOfURL_(NSURL.fileURLWithPath_(str(src)))
    if ci is None:
        raise ShowtimeError("macOS could not read %s" % src)
    req = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(ci, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise ShowtimeError("Vision failed: %s" % err)
    res = req.results()
    if not res:
        raise NoSubject("no subject found in %s" % src.name)
    obs = res[0]
    buf, err = obs.generateMaskedImageOfInstances_fromRequestHandler_croppedToInstancesExtent_error_(
        obs.allInstances(), handler, False, None)
    if buf is None:
        raise ShowtimeError("Vision could not build the mask: %s" % err)
    out = Quartz.CIImage.imageWithCVPixelBuffer_(buf)
    ctx = Quartz.CIContext.context()
    cs = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB)
    ok = ctx.writePNGRepresentationOfImage_toURL_format_colorSpace_options_error_(
        out, NSURL.fileURLWithPath_(str(dst)), Quartz.kCIFormatRGBA8, cs, {}, None)
    if not ok or not dst.is_file():
        raise ShowtimeError("Vision could not write %s" % dst)
    return {"instances": len(obs.allInstances())}


def install_rembg() -> None:
    """Install rembg into the showtime venv, constrained to the pinned lock file."""
    uv = shutil.which("uv") or shutil.which("uv.exe")
    lock = skill_dir() / "setup" / "requirements.txt"
    if uv:
        args = [uv, "pip", "install", "--python", sys.executable, "--only-binary", ":all:"]
        if lock.is_file():
            args += ["-c", str(lock)]
        args.append(REMBG_SPEC)
    else:
        args = [sys.executable, "-m", "pip", "install", REMBG_SPEC]
        if lock.is_file():
            args += ["-c", str(lock)]
    log("installing the background-removal engine (rembg, ~60 MB, one time)...")
    t0 = time.time()
    cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    if cp.returncode != 0:
        tail = "\n".join((cp.stdout or "").strip().splitlines()[-10:])
        raise ShowtimeError("could not install rembg:\n%s" % tail,
                            hint="install uv (https://docs.astral.sh/uv/) and retry, or run: showtime setup")
    log("rembg installed in %.0fs" % (time.time() - t0))


def _rembg_cut(src: Path, dst: Path, model: str, mask_only: bool = False) -> Dict[str, Any]:
    os.environ.setdefault("U2NET_HOME", str(paths()["models"] / "rembg"))
    Path(os.environ["U2NET_HOME"]).mkdir(parents=True, exist_ok=True)
    if not rembg_available():
        install_rembg()
    import warnings

    from PIL import Image
    warnings.filterwarnings("ignore", category=UserWarning, module=r"numba.*")
    from rembg import new_session, remove  # type: ignore

    if model not in REMBG_MODELS:
        raise ShowtimeError("unknown rembg model %r" % model, hint="models: " + ", ".join(REMBG_MODELS))
    if not list(Path(os.environ["U2NET_HOME"]).rglob(model + ".onnx")):
        log("downloading the %s model (one time)..." % model)
    session = new_session(model)
    with Image.open(src) as im:
        out = remove(im.convert("RGB"), session=session, only_mask=mask_only)
    out.save(dst)
    return {"model": model}


DEFAULT_MAX_SIZE = 2048   # px, the long side: enough for a 1080p/1440p page; 0 keeps the full resolution


def cutout(src: Path, *, out: Optional[Path] = None, engine: str = "auto", model: str = "isnet-general-use",
           mask: Optional[Path] = None, crop: bool = False, pad: int = 0,
           max_size: Optional[int] = DEFAULT_MAX_SIZE) -> Dict[str, Any]:
    src = Path(src)
    if not src.is_file():
        raise ShowtimeError("image not found: %s" % src)
    dst = Path(out) if out else src.with_name(src.stem + ".cutout.png")
    if dst.suffix.lower() != ".png":
        dst = dst.with_suffix(".png")
    dst.parent.mkdir(parents=True, exist_ok=True)
    engines = []
    if engine in ("auto", "vision"):
        if vision_available():
            engines.append("vision")
        elif engine == "vision":
            raise ShowtimeError("the Vision engine needs macOS 14 or newer with PyObjC",
                                hint="use --engine rembg (works on every OS)")
    if engine in ("auto", "rembg"):
        engines.append("rembg")
    if not engines:
        raise ShowtimeError("unknown engine %r" % engine, hint="use auto, vision or rembg")
    t0 = time.time()
    used = None
    detail: Dict[str, Any] = {}
    errors = []
    for e in engines:
        try:
            if e == "vision":
                detail = _vision_cut(src, dst)
            else:
                detail = _rembg_cut(src, dst, model)
            used = e
            break
        except NoSubject as ex:
            errors.append("%s: %s" % (e, ex))
            if engine == "vision":
                raise
            debug("vision found no subject; trying rembg")
        except ShowtimeError as ex:
            errors.append("%s: %s" % (e, ex))
            if engine != "auto":
                raise
    if not used:
        raise ShowtimeError("background removal failed (%s)" % "; ".join(errors),
                            hint="try --engine rembg --model birefnet-general-lite for difficult images")
    stats = _post(dst, mask, crop, pad, max_size)
    res = {"path": str(dst), "engine": used, "seconds": round(time.time() - t0, 2)}
    res.update(detail)
    res.update(stats)
    return res


def _post(dst: Path, mask: Optional[Path], crop: bool, pad: int, max_size: Optional[int] = None) -> Dict[str, Any]:
    """Coverage stats, crop-to-subject, a size cap on the long side (premultiplied resize: no dark
    fringes), and the optional mask at the output's size."""
    from PIL import Image

    with Image.open(dst) as im:
        im = im.convert("RGBA")
        alpha = im.getchannel("A")
        hist = alpha.histogram()
        total = im.width * im.height
        covered = sum(hist[128:]) / float(total or 1)
        bbox = alpha.point(lambda v: 255 if v > 16 else 0).getbbox()
        changed = False
        if crop and bbox:
            x0, y0, x1, y1 = bbox
            x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
            x1, y1 = min(im.width, x1 + pad), min(im.height, y1 + pad)
            im = im.crop((x0, y0, x1, y1))
            changed = True
        full = im.size
        if max_size and max(im.size) > int(max_size):
            k = int(max_size) / float(max(im.size))
            im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
            changed = True
        if changed:
            im.save(dst, optimize=True)
        if mask:
            Path(mask).parent.mkdir(parents=True, exist_ok=True)
            im.getchannel("A").save(mask)
        size = im.size
    if covered < 0.005:
        raise NoSubject("the cutout is empty (no subject detected)")
    return {"coverage": round(covered, 4), "bbox": list(bbox) if bbox else None, "width": size[0], "height": size[1],
            "mask": str(mask) if mask else None, "resized_from": list(full) if tuple(full) != tuple(size) else None,
            "bytes": dst.stat().st_size}
