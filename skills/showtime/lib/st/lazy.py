"""Components fetched on first use (everything outside the default install).

The default install stays small; a feature that needs more fetches it the first
time it runs, the same way from the CLI and from the MCP server:

    showtime: fetching whisper-small.en (486 MB) for transcription (one time; resumable)
    showtime: fetching whisper-small.en 120/486  24%  31.2 MB/s  ETA 11 s

Kinds of component (all listed by `showtime setup --plan`):

  item     a file set pinned in setup/manifest.json with "tier": "lazy" (or any other
           manifest item: an extra's model is fetched the same way). Downloads resume,
           are verified by size + sha256, and reuse a --seed folder or a shared Hugging
           Face cache copy first (setup.fetch).
  pip      pinned Python packages installed into the showtime venv with uv
           (manifest "lazy_pip", e.g. the Whisper engine).
  extra    a setup step (`showtime setup --fetch manim`), for extras marked "auto".
  library  the audio library's starter part and category parts (audio/libparts.py).
  icons    single icon SVGs from pinned package versions (assets/icons.py).
  browser  the headless shell or full Chromium (scripts/lib/chrome.mjs asks for them).

Offline (SHOWTIME_OFFLINE=1, or the host is unreachable) a missing component is a
ShowtimeError whose fix names `showtime setup --full` and `--seed DIR`, never a hang.

Generic ASR hook (for any engine): `ensure_asr(engine, model)` fetches whatever
ASR_COMPONENTS lists for that engine/model; adding an engine is one dict entry.

CLI (used by `showtime setup --fetch` for the kinds that need the venv):
    python -m st.lazy fetch whisper-engine audio-library icons
    python -m st.lazy status [--json]
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import platform as plat
from .common import ShowtimeError, cache_lock, debug, home, human_size, info, paths, skill_dir

# engine -> model name -> component ids (fnmatch-style "*" matches any model of that engine).
# The first transcription with that engine/model fetches these (in order).
ASR_COMPONENTS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "whisper": {"small.en": ("whisper-engine", "whisper-small.en"),
                "large-v3-turbo": ("whisper-engine", "whisper-large-v3-turbo"),
                "*": ("whisper-engine",)},
    "parakeet": {"sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8": ("parakeet-tdt-0.6b-v2-int8",),
                 "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8": ("parakeet-tdt-0.6b-v3-int8",)},
    # speech under loud music: the vocal separator (footage/separate.py), fetched only when a clip needs it
    "separate": {"*": ("uvr-mdx-net-voc-ft",)},
}

FULL_HINT = ("on a connected machine run `showtime setup --full` (installs every component up front), or copy the "
             "files listed by `showtime setup --plan --urls` into a folder and run `showtime setup --seed DIR --fetch %s`")


# ------------------------------------------------------------------ manifest / state

def _setup():
    """The installer module (setup/setup.py): shared fetcher, extractor, manifest helpers."""
    mod = sys.modules.get("showtime_setup_lazy")
    if mod is not None:
        return mod
    p = paths()["setup"] / "setup.py"
    spec = importlib.util.spec_from_file_location("showtime_setup_lazy", str(p))
    if spec is None or spec.loader is None:
        raise ShowtimeError("installer not found at %s" % p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["showtime_setup_lazy"] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def manifest() -> Dict[str, Any]:
    return json.loads((paths()["setup"] / "manifest.json").read_text(encoding="utf-8"))


def offline() -> bool:
    return os.environ.get("SHOWTIME_OFFLINE", "").strip().lower() not in ("", "0", "false", "no")


def _find_item(man: Dict[str, Any], item_id: str) -> Optional[Dict[str, Any]]:
    return next((it for it in man.get("items", []) if it["id"] == item_id), None)


def _state_update(fn: Callable[[Dict[str, Any]], None]) -> None:
    st = _setup().State(home())
    fn(st.data)
    st.save()


def _say(msg: str) -> None:
    info(msg)


def missing_error(cid: str, label: str, nbytes: int, feature: str, cause: Optional[str] = None) -> ShowtimeError:
    size = (" (%s)" % human_size(nbytes)) if nbytes else ""
    why = ("showtime fetches %s%s the first time %s needs it, and %s" %
           (label, size, feature, cause or "showtime is offline (SHOWTIME_OFFLINE is set)"))
    return ShowtimeError("%s needs %s, which is not downloaded yet" % (feature, label), why=why,
                         hint=FULL_HINT % cid, code=3)


class _Bytes:
    """Byte progress through showtime's Progress (the MCP server relays these lines)."""

    def __init__(self, cid: str, total: int) -> None:
        from .common import Progress
        self.mb = max(1, int(round(total / 1e6)))
        self.pr = Progress(total=self.mb, label="fetching %s" % cid, unit="MB/s", every=5.0)

    def __call__(self, done: int, _total: Optional[int] = None) -> None:
        self.pr.set(min(self.mb, done / 1e6))

    def close(self, ok: bool = True) -> None:
        self.pr.close(ok=ok)


