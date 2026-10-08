"""Install and resolve font families (Fontsource catalog: Google Fonts + other open fonts).

    showtime assets font "Space Grotesk"                 # 400 + 700, latin, ttf + woff2
    showtime assets font inter --weights all --subsets latin,latin-ext
    showtime assets font inter --path --weight 700       # print the TTF path (installs if needed)
    showtime assets fonts                                # installed families
    showtime assets fonts --search grotesk               # search the catalog

Layout: ~/.showtime/assets/fonts/<id>/
    <id>-<subset>-<weight>-<style>.ttf     static instances (libass / drawtext / PIL need these)
    <id>-<subset>-<weight>-<style>.woff2   same, compact for the browser
    <id>-<subset>-wght-<style>.woff2       variable font (when the family has one)
    font.css                               @font-face rules (relative URLs; copy the folder anywhere)
    font.json                              manifest (files, weights, version, license)
    <id>.license.json + LICENSE.txt        license sidecar and full license text

Files are pinned to the Fontsource package version reported by the API, so a
re-install gives byte-identical files. Only OFL / Apache / MIT / UFL families
are installed unless --allow-license is given.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..common import ShowtimeError, debug, log, paths, read_json, write_json
from . import licenses, net

API = "https://api.fontsource.org/v1"
CDN = "https://cdn.jsdelivr.net/fontsource/fonts"
GF_RAW = "https://raw.githubusercontent.com/google/fonts/main"
SPDX_RAW = "https://raw.githubusercontent.com/spdx/license-list-data/main/text"
CATALOG_TTL = 7 * 86400


def fonts_dir() -> Path:
    return paths()["fonts"]


def catalog() -> List[Dict[str, Any]]:
    """Every Fontsource family (cached for a week)."""
    data = net.get_json(API + "/fonts", ttl=CATALOG_TTL)
    if not isinstance(data, list):
        raise ShowtimeError("unexpected response from the Fontsource API")
    return data


def to_id(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.strip().lower()).strip("-")


def find(family: str) -> Dict[str, Any]:
    """Catalog entry for a family name or id; raises with suggestions."""
    fid = to_id(family)
    try:
        cat = catalog()
    except ShowtimeError:
        # offline: fall back to the per-family endpoint (also cached) or an installed copy
        inst = _installed_manifest(fid)
        if inst:
            return {"id": fid, "family": inst.get("family", family), "license": inst.get("license")}
        raise
    for f in cat:
        if f.get("id") == fid or str(f.get("family", "")).lower() == family.strip().lower():
            return f
    names = {f["family"]: f for f in cat}
    close = difflib.get_close_matches(family, list(names), n=5, cutoff=0.6)
    hint = ("did you mean: " + ", ".join(close)) if close else "search with: showtime assets fonts --search <words>"
    raise ShowtimeError("font family not found: %s" % family, hint=hint)


def details(fid: str) -> Dict[str, Any]:
    return net.get_json("%s/fonts/%s" % (API, fid), ttl=CATALOG_TTL)


def search(query: str, limit: int = 20, category: Optional[str] = None) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    out = []
    for f in catalog():
        name = str(f.get("family", "")).lower()
        if category and f.get("category") != category:
            continue
        if not q or q in name or q in f.get("id", ""):
            out.append(f)
    out.sort(key=lambda f: (not str(f.get("family", "")).lower().startswith(q), len(f.get("family", ""))))
    return out[:limit]


def _pick_weights(want: Optional[Sequence[str]], available: Sequence[int]) -> List[int]:
    avail = sorted(int(w) for w in available)
    if not avail:
        return []
    if not want:
        want = ["400", "700"]
    if len(want) == 1 and str(want[0]).lower() == "all":
        return avail
    out = []
    for w in want:
        try:
            wi = int(str(w).strip())
        except ValueError:
            named = {"thin": 100, "extralight": 200, "light": 300, "regular": 400, "normal": 400,
                     "medium": 500, "semibold": 600, "bold": 700, "extrabold": 800, "black": 900}
            wi = named.get(str(w).strip().lower().replace("-", ""), 400)
        best = min(avail, key=lambda a: (abs(a - wi), a))
        if best not in out:
            out.append(best)
    return sorted(out)


def _license_dir(meta: Dict[str, Any]) -> str:
    lic = str(meta.get("license", "")).lower()
    return "ofl" if lic.startswith("ofl") else ("apache" if lic.startswith("apache") else ("ufl" if lic.startswith("ufl") else "ofl"))


def _fetch_license_text(meta: Dict[str, Any], dest: Path) -> str:
    """Write LICENSE.txt; returns where it came from."""
    fam_dir = re.sub(r"[^a-z0-9]", "", str(meta.get("family", "")).lower())
    tries = []
    if meta.get("type") == "google" or str(meta.get("source", "")).startswith("https://github.com/google/fonts"):
        ld = _license_dir(meta)
        name = {"ofl": "OFL.txt", "apache": "LICENSE.txt", "ufl": "UFL.txt"}[ld]
        tries.append("%s/%s/%s/%s" % (GF_RAW, ld, fam_dir, name))
    spdx = str(meta.get("license") or "OFL-1.1")
    tries.append("%s/%s.txt" % (SPDX_RAW, spdx))
    for u in tries:
        try:
            body, _ = net.get_bytes(u, max_bytes=2 << 20, retries=1)
            if body.strip():
                dest.write_bytes(body)
                return u
        except ShowtimeError as e:
            debug("license text not at %s (%s)" % (u, e))
    dest.write_text("License: %s\nSee https://spdx.org/licenses/%s.html\n" % (spdx, spdx), encoding="utf-8")
    return "stub"


def _installed_manifest(fid: str) -> Optional[Dict[str, Any]]:
    p = fonts_dir() / fid / "font.json"
    if p.is_file():
        try:
            return read_json(p)
        except ShowtimeError:
            return None
    return None


def install(family: str, *, weights: Optional[Sequence[str]] = None, styles: Optional[Sequence[str]] = None,
            subsets: Optional[Sequence[str]] = None, formats: Sequence[str] = ("ttf", "woff2"),
            variable: bool = True, allow_license: bool = False, force: bool = False) -> Dict[str, Any]:
    """Download a family into ~/.showtime/assets/fonts/<id>/ and return its manifest."""
    meta0 = find(family)
    fid = meta0["id"]
    meta = details(fid)
    lic = meta.get("license") or meta0.get("license")
    if licenses.classify(lic) != licenses.FREE and not allow_license:
        raise ShowtimeError("%s is licensed %s" % (meta.get("family", fid), lic),
                            hint="showtime installs OFL/Apache/MIT/UFL fonts by default; pass --allow-license to override")
    version = meta.get("npmVersion") or "latest"
    styles = [s.strip() for s in (styles or ["normal"]) if s.strip()]
    styles = [s for s in styles if s in meta.get("styles", ["normal"])] or [meta.get("styles", ["normal"])[0]]
    subsets = [s.strip() for s in (subsets or [meta.get("defSubset") or "latin"]) if s.strip()]
    bad = [s for s in subsets if s not in meta.get("subsets", [])]
    if bad:
        raise ShowtimeError("%s has no subset %s" % (meta.get("family"), ", ".join(bad)),
                            hint="available: " + ", ".join(meta.get("subsets", [])))
    ws = _pick_weights(weights, meta.get("weights", [400]))
    d = fonts_dir() / fid
    d.mkdir(parents=True, exist_ok=True)
    normalize_installed(fid)
    prev = _installed_manifest(fid) or {}
    files: Dict[str, Dict[str, Any]] = {f["file"]: f for f in prev.get("files", [])} if not force else {}
    fetched = 0
    t0 = time.time()
    variants = meta.get("variants", {})
    for w in ws:
        for st in styles:
            for sub in subsets:
                v = variants.get(str(w), {}).get(st, {}).get(sub)
                if not v:
                    continue
                for fmt in formats:
                    url = (v.get("url") or {}).get(fmt)
                    if not url:
                        continue
                    url = url.replace("@latest/", "@%s/" % version)
                    name = "%s-%s-%s-%s.%s" % (fid, sub, w, st, fmt)
                    dest = d / name
                    if dest.is_file() and name in files and not force:
                        continue
                    info = net.download(url, dest, max_bytes=30 << 20,
                                        reject_types=("text/html",))
                    if info["ext"] not in (fmt, "ttf", "otf", "woff", "woff2"):
                        dest.unlink()
                        raise ShowtimeError("unexpected file for %s (%s)" % (name, info["ext"]))
                    rec = {"file": name, "weight": w, "style": st, "subset": sub, "format": fmt,
                           "variable": False, "url": url, "sha256": info["sha256"], "bytes": info["bytes"]}
                    if fmt in ("ttf", "otf"):
                        _fix_names(dest, meta.get("family", fid), rec)
                    files[name] = rec
                    fetched += 1
    axes = None
    if variable and meta.get("variable"):
        try:
            vinfo = net.get_json("%s/variable/%s" % (API, fid), ttl=CATALOG_TTL)
            axes = vinfo.get("axes")
        except ShowtimeError:
            axes = None
        for st in styles:
            for sub in subsets:
                name = "%s-%s-wght-%s.woff2" % (fid, sub, st)
                if name in files and (d / name).is_file() and not force:
                    continue
                url = "%s/%s:vf@%s/%s-wght-%s.woff2" % (CDN, fid, version, sub, st)
                try:
                    info = net.download(url, d / name, max_bytes=30 << 20, retries=1)
                except ShowtimeError as e:
                    debug("no variable file %s: %s" % (url, e))
                    continue
                wr = (axes or {}).get("wght") or {}
                files[name] = {"file": name, "weight": [int(float(wr.get("min", min(ws or [400])))),
                                                        int(float(wr.get("max", max(ws or [400]))))],
                               "style": st, "subset": sub, "format": "woff2", "variable": True,
                               "url": url, "sha256": info["sha256"], "bytes": info["bytes"]}
                fetched += 1
    if not files:
        raise ShowtimeError("no font files were available for %s with weights %s / styles %s"
                            % (meta.get("family"), ws, styles))
    lic_src = None
    if not (d / "LICENSE.txt").is_file() or force:
        lic_src = _fetch_license_text(meta, d / "LICENSE.txt")
    manifest = {
        "id": fid, "family": meta.get("family", fid), "category": meta.get("category"),
        "version": version, "license": lic, "type": meta.get("type"),
        "source": meta.get("source") or "https://fontsource.org/fonts/%s" % fid,
        "axes": axes if axes is not None else prev.get("axes"),
        "subsets": sorted(set(prev.get("subsets", [])) | set(subsets)),
        "weights": sorted({f["weight"] for f in files.values() if not f.get("variable")}),
        "styles": sorted({f["style"] for f in files.values()}),
        "files": sorted(files.values(), key=lambda f: (f["variable"], f["subset"], str(f["weight"]), f["style"], f["format"])),
        "names_fixed": NAMES_VERSION,
        "installed": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(d / "font.json", manifest)
    (d / "font.css").write_text(css_for(manifest, meta.get("unicodeRange") or {}), encoding="utf-8")
    licenses.write_sidecar(d / fid, {
        "source": "fontsource", "source_label": "Fontsource", "id": fid, "title": manifest["family"],
        "license": lic, "license_url": "https://spdx.org/licenses/%s.html" % lic,
        "landing_url": "https://fontsource.org/fonts/%s" % fid, "license_text": "LICENSE.txt",
        "license_text_source": lic_src,
    })
    manifest["dir"] = str(d)
    manifest["fetched"] = fetched
    manifest["seconds"] = round(time.time() - t0, 2)
    return manifest


NAMES_VERSION = 1
DEFAULT_WEIGHTS = (400, 700)


def _fix_names(path: Path, family: str, rec: Dict[str, Any]) -> None:
    """Give a static TTF/OTF the family/style names libass and Pillow match on.

    The download's own hash stays in rec["sha256"]; the rewrite is deterministic."""
    from . import sfnt
    try:
        data = path.read_bytes()
        w, italic = int(rec["weight"]), rec.get("style") == "italic"
        if sfnt.needs_names(data, family, w, italic):
            fixed = sfnt.set_style_names(data, family, w, italic)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(fixed)
            tmp.replace(path)
            rec["renamed"] = True
    except (OSError, ValueError, KeyError) as e:  # a naming problem must never lose the font
        debug("could not normalise names in %s: %s" % (path, e))


