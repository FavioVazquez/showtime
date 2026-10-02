"""Agent sandboxes: which host runs us, can we write and download, and what to change if not (stdlib only).

`showtime doctor` uses this to turn "permission denied" and "network unreachable" into the exact
setting to change in the agent that runs showtime. Several agents run shell commands in a sandbox by
default: some block the network, some allow writes only inside the workspace, so a first `showtime
setup` into ~/.showtime fails there. The two ways out work everywhere:

  1. run `showtime setup` once in a normal terminal (outside the agent), or
  2. point SHOWTIME_HOME at a folder inside the workspace (the sandbox allows writes there) and allow
     the download hosts in the agent's network settings.

Host detection only picks the wording of the fix; nothing else depends on it. SHOWTIME_HOST=<name>
overrides it (codex, antigravity, cursor, copilot-cloud, gemini, claude, devin, generic).
"""
from __future__ import annotations

import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROBE_URL = "https://huggingface.co/"      # the host most of the models come from
PROBE_TIMEOUT = 4.0

# Hosts setup and the lazy downloads talk to, besides the ones in setup/manifest.json.
EXTRA_HOSTS = [
    "pypi.org", "files.pythonhosted.org",                                  # Python packages (uv)
    "registry.npmjs.org",                                                   # Node packages
    "cdn.playwright.dev", "playwright.download.prss.microsoft.com",        # the headless browser
    "storage.googleapis.com",                                               # (cdn.playwright.dev redirects there)
    "releases.astral.sh",                                                   # uv's Python 3.12, when none is installed
    "us.aws.cdn.hf.co",                                                     # Hugging Face file CDN (model downloads)
    "media.githubusercontent.com",                                          # GitHub LFS files (face detector)
    "objects.githubusercontent.com", "release-assets.githubusercontent.com",  # GitHub release files
    "cdn-lfs.huggingface.co", "cas-bridge.xethub.hf.co",                  # Hugging Face file storage
    "cdn.jsdelivr.net",                                                     # fonts and icons
    "nodejs.org",
    "api.openverse.org",                                                    # live music search (audio music openverse)
    "cdn.freesound.org",                                                    # Openverse results from Freesound
]

# Audio fetched on first use: the library tiers, produced-music catalog tracks and extra sound packs.
AUDIO_URL_FIELDS = (("library_manifest.json", "sources", "url"), ("music_catalog.json", "tracks", "file_url"),
                    ("sfx_packs.json", "packs", "url"))


