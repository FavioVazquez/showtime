"""espeak-ng discovery and phonemization (Kokoro's grapheme-to-phoneme step).

espeak-ng has two failure modes that kill the whole Python process with no
traceback, so every candidate library is probed once in a subprocess and the
working choice is cached in ~/.showtime/cache/voice/espeak.json:

- its data directory path is kept in a fixed ~160-byte buffer: a longer path
  is silently truncated and espeak falls back to a path compiled in at build
  time, then calls exit();
- on Windows it opens the data directory through the ANSI code page, so a
  non-ASCII user name can break it.

Resolution order (first candidate whose probe succeeds wins):
  1. SHOWTIME_ESPEAK_LIB + SHOWTIME_ESPEAK_DATA (explicit paths)
  2. SHOWTIME_ESPEAK=bundled|system forces one family
  3. a system espeak-ng (Homebrew / MacPorts / apt / the Windows installer)
  4. the copy bundled in the `espeakng-loader` wheel (all platforms)
A data directory whose path is too long (or non-ASCII on Windows) is copied
once to a short location first: <home>/cache, %ProgramData% on Windows,
$TMPDIR, then /tmp/showtime-espeak-<uid> (a 0700 folder of this user) on
macOS and Linux.
"""
from __future__ import annotations

import ctypes.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .. import platform as plat
from ..common import ShowtimeError, debug, home, warn

MAX_DATA_PATH = 140          # espeak-ng keeps ~160 bytes incl. "/phontab" etc.
SHORT_ROOT = "/tmp"          # last resort when $SHOWTIME_HOME and $TMPDIR are both long (POSIX)
_lock = threading.RLock()
_ready: Optional[Tuple[str, str, str]] = None   # (lib, data, source)

_PROBE = r"""
import sys
from phonemizer.backend.espeak.wrapper import EspeakWrapper
import phonemizer
EspeakWrapper.set_data_path(sys.argv[2]); EspeakWrapper.set_library(sys.argv[1])
out = phonemizer.phonemize("hello world", "en-us", preserve_punctuation=True, with_stress=True)
es = phonemizer.phonemize("hola", "es", preserve_punctuation=True, with_stress=True)
print("OK|" + out.strip() + "|" + es.strip())
"""

# espeak-ng language codes for Kokoro voice prefixes (and friendly aliases).
LANG_ALIASES = {
    "en": "en-us", "en-us": "en-us", "american": "en-us", "en-gb": "en-gb", "british": "en-gb",
    "es": "es", "es-es": "es", "es-mx": "es-419", "es-419": "es-419", "spanish": "es",
    "fr": "fr-fr", "fr-fr": "fr-fr", "french": "fr-fr", "it": "it", "italian": "it",
    "pt": "pt-br", "pt-br": "pt-br", "portuguese": "pt-br", "pt-pt": "pt",
    "hi": "hi", "hindi": "hi", "ja": "ja", "japanese": "ja",
    "zh": "cmn", "cmn": "cmn", "mandarin": "cmn", "chinese": "cmn",
    "de": "de", "nl": "nl", "ko": "ko",
}


def espeak_lang(lang: str) -> str:
    """Map a public language code (en, es, zh, en-gb...) to espeak's code."""
    key = (lang or "en-us").strip().lower().replace("_", "-")
    return LANG_ALIASES.get(key, key)


def _bundled() -> Optional[Tuple[str, str]]:
    try:
        import espeakng_loader  # type: ignore
        lib, data = espeakng_loader.get_library_path(), espeakng_loader.get_data_path()
    except Exception as e:  # noqa: BLE001
        debug("espeakng_loader unavailable: %s" % e)
        return None
    if not Path(lib).is_file():
        # Some wheels ship only the versioned name (libespeak-ng.1.dylib, .so.1).
        for cand in sorted(Path(lib).parent.glob("*espeak-ng*")):
            if cand.is_file() and (cand.suffix in (".dylib", ".so", ".dll") or ".so." in cand.name
                                   or cand.name.endswith(".1.dylib")):
                lib = str(cand)
                break
    return (lib, data) if Path(lib).exists() and Path(data).is_dir() else None


