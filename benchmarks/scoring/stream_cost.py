#!/usr/bin/env python3
"""Where did a run's tokens go? Reads a Claude Code stream-json file (stream.jsonl).

Reports, for the main agent (sub-agents separately):
  - cost, turns (from the result line)
  - images that entered the main context, and which tool call produced each one
  - max and median context per model call (input + cache read + cache write)
  - the largest non-image tool outputs (by characters), with the command that produced them

Usage:
  python3 benchmarks/scoring/stream_cost.py <stream.jsonl> [...] [--json] [--top N]
  python3 benchmarks/scoring/stream_cost.py runs/*/*/stream.jsonl --summary
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List


def _label(tool: Dict) -> str:
    name = tool.get("name", "?")
    inp = tool.get("input") or {}
    if name == "Bash":
        cmd = " ".join(str(inp.get("command", "")).split())
        return f"Bash: {cmd[:140]}"
    if name == "Read":
        return f"Read: {inp.get('file_path', '')}"
    if name in ("Task", "Agent"):
        return f"{name}: {inp.get('subagent_type', '')} {str(inp.get('description', ''))[:60]}"
    short = name.replace("mcp__plugin_showtime_showtime__", "mcp:")
    args = json.dumps(inp)[:120]
    return f"{short} {args}"


def _text_len(content) -> int:
    if isinstance(content, str):
        return len(content)
    n = 0
    for b in content or []:
        if b.get("type") == "text":
            n += len(b.get("text", ""))
    return n


def analyse(path: Path, top: int = 10) -> Dict:
    tools: Dict[str, Dict] = {}
    calls: Dict[str, Dict] = {}          # message id -> {ctx, main}
    images_main: List[str] = []
    images_sub: List[str] = []
    outputs: List[Dict] = []
    result = None
    for line in path.read_text(errors="replace").splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        typ = m.get("type")
        main = not m.get("parent_tool_use_id")
        if typ == "assistant":
            msg = m.get("message") or {}
            for b in msg.get("content") or []:
                if b.get("type") == "tool_use":
                    tools[b["id"]] = b
            u = msg.get("usage") or {}
            ctx = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                + (u.get("cache_creation_input_tokens") or 0)
            mid = msg.get("id") or m.get("uuid")
            if ctx and mid:
                prev = calls.get(mid)
                if not prev or ctx > prev["ctx"]:
                    calls[mid] = {"ctx": ctx, "main": main}
        elif typ == "user":
            content = (m.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if b.get("type") != "tool_result":
                    continue
                src = tools.get(b.get("tool_use_id"), {})
                label = _label(src) if src else "?"
                inner = b.get("content")
                imgs = [x for x in inner if isinstance(x, dict) and x.get("type") == "image"] \
                    if isinstance(inner, list) else []
                for _ in imgs:
                    (images_main if main else images_sub).append(label)
                n = _text_len(inner)
                if main and n:
                    outputs.append({"chars": n, "tool": label})
        elif typ == "result":
            result = m    # keep the last one (a follow-up result carries the final totals)
    main_ctx = [c["ctx"] for c in calls.values() if c["main"]]
    outputs.sort(key=lambda o: -o["chars"])
    by_src: Dict[str, int] = {}
    for lab in images_main:
        key = lab.split(":", 1)[0] if lab.startswith("Read:") else lab[:80]
        if lab.startswith("Read:"):
            key = "Read " + Path(lab[5:].strip()).suffix
        by_src[key] = by_src.get(key, 0) + 1
    return {
        "file": str(path),
        "cost_usd": round(result.get("total_cost_usd", 0), 2) if result else None,
        "turns": result.get("num_turns") if result else None,
        "images_main": len(images_main),
        "images_sub": len(images_sub),
        "image_sources": dict(sorted(by_src.items(), key=lambda kv: -kv[1])),
        "image_calls": images_main,
        "calls_main": len(main_ctx),
        "ctx_max": max(main_ctx) if main_ctx else 0,
        "ctx_median": int(statistics.median(main_ctx)) if main_ctx else 0,
        "tool_output_chars": sum(o["chars"] for o in outputs),
        "largest_outputs": outputs[:top],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("streams", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true", help="one line per stream")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    rows = [analyse(Path(p), a.top) for p in a.streams]
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    for r in rows:
        print(f"{r['file']}: ${r['cost_usd']}  turns {r['turns']}  images main {r['images_main']}"
              f" (sub-agents {r['images_sub']})  ctx max {r['ctx_max'] // 1000}k median {r['ctx_median'] // 1000}k"
              f"  calls {r['calls_main']}  tool text {r['tool_output_chars'] // 1000}k chars")
        if a.summary:
            continue
        for src, n in r["image_sources"].items():
            print(f"    {n:3d} images  {src}")
        print("  largest text outputs:")
        for o in r["largest_outputs"]:
            print(f"    {o['chars']:7d}  {o['tool']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
