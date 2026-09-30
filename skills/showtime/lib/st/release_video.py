"""Release notes or a pull request -> a finished HTML video project, with no agent in the loop.

`showtime release-video notes.md -o <project>` reads release notes (a GitHub release body, a
CHANGELOG section, a PR description) and writes a project `showtime render` can render: a hook card
(name, version, date), one scene per group of changes (the notes' own headings and lines, verbatim),
and an end card (install command, URL, the people credited in the notes). Every word on screen comes
from the notes or from a flag the caller passed; nothing is invented, so the output is safe to run
unattended (CI, the GitHub Action) and honest by construction. What it cannot do is choose an angle:
a person or an agent following references/workflows/changelog-video.md makes a better film.

Stdlib only (it also runs before the venv exists).
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

# heading words -> the group a section belongs to, in the order groups are shown
GROUPS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("highlights", "Highlights", ("highlight", "what's new", "whats new", "headline", "summary of changes")),
    ("breaking", "Breaking changes", ("breaking", "removed", "removal", "deprecat", "migration", "upgrade note")),
    ("new", "New", ("added", "feature", "new", "enhancement", "addition")),
    ("changed", "Changed", ("changed", "change", "improve", "performance", "perf", "update", "refactor")),
    ("fixed", "Fixed", ("fix", "bug", "patch", "security")),
]
# sections that are not user-facing: counted, never shown
GROUP_KEYS = tuple(k for k, _t, _w in GROUPS)
SKIP_WORDS = ("contributor", "dependenc", "chore", "internal", "ci", "build", "tests", "testing",
              "docs", "documentation", "maintenance", "full changelog", "checksum", "assets", "download")
LAST_WORDS = ("other", "misc")                # catch-all sections: shown after the named groups
GENERIC_HEADINGS = ("what's changed", "whats changed", "changes", "changelog", "release notes", "notes")
CONVENTIONAL = {"feat": "new", "feature": "new", "fix": "fixed", "bugfix": "fixed", "perf": "changed",
                "refactor": "changed", "revert": "changed", "security": "fixed",
                "docs": None, "doc": None, "chore": None, "ci": None, "build": None, "test": None, "tests": None,
                "style": None, "deps": None}

BOTS = ("dependabot", "renovate", "github-actions", "pre-commit-ci")
_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_PR_URL = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues)/(\d+)\S*")
_URL = re.compile(r"<?https?://\S+?>?(?=[\s),.;]|$)")
_BY_IN = re.compile(r"\s+by\s+(@[\w-]+(?:\[bot\])?(?:\s*(?:,|and)\s*@[\w-]+)*)\s+in\s+(#\d+|\S+)\s*$", re.I)
_AUTHOR = re.compile(r"(?<![\w/])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(\[bot\])?")
_REFS = re.compile(r"\s*\((?:#\d+|[0-9a-f]{7,40})(?:\s*,\s*(?:#\d+|[0-9a-f]{7,40}))*\)\s*$")
_TRAIL_REF = re.compile(r"\s+(#\d+)\s*$")
_HASH_REF = re.compile(r"#(\d+)")
_CONV = re.compile(r"^([a-z]+)(?:\(([^)]*)\))?(!)?:\s+", re.I)
_VERSION = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?(?:[-.+][0-9A-Za-z.]+)?)\b")
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
MAX_ITEM_CHARS = 96


def _plain(text: str) -> str:
    """Markdown inline -> plain text (links keep their text; emphasis markers go; code keeps backticks)."""
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _PR_URL.sub(lambda m: "#" + m.group(1), text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    parts = re.split(r"(`[^`]*`)", text)      # HTML tags go, except inside code spans (`--agent <name>`)
    text = "".join(p if p.startswith("`") else re.sub(r"</?[A-Za-z][^>]*>", "", p) for p in parts)
    return re.sub(r"\s+", " ", text).strip()


def _group_of(heading: str) -> Tuple[Optional[str], str]:
    """(group key or None to skip, display title) for a section heading."""
    h = _plain(heading).strip(" :#").strip()
    low = re.sub(r"[^\w' ]+", " ", h.lower()).strip()
    low = re.sub(r"\s+", " ", low)
    disp = re.sub(r"\s*\([^)]*\)", "", h).strip() or h
    if not low or low in GENERIC_HEADINGS:
        return "", disp
    if any(re.search(r"\b" + re.escape(w), low) for w in SKIP_WORDS):
        return None, disp
    if low.split()[0] in LAST_WORDS:
        return "other:" + low, disp
    for key, _title, words in GROUPS:
        if any(re.search(r"\b" + re.escape(w), low) for w in words):
            if ":" in disp:                  # "Added: faster test runs" -> "Added"
                disp = disp.split(":", 1)[0].strip()
            return key, shorten(disp, 48)
    return "other:" + low, shorten(disp, 48)


def _clean_item(raw: str) -> Dict[str, Any]:
    """One bullet -> {text, refs, authors, conv}."""
    text = _plain(raw)
    authors: List[str] = []
    refs: List[str] = []
    m = _BY_IN.search(text)
    bot = False
    if m:                                    # GitHub's generated notes: "Fix x by @a in #12"
        found = _AUTHOR.findall(m.group(1))
        authors += ["@" + a for a, _b in found]
        bot = bool(found) and all(b or a.lower() in BOTS for a, b in found)
        ref = m.group(2)
        refs.append(ref if ref.startswith("#") else "")
        text = text[:m.start()].rstrip()
    m = _REFS.search(text)
    if m:
        refs += ["#" + n for n in _HASH_REF.findall(m.group(0))]
        text = text[:m.start()].rstrip()
    m = _TRAIL_REF.search(text)
    if m:
        refs.append(m.group(1))
        text = text[:m.start()].rstrip()
    m = re.search(r"\s*[-(]?\s*(?:thanks|by)\s+(@[\w-]+(?:\s*(?:,|and)\s*@[\w-]+)*)\)?\.?\s*$", text, re.I)
    if m:
        authors += ["@" + a for a, _b in _AUTHOR.findall(m.group(1))]
        text = text[:m.start()].rstrip()
    text = _URL.sub("", text).strip()
    conv = None
    cm = _CONV.match(text)
    if cm and cm.group(1).lower() in CONVENTIONAL:
        conv = CONVENTIONAL[cm.group(1).lower()]
        if cm.group(3):
            conv = "breaking"
        text = text[cm.end():]
        conv = conv or "skip"
    if bot or re.match(r"^(bump|update) \S+ from \S+ to \S+", text, re.I):
        conv = "skip"                        # dependency bumps: counted, not shown
    text = text.strip(" -–—:;")
    if text[:1].islower() and conv:
        text = text[0].upper() + text[1:]
    refs = [r for r in refs if r]
    seen: List[str] = []
    for a in authors:
        if a not in seen and not a.lower().endswith("[bot]") and a.lower().lstrip("@") not in BOTS:
            seen.append(a)
    return {"text": text, "refs": list(dict.fromkeys(refs)), "authors": seen, "conv": conv}


def shorten(text: str, limit: int = MAX_ITEM_CHARS) -> str:
    """Cut a long line at a word boundary and mark the cut with an ellipsis (the words kept are verbatim)."""
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"


def first_sentence(text: str, limit: int = 120) -> str:
    """The notes' opening sentence (verbatim), cut at a word past `limit` characters."""
    m = re.match(r"^(.+?[.!?])(?:\s|$)", text or "")
    return shorten(m.group(1) if m else (text or ""), limit)


