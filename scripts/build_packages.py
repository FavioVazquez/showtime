#!/usr/bin/env python3
"""Build showtime's MCP distribution packages (stdlib only, any OS, Python 3.8+). Nothing is published.

    python scripts/build_packages.py npm  --out DIR [--pack]   # the npm package (registry: MCP Registry)
    python scripts/build_packages.py mcpb --out DIR            # the MCPB bundle (Smithery, desktop clients)
    python scripts/build_packages.py openai --out DIR           # the OpenAI plugin directory upload (skills only)
    python scripts/build_packages.py all  --out DIR [--pack]

Both carry the skill folder (skills/showtime, without its tests): the MCP server is part of the skill,
has no dependencies and runs showtime through the skill's own launcher, so the package *is* the local
server. The runtime (ffmpeg, models, Node packages, Python venv) is not in either package: `showtime
setup` installs it into ~/.showtime once, and the server's `doctor` tool says when it is missing.

npm   DIR/npm/            staged package (packages/npm/package.json + README, LICENSE, bin/, skill/)
      DIR/*.tgz           with --pack: the tarball `npm publish` would upload (needs npm)
mcpb  DIR/mcpb/           staged bundle (manifest.json, icon.png, server/ = the skill)
      DIR/showtime-<version>.mcpb   the zip archive; its SHA-256 is printed
      DIR/server.json     server.json with the bundle added as a second package (release-asset URL +
                          fileSha256), for publishing to the MCP Registry once the bundle is uploaded

openai DIR/openai/showtime/  staged plugin: plugin.json (Agent Plugins, with its `extensions.com.openai`
                             listing), skills/showtime without tests and without mcp/ (the directory takes skills
                             only, no local MCP server), the icon and logo it names, LICENSE, PRIVACY.md, README.md
       DIR/showtime-<version>-openai-plugin.zip   one top-level folder; upload it at platform.openai.com/plugins
                             (Create plugin > Skills only). No hooks, commands or agents: the directory refuses them.

The bundle's tool list is read from the server itself (initialize + tools/list), so it always matches.
Files come from `git ls-files` (so nothing ignored or untracked ships); outside a git checkout, from a
walk of the folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "showtime"
NPM_TEMPLATE = REPO / "packages" / "npm"
SERVER_JSON = REPO / "server.json"
PLUGIN_JSON = REPO / ".claude-plugin" / "plugin.json"
ICON = REPO / "assets" / "brand" / "icon" / "app-icon-512.png"   # the size desktop clients recommend
GITHUB = "https://github.com/FavioVazquez/showtime"

MCPB_MANIFEST_VERSION = "0.3"
TAGLINE = "A local video studio for your coding agent. Describe a video. Your agent directs. Your machine renders."
SKIP_PARTS = {"tests", "__pycache__", "node_modules", ".DS_Store", "work", "showtime-out"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
# fixed timestamp for reproducible archives (zip cannot store dates before 1980)
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def die(msg: str, fix: str = "") -> None:
    sys.stderr.write("build_packages: %s\n" % msg)
    if fix:
        sys.stderr.write("  fix: %s\n" % fix)
    raise SystemExit(1)


def version() -> str:
    text = (SKILL / "lib" / "st" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        die("no __version__ in skills/showtime/lib/st/__init__.py")
    return m.group(1)


def skill_files() -> List[Path]:
    """Relative paths (to SKILL) of the files that ship: tracked by git, tests and caches left out."""
    rels: List[Path] = []
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=str(SKILL), check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
        rels = [Path(p) for p in out.decode("utf-8").split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        for root, dirs, files in os.walk(SKILL):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for f in files:
                rels.append((Path(root) / f).relative_to(SKILL))
    keep = [r for r in rels if not (set(r.parts) & SKIP_PARTS) and r.suffix not in SKIP_SUFFIXES
            and (SKILL / r).is_file()]
    if not any(r.as_posix() == "mcp/server.mjs" for r in keep):
        die("skills/showtime/mcp/server.mjs is missing from the file list")
    return sorted(keep, key=lambda p: p.as_posix())


def copy_skill(dest: Path) -> int:
    files = skill_files()
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(SKILL / rel), str(target))
    return len(files)


def fresh_dir(d: Path) -> Path:
    if d.exists():
        shutil.rmtree(str(d))
    d.mkdir(parents=True)
    return d


def check_out_dir(out: Path) -> Path:
    out = out.expanduser().resolve()
    try:
        out.relative_to(REPO)
        die("--out %s is inside the repository" % out, "build outside it, e.g. --out ../showtime-dist")
    except ValueError:
        pass
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------------------------- npm

def build_npm(out: Path, pack: bool) -> Dict[str, str]:
    ver = version()
    stage = fresh_dir(out / "npm")
    pkg = json.loads((NPM_TEMPLATE / "package.json").read_text(encoding="utf-8"))
    if pkg.get("version") != ver:
        die("packages/npm/package.json says %s, the skill says %s" % (pkg.get("version"), ver),
            "python scripts/check_release.py   (syncs every version line)")
    server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    if pkg.get("mcpName") != server.get("name"):
        die("package.json mcpName %r differs from server.json name %r" % (pkg.get("mcpName"), server.get("name")))
    (stage / "package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.copy2(str(NPM_TEMPLATE / "README.md"), str(stage / "README.md"))
    shutil.copy2(str(REPO / "LICENSE"), str(stage / "LICENSE"))
    shutil.copytree(str(NPM_TEMPLATE / "bin"), str(stage / "bin"))
    n = copy_skill(stage / "skill")
    for rel in pkg.get("bin", {}).values():
        f = stage / rel
        if not f.is_file():
            die("bin entry %s is missing from the staged package" % rel)
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    res = {"stage": str(stage), "name": pkg["name"], "version": ver, "files": str(n)}
    if pack:
        npm = shutil.which("npm")
        if not npm:
            die("--pack needs npm on PATH")
        cp = subprocess.run([npm, "pack", "--json", "--pack-destination", str(out)], cwd=str(stage),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if cp.returncode != 0:
            die("npm pack failed:\n" + cp.stderr[-2000:])
        info = json.loads(cp.stdout)[0]
        res.update(tarball=str(out / info["filename"]), packed_bytes=str(info.get("size")),
                   unpacked_bytes=str(info.get("unpackedSize")), entries=str(info.get("entryCount")))
    return res


# --------------------------------------------------------------------------------------------- mcpb

def server_tools(entry: Path) -> List[Dict[str, str]]:
    """Ask the staged server for its tools (initialize, then tools/list) over stdio."""
    node = shutil.which("node")
    if not node:
        die("the bundle's tool list is read from the server, which needs node on PATH")
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "build_packages", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SHOWTIME_OPT_", "SHOWTIME_MCP_TRACE"))}
    env["SHOWTIME_MCP_TOOLS"] = "all"          # what the bundle's mcp_config sets
    proc = subprocess.Popen([node, str(entry)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8", env=env)
    tools = None
    try:
        for m in msgs:
            proc.stdin.write(json.dumps(m) + "\n")
            proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == 2:
                tools = (msg.get("result") or {}).get("tools")
                break
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    if not tools:
        die("the staged MCP server did not list its tools:\n" + (proc.stderr.read() or "")[-2000:])
    out = []
    for t in tools:
        desc = re.sub(r"\s+", " ", t.get("description") or t.get("title") or "").strip()
        out.append({"name": t["name"], "description": desc})
    return out


def user_config() -> Dict[str, dict]:
    """The plugin's userConfig as MCPB user_config, plus the projects folder desktop clients lack."""
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    cfg: Dict[str, dict] = {
        "projects": {
            "type": "directory",
            "title": "Projects folder",
            "description": "Where new video projects go and what relative paths resolve against.",
            "default": "${DOCUMENTS}",
            "required": False,
        },
    }
    for key, spec in (plugin.get("userConfig") or {}).items():
        item = {"type": spec.get("type", "string"), "title": spec.get("title", key),
                "description": spec.get("description", ""), "required": False}
        for k in ("default", "min", "max"):
            if k in spec:
                item[k] = spec[k]
        cfg[key] = item
    return cfg


