"""`showtime release-video`: release notes or a PR description -> a video project, no agent needed."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .common import ShowtimeError, print_json

COMMANDS = {
    "release-video": "Release notes, a CHANGELOG section or a PR description -> a ready-to-render video project",
    "pr-video": "A pull request -> a short video under 10 MB to drag into its description, in one command",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("release-video", help=COMMANDS["release-video"], formatter_class=_F, description=(
        "Write a video project from release notes, with no agent in the loop (CI, the GitHub Action).\n\n"
        "Reads Markdown release notes (a GitHub release body, a CHANGELOG section with --changelog-version,\n"
        "or a PR description with --kind pr) and writes <out>/index.html, showtime.json and audio/mix.json:\n"
        "a hook card (name, version, date), one scene per group of changes (the notes' own headings and lines,\n"
        "verbatim; long lines are cut at a word with an ellipsis), and an end card (install command, URL and\n"
        "the @people the notes credit). Internal sections (dependencies, CI, docs, chores) are counted, not\n"
        "shown. Every word on screen comes from the notes or from a flag, so nothing is invented. The music\n"
        "is composed on this machine. Then: `showtime check <out>`, `showtime render <out>`, `showtime qa`.\n\n"
        "For a film with an angle (a demo of the new feature, a real diff) follow the changelog workflow\n"
        "with an agent instead; this command is the unattended fallback."),
        epilog=("Examples:\n"
                "  showtime release-video notes.md -o release-project --name acme --version 2.3.0\n"
                "  showtime release-video CHANGELOG.md --changelog-version 2.3.0 --name acme -o rv\n"
                "  gh release view v2.3.0 --json body -q .body | showtime release-video - --name acme -o rv\n"
                "  showtime release-video pr.md --kind pr --name acme --version '#482' -o pr-video\n"
                "  showtime release-video notes.md -o rv --install 'pip install -U acme' --url https://acme.dev"))
    p.add_argument("notes", help="Markdown file with the notes, or - for stdin")
    p.add_argument("-o", "--out", required=True, help="project folder to write (created; must be empty unless --force)")
    p.add_argument("--name", help="product or repository name (default: the notes' title, else the folder name)")
    p.add_argument("--version", dest="rel_version", metavar="VERSION",
                   help="version shown (default: found in the notes' title)")
    p.add_argument("--changelog-version", metavar="VERSION",
                   help="the notes file is a whole CHANGELOG: use the section of this version")
    p.add_argument("--kind", choices=["release", "pr"], default="release", help="labels for a release or a PR")
    p.add_argument("--date", help="date shown on the hook (default: found in the notes)")
    p.add_argument("--install", help="install or upgrade command for the end card, e.g. 'pip install -U acme'")
    p.add_argument("--url", help="URL for the end card (the release page)")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1", "4:5"])
    p.add_argument("--max-items", type=int, default=7, help="lines shown in all (default 7; the rest are counted)")
    p.add_argument("--force", action="store_true", help="write into a non-empty folder")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_release_video)

    p = sub.add_parser("pr-video", help=COMMANDS["pr-video"], formatter_class=_F, description=(
        "Turn a pull request into a short video (about 20-45 s) for its description, with no agent in the loop.\n\n"
        "Reads the PR with gh (gh pr view, gh pr diff; a paginated gh api call when the file list is capped).\n"
        "Without gh (or not signed in) a public PR is read from GitHub's REST API, without signing in; or pass\n"
        "it yourself with --diff/--body/--title, or diff the local branch with --base (git diff <base>...HEAD).\n"
        "Writes <out>/project in the release-video look: a hook (repo, number, title, author), the\n"
        "description's own lines, the evidence (files changed with +/- counts, one or two real hunks, the tests\n"
        "touched) and a closing card (what changes for users when the description says so, the PR URL).\n"
        "Every word on screen comes from the PR or a flag. Lines that look like secrets (keys, tokens, .env\n"
        "values) are masked before anything is written, and the output says so. Then it renders\n"
        "<out>/pr-<N>.mp4 and <out>/pr-<N>.github.mp4 (under 10 MB, what GitHub accepts as an attachment)\n"
        "and prints the lines to paste into the PR. Nothing is uploaded: you drag the file in yourself."),
        epilog=("Examples:\n"
                "  showtime pr-video 482                         # in a clone of the repo, gh signed in\n"
                "  showtime pr-video https://github.com/acme/tool/pull/482 --out pr-482\n"
                "  showtime pr-video 482 --repo acme/tool --aspect 1:1 --no-render\n"
                "  showtime pr-video --base main --title 'Faster exports' --body pr.md   # local branch, no gh\n"
                "  showtime pr-video 482 --diff pr.diff --body pr.md --title 'Faster exports' --repo acme/tool\n"
                "  showtime pr-video 482 --background            # long renders in hosts with short timeouts"))
    p.add_argument("pr", nargs="?", help="PR number or URL (read with gh unless --diff, --base or --pr-json is given)")
    p.add_argument("--out", help="folder for the project and the videos, its own job (default: pr-<N>-video; beside the job folder when "
                        "run inside one)")
    p.add_argument("--repo", metavar="OWNER/REPO", help="the repository (gh -R; the name shown on screen)")
    p.add_argument("--diff", metavar="FILE", help="the PR's unified diff (- for stdin), instead of gh pr diff")
    p.add_argument("--base", metavar="REF", help="diff the current branch against REF (git diff REF...HEAD), no gh")
    p.add_argument("--body", metavar="FILE", help="the PR description as Markdown (- for stdin)")
    p.add_argument("--title", help="the PR title")
    p.add_argument("--author", help="the PR author's GitHub login (without gh)")
    p.add_argument("--url", help="the PR URL for the closing card (default: from gh, or built from --repo and N)")
    p.add_argument("--pr-json", metavar="FILE",
                   help="saved `gh pr view --json %s` output (or a REST pulls/N object)" % "title,body,number,...")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1", "4:5"])
    p.add_argument("--max-items", type=int, default=4,
                   help="description lines shown in all (default 4; the rest are counted)")
    p.add_argument("--no-render", action="store_true", help="write the project only")
    p.add_argument("--preview", action="store_true", help="fast draft render (<=720p)")
    p.add_argument("--keep-work", action="store_true",
                   help="keep the render's pr-<N>.work folder (audio stems, the intermediate video) after the export")
    p.add_argument("--force", action="store_true", help="write into a non-empty project folder")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_pr_video)


def cmd_release_video(args: argparse.Namespace) -> int:
    from . import release_video as rv
    if args.notes == "-":
        md = sys.stdin.read()
    else:
        src = Path(args.notes)
        if not src.is_file():
            raise ShowtimeError("notes file not found: %s" % src, hint="pass a Markdown file, or - to read stdin")
        md = src.read_text(encoding="utf-8", errors="replace")
    if args.changelog_version:
        sec = rv.changelog_section(md, args.changelog_version)
        if not sec:
            raise ShowtimeError("no section for version %s in %s" % (args.changelog_version, args.notes),
                                why="looked for a heading such as '## %s' or '## [v%s] - <date>'"
                                    % (args.changelog_version, args.changelog_version.lstrip("v")),
                                hint="check the version spelling, or pass the section itself as the notes file")
        md = sec
    notes = rv.parse_notes(md)
    if not any(s["items"] for s in notes["sections"]):
        raise ShowtimeError("no user-facing changes found in the notes",
                            why="the video shows the notes' bullet lines; there were none outside internal sections "
                                "(dependencies, CI, docs, chores)",
                            hint="pass notes with a bulleted list of changes, or make the video with an agent "
                                 "(references/workflows/changelog-video.md)")
    name = args.name or _name_from_title(notes["title"]) or Path(os.getcwd()).name
    version = args.rel_version or notes["version"]
    if args.kind == "pr" and version and version.isdigit():
        version = "#" + version
    p = rv.plan(notes, name=name, version=version, kind=args.kind, max_items=max(1, args.max_items))
    try:
        res = rv.write_project(Path(args.out), notes, p, install=args.install or "", url=args.url or notes["compare"] or "",
                               date=args.date or notes["date"], aspect=args.aspect, force=args.force)
    except FileExistsError:
        raise ShowtimeError("%s is not empty" % args.out, hint="pick a new folder, or pass --force to write into it")
    if args.json:
        print_json(res)
        return 0
    print("wrote %s: %d scenes, %.1f s, %d of %d changes shown%s" % (
        res["project"], res["scenes"], res["duration"], res["shown"], res["total"],
        " (%d more counted on screen)" % res["more"] if res["more"] else ""))
    print("next: showtime check %s && showtime render %s" % (_q(res["project"]), _q(res["project"])))
    return 0


def _name_from_title(title: str) -> str:
    import re
    t = re.sub(r"\bv?\d+\.\d+(?:\.\d+)?\S*", "", title or "")
    t = re.sub(r"\b(release|released|version)\b", "", t, flags=re.I)
    t = re.sub(r"\d{4}-\d{2}-\d{2}", "", t)
    return t.strip(" -–—:·|[]()")


def _q(s: str) -> str:
    return '"%s"' % s if " " in s else s


# ---------------------------------------------------------------------------
# pr-video
# ---------------------------------------------------------------------------

_NO_GH_HINT = ("without gh: showtime pr-video <N> --diff pr.diff --body pr.md --title '<title>' (gh pr diff and the "
               "description, saved), or --base main in the repo for git diff main...HEAD")


def _read_text(path: str, what: str) -> str:
    if path == "-":
        return sys.stdin.read()
    src = Path(path)
    if not src.is_file():
        raise ShowtimeError("%s file not found: %s" % (what, src), hint="pass a file, or - to read stdin")
    return src.read_text(encoding="utf-8", errors="replace")


def _run(cmd: list, timeout: int = 120, env: dict = None):
    import subprocess
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ShowtimeError("%s failed: %s" % (cmd[0], e.__class__.__name__ if not isinstance(e, OSError) else e))


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return (lines[-1] if lines else "")[:300]


class _NoGh(ShowtimeError):
    """gh is not installed or not signed in: a public PR can still be read from GitHub's REST API."""