def parse_notes(md: str) -> Dict[str, Any]:
    """Release notes (Markdown) -> {title, version, date, summary, sections, authors, compare, skipped}."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"```.*?```", "", md, flags=re.S)
    title = ""
    summary = ""
    compare = ""
    sections: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = {"key": "", "title": "", "items": []}
    sections.append(cur)
    authors: List[str] = []
    skipped = 0
    in_para = False
    lines = _join_continuations(md.splitlines())
    for line in lines:
        s = line.rstrip()
        h = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if h:
            in_para = False
            level, text = len(h.group(1)), h.group(2)
            if not title and level <= 2 and not any(sec["items"] for sec in sections if sec):
                gk = _group_of(text)[0]
                if gk is not None and gk not in GROUP_KEYS and (level == 1 or _VERSION.search(text)):
                    title = _plain(text)
                    continue
            key, disp = _group_of(text)
            if key is None:
                cur = None
            else:
                cur = {"key": key, "title": disp, "items": []}
                sections.append(cur)
            continue
        fc = re.match(r"^\s*\**Full Changelog\**:?\s*\**:?\s*(\S+)", s, re.I)
        if fc:
            compare = _LINK.sub(lambda m: m.group(2), fc.group(1)).strip("<>")
            continue
        b = re.match(r"^(\s*)[-*+]\s+(.*)$", s)
        if b and len(b.group(1).expandtabs(4)) < 2:
            in_para = False
            item = _clean_item(b.group(2))
            authors += [a for a in item["authors"] if a not in authors]
            if cur is None:
                skipped += 1
                continue
            if item["conv"] == "skip" or not item["text"] or len(item["text"]) < 3:
                skipped += 1
                continue
            cur["items"].append(item)
            continue
        if b:                                # nested bullet: detail of the item above, not shown
            continue
        lab = re.match(r"^\s*(?:\*\*|__)?([^*_|>].{1,58}?):(?:\*\*|__)?\s*$", s)
        if lab and not re.search(r"https?:", s):   # "Highlights:" before a list works like a heading
            in_para = False
            key, disp = _group_of(lab.group(1))
            if key:
                cur = {"key": key, "title": disp, "items": []}
                sections.append(cur)
                continue
        if s.strip() and not summary and cur is sections[0] and not sections[0]["items"] \
                and not re.match(r"^\s*(\||>|!\[)", s):
            summary = _plain(s)
            in_para = True
            continue
        if s.strip() and in_para and cur is sections[0] and not sections[0]["items"]:
            summary = (summary + " " + _plain(s)).strip()
            continue
        in_para = False
        for a, _bot in _AUTHOR.findall(s):   # "New contributors" and prose credit lines
            if cur is None and "@" + a not in authors:
                authors.append("@" + a)
    # items without a heading (or under a generic one): sort them by their conventional prefix
    out: List[Dict[str, Any]] = []
    for sec in sections:
        if not sec["items"]:
            continue
        if sec["key"] == "":
            by: Dict[str, List[Dict[str, Any]]] = {}
            for it in sec["items"]:
                by.setdefault(it["conv"] or "", []).append(it)
            for key, _t, _w in GROUPS + [("", "", ())]:
                if by.get(key):
                    out.append({"key": key or "changes", "title": _default_title(key, sec["title"]),
                                "items": by[key]})
            continue
        out.append(sec)
    order = {k: i for i, (k, _t, _w) in enumerate(GROUPS)}
    out.sort(key=lambda s: order.get(s["key"], len(order)))
    merged: List[Dict[str, Any]] = []
    for sec in out:                          # two "Added" headings -> one group
        prev = next((m for m in merged if m["key"] == sec["key"]), None)
        if prev is not None:
            prev["items"] += sec["items"]
        else:
            merged.append({"key": sec["key"], "title": sec["title"], "items": list(sec["items"])})
    version = ""
    date = ""
    for src in (title, summary):
        if not version:
            m = _VERSION.search(src or "")
            version = m.group(1) if m else ""
        if not date:
            m = _DATE.search(src or "")
            date = m.group(1) if m else ""
    return {"title": title, "version": version, "date": date, "summary": summary, "sections": merged,
            "authors": authors, "compare": compare, "skipped": skipped}


def _join_continuations(lines: Sequence[str]) -> List[str]:
    """A bullet's wrapped lines (indented or lazy) join the bullet, so no item is cut mid-sentence."""
    out: List[str] = []
    in_item = False
    for line in lines:
        s = line.rstrip()
        is_head = re.match(r"^\s{0,3}#{1,6}\s", s)
        is_bullet = re.match(r"^(\s*)[-*+]\s+", s)
        if in_item and s.strip() and not is_head and not is_bullet and not re.match(r"^\s*(\||>|```|\d+\.\s)", s):
            out[-1] = out[-1] + " " + s.strip()
            continue
        in_item = bool(is_bullet) and len(is_bullet.group(1).expandtabs(4)) < 2
        out.append(s)
    return out