# ------------------------------------------------------------------ manifest items

def item_ready(item_id: str) -> bool:
    man = manifest()
    it = _find_item(man, item_id)
    if it is None:
        return False
    return _setup().item_status(it, home(), plat.platform_key())[0] == "ok"


def item_path(item: Dict[str, Any], key: Optional[str] = None) -> Path:
    """Where an item lands: its `creates` path, or the folder of its first file."""
    files = _setup().item_files(item, key or plat.platform_key()) or []
    if not files:
        return home()
    f = files[0]
    if f.get("creates"):
        return home() / f["creates"]
    if f.get("archive"):
        return home() / f["dest"]
    return (home() / f["dest"]).parent


def ensure_item(item_id: str, feature: str, allow_download: bool = True) -> Path:
    """Make sure manifest item `item_id` is installed; fetch it (announced) if not. Returns item_path()."""
    su = _setup()
    man = manifest()
    it = _find_item(man, item_id)
    if it is None:
        raise ShowtimeError("unknown component %r" % item_id, hint="see `showtime setup --plan`")
    key = plat.platform_key()
    if su.item_status(it, home(), key)[0] == "ok":
        return item_path(it, key)
    files = su.item_files(it, key)
    if files is None:
        raise ShowtimeError("%s is not available for %s" % (item_id, key))
    nbytes = su.item_size(it, key)
    label = it.get("description", item_id).split(" (")[0]
    seeds = su.Seeds([d for d in os.environ.get("SHOWTIME_SEED_DIRS", "").split(os.pathsep) if d])
    if not allow_download or offline():
        # a seed folder, a shared cache copy or a SHOWTIME_MODEL_MIRROR folder still counts when offline
        from . import mirror
        if not all(seeds.find(f.get("size"), f.get("sha256"), f.get("url")) or mirror.local_copy(f.get("url", ""))
                   for f in files):
            raise missing_error(item_id, label, nbytes, feature)
    with cache_lock(paths()["cache"] / "lazy" / item_id, timeout=4 * 3600, stale=6 * 3600):
        if su.item_status(it, home(), key)[0] == "ok":      # another process just fetched it
            return item_path(it, key)
        _say("fetching %s (%s) for %s (one time; resumable, sha256-verified)" % (item_id, human_size(nbytes), feature))
        bar = _Bytes(item_id, nbytes)
        t0 = time.time()
        box: Dict[str, Any] = {}
        try:
            box["state"] = su.State(home())
            status, detail = su.install_files(it, home(), key, seeds, box["state"].data, verify=True, progress=bar)
        except Exception as e:  # noqa: BLE001
            bar.close(ok=False)
            msg = str(e)
            if offline() or "urlopen error" in msg or "Name or service not known" in msg or "timed out" in msg:
                raise missing_error(item_id, label, nbytes, feature, cause="the download failed (%s)" % msg[:200])
            raise ShowtimeError("could not fetch %s: %s" % (item_id, msg[:400]),
                                hint="run the command again (downloads resume), or `showtime setup --fetch %s`; "
                                     "`showtime doctor` checks the install" % item_id)
        bar.close(ok=True)
        rec = box["state"].data.setdefault("items", {}).setdefault(item_id, {})
        rec.update({"lazy": True, "fetched_for": feature})
        box["state"].save()
        _say("%s ready in %.0fs (%s)" % (item_id, time.time() - t0, detail))
    return item_path(it, key)


# ------------------------------------------------------------------ Python packages

def _venv_python() -> Path:
    return paths()["venv_python"]


def _in_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == _venv_python().resolve()
    except OSError:
        return False


