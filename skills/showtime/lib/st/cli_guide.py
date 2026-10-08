"""`showtime guide`: read a reference's Essentials, one section, or find a word across every reference."""
from __future__ import annotations

import argparse
import sys

from .common import ShowtimeError

COMMANDS = {
    "guide": "Read the references by the piece: a topic's Essentials, one section, or --find a word in all of them",
}

RAW = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("guide", help=COMMANDS["guide"], formatter_class=RAW, description=(
        "Print what the current step needs from the references instead of whole files.\n\n"
        "  showtime guide <topic>              the topic's Essentials (the rules for that step) and its sections\n"
        "  showtime guide <topic> <section>    one section: its number (3 or §3), its name or part of it, or a\n"
        "                                      sub-heading such as a component (count-up) or a command\n"
        "  showtime guide --find <words>       every line that mentions all the words, with topic and section\n"
        "  showtime guide <topic> --find <words>   the same in one reference (the topic goes before --find)\n"
        "  showtime guide                      the list of topics\n\n"
        "A topic is a file under references/ without .md (components, workflows/launch-video, crew/critic);\n"
        "a unique part of the name works too (launch, data-story, manim)."),
        epilog=("examples:\n"
                "  showtime guide launch                  # the launch workflow's Essentials and sections\n"
                "  showtime guide components count-up     # one component's options\n"
                "  showtime guide render 'showtime check' # one command's section\n"
                "  showtime guide audio 3 5               # two sections\n"
                "  showtime guide --find typewriter at    # where a detail lives (every word after --find)\n"
                "  showtime guide audio --find loudnorm   # in one reference\n"
                "  showtime guide stage-api --all         # the whole file"))
    p.add_argument("topic", nargs="?", help="a reference name (components, launch, workflows/data-story ...)")
    p.add_argument("section", nargs="*", help="section numbers or names (several print one after another)")
    p.add_argument("--find", metavar="WORD", nargs="+",
                   help="lines that contain every word (in the topic, or in all); every word after --find is searched, "
                        "so put a topic before it")
    p.add_argument("--all", action="store_true", help="print the whole file")
    p.set_defaults(func=cmd_guide)


def _out(text: str) -> None:
    try:
        sys.stdout.write(text.rstrip("\n") + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(text.encode("ascii", "replace").decode() + "\n")


def _topic(refs, query: str) -> str:
    from . import guide
    name, cands = guide.resolve(query, refs)
    if name:
        return name
    if cands:
        raise ShowtimeError("'%s' matches several references: %s" % (query, ", ".join(cands[:12])),
                            hint="name one of them, e.g. `showtime guide %s`" % cands[0])
    raise ShowtimeError("no reference called '%s'" % query,
                        hint="`showtime guide` lists them; `showtime guide --find %s` searches inside them" % query)


def cmd_guide(args: argparse.Namespace) -> int:
    from . import guide
    refs = guide.references_dir()
    if not refs.is_dir():
        raise ShowtimeError("the references folder is missing: %s" % refs, hint="reinstall the skill")
    all_topics = guide.topics(refs)

    if args.find:
        words = " ".join(args.find) if isinstance(args.find, list) else str(args.find)
        names = [_topic(refs, args.topic)] if args.topic else list(all_topics)
        docs = [(n, guide.Doc(all_topics[n], all_topics[n].read_text(encoding="utf-8"))) for n in names]
        hits, total = guide.find_lines(docs, words)
        if not hits:
            _out("no line mentions all of: %s%s" % (words, " in " + names[0] if args.topic else ""))
            return 1
        more = ""
        if total > len(hits):
            more = "\n... %d more; add a word or a topic (showtime guide <topic> --find ...)" % (total - len(hits))
        _out("\n".join(hits) + more + "\nprint one: showtime guide <topic> <section or sub-heading>")
        return 0

    if not args.topic:
        lines = ["references (showtime guide <topic> for its Essentials and sections):"]
        for n, p in all_topics.items():
            doc = guide.Doc(p, p.read_text(encoding="utf-8"))
            lines.append("  %-30s %4d lines  %s" % (n, len(doc.lines), doc.title[:70]))
        _out("\n".join(lines))
        return 0

    name = _topic(refs, args.topic)
    path = all_topics[name]
    doc = guide.Doc(path, path.read_text(encoding="utf-8"))
    rel = "references/%s.md" % name
    if args.all:
        _out("\n".join(doc.lines))
        return 0
    if not args.section:
        _out(guide.overview(name, doc, rel))
        return 0
    parts, missing = [], []
    for sel in args.section:
        if "-" in sel and sel.replace("-", "").isdigit() and sel.count("-") == 1:
            a, b = (int(x) for x in sel.split("-"))
            if 1 <= a <= b:
                parts.append("%s lines %d-%d\n\n%s" % (rel, a, min(b, len(doc.lines)), doc.text(a, b)))
                continue
        sec, others = guide.find_section(doc, sel)
        if sec is None:
            missing.append(sel)
            continue
        parts.append(guide.section_text(name, doc, sec, rel, others))
    if parts:
        _out("\n\n".join(parts))
    if missing:
        listing = "; ".join(guide._short(guide._plain(s.title), 36) for s in doc.body_sections())
        raise ShowtimeError("%s has no section '%s'" % (rel, "', '".join(missing)),
                            why="its sections: %s" % listing,
                            hint="`showtime guide %s --find %s` searches its lines" % (name, missing[0]))
    return 0
