#!/usr/bin/env python3
"""Run ONE (arm, task) headless session and record everything needed to score it.

    python benchmarks/harness/run_one.py --arm showtime --task t7 --run smoke-01 --cap-min 8

What it does
  1. Builds a fresh workspace <ws root>/<opaque>/project (outside the operator's home) with only the task's inputs, committed
     to a new git repo, and a fresh CLAUDE_CONFIG_DIR copied from the arm's template.
  2. Starts `claude -p <task prompt>` with the arm's flags (same model, effort, budget, tools for all arms),
     streaming JSON to runs/<run>/<task>/<arm>/stream.jsonl with receive times.
  3. Watches the workspace every 2 s for the first deliverable (time to first output).
  4. If the agent stops to ask the user something and has not delivered, answers ONCE with the same
     neutral reply for every arm (common.NEUTRAL_REPLY) and resumes the session; the question counts.
  5. Kills the whole process group at the time cap, then any leftover process that still references the
     workspace (renders the agent started in the background), so nothing outlives the run.
  6. Writes meta.json: timings, tokens, cost, turns, tool counts, questions, deliverables, integrity checks.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arms as armlib  # noqa: E402
import common  # noqa: E402

QUESTION_RE = re.compile(r"(would you like|should i\b|do you (already |still )?(want|have|prefer|need)|"
                         r"which (one|option|style|version|direction)|"
                         r"can you (confirm|share|provide)|please (confirm|provide|share|upload)|"
                         r"before i (start|proceed|begin|pitch|build|make)|shall i\b|one question|"
                         r"tell me (which|what|if)|let me know (which|what|if))", re.I)


# ---------------------------------------------------------------- workspace

def make_workspace(task: Dict, ws: Path) -> List[str]:
    """Copy the task inputs into ws, commit them; return the input paths (relative) to exclude later."""
    ws.mkdir(parents=True)
    rels = []
    for item in task.get("inputs", []):
        if "fetch" in item:
            src = common.BENCH / "fixtures" / "media" / (item["fetch"] + ".mp4")
            if not src.exists():
                raise SystemExit("fixture %s missing. FIX: python benchmarks/fixtures/fetch_fixtures.py" % src.name)
        else:
            src = common.BENCH / item["from"]
        dst = ws / item["to"]
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            rels += [str(p.relative_to(ws)) for p in dst.rglob("*") if p.is_file()]
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rels.append(str(dst.relative_to(ws)))
    git = ["git", "-c", "user.name=user", "-c", "user.email=user@example.invalid", "-c", "init.defaultBranch=main"]
    common.run(git + ["init", "-q"], cwd=str(ws))
    if rels:
        common.run(git + ["add", "-A"], cwd=str(ws))
        common.run(git + ["commit", "-q", "-m", "Initial commit"], cwd=str(ws))
    return rels


def deliverable_files(ws: Path, kind: str, exclude: set) -> List[Path]:
    exts = common.HTML_EXT if kind == "html" else common.VIDEO_EXT
    out = []
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in common.SKIP_DIRS]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in exts and str(p.relative_to(ws)) not in exclude:
                try:
                    if p.stat().st_size > 0:
                        out.append(p)
                except OSError:
                    pass
    return out


def pick_primary(ws: Path, kind: str, exclude: set, final_text: str, expect: Optional[Dict] = None) -> Dict:
    """The deliverable: named in the agent's last message, called final, not a draft, a playable video, and (a
    tie-break added in round 4) as long as the task asked. A partial re-render written next to the full video
    (an 18 s final-2.mp4 beside the 82 s final.mp4, both named in the message) no longer wins by being newer."""
    cands = deliverable_files(ws, kind, exclude)
    span = (expect or {}).get("duration")
    info = []
    for p in cands:
        rel = str(p.relative_to(ws))
        low = rel.lower()
        score = 0
        if rel in final_text or p.name in final_text:
            score += 10
        if "final" in p.name.lower():
            score += 3
        if re.search(r"(preview|draft|test|tmp|temp|frame|proxy|scratch|segment|seg_|part)", p.name.lower()):
            score -= 2
        if re.search(r"(^|/)(work|frames|cache|tmp|temp|\.render|segments|parts)(/|$)", low):
            score -= 3
        pr = common.probe(p) if kind == "video" else {"ok": True, "bytes": p.stat().st_size}
        if kind == "video" and (not pr.get("ok") or (pr.get("duration") or 0) < 0.5 or not pr.get("video")):
            score -= 20
        elif kind == "video" and span and span[0] <= (pr.get("duration") or 0) <= span[1]:
            score += 2
        info.append({"path": rel, "score": score, "mtime": p.stat().st_mtime, "probe": pr})
    info.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)
    primary = info[0] if info and info[0]["score"] > -20 else None
    return {"primary": primary["path"] if primary else None, "candidates": info[:20]}


# ---------------------------------------------------------------- integrity

def operator_state() -> Dict:
    """Things a run must never change: the operator's Claude Code settings and user skills."""
    base = Path.home() / ".claude"
    st = {}
    for f in ("settings.json", "settings.local.json"):
        p = base / f
        st[f] = common.sha256_file(p) if p.exists() else None
    sk = base / "skills"
    st["skills"] = sorted(os.listdir(sk)) if sk.is_dir() else []
    return st


