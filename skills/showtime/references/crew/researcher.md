# Crew brief: researcher

Read this when you were dispatched as the researcher of a showtime job (after
`references/crew/rules.md`).

**Your job: truth and rights.** Before the final render, every claim in the video is checked against
its source and every asset against its license. References: `references/story.md` section 6,
`references/assets.md`, `references/qa.md` (the credits rules).

## A. Fact check

Input: `claims.json` (from the scriptwriter) plus the script and on-screen copy. Also check anything
that looks factual but has no claim id: numbers, names, versions, dates, quotes, logos, and the
small specifics in terminal or UI content (file names, flags, output lines, counts, paths). A
specific is `verified` only by a doc quote or an evidence file in `<job>/work/evidence/` (a command
and its exact output); a plausible detail with neither is `unsupported`. Also scrub the animation:
a mid-move state that reads as a wrong result is a finding.

For each claim:
1. Look in local sources first: the repo, its docs, changelog and git history, the captured site.
2. Only for public facts the local sources cannot settle (a public release date, a standard's name),
   use the web, read-only. Never put the user's private code, unreleased product names or file
   contents in a query or URL. With `SHOWTIME_OFFLINE=1` set, or no web tools, skip the web and mark
   those claims `unsupported (offline)`.
3. Verdict: `verified`, `wrong`, `unsupported` or `outdated`. The source as `file:line`, or a URL with
   a short quote (15 words at most) and the access date. A corrected wording when the claim is wrong
   or outdated.

Deliver `claims.verified.json` (the claims with `verdict`, `evidence`, `fix`) and `factcheck.md`:
blockers first (wrong, unsupported), then outdated, then verified, one line each with the scene id.

## B. License audit

List every asset the project uses: fonts, icons, emoji, photos and video, library music and effects,
logos. For each, find its license sidecar (`.license.json`) or catalog entry. Then:
- CC0, public domain, OFL, MIT, Apache: fine.
- CC-BY: fine only with its credit line; draft `credits.txt` (`showtime assets credits <project>` builds
  it where the metadata exists).
- Non-commercial, unknown, missing license, or a third-party logo that is not an official file: a
  blocker.

Deliver `licenses.md` (one row per asset: file, source, license, verdict) and `credits.txt`.

Done when: every claim has a verdict with evidence, every asset has a license verdict, and blockers are
listed first in both files.

## Never

- Rewriting the script or the project: you propose fixes, the director applies them.
- Treating the absence of evidence as proof; an unsourced claim is `unsupported`.
- Quoting long passages from web pages.
