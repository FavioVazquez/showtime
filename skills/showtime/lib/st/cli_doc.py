"""`showtime doc ...`: bring documents in as source material (PDF import)."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .common import ShowtimeError, print_json

COMMANDS = {
    "doc": "Import a PDF as source material: text by page, images, figures with captions and credits, page renders",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    d = sub.add_parser("doc", help=COMMANDS["doc"], formatter_class=_F, description=(
        "Documents as source material for a video.\n\n"
        "  extract  a PDF -> text.md (by page), images/, figures.md (captions + credit lines), pages/ (renders)"),
        epilog="Examples:\n"
               "  showtime doc extract paper.pdf -o research/paper\n"
               "  showtime doc extract report.pdf --pages 1-4,9 --no-render\n"
               "  showtime doc extract deck.pdf --render-width 1920       # slides as full-HD stills")
    ds = d.add_subparsers(dest="doc_cmd", metavar="<subcommand>")
    p = ds.add_parser("extract", help="PDF -> text with page numbers, embedded images, figure list, page renders",
                      formatter_class=_F,
                      description=(
                          "Read a PDF locally (PDFium) and write, into the output folder:\n"
                          "  text.md      the text, one '## Page N' section per page\n"
                          "  figures.md   every captioned figure/table: page, caption, credit lines found, image file\n"
                          "  images/      embedded images (JPEGs copied as they are, others as PNG; repeats kept once)\n"
                          "  pages/       page renders as PNG (default 1600 px wide)\n"
                          "  doc.json     all of it, with metadata, outline and image positions\n\n"
                          "Default folder: <job>/sources/<name>/ when the current folder is inside a job, else "
                          "./showtime-out/<name>-pdf-<time>/. Nothing is written next to the PDF.\n"
                          "Credit lines are what the PDF prints, not a license: check the rights before an image "
                          "from a document goes into a published video. Pages without a text layer (scans) are "
                          "listed; read those from the renders."),
                      epilog="Examples:\n"
                             "  showtime doc extract paper.pdf -o research/paper\n"
                             "  showtime doc extract report.pdf --pages 3-5 --json\n"
                             "  showtime doc extract brochure.pdf --no-images --render-width 2400")
    p.add_argument("pdf", help="the PDF file")
    p.add_argument("-o", "--out", help="output folder (default: see above)")
    p.add_argument("--pages", help="pages to extract, e.g. 1-3,7 or 5- (default: all)")
    p.add_argument("--render-width", type=int, default=1600, help="page render width in px (default 1600)")
    p.add_argument("--no-render", action="store_true", help="skip the page renders")
    p.add_argument("--no-images", action="store_true", help="skip embedded images")
    p.add_argument("--min-image", type=int, default=32,
                   help="skip embedded images smaller than this many px on a side (default 32)")
    p.add_argument("--password", help="password of an encrypted PDF (used locally only)")
    p.add_argument("--json", action="store_true", help="print doc.json (without per-page text) on stdout")
    p.set_defaults(func=cmd_extract)


def _default_out(pdf: Path) -> Path:
    from .common import output_dir, slugify
    from .job import ledger
    job = ledger.enclosing_job(Path.cwd())
    if job is not None:
        base = job / "sources" / slugify(pdf.stem, default="document")
        k, cand = 2, base
        while cand.exists():
            cand = base.with_name("%s-%d" % (base.name, k))
            k += 1
        return cand
    return output_dir("%s-pdf" % pdf.stem)


def cmd_extract(args: argparse.Namespace) -> int:
    from . import pdfdoc
    pdf = Path(args.pdf).expanduser()
    if not pdf.is_file():
        raise ShowtimeError("file not found: %s" % pdf)
    if args.render_width < 64 or args.render_width > 10000:
        raise ShowtimeError("--render-width must be between 64 and 10000 px")
    out: Optional[Path] = Path(args.out).expanduser() if args.out else None
    if out is None:
        out = _default_out(pdf)
    if out.resolve() == pdf.parent.resolve():
        raise ShowtimeError("the output folder is the PDF's own folder", hint="pass -o <new folder>")
    rep = pdfdoc.extract(pdf, out, pages=args.pages, render=not args.no_render, render_width=args.render_width,
                         images=not args.no_images, password=args.password, min_image=args.min_image)
    if args.json:
        slim = dict(rep, page_info=[{k: v for k, v in p.items() if k != "text"} for p in rep["page_info"]])
        print_json(slim)
    else:
        print(rep["out_dir"])
    return 0