def pip_ready(cid: str, man: Optional[Dict[str, Any]] = None) -> bool:
    spec = ((man or manifest()).get("lazy_pip") or {}).get(cid)
    if spec is None:
        return False
    mod = spec["import"]
    if _in_venv():
        importlib.invalidate_caches()
        return importlib.util.find_spec(mod) is not None
    vpy = _venv_python()
    if not vpy.exists():
        return False
    cp = subprocess.run([str(vpy), "-c", "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(%r) else 1)" % mod],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cp.returncode == 0


def pip_bytes(spec: Dict[str, Any], key: Optional[str] = None) -> int:
    b = spec.get("download_bytes") or {}
    return int(b.get(key or plat.platform_key()) or b.get("linux-x64") or 0)


def ensure_pip(cid: str, feature: str, allow_download: bool = True) -> None:
    """Install lazy Python component `cid` (manifest "lazy_pip") into the showtime venv if missing."""
    man = manifest()
    spec = (man.get("lazy_pip") or {}).get(cid)
    if spec is None:
        raise ShowtimeError("unknown Python component %r" % cid, hint="see `showtime setup --plan`")
    if pip_ready(cid, man):
        return
    nbytes = pip_bytes(spec)
    label = spec.get("description", cid)
    if not allow_download:
        raise missing_error(cid, label, nbytes, feature)
    uv = os.environ.get("SHOWTIME_UV") or plat.find_tool("uv")
    if offline() and (not uv or not _venv_python().exists()):
        raise missing_error(cid, label, nbytes, feature)
    if not uv:
        raise ShowtimeError("%s needs %s, and uv (the Python package installer) was not found" % (feature, label),
                            hint="install uv (see `showtime doctor`), then run `showtime setup --fetch %s`" % cid)
    vpy = _venv_python()
    if not vpy.exists():
        raise ShowtimeError("the showtime Python environment is missing", hint="run `showtime setup`")
    req = paths()["setup"] / spec["requirements"]
    with cache_lock(paths()["cache"] / "lazy" / cid, timeout=3600, stale=4 * 3600):
        if pip_ready(cid, man):
            return
        _say("fetching %s (about %s) for %s (one time)" % (cid, human_size(nbytes), feature))
        t0 = time.time()
        cmd = [uv, "pip", "install", "--python", str(vpy), "--only-binary", ":all:", "-r", str(req),
               "-c", str(paths()["setup"] / "requirements.txt")] + (["--offline"] if offline() else [])
        env = dict(os.environ)
        env.setdefault("UV_PYTHON_DOWNLOADS", "never")
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                            errors="replace", env=env)
        if cp.returncode != 0:
            tail = "\n".join((cp.stdout or "").strip().splitlines()[-8:])
            if offline():   # uv's cache did not hold every wheel
                raise missing_error(cid, label, nbytes, feature, cause="showtime is offline and uv's cache lacks "
                                    "some packages:\n" + tail)
            if "Failed to fetch" in tail or "dns error" in tail.lower() or "connect" in tail.lower():
                raise missing_error(cid, label, nbytes, feature, cause="the download failed:\n" + tail)
            raise ShowtimeError("installing %s failed:\n%s" % (cid, tail),
                                hint="run `showtime setup --fetch %s` to retry, then `showtime doctor`" % cid)
        importlib.invalidate_caches()
        _state_update(lambda d: d.setdefault("lazy_pip", {}).__setitem__(
            cid, {"installed": time.strftime("%Y-%m-%d"), "fetched_for": feature}))
        _say("%s ready in %.0fs" % (cid, time.time() - t0))


# ------------------------------------------------------------------ extras (setup steps)

def ensure_extra(name: str, feature: str) -> None:
    """Run `showtime setup --fetch <name>` for an extra marked "auto" (e.g. manim), announced."""
    from .common import extra_info
    ex = extra_info(name)
    size = ex.get("download_bytes") or int(((manifest().get("extras") or {}).get(name) or {}).get("approx_bytes") or 0)
    if offline():
        raise missing_error(name, ex.get("description", name).split(" (")[0], size, feature)
    _say("fetching %s (about %s) for %s (one time)" % (name, human_size(size) if size else "?", feature))
    base = getattr(sys, "_base_executable", None) or sys.executable
    rc = subprocess.call([base, str(paths()["setup"] / "setup.py"), "--fetch", name])
    if rc != 0:
        raise ShowtimeError("installing %s failed (exit %d)" % (name, rc),
                            hint="run `showtime setup --fetch %s` to see the details, then `showtime doctor`" % name)


# ------------------------------------------------------------------ ASR hook

def asr_components(engine: str, model: str) -> Tuple[str, ...]:
    table = ASR_COMPONENTS.get(engine) or {}
    return table.get(model) or table.get("*") or ()


def ensure_asr(engine: str, model: str, feature: str = "transcription") -> None:
    """Fetch what `engine`/`model` needs before the first transcription (no-op when present)."""
    man = manifest()
    for cid in asr_components(engine, model):
        if cid in (man.get("lazy_pip") or {}):
            ensure_pip(cid, feature)
        else:
            ensure_item(cid, feature)


# ------------------------------------------------------------------ status (doctor, plan)

