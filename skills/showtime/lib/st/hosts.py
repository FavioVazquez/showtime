"""Install showtime into another agent host: `showtime install --agent <host>` (stdlib only, Python 3.8+).

Three pieces per host, each optional:

  skill   a link to (or copy of) the skill folder where the host looks for skills, for hosts that do not
          read the shared ~/.agents/skills folder (Kiro, Cline, Qwen ...) or when no host has it yet
  crew    the ten crew agents (the plugin's agents/*.md) translated to the host's own agent format:
          Codex TOML with developer_instructions, OpenCode `mode: subagent`, Gemini tool names and a raised
          timeout_mins, Kiro JSON ... Claude-only fields and model aliases are dropped
  mcp     the MCP server entry in the host's config file, launched through the stable command
          <SHOWTIME_HOME>/bin/showtime mcp, so no host variable is needed

Every file it writes carries a marker, so `--uninstall` removes exactly what it made and nothing else;
running install twice changes nothing the second time. Config files that hold other settings are merged
(only the "showtime" entry is touched, a one-time backup is kept next to the file) and are left alone
when they cannot be parsed (JSON with comments, YAML): the entry to paste is printed instead. `--print`
shows everything without writing. A small ledger (<home>/installs.json) keeps shared pieces, such as a
skill link in ~/.agents/skills that several hosts read, until the last host using them is uninstalled.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import shim

MARK = "generated from the showtime crew"
SKILL_MARK_FILE = ".showtime-install"          # inside a copied skill folder
LEDGER = "installs.json"
SERVER = "showtime"
BLOCK_BEGIN = "# >>> showtime mcp server (showtime install; remove with: showtime install --agent codex --uninstall)"
BLOCK_END = "# <<< showtime mcp server"
CLAUDE_ROOT_PHRASE = "(Claude Code also fills it in: `${CLAUDE_PLUGIN_ROOT}/skills/showtime`)"

# Claude tool names -> the host's names. Hosts missing here get no tool list (their agents inherit every tool).
TOOL_MAP = {
    "copilot": {"Read": "read", "Glob": "search", "Grep": "search", "Write": "edit", "Edit": "edit",
                "Bash": "execute", "PowerShell": "execute", "WebFetch": "web", "WebSearch": "web"},
    "gemini": {"Read": ["read_file", "read_many_files", "list_directory"], "Glob": "glob", "Grep": "grep_search",
               "Write": "write_file", "Edit": "replace", "Bash": "run_shell_command",
               "PowerShell": "run_shell_command", "WebFetch": "web_fetch", "WebSearch": "google_web_search"},
}
# OpenCode switches tools off by name; a Claude tool missing from an agent turns these off
OPENCODE_OFF = {"Bash": ["bash"], "Edit": ["edit", "patch"], "Write": ["write"], "WebFetch": ["webfetch"]}
GEMINI_TIMEOUT_MINS = 60          # default 10 would stop a crew member supervising a render


# --------------------------------------------------------------------------- hosts

class Host:
    def __init__(self, key: str, label: str, skill: Tuple[str, str], crew: Optional[Tuple[str, str, str]],
                 mcp: Optional[Tuple[str, str, Optional[str]]], notes: Sequence[str] = (), docs: str = ""):
        self.key, self.label = key, label
        self.skill_user, self.skill_project = skill            # folder that holds skill folders
        self.crew = crew                                        # (format, user dir, project dir)
        self.mcp = mcp                                          # (format, user file, project file or None)
        self.notes = list(notes)
        self.docs = docs


AGENTS_SKILLS = ("~/.agents/skills", ".agents/skills")
HOSTS: Dict[str, Host] = {h.key: h for h in [
    Host("claude", "Claude Code", ("~/.claude/skills", ".claude/skills"),
         ("claude", "~/.claude/agents", ".claude/agents"), ("claude-cli", "", None),
         ["The plugin is the easiest route in Claude Code: /plugin marketplace add FavioVazquez/showtime"]),
    Host("codex", "OpenAI Codex", AGENTS_SKILLS,
         ("codex", "~/.codex/agents", ".codex/agents"), ("codex-toml", "~/.codex/config.toml", ".codex/config.toml"),
         ["Codex never starts sub-agents by itself: ask for them (\"spawn the scriptwriter agent\").",
          "Setup and renders write to ~/.showtime and setup needs the network. In the workspace-write sandbox add "
          "to ~/.codex/config.toml:  [sandbox_workspace_write]  network_access = true  writable_roots = "
          "[\"%(home)s\"]  (or run `showtime setup` once in a normal terminal)."]),
    Host("copilot", "GitHub Copilot (CLI and VS Code)", AGENTS_SKILLS,
         ("copilot", "~/.copilot/agents", ".github/agents"), ("json:mcpServers:copilot", "~/.copilot/mcp-config.json",
                                                            ".github/mcp.json"),
         ["VS Code reads MCP servers from its own settings: run \"MCP: Add Server\" with the command shown above."]),
    Host("cursor", "Cursor (editor and CLI)", AGENTS_SKILLS,
         ("cursor", "~/.cursor/agents", ".cursor/agents"), ("json:mcpServers:stdio", "~/.cursor/mcp.json",
                                                          ".cursor/mcp.json"),
         ["Cursor's sandbox limits network to sandbox.json: run `showtime setup` once in a normal terminal."]),
    Host("devin", "Devin (CLI and Desktop)", AGENTS_SKILLS,
         ("devin", "@devin/agents", ".devin/agents"), ("json:mcpServers:plain", "@devin/mcp_config.json",
                                                      ".devin/mcp_config.json"),
         ["Devin asks before each MCP tool by default; allow them with permissions.allow `mcp__showtime__*`."]),
    Host("gemini", "Gemini CLI", AGENTS_SKILLS,
         ("gemini", "~/.gemini/agents", ".gemini/agents"), ("json:mcpServers:gemini", "~/.gemini/settings.json",
                                                          ".gemini/settings.json"),
         ["Gemini CLI stops a shell command after 300 s without output; showtime prints a progress line "
          "every 45 s, and long renders can run with --background."]),
    Host("antigravity", "Antigravity CLI", ("~/.gemini/antigravity-cli/skills", ".agents/skills"),
         ("antigravity", "~/.gemini/config/agents", ".agents/agents"), ("json:mcpServers:plain",
                                                                         "~/.gemini/config/mcp_config.json",
                                                                         ".agents/mcp_config.json"),
         ["Antigravity's terminal sandbox has no network by default: run `showtime setup` once in a normal "
          "terminal, and allow writes to %(home)s."]),
    Host("opencode", "OpenCode", AGENTS_SKILLS,
         ("opencode", "~/.config/opencode/agents", ".opencode/agents"), ("json:mcp:opencode",
                                                                        "~/.config/opencode/opencode.json",
                                                                        "opencode.json")),
    Host("cline", "Cline", ("~/.cline/skills", ".cline/skills"), None,
         ("json:mcpServers:cline", "~/.cline/mcp.json", None),
         ["Cline's sub-agents cannot use MCP servers, so no crew is installed; the skill does every step itself.",
          "In the Cline extension add the same entry under MCP Servers > Configure MCP Servers."]),
    Host("kilo", "Kilo Code", AGENTS_SKILLS, None, ("print", "", None),
         ["Add the MCP server in Kilo's MCP settings with the command shown above."]),
    Host("kiro", "Kiro (IDE and CLI)", ("~/.kiro/skills", ".kiro/skills"),
         ("kiro", "~/.kiro/agents", ".kiro/agents"), ("json:mcpServers:kiro", "~/.kiro/settings/mcp.json",
                                                     ".kiro/settings/mcp.json")),
    Host("zed", "Zed", AGENTS_SKILLS, None, ("json:context_servers:zed", "@zed/settings.json", ".zed/settings.json"),
         ["Zed has no custom agent files, so no crew is installed; the skill does every step itself.",
          "Zed loads project skills only in trusted worktrees."]),
    Host("goose", "Goose", AGENTS_SKILLS, None, ("print-goose", "", None),
         ["Goose keeps extensions in its config.yaml: run `goose configure` > Add Extension > Command-line "
          "Extension, or paste the block shown above."]),
    Host("amp", "Amp", AGENTS_SKILLS, None, ("json:amp.mcpServers:plain", "~/.config/amp/settings.json",
                                             ".amp/settings.json")),
    Host("factory", "Factory Droid", ("~/.factory/skills", ".factory/skills"),
         ("factory", "~/.factory/droids", ".factory/droids"), ("json:mcpServers:stdio", "~/.factory/mcp.json",
                                                             ".factory/mcp.json")),
    Host("qwen", "Qwen Code", ("~/.qwen/skills", ".qwen/skills"),
         ("qwen", "~/.qwen/agents", ".qwen/agents"), ("json:mcpServers:gemini", "~/.qwen/settings.json",
                                                     ".qwen/settings.json")),
]}
ALIASES = {"claude-code": "claude", "github-copilot": "copilot", "vscode": "copilot", "gemini-cli": "gemini",
           "agy": "antigravity", "cursor-agent": "cursor", "droid": "factory", "kilocode": "kilo",
           "qwen-code": "qwen", "windsurf": "devin"}


def resolve_host(name: str) -> Host:
    key = ALIASES.get(name.strip().lower(), name.strip().lower())
    if key not in HOSTS:
        raise KeyError(name)
    return HOSTS[key]


# --------------------------------------------------------------------------- paths

class Where:
    """Where things go: the user's home folder for `--scope user`, a project folder for `--project`."""

    def __init__(self, user_home: Path, project: Optional[Path] = None, windows: Optional[bool] = None,
                 appdata: Optional[Path] = None):
        self.user_home = Path(user_home)
        self.project = Path(project) if project else None
        self.windows = os.name == "nt" if windows is None else windows
        self.appdata = Path(appdata) if appdata else (Path(os.environ["APPDATA"]) if os.environ.get("APPDATA")
                                                      else self.user_home / "AppData" / "Roaming")

    @property
    def scope(self) -> str:
        return "project" if self.project else "user"

    def path(self, user_spec: str, project_spec: Optional[str]) -> Optional[Path]:
        if self.project:
            return (self.project / project_spec) if project_spec else None
        if not user_spec:
            return None
        if user_spec.startswith("@devin/"):
            rest = user_spec[len("@devin/"):]
            return (self.appdata / "devin" / rest) if self.windows else self.user_home / ".config" / "devin" / rest
        if user_spec.startswith("@zed/"):
            rest = user_spec[len("@zed/"):]
            return (self.appdata / "Zed" / rest) if self.windows else self.user_home / ".config" / "zed" / rest
        return self.user_home / user_spec[2:] if user_spec.startswith("~/") else Path(user_spec)


