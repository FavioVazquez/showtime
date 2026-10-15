#!/usr/bin/env python3
"""Skill structure and release-hygiene tests (stdlib only, a few seconds).

Uses the repository's scripts/check_release.py for the actual rules:
  - versions agree (plugin.json, marketplace.json, setup/package.json, st.__version__)
  - no names of outside projects and no machine-specific paths in shipped files
  - SKILL.md frontmatter is valid, description <= 1024 chars, body within the word budget
  - every link in SKILL.md and references/ resolves
  - every `showtime <cmd> [sub]` named in SKILL.md, references/ and agents/ exists in the CLI
  - the crew: agents/*.md are valid plugin sub-agents (name, short description, tool list without
    the Agent tool, known model/effort/color), point at existing briefs in references/crew/ and
    carry the return contract; every brief has an agent
and proves each rule still fails on a known-bad sample.

While SKILL.md has not been written yet, the SKILL.md-dependent tests are
skipped with a message (they fail once SKILL.md exists and is invalid).

usage: python tests/test_skill_structure.py [--fast] [-v]
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
CHECKER = REPO / "scripts" / "check_release.py"
SKILL_MD = SKILL / "SKILL.md"
NO_SKILL_MSG = ("SKILL.md not written yet: frontmatter, word budget and command checks are skipped "
                "(they run and must pass once %s exists)" % "skills/showtime/SKILL.md")


def load_checker():
    if not CHECKER.is_file():
        return None
    spec = importlib.util.spec_from_file_location("check_release", str(CHECKER))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


cr = load_checker()


def fmt(findings) -> str:
    return "\n".join("  %s %s: %s (%s)" % (i["level"], i["check"], i["message"], i["where"]) for i in findings)


@unittest.skipIf(cr is None, "scripts/check_release.py not found (skill copied without its repository)")
class TestRepoHygiene(unittest.TestCase):
    def run_only(self, *names):
        return cr.run_checks(fix=False, only=names)

    def test_versions_in_sync(self):
        f = self.run_only("versions")
        self.assertEqual(f.errors(), [], "version drift:\n" + fmt(f.errors()))

    def test_no_banned_names(self):
        errs = [i for i in self.run_only("names").errors() if i["check"] == "names"]  # paths run in the same scan
        self.assertEqual(errs, [], "banned names found:\n" + fmt(errs))

    def test_no_machine_paths(self):
        errs = [i for i in self.run_only("paths").errors() if i["check"] == "paths"]
        self.assertEqual(errs, [], "machine-specific paths found:\n" + fmt(errs))

    def test_links_resolve(self):
        f = self.run_only("links")
        self.assertEqual(f.errors(), [], "broken links:\n" + fmt(f.errors()))

    def test_plugin_manifests(self):
        import json
        plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "showtime")
        self.assertTrue(plugin.get("description"))
        self.assertIn("showtime", [p["name"] for p in market["plugins"]])
        self.assertTrue((SKILL / "bin" / "showtime").is_file())
        for name in (".gitattributes", "CHANGELOG.md", "CONTEXT.md", "CONTRIBUTING.md", "LICENSE", "README.md"):
            self.assertTrue((REPO / name).is_file(), name + " is missing")
        self.assertTrue(list((REPO / ".out-of-scope").glob("*.md")), ".out-of-scope/ has no entries")

    def test_template_sample_urls_are_reserved_names(self):
        """A template's sample URL (data-url) shows on screen in every video made from it: it must be a reserved
        name (RFC 2606 / 6761: .example, .test, .invalid, example.com), never a domain someone can own
        (northwind.app was registered)."""
        import re
        bad = []
        for page in sorted((SKILL / "templates").rglob("*.html")):
            for url in re.findall(r'data-url="([^"]*)"', page.read_text(encoding="utf-8")):
                host = re.sub(r"^[a-z]+://", "", url).split("/")[0].split(":")[0].lower()
                if not (re.search(r"\.(example|test|invalid|localhost)$", host)
                        or host in ("localhost", "example.com", "example.org", "example.net")):
                    bad.append("%s: %s" % (page.relative_to(SKILL), url))
        self.assertEqual(bad, [])

    def test_gitattributes_line_endings(self):
        text = (REPO / ".gitattributes").read_text(encoding="utf-8")
        for pat, eol in (("*.sh", "lf"), ("*.py", "lf"), ("*.mjs", "lf"), ("*.md", "lf"),
                         ("*.cmd", "crlf"), ("*.ps1", "crlf")):
            self.assertRegex(text, r"(?m)^%s\s+.*eol=%s\b" % (pat.replace("*", r"\*").replace(".", r"\."), eol))

    def test_every_test_file_takes_fast(self):
        """run_all.py --fast (the CI fast tier) passes --fast to every file; a bare unittest.main() exits 2 on it."""
        bare = [p.name for p in sorted(TESTS_DIR.glob("test_*.py"))
                if re.search(r"(?m)^\s*unittest\.main\(\)\s*$", p.read_text(encoding="utf-8"))]
        self.assertEqual(bare, [], "these call unittest.main() with --fast still in sys.argv")


CREW = ("creative-director", "brand-designer", "scriptwriter", "storyboard-artist", "motion-designer",
        "sound-designer", "voice-director", "editor", "researcher", "critic")


@unittest.skipIf(cr is None, "scripts/check_release.py not found")
class TestCrew(unittest.TestCase):
    def test_agents_valid(self):
        f = cr.run_checks(fix=False, only=["agents"])
        self.assertEqual(f.errors(), [], "crew agent problems:\n" + fmt(f.errors()))

    def test_every_agent_caps_its_turns(self):
        for role in CREW:
            text = (REPO / "agents" / (role + ".md")).read_text(encoding="utf-8")
            m = re.search(r"(?m)^maxTurns:\s*(\d+)\s*$", text)
            self.assertIsNotNone(m, "agents/%s.md declares no maxTurns" % role)
            self.assertTrue(20 <= int(m.group(1)) <= 100,
                            "agents/%s.md: maxTurns %s is outside 20-100" % (role, m.group(1)))

    def test_roster_complete(self):
        for role in CREW:
            self.assertTrue((REPO / "agents" / (role + ".md")).is_file(), "agents/%s.md is missing" % role)
            self.assertTrue((SKILL / "references" / "crew" / (role + ".md")).is_file(),
                            "references/crew/%s.md is missing" % role)
        self.assertTrue((SKILL / "references" / "crew" / "rules.md").is_file())
        self.assertTrue((SKILL / "references" / "crew.md").is_file())

    def test_briefs_open_with_read_this_when(self):
        for brief in sorted((SKILL / "references" / "crew").glob("*.md")):
            lines = [l for l in brief.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertTrue(lines[1].startswith("Read this when"), "%s: second line must say when to read it"
                            % brief.name)

    def test_director_playbook_names_every_role(self):
        text = (SKILL / "references" / "crew.md").read_text(encoding="utf-8")
        for role in CREW:
            self.assertIn("`%s`" % role, text, "crew.md does not list %s" % role)

    @unittest.skipUnless((REPO / "site" / "content" / "crew.json").is_file(), "site/ not in this copy")
    def test_outer_docs_say_the_critic_reviews_every_video(self):
        # quality mode (the default since 0.3.0) sends a critic to every finished video (modes.md section 6);
        # the README and the site once said the critic joined only videos that would be published
        import json
        roles = {r["id"]: r for r in json.loads((REPO / "site" / "content" / "crew.json").read_text(encoding="utf-8"))["roles"]}
        self.assertEqual(sorted(roles), sorted(CREW))
        self.assertIn("All Videos", roles["critic"]["when"])
        self.assertNotIn("Publish", roles["critic"]["when"])
        for rel in ("README.md", "site/build.py", "docs/README.md"):
            text = " ".join((REPO / rel).read_text(encoding="utf-8").split())
            for stale in ("except a researcher and a critic", "Quick videos stay lean", "critic pass on publish-bound",
                          "Researcher and critic join"):
                self.assertNotIn(stale, text, "%s still says the critic is only for published videos" % rel)


@unittest.skipIf(cr is None, "scripts/check_release.py not found")
class TestSkillMd(unittest.TestCase):
    def setUp(self):
        if not SKILL_MD.is_file():
            self.skipTest(NO_SKILL_MSG)

    def test_frontmatter_and_budget(self):
        f = cr.Findings()
        cr.check_skill(f)
        self.assertEqual(f.errors(), [], "SKILL.md problems:\n" + fmt(f.errors()))

    def test_commands_exist(self):
        f = cr.run_checks(fix=False, only=["commands"])
        self.assertEqual(f.errors(), [], "docs name commands the CLI does not have:\n" + fmt(f.errors()))

    def test_fit_is_estimated_before_synthesis(self):
        # `voice script --fit S --estimate` answers "cut about N words" without speech (issue #45): every
        # workflow or crew brief that runs `voice script ... --fit` says so
        files = [SKILL_MD] + sorted((SKILL / "references" / "workflows").glob("*.md")) + sorted((SKILL / "references" / "crew").glob("*.md"))
        files.append(SKILL / "references" / "manim.md")
        files.append(SKILL / "references" / "voice.md")
        missing = []
        for p in files:
            text = re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))
            for m in re.finditer(r"voice script", text):
                # a `voice script` that goes on to `--fit` (the file names in between have dots: no [^.] shortcuts)
                if "--fit" in text[m.start():m.end() + 250] and "--estimate" not in text[max(0, m.start() - 500):m.end() + 500]:
                    missing.append("%s: ...%s..." % (p.name, text[m.start():m.end() + 120]))
        self.assertEqual(missing, [], "runs `voice script --fit` without pointing to --estimate first:\n" + "\n".join(missing))
        # the files the issue names must be in the list (a moved or renamed guide must not drop out silently)
        names = {p.name for p in files}
        for n in ("social-short.md", "explainer.md", "scriptwriter.md", "voice-director.md"):
            self.assertIn(n, names)

    def test_skill_md_names_the_synthesis_run_after_the_estimate(self):
        # the step that sets the scene lengths from voice/timeline.json must still run the real `voice script --fit`
        body = re.sub(r"\s+", " ", SKILL_MD.read_text(encoding="utf-8"))
        m = re.search(r"Voice-led:(.{0,300}?)timeline\.json", body)
        self.assertTrue(m, "SKILL.md step 2 no longer mentions voice/timeline.json")
        self.assertIn("--estimate", m.group(1))
        self.assertRegex(m.group(1), r"then without `--estimate`", "the real (synthesizing) run must stay named")


@unittest.skipIf(cr is None, "scripts/check_release.py not found")
class TestCheckersBite(unittest.TestCase):
    """Every rule must fail on a known-bad sample, or a passing run proves nothing."""

    def test_frontmatter_rules(self):
        self.assertIsNone(cr.parse_frontmatter("no frontmatter here")[0])
        fields, body, err = cr.parse_frontmatter("---\nname: showtime\ndescription: >\n  Use when making videos.\n"
                                                 "---\n# body\n")
        self.assertEqual(err, "")
        self.assertEqual(fields["description"], "Use when making videos.")
        self.assertGreater(cr.word_count("word " * 1600), cr.BODY_WORDS_MAX)

    def test_mirror_check_heads_every_asset(self):
        # no network: the mirror.json shape and a fake HEAD (the real one runs with --mirror before a release)
        data = {"mirrors": ["https://m.example/models-v1/"],
                "files": [{"file": "a--x.onnx", "size": 10}, {"file": "b--y.bin", "size": 20}, {"file": "c--z.bin", "size": 30}],
                "audio": {"mirrors": ["https://m.example/audio-v1"]}}
        assets = cr.mirror_assets(data, audio_items=[{"file": "music--t.mp3", "bytes": 5}])
        urls = [u for _n, u, _s in assets]
        self.assertIn("https://m.example/models-v1/a--x.onnx", urls)
        self.assertIn("https://m.example/models-v1/LICENSES.txt", urls)
        self.assertIn("https://m.example/models-v1/SHA256SUMS", urls)
        self.assertIn("https://m.example/audio-v1/music--t.mp3", urls)
        self.assertIn("https://m.example/audio-v1/SHA256SUMS", urls)
        answers = {"https://m.example/models-v1/b--y.bin": (404, None, "HTTP 404"),
                   "https://m.example/models-v1/c--z.bin": (200, 31, "")}
        heads = []

        def head(url):
            heads.append(url)
            return answers.get(url, (200, None, ""))
        f = cr.Findings()
        cr.check_mirror(f, assets, head=head, jobs=2)
        self.assertEqual(sorted(heads), sorted(urls), "every asset is checked")
        msgs = [i["message"] for i in f.errors()]
        self.assertEqual(len(msgs), 2, fmt(f.items))
        self.assertIn("b--y.bin is not on the release (HTTP 404)", msgs[0])
        self.assertIn("c--z.bin is 31 bytes, mirror.json says 30", msgs[1])
        # opt-in: the default run never goes online
        self.assertNotIn("mirror", cr.default_checks())
        real = cr.mirror_assets(audio_items=[])
        self.assertTrue(any(n == "modnet--model.onnx" for n, _u, _s in real))

    def test_routing_rule(self):
        # every workflow guide is read by an eval case; a routing case names a guide that exists
        import shutil
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-route-"))
        try:
            skill, evals = d / "skill", d / "benchmarks"
            (skill / "references" / "workflows").mkdir(parents=True)
            for t in ("covered", "uncovered", "old", "oldcovered"):
                (skill / "references" / "workflows" / (t + ".md")).write_text("# x\n", encoding="utf-8")

            def case(suite, name, pattern, first=True):
                g = evals / suite / name / "graders"
                g.mkdir(parents=True)
                (g.parent / "prompt.md").write_text("---\nruns: 3\n---\n\nMake a video.\n", encoding="utf-8")
                (g / "reads-the-guide.md").write_text("---\ntype: tool_used\ntool: Read\ninput_match: '%s'\n---\n"
                                                      % pattern, encoding="utf-8")
                if first:
                    (g / "names-the-first-command.md").write_text("---\ntype: regex\ntarget: last_message\n"
                                                                  "pattern: 'x'\n---\n", encoding="utf-8")
            case("routing-eval", "route-covered", r"workflows/covered\.md")
            case("routing-eval", "route-gone", r"workflows/gone\.md", first=False)
            case("plugin-eval", "old-trigger", r"workflows/oldcovered\.md")
            f = cr.Findings()
            cr.check_routing(f, evals=evals, skill=skill, legacy={"old", "oldcovered"})
            errs = sorted(i["message"] for i in f.errors())
            self.assertEqual(len(errs), 3, fmt(f.items))
            self.assertIn("route-gone has no names-the-first-command", " ".join(errs))
            self.assertIn("route-gone reads a guide that does not exist", " ".join(errs))
            self.assertIn("uncovered.md has no routing eval case", " ".join(errs))
            warns = [i["message"] for i in f.items if i["level"] == "warning"]
            self.assertEqual(len(warns), 1, fmt(f.items))
            self.assertIn("oldcovered now has a routing case", warns[0])
            # the real suite passes, and the cap is the restructured one
            self.assertEqual(cr.run_checks(only=["routing"]).errors(), [])
            self.assertIn("routing", cr.default_checks())
            self.assertLessEqual(cr.BODY_WORDS_MAX, 1200, "the cap SKILL.md was restructured to (0.4.5)")
        finally:
            shutil.rmtree(str(d), ignore_errors=True)

    def test_banned_and_path_rules(self):
        import codecs
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-struct-"))
        try:
            bad = d / "bad.md"
            name = codecs.decode(cr._BANNED_ROT13[3], "rot13")  # noqa: SLF001
            home = "/" + "Users" + "/somebody/project/x.py"
            tmp = "/pri" + "vate/tmp/x"
            bad.write_text("see %s\nfile %s\nand %s\nok C:\\Users\\me\\x.ass\n" % (name.upper(), home, tmp),
                           encoding="utf-8")
            f = cr.Findings()
            cr.check_paths_and_names(f, [bad])
            checks = sorted(i["check"] for i in f.errors())
            self.assertEqual(checks, ["names", "paths", "paths"], fmt(f.items))
        finally:
            import shutil
            shutil.rmtree(str(d), ignore_errors=True)

    def test_conflict_markers_are_errors(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-conflict-"))
        try:
            mark = lambda c: c * 7   # noqa: E731  (built here so this file holds no marker line itself)
            bad = d / "merged.md"
            bad.write_text("## 0.4.5\n%s HEAD\n- ours\n%s\n- theirs\n%s other\n" % (mark("<"), mark("="), mark(">")), encoding="utf-8")
            tail = d / "tail.py"
            tail.write_text("x = 1\n%s main\n" % mark(">"), encoding="utf-8")
            heading = d / "ok.md"
            heading.write_text("Title\n%s\n\ntext\n" % mark("="), encoding="utf-8")
            f = cr.Findings()
            cr.check_conflict_markers(f, [bad, tail, heading])
            where = sorted((Path(i["where"].rsplit(":", 1)[0]).name, i["where"].rsplit(":", 1)[1]) for i in f.errors())
            self.assertEqual([i["check"] for i in f.errors()], ["conflicts"] * 4, fmt(f.items))
            self.assertEqual(where, [("merged.md", "2"), ("merged.md", "4"), ("merged.md", "6"), ("tail.py", "2")])
            self.assertIn("conflicts", cr.default_checks())
        finally:
            import shutil
            shutil.rmtree(str(d), ignore_errors=True)

    def test_people_guides_are_checked(self):
        # docs/guides/*.md (task guides for people) go through the links and commands checks too
        self.assertIn(cr.REPO / "docs" / "guides" / "README.md", cr.people_docs())
        d = Path(tempfile.mkdtemp(prefix="st-guides-"))
        real = cr.people_docs
        try:
            doc = d / "guide.md"
            doc.write_text("Run `showtime edit clipz <job>`, then read [the rules](no-such-file.md).\n", encoding="utf-8")
            cr.people_docs = lambda: [doc]
            f = cr.Findings()
            cr.check_commands(f)
            cr.check_links(f)
            found = sorted(i["check"] for i in f.errors() if i["where"].startswith(str(doc)))
            self.assertEqual(found, ["commands", "links"], fmt(f.items))
        finally:
            cr.people_docs = real
            shutil.rmtree(str(d), ignore_errors=True)

    def test_newcomer_pages_are_linked_and_checked(self):
        # the docs audit for 0.4.2: newcomers were sent to the 1,382-line README, troubleshooting answers were written
        # for agents only, and EDL, ledger and look signature had no reader's definition
        docs = REPO / "docs"
        for page in (docs / "guides" / "first-video.md", docs / "troubleshooting.md", docs / "glossary.md"):
            self.assertTrue(page.is_file(), page)
            self.assertIn(page, cr.people_docs(), "%s is not link- and command-checked" % page.name)
        for rel, links in (("docs/README.md", ("guides/first-video.md", "troubleshooting.md", "glossary.md")),
                           ("docs/guides/README.md", ("first-video.md", "../troubleshooting.md", "../glossary.md")),
                           ("docs/faq.md", ("troubleshooting.md", "guides/first-video.md")),
                           ("README.md", ("docs/guides/first-video.md", "docs/troubleshooting.md", "docs/glossary.md"))):
            text = (REPO / rel).read_text(encoding="utf-8")
            for link in links:
                self.assertIn("(%s" % link, text, "%s does not link %s" % (rel, link))
        glossary = (docs / "glossary.md").read_text(encoding="utf-8")
        for term in ("EDL", "ledger", "look signature", "splice", "critic", "crew", "quality and lean", "quick and studio"):
            self.assertIn("## %s" % term, glossary, "the glossary does not define %s" % term)
        self.assertIn("../CONTEXT.md", glossary, "the glossary must say how it relates to CONTEXT.md")
        # contradictions the audit found: review mode is not tied to quick mode, and the first-use transcription model is
        # Parakeet (outside its 25 languages Whisper small is fetched, or turbo when installed; --full fetches turbo)
        for rel in ("docs/README.md", "docs/agents.md", "README.md", "site/build.py", "skills/showtime/references/harness-notes.md"):
            text = " ".join((REPO / rel).read_text(encoding="utf-8").split())
            for stale in ("quick is lean", "Whisper for transcripts", "Whisper before the first transcription"):
                self.assertNotIn(stale, text, "%s still says %r" % (rel, stale))

    def test_moved_doc_links(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-moved-"))
        try:
            doc = d / "doc.md"
            old = "https://developers." + "openai.com/codex/mcp"     # split: this file ships too
            doc.write_text("old: %s\nnew: https://learn.chatgpt.com/docs/extend/mcp\n" % old, encoding="utf-8")
            f = cr.Findings()
            cr.check_moved_urls(f, [doc])
            self.assertEqual([(i["check"], i["where"].rsplit(":", 1)[1]) for i in f.errors()], [("links", "1")], fmt(f.items))
            self.assertIn("learn.chatgpt.com", f.errors()[0]["message"])
        finally:
            import shutil
            shutil.rmtree(str(d), ignore_errors=True)

    def test_registry_names_rule(self):
        import json
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-registry-"))
        real = cr.REPO
        try:
            (d / "packages" / "npm").mkdir(parents=True)
            (d / "server.json").write_text(json.dumps({"name": "io.github.someone/showtime", "description": "x" * 101,
                                                        "packages": [{"registryType": "npm", "identifier": "other"}]}),
                                           encoding="utf-8")
            (d / "packages" / "npm" / "package.json").write_text(json.dumps({"name": "@a/b", "mcpName": "io.github.x/y"}),
                                                                 encoding="utf-8")
            cr.REPO = d
            f = cr.Findings()
            cr.check_registry_names(f)
            msgs = " | ".join(i["message"] for i in f.errors())
            for needle in ("mcpName", "npm package must be", "over 100 characters"):
                self.assertIn(needle, msgs)
        finally:
            cr.REPO = real
            import shutil
            shutil.rmtree(str(d), ignore_errors=True)

    def test_doc_version_rules(self):
        """A stale copy of the docs fails; fixing rewrites every mechanical claim; the prose summary needs a person."""
        import json
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-docver-"))
        try:
            for sub in ("site", "docs/examples", "assets/readme/badges", "benchmarks"):
                (d / sub).mkdir(parents=True)
            (d / "site" / "config.json").write_text('{\n  "version": "0.3",\n  "hero": {"label": "0.3.0 reel"}\n}\n',
                                                   encoding="utf-8")
            link = ("[`showtime-0.3.0.mcpb`](https://github.com/o/r/releases/download/v0.3.0/showtime-0.3.0.mcpb) from\n"
                    "the v0.3.0 release")
            pin = "uses: o/r/.github/actions/showtime-video@v0.3.0\n"
            (d / "README.md").write_text(
                '<img alt="status: 0.3, early" src="x.svg">\n\n**What\'s new in 0.3.0** (the full list is '
                "[below](#new-in-030)):\n\n- a\n\n%s\n\n## New in 0.3.0\n\n<sub>Status: 0.2, early. More.</sub>\n"
                % link, encoding="utf-8")
            (d / "docs" / "github-action.md").write_text("```yaml\n- " + pin + "```\n", encoding="utf-8")
            (d / "docs" / "examples" / "video.yml").write_text("    - " + pin + "#   - " + pin, encoding="utf-8")
            (d / "assets" / "readme" / "badges" / "status.svg").write_text(
                '<svg><title id="t">status: 0.3 · early</title></svg>', encoding="utf-8")
            (d / "CHANGELOG.md").write_text(pin + link, encoding="utf-8")            # history: never flagged
            (d / "benchmarks" / "r1.md").write_text(pin, encoding="utf-8")
            f = cr.Findings()
            cr.check_doc_versions(f, False, "0.4.0", repo=d)
            where = sorted(i["where"] for i in f.errors())
            self.assertEqual(where, ["README.md:1", "README.md:12", "README.md:3", "README.md:7",
                                     "assets/readme/badges/status.svg", "docs/examples/video.yml:1",
                                     "docs/examples/video.yml:2", "docs/github-action.md:2", "site/config.json"],
                             fmt(f.items))
            self.assertTrue(any("needs a person" in i["message"] for i in f.errors()))
            f = cr.Findings()
            cr.check_doc_versions(f, True, "0.4.0", repo=d)
            self.assertEqual(sorted(i["where"] for i in f.errors()), ["README.md:3", "assets/readme/badges/status.svg"],
                             fmt(f.items))
            self.assertEqual(json.loads((d / "site" / "config.json").read_text(encoding="utf-8"))["version"], "0.4")
            readme = (d / "README.md").read_text(encoding="utf-8")
            self.assertIn("showtime-0.4.0.mcpb`](https://github.com/o/r/releases/download/v0.4.0/showtime-0.4.0.mcpb) "
                          "from\nthe v0.4.0 release", readme)
            self.assertIn("Status: 0.4, early.", readme)
            self.assertIn('alt="status: 0.4, early"', readme)
            self.assertIn("What's new in 0.3.0", readme)                                # prose is left alone
            for p in ("docs/github-action.md", "docs/examples/video.yml"):
                text = (d / p).read_text(encoding="utf-8")
                self.assertNotIn("@v0.3.0", text, p)
                self.assertIn("showtime-video@v0.4.0", text, p)
            self.assertIn("@v0.3.0", (d / "CHANGELOG.md").read_text(encoding="utf-8"))
            self.assertIn("@v0.3.0", (d / "benchmarks" / "r1.md").read_text(encoding="utf-8"))
            # the summary rewritten by hand, for the same minor: clean (a patch release keeps it)
            (d / "README.md").write_text(readme.replace("What's new in 0.3.0", "What's new in 0.4.0")
                                         .replace("#new-in-030", "#new-in-040")
                                         .replace("## New in 0.3.0", "## New in 0.4.0\n\n## New in 0.3.0"),
                                         encoding="utf-8")
            (d / "assets" / "readme" / "badges" / "status.svg").write_text('<svg><title>status: 0.4 · early</title></svg>',
                                                                           encoding="utf-8")
            f = cr.Findings()
            cr.check_doc_versions(f, False, "0.4.0", repo=d)
            self.assertEqual(f.errors(), [], fmt(f.items))
            f = cr.Findings()
            cr.check_doc_versions(f, False, "0.4.1", repo=d)
            self.assertEqual(sorted(i["where"] for i in f.errors()),
                             ["README.md:7", "docs/examples/video.yml:1", "docs/examples/video.yml:2",
                              "docs/github-action.md:2"], fmt(f.items))
            # a wrong anchor and a missing section are caught too
            (d / "README.md").write_text(readme.replace("What's new in 0.3.0", "What's new in 0.4.0"), encoding="utf-8")
            f = cr.Findings()
            cr.check_doc_versions(f, False, "0.4.0", repo=d)
            msgs = " | ".join(i["message"] for i in f.errors())
            self.assertIn('no "## New in 0.4.0" section', msgs)
            self.assertIn("links #new-in-030, expected #new-in-040", msgs)
        finally:
            import shutil
            shutil.rmtree(str(d), ignore_errors=True)

    def test_agent_rules(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="st-agents-"))
        try:
            agents, crew = d / "agents", d / "crew"
            agents.mkdir()
            crew.mkdir()
            (crew / "rules.md").write_text("# rules\n", encoding="utf-8")
            (crew / "good.md").write_text("# good\n", encoding="utf-8")
            (crew / "orphan.md").write_text("# no agent\n", encoding="utf-8")
            good = ("---\nname: good\ndescription: showtime crew. Dispatched by the showtime skill.\n"
                    "tools: Read, Write, Bash, PowerShell\nmodel: sonnet\neffort: medium\nmaxTurns: 10\n"
                    "color: green\n---\nRead ${CLAUDE_PLUGIN_ROOT}/crew/rules.md and ${CLAUDE_PLUGIN_ROOT}/crew/good.md.\n"
                    "STATUS: DONE | NEEDS_INPUT\n")
            (agents / "good.md").write_text(good, encoding="utf-8")
            f = cr.Findings()
            cr.check_agents(f, agents_dir=agents, crew_dir=crew, root=d)
            self.assertEqual([i["where"] for i in f.errors()], [cr.rel(crew / "orphan.md")], fmt(f.items))
            bad = ("---\nname: Bad_Name\ndescription: %s\ntools: Read, Agent, Frobnicate\nmodel: gpt\n"
                   "effort: extreme\ncolor: teal\nmaxTurns: lots\npermissionMode: plan\n---\n"
                   "Read ${CLAUDE_PLUGIN_ROOT}/crew/missing.md\n" % ("Reviews anything. " * 20))
            (agents / "bad.md").write_text(bad, encoding="utf-8")
            (agents / "nested").mkdir()
            f = cr.Findings()
            cr.check_agents(f, agents_dir=agents, crew_dir=crew, root=d)
            msgs = " | ".join(i["message"] for i in f.errors() if i["where"].endswith("bad.md"))
            for needle in ("must match the file name", "lowercase", "characters (max", "ignored for plugin agents",
                           "dispatch agents", "unknown tool", "model 'gpt'", "effort 'extreme'", "color 'teal'",
                           "maxTurns", "does not exist", "must point at", "no role brief", "return contract"):
                self.assertIn(needle, msgs)
            self.assertTrue(any("flat" in i["message"] for i in f.errors()), fmt(f.items))
        finally:
            import shutil
            shutil.rmtree(str(d), ignore_errors=True)

    def test_command_rules(self):
        cmds = cr.cli_commands()
        for must in ("setup", "doctor", "render", "deliver", "new", "version"):
            self.assertIn(must, cmds)
        found = cr.command_mentions("Run `showtime renderz x`.\n```\n$ showtime deliver exportz a.mp4\n```\n")
        self.assertEqual(sorted((c, s) for c, s, _ in found), [("deliver", "exportz"), ("renderz", "x")])
        self.assertNotIn("renderz", cmds)
        if cmds.get("deliver"):
            self.assertNotIn("exportz", cmds["deliver"])


def load_publish_media():
    path = REPO / "scripts" / "publish_media.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("publish_media", str(path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


pm = load_publish_media()


@unittest.skipIf(pm is None, "scripts/publish_media.py lives in the showtime-examples repository "
                             "(or the skill was copied without its repository)")
class TestPublishMedia(unittest.TestCase):
    """Large example media are release assets: policy, manifest, .gitignore block, verify, links, upload."""

    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="st-media-"))
        ex = self.root / "examples"

        def mk(rel, size):
            p = ex / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(str(p), "wb") as f:
                f.truncate(size)   # sparse: sizes without writing megabytes
            return p
        self.big = mk("01-demo/final.mp4", 11_000_000)
        self.small = mk("01-demo/final-9x16.mp4", 9_500_000)
        self.poster = mk("01-demo/poster.jpg", 120_000)
        self.mov = mk("20-pack/pack/lower-thirds/lt-bar.mov", 2_000)
        self.page = mk("13-bees/waggle.html", 10_500_000)
        mk("01-demo/work/scratch.mp4", 30_000_000)        # work folders never count

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.root), ignore_errors=True)

    def manifest(self):
        return pm.build_manifest(examples=self.root / "examples", root=self.root)

    def test_policy(self):
        self.assertEqual(pm.reason_for(Path("a.mov"), 10), "ProRes/.mov master")
        self.assertEqual(pm.reason_for(Path("a.mp4"), 10_000_001), "over 10 MB")
        self.assertIsNone(pm.reason_for(Path("a.mp4"), 10_000_000))
        self.assertIsNone(pm.reason_for(Path("poster.jpg"), 200_000))
        self.assertEqual(pm.reason_for(Path("examples/_brand/sting.mp4"), 4_000_000), "brand media")
        self.assertIsNone(pm.reason_for(Path("examples/_brand/README.md"), 2_000))
        self.assertEqual(pm.asset_name("examples/20-pack/pack/lower-thirds/lt-bar.mov"), "20-pack--pack--lower-thirds--lt-bar.mov")

    def test_manifest_and_summary(self):
        m = self.manifest()
        paths = [e["path"] for e in m["files"]]
        self.assertEqual(paths, ["examples/01-demo/final.mp4", "examples/13-bees/waggle.html",
                                 "examples/20-pack/pack/lower-thirds/lt-bar.mov"])
        self.assertEqual(len({e["asset"] for e in m["files"]}), 3, "asset names must be unique")
        self.assertTrue(all(len(e["sha256"]) == 64 for e in m["files"]))
        self.assertEqual(m["summary"]["release_bytes"], 11_000_000 + 10_500_000 + 2_000)
        self.assertEqual(m["summary"]["git_files"], 2)
        self.assertEqual(m["summary"]["git_bytes"], 9_500_000 + 120_000)

    def test_gitignore_block_idempotent_and_verify(self):
        m = self.manifest()
        base = (REPO / ".gitignore").read_text(encoding="utf-8") if (REPO / ".gitignore").is_file() else "*.mp4\n!examples/**/*.mp4\n"
        base = pm.with_block(base, "")  # drop any real block
        once = pm.with_block(base, pm.gitignore_block(m))
        self.assertEqual(pm.with_block(once, pm.gitignore_block(m)), once)
        self.assertIn("/examples/01-demo/final.mp4", once)
        self.assertNotIn("final-9x16.mp4", once)
        ex = self.root / "examples"
        ok = pm.verify(m, once, examples=ex, root=self.root, hash_files=True)
        self.assertEqual((ok["errors"], ok["warnings"]), ([], []))
        # the rule bites: no block, or no manifest
        self.assertTrue(any("does not exclude" in e for e in pm.verify(m, base, examples=ex, root=self.root)["errors"]))
        self.assertTrue(pm.verify(None, once, examples=ex, root=self.root)["errors"])
        # a re-render changes the size: a warning (refresh before uploading), not an error
        with open(str(self.big), "ab") as f:
            f.truncate(12_000_000)
        self.assertTrue(pm.verify(m, once, examples=ex, root=self.root)["warnings"])
        # a new big file is an error until --refresh lists it
        with open(str(ex / "01-demo" / "final-2.mp4"), "wb") as f:
            f.truncate(15_000_000)
        self.assertTrue(any("final-2.mp4" in e for e in pm.verify(m, once, examples=ex, root=self.root)["errors"]))
        # git really ignores the listed files and keeps the small ones (after the !examples/**/*.mp4 exception)
        import shutil
        import subprocess
        git = shutil.which("git")
        if git:
            (self.root / ".gitignore").write_text(once, encoding="utf-8")
            subprocess.run([git, "init", "-q", str(self.root)], check=True)
            ign = lambda rel: subprocess.run([git, "-C", str(self.root), "check-ignore", "-q", rel]).returncode == 0  # noqa: E731
            self.assertTrue(ign("examples/01-demo/final.mp4"))
            self.assertTrue(ign("examples/20-pack/pack/lower-thirds/lt-bar.mov"))
            self.assertTrue(ign("examples/13-bees/waggle.html"))
            self.assertFalse(ign("examples/01-demo/final-9x16.mp4"))
            self.assertFalse(ign("examples/01-demo/poster.jpg"))

    def test_links_and_upload_command(self):
        m = self.manifest()
        md = pm.links_markdown(m, example="20", repo="me/showtime", tag="v9")
        self.assertEqual(md, "- [`pack/lower-thirds/lt-bar.mov`](https://github.com/me/showtime/releases/download/v9/"
                             "20-pack--pack--lower-thirds--lt-bar.mov) (0.0 MB)")
        cmd = pm.upload_command(m, Path("stage"), "v9", "me/showtime")
        self.assertEqual(cmd[:4], ["gh", "release", "upload", "v9"])
        self.assertIn(str(Path("stage") / "01-demo--final.mp4"), cmd)
        self.assertEqual(cmd[-3:], ["--clobber", "--repo", "me/showtime"])
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            staged = pm.stage(m, self.root, Path(d))
            self.assertEqual(sorted(p.name for p in staged), sorted(e["asset"] for e in m["files"]))
        self.assertTrue(self.big.exists(), "staging never moves the example's own file")

    def test_repository_manifest_follows_the_policy(self):
        man = pm.load_manifest()
        if man is None:
            self.skipTest("examples/MEDIA.json not written yet")
        res = pm.verify(man, (REPO / ".gitignore").read_text(encoding="utf-8"))
        self.assertEqual(res["errors"], [], "\n".join(res["errors"]))


class TestRunAllStrayCheck(unittest.TestCase):
    """run_all.py flags files a test writes into the repository, never the repository's own folders."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("st_run_all", str(TESTS_DIR / "run_all.py"))
        self.ra = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(self.ra)  # type: ignore[union-attr]

    def test_legit_top_level_folders_are_not_strays(self):
        ra = self.ra
        legit = ra.legit_entries()
        root = ra.PLUGIN_ROOT
        before = {str(root / "skills")}
        after = before | {str(root / "benchmarks"), str(root / "examples"), str(ra.SKILL_DIR / "__pycache__"),
                          str(root / "showtime-out"), str(ra.SKILL_DIR / "final.mp4")}
        self.assertEqual(ra.strays(before, after, legit),
                         sorted([str(root / "showtime-out"), str(ra.SKILL_DIR / "final.mp4")]))

    def test_every_current_top_level_entry_is_legit(self):
        # whatever is in git's file list today is part of the repository
        ra = self.ra
        tops = ra.git_top_level(ra.PLUGIN_ROOT)
        if not tops:
            self.skipTest("no git checkout")
        legit = ra.legit_entries()
        self.assertEqual(sorted(t for t in tops if str(ra.PLUGIN_ROOT / t) not in legit), [])