def _from_gh(ref: str, repo: str, pv) -> tuple:
    """(meta, diff, notes) from gh. Never passes or prints a token: gh uses its own sign-in."""
    import json
    import shutil
    gh = os.environ.get("SHOWTIME_GH") or shutil.which("gh")     # SHOWTIME_GH: a gh binary to use instead
    if not gh or not os.path.isfile(gh):
        raise _NoGh("gh (the GitHub CLI) is not installed, so the PR cannot be read",
                            why="pr-video reads a PR with gh pr view and gh pr diff",
                            hint="install gh (https://cli.github.com) and run gh auth login, or %s" % _NO_GH_HINT)
    env = dict(os.environ, GH_PROMPT_DISABLED="1", NO_COLOR="1", GH_NO_UPDATE_NOTIFIER="1", CLICOLOR="0")
    rflag = ["-R", repo] if repo else []
    cp = _run([gh, "pr", "view", ref, "--json", pv.GH_FIELDS] + rflag, env=env)
    if cp.returncode != 0:
        err = cp.stderr or cp.stdout
        if any(w in err for w in ("auth login", "not logged", "GH_TOKEN", "HTTP 401", "authentication")):
            raise _NoGh("gh is not signed in, so the PR cannot be read",
                                hint="run gh auth login, or %s" % _NO_GH_HINT)
        if "not a git repository" in err or "none of the git remotes" in err.lower() or "no git remotes" in err.lower():
            raise ShowtimeError("gh could not tell which repository PR %s is in" % ref,
                                hint="pass the PR URL, or --repo OWNER/REPO, or run it inside a clone")
        raise ShowtimeError("gh pr view %s failed: %s" % (ref, _last_line(err)),
                            hint="check the number or URL (and --repo), or %s" % _NO_GH_HINT)
    meta = pv.normalize_meta(json.loads(cp.stdout))
    notes = []
    repo = repo or meta["repo"]
    if pv.files_look_capped(meta) and repo and meta["number"]:
        cp = _run([gh, "api", "repos/%s/pulls/%d/files?per_page=100" % (repo, meta["number"]), "--paginate"],
                  timeout=300, env=env)
        if cp.returncode == 0:
            try:
                files = pv.normalize_meta({"files": pv.parse_json_stream(cp.stdout)})["files"]
                if len(files) > len(meta["files"]):
                    meta["files"] = files
            except ValueError:
                pass
        else:
            notes.append("could not list every file (gh api: %s): the tree uses the first %d"
                         % (_last_line(cp.stderr), len(meta["files"])))
    cf = meta.get("changed_files")
    if isinstance(cf, int) and cf > len(meta["files"]):
        notes.append("this PR is too big to show in full: it changes %d files and GitHub lists %d; the count on screen "
                     "is %d, the tree and the hunks come from the files listed" % (cf, len(meta["files"]), cf))
    cp = _run([gh, "pr", "diff", ref, "--color", "never"] + rflag, timeout=300, env=env)
    diff = cp.stdout if cp.returncode == 0 else ""
    if cp.returncode != 0:
        err = cp.stderr or ""
        if any(w in err.lower() for w in ("406", "too large", "exceeded", "maximum")):
            notes.append("this PR is too big to show in full: GitHub would not send its diff (%s); the video shows "
                         "the files changed, without hunks" % _last_line(err))
        else:
            raise ShowtimeError("gh pr diff %s failed: %s" % (ref, _last_line(err)), hint=_NO_GH_HINT)
    return meta, diff, notes


