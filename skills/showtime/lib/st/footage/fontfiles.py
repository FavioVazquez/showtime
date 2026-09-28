"""Font files for burned-in captions (libass) and PNG labels (Pillow).

libass only uses fonts it is given as TTF/OTF files (through `fontsdir=`);
it silently ignores WOFF/WOFF2 and substitutes a system font, which differs
per machine. showtime therefore always hands libass explicit TTF files:

1. ~/.showtime/assets/fonts/<id>/ (fonts fetched by `showtime assets font ...`,
   internal names normalised there) when it holds the exact weight asked for
   (a bold caption fetches the static bold cut once when online), then
   $SHOWTIME_CAPTION_FONTS (a folder of .ttf/.otf, matched on internal family names);
2. otherwise the OFL fonts installed by setup as npm Fontsource packages are
   converted once from WOFF (zlib) or WOFF2 (brotli + glyf reconstruction,
   implemented here from the W3C WOFF2 spec) to TTF in ~/.showtime/cache/fonts.

Everything is pure Python (zlib from the stdlib, brotli from the venv).
"""
from __future__ import annotations

import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..common import ShowtimeError, debug, ensure_dir, home, node_modules, part_path

# family key -> (npm package, file stem prefix, weight label)
FONTSOURCE: Dict[str, Tuple[str, str]] = {
    "anton": ("@fontsource/anton", "anton-{subset}-400-normal"),
    "bebas-neue": ("@fontsource/bebas-neue", "bebas-neue-{subset}-400-normal"),
    "instrument-serif": ("@fontsource/instrument-serif", "instrument-serif-{subset}-400-normal"),
    "ibm-plex-mono": ("@fontsource/ibm-plex-mono", "ibm-plex-mono-{subset}-500-normal"),
    "inter": ("@fontsource-variable/inter", "inter-{subset}-wght-normal"),
    "geist": ("@fontsource-variable/geist", "geist-{subset}-wght-normal"),
    "space-grotesk": ("@fontsource-variable/space-grotesk", "space-grotesk-{subset}-wght-normal"),
    "bricolage-grotesque": ("@fontsource-variable/bricolage-grotesque", "bricolage-grotesque-{subset}-wght-normal"),
    "fraunces": ("@fontsource-variable/fraunces", "fraunces-{subset}-wght-normal"),
    "unbounded": ("@fontsource-variable/unbounded", "unbounded-{subset}-wght-normal"),
    "ibm-plex-sans": ("@fontsource-variable/ibm-plex-sans", "ibm-plex-sans-{subset}-wght-normal"),
    "jetbrains-mono": ("@fontsource-variable/jetbrains-mono", "jetbrains-mono-{subset}-wght-normal"),
    "noto-sans-jp": ("@fontsource-variable/noto-sans-jp", "noto-sans-jp-{subset}-wght-normal"),
}
SUBSETS = ("latin", "latin-ext")


@dataclass
class Font:
    key: str
    family: str          # name libass/Pillow match on (name table family)
    path: Path           # primary TTF (latin)
    files: List[Path]    # all subset files
    variable: bool = False
    weight: int = 400    # OS/2 usWeightClass of the primary file (default instance for variable fonts)