def _system_candidates() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []

    def add(lib: Optional[str], data: Optional[Path]) -> None:
        if lib and data and data.is_dir() and (lib, str(data)) not in out:
            out.append((lib, str(data)))

    os_name = plat.os_name()
    exe = shutil.which("espeak-ng")
    prefixes: List[Path] = []
    if exe:
        prefixes.append(Path(exe).resolve().parent.parent)
    if os_name == "mac":
        prefixes += [Path("/opt/homebrew/opt/espeak-ng"), Path("/usr/local/opt/espeak-ng"),
                     Path("/opt/homebrew"), Path("/usr/local"), Path("/opt/local")]
        for pre in prefixes:
            for name in ("libespeak-ng.1.dylib", "libespeak-ng.dylib"):
                lib = pre / "lib" / name
                if lib.is_file():
                    add(str(lib), pre / "share" / "espeak-ng-data")
                    break
    elif os_name == "windows":
        # The installer puts espeak-ng.exe, libespeak-ng.dll and espeak-ng-data side by side.
        roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
        dirs = ([Path(exe).resolve().parent] if exe else []) + [Path(r) / "eSpeak NG" for r in roots if r]
        for d in dirs:
            lib = d / "libespeak-ng.dll"
            if lib.is_file():
                add(str(lib), d / "espeak-ng-data")
    else:  # linux / other unix
        found = ctypes.util.find_library("espeak-ng")
        libs = [found] if found else []
        for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/lib",
                  "/usr/local/lib"):
            for name in ("libespeak-ng.so.1", "libespeak-ng.so"):
                if Path(d, name).exists():
                    libs.append(str(Path(d, name)))
        datas = [Path(d) for d in ("/usr/lib/x86_64-linux-gnu/espeak-ng-data", "/usr/lib/aarch64-linux-gnu/espeak-ng-data",
                                   "/usr/share/espeak-ng-data", "/usr/local/share/espeak-ng-data",
                                   "/usr/lib/espeak-ng-data", "/usr/lib64/espeak-ng-data")]
        datas += [p / "share" / "espeak-ng-data" for p in prefixes]
        data = next((d for d in datas if (d / "phontab").is_file()), None)
        for lib in libs:
            add(lib, data)
    return out


def _needs_short_copy(data: str) -> bool:
    if len(os.fsencode(data)) > MAX_DATA_PATH:
        return True
    if plat.os_name() == "windows":
        try:
            data.encode("ascii")
        except UnicodeEncodeError:
            return True
    return False


def _private_dir(d: Path) -> bool:
    """Make d (in a shared folder such as /tmp) or accept it only as this user's own 0700 directory."""
    try:
        os.mkdir(str(d), 0o700)
    except FileExistsError:
        pass
    except OSError as e:
        debug("could not create %s: %s" % (d, e))
        return False
    try:
        st = os.lstat(str(d))
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        debug("not using %s: not a private directory of this user" % d)
        return False
    return True


def _shared_short() -> Optional[Path]:
    """/tmp/showtime-espeak-<uid>/espeak-ng-data (None on Windows: %ProgramData% is short there)."""
    if plat.os_name() == "windows":
        return None
    return Path(SHORT_ROOT) / ("showtime-espeak-%d" % os.getuid()) / "espeak-ng-data"


def _short_candidates() -> List[Path]:
    cands = [home() / "cache" / "espeak-ng-data"]
    if plat.os_name() == "windows":
        pd = os.environ.get("ProgramData") or os.environ.get("PUBLIC")
        if pd:
            cands.append(Path(pd) / "showtime" / "espeak-ng-data")
    cands.append(Path(tempfile.gettempdir()) / "showtime-espeak-ng-data")
    shared = _shared_short()
    return cands + ([shared] if shared else [])


def _short_copy(data: str) -> Optional[str]:
    """Copy espeak-ng-data to a short (ASCII) path; returns the new path."""
    shared = _shared_short()
    for c in _short_candidates():
        if _needs_short_copy(str(c)):
            continue
        if c == shared and not _private_dir(c.parent):
            continue
        try:
            if not (c / "phontab").is_file():
                tmp = c.with_name("%s.part-%d" % (c.name, os.getpid()))   # several homes can share this folder
                shutil.rmtree(str(tmp), ignore_errors=True)
                shutil.copytree(data, str(tmp))
                if (c / "phontab").is_file():                       # another process finished first
                    shutil.rmtree(str(tmp), ignore_errors=True)
                    return str(c)
                shutil.rmtree(str(c), ignore_errors=True)
                os.replace(str(tmp), str(c))
            return str(c)
        except OSError as e:
            debug("could not copy espeak data to %s: %s" % (c, e))
    return None


def _python() -> str:
    return sys.executable or "python"