def _default_title(key: str, heading: str) -> str:
    for k, t, _w in GROUPS:
        if k == key:
            return t
    return heading if heading and heading.lower() not in GENERIC_HEADINGS else "Changes"


def changelog_section(md: str, version: str) -> str:
    """The `## <version>` section of a CHANGELOG (with or without a leading v, brackets or a date)."""
    v = re.escape(version.lstrip("v"))
    lines = md.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,3})\s+\[?v?(%s)\]?(?:\b|\s|$)" % v, line)
        if m:
            start, level = i, len(m.group(1))
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    # promote the version heading so it reads as the title
    return "\n".join(["# " + lines[start].lstrip("#").strip()] + lines[start + 1:end])


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------

def reading_time(text: str) -> float:
    """Settled hold for text no voice carries (references/pacing.md section 1), plus the entrance."""
    return max(1.6, 0.5 + len(text) / 13.0) + 0.45


def plan(notes: Dict[str, Any], *, name: str, version: str = "", kind: str = "release", max_items: int = 7,
         per_scene: int = 3, max_scenes: int = 3, max_seconds: float = 50.0) -> Dict[str, Any]:
    """Pick what goes on screen and how long each scene holds. Returns the scene plan."""
    shown: List[Dict[str, Any]] = []
    total = sum(len(s["items"]) for s in notes["sections"])
    budget = max_items
    for sec in notes["sections"]:
        if len(shown) >= max_scenes or budget <= 0:
            break
        items = sec["items"][:min(per_scene, budget)]
        budget -= len(items)
        shown.append({"key": sec["key"], "title": sec["title"],
                      "items": [dict(it, text=shorten(it["text"])) for it in items]})
    def length() -> float:
        return 3.6 + 4.8 + (reading_time(first_sentence(notes.get("summary", ""))) if notes.get("summary") else 0) + sum(1.8 + sum(reading_time(it["text"]) for it in sec["items"]) for sec in shown)
    while max_seconds and length() > max_seconds:     # drop from the last group first, keep one line per group
        longest = [sec for sec in shown if len(sec["items"]) > 1]
        if longest:
            longest[-1]["items"].pop()
        elif len(shown) > 1:
            shown.pop()
        else:
            break
    n_shown = sum(len(s["items"]) for s in shown)
    hook = 3.6
    if notes.get("summary"):                 # the summary line rises at 0.9 s and must be read before the cut
        hook = max(hook, round(0.9 + reading_time(first_sentence(notes["summary"])), 2))
    scenes: List[Dict[str, Any]] = [{"id": "hook", "dur": hook}]
    more = max(0, total - n_shown)
    for i, sec in enumerate(shown):
        dur = 0.9 + sum(reading_time(it["text"]) for it in sec["items"]) + 0.9
        if more and i == len(shown) - 1:
            dur += 1.6                       # "+ N more in the release notes" gets its own beat
        scenes.append({"id": "s%d" % (i + 1), "dur": round(dur, 2), "section": sec})
    scenes.append({"id": "end", "dur": 4.8})
    return {"name": name, "version": version, "kind": kind, "scenes": scenes, "shown": n_shown,
            "total": total, "more": max(0, total - n_shown)}


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