def cache_root() -> Path:
    return ensure_dir(home() / "cache" / "fonts" / "ttf")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_font(name: str, bold: bool = False, package_only: bool = False) -> Font:
    """Resolve a family ('anton', 'Inter') or a .ttf/.otf path to TTF files.

    `bold` prefers a bold static file as the primary one (all weights found
    are returned in .files, so libass can pick the bold face itself)."""
    p = Path(name).expanduser()
    if p.suffix.lower() in (".ttf", ".otf") and p.is_file():
        data = p.read_bytes()
        return Font(_norm(p.stem), family_name(data) or p.stem, p, [p], b"fvar" in _table_tags(data),
                    weight_class(data))
    key = re.sub(r"[\s_]+", "-", name.strip().lower())
    want = _norm(name)
    target = 700 if bold else 400
    # 1) fonts installed by `showtime assets font` (manifest + normalised names), exact weight only
    #    for the families setup also ships, so a stray SemiBold-only install never changes captions
    hit = None if package_only else _from_assets(key, target, exact=key in FONTSOURCE)
    if hit is None and bold and key in FONTSOURCE and not _offline() and not package_only:
        # a static bold cut looks much better than libass's synthetic bold on a variable font
        try:
            from ..assets import fonts as _af
            _af.resolve(key, 700)
            hit = _from_assets(key, target, exact=True)
        except Exception as e:  # noqa: BLE001 - offline / API down: use the setup fonts
            debug("static bold for %s unavailable (%s)" % (key, e))
    if hit is not None:
        return hit
    # 2) a user folder of .ttf/.otf files (SHOWTIME_CAPTION_FONTS), matched on the internal family name
    env = os.environ.get("SHOWTIME_CAPTION_FONTS")
    if env and Path(env).expanduser().is_dir():
        hits = []
        for f in sorted(Path(env).expanduser().rglob("*")):
            if f.suffix.lower() not in (".ttf", ".otf") or not f.is_file():
                continue
            data = f.read_bytes()
            if _norm(family_name(data) or f.stem).startswith(want) or _norm(f.stem).startswith(want):
                hits.append((abs(weight_class(data) - target), len(f.name), f, data))
        if hits:
            hits.sort(key=lambda h: h[:2])
            _d, _l, f, data = hits[0]
            if key not in FONTSOURCE or _d <= 100:
                return Font(key, family_name(data) or f.stem, f, [h[2] for h in hits],
                            b"fvar" in _table_tags(data), weight_class(data))
    # 2) Fontsource packages from setup -> converted TTF
    if key not in FONTSOURCE:
        raise ShowtimeError("font %r not available" % name,
                            hint="use one of: %s, or pass a .ttf/.otf path" % ", ".join(sorted(FONTSOURCE)))
    pkg, pattern = FONTSOURCE[key]
    files: List[Path] = []
    for subset in SUBSETS:
        stem = pattern.format(subset=subset)
        out = cache_root() / (stem + ".ttf")
        if not out.is_file():
            src_dir = node_modules() / pkg / "files"
            src = None
            for ext in (".woff", ".woff2"):
                if (src_dir / (stem + ext)).is_file():
                    src = src_dir / (stem + ext)
                    break
            if src is None:
                if subset == "latin":
                    raise ShowtimeError("font files for %r are missing (%s)" % (name, src_dir),
                                        hint="run `showtime setup` (installs the Fontsource font packages)")
                continue
            data = src.read_bytes()
            ttf = woff_to_sfnt(data) if data[:4] == b"wOFF" else woff2_to_sfnt(data)
            tmp = part_path(out)
            tmp.write_bytes(ttf)
            os.replace(str(tmp), str(out))
            debug("converted %s -> %s" % (src.name, out))
        files.append(out)
    data = files[0].read_bytes()
    return Font(key, family_name(data) or key, files[0], files, b"fvar" in _table_tags(data), weight_class(data))


def _offline() -> bool:
    return os.environ.get("SHOWTIME_OFFLINE", "") not in ("", "0", "false", "no")