def mcpb_manifest(tools: List[Dict[str, str]]) -> dict:
    ver = version()
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    cfg = user_config()
    # a desktop client has no shell to fall back on: the bundle lists every tool, not only the core loop
    env = {"SHOWTIME_MCP_BASE": "${user_config.projects}", "SHOWTIME_MCP_TOOLS": "all"}
    for key in cfg:
        if key != "projects":
            env["SHOWTIME_OPT_" + key.upper()] = "${user_config.%s}" % key
    return {
        "manifest_version": MCPB_MANIFEST_VERSION,
        "name": "showtime",
        "display_name": "showtime",
        "version": ver,
        "description": "Local video studio for your coding agent: scenes, voice, music and captions, on your machine.",
        "long_description": (
            TAGLINE + "\n\n"
            "showtime renders HTML and canvas scenes frame by frame, and makes voice-over, music, sound effects, "
            "transcripts, captions, QA reports and platform exports on your own computer. No API keys, no uploads.\n\n"
            "**One-time setup.** showtime keeps its tools and models in `~/.showtime`. After installing, ask for the "
            "`doctor` tool: it lists what is missing and the command that installs it."),
        "author": {"name": (plugin.get("author") or {}).get("name", "Favio Vazquez"), "url": "https://github.com/FavioVazquez"},
        "repository": {"type": "git", "url": GITHUB + ".git"},
        "homepage": "https://faviovazquez.github.io/showtime/",
        "documentation": GITHUB + "#readme",
        "support": GITHUB + "/issues",
        "icon": "icon.png",
        "license": plugin.get("license", "MIT"),
        "keywords": ["video", "motion graphics", "voice-over", "music", "captions", "ffmpeg", "local"],
        "server": {
            "type": "node",
            "entry_point": "server/mcp/server.mjs",
            "mcp_config": {"command": "node", "args": ["${__dirname}/server/mcp/server.mjs"], "env": env},
        },
        "tools": tools,
        "tools_generated": False,
        "prompts_generated": False,
        "user_config": cfg,
        "compatibility": {"platforms": ["darwin", "win32", "linux"], "runtimes": {"node": ">=20.0.0"}},
    }


