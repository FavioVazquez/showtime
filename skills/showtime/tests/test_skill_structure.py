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
import sys
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

    def test_gitattributes_line_endings(self):
        text = (REPO / ".gitattributes").read_text(encoding="utf-8")
        for pat, eol in (("*.sh", "lf"), ("*.py", "lf"), ("*.mjs", "lf"), ("*.md", "lf"),
                         ("*.cmd", "crlf"), ("*.ps1", "crlf")):
            self.assertRegex(text, r"(?m)^%s\s+.*eol=%s\b" % (pat.replace("*", r"\*").replace(".", r"\."), eol))


CREW = ("creative-director", "brand-designer", "scriptwriter", "storyboard-artist", "motion-designer",
        "sound-designer", "voice-director", "editor", "researcher", "critic")


@unittest.skipIf(cr is None, "scripts/check_release.py not found")
class TestCrew(unittest.TestCase):
    def test_agents_valid(self):
        f = cr.run_checks(fix=False, only=["agents"])
        self.assertEqual(f.errors(), [], "crew agent problems:\n" + fmt(f.errors()))

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

    def test_parse_shard(self):
        ra = self.ra
        self.assertEqual(ra.parse_shard("2/3"), (2, 3))
        for bad in ("0/3", "4/3", "3", "a/b", "1/0"):
            with self.assertRaises(Exception, msg=bad):
                ra.parse_shard(bad)


if __name__ == "__main__":
    if not SKILL_MD.is_file():
        sys.stderr.write("note: %s\n" % NO_SKILL_MSG)
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
