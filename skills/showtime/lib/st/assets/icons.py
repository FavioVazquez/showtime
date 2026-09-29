"""Icon lookup: Lucide, Phosphor, Tabler, simple-icons (brand logos), Heroicons -> recoloured SVG.

    showtime assets icon lucide rocket --color "#a78bfa" --size 128
    showtime assets icon phosphor rocket --weight duotone -o scene/rocket.svg
    showtime assets icon simple-icons github --color brand --png --size 512
    showtime assets icons deploy --set lucide              # search names + tags

Icons are fetched one at a time on first use from the pinned package versions on
jsDelivr and kept in ~/.showtime/cache/icons/<package>@<version>/ (a few KB each),
instead of installing ~175 MB of icon packages up front. An older install that still
has the packages in ~/.showtime/node is used first. Offline machines pre-seed the
cache with the pinned npm tarballs: `showtime setup --fetch icons` (or --full, or
--seed DIR with the tarballs from `showtime setup --plan --urls`).
Licenses: Lucide ISC, Phosphor MIT, Tabler MIT, Heroicons MIT, simple-icons CC0
(brand logos are trademarks: only use them to depict that brand).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ShowtimeError, debug, paths, skill_dir
from . import licenses, net

CDN = "https://cdn.jsdelivr.net/npm"

SETS: Dict[str, Dict[str, Any]] = {
    "lucide": {"pkg": "lucide-static", "version": "1.48.0", "license": "ISC", "kind": "stroke",
               "variants": ["default"], "home": "https://lucide.dev/icons/{name}"},
    "phosphor": {"pkg": "@phosphor-icons/core", "version": "2.1.1", "license": "MIT", "kind": "fill",
                 "variants": ["regular", "thin", "light", "bold", "fill", "duotone"],
                 "home": "https://phosphoricons.com/?q={name}"},
    "tabler": {"pkg": "@tabler/icons", "version": "3.48.0", "license": "MIT", "kind": "stroke",
               "variants": ["outline", "filled"], "home": "https://tabler.io/icons/icon/{name}"},
    "simple-icons": {"pkg": "simple-icons", "version": "16.33.0", "license": "CC0-1.0", "kind": "brand",
                     "variants": ["default"], "home": "https://simpleicons.org/?q={name}"},
    "heroicons": {"pkg": "heroicons", "version": "2.2.0", "license": "MIT", "kind": "stroke",
                  "variants": ["outline", "solid", "mini", "micro"], "home": "https://heroicons.com"},
}
ALIASES = {"brands": "simple-icons", "simple": "simple-icons", "si": "simple-icons", "logos": "simple-icons",
           "ph": "phosphor", "hero": "heroicons", "lucide-static": "lucide"}


def norm_set(name: str) -> str:
    n = name.strip().lower()
    n = ALIASES.get(n, n)
    if n not in SETS:
        raise ShowtimeError("unknown icon set: %s" % name, hint="sets: " + ", ".join(SETS))
    return n


def _node_pkg_dir(pkg: str) -> Path:
    env = os.environ.get("SHOWTIME_NODE_MODULES")
    base = Path(env) if env else paths()["node_modules"]
    return base.joinpath(*pkg.split("/"))


def cache_dir(set_name: str) -> Path:
    """~/.showtime/cache/icons/<package>@<version>: icons fetched one by one, or a seeded package."""
    s = SETS[set_name]
    return paths()["cache"] / "icons" / ("%s@%s" % (s["pkg"].replace("/", "+"), s["version"]))


def _pkg_dir(pkg: str) -> Path:
    """The package folder to read from: node_modules when an older install has it, else the icon cache."""
    d = _node_pkg_dir(pkg)
    if d.is_dir():
        return d
    for name, s in SETS.items():
        if s["pkg"] == pkg:
            return cache_dir(name)
    return d


def _seeded(set_name: str) -> bool:
    return (cache_dir(set_name) / ".seeded").is_file() or _node_pkg_dir(SETS[set_name]["pkg"]).is_dir()


def _rel_path(set_name: str, name: str, variant: Optional[str]) -> str:
    s = SETS[set_name]
    v = variant or s["variants"][0]
    if v not in s["variants"]:
        raise ShowtimeError("%s has no variant %r" % (set_name, v), hint="variants: " + ", ".join(s["variants"]))
    if set_name == "lucide":
        return "icons/%s.svg" % name
    if set_name == "phosphor":
        return "assets/%s/%s%s.svg" % (v, name, "" if v == "regular" else "-" + v)
    if set_name == "tabler":
        return "icons/%s/%s.svg" % (v, name)
    if set_name == "simple-icons":
        return "icons/%s.svg" % name
    if set_name == "heroicons":
        return {"outline": "24/outline", "solid": "24/solid", "mini": "20/solid", "micro": "16/solid"}[v] + "/%s.svg" % name
    raise AssertionError(set_name)


def _names_local(set_name: str, variant: Optional[str] = None) -> Optional[List[str]]:
    s = SETS[set_name]
    if not _seeded(set_name):
        return None                  # a cache of single icons is not a full listing
    d = _pkg_dir(s["pkg"])
    if not d.is_dir():
        return None
    rel = _rel_path(set_name, "__X__", variant)
    folder = d / Path(rel).parent
    if not folder.is_dir():
        return None
    suffix = Path(rel).name.replace("__X__", "")
    return sorted(p.name[:-len(suffix)] for p in folder.iterdir() if p.name.endswith(suffix))


def _names_cdn(set_name: str, variant: Optional[str] = None) -> List[str]:
    s = SETS[set_name]
    data = net.get_json("https://data.jsdelivr.com/v1/packages/npm/%s@%s?structure=flat" % (s["pkg"], s["version"]),
                        ttl=30 * 86400)
    rel = _rel_path(set_name, "__X__", variant)
    prefix = "/" + str(Path(rel).parent).replace("\\", "/") + "/"
    suffix = Path(rel).name.replace("__X__", "")
    out = []
    for f in data.get("files", []):
        n = f.get("name", "")
        if n.startswith(prefix) and n.endswith(suffix) and "/" not in n[len(prefix):]:
            out.append(n[len(prefix):-len(suffix)])
    return sorted(out)


def names(set_name: str, variant: Optional[str] = None) -> List[str]:
    set_name = norm_set(set_name)
    local = _names_local(set_name, variant)
    return local if local is not None else _names_cdn(set_name, variant)


def _tags(set_name: str) -> Dict[str, List[str]]:
    """Keyword tags per icon where the package ships them (lucide tags.json, simple-icons titles)."""
    try:
        if set_name == "lucide":
            return json.loads(_pkg_file(set_name, "tags.json", max_bytes=8 << 20).decode("utf-8"))
        if set_name == "simple-icons":
            data = json.loads(_pkg_file(set_name, "data/simple-icons.json", max_bytes=16 << 20).decode("utf-8"))
            return {x["slug"]: [x.get("title", "")] + list((x.get("aliases") or {}).get("aka", [])) for x in data
                    if x.get("slug")}
    except (OSError, ValueError, KeyError, ShowtimeError) as e:
        debug("no tags for %s (%s)" % (set_name, e))
    return {}


def _pkg_file(set_name: str, rel: str, max_bytes: int = 2 << 20) -> bytes:
    """One file of a pinned icon package: node_modules, then the icon cache, then jsDelivr (cached)."""
    s = SETS[set_name]
    for base in (_node_pkg_dir(s["pkg"]), cache_dir(set_name)):
        f = base / rel
        if f.is_file():
            return f.read_bytes()
    url = "%s/%s@%s/%s" % (CDN, s["pkg"], s["version"], rel)
    if net.offline():
        raise ShowtimeError("%s %s is not cached yet and showtime is offline" % (s["pkg"], rel),
                            why="icons are fetched one at a time on first use",
                            hint="on a connected machine run `showtime setup --fetch icons` (all icon sets, ~16 MB) or "
                                 "`showtime setup --full`; or copy the tarballs from `showtime setup --plan --urls` "
                                 "into a folder and run `showtime setup --seed DIR --fetch icons`", code=3)
    body, _ = net.get_bytes(url, max_bytes=max_bytes)
    dest = cache_dir(set_name) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    from ..common import part_path
    tmp = part_path(dest)
    tmp.write_bytes(body)
    os.replace(str(tmp), str(dest))
    return body


def search(query: str, set_name: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    q = query.strip().lower().replace(" ", "-")
    sets = [norm_set(set_name)] if set_name else ["lucide", "phosphor", "tabler", "simple-icons"]
    out: List[Dict[str, Any]] = []
    for s in sets:
        try:
            all_names = names(s)
        except ShowtimeError as e:
            debug("cannot list %s: %s" % (s, e))
            continue
        tags = _tags(s)
        scored = []
        for n in all_names:
            score = None
            if n == q:
                score = 0
            elif n.startswith(q):
                score = 1
            elif q in n:
                score = 2
            elif any(q.replace("-", " ") in t.lower() or q in t.lower() for t in tags.get(n, [])):
                score = 3
            if score is not None:
                scored.append((score, len(n), n))
        for score, _, n in sorted(scored)[:limit]:
            out.append({"set": s, "name": n, "match": ["exact", "prefix", "name", "tag"][score]})
    out.sort(key=lambda r: ["exact", "prefix", "name", "tag"].index(r["match"]))
    return out[:limit]


def brand_hex(slug: str) -> Optional[str]:
    try:
        data = json.loads(_pkg_file("simple-icons", "data/simple-icons.json", max_bytes=16 << 20).decode("utf-8"))
        for x in data:
            if x.get("slug") == slug:
                return "#" + x["hex"]
    except (OSError, ValueError, ShowtimeError):
        return None
    return None


def raw_svg(set_name: str, name: str, variant: Optional[str] = None) -> str:
    set_name = norm_set(set_name)
    name = name.strip().lower().replace(" ", "-")
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", name):
        raise ShowtimeError("invalid icon name: %r" % name)
    rel = _rel_path(set_name, name, variant)
    try:
        body = _pkg_file(set_name, rel)
    except net.HTTPStatusError as e:
        if e.status == 404:
            import difflib
            try:
                pool = names(set_name, variant)
            except ShowtimeError:
                pool = []
            close = difflib.get_close_matches(name, pool, n=6, cutoff=0.6) or \
                [r["name"] for r in search(name, set_name, limit=6)]
            raise ShowtimeError("no icon %r in %s" % (name, set_name),
                                hint=("similar: " + ", ".join(close)) if close else
                                "search with: showtime assets icons <words> --set %s" % set_name)
        raise
    return body.decode("utf-8")


_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([^)]*\)|hsla?\([^)]*\)|currentColor)$")


def style_svg(svg: str, *, color: Optional[str] = None, size: Optional[int] = None,
              stroke_width: Optional[float] = None, kind: str = "stroke", title: Optional[str] = None) -> str:
    """Apply colour/size/stroke to an icon SVG (root attributes + currentColor)."""
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S).strip()
    m = re.search(r"<svg\b[^>]*>", svg, flags=re.S)
    if not m:
        raise ShowtimeError("not an SVG icon")
    root = m.group(0)
    new = root

    def set_attr(tag: str, attr: str, value: str) -> str:
        pat = re.compile(r'(\s%s=)"[^"]*"' % re.escape(attr))
        if pat.search(tag):
            return pat.sub(lambda mm: '%s"%s"' % (mm.group(1), value), tag, count=1)
        return tag[:-1].rstrip("/").rstrip() + ' %s="%s"' % (attr, value) + ("/>" if tag.endswith("/>") else ">")

    if color and not _COLOR_RE.match(color):
        raise ShowtimeError("invalid colour %r" % color, hint="use #rrggbb, a CSS colour name or rgb(...)")
    if size:
        new = set_attr(new, "width", str(int(size)))
        new = set_attr(new, "height", str(int(size)))
    if stroke_width is not None and kind == "stroke":
        new = set_attr(new, "stroke-width", ("%g" % stroke_width))
    if kind == "brand" and color:
        new = set_attr(new, "fill", color)
    out = svg.replace(root, new, 1)
    if color:
        out = out.replace("currentColor", color)
    if title is not None:
        out = re.sub(r"<title>.*?</title>", "", out, flags=re.S)
    return out + ("\n" if not out.endswith("\n") else "")


def get(set_name: str, name: str, *, variant: Optional[str] = None, color: Optional[str] = None,
        size: Optional[int] = 96, stroke_width: Optional[float] = None, out: Optional[Path] = None,
        png: bool = False) -> Dict[str, Any]:
    """Write a styled icon; returns {svg, png?, set, name, license}."""
    set_name = norm_set(set_name)
    s = SETS[set_name]
    name = name.strip().lower().replace(" ", "-")
    if color and color.lower() == "brand":
        if set_name != "simple-icons":
            raise ShowtimeError("--color brand only works with simple-icons")
        color = brand_hex(name) or "#000000"
    svg = style_svg(raw_svg(set_name, name, variant), color=color, size=size, stroke_width=stroke_width,
                    kind=s["kind"])
    if out:
        dest = Path(out)
        if dest.suffix.lower() == ".png":
            png = True
            dest = dest.with_suffix(".svg")
    else:
        tag = "-".join(x for x in [variant if variant and variant != s["variants"][0] else "",
                                   (color or "").lstrip("#").lower().replace("(", "").replace(")", "").replace(",", "_").replace(" ", ""),
                                   str(size) if size else ""] if x)
        dest = paths()["icons"] / set_name / ("%s%s.svg" % (name, ("-" + tag) if tag else ""))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(svg, encoding="utf-8")
    info = {"source": set_name, "source_label": "%s %s" % (s["pkg"], s["version"]), "id": "%s:%s" % (set_name, name),
            "title": name, "license": s["license"],
            "license_url": "https://spdx.org/licenses/%s.html" % s["license"],
            "landing_url": s["home"].format(name=name)}
    if set_name == "simple-icons":
        info["note"] = "Brand logos are trademarks of their owners; use only to depict that brand."
    licenses.write_sidecar(dest, info)
    res: Dict[str, Any] = {"svg": str(dest), "set": set_name, "name": name, "variant": variant or s["variants"][0],
                           "color": color, "size": size, "license": s["license"]}
    if png:
        png_path = dest.with_suffix(".png")
        rasterize(dest, png_path, size=max(int(size or 96), 16))
        licenses.write_sidecar(png_path, info)
        res["png"] = str(png_path)
    if "note" in info:
        res["note"] = info["note"]
    return res


def node_exe() -> Optional[str]:
    return shutil.which("node")


def rasterize(svg: Path, png: Path, size: int = 512, background: Optional[str] = None) -> Path:
    """SVG -> PNG with headless Chrome (scripts/lib/raster.mjs); transparent by default."""
    node = node_exe()
    if not node:
        raise ShowtimeError("PNG output needs Node.js", hint="install Node 20+ (see `showtime doctor`), or use the SVG")
    script = skill_dir() / "scripts" / "lib" / "raster.mjs"
    args = [node, str(script), str(svg), str(png), "--size", str(int(size))]
    if background:
        args += ["--background", background]
    cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    if cp.returncode != 0 or not Path(png).is_file():
        tail = "\n".join((cp.stderr or cp.stdout or "").strip().splitlines()[-6:])
        raise ShowtimeError("could not rasterize %s:\n%s" % (Path(svg).name, tail),
                            hint="run `showtime doctor` to check the browser")
    return Path(png)


# ------------------------------------------------------------------ offline pre-seed

def seed_all(sets: Optional[List[str]] = None) -> Dict[str, Any]:
    """Unpack the pinned npm tarballs of the icon sets into the icon cache (offline use, `setup --fetch icons`).

    Tarballs are listed in setup/manifest.json ("icon_packs": url, size, sha256) and go through the
    installer's resumable, verified, seedable fetcher; only SVGs and the tag files are kept."""
    import importlib.util
    import tarfile
    from ..common import info
    man = json.loads((paths()["setup"] / "manifest.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("showtime_setup_icons", str(paths()["setup"] / "setup.py"))
    su = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(su)  # type: ignore[union-attr]
    seeds = su.Seeds([d for d in os.environ.get("SHOWTIME_SEED_DIRS", "").split(os.pathsep) if d])
    out: Dict[str, Any] = {}
    for pk in man.get("icon_packs", []):
        name = pk["set"]
        if sets and name not in sets:
            continue
        if SETS[name]["version"] != pk["version"]:
            raise ShowtimeError("icon pack %s: manifest pins %s, icons.py %s" % (name, pk["version"], SETS[name]["version"]))
        dest = cache_dir(name)
        if (dest / ".seeded").is_file():
            out[name] = "present"
            continue
        arc = paths()["downloads"] / pk["url"].rsplit("/", 1)[-1]
        info("fetching icon pack %s %s (%.1f MB)" % (SETS[name]["pkg"], pk["version"], pk["size"] / 1e6))
        how = su.fetch(pk["url"], arc, pk["sha256"], pk["size"], seeds, arc.name, verify=True)
        n = 0
        with tarfile.open(str(arc), "r:gz") as tf:
            for m in tf:
                rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
                if not m.isfile() or ".." in rel.split("/") or not (
                        rel.endswith(".svg") or rel in ("tags.json", "data/simple-icons.json", "package.json")):
                    continue
                t = dest / rel
                t.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    continue
                with src:
                    t.write_bytes(src.read())
                n += 1
        (dest / ".seeded").write_text("%s %s\n" % (pk["url"], pk["sha256"]), encoding="utf-8")
        try:
            arc.unlink()
        except OSError:
            pass
        out[name] = "%s, %d files" % (how, n)
    return out
