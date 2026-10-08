#!/usr/bin/env python3
"""Render speed, before and after: the same projects rendered by two showtime versions, interleaved, best of N.

    python scripts/render_speed.py --out ~/rs                                  # v0.4.0 vs this checkout
    python scripts/render_speed.py --out ~/rs --before v0.4.0 --after HEAD --reps 2
    python scripts/render_speed.py --out ~/rs --gpu off --workers auto,3,8,16  # a machine without a GPU
    python scripts/render_speed.py --out ~/rs --variants seq,medium,prewarm,noflag --templates showreel
    python scripts/render_speed.py --out ~/rs --fps 90 --templates launch       # 2,700 frames
    python scripts/render_speed.py --out ~/rs --project PATH --span 10-15      # a real project, one 5 s span
    python scripts/render_speed.py --out ~/rs --splice 6-7                     # a 1 s fix spliced into a job

--before/--after take a git ref of this repository (extracted with `git archive`, read only) or a folder
that holds a skill (scripts/render.mjs). Projects: --projects DIR (folders named after the templates), else
`showtime new <template>` from the after copy. Every render runs `node <skill>/scripts/render.mjs` directly
(not the launcher, so ~/.showtime/skill-path is never rewritten) with the same ffmpeg, browser and node.

Variants of the after copy (each is one more column, interleaved with the others):
  seq      SHOWTIME_PIPE_ENCODE=0: encode after the capture, as before 0.4.1
  medium   --x264-preset medium (the encoder preset before 0.4.1)
  prewarm  SHOWTIME_PREWARM=1: each page draws every clip's first frame before it captures (shader warm-up)
  parts2   SHOWTIME_RENDER_PARTS=2: two parts per worker, each worker's second after all the first ones
           (the in-order encoder gets the first half of the video early; one more warm-up per worker)
  noflag   a copy of the after skill without --disable-frame-rate-limit in chrome-flags.json ("render")

Full renders get a fresh soundtrack cache each (SHOWTIME_AUDIO_CACHE_DIR), so no side reuses a mix; --span
renders share one per side (the second rep of the after side may reuse the first one's mix: the fix loop); --splice
renders a full final into a job per side and then the fix twice (the after side's second fix may reuse the
soundtrack, which is the point). Frames are kept for the first rep of each config and compared by hash
between before and after; files are compared by md5 and SSIM.

Writes OUT/runs.jsonl (one line per render: wall, render.json timings, workers and why, size, md5) and
OUT/summary.md (best wall per config, the stage split, size and SSIM against before). The machine's load is
recorded with each run: on a busy machine say the numbers are noisy. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SHOWTIME_HOME") or Path.home() / ".showtime")


def ffmpeg_bin() -> str:
    exe = ".exe" if os.name == "nt" else ""
    for c in [os.environ.get("SHOWTIME_FFMPEG"), str(HOME / "bin" / ("ffmpeg" + exe)), shutil.which("ffmpeg")]:
        if c and Path(c).is_file():
            return c
    sys.exit("no ffmpeg found (run `showtime setup`)")


def venv_python() -> str:
    for c in (HOME / "venv" / "bin" / "python", HOME / "venv" / "Scripts" / "python.exe"):
        if c.is_file():
            return str(c)
    return sys.executable


def skill_copy(spec: str, dest: Path) -> Path:
    """A skill folder from a path or a git ref (git archive, extracted under dest)."""
    p = Path(spec).expanduser()
    for cand in (p, p / "skills" / "showtime"):
        if (cand / "scripts" / "render.mjs").is_file():
            return cand.resolve()
    out = dest / re.sub(r"[^A-Za-z0-9._-]+", "_", spec)
    if not (out / "skills" / "showtime" / "scripts" / "render.mjs").is_file():
        out.mkdir(parents=True, exist_ok=True)
        tar = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", spec, "skills/showtime"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if tar.returncode != 0:
            sys.exit("git archive %s failed: %s" % (spec, tar.stderr.decode("utf-8", "replace")[-400:]))
        with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as tf:
            tf.extractall(str(out))
    return (out / "skills" / "showtime").resolve()


def noflag_copy(skill: Path, dest: Path) -> Path:
    out = dest / "after-noflag"
    if not (out / "scripts" / "render.mjs").is_file():
        shutil.copytree(str(skill), str(out), ignore=shutil.ignore_patterns("tests", "__pycache__"))
    f = out / "scripts" / "lib" / "chrome-flags.json"
    j = json.loads(f.read_text(encoding="utf-8"))
    for k in ("common", "render"):
        j[k] = [x for x in j.get(k, []) if x != "--disable-frame-rate-limit"]
    f.write_text(json.dumps(j, indent=2), encoding="utf-8")
    return out


def py_env(skill: Path) -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(skill / "lib")
    env["SHOWTIME_SKILL"] = str(skill)
    env["PYTHONUTF8"] = "1"
    env["PATH"] = str(HOME / "bin") + os.pathsep + env.get("PATH", "")
    return env


def make_projects(skill: Path, dest: Path, templates: List[str]) -> Dict[str, Path]:
    out = {}
    for t in templates:
        d = dest / t
        if not (d / "showtime.json").is_file():
            cp = subprocess.run([venv_python(), "-m", "st.cli", "new", t, str(d)], env=py_env(skill), cwd=str(dest),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
            if cp.returncode != 0 or not (d / "showtime.json").is_file():
                sys.exit("showtime new %s failed: %s" % (t, (cp.stderr or cp.stdout)[-800:]))
        out[t] = d
    return out


def load() -> Optional[float]:
    try:
        return round(os.getloadavg()[0], 1)
    except (AttributeError, OSError):
        return None


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ssim(a: Path, b: Path) -> Optional[float]:
    cp = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]ssim", "-f", "null", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    m = re.findall(r"All:([0-9.]+)", cp.stderr)
    return float(m[-1]) if m else None


def frame_hashes(folder: Path) -> Dict[str, str]:
    return {f.name: md5(f) for f in sorted(folder.glob("f_*"))} if folder.is_dir() else {}


def render(skill: Path, proj: Path, out: Path, args: List[str], env_extra: Dict[str, str]) -> dict:
    node = shutil.which("node") or "node"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, **env_extra)
    env.pop("SHOWTIME_OUT", None)
    l0 = load()
    t0 = time.time()
    cp = subprocess.run([node, str(skill / "scripts" / "render.mjs"), str(proj), "--json", "--no-check"] + args + ["-o", str(out)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=env)
    wall = time.time() - t0
    try:
        rep = json.loads(cp.stdout)
    except ValueError:
        rep = {"ok": False, "error": (cp.stderr or "")[-1500:]}
    rep["_wall"] = round(wall, 2)
    rep["_load"] = [l0, load()]
    rep["_rc"] = cp.returncode
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="results folder (renders go to OUT/renders, deleted unless --keep)")
    ap.add_argument("--before", default="v0.4.0", help="git ref or skill folder (default v0.4.0, the previous release)")
    ap.add_argument("--after", default=str(REPO / "skills" / "showtime"), help="git ref or skill folder (default: this checkout)")
    ap.add_argument("--templates", default="showreel,dom,launch")
    ap.add_argument("--projects", help="folder with one project per template name (default: showtime new)")
    ap.add_argument("--project", help="one real project instead of the templates (use with --span)")
    ap.add_argument("--span", help="S-E: render only these seconds (a span clip) of every project")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--gpu", default="auto")
    ap.add_argument("--fps", help="render at this frame rate (e.g. 90: 2,700 frames for the 30 s launch film)")
    ap.add_argument("--workers", default="auto", help="comma list: auto and/or numbers (each one is a config)")
    ap.add_argument("--variants", default="", help="comma list of after variants: seq, medium, prewarm, parts2, noflag")
    ap.add_argument("--splice", help="S-E: also time a fix of these seconds spliced into a job's full render")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the rendered files")
    a = ap.parse_args()

    out = Path(a.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / "renders"
    work.mkdir(exist_ok=True)
    skills = out / "skills"
    skills.mkdir(exist_ok=True)
    before = skill_copy(a.before, skills)
    after = skill_copy(a.after, skills)
    sides = [("before", before, {}, [])]
    sides.append(("after", after, {}, []))
    for v in [x for x in a.variants.split(",") if x]:
        if v == "seq":
            sides.append(("after-seq", after, {"SHOWTIME_PIPE_ENCODE": "0"}, []))
        elif v == "medium":
            sides.append(("after-medium", after, {}, ["--x264-preset", "medium"]))
        elif v == "prewarm":
            sides.append(("after-prewarm", after, {"SHOWTIME_PREWARM": "1"}, []))
        elif v == "parts2":
            sides.append(("after-parts2", after, {"SHOWTIME_RENDER_PARTS": "2"}, []))
        elif v == "noflag":
            sides.append(("after-noflag", noflag_copy(after, skills), {}, []))
        else:
            sys.exit("unknown variant %s" % v)
    if a.project:
        projects = {Path(a.project).name: Path(a.project).resolve()}
    elif a.projects:
        projects = {t: Path(a.projects).expanduser().resolve() / t for t in a.templates.split(",")}
    else:
        projects = make_projects(after, out / "projects", a.templates.split(","))
    common = ["--gpu", a.gpu] + (["--fps", a.fps] if a.fps else []) + (["--no-audio"] if a.no_audio else [])
    if a.span:
        s, e = a.span.split("-")
        common += ["--from", s, "--to", e]
    workers = [w.strip() for w in a.workers.split(",") if w.strip()]

    machine = {"platform": platform.platform(), "cpus": os.cpu_count(), "python": sys.version.split()[0],
               "node": subprocess.run([shutil.which("node") or "node", "--version"], stdout=subprocess.PIPE, encoding="utf-8").stdout.strip(),
               "before": a.before, "after": a.after, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "machine.json").write_text(json.dumps(machine, indent=2), encoding="utf-8")
    runs = out / "runs.jsonl"
    rows: List[dict] = []

    def record(row: dict) -> None:
        rows.append(row)
        with open(runs, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print("%-10s %-14s w=%-4s rep %d  wall %6.1f s  capture %6.1f  encode %5.1f  %s" % (
            row["project"], row["side"], row["workers_arg"], row["rep"], row["wall"], (row["timings"].get("capture") or 0) / 1000,
            (row["timings"].get("encode") or 0) / 1000, "" if row["ok"] else "FAILED " + str(row.get("error", ""))[:200]), flush=True)

    for name, proj in projects.items():
        for w in workers:
            for rep in range(a.reps):
                for side, skill, env, extra in sides:     # interleaved: before, after, variants, then again
                    o = work / name / ("w" + w) / side / ("rep%d" % rep) / "final.mp4"
                    if o.parent.exists():
                        shutil.rmtree(str(o.parent), ignore_errors=True)
                    # a full render mixes its soundtrack every time; a span (the fix loop) may reuse its side's earlier mix
                    cache = work / ".audio-cache" / name / side
                    env = dict(env, SHOWTIME_AUDIO_CACHE_DIR=str(cache if a.span else cache / ("w" + w) / str(rep)))
                    args = common + extra + ([] if w == "auto" else ["--workers", w]) + (["--keep-frames"] if rep == 0 else [])
                    r = render(skill, proj, o, args, env)
                    t = r.get("timings") or {}
                    record({"project": name, "side": side, "workers_arg": w, "rep": rep, "ok": bool(r.get("ok")) and r["_rc"] == 0,
                            "error": r.get("error"), "wall": r["_wall"], "load": r["_load"], "timings": t, "workers": r.get("workers"),
                            "workers_why": r.get("workers_why"), "encode": r.get("encode"), "frames": r.get("frames"),
                            "size": r.get("size_bytes"), "md5": md5(Path(r["output"])) if r.get("output") and Path(r["output"]).is_file() else None,
                            "output": r.get("output"), "audio_reused": (r.get("audio") or {}).get("reused", False)})
        if a.splice:
            s, e = a.splice.split("-")
            for side, skill, env, extra in sides[:2]:
                jobs_dir = work / name / "splice" / side
                shutil.rmtree(str(jobs_dir), ignore_errors=True)
                jobs_dir.mkdir(parents=True)
                ji = subprocess.run([venv_python(), "-m", "st.cli", "job", "init", "speed", "--base", str(jobs_dir), "--json"], env=py_env(after),
                                    cwd=str(jobs_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
                try:
                    job = Path(json.loads(ji.stdout)["job"])
                except (ValueError, KeyError):
                    print("job init failed: %s" % (ji.stderr or ji.stdout)[-600:])
                    continue
                cache = {"SHOWTIME_AUDIO_CACHE_DIR": str(work / ".audio-cache" / name / "splice" / side)}
                node = shutil.which("node") or "node"
                cp = subprocess.run([node, str(skill / "scripts" / "render.mjs"), str(proj), "--json", "--no-check", "--job", str(job), "--gpu", a.gpu] + extra,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=dict(os.environ, **env, **cache))
                if cp.returncode != 0:
                    print("full render into the job failed (%s): %s" % (side, cp.stderr[-600:]))
                    continue
                for k in range(2):
                    l0 = load()
                    t0 = time.time()
                    cp = subprocess.run([node, str(skill / "scripts" / "render.mjs"), str(proj), "--json", "--no-check", "--job", str(job), "--gpu", a.gpu,
                                         "--from", s, "--to", e] + extra, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                        env=dict(os.environ, **env, **cache))
                    wall = time.time() - t0
                    try:
                        r = json.loads(cp.stdout)
                    except ValueError:
                        r = {"ok": False, "error": cp.stderr[-800:]}
                    record({"project": name, "side": side + "-splice", "workers_arg": "auto", "rep": k, "ok": cp.returncode == 0, "error": r.get("error"),
                            "wall": round(wall, 2), "load": [l0, load()], "timings": r.get("timings") or {}, "workers": r.get("workers"),
                            "workers_why": r.get("workers_why"), "encode": r.get("encode"), "frames": r.get("frames"), "size": r.get("size_bytes"),
                            "md5": None, "output": r.get("output"), "splice": (r.get("splice") or {}).get("mode"),
                            "audio_reused": (r.get("audio") or {}).get("reused", False)})

    # ---- summary
    lines = ["# Render speed: %s vs %s" % (a.before, a.after), "",
             "%s, %s CPU threads, node %s; started %s. Wall = outer time of `node render.mjs`; best of %d, interleaved. "
             "Load = 1-minute load average before/after each run (a busy machine makes every number noisy)." % (
                 machine["platform"], machine["cpus"], machine["node"], machine["started"], a.reps), "",
             "| project | workers | side | best wall s | all walls | capture s | encode s (after capture) | audio wait s | workers (why) | MB | same file as before | SSIM vs before | frames same as before | load |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    by: Dict[tuple, List[dict]] = {}
    for r in rows:
        by.setdefault((r["project"], r["workers_arg"], r["side"]), []).append(r)
    for (pname, w, side), rs in by.items():
        ok = [r for r in rs if r["ok"]]
        if not ok:
            lines.append("| %s | %s | %s | FAILED | | | | | | | | | | |" % (pname, w, side))
            continue
        best = min(ok, key=lambda r: r["wall"])
        ref = by.get((pname, w, "before"), [])
        ref_ok = [r for r in ref if r["ok"]]
        same = ssim_v = fsame = ""
        if ref_ok and not side.startswith("before") and not side.endswith("splice") and best.get("output"):
            rb = min(ref_ok, key=lambda r: r["wall"])
            same = "yes" if rb["md5"] == best["md5"] else "no"
            if rb.get("output") and Path(rb["output"]).is_file() and Path(best["output"]).is_file():
                v = ssim(Path(rb["output"]), Path(best["output"]))
                ssim_v = "%.5f" % v if v is not None else "?"
            fa = frame_hashes(Path(rs[0]["output"]).parent / "final.work" / "frames") if rs[0].get("output") else {}
            fb = frame_hashes(Path(ref[0]["output"]).parent / "final.work" / "frames") if ref[0].get("output") else {}
            if fa and fb:
                d = [k for k in fb if fa.get(k) != fb[k]]
                fsame = "all %d" % len(fb) if not d else "%d of %d differ (first %s)" % (len(d), len(fb), d[0])
        t = best["timings"]
        lines.append("| %s | %s | %s | %.1f | %s | %.1f | %.1f | %.1f | %s (%s) | %.1f | %s | %s | %s | %s |" % (
            pname, w, side, best["wall"], " / ".join("%.1f" % r["wall"] for r in ok), (t.get("capture") or 0) / 1000, (t.get("encode") or 0) / 1000,
            (t.get("audio_wait") or 0) / 1000, best.get("workers"), best.get("workers_why") or "", (best.get("size") or 0) / 1e6, same, ssim_v, fsame,
            "/".join(str(x) for x in best["load"])))
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if not a.keep:
        for r in rows:
            if r.get("output"):
                shutil.rmtree(str(Path(r["output"]).parent), ignore_errors=True)
        shutil.rmtree(str(work / ".audio-cache"), ignore_errors=True)
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
