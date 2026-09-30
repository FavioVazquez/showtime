"""`showtime manim render`: scenes -> one video, cached per scene, on the voice's clock.

Pipeline
  1. project, size (quality x aspect), cues (voice timeline or estimate), theme (fonts as files)
  2. per-scene cache key; scenes whose key is cached are reused (build/cache/)
  3. the rest render in ONE manim subprocess (`python -m st_manim.runner`), encoded by PyAV
  4. concat through showtime's ffmpeg (never a bare ffmpeg); alpha: VP9 webm or ProRes 4444
  5. audio: vo.wav when the scenes sit on the voice's clock, else each line placed at its measured
     start through `showtime audio mix` (also used when a mix spec with music/effects is given)
  6. draft: contact sheet of every scene's last frame; final: poster.jpg (mark("poster") or last frame)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import ff
from .. import platform as plat
from ..common import ShowtimeError, extra_installed, home, log, paths, require_extra, slugify, warn
from . import cues as cues_mod
from . import palette, tex
from .project import Project, frame_units, kit_hash, size_for

LIB = Path(__file__).resolve().parents[2]            # SKILL/lib
GL_VENV = "venv-manimgl"


# ------------------------------------------------------------------ environment

def manim_installed(vpy: Optional[Path] = None) -> bool:
    venv = paths()["venv"]
    for sp in list(venv.glob("lib/python3*/site-packages")) + [venv / "Lib" / "site-packages"]:
        if (sp / "manim" / "__init__.py").is_file():
            return True
    return False


def ensure_manim(feature: str) -> Path:
    vpy = paths()["venv_python"]
    if not vpy.exists():
        raise ShowtimeError("the showtime Python environment is missing", hint="run `showtime setup`")
    ok = manim_installed()
    require_extra("manim", feature, available=ok)
    return vpy


def gl_python() -> Optional[Path]:
    vpy = plat.venv_python(home() / GL_VENV)
    return vpy if vpy.exists() else None


def kit_env(settings_file: Path, tex_info: Dict[str, Any]) -> Dict[str, str]:
    env = dict(os.environ)
    pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(LIB) + ((os.pathsep + pp) if pp else "")
    env["SHOWTIME_MANIM"] = str(settings_file)
    extra = [str(home() / "bin")]
    if tex_info.get("bin_dir"):
        extra.insert(0, str(tex_info["bin_dir"]))
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def tex_cache_dir() -> Path:
    d = home() / "cache" / "manim" / "tex"
    d.mkdir(parents=True, exist_ok=True)
    return d


def latex_error(missing: Optional[List[str]] = None) -> ShowtimeError:
    return ShowtimeError("this scene uses equations (LaTeX), but no LaTeX was found" if not missing else
                         "LaTeX is missing packages Manim needs: " + ", ".join(missing),
                         why="MathTex, eq(), matrices and numbered axes compile through latex + dvisvgm "
                             "(Text, shapes and graphs do not need it)",
                         hint="\n       ".join(tex.fix_lines(missing=missing)))


# ------------------------------------------------------------------ one kit run

def run_kit(project: Project, scenes: List[str], *, width: int, height: int, fps: float,
            settings: Dict[str, Any], dry_run: bool = False, transparent: bool = False, fmt: str = "mp4",
            fresh: bool = False, last_frames: Optional[Dict[str, str]] = None, label: str = "render",
            timeout: float = 7200) -> Dict[str, Any]:
    """Run st_manim.runner once for `scenes`. Returns its result JSON (+ 'log' path)."""
    vpy = ensure_manim("showtime manim %s" % label)
    bdir = project.build_dir()
    rdir = bdir / "run"
    rdir.mkdir(parents=True, exist_ok=True)
    (bdir / "logs").mkdir(parents=True, exist_ok=True)
    stamp = "%s-%d" % (label, int(time.time() * 1000))
    sfile = rdir / (stamp + ".settings.json")
    sfile.write_text(json.dumps(settings, indent=1, default=str), encoding="utf-8")
    result = rdir / (stamp + ".result.json")
    spec = {"file": str(project.file), "scenes": scenes, "width": width, "height": height, "fps": fps,
            "transparent": transparent, "format": fmt, "dry_run": dry_run, "fresh": fresh,
            "media_dir": str(bdir / "media"), "tex_dir": str(tex_cache_dir()), "result": str(result),
            "last_frames": last_frames or {}}
    specf = rdir / (stamp + ".spec.json")
    specf.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    tinfo = tex.find()
    logf = bdir / "logs" / ("%s.log" % label)
    env = kit_env(sfile, tinfo)
    with open(logf, "w", encoding="utf-8", errors="replace") as lf:
        try:
            cp = subprocess.run([str(vpy), "-m", "st_manim.runner", str(specf)], cwd=str(project.dir), env=env,
                                stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
            rc = cp.returncode
        except subprocess.TimeoutExpired:
            raise ShowtimeError("manim did not finish within %d s" % timeout, hint="see %s" % logf)
    try:
        res = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tail = "\n".join(logf.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:])
        raise ShowtimeError("manim exited with code %d before writing a result" % rc,
                            why=tail or "no output", hint="read the full log: %s" % logf)
    res["log"] = str(logf)
    res["returncode"] = rc
    return res


def explain_failure(project: Project, rec: Dict[str, Any], logf: str) -> ShowtimeError:
    err = rec.get("error") or rec.get("import_error") or "unknown error"
    where = rec.get("where") or ""
    tb = rec.get("traceback") or ""
    if "latex" in (err + tb).lower() and ("not found" in (err + tb).lower() or "FileNotFoundError" in err
                                          or "error converting" in (err + tb).lower()):
        missing = tex.missing_packages()
        e = latex_error(missing if missing else None)
        e.why = "%s%s (%s)" % (err[:300], (" at " + where) if where else "", e.why)
        return e
    if rec.get("kind") == "CueError":
        return ShowtimeError("%s: %s" % (rec.get("name", "scene"), err.split(": ", 1)[-1]),
                             why=where or "a cue names a word the narration does not say",
                             hint="list the words with `showtime manim cues %s`, then fix the cue" % project.dir)
    name = rec.get("name")
    return ShowtimeError("%s failed: %s" % (("scene " + name) if name else "the scene file", err[:500]),
                         why=where or "see the log", hint="fix it and render again; full log: %s" % logf)


# ------------------------------------------------------------------ settings shared by render and check

def kit_settings(project: Project, cues: Optional[Dict[str, Any]], theme: Dict[str, Any],
                 scene_paths: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    return {"theme": theme, "colors": project.colors, "cues": cues, "scenes": scene_paths,
            "aspect": project.aspect}


def resolve_theme(project: Project, brand: Optional[str], install_fonts: bool = True) -> Dict[str, Any]:
    brand_file = Path(brand) if brand else (project.dir / project.cfg["brand"] if project.cfg.get("brand") else None)
    if brand_file is not None and not brand_file.exists():
        raise ShowtimeError("brand file not found: %s" % brand_file, hint="pass --brand path/to/brand.json")
    return palette.resolve(project.dir, brand_file=brand_file, light=bool(project.cfg.get("light")),
                           install_fonts=install_fonts)


def manim_version() -> str:
    venv = paths()["venv"]
    for sp in list(venv.glob("lib/python3*/site-packages")) + [venv / "Lib" / "site-packages"]:
        for d in sp.glob("manim-*.dist-info"):
            return d.name[len("manim-"):-len(".dist-info")]
    return "?"


# ------------------------------------------------------------------ render

def _unique(p: Path) -> Path:
    if not p.exists():
        return p
    k = 2
    while True:
        c = p.with_name("%s-%d%s" % (p.stem, k, p.suffix))
        if not c.exists():
            return c
        k += 1


def render(target: Path, *, scenes: Optional[List[str]] = None, quality: str = "draft", aspect: Optional[str] = None,
           alpha: Optional[str] = None, fps: Optional[float] = None, cues_arg: Optional[str] = None,
           out: Optional[str] = None, brand: Optional[str] = None, fresh: bool = False, no_audio: bool = False,
           mix: Optional[str] = None, engine: Optional[str] = None, sheet: Optional[bool] = None,
           size: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    t_start = time.time()
    project = Project(target)
    if mix:
        # --mix is a path like any other on the command line: from the current folder first
        # (`showtime manim render manim --mix manim/audio/mix.json` from the job folder), else the project's
        mp = Path(mix).expanduser()
        if not mp.is_absolute() and mp.is_file():
            mix = str(mp.resolve())
    eng = engine or project.engine
    if eng == "gl":
        return render_gl(project, scenes=scenes, quality=quality, aspect=aspect, alpha=alpha, fps=fps, out=out,
                         brand=brand)
    aspect = aspect or project.aspect
    width, height = size if size else size_for(aspect, quality)
    if width % 2 or height % 2 or width < 16 or height < 16:
        raise ShowtimeError("--size %dx%d: use even numbers of at least 16" % (width, height))
    fps = float(fps or (project.cfg.get("fps", 30) if quality == "final" else 15))
    names = project.scenes(scenes)
    for w in project.warnings:
        warn(w)
    if tex.uses_tex(project.source):
        ti = tex.find()
        if not ti["ok"]:
            raise latex_error()
    cues = cues_mod.load(cues_arg, project.dir, project.cfg.get("voice", "voice/timeline.json"),
                         project.cfg.get("narration", "narration.md"), fps)
    if cues and cues.get("estimated"):
        warn("timing is estimated from %s (about %.1f words/s); for the real voice run: showtime voice script "
             "%s -o %s" % (Path(cues["source"]).name, cues_mod.EST_WPS, Path(cues["source"]).name,
                           project.cfg.get("voice", "voice/timeline.json").rsplit("/", 1)[0]))
    theme = resolve_theme(project, brand)
    for n in theme.get("notes") or []:
        warn("theme: " + n)
    transparent = alpha is not None
    fmt = "webm" if alpha == "webm" else ("mov" if alpha == "prores" else "mp4")
    ext = ".webm" if alpha == "webm" else (".mov" if alpha == "prores" else ".mp4")
    bdir = project.build_dir()
    cache = bdir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    khash = kit_hash(LIB, manim_version())
    pix = {"w": width, "h": height, "fps": fps, "fmt": fmt, "transparent": transparent, "aspect": aspect}
    keyed: Dict[str, str] = {}
    for n in names:
        keyed[n] = project.cache_key(n, dict(pix, theme=theme, colors=project.colors), cues, khash)[:16]

    def cpath(n: str, suffix: str) -> Path:
        return cache / ("%s-%s%s" % (n, keyed[n], suffix))

    todo = [n for n in names if fresh or not (cpath(n, ext).is_file() and cpath(n, ".log.json").is_file())]
    scene_paths = {n: {"log": str(cpath(n, ".log.json.tmp")), "poster": str(cpath(n, ".poster.png"))} for n in names}
    settings = kit_settings(project, cues, theme, scene_paths)
    rendered: Dict[str, float] = {}
    if todo:
        est = len(todo)
        log("rendering %d scene%s at %dx%d %gfps (%s)%s" % (est, "" if est == 1 else "s", width, height, fps, quality,
                                                          ", %d cached" % (len(names) - est) if len(names) > est else ""))
        res = run_kit(project, todo, width=width, height=height, fps=fps, settings=settings, transparent=transparent,
                      fmt=fmt, fresh=fresh, last_frames={n: str(cpath(n, ".last.png")) for n in todo})
        if res.get("import_error"):
            raise explain_failure(project, {"error": res["import_error"], "where": res.get("where"),
                                            "traceback": res.get("traceback")}, res["log"])
        for rec in res.get("scenes", []):
            if not rec.get("ok"):
                raise explain_failure(project, rec, res["log"])
            n = rec["name"]
            shutil.copyfile(rec["movie"], str(cpath(n, ext)))
            tmp_log = Path(scene_paths[n]["log"])
            if tmp_log.is_file():
                os.replace(str(tmp_log), str(cpath(n, ".log.json")))
            rendered[n] = rec.get("seconds", 0)
        _prune(cache, names)
    logs = {n: json.loads(cpath(n, ".log.json").read_text(encoding="utf-8")) for n in names}

    # ---- output path
    slug = slugify(project.title)
    if out:
        dest = Path(out).expanduser()
        if dest.suffix.lower() != ext:
            dest = dest.with_suffix(ext)
    else:
        dest = project.dir / "out" / ("%s%s%s" % (slug, "-draft" if quality == "draft" else "", ext))
    asked_stem = dest.stem
    dest = _unique(dest.resolve())
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = bdir / "assemble"
    work.mkdir(parents=True, exist_ok=True)

    # ---- video: concat scenes (stream copy; every scene shares codec, size and rate)
    clips = [cpath(n, ext) for n in names]
    joined = work / ("joined" + ext)
    if len(clips) == 1:
        shutil.copyfile(str(clips[0]), str(joined))
    else:
        lst = work / "concat.txt"
        lst.write_text("".join("file '%s'\n" % plat.concat_list_path(c) for c in clips), encoding="utf-8")
        ff.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    total_frames = sum(int(logs[n]["frames"]) for n in names)
    duration = total_frames / fps

    audio_note = None
    audio_file = None
    if alpha == "prores":
        # RGBA -> YUV with the BT.709 matrix the tags declare (swscale's default is BT.601)
        ff.run_ffmpeg(["-i", str(joined), "-vf", ff.BT709_VF + ",format=yuva444p10le", "-c:v", "prores_ks",
                       "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0"] + ff.BT709_TAGS
                      + [str(dest)], timeout=3600)
    elif alpha == "webm":
        shutil.copyfile(str(joined), str(dest))
    if not transparent:
        audio_file, audio_note = _audio(project, names, logs, cues, fps, mix or project.cfg.get("mix"), work,
                                        duration, no_audio)
        # one encode: Manim's frames were converted to YUV with the BT.601 matrix and left untagged; the
        # delivery is BT.709, tagged, H.264 High (showtime's final/preview presets)
        pr = ff.preset("final" if quality == "final" else "preview")
        vf = ("scale=in_color_matrix=bt601:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
              "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
        if audio_file:
            ff.run_ffmpeg(["-i", str(joined), "-i", str(audio_file), "-map", "0:v:0", "-map", "1:a:0", "-vf", vf]
                          + pr.output_args(audio=True) + ["-t", "%.4f" % duration, str(dest)], timeout=7200)
        else:
            ff.run_ffmpeg(["-i", str(joined), "-map", "0:v:0", "-vf", vf] + pr.output_args(audio=False)
                          + [str(dest)], timeout=7200)
    elif cues and not cues.get("estimated") and not no_audio:
        audio_note = "alpha output has no audio: put the voice in the page or edit mix (voice/vo.wav)"

    # ---- stills
    frames = [{"path": str(cpath(n, ".last.png")), "label": n, "sub": "%.1fs" % (logs[n]["frames"] / fps)}
              for n in names]
    sheet_path = None
    if sheet if sheet is not None else quality == "draft":
        try:
            from ..qa.images import contact_sheet
            sheet_path = contact_sheet(frames, dest.with_name(dest.stem + "-sheet.jpg"),
                                       title="%s: last frame of each scene (%dx%d)" % (project.title, width, height))
        except Exception as e:  # noqa: BLE001 - a sheet must not fail the render
            warn("contact sheet skipped: %s" % e)
    poster = None
    if quality == "final" and not transparent:
        src = next((cpath(n, ".poster.png") for n in names if cpath(n, ".poster.png").is_file()),
                   cpath(names[-1], ".last.png"))
        if src.is_file():
            # same names as `showtime render`: poster.jpg beside a job's main video (-o <job>/final.mp4, even
            # when it is saved as final-2.mp4 because final.mp4 exists) and beside the default output;
            # <stem>.poster.jpg beside any other name. The poster belongs to the newest render: overwrite it.
            poster = dest.parent / "poster.jpg" if (not out or asked_stem == "final") \
                else dest.with_name(dest.stem + ".poster.jpg")
            try:
                from PIL import Image
                Image.open(str(src)).convert("RGB").save(str(poster), "JPEG", quality=90)
            except Exception as e:  # noqa: BLE001
                warn("poster skipped: %s" % e)
                poster = None
    late = [dict(scene=n, **e) for n in names for e in logs[n]["events"] if e["kind"] == "late"]
    return {
        "ok": True, "output": str(dest), "engine": "manim-ce %s" % manim_version(), "quality": quality,
        "size": [width, height], "fps": fps, "aspect": aspect, "frame_units": list(frame_units(width, height)),
        "duration": round(duration, 3), "frames": total_frames, "alpha": alpha,
        "scenes": [{"name": n, "frames": logs[n]["frames"], "cached": n not in rendered,
                    "seconds": rendered.get(n)} for n in names],
        "cues": None if not cues else {"source": cues["source"], "estimated": bool(cues.get("estimated"))},
        "audio": str(audio_file) if audio_file else None, "audio_note": audio_note,
        "sheet": str(sheet_path) if sheet_path else None, "poster": str(poster) if poster else None,
        "late_cues": late, "theme": theme.get("source"), "seconds": round(time.time() - t_start, 1),
    }


def _prune(cache: Path, names: List[str], keep: int = 3) -> None:
    """Keep the newest `keep` cached versions per scene."""
    for n in names:
        vids = sorted((p for p in cache.glob("%s-*.log.json" % n)), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in vids[keep:]:
            key = old.name[len(n) + 1:].split(".", 1)[0]
            for p in cache.glob("%s-%s.*" % (n, key)):
                try:
                    p.unlink()
                except OSError:
                    pass


def _scene_starts(names: List[str], logs: Dict[str, Dict[str, Any]]) -> List[int]:
    out, acc = [], 0
    for n in names:
        out.append(acc)
        acc += int(logs[n]["frames"])
    return out


def _audio(project: Project, names: List[str], logs: Dict[str, Dict[str, Any]], cues: Optional[Dict[str, Any]],
           fps: float, mix: Optional[str], work: Path, duration: float,
           no_audio: bool) -> Tuple[Optional[Path], Optional[str]]:
    """The soundtrack: vo.wav as-is when every scene sits on the voice's clock, otherwise each line placed at
    its measured position; a mix spec (music, effects) goes through `showtime audio mix` with the voice."""
    if no_audio:
        return None, "no audio (--no-audio)"
    voice = cues if cues and not cues.get("estimated") else None
    if voice is None and not mix:
        return None, ("timing estimated from narration.md: no voice yet" if cues else None)
    starts = _scene_starts(names, logs)
    aligned = all(abs(starts[i] - int(logs[n].get("origin", 0))) <= 1 for i, n in enumerate(names)) \
        if voice else True
    tracks: List[Dict[str, Any]] = []
    if voice:
        if aligned and voice.get("audio") and Path(voice["audio"]).is_file():
            tracks.append({"id": "voice", "kind": "voice", "file": voice["audio"], "start": 0.0, "level": "raw"})
        else:
            spans = [(starts[i], int(logs[n].get("origin", 0)), int(logs[n]["frames"])) for i, n in enumerate(names)]
            for ln in voice["lines"]:
                if not ln.get("file") or not Path(ln["file"]).is_file():
                    continue
                vf = int(round(ln["start"] * fps))
                seg = next((s for s in spans if s[1] <= vf < s[1] + s[2]), spans[-1])
                at = (seg[0] + (vf - seg[1])) / fps
                tracks.append({"id": "vo-" + ln["id"], "kind": "voice", "file": ln["file"], "start": round(at, 4),
                               "level": "raw"})
            if not aligned:
                warn("the scenes do not sit on the voice's clock (a scene without beats, or pre-beat animation); "
                     "each line is placed at its measured start instead")
        if not mix and aligned and tracks and len(tracks) == 1:
            return Path(tracks[0]["file"]), "voice: %s" % Path(tracks[0]["file"]).name
    spec: Dict[str, Any] = {"duration": round(duration, 3), "tracks": [], "master": {"lufs": -14, "true_peak": -1}}
    base = project.dir
    if mix:
        mp = Path(mix)
        if not mp.is_absolute():
            mp = project.dir / mix
        if not mp.is_file():
            raise ShowtimeError("mix spec not found: %s" % mix,
                                why="looked in the current folder and in the project folder (%s)" % project.dir,
                                hint="pass the path from where you run the command, or relative to the project "
                                     "(--mix audio/mix.json); the format is in references/audio.md")
        user = json.loads(mp.read_text(encoding="utf-8"))
        base = mp.parent
        for t in user.get("tracks", []):
            if t.get("kind") == "voice" and voice:
                continue          # the voice comes from the cues, placed on the measured clock
            spec["tracks"].append(_track_paths(t, [mp.parent, project.dir, Path.cwd()]))
        for k in ("sections", "master"):
            if k in user:
                spec[k] = user[k]
    for t in tracks:
        t = dict(t)
        t.pop("level", None)
        spec["tracks"].append(t)
    if not spec["tracks"]:
        return None, None
    specf = work / "mix.json"
    specf.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    wav = work / "mix.wav"
    launcher = LIB / "st" / "launcher.py"
    cp = subprocess.run([sys.executable, str(launcher), "audio", "mix", str(specf), "-o", str(wav), "--root", str(base)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    if cp.returncode != 0 or not wav.is_file():
        raise ShowtimeError("the audio mix failed", why=(cp.stderr or cp.stdout).strip()[-600:],
                            hint="check %s (showtime audio mix %s)" % (specf, specf))
    return wav, "mixed: %d track(s) via showtime audio mix" % len(spec["tracks"])


def _track_paths(tr: Any, bases: List[Path]) -> Any:
    """A mix track with its relative file paths made absolute: a file is looked up beside the mix spec,
    then in the Manim project folder (where scenes.py lives: "audio/bed.wav" in manim/audio/mix.json),
    then in the current folder. A path found nowhere is left as written for the mix to report."""
    if not isinstance(tr, dict):
        return tr
    out = dict(tr)
    for k in ("file", "keystrokes"):
        v = out.get(k)
        if not isinstance(v, str) or not v or Path(os.path.expanduser(v)).is_absolute():
            continue
        for b in bases:
            c = Path(b) / v
            if c.is_file():
                out[k] = str(c.resolve())
                break
    return out


# ------------------------------------------------------------------ ManimGL (optional engine)

def render_gl(project: Project, *, scenes: Optional[List[str]], quality: str, aspect: Optional[str],
              alpha: Optional[str], fps: Optional[float], out: Optional[str], brand: Optional[str]) -> Dict[str, Any]:
    """Scene files written for ManimGL (`from manimlib import *`) render in their own venv. The st_manim kit,
    cues and checks are Manim Community only."""
    t0 = time.time()
    vpy = gl_python()
    if vpy is None or not extra_installed("manimgl"):
        require_extra("manimgl", "rendering a ManimGL scene (from manimlib import *)", available=vpy is not None)
        vpy = gl_python()
    assert vpy is not None
    aspect = aspect or project.aspect
    width, height = size_for(aspect, quality)
    fps = float(fps or (project.cfg.get("fps", 30) if quality == "final" else 15))
    names = project.scenes(scenes)
    theme = resolve_theme(project, brand, install_fonts=False)
    bdir = project.build_dir() / "gl"
    bdir.mkdir(parents=True, exist_ok=True)
    cfg = bdir / "config.yml"
    ffbin = ff.ffmpeg_path().replace("\\", "/")
    fw, fh = frame_units(width, height)
    # 1.7.2's --fps flag is broken (it passes a string), so the rate goes through a config file
    # frame height in units so the short side is 8 (ManimGL derives the width from the resolution)
    cfg.write_text("camera:\n  fps: %g\n  background_color: \"%s\"\n  resolution: (%d, %d)\n"
                   "sizes:\n  frame_height: %.6f\nfile_writer:\n  ffmpeg_bin: \"%s\"\n"
                   % (fps, theme["bg"], width, height, fh, ffbin), encoding="utf-8")
    clips = []
    tinfo = tex.find()
    env = kit_env(bdir / "none.json", tinfo)
    prefix, no_display = plat.gl_display_prefix(env)  # a Linux server has no display: xvfb-run gives one
    if no_display:
        raise ShowtimeError("ManimGL needs a display", why=no_display, hint=plat.XVFB_FIX)
    for n in names:
        argv = prefix + [str(vpy), "-m", "manimlib", str(project.file), n, "-w", "-r", "%dx%d" % (width, height),
                "--video_dir", str(bdir), "--file_name", n, "--config_file", str(cfg)]
        if alpha:
            argv.append("-t")
        cp = subprocess.run(argv, cwd=str(project.dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding="utf-8", errors="replace")
        logf = project.build_dir() / "logs" / ("gl-%s.log" % n)
        logf.parent.mkdir(parents=True, exist_ok=True)
        logf.write_text(cp.stdout or "", encoding="utf-8")
        found = sorted(bdir.rglob("%s.%s" % (n, "mov" if alpha else "mp4")), key=lambda p: p.stat().st_mtime)
        if cp.returncode != 0 or not found:
            tail = "\n".join((cp.stdout or "").strip().splitlines()[-8:])
            raise ShowtimeError("ManimGL scene %s failed" % n, why=tail or "no output",
                                hint="full log: %s (ManimGL needs OpenGL 3.3)" % logf)
        clips.append(found[-1])
    ext = ".mov" if alpha else ".mp4"
    dest = Path(out).expanduser().with_suffix(ext) if out else \
        project.dir / "out" / ("%s%s-gl%s" % (slugify(project.title), "-draft" if quality == "draft" else "", ext))
    dest = _unique(dest.resolve())
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        shutil.copyfile(str(clips[0]), str(dest))
    else:
        lst = bdir / "concat.txt"
        lst.write_text("".join("file '%s'\n" % plat.concat_list_path(c) for c in clips), encoding="utf-8")
        ff.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dest)])
    try:
        duration = float(ff.probe(dest).get("duration") or 0.0)
    except ShowtimeError:
        duration = 0.0
    return {"ok": True, "output": str(dest), "engine": "manimgl", "quality": quality, "size": [width, height],
            "fps": fps, "aspect": aspect, "duration": round(duration, 3), "scenes": [{"name": n} for n in names],
            "alpha": "prores" if alpha else None,
            "seconds": round(time.time() - t0, 1),
            "note": "ManimGL scenes use manimlib directly: no st_manim kit, cues or checks"}
