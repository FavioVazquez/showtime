"""Narration beats: scenes that land on the voice's words, frame-exactly.

    class Squares(ShowScene):
        def construct(self):
            self.beat("hook")                  # this narration line starts here (waits for its slot)
            self.play(FadeIn(title("Odd numbers")))
            self.at("three")                   # wait until 0.3 s before the word "three"
            self.play(Write(term))
            self.fit(Create(band), until="five")   # run_time chosen so it ends as "five" starts
            self.hold(1)                       # frame-snapped wait
            self.mark("poster")                # this frame becomes poster.jpg

Cues come from the voice timeline (`showtime voice script`), or an estimate from narration.md.
A cue is a word ("three"), the n-th time a word is said ("three#2"), a word in another line
("tiles:five"), a line id ("tiles" = its first word, "tiles.end" = its last word), or seconds
since the scene started (a number). When a line id is also a word of the line being spoken, the
word wins there (`manim check` warns about such ids: rename the line to avoid surprises). With no cues at all, at()/fit() don't wait.

Every play and wait is snapped to whole frames: Manim Community rounds animations up and still
holds down, so unsnapped scenes drift up to a frame per call. The kit keeps its own frame counter as
the clock, so cue landings are exact and a scene ends exactly on its last line's slot.

Scene k starts at the slot start of its first beat (the first scene at 0), and ends at the slot end
of its last beat, so the scenes of a project concatenate onto the voice's clock.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from manim import (MarkupText, MathTex, MovingCameraScene, Paragraph, Scene, SingleStringMathTex, Text, ThreeDScene,
                   Wait, config)
from manim.animation.animation import prepare_animation

from . import _settings
from ._layout import outside_safe
from ._line import line_metrics
from ._theme import theme

LEAD = 0.3          # at(): arrive this long before the cue word, so the motion finishes on it
BASELINE_TOL = 0.04     # type lines: baselines may differ by this share of the text's cap height
XHEIGHT_TOL = 0.12      # ... and math x-height may differ from the text's by this share


class CueError(ValueError):
    """A cue word or line id that the narration does not contain."""


def _norm(w: str) -> str:
    from st.manim_run.cues import norm_word
    return norm_word(w)


class _Beats:
    """Mixin for manim Scene classes (use ShowScene, ShowCameraScene or Show3DScene)."""

    def setup(self) -> None:  # noqa: D401 - manim hook
        super().setup()  # type: ignore[misc]
        self.st_fps = float(config.frame_rate)
        self.st_frame = 0
        self.st_origin: Optional[int] = None   # video frame where this scene starts (from its first beat)
        self.st_line: Optional[Dict[str, Any]] = None
        self.st_cues = _settings.cues()
        self.st_events: List[Dict[str, Any]] = []
        self.st_texts: Dict[int, Dict[str, Any]] = {}
        self.st_colors: Dict[str, List[str]] = {}
        self.st_lines: Dict[Tuple[int, int], Tuple[str, ...]] = {}
        self.st_warned_no_cues = False
        self.T = theme()

    # ------------------------------------------------------------ clock
    @property
    def now(self) -> float:
        """Seconds since this scene started (the kit's frame-exact clock)."""
        return self.st_frame / self.st_fps

    def _n(self, seconds: float, minimum: int = 1) -> int:
        return max(minimum, int(round(float(seconds) * self.st_fps)))

    def _moving(self) -> bool:
        s: Any = self
        try:
            return bool(s.always_update_mobjects or s.updaters or
                        any(m.has_time_based_updater() for m in s.get_mobject_family_members()))
        except Exception:  # noqa: BLE001
            return True

    def _log(self, kind: str, **data: Any) -> None:
        self.st_events.append(dict(kind=kind, f=self.st_frame, **data))

    # ------------------------------------------------------------ play / wait (frame-snapped)
    def play(self, *args: Any, **kwargs: Any) -> None:
        if len(args) == 1 and isinstance(args[0], Wait) and not kwargs:
            w = args[0]
            return self.wait(w.run_time, stop_condition=w.stop_condition)
        anims = [prepare_animation(a) for a in args]
        rt = kwargs.pop("run_time", None)
        if rt is None:
            rt = max((a.get_run_time() for a in anims), default=1.0)
        n = self._n(rt)
        kwargs["run_time"] = (n - 0.5) / self.st_fps     # manim renders ceil(run_time * fps) frames
        start = self.st_frame
        before = self._ink_state(anims)
        super().play(*anims, **kwargs)  # type: ignore[misc]
        self.st_frame += n
        ev: Dict[str, Any] = {"kind": "play", "f": start, "n": n, "anims": [type(a).__name__ for a in anims][:6]}
        ink = self._ink_change(before, self._ink_state(anims)) if before is not None else None
        if ink is not None:
            ev["ink"] = round(ink, 5)
        self.st_events.append(ev)
        self._snapshot()

    # ------------------------------------------------------------ how much of the picture a play changes
    # check compares it with qa's freeze threshold, so thin lines, small labels and a slow radius sweep that
    # qa's frozen-frame detector cannot see count as holds in check too (see manim_run/check.py)
    def _ink_state(self, anims: List[Any]) -> Optional[Dict[int, Tuple[float, ...]]]:
        s: Any = self
        if isinstance(self, ThreeDScene) or self._moving():
            return None                       # a camera or updater changes the frame: always "moving"
        frame = getattr(s.camera, "frame", None)
        out: Dict[int, Tuple[float, ...]] = {}
        try:
            for a in anims:
                mob = getattr(a, "mobject", None)
                if mob is None:
                    return None
                fam = mob.get_family()
                if frame is not None and any(m is frame for m in fam):
                    return None
                for m in fam:
                    if not m.has_points():
                        continue
                    w, h = float(m.width), float(m.height)
                    try:
                        fill = float(m.get_fill_opacity()) * w * h * 0.6
                        sw = float(m.get_stroke_width()) * 0.01 * float(m.get_stroke_opacity())
                        closed = bool(m.is_closed()) if hasattr(m, "is_closed") else False
                        stroke = sw * (w + h) * (1.6 if closed else 1.0)
                        col = hash((str(m.get_fill_color()), str(m.get_stroke_color())))
                    except Exception:  # noqa: BLE001 - not a VMobject (an image): its box
                        fill, stroke, col = w * h * float(getattr(m, "fill_opacity", 1.0) or 1.0), 0.0, 0
                    c = m.get_center()
                    out[id(m)] = (float(c[0]), float(c[1]), w, h, fill + stroke, float(col))
        except Exception:  # noqa: BLE001 - measuring must never stop a render
            return None
        return out

    @staticmethod
    def _ink_change(a: Dict[int, Tuple[float, ...]], b: Optional[Dict[int, Tuple[float, ...]]]) -> Optional[float]:
        """Share of the frame that differs after the play (0-1, rough: boxes x opacity, strokes x length)."""
        if b is None:
            return None
        area = float(config.frame_width) * float(config.frame_height)
        changed = 0.0
        net = 0.0
        for k in set(a) | set(b):
            pa, pb = a.get(k), b.get(k)
            if pa is None or pb is None:
                changed += (pa or pb)[4]  # type: ignore[index]
                continue
            moved = abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) > 0.02 or abs(pa[2] - pb[2]) + abs(pa[3] - pb[3]) > 0.02
            if moved:
                changed += pa[4] + pb[4]
            elif pa[5] != pb[5]:
                changed += max(pa[4], pb[4])
            else:
                changed += abs(pa[4] - pb[4])
            net += max(pa[4], pb[4])
        if changed < 1e-9 and net > 0:
            changed = 0.5 * net                # there and back (Indicate, a pulse): it changed mid-way
        return min(1.0, changed / area) if area > 0 else None

    def wait(self, duration: float = 1.0, stop_condition: Any = None, frozen_frame: Optional[bool] = None) -> None:
        n = self._n(duration, minimum=0)
        if n == 0:
            return
        moving = self._moving() if frozen_frame is None else not frozen_frame
        rt = (n - 0.5) / self.st_fps if moving else (n + 0.5) / self.st_fps   # moving: ceil, still: floor
        start = self.st_frame
        t0 = float(self.time)  # type: ignore[attr-defined]
        super().play(Wait(run_time=rt, stop_condition=stop_condition, frozen_frame=not moving))  # type: ignore[misc]
        if stop_condition is not None:
            n = max(1, int(round((float(self.time) - t0) * self.st_fps)))  # type: ignore[attr-defined]
        self.st_frame += n
        self.st_events.append({"kind": "wait", "f": start, "n": n, "moving": moving})

    def hold(self, seconds: float) -> None:
        """A frame-snapped wait (same as self.wait)."""
        self.wait(seconds)

    def _pad_to(self, frame: int, why: str, grace: int = 0) -> None:
        """Wait until `frame`; if it has passed by more than `grace` + 1 frames, log a late cue."""
        gap = frame - self.st_frame
        if gap > 0:
            self.wait(gap / self.st_fps)
        elif gap < -(1 + grace):
            self._log("late", why=why, by=round((-gap - grace) / self.st_fps, 3))

    # ------------------------------------------------------------ cues
    def _lines(self) -> List[Dict[str, Any]]:
        return (self.st_cues or {}).get("lines") or []

    def _line(self, line_id: str) -> Dict[str, Any]:
        for ln in self._lines():
            if ln["id"] == line_id:
                return ln
        raise CueError("no narration line %r; lines: %s" % (line_id, ", ".join(l["id"] for l in self._lines())))

    def _origin(self) -> int:
        return self.st_origin or 0

    def cue_time(self, cue: Any) -> Optional[float]:
        """Video-clock seconds of a cue (None when there are no cues and the cue is a word)."""
        if isinstance(cue, (int, float)):
            return self._origin() / self.st_fps + float(cue)
        cue = str(cue)
        if not self._lines():
            return None
        line_ids = [l["id"] for l in self._lines()]
        cur = self.st_line
        if cue in line_ids and not (cur is not None and cue != cur["id"]
                                    and any(_norm(w[0]) == _norm(cue) for w in cur["words"])):
            # a line id, unless the line being spoken says that word: at("half") inside a line that
            # says "half" means the word, not the start of another line named "half"
            return float(self._line(cue)["speech_start"])
        if cue.endswith(".end") and cue[:-4] in line_ids:
            return float(self._line(cue[:-4])["speech_end"])
        scope: List[Dict[str, Any]]
        word = cue
        if ":" in cue and cue.split(":", 1)[0] in line_ids:
            lid, word = cue.split(":", 1)
            scope = [self._line(lid)]
        elif self.st_line is not None:
            idx = line_ids.index(self.st_line["id"])
            scope = self._lines()[idx:] + self._lines()[:idx]
        else:
            scope = self._lines()
        occ = 1
        if "#" in word:
            word, o = word.rsplit("#", 1)
            occ = int(o) if o.isdigit() else 1
        key = _norm(word)
        for ln in scope:
            seen = 0
            for w, s, _e in ln["words"]:
                if _norm(w) == key:
                    seen += 1
                    if seen == occ:
                        return float(s)
        where = scope[0] if scope else None
        words = " ".join(_norm(w[0]) for w in (where or {}).get("words", []))
        raise CueError("cue %r is not in the narration%s; words of line %r: %s" % (
            cue, "" if occ == 1 else " (occurrence %d)" % occ, (where or {}).get("id"), words))

    def _cue_frame(self, cue: Any, lead: float) -> Optional[int]:
        t = self.cue_time(cue)
        if t is None:
            if not self.st_warned_no_cues:
                self._log("no_cues", cue=str(cue))
                self.st_warned_no_cues = True
            return None
        return int(round((t - lead) * self.st_fps)) - self._origin()

    def beat(self, line_id: str) -> None:
        """Start narration line `line_id` here: wait for its slot (the first beat also sets where this
        scene sits on the voice's clock)."""
        self._log("beat", id=line_id)
        if not self._lines():
            self.st_line = {"id": line_id, "words": []}
            return
        ln = self._line(line_id)
        if self.st_origin is None:   # the scene starts at its first beat's slot (the first line: at 0)
            first = self._lines()[0]["id"] == line_id
            self.st_origin = 0 if first else int(round(ln["slot_start"] * self.st_fps))
        self._pad_to(int(round(ln["slot_start"] * self.st_fps)) - self._origin(), "beat %s" % line_id)
        self.st_line = ln
        self._snapshot(safe=True)

    def at(self, cue: Any, lead: float = LEAD) -> None:
        """Wait until `lead` seconds before the cue (frame-snapped). Late cues are logged, not waited for."""
        f = self._cue_frame(cue, lead)
        if f is not None:   # late only when the motion starts after the word itself
            self._pad_to(f, "at %s" % cue, grace=int(round(lead * self.st_fps)))

    def fit(self, *anims: Any, until: Any = None, lead: float = 0.0, min_run_time: float = 0.3, **kwargs: Any) -> None:
        """Play `anims` with a run_time that ends `lead` seconds before the cue `until`."""
        f = self._cue_frame(until, lead) if until is not None else None
        if f is None:
            self.play(*anims, **kwargs)
            return
        n = f - self.st_frame
        mn = self._n(min_run_time)
        if n < mn:
            over = mn - n - int(round(lead * self.st_fps))
            if over > 1:
                self._log("late", why="fit until %s" % until, by=round(over / self.st_fps, 3))
            n = mn
        self.play(*anims, run_time=n / self.st_fps, **kwargs)

    def mark(self, name: str) -> None:
        """A named instant: "poster" saves this frame as the video's poster."""
        self._log("mark", name=name)
        if name == "poster":
            p = _settings.scene_paths(type(self).__name__).get("poster")
            if p and not config.dry_run:
                try:
                    from PIL import Image
                    arr = self.renderer.get_frame()  # type: ignore[attr-defined]
                    Image.fromarray(arr).convert("RGB").save(p)
                except Exception as e:  # noqa: BLE001 - a poster must not stop the render
                    self._log("poster_failed", error=str(e))

    # ------------------------------------------------------------ what check reads
    def _snapshot(self, safe: bool = False) -> None:
        s: Any = self
        tops = list(s.mobjects)
        for top in tops:
            for m in top.get_family():
                if isinstance(m, (Text, MarkupText, Paragraph)) and id(m) not in self.st_texts:
                    text = getattr(m, "_st_text", None) or getattr(m, "text", None) or getattr(m, "original_text", "")
                    words = len([w for w in str(text).split() if any(ch.isalnum() for ch in w)])
                    self.st_texts[id(m)] = {"text": str(text)[:120], "words": words,
                                            "tier": getattr(m, "_st_tier", None), "f": self.st_frame}
                if isinstance(m, MathTex) and getattr(m, "st_colors", None):
                    for k, col in m.st_colors.items():  # type: ignore[attr-defined]
                        seen = self.st_colors.setdefault(k, [])
                        actual = _hex(m, k, col)
                        if actual not in seen:
                            seen.append(actual)
        try:
            self._type_lines(tops)
        except Exception as e:  # noqa: BLE001 - a measuring problem must never stop a render
            if not getattr(self, "_st_line_err", False):
                self._st_line_err = True
                self._log("type_line_error", error=str(e)[:200])
        if safe:
            bad = []
            if not hasattr(s.camera, "frame"):
                for top in tops:
                    if getattr(top, "_st_bleed", False) or type(top).__name__ in ("NumberPlane", "ComplexPlane"):
                        continue
                    try:
                        if top.get_family() and max((mm.get_fill_opacity() + mm.get_stroke_opacity())
                                                    for mm in top.get_family()) < 0.05:
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                    if top.width > 0 and outside_safe(top):
                        bad.append(type(top).__name__)
            if bad:
                self._log("outside_safe", mobjects=bad[:6])

    def _type_lines(self, tops: List[Any]) -> None:
        """Words and math (or numbers) side by side on one line: same baseline, matching x-height, and
        built with mixed_line()/align_baseline(). Logged once per pair and state (check reads it)."""
        units: List[Any] = []
        seen: set = set()
        for top in tops:
            for m in top.get_family():
                if id(m) in seen:
                    continue
                kind = None
                if isinstance(m, (Text, MarkupText)) and not isinstance(m, Paragraph):
                    kind = "text"
                elif isinstance(m, SingleStringMathTex) and type(m).__name__ != "MathTexPart":
                    kind = "math"
                elif type(m).__name__ == "Counter" and getattr(m, "_st_metrics", None):
                    kind = "number"
                if kind is None:
                    continue
                seen.update(id(x) for x in m.get_family())
                try:
                    if max(x.get_fill_opacity() for x in m.family_members_with_points()) < 0.05 or m.height <= 1e-6:
                        continue
                except ValueError:
                    continue
                units.append((kind, m))
        if len(units) < 2 or len(units) > 40:
            return
        boxes = [(k, m, float(m.get_left()[0]), float(m.get_right()[0]), float(m.get_bottom()[1]),
                  float(m.get_top()[1])) for k, m in units]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                A, B = boxes[i], boxes[j]
                if (A[0] == "text") == (B[0] == "text"):
                    continue                  # one text and one math/number part (two texts share one engine)
                if A[0] != "text":
                    A, B = B, A               # a = the text (the reference), b = the math or number
                ka, a, ax0, ax1, ay0, ay1 = A
                kb, b, bx0, bx1, by0, by1 = B
                overlap = min(ay1, by1) - max(ay0, by0)
                if overlap < 0.5 * min(ay1 - ay0, by1 - by0):
                    continue
                ma = line_metrics(a)
                if ma is None:
                    continue
                g = max(ax0, bx0) - min(ax1, bx1)      # the horizontal gap between the two boxes
                if g < -0.1 * ma["cap_height"] or g > 1.5 * ma["cap_height"]:
                    continue
                mb = line_metrics(b)
                if mb is None or ma["cap_height"] <= 1e-9:
                    continue
                off = (mb["baseline"] - ma["baseline"]) / ma["cap_height"]
                ratio = mb["x_height"] / ma["x_height"] if ma["x_height"] > 1e-9 else 1.0
                issues = []
                if abs(off) > BASELINE_TOL:
                    issues.append("baseline")
                if kb == "math" and abs(ratio - 1) > XHEIGHT_TOL:
                    issues.append("x_height")
                helper = bool(getattr(a, "_st_aligned", False) and getattr(b, "_st_aligned", False))
                if kb == "math" and not helper:
                    issues.append("no_helper")
                key = (id(a), id(b))
                state = tuple(issues)
                if self.st_lines.get(key) == state:
                    continue
                self.st_lines[key] = state
                if not issues:
                    continue
                self._log("type_line", issues=issues, part=kb, helper=helper,
                          text=str(getattr(a, "_st_text", None) or getattr(a, "original_text", "") or "")[:40],
                          other=str(getattr(b, "st_tex", None) or getattr(b, "tex_string", None)
                                    or getattr(b, "_st_text", "") or "")[:40],
                          baseline_off=round(off, 3), x_height_ratio=round(ratio, 3))

    def tear_down(self) -> None:
        if self.st_line is not None and self._lines() and "slot_end" in self.st_line:
            last_line = self.st_line["id"] == self._lines()[-1]["id"]   # running past the voice's end is fine
            end = int(round(self.st_line["slot_end"] * self.st_fps)) - self._origin()
            if not (last_line and self.st_frame >= end):
                self._pad_to(end, "scene end (the next scene starts late)")
        self._snapshot(safe=True)
        self._log("end")
        super().tear_down()  # type: ignore[misc]
        p = _settings.scene_paths(type(self).__name__).get("log")
        if p:
            data = {"scene": type(self).__name__, "fps": self.st_fps, "frames": self.st_frame,
                    "origin": self._origin(), "estimated": bool((self.st_cues or {}).get("estimated")),
                    "events": self.st_events, "texts": list(self.st_texts.values()), "colors": self.st_colors,
                    "declared": theme().colors, "theme_notes": theme().notes,
                    "size": [int(config.pixel_width), int(config.pixel_height)],
                    "frame_units": [float(config.frame_width), float(config.frame_height)]}
            Path(p).write_text(json.dumps(data, indent=1), encoding="utf-8")


def _hex(m: Any, key: str, fallback: str) -> str:
    try:
        return m.part(key).get_color().to_hex().lower()
    except Exception:  # noqa: BLE001
        return fallback


class ShowScene(_Beats, Scene):
    """A manim Scene with narration beats, frame-snapped timing and the showtime theme."""


class ShowCameraScene(_Beats, MovingCameraScene):
    """ShowScene with a movable camera frame (self.camera.frame.animate...)."""


class Show3DScene(_Beats, ThreeDScene):
    """ShowScene for 3D (start flat, then tilt: self.move_camera(phi=65*DEGREES, run_time=4))."""
