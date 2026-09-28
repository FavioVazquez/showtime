"""Key-free stock media search + fetch with a license gate.

    showtime assets media search "mountain sunrise"                 # CC0 / public domain images
    showtime assets media search "ocean waves" --type video
    showtime assets media search "great wave" --source met,aic,cma --preview sheet.jpg
    showtime assets media fetch openverse:7bc707f3-... --project ./my-video
    showtime assets credits ./my-video                                # compile CREDITS.txt

Sources (no API keys):
    openverse   Openverse (images; CC0 + Public Domain Mark by default)       anonymous: ~20 req/min
    commons     Wikimedia Commons (images + video; CC0 / public-domain statements)
    nasa        NASA Image and Video Library (images + video; generally not copyrighted,
                no endorsement implied, never use NASA logos/insignia)
    cma         Cleveland Museum of Art open access (CC0)
    met         The Met open access (public-domain objects only)
    aic         Art Institute of Chicago (public-domain artworks, CC0 images). Opt-in (--source aic):
                its image server often answers scripts with a bot check, which showtime never bypasses.

License policy: CC0 / public domain by default. `--allow-attribution` also accepts
CC BY (a credit line goes to CREDITS.txt); `--allow-share-alike` accepts CC BY-SA.
Non-commercial / no-derivatives material is never returned.

Search results are remembered in ~/.showtime/cache/media-index.json so `fetch <id>`
works without repeating the search. Downloads are cached in
~/.showtime/assets/media/<source>/ with a .license.json sidecar.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, debug, home, paths, sha256_file, warn, write_json
from . import licenses, net

IMAGE_SOURCES = ["openverse", "commons", "nasa", "cma", "met"]
ALL_SOURCES = IMAGE_SOURCES + ["aic"]   # aic is opt-in: its image server sits behind bot protection
VIDEO_SOURCES = ["commons", "nasa"]
LABELS = {"openverse": "Openverse", "commons": "Wikimedia Commons", "nasa": "NASA Image and Video Library",
          "cma": "Cleveland Museum of Art", "met": "The Metropolitan Museum of Art",
          "aic": "Art Institute of Chicago"}
AIC_HEADERS = {"User-Agent": net.BROWSER_UA, "AIC-User-Agent": "showtime (open-source local video tool)"}


# --------------------------------------------------------------------------- helpers

def _strip_html(s: Any) -> str:
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def _result(**kw: Any) -> Dict[str, Any]:
    r = {"id": None, "source": None, "type": "image", "title": "", "author": "", "author_url": None,
         "license": "", "license_url": None, "landing_url": None, "url": None, "thumb": None,
         "width": None, "height": None, "mime": None, "bytes": None, "note": None}
    r.update(kw)
    r["source_label"] = LABELS.get(r["source"], r["source"])
    r["license_class"] = licenses.classify(r["license"])
    r["attribution_required"] = r["license_class"] in (licenses.ATTRIBUTION, licenses.SHARE_ALIKE)
    r["title"] = (r.get("title") or "").strip()[:200]
    r["author"] = (r.get("author") or "").strip()[:160]
    return r


def _allowed(r: Dict[str, Any], allow_attribution: bool, allow_share_alike: bool) -> bool:
    c = r["license_class"]
    return c == licenses.FREE or (c == licenses.ATTRIBUTION and allow_attribution) or \
        (c == licenses.SHARE_ALIKE and allow_share_alike)


def _orientation_ok(r: Dict[str, Any], orientation: Optional[str]) -> bool:
    if not orientation or not r.get("width") or not r.get("height"):
        return True
    a = float(r["width"]) / float(r["height"])
    return {"landscape": a > 1.15, "portrait": a < 0.87, "square": 0.87 <= a <= 1.15}.get(orientation, True)


# --------------------------------------------------------------------------- providers

def _openverse(q: str, kind: str, limit: int, aa: bool, sa: bool, orientation: Optional[str]) -> List[Dict[str, Any]]:
    if kind != "image":
        return []
    lic = ["cc0", "pdm"] + (["by"] if aa else []) + (["by-sa"] if sa else [])
    params = {"q": q, "license": ",".join(lic), "page_size": str(min(max(limit, 1), 20)), "mature": "false"}
    if orientation:
        params["aspect_ratio"] = {"landscape": "wide", "portrait": "tall", "square": "square"}.get(orientation, "wide")
    data = net.get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(params), ttl=86400)
    out = []
    for it in data.get("results", []):
        lic_code = str(it.get("license") or "")
        label = {"cc0": "CC0 1.0", "pdm": "Public Domain Mark 1.0"}.get(lic_code, "CC %s %s" % (lic_code.upper(), it.get("license_version") or ""))
        out.append(_result(id="openverse:%s" % it["id"], source="openverse", title=it.get("title"),
                           author=it.get("creator"), author_url=it.get("creator_url"),
                           license=label.strip(), license_url=it.get("license_url"),
                           landing_url=it.get("foreign_landing_url"), url=it.get("url"), thumb=it.get("thumbnail"),
                           width=it.get("width"), height=it.get("height"), bytes=it.get("filesize"),
                           provider=it.get("provider")))
    return out


def _commons_license_ok(meta: Dict[str, Any]) -> str:
    return _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))


def _commons(q: str, kind: str, limit: int, aa: bool, sa: bool, orientation: Optional[str]) -> List[Dict[str, Any]]:
    ft = "bitmap" if kind == "image" else "video"
    search = "%s filetype:%s" % (q, ft)
    if not (aa or sa):
        search += " haswbstatement:P275=Q6938433|P6216=Q19652"
    prop = "imageinfo" if kind == "image" else "videoinfo"
    pre = "ii" if kind == "image" else "vi"
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
              "gsrlimit": str(min(max(limit * 2, 4), 40)), "gsrsearch": search, "prop": prop,
              pre + "prop": "url|size|mime|extmetadata" + ("|derivatives" if kind == "video" else ""),
              pre + "extmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ObjectName|ImageDescription|AttributionRequired"}
    if kind == "image":
        params["iiurlwidth"] = "1920"
    data = net.get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params), ttl=86400)
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        info = (p.get(prop) or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _commons_license_ok(meta)
        if re.search(r"\b(pd|public domain|cc0)\b", lic, flags=re.I):
            lic = "CC0 1.0" if "cc0" in lic.lower() else "Public domain"
        url = info.get("thumburl") if kind == "image" and info.get("width", 0) > 1920 else info.get("url")
        if kind == "video":
            ders = [d for d in info.get("derivatives") or [] if d.get("height") and int(d["height"]) <= 1080]
            ders.sort(key=lambda d: int(d.get("height") or 0))
            if ders and int(info.get("size") or 0) > 80e6:
                url = ders[-1]["src"]
        title = _strip_html((meta.get("ObjectName") or {}).get("value")) or p.get("title", "").replace("File:", "")
        out.append(_result(id="commons:%s" % p["pageid"], source="commons", type=kind, title=title,
                           author=_strip_html((meta.get("Artist") or {}).get("value")),
                           license=lic, license_url=(meta.get("LicenseUrl") or {}).get("value"),
                           landing_url=info.get("descriptionurl"), url=url,
                           thumb=info.get("thumburl") if kind == "image" else None,
                           width=info.get("thumbwidth") if url == info.get("thumburl") else info.get("width"),
                           height=info.get("thumbheight") if url == info.get("thumburl") else info.get("height"),
                           mime=info.get("mime"), bytes=info.get("size") if url == info.get("url") else None))
    return out


# NASA's "public domain" does not cover third-party work shown or processed in an item: citizen-
# processed JunoCam images, ESA/Hubble frames, credited photographers. Their licence is in the author or
# description text, which the search API returns and showtime reads.
_CC_RE = re.compile(r"\bCC[\s-]*BY(?:[\s-]*(?:NC|SA|ND)){0,3}(?:[\s-]*\d\.\d)?", re.I)
_NOTICE_RE = re.compile(r"citizen scien|enhanced image by|image processing by|processed by|processing:|"
                        r"ESA/Hubble|\u00a9|\(c\)\s*\d{4}|copyright|all rights reserved|courtesy of (?!NASA)", re.I)


def nasa_license(*texts: Any) -> Tuple[str, Optional[str]]:
    """(licence string, notice excerpt or None) for a NASA item from its author/description text."""
    text = " ".join(str(t or "") for t in texts)
    m = _CC_RE.search(text)
    if m:
        up = m.group(0).upper()
        comps = re.findall(r"BY|NC|SA|ND", up)
        ver = re.search(r"\d\.\d", up)
        lic = "CC " + "-".join(comps) + (" " + ver.group(0) if ver else "")
        start = max(0, m.start() - 80)
        return "%s (third-party processing; see the description)" % lic, text[start:m.end() + 40].strip()
    n = _NOTICE_RE.search(text)
    if n:
        start = max(0, n.start() - 60)
        return "Unclear: third-party credit in the description (check it before use)", text[start:n.end() + 80].strip()
    return "Public domain (NASA media)", None


def _nasa_meta(nid: str, kind: str) -> Dict[str, Any]:
    """Size, duration and file size of the original rendition (metadata.json; cached a day)."""
    try:
        d = net.get_json("https://images-assets.nasa.gov/%s/%s/metadata.json" % (kind, _q(nid)), ttl=86400)
    except Exception:  # noqa: BLE001 - details are optional
        return {}
    out: Dict[str, Any] = {}
    for k, v in d.items():
        kl = k.lower()
        if kl.endswith(":imagewidth") and "source" not in kl and isinstance(v, (int, float)):
            out.setdefault("width", int(v))
        elif kl.endswith(":imageheight") and "source" not in kl and isinstance(v, (int, float)):
            out.setdefault("height", int(v))
        elif kl in ("quicktime:duration", "quicktime:mediaduration") and isinstance(v, str):
            parts = [float(x) for x in re.findall(r"[\d.]+", v)]
            if ":" in v and parts:
                sec = 0.0
                for x in parts:
                    sec = sec * 60 + x
                out.setdefault("duration", round(sec, 2))
            elif parts:
                out.setdefault("duration", parts[0])
        elif kl == "quicktime:mediadatasize" and isinstance(v, (int, float)):
            out["bytes"] = int(v)
        elif kl == "file:filesize" and isinstance(v, str) and "bytes" not in out:
            m = re.match(r"([\d.]+)\s*(k|m|g)?i?b", v.strip(), re.I)
            if m:
                out["bytes"] = int(float(m.group(1)) * {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}.get((m.group(2) or "").lower(), 1))
    return out


def _nasa(q: str, kind: str, limit: int, aa: bool, sa: bool, orientation: Optional[str]) -> List[Dict[str, Any]]:
    params = {"q": q, "media_type": kind, "page_size": str(min(max(limit, 1), 50))}
    data = net.get_json("https://images-api.nasa.gov/search?" + urllib.parse.urlencode(params), ttl=86400)
    out = []
    for it in (data.get("collection") or {}).get("items", [])[:limit]:
        d = (it.get("data") or [{}])[0]
        nid = d.get("nasa_id")
        if not nid:
            continue
        thumb = next((lk.get("href") for lk in it.get("links") or [] if lk.get("rel") == "preview"), None)
        author = d.get("photographer") or d.get("secondary_creator") or ("NASA/%s" % d["center"] if d.get("center") else "NASA")
        desc = _strip_html(d.get("description"))
        lic, notice = nasa_license(d.get("photographer"), d.get("secondary_creator"), desc)
        r = _result(id="nasa:%s" % nid, source="nasa", type=kind, title=d.get("title"), author=author,
                    license=lic, license_url="https://www.nasa.gov/nasa-brand-center/images-and-media/",
                    landing_url="https://images.nasa.gov/details/%s" % _q(nid), url=None, thumb=thumb,
                    note="NASA media: no endorsement implied; do not use NASA logos or insignia. "
                         "Check the description for third-party copyright notices.",
                    description=desc[:300])
        if notice:
            r["license_notice"] = notice[:240]
        out.append(r)
    return out


def _nasa_asset_url(nid: str, kind: str, quality: str) -> Tuple[str, List[str]]:
    data = net.get_json("https://images-api.nasa.gov/asset/%s" % _q(nid), ttl=86400)
    hrefs = [i.get("href", "") for i in (data.get("collection") or {}).get("items", [])]
    hrefs = [h.replace("http://", "https://") for h in hrefs]
    if kind == "video":
        order = {"small": ["~small.mp4", "~mobile.mp4", "~medium.mp4"],
                 "medium": ["~medium.mp4", "~large.mp4", "~small.mp4", "~orig.mp4"],
                 "large": ["~large.mp4", "~orig.mp4", "~medium.mp4"],
                 "orig": ["~orig.mp4", "~large.mp4", "~medium.mp4"]}[quality]
    else:
        order = {"small": ["~small.jpg", "~medium.jpg", "~thumb.jpg"],
                 "medium": ["~medium.jpg", "~large.jpg", "~orig.jpg"],
                 "large": ["~large.jpg", "~orig.jpg", "~medium.jpg"],
                 "orig": ["~orig.jpg", "~orig.png", "~orig.tif", "~large.jpg"]}[quality]
    for suf in order:
        for h in hrefs:
            if h.lower().endswith(suf):
                return h, hrefs
    media = [h for h in hrefs if re.search(r"\.(mp4|mov)$" if kind == "video" else r"\.(jpe?g|png)$", h, re.I)]
    if not media:
        raise ShowtimeError("NASA item %s has no downloadable %s" % (nid, kind))
    return media[0], hrefs


def _cma(q: str, kind: str, limit: int, aa: bool, sa: bool, orientation: Optional[str]) -> List[Dict[str, Any]]:
    if kind != "image":
        return []
    params = {"q": q, "cc0": "1", "has_image": "1", "limit": str(min(max(limit, 1), 30))}
    data = net.get_json("https://openaccess-api.clevelandart.org/api/artworks/?" + urllib.parse.urlencode(params), ttl=86400)
    out = []
    for a in data.get("data", []):
        imgs = a.get("images") or {}
        best = imgs.get("print") or imgs.get("web") or {}
        web = imgs.get("web") or {}
        creators = "; ".join(c.get("description", "") for c in a.get("creators") or [] if c.get("description"))
        out.append(_result(id="cma:%s" % a["id"], source="cma", title=a.get("title"), author=creators,
                           license="CC0 1.0" if str(a.get("share_license_status", "")).upper() == "CC0" else a.get("share_license_status"),
                           license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                           landing_url=a.get("url"), url=best.get("url"), thumb=web.get("url"),
                           width=int(best["width"]) if best.get("width") else None,
                           height=int(best["height"]) if best.get("height") else None,
                           bytes=int(best["filesize"]) if best.get("filesize") else None))
    return out


def _met_object(oid: int) -> Optional[Dict[str, Any]]:
    try:
        d = net.get_json("https://collectionapi.metmuseum.org/public/collection/v1/objects/%d" % oid, ttl=7 * 86400)
    except ShowtimeError as e:
        debug("met object %s: %s" % (oid, e))
        return None
    if not d.get("isPublicDomain") or not d.get("primaryImage"):
        return None
    return _result(id="met:%d" % oid, source="met", title=d.get("title"), author=d.get("artistDisplayName") or d.get("culture"),
                   license="CC0 1.0", license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                   landing_url=d.get("objectURL"), url=d.get("primaryImage"), thumb=d.get("primaryImageSmall"))


def _met(q: str, kind: str, limit: int, aa: bool, sa: bool, orientation: Optional[str]) -> List[Dict[str, Any]]:
    if kind != "image":
        return []
    params = {"hasImages": "true", "q": q}
    data = net.get_json("https://collectionapi.metmuseum.org/public/collection/v1/search?" + urllib.parse.urlencode(params), ttl=86400)
    ids = (data.get("objectIDs") or [])[:max(6, min(limit * 2, 16))]
    with ThreadPoolExecutor(max_workers=4) as ex:
        objs = list(ex.map(_met_object, ids))
    return [o for o in objs if o][:limit]


def _aic(q: str, kind: str, limit: int, aa: bool, sa: bool, orientation: Optional[str]) -> List[Dict[str, Any]]:
    if kind != "image":
        return []
    params = {"q": q, "query[term][is_public_domain]": "true", "limit": str(min(max(limit, 1), 30)),
              "fields": "id,title,image_id,artist_display,is_public_domain,thumbnail"}
    data = net.get_json("https://api.artic.edu/api/v1/artworks/search?" + urllib.parse.urlencode(params),
                        headers=AIC_HEADERS, ttl=86400)
    out = []
    for a in data.get("data", []):
        if not a.get("image_id") or not a.get("is_public_domain"):
            continue
        th = a.get("thumbnail") or {}
        w, h = th.get("width"), th.get("height")
        # never ask for more than the original width: the IIIF server rejects upscaling
        tw = int(min(1686, w)) if w else 843
        iiif = "https://www.artic.edu/iiif/2/%s/full/%d,/0/default.jpg" % (a["image_id"], tw)
        out.append(_result(id="aic:%s" % a["id"], source="aic", title=a.get("title"),
                           author=(a.get("artist_display") or "").split("\n")[0],
                           license="CC0 1.0", license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                           landing_url="https://www.artic.edu/artworks/%s" % a["id"], url=iiif,
                           thumb="https://www.artic.edu/iiif/2/%s/full/400,/0/default.jpg" % a["image_id"],
                           width=tw if w else None, height=round(tw * h / w) if w and h else None,
                           note="The Art Institute's image server may answer with a bot check; "
                                "showtime never bypasses it (pick another result if the download is refused)."))
    return out


PROVIDERS: Dict[str, Callable[..., List[Dict[str, Any]]]] = {
    "openverse": _openverse, "commons": _commons, "nasa": _nasa, "cma": _cma, "met": _met, "aic": _aic}


# --------------------------------------------------------------------------- index

def _index_path() -> Path:
    return home() / "cache" / "media-index.json"


def _load_index() -> Dict[str, Any]:
    p = _index_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def _save_index(results: Sequence[Dict[str, Any]]) -> None:
    idx = _load_index()
    now = time.time()
    for r in results:
        r2 = dict(r)
        r2["_seen"] = now
        idx[r["id"]] = r2
    if len(idx) > 3000:
        for k, _ in sorted(idx.items(), key=lambda kv: kv[1].get("_seen", 0))[:len(idx) - 3000]:
            idx.pop(k, None)
    try:
        write_json(_index_path(), idx, indent=0)
    except OSError as e:
        debug("could not save media index: %s" % e)


# --------------------------------------------------------------------------- public API

def search(query: str, *, kind: str = "image", sources: Optional[Sequence[str]] = None, limit: int = 12,
           allow_attribution: bool = False, allow_share_alike: bool = False,
           orientation: Optional[str] = None, details: Optional[bool] = None, min_size: Optional[int] = None,
           max_duration: Optional[float] = None, max_mb: Optional[float] = None) -> Dict[str, Any]:
    """Search several key-free sources in parallel. Returns {results, errors, sources}."""
    if kind not in ("image", "video"):
        raise ShowtimeError("--type must be image or video")
    if not query.strip():
        raise ShowtimeError("empty search query")
    default = IMAGE_SOURCES if kind == "image" else VIDEO_SOURCES
    srcs = [s.strip().lower() for s in (sources or default) if s.strip()]
    bad = [s for s in srcs if s not in PROVIDERS]
    if bad:
        raise ShowtimeError("unknown source(s): %s" % ", ".join(bad), hint="sources: " + ", ".join(PROVIDERS))
    if kind == "video":
        srcs = [s for s in srcs if s in VIDEO_SOURCES] or VIDEO_SOURCES
    per = max(3, -(-limit // max(1, len(srcs))) + 2)
    errors: Dict[str, str] = {}

    def run(s: str) -> List[Dict[str, Any]]:
        try:
            return PROVIDERS[s](query, kind, per, allow_attribution, allow_share_alike, orientation)
        except ShowtimeError as e:
            errors[s] = str(e).split("\n")[0]
            return []
        except Exception as e:  # noqa: BLE001 - one broken source must not break the search
            errors[s] = "%s: %s" % (type(e).__name__, e)
            return []

    with ThreadPoolExecutor(max_workers=min(4, len(srcs))) as ex:
        lists = list(ex.map(run, srcs))
    hidden = sum(1 for lst in lists for r in lst if r.get("license_notice") and not _allowed(r, allow_attribution, allow_share_alike))
    lists = [[r for r in lst if r.get("id") and _allowed(r, allow_attribution, allow_share_alike)
              and _orientation_ok(r, orientation)] for lst in lists]
    # NASA results carry no size or length: read each one's metadata when asked or when filtering
    want_details = details if details is not None else bool(min_size or max_duration or max_mb or kind == "video")
    if want_details:
        todo = [r for lst in lists for r in lst[: max(limit, 12)] if r["source"] == "nasa"]
        with ThreadPoolExecutor(max_workers=6) as ex:
            metas = list(ex.map(lambda r: _nasa_meta(r["id"].split(":", 1)[1], r.get("type", "image")), todo))
        for r, m in zip(todo, metas):
            for k in ("width", "height", "duration", "bytes"):
                if m.get(k) is not None and r.get(k) in (None, 0):
                    r[k] = m[k]

    def fits(r: Dict[str, Any]) -> bool:
        if min_size and r.get("width") and min(r["width"], r.get("height") or r["width"]) < min_size:
            return False
        if max_duration and r.get("duration") and float(r["duration"]) > max_duration:
            return False
        if max_mb and r.get("bytes") and r["bytes"] > max_mb * 1e6:
            return False
        return True
    lists = [[r for r in lst if fits(r)] for lst in lists]
    merged: List[Dict[str, Any]] = []
    i = 0
    while len(merged) < limit and any(i < len(lst) for lst in lists):
        for lst in lists:
            if i < len(lst) and len(merged) < limit:
                merged.append(lst[i])
        i += 1
    _save_index(merged)
    for n, r in enumerate(merged, 1):
        r["n"] = n
    return {"query": query, "type": kind, "results": merged, "errors": errors, "sources": srcs,
            "hidden_third_party": hidden}


def lookup(asset_id: str) -> Dict[str, Any]:
    """Result metadata for an id (from the search index, else asked from the source)."""
    idx = _load_index()
    if asset_id in idx:
        return idx[asset_id]
    src, _, key = asset_id.partition(":")
    if not key or src not in PROVIDERS:
        raise ShowtimeError("not a media id: %r" % asset_id, hint="ids look like openverse:<uuid>, commons:<pageid>, "
                                                                  "nasa:<nasa_id>, cma:<id>, met:<id>, aic:<id>")
    r: Optional[Dict[str, Any]] = None
    if src == "openverse":
        it = net.get_json("https://api.openverse.org/v1/images/%s/" % _q(key), ttl=86400)
        lic_code = str(it.get("license") or "")
        label = {"cc0": "CC0 1.0", "pdm": "Public Domain Mark 1.0"}.get(lic_code, "CC %s %s" % (lic_code.upper(), it.get("license_version") or ""))
        r = _result(id=asset_id, source=src, title=it.get("title"), author=it.get("creator"),
                    author_url=it.get("creator_url"), license=label.strip(), license_url=it.get("license_url"),
                    landing_url=it.get("foreign_landing_url"), url=it.get("url"), thumb=it.get("thumbnail"),
                    width=it.get("width"), height=it.get("height"))
    elif src == "met":
        r = _met_object(int(key))
    elif src == "cma":
        a = net.get_json("https://openaccess-api.clevelandart.org/api/artworks/%s" % _q(key), ttl=86400).get("data", {})
        imgs = a.get("images") or {}
        best = imgs.get("print") or imgs.get("web") or {}
        r = _result(id=asset_id, source=src, title=a.get("title"),
                    author="; ".join(c.get("description", "") for c in a.get("creators") or []),
                    license="CC0 1.0" if str(a.get("share_license_status", "")).upper() == "CC0" else a.get("share_license_status"),
                    landing_url=a.get("url"), url=best.get("url"))
    elif src == "aic":
        a = net.get_json("https://api.artic.edu/api/v1/artworks/%s?fields=id,title,image_id,artist_display,is_public_domain" % _q(key),
                         headers=AIC_HEADERS, ttl=86400).get("data", {})
        if a.get("image_id"):
            r = _result(id=asset_id, source=src, title=a.get("title"), author=(a.get("artist_display") or "").split("\n")[0],
                        license="CC0 1.0" if a.get("is_public_domain") else "unknown",
                        landing_url="https://www.artic.edu/artworks/%s" % key,
                        url="https://www.artic.edu/iiif/2/%s/full/1686,/0/default.jpg" % a["image_id"])
    elif src == "nasa":
        hits = _nasa(key, "image", 5, False, False, None) + _nasa(key, "video", 5, False, False, None)
        r = next((h for h in hits if h["id"] == asset_id), None)
    elif src == "commons":
        for kind in ("image", "video"):
            prop = "imageinfo" if kind == "image" else "videoinfo"
            pre = "ii" if kind == "image" else "vi"
            params = {"action": "query", "format": "json", "pageids": key, "prop": prop,
                      pre + "prop": "url|size|mime|extmetadata",
                      pre + "extmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ObjectName"}
            data = net.get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params), ttl=86400)
            p = ((data.get("query") or {}).get("pages") or {}).get(key) or {}
            info = (p.get(prop) or [{}])[0]
            if not info.get("url"):
                continue
            meta = info.get("extmetadata") or {}
            lic = _commons_license_ok(meta)
            if re.search(r"\b(pd|public domain|cc0)\b", lic, flags=re.I):
                lic = "CC0 1.0" if "cc0" in lic.lower() else "Public domain"
            r = _result(id=asset_id, source=src, type="video" if str(info.get("mime", "")).startswith("video") else "image",
                        title=_strip_html((meta.get("ObjectName") or {}).get("value")) or p.get("title", ""),
                        author=_strip_html((meta.get("Artist") or {}).get("value")), license=lic,
                        license_url=(meta.get("LicenseUrl") or {}).get("value"), landing_url=info.get("descriptionurl"),
                        url=info.get("url"), width=info.get("width"), height=info.get("height"), mime=info.get("mime"))
            break
    if not r:
        raise ShowtimeError("could not find %s" % asset_id, hint="search again with `showtime assets media search`")
    _save_index([r])
    return r


def _safe_name(asset_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", asset_id.split(":", 1)[1])[:80]


# Commons serves thumbnails at standard widths (others, e.g. 2560, are refused with HTTP 400) from a tier that
# is not rate limited like the originals; its error pages ask scripts to use them
COMMONS_STEPS = (250, 330, 500, 960, 1280, 1920, 3840)
COMMONS_DEFAULT_MAX = 3840


def commons_step(max_size: int) -> int:
    """The largest standard Commons thumbnail width that is not above `max_size` (at least the smallest)."""
    fit = [w for w in COMMONS_STEPS if w <= int(max_size)]
    return fit[-1] if fit else COMMONS_STEPS[0]


def _commons_rendition(pageid: str, max_size: Optional[int]) -> Dict[str, Any]:
    """{url, width, height, original_url, original_width, original_height, step} for a Commons image: the
    original when it is small enough (or max_size is 0/None), else the standard thumbnail step."""
    params = {"action": "query", "format": "json", "pageids": pageid, "prop": "imageinfo", "iiprop": "url|size"}
    step = commons_step(max_size) if max_size else None
    if step:
        params["iiurlwidth"] = str(step)
    data = net.get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params), ttl=86400)
    p = ((data.get("query") or {}).get("pages") or {}).get(str(pageid)) or {}
    info = (p.get("imageinfo") or [{}])[0]
    ow, oh = info.get("width"), info.get("height")
    out = {"original_url": info.get("url"), "original_width": ow, "original_height": oh, "step": step}
    if step and ow and int(ow) > step and info.get("thumburl"):
        out.update(url=info["thumburl"], width=info.get("thumbwidth"), height=info.get("thumbheight"))
    else:
        out.update(url=info.get("url"), width=ow, height=oh, step=None)
    return out


def fetch_url(url: str, *, license: Optional[str], out: Optional[Path] = None, project: Optional[Path] = None,
              source_page: Optional[str] = None, title: Optional[str] = None, author: Optional[str] = None,
              allow_attribution: bool = False, allow_share_alike: bool = False, max_mb: int = 300) -> Dict[str, Any]:
    """Download any http(s) file with a license sidecar the user vouches for (a public-domain government
    PDF or photo that no search source covers), so credits and qa treat it like a searched item."""
    if not license:
        raise ShowtimeError("a plain URL carries no license information",
                            why="showtime only keeps files whose license is recorded next to them",
                            hint="read the license on the source page, then pass it: --license public-domain "
                                 "--source-page <page that states it>")
    licenses.check(license, allow_attribution=allow_attribution, allow_share_alike=allow_share_alike, what=url)
    import hashlib
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name or key
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem)[:60] + "-" + key[:8]
    cache_dir = paths()["media"] / "url"
    existing = sorted(p for p in cache_dir.glob(stem + ".*") if not p.name.endswith((".json", ".part", ".download")))
    if existing:
        cached = existing[0]
        info: Dict[str, Any] = {"sha256": None}
    else:
        tmp = cache_dir / (stem + ".download")
        try:
            info = net.download(url, tmp, max_bytes=max_mb << 20, timeout=120, progress=True)
        except net.HTTPStatusError as e:
            if e.status != 403:
                raise
            # some public hosts refuse unknown agents: retry once with a browser-like one (it still names showtime)
            info = net.download(url, tmp, headers={"User-Agent": net.BROWSER_UA}, max_bytes=max_mb << 20,
                                timeout=120, progress=True)
        ext = info.get("ext") or Path(name).suffix.lstrip(".").lower() or "bin"
        cached = cache_dir / ("%s.%s" % (stem, "jpg" if ext == "jpeg" else ext))
        tmp.replace(cached)
    side = {"source": "url", "source_label": urllib.parse.urlsplit(url).hostname, "id": "url:" + key,
            "title": title or Path(name).stem, "author": author, "license": license,
            "landing_url": source_page or url, "file_url": url,
            "note": "license given by the user (--license)%s" % (" as stated on " + source_page if source_page else "")}
    side["sha256"] = info.get("sha256") or sha256_file(cached)
    licenses.write_sidecar(cached, side)
    return _deliver(cached, side, out, project, notes=[] if source_page else [
        "no --source-page: keep the page that states the license (--source-page <url>) for the credits"])


def _deliver(cached: Path, side: Dict[str, Any], out: Optional[Path], project: Optional[Path],
             notes: Optional[List[str]] = None) -> Dict[str, Any]:
    dest = cached
    if project and not out:
        out = Path(project) / "assets" / "media"
    if out:
        o = Path(out)
        dest = o / cached.name if (o.is_dir() or not o.suffix) else o
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(cached), str(dest))
        licenses.write_sidecar(dest, side)
    res = {"id": side.get("id"), "path": str(dest), "cached": str(cached), "bytes": Path(dest).stat().st_size,
           "type": side.get("type"), "title": side.get("title"), "license": side.get("license"),
           "attribution_required": licenses.classify(side.get("license")) != licenses.FREE,
           "credit": licenses.credit_line(side), "notes": list(notes or [])}
    if side.get("rendition"):
        res["rendition"] = side["rendition"]
    if res["attribution_required"]:
        target = Path(project) if project else Path(dest).parent
        res["credits_file"] = str(licenses.append_credit(target, side))
    return res


def fetch(asset_id: str, *, out: Optional[Path] = None, project: Optional[Path] = None,
          allow_attribution: bool = False, allow_share_alike: bool = False, quality: str = "large",
          max_mb: int = 300, max_size: Optional[int] = None) -> Dict[str, Any]:
    """Download one search result (license-gated) and write its sidecar (+ credits when needed).

    max_size: Commons images, the longest width to download (a standard thumbnail step; default 3840,
    0 or quality="orig" = the original)."""
    r = lookup(asset_id)
    licenses.check(r.get("license"), allow_attribution=allow_attribution, allow_share_alike=allow_share_alike,
                   what="%s (%s)" % (asset_id, r.get("title") or "untitled"))
    src = r["source"]
    url = r.get("url")
    extra: Dict[str, Any] = {}
    if src == "nasa":
        url, hrefs = _nasa_asset_url(asset_id.split(":", 1)[1], r.get("type", "image"), quality)
        extra["captions"] = [h for h in hrefs if h.lower().endswith((".srt", ".vtt"))][:2]
    if not url:
        raise ShowtimeError("%s has no downloadable file" % asset_id)
    rend: Optional[Dict[str, Any]] = None
    notes: List[str] = []
    if src == "commons" and r.get("type", "image") == "image":
        # one rule for every Commons image (search results used to carry a 1920 px thumbnail, a direct id the
        # original): the standard thumbnail step under max_size, the original only when asked for
        ms = 0 if quality == "orig" else (COMMONS_DEFAULT_MAX if max_size is None else int(max_size))
        rend = _commons_rendition(asset_id.split(":", 1)[1], ms or None)
        if rend.get("url"):
            url = rend["url"]
        if rend.get("step"):
            notes.append("using Commons' %d px rendition (%sx%s; the original is %sx%s): --max-size 0 or --quality "
                         "orig for the original" % (rend["step"], rend.get("width"), rend.get("height"),
                                                   rend.get("original_width"), rend.get("original_height")))
    headers = AIC_HEADERS if src == "aic" else None
    cache_dir = paths()["media"] / src
    # the cache is keyed on id + rendition, so --quality orig never returns the cached large file
    stem = _safe_name(asset_id) + ("" if src != "nasa" or quality == "large" else "~" + quality)
    if rend is not None:
        stem = _safe_name(asset_id) + ("~w%d" % rend["step"] if rend.get("step") else "~orig")
    existing = sorted(p for p in cache_dir.glob(stem + ".*") if not p.name.endswith((".json", ".part")))
    if existing:
        cached = existing[0]
        info = {"path": str(cached), "bytes": cached.stat().st_size, "cached": True}
    else:
        tmp = cache_dir / (stem + ".download")
        info = net.download(url, tmp, headers=headers, max_bytes=max_mb << 20, timeout=120, progress=True)
        ext = info.get("ext") or Path(urllib.parse.urlsplit(url).path).suffix.lstrip(".").lower() or "bin"
        if ext in ("jpeg",):
            ext = "jpg"
        cached = cache_dir / ("%s.%s" % (stem, ext))
        tmp.replace(cached)
        info["path"] = str(cached)
    side = {k: r.get(k) for k in ("source", "source_label", "id", "title", "author", "author_url", "license",
                                  "license_url", "landing_url", "note", "type", "license_notice")}
    if r.get("description"):
        side["description_excerpt"] = str(r["description"])[:300]
    if src == "nasa":
        side["quality"] = quality
    side["file_url"] = url
    if rend is not None:
        side["rendition"] = {"width": rend.get("width"), "height": rend.get("height"),
                             "step": rend.get("step") or "original"}
        side["original_url"] = rend.get("original_url")
    side.update(extra)
    prev = licenses.read_sidecar(cached) or {}
    side["sha256"] = info.get("sha256") or prev.get("sha256") or sha256_file(cached)
    if not prev:
        licenses.write_sidecar(cached, side)
    if src == "commons" and side.get("author"):
        notes.append("the author comes from Commons' Author field as written there: check it against the "
                     "primary source (for a figure from a paper it can name an editor or a journal)")
    res = _deliver(cached, side, out, project, notes=notes)
    res["id"] = asset_id
    res["type"] = r.get("type")
    if r.get("note"):
        res["note"] = r["note"]
    return res


def preview_sheet(results: Sequence[Dict[str, Any]], out: Path, cols: int = 4, cell: int = 320) -> Optional[Path]:
    """Download thumbnails and build a numbered contact sheet (JPEG) for choosing results."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover
        warn("pillow is missing; cannot build a preview sheet")
        return None
    import io

    def thumb(r: Dict[str, Any]) -> Optional[Any]:
        u = r.get("thumb") or (r.get("url") if r.get("type") == "image" else None)
        if not u:
            return None
        try:
            body, _ = net.get_bytes(u, headers=AIC_HEADERS if r["source"] == "aic" else None, max_bytes=15 << 20,
                                    timeout=20, retries=1)
            im = Image.open(io.BytesIO(body))
            im.thumbnail((cell, cell))
            return im.convert("RGB")
        except Exception as e:  # noqa: BLE001
            debug("thumb failed for %s: %s" % (r["id"], e))
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        thumbs = list(ex.map(thumb, results))
    if not any(thumbs):
        return None
    rows = -(-len(results) // cols)
    label_h = 34
    sheet = Image.new("RGB", (cols * (cell + 8) + 8, rows * (cell + label_h + 8) + 8), (24, 24, 27))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=15)
    except TypeError:  # old pillow
        font = ImageFont.load_default()
    for i, (r, im) in enumerate(zip(results, thumbs)):
        x = 8 + (i % cols) * (cell + 8)
        y = 8 + (i // cols) * (cell + label_h + 8)
        draw.rectangle([x, y, x + cell, y + cell], fill=(40, 40, 46))
        if im is not None:
            sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        else:
            draw.text((x + 10, y + cell // 2), "(%s: no preview)" % r.get("type"), fill=(160, 160, 170), font=font)
        text = "%d  %s  %s" % (r.get("n", i + 1), r["source"], (r.get("title") or "")[:30])
        draw.text((x + 4, y + cell + 8), text, fill=(235, 235, 240), font=font)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)
    return out
