"""`showtime config`: show the saved settings and set the default review mode (quality or lean)."""
from __future__ import annotations

import argparse

from .common import print_json

COMMANDS = {
    "config": "Show settings; `showtime config mode lean|quality` sets the default review mode for new jobs",
}

RAW = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    from . import review_mode as rm
    p = sub.add_parser("config", help=COMMANDS["config"], formatter_class=RAW, description=(
        "Show the saved settings, or set the review mode new jobs start in.\n\n"
        "Review modes:\n"
        "  quality (default)  the full review on every finished video: looks, qa and a look after the final\n"
        "                     render, and a critic round (review-pack + a critic sub-agent) before delivery;\n"
        "                     `showtime qa` and `deliver` say \"review pending\" until that round has a verdict\n"
        "  lean               a cheaper draft pass: one look per stage, and no critic round unless the video\n"
        "                     is publish-bound or the user asks; check, qa and the looks still run\n\n"
        "Order (first wins): a job's own --mode (showtime job init|note --mode lean), the project's\n"
        "showtime.json \"review_mode\", %s=lean|quality in the environment, this saved default, quality.\n"
        "Saved in the settings file the launcher reads (~/.showtime/plugin-settings.json; SHOWTIME_SETTINGS\n"
        "moves it). In Claude Code the plugin option \"Review mode\" (/config) sets the same value." % rm.ENV),
        epilog=("examples:\n"
                "  showtime config                  # the review mode and where it comes from, and the saved settings\n"
                "  showtime config mode lean        # new jobs start lean (a draft pass)\n"
                "  showtime config mode quality     # back to the full review\n"
                "  showtime config mode --unset     # forget the saved value (quality unless SHOWTIME_MODE says otherwise)\n"
                "  SHOWTIME_MODE=lean showtime job init draft   # one shell or one run"))
    p.add_argument("key", nargs="?", choices=["mode"], help="the setting to show or change (mode)")
    p.add_argument("value", nargs="?", help="lean or quality")
    p.add_argument("--unset", action="store_true", help="remove the saved value")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_config)


def cmd_config(args: argparse.Namespace) -> int:
    from . import review_mode as rm
    from .common import ShowtimeError
    if args.value is not None or args.unset:
        if args.key != "mode":
            raise ShowtimeError("name the setting to change", hint="showtime config mode lean|quality")
        if args.unset:
            path = rm.save_setting(rm.SETTING, None)
        else:
            m = rm.normalize(args.value)
            if m is None:
                raise ShowtimeError("unknown review mode %r" % args.value, hint="use quality (the default) or lean")
            path = rm.save_setting(rm.SETTING, m)
        info = rm.info()
        if args.json:
            print_json(dict(info, saved=rm.load_settings().get(rm.SETTING)))
            return 0
        print("saved: review mode %s in %s" % (rm.load_settings().get(rm.SETTING) or "(unset)", path))
        print("new jobs: " + rm.describe(info["mode"], info["source"]))
        if info["source"] == "env":
            print("note: %s=%s in this environment wins over the saved value" % (rm.ENV, info["mode"]))
        return 0
    info = rm.info()
    saved = {k: v for k, v in rm.load_settings().items() if not str(k).startswith("_")}
    if args.json:
        print_json(dict(info, saved=saved))
        return 0
    print("review mode: " + rm.describe(info["mode"], info["source"]))
    if info["mode"] == "quality":
        print("  lean: " + rm.LEAN_SKIPS.replace("lean skips", "skips") + "  (showtime config mode lean)")
    if args.key == "mode":
        return 0
    print("settings file: %s%s" % (info["settings_file"], "" if saved else " (nothing saved)"))
    for k in sorted(saved):
        print("  %s = %s" % (k, saved[k]))
    return 0
