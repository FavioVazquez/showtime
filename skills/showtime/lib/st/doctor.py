"""showtime doctor: verify the installation with real checks.

Stdlib only and Python 3.8+ compatible, so it runs even before the venv
exists (the launcher calls it with whatever Python it found). It actually
runs things: ffmpeg/ffprobe (plus a tiny encode), the venv's imports, Node
and Playwright, a headless browser launch with a WebGL page, and checks
every model file the installed tier needs.

usage: showtime doctor [--json] [--quick] [--verify] [--no-browser] [--report [JOB]]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__
from . import platform as plat
from .common import ShowtimeError, fmt_duration, paint, paths, read_json, use_color

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"

REQUIRED_MODULES = ["numpy", "scipy", "soundfile", "PIL", "cv2", "av", "scenedetect", "faster_whisper",
                    "ctranslate2", "onnxruntime", "kokoro_onnx", "sherpa_onnx", "librosa", "mido",
                    "pretty_midi", "pyloudnorm", "requests", "huggingface_hub", "pypdfium2"]
OPTIONAL_MODULES = ["tinysoundfont", "rich", "imageio_ffmpeg"]
MAC_MODULES = ["Vision", "Quartz"]
DIST_NAMES = {"PIL": "pillow", "cv2": "opencv-python", "faster_whisper": "faster-whisper",
              "kokoro_onnx": "kokoro-onnx", "sherpa_onnx": "sherpa-onnx",
              "imageio_ffmpeg": "imageio-ffmpeg", "huggingface_hub": "huggingface-hub",
              "Vision": "pyobjc-framework-Vision", "Quartz": "pyobjc-framework-Quartz"}


SLOW_NOTE_AFTER = 10.0   # seconds a check may take before the "first run after a restart" note appears
RECENT_BOOT = 30 * 60    # a machine up for less than this gets the note before the checks start


def slow_start_note() -> str:
    if plat.IS_MAC:
        why = "while macOS checks libraries"
    elif plat.IS_WINDOWS:
        why = "while Windows scans libraries"
    else:
        why = "while libraries load from disk"
    return "first run after a restart can take a few minutes %s; later runs take seconds" % why


class Live:
    """What doctor is doing right now, on stderr, so a slow check never looks frozen.

    TTY: one line redrawn in place (`  - checking python imports (cv2, 7/22)  45 s`), cleared when the
    check ends. Not a TTY (Claude's tool output, logs): quiet for fast checks, then one line every 15 s
    while a check keeps running. The restart note appears once, up front when the machine booted less
    than 30 minutes ago, otherwise as soon as a check has run for 10 s. SHOWTIME_PROGRESS=off silences it.
    """

    FRAMES = "-\\|/"

    def __init__(self, stream: Any = None, enabled: bool = True) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled and os.environ.get("SHOWTIME_PROGRESS", "auto").lower() != "off"
        try:
            self.tty = self.enabled and self.stream.isatty()
        except (AttributeError, ValueError, OSError):
            self.tty = False
        self.label = ""
        self.detail = ""
        self.t0 = time.time()
        self.noted = False
        self._width = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except (OSError, ValueError, UnicodeEncodeError):
            pass

    def _clear(self) -> None:
        if self.tty and self._width:
            self._write("\r" + " " * self._width + "\r")
            self._width = 0

    def say(self, line: str) -> None:
        """A permanent line (above the live one)."""
        if not self.enabled:
            return
        with self._lock:
            self._clear()
            self._write("showtime doctor: %s\n" % line)

    def note_restart(self) -> None:
        if not self.noted:
            self.noted = True
            self.say(slow_start_note())

    def start(self) -> None:
        if not self.enabled:
            return
        up = plat.uptime_seconds()
        if up is not None and up < RECENT_BOOT:
            self.note_restart()
        self._thread = threading.Thread(target=self._loop, name="doctor-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            self._clear()

    def step(self, label: str) -> None:
        with self._lock:
            self.label, self.detail, self.t0 = label, "", time.time()

    def _loop(self) -> None:
        i = 0
        last_plain = 0.0
        while not self._stop.wait(0.2 if self.tty else 1.0):
            with self._lock:
                if not self.label:
                    continue
                el = time.time() - self.t0
                if el >= SLOW_NOTE_AFTER and not self.noted:
                    self.noted = True
                    self._clear()
                    self._write("showtime doctor: %s\n" % slow_start_note())
                what = "checking %s%s" % (self.label, (" (%s)" % self.detail) if self.detail else "")
                if self.tty:
                    i += 1
                    text = "  %s %s  %s" % (self.FRAMES[i % 4], what, fmt_duration(el))
                    pad = max(0, self._width - len(text))
                    self._write("\r" + text + " " * pad)
                    self._width = len(text)
                elif el >= 15 and el - last_plain >= 15:
                    last_plain = el
                    self._write("showtime doctor: still %s, %s so far\n" % (what, fmt_duration(el)))


class Doctor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.rows: List[Dict[str, Any]] = []
        self.p = paths()
        self.state: Dict[str, Any] = {}
        try:
            self.state = read_json(self.p["state"], {})
        except ShowtimeError:
            self.state = {}
        self._setup_mod = None
        self.live = Live()

    # ------------------------------------------------------------ plumbing
    def add(self, name: str, status: str, detail: str = "", hint: str = "", **data: Any) -> None:
        self.rows.append({"check": name, "status": status, "detail": detail, "hint": hint, "data": data})

    def guard(self, name: str, fn: Callable[[], None], label: str = "") -> None:
        self.live.step(label or name)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - a broken check must not kill the report
            self.add(name, FAIL, "check crashed: %s: %s" % (type(e).__name__, e),
                     "re-run `showtime doctor --debug`; if it persists, `showtime setup --force`")

    def setup_module(self):
        if self._setup_mod is None:
            path = self.p["setup"] / "setup.py"
            spec = importlib.util.spec_from_file_location("showtime_setup", str(path))
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            self._setup_mod = mod
        return self._setup_mod

    # --------------------------------------------------------------- checks
    def check_platform(self) -> None:
        s = plat.summary()
        extra = ""
        if plat.IS_MAC:
            try:
                extra = "macOS " + subprocess.run(["sw_vers", "-productVersion"], stdout=subprocess.PIPE,
                                                  encoding="utf-8", timeout=10).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        elif os.name == "nt":
            import platform as _pf
            rel, ver = _pf.release(), _pf.version()
            extra = ("Windows %s %s" % (rel, ver)).strip() if (rel or ver) else ""
        self.add("platform", PASS, "%s%s, %s CPUs, launcher python %s" % (s["key"], (" " + extra) if extra else "",
                                                                          s["cpus"], s["python"]),
                 **s)

    def check_home(self) -> None:
        h = self.p["home"]
        if not h.is_dir():
            self.add("home", FAIL, "%s does not exist" % h, "run `showtime setup`")
            return
        free = shutil.disk_usage(str(h)).free
        st = PASS if free > 5 * 1024 ** 3 else WARN
        self.add("home", st, "%s (%.1f GB free)" % (h, free / 1024 ** 3),
                 "" if st == PASS else "less than 5 GB free: renders and models need space")
        inst = self.state.get("installed")
        if inst:
            self.add("setup", PASS, "tier %s%s, last run %s" % (
                inst.get("tier"), (", extras " + ",".join(inst["extras"])) if inst.get("extras") else "",
                self.state.get("updated", "?")))
        else:
            self.add("setup", WARN, "setup has not completed yet", "run `showtime setup`")

    def check_uv(self) -> None:
        uv = plat.find_tool("uv")
        if uv:
            try:
                v = subprocess.run([uv, "--version"], stdout=subprocess.PIPE, encoding="utf-8", timeout=20).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                v = "?"
            self.add("uv", PASS, v)
        else:
            self.add("uv", WARN, "not found (only needed to install/update)",
                     "install: https://docs.astral.sh/uv/getting-started/installation/ ; if you just installed it, "
                     "restart Claude Code (or open a new terminal)")

    def check_python(self) -> None:
        vpy = self.p["venv_python"]
        if not vpy.exists():
            self.add("python venv", FAIL, "%s missing" % vpy, "run `showtime setup`")
            return
        mods = REQUIRED_MODULES + OPTIONAL_MODULES + (MAC_MODULES if plat.IS_MAC else [])
        extras = set((self.state.get("installed") or {}).get("extras", []))
        if "supertonic" in extras:
            mods.append("supertonic")
        code = (
            "import importlib, json, sys, time\n"
            "from importlib import metadata\n"
            "res = {'python': sys.version.split()[0]}\n"
            "dist = %r\n"
            "mods = %r\n"
            "for i, m in enumerate(mods):\n"
            "    sys.stderr.write('@@doctor %%d/%%d %%s\\n' %% (i + 1, len(mods), m)); sys.stderr.flush()\n"
            "    t = time.time()\n"
            "    try:\n"
            "        importlib.import_module(m)\n"
            "        try: v = metadata.version(dist.get(m, m))\n"
            "        except Exception: v = '?'\n"
            "        res[m] = {'ok': True, 'version': v, 's': round(time.time() - t, 2)}\n"
            "    except Exception as e:\n"
            "        res[m] = {'ok': False, 'error': '%%s: %%s' %% (type(e).__name__, str(e)[:300])}\n"
            "print(json.dumps(res))\n" % (DIST_NAMES, mods))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.p["skill"] / "lib")
        t0 = time.time()
        stdout, stderr = self._run_streaming([str(vpy), "-c", code], env, timeout=900)
        try:
            res = json.loads((stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            self.add("python venv", FAIL, "venv python failed: %s" % (stderr or "").strip()[-300:],
                     "re-run `showtime setup --force`")
            return
        self.add("python venv", PASS if res.get("python", "").startswith("3.12") else WARN,
                 "python %s at %s" % (res.get("python"), vpy))
        bad_req = [m for m in REQUIRED_MODULES if not res.get(m, {}).get("ok")]
        vers = ", ".join("%s %s" % (DIST_NAMES.get(m, m), res[m]["version"]) for m in REQUIRED_MODULES
                         if res.get(m, {}).get("ok") and m in ("numpy", "onnxruntime", "ctranslate2", "faster_whisper",
                                                               "kokoro_onnx", "sherpa_onnx", "cv2", "librosa"))
        if bad_req:
            self.add("python packages", FAIL, "; ".join("%s (%s)" % (m, res.get(m, {}).get("error", "?")) for m in bad_req),
                     "run `showtime setup --force`")
        else:
            self.add("python packages", PASS, "%d required imports OK in %.1fs (%s)" % (
                len(REQUIRED_MODULES), time.time() - t0, vers), versions={m: res[m].get("version") for m in res
                                                                            if isinstance(res[m], dict)})
        opt = [m for m in mods if m not in REQUIRED_MODULES]
        missing_opt = [m for m in opt if not res.get(m, {}).get("ok")]
        if missing_opt:
            notes = []
            for m in missing_opt:
                if m == "tinysoundfont":
                    notes.append("tinysoundfont (no wheel for %s; SoundFont rendering uses a fallback)" % plat.platform_key())
                else:
                    notes.append("%s (%s)" % (m, res.get(m, {}).get("error", "?")[:80]))
            self.add("python optional", WARN, "; ".join(notes))
        else:
            self.add("python optional", PASS, ", ".join(opt))

    def _run_streaming(self, argv: List[str], env: Dict[str, str], timeout: float) -> Tuple[str, str]:
        """Run the import probe; its `@@doctor i/n module` stderr lines feed the live line."""
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                errors="replace", env=env)
        err_lines: List[str] = []

        def pump() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                if line.startswith("@@doctor "):
                    parts = line.split()
                    if len(parts) >= 3:  # "@@doctor 7/22 cv2" -> "cv2, 7/22"
                        self.live.detail = "%s, %s" % (parts[2], parts[1])
                else:
                    err_lines.append(line)

        th = threading.Thread(target=pump, name="doctor-probe", daemon=True)
        th.start()
        killer = threading.Timer(timeout, proc.kill)
        killer.daemon = True
        killer.start()
        try:
            assert proc.stdout is not None
            stdout = proc.stdout.read()
            proc.wait()
        finally:
            killer.cancel()
        th.join(timeout=5)
        self.live.detail = ""
        if proc.returncode and proc.returncode < 0:
            err_lines.append("stopped after %d s" % timeout)
        return stdout or "", "".join(err_lines)

    def check_ffmpeg(self) -> None:
        from . import ff
        try:
            info = ff.resolve(refresh=True)
        except ShowtimeError as e:
            self.add("ffmpeg", FAIL, str(e).splitlines()[0], "run `showtime setup` (installs a static ffmpeg)")
            return
        self.add("ffmpeg", PASS if info.source in ("showtime", "system", "env") else WARN,
                 "%s (%s) %s" % (info.version, info.source, info.ffmpeg),
                 "" if info.source != "imageio" else "fallback build without ffprobe/libass; run `showtime setup`",
                 **info.as_dict())
        if info.ffprobe:
            self.add("ffprobe", PASS, info.ffprobe)
        else:
            self.add("ffprobe", WARN, "not found; probing falls back to parsing ffmpeg output")
        caps = ff.check_capabilities(info.ffmpeg)
        if caps["missing_required"]:
            self.add("ffmpeg features", FAIL, "missing: " + ", ".join(caps["missing_required"]),
                     "needs a build with libx264, libass and libfreetype: `showtime setup --ffmpeg static --force`")
        elif caps["missing_recommended"]:
            self.add("ffmpeg features", WARN, "all required present; optional missing: " +
                     ", ".join(caps["missing_recommended"]),
                     "features using them fall back (e.g. deshake instead of vid.stab)")
        else:
            self.add("ffmpeg features", PASS, "libx264, libass (subtitles/ass), drawtext, loudnorm, ebur128, xfade, "
                                              "zscale, vid.stab, arnndn, rubberband")
        if self.args.quick:
            return
        t0 = time.time()
        tmp_dir = self.p["cache"]
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out = tmp_dir / ("doctor-%d.mp4" % os.getpid())
        try:
            cp = subprocess.run([info.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                                 "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=0.5",
                                 "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                                 "-vf", ff.BT709_VF + ",format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                                 "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                timeout=120)
            ok = cp.returncode == 0 and out.is_file() and out.stat().st_size > 1000
        finally:
            size = out.stat().st_size if out.is_file() else 0
            try:
                out.unlink()
            except OSError:
                pass
        if ok:
            self.add("ffmpeg encode", PASS, "H.264 + AAC test encode (%d bytes) in %.2fs" % (size, time.time() - t0))
        else:
            self.add("ffmpeg encode", FAIL, (cp.stderr or "").strip()[-300:],
                     "reinstall the bundled build: `showtime setup --ffmpeg static --force`")

    def _node(self) -> Tuple[Optional[str], Optional[Tuple[int, ...]]]:
        node = os.environ.get("SHOWTIME_NODE") or plat.find_tool("node")
        if not node:
            return None, None
        try:
            out = subprocess.run([node, "--version"], stdout=subprocess.PIPE, encoding="utf-8", timeout=30).stdout
            return node, tuple(int(x) for x in re.findall(r"\d+", out)[:3])
        except (OSError, ValueError, subprocess.SubprocessError):
            return node, None

    def check_node(self) -> None:
        node, ver = self._node()
        if not node:
            self.add("node", FAIL, "Node.js not found", "install Node.js 24 or 22 LTS (20+) from https://nodejs.org"
                     "%s; if you just installed it, restart Claude Code (or open a new terminal)"
                     % (" (on Linux: fnm or NodeSource; distribution packages are often too old)" if plat.os_name() == "linux" else ""))
            return
        vs = ".".join(map(str, ver or ()))
        if not ver or ver[0] < 20:
            self.add("node", FAIL, "Node.js %s at %s is too old" % (vs, node), "install Node.js 24 or 22 LTS (20+)")
        else:
            self.add("node", PASS, "v%s at %s" % (vs, node))
        pkg = self.p["setup"] / "package.json"
        nm = self.p["node_modules"]
        try:
            deps = json.loads(pkg.read_text(encoding="utf-8"))["dependencies"]
        except (OSError, ValueError, KeyError):
            self.add("node packages", FAIL, "cannot read %s" % pkg, "the skill folder is incomplete; reinstall showtime")
            return
        missing, wrong = [], []
        for name, want in deps.items():
            pj = nm.joinpath(*name.split("/")) / "package.json"
            try:
                have = json.loads(pj.read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError):
                missing.append(name)
                continue
            if have != want:
                wrong.append("%s %s (want %s)" % (name, have, want))
        if "playwright" in missing:
            self.add("node packages", FAIL, "playwright missing from %s" % nm, "run `showtime setup`")
        elif missing or wrong:
            self.add("node packages", WARN, "; ".join((["missing: " + ", ".join(missing)] if missing else []) +
                                                     (["version drift: " + ", ".join(wrong)] if wrong else [])),
                     "run `showtime setup` to sync")
        else:
            self.add("node packages", PASS, "%d pinned packages in %s" % (len(deps), nm))

    def check_browser(self) -> None:
        browsers = plat.find_browsers(self.p["browsers"])
        if not browsers:
            self.add("browser", FAIL, "no Chrome, Edge or Chromium found",
                     "install Google Chrome, or run `showtime setup --with chromium`")
            return
        b = browsers[0]
        self.add("browser", PASS, "%s: %s%s" % (b["kind"], b["path"],
                                               (" (+%d more)" % (len(browsers) - 1)) if len(browsers) > 1 else ""),
                 browsers=browsers)
        if self.args.quick or self.args.no_browser:
            self.add("browser launch", SKIP, "skipped (--quick/--no-browser)")
            return
        node, ver = self._node()
        if not node or not (self.p["node_modules"] / "playwright").is_dir():
            self.add("browser launch", SKIP, "needs Node + Playwright")
            return
        script = self.p["scripts"] / "lib" / "chrome.mjs"
        cp = subprocess.run([node, str(script), "--probe", "--gpu", self.args.gpu], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=180,
                            env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=os.environ.get(
                                "PLAYWRIGHT_BROWSERS_PATH", str(self.p["browsers"]))))
        try:
            res = json.loads((cp.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            res = {"ok": False, "error": (cp.stderr or cp.stdout or "no output").strip()[-400:]}
        if res.get("ok"):
            st = PASS if res.get("webgl") else WARN
            self.add("browser launch", st, "%s %s headless in %.1fs; WebGL: %s" % (
                res.get("kind"), res.get("version"), res.get("ms", 0) / 1000.0, res.get("renderer")),
                "" if st == PASS else "WebGL unavailable: 3D/shader scenes will fail (try --gpu off)", **res)
        else:
            self.add("browser launch", FAIL, str(res.get("error", "?")).splitlines()[0][:300],
                     "see `node %s --probe`; on Linux try `npx playwright install-deps chromium`" % script)

    def check_models(self) -> None:
        try:
            setup = self.setup_module()
            man = setup.load_manifest()
        except Exception as e:  # noqa: BLE001
            self.add("models", FAIL, "cannot read setup manifest: %s" % e, "the skill folder is incomplete; reinstall showtime")
            return
        inst = self.state.get("installed") or {}
        tier = inst.get("tier") or "core"
        extras = inst.get("extras", [])
        key = plat.platform_key()
        items = setup.select_items(man, tier, extras)
        base_tiers = setup.TIER_ORDER[:setup.TIER_ORDER.index(tier) + 1]
        ok_count = 0
        for it in items:
            st, detail = setup.item_status(it, self.p["home"], key, self.state, verify=self.args.verify)
            if st == "ok":
                ok_count += 1
                if self.args.verbose:
                    self.add("model " + it["id"], PASS, it.get("description", ""))
                continue
            if st == "unsupported":
                self.add("model " + it["id"], SKIP, detail)
                continue
            required = it.get("tier") in base_tiers
            self.add("model " + it["id"], FAIL if required else WARN, "%s: %s" % (st, detail),
                     "run `showtime setup%s`" % ((" --with " + it["extra"]) if it.get("extra") else ""))
        self.add("models", PASS if ok_count == len(items) else WARN,
                 "%d/%d items for tier %s%s present in %s" % (ok_count, len(items), tier,
                                                             ("+" + ",".join(extras)) if extras else "",
                                                             self.p["home"]))

    def check_extras(self) -> None:
        lib = self.p["library"] / "catalog.json"
        if lib.is_file():
            try:
                n = len((read_json(lib, {}) or {}).get("items", []))
            except ShowtimeError:
                n = -1
            self.add("audio library", PASS if n != -1 else WARN, "%s (%s entries)" % (lib, n if n >= 0 else "unreadable"))
        else:
            self.add("audio library", WARN, "not fetched yet", "run `showtime audio lib fetch`")
        self.check_espeak()
        self.check_manim()
        link = (Path(os.environ["CLAUDE_CONFIG_DIR"]) if os.environ.get("CLAUDE_CONFIG_DIR")
                else plat.user_home() / ".claude") / "skills" / "showtime"
        try:
            linked = link.exists() and os.path.samefile(str(link), str(self.p["skill"]))
        except OSError:
            linked = False
        skill_s = str(self.p["skill"]).replace("\\", "/")
        if linked:
            self.add("claude skill", PASS, "personal skill link %s -> %s" % (link, self.p["skill"]))
        elif "/plugins/" in skill_s or os.environ.get("CLAUDE_PLUGIN_ROOT"):
            self.add("claude skill", PASS, "installed as a Claude Code plugin (%s)" % self.p["skill"])
        else:
            self.add("claude skill", SKIP, "running from %s (install as a Claude Code plugin; see README)"
                     % self.p["skill"])
        self.add("chrome flags", PASS, "gpu=%s: %s" % (self.args.gpu, " ".join(
            f for f in plat.chrome_flags(self.args.gpu) if "angle" in f or "gpu" in f or "swiftshader" in f)))

    def check_espeak(self) -> None:
        """Ask the voice module which espeak-ng it would use (it self-tests each candidate)."""
        vpy = self.p["venv_python"]
        esp_mod = self.p["skill"] / "lib" / "st" / "voice" / "espeak.py"
        if not vpy.exists() or not esp_mod.is_file():
            esp = shutil.which("espeak-ng")
            self.add("espeak-ng", PASS if esp else WARN,
                     ("system %s" % esp) if esp else "not checked (the voice module or the venv is missing)",
                     "" if esp else "run `showtime setup`")
            return
        code = ("import json\nfrom st.common import ShowtimeError\n"
                "try:\n    from st.voice.espeak import resolve\n    lib, data, src = resolve()\n"
                "    print(json.dumps({'ok': True, 'lib': lib, 'data': data, 'source': src}))\n"
                "except ShowtimeError as e:\n"
                "    print(json.dumps({'ok': False, 'error': e.message if hasattr(e, 'message') else str(e),"
                " 'hint': getattr(e, 'hint', None)}))\n")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.p["skill"] / "lib")
        try:
            cp = subprocess.run([str(vpy), "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace", env=env, timeout=240)
            res = json.loads((cp.stdout or "").strip().splitlines()[-1])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
            self.add("espeak-ng", WARN, "self-test did not run: %s" % e,
                     "run `showtime voice say \"test\" -o t.wav --debug` to see why")
            return
        if res.get("ok"):
            self.add("espeak-ng", PASS, "%s (%s), self-test passed" % (res.get("source"), res.get("lib")), **res)
        else:
            self.add("espeak-ng", FAIL, str(res.get("error", "no working espeak-ng")).splitlines()[0][:300],
                     res.get("hint") or "set SHOWTIME_ESPEAK=bundled|system, or re-run `showtime setup`")

    def check_manim(self) -> None:
        """Rows for the optional Manim extras (silent when neither is installed)."""
        from .manim_run import render as mr
        from .manim_run import tex
        extras = set((self.state.get("installed") or {}).get("extras", []))
        have = mr.manim_installed()
        if "manim" in extras or have:
            if have:
                self.add("manim", PASS, "Manim Community %s in the main venv" % mr.manim_version())
            else:
                self.add("manim", WARN, "the manim extra is recorded but not importable",
                         "showtime setup --with manim --force   (build deps: %s)" % "; ".join(tex.cairo_fix_lines()))
            info = tex.find()
            if not info["ok"]:
                self.add("latex", WARN, "no LaTeX: Text, shapes and graphs render; equations (MathTex) need it",
                         " ; ".join(tex.fix_lines()))
            elif self.args.quick:
                self.add("latex", PASS, "%s (%s)" % (info["latex"], info["distribution"]))
            else:
                missing = tex.missing_packages(info)
                if missing:
                    self.add("latex", WARN, "%s is missing packages: %s" % (info["distribution"], ", ".join(missing)),
                             tex.fix_text(missing=missing))
                else:
                    self.add("latex", PASS, "%s (%s), dvisvgm, the packages Manim needs" % (
                        info["latex"], info["distribution"]))
        if "manimgl" in extras or mr.gl_python() is not None:
            vpy = mr.gl_python()
            if vpy is None:
                self.add("manimgl", WARN, "the manimgl extra is recorded but its venv is missing",
                         "showtime setup --with manimgl --force")
            else:
                prefix, no_display = plat.gl_display_prefix()
                if no_display:
                    self.add("manimgl", WARN, "ManimGL 1.7.2 is installed but cannot render: %s" % no_display,
                             plat.XVFB_FIX)
                else:
                    self.add("manimgl", PASS, "ManimGL 1.7.2 in %s (optional engine; renders need OpenGL 3.3%s)" % (
                        vpy.parent.parent, "; under xvfb-run, no display here" if prefix else ""))

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        t0 = time.time()
        self.live.start()
        try:
            self.guard("platform", self.check_platform)
            self.guard("home", self.check_home, "the showtime home folder")
            self.guard("uv", self.check_uv)
            self.guard("ffmpeg", self.check_ffmpeg, "ffmpeg (test encode)" if not self.args.quick else "ffmpeg")
            self.guard("python", self.check_python, "python imports")
            self.guard("node", self.check_node, "node and playwright")
            self.guard("browser", self.check_browser, "the headless browser")
            self.guard("models", self.check_models, "model files")
            self.guard("extras", self.check_extras, "extras and espeak-ng")
        finally:
            self.live.stop()
        counts = {s: sum(1 for r in self.rows if r["status"] == s) for s in (PASS, WARN, FAIL, SKIP)}
        result = {"ok": counts[FAIL] == 0, "version": __version__, "counts": counts,
                  "seconds": round(time.time() - t0, 1), "checks": self.rows}
        report_path = None
        if self.args.report is not None:
            report_path = write_report(self.args.report or None, result, use_job_module=True)
            result["report"] = str(report_path)
        if self.args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            self.print_table(counts, time.time() - t0)
            if report_path is not None:
                sys.stdout.write("\nbug report written to %s\n  Review it before sharing; showtime never uploads "
                                 "anything.\n" % report_path)
        return 1 if counts[FAIL] else 0

    def print_table(self, counts: Dict[str, int], secs: float) -> None:
        color = use_color(sys.stdout)
        styles = {PASS: "green", WARN: "yellow", FAIL: "red", SKIP: "dim"}

        def tag(s: str) -> str:
            return paint(s.upper().ljust(4), styles[s], force=color)

        w = max(len(r["check"]) for r in self.rows)
        head = None
        try:
            from .delight import header
            home_s = str(paths()["home"]).replace(str(plat.user_home()), "~", 1)
            head = header("showtime doctor %s" % __version__, "%s  \u00b7  home %s" % (plat.platform_key(), home_s))
        except Exception:  # noqa: BLE001 - decoration never breaks the report
            head = None
        out = [head or ("showtime doctor %s" % __version__), ""]
        for r in self.rows:
            out.append("  %s  %s  %s" % (tag(r["status"]), r["check"].ljust(w), r["detail"]))
            if r["hint"] and r["status"] in (WARN, FAIL):
                out.append("  %s  %s  %s %s" % (" " * 4, " " * w, paint("fix:", "green", force=color), r["hint"]))
        out.append("")
        out.append("%d pass, %d warn, %d fail%s  (%.1fs)" % (
            counts[PASS], counts[WARN], counts[FAIL], (", %d skipped" % counts[SKIP]) if counts[SKIP] else "", secs))
        text = "\n".join(out) + "\n"
        try:
            sys.stdout.write(text)
        except UnicodeEncodeError:
            sys.stdout.write(text.encode("ascii", "replace").decode())


# ---------------------------------------------------------------------------
# Bug report (`showtime doctor --report [JOB]`): local file only, never uploaded
# ---------------------------------------------------------------------------

_TOKEN_RES = [
    re.compile(r"(?i)\b(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abprs]|hf|glpat)[-_][A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)(\s*[=:]\s*|\s+)(\S{6,})"),
    re.compile(r"\b[A-Za-z0-9+/_\-]{40,}={0,2}\b"),
]
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def redact(text: str) -> str:
    """Hide home paths, the user name, e-mail addresses and token-like strings."""
    home_s = str(plat.user_home())
    for h in {home_s, home_s.replace("\\", "/"), home_s.replace("/", "\\")}:
        if len(h) > 3:
            text = text.replace(h, "~")
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    if len(user) >= 3:
        text = re.sub(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(user), "<user>", text)
    text = _EMAIL_RE.sub("<email>", text)
    text = _TOKEN_RES[0].sub("<token>", text)
    text = _TOKEN_RES[1].sub(lambda m: m.group(1) + m.group(2) + "<redacted>", text)
    text = re.sub(r"\b(?=[A-Za-z0-9+/_\-]*[0-9])(?=[A-Za-z0-9+/_\-]*[A-Za-z])[A-Za-z0-9+/_\-]{40,}={0,2}",
                  lambda m: m.group(0) if re.fullmatch(r"[0-9a-f]{40,64}", m.group(0)) else "<token>", text)
    return text


def _tail(path: Path, n: int = 40) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            data = fh.read().decode("utf-8", "replace")
    except OSError as e:
        return "(unreadable: %s)" % e
    return "\n".join(data.splitlines()[-n:])


def _report_command(job: Optional[str]) -> Optional[Path]:
    """Use `showtime report` (the job module's bug report) when it is installed.

    It includes the job ledger, QA verdicts and log tails; this module's own
    writer below is the fallback when the venv or the job module is missing.
    """
    p = paths()
    vpy = p["venv_python"]
    if not (p["skill"] / "lib" / "st" / "job" / "report.py").is_file() or not vpy.exists():
        return None
    env = dict(os.environ)
    env["PYTHONPATH"] = str(p["skill"] / "lib") + ((os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    argv = [str(vpy), "-m", "st.cli", "report"] + ([job] if job else []) + ["--json"]
    try:
        cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                            env=env, timeout=600)
        res = json.loads(cp.stdout) if cp.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    out = Path(res["path"]) if isinstance(res, dict) and res.get("path") else None
    return out if out is not None and out.is_file() else None


def write_report(job: Optional[str], result: Dict[str, Any], use_job_module: bool = False) -> Path:
    """bug-report.md in the job folder (or the current folder): environment,
    doctor results, job.json and the tail of each log, redacted."""
    if use_job_module:
        hooked = _report_command(job)
        if hooked is not None:
            return hooked
    target = Path(job).expanduser() if job else Path.cwd()
    if job and not target.is_dir():
        raise ShowtimeError("job folder not found: %s" % target,
                            hint="pass a folder from showtime-out/, or omit it to write the report here")
    logs_dir = target / "work" / "logs"
    lines = ["# showtime bug report", "",
             "Written by `showtime doctor --report` on %s. Home paths, the user name, e-mails and token-like "
             "strings are redacted. Nothing was uploaded: read it, then share it only if you want to." % (
                 time.strftime("%Y-%m-%d %H:%M")), "",
             "## Environment", "", "| check | status | detail |", "|---|---|---|"]
    for r in result.get("checks", []):
        detail = str(r.get("detail", "")).replace("|", "\\|").replace("\n", " ")[:200]
        lines.append("| %s | %s | %s |" % (r.get("check"), str(r.get("status", "")).upper(), detail))
    fails = [r for r in result.get("checks", []) if r.get("status") in (FAIL, WARN) and r.get("hint")]
    if fails:
        lines += ["", "Suggested fixes:", ""] + ["- %s: %s" % (r["check"], r["hint"]) for r in fails]
    if job:
        lines += ["", "## Job: %s" % target.name, ""]
        jj = target / "job.json"
        if jj.is_file():
            lines += ["`job.json`:", "", "```json", _tail(jj, 200), "```", ""]
        else:
            lines += ["(no job.json in this folder)", ""]
        for name in ("SHOWTIME.md",):
            f = target / name
            if f.is_file():
                lines += ["`%s` (last lines):" % name, "", "```", _tail(f, 40), "```", ""]
        logs = sorted(logs_dir.glob("*.log")) if logs_dir.is_dir() else []
        for lg in logs[:20]:
            lines += ["`work/logs/%s` (last 40 lines):" % lg.name, "", "```", _tail(lg, 40), "```", ""]
        for extra in ("work/check/check.json", "work/check/report.json"):
            f = target / extra
            if f.is_file():
                lines += ["`%s`:" % extra, "", "```json", _tail(f, 120), "```", ""]
    out = target / ("bug-report.md" if job else "showtime-bug-report.md")
    out.write_text(redact("\n".join(lines)) + "\n", encoding="utf-8")
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="showtime doctor",
                                 description="Check the showtime installation (runs ffmpeg, Python imports, "
                                             "Node/Playwright and a headless browser for real). Every WARN/FAIL "
                                             "comes with a one-line fix.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Examples:\n"
                                        "  showtime doctor                      # full check (about 10-60 s)\n"
                                        "  showtime doctor --quick              # no test encode, no browser launch\n"
                                        "  showtime doctor --json               # for scripts and Claude\n"
                                        "  showtime doctor --report showtime-out/launch-20260926-101500\n"
                                        "                                       # write bug-report.md into that job\n\n"
                                        "The first run after a restart can take a few minutes while the OS checks the\n"
                                        "native libraries (macOS especially); a live line on stderr shows what is being\n"
                                        "checked. SHOWTIME_PROGRESS=off hides it.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quick", action="store_true", help="skip the test encode and the browser launch")
    ap.add_argument("--no-browser", action="store_true", help="skip only the browser launch")
    ap.add_argument("--verify", action="store_true", help="also sha256-check every model file (slow)")
    ap.add_argument("--gpu", default="auto", choices=["auto", "off"], help="GPU mode for the browser probe")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every model item, not only problems")
    ap.add_argument("--report", nargs="?", const="", metavar="JOB",
                    help="also write bug-report.md (environment, job.json, log tails; home paths and tokens "
                         "redacted) into JOB, or into the current folder; nothing is uploaded")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return Doctor(args).run()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
