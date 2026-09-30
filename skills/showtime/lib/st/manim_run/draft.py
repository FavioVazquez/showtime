"""`showtime manim check`, the draft pass: qa's black and frozen-frame detectors on a real draft render.

The dry run judges the kit's event log (what each play is expected to change). qa judges pixels, and two
things it flagged on real Manim films the event log cannot see: a frame with nothing visible on it (an
opening that fades its first title in from the empty ground, or content so faint it does not show:
blackdetect counts a frame black when 99.5 % of it is dark, and frame 0 when it also has no bright detail)
and a small change such as Indicate on one equation (the mean difference stays under freeze_noise_db, so
the stretch is "frozen"). So check renders the draft (the same 480p15 scenes
`showtime manim render` caches, so the later render costs nothing extra), runs qa's `media.detect` and
`_check_picture` on it with qa's thresholds, and reports the findings under qa's rule names with a
Manim fix. A hold the dry run already reported in the same scene is not reported twice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError
from .project import Project

# what qa's picture check may report, and how each maps onto check's levels
LEVEL = {"FAIL": "ERROR", "WARN": "WARN", "INFO": "INFO"}
BLACK_RULES = ("first_frame_black", "black_segment", "ends_black")
HOLD_RULES = ("frozen", "final_hold", "held_shot")
FRAME0_RULES = ("first_frame_flat",)          # qa's own wording and fix apply (a flat light ground at t=0)

BLACK_FIX = ('qa counts a frame as black only when nothing visible is on it (99.5 % of it dark; for frame 0 also no '
             'bright detail): a title or an equation on Manim\'s dark ground is not black, an empty ground or a faint '
             'grid alone is. Put something visible there: add() the first title, equation or image instead of fading '
             'it in from the empty ground, keep content on screen between scenes, and draw faint layers (a ghost grid) '
             'together with something bright; or set "light": true in manim.json (the brand\'s light ground is never '
             'black). A planned dip to black is the only exception')
FRAME0_FIX = ('; frame 0 is what feeds and players show as the thumbnail: add() the title or first image before the '
              'first play so t=0 already shows it')
FROZEN_FIX = ('a small change (Indicate or a flash on one equation, a label pulse, a thin line) moves too little of the '
              'frame for qa: make the change visible (a highlight() box or dim_others() on the equation, a larger '
              'move, a slow camera push of 5-7 %%) or shorten the beat; qa WARNs from %.1f s and FAILs from %.0f s')


def _span_scenes(s: float, e: float, starts: List[Tuple[str, float, float]]) -> List[str]:
    return [n for n, a, b in starts if s < b - 1e-6 and e > a + 1e-6]


def draft_findings(target: Path, project: Project, f: Any, *, scenes: Optional[List[str]], aspect: str,
                   cues_arg: Optional[str], brand: Optional[str]) -> Optional[Dict[str, Any]]:
    """Render the draft and add qa's black/frozen findings to `f` (check's Findings). Returns a summary."""
    from ..qa import media, video as qa_video
    from .render import render
    cdir = project.build_dir() / "check"
    cdir.mkdir(parents=True, exist_ok=True)
    dest = cdir / "draft.mp4"
    for old in cdir.glob("draft*.mp4"):
        old.unlink()
    try:
        res = render(target, scenes=scenes,
                     quality="draft", aspect=aspect, cues_arg=cues_arg, out=str(dest), brand=brand, no_audio=True,
                     sheet=False)
    except ShowtimeError as e:
        f.add("WARN", "draft_failed", "the draft render for qa's black and frozen-frame checks failed: %s" % e,
              fix="fix the error above, or skip this pass with --no-draft")
        return None
    out = Path(res["output"])
    dur, fps = float(res["duration"]), float(res["fps"])
    th = qa_video.thresholds()
    det = media.detect(out, dur, freeze_noise_db=th["freeze_noise_db"])
    first = media.extract_frames(out, [0.0], cdir / "frames", width=480, duration=dur, fps=fps)
    F = qa_video.Findings()
    qa_video._check_picture(F, det, first[0] if first else None, dur, fps, vpath=out)
    t0 = 0.0
    spans: List[Tuple[str, float, float]] = []
    for sc in res["scenes"]:
        d = int(sc["frames"]) / fps
        spans.append((sc["name"], t0, t0 + d))
        t0 += d
    held = {i["scene"] for i in f.items if i["code"] == "static_hold" and i.get("scene")}
    for it in F.items:
        rule = it["rule"]
        if rule not in BLACK_RULES + HOLD_RULES + FRAME0_RULES or rule == "held_shot":
            continue
        s, e = it.get("t", 0.0), it.get("end", it.get("t", 0.0))
        where = _span_scenes(s, max(e, s + 1e-3), spans)
        if rule in HOLD_RULES and any(n in held for n in where):
            continue            # the dry run already named this hold
        if rule in BLACK_RULES:
            fix = BLACK_FIX + (FRAME0_FIX if rule == "first_frame_black" else "")
        elif rule == "frozen":
            fix = FROZEN_FIX % (th["still_hold_s"], th["frozen_fail_s"])
        elif rule == "first_frame_flat":
            fix = ("add() the title or first image before the first play so frame 0 already shows it (a flat ground "
                   "is a poor thumbnail), or bake a poster: showtime deliver poster <video> --bake")
        else:
            fix = it.get("fix", "")
        extra = {"at": it.get("t"), "end": it.get("end"), "rule": rule, "source": "draft"}
        f.add(LEVEL.get(it["severity"], "WARN"), rule, it["message"] + " (in the draft render, as qa reads it)",
              scene=where[0] if where else None, fix=fix, **extra)
    return {"video": str(out), "seconds": round(dur, 3), "fps": fps, "black": det["black"], "freeze": det["freeze"]}