def audio_hosts(audio_dir: Optional[Path] = None) -> List[str]:
    """The exact hosts audio downloads come from (creators' own sites: Kenney, OpenGameArt, incompetech,
    Scott Buckley, Wikimedia, the Internet Archive ...)."""
    import json
    d = Path(audio_dir) if audio_dir else Path(__file__).resolve().parent / "audio"
    out: List[str] = []
    for name, key, field in AUDIO_URL_FIELDS:
        try:
            data = json.loads((d / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for it in data.get(key) or []:
            m = re.match(r"https?://([A-Za-z0-9.-]+)", str(it.get(field) or ""))
            if m and m.group(1) not in out:
                out.append(m.group(1))
    return out

HOST_NAMES = {
    "codex": "Codex", "antigravity": "Antigravity", "cursor": "Cursor", "copilot-cloud": "the Copilot cloud agent",
    "copilot": "GitHub Copilot", "gemini": "Gemini CLI", "claude": "Claude Code", "devin": "Devin",
    "generic": "this agent",
}


def detect_host(env: Optional[Dict[str, str]] = None) -> str:
    env = dict(os.environ if env is None else env)
    forced = (env.get("SHOWTIME_HOST") or "").strip().lower()
    if forced in HOST_NAMES:
        return forced
    keys = set(env)
    if any(k.startswith("CODEX_") for k in keys):
        return "codex"
    if any(k.startswith(("ANTIGRAVITY", "AGY_")) for k in keys):
        return "antigravity"
    if any(k.startswith("CURSOR_") for k in keys):
        return "cursor"
    if env.get("GITHUB_ACTIONS") == "true" and ("copilot" in (env.get("GITHUB_WORKFLOW") or "").lower()
                                               or any(k.startswith("COPILOT_AGENT") for k in keys)):
        return "copilot-cloud"
    if any(k.startswith("COPILOT_") for k in keys):
        return "copilot"
    if env.get("GEMINI_CLI") or any(k.startswith("GEMINI_CLI") for k in keys):
        return "gemini"
    if any(k.startswith("DEVIN_") for k in keys):
        return "devin"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    return "generic"


def sandbox_signals(env: Optional[Dict[str, str]] = None) -> List[str]:
    """Environment hints that commands run in a sandbox (informational)."""
    env = dict(os.environ if env is None else env)
    out = []
    if env.get("CODEX_SANDBOX"):
        out.append("CODEX_SANDBOX=%s" % env["CODEX_SANDBOX"])
    if env.get("CODEX_SANDBOX_NETWORK_DISABLED"):
        out.append("CODEX_SANDBOX_NETWORK_DISABLED=%s" % env["CODEX_SANDBOX_NETWORK_DISABLED"])
    if env.get("SANDBOX") and env.get("SANDBOX") not in ("0", "false"):
        out.append("SANDBOX=%s" % env["SANDBOX"])
    return out


def download_hosts(manifest: Optional[Path] = None) -> List[str]:
    hosts: List[str] = []
    if manifest is None:
        manifest = Path(__file__).resolve().parents[2] / "setup" / "manifest.json"
    try:
        text = Path(manifest).read_text(encoding="utf-8")
        hosts = re.findall(r"https?://([A-Za-z0-9.-]+)", text)
    except OSError:
        pass
    out: List[str] = []
    for h in hosts + EXTRA_HOSTS + audio_hosts():
        if h not in out:
            out.append(h)
    return out


def writable(p: Path) -> Tuple[bool, Path, str]:
    """(can a file be created, the folder tried, error). Tries p, else its nearest existing parent.
    A real write: sandbox rules (Seatbelt, Landlock, nsjail) refuse what the permission bits allow."""
    p = Path(p)
    while not p.is_dir():
        if p.parent == p or p.exists():
            return False, p, "not a folder"
        p = p.parent
    probe = p / (".showtime-write-test-%d" % os.getpid())
    try:
        with open(str(probe), "w") as fh:
            fh.write("x")
        os.remove(str(probe))
        return True, p, ""
    except OSError as e:
        return False, p, "%s" % (e.strerror or e)


def probe_network(url: Optional[str] = None, timeout: float = PROBE_TIMEOUT) -> Tuple[bool, str]:
    """(reachable, detail). Any HTTP answer, even an error status or a certificate problem, counts as
    reachable: only DNS failures, refused/blocked connections and timeouts mean "no network".
    Honours HTTPS_PROXY like the downloads do. SHOWTIME_NET_PROBE sets the URL (tests)."""
    url = url or os.environ.get("SHOWTIME_NET_PROBE") or PROBE_URL
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "showtime-doctor"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return True, "%s answered (HTTP %s)" % (_host(url), r.status)
    except urllib.error.HTTPError as e:
        return True, "%s answered (HTTP %s)" % (_host(url), e.code)
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, ssl.SSLError):
            return True, "%s reachable (TLS: %s)" % (_host(url), reason)
        return False, _why(reason)
    except ssl.SSLError as e:
        return True, "%s reachable (TLS: %s)" % (_host(url), e)
    except (socket.timeout, TimeoutError):
        return False, "no answer from %s within %.0f s" % (_host(url), timeout)
    except OSError as e:
        return False, _why(e)


MIRROR_ENV = "SHOWTIME_MODEL_MIRROR"


def probe_mirror(timeout: float = PROBE_TIMEOUT) -> Tuple[bool, str]:
    """(reachable, detail) for the first model mirror (st/mirror.py): where model files come from when
    Hugging Face or GitHub LFS is blocked. A local SHOWTIME_MODEL_MIRROR folder counts when it exists."""
    try:
        from . import mirror
    except ImportError:
        return False, "no mirror list"
    for d in mirror.local_dirs():
        if d.is_dir():
            return True, "folder %s" % d
    for base in mirror.bases()[:1]:
        return probe_network(base, timeout)
    return False, "mirrors off"


AUDIO_MIRROR_ENV = "SHOWTIME_AUDIO_MIRROR"


def probe_audio_mirror(timeout: float = PROBE_TIMEOUT) -> Tuple[bool, str]:
    """(reachable, detail) for the audio mirror (st/mirror.py `audio_sources`): where music, sfx and
    library files come from when their own hosts (opengameart.org, scottbuckley.com.au, incompetech.com,
    archive.org, upload.wikimedia.org, bigsoundbank.com, kenney.nl ...) are blocked. A local
    SHOWTIME_AUDIO_MIRROR folder counts when it exists."""
    try:
        from . import mirror
    except ImportError:
        return False, "no mirror list"
    for d in mirror.audio_local_dirs():
        if d.is_dir():
            return True, "folder %s" % d
    for base in mirror.audio_bases()[:1]:
        return probe_network(base, timeout)
    return False, "mirrors off"


def _host(url: str) -> str:
    m = re.match(r"^[a-z]+://([^/:]+)", url)
    return m.group(1) if m else url


def _why(reason: object) -> str:
    if isinstance(reason, socket.gaierror):
        return "name lookup failed (%s)" % reason
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timed out"
    if isinstance(reason, PermissionError):
        return "connection not permitted (%s)" % reason
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    return str(reason)


# --------------------------------------------------------------------------- the fixes

def fix_lines(host: str, problem: str, home: Path, skill: Optional[Path] = None) -> List[str]:
    """What to change, for `problem` in ("network", "write"), in the wording of `host`."""
    home_s = str(home)
    hosts = download_hosts()
    doms = ", ".join(hosts)
    ws_home = "SHOWTIME_HOME=\"$PWD/.showtime\"" if os.name != "nt" else "$env:SHOWTIME_HOME = \"$PWD\\.showtime\""
    out: List[str] = []
    if host == "codex":
        out.append("Codex runs commands in a sandbox (workspace-write: no network, writes only in the workspace). "
                   "In ~/.codex/config.toml set:")
        out.append("  [sandbox_workspace_write]")
        out.append("  network_access = true")
        out.append("  writable_roots = [%s]" % json.dumps(home_s))
        out.append("then start a new Codex session (or approve the command to run outside the sandbox).")
    elif host == "antigravity":
        out.append("Antigravity runs terminal commands in a sandbox with no network by default. In its sandbox "
                   "settings allow the download hosts with read_url rules (%s) and %s with a write_file rule, or run "
                   "this one command unsandboxed." % (doms, home_s))
    elif host == "cursor":
        out.append("Cursor's sandbox limits the network to the domains in sandbox.json. Add these to the network "
                   "allowlist in ~/.cursor/sandbox.json (or .cursor/sandbox.json in the project): %s" % doms)
        if problem == "write":
            out.append("and allow writes to %s there too (or approve running this command outside the sandbox)." % home_s)
    elif host == "copilot-cloud":
        out.append("The Copilot cloud agent's firewall blocks these downloads. Install showtime in "
                   ".github/workflows/copilot-setup-steps.yml (its steps run before the firewall), with "
                   "SHOWTIME_HOME inside the workspace, e.g. a step: run: %s setup"
                   % ("<skill folder>/bin/showtime" if skill is None else str(Path(skill) / "bin" / "showtime")))
        out.append("or allow the hosts in the repository's Copilot firewall settings: %s" % doms)
    elif host == "gemini":
        out.append("Gemini CLI's sandbox is in the way: run setup without --sandbox (or GEMINI_SANDBOX=false), or "
                   "with a sandbox profile that allows the network and writes to %s." % home_s)
    elif host == "devin":
        out.append("Devin's sandbox is in the way: allow the download hosts (%s) and writes to %s in its permission "
                   "rules, or run setup outside the sandbox." % (doms, home_s))
    if problem == "network":
        out.append("Anywhere: run `showtime setup` once in a normal terminal outside the agent; after that, "
                   "showtime works offline except for features that fetch on first use.")
    else:
        out.append("Anywhere: run `showtime setup` once in a normal terminal outside the agent, or keep showtime "
                   "inside the workspace: %s, then `showtime setup` (set the same SHOWTIME_HOME wherever showtime runs)."
                   % ws_home)
    return out