def _git(args: list) -> str:
    cp = _run(["git"] + args)
    if cp.returncode != 0:
        raise ShowtimeError("git %s failed: %s" % (" ".join(args), _last_line(cp.stderr)),
                            hint="run it inside the repository, with --base naming a branch or commit that exists")
    return cp.stdout


def _local_repo_name() -> str:
    """owner/repo from the origin remote (only the path is kept: a URL's credentials are never read out)."""
    import re
    try:
        cp = _run(["git", "remote", "get-url", "origin"], timeout=20)
    except ShowtimeError:
        return ""
    m = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", (cp.stdout or "").strip()) if cp.returncode == 0 else None
    return "%s/%s" % (m.group(1), m.group(2)) if m else ""


def cmd_pr_video(args: argparse.Namespace) -> int:
    import json
    import re
    from . import pr_video as pv
    ref_repo, number = pv.parse_pr_ref(args.pr) if args.pr else ("", None)
    if args.pr and number is None:
        raise ShowtimeError("%r is not a PR number or URL" % args.pr,
                            hint="pass the number (482) or the URL (https://github.com/OWNER/REPO/pull/482)")
    if args.diff == "-" and args.body == "-":
        raise ShowtimeError("only one of --diff and --body can read stdin", hint="save one of them to a file")
    notes = []
    branch = ""
    if args.diff or args.base or args.pr_json:
        meta = pv.normalize_meta(json.loads(_read_text(args.pr_json, "--pr-json")) if args.pr_json else {})
        if args.diff:
            diff = _read_text(args.diff, "diff")
        elif args.base:
            _git(["rev-parse", "--git-dir"])
            diff = _git(["diff", "--no-color", "--no-ext-diff", "%s...HEAD" % args.base])
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
            if not args.title and not meta["title"]:
                if _git(["rev-list", "--count", "%s..HEAD" % args.base]).strip() != "1":
                    raise ShowtimeError("--title is needed: %s has more than one commit since %s" % (branch, args.base),
                                        hint="pass --title '<the PR title>' (and --body pr.md for the description)")
                msg = _git(["log", "-1", "--format=%s%n%n%b"])
                subject, _, rest = msg.partition("\n")
                meta["title"] = subject.strip()
                meta["body"] = meta["body"] or rest.strip()
        else:
            diff = ""
    elif args.pr:
        try:
            meta, diff, notes = _from_gh(args.pr, args.repo or ref_repo, pv)
        except _NoGh as e:
            repo = args.repo or ref_repo or _local_repo_name()
            if not repo or ("://" in args.pr and not re.match(r"https?://(www\.)?github\.com/", args.pr)):
                raise ShowtimeError("%s, and there is no github.com repository to read it from without gh" % e,
                                    hint="pass the PR URL (https://github.com/OWNER/REPO/pull/%s) or --repo OWNER/REPO "
                                         "for a public PR, run gh auth login, or %s" % (number, _NO_GH_HINT))
            if not args.json:
                print("note: %s; reading the public PR from GitHub's REST API (no sign-in, nothing sent but the "
                      "request)" % str(e).split(",")[0])
            meta, diff, notes = pv.rest_pr(repo, number)
    else:
        raise ShowtimeError("no pull request given",
                            hint="showtime pr-video <N or URL> (with gh), or %s" % _NO_GH_HINT)
    if args.title:
        meta["title"] = args.title.strip()
    if args.body:
        meta["body"] = _read_text(args.body, "--body")
    if args.author:
        meta["author"] = args.author.lstrip("@")
    meta["number"] = meta.get("number") or number
    meta["repo"] = args.repo or meta.get("repo") or ref_repo or _local_repo_name() or Path(os.getcwd()).name
    if args.url:
        meta["url"] = args.url
    elif not meta.get("url") and meta["number"] and re.fullmatch(r"[\w.-]+/[\w.-]+", meta["repo"]):
        meta["url"] = "https://github.com/%s/pull/%d" % (meta["repo"], meta["number"])
    if not meta["title"]:
        raise ShowtimeError("the PR has no title to show", hint="pass --title '<the PR title>'")

    files = pv.parse_diff(diff)
    masked = pv.mask_diff(files)
    meta["title"], n_title = pv.mask_text(meta["title"])
    meta["body"], n_body = pv.mask_text(meta["body"])
    if n_title or n_body:
        masked.append({"path": "(title and description)", "lines": n_title + n_body})
    stats = pv.file_stats(files, meta.get("files") or [])
    if not stats:
        raise ShowtimeError("the PR has no changed files to show",
                            why="the diff was empty%s" % (" (git diff %s...HEAD)" % args.base if args.base else ""),
                            hint="check --base or --diff, or that the PR has commits")
    body = pv.parse_body(meta["body"])
    hunks = pv.pick_hunks(files, aspect=args.aspect)
    p = pv.plan(meta, body, stats, hunks, max_items=max(1, args.max_items), aspect=args.aspect)
    stem = ("pr-%d" % meta["number"]) if meta["number"] else ("pr-" + re.sub(r"[^\w.-]+", "-", branch).strip("-.")
                                                              if branch and branch != "HEAD" else "pr")
    out, beside = _pr_out(args.out, stem)
    try:
        res = pv.write_project(out / "project", p, meta, masked=masked, notes=notes, force=args.force)
    except FileExistsError:
        raise ShowtimeError("%s is not empty" % (out / "project"),
                            hint="pick another --out, or pass --force to write into it")
    job, own = _pr_job(out, Path(res["project"]), stem)
    res.update({"masked": masked, "notes": notes, "files": p["files"], "out": str(out), "job": str(job)})
    say = (lambda *a: None) if args.json else print
    if beside is not None:
        say("note: the current folder is inside job %s; writing beside it, in %s (--out picks the folder)"
            % (beside.name, out))
    say("wrote %s: %d scenes, %.1f s; %d of %d description lines, %d file%s, %d hunk%s" % (
        res["project"], res["scenes"], res["duration"], res["shown"], res["total"], p["files"],
        "" if p["files"] == 1 else "s", p["hunks"], "" if p["hunks"] == 1 else "s"))
    if masked:
        say("masked %d secret-looking line%s (%s): shown as dots, and kept out of the project files" % (
            sum(m["lines"] for m in masked), "" if sum(m["lines"] for m in masked) == 1 else "s",
            ", ".join(m["path"] for m in masked[:4]) + (", ..." if len(masked) > 4 else "")))
    for n in notes:
        say("note: " + n)
    if args.no_render:
        if args.json:
            print_json(res)
        else:
            print("next: showtime check %s && showtime render %s" % (_q(res["project"]), _q(res["project"])))
        return 0
    video = _render_pr(Path(res["project"]), out / (stem + ".mp4"), preview=args.preview, quiet=args.json)
    if own:
        # the render logged pr-<N>.mp4 as a variant (its name does not start with final): in pr-video's own
        # job it is the video, so `showtime qa <out>` and the receipt find it
        from .job import ledger
        kind = "preview" if args.preview else "final"
        ledger.note(job, outputs=["%s=%s" % (kind, video)], event="pr-video: %s is the latest %s" % (video.name, kind))
    gh = pv.deliver_github(video, out)
    if not args.keep_work:
        pv.remove_work(video)
    md = pv.markdown_line(Path(gh["output"]).name, res["duration"], gh["size_mb"])
    (out / (video.stem + ".md")).write_text(md + "\n", encoding="utf-8")
    res.update({"video": str(video), "github": gh, "markdown": md})
    if args.json:
        print_json(res)
        return 0
    print("video   %s" % video)
    print("github  %s (%.1f MB, under GitHub's %g MB limit)" % (gh["output"], gh["size_mb"], pv.GITHUB_MAX_MB))
    print("\nPaste this into the PR description, then drag %s onto the comment line%s:\n" % (
        Path(gh["output"]).name, " (%s)" % meta["url"] if meta.get("url") else ""))
    print(md)
    print("\n(also saved as %s; nothing was uploaded)" % (out / (video.stem + ".md")))
    return 0


