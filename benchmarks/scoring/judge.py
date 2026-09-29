"""Call a blind LLM judge through headless Claude Code (same credential path as the runs).

The judge runs in its own empty config dir and HOME, with only the Read tool, inside a packet folder
that holds nothing but anonymised images and text. It must answer with JSON matching a schema
(--json-schema); the parsed object is returned.
"""
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import arms as armlib  # noqa: E402
import common  # noqa: E402

JUDGE_MODEL = os.environ.get("BENCH_JUDGE_MODEL", "claude-opus-5-5")


def _env(tmp: Path) -> Dict[str, str]:
    base = common.bench_home() / "judge"
    cfg, home = base / "cfg", base / "home"
    for p in (cfg, home, tmp):
        p.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in armlib.PASS_ENV if k in os.environ}
    env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(cfg), "TMPDIR": str(tmp),
                "PATH": os.pathsep.join(armlib.SYSTEM_DIRS) or os.environ.get("PATH", ""),
                "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "DISABLE_AUTOUPDATER": "1"})
    env.update(armlib.auth_env())
    return env


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
# what a judge writes when it ranked without looking (it has only the Read tool: no listing)
BLIND_RE = re.compile(r"(could ?n[o']?t|could not|can ?not|can't|unable to|no way to|did not|didn't|failed to)\s+"
                      r"(open|see|view|find|read|list|load|access)[^.]{0,60}\b(images?|frames?|stills?|pictures?|contact sheets?)",
                      re.I)


def frame_list(packet: Path) -> List[str]:
    """Every image in the packet, relative to it (posix), in folder then name order."""
    return sorted(p.relative_to(packet).as_posix() for p in packet.rglob("*")
                  if p.is_file() and p.suffix.lower() in IMAGE_EXT and ".tmp" not in p.parts)


def frames_prompt(packet: Path) -> str:
    """The exact image paths (a judge with only Read cannot list folders and must not guess names)."""
    files = frame_list(packet)
    if not files:
        return "There are no frame images in this packet."
    lines = []
    for f in files:
        idx = packet / Path(f).parent / "INDEX.txt"
        label = ""
        if idx.is_file():
            for ln in idx.read_text(encoding="utf-8").splitlines():
                if ln.startswith(Path(f).name + " "):
                    label = "  (" + ln.split(" ", 1)[1].strip() + ")"
        lines.append("  " + f + label)
    return ("Open EVERY one of these images with the Read tool, using exactly these paths (relative to the "
            "current folder), before you score anything:\n" + "\n".join(lines))


# ---------------------------------------------------------------- proof that the judge looked at the pictures
# Two independent proofs, both required for a judgment to count:
#   1. the session's own tool calls: every image in the packet was opened with Read (the stream is parsed,
#      not the judge's word), and
#   2. a reading check: every image carries a black strip at the bottom with a random 5-digit number that
#      exists nowhere else (not in the file name, not in any text file). The judge must report the number of
#      each image it opened in `frame_codes`; a number can only be known from the pixels. The strip is added
#      to every image of every candidate alike, so it cannot favour anyone.
# A judgment that fails either proof is discarded and asked again in a fresh session (ask_verified).
GLYPHS = {  # 5 x 7 digit bitmaps
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": (".###.", "#...#", "....#", "..##.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
}
CODE_LEN = 5
GLYPH_SCALE = 6
STRIP_MARGIN = 8
STRIP_H = 7 * GLYPH_SCALE + 2 * STRIP_MARGIN


def code_png(code: str, scale: int = GLYPH_SCALE, margin: int = STRIP_MARGIN) -> bytes:
    """White digits on black as a grayscale PNG (stdlib only)."""
    cell = 6 * scale
    w, h = len(code) * cell + 2 * margin, 7 * scale + 2 * margin
    rows = [bytearray(w) for _ in range(h)]
    for i, ch in enumerate(code):
        for gy, line in enumerate(GLYPHS[ch]):
            for gx, c in enumerate(line):
                if c == "#":
                    for dy in range(scale):
                        row = rows[margin + gy * scale + dy]
                        x0 = margin + i * cell + gx * scale
                        row[x0:x0 + scale] = b"\xff" * scale
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def new_codes(files: List[str], rng: random.Random) -> Dict[str, str]:
    """A distinct random number per image."""
    out: Dict[str, str] = {}
    used = set()
    for f in files:
        while True:
            c = "".join(rng.choice("0123456789") for _ in range(CODE_LEN))
            if c not in used and c[0] != "0":
                used.add(c)
                out[f] = c
                break
    return out


