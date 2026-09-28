"""Emoji images: Noto (Apache-2.0) and Fluent (MIT) by default -- no attribution needed.

    showtime assets emoji 🚀                          # Noto 2D SVG
    showtime assets emoji rocket --set fluent-3d      # Fluent 3D PNG (256 px)
    showtime assets emoji "red heart" --set noto-3d --size 512
    showtime assets emoji "thumbs up" --set fluent --format png --size 512
    showtime assets emojis party                      # search names/keywords

Sets (default: noto):
    noto        Google Noto 2D colour, SVG (or PNG 32/72/128/512)         Apache-2.0
    noto-3d     Google Noto 3D glossy PNG (32/72/128/512)                  Apache-2.0
    fluent      Microsoft Fluent colour SVG                               MIT
    fluent-flat Microsoft Fluent flat SVG                                 MIT
    fluent-3d   Microsoft Fluent 3D PNG (256 px)                          MIT
    twemoji     Twemoji SVG            CC-BY-4.0 -> needs --allow-attribution (credit written)
    openmoji    OpenMoji SVG           CC-BY-SA-4.0 -> needs --allow-share-alike

The emoji index (names, keywords, skin tones) comes from emojibase-data (MIT),
cached in ~/.showtime/cache. Input may be the emoji itself, a name or keyword
("rocket", "red heart"), or code points ("1f680", "U+1F680").
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ShowtimeError, debug, paths
from . import icons as _icons
from . import licenses, net

INDEX_URL = "https://cdn.jsdelivr.net/npm/emojibase-data@17.0.0/en/compact.json"
NOTO = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main"
FLUENT = "https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets"
TWEMOJI = "https://cdn.jsdelivr.net/npm/@twemoji/svg@15.0.0"
OPENMOJI = "https://cdn.jsdelivr.net/npm/openmoji@17.0.0/color/svg"

SETS: Dict[str, Dict[str, Any]] = {
    "noto": {"license": "Apache-2.0", "formats": ["svg", "png"], "label": "Noto Emoji (Google)",
             "home": "https://github.com/googlefonts/noto-emoji"},
    "noto-3d": {"license": "Apache-2.0", "formats": ["png"], "label": "Noto Emoji 3D (Google)",
                "home": "https://github.com/googlefonts/noto-emoji"},
    "fluent": {"license": "MIT", "formats": ["svg"], "label": "Fluent Emoji (Microsoft)",
               "home": "https://github.com/microsoft/fluentui-emoji"},
    "fluent-flat": {"license": "MIT", "formats": ["svg"], "label": "Fluent Emoji Flat (Microsoft)",
                    "home": "https://github.com/microsoft/fluentui-emoji"},
    "fluent-3d": {"license": "MIT", "formats": ["png"], "label": "Fluent Emoji 3D (Microsoft)",
                  "home": "https://github.com/microsoft/fluentui-emoji"},
    "twemoji": {"license": "CC-BY-4.0", "formats": ["svg"], "label": "Twemoji (Twitter/X, jdecked fork)",
                "home": "https://github.com/jdecked/twemoji"},
    "openmoji": {"license": "CC-BY-SA-4.0", "formats": ["svg"], "label": "OpenMoji",
                 "home": "https://openmoji.org"},
}
NOTO_PNG_SIZES = [32, 72, 128, 512]
SKIN = {"light": "1F3FB", "medium-light": "1F3FC", "medium": "1F3FD", "medium-dark": "1F3FE", "dark": "1F3FF"}
FLUENT_SKIN = {"1F3FB": "Light", "1F3FC": "Medium-Light", "1F3FD": "Medium", "1F3FE": "Medium-Dark", "1F3FF": "Dark"}


def index() -> List[Dict[str, Any]]:
    """Flattened emojibase entries (base + skin variants), cached for 90 days."""
    data = net.get_json(INDEX_URL, ttl=90 * 86400)
    out = []
    for e in data:
        out.append(e)
        for s in e.get("skins") or []:
            s = dict(s)
            s.setdefault("tags", e.get("tags", []))
            s["base"] = e["hexcode"]
            out.append(s)
    return out


def _hex_of(text: str) -> str:
    return "-".join("%04X" % ord(c) for c in text)


def resolve(query: str, skin: Optional[str] = None) -> Dict[str, Any]:
    """Find an emoji by glyph, code points, name or keyword."""
    q = query.strip()
    if not q:
        raise ShowtimeError("empty emoji query")
    idx = index()
    by_hex = {e["hexcode"].upper(): e for e in idx}
    cand: Optional[Dict[str, Any]] = None
    m = re.fullmatch(r"(?:u\+)?([0-9a-fA-F]{4,6})(?:[-_ ](?:u\+)?[0-9a-fA-F]{4,6})*", q, flags=re.I)
    if m and not re.fullmatch(r"[a-zA-Z]+", q):
        hx = "-".join(p.upper().lstrip("U+") for p in re.split(r"[-_ ]", q.upper().replace("U+", "")))
        cand = by_hex.get(hx) or by_hex.get(hx.replace("-FE0F", ""))
        if not cand:
            cand = {"hexcode": hx, "label": q, "unicode": "".join(chr(int(p, 16)) for p in hx.split("-"))}
    elif any(ord(c) > 0x2000 for c in q):
        hx = _hex_of(q)
        cand = by_hex.get(hx) or by_hex.get(hx.replace("-FE0F", "")) or \
            next((e for e in idx if e.get("unicode") == q), None)
        if not cand:
            cand = {"hexcode": hx, "label": q, "unicode": q}
    else:
        def nm(x: str) -> str:
            return re.sub(r"[\s_\-]+", " ", x.lower()).strip()
        name = nm(q)
        labels = {nm(e["label"]): e for e in idx if "base" not in e}
        cand = labels.get(name)
        if not cand:
            tagged = [e for e in idx if "base" not in e and name in [t.lower() for t in e.get("tags", [])]]
            if tagged:
                cand = sorted(tagged, key=lambda e: e.get("order", 1e9))[0]
        if not cand:
            close = difflib.get_close_matches(name, list(labels), n=5, cutoff=0.6)
            raise ShowtimeError("no emoji named %r" % query,
                                hint=("did you mean: " + ", ".join(close)) if close else
                                "search with: showtime assets emojis <word>")
    if skin:
        s = SKIN.get(skin.lower())
        if not s:
            raise ShowtimeError("unknown skin tone %r" % skin, hint="use: " + ", ".join(SKIN))
        base = cand.get("base") or cand["hexcode"]
        tone = by_hex.get("%s-%s" % (base, s))
        if not tone:
            raise ShowtimeError("%s has no skin-tone variants" % cand.get("label"))
        cand = tone
    return cand


def search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    out = []
    for e in index():
        if "base" in e:
            continue
        label = e["label"].lower()
        tags = [t.lower() for t in e.get("tags", [])]
        if q == label:
            score = 0
        elif label.startswith(q):
            score = 1
        elif q in tags:
            score = 2
        elif q in label:
            score = 3
        elif any(q in t for t in tags):
            score = 4
        else:
            continue
        out.append((score, e.get("order", 1e9), e))
    out.sort(key=lambda x: (x[0], x[1]))
    return [{"emoji": e.get("unicode"), "name": e["label"], "hex": e["hexcode"], "tags": e.get("tags", [])[:8]}
            for _, _, e in out[:limit]]


def _noto_name(hexcode: str) -> str:
    parts = [p.lower() for p in hexcode.split("-") if p.upper() != "FE0F"]
    return "emoji_u" + "_".join(parts)


def _fluent_urls(entry: Dict[str, Any], style: str) -> List[str]:
    """Candidate URLs in the Fluent repo (folder = CLDR label in sentence case)."""
    label = entry.get("label", "")
    hexcode = entry["hexcode"].upper()
    tone = None
    for k, v in FLUENT_SKIN.items():
        if hexcode.endswith("-" + k):
            tone = v
            label = label.split(":")[0]
    if ":" in label:  # e.g. "flag: Japan" -- not in Fluent
        return []
    folder = label[:1].upper() + label[1:]
    stem = re.sub(r"[^a-z0-9-]+", "_", label.lower()).strip("_")
    sub = {"fluent": ("Color", "color", "svg"), "fluent-flat": ("Flat", "flat", "svg"),
           "fluent-3d": ("3D", "3d", "png")}[style]
    q = net.quote_path
    if tone:
        return ["%s/%s/%s/%s/%s_%s_%s.%s" % (FLUENT, q(folder), tone, sub[0], stem, sub[1], tone.lower(), sub[2])]
    return ["%s/%s/%s/%s_%s.%s" % (FLUENT, q(folder), sub[0], stem, sub[1], sub[2]),
            "%s/%s/Default/%s/%s_%s_default.%s" % (FLUENT, q(folder), sub[0], stem, sub[1], sub[2])]


def _urls(entry: Dict[str, Any], set_name: str, fmt: str, size: int) -> List[str]:
    hx = entry["hexcode"].upper()
    if set_name == "noto":
        if fmt == "svg":
            return ["%s/2D/svg/%s.svg" % (NOTO, _noto_name(hx))]
        s = min((x for x in NOTO_PNG_SIZES if x >= size), default=512)
        return ["%s/2D/png/%d/%s.png" % (NOTO, s, _noto_name(hx))]
    if set_name == "noto-3d":
        s = min((x for x in NOTO_PNG_SIZES if x >= size), default=512)
        return ["%s/3D/png/%d/%s.png" % (NOTO, s, _noto_name(hx))]
    if set_name.startswith("fluent"):
        return _fluent_urls(entry, set_name)
    if set_name == "twemoji":
        parts = [p.lower() for p in hx.split("-")]
        return ["%s/%s.svg" % (TWEMOJI, "-".join(parts)), "%s/%s.svg" % (TWEMOJI, "-".join(p for p in parts if p != "fe0f"))]
    if set_name == "openmoji":
        return ["%s/%s.svg" % (OPENMOJI, hx), "%s/%s.svg" % (OPENMOJI, hx.replace("-FE0F", ""))]
    raise AssertionError(set_name)


def get(query: str, *, set_name: str = "noto", fmt: Optional[str] = None, size: int = 512,
        skin: Optional[str] = None, out: Optional[Path] = None, allow_attribution: bool = False,
        allow_share_alike: bool = False, project: Optional[Path] = None) -> Dict[str, Any]:
    set_name = set_name.lower()
    if set_name not in SETS:
        raise ShowtimeError("unknown emoji set %r" % set_name, hint="sets: " + ", ".join(SETS))
    meta = SETS[set_name]
    licenses.check(meta["license"], allow_attribution=allow_attribution, allow_share_alike=allow_share_alike,
                   what="the %s emoji set" % set_name)
    entry = resolve(query, skin)
    if out and not fmt:
        fmt = Path(out).suffix.lstrip(".").lower() or None
    fmt = (fmt or meta["formats"][0]).lower()
    native = fmt in meta["formats"]
    if fmt not in ("svg", "png"):
        raise ShowtimeError("format must be svg or png")
    if fmt == "svg" and not native:
        raise ShowtimeError("%s only has %s images" % (set_name, "/".join(meta["formats"])),
                            hint="use --format png, or --set noto / fluent for SVG")
    fetch_fmt = fmt if native else "svg"  # png from an SVG-only set -> rasterize
    stem = "%s-%s" % (entry["hexcode"].lower(), re.sub(r"[^a-z0-9]+", "-", entry.get("label", "").lower()).strip("-")[:40])
    if out:
        dest = Path(out)
        if dest.suffix.lower() not in (".svg", ".png"):
            dest = dest / ("%s.%s" % (stem, fmt))
    else:
        dest = paths()["emoji"] / set_name / ("%s%s.%s" % (stem, ("-%d" % size) if fmt == "png" else "", fmt))
    fetch_dest = dest if native else dest.with_suffix(".svg")
    urls = _urls(entry, set_name, fetch_fmt, size)
    if not urls:
        raise ShowtimeError("%s (%s) is not in the %s set" % (entry.get("unicode", ""), entry.get("label"), set_name),
                            hint="try --set noto")
    last: Optional[Exception] = None
    got = None
    for u in urls:
        try:
            got = net.download(u, fetch_dest, max_bytes=10 << 20, retries=1)
            got["url"] = u
            break
        except net.HTTPStatusError as e:
            last = e
            debug("not found: %s" % u)
            continue
    if not got:
        raise ShowtimeError("%s (%s) is not available in the %s set" % (entry.get("unicode", ""), entry.get("label"), set_name),
                            hint="try another set (--set noto covers the full Unicode list)") from last
    info = {"source": set_name, "source_label": meta["label"], "id": "%s:%s" % (set_name, entry["hexcode"]),
            "title": "%s emoji" % entry.get("label", ""), "author": meta["label"].split("(")[-1].rstrip(")"),
            "license": meta["license"], "license_url": "https://spdx.org/licenses/%s.html" % meta["license"],
            "landing_url": meta["home"], "file_url": got["url"], "sha256": got["sha256"]}
    if not native:
        _icons.rasterize(fetch_dest, dest, size=size)
    if fmt == "png" and native and set_name in ("noto", "noto-3d", "fluent-3d"):
        _resize_png(dest, size)
    licenses.write_sidecar(dest, info)
    res = {"path": str(dest), "emoji": entry.get("unicode"), "name": entry.get("label"), "hex": entry["hexcode"],
           "set": set_name, "format": fmt, "license": meta["license"]}
    if licenses.classify(meta["license"]) != licenses.FREE:
        res["credit"] = licenses.credit_line(info)
        if project:
            res["credits_file"] = str(licenses.append_credit(Path(project), info))
    return res


def _resize_png(p: Path, size: int) -> None:
    """Downscale a fetched PNG to `size` on its longer side (never upscale)."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - pillow is a core dependency
        return
    with Image.open(p) as im:
        if max(im.size) <= size:
            return
        im = im.convert("RGBA")
        r = size / float(max(im.size))
        im = im.resize((max(1, round(im.size[0] * r)), max(1, round(im.size[1] * r))), Image.LANCZOS)
        im.save(p)
