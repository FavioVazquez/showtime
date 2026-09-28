#!/usr/bin/env python3
"""A stand-in for `claude -p` that exercises the harness without a model or a credential.

Run mode (no --json-schema): prints stream-json like the real CLI (init, one tool call, result) and
renders a 5 s 1280x720 test clip with a tone into ./out/final.mp4 using the ffmpeg on PATH.
With <ws root>/FAKE_ASK present the first session only asks a question; the resumed session (--resume) delivers.
Judge mode (--json-schema): prints one JSON result whose structured_output fits the schema.
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path


def arg(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def judge(schema):
    props = schema.get("properties", {})
    # like a real judge session in stream-json: one Read per frame image the prompt lists, then the result.
    # <bench home>/judge/FAKE_BLIND makes it a judge that opens nothing and says so (the rankers must reject it)
    import re
    blind = (Path(os.environ.get("HOME", ".")).parent / "FAKE_BLIND").exists()
    if not blind:
        for rel in re.findall(r"^\s+(video-\d+/frames/\S+\.(?:jpe?g|png|webp))", arg("-p") or "", re.M):
            emit({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t" + uuid.uuid4().hex[:8], "name": "Read",
                 "input": {"file_path": str(Path.cwd() / rel)}}]}})
    if "ranking" in props:
        labels = props["ranking"]["items"]["enum"]
        crit = props["scores"]["properties"][labels[0]]["required"]
        data = {"ranking": list(labels), "confidence": 3,
                "scores": {l: {c: 7 for c in crit} for l in labels},
                "reason": "I could not open any frame images." if blind else "selftest ranking", "saw_frames": not blind}
    elif "winner" in props:
        crit = props["scores"]["properties"]["1"]["required"]
        data = {"winner": "1", "confidence": 3, "scores": {"1": {c: 7 for c in crit}, "2": {c: 6 for c in crit}},
                "reason": "I could not open any frame images." if blind else "selftest verdict", "saw_frames": not blind}
    else:
        data = {"claims": [{"text": "Brightloom", "where": "screen", "verdict": "not_a_claim", "why": "brand name"}],
                "legibility_problems": []}
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(data),
                      "structured_output": data, "total_cost_usd": 0.0, "num_turns": 1}))


def main():
    schema = arg("--json-schema")
    if schema:
        return judge(json.loads(schema))
    sid = arg("--resume") or str(uuid.uuid4())
    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR", "."))
    skills = sorted(p.name for p in (cfg / "skills").glob("*") if p.is_dir())
    plugins = [{"name": Path(arg("--plugin-dir")).name, "path": arg("--plugin-dir")}] if arg("--plugin-dir") else []
    emit({"type": "system", "subtype": "init", "session_id": sid, "model": arg("--model"), "skills": skills,
          "plugins": plugins, "mcp_servers": [], "claude_code_version": "selftest", "permissionMode": "bypassPermissions"})
    marker = cfg.parent.parent / "FAKE_ASK"  # <ws root>/FAKE_ASK (the harness passes no extra env)
    if marker.exists() and not arg("--resume"):
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "Which colour should I use for the background?"}]}})
        emit({"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "num_turns": 1,
              "result": "Which colour should I use for the background?", "total_cost_usd": 0.0,
              "usage": {"input_tokens": 10, "output_tokens": 5}})
        return 0
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                         "input": {"command": "ffmpeg ..."}}]}})
    Path("out").mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=5:sample_rate=48000",
                    "-filter:a", "volume=0.25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    "-movflags", "+faststart", "out/final.mp4"], check=True)
    emit({"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "num_turns": 3,
          "result": "Done: out/final.mp4 (5 s sting).", "total_cost_usd": 0.0, "duration_api_ms": 10,
          "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