def normalize_installed(fid: str) -> bool:
    """Fix internal names of an already installed family (older installs). -> changed"""
    m = _installed_manifest(fid)
    if not m or m.get("names_fixed") == NAMES_VERSION:
        return False
    d = fonts_dir() / fid
    for f in m.get("files", []):
        if not f.get("variable") and f.get("format") in ("ttf", "otf") and (d / f["file"]).is_file():
            _fix_names(d / f["file"], m.get("family", fid), f)
    m["names_fixed"] = NAMES_VERSION
    write_json(d / "font.json", m)
    return True


def css_for(manifest: Dict[str, Any], unicode_ranges: Dict[str, str]) -> str:
    """@font-face rules for the installed files (variable woff2 first, then static)."""
    fam = manifest["family"]
    out = ["/* %s %s (%s) - generated by showtime; url()s are relative to this file */" % (
        fam, manifest.get("version"), manifest.get("license"))]
    by_var = [f for f in manifest["files"] if f.get("variable")]
    static = [f for f in manifest["files"] if not f.get("variable")]
    var_keys = {(f["subset"], f["style"]) for f in by_var}
    for f in by_var:
        lo, hi = f["weight"]
        out.append(_face(fam, "%d %d" % (lo, hi), f["style"], [("%s" % f["file"], "woff2-variations")],
                         unicode_ranges.get(f["subset"])))
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for f in static:
        if (f["subset"], f["style"]) in var_keys:
            continue  # the variable file already covers these weights
        groups.setdefault((f["subset"], f["weight"], f["style"]), []).append(f)
    order = {"woff2": 0, "woff": 1, "ttf": 2, "otf": 3}
    for (sub, w, st), fs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        fs.sort(key=lambda f: order.get(f["format"], 9))
        srcs = [(f["file"], {"ttf": "truetype", "otf": "opentype"}.get(f["format"], f["format"])) for f in fs]
        out.append(_face(fam, str(w), st, srcs, unicode_ranges.get(sub)))
    return "\n".join(out) + "\n"