def stamp_packet(packet: Path, rng: Optional[random.Random] = None) -> Dict[str, str]:
    """Add the reading-check strip to every image of the packet (in place: the packet holds copies).
    Returns {relative path: number}. The numbers are only kept by the caller, never written into the packet."""
    files = frame_list(packet)
    codes = new_codes(files, rng or random.Random())
    tmp = packet / ".stamp"
    tmp.mkdir(exist_ok=True)
    try:
        for f, code in codes.items():
            src = packet / f
            png = tmp / "code.png"
            png.write_bytes(code_png(code))
            out = tmp / ("out" + src.suffix.lower())
            args = [common.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-i", str(png),
                    "-filter_complex", "[0:v]pad=iw:ih+%d:0:0:color=black[a];[a][1:v]overlay=0:H-h" % STRIP_H,
                    "-frames:v", "1"]
            if src.suffix.lower() in (".jpg", ".jpeg"):
                args += ["-q:v", "3"]
            r = common.run(args + [str(out)])
            if r.returncode != 0 or not out.exists():
                raise RuntimeError("could not stamp %s: %s" % (f, (r.stderr or "")[-300:]))
            out.replace(src)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return codes


CODES_PROMPT = """
Reading check (required): every image has a black strip at the bottom with a white 5-digit number. It is
not part of the video; ignore it when you judge. For EVERY image you opened, copy its number into
frame_codes as {"file": "<the path exactly as listed>", "code": "<the 5 digits>"}. A judgment without the
correct number for each image is discarded and you will be asked again."""

CODES_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "file": {"type": "string"}, "code": {"type": "string"}}, "required": ["file", "code"]}}


def with_codes(schema: Dict) -> Dict:
    """The judge's schema plus the required frame_codes list."""
    s = json.loads(json.dumps(schema))
    s["properties"]["frame_codes"] = CODES_SCHEMA
    s["required"] = list(s.get("required") or []) + ["frame_codes"]
    return s


def _norm(p: str) -> str:
    return Path(str(p).strip()).as_posix().lstrip("./")


def proof(res: Dict, packet: Path, codes: Optional[Dict[str, str]] = None) -> Dict:
    """What the judge demonstrably saw: images opened (from the tool calls) and numbers read correctly."""
    files = frame_list(packet)
    read = [_norm(x) for x in res.get("read") or []]
    opened = [f for f in files if any(r == f or r.endswith("/" + f) for r in read)]
    out = {"images_total": len(files), "images_opened": len(opened),
           "unopened": [f for f in files if f not in opened]}
    if codes is not None:
        said: Dict[str, str] = {}
        for it in (res.get("data") or {}).get("frame_codes") or []:
            if isinstance(it, dict):
                said[_norm(it.get("file") or "")] = re.sub(r"\D", "", str(it.get("code") or ""))
        right = [f for f in files if said.get(f) == codes.get(f)]
        out.update({"codes_total": len(codes), "codes_right": len(right), "said": said,
                    "codes_wrong": [f for f in codes if said.get(f) not in (None, codes[f])],
                    "codes_missing": [f for f in codes if f not in said]})
    return out


def check_seen(res: Dict, packet: Path, folders: List[str], codes: Optional[Dict[str, str]] = None) -> Optional[str]:
    """None when the judge verifiably looked at the frames, else why the judgment does not count.
    Fails when: it says it could not see them; it did not open EVERY image (from the session's own tool
    calls); or (when `codes` are given) it could not read the number on more than 10 percent of the images."""
    files = frame_list(packet)
    p = proof(res, packet, codes)
    data = res.get("data") or {}
    text = " ".join(str(data.get(k) or "") for k in ("reason", "notes"))
    if data.get("saw_frames") is False or BLIND_RE.search(text):
        return "the judge says it could not see the frame images"
    if files and p["images_opened"] < p["images_total"]:
        return "the judge opened %d of %d images (not opened: %s)" % (
            p["images_opened"], p["images_total"], ", ".join(p["unopened"][:6]))
    blind = [d for d in folders if any(f.startswith(d.rstrip("/") + "/") for f in files)
             and not any(f.startswith(d.rstrip("/") + "/") and f not in p["unopened"] for f in files)]
    if blind:
        return "the judge opened no frame image of %s" % ", ".join(blind)
    if codes is not None and codes:
        allowed = len(codes) // 10
        if p["codes_total"] - p["codes_right"] > allowed:
            return "the judge could not report the reading-check number of %d of %d images (wrong %d, missing %d)" % (
                p["codes_total"] - p["codes_right"], p["codes_total"], len(p["codes_wrong"]), len(p["codes_missing"]))
    return None


