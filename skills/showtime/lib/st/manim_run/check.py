"""`showtime manim check`: static checks, then a dry run of every scene that reads the kit's event log.

Static (no manim needed): scenes exist, beat ids and cue words exist in the narration, LaTeX is
available when the file uses equations (else a FIX line for this OS), the theme's contrast notes.
Dry run (manim runs construct() without drawing a frame, a few seconds per scene):
  ERROR  import_failed, scene_failed, cue_not_found, latex_missing
  WARN   cue_ambiguous a line id that is also a spoken word (at("half") with a line named "half")
  WARN   static_hold   2.5 s or more with nothing visibly moving mid-video (ERROR from 6 s), an end hold over
                        4 s: qa's thresholds (runtime/thresholds.json). A play that changes too little of the
                        frame for qa's frozen-frame detector (a thin line, a small label) does not break a hold;
                        still frames at a scene's end and the next scene's start count as one hold
  WARN   cue_late      a reveal lands after its cue word (the picture trails the voice)
  WARN   word_budget   title > 4 words, label > 3, callout/note/plain text > 8
  WARN   color_drift   one concept shown in two colours, or not in its declared colour
  WARN   outside_safe  something crosses the safe area at a beat boundary
  WARN   baseline_mismatch  words and math (or a number) side by side sit on baselines more than 4 % of
                            the text's cap height apart (glyph geometry, not boxes: descenders and
                            superscripts do not count)
  WARN   xheight_mismatch   math beside words whose x-height differs from the text's by more than 12 %
  WARN   mixed_type    Text and MathTex/Tex combined on one line by hand, not with mixed_line()/align_baseline()
  WARN   black_segment, first_frame_black (ERROR), frozen  qa's black and frozen-frame detectors on a draft
                        render (480p15, the scenes `manim render` caches), with qa's thresholds: Manim's
                        near-black ground with sparse content and a small Indicate on an equation are what
                        qa flagged in real runs; a hold the dry run already named is not repeated (--no-draft skips)
  INFO   estimated cues, scene lengths, short final hold
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ShowtimeError
from . import cues as cues_mod
from . import palette, tex
from .project import Project, size_for

MIN_END_HOLD = 1.5
INK_CONTRAST = 0.8   # calibrated on draft renders against qa's freezedetect (a 3-word title fade-in is just visible)


def hold_thresholds() -> Dict[str, float]:
    """qa's thresholds (runtime/thresholds.json): a mid-video still WARNs from still_hold_s and FAILs from
    frozen_fail_s, an end hold WARNs above final_hold_max_s. `ink` is the least share of the frame a play
    must change to break a hold: qa's frozen-frame detector sees a mean difference under freeze_noise_db
    as no change, so a thin line or a small label moving is still a hold for it."""
    from ..qa.video import thresholds
    th = dict(thresholds())
    th["ink"] = 10 ** (th["freeze_noise_db"] / 20.0) / INK_CONTRAST
    return th
BUDGETS = {"title": 4, "label": 3, "callout": 8, "note": 8, None: 8}


class Findings:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, level: str, code: str, message: str, scene: Optional[str] = None, fix: Optional[str] = None,
            **data: Any) -> None:
        self.items.append(dict(level=level, code=code, message=message, scene=scene, fix=fix, **data))

    def count(self, level: str) -> int:
        return sum(1 for i in self.items if i["level"] == level)


def static_checks(project: Project, names: List[str], cues: Optional[Dict[str, Any]], f: Findings) -> None:
    if tex.uses_tex(project.source):
        info = tex.find()
        if not info["ok"]:
            f.add("ERROR", "latex_missing", "the scene file uses equations (LaTeX) and no LaTeX was found",
                  fix=" ; ".join(tex.fix_lines()))
        else:
            missing = tex.missing_packages(info)
            if missing:
                f.add("ERROR", "tex_package_missing", "LaTeX is missing packages Manim needs: " + ", ".join(missing),
                      fix=tex.fix_text(missing=missing))
    if not cues:
        for n in names:
            if project.beats_of(n):
                f.add("INFO", "no_cues", "beats are declared but there is no voice timeline or narration.md: "
                      "scenes run on their own timing", scene=n,
                      fix="write narration.md (## <beat> headings), then: showtime voice script narration.md -o voice/")
                break
        return
    ids = [ln["id"] for ln in cues["lines"]]
    words = {ln["id"]: [cues_mod.norm_word(w[0]) for w in ln["words"]] for ln in cues["lines"]}
    allw = {w for ws in words.values() for w in ws}
    clash = [i for i in ids if cues_mod.norm_word(i) in allw]
    if clash:
        said = {i: [lid for lid, ws in words.items() if cues_mod.norm_word(i) in ws] for i in clash}
        f.add("WARN", "cue_ambiguous", "line id%s %s %s also spoken (%s): at(%r) means the word inside a line that "
              "says it and the start of line %r everywhere else" % (
                  "s" if len(clash) > 1 else "", ", ".join(repr(c) for c in clash), "are" if len(clash) > 1 else "is",
                  "; ".join("%r in %s" % (c, ", ".join(said[c])) for c in clash), clash[0], clash[0]),
              fix="rename the line (## %s-line in narration.md, then the beat() calls) so ids and words never "
                  "collide; for the word in another line use \"<line>:<word>\"" % clash[0], ids=clash)
    for n in names:
        for meth, val, line in project.string_calls(n, ("beat", "at", "fit", "cue_time")):
            if meth == "beat":
                if val not in ids:
                    f.add("ERROR", "beat_unknown", "beat(%r) at %s:%d is not a narration line (lines: %s)"
                          % (val, project.file.name, line, ", ".join(ids)), scene=n,
                          fix="name the line `## %s` in narration.md, or use an existing id" % val)
                continue
            cue = val
            if cue in ids or (cue.endswith(".end") and cue[:-4] in ids):
                continue
            lid = None
            if ":" in cue and cue.split(":", 1)[0] in ids:
                lid, cue = cue.split(":", 1)
            w = cues_mod.norm_word(cue.split("#", 1)[0])
            pool = set(words[lid]) if lid else allw
            if w not in pool:
                f.add("ERROR", "cue_not_found", "%s(%r) at %s:%d: the narration never says %r" % (
                    meth, val, project.file.name, line, w), scene=n,
                    fix="pick a word from `showtime manim cues %s`" % project.dir)


def _line_fix(e: Dict[str, Any]) -> str:
    text, other = e.get("text") or "...", e.get("other") or "..."
    if e.get("part") != "math":
        return ('put the number on the text\'s baseline: VGroup(words, number).arrange(RIGHT), then '
                'align_baseline(words, number) (never arrange(aligned_edge=DOWN): a descender such as "g" '
                'or "y" lowers the box, not the baseline)')
    return ('build the line with mixed_line("%s", tex(r"%s")): one baseline, the math scaled to the text\'s '
            'x-height, bold math beside bold text. For parts placed by hand: align_baseline(text, math). Never '
            'arrange(aligned_edge=DOWN) or nudge by eye' % (text, other))


def type_line_findings(e: Dict[str, Any], f: Findings, name: str, fps: float) -> None:
    """Findings for one `type_line` event (words and math, or a number, side by side on one line). The
    same line in a later scene (scenes open on the previous one's last frame) is folded into the first."""
    at = e["f"] / fps
    what = "\"%s\" and \"%s\"" % (e.get("text"), e.get("other"))
    issues = e.get("issues") or []
    todo = []
    if "baseline" in issues:
        todo.append(("baseline_mismatch", "%s sit on different baselines: off by %d %% of the text's cap height "
                     "(tolerance 4 %%)" % (what, round(abs(e.get("baseline_off", 0)) * 100)),
                     {"baseline_off": e.get("baseline_off")}))
    if "x_height" in issues:
        r = e.get("x_height_ratio", 1)
        todo.append(("xheight_mismatch", "%s: the math's x-height is %d %% of the text's (tolerance 12 %%), so it "
                     "reads a size %s" % (what, round(r * 100), "smaller" if r < 1 else "larger"),
                     {"x_height_ratio": r}))
    if "no_helper" in issues:
        todo.append(("mixed_type", "%s: words and math on one line placed by hand (Text and MathTex have different "
                     "metrics: the boxes line up, the glyphs do not)" % what, {}))
    seen = getattr(f, "type_lines", None)
    if seen is None:
        seen = f.type_lines = {}  # type: ignore[attr-defined]
    for code, msg, data in todo:
        key = (code, e.get("text"), e.get("other"))
        if key in seen:
            first = seen[key]
            if name != first["scene"] and name not in first["also"]:
                first["also"].append(name)
                first["message"] = first["base"] + " (from %.1f s in %s; also in %s)" % (
                    first["at"], first["scene"], ", ".join(first["also"]))
            continue
        f.add("WARN", code, msg + " (from %.1f s)" % at, scene=name, fix=_line_fix(e), at=round(at, 2), **data)
        item = f.items[-1]
        item["also"], item["base"] = [], msg
        seen[key] = item


def _hold_finding(f: Findings, name: str, start: float, secs: float, is_end: bool, subtle: int,
                  th: Dict[str, float], note: str = "") -> None:
    small = (" (%d animation%s too small for qa to see as change: thin lines, small labels, a slow sweep)"
             % (subtle, "" if subtle == 1 else "s")) if subtle else ""
    fix = ("add a visible change (a larger label, a highlight, a slow camera push of 5-7 %%) or shorten the beat; "
           "qa WARNs from %.1f s and FAILs from %.0f s" % (th["still_hold_s"], th["frozen_fail_s"]))
    if is_end:
        if secs > th["final_hold_max_s"] + 1e-6:
            f.add("WARN", "static_hold", "%.1f s with nothing moving at %.1f-%.1f s (the end hold; qa WARNs over "
                  "%.0f s)%s%s" % (secs, start, start + secs, th["final_hold_max_s"], small, note), scene=name,
                  fix="shorten the end hold to %.0f s or less, or add a slow drift" % th["final_hold_max_s"],
                  at=round(start, 2), seconds=round(secs, 2))
        return
    if secs >= th["still_hold_s"] - 1e-6:
        fail = secs >= th["frozen_fail_s"] - 1e-6
        f.add("ERROR" if fail else "WARN", "static_hold", "%.1f s with nothing moving at %.1f-%.1f s%s%s%s" % (
            secs, start, start + secs, " (qa FAILs this)" if fail else "", small, note), scene=name, fix=fix,
            at=round(start, 2), seconds=round(secs, 2))


def analyze_log(lg: Dict[str, Any], f: Findings, declared: Dict[str, str], last: bool,
                th: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    th = th or hold_thresholds()
    name = lg["scene"]
    fps = float(lg["fps"])
    frames = int(lg["frames"])
    active = [False] * max(frames, 1)
    subtle_at = [0] * max(frames, 1)
    acc = 0.0      # change since the last visible change (qa's detector compares with the start of a hold)
    for e in sorted(lg["events"], key=lambda ev: ev["f"]):
        if e["kind"] == "play":
            ink = e.get("ink")
            if ink is not None and acc + ink < th["ink"]:
                acc += ink
                if e["f"] < frames:
                    subtle_at[e["f"]] = 1
                continue
            acc = 0.0
        elif not (e["kind"] == "wait" and e.get("moving")):
            continue
        acc = 0.0
        for k in range(e["f"], min(frames, e["f"] + e["n"])):
            active[k] = True
    run = 0
    runs = []
    for k in range(frames):
        if active[k]:
            if run:
                runs.append((k - run, run))
            run = 0
        else:
            run += 1
    if run:
        runs.append((frames - run, run))
    for start, length in runs:
        is_end = start + length >= frames
        if start == 0 or is_end:
            continue            # joined with the neighbouring scene's still frames in check()
        _hold_finding(f, name, start / fps, length / fps, False, sum(subtle_at[start:start + length]), th)
    head = runs[0] if runs and runs[0][0] == 0 else None
    tail = runs[-1] if runs and runs[-1][0] + runs[-1][1] >= frames else None
    if last:
        end_hold = runs[-1][1] / fps if runs and runs[-1][0] + runs[-1][1] >= frames else 0.0
        if end_hold < MIN_END_HOLD:
            f.add("INFO", "short_end", "the last frame holds %.1f s (2-3 s lets the final image land)" % end_hold,
                  scene=name, fix="end with self.hold(2.5)")
    for e in lg["events"]:
        if e["kind"] == "late" and e.get("by", 0) > 1.0 / fps + 1e-6:
            f.add("WARN", "cue_late", "%s lands %.2f s late at %.1f s" % (e["why"], e["by"], e["f"] / fps), scene=name,
                  fix="shorten the animations before it, or cue an earlier word")
        elif e["kind"] == "outside_safe":
            f.add("WARN", "outside_safe", "%s cross the safe area at %.1f s" % (", ".join(e["mobjects"]), e["f"] / fps),
                  scene=name, fix="use place(mob, region) or fit_width(); mark a deliberate bleed with mob._st_bleed = True")
        elif e["kind"] == "no_cues":
            f.add("INFO", "no_cues", "at()/fit() cues are ignored: no voice timeline or narration.md", scene=name)
        elif e["kind"] == "type_line":
            type_line_findings(e, f, name, fps)
        elif e["kind"] == "type_line_error":
            f.add("INFO", "type_line_skipped", "mixed text/math lines were not measured: %s" % e.get("error"),
                  scene=name)
    for t in lg.get("texts", []):
        budget = BUDGETS.get(t.get("tier"), 8)
        if t["words"] > budget:
            f.add("WARN", "word_budget", "%s text has %d words (budget %d): %r" % (
                t.get("tier") or "plain", t["words"], budget, t["text"][:60]), scene=name,
                fix="the narration carries sentences; keep %s text to %d words" % (t.get("tier") or "on-screen", budget))
    for key, cols in (lg.get("colors") or {}).items():
        want = declared.get(key)
        if len(cols) > 1:
            f.add("WARN", "color_drift", "%r appears in %d colours (%s)" % (key, len(cols), ", ".join(cols)), scene=name,
                  fix="one colour per concept: declare it once in manim.json \"colors\" and drop per-equation colours")
        elif want and cols and cols[0].lower() != want.lower():
            f.add("WARN", "color_drift", "%r is %s but manim.json declares %s" % (key, cols[0], want), scene=name,
                  fix="remove the per-equation colour so the declared one applies")
    return {"name": name, "seconds": round(frames / fps, 3), "frames": frames, "origin": lg.get("origin", 0),
            "_head": (head[1], sum(subtle_at[:head[1]])) if head else None,
            "_tail": (tail[1], sum(subtle_at[tail[0]:])) if tail else None, "_fps": fps}


def join_holds(summary: List[Dict[str, Any]], f: Findings, th: Dict[str, float]) -> None:
    """Still frames at the end of one scene and the start of the next are one hold in the final video."""
    t0 = 0.0
    run: Optional[Dict[str, Any]] = None       # {"start", "secs", "subtle", "scenes"}
    for i, s in enumerate(summary):
        fps = s["_fps"]
        whole = s["_head"] is not None and s["_head"][0] >= s["frames"]
        if s["_head"] is not None:
            secs, sub = s["_head"][0] / fps, s["_head"][1]
            if run is None:
                run = {"start": t0, "secs": 0.0, "subtle": 0, "scenes": []}
            run["secs"] += secs
            run["subtle"] += sub
            run["scenes"].append(s["name"])
        if not whole:
            if run is not None:
                _flush(run, f, th, is_end=False)
            run = None
            if s["_tail"] is not None:
                ln, sub = s["_tail"]
                run = {"start": t0 + (s["frames"] - ln) / fps, "secs": ln / fps, "subtle": sub, "scenes": [s["name"]]}
        t0 += s["frames"] / fps
    if run is not None:
        _flush(run, f, th, is_end=True)


def _flush(run: Dict[str, Any], f: Findings, th: Dict[str, float], is_end: bool) -> None:
    scenes = list(dict.fromkeys(run["scenes"]))
    note = (" (across scenes %s)" % " -> ".join(scenes)) if len(scenes) > 1 else ""
    _hold_finding(f, scenes[0], run["start"], run["secs"], is_end, run["subtle"], th, note=note)


def check(target: Path, scenes: Optional[List[str]] = None, cues_arg: Optional[str] = None,
          brand: Optional[str] = None, dry_run: bool = True, aspect: Optional[str] = None,
          draft: bool = True) -> Dict[str, Any]:
    from .render import kit_settings, manim_installed, resolve_theme, run_kit
    project = Project(target)
    f = Findings()
    for w in project.warnings:
        f.add("WARN", "config", w)
    if project.engine == "gl":
        f.add("INFO", "engine", "ManimGL scene file: only static checks apply (the kit and its checks are "
              "Manim Community)")
        dry_run = False
    names = project.scenes(scenes)
    fps = float(project.cfg.get("fps", 30))     # the final rate: frame snapping differs per rate
    aspect = aspect or project.aspect
    width, height = size_for(aspect, "draft")
    cues = cues_mod.load(cues_arg, project.dir, project.cfg.get("voice", "voice/timeline.json"),
                         project.cfg.get("narration", "narration.md"), fps)
    if cues and cues.get("estimated"):
        f.add("INFO", "estimated_cues", "timing estimated from %s until the voice exists" % Path(cues["source"]).name,
              fix="showtime voice script %s -o voice/" % Path(cues["source"]).name)
    static_checks(project, names, cues, f)
    theme = resolve_theme(project, brand, install_fonts=False)
    for n in theme.get("notes") or []:
        f.add("INFO", "theme", n)
    declared = {k: palette.resolve_color(v, theme) or "" for k, v in project.colors.items()}
    summary: List[Dict[str, Any]] = []
    blocked = any(i["code"] in ("latex_missing", "tex_package_missing", "beat_unknown") for i in f.items)
    if dry_run and not blocked:
        if not manim_installed():
            f.add("WARN", "manim_missing", "manim is not installed: render-time checks skipped",
                  fix="showtime setup --with manim")
        else:
            cdir = project.build_dir() / "check"
            cdir.mkdir(parents=True, exist_ok=True)
            paths = {n: {"log": str(cdir / ("%s.log.json" % n))} for n in names}
            for p in paths.values():
                if Path(p["log"]).exists():
                    Path(p["log"]).unlink()
            settings = kit_settings(project, cues, theme, paths)
            settings["aspect"] = aspect
            res = run_kit(project, names, width=width, height=height, fps=fps, settings=settings, dry_run=True,
                          label="check")
            if res.get("import_error"):
                f.add("ERROR", "import_failed", "%s does not import: %s" % (project.file.name, res["import_error"]),
                      fix=res.get("where") or "see %s" % res["log"])
            for rec in res.get("scenes", []):
                if not rec.get("ok"):
                    err = rec.get("error", "")
                    code = "cue_not_found" if rec.get("kind") == "CueError" else "scene_failed"
                    low = (err + rec.get("traceback", "")).lower()
                    if "latex" in low and ("not found" in low or "error converting" in low):
                        code = "latex_missing"
                    f.add("ERROR", code, "%s: %s" % (rec["name"], err[:300]), scene=rec["name"],
                          fix=(rec.get("where") or "see %s" % res["log"]) if code != "latex_missing"
                          else " ; ".join(tex.fix_lines()))
            ok_names = [r["name"] for r in res.get("scenes", []) if r.get("ok")]
            th = hold_thresholds()
            for i, n in enumerate(names):
                lp = Path(paths[n]["log"])
                if n in ok_names and lp.is_file():
                    lg = json.loads(lp.read_text(encoding="utf-8"))
                    summary.append(analyze_log(lg, f, declared, last=(i == len(names) - 1), th=th))
            if len(summary) == len(names):
                join_holds(summary, f, th)
            else:       # a scene failed: judge each scene's own edges
                for srec in summary:
                    join_holds([srec], f, th)
    draft_info = None
    broken = any(i["code"] in ("import_failed", "scene_failed", "cue_not_found", "latex_missing", "beat_unknown")
                 for i in f.items)          # a hold ERROR does not stop the draft: qa's view is what we want
    if dry_run and draft and not blocked and not broken and summary and len(summary) == len(names) and manim_installed():
        from .draft import draft_findings
        draft_info = draft_findings(target, project, f, scenes=scenes, aspect=aspect, cues_arg=cues_arg, brand=brand)
    for srec in summary:
        for k in ("_head", "_tail", "_fps"):
            srec.pop(k, None)
    total = sum(s["seconds"] for s in summary)
    if summary and cues:
        f.add("INFO", "length", "%d scene(s), %.1f s (narration %.1f s)" % (len(summary), total, cues["duration"]))
    for it in f.items:
        it.pop("base", None)
    return {"ok": f.count("ERROR") == 0, "project": str(project.dir), "file": str(project.file), "aspect": aspect,
            "errors": f.count("ERROR"), "warnings": f.count("WARN"), "findings": f.items, "scenes": summary,
            "duration": round(total, 3), "draft": draft_info, "cues": None if not cues else {"source": cues["source"],
                                                                         "estimated": bool(cues.get("estimated"))}}
