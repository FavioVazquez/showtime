#!/usr/bin/env python3
"""End-to-end platform test for showtime (stdlib only, any OS, Python 3.8+).

Runs what the README's "Requirements" section means by "tested end to end", through the same entry point
a user has (skills/showtime/bin/showtime, or showtime.cmd on Windows):

    setup (default tier) -> doctor -> job init -> new dom -> voice script -> retime --from-voice -> check
    -> render -> qa -> export html -> transcribe -> captions (SRT/VTT + burned) -> qa (captioned)
    -> MCP server handshake (initialize + tools/list over stdio) -> fast test suite

    python scripts/e2e.py --out ~/showtime-e2e              # everything (setup downloads ~3 GB the first time)
    python scripts/e2e.py --out DIR --skip-setup             # an installed runtime: skip setup
    python scripts/e2e.py --out DIR --no-suite               # skip the fast test suite
    python scripts/e2e.py --out DIR --suite-args "-j 2 --shard 1/3"

Every step writes its full output to DIR/logs/NN-step.txt. DIR/summary.json and DIR/summary.md list each
step with its exit code, seconds and one key line, plus the machine (platform key, OS, CPU, Python, Node).
The job folder with final.mp4, final.captioned.mp4, exports/promo.html and the subtitles is
DIR/work/showtime-out/e2e-*/. Exit code 0 only when every step passed. Nothing is written into the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "showtime"
sys.path.insert(0, str(SKILL / "lib"))
from st import platform as plat  # noqa: E402

IS_WIN = os.name == "nt"
NARRATION = """## hero
Meet Northwind: your launch video, in one sentence.

## features
Voice, music and captions, made on this machine. Café-quality, naïvely simple.

## formats
Every format, from one project.
"""


class Run:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.logs = out / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.steps: List[Dict[str, object]] = []
        self.env = dict(os.environ, NO_COLOR="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self.env.setdefault("SHOWTIME_PROGRESS", "plain")

    def shim(self) -> List[str]:
        b = SKILL / "bin"
        if IS_WIN:
            return [str(b / "showtime.cmd")]
        return ["sh", str(b / "showtime")]

    def log_path(self, name: str) -> Path:
        return self.logs / ("%02d-%s.txt" % (len(self.steps) + 1, name))

    def record(self, name: str, ok: bool, rc: Optional[int], secs: float, note: str, log: Optional[Path]) -> bool:
        self.steps.append({"step": name, "ok": ok, "rc": rc, "seconds": round(secs, 1), "note": note,
                           "log": str(log.relative_to(self.out)) if log else None})
        print("%-4s %-12s rc=%-4s %6.1fs  %s" % ("PASS" if ok else "FAIL", name, rc, secs, note), flush=True)
        return ok

    def skip(self, name: str, why: str) -> bool:
        self.steps.append({"step": name, "ok": None, "rc": None, "seconds": 0, "note": "skipped: " + why, "log": None})
        print("SKIP %-12s %s" % (name, why), flush=True)
        return False

    def cmd(self, name: str, argv: List[str], cwd: Path, timeout: int = 1800, expect=None,
            strict: bool = True) -> Optional[str]:
        """Run argv, log everything, return its output when it passed: exit code 0, expect(output) returns
        no complaint and (strict) no Python traceback in the output, such as an "Exception ignored in
        atexit callback" that leaves the exit code at 0."""
        log = self.log_path(name)
        t0 = time.time()
        try:
            cp = subprocess.run(argv, cwd=str(cwd), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, timeout=timeout)
            text, rc = cp.stdout.decode("utf-8", "replace"), cp.returncode
        except subprocess.TimeoutExpired as e:
            text, rc = (e.output or b"").decode("utf-8", "replace") + "\n[e2e] timed out after %ds" % timeout, None
        except OSError as e:
            text, rc = "[e2e] could not start: %s" % e, None
        secs = time.time() - t0
        log.write_text("$ %s\n(cwd %s)\n\n%s" % (" ".join(shlex.quote(a) for a in argv), cwd, text), encoding="utf-8")
        ok = rc == 0
        note = key_line(text)
        if ok and strict and TRACEBACK in text:
            ok, note = False, "traceback in the output: " + traceback_line(text)
        if ok and expect is not None:
            why = expect(text)
            if why:
                ok, note = False, why
        self.record(name, ok, rc, secs, note, log)
        return text if ok else None

    def st(self, name: str, *args: str, cwd: Path, timeout: int = 1800, expect=None) -> Optional[str]:
        return self.cmd(name, self.shim() + list(args), cwd, timeout, expect)


