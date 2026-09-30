"""Run a Python frame generator for `showtime adopt` (stdlib only; runs under the script's own Python).

A model asked for a video with no tools often writes a Python script that draws every frame
(Pillow, numpy, cairo, matplotlib ...) and pipes them to ffmpeg. This harness runs such a script
in a separate process, on the copy `showtime adopt` made, and talks JSON on stderr's last line /
raw frames on stdout:

  inspect <script>                          what the script defines (JSON on stdout)
  frames  <script> --fn F --unit s|frame --fps N --size WxH --from A --to B [--workers N]
                                            raw RGB24 frames A..B-1 on stdout, in order
  hash    <script> --fn F --unit s|frame --fps N --size WxH --frames 0,40,80
                                            each frame twice, in two orders: JSON with sha256 per pass
  run     <script> [args...]                the script's own main, as `python script.py` would

Guard rails (not an OS jail): the working directory is the script's folder in the copy, sockets
to anything but this machine are refused inside the Python process, and the caller enforces a
wall-clock limit. The original folder is never touched: `showtime adopt` copies it first.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import socket
import sys
import time
import traceback

FN_NAMES = ["render", "render_frame", "draw", "draw_frame", "make_frame", "frame", "get_frame", "frame_at",
            "render_at", "compose", "compose_frame", "paint", "paint_frame", "build_frame", "generate_frame", "scene"]
FRAME_PARAMS = {"i", "n", "f", "fi", "idx", "index", "frame", "frame_no", "frame_index", "frame_idx", "k", "fn", "num"}
TIME_PARAMS = {"t", "time", "ts", "sec", "secs", "seconds", "tt", "now", "t_s"}
W_NAMES = ["W", "WIDTH", "VIDEO_W", "VIDEO_WIDTH", "OUT_W", "FRAME_W", "w"]
H_NAMES = ["H", "HEIGHT", "VIDEO_H", "VIDEO_HEIGHT", "OUT_H", "FRAME_H", "h"]
FPS_NAMES = ["FPS", "fps", "FRAME_RATE", "FRAMERATE", "RATE", "R"]
DUR_NAMES = ["DURATION", "DUR", "TOTAL", "TOTAL_DURATION", "LENGTH", "T_TOTAL", "TOTAL_TIME", "VIDEO_DURATION", "duration", "END", "T_END"]
FRAMES_NAMES = ["N_FRAMES", "NFRAMES", "FRAMES", "TOTAL_FRAMES", "NUM_FRAMES", "FRAME_COUNT"]
SIZE_NAMES = ["SIZE", "RES", "RESOLUTION", "FRAME_SIZE"]


def _is_local(host) -> bool:
    h = str(host or "").strip("[]").lower()
    return h in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "") or h.startswith("127.")


def block_network() -> None:
    """Refuse connections to other machines from inside this process (and say so)."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_gai = socket.getaddrinfo

    def _addr_host(addr):
        return addr[0] if isinstance(addr, tuple) and addr else addr

    def connect(self, addr):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(_addr_host(addr)):
            raise PermissionError("showtime adopt: network access is blocked for adopted scripts (%s)" % (_addr_host(addr),))
        return real_connect(self, addr)

    def connect_ex(self, addr):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(_addr_host(addr)):
            raise PermissionError("showtime adopt: network access is blocked for adopted scripts (%s)" % (_addr_host(addr),))
        return real_connect_ex(self, addr)

    def getaddrinfo(host, *a, **k):
        if not _is_local(host):
            raise PermissionError("showtime adopt: network access is blocked for adopted scripts (%s)" % (host,))
        return real_gai(host, *a, **k)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


# ---------------------------------------------------------------------------------------- static scan
def _num(node):
    try:
        v = ast.literal_eval(node)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (tuple, list)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return list(v)
    return None