def _pr_out(out_arg, stem: str) -> tuple:
    """(the output folder, the job the current folder is inside or None). --out is used as given; the default
    pr-<N>-video goes in the current folder, or beside the job folder when the current folder is inside one
    (showtime-out/<job>/...), so no file of the PR video lands in an unrelated job."""
    if out_arg:
        return Path(out_arg), None
    from .job import ledger
    here = ledger.enclosing_job(Path.cwd())
    if here is None:
        return Path(stem + "-video"), None
    return here.parent / (stem + "-video"), here


def _pr_job(out: Path, project: Path, stem: str) -> tuple:
    """(job, created): the output folder is pr-video's own job, so its check and render never inherit a job
    from the folders above (render logs into the nearest job.json, check reads the nearest job's tone). An
    --out that already is a job folder is used as it is."""
    from .job import ledger
    out = out.resolve()
    if ledger.enclosing_job(out) == out:
        return out, False
    data = ledger.new_data(stem, "quick", "showtime pr-video: %s, a short video for the pull request's description"
                           % stem, out, project.resolve())
    data["pointers"]["project"] = str(project.resolve())
    data["history"][-1]["event"] = "job created by showtime pr-video"
    ledger.save(out, data)
    return out, True


def _render_pr(project: Path, video: Path, *, preview: bool = False, quiet: bool = False) -> Path:
    """`showtime check <project>` (stops on errors), then `showtime render <project> -o <video>`; returns the
    file written (renders never overwrite: pr-N-2.mp4)."""
    import json
    import subprocess
    launcher = Path(__file__).resolve().parent / "launcher.py"
    sys.stdout.flush()
    # --no-history: every PR video shares this look on purpose, so the repeat-look comparison does not apply
    cp = subprocess.run([sys.executable, str(launcher), "check", str(project), "--quiet", "--no-history"],
                        stdout=subprocess.DEVNULL if quiet else sys.stderr)
    if cp.returncode != 0:
        raise ShowtimeError("showtime check found errors in the project, so it was not rendered",
                            hint="showtime check %s lists them; the project is kept" % _q(str(project)))
    cmd = [sys.executable, str(launcher), "render", str(project), "-o", str(video), "--json"]
    if preview:
        cmd.append("--preview")
    if quiet:
        cmd.append("--quiet")
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, encoding="utf-8", errors="replace")
    out = cp.stdout or ""
    try:
        rep = json.loads(out[out.index("{"):])
    except ValueError:
        rep = {}
    if cp.returncode != 0 or not rep.get("output"):
        raise ShowtimeError("the render failed (see the messages above)",
                            hint="showtime check %s shows what the page needs; the project is kept" % _q(str(project)))
    return Path(rep["output"])