def write_zip(src: Path, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted((p for p in src.rglob("*") if p.is_file()), key=lambda p: p.relative_to(src).as_posix()):
            info = zipfile.ZipInfo(f.relative_to(src).as_posix(), ZIP_DATE)
            mode = 0o755 if os.access(str(f), os.X_OK) else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    os.replace(str(tmp), str(dest))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_mcpb(out: Path) -> Dict[str, str]:
    ver = version()
    stage = fresh_dir(out / "mcpb")
    n = copy_skill(stage / "server")
    shutil.copy2(str(ICON), str(stage / "icon.png"))
    shutil.copy2(str(REPO / "LICENSE"), str(stage / "LICENSE"))
    tools = server_tools(stage / "server" / "mcp" / "server.mjs")
    manifest = mcpb_manifest(tools)
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    bundle = out / ("showtime-%s.mcpb" % ver)
    write_zip(stage, bundle)
    digest = sha256(bundle)
    # server.json with the bundle as a second package, for the MCP Registry after the release upload
    server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
    server["packages"] = [p for p in server.get("packages", []) if p.get("registryType") != "mcpb"] + [{
        "registryType": "mcpb",
        "identifier": "%s/releases/download/v%s/%s" % (GITHUB, ver, bundle.name),
        "version": ver,
        "fileSha256": digest,
        "transport": {"type": "stdio"},
    }]
    (out / "server.json").write_text(json.dumps(server, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"stage": str(stage), "bundle": str(bundle), "sha256": digest, "bytes": str(bundle.stat().st_size),
            "files": str(n + 3), "tools": str(len(tools)), "server_json": str(out / "server.json")}


# ------------------------------------------------------------------------------------ OpenAI plugin

OPENAI_README = """# showtime

A local video studio. Describe a video in one sentence; the model directs and your machine renders it: launch films,
explainers, data stories, repo and paper explainers, release videos and social shorts, with local voice-over, music,
captions and footage editing. Every finished video is checked (text cut off or too small on a phone, reading time,
black or frozen frames, loudness) and reviewed before you see it. Nothing is uploaded; no cloud AI services or keys.

First run: the skill runs `showtime setup` once, which installs its open tools and models into `~/.showtime`
(it says what it downloads and how big it is).

Source, docs and examples: https://github.com/FavioVazquez/showtime (MIT)
"""


def build_openai(out: Path) -> Dict[str, str]:
    """The OpenAI plugin directory package: skills only (no hooks, no local MCP server, no commands or agents)."""
    ver = version()
    manifest = json.loads((REPO / "plugin.json").read_text(encoding="utf-8"))
    ui = ((manifest.get("extensions") or {}).get("com.openai") or {}).get("interface") or {}
    for key, limit in (("displayName", 30), ("shortDescription", 30), ("longDescription", 4000), ("developerName", 80)):
        if not ui.get(key) or len(ui[key]) > limit:
            die("plugin.json extensions.com.openai.interface.%s is missing or longer than %d characters" % (key, limit))
    if len(ui.get("defaultPrompt") or []) > 3 or any(len(x) > 128 for x in ui.get("defaultPrompt") or []):
        die("plugin.json defaultPrompt: at most 3 prompts of 128 characters")
    if manifest.get("version") != ver:
        die("plugin.json version %s is not %s" % (manifest.get("version"), ver), "python scripts/check_release.py")
    for banned in ("hooks", "apps"):
        if banned in manifest["extensions"]["com.openai"]:
            die("plugin.json extensions.com.openai.%s: the directory refuses %s for now" % (banned, banned))
    root = fresh_dir(out / "openai") / "showtime"
    n = copy_skill(root / "skills" / "showtime")
    shutil.rmtree(str(root / "skills" / "showtime" / "mcp"), ignore_errors=True)   # no local MCP server
    for key in ("composerIcon", "logo", "composerIconDark", "logoDark"):
        rel = ui.get(key)
        if rel:
            src = (REPO / rel).resolve()
            if not src.is_file():
                die("plugin.json %s: %s not found" % (key, rel))
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
    for name in ("LICENSE", "PRIVACY.md"):
        shutil.copy2(str(REPO / name), str(root / name))
    (root / "README.md").write_text(OPENAI_README, encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    skill_md = (root / "skills" / "showtime" / "SKILL.md").read_text(encoding="utf-8")
    if not skill_md.startswith("---\n") or "\nname:" not in skill_md.split("\n---", 1)[0] \
            or "\ndescription:" not in skill_md.split("\n---", 1)[0]:
        die("skills/showtime/SKILL.md has no YAML header with name and description")
    for bad in ("hooks", "mcp.json", ".mcp.json", ".claude-plugin", "agents", "commands"):
        if (root / bad).exists():
            die("the OpenAI package must not contain %s" % bad)
    if any(p.suffix == ".mcpb" for p in root.rglob("*")):
        die("the OpenAI package must not contain a .mcpb file")
    zpath = out / ("showtime-%s-openai-plugin.zip" % ver)
    write_zip(out / "openai", zpath)
    files = sum(1 for p in root.rglob("*") if p.is_file())
    return {"stage": str(root), "zip": str(zpath), "sha256": sha256(zpath), "bytes": str(zpath.stat().st_size),
            "files": str(files)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="examples:\n  python scripts/build_packages.py all --out ../showtime-dist --pack\n"
                                        "  python scripts/build_packages.py mcpb --out ../showtime-dist --json")
    ap.add_argument("what", choices=["npm", "mcpb", "openai", "all"])
    ap.add_argument("--out", required=True, type=Path, help="output folder, outside the repository")
    ap.add_argument("--pack", action="store_true", help="npm: also run `npm pack` (the exact tarball, no upload)")
    ap.add_argument("--json", action="store_true", help="print the results as JSON")
    a = ap.parse_args(argv)
    out = check_out_dir(a.out)
    res: Dict[str, Dict[str, str]] = {}
    if a.what in ("npm", "all"):
        res["npm"] = build_npm(out, a.pack)
    if a.what in ("mcpb", "all"):
        res["mcpb"] = build_mcpb(out)
    if a.what in ("openai", "all"):
        res["openai"] = build_openai(out)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        for kind, r in res.items():
            print("%s:" % kind)
            for k, v in r.items():
                print("  %-14s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