def _e(s: str) -> str:
    return html.escape(s or "", quote=True)


def _inline(s: str) -> str:
    """Escape, then show `code` spans in the mono face."""
    parts = re.split(r"(`[^`]+`)", s or "")
    out = []
    for p in parts:
        if len(p) > 2 and p.startswith("`") and p.endswith("`"):
            # short spans never break at their hyphens ("--explain" split as "-" / "-explain")
            out.append("<code%s>%s</code>" % (' class="nw"' if len(p) <= 26 else "", _e(p[1:-1])))
        else:
            out.append(_e(p))
    return "".join(out)


CSS = r"""
  :root {
    --bg: #0e1013; --fg: #f3f1ec; --muted: #aab0ba; --accent: #7fb2ff; --surface: #171a20;
    --line: rgb(243 241 236 / 0.10);
    --font-display: 'Geist', 'Inter', sans-serif; --font-mono: 'Geist Mono', 'JetBrains Mono', monospace;
    --scene-bg: transparent; color-scheme: dark;
  }
  .stage { background: var(--bg); }
  .scene { --s-label: 2.6cqh; --s-name: 13cqh; --s-ver: 6.4cqh; --s-sum: 3.6cqh; --s-head: 8.4cqh;
           --s-item: 4.6cqh; --s-ref: 2.7cqh; --s-cta: 3.8cqh; --s-url: 3cqh; --s-thanks: 2.8cqh; }
  .world { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
  .world .key { position: absolute; inset: -30%;
    background: radial-gradient(34% 40% at 50% 50%, color-mix(in oklab, var(--accent) 15%, transparent), transparent 72%);
    animation: keyDrift 40s linear both; }
  @keyframes keyDrift { from { transform: translate(-16%, 8%); } to { transform: translate(18%, -10%); } }
  .world .vig { position: absolute; inset: 0; background: radial-gradient(120% 95% at 50% 45%, transparent 55%, rgb(0 0 0 / 0.5)); }
  .cam { position: absolute; inset: 0; }
  .label { font: 500 var(--s-label)/1.3 var(--font-mono); letter-spacing: 0.14em; text-transform: uppercase;
           color: var(--muted); margin: 0; }
  .label b { color: var(--accent); font-weight: 500; }
  @keyframes rise { from { opacity: 0; transform: translateY(0.4em); } to { opacity: 1; transform: none; } }
  @keyframes grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }

  /* hook: complete at frame 0 (the poster) */
  .hook { position: absolute; left: 8cqw; right: 8cqw; top: 50%; translate: 0 -50%; display: flex;
          flex-direction: column; gap: 2.6cqh; }
  .hook .name { font: 700 var(--s-name)/0.98 var(--font-display); letter-spacing: -0.04em; color: var(--fg); margin: 0;
                overflow-wrap: anywhere; }
  .hook .ver { font: 600 var(--s-ver)/1 var(--font-mono); color: var(--accent); margin: 0; letter-spacing: -0.01em; }
  .hook .sum { font: 400 var(--s-sum)/1.35 var(--font-display); color: var(--muted); margin: 0; max-width: 38em; }
  .hook .sum { animation: rise 0.8s cubic-bezier(0.16, 1, 0.3, 1) calc(0.9s + var(--i, 0) * 0.25s) both; }

  /* change scenes: the notes' heading and its lines, one after another */
  .list { position: absolute; left: 9cqw; right: 9cqw; top: 50%; translate: 0 -50%; display: flex;
          flex-direction: column; gap: 3.2cqh; }
  .list .head { font: 650 var(--s-head)/1.04 var(--font-display); letter-spacing: -0.03em; color: var(--fg); margin: 0; }
  .list .head em { font-style: normal; color: var(--accent); }
  .items { display: flex; flex-direction: column; gap: 2.6cqh; margin: 0.6cqh 0 0; padding: 0; list-style: none; }
  .item { position: relative; padding-left: 3cqh; opacity: 0;
          animation: rise 0.55s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .item::before { content: ""; position: absolute; left: 0; top: 0.2em; bottom: 0.2em; width: 0.5cqh; border-radius: 1cqh;
                  background: var(--accent); transform-origin: top; animation: grow 0.6s cubic-bezier(0.16, 1, 0.3, 1) var(--at) both; }
  .item .t { font: 450 var(--s-item)/1.32 var(--font-display); color: var(--fg); margin: 0; }
  .item .t code { font: 450 0.92em/1 var(--font-mono); color: var(--accent); }
  code.nw { white-space: nowrap; }
  .item .r { font: 500 var(--s-ref)/1.3 var(--font-mono); color: var(--muted); margin: 0.6cqh 0 0; letter-spacing: 0.02em; }
  .more { font: 500 var(--s-ref)/1.3 var(--font-mono); color: var(--muted); margin: 0.4cqh 0 0 3cqh;
          animation: rise 0.6s ease var(--at) both; }

  /* end card */
  .end { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
         justify-content: center; gap: 2.8cqh; text-align: center; padding: 0 8cqw; }
  .end .name { font: 700 calc(var(--s-name) * 0.85)/0.95 var(--font-display); letter-spacing: -0.04em; color: var(--fg); margin: 0;
               overflow-wrap: anywhere; }
  .end .name em { font-style: normal; color: var(--accent); font-size: 0.5em; letter-spacing: -0.01em; margin-left: 0.25em; }
  .end .cta { padding: 1.5cqh 3cqh; border-radius: 1.2cqh; font: 500 var(--s-cta)/1.2 var(--font-mono); color: var(--fg);
              background: color-mix(in oklab, var(--surface) 90%, var(--fg)); max-width: 84cqw;
              box-shadow: 0 0 0 max(1px, 0.14cqh) color-mix(in oklab, var(--accent) 55%, transparent); }
  .end .cta .ps { color: var(--accent); }
  .end .url { font: 500 var(--s-url)/1.2 var(--font-mono); color: var(--muted); margin: 0; max-width: 100%; white-space: nowrap; }
  .end .thanks { font: 400 var(--s-thanks)/1.4 var(--font-display); color: var(--muted); margin: 1cqh 0 0; max-width: 60em; }
  .end > * { animation: rise 0.8s cubic-bezier(0.16, 1, 0.3, 1) calc(0.3s + var(--i, 0) * 0.16s) both; }

  /* square and tall frames: the same page re-laid (showtime render --size 9:16) */
  @container (max-aspect-ratio: 5/4) {
    .scene { --s-label: 2.7cqw; --s-name: 12cqw; --s-ver: 6cqw; --s-sum: 3.9cqw; --s-head: 7cqw; --s-item: 4.2cqw;
             --s-ref: 2.9cqw; --s-cta: 3.6cqw; --s-url: 3cqw; --s-thanks: 3cqw; }
    .hook, .list { left: 7cqw; right: 7cqw; }
  }
  @container (max-aspect-ratio: 3/4) {
    .scene { --s-label: 4.2cqw; --s-name: 12cqw; --s-ver: 7cqw; --s-sum: 4.8cqw; --s-head: 8.4cqw; --s-item: 5.2cqw;
             --s-ref: 4.2cqw; --s-cta: 4.4cqw; --s-url: 4.2cqw; --s-thanks: 4.2cqw; }
    .hook, .list { left: 10cqw; right: 19cqw; top: 43%; }
    .end { justify-content: flex-start; padding: 26cqh 19cqw 0 10cqw; }
  }
"""