def _from_assets(key: str, target: int, exact: bool) -> Optional[Font]:
    """A family installed under ~/.showtime/assets/fonts/<id>/ (static TTFs)."""
    d = home() / "assets" / "fonts" / key
    if not (d / "font.json").is_file():
        return None
    try:
        from ..assets import fonts as _af
        _af.normalize_installed(key)  # older installs: fix internal names first
    except Exception as e:  # noqa: BLE001
        debug("font name check skipped for %s: %s" % (key, e))
    cands = []
    for f in sorted(d.glob("*.ttf")) + sorted(d.glob("*.otf")):
        data = f.read_bytes()
        if b"fvar" in _table_tags(data):
            continue
        italic = "-italic" in f.stem
        cands.append((italic, abs(weight_class(data) - target), "-latin-" not in f.stem, f, data))
    upright = [c for c in cands if not c[0]]
    if not upright:
        return None
    upright.sort(key=lambda c: c[1:3])
    _i, dist, _s, f, data = upright[0]
    if exact and dist > 0:
        return None
    return Font(key, family_name(data) or key, f, [c[3] for c in cands], False, weight_class(data))


def fonts_dir(fonts: List[Font]) -> Path:
    """A folder holding exactly these fonts (for libass `fontsdir=`)."""
    import hashlib
    h = hashlib.sha1("|".join(sorted(str(f) for x in fonts for f in x.files)).encode()).hexdigest()[:10]
    d = ensure_dir(home() / "cache" / "fonts" / ("set-" + h))
    for x in fonts:
        for f in x.files:
            dst = d / f.name
            if not dst.is_file() or dst.stat().st_size != f.stat().st_size:
                # atomic: a parallel render reading this folder (libass) never sees a half-written font;
                # the temp file sits outside the folder so libass never scans it
                tmp = part_path(d.parent / f.name)
                tmp.write_bytes(f.read_bytes())
                os.replace(str(tmp), str(dst))
    return d


def pil_font(size: int, name: str = "inter"):
    """A Pillow FreeType font (falls back to Pillow's built-in font)."""
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(find_font(name).path), size)
    except Exception:  # noqa: BLE001 - labels must never break a tool
        try:
            return ImageFont.load_default(size)
        except TypeError:
            return ImageFont.load_default()


# --------------------------------------------------------------------------
# sfnt helpers
# --------------------------------------------------------------------------

def weight_class(data: bytes) -> int:
    try:
        n = struct.unpack(">H", data[4:6])[0]
        for i in range(n):
            tag, _cs, o, _ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            if tag == b"OS/2":
                return int(struct.unpack(">H", data[o + 4: o + 6])[0])
    except struct.error:
        pass
    return 400


def cmap_chars(data: bytes) -> set:
    """Code points mapped by an sfnt's Unicode cmap (formats 4 and 12)."""
    out: set = set()
    try:
        n = struct.unpack(">H", data[4:6])[0]
        off = None
        for i in range(n):
            tag, _cs, o, _ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            if tag == b"cmap":
                off = o
        if off is None:
            return out
        count = struct.unpack(">H", data[off + 2: off + 4])[0]
        subs = []
        for i in range(count):
            pid, eid, so = struct.unpack(">HHI", data[off + 4 + 8 * i: off + 12 + 8 * i])
            if (pid, eid) in ((3, 10), (0, 4), (0, 6), (3, 1), (0, 3), (0, 1), (0, 0)):
                subs.append(off + so)
        for st_ in subs:
            fmt = struct.unpack(">H", data[st_: st_ + 2])[0]
            if fmt == 4:
                segx2 = struct.unpack(">H", data[st_ + 6: st_ + 8])[0]
                seg = segx2 // 2
                ends = struct.unpack(">%dH" % seg, data[st_ + 14: st_ + 14 + segx2])
                starts = struct.unpack(">%dH" % seg, data[st_ + 16 + segx2: st_ + 16 + 2 * segx2])
                for a, b in zip(starts, ends):
                    if a != 0xFFFF:
                        out.update(range(a, b + 1))
            elif fmt == 12:
                ng = struct.unpack(">I", data[st_ + 12: st_ + 16])[0]
                for k in range(ng):
                    a, b, _g = struct.unpack(">III", data[st_ + 16 + 12 * k: st_ + 28 + 12 * k])
                    out.update(range(a, min(b, a + 0x20000) + 1))
    except (struct.error, IndexError):
        pass
    return out