# --------------------------------------------------------------------------- the crew

def parse_agent(text: str) -> Tuple[Dict[str, str], str]:
    """(frontmatter as flat strings, body) of a Claude agent file."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not m:
        raise ValueError("no frontmatter")
    meta: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2).lstrip("\n")


def crew_sources(skill: Path) -> List[Path]:
    """The ten Claude agent files: the plugin's agents/ next to the skill when it is there (a clone or an
    installed plugin), else the copy the skill carries (setup/agents/, for a skill installed on its own)."""
    for d in (Path(skill).parent.parent / "agents", Path(skill) / "setup" / "agents"):
        files = sorted(d.glob("*.md")) if d.is_dir() else []
        if files and all(_looks_like_agent(f) for f in files):
            return files
    return []


def _looks_like_agent(f: Path) -> bool:
    try:
        meta, _ = parse_agent(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return bool(meta.get("name")) and "showtime crew" in meta.get("description", "")


def load_crew(skill: Path) -> List[Tuple[Dict[str, str], str]]:
    return [parse_agent(f.read_text(encoding="utf-8")) for f in crew_sources(skill)]


def claude_tools(meta: Dict[str, str]) -> List[str]:
    return [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]


PLUGIN_REF = "@plugin"      # skill_ref for agent files shipped inside the plugin itself (no absolute path known)


def host_body(body: str, skill_ref: str) -> str:
    """The agent body with the Claude-only plugin variable replaced by where the skill really is."""
    if skill_ref == PLUGIN_REF:
        return body.replace(CLAUDE_ROOT_PHRASE, "(in an installed plugin: its `skills/showtime` folder)")
    return body.replace(CLAUDE_ROOT_PHRASE, "(on this machine: `%s`)" % skill_ref)


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)          # a JSON string is a valid YAML double-quoted scalar


def _yaml_list(items: Sequence[str]) -> str:
    return "[" + ", ".join(_yaml_str(i) for i in items) + "]"


def _mapped_tools(host: str, tools: Sequence[str]) -> List[str]:
    out: List[str] = []
    table = TOOL_MAP[host]
    for t in tools:
        v = table.get(t)
        for x in ([v] if isinstance(v, str) else (v or [])):
            if x not in out:
                out.append(x)
    return out


def _frontmatter(pairs: Sequence[Tuple[str, str]], body: str, tail_comment: bool = True) -> str:
    lines = ["---"] + ["%s: %s" % (k, v) for k, v in pairs] + ["---", ""]
    head = "\n".join(lines)
    note = "<!-- %s; edit the source in the showtime plugin, not here -->\n\n" % MARK
    return head + (note if tail_comment else "") + body.rstrip("\n") + "\n"


def _toml_multiline(s: str) -> str:
    if "'''" not in s:
        return "'''\n" + s.rstrip("\n") + "\n'''"
    esc = s.replace("\\", "\\\\").replace('"""', '\\"""')
    return '"""\n' + esc.rstrip("\n") + '\n"""'


def render_agent(host: str, meta: Dict[str, str], body: str, skill_ref: str) -> Tuple[str, str]:
    """(file name, content) of one crew agent for `host`."""
    name, desc = meta["name"], meta.get("description", "")
    tools = claude_tools(meta)
    b = host_body(body, skill_ref)
    turns = meta.get("maxTurns", "")
    if host == "claude":
        pairs = [(k, v) for k, v in meta.items()]
        return name + ".md", _frontmatter(pairs, b)
    if host == "codex":
        text = ("# %s; edit the source in the showtime plugin, not here\n"
                "name = %s\ndescription = %s\ndeveloper_instructions = %s\n"
                % (MARK, json.dumps(name), json.dumps(desc, ensure_ascii=False), _toml_multiline(b)))
        return name + ".toml", text
    if host == "copilot":
        pairs = [("name", name), ("description", _yaml_str(desc)), ("tools", _yaml_list(_mapped_tools("copilot", tools)))]
        return name + ".agent.md", _frontmatter(pairs, b)
    if host == "cursor":
        return name + ".md", _frontmatter([("name", name), ("description", _yaml_str(desc)), ("model", "inherit")], b)
    if host in ("devin", "qwen"):
        return name + ".md", _frontmatter([("name", name), ("description", _yaml_str(desc))], b)
    if host == "factory":
        return name + ".md", _frontmatter([("name", name), ("description", _yaml_str(desc)), ("model", "inherit")], b)
    if host == "antigravity":
        return name + ".md", _frontmatter([("name", name), ("description", _yaml_str(desc)), ("model", "inherit")], b)
    if host == "gemini":
        pairs = [("name", name), ("description", _yaml_str(desc)),
                 ("tools", _yaml_list(_mapped_tools("gemini", tools))), ("timeout_mins", str(GEMINI_TIMEOUT_MINS))]
        if turns.isdigit():
            pairs.append(("max_turns", turns))
        return name + ".md", _frontmatter(pairs, b)
    if host == "opencode":
        off = sorted({x for t, xs in OPENCODE_OFF.items() if t not in tools for x in xs})
        pairs = [("description", _yaml_str(desc)), ("mode", "subagent")]
        if off:
            pairs.append(("tools", "{" + ", ".join("%s: false" % x for x in off) + "}"))
        return name + ".md", _frontmatter(pairs, b)
    if host == "kiro":
        data = {"name": name, "description": desc, "prompt": b, "tools": ["*"],
                "resources": ["skill://%s/SKILL.md" % skill_ref.replace("\\", "/")],
                "_generated": "%s; edit the source in the showtime plugin, not here" % MARK}
        return name + ".json", json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    raise KeyError(host)


def is_ours(path: Path) -> bool:
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            return MARK in fh.read(4096)
    except OSError:
        return False


# --------------------------------------------------------------------------- MCP entries

def mcp_command(home: Path, windows: Optional[bool] = None) -> List[str]:
    """[command, args...] of the MCP server: the stable launcher in <home>/bin, which finds the newest skill."""
    windows = os.name == "nt" if windows is None else windows
    return [str(Path(home) / "bin" / ("showtime.cmd" if windows else "showtime")), "mcp"]


def mcp_entry(style: str, cmd: List[str]) -> Dict[str, Any]:
    c, args = cmd[0], cmd[1:]
    if style == "copilot":
        return {"type": "local", "command": c, "args": args, "tools": ["*"]}
    if style == "stdio":
        return {"type": "stdio", "command": c, "args": args}
    if style == "gemini":
        return {"command": c, "args": args, "timeout": 600000}
    if style == "cline":
        return {"command": c, "args": args, "timeout": 3600, "disabled": False, "autoApprove": []}
    if style == "kiro":
        return {"command": c, "args": args, "disabled": False}
    if style == "zed":
        return {"command": c, "args": args, "env": {}}
    if style == "opencode":
        return {"type": "local", "command": cmd, "enabled": True}
    return {"command": c, "args": args}


def codex_block(cmd: List[str]) -> str:
    return "\n".join([BLOCK_BEGIN, "[mcp_servers.%s]" % SERVER, "command = %s" % json.dumps(cmd[0]),
                      "args = %s" % json.dumps(cmd[1:]), "startup_timeout_sec = 30", "tool_timeout_sec = 600",
                      BLOCK_END]) + "\n"


def goose_block(cmd: List[str]) -> str:
    return ("extensions:\n  %s:\n    name: %s\n    type: stdio\n    cmd: %s\n    args: %s\n    enabled: true\n"
            "    timeout: 600\n" % (SERVER, SERVER, json.dumps(cmd[0]), json.dumps(cmd[1:])))


def claude_cli_line(cmd: List[str], project: bool) -> str:
    return "claude mcp add --scope %s %s -- %s" % ("project" if project else "user", SERVER,
                                                  " ".join(_shell_quote(x) for x in cmd))


def _shell_quote(s: str) -> str:
    return s if re.match(r"^[\w@%+=:,./\\-]+$", s) else json.dumps(s)


# --------------------------------------------------------------------------- actions

class Plan:
    """What an install or uninstall does, before and after it runs (also the --print and --json output)."""

    def __init__(self, host: Host, where: Where):
        self.host, self.where = host, where
        self.actions: List[Dict[str, Any]] = []
        self.notes: List[str] = []

    def add(self, kind: str, path: Optional[Path], state: str, detail: str = "", content: str = "") -> None:
        self.actions.append({"kind": kind, "path": str(path) if path else None, "state": state,
                             "detail": detail, "content": content})

    def as_json(self) -> Dict[str, Any]:
        return {"host": self.host.key, "label": self.host.label, "scope": self.where.scope,
                "actions": [{k: v for k, v in a.items() if k != "content"} for a in self.actions],
                "notes": self.notes}


def _read(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".%s.%d.tmp" % (p.name, os.getpid()))
    with open(str(tmp), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(str(tmp), str(p))


def _backup_once(p: Path) -> None:
    b = p.with_name(p.name + ".before-showtime")
    if p.is_file() and not b.exists():
        shutil.copy2(str(p), str(b))


# ----- skill link

def _link_target(p: Path) -> Optional[Path]:
    """Where a symlink or a Windows junction points, else None."""
    try:
        if p.is_symlink():
            return Path(os.path.realpath(str(p)))
        if os.name == "nt" and p.is_dir():
            r = os.path.realpath(str(p))
            if os.path.normcase(r) != os.path.normcase(os.path.abspath(str(p))):
                return Path(r)
    except OSError:
        return None
    return None


def durable_skill(home: Path, skill: Path) -> Path:
    """The skill folder a host link should point at: the skill itself, or for one that lives somewhere its
    package manager replaces or deletes (npx's cache, a versioned plugin cache) a copy in <home>/skill."""
    s = Path(skill)
    parts = [x.lower() for x in s.resolve().parts] if s.exists() else []
    versioned = "cache" in parts and ("plugins" in parts or "installed-plugins" in parts)
    if shim.is_ephemeral(s) or versioned:
        return shim.stable_skill(home, s, force=True)
    return s


def _make_link(src: Path, dest: Path) -> str:
    """Symlink, else (Windows without the privilege) a junction, else a marked copy. The method used."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(src), str(dest), target_is_directory=True)
        return "link"
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(dest), str(src)], capture_output=True)
        if r.returncode == 0:
            return "junction"
    shutil.copytree(str(src), str(dest), ignore=shutil.ignore_patterns(*shim.COPY_SKIP))
    (dest / SKILL_MARK_FILE).write_text("copied by `showtime install` from %s\n" % src, encoding="utf-8")
    return "copy"


def plan_skill(plan: Plan, skill_src: Path, write: bool) -> None:
    h, w = plan.host, plan.where
    parent = w.path(h.skill_user, h.skill_project)
    if parent is None:
        return
    dest = parent / "showtime"
    tgt = _link_target(dest)
    if tgt is not None:
        if shim._same(tgt, skill_src):  # noqa: SLF001
            plan.add("skill", dest, "unchanged", "links to %s" % skill_src)
            return
        if not shim.valid_skill(tgt) and tgt.exists():
            plan.add("skill", dest, "skipped", "a link to something else is there (%s); left alone" % tgt)
            return
        if write:
            _unlink(dest)
            how = _make_link(skill_src, dest)
            plan.add("skill", dest, "updated", "%s -> %s (was %s)" % (how, skill_src, tgt))
        else:
            plan.add("skill", dest, "would update", "link -> %s (now %s)" % (skill_src, tgt))
        return
    if dest.exists():
        if (dest / SKILL_MARK_FILE).is_file():
            if shim.skill_version(dest) >= shim.skill_version(skill_src):
                plan.add("skill", dest, "unchanged", "copy of showtime %s" % ".".join(map(str, shim.skill_version(dest))))
                return
            if write:
                shutil.rmtree(str(dest))
                how = _make_link(skill_src, dest)
                plan.add("skill", dest, "updated", "%s of %s" % (how, skill_src))
            else:
                plan.add("skill", dest, "would update", "older copy, replaced by %s" % skill_src)
            return
        if shim.valid_skill(dest):
            same = shim._same(dest, skill_src)  # noqa: SLF001
            plan.add("skill", dest, "unchanged", "this is the running skill" if same else
                     "showtime is already installed here (not by this command); left as it is")
            return
        plan.add("skill", dest, "skipped", "something else named showtime is there; left alone")
        return
    if write:
        how = _make_link(skill_src, dest)
        plan.add("skill", dest, "created", "%s -> %s" % (how, skill_src))
    else:
        plan.add("skill", dest, "would create", "link -> %s" % skill_src)


def _unlink(p: Path) -> None:
    if p.is_symlink():
        p.unlink()
    elif os.name == "nt" and _link_target(p) is not None:
        os.rmdir(str(p))                         # a junction: removes the link, not the target
    elif p.is_dir():
        shutil.rmtree(str(p))


def unplan_skill(plan: Plan, skill_src: Optional[Path], write: bool, shared_users: Sequence[str]) -> None:
    h, w = plan.host, plan.where
    parent = w.path(h.skill_user, h.skill_project)
    if parent is None:
        return
    dest = parent / "showtime"
    ours = _link_target(dest) is not None and shim.valid_skill(_link_target(dest)) or (dest / SKILL_MARK_FILE).is_file()
    if not ours:
        if dest.exists() or dest.is_symlink():
            plan.add("skill", dest, "kept", "not made by showtime install")
        return
    if shared_users:
        plan.add("skill", dest, "kept", "still used by %s" % ", ".join(shared_users))
        return
    if write:
        _unlink(dest)
    plan.add("skill", dest, "removed" if write else "would remove")


# ----- crew

def plan_crew(plan: Plan, skill_src: Path, skill_ref: str, write: bool) -> None:
    h, w = plan.host, plan.where
    if not h.crew:
        return
    fmt, user_dir, proj_dir = h.crew
    d = w.path(user_dir, proj_dir)
    if d is None:
        return
    crew = load_crew(skill_src)
    if not crew:
        plan.add("crew", d, "skipped", "the crew files were not found next to the skill")
        return
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for meta, body in crew:
        fname, text = render_agent(fmt, meta, body, skill_ref)
        p = d / fname
        cur = _read(p)
        if cur == text:
            counts["unchanged"] += 1
            continue
        if cur is not None and not is_ours(p):
            counts["skipped"] += 1
            plan.add("crew", p, "skipped", "a file not made by showtime install is there; left alone")
            continue
        counts["updated" if cur is not None else "created"] += 1
        if write:
            _write(p, text)
        else:
            plan.add("crew", p, "would write", "", text)
    summary = ", ".join("%d %s" % (n, k) for k, n in counts.items() if n)
    plan.add("crew", d, ("done" if write else "plan"), "%d agents (%s)" % (len(crew), summary))


def unplan_crew(plan: Plan, skill_src: Optional[Path], write: bool) -> None:
    h, w = plan.host, plan.where
    if not h.crew:
        return
    fmt, user_dir, proj_dir = h.crew
    d = w.path(user_dir, proj_dir)
    if d is None or not d.is_dir():
        return
    n = 0
    for p in sorted(d.iterdir()):
        if p.is_file() and is_ours(p):
            n += 1
            if write:
                p.unlink()
    if n:
        plan.add("crew", d, "removed" if write else "would remove", "%d agents" % n)


# ----- MCP

def _json_load(p: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(data, error). A missing or empty file is an empty object."""
    text = _read(p)
    if text is None:
        return ({}, None) if not p.exists() else (None, "cannot read it")
    if not text.strip():
        return {}, None
    try:
        data = json.loads(text)
    except ValueError as e:
        return None, "it is not plain JSON (%s)" % e.msg
    if not isinstance(data, dict):
        return None, "it does not hold a JSON object"
    return data, None


def _json_dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def plan_mcp(plan: Plan, home: Path, write: bool) -> None:
    h, w = plan.host, plan.where
    if not h.mcp:
        return
    fmt, user_file, proj_file = h.mcp
    cmd = mcp_command(home, w.windows)
    if fmt == "claude-cli":
        plan.add("mcp", None, "run", "run this once: " + claude_cli_line(cmd, bool(w.project)))
        return
    if fmt == "print":
        plan.add("mcp", None, "paste", "command: %s  args: %s" % (cmd[0], json.dumps(cmd[1:])))
        return
    if fmt == "print-goose":
        plan.add("mcp", None, "paste", "add to ~/.config/goose/config.yaml:", goose_block(cmd))
        return
    p = w.path(user_file, proj_file)
    if p is None:
        plan.add("mcp", None, "paste", "no project-level config for this host; add it for your user with "
                 "`showtime install --agent %s`" % h.key)
        return
    if fmt == "codex-toml":
        _plan_codex(plan, p, cmd, write)
        return
    _, key, style = fmt.split(":")
    entry = mcp_entry(style, cmd)
    data, err = _json_load(p)
    snippet = _json_dump({key: {SERVER: entry}})
    if data is None:
        plan.add("mcp", p, "paste", "left alone: %s. Add this entry by hand:" % err, snippet)
        return
    section = data.get(key)
    if section is not None and not isinstance(section, dict):
        plan.add("mcp", p, "paste", "left alone: %r is not an object. Add this entry by hand:" % key, snippet)
        return
    if (section or {}).get(SERVER) == entry:
        plan.add("mcp", p, "unchanged", "%s.%s" % (key, SERVER))
        return
    state = "updated" if (section or {}).get(SERVER) is not None else "created"
    if write:
        _backup_once(p)
        data.setdefault(key, {})[SERVER] = entry
        _write(p, _json_dump(data))
        plan.add("mcp", p, state, "%s.%s" % (key, SERVER))
    else:
        plan.add("mcp", p, "would write", "%s.%s" % (key, SERVER), snippet)


def _codex_strip(text: str) -> Tuple[str, bool]:
    pat = re.compile(r"\n?" + re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"[^\n]*\n?", re.S)
    new, n = pat.subn("\n", text)
    return (new.strip("\n") + "\n" if new.strip() else ""), bool(n)


def _plan_codex(plan: Plan, p: Path, cmd: List[str], write: bool) -> None:
    text = _read(p) or ""
    block = codex_block(cmd)
    if block in text:
        plan.add("mcp", p, "unchanged", "[mcp_servers.%s]" % SERVER)
        return
    rest, had = _codex_strip(text)
    if re.search(r"^\s*\[mcp_servers\.%s\]" % SERVER, rest, re.M) or re.search(
            r"^\s*\[mcp_servers\.[\"']%s[\"']\]" % SERVER, rest, re.M):
        plan.add("mcp", p, "paste", "left alone: it already has an [mcp_servers.%s] table not made by this "
                 "command" % SERVER, block)
        return
    new = (rest.rstrip("\n") + "\n\n" if rest.strip() else "") + block
    if write:
        _backup_once(p)
        _write(p, new)
        plan.add("mcp", p, "updated" if had else "created", "[mcp_servers.%s]" % SERVER)
    else:
        plan.add("mcp", p, "would write", "[mcp_servers.%s]" % SERVER, block)


def unplan_mcp(plan: Plan, home: Path, write: bool) -> None:
    h, w = plan.host, plan.where
    if not h.mcp:
        return
    fmt, user_file, proj_file = h.mcp
    if fmt.startswith("print") or fmt == "claude-cli":
        if fmt == "claude-cli":
            plan.add("mcp", None, "run", "run this once: claude mcp remove %s" % SERVER)
        return
    p = w.path(user_file, proj_file)
    if p is None or not p.is_file():
        return
    if fmt == "codex-toml":
        rest, had = _codex_strip(_read(p) or "")
        if had:
            if write:
                _write(p, rest)
            plan.add("mcp", p, "removed" if write else "would remove", "[mcp_servers.%s]" % SERVER)
        return
    _, key, style = fmt.split(":")
    data, err = _json_load(p)
    if data is None or not isinstance(data.get(key), dict) or SERVER not in data[key]:
        return
    ours = data[key][SERVER] == mcp_entry(style, mcp_command(home, w.windows))
    if not ours:
        plan.add("mcp", p, "kept", "%s.%s was changed by hand; remove it yourself if you want" % (key, SERVER))
        return
    if write:
        del data[key][SERVER]
        if not data[key]:
            del data[key]
        _write(p, _json_dump(data))
    plan.add("mcp", p, "removed" if write else "would remove", "%s.%s" % (key, SERVER))


# --------------------------------------------------------------------------- ledger

def _ledger_path(home: Path) -> Path:
    return Path(home) / LEDGER


def read_ledger(home: Path) -> Dict[str, Any]:
    try:
        d = json.loads(_ledger_path(home).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("installs"), list) else {"installs": []}
    except (OSError, ValueError):
        return {"installs": []}


def _ledger_key(host: Host, where: Where) -> Dict[str, str]:
    return {"host": host.key, "scope": where.scope, "root": str(where.project or where.user_home)}


def _save_ledger(home: Path, data: Dict[str, Any]) -> None:
    try:
        _write(_ledger_path(home), json.dumps(data, indent=2) + "\n")
    except OSError:
        pass


def _skill_users(home: Path, where: Where, host: Host) -> List[str]:
    """Other installed hosts whose skill link is the same folder as `host`'s."""
    mine = where.path(host.skill_user, host.skill_project)
    out = []
    for e in read_ledger(home)["installs"]:
        if e.get("host") == host.key or e.get("scope") != where.scope or e.get("root") != str(where.project or where.user_home):
            continue
        other = HOSTS.get(e.get("host", ""))
        if other and mine is not None and where.path(other.skill_user, other.skill_project) == mine:
            out.append(other.key)
    return out


# --------------------------------------------------------------------------- entry points

def install(host: Host, where: Where, home: Path, skill: Path, write: bool = True, parts: Sequence[str] = ("skill", "crew", "mcp")) -> Plan:
    plan = Plan(host, where)
    home = Path(home)
    if write:
        st = shim.status(home)
        if not st["ok"]:
            code, detail = shim.install(home, skill)
            plan.add("command", shim.shim_path(home), "created" if code == "ok" else "failed", detail)
    src = durable_skill(home, skill) if write else Path(skill)
    skill_ref = str(src)
    if "skill" in parts:
        plan_skill(plan, src, write)
        linked = [a for a in plan.actions if a["kind"] == "skill"]
        if linked and linked[-1]["state"] != "skipped":
            skill_ref = linked[-1]["path"]        # the agents name the link, which survives updates
    if "crew" in parts:
        plan_crew(plan, src, skill_ref, write)
    if "mcp" in parts:
        plan_mcp(plan, home, write)
    plan.notes = [n % {"home": str(home)} if "%(home)s" in n else n for n in host.notes]
    if write:
        led = read_ledger(home)
        key = _ledger_key(host, where)
        led["installs"] = [e for e in led["installs"] if {k: e.get(k) for k in key} != key]
        led["installs"].append(dict(key, parts=list(parts)))
        _save_ledger(home, led)
    return plan


def uninstall(host: Host, where: Where, home: Path, skill: Optional[Path], write: bool = True) -> Plan:
    plan = Plan(host, where)
    home = Path(home)
    unplan_skill(plan, skill, write, _skill_users(home, where, host))
    unplan_crew(plan, skill, write)
    unplan_mcp(plan, home, write)
    if write:
        led = read_ledger(home)
        key = _ledger_key(host, where)
        led["installs"] = [e for e in led["installs"] if {k: e.get(k) for k in key} != key]
        _save_ledger(home, led)
    return plan


def installed(home: Path) -> List[Dict[str, Any]]:
    return read_ledger(home)["installs"]