TRACEBACK = "Traceback (most recent call last)"


def traceback_line(text: str) -> str:
    """The exception line that ends the first traceback in text."""
    lines = text[text.find(TRACEBACK):].splitlines()
    for ln in lines[1:]:
        if ln and not ln.startswith((" ", "\t")):
            return ln.strip()[:200]
    return lines[0][:200] if lines else ""


def key_line(text: str) -> str:
    """The most telling line of a step's output: a verdict/summary line, else the last non-empty one."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for pref in ("verdict:", "result:", "done ", "exported ", "showtime setup summary", "summary", "FAILED", "OK"):
        for ln in reversed(lines):
            if ln.startswith(pref):
                return ln[:200]
    return lines[-1][:200] if lines else ""


def probe(path: Path) -> Dict[str, object]:
    try:
        from st import ff
        p = ff.probe(str(path))
        return {"width": p.get("width"), "height": p.get("height"), "duration": p.get("duration"),
                "video": p.get("has_video"), "audio": p.get("has_audio")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def mcp_handshake(r: Run, cwd: Path) -> bool:
    log = r.log_path("mcp")
    node = shutil.which("node")
    if not node:
        return r.record("mcp", False, None, 0, "node not on PATH", None)
    server = SKILL / "mcp" / "server.mjs"
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    t0 = time.time()
    p = subprocess.Popen([node, str(server)], cwd=str(cwd), env=dict(r.env, SHOWTIME_MCP_BASE=str(cwd)),
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    got: Dict[int, dict] = {}
    lines: List[str] = []
    errbuf: List[bytes] = []
    reader = threading.Thread(target=lambda: errbuf.append(p.stderr.read() if p.stderr else b""), daemon=True)
    reader.start()
    try:
        assert p.stdin is not None and p.stdout is not None
        p.stdin.write(("\n".join(json.dumps(q) for q in reqs) + "\n").encode("utf-8"))
        p.stdin.flush()
        deadline = time.time() + 60
        while time.time() < deadline and not (1 in got and 2 in got):
            raw = p.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            lines.append(line)
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") in (1, 2):
                got[msg["id"]] = msg
        p.stdin.close()   # the server exits when its client goes away
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            errbuf.append(b"\n[e2e] server did not exit within 15 s after stdin closed")
    finally:
        if p.poll() is None:
            p.kill()
    reader.join(timeout=5)
    err = b"".join(errbuf).decode("utf-8", "replace")
    secs = time.time() - t0
    init = (got.get(1) or {}).get("result") or {}
    tools = ((got.get(2) or {}).get("result") or {}).get("tools") or []
    log.write_text("stdout:\n%s\n\nstderr:\n%s\n" % ("\n".join(lines), err), encoding="utf-8")
    info = init.get("serverInfo") or {}
    ok = bool(info.get("name")) and len(tools) > 0
    note = "server %s %s, protocol %s, %d tools" % (info.get("name"), info.get("version"), init.get("protocolVersion"),
                                                  len(tools))
    return r.record("mcp", ok, p.returncode, secs, note, log)


def browser_deps(r: Run, work: Path) -> None:
    """README (Linux): if the browser does not start, install Chromium's system libraries once."""
    try:
        cp = subprocess.run(r.shim() + ["doctor", "--json"], cwd=str(work), env=r.env, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=900)
        txt = cp.stdout.decode("utf-8", "replace")
        rows = json.loads(txt[txt.find("{"):]).get("checks", [])
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        r.record("browser-deps", False, None, 0, "doctor --json unreadable: %s" % e, None)
        return
    launch = next((x for x in rows if x.get("check") == "browser launch"), {})
    if launch.get("status") != "fail":
        r.skip("browser-deps", "not needed (browser launch: %s)" % launch.get("status"))
        return
    home = Path(os.path.expanduser(os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
    cli = home / "node" / "node_modules" / "playwright" / "cli.js"
    r.cmd("browser-deps", ["sudo", "-n", shutil.which("node") or "node", str(cli), "install-deps", "chromium"],
          cwd=work, timeout=1800)


def machine_info() -> Dict[str, object]:
    node = shutil.which("node")
    nv = ""
    if node:
        try:
            nv = subprocess.run([node, "--version"], stdout=subprocess.PIPE, timeout=30).stdout.decode().strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {"platform_key": plat.platform_key(), "binary_key": plat.binary_key(), "os": platform.platform(),
            "machine": platform.machine(), "cpus": os.cpu_count(), "python": sys.version.split()[0],
            "python_arch": platform.machine(), "node": nv, "user": os.environ.get("USERNAME") or os.environ.get("USER"),
            "repo": str(REPO)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("--out", required=True, help="folder for logs, the job and the summary (created)")
    ap.add_argument("--skip-setup", action="store_true", help="use the runtime that is already installed")
    ap.add_argument("--setup-args", default="", help="extra arguments for `showtime setup` (quoted string)")
    ap.add_argument("--no-suite", action="store_true", help="skip the fast test suite")
    ap.add_argument("--suite-args", default="-j auto", help="arguments for run_all.py --fast (default: -j auto)")
    ap.add_argument("--browser-deps", action="store_true",
                    help="Linux: when the browser does not start after setup, install Chromium's system libraries "
                         "(the README step; needs passwordless sudo) and record that it was needed")
    ap.add_argument("--duration", type=int, default=16, help="length of the voiced render in seconds (default 16; at least 14, the narration is about 13 s)")
    a = ap.parse_args()

    out = Path(a.out).expanduser().resolve()
    try:
        out.relative_to(REPO)
        ap.error("--out must be outside the repository (%s)" % REPO)
    except ValueError:
        pass
    r = Run(out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    info = machine_info()
    print("showtime e2e on %s (%s, %s cpus, python %s, node %s)" % (info["platform_key"], info["os"], info["cpus"],
                                                                     info["python"], info["node"]), flush=True)
    t_all = time.time()

    r.st("version", "--version", cwd=work, timeout=600)
    if a.skip_setup:
        r.skip("setup", "--skip-setup")
    else:
        r.st("setup", "setup", *shlex.split(a.setup_args), cwd=work, timeout=5400)
    if a.browser_deps and sys.platform.startswith("linux"):
        browser_deps(r, work)
    r.st("doctor", "doctor", cwd=work, timeout=900)

    job: Optional[Path] = None
    txt = r.st("job-init", "job", "init", "e2e", "--goal", "short voiced promo, end-to-end platform test", "--json",
               cwd=work, timeout=300)
    if txt:
        try:
            job = Path(json.loads(txt[txt.find("{"):])["job"])
            r.steps[-1]["note"] = str(job)
        except (ValueError, KeyError):
            job = None
    proj = job / "project" if job else None
    d = str(a.duration)
    chain = [
        ("new", lambda: r.st("new", "new", "dom", str(proj), "--duration", d, cwd=work, timeout=600)),
        ("voice", lambda: (proj / "narration.md").write_text(NARRATION, encoding="utf-8") and
            r.st("voice", "voice", "script", str(proj / "narration.md"), "-o", str(proj / "voice"), cwd=work, timeout=1800)),
        ("retime", lambda: r.st("retime", "retime", str(proj), "--from-voice", str(proj / "voice" / "timeline.json"),
                                "--total", d, cwd=work, timeout=600)),
        ("check", lambda: r.st("check", "check", str(proj), cwd=work, timeout=1800)),
        ("render", lambda: r.st("render", "render", str(proj), "--job", str(job), cwd=work, timeout=3600,
                                expect=lambda t: None if (job / "final.mp4").is_file() else "no final.mp4")),
        ("qa", lambda: r.st("qa", "qa", str(job), cwd=work, timeout=900)),
    ]
    alive = job is not None
    for name, fn in chain:
        if not alive:
            r.skip(name, "an earlier step failed")
            continue
        if not fn():
            alive = name == "check"  # check warnings or errors do not stop the render
    rendered = job is not None and (job / "final.mp4").is_file()
    if rendered:
        r.st("export", "export", "html", str(proj), "-o", str(job / "exports" / "promo.html"), cwd=work, timeout=1800,
             expect=lambda t: None if (job / "exports" / "promo.html").is_file() else "no promo.html")
        tr = job / "edit" / "transcripts" / "final.json"

        def words_ok(_t: str) -> Optional[str]:
            try:
                data = json.loads(tr.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                return "transcript unreadable: %s" % e
            words = [w for w in data.get("words") or [] if w.get("type", "word") == "word"]
            text = " ".join(str(w.get("text") or "") for w in words).lower()
            if len(words) < 5:
                return "only %d words transcribed" % len(words)
            if "northwind" not in text and "voice" not in text and "format" not in text:
                return "transcript does not contain the narration: %s" % text[:120]
            return None
        if r.st("transcribe", "transcribe", str(job / "final.mp4"), cwd=work, timeout=1800, expect=words_ok):
            r.st("captions", "captions", str(tr), "--style", "clean", "-o", str(job / "subs.ass"), "--srt",
                 str(job / "subs.srt"), "--vtt", str(job / "subs.vtt"), cwd=work, timeout=600,
                 expect=lambda t: None if (job / "subs.srt").stat().st_size > 20 else "empty subs.srt")
            if r.st("burn", "captions", str(tr), "--style", "bold-pop", "--burn", str(job / "final.mp4"), "-o",
                    str(job / "final.captioned.mp4"), cwd=work, timeout=1800,
                    expect=lambda t: None if (job / "final.captioned.mp4").is_file() else "no final.captioned.mp4"):
                r.st("qa-captioned", "qa", str(job / "final.captioned.mp4"), cwd=work, timeout=900)
            else:
                r.skip("qa-captioned", "burn failed")
        else:
            for n in ("captions", "burn", "qa-captioned"):
                r.skip(n, "transcribe failed")
    else:
        for n in ("export", "transcribe", "captions", "burn", "qa-captioned"):
            r.skip(n, "no render")
    mcp_handshake(r, work)

    if a.no_suite:
        r.skip("fast-suite", "--no-suite")
    else:
        home = Path(os.path.expanduser(os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
        vpy = plat.venv_python(home / "venv")
        py = str(vpy) if vpy.exists() else sys.executable
        r.cmd("fast-suite", [py, str(SKILL / "tests" / "run_all.py"), "--fast"] + shlex.split(a.suite_args), cwd=work,
              timeout=5400, strict=False)   # tests print expected tracebacks; the exit code is the verdict

    media = {}
    if job:
        for rel in ("final.mp4", "final.captioned.mp4"):
            if (job / rel).is_file():
                media[rel] = dict(probe(job / rel), bytes=(job / rel).stat().st_size)
        if (job / "exports" / "promo.html").is_file():
            media["exports/promo.html"] = {"bytes": (job / "exports" / "promo.html").stat().st_size}
    failed = [s["step"] for s in r.steps if s["ok"] is False]
    summary = {"ok": not failed, "failed": failed, "seconds": round(time.time() - t_all, 1), "machine": info,
               "job": str(job) if job else None, "media": media, "steps": r.steps,
               "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = ["# showtime e2e: %s" % info["platform_key"], "",
          "%s, %s cpus, Python %s, Node %s, user %s" % (info["os"], info["cpus"], info["python"], info["node"], info["user"]),
          "", "| step | result | rc | seconds | note |", "|---|---|---|---|---|"]
    for s in r.steps:
        res = "pass" if s["ok"] else ("skip" if s["ok"] is None else "**FAIL**")
        md.append("| %s | %s | %s | %s | %s |" % (s["step"], res, s["rc"], s["seconds"], str(s["note"]).replace("|", "/")))
    md += ["", "media: " + json.dumps(media), "", "total %.0f s; %s" % (summary["seconds"],
                                                                       "all passed" if not failed else "failed: " + ", ".join(failed))]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[-1:]))
    print("summary: %s" % (out / "summary.md"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
