"""Call a blind LLM judge through headless Claude Code (same credential path as the runs).

The judge runs in its own empty config dir and HOME, with only the Read tool, inside a packet folder
that holds nothing but anonymised images and text. It must answer with JSON matching a schema
(--json-schema); the parsed object is returned.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

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


def check_seen(res: Dict, packet: Path, folders: List[str]) -> Optional[str]:
    """None when the judge verifiably looked at the frames, else why the judgment does not count: it read no
    image of some video (from the session's own tool calls), or it says it could not see them."""
    files = frame_list(packet)
    read = {Path(x).as_posix() for x in res.get("read") or []}
    seen = {f for f in files if any(r == f or r.endswith("/" + f) for r in read)}
    blind = [d for d in folders if any(f.startswith(d.rstrip("/") + "/") for f in files)
             and not any(f.startswith(d.rstrip("/") + "/") for f in seen)]
    data = res.get("data") or {}
    text = " ".join(str(data.get(k) or "") for k in ("reason", "notes"))
    if data.get("saw_frames") is False or BLIND_RE.search(text):
        return "the judge says it could not see the frame images"
    if blind:
        return "the judge opened no frame image of %s (read %d of %d images)" % (", ".join(blind), len(seen), len(files))
    return None


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
