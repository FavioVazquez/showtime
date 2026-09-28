"""`showtime assets ...` (fonts, icons, emoji, stock media, cutouts, credits) and `showtime autozoom`.

Website capture and app demos are Node scripts routed by the launcher:
`showtime site ...` -> scripts/site.mjs, `showtime demo ...` -> scripts/demo.mjs.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from .common import ShowtimeError, log, print_json

COMMANDS = {
    "assets": "Fonts, icons, emoji, CC0/public-domain photos and video, cutouts, credits",
    "autozoom": "Smooth auto zoom + cursor + keycaps for demo recordings (same as footage autozoom)",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    a = sub.add_parser("assets", help=COMMANDS["assets"], formatter_class=_F, description=(
        "Key-free, license-gated assets. Everything is cached in ~/.showtime/assets with a\n"
        ".license.json sidecar; CC-BY material is only used with --allow-attribution and then\n"
        "credited automatically (CREDITS.txt).\n\n"
        "  font     install a Google/open font family as TTF + WOFF2 (+ font.css)\n"
        "  fonts    list installed families, or --search the catalog\n"
        "  icon     Lucide / Phosphor / Tabler / Heroicons / simple-icons -> recoloured SVG (or PNG)\n"
        "  icons    search icon names and tags\n"
        "  emoji    Noto / Fluent emoji -> SVG or PNG (no attribution needed)\n"
        "  emojis   search emoji by name or keyword\n"
        "  media    search + fetch CC0 / public-domain images and video (Openverse, Commons, NASA, museums)\n"
        "  cutout   remove the background of a still (macOS Vision, else rembg)\n"
        "  sheet    numbered contact sheet of a folder of photos/screenshots/clips (EXIF rotation applied)\n"
        "  credits  write CREDITS.txt for a project from its .license.json sidecars"),
        epilog="examples:\n"
               "  showtime assets font \"Space Grotesk\" --weights 400,700\n"
               "  showtime assets icon lucide rocket --color \"#a78bfa\" --size 128\n"
               "  showtime assets emoji rocket --set fluent-3d\n"
               "  showtime assets media search \"mountain sunrise\" --preview sheet.jpg\n"
               "  showtime assets media fetch openverse:7bc707f3-... --project ./my-video\n"
               "  showtime assets cutout product.jpg --crop\n"
               "  showtime assets sheet ./photos --sort date")
    s = a.add_subparsers(dest="assets_cmd", metavar="<subcommand>")

    p = s.add_parser("font", help="install a font family (TTF for captions/drawtext, WOFF2 + font.css for pages)",
                     formatter_class=_F, description=(
                         "Install a font family from the Fontsource catalog (Google Fonts and other open fonts) into\n"
                         "~/.showtime/assets/fonts/<id>/ with its license. Only OFL/Apache/MIT/UFL by default."),
                     epilog="examples:\n  showtime assets font inter\n  showtime assets font \"Bricolage Grotesque\" --weights 400,800\n"
                            "  showtime assets font inter --path --weight 700     # print the TTF path\n"
                            "  showtime assets font anton --copy-to ./my-video/fonts")
    p.add_argument("family", help="family name or id, e.g. \"Space Grotesk\" or space-grotesk")
    p.add_argument("--weights", default="400,700", help="comma list or 'all' (default 400,700; nearest available is used)")
    p.add_argument("--styles", default="normal", help="normal,italic (default normal)")
    p.add_argument("--subsets", help="e.g. latin,latin-ext (default: the family's default subset)")
    p.add_argument("--formats", default="ttf,woff2", help="ttf,woff2,woff (default ttf,woff2)")
    p.add_argument("--no-variable", action="store_true", help="skip the variable WOFF2")
    p.add_argument("--path", action="store_true", help="print the path of one TTF (installs it if needed)")
    p.add_argument("--weight", type=int, default=400, help="weight for --path (default 400)")
    p.add_argument("--style", default="normal", help="style for --path (default normal)")
    p.add_argument("--copy-to", help="also copy the family folder into this directory (e.g. a project)")
    p.add_argument("--allow-license", action="store_true", help="install even if the license is not OFL/Apache/MIT/UFL")
    p.add_argument("--force", action="store_true", help="re-download files")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_font)

    p = s.add_parser("fonts", help="list installed fonts, or search the catalog",
                     epilog="examples:\n  showtime assets fonts\n  showtime assets fonts --search grotesk\n"
                            "  showtime assets fonts --search \"\" --category monospace", formatter_class=_F)
    p.add_argument("--search", help="search the catalog by name")
    p.add_argument("--category", help="sans-serif, serif, display, handwriting, monospace")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fonts)

    p = s.add_parser("icon", help="get an icon as SVG (or PNG) with colour and size", formatter_class=_F,
                     description="Sets: lucide (ISC), phosphor (MIT; --variant regular|thin|light|bold|fill|duotone),\n"
                                 "tabler (MIT; outline|filled), heroicons (MIT; outline|solid|mini|micro),\n"
                                 "simple-icons (CC0 brand logos; --color brand = the brand's own colour).",
                     epilog="examples:\n  showtime assets icon lucide rocket --color \"#a78bfa\" --size 128\n"
                            "  showtime assets icon phosphor rocket --variant duotone -o scene/rocket.svg\n"
                            "  showtime assets icon simple-icons github --color brand --png --size 512")
    p.add_argument("set", help="lucide | phosphor | tabler | heroicons | simple-icons")
    p.add_argument("name", help="icon name, e.g. rocket, arrow-right, github")
    p.add_argument("--variant", "--weight", dest="variant", help="set-specific variant (see above)")
    p.add_argument("--color", "-c", help="#rrggbb, CSS colour name, or 'brand' (simple-icons)")
    p.add_argument("--size", "-s", type=int, default=96, help="width/height in px (default 96)")
    p.add_argument("--stroke", type=float, help="stroke width for stroke icons (lucide/tabler/heroicons outline)")
    p.add_argument("--png", action="store_true", help="also write a PNG (rendered with headless Chrome)")
    p.add_argument("-o", "--output", help="output .svg or .png path (default: ~/.showtime/assets/icons/<set>/)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_icon)

    p = s.add_parser("icons", help="search icon names/tags across sets", formatter_class=_F,
                     epilog="examples:\n  showtime assets icons rocket\n  showtime assets icons \"arrow right\" --set lucide --limit 10")
    p.add_argument("query")
    p.add_argument("--set", help="limit to one set")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_icons)

    p = s.add_parser("emoji", help="get an emoji image (Noto / Fluent; SVG or PNG)", formatter_class=_F,
                     description="Sets: noto (default, SVG/PNG), noto-3d (PNG), fluent (SVG), fluent-flat (SVG),\n"
                                 "fluent-3d (PNG). twemoji (CC-BY) needs --allow-attribution; openmoji (CC-BY-SA)\n"
                                 "needs --allow-share-alike. Input: the emoji, its name, a keyword or code points.",
                     epilog="examples:\n  showtime assets emoji 🚀\n  showtime assets emoji rocket --set fluent-3d --size 256\n"
                            "  showtime assets emoji \"thumbs up\" --set fluent --skin medium --format png\n"
                            "  showtime assets emoji 1f389 -o scene/party.svg")
    p.add_argument("emoji", help="🚀, 'rocket', 'red heart', or 1f680 / U+1F680")
    p.add_argument("--set", dest="set_name", default="noto", help="noto | noto-3d | fluent | fluent-flat | fluent-3d | twemoji | openmoji")
    p.add_argument("--format", choices=["svg", "png"], help="default: the set's native format")
    p.add_argument("--size", type=int, default=512, help="PNG size (default 512)")
    p.add_argument("--skin", help="light | medium-light | medium | medium-dark | dark")
    p.add_argument("-o", "--output", help="output file or folder")
    p.add_argument("--project", help="project folder (for CREDITS.txt when attribution is required)")
    p.add_argument("--allow-attribution", action="store_true", help="allow CC-BY sets (credit line written)")
    p.add_argument("--allow-share-alike", action="store_true", help="allow CC-BY-SA sets")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_emoji)

    p = s.add_parser("emojis", help="search emoji by name or keyword", formatter_class=_F,
                     epilog="examples:\n  showtime assets emojis party\n  showtime assets emojis \"thumbs\" --limit 5")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_emojis)

    m = s.add_parser("media", help="search/fetch CC0 and public-domain photos and video", formatter_class=_F,
                     description="Sources (no API keys): openverse, commons, nasa, cma (Cleveland), met; aic is opt-in.\n"
                                 "Default license filter: CC0 + public domain. --allow-attribution adds CC BY\n"
                                 "(a CREDITS.txt line is written on fetch); --allow-share-alike adds CC BY-SA.",
                     epilog="examples:\n  showtime assets media search \"mountain sunrise\" --preview sheet.jpg\n"
                            "  showtime assets media search \"ocean waves\" --type video\n"
                            "  showtime assets media fetch commons:92787576 --project ./my-video\n"
                            "  showtime assets media fetch nasa:iss065e018683 -o plates/earth.jpg")
    ms = m.add_subparsers(dest="media_cmd", metavar="<search|fetch>")
    q = ms.add_parser("search", help="search several sources in parallel")
    q.add_argument("query")
    q.add_argument("--type", choices=["image", "video"], default="image")
    q.add_argument("--source", help="comma list (default: all image sources, or commons,nasa for video)")
    q.add_argument("--license", choices=["free", "attribution", "share-alike"], default="free",
                   help="free = CC0/PD only (default); attribution adds CC BY; share-alike adds CC BY-SA")
    q.add_argument("--allow-attribution", action="store_true", help="same as --license attribution")
    q.add_argument("--orientation", choices=["landscape", "portrait", "square"])
    q.add_argument("--limit", "-n", type=int, default=12)
    q.add_argument("--details", action="store_true",
                   help="read size / length / file size of every NASA result (automatic for video and with filters)")
    q.add_argument("--min-size", type=int, metavar="PX", help="shortest side of the original at least PX (e.g. 1920)")
    q.add_argument("--max-duration", type=float, metavar="S", help="videos at most S seconds long")
    q.add_argument("--max-mb", type=float, metavar="MB", help="files at most MB (original rendition)")
    q.add_argument("--preview", help="write a numbered contact sheet of the results (JPEG)")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_media_search)
    q = ms.add_parser("fetch", help="download one result by id, or any URL with --license (sidecar + credits)",
                      formatter_class=_F,
                      epilog="examples:\n  showtime assets media fetch commons:92787576 --project ./my-video\n"
                             "  showtime assets media fetch commons:<pageid> --max-size 1920   (Commons' 1920 px rendition)\n"
                             "  showtime assets media fetch https://pubs.usgs.gov/.../fig3.jpg --license public-domain \\\n"
                             "      --source-page https://pubs.usgs.gov/... --author \"USGS\" --project ./my-video")
    q.add_argument("id", help="id from search (openverse:<uuid>, commons:<pageid>, nasa:<id>, cma:<id>, met:<id>), "
                              "or an http(s) URL together with --license")
    q.add_argument("-o", "--output", help="output file or folder")
    q.add_argument("--project", help="copy into <project>/assets/media and credit there")
    q.add_argument("--quality", choices=["small", "medium", "large", "orig"], default="large",
                   help="rendition for NASA items (default large); orig also means the original for Commons")
    q.add_argument("--max-size", type=int, metavar="PX",
                   help="Commons images: the widest rendition to download, a standard thumbnail step (250, 330, "
                        "500, 960, 1280, 1920, 3840; default 3840; 0 = the original). Thumbnails come from a tier "
                        "that is not rate limited like the originals")
    q.add_argument("--license", help="with a URL: the license the source page states (e.g. public-domain, CC0-1.0, "
                                     "CC-BY-4.0), written to the sidecar")
    q.add_argument("--source-page", metavar="URL", help="with a URL: the page that states the license (the credit's link)")
    q.add_argument("--title", help="with a URL: the title for the credit (default: the file name)")
    q.add_argument("--author", help="with a URL: the author or agency for the credit")
    q.add_argument("--max-mb", type=int, default=300, help="size limit (default 300 MB)")
    q.add_argument("--allow-attribution", action="store_true")
    q.add_argument("--allow-share-alike", action="store_true")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_media_fetch)
    m.set_defaults(func=lambda args: _group_help(m))

    p = s.add_parser("cutout", help="remove the background of an image (RGBA PNG)", formatter_class=_F,
                     description="Engines: vision (macOS 14+, built in, fast) and rembg (every OS; installed into the\n"
                                 "showtime venv on first use, models downloaded once to ~/.showtime/models/rembg).",
                     epilog="examples:\n  showtime assets cutout product.jpg\n  showtime assets cutout photo.jpg --crop --pad 24 --mask mask.png\n"
                            "  showtime assets cutout teapot.jpg --crop --max-size 1800   (a smaller PNG for a 1080p page)\n"
                            "  showtime assets cutout art.jpg --engine rembg --model birefnet-general-lite")
    p.add_argument("image")
    p.add_argument("-o", "--output", help="output PNG (default <image>.cutout.png)")
    p.add_argument("--engine", choices=["auto", "vision", "rembg"], default="auto")
    p.add_argument("--model", default="isnet-general-use",
                   help="rembg model: isnet-general-use (default), u2netp (small), u2net, silueta, birefnet-general-lite")
    p.add_argument("--mask", help="also write the alpha mask as a grayscale PNG")
    p.add_argument("--crop", action="store_true", help="crop to the subject")
    p.add_argument("--pad", type=int, default=0, help="padding around the crop in px")
    p.add_argument("--max-size", type=int, default=None, metavar="PX",
                   help="longest side of the PNG in px (default 2048: enough for a 1080p or 1440p page, about a "
                        "quarter of a full-res 4K cut-out; 0 keeps the full resolution)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cutout)

    p = s.add_parser("sheet", help="numbered contact sheet of a folder of photos/screenshots/clips", formatter_class=_F,
                     description=(
                         "One numbered grid image of every photo, screenshot or clip in a folder (paged past --per-page),\n"
                         "so a whole folder can be judged in one look (e.g. before a slideshow). EXIF rotation is applied\n"
                         "(phone photos show upright; sizes are as displayed). HEIC and clips are read with ffmpeg; a clip\n"
                         "shows one frame and its duration. Badges: the number, low-res (long side < 1280 px), ~N (looks\n"
                         "like item N: a burst/duplicate), clip length. Also writes <sheet>.json with every item (size,\n"
                         "orientation, date taken, flags).\n"
                         "Output: -o FILE (never overwritten without --overwrite; more pages -> FILE-p2.jpg ...), default\n"
                         "./showtime-out/<folder>-sheet-<time>/sheet.jpg. Prints the list, then the sheet path(s)."),
                     epilog="examples:\n  showtime assets sheet ./photos\n"
                            "  showtime assets sheet ./photos --sort date --cols 6 -o work/photos-sheet.jpg\n"
                            "  showtime assets sheet \"shots/*.png\" --labels name\n"
                            "  showtime assets sheet ./trip -r --per-page 48 --json")
    p.add_argument("inputs", nargs="+", metavar="DIR|FILE|GLOB", help="folders, files or quoted glob patterns (** recurses)")
    p.add_argument("-o", "--output", help="sheet image (.jpg/.png); default ./showtime-out/<folder>-sheet-<time>/sheet.jpg")
    p.add_argument("--cols", "-c", type=int, help="columns (default: about square, at most 8)")
    p.add_argument("--cell", type=int, default=300, help="cell size in px (default 300)")
    p.add_argument("--labels", nargs="?", const="full", default="full", choices=["none", "number", "name", "full"],
                   help="full = number + file name + size/orientation/date (default); name; number; none")
    p.add_argument("--no-labels", dest="labels", action="store_const", const="none", help="same as --labels none")
    p.add_argument("--sort", choices=["name", "date", "none"], default="name",
                   help="name (natural order, default), date (EXIF date taken, else file time), none (as given)")
    p.add_argument("--per-page", type=int, default=36, help="items per sheet image (default 36)")
    p.add_argument("-r", "--recursive", action="store_true", help="include sub-folders")
    p.add_argument("--title", help="title line on the sheet (default: folder name and count)")
    p.add_argument("--overwrite", action="store_true", help="replace an existing -o file")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.set_defaults(func=cmd_sheet)

    p = s.add_parser("credits", help="write CREDITS.txt from the .license.json sidecars in a folder", formatter_class=_F,
                     epilog="examples:\n  showtime assets credits ./my-video\n  showtime assets credits ./my-video --all -o credits-full.txt")
    p.add_argument("folder", help="project folder")
    p.add_argument("--all", action="store_true", help="also list assets that need no attribution")
    p.add_argument("-o", "--output", help="output file (default <folder>/CREDITS.txt)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_credits)
    a.set_defaults(func=lambda args: _group_help(a))

    try:
        from .footage import autozoom as _az
    except Exception as e:  # noqa: BLE001 - keep `assets` usable even if footage fails to import
        z = sub.add_parser("autozoom", help=COMMANDS["autozoom"] + " [unavailable]")
        z.add_argument("rest", nargs=argparse.REMAINDER)
        z.set_defaults(func=lambda args, _e=e: (_ for _ in ()).throw(
            ShowtimeError("autozoom is unavailable (%s)" % _e, hint="run `showtime doctor`")))
        return
    z = sub.add_parser("autozoom", help=COMMANDS["autozoom"], formatter_class=_F,
                       description=_az.__doc__.split("\n\n")[0] + "\n\n" + _az.DESCRIPTION, epilog=_az.EXAMPLES)
    _az.add_arguments(z)
    z.set_defaults(func=cmd_autozoom)


def _group_help(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


# ------------------------------------------------------------------ fonts

def _split(s):
    return [x.strip() for x in str(s).split(",") if x.strip()] if s else None


def cmd_font(args) -> int:
    from .assets import fonts
    if args.path:
        p = fonts.resolve(args.family, args.weight, args.style, "ttf")
        if args.json:
            print_json({"path": str(p), "family": args.family, "weight": args.weight, "style": args.style})
        else:
            print(p)
        return 0
    m = fonts.install(args.family, weights=_split(args.weights), styles=_split(args.styles), subsets=_split(args.subsets),
                      formats=tuple(_split(args.formats) or ["ttf", "woff2"]), variable=not args.no_variable,
                      allow_license=args.allow_license, force=args.force)
    copied = None
    link = None
    if args.copy_to:
        copied = fonts.copy_to(args.family, Path(args.copy_to))
        link = _font_link(Path(args.copy_to), copied, m["family"])
    if args.json:
        m = dict(m)
        m["copied_to"] = str(copied) if copied else None
        m["link"] = link
        print_json(m)
    else:
        log("%s %s (%s): weights %s, %d file(s) downloaded in %.1fs" % (
            m["family"], m["version"], m["license"], ",".join(str(w) for w in m["weights"]), m["fetched"], m["seconds"]))
        print(Path(m["dir"]) / "font.css")
        for f in m["files"]:
            if f["format"] == "ttf":
                print(Path(m["dir"]) / f["file"])
        if copied:
            print(copied)
            log("use it in the page: %s" % link["html"])
            log("  and in CSS: %s" % link["css"])
    return 0


def _font_link(dest: Path, copied: Path, family: str) -> dict:
    """The <link> line for a family copied into a project (href relative to the project root,
    taken as the folder above --copy-to: <project>/fonts -> "fonts/<id>/font.css")."""
    import os
    root = dest.resolve().parent
    try:
        href = Path(os.path.relpath(copied.resolve() / "font.css", root)).as_posix()
    except ValueError:  # another drive on Windows
        href = (copied / "font.css").as_posix()
    fam = family.replace("'", "\\'")
    return {"href": href, "html": '<link rel="stylesheet" href="%s">' % href,
            "css": ":root { --font-display: '%s', sans-serif; --font-body: '%s', sans-serif; }" % (fam, fam)}


def cmd_fonts(args) -> int:
    from .assets import fonts
    if args.search is not None or args.category:
        res = fonts.search(args.search or "", limit=args.limit, category=args.category)
        if args.json:
            print_json(res)
        else:
            for f in res:
                print("%-28s %-12s %-8s weights %s%s" % (f["family"], f.get("category", ""), f.get("license", ""),
                                                          ",".join(str(w) for w in f.get("weights", [])),
                                                          "  variable" if f.get("variable") else ""))
        return 0
    res = fonts.list_installed()
    if args.json:
        print_json(res)
    elif not res:
        log("no fonts installed yet: showtime assets font inter")
    else:
        for f in res:
            print("%-28s %-8s weights %-20s %s" % (f["family"], f["license"], ",".join(str(w) for w in f["weights"] or []), f["css"]))
    return 0


# ------------------------------------------------------------------ icons / emoji

def cmd_icon(args) -> int:
    from .assets import icons
    res = icons.get(args.set, args.name, variant=args.variant, color=args.color, size=args.size,
                    stroke_width=args.stroke, out=Path(args.output) if args.output else None, png=args.png)
    if args.json:
        print_json(res)
    else:
        print(res.get("png") if args.output and str(args.output).lower().endswith(".png") else res["svg"])
        if res.get("png") and not (args.output and str(args.output).lower().endswith(".png")):
            print(res["png"])
        if res.get("note"):
            log(res["note"])
    return 0


def cmd_icons(args) -> int:
    from .assets import icons
    res = icons.search(args.query, args.set, limit=args.limit)
    if args.json:
        print_json(res)
    elif not res:
        log("no icons match %r" % args.query)
        return 1
    else:
        for r in res:
            print("%-14s %-32s (%s)" % (r["set"], r["name"], r["match"]))
    return 0


def cmd_emoji(args) -> int:
    from .assets import emoji
    res = emoji.get(args.emoji, set_name=args.set_name, fmt=args.format, size=args.size, skin=args.skin,
                    out=Path(args.output) if args.output else None, allow_attribution=args.allow_attribution,
                    allow_share_alike=args.allow_share_alike, project=Path(args.project) if args.project else None)
    if args.json:
        print_json(res)
    else:
        print(res["path"])
        if res.get("credit"):
            log("credit required: %s" % res["credit"])
    return 0


def cmd_emojis(args) -> int:
    from .assets import emoji
    res = emoji.search(args.query, limit=args.limit)
    if args.json:
        print_json(res)
    elif not res:
        log("no emoji match %r" % args.query)
        return 1
    else:
        for r in res:
            print("%s  %-40s %s" % (r["emoji"], r["name"], r["hex"]))
    return 0


# ------------------------------------------------------------------ media

def cmd_media_search(args) -> int:
    from .assets import media
    aa = args.allow_attribution or args.license in ("attribution", "share-alike")
    res = media.search(args.query, kind=args.type, sources=_split(args.source), limit=args.limit,
                       allow_attribution=aa, allow_share_alike=args.license == "share-alike",
                       orientation=args.orientation, details=True if args.details else None,
                       min_size=args.min_size, max_duration=args.max_duration, max_mb=args.max_mb)
    sheet = None
    if args.preview and res["results"]:
        sheet = media.preview_sheet(res["results"], Path(args.preview))
        res["preview"] = str(sheet) if sheet else None
    if args.json:
        print_json(res)
        return 0 if res["results"] else 1
    for src, err in res["errors"].items():
        log("%s: %s" % (src, err))
    if not res["results"]:
        log("no %s results for %r with license %s" % (args.type, args.query, args.license))
        return 1
    for r in res["results"]:
        dims = "%sx%s" % (r["width"], r["height"]) if r.get("width") else "?"
        extra = []
        if r.get("duration"):
            extra.append("%.0fs" % float(r["duration"]))
        if r.get("bytes"):
            extra.append("%.0f MB" % (r["bytes"] / 1e6))
        # the full id on its own line: it is what `fetch` needs (never truncated)
        print("%2d  %s" % (r["n"], r["id"]))
        print("    %-26s %-10s %-14s %s" % ((r["license"] or "")[:26], dims, " ".join(extra), (r["title"] or "")[:60]))
        if r.get("license_notice"):
            print("    notice: %s" % r["license_notice"][:140])
    if res.get("hidden_third_party"):
        log("%d NASA result(s) were left out: their description credits third-party processing or copyright "
            "(e.g. citizen-processed JunoCam images); --license attribution shows the CC BY ones" % res["hidden_third_party"])
    if sheet:
        print(sheet)
    log("fetch one with: showtime assets media fetch <id> [--project DIR]")
    return 0


def cmd_media_fetch(args) -> int:
    from .assets import media
    out = Path(args.output) if args.output else None
    project = Path(args.project) if args.project else None
    if re.match(r"(?i)^https?://", args.id):
        res = media.fetch_url(args.id, license=args.license, out=out, project=project, source_page=args.source_page,
                              title=args.title, author=args.author, allow_attribution=args.allow_attribution,
                              allow_share_alike=args.allow_share_alike, max_mb=args.max_mb)
    else:
        extra = [n for n, v in (("--license", args.license), ("--source-page", args.source_page),
                                ("--title", args.title), ("--author", args.author)) if v]
        if extra:
            raise ShowtimeError("%s only apply to a URL" % "/".join(extra),
                                why="a search id's license is read from its source",
                                hint="showtime assets media fetch <https://...> --license ... --source-page ...")
        res = media.fetch(args.id, out=out, project=project, allow_attribution=args.allow_attribution,
                          allow_share_alike=args.allow_share_alike, quality=args.quality, max_mb=args.max_mb,
                          max_size=args.max_size)
    if args.json:
        print_json(res)
    else:
        print(res["path"])
        if res.get("attribution_required"):
            log("credit required (added to %s): %s" % (res.get("credits_file"), res["credit"]))
        if res.get("note"):
            log(res["note"])
        for n in res.get("notes") or []:
            log(n)
    return 0


def cmd_cutout(args) -> int:
    from .assets import cutout
    ms = cutout.DEFAULT_MAX_SIZE if args.max_size is None else args.max_size
    res = cutout.cutout(Path(args.image), out=Path(args.output) if args.output else None, engine=args.engine,
                        model=args.model, mask=Path(args.mask) if args.mask else None, crop=args.crop, pad=args.pad,
                        max_size=ms or None)
    if args.json:
        print_json(res)
    else:
        log("%s: subject covers %.0f%% of the image (%s, %.1fs)" % (res["engine"], 100 * res["coverage"], res["engine"], res["seconds"]))
        if res.get("resized_from"):
            log("scaled from %dx%d to %dx%d (--max-size %d; --max-size 0 keeps the full resolution)" % (
                res["resized_from"][0], res["resized_from"][1], res["width"], res["height"], ms))
        print(res["path"])
    return 0


def cmd_sheet(args) -> int:
    from .assets import sheet
    rep = sheet.build(args.inputs, out=Path(args.output) if args.output else None, cols=args.cols, cell=args.cell,
                      labels=args.labels, per_page=args.per_page, sort=args.sort, recursive=args.recursive,
                      overwrite=args.overwrite, title=args.title)
    if args.json:
        print_json(rep)
        return 0
    c = rep["counts"]
    parts = ["%d landscape" % c["landscape"], "%d portrait" % c["portrait"], "%d square" % c["square"]]
    extra = []
    if c["clips"]:
        extra.append("%d clip(s)" % c["clips"])
    if c["rotated_by_exif"]:
        extra.append("%d rotated by EXIF" % c["rotated_by_exif"])
    if c["low_res"]:
        extra.append("%d low-res" % c["low_res"])
    if c["similar"]:
        extra.append("%d near-duplicate(s)" % c["similar"])
    log("%d item(s): %s%s" % (c["items"], ", ".join(parts), ("; " + ", ".join(extra)) if extra else ""))
    for it in rep["items"]:
        size = "%dx%d" % tuple(it["size"]) if it.get("size") else "?"
        flags = []
        if it.get("duration") is not None:
            flags.append("clip %.1fs" % it["duration"])
        if it.get("rotated") and it["kind"] == "image":
            flags.append("exif-rotated")
        if it.get("low_res"):
            flags.append("low-res")
        if it.get("similar_to"):
            flags.append("like #%d" % it["similar_to"])
        if it.get("error"):
            flags.append(it["error"])
        log("  %3d  %-34s %-10s %-9s %-19s %s" % (it["n"], it["name"][:34], size, it.get("orientation") or "",
                                                 it.get("date") or "", " ".join(flags)))
    for w in rep["warnings"]:
        log("warning: %s" % w)
    print(rep["json"])
    for f in rep["sheets"]:
        print(f)
    return 0


def cmd_credits(args) -> int:
    from .assets import licenses
    folder = Path(args.folder)
    if not folder.exists():
        raise ShowtimeError("folder not found: %s" % folder)
    items = licenses.collect(folder, only_required=not args.all)
    out = licenses.write_credits(folder, out=Path(args.output) if args.output else None, include_free=args.all)
    if args.json:
        print_json({"credits_file": str(out) if out else None, "items": [
            {k: i.get(k) for k in ("file", "title", "author", "license", "credit", "sidecar")} for i in items]})
    elif out:
        log("%d credit line(s)" % len(items))
        print(out)
    else:
        log("nothing in %s needs attribution (no CREDITS.txt written)" % folder)
    if args.all and not args.json:
        log("--all lists files with a .license.json sidecar; fonts, the voice and a composed score have none: add "
            "their lines by hand (see references/assets.md, credits)")
    return 0


def cmd_autozoom(args) -> int:
    from .footage import autozoom
    return autozoom.run_cli(args)
