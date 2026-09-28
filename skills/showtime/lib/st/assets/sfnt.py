"""Tiny, dependency-free TrueType/OpenType (sfnt) helpers.

Used to give downloaded static font files correct internal names. Some
generated static instances carry the name of the variable font's default
instance (e.g. every Space Grotesk weight calls itself "Space Grotesk Light"),
and non-RIBBI weights (SemiBold, Medium ...) use their own legacy family.
libass matches on the legacy family (name ID 1) plus the OS/2 weight, so a
wrong name makes captions silently fall back to another font or weight.

`set_style_names()` rewrites name IDs 1/2/4/6/16/17, OS/2 usWeightClass and
fsSelection, and head macStyle following the usual convention:

    400/700 (+ italic): ID1 = "<Family>",           ID2 = Regular|Bold|Italic|Bold Italic
    other weights:      ID1 = "<Family> <Weight>",  ID2 = Regular|Italic
    always:             ID16 = "<Family>",          ID17 = "<Weight>[ Italic]"

The rewrite is deterministic, so re-installing gives byte-identical files.
"""
from __future__ import annotations

import re
import struct
from typing import Dict, Optional, Tuple

WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
                600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}
OUR_IDS = (1, 2, 4, 6, 16, 17)


def _checksum(b: bytes) -> int:
    b = b + b"\0" * (-len(b) % 4)
    return sum(struct.unpack(">%dI" % (len(b) // 4), b)) & 0xFFFFFFFF


def read_tables(data: bytes) -> Tuple[int, Dict[bytes, bytes]]:
    """(flavor, {tag: table bytes}) of a plain sfnt (not WOFF/WOFF2/collections)."""
    flavor, n = struct.unpack(">IH", data[:6])
    if data[:4] in (b"wOFF", b"wOF2", b"ttcf"):
        raise ValueError("not a plain TTF/OTF file")
    tables: Dict[bytes, bytes] = {}
    for i in range(n):
        tag, _cs, off, ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        tables[tag] = data[off: off + ln]
    return flavor, tables


def build(flavor: int, tables: Dict[bytes, bytes]) -> bytes:
    """Assemble an sfnt with sorted tables, 4-byte padding and valid checksums."""
    tags = sorted(tables)
    n = len(tags)
    es = max(0, n.bit_length() - 1)
    sr = (1 << es) * 16
    header = struct.pack(">IHHHH", flavor, n, sr, es, n * 16 - sr)
    offset = 12 + 16 * n
    recs, body, head_pos = [], [], None
    for tag in tags:
        t = tables[tag]
        if tag == b"head" and len(t) >= 12:
            t = t[:8] + b"\0\0\0\0" + t[12:]
            head_pos = offset
        recs.append(struct.pack(">4sIII", tag, _checksum(t), offset, len(t)))
        body.append(t + b"\0" * (-len(t) % 4))
        offset += len(body[-1])
    font = bytearray(header + b"".join(recs) + b"".join(body))
    if head_pos is not None:
        struct.pack_into(">I", font, head_pos + 8, (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF)
    return bytes(font)


def names(data: bytes) -> Dict[int, str]:
    """Name IDs -> strings (Windows/Unicode records preferred)."""
    _flavor, tables = read_tables(data)
    t = tables.get(b"name")
    out: Dict[int, str] = {}
    if not t:
        return out
    _fmt, count, so = struct.unpack(">HHH", t[:6])
    for i in range(count):
        pid, _eid, _lid, nid, ln, off = struct.unpack(">HHHHHH", t[6 + 12 * i: 18 + 12 * i])
        raw = t[so + off: so + off + ln]
        s = raw.decode("utf-16-be", "replace") if pid in (0, 3) else raw.decode("latin-1", "replace")
        if pid == 3 or nid not in out:
            out[nid] = s
    return out


def weight_class(data: bytes) -> int:
    _f, tables = read_tables(data)
    os2 = tables.get(b"OS/2")
    return int(struct.unpack(">H", os2[4:6])[0]) if os2 and len(os2) >= 6 else 400


def _name_table(old: Optional[bytes], new: Dict[int, str]) -> bytes:
    recs = []  # (pid, eid, lid, nid, raw)
    if old and len(old) >= 6:
        _fmt, count, so = struct.unpack(">HHH", old[:6])
        for i in range(count):
            pid, eid, lid, nid, ln, off = struct.unpack(">HHHHHH", old[6 + 12 * i: 18 + 12 * i])
            if nid in OUR_IDS or nid in new:
                continue
            recs.append((pid, eid, lid, nid, old[so + off: so + off + ln]))
    for nid, s in new.items():
        recs.append((3, 1, 0x409, nid, s.encode("utf-16-be")))
    recs.sort(key=lambda r: r[:4])
    so = 6 + 12 * len(recs)
    head = [struct.pack(">HHH", 0, len(recs), so)]
    pool, seen, off = [], {}, 0
    for pid, eid, lid, nid, raw in recs:
        if raw not in seen:
            seen[raw] = off
            pool.append(raw)
            off += len(raw)
        head.append(struct.pack(">HHHHHH", pid, eid, lid, nid, len(raw), seen[raw]))
    return b"".join(head) + b"".join(pool)


def style_names(family: str, weight: int, italic: bool = False) -> Dict[int, str]:
    w = min(WEIGHT_NAMES, key=lambda k: abs(k - int(weight)))
    wname = WEIGHT_NAMES[w]
    ribbi = w in (400, 700)
    sub = ("Bold" if w == 700 else "Regular") if ribbi else "Regular"
    if italic:
        sub = "Bold Italic" if (ribbi and w == 700) else "Italic"
    fam1 = family if ribbi else "%s %s" % (family, wname)
    typo_sub = ("Italic" if w == 400 else wname + " Italic") if italic else wname
    full = "%s %s" % (family, typo_sub) if typo_sub != "Regular" else "%s Regular" % family
    ps = "%s-%s" % (re.sub(r"[^A-Za-z0-9]", "", family), re.sub(r"[^A-Za-z0-9]", "", typo_sub))
    return {1: fam1, 2: sub, 4: full, 6: ps[:63], 16: family, 17: typo_sub}


def set_style_names(data: bytes, family: str, weight: int, italic: bool = False) -> bytes:
    """Return `data` with consistent family/style names, weight class and style bits."""
    flavor, tables = read_tables(data)
    tables[b"name"] = _name_table(tables.get(b"name"), style_names(family, weight, italic))
    w = min(WEIGHT_NAMES, key=lambda k: abs(k - int(weight)))
    os2 = tables.get(b"OS/2")
    if os2 and len(os2) >= 64:
        b = bytearray(os2)
        struct.pack_into(">H", b, 4, int(weight))
        fs = struct.unpack(">H", b[62:64])[0]
        fs &= ~(0x01 | 0x20 | 0x40)
        if italic:
            fs |= 0x01
        if w == 700:
            fs |= 0x20
        if not italic and w != 700:
            fs |= 0x40
        struct.pack_into(">H", b, 62, fs)
        tables[b"OS/2"] = bytes(b)
    head = tables.get(b"head")
    if head and len(head) >= 46:
        b = bytearray(head)
        ms = struct.unpack(">H", b[44:46])[0] & ~0x03
        ms |= (0x01 if w == 700 else 0) | (0x02 if italic else 0)
        struct.pack_into(">H", b, 44, ms)
        tables[b"head"] = bytes(b)
    return build(flavor, tables)


def needs_names(data: bytes, family: str, weight: int, italic: bool = False) -> bool:
    try:
        cur = names(data)
    except (ValueError, struct.error):
        return False
    want = style_names(family, weight, italic)
    return any(cur.get(k) != v for k, v in want.items()) or weight_class(data) != int(weight)