def probe(lib: str, data: str, timeout: float = 90.0) -> Tuple[bool, str]:
    """Phonemize a word in a child process: a crash there cannot kill us."""
    try:
        cp = subprocess.run([_python(), "-c", _PROBE, lib, data], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    line = (cp.stdout or "").strip().splitlines()[-1:] or [""]
    if cp.returncode == 0 and line[0].startswith("OK|") and len(line[0]) > 6:
        return True, line[0][3:]
    err = ((cp.stderr or "") + (cp.stdout or "")).strip().splitlines()[-2:]
    return False, " / ".join(err) or "exit code %s" % cp.returncode


def _cache_file() -> Path:
    return home() / "cache" / "voice" / "espeak.json"


def _fingerprint(lib: str, data: str) -> str:
    try:
        st = os.stat(lib)
        return "%s|%s|%d|%d" % (lib, data, st.st_size, int(st.st_mtime))
    except OSError:
        return "%s|%s" % (lib, data)


def candidates() -> List[Tuple[str, str, str]]:
    """(lib, data, source) in resolution order."""
    env_lib, env_data = os.environ.get("SHOWTIME_ESPEAK_LIB"), os.environ.get("SHOWTIME_ESPEAK_DATA")
    if env_lib or env_data:
        if not (env_lib and env_data):
            raise ShowtimeError("set both SHOWTIME_ESPEAK_LIB and SHOWTIME_ESPEAK_DATA (or neither)")
        return [(env_lib, env_data, "env")]
    force = (os.environ.get("SHOWTIME_ESPEAK") or "").strip().lower()
    system = [(lib, data, "system") for lib, data in _system_candidates()]
    b = _bundled()
    bundled = [(b[0], b[1], "bundled")] if b else []
    if force == "bundled":
        return bundled
    if force == "system":
        return system
    return system + bundled


_cleanup_guarded = False


def _leftovers_file() -> Path:
    return home() / "cache" / "voice" / "espeak-tempdirs.txt"


def _is_phonemizer_tempdir(path: str) -> bool:
    """A folder phonemizer made with tempfile.mkdtemp() for its copy of the espeak-ng library."""
    p = Path(path)
    try:
        return (p.parent.resolve() == Path(tempfile.gettempdir()).resolve() and p.name.startswith("tmp")
                and all("espeak" in c.name.lower() for c in p.iterdir()))
    except OSError:
        return False


def _sweep_leftovers() -> None:
    """Remove the library copies earlier runs could not delete (see _guard_windows_cleanup)."""
    f = _leftovers_file()
    try:
        paths = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return
    keep = []
    for d in paths:
        if Path(d).is_dir() and _is_phonemizer_tempdir(d):
            shutil.rmtree(d, ignore_errors=True)
            if Path(d).exists():
                keep.append(d)   # still loaded by another running process
    try:
        if keep:
            f.write_text("\n".join(keep) + "\n", encoding="utf-8")
        else:
            f.unlink()
    except OSError:
        pass


def _guard_windows_cleanup() -> None:
    """Keep phonemizer's Windows exit hook from printing a traceback after a successful run.

    phonemizer copies the espeak-ng DLL into a new temporary folder for every EspeakAPI and, on
    Windows, deletes that folder from an atexit hook. When the copy is still mapped at exit (seen
    on Windows 11 on Arm, where showtime's x64 Python runs under emulation) the delete fails with
    PermissionError [WinError 5]: Python prints "Exception ignored in atexit callback" and the
    copy stays in %TEMP%. The hook is replaced by one that remembers such a folder instead, and
    the next run removes it. Must run before the first EspeakAPI is created.
    """
    global _cleanup_guarded
    if _cleanup_guarded or not plat.IS_WINDOWS:
        return
    _cleanup_guarded = True
    try:
        from phonemizer.backend.espeak import api  # type: ignore
    except Exception:  # noqa: BLE001 - phonemizer missing: nothing to guard
        return
    delete = getattr(api.EspeakAPI, "_delete", None)
    if delete is None or not hasattr(api.EspeakAPI, "_delete_win32"):
        return   # a phonemizer without this hook
    _sweep_leftovers()

    def _delete_win32(self) -> None:
        try:
            delete(self._library, self._tempdir)
        except Exception:  # noqa: BLE001 - at interpreter exit: never raise
            tmp = getattr(self, "_tempdir", None)
            if tmp and Path(tmp).exists():
                try:
                    f = _leftovers_file()
                    f.parent.mkdir(parents=True, exist_ok=True)
                    with open(f, "a", encoding="utf-8") as fh:
                        fh.write(str(tmp) + "\n")
                except OSError:
                    pass

    api.EspeakAPI._delete_win32 = _delete_win32


def resolve(refresh: bool = False) -> Tuple[str, str, str]:
    """Return a working (lib_path, data_path, source) or raise ShowtimeError."""
    global _ready
    _guard_windows_cleanup()
    with _lock:
        if _ready and not refresh:
            return _ready
        cache: Dict[str, dict] = {}
        cf = _cache_file()
        if cf.is_file() and not refresh:
            try:
                cache = json.loads(cf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache = {}
        errors, too_long = [], []
        for lib, data, source in candidates():
            if _needs_short_copy(data):
                short = _short_copy(data)
                if not short:
                    errors.append("%s: data path too long and could not be copied: %s" % (source, data))
                    if len(os.fsencode(data)) > MAX_DATA_PATH:   # (else: non-ASCII on Windows)
                        too_long.append(data)
                    continue
                data = short
            fp = _fingerprint(lib, data)
            hit = cache.get(fp)
            if hit and hit.get("ok"):
                _ready = (lib, data, source)
                return _ready
            if hit and not hit.get("ok"):
                errors.append("%s (%s): %s" % (source, lib, hit.get("error")))
                continue
            ok, msg = probe(lib, data)
            cache[fp] = {"ok": ok, "source": source, ("sample" if ok else "error"): msg}
            try:
                cf.parent.mkdir(parents=True, exist_ok=True)
                cf.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            if ok:
                _ready = (lib, data, source)
                return _ready
            warn("espeak-ng %s (%s) failed its self-test: %s" % (source, lib, msg))
            errors.append("%s (%s): %s" % (source, lib, msg))
        if too_long:
            # re-running setup cannot help: the folders are long, not missing
            shared = _shared_short()
            hint = ("espeak-ng cannot read a data folder whose path is longer than %d bytes (this one is %d), and "
                    "no shorter folder to copy it to was usable (SHOWTIME_HOME and TMPDIR are long too%s): point "
                    "SHOWTIME_HOME or TMPDIR at a shorter path, or set SHOWTIME_ESPEAK_LIB and SHOWTIME_ESPEAK_DATA "
                    "to an espeak-ng whose data folder has a short path"
                    % (MAX_DATA_PATH, len(os.fsencode(too_long[0])),
                       ", and %s is not writable or not this user's 0700 folder" % shared.parent if shared else ""))
        else:
            hint = ("re-run `showtime setup` (it installs espeakng-loader), or install espeak-ng "
                    "(macOS: brew install espeak-ng; Debian/Ubuntu: sudo apt install espeak-ng; "
                    "Windows: the espeak-ng .msi) or set SHOWTIME_ESPEAK_LIB and SHOWTIME_ESPEAK_DATA")
        raise ShowtimeError(
            "no working espeak-ng found (Kokoro needs it to turn text into phonemes)" +
            ("\n    " + "\n    ".join(errors) if errors else ""), hint=hint)


def check(refresh: bool = False) -> Dict[str, object]:
    """resolve() as JSON-ready data, for doctor and setup (which run it in the venv's Python)."""
    try:
        lib, data, source = resolve(refresh=refresh)
    except ShowtimeError as e:
        return {"ok": False, "error": e.message, "hint": e.hint}
    return {"ok": True, "lib": lib, "data": data, "source": source}


_configured = False
_LANG_FLAG = re.compile(r"\([a-z]{2,3}(?:-[a-z0-9]+)?\)")


def _configure() -> None:
    global _configured
    if _configured:
        return
    lib, data, source = resolve()
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    EspeakWrapper.set_data_path(data)
    EspeakWrapper.set_library(lib)
    # kokoro-onnx's Tokenizer re-applies its own config; keep it consistent.
    os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = lib
    debug("espeak-ng: %s (%s, data %s)" % (source, lib, data))
    _configured = True


def config():
    """A kokoro_onnx EspeakConfig for the resolved espeak-ng."""
    lib, data, _ = resolve()
    from kokoro_onnx.config import EspeakConfig
    return EspeakConfig(lib_path=lib, data_path=data)


_backends: Dict[str, object] = {}


def _backend(lang: str):
    """One EspeakBackend per language (creating one costs ~20 ms)."""
    b = _backends.get(lang)
    if b is None:
        _configure()
        from phonemizer.backend import EspeakBackend
        try:
            b = EspeakBackend(lang, preserve_punctuation=True, with_stress=True,
                              language_switch="remove-flags")
        except RuntimeError as e:
            raise ShowtimeError("espeak-ng does not support language %r (%s)" % (lang, e),
                                hint="languages: en-us en-gb es fr-fr it pt-br hi ja cmn (and ~100 more)")
        _backends[lang] = b
    return b


def phonemize(texts, lang: str = "en-us"):
    """Phonemize a string or a list of strings (IPA with stress marks).

    Language-switch flags such as "(en)" that espeak inserts for foreign
    words are removed, and newlines between clauses become spaces.
    """
    code = espeak_lang(lang)
    single = isinstance(texts, str)
    items = [texts] if single else list(texts)
    res = []
    with _lock:
        b = _backend(code)
        for item in items:
            if not item or not item.strip():
                res.append("")
                continue
            try:
                # espeak may break one input into several lines (e.g. at "3.5"):
                # the backend then returns several entries, all belonging to it.
                out = b.phonemize([item], strip=True)
            except RuntimeError as e:
                raise ShowtimeError("espeak-ng could not phonemize %r in %r: %s" % (item[:40], lang, e),
                                    hint="use a voice of that language or pass --lang")
            res.append(" ".join(_LANG_FLAG.sub("", " ".join(out)).split()))
    return res[0] if single else res
