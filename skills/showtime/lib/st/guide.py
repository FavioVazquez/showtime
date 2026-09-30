"""Read the references one piece at a time (`showtime guide`), and keep their section tables current.

Every reference opens with a `## Essentials` block (the rules to follow at that step) that ends with a
table of its sections and their line ranges. `showtime guide <topic>` prints the Essentials and a live
section list; `showtime guide <topic> <section>` prints one section (by number, name or a `###`
sub-heading such as a component); `showtime guide --find <words>` finds the lines that mention something
across every reference. Agents read what the step needs instead of whole files.

Stdlib only and no package-relative imports at module level: scripts/check_release.py loads this file
directly to check (and fix) the section tables.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ESSENTIALS = "Essentials"
TABLE_MARK = "<!-- section lines: kept current by scripts/check_release.py -->"
ESSENTIALS_MAX_LINES = 40          # bullet lines in the block (the section table not counted)
EXEMPT = ("index", "crew/")        # the catalog and the crew role briefs are read whole
WHOLE_FILE_LINES = 120             # a file without Essentials this short prints whole
FIND_LIMIT = 25

_HEADING = re.compile(r"^(#{2,3})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_NUM = re.compile(r"^(\d+)[.)]?\s+")


# --------------------------------------------------------------------------- parsing

class Section:
    __slots__ = ("level", "title", "start", "end", "children")

    def __init__(self, level: int, title: str, start: int) -> None:
        self.level = level
        self.title = title
        self.start = start          # 1-based line of the heading
        self.end = start            # last line with content (inclusive)
        self.children: List["Section"] = []

    @property
    def number(self) -> Optional[str]:
        m = _NUM.match(self.title)
        return m.group(1) if m else None

    @property
    def name(self) -> str:
        """The title without its number and markup, for matching."""
        return _plain(_NUM.sub("", self.title))


def _plain(s: str) -> str:
    s = s.replace("`", "").replace("**", "")
    return re.sub(r"\s+", " ", s).strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _plain(s).lower()).strip()


class Doc:
    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.lines = text.splitlines()
        self.title = ""
        self.sections: List[Section] = []
        self._parse()

    def _parse(self) -> None:
        fence = None
        cur2: Optional[Section] = None
        cur3: Optional[Section] = None
        for i, line in enumerate(self.lines, 1):
            m = _FENCE.match(line)
            if m:
                fence = None if fence == m.group(1) else (fence or m.group(1))
                continue
            if fence:
                continue
            if not self.title and line.startswith("# "):
                self.title = line[2:].strip()
                continue
            h = _HEADING.match(line)
            if not h:
                continue
            if len(h.group(1)) == 2:
                cur2 = Section(2, h.group(2), i)
                self.sections.append(cur2)
                cur3 = None
            elif cur2 is not None:
                cur3 = Section(3, h.group(2), i)
                cur2.children.append(cur3)
        # ends: up to the next heading of the same or a higher level, without trailing blank lines
        flat = []
        for s in self.sections:
            flat.append(s)
            flat.extend(s.children)
        n = len(self.lines)
        for s in flat:
            nxt = n + 1
            for o in flat:
                if o.start > s.start and o.level <= s.level:
                    nxt = min(nxt, o.start)
            end = nxt - 1
            while end > s.start and not self.lines[end - 1].strip():
                end -= 1
            s.end = end

    @property
    def intro(self) -> List[str]:
        """The lines between the title and the first section (the "Read this when" paragraph)."""
        first = self.sections[0].start if self.sections else len(self.lines) + 1
        out, started = [], False
        for line in self.lines[:first - 1]:
            if not started:
                if line.startswith("# "):
                    started = True
                continue
            out.append(line)
        while out and not out[0].strip():
            out.pop(0)
        while out and not out[-1].strip():
            out.pop()
        return out

    def essentials(self) -> Optional[Section]:
        for s in self.sections:
            if s.name.lower() == ESSENTIALS.lower():
                return s
        return None

    def essentials_body(self) -> List[str]:
        """The Essentials bullets without the heading and the section table."""
        s = self.essentials()
        if s is None:
            return []
        body = self.lines[s.start:s.end]
        if TABLE_MARK in body:
            body = body[:body.index(TABLE_MARK)]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        return body

    def text(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start - 1:end])

    def body_sections(self) -> List[Section]:
        return [s for s in self.sections if s.name.lower() != ESSENTIALS.lower()]


def _row_label(s: Section, width: int = 100) -> str:
    label = _plain(s.title)
    subs = [_plain(c.title) for c in s.children]
    if subs:
        tail = ": " + ", ".join(subs)
        if len(label) + len(tail) > width:
            keep = []
            room = width - len(label) - 6
            for x in subs:
                if len(", ".join(keep + [x])) > room:
                    break
                keep.append(x)
            tail = ": " + ", ".join(keep) + (", ..." if len(keep) < len(subs) else "")
        label += tail
    return label.replace("|", "/")


# --------------------------------------------------------------------------- the section table

def section_table(doc: Doc) -> List[str]:
    rows = ["| Section | Lines |", "|---|---|"]
    for s in doc.body_sections():
        rows.append("| %s | %d-%d |" % (_row_label(s), s.start, s.end))
    return rows


def with_table(text: str, path: Path = Path("x.md")) -> str:
    """`text` with the section table at the end of its Essentials block, line numbers current.

    A file without an Essentials block comes back unchanged. The table's own length depends only on the
    number of sections, so one pass with placeholder numbers fixes every line number."""
    doc = Doc(path, text)
    ess = doc.essentials()
    if ess is None:
        return text
    lines = list(doc.lines)
    block = lines[ess.start:ess.end]                  # after the heading, up to the last content line
    if TABLE_MARK in block:
        block = block[:block.index(TABLE_MARK)]
    while block and not block[-1].strip():
        block.pop()
    n_rows = len(doc.body_sections())
    placeholder = [TABLE_MARK, "| Section | Lines |", "|---|---|"] + ["| x | 0-0 |"] * n_rows
    trial = lines[:ess.start] + block + [""] + placeholder + lines[ess.end:]
    doc2 = Doc(path, "\n".join(trial))
    real = [TABLE_MARK] + section_table(doc2)
    out = lines[:ess.start] + block + [""] + real + lines[ess.end:]
    new = "\n".join(out)
    if text.endswith("\n"):
        new += "\n"
    return new


def table_current(text: str) -> bool:
    return with_table(text) == text


# --------------------------------------------------------------------------- topics

def references_dir(skill: Optional[Path] = None) -> Path:
    if skill is None:
        env = os.environ.get("SHOWTIME_SKILL")
        skill = Path(env) if env else Path(__file__).resolve().parents[2]
    return skill / "references"


def topics(refs: Path) -> Dict[str, Path]:
    """name -> file: `components`, `workflows/launch-video`, `crew/critic`."""
    out = {}
    for p in sorted(refs.rglob("*.md")):
        out[p.relative_to(refs).with_suffix("").as_posix()] = p
    return out


def needs_essentials(name: str) -> bool:
    return not any(name == e or name.startswith(e) for e in EXEMPT)


def resolve(query: str, refs: Path) -> Tuple[Optional[str], List[str]]:
    """(topic name, candidates when ambiguous or unknown)."""
    all_t = topics(refs)
    q = query.strip().replace("\\", "/")
    q = re.sub(r"^(?:.*/)?references/", "", q)
    q = re.sub(r"\.md$", "", q).strip("/").lower()
    if q in all_t:
        return q, []
    base = {n: n.rsplit("/", 1)[-1] for n in all_t}
    for tier in (lambda n: base[n] == q,
                 lambda n: base[n].startswith(q) or n.startswith(q),
                 lambda n: q in n,
                 lambda n: all(w in n for w in re.split(r"[\s_-]+", q) if w)):
        hits = sorted(n for n in all_t if tier(n))
        if len(hits) == 1:
            return hits[0], []
        if hits:
            return None, hits
    return None, []


# --------------------------------------------------------------------------- sections

def find_section(doc: Doc, sel: str) -> Tuple[Optional[Section], List[Section]]:
    """The section `sel` names (a number, `§3`, a heading or part of one, a `###` name), plus the other
    sections that match as well as it does."""
    s = sel.strip().lstrip("§").strip()
    s = re.sub(r"[.)]$", "", s)
    subs = [c for sec in doc.sections for c in sec.children]
    if re.fullmatch(r"\d+", s):
        hits = [x for x in doc.sections if x.number == s]
        if not hits and not any(x.number for x in doc.sections):
            body = doc.body_sections()           # unnumbered headings: the n-th section in order
            hits = [body[int(s) - 1]] if 1 <= int(s) <= len(body) else []
        return (hits[0], hits[1:]) if hits else (None, [])
    q = _norm(s)
    if not q:
        return None, []
    words = q.split()
    tiers = [
        lambda x: _norm(x.name) == q,
        lambda x: _norm(x.name).startswith(q),
        lambda x: (" " + _norm(x.name) + " ").find(" " + q) >= 0,
        lambda x: q in _norm(x.name),
        lambda x: all(w in _norm(x.name) for w in words),
    ]
    for tier in tiers:
        for pool in (doc.sections, subs):
            hits = [x for x in pool if tier(x)]
            if hits:
                return hits[0], hits[1:]
    return None, []


def find_lines(docs: Sequence[Tuple[str, Doc]], words: str, limit: int = FIND_LIMIT) -> Tuple[List[str], int]:
    """Lines (and headings) that contain every word, as `topic §section > sub (line N): text`."""
    terms = [w for w in re.split(r"\s+", words.lower().strip()) if w]
    out: List[Tuple[int, str]] = []
    for name, doc in docs:
        table = set()
        ess = doc.essentials()
        if ess is not None:
            body = doc.lines[ess.start:ess.end]
            if TABLE_MARK in body:
                k = ess.start + body.index(TABLE_MARK) + 1
                table = set(range(k, ess.end + 1))
        for i, line in enumerate(doc.lines, 1):
            if i in table:
                continue
            low = line.lower()
            if not all(t in low for t in terms):
                continue
            where = _where(doc, i)
            head = bool(_HEADING.match(line)) or line.startswith("# ")
            text = _plain(line.lstrip("#-|* ").strip())
            if len(text) > 150:
                text = text[:147] + "..."
            out.append((0 if head else 1, "%s%s (line %d): %s" % (name, where, i, text)))
    out.sort(key=lambda x: x[0])
    total = len(out)
    return [t for _, t in out[:limit]], total


def _where(doc: Doc, line: int) -> str:
    owner = [s for s in doc.sections if s.start <= line]
    if not owner:
        return ""
    s = owner[-1]
    label = " §" + (s.number if s.number else _short(s.name))
    sub = [c for c in s.children if c.start <= line]
    return label + (" > " + _short(sub[-1].name) if sub else "")


def _short(name: str, n: int = 40) -> str:
    return name if len(name) <= n else name[:n - 3].rstrip() + "..."


# --------------------------------------------------------------------------- printing

def overview(name: str, doc: Doc, rel: str) -> str:
    """What `showtime guide <topic>` prints: intro, Essentials, the section list."""
    out = ["%s (%d lines): %s" % (rel, len(doc.lines), doc.title), ""]
    out.extend(doc.intro)
    body = doc.essentials_body()
    secs = doc.body_sections()
    if not body and len(doc.lines) <= WHOLE_FILE_LINES:
        return "\n".join(["%s (%d lines)" % (rel, len(doc.lines)), ""] + doc.lines)
    if body:
        out += ["", "## Essentials", ""] + body
    if secs:
        out += ["", "Sections (showtime guide %s <number or name>; --all prints the whole file):" % name]
        w = min(max(len(_row_label(s, 90)) for s in secs), 90)
        for s in secs:
            out.append("  %s  %s" % (_row_label(s, 90).ljust(w), "%d-%d" % (s.start, s.end)))
    return "\n".join(out)


def section_text(name: str, doc: Doc, sec: Section, rel: str, others: Sequence[Section]) -> str:
    kind = "§" + sec.number if sec.number else _plain(sec.title)
    head = "%s %s (%s lines %d-%d)" % (name, kind if sec.level == 2 else "> " + _plain(sec.title), rel,
                                        sec.start, sec.end)
    out = [head, "", doc.text(sec.start, sec.end)]
    if others:
        out += ["", "also matches: " + "; ".join("%s (lines %d-%d)" % (_plain(o.title), o.start, o.end)
                                                 for o in others[:6])]
    return "\n".join(out)
