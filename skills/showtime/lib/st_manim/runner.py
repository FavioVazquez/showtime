"""Render (or dry-run) scenes of one file inside the manim venv. Called by `showtime manim render|check`:

    python -m st_manim.runner <spec.json>

spec: {"file": ..., "scenes": ["A", "B"], "width": W, "height": H, "fps": F, "transparent": false,
       "format": "mp4" | "webm" | "mov", "dry_run": false, "media_dir": ..., "tex_dir": ..., "result": ...}
The kit's own settings (theme, cues, per-scene log/poster paths) come from $SHOWTIME_MANIM.

Writes `result` as JSON: {"scenes": [{"name", "ok", "movie", "last_frame", "error", "where", "seconds"}]}.
One failing scene does not stop the others in a dry run; a render stops at the first failure.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path


def _where(exc: BaseException, scene_file: Path) -> str:
    """The last traceback line inside the scene file (what the user should look at)."""
    best = ""
    for fr in traceback.extract_tb(exc.__traceback__):
        if Path(fr.filename).resolve() == scene_file:
            best = "%s line %d: %s" % (scene_file.name, fr.lineno, (fr.line or "").strip())
    return best


def main(argv: list) -> int:
    spec = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    scene_file = Path(spec["file"]).resolve()
    from manim import config

    config.pixel_width = int(spec["width"])
    config.pixel_height = int(spec["height"])
    config.frame_rate = float(spec["fps"])
    config.media_dir = str(spec["media_dir"])
    if spec.get("tex_dir"):
        config.tex_dir = str(spec["tex_dir"])
    config.input_file = str(scene_file)
    config.progress_bar = "none"
    config.verbosity = "WARNING"
    config.preview = False
    config.disable_caching = bool(spec.get("fresh"))
    config.transparent = bool(spec.get("transparent"))
    config.format = spec.get("format") or "mp4"
    config.dry_run = bool(spec.get("dry_run"))
    config.write_to_movie = not config.dry_run
    config.save_last_frame = False
    if spec.get("seed") is not None:
        config.seed = int(spec["seed"])

    import st_manim  # noqa: F401  (frame units, background, fonts)
    st_manim.apply_frame()
    if not config.transparent:
        config.background_color = st_manim.T.bg

    results = []
    out = {"scenes": results, "manim": None}
    try:
        import manim
        out["manim"] = manim.__version__
    except Exception:  # noqa: BLE001
        pass
    sys.path.insert(0, str(scene_file.parent))
    try:
        mspec = importlib.util.spec_from_file_location(scene_file.stem, str(scene_file))
        mod = importlib.util.module_from_spec(mspec)  # type: ignore[arg-type]
        sys.modules[scene_file.stem] = mod
        mspec.loader.exec_module(mod)  # type: ignore[union-attr]
    except BaseException as e:  # noqa: BLE001
        out["import_error"] = "%s: %s" % (type(e).__name__, e)
        out["where"] = _where(e, scene_file)
        out["traceback"] = traceback.format_exc()[-4000:]
        Path(spec["result"]).write_text(json.dumps(out, indent=1), encoding="utf-8")
        return 2
    rc = 0
    for name in spec["scenes"]:
        t0 = time.time()
        rec = {"name": name, "ok": False}
        results.append(rec)
        try:
            cls = getattr(mod, name)
            config.output_file = name          # manim keeps the first scene's name otherwise
            scene = cls()
            scene.render()
            rec["ok"] = True
            if not config.dry_run:
                rec["movie"] = str(scene.renderer.file_writer.movie_file_path)
                lf = spec.get("last_frames", {}).get(name)
                if lf:
                    from PIL import Image
                    arr = scene.renderer.get_frame()
                    im = Image.fromarray(arr)
                    (im.convert("RGBA") if config.transparent else im.convert("RGB")).save(lf)
                    rec["last_frame"] = lf
        except BaseException as e:  # noqa: BLE001 - report every failure as data
            rec["error"] = "%s: %s" % (type(e).__name__, e)
            rec["kind"] = type(e).__name__
            rec["where"] = _where(e, scene_file)
            rec["traceback"] = traceback.format_exc()[-4000:]
            rc = 1
            if not config.dry_run:
                break
        finally:
            rec["seconds"] = round(time.time() - t0, 2)
    Path(spec["result"]).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
