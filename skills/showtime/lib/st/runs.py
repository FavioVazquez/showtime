"""Background runs: `showtime <command> ... --background` and `showtime status <run>` (stdlib only).

Many agent hosts stop a shell command after a few seconds or minutes (or after a few minutes without
output), and some kill whatever a command left running when it returns. A render, a transcription or
`setup` can take longer than that. With --background the launcher starts the command under a small
detached supervisor and returns at once with a run id:

  <home>/runs/<id>/run.json     what runs, where, its state, exit code and times (rewritten atomically)
  <home>/runs/<id>/output.log   everything the command printed (stdout and stderr, in order)

`showtime status <id>` reads them: running for how long, the latest progress line, and at the end the
exit code and the last lines of output. `--wait S` keeps watching for up to S seconds, printing a line
every 30 s, and exits with the command's own exit code once it has finished (75 while it still runs).
`--cancel` stops it. The showtime MCP server runs its long tools the same way, so a tool call can
return a run id and the `status` tool can report on it later.

Run ids look like `render-20260928-141500-a1b2` (the command, the start time, 4 random hex digits).
The newest 50 runs are kept; older finished ones are removed when a new one starts.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}-\d{8}-\d{6}-[0-9a-f]{4}$")
KEEP = 50
STILL_RUNNING = 75           # `status --wait` exit code when the run has not finished yet
PRINT_EVERY = 30.0           # `status --wait`: one line at least this often
ACTIVE = ("starting", "running")
LAUNCHER = Path(__file__).resolve().parent / "launcher.py"
LIB_DIR = Path(__file__).resolve().parents[1]


def home() -> Path:
    env = os.environ.get("SHOWTIME_HOME")
    return Path(os.path.expanduser(env)).absolute() if env else Path(os.path.expanduser("~")) / ".showtime"


def root(h: Optional[Path] = None) -> Path:
    return (Path(h) if h else home()) / "runs"


def now_iso(t: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t if t is not None else time.time()))


def fmt_secs(s: float) -> str:
    s = max(0.0, float(s))
    if s < 60:
        return "%d s" % round(s)
    m, sec = divmod(int(round(s)), 60)
    if m < 60:
        return "%d min %d s" % (m, sec)
    h, m = divmod(m, 60)
    return "%d h %d min" % (h, m)


def display(argv: List[str]) -> str:
    out = []
    for a in ["showtime"] + list(argv):
        out.append(a if re.match(r"^[\w@%+=:,./\\-]+$", a) else json.dumps(a))
    return " ".join(out)


# --------------------------------------------------------------------------- run records

def load(run_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["dir"] = str(run_dir)
    data["log"] = str(Path(run_dir) / "output.log")
    return data


def save(run_dir: Path, data: Dict[str, Any]) -> None:
    body = {k: v for k, v in data.items() if k not in ("dir", "log")}
    tmp = Path(run_dir) / (".run.json.%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(Path(run_dir) / "run.json"))


def update(run_dir: Path, **fields: Any) -> Dict[str, Any]:
    data = load(run_dir) or {}
    data.update(fields)
    save(run_dir, data)
    return data


def find(ref: str, h: Optional[Path] = None) -> Optional[Path]:
    """The run folder for an id (or a folder path to one); None when it is not a run."""
    if not ref:
        return None
    p = Path(ref)
    if (p / "run.json").is_file() and p.parent.name == "runs":
        return p
    if not ID_RE.match(ref):
        return None
    d = root(h) / ref
    return d if (d / "run.json").is_file() else None


def all_runs(h: Optional[Path] = None) -> List[Dict[str, Any]]:
    r = root(h)
    out = []
    try:
        for d in r.iterdir():
            if d.is_dir() and ID_RE.match(d.name):
                data = load(d)
                if data:
                    out.append(refresh(data))
    except OSError:
        return []
    out.sort(key=lambda x: x.get("created_ts", 0), reverse=True)
    return out


def pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            k32.CloseHandle(h)
            return bool(ok) and code.value == 259     # STILL_ACTIVE
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def refresh(data: Dict[str, Any]) -> Dict[str, Any]:
    """A run whose supervisor died without writing an end (a reboot, a kill -9) is 'lost'."""
    if data.get("state") in ACTIVE:
        sup = data.get("supervisor_pid")
        age = time.time() - float(data.get("created_ts") or 0)
        if (sup and not pid_alive(sup)) or (not sup and age > 60):
            data["state"] = "lost"
            try:
                save(Path(data["dir"]), data)
            except OSError:
                pass
    return data


# --------------------------------------------------------------------------- starting

def new_id(argv: List[str]) -> str:
    words = [a for a in argv[:1] if re.match(r"^[a-z][a-z0-9-]*$", a)]
    stem = (words[0] if words else "run")[:24].strip("-") or "run"
    return "%s-%s-%s" % (stem, time.strftime("%Y%m%d-%H%M%S"), os.urandom(2).hex())


def prune(h: Optional[Path] = None, keep: int = KEEP) -> None:
    import shutil
    runs = all_runs(h)
    for data in runs[keep:]:
        if data.get("state") not in ACTIVE:
            shutil.rmtree(data["dir"], ignore_errors=True)


def start(argv: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None,
          source: str = "cli", program: Optional[List[str]] = None) -> Dict[str, Any]:
    """Start `showtime <argv>` under a detached supervisor; returns the run record at once.
    `program` replaces the launcher (`[python, launcher.py]`) in front of argv (tests)."""
    env = dict(os.environ if env is None else env)
    h = Path(env.get("SHOWTIME_HOME") or home())
    r = root(h)
    r.mkdir(parents=True, exist_ok=True)
    try:
        prune(h)
    except OSError:
        pass
    run_id = new_id(argv)
    d = r / run_id
    d.mkdir()
    t = time.time()
    data = {"id": run_id, "argv": list(argv), "command": display(argv), "cwd": str(cwd or os.getcwd()),
            "source": source, "state": "starting", "created": now_iso(t), "created_ts": t}
    if program:
        data["program"] = list(program)
    save(d, data)
    (d / "output.log").write_bytes(b"")
    env["PYTHONPATH"] = str(LIB_DIR) + ((os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONUTF8", "1")
    cmd = [sys.executable, "-m", "st.runs", "supervise", str(d)]
    kw: Dict[str, Any] = {"cwd": str(cwd or os.getcwd()), "env": env, "stdin": subprocess.DEVNULL,
                          "stdout": subprocess.DEVNULL, "close_fds": True}
    err = open(str(d / "supervisor.log"), "ab")
    kw["stderr"] = err
    try:
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)   # + CREATE_BREAKAWAY_FROM_JOB
            except OSError:
                proc = subprocess.Popen(cmd, creationflags=flags, **kw)   # the host's job forbids breaking away
        else:
            proc = subprocess.Popen(cmd, start_new_session=True, **kw)
    finally:
        err.close()
    proc.returncode = 0   # detached on purpose: never waited for here (no "still running" warning at exit)
    # the supervisor records its own pid (one writer per run.json after this point, no lost updates)
    data["launcher_pid"] = proc.pid
    data["dir"], data["log"] = str(d), str(d / "output.log")
    return data


# --------------------------------------------------------------------------- the supervisor

def supervise(run_dir: Path) -> int:
    """Run the command, send its output to output.log, record the outcome. Runs detached."""
    run_dir = Path(run_dir)
    data = load(run_dir)
    if not data:
        return 2
    env = dict(os.environ)
    env["SHOWTIME_RUN_ID"] = data["id"]
    env["SHOWTIME_HEARTBEAT"] = "0"        # status reports the elapsed time itself
    env.setdefault("PYTHONUNBUFFERED", "1")
    cancel_flag = run_dir / "cancel"
    t0 = time.time()
    update(run_dir, supervisor_pid=os.getpid())
    with open(str(run_dir / "output.log"), "ab", buffering=0) as log:
        kw: Dict[str, Any] = {"cwd": data.get("cwd") or None, "env": env, "stdin": subprocess.DEVNULL,
                              "stdout": log, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kw["creationflags"] = 0x00000200 | 0x08000000   # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        else:
            kw["start_new_session"] = True
        try:
            prog = data.get("program") or [sys.executable, str(LAUNCHER)]
            child = subprocess.Popen(list(prog) + list(data["argv"]), **kw)
        except OSError as e:
            log.write(("showtime: could not start the command: %s\n" % e).encode("utf-8"))
            update(run_dir, state="failed", exit_code=127, ended=now_iso(), seconds=0.0)
            return 127

        def on_term(signum, frame):  # noqa: ANN001, ARG001
            try:
                cancel_flag.write_text("signal\n", encoding="utf-8")
            except OSError:
                pass
            _kill_tree(child.pid, soft=True)

        if os.name != "nt":
            signal.signal(signal.SIGTERM, on_term)
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        update(run_dir, state="running", pid=child.pid, started=now_iso(t0), started_ts=t0)
        code = child.wait()
    secs = round(time.time() - t0, 1)
    cancelled = cancel_flag.exists()
    state = "cancelled" if cancelled else ("done" if code == 0 else "failed")
    update(run_dir, state=state, exit_code=code, ended=now_iso(), seconds=secs)
    return 0


def _kill_tree(pid: int, soft: bool = True) -> None:
    if os.name == "nt":
        subprocess.call(["taskkill", "/pid", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        return
    try:
        os.killpg(pid, signal.SIGTERM if soft else signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM if soft else signal.SIGKILL)
        except OSError:
            pass


def cancel(run_dir: Path, grace: float = 5.0) -> Dict[str, Any]:
    """Stop a run (its whole process tree). Returns the refreshed record."""
    data = load(run_dir) or {}
    if data.get("state") not in ACTIVE:
        return data
    try:
        (Path(run_dir) / "cancel").write_text("requested %s\n" % now_iso(), encoding="utf-8")
    except OSError:
        pass
    pid = data.get("pid")
    if pid:
        _kill_tree(int(pid), soft=True)
        t_end = time.time() + grace
        while time.time() < t_end and pid_alive(pid):
            time.sleep(0.2)
        if pid_alive(pid):
            _kill_tree(int(pid), soft=False)
    t_end = time.time() + 5
    while time.time() < t_end:
        data = refresh(load(run_dir) or data)
        if data.get("state") not in ACTIVE:
            break
        time.sleep(0.2)
    if data.get("state") in ACTIVE:   # no supervisor to write the end: do it here
        data = update(Path(run_dir), state="cancelled", ended=now_iso())
    return data


# --------------------------------------------------------------------------- reading the output

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def output_lines(data: Dict[str, Any], max_bytes: int = 256 * 1024) -> List[str]:
    try:
        with open(data["log"], "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read().decode("utf-8", "replace")
    except (OSError, KeyError):
        return []
    out = []
    for line in raw.splitlines():
        line = _ANSI.sub("", line).split("\r")[-1].rstrip()
        if line:
            out.append(line)
    return out


PROGRESS_RE = re.compile(r"\d+/\d+\s+\d{1,3}%|\d{1,3}%|ETA|still running|still ")


def latest_progress(lines: List[str]) -> str:
    for line in reversed(lines[-40:]):
        if PROGRESS_RE.search(line):
            return line.strip()
    return lines[-1].strip() if lines else ""


def elapsed(data: Dict[str, Any]) -> float:
    if data.get("seconds") is not None and data.get("state") not in ACTIVE:
        return float(data["seconds"])
    t0 = data.get("started_ts") or data.get("created_ts") or time.time()
    return time.time() - float(t0)


def summary(data: Dict[str, Any], tail: int = 15) -> Dict[str, Any]:
    lines = output_lines(data)
    st = data.get("state")
    return {"id": data.get("id"), "state": st, "running": st in ACTIVE, "command": data.get("command"),
            "argv": data.get("argv"), "cwd": data.get("cwd"), "exit_code": data.get("exit_code"),
            "seconds": round(elapsed(data), 1), "created": data.get("created"), "ended": data.get("ended"),
            "latest": latest_progress(lines) if st in ACTIVE else "", "tail": lines[-tail:],
            "log": data.get("log"), "dir": data.get("dir")}


def status_text(data: Dict[str, Any], tail: int = 15) -> str:
    s = summary(data, tail)
    rid = s["id"]
    st = s["state"]
    out = []
    if st in ACTIVE:
        out.append("%s: running for %s" % (rid, fmt_secs(s["seconds"])))
    elif st == "done":
        out.append("%s: finished OK in %s (exit 0)" % (rid, fmt_secs(s["seconds"])))
    elif st == "failed":
        out.append("%s: FAILED after %s (exit %s)" % (rid, fmt_secs(s["seconds"]), s["exit_code"]))
    elif st == "cancelled":
        out.append("%s: cancelled after %s" % (rid, fmt_secs(s["seconds"])))
    else:
        out.append("%s: lost (its supervisor stopped without recording an end, e.g. a restart)" % rid)
    out.append("  command: %s" % s["command"])
    out.append("  folder:  %s" % s["cwd"])
    if st in ACTIVE:
        if s["latest"]:
            out.append("  latest:  %s" % s["latest"])
        out.append("  log:     %s" % s["log"])
        out.append("  next:    showtime status %s --wait 240   (stop it: showtime status %s --cancel)" % (rid, rid))
    else:
        if s["tail"]:
            out.append("  output (last %d lines):" % len(s["tail"]))
            out += ["    " + line for line in s["tail"]]
        out.append("  log:     %s" % s["log"])
    return "\n".join(out)


def list_text(runs: List[Dict[str, Any]], limit: int = 20) -> str:
    if not runs:
        return "no background runs yet (start one with `showtime <command> ... --background`)"
    out = ["background runs, newest first:"]
    for d in runs[:limit]:
        out.append("  %-44s %-9s %8s  %s" % (d.get("id"), d.get("state"), fmt_secs(elapsed(d)), d.get("command")))
    return "\n".join(out)


def started_text(data: Dict[str, Any]) -> str:
    rid = data["id"]
    return "\n".join([
        "started in the background: %s" % rid,
        "  command: %s" % data["command"],
        "  check:   showtime status %s          (add --wait 240 to watch until it ends)" % rid,
        "  stop:    showtime status %s --cancel" % rid,
        "  log:     %s" % data["log"],
    ])


# --------------------------------------------------------------------------- `showtime status <run>`

def status_main(args: List[str], out=None) -> int:
    """`showtime status <run-id> [--wait S] [--cancel] [--json]` and `showtime status --runs [--json]`."""
    out = out or sys.stdout
    as_json = "--json" in args
    wait = None
    ref = None
    do_cancel = "--cancel" in args
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--wait":
            nxt = args[i + 1] if i + 1 < len(args) else ""
            if re.match(r"^\d+(\.\d+)?$", nxt):
                wait = float(nxt)
                i += 1
            else:
                wait = 240.0
        elif a.startswith("--wait="):
            try:
                wait = float(a.split("=", 1)[1])
            except ValueError:
                wait = 240.0
        elif not a.startswith("-") and ref is None:
            ref = a
        i += 1
    if "--runs" in args or ref is None:
        runs = all_runs()
        if as_json:
            out.write(json.dumps([summary(d, 0) for d in runs[:50]], indent=2) + "\n")
        else:
            out.write(list_text(runs) + "\n")
        return 0
    d = find(ref)
    if d is None:
        sys.stderr.write("error: no background run %r\n  fix: `showtime status --runs` lists them\n" % ref)
        return 2
    data = refresh(load(d) or {})
    if do_cancel:
        data = cancel(d)
    elif wait is not None:
        data = watch(d, wait, None if as_json else out)
    if as_json:
        out.write(json.dumps(summary(data), indent=2) + "\n")
    else:
        out.write(status_text(data) + "\n")
    if data.get("state") in ACTIVE:
        return STILL_RUNNING if wait is not None else 0
    if do_cancel:
        return 0
    code = data.get("exit_code")
    return int(code) if isinstance(code, int) else (0 if data.get("state") == "done" else 1)


def watch(run_dir: Path, seconds: float, out=None, every: float = PRINT_EVERY) -> Dict[str, Any]:
    """Wait up to `seconds` for the run to end, printing its progress every `every` seconds."""
    t_end = time.time() + max(0.0, seconds)
    last_print = time.time()
    data = refresh(load(run_dir) or {})
    while data.get("state") in ACTIVE and time.time() < t_end:
        time.sleep(min(1.0, max(0.05, t_end - time.time())))
        data = refresh(load(run_dir) or data)
        if out is not None and time.time() - last_print >= every and data.get("state") in ACTIVE:
            last_print = time.time()
            latest = latest_progress(output_lines(data))
            out.write("showtime: %s still running (%s)%s\n" % (data.get("id"), fmt_secs(elapsed(data)),
                                                            (": " + latest) if latest else ""))
            out.flush()
    return data


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "supervise":
        return supervise(Path(argv[1]))
    return status_main(argv)


if __name__ == "__main__":
    sys.exit(main())