def coverage(font: "Font") -> set:
    """Union of the code points of all of a Font's files."""
    cps: set = set()
    for f in font.files:
        try:
            cps |= cmap_chars(Path(f).read_bytes())
        except OSError:
            pass
    return cps


def _table_tags(data: bytes) -> bytes:
    try:
        n = struct.unpack(">H", data[4:6])[0]
        return b"".join(data[12 + 16 * i: 16 + 16 * i] for i in range(n))
    except struct.error:
        return b""


def family_name(data: bytes) -> Optional[str]:
    """Typographic (16) or legacy (1) family name from an sfnt's name table."""
    try:
        n = struct.unpack(">H", data[4:6])[0]
        off = None
        for i in range(n):
            tag, _cs, o, _ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            if tag == b"name":
                off = o
        if off is None:
            return None
        _fmt, count, str_off = struct.unpack(">HHH", data[off: off + 6])
        found: Dict[int, str] = {}
        for i in range(count):
            pid, eid, _lid, nid, ln, so = struct.unpack(">HHHHHH", data[off + 6 + 12 * i: off + 18 + 12 * i])
            if nid not in (1, 16):
                continue
            raw = data[off + str_off + so: off + str_off + so + ln]
            if pid in (0, 3):
                s = raw.decode("utf-16-be", "replace")
            else:
                s = raw.decode("latin-1", "replace")
            found.setdefault(nid, s)
        return found.get(1) or found.get(16)
    except (struct.error, IndexError):
        return None