def _join_people(people: Sequence[str], limit: int = 8) -> str:
    people = list(people)
    if len(people) <= limit:
        return ", ".join(people)
    return "%s and %d more" % (", ".join(people[:limit]), len(people) - limit)


def build_page(p: Dict[str, Any], notes: Dict[str, Any], *, install: str = "", url: str = "", date: str = "",
               label: str = "") -> str:
    name, version, kind = p["name"], p["version"], p["kind"]
    ver_disp = version if (not version or kind == "pr" or version.startswith(("v", "#"))) else "v" + version
    lab = label or ("Pull request" if kind == "pr" else "Release")
    out: List[str] = []
    t = 0.0
    prev = ""
    for sc in p["scenes"]:
        start = "0" if not prev else "#" + prev
        trans = "" if not prev else ' data-transition="dip 0.5"'   # text to text: a blur dissolve smears both mid-window
        # one slow push per scene (about 5 %, zooming about the text block), so no stretch reads as a freeze
        push = [{"at": 0, "zoom": 1}, {"at": 0.15, "dur": round(max(1.0, sc["dur"] - 0.3), 2), "zoom": 1.08,
                                       "focus": [50, 50] if sc["id"] in ("hook", "end") else [30, 50],
                                       "to": "stay", "ease": "linear"}]
        out.append('  <section class="scene" id="%s" data-start="%s" data-dur="%.2f"%s>\n    <div class="cam" '
                   'data-st="camera" data-path=\'%s\'>' % (sc["id"], start, sc["dur"], trans, json.dumps(push)))
        if sc["id"] == "hook":
            meta = " &middot; ".join(x for x in (_e(lab), _e(date)) if x)
            out.append('      <div class="hook">\n        <p class="label">%s</p>\n        <h1 class="name">%s</h1>'
                       % (meta, _inline(name)))
            if ver_disp:
                out.append('        <p class="ver">%s</p>' % _e(ver_disp))
            if notes.get("summary"):
                out.append('        <p class="sum" style="--i:0">%s</p>' % _inline(first_sentence(notes["summary"])))
            out.append("      </div>")
        elif sc["id"] == "end":
            out.append('      <div class="end">')
            out.append('        <h2 class="name" style="--i:0">%s%s</h2>' % (
                _inline(name), "<em>%s</em>" % _e(ver_disp) if ver_disp else ""))
            i = 1
            if install:
                out.append('        <div class="cta" data-st="fit" style="--i:%d"><span class="ps">$ </span>%s</div>'
                           % (i, _e(install)))
                i += 1
            if url:
                out.append('        <p class="url" data-st="fit" style="--i:%d">%s</p>' % (i, _e(re.sub(r"^https?://", "", url))))
                i += 1
            if notes.get("authors"):
                out.append('        <p class="thanks" style="--i:%d">Thanks to %s</p>'
                           % (i, _e(_join_people(notes["authors"]))))
            out.append("      </div>")
        else:
            sec = sc["section"]
            out.append('      <div class="list">\n        <p class="label">%s <b>&middot;</b> %s</p>\n'
                       '        <h2 class="head">%s</h2>\n        <ul class="items">'
                       % (_e(name), _e(ver_disp or lab), _inline(sec["title"])))
            at = 0.9
            for it in sec["items"]:
                ref = " \u00b7 ".join(x for x in (" ".join(it["refs"]), " ".join(it["authors"])) if x)
                out.append('          <li class="item" style="--at:%.2fs"><p class="t">%s</p>%s</li>'
                           % (at, _inline(it["text"]), '<p class="r">%s</p>' % _e(ref) if ref else ""))
                at += reading_time(it["text"])
            out.append("        </ul>")
            if sc is p["scenes"][-2] and p["more"]:
                out.append('        <p class="more" style="--at:%.2fs">+ %d more in the release notes</p>'
                           % (at, p["more"]))
            out.append("      </div>")
        out.append("    </div>\n  </section>")
        t += sc["dur"]
        prev = sc["id"]
    body = "\n".join(out)
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>%s</title>\n"
            "<script src=\"/_st/stage.js\"></script>\n<link rel=\"stylesheet\" href=\"/_st/themes/neutral.css\">\n"
            "<script type=\"module\" src=\"/_st/components/index.js\"></script>\n<!-- Written by `showtime "
            "release-video` from release notes: every line on screen is from the notes or a flag. Edit freely; "
            "`showtime retime . -d <s>` changes the length. -->\n<style>%s</style>\n</head>\n<body>\n"
            "<div class=\"stage\">\n  <div class=\"world\" data-st-decor><div class=\"key\"></div><div class=\"vig\">"
            "</div></div>\n%s\n  <div data-st=\"grain\" data-opacity=\"0.035\"></div>\n</div>\n</body>\n</html>\n"
            % (_e("%s %s" % (name, ver_disp)).strip(), CSS, body))


