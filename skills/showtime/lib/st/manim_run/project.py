"""A Manim project: a folder with manim.json + a scene file, or a bare scene file.

    manim.json (every key optional)
      title       name used for outputs                                  (folder name)
      file        the scene file                                         scenes.py
      scenes      scene classes in play order                            every scene class, file order
      aspect      16:9 | 9:16 | 1:1 | 4:5                                16:9
      fps         final frame rate (draft renders use 15)                30
      voice       voice timeline used for cues and audio                 voice/timeline.json
      narration   narration.md: estimated cues until the voice exists    narration.md
      colors      one colour per concept: {"n": "hue1", "x": "#e0a030"}  {}
      brand       brand.json path (else the usual search from the folder)
      light       use the brand's light palette                          false
      mix         audio/mix.json for music and effects under the voice

Frame units: the short side of the frame is always 8 units, so type and strokes look the same in
every aspect (a 9:16 frame is 8 x 14.22 units, not a squeezed 14.22 x 8).
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..common import ShowtimeError

PROJECT_FILE = "manim.json"
ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5)}
QUALITY = {"draft": {"short": 480, "fps": 15}, "final": {"short": 1080, "fps": 30}}
KNOWN_KEYS = {"schema", "title", "file", "scenes", "aspect", "fps", "voice", "narration", "colors", "brand",
              "light", "mix", "notes"}
SKIP_DIRS = {"build", "out", "voice", "__pycache__", ".git", "media"}


def size_for(aspect: str, quality: str) -> Tuple[int, int]:
    """Pixel size for an aspect at a quality (even numbers, short side from QUALITY)."""
    if aspect not in ASPECTS:
        raise ShowtimeError("unknown aspect %r" % aspect, hint="use one of: " + ", ".join(ASPECTS))
    a, b = ASPECTS[aspect]
    short = QUALITY[quality]["short"]
    if a >= b:
        h = short
        w = int(round(short * a / b / 2.0)) * 2
    else:
        w = short
        h = int(round(short * b / a / 2.0)) * 2
    return w, h


def frame_units(width: int, height: int) -> Tuple[float, float]:
    """(frame_width, frame_height) in scene units: the short side is 8."""
    if width >= height:
        return 8.0 * width / height, 8.0
    return 8.0, 8.0 * height / width


class Project:
    def __init__(self, target: Path) -> None:
        target = Path(target).expanduser()
        if not target.exists():
            raise ShowtimeError("not found: %s" % target,
                                hint="pass a scene file or a folder made by `showtime manim new <dir>`")
        self.cfg: Dict[str, Any] = {}
        self.warnings: List[str] = []
        if target.is_dir():
            self.dir = target.resolve()
            cfgp = self.dir / PROJECT_FILE
            if cfgp.is_file():
                self.cfg = self._read_cfg(cfgp)
            name = self.cfg.get("file") or "scenes.py"
            self.file = (self.dir / name).resolve()
            if not self.file.is_file():
                pys = sorted(p for p in self.dir.glob("*.py"))
                if len(pys) == 1 and not self.cfg.get("file"):
                    self.file = pys[0].resolve()
                else:
                    raise ShowtimeError("no scene file %s in %s" % (name, self.dir),
                                        hint="set \"file\" in manim.json, or pass the .py file itself")
        else:
            self.file = target.resolve()
            self.dir = self.file.parent
            cfgp = self.dir / PROJECT_FILE
            if cfgp.is_file():
                cfg = self._read_cfg(cfgp)
                if (self.dir / (cfg.get("file") or "scenes.py")).resolve() == self.file:
                    self.cfg = cfg
        try:
            self.source = self.file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ShowtimeError("cannot read %s: %s" % (self.file, e))
        for k in self.cfg:
            if k not in KNOWN_KEYS:
                self.warnings.append("manim.json: unknown key %r (ignored)" % k)
        aspect = self.cfg.get("aspect", "16:9")
        if aspect not in ASPECTS:
            raise ShowtimeError("manim.json: aspect %r is not supported" % aspect,
                                why="the frame size is derived from it", hint="use one of: " + ", ".join(ASPECTS))

    @staticmethod
    def _read_cfg(p: Path) -> Dict[str, Any]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ShowtimeError("%s is not valid JSON: %s" % (p, e), why="it holds the project settings",
                                hint="fix the file (or delete it to use the defaults)")
        if not isinstance(data, dict):
            raise ShowtimeError("%s must hold a JSON object" % p)
        return data

    # -------------------------------------------------------------- facts
    @property
    def title(self) -> str:
        return str(self.cfg.get("title") or (self.dir.name if self.file.name == "scenes.py" else self.file.stem))

    @property
    def aspect(self) -> str:
        return str(self.cfg.get("aspect", "16:9"))

    @property
    def colors(self) -> Dict[str, str]:
        c = self.cfg.get("colors") or {}
        return {str(k): str(v) for k, v in c.items()} if isinstance(c, dict) else {}

    @property
    def engine(self) -> str:
        """'gl' for scene files written for ManimGL (`from manimlib import *`), else 'ce'."""
        return "gl" if re.search(r"(?m)^\s*(from|import)\s+manimlib\b", self.source) else "ce"

    def build_dir(self) -> Path:
        return self.dir / "build"

    def tree(self) -> ast.Module:
        try:
            return ast.parse(self.source, filename=str(self.file))
        except SyntaxError as e:
            raise ShowtimeError("%s line %s: %s" % (self.file.name, e.lineno, e.msg),
                                why="the scene file is not valid Python", hint="fix that line, then run the command again")

    def classes(self) -> Dict[str, ast.ClassDef]:
        return {n.name: n for n in self.tree().body if isinstance(n, ast.ClassDef)}

    def scene_classes(self) -> List[str]:
        """Scene classes in file order: they (or an in-file ancestor) derive from a *Scene base.
        Classes only used as a base for other in-file classes are left out."""
        cls = self.classes()

        def base_names(c: ast.ClassDef) -> List[str]:
            out = []
            for b in c.bases:
                if isinstance(b, ast.Name):
                    out.append(b.id)
                elif isinstance(b, ast.Attribute):
                    out.append(b.attr)
            return out

        def is_scene(name: str, seen: Set[str]) -> bool:
            if name in seen:
                return False
            seen.add(name)
            c = cls.get(name)
            if c is None:
                return name.endswith("Scene")
            return any(is_scene(b, seen) for b in base_names(c))

        used_as_base = {b for c in cls.values() for b in base_names(c) if b in cls}
        return [n for n in cls if not n.startswith("_") and n not in used_as_base and is_scene(n, set())]

    def scene_like_classes(self) -> Set[str]:
        """Every top-level class that is a scene or derives from one (scene bases included)."""
        cls = self.classes()
        memo: Dict[str, bool] = {}

        def is_scene(name: str, seen: Set[str]) -> bool:
            if name in memo:
                return memo[name]
            if name in seen:
                return False
            seen.add(name)
            c = cls.get(name)
            if c is None:
                return name.endswith("Scene")
            bases = [b.id if isinstance(b, ast.Name) else b.attr for b in c.bases
                     if isinstance(b, (ast.Name, ast.Attribute))]
            memo[name] = any(is_scene(b, seen) for b in bases)
            return memo[name]

        return {n for n in cls if is_scene(n, set())}

    def scenes(self, wanted: Optional[List[str]] = None) -> List[str]:
        found = self.scene_classes()
        order = wanted or self.cfg.get("scenes") or found
        missing = [s for s in order if s not in self.classes()]
        if missing:
            raise ShowtimeError("scene %s is not in %s" % (", ".join(missing), self.file.name),
                                why="scene classes found: %s" % (", ".join(found) or "none"),
                                hint="check the name (case matters) or the \"scenes\" list in manim.json")
        if not order:
            raise ShowtimeError("no scene classes in %s" % self.file.name,
                                why="a scene is a class deriving from ShowScene (or any manim Scene)",
                                hint="start from a template: showtime manim new <dir>")
        return list(order)

    # ------------------------------------------------------------- AST facts per scene
    def _ancestry(self, name: str) -> List[ast.ClassDef]:
        cls = self.classes()
        out: List[ast.ClassDef] = []
        todo = [name]
        seen: Set[str] = set()
        while todo:
            n = todo.pop()
            if n in seen or n not in cls:
                continue
            seen.add(n)
            out.append(cls[n])
            for b in cls[n].bases:
                if isinstance(b, ast.Name):
                    todo.append(b.id)
        return out

    def string_calls(self, name: str, methods: Tuple[str, ...]) -> List[Tuple[str, str, int]]:
        """(method, first string argument or until=..., line) for calls like self.beat("x") in a scene."""
        out = []
        for c in self._ancestry(name):
            for node in ast.walk(c):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                meth = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                if meth not in methods:
                    continue
                val = None
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    val = node.args[0].value
                for kw in node.keywords:
                    if kw.arg in ("until", "cue") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        val = kw.value.value
                if val is not None:
                    out.append((meth, val, node.lineno))
        return out

    def beats_of(self, name: str) -> List[str]:
        return [v for m, v, _ in self.string_calls(name, ("beat",))]

    def cache_key(self, name: str, settings: Dict[str, Any], cues: Optional[Dict[str, Any]], kit_hash: str) -> str:
        """Hash of everything that changes this scene's pixels (see references/manim.md, caching)."""
        h = hashlib.sha256()
        src = self.source
        tree = self.tree()
        scene_like = self.scene_like_classes()
        for node in tree.body:
            # every top-level statement except other scenes: helpers, constants and non-scene classes
            # (a layout class, a custom mobject) change this scene's pixels too
            if not (isinstance(node, ast.ClassDef) and node.name in scene_like):
                h.update((ast.get_source_segment(src, node) or "").encode("utf-8"))
        for c in self._ancestry(name):
            h.update((ast.get_source_segment(src, c) or "").encode("utf-8"))
        h.update(name.encode("utf-8"))
        for p in sorted(self.dir.rglob("*")):
            rel = p.relative_to(self.dir)
            if any(part in SKIP_DIRS for part in rel.parts[:-1]) or (rel.parts and rel.parts[0] in SKIP_DIRS):
                continue
            if not p.is_file() or p == self.file or p.name == PROJECT_FILE:
                continue
            st = p.stat()
            h.update(("%s:%d:%d" % (rel.as_posix(), st.st_size, int(st.st_mtime))).encode("utf-8"))
        h.update(json.dumps(settings, sort_keys=True, default=str).encode("utf-8"))
        h.update(kit_hash.encode("utf-8"))
        if cues:
            beats = set(self.beats_of(name))
            cue_calls = self.string_calls(name, ("at", "fit", "cue_time"))
            if beats:
                ids = [ln["id"] for ln in cues["lines"]]
                keep = [ln for ln in cues["lines"] if ln["id"] in beats]
                first = min((ids.index(b) for b in beats if b in ids), default=0)
                h.update(json.dumps({"lines": keep, "first": first, "fps": cues.get("fps")}, sort_keys=True).encode())
            elif cue_calls:
                h.update(json.dumps(cues, sort_keys=True).encode("utf-8"))
        return h.hexdigest()


def kit_hash(lib_dir: Path, manim_version: str = "") -> str:
    """Version of the scene kit (its sources) plus the engine version: part of every cache key."""
    h = hashlib.sha256(manim_version.encode("utf-8"))
    for p in sorted((lib_dir / "st_manim").glob("*.py")):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    h.update((lib_dir / "st" / "manim_run" / "palette.py").read_bytes())
    return h.hexdigest()[:16]