def _checksum(b: bytes) -> int:
    b = b + b"\0" * (-len(b) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF


def build_sfnt(flavor: int, tables: Dict[bytes, bytes]) -> bytes:
    tags = sorted(tables)
    n = len(tags)
    es = max(0, n.bit_length() - 1)
    sr = (1 << es) * 16
    header = struct.pack(">IHHHH", flavor, n, sr, es, n * 16 - sr)
    offset = 12 + 16 * n
    recs, body = [], []
    for tag in tags:
        data = tables[tag]
        if tag == b"head" and len(data) >= 12:
            data = data[:8] + b"\0\0\0\0" + data[12:]
            tables[tag] = data
        recs.append(struct.pack(">4sIII", tag, _checksum(data), offset, len(data)))
        pad = data + b"\0" * (-len(data) % 4)
        body.append(pad)
        offset += len(pad)
    font = bytearray(header + b"".join(recs) + b"".join(body))
    if b"head" in tables:
        adj = (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF
        pos = 12 + 16 * n
        for tag in tags:
            if tag == b"head":
                struct.pack_into(">I", font, pos + 8, adj)
                break
            pos += len(tables[tag]) + (-len(tables[tag]) % 4)
    return bytes(font)


def woff_to_sfnt(data: bytes) -> bytes:
    """WOFF 1.0 -> TTF/OTF (tables are individually zlib-compressed)."""
    sig, flavor, _length, num = struct.unpack(">4sIIH", data[:14])
    if sig != b"wOFF":
        raise ShowtimeError("not a WOFF file")
    tables = {}
    for i in range(num):
        tag, off, comp, orig, _cs = struct.unpack(">4sIIII", data[44 + 20 * i: 64 + 20 * i])
        raw = data[off: off + comp]
        tables[tag] = zlib.decompress(raw) if comp < orig else raw
    return build_sfnt(flavor, tables)


# ---- WOFF2 ----------------------------------------------------------------

_KNOWN_TAGS = [b"cmap", b"head", b"hhea", b"hmtx", b"maxp", b"name", b"OS/2", b"post", b"cvt ", b"fpgm", b"glyf",
               b"loca", b"prep", b"CFF ", b"VORG", b"EBDT", b"EBLC", b"gasp", b"hdmx", b"kern", b"LTSH", b"PCLT",
               b"VDMX", b"vhea", b"vmtx", b"BASE", b"GDEF", b"GPOS", b"GSUB", b"EBSC", b"JSTF", b"MATH", b"CBDT",
               b"CBLC", b"COLR", b"CPAL", b"SVG ", b"sbix", b"acnt", b"avar", b"bdat", b"bloc", b"bsln", b"cvar",
               b"fdsc", b"feat", b"fmtx", b"fvar", b"gvar", b"hsty", b"just", b"lcar", b"mort", b"morx", b"opbd",
               b"prop", b"trak", b"Zapf", b"Silf", b"Glat", b"Gloc", b"Feat", b"Sill"]


class _Buf:
    __slots__ = ("b", "i")

    def __init__(self, b: bytes, i: int = 0):
        self.b, self.i = b, i

    def u8(self) -> int:
        v = self.b[self.i]
        self.i += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from(">H", self.b, self.i)[0]
        self.i += 2
        return v

    def i16(self) -> int:
        v = struct.unpack_from(">h", self.b, self.i)[0]
        self.i += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from(">I", self.b, self.i)[0]
        self.i += 4
        return v

    def take(self, n: int) -> bytes:
        v = self.b[self.i: self.i + n]
        if len(v) != n:
            raise ShowtimeError("truncated WOFF2 data")
        self.i += n
        return v

    def base128(self) -> int:
        v = 0
        for _ in range(5):
            c = self.u8()
            v = (v << 7) | (c & 0x7F)
            if not c & 0x80:
                return v
        raise ShowtimeError("bad UIntBase128 in WOFF2")

    def u255(self) -> int:
        c = self.u8()
        if c == 253:
            return self.u16()
        if c == 255:
            return self.u8() + 253
        if c == 254:
            return self.u8() + 506
        return c


def woff2_to_sfnt(data: bytes) -> bytes:
    """WOFF2 -> TTF (including the transformed glyf/loca and hmtx tables)."""
    try:
        import brotli  # type: ignore
    except ImportError:  # pragma: no cover - brotli ships with the venv
        try:
            import brotlicffi as brotli  # type: ignore
        except ImportError:
            raise ShowtimeError("WOFF2 fonts need the 'brotli' package", hint="run `showtime setup`")
    h = _Buf(data)
    if h.take(4) != b"wOF2":
        raise ShowtimeError("not a WOFF2 file")
    flavor = h.u32()
    h.u32()                      # length
    num = h.u16()
    h.u16()                      # reserved
    h.u32()                      # totalSfntSize
    comp_size = h.u32()
    h.i = 48
    entries = []
    for _ in range(num):
        flags = h.u8()
        idx = flags & 0x3F
        tag = h.take(4) if idx == 63 else _KNOWN_TAGS[idx]
        tv = (flags >> 6) & 3
        orig = h.base128()
        transformed = (tv == 0) if tag in (b"glyf", b"loca") else (tv != 0)
        tlen = h.base128() if transformed else orig
        entries.append((tag, orig, tlen, transformed))
    if flavor == 0x74746366:  # 'ttcf'
        raise ShowtimeError("WOFF2 font collections are not supported")
    stream = brotli.decompress(data[h.i: h.i + comp_size])
    raw: Dict[bytes, bytes] = {}
    pos = 0
    for tag, _orig, tlen, _tr in entries:
        raw[tag] = stream[pos: pos + tlen]
        pos += tlen
    tables: Dict[bytes, bytes] = {}
    glyf_info = None
    for tag, orig, tlen, tr in entries:
        if tag == b"glyf" and tr:
            glyf, loca, index_format, bboxes = _reconstruct_glyf(raw[b"glyf"])
            tables[b"glyf"], tables[b"loca"] = glyf, loca
            glyf_info = (index_format, bboxes)
        elif tag == b"loca" and tr:
            continue
        elif tag == b"hmtx" and tr:
            continue  # rebuilt below (needs glyf bboxes)
        else:
            tables[tag] = raw[tag]
    for tag, orig, tlen, tr in entries:
        if tag == b"hmtx" and tr:
            tables[b"hmtx"] = _reconstruct_hmtx(raw[b"hmtx"], tables, glyf_info)
    if glyf_info and b"head" in tables:
        head = bytearray(tables[b"head"])
        struct.pack_into(">h", head, 50, glyf_info[0])       # indexToLocFormat
        tables[b"head"] = bytes(head)
    return build_sfnt(flavor, tables)


def _with_sign(flag: int, v: int) -> int:
    return v if flag & 1 else -v


def _triplets(flags: List[int], g: _Buf) -> List[Tuple[int, int, bool]]:
    pts = []
    x = y = 0
    for fl in flags:
        on = not (fl >> 7)
        f = fl & 0x7F
        if f < 10:
            dx, dy = 0, _with_sign(f, ((f & 14) << 7) + g.u8())
        elif f < 20:
            dx, dy = _with_sign(f, (((f - 10) & 14) << 7) + g.u8()), 0
        elif f < 84:
            b0, b1 = f - 20, g.u8()
            dx = _with_sign(f, 1 + (b0 & 0x30) + (b1 >> 4))
            dy = _with_sign(f >> 1, 1 + ((b0 & 0x0C) << 2) + (b1 & 0x0F))
        elif f < 120:
            b0 = f - 84
            dx = _with_sign(f, 1 + ((b0 // 12) << 8) + g.u8())
            dy = _with_sign(f >> 1, 1 + (((b0 % 12) >> 2) << 8) + g.u8())
        elif f < 124:
            b0, b1, b2 = g.u8(), g.u8(), g.u8()
            dx = _with_sign(f, (b0 << 4) + (b1 >> 4))
            dy = _with_sign(f >> 1, ((b1 & 0x0F) << 8) + b2)
        else:
            b0, b1, b2, b3 = g.u8(), g.u8(), g.u8(), g.u8()
            dx = _with_sign(f, (b0 << 8) + b1)
            dy = _with_sign(f >> 1, (b2 << 8) + b3)
        x += dx
        y += dy
        pts.append((x, y, on))
    return pts


def _reconstruct_glyf(t: bytes):
    b = _Buf(t)
    b.u16()                                  # reserved
    option_flags = b.u16()
    num_glyphs = b.u16()
    index_format = b.u16()
    sizes = [b.u32() for _ in range(7)]
    start = b.i
    offs = []
    for s in sizes:
        offs.append(start)
        start += s
    n_contour = _Buf(t, offs[0])
    n_points = _Buf(t, offs[1])
    flag_s = _Buf(t, offs[2])
    glyph_s = _Buf(t, offs[3])
    comp_s = _Buf(t, offs[4])
    bbox_s = _Buf(t, offs[5])
    instr_s = _Buf(t, offs[6])
    overlap = None
    if option_flags & 1:
        overlap = t[start: start + ((num_glyphs + 7) >> 3)]
    bitmap_len = 4 * ((num_glyphs + 31) >> 5)
    bbox_bitmap = bbox_s.take(bitmap_len)
    glyf = bytearray()
    loca = [0]
    bboxes: List[Optional[Tuple[int, int, int, int]]] = []
    for gid in range(num_glyphs):
        nc = n_contour.i16()
        has_bbox = bbox_bitmap[gid >> 3] & (0x80 >> (gid & 7))
        out = b""
        box = None
        if nc == 0:
            if has_bbox:
                raise ShowtimeError("WOFF2: empty glyph with bbox")
        elif nc > 0:
            ends, total = [], 0
            for _ in range(nc):
                total += n_points.u255()
                ends.append(total - 1)
            flags = [flag_s.u8() for _ in range(total)]
            pts = _triplets(flags, glyph_s)
            ilen = glyph_s.u255()
            instr = instr_s.take(ilen)
            if has_bbox:
                box = (bbox_s.i16(), bbox_s.i16(), bbox_s.i16(), bbox_s.i16())
            else:
                xs = [p[0] for p in pts] or [0]
                ys = [p[1] for p in pts] or [0]
                box = (min(xs), min(ys), max(xs), max(ys))
            parts = [struct.pack(">hhhhh", nc, *box), struct.pack(">%dH" % nc, *ends),
                     struct.pack(">H", ilen), instr]
            fl_bytes = bytearray()
            xb, yb = bytearray(), bytearray()
            px = py = 0
            ovl = bool(overlap and overlap[gid >> 3] & (0x80 >> (gid & 7)))
            for k, (x, y, on) in enumerate(pts):
                dx, dy = x - px, y - py
                px, py = x, y
                f = 0x01 if on else 0
                if k == 0 and ovl:
                    f |= 0x40
                if dx == 0:
                    f |= 0x10
                elif -255 <= dx <= 255:
                    f |= 0x02 | (0x10 if dx > 0 else 0)
                    xb.append(abs(dx))
                else:
                    xb += struct.pack(">h", dx)
                if dy == 0:
                    f |= 0x20
                elif -255 <= dy <= 255:
                    f |= 0x04 | (0x20 if dy > 0 else 0)
                    yb.append(abs(dy))
                else:
                    yb += struct.pack(">h", dy)
                fl_bytes.append(f)
            out = b"".join(parts) + bytes(fl_bytes) + bytes(xb) + bytes(yb)
        else:  # composite
            if not has_bbox:
                raise ShowtimeError("WOFF2: composite glyph without bbox")
            comp_start = comp_s.i
            have_instr = False
            while True:
                fl = comp_s.u16()
                comp_s.u16()                                 # glyph index
                comp_s.i += 4 if fl & 0x0001 else 2          # args
                if fl & 0x0008:
                    comp_s.i += 2
                elif fl & 0x0040:
                    comp_s.i += 4
                elif fl & 0x0080:
                    comp_s.i += 8
                if fl & 0x0100:
                    have_instr = True
                if not fl & 0x0020:
                    break
            comp_data = t[comp_start: comp_s.i]
            box = (bbox_s.i16(), bbox_s.i16(), bbox_s.i16(), bbox_s.i16())
            out = struct.pack(">hhhhh", -1, *box) + comp_data
            if have_instr:
                ilen = glyph_s.u255()
                out += struct.pack(">H", ilen) + instr_s.take(ilen)
        out += b"\0" * (-len(out) % 4)
        glyf += out
        loca.append(len(glyf))
        bboxes.append(box)
    if index_format:
        loca_b = struct.pack(">%dI" % len(loca), *loca)
    else:
        loca_b = struct.pack(">%dH" % len(loca), *[v // 2 for v in loca])
    return bytes(glyf), loca_b, index_format, bboxes


def _reconstruct_hmtx(t: bytes, tables: Dict[bytes, bytes], glyf_info) -> bytes:
    b = _Buf(t)
    flags = b.u8()
    num_h = struct.unpack(">H", tables[b"hhea"][34:36])[0]
    num_glyphs = struct.unpack(">H", tables[b"maxp"][4:6])[0]
    adv = [b.u16() for _ in range(num_h)]
    bboxes = glyf_info[1] if glyf_info else [None] * num_glyphs
    xmin = [(bx[0] if bx else 0) for bx in bboxes]
    lsb = [b.i16() for _ in range(num_h)] if not flags & 1 else xmin[:num_h]
    rest = [b.i16() for _ in range(num_glyphs - num_h)] if not flags & 2 else xmin[num_h:num_glyphs]
    out = bytearray()
    for a, l in zip(adv, lsb):
        out += struct.pack(">Hh", a, l)
    for l in rest:
        out += struct.pack(">h", l)
    return bytes(out)
