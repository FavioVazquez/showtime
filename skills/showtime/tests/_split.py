"""Split a long test file into parts that run as separate processes (run_all.py on machines with many cores).

A part is a set of test ids ("Class.test_method"). tests/_part.py runs one part of a file: it loads the file's
tests the normal way (unittest) and keeps the ids of its part, so nothing is lost if this scan misses a test
(a test the plan does not know runs in part 1). Each part is a whole process with its own TMPDIR, scratch
folder and class fixtures (setUpClass runs once per part that has tests of that class).

Which files split, and how finely, is declared in SPLIT. Tests that share state stay in one part; the scan
finds the usual ways they do:
  - a test stores a result on the class (`type(self).x = ...`, `self.__class__.x = ...`) that another reads
  - two tests use the same scratch path (`self.tmp / "canvas"`, `TMP / "sheet"`)
  - a test calls another (`self.test_03_sfx()`) or skips without it (`self.skipTest("needs test_05")`)
and KEEP_TOGETHER lists what the scan cannot see. Stdlib only.
"""
from __future__ import annotations

import ast
import math
import re
from pathlib import Path

# file -> "methods": each test method may run in its own part (coupled methods stay together);
#         "classes": whole TestCase classes per part (their tests share class state the scan cannot see)
# A file not listed here always runs whole. A file in run_all.SERIAL never splits.
SPLIT = {
    "test_render.py": "methods",
    "test_capture.py": "methods",
    "test_audio.py": "methods",
    "test_qa.py": "methods",
    "test_footage.py": "methods",
    "test_motion.py": "methods",
    "test_voice.py": "methods",
    "test_foundation.py": "classes",
    "test_manim.py": "classes",
    "test_mcp.py": "classes",
}
# (not listed: test_job.py - its tests build on the jobs test_01 leaves in the class's repo folder;
#  test_studio.py - one studio server for the class, stopped and restarted by its tests; test_export.py - SERIAL)
# classes whose tests share state through a folder they all work in (not visible to the scan): never split
WHOLE_CLASSES = {
    "test_footage.py": ["LatestRenderTest"],     # every command runs with cwd = the class's folder
}
# most parts per file; each part repeats the module import and the class setup
DEFAULT_MAX_PARTS = 8
MAX_PARTS = {
    "test_footage.py": 4,     # FootageTest.setUpClass speaks a clip and encodes a video; the transcript is
                              # made on first use in each part
}
# {file: [[ids that must share a process], ...]} for couplings the scan does not find
KEEP_TOGETHER: dict = {}
# a part shorter than this is not worth a process of its own
MIN_PART_SECONDS = 12.0


# ------------------------------------------------------------------ reading a test file

class FileTests:
    """The unittest test ids of one file and the groups of ids that must run in the same process."""

    def __init__(self, path: Path, mode: str = "methods", text: str = None, keep_together=(), whole_classes=()):
        self.path = Path(path)
        self.name = self.path.name
        src = text if text is not None else self.path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        self.classes = _test_classes(tree)                     # {class: [test methods]}, inherited included
        self.ids = sorted("%s.%s" % (c, m) for c, ms in self.classes.items() for m in ms)
        self._parent = {i: i for i in self.ids}
        for c, ms in self.classes.items():
            if mode == "classes" or c in whole_classes:
                self._join_all(["%s.%s" % (c, m) for m in ms])
        for group in _couplings(tree, self.classes):
            self._join_all(group)
        for group in keep_together:
            self._join_all([i for i in group if i in self._parent])

    def _find(self, i):
        while self._parent[i] != i:
            self._parent[i] = self._parent[self._parent[i]]
            i = self._parent[i]
        return i

    def _join_all(self, ids):
        ids = [i for i in ids if i in self._parent]
        for a in ids[1:]:
            ra, rb = self._find(ids[0]), self._find(a)
            if ra != rb:
                self._parent[max(ra, rb)] = min(ra, rb)

    def units(self) -> list:
        """Groups of ids that must share a process, each sorted, in a stable order."""
        groups: dict = {}
        for i in self.ids:
            groups.setdefault(self._find(i), []).append(i)
        return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def file_tests(path: Path) -> FileTests:
    """FileTests of a file listed in SPLIT, with its declared couplings."""
    name = Path(path).name
    return FileTests(path, SPLIT.get(name, "classes"), keep_together=KEEP_TOGETHER.get(name, ()),
                     whole_classes=WHOLE_CLASSES.get(name, ()))


def _base_name(b) -> str:
    if isinstance(b, ast.Name):
        return b.id
    if isinstance(b, ast.Attribute):
        return b.attr
    return ""


def _test_classes(tree) -> dict:
    defs = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    def is_case(name, seen=()):
        node = defs.get(name)
        if node is None or name in seen:
            return False
        for b in node.bases:
            bn = _base_name(b)
            if bn.endswith("TestCase") and bn not in defs:
                return True
            if bn in defs and is_case(bn, seen + (name,)):
                return True
        return False

    def methods(name, seen=()):
        node = defs.get(name)
        if node is None or name in seen:
            return set()
        own = {f.name for f in node.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
               and f.name.startswith("test")}
        for b in node.bases:
            own |= methods(_base_name(b), seen + (name,))
        return own

    return {c: sorted(methods(c)) for c in defs if is_case(c) and methods(c)}


def _scratch_names(tree) -> set:
    """Module-level names that hold a per-process scratch folder (TMP = Path(tempfile.mkdtemp()), and names
    built from one: SITE = TMP / "site")."""
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = node.value
            dump = ast.dump(v)
            base = v
            while isinstance(base, ast.BinOp) and isinstance(base.op, ast.Div):
                base = base.left
            if "mkdtemp" in dump or (isinstance(base, ast.Name) and base.id in out):
                out.add(node.targets[0].id)
    return out