def build_mix(p: Dict[str, Any], seed: int = 7) -> Dict[str, Any]:
    starts: List[float] = []
    t = 0.0
    for sc in p["scenes"]:
        starts.append(round(t, 2))
        t += sc["dur"]
    names = ["intro"] + ["verse"] * max(0, len(starts) - 2) + ["outro"]
    sections = ",".join("%g:%s" % (s, n) for s, n in zip(starts, names))
    tracks: List[Dict[str, Any]] = [
        {"id": "bed", "kind": "music", "compose": {"style": "minimal-pulse", "sections": sections, "seed": seed},
         "gain_db": -2, "fade_out": 1.2}]
    for s in starts[1:]:
        tracks.append({"kind": "sfx", "synth": {"type": "swoosh-in", "intensity": 0.35, "seed": seed + int(s)},
                       "at": s, "align": "hit", "gain_db": -9})
    return {"_comment": "Generated by showtime release-video: a composed bed on the scene starts and a soft swoosh "
                        "on each cut; everything is made on this machine.",
            "sample_rate": 48000, "tracks": tracks, "master": {"lufs": -14, "true_peak": -1}}


def total_duration(p: Dict[str, Any]) -> float:
    return round(sum(sc["dur"] for sc in p["scenes"]), 2)


def write_project(out: Path, notes: Dict[str, Any], p: Dict[str, Any], *, install: str = "", url: str = "",
                  date: str = "", aspect: str = "16:9", fps: int = 30, force: bool = False) -> Dict[str, Any]:
    sizes = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
    if aspect not in sizes:
        raise ValueError("aspect must be one of %s" % ", ".join(sizes))
    out = Path(out)
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(str(out))
    (out / "audio").mkdir(parents=True, exist_ok=True)
    w, h = sizes[aspect]
    dur = total_duration(p)
    ver = p["version"]
    title = ("%s %s" % (p["name"], ver if ver.startswith(("v", "#")) or not ver else "v" + ver)).strip()
    cfg = {"title": title, "width": w, "height": h, "fps": fps, "duration": dur, "background": "#0e1013",
           "poster": 0, "audio": "audio/mix.json",
           "subtitle": "What changed, from the release notes." if p["kind"] != "pr" else "What this pull request changes.",
           "kicker": "Pull request" if p["kind"] == "pr" else "Release",
           "startTitle": False,
           "expect": {"duration": dur, "audio": True, "must_show": [p["name"]]}}
    (out / "index.html").write_text(build_page(p, notes, install=install, url=url, date=date), encoding="utf-8")
    (out / "showtime.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (out / "audio" / "mix.json").write_text(json.dumps(build_mix(p), indent=2) + "\n", encoding="utf-8")
    src = {"generator": "showtime release-video", "notes": notes, "plan": {k: v for k, v in p.items() if k != "scenes"},
           "scenes": [{"id": s["id"], "dur": s["dur"]} for s in p["scenes"]], "install": install, "url": url}
    (out / "release.json").write_text(json.dumps(src, indent=2) + "\n", encoding="utf-8")
    return {"project": str(out), "duration": dur, "scenes": len(p["scenes"]), "shown": p["shown"],
            "total": p["total"], "more": p["more"], "authors": notes.get("authors", []), "title": title}