# ---------------------------------------------------------------- process control

def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        pass
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            for _ in range(20):
                if proc.poll() is not None:
                    break
                time.sleep(0.5)
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def kill_stragglers(marker: str) -> List[str]:
    """Kill leftover processes whose command line mentions the run's workspace (POSIX)."""
    if os.name == "nt":
        return []
    me = os.getpid()
    pids = {}
    r = common.run(["ps", "-axo", "pid=,command="])
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and marker in parts[1]:
            pids[int(parts[0])] = parts[1][:160]
    if shutil.which("lsof"):  # processes whose working directory is inside the workspace
        r = common.run(["lsof", "-a", "-d", "cwd", "-F", "pn"])
        pid = None
        for line in r.stdout.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and pid and line[1:].startswith(marker):
                pids.setdefault(pid, "cwd " + line[1:][:140])
    killed = []
    for pid, what in pids.items():
        if pid == me:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(what)
        except OSError:
            pass
    return killed


class Session:
    """One `claude -p` process: stream capture, stats, cap enforcement."""

    def __init__(self, args: List[str], ws: Path, env: Dict, stream_fh, t0: float, deadline: float, phase: int):
        self.args, self.ws, self.env, self.fh, self.t0, self.deadline, self.phase = args, ws, env, stream_fh, t0, deadline, phase
        self.init: Dict = {}
        self.result: Dict = {}
        self.tools: Dict[str, int] = {}
        self.skills_used: List[str] = []
        self.ask_calls = 0
        self.first_tool_s: Optional[float] = None
        self.last_text = ""
        self.capped = False
        self.subagents = 0

    def run(self, stderr_fh) -> int:
        kw = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        proc = subprocess.Popen(self.args, cwd=str(self.ws), env=self.env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=stderr_fh, text=True, bufsize=1, **kw)
        self.proc = proc

        def guard():
            while proc.poll() is None:
                if time.time() >= self.deadline:
                    self.capped = True
                    kill_tree(proc)
                    return
                time.sleep(1)
        g = threading.Thread(target=guard, daemon=True)
        g.start()
        for line in proc.stdout:
            now = time.time() - self.t0
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.fh.write(json.dumps({"_t": round(now, 2), "_phase": self.phase, "_raw": line[:2000]}) + "\n")
                continue
            self._observe(msg, now)
            msg["_t"] = round(now, 2)
            msg["_phase"] = self.phase
            self.fh.write(json.dumps(msg) + "\n")
        proc.wait()
        g.join(timeout=2)
        kill_tree(proc)  # whatever the agent left running in its process group
        return proc.returncode

    def _observe(self, m: Dict, now: float) -> None:
        t = m.get("type")
        if t == "system" and m.get("subtype") == "init":
            self.init = m
        elif t == "result":
            self.result = m
        elif t == "assistant":
            if m.get("parent_tool_use_id"):
                return
            for b in (m.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use":
                    name = b.get("name", "?")
                    self.tools[name] = self.tools.get(name, 0) + 1
                    if self.first_tool_s is None:
                        self.first_tool_s = now
                    if name == "AskUserQuestion":
                        self.ask_calls += 1
                    if name == "Skill":
                        self.skills_used.append(str((b.get("input") or {}).get("skill") or (b.get("input") or {}).get("command")))
                    if name in ("Agent", "Task"):
                        self.subagents += 1
                elif b.get("type") == "text" and b.get("text"):
                    self.last_text = b["text"]


def text_asks(s: Session) -> bool:
    """The turn ended by asking the user something (last line is a question, or a typical ask phrase)."""
    text = (s.result.get("result") or s.last_text or "")[-800:].strip()
    last = text.splitlines()[-1].strip() if text else ""
    return last.endswith("?") or ("?" in text and bool(QUESTION_RE.search(text)))


def asks_user(s: Session) -> bool:
    return s.ask_calls > 0 or text_asks(s)


# ---------------------------------------------------------------- main entry

def run_one(arm_id: str, task_id: str, run_name: str, cap_min: Optional[float] = None, budget: float = 15.0,
            model: Optional[str] = None, effort: Optional[str] = None, max_continues: int = 1,
            force: bool = False, cell_name: Optional[str] = None) -> Dict:
    """Run one cell under a lock file, so two run_matrix processes can share a round safely.
    cell_name: the cell's folder (default: the arm id); a second run of the same arm in one round uses
    another name (e.g. showtime-rep2) and is otherwise identical."""
    task = common.load_tasks([task_id])[0]
    cell_name = cell_name or arm_id
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", cell_name):
        raise SystemExit("cell name %r: use lower-case letters, digits, dot, dash or underscore" % cell_name)
    cell = common.bench_home() / "runs" / run_name / task["id"]
    cell.mkdir(parents=True, exist_ok=True)
    lock = cell / (cell_name + ".lock")
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            os.kill(int(lock.read_text().strip() or 0), 0)
            common.log("skip %s/%s (running in another process)" % (task["id"], arm_id))
            return {"skipped": "running elsewhere"}
        except (ValueError, ProcessLookupError, PermissionError):
            lock.unlink(missing_ok=True)  # stale lock from a process that died
            return run_one(arm_id, task_id, run_name, cap_min, budget, model, effort, max_continues, force, cell_name)
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    try:
        return _run_one_locked(arm_id, task_id, run_name, cap_min, budget, model, effort, max_continues, force, cell_name)
    finally:
        lock.unlink(missing_ok=True)


def _run_one_locked(arm_id: str, task_id: str, run_name: str, cap_min: Optional[float] = None, budget: float = 15.0,
                    model: Optional[str] = None, effort: Optional[str] = None, max_continues: int = 1,
                    force: bool = False, cell_name: Optional[str] = None) -> Dict:
    cfg = common.load_arms([arm_id])
    arm, ccfg = cfg["arms"][0], cfg["common"]
    task = common.load_tasks([task_id])[0]
    home = common.bench_home()
    cell_name = cell_name or arm["id"]
    rdir = home / "runs" / run_name / task["id"] / cell_name
    if (rdir / "meta.json").exists() and not force:
        common.log("skip %s/%s (done; --force to redo)" % (task["id"], cell_name))
        return common.read_json(rdir / "meta.json")
    if rdir.exists():
        shutil.rmtree(rdir)
    rdir.mkdir(parents=True)
    tmpl = armlib.arm_dir(arm["id"]) / "cfg-template"
    if not tmpl.exists():
        raise SystemExit("arm %s not set up. FIX: python benchmarks/harness/arms.py setup --arms %s" % (arm["id"], arm["id"]))
    slot = common.ws_root() / common.opaque("%s/%s/%s/%f" % (run_name, task["id"], cell_name, time.time()), 10)
    ws, cfg_dir, tmp = slot / "project", slot / "cfg", slot / "tmp"
    exclude = set(make_workspace(task, ws))
    shutil.copytree(tmpl, cfg_dir)
    tmp.mkdir()
    env = armlib.build_env(arm, ccfg, cfg_dir, tmp)
    cap_s = 60.0 * (cap_min or task.get("cap_minutes", 20))
    before = operator_state()

    meta = {"schema": "showtime.bench.run/1", "run": run_name, "task": task["id"], "arm": arm["id"], "cell": cell_name,
            "prompt": task["prompt"], "model": model or ccfg["model"], "effort": effort or ccfg["effort"],
            "cap_s": cap_s, "budget_usd": budget, "workspace": str(ws), "started": common.now_iso(),
            "auth": "present" if armlib.auth_env() else "missing"}
    t0 = time.time()
    deadline = t0 + cap_s
    ttfo = {"s": None, "path": None}
    stop_watch = threading.Event()
    kind = task.get("deliverable", "video")

    def watch():
        while not stop_watch.is_set():
            if ttfo["s"] is None:
                found = deliverable_files(ws, kind, exclude)
                if found:
                    ttfo["s"] = round(time.time() - t0, 1)
                    ttfo["path"] = str(found[0].relative_to(ws))
            stop_watch.wait(2.0)
    w = threading.Thread(target=watch, daemon=True)
    w.start()

    sessions: List[Session] = []
    with open(rdir / "stream.jsonl", "w", encoding="utf-8") as fh, open(rdir / "stderr.log", "w", encoding="utf-8") as eh:
        prompt, resume = task["prompt"], None
        for phase in range(max_continues + 1):
            left = deadline - time.time()
            if left < 30:
                break
            args = armlib.claude_args(arm, ccfg, prompt, budget, model, effort, resume)
            s = Session(args, ws, env, fh, t0, deadline, phase)
            s.run(eh)
            sessions.append(s)
            fh.flush()
            sid = s.result.get("session_id") or s.init.get("session_id")
            delivered = bool(deliverable_files(ws, kind, exclude))
            if s.capped or delivered or not sid or not asks_user(s) or s.result.get("is_error"):
                break
            prompt, resume = common.NEUTRAL_REPLY, sid
    stop_watch.set()
    w.join(timeout=3)
    stragglers = kill_stragglers(str(slot))
    wall = round(time.time() - t0, 1)
    after = operator_state()

    final_text = "\n".join((s.result.get("result") or s.last_text or "") for s in sessions)
    picked = pick_primary(ws, kind, exclude, final_text, task.get("expect"))
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    cost, turns, api_ms = 0.0, 0, 0
    tools: Dict[str, int] = {}
    for s in sessions:
        u = s.result.get("usage") or {}
        for k in usage:
            usage[k] += int(u.get(k) or 0)
        cost += float(s.result.get("total_cost_usd") or 0)
        turns += int(s.result.get("num_turns") or 0)
        api_ms += int(s.result.get("duration_api_ms") or 0)
        for k, v in s.tools.items():
            tools[k] = tools.get(k, 0) + v
    first = sessions[0] if sessions else None
    meta.update({
        "ended": common.now_iso(), "wall_s": wall, "capped": any(s.capped for s in sessions),
        "ttfo_s": ttfo["s"], "ttfo_path": ttfo["path"],
        "first_tool_s": round(first.first_tool_s, 1) if first and first.first_tool_s is not None else None,
        "sessions": len(sessions), "auto_replies": max(0, len(sessions) - 1),
        # AskUserQuestion calls + turns that ended by asking in text (the last one only if nothing was delivered)
        "questions": sum(s.ask_calls for s in sessions) + sum(1 for s in sessions[:-1] if text_asks(s))
                     + (1 if sessions and text_asks(sessions[-1]) and not picked["primary"] else 0),
        "ask_user_tool_calls": sum(s.ask_calls for s in sessions),
        "tokens": usage, "cost_usd": round(cost, 4), "num_turns": turns, "api_s": round(api_ms / 1000.0, 1),
        "tools": tools, "skills_invoked": [x for s in sessions for x in s.skills_used],
        "subagents": sum(s.subagents for s in sessions),
        "is_error": any(s.result.get("is_error") for s in sessions) or not any(s.result for s in sessions),
        "terminal_reason": [s.result.get("terminal_reason") for s in sessions],
        "result_text": final_text[-4000:],
        "init": {"model": first.init.get("model") if first else None,
                 "version": first.init.get("claude_code_version") if first else None,
                 "skills": first.init.get("skills") if first else None,
                 "plugins": [p.get("name") for p in (first.init.get("plugins") or [])] if first else None,
                 "mcp_servers": first.init.get("mcp_servers") if first else None},
        "deliverable": picked, "stragglers_killed": stragglers,
        "integrity": {"operator_state_unchanged": before == after, "before": before, "after": after},
    })
    common.write_json(rdir / "meta.json", meta)
    common.log("%s/%s: wall %.0fs, ttfo %s, cost $%.2f, primary %s%s" % (
        task["id"], cell_name, wall, ttfo["s"], cost, picked["primary"], " (CAPPED)" if meta["capped"] else ""))
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--task", required=True, help="task id or prefix (t7 or t7-logo-sting)")
    ap.add_argument("--run", required=True, help="run name (folder under runs/)")
    ap.add_argument("--cap-min", type=float, help="time cap in minutes (default: the task's cap_minutes)")
    ap.add_argument("--budget", type=float, default=15.0, help="--max-budget-usd per session (default 15)")
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--max-continues", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--cell", help="the cell's folder name (default: the arm id), e.g. showtime-rep2 for a second run")
    a = ap.parse_args()
    m = run_one(a.arm, a.task, a.run, a.cap_min, a.budget, a.model, a.effort, a.max_continues, a.force, a.cell)
    print(json.dumps({k: m.get(k) for k in ("task", "arm", "wall_s", "ttfo_s", "cost_usd", "num_turns", "questions",
                                            "capped", "is_error")}, indent=2))
    print("primary:", (m.get("deliverable") or {}).get("primary"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