def _self_attr(node):
    """'x' for self.x, cls.x, self.__class__.x, type(self).x; else None."""
    if not isinstance(node, ast.Attribute):
        return None
    v = node.value
    if isinstance(v, ast.Name) and v.id in ("self", "cls"):
        return node.attr
    if isinstance(v, ast.Attribute) and v.attr == "__class__" and isinstance(v.value, ast.Name) and v.value.id == "self":
        return node.attr
    if isinstance(v, ast.Call) and _base_name(v.func) == "type" and v.args and isinstance(v.args[0], ast.Name) \
            and v.args[0].id == "self":
        return node.attr
    return None


def _class_holder(node) -> bool:
    """self.__class__ / type(self) / cls: where a test stores a result for later tests."""
    if isinstance(node, ast.Name) and node.id == "cls":
        return True
    if isinstance(node, ast.Attribute) and node.attr == "__class__" and isinstance(node.value, ast.Name) \
            and node.value.id == "self":
        return True
    return isinstance(node, ast.Call) and _base_name(node.func) == "type" and bool(node.args) \
        and isinstance(node.args[0], ast.Name) and node.args[0].id == "self"


def _couplings(tree, classes: dict) -> list:
    """Groups of ids that must share a process (see the module docstring)."""
    scratch = _scratch_names(tree)
    defs = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    groups = []
    shared_paths: dict = {}                    # (base, first name) -> ids
    for cname, methods in classes.items():
        writers: dict = {}
        readers: dict = {}
        funcs = {}
        seen_cls = set()

        def collect(cn):
            node = defs.get(cn)
            if node is None or cn in seen_cls:
                return
            seen_cls.add(cn)
            for f in node.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith("test"):
                    funcs.setdefault(f.name, f)
            for b in node.bases:
                collect(_base_name(b))

        collect(cname)
        for m in methods:
            f = funcs.get(m)
            if f is None:
                continue
            tid = "%s.%s" % (cname, m)
            for node in ast.walk(f):
                # results stored on the class
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Attribute) and _class_holder(t.value):
                            writers.setdefault(t.attr, set()).add(tid)
                elif isinstance(node, ast.Call) and _base_name(node.func) in ("setattr", "getattr", "hasattr") \
                        and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                        and isinstance(node.args[1].value, str):
                    holder = node.args[0]
                    if _class_holder(holder) or (isinstance(holder, ast.Name) and holder.id == "self"):
                        d = writers if _base_name(node.func) == "setattr" else readers
                        d.setdefault(node.args[1].value, set()).add(tid)
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                    a = _self_attr(node)
                    if a:
                        readers.setdefault(a, set()).add(tid)
                # one test calls another, or skips when another has not run
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr.startswith("test") and _self_attr(node.func) is not None:
                    groups.append([tid, "%s.%s" % (cname, node.func.attr)])
                if isinstance(node, ast.Call) and _base_name(node.func) == "skipTest":
                    for s in (a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)):
                        for want in _named_tests(s):
                            groups.append([tid] + ["%s.%s" % (cname, x) for x in methods
                                                   if x == want or x.startswith(want + "_")])
                # the same scratch path
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) \
                        and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
                    left = node.left
                    key = None
                    a = _self_attr(left)
                    if a:
                        key = ("attr", a, node.right.value)
                    elif isinstance(left, ast.Name) and left.id in scratch:
                        key = ("name", left.id, node.right.value)
                    if key:
                        shared_paths.setdefault(key if key[0] == "name" else (cname,) + key, set()).add(tid)
        for attr, ws in writers.items():
            groups.append(sorted(ws | readers.get(attr, set())))
    for ids in shared_paths.values():
        if len(ids) > 1:
            groups.append(sorted(ids))
    return groups


def _named_tests(s: str) -> list:
    return re.findall(r"\b(test_\w+)", s)


# ------------------------------------------------------------------ planning parts

def part_count(est_seconds: float, target: float, n_units: int, max_parts: int) -> int:
    if n_units < 2 or est_seconds <= 0 or target <= 0:
        return 1
    return max(1, min(max_parts, n_units, int(math.ceil(est_seconds / target - 1e-9))))


def assign(units: list, weights: dict, n: int) -> list:
    """Units (lists of ids) into n parts: heaviest first, each into the currently lightest part (ties: the
    lower-numbered part). -> [[ids], ...] (no empty part), each part's ids sorted."""
    w = lambda u: sum(weights.get(i, 0.0) for i in u)  # noqa: E731
    parts, loads = [[] for _ in range(n)], [0.0] * n
    for u in sorted(units, key=lambda u: (-w(u), u[0])):
        k = min(range(n), key=lambda j: (loads[j], j))
        parts[k].extend(u)
        loads[k] += w(u)
    return [sorted(p) for p in parts if p]


def test_weights(ft: FileTests, file_seconds: float, times: dict, mode: str) -> dict:
    """Seconds per test id: the recorded time of each test ("<mode>:<file>::<id>" in the timing cache), else
    an even share of the file's time."""
    rec = {i: times.get("%s:%s::%s" % (mode, ft.name, i)) for i in ft.ids}
    known = {i: float(v) for i, v in rec.items() if isinstance(v, (int, float))}
    missing = [i for i in ft.ids if i not in known]
    if missing:
        rest = max(0.0, file_seconds - sum(known.values())) if known else file_seconds
        share = rest / len(missing) if rest > 0 else (file_seconds / max(1, len(ft.ids)))
        for i in missing:
            known[i] = share
    return known