def _face(family: str, weight: str, style: str, srcs: List[tuple], urange: Optional[str]) -> str:
    src = ", ".join('url("%s") format("%s")' % (u, f) for u, f in srcs)
    lines = ["@font-face {", "  font-family: '%s';" % family.replace("'", "\\'"), "  font-style: %s;" % style,
             "  font-weight: %s;" % weight, "  font-display: block;", "  src: %s;" % src]
    if urange:
        lines.append("  unicode-range: %s;" % urange)
    lines.append("}")
    return "\n".join(lines)


def list_installed() -> List[Dict[str, Any]]:
    out = []
    root = fonts_dir()
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        m = _installed_manifest(d.name)
        if not m:
            continue
        out.append({"id": m["id"], "family": m["family"], "license": m.get("license"),
                    "weights": m.get("weights"), "styles": m.get("styles"), "subsets": m.get("subsets"),
                    "variable": any(f.get("variable") for f in m.get("files", [])),
                    "files": len(m.get("files", [])), "dir": str(d), "css": str(d / "font.css")})
    return out


def resolve(family: str, weight: int = 400, style: str = "normal", fmt: str = "ttf",
            subset: Optional[str] = None, install_missing: bool = True) -> Path:
    """Path to the closest installed static file (installing the weight if needed).

    fmt 'ttf' is what libass (fontsdir=), ffmpeg drawtext and PIL want.
    """
    fid = to_id(family)
    normalize_installed(fid)
    for attempt in (0, 1):
        m = _installed_manifest(fid)
        if m:
            cands = [f for f in m.get("files", []) if not f.get("variable") and f["format"] == fmt
                     and f["style"] == style and (subset is None or f["subset"] == subset)]
            if cands:
                best = min(cands, key=lambda f: (abs(int(f["weight"]) - int(weight)), f["subset"] != "latin"))
                if abs(int(best["weight"]) - int(weight)) <= 50 or attempt == 1 or not install_missing:
                    p = fonts_dir() / fid / best["file"]
                    if p.is_file():
                        return p
        if attempt == 0 and install_missing:
            log("installing font %s %s %s (%s)" % (family, weight, style, fmt))
            # always keep a regular and a bold cut beside the requested one, so tools that pick
            # "bold" or "regular" by family name never land on an odd weight
            want = sorted({int(weight)} | set(DEFAULT_WEIGHTS))
            install(family, weights=[str(w) for w in want], styles=[style], subsets=[subset] if subset else None,
                    formats=(fmt, "woff2") if fmt != "woff2" else ("woff2",))
    raise ShowtimeError("font %s %s %s (%s) is not installed" % (family, weight, style, fmt),
                        hint="run: showtime assets font \"%s\" --weights %s" % (family, weight))


