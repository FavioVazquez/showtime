"""Credits for every licensed sound in a video: credits.txt, the description block, the end card.

Input is a list of credit items (TASL: title, author, source, license), as `mix.report.json` lists
them under "credit_items": catalog music (`music.credit_item`), library items, and files with a
`.license.json` sidecar. Output:

  credits.txt       required attributions verbatim (the lines a license asks for), the project's
                    other credit lines, optional courtesy credits, an optional end-card line and
                    the Content ID notes
  share.txt block   between "--- Credits (keep in the video description) ---" and "--- end credits ---":
                    the same required lines, ready to paste under a YouTube/Vimeo/social post; the
                    block is replaced on every render and the rest of share.txt is left alone
  end card          one short line per track ("Music: “With These Hands” by Scott Buckley (CC BY 4.0)")

A CC BY (or other attribution-required) item without attribution text is an error, never a silent
omission. Scott Buckley's library is protected by Smart Content ID, which claims videos whose
description lacks the credit; the note says so every time one of his tracks is used.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..common import ShowtimeError, read_json

BLOCK_START = "--- Credits (keep in the video description) ---"
BLOCK_END = "--- end credits ---"
CLAIMS_RELEASE = "https://www.scottbuckley.com.au/library/copyright-claims-release/"


def _needs_credit(it: Dict[str, Any]) -> bool:
    if it.get("attribution_required"):
        return True
    lic = str(it.get("license") or "")
    if not lic or lic == "generated":
        return False
    try:
        from ..assets import licenses
        return licenses.classify(lic) in (licenses.ATTRIBUTION, licenses.SHARE_ALIKE)
    except Exception:  # noqa: BLE001
        return lic.upper().startswith("CC-BY") or lic.upper().startswith("CC BY")


def normalize(items: Iterable[Any]) -> List[Dict[str, Any]]:
    """Dicts with at least id/attribution/license; plain strings are attribution lines. Deduplicated."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for it in items or []:
        if isinstance(it, str):
            it = {"id": "line:" + it[:40], "attribution": it, "attribution_required": True}
        if not isinstance(it, dict):
            continue
        key = it.get("id") or (it.get("attribution") or "")[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(it))
    return out


def check(items: Iterable[Dict[str, Any]]) -> None:
    """Fail loudly when an attribution-required item has no credit text."""
    missing = [it for it in normalize(items) if _needs_credit(it) and not (it.get("attribution") or "").strip()]
    if missing:
        names = ", ".join("%s (%s)" % (it.get("title") or it.get("id"), it.get("license")) for it in missing[:5])
        raise ShowtimeError("%d sound(s) need attribution but have no credit text: %s" % (len(missing), names),
                            why="their license (CC BY) only allows use with a credit, and a video without it breaks it",
                            hint="use a catalog or library id (they carry the exact credit), add \"credit\" to the "
                                 "file's .license.json, or re-index your folder with --attribution \"...\"")


def content_id_notes(items: Iterable[Dict[str, Any]]) -> List[str]:
    notes = []
    for it in normalize(items):
        if it.get("content_id") == "smart-cid-releasable":
            notes.append("“%s” by %s is protected by Smart Content ID: keep the credit in your video "
                         "description (share.txt has it) or YouTube will claim the video; to lift a claim see %s"
                         % (it.get("title"), it.get("artist"), CLAIMS_RELEASE))
    return notes