class TestRunAllShards(unittest.TestCase):
    """run_all.py --shard I/N: every file in exactly one part, the same split everywhere, balanced parts."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("st_run_all_shard", str(TESTS_DIR / "run_all.py"))
        self.ra = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(self.ra)  # type: ignore[union-attr]

    def test_parts_cover_every_file_once(self):
        ra = self.ra
        tests = ra.discover()
        names = [t.name for t in tests]
        for n in (1, 2, 3, 4, len(names) + 2):
            parts = [ra.select_shard(tests, (i, n)) for i in range(1, n + 1)]
            flat = [t.name for part in parts for t in part]
            self.assertEqual(sorted(flat), sorted(names), "n=%d" % n)
            self.assertEqual(len(flat), len(set(flat)), "n=%d: a file is in two parts" % n)
            for part in parts:   # each part keeps the discovery order
                self.assertEqual([t.name for t in part], [x for x in names if x in {t.name for t in part}])

    def test_split_is_stable_and_ignores_input_order(self):
        ra = self.ra
        names = ["test_%s.py" % c for c in "abcdefghij"] + ["test_render.py", "test_motion.py"]
        a = ra.shard_parts(names, 3)
        self.assertEqual(a, ra.shard_parts(list(reversed(names)), 3))
        self.assertEqual(a, ra.shard_parts(names, 3))

    def test_parts_are_balanced_by_weight(self):
        ra = self.ra
        w = {"a": 10, "b": 9, "c": 8, "d": 3, "e": 2, "f": 1}
        parts = ra.shard_parts(list(w), 2, w)
        loads = sorted(sum(w[x] for x in p) for p in parts)
        self.assertEqual(loads, [16, 17])
        heavy = [n for n, _ in sorted(ra.SHARD_WEIGHTS.items(), key=lambda kv: -kv[1])[:3]]
        self.assertEqual(sorted(len(set(p) & set(heavy)) for p in ra.shard_parts(list(ra.SHARD_WEIGHTS), 3)),
                         [1, 1, 1], "the three heaviest files share a part")

    def test_serial_files_count_double(self):
        ra = self.ra
        ra.SERIAL = {"test_b.py": "runs alone"}
        ra.SHARD_WEIGHTS = {"test_a.py": 100, "test_b.py": 60, "test_c.py": 50, "test_d.py": 50}
        # b runs alone, so it weighs 120 and goes first: b (120) + d (50) against a (100) + c (50)
        self.assertEqual(ra.shard_parts(["test_a.py", "test_b.py", "test_c.py", "test_d.py"], 2),
                         [["test_b.py", "test_d.py"], ["test_a.py", "test_c.py"]])

    def test_parse_shard(self):
        ra = self.ra
        self.assertEqual(ra.parse_shard("2/3"), (2, 3))
        for bad in ("0/3", "4/3", "3", "a/b", "1/0"):
            with self.assertRaises(Exception, msg=bad):
                ra.parse_shard(bad)


E2E = REPO / "scripts" / "e2e.py"


@unittest.skipIf(not E2E.is_file(), "scripts/e2e.py not found (skill copied without its repository)")
class TestE2EScript(unittest.TestCase):
    """scripts/e2e.py (the platform test behind .github/workflows/e2e.yml) judges steps strictly."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("st_e2e", str(E2E))
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def run_step(self, code: str, **kw):
        out = Path(tempfile.mkdtemp(prefix="st-e2e-test-"))
        try:
            r = self.m.Run(out)
            text = r.cmd("step", [sys.executable, "-c", code], cwd=out, timeout=60, **kw)
            return text, r.steps[-1]
        finally:
            shutil.rmtree(str(out), ignore_errors=True)

    def test_traceback_with_exit_code_0_fails(self):
        # what phonemizer's exit hook printed on Windows on Arm: rc 0, yet an exception
        code = ("import atexit, sys\n"
                "def hook(): raise PermissionError(13, 'Access is denied', 'espeak-ng.dll')\n"
                "atexit.register(hook)\nprint('done vo.wav')")
        text, step = self.run_step(code)
        self.assertIsNone(text)
        self.assertFalse(step["ok"])
        self.assertEqual(step["rc"], 0)
        self.assertIn("PermissionError", step["note"])
        text, step = self.run_step(code, strict=False)   # the suite step: its exit code decides
        self.assertTrue(step["ok"])

    def test_clean_step_passes_and_expect_can_fail_it(self):
        text, step = self.run_step("print('verdict: PASS')")
        self.assertTrue(step["ok"])
        self.assertEqual(step["note"], "verdict: PASS")
        text, step = self.run_step("print('ok')", expect=lambda t: "no final.mp4")
        self.assertFalse(step["ok"])
        self.assertEqual(step["note"], "no final.mp4")

    def test_workflow_uses_the_script(self):
        wf = (REPO / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/e2e.py", wf)
        self.assertIn("e2e-windows.ps1", wf)
        for label in ("macos-14", "ubuntu-24.04-arm", "windows-11-arm", "windows-2025"):
            self.assertIn(label, wf)
        ps1 = (REPO / "scripts" / "e2e-windows.ps1").read_bytes()
        self.assertTrue(all(b < 128 for b in ps1), "e2e-windows.ps1 must stay ASCII (PowerShell 5.1 reads it as ANSI)")


if __name__ == "__main__":
    if not SKILL_MD.is_file():
        sys.stderr.write("note: %s\n" % NO_SKILL_MSG)
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