def copy_to(family: str, dest_dir: Path) -> Path:
    """Copy an installed family folder (files + font.css + license) into a project."""
    fid = to_id(family)
    src = fonts_dir() / fid
    if not (src / "font.json").is_file():
        install(family)
    dest = Path(dest_dir) / fid
    dest.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file():
            shutil.copy2(str(p), str(dest / p.name))
    return dest


GOOGLE_CSS_HOSTS = ("fonts.googleapis.com",)
_FACE_RE = re.compile(r"(?:/\*\s*([\w-]+)\s*\*/\s*)?@font-face\s*\{([^}]*)\}", re.S)


def is_google_css(url: str) -> bool:
    import urllib.parse
    try:
        u = urllib.parse.urlsplit(url.replace("&amp;", "&"))
    except ValueError:
        return False
    return u.scheme in ("http", "https") and (u.hostname or "").lower() in GOOGLE_CSS_HOSTS and u.path in ("/css", "/css2")


def parse_font_css(css: str) -> List[Dict[str, Any]]:
    """@font-face rules of a stylesheet -> [{family, style, weight, stretch, url, format, unicode_range, subset}]."""
    out = []
    for m in _FACE_RE.finditer(css):
        body = m.group(2)

        def prop(name: str) -> Optional[str]:
            pm = re.search(r"(?:^|;)\s*%s\s*:\s*([^;]+)" % re.escape(name), body)
            return pm.group(1).strip() if pm else None
        fam = (prop("font-family") or "").strip().strip("'\"")
        src = prop("src") or ""
        um = re.search(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)\s*(?:format\(\s*['\"]?([\w-]+)['\"]?\s*\))?", src)
        if not fam or not um:
            continue
        out.append({"family": fam, "style": prop("font-style") or "normal", "weight": prop("font-weight") or "400",
                    "stretch": prop("font-stretch"), "url": um.group(1), "format": um.group(2) or "woff2",
                    "unicode_range": prop("unicode-range"), "subset": m.group(1) or ""})
    return out


GSTATIC = "https://fonts.gstatic.com/"


def _https(url: str) -> str:
    """A Google Fonts link over plain http (or scheme-relative) -> the same link over https."""
    u = str(url).strip()
    if u.startswith("//"):
        return "https:" + u
    if u[:7].lower() == "http://":
        return "https://" + u[7:]
    return u


def _safe_part(s: Any) -> str:
    """One piece of a file name built from the stylesheet (weight, style, subset): no separators."""
    return re.sub(r"[^A-Za-z0-9.-]+", "-", str(s)).strip("-.") or "x"


def _safe_id(fid: Any, family: str) -> str:
    """A family folder name: the catalog id, cleaned the way to_id cleans a family name."""
    return to_id(str(fid or "")) or to_id(family) or "font"


def _write_local_css(url: str, faces: List[Dict[str, Any]], path: Path) -> None:
    css = ["/* %s - made local by showtime; url()s are relative to this file */" % url]
    for fc in faces:
        lines = ["@font-face {", "  font-family: '%s';" % fc["family"].replace("'", "\\'"), "  font-style: %s;" % fc["style"],
                 "  font-weight: %s;" % fc["weight"]]
        if fc.get("stretch"):
            lines.append("  font-stretch: %s;" % fc["stretch"])
        lines += ["  font-display: block;", '  src: url("%s") format("%s");' % (fc["local"], fc["format"])]
        if fc.get("unicode_range"):
            lines.append("  unicode-range: %s;" % fc["unicode_range"])
        css.append("\n".join(lines + ["}"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(css) + "\n", encoding="utf-8")


def _local_copy(url: str, dest_dir: Path, css_name: str, allow_license: bool) -> Optional[Dict[str, Any]]:
    """The fonts an earlier from_css copied for this stylesheet, when every file is still there with its
    sha256 (and its license text): -> the manifest, with the stylesheet written again from it. None when
    anything is missing or changed (then the stylesheet is fetched again)."""
    mpath = dest_dir / (Path(css_name).stem + ".json")
    if not mpath.is_file():
        return None
    try:
        m = read_json(mpath)
        if _https(m.get("stylesheet") or "") != url or not m.get("families"):
            return None
        local = set()
        for fam in m["families"]:
            fid = fam["id"]
            if fid != _safe_id(fid, fam["family"]) or not fam.get("files"):
                return None
            if licenses.classify(fam.get("license")) != licenses.FREE and not allow_license:
                return None
            d = dest_dir / fid
            if not (d / "LICENSE.txt").is_file():
                return None
            for f in fam["files"]:
                name = f["file"]
                if not isinstance(name, str) or name != Path(name).name or name.startswith("."):
                    return None
                if not (d / name).is_file() or hashlib_sha(d / name) != f.get("sha256"):
                    return None
                local.add("%s/%s" % (fid, name))
        faces = m.get("faces")
        css = dest_dir / css_name
        if faces:
            if any(fc.get("local") not in local for fc in faces):
                return None
            _write_local_css(url, faces, css)
        elif not css.is_file():
            return None
    except (ShowtimeError, KeyError, TypeError, AttributeError, OSError):
        return None
    log("the fonts of %s are already in %s (nothing downloaded)" % (url, dest_dir))
    m["css"] = css_name
    m["dir"] = str(dest_dir)
    return m


def from_css(url: str, dest_dir: Path, *, allow_license: bool = False, css_name: str = "fonts.css") -> Dict[str, Any]:
    """Make a Google Fonts stylesheet local: the same files a browser gets for `url`, saved under
    dest_dir/<id>/ with their license, and dest_dir/fonts.css with @font-face rules pointing at them.

    The axes and weights are exactly the ones the link asked for (a variable cut stays variable), so the
    page draws what it drew online; font-display becomes block, so a render never catches a fallback.
    When every file of an earlier copy for the same link is still there (same sha256), nothing is
    fetched at all, so a refresh works offline. The link is fetched over https only, font files only
    from fonts.gstatic.com, and file names are built from cleaned pieces with the extension of the
    bytes received."""
    url = _https(url.replace("&amp;", "&"))
    if not is_google_css(url):
        raise ShowtimeError("not a Google Fonts stylesheet: %s" % url,
                            hint="pass the fonts.googleapis.com/css2?family=... link the page uses")
    dest_dir = Path(dest_dir)
    if Path(css_name).name != css_name or not css_name.endswith(".css"):
        raise ShowtimeError("--css-name must be a file name ending in .css (got %s)" % css_name)
    cached = _local_copy(url, dest_dir, css_name, allow_license)
    if cached:
        return cached
    # a browser agent: Google serves WOFF2 (and variable axes) only to browsers it knows
    body, _ = net.get_bytes(url, headers={"User-Agent": net.BROWSER_UA, "Accept": "text/css,*/*;q=0.1"},
                            max_bytes=2 << 20, retries=2)
    faces = parse_font_css(body.decode("utf-8", "replace"))
    if not faces:
        raise ShowtimeError("no @font-face rules in %s" % url, hint="check the link in a browser")
    for fc in faces:
        fc["url"] = _https(fc["url"])
        if not fc["url"].startswith(GSTATIC):
            raise ShowtimeError("the stylesheet %s names a font file outside %s: %s" % (url, GSTATIC, fc["url"][:120]),
                                hint="only files on Google's own font host are copied; download that font yourself")
    prev = {}
    mpath = dest_dir / (Path(css_name).stem + ".json")
    if mpath.is_file():
        try:
            prev = {f["url"]: f for fam in read_json(mpath).get("families", []) for f in fam.get("files", [])}
        except (ShowtimeError, KeyError, TypeError):
            prev = {}
    fams: Dict[str, Dict[str, Any]] = {}
    files_by_url: Dict[str, Dict[str, Any]] = {}
    bases: set = set()
    for fc in faces:
        fam = fams.get(fc["family"])
        if fam is None:
            fid = to_id(fc["family"])
            try:
                meta0 = find(fc["family"])
                fid = meta0.get("id", fid)
                lic = meta0.get("license")
            except ShowtimeError as e:
                debug("license lookup for %s failed: %s" % (fc["family"], e))
                meta0, lic = {"id": fid, "family": fc["family"]}, None
            fid = _safe_id(fid, fc["family"])
            if licenses.classify(lic) != licenses.FREE and not allow_license:
                raise ShowtimeError("%s is licensed %s" % (fc["family"], lic or "unknown (not in the Fontsource catalog)"),
                                    hint="showtime copies OFL/Apache/MIT/UFL fonts by default; pass --allow-license to override")
            fam = fams[fc["family"]] = {"family": fc["family"], "id": fid, "license": lic, "meta": meta0, "files": []}
        rec = files_by_url.get(fc["url"])
        if rec is None:
            base = "%s-%s-%s-%s" % (fam["id"], _safe_part(fc["subset"] or "all"), _safe_part(fc["weight"].strip()),
                                    _safe_part(fc["style"]))
            b0, n = base, 2
            while base in bases:
                base = "%s-%d" % (b0, n)
                n += 1
            bases.add(base)
            d = dest_dir / fam["id"]
            old = prev.get(fc["url"])
            oname = old.get("file") if old else None
            if (isinstance(oname, str) and oname == Path(oname).name and Path(oname).stem == base and (d / oname).is_file()
                    and hashlib_sha(d / oname) == old.get("sha256")):
                rec = dict(old)
            else:
                tmp = d / (base + ".download")
                info = net.download(fc["url"], tmp, max_bytes=30 << 20, reject_types=("text/html",))
                ext = info.get("ext")
                if ext not in ("ttf", "otf", "woff", "woff2"):
                    tmp.unlink()
                    raise ShowtimeError("unexpected file for %s (%s)" % (base, ext or "not a font"))
                name = "%s.%s" % (base, ext)
                os.replace(str(tmp), str(d / name))
                rec = {"file": name, "url": fc["url"], "sha256": info["sha256"], "bytes": info["bytes"]}
            files_by_url[fc["url"]] = rec
            fam["files"].append(rec)
        fc["local"] = "%s/%s" % (fam["id"], rec["file"])
    for fam in fams.values():
        d = dest_dir / fam["id"]
        d.mkdir(parents=True, exist_ok=True)
        lic_src = None
        if not (d / "LICENSE.txt").is_file():
            meta = fam["meta"]
            try:
                meta = details(fam["id"])
            except ShowtimeError:
                pass
            lic_src = _fetch_license_text(dict(meta, family=fam["family"], license=fam["license"] or meta.get("license")), d / "LICENSE.txt")
        licenses.write_sidecar(d / fam["id"], {
            "source": "google-fonts", "source_label": "Google Fonts", "id": fam["id"], "title": fam["family"],
            "license": fam["license"], "license_url": "https://spdx.org/licenses/%s.html" % fam["license"],
            "landing_url": "https://fonts.google.com/specimen/%s" % fam["family"].replace(" ", "+"),
            "license_text": "LICENSE.txt", "license_text_source": lic_src, "stylesheet": url,
        })
    _write_local_css(url, faces, dest_dir / css_name)
    manifest = {
        "stylesheet": url, "css": css_name,
        "families": [{"family": f["family"], "id": f["id"], "license": f["license"], "files": f["files"]} for f in fams.values()],
        "faces": [{k: fc.get(k) for k in ("family", "style", "weight", "stretch", "format", "unicode_range", "local")} for fc in faces],
    }
    write_json(mpath, manifest)
    manifest["dir"] = str(dest_dir)
    return manifest


def hashlib_sha(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def remove(family: str) -> bool:
    d = fonts_dir() / to_id(family)
    if d.is_dir():
        shutil.rmtree(str(d))
        return True
    return False


def parse_list(s: Optional[str]) -> Optional[List[str]]:
    if s is None:
        return None
    return [x.strip() for x in str(s).split(",") if x.strip()]