def render(items: Iterable[Any], extra_lines: Sequence[str] = ()) -> Dict[str, Any]:
    """Text for credits.txt, the description block and the end card, from credit items."""
    its = normalize(items)
    check(its)
    required = []
    for it in its:
        if _needs_credit(it):
            a = it["attribution"].strip()
            if a not in required:
                required.append(a)
    body_req = " ".join(" ".join(required).lower().split())
    extra = []
    for l in extra_lines or []:
        l = str(l).strip()
        if l and " ".join(l.lower().split())[:40] not in body_req and l not in extra:
            extra.append(l)
    optional = []
    for it in its:
        o = it.get("credit_optional")
        if not _needs_credit(it) and o and o not in optional:
            optional.append(o)
    end_card = [it["end_card"] for it in its if it.get("end_card") and it.get("kind") == "music"]
    notes = content_id_notes(its)
    lines: List[str] = ["Credits", ""]
    if required:
        lines += ["Music and sound (required by their licenses: keep these in the video description):", ""]
        for a in required:
            lines += [a, ""]
    if extra:
        lines += ["Other material:", ""] + ["- " + e for e in extra] + [""]
    if optional:
        # "·", not "- ": render reads "- " lines of a project's credits.txt as required credits
        lines += ["Courtesy credits (CC0 / public domain, not required):", ""] + ["· " + o for o in optional] + [""]
    if end_card:
        lines += ["End card (optional, on screen):", ""] + end_card + [""]
    for n in notes:
        lines += ["Note: " + n, ""]
    if len(lines) == 2:
        lines += ["No attribution required (CC0, public domain or made with showtime).", ""]
    desc = ""
    if required or extra:
        dl = [BLOCK_START]
        for a in required:
            dl.append(" / ".join(x.strip() for x in a.splitlines() if x.strip()))
        dl += extra
        dl.append(BLOCK_END)
        desc = "\n".join(dl)
    return {"credits_txt": "\n".join(lines).rstrip() + "\n", "description": desc, "end_card": end_card,
            "notes": notes, "required": required, "extra": extra, "optional": optional}


def upsert_block(text: str, block: str) -> str:
    """share.txt with the credits block replaced (or appended); other text is untouched."""
    pat = re.compile(re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END), re.S)
    if not block:
        return pat.sub("", text).rstrip() + ("\n" if text.strip() else "")
    # a "Style reference:" line that `showtime reference` put in share.txt moves into the block
    for l in block.splitlines():
        if l.startswith("Style reference: "):
            text = _drop_outside(text, l, pat)
    if pat.search(text):
        return pat.sub(lambda _m: block, text)
    base = text.rstrip()
    return (base + "\n\n" if base else "") + block + "\n"


def _drop_outside(text: str, line: str, pat: "re.Pattern[str]") -> str:
    """`text` without standalone copies of `line` outside the credits block."""
    out, pos = [], 0
    for m in pat.finditer(text):
        out.append(re.sub(r"(?m)^%s[ \t]*(\n|$)" % re.escape(line), "", text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(re.sub(r"(?m)^%s[ \t]*(\n|$)" % re.escape(line), "", text[pos:]))
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


def write(out_dir: Path, items: Iterable[Any], credits_name: str = "credits.txt", share: bool = True,
          extra_lines: Sequence[str] = ()) -> Dict[str, Any]:
    """Write credits.txt (and the share.txt block) into out_dir. Returns what was written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    r = render(items, extra_lines)
    res: Dict[str, Any] = {"notes": r["notes"], "end_card": r["end_card"], "required": r["required"]}
    if r["required"] or r["extra"] or r["optional"]:
        from .mix import credits_file
        cp = credits_file(out_dir) if credits_name == "credits.txt" else out_dir / credits_name
        cp.write_text(r["credits_txt"], encoding="utf-8", newline="\n")
        res["credits_file"] = str(cp)
    if share and r["description"]:
        sp = out_dir / "share.txt"
        old = sp.read_text(encoding="utf-8") if sp.is_file() else ""
        new = upsert_block(old, r["description"])
        if new != old:
            sp.write_text(new, encoding="utf-8", newline="\n")
        res["share_file"] = str(sp)
    return res


def items_from_report(report: Any) -> List[Dict[str, Any]]:
    """Credit items of a mix.report.json (path or dict); older reports only have "credits" lines."""
    rep = read_json(report) if not isinstance(report, dict) else report
    if not isinstance(rep, dict):
        return []
    if rep.get("credit_items"):
        return normalize(rep["credit_items"])
    return normalize(rep.get("credits") or [])


def lines_from_file(p: Path) -> List[str]:
    """Credit lines of an existing credits file (`- line` items and bare lines), headers skipped."""
    if not Path(p).is_file():
        return []
    out = []
    skip = False
    for l in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
        s = l.strip()
        if s.endswith(":"):
            # our own optional sections are not requirements for the next render
            skip = s.startswith(("Courtesy credits", "End card"))
            continue
        if skip or not s or s in ("Credits", "Audio credits") or s.startswith(("Note:", "---", "No attribution required",
                                                                              "This video uses", "Generated by showtime")):
            continue
        out.append(s[2:].strip() if s.startswith(("- ", "* ")) else s)
    return out