def components(man: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every first-use component with its size for this platform and whether it is here yet."""
    man = man or manifest()
    su = _setup()
    key = plat.platform_key()
    out: List[Dict[str, Any]] = []
    for it in man.get("items", []):
        if it.get("tier") != "lazy":
            continue
        out.append({"id": it["id"], "kind": "item", "bytes": su.item_size(it, key), "when": it.get("when", "first use"),
                    "ready": su.item_status(it, home(), key)[0] == "ok"})
    for cid, spec in (man.get("lazy_pip") or {}).items():
        if spec.get("fallback_only"):
            continue
        out.append({"id": cid, "kind": "pip", "bytes": pip_bytes(spec, key), "when": spec.get("when", "first use"),
                    "ready": pip_ready(cid, man)})
    from .common import extra_installed
    for name, ex in (man.get("extras") or {}).items():
        if ex.get("auto"):
            out.append({"id": name, "kind": "extra", "bytes": int(ex.get("approx_bytes") or 0),
                        "when": ex.get("when", "first use"), "ready": extra_installed(name)})
    try:
        from .audio import libparts
        for p in libparts.status():
            if p["id"] == "extended":      # an explicit tier (`audio lib fetch --tier extended`), not first-use
                continue
            out.append({"id": "library:" + p["id"], "kind": "library", "bytes": p["bytes"], "when": p["when"],
                        "ready": p["ready"]})
    except Exception as e:  # noqa: BLE001 - informational
        debug("library parts status: %s" % e)
    out += _audio_first_use(man)
    return out


def _audio_first_use(man: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The produced-music catalog and the extra SFX packs: each track / pack arrives when first used."""
    out: List[Dict[str, Any]] = []
    for name, ex in (man.get("extras") or {}).items():
        if not ex.get("first_use"):
            continue
        files = audio_extra_files(name)
        ready = False
        try:
            if name == "music-catalog":
                from .audio import music
                ready = all(music.is_cached(t) for t in music.load_catalog()["tracks"] if t.get("status", "active") == "active")
            elif name == "sfx-packs":
                from .audio import packs
                ready = len(set(packs.installed_ids())) >= len(packs.load()["packs"])
        except Exception as e:  # noqa: BLE001 - informational
            debug("%s status: %s" % (name, e))
        out.append({"id": name, "kind": "audio", "bytes": sum(int(f.get("size") or 0) for f in files),
                    "when": ex.get("when", "first use"), "ready": ready})
    return out


def audio_extra_files(name: str) -> List[Dict[str, Any]]:
    """Pinned files ({url, sha256, size}) of the music catalog or the SFX packs (stdlib: plan, doctor)."""
    base = Path(__file__).resolve().parent / "audio"
    try:
        if name == "music-catalog":
            doc = json.loads((base / "music_catalog.json").read_text(encoding="utf-8"))
            return [{"url": t["file_url"], "sha256": t.get("sha256"), "size": t.get("bytes")} for t in doc["tracks"]
                    if t.get("file_url") and t.get("status", "active") == "active"]
        if name == "sfx-packs":
            doc = json.loads((base / "sfx_packs.json").read_text(encoding="utf-8"))
            return [{"url": p["url"], "sha256": p.get("sha256"), "size": p.get("bytes")} for p in doc["packs"]]
    except (OSError, ValueError, KeyError):
        pass
    return []


def status_line(comps: Sequence[Dict[str, Any]]) -> str:
    todo = [c for c in comps if not c["ready"]]
    if not todo:
        return "every first-use component is already here"
    return "%d not fetched yet (%s): %s" % (
        len(todo), human_size(sum(c["bytes"] for c in todo)),
        ", ".join("%s %s" % (c["id"], human_size(c["bytes"])) for c in todo[:8]) + (" ..." if len(todo) > 8 else ""))


def fetch_cli(names: Sequence[str]) -> int:
    """`python -m st.lazy fetch a b`: fetch named components now (setup --fetch uses it)."""
    man = manifest()
    rc = 0
    for n in names:
        try:
            if n in (man.get("lazy_pip") or {}):
                ensure_pip(n, "setup --fetch")
            elif n in ("audio-library", "library") or n.startswith("library:"):
                from .audio import libparts
                libparts.ensure(n.split(":", 1)[1] if ":" in n else "all", "setup --fetch")
            elif n == "icons":
                from .assets import icons
                icons.seed_all()
            elif _find_item(man, n) is not None:
                ensure_item(n, "setup --fetch")
            else:
                raise ShowtimeError("unknown component %r" % n, hint="see `showtime setup --plan`")
        except ShowtimeError as e:
            sys.stderr.write(e.format() + "\n")
            rc = e.code or 1
    return rc


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["fetch"] and argv[1:]:
        return fetch_cli(argv[1:])
    if argv[:1] == ["status"]:
        comps = components()
        if "--json" in argv:
            print(json.dumps(comps, indent=2))
        else:
            for c in comps:
                print("%-28s %-8s %10s  %-5s %s" % (c["id"], c["kind"], human_size(c["bytes"]),
                                                    "yes" if c["ready"] else "no", c["when"]))
        return 0
    sys.stderr.write("usage: python -m st.lazy fetch NAME... | status [--json]\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