def ask_verified(build: Callable[[], Path], make_prompt: Callable[[Path], str], schema: Dict, folders: List[str],
                 attempts: int = 3, seed: Optional[str] = None, **kw) -> Tuple[Dict, List[Dict]]:
    """Build a packet, stamp it, ask, and require the proof; on a failed proof discard the judgment and ask again
    in a fresh session with a fresh packet and fresh numbers (up to `attempts` in all).
    Returns (final result, one log entry per attempt). The result has ok False and the reason in "error"
    when no attempt was verifiable."""
    log: List[Dict] = []
    res: Dict = {"ok": False, "error": "no attempt"}
    for i in range(max(1, attempts)):
        pk = build()
        rng = random.Random("%s/%d" % (seed, i)) if seed is not None else random.Random()
        codes = stamp_packet(pk, rng)
        res = ask(pk, make_prompt(pk) + "\n" + CODES_PROMPT, with_codes(schema), **kw)
        why = check_seen(res, pk, folders, codes) if res.get("ok") else None
        pr = proof(res, pk, codes)
        log.append({"attempt": i + 1, "ok": bool(res.get("ok")) and not why, "error": why or res.get("error"),
                    "cost_usd": res.get("cost_usd"), "images_total": pr["images_total"],
                    "images_opened": pr["images_opened"], "codes_total": pr.get("codes_total"),
                    "codes_right": pr.get("codes_right"),
                    "frame_codes": {f: {"true": c, "said": (pr.get("said") or {}).get(f)} for f, c in codes.items()}})
        if res.get("ok") and not why:
            break
        if res.get("ok") and why:
            res = dict(res, ok=False, error=why)
        if res.get("error") == "timeout":
            break
    return res, log


def ask(packet: Path, prompt: str, schema: Dict, budget_usd: float = 3.0, timeout_s: int = 900) -> Dict:
    """Run one judgment in `packet` (cwd). Returns {"ok", "data", "cost_usd", "read", "error"}.

    The session streams its events (stream-json), so the files it actually opened with Read are known
    ("read"): callers check that every video's frames were looked at (check_seen)."""
    args = [common.claude_bin(), "-p", prompt, "--model", JUDGE_MODEL, "--effort", "high",
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(schema),
            "--tools", "Read", "--permission-mode", "dontAsk", "--allowedTools", "Read",
            "--no-session-persistence", "--no-chrome", "--max-budget-usd", "%.2f" % budget_usd]
    tmp = packet / ".tmp"
    try:
        r = subprocess.run(args, cwd=str(packet), env=_env(tmp), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    res, read = None, []
    for line in (r.stdout or "").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "result":
            res = ev
        for block in ((ev.get("message") or {}).get("content") or []) if ev.get("type") == "assistant" else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read":
                fp = str((block.get("input") or {}).get("file_path") or "")
                if fp:
                    try:
                        fp = Path(fp).resolve().relative_to(packet.resolve()).as_posix()
                    except ValueError:
                        pass
                    read.append(fp)
    if res is None:
        return {"ok": False, "error": (r.stderr or r.stdout)[-600:], "read": read}
    data: Optional[Dict] = res.get("structured_output")
    if data is None:
        txt = res.get("result") or ""
        try:
            data = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        except ValueError:
            data = None
    return {"ok": data is not None and not res.get("is_error"), "data": data, "read": read,
            "cost_usd": res.get("total_cost_usd"), "error": None if data else (res.get("result") or "")[:400]}