def static_scan(path: str) -> dict:
    src = open(path, encoding="utf-8", errors="replace").read()
    out = {"main_guard": False, "functions": [], "constants": {}, "ffmpeg": [], "imports": [], "loop_calls": [],
           "prints_wrote": False, "argv": "sys.argv" in src}
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        out["syntax_error"] = "%s (line %s)" % (e.msg, e.lineno)
        return out
    for node in tree.body:
        if isinstance(node, ast.If):
            t = node.test
            if isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__":
                out["main_guard"] = True
        elif isinstance(node, ast.FunctionDef):
            args = [a.arg for a in node.args.args]
            required = len(args) - len(node.args.defaults)
            out["functions"].append({"name": node.name, "args": args, "required": required, "line": node.lineno})
        elif isinstance(node, ast.Assign):
            v = _num(node.value)
            for tg in node.targets:
                if isinstance(tg, ast.Name) and v is not None:
                    out["constants"][tg.id] = v
                elif isinstance(tg, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    for n2, v2 in zip(tg.elts, node.value.elts):
                        vv = _num(v2)
                        if isinstance(n2, ast.Name) and vv is not None:
                            out["constants"][n2.id] = vv
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            out["imports"] += [m.split(".")[0] for m in mods if m]
    fnames = {f["name"] for f in out["functions"]}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # ffmpeg command lines written as lists
            for a in node.args:
                if isinstance(a, ast.List) and a.elts and isinstance(a.elts[0], ast.Constant) and \
                        str(a.elts[0].value).endswith(("ffmpeg", "ffmpeg.exe")):
                    out["ffmpeg"].append([e.value if isinstance(e, ast.Constant) else "?" for e in a.elts][:60])
            # frame calls inside write(...) / imap(fn, ...) / map(fn, ...)
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("write", "imap", "map", "imap_unordered", "starmap", "append"):
                for a in node.args:
                    for sub in ast.walk(a):
                        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in fnames:
                            out["loop_calls"].append(sub.func.id)
                        elif isinstance(sub, ast.Name) and sub.id in fnames and f.attr != "write":
                            out["loop_calls"].append(sub.id)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.match(r"(?i)^(wrote|saved|written)\b", node.value):
            out["prints_wrote"] = True
    out["loop_calls"] = sorted(set(out["loop_calls"]))
    return out


# ------------------------------------------------------------------------------------ module loading
_MOD = None


def load(script: str):
    """Import the script as a module (its main guard keeps main() from running)."""
    global _MOD
    if _MOD is not None:
        return _MOD
    script = os.path.abspath(script)
    d = os.path.dirname(script)
    os.chdir(d)
    if d not in sys.path:
        sys.path.insert(0, d)
    sys.argv = [script]
    spec = importlib.util.spec_from_file_location("adopted_script", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["adopted_script"] = mod
    spec.loader.exec_module(mod)
    _MOD = mod
    return mod


def first(mod, names):
    for n in names:
        v = getattr(mod, n, None)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return n, v
    return None, None


def to_rgb(img, size):
    """PIL image, numpy array, bytes or a (W,H,3) nested list -> RGB24 bytes of size WxH."""
    w, h = size
    if hasattr(img, "convert") and hasattr(img, "size") and hasattr(img, "tobytes"):
        if tuple(img.size) != (w, h):
            raise ValueError("frame is %dx%d, expected %dx%d" % (img.size[0], img.size[1], w, h))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img.tobytes()
    if hasattr(img, "shape") and hasattr(img, "tobytes"):
        shp = tuple(img.shape)
        if len(shp) != 3 or shp[0] != h or shp[1] != w or shp[2] not in (3, 4):
            raise ValueError("frame array has shape %s, expected (%d, %d, 3)" % (shp, h, w))
        a = img
        if str(getattr(a, "dtype", "uint8")) != "uint8":
            import numpy as np  # the script already uses numpy
            a = np.clip(a * (255.0 if float(a.max() if a.size else 0) <= 1.0 else 1.0), 0, 255).astype("uint8")
        if shp[2] == 4:
            a = a[:, :, :3]
        return a.tobytes() if getattr(a, "flags", None) is None or a.flags["C_CONTIGUOUS"] else a.copy(order="C").tobytes()
    if isinstance(img, (bytes, bytearray, memoryview)):
        b = bytes(img)
        if len(b) == w * h * 3:
            return b
        if len(b) == w * h * 4:
            return bytes(bytearray(b[i] for i in range(len(b)) if i % 4 != 3))
        raise ValueError("frame has %d bytes, expected %d (RGB %dx%d)" % (len(b), w * h * 3, w, h))
    raise ValueError("frame function returned %s, not an image, an array or bytes" % type(img).__name__)


def guess_size(img):
    if hasattr(img, "size") and hasattr(img, "convert"):
        return list(img.size)
    if hasattr(img, "shape") and len(getattr(img, "shape", ())) == 3:
        return [int(img.shape[1]), int(img.shape[0])]
    return None


def inspect(script: str) -> dict:
    info = {"static": static_scan(script)}
    st = info["static"]
    if st.get("syntax_error"):
        return info
    if not st["main_guard"]:
        info["import_safe"] = False
        return info
    info["import_safe"] = True
    t0 = time.time()
    try:
        mod = load(script)
    except BaseException as e:  # noqa: BLE001
        info["import_error"] = "%s: %s" % (type(e).__name__, e)
        info["import_trace"] = traceback.format_exc()[-1500:]
        return info
    info["import_s"] = round(time.time() - t0, 3)
    nums = {}
    for group in (W_NAMES, H_NAMES, FPS_NAMES, DUR_NAMES, FRAMES_NAMES):
        n, v = first(mod, group)
        if n:
            nums[n] = v
    for n in SIZE_NAMES:
        v = getattr(mod, n, None)
        if isinstance(v, (tuple, list)) and len(v) == 2 and all(isinstance(x, int) for x in v):
            nums[n] = list(v)
    info["numbers"] = nums
    cands = []
    for f in st["functions"]:
        if f["required"] != 1:
            continue
        name = f["name"]
        score = 0
        if name in FN_NAMES:
            score += 10 - FN_NAMES.index(name) * 0.1
        if name in st["loop_calls"]:
            score += 20
        if name.startswith("_") or name in ("main", "clamp", "ease", "lerp", "font", "mix"):
            score -= 30
        p = f["args"][0]
        unit = "frame" if p in FRAME_PARAMS else ("s" if p in TIME_PARAMS else None)
        if unit:
            score += 3
        if score >= 10:   # a known frame-function name, or called where the frames are written
            cands.append({"name": name, "param": p, "unit": unit or "s", "score": score, "line": f["line"]})
    cands.sort(key=lambda c: -c["score"])
    info["candidates"] = cands
    tried = []
    for c in cands[:4]:
        fn = getattr(mod, c["name"], None)
        if not callable(fn):
            continue
        try:
            t1 = time.time()
            img = fn(0)
            ms = (time.time() - t1) * 1000
        except BaseException as e:  # noqa: BLE001
            tried.append({"name": c["name"], "error": "%s: %s" % (type(e).__name__, str(e)[:300])})
            continue
        size = guess_size(img)
        kind = type(img).__module__.split(".")[0] + "." + type(img).__name__
        if isinstance(img, (bytes, bytearray)):
            size = None
            kind = "bytes(%d)" % len(img)
        tried.append({"name": c["name"], "returns": kind, "size": size, "ms": round(ms, 1)})
        if size or isinstance(img, (bytes, bytearray)):
            info["fn"] = dict(c, returns=kind, size=size, ms=round(ms, 1), nbytes=len(img) if isinstance(img, (bytes, bytearray)) else None)
            break
    info["tried"] = tried
    return info


# ------------------------------------------------------------------------------------ frame output
def _call(fn, unit, fps, k):
    return fn(k if unit == "frame" else k / float(fps))


_W = {}


def _winit(script, fn, unit, fps, size, net):
    if net:
        block_network()
    mod = load(script)
    _W.update(fn=getattr(mod, fn), unit=unit, fps=fps, size=size)


def _wframe(k):
    return to_rgb(_call(_W["fn"], _W["unit"], _W["fps"], k), _W["size"])


def frames(script, fn, unit, fps, size, a, b, workers, net=True):
    out = sys.stdout.buffer
    if workers <= 1 or b - a < 8:
        _winit(script, fn, unit, fps, size, net)
        for k in range(a, b):
            out.write(_wframe(k))
        out.flush()
        return
    import multiprocessing as mp
    ctx = mp.get_context("fork" if sys.platform.startswith("linux") else "spawn")
    with ctx.Pool(workers, initializer=_winit, initargs=(os.path.abspath(script), fn, unit, fps, size, net)) as pool:
        for buf in pool.imap(_wframe, range(a, b), chunksize=2):
            out.write(buf)
    out.flush()


def hashes(script, fn, unit, fps, size, ks):
    _winit(script, fn, unit, fps, size, True)
    first_pass = [hashlib.sha256(_wframe(k)).hexdigest() for k in ks]
    second = {}
    for k in reversed(ks):   # the other order: every frame is now reached after different ones
        second[k] = hashlib.sha256(_wframe(k)).hexdigest()
    return {"frames": ks, "pass1": first_pass, "pass2": [second[k] for k in ks]}


def run_main(script, args):
    script = os.path.abspath(script)
    os.chdir(os.path.dirname(script))
    sys.path.insert(0, os.path.dirname(script))
    sys.argv = [script] + list(args)
    import runpy
    runpy.run_path(script, run_name="__main__")


def _opts(argv):
    o, pos, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and i + 1 < len(argv):
            o[a[2:]] = argv[i + 1]
            i += 2
        else:
            pos.append(a)
            i += 1
    return o, pos


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    cmd, script, rest = argv[0], argv[1], argv[2:]
    if cmd == "run":
        if os.environ.get("SHOWTIME_ADOPT_NET") != "1":
            block_network()
        run_main(script, rest)
        return 0
    if os.environ.get("SHOWTIME_ADOPT_NET") != "1":
        block_network()
    if cmd == "inspect":
        sys.stdout.write(json.dumps(inspect(script)))
        return 0
    o, _ = _opts(rest)
    size = [int(x) for x in o["size"].lower().split("x")]
    fps = float(o.get("fps", 30))
    if cmd == "frames":
        frames(script, o["fn"], o.get("unit", "s"), fps, size, int(o["from"]), int(o["to"]), int(o.get("workers", 1)))
        return 0
    if cmd == "hash":
        ks = [int(x) for x in o["frames"].split(",") if x != ""]
        sys.stdout.write(json.dumps(hashes(script, o["fn"], o.get("unit", "s"), fps, size, ks)))
        return 0
    sys.stderr.write("unknown command %s\n" % cmd)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:
        sys.exit(0)
