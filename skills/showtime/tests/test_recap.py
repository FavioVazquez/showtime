#!/usr/bin/env python3
"""`showtime recap` (lib/st/recap.py, cli_recap.py): a Claude Code session -> a short film of what the agent did.

A synthetic transcript (tests/fixtures/recap: a session and a sub-agent; never a real one) holds planted private
material: a key in the request, keys in tool output and in a command, a memory block in a system reminder, an
attachment event, assistant thinking and prose, a file outside the repository, a .env file, a URL, an ssh host,
an unknown event type and a broken line. The tests check the parser, the allow-list (none of the planted material
reaches script.md, facts.json or any file of the project), the hard filter (keys and absolute paths, also when the
user pastes them into script.md), commands as program + subcommand, test counts per runner, the diff stats from git,
the script round trip, and the end to end (`--no-voice --preview`, qa PASS or WARN; skipped with --fast).

usage: python tests/test_recap.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
FIX = TESTS_DIR / "fixtures" / "recap"
sys.path.insert(0, str(SKILL / "lib"))

from st import recap as rc  # noqa: E402
from st.common import ShowtimeError  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
PLACEHOLDER_ROOT = "/Users/me/code/acme"
GH_TOKEN = "gh" + "p_0123456789abcdefghijABCDEFGHIJ012345"     # a fake token, assembled at run time
PLANTED = ("sk-test-notarealkey", "AKIAIOSFODNN7EXAMPLE", "ghp_0123456789", "Zorblax", "PRIVATE-MEMORY-NOTE",
           "THINKING-SECRET", "ASSISTANT-PROSE-SECRET", "ci-runner-07", "/Users/me", "intranet.example.com",
           "internal.example.com", "MEMORY.md", ".env", "missing.py", "1a59c906", "secret")


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="T",
               GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, encoding="utf-8", env=env).stdout


def make_repo(root: Path) -> tuple:
    """A git repository with src/parser.py and a commit that changes it; (base sha, fix sha)."""
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "parser.py").write_text("def parse(s):\n    return s.split()[0]\n", encoding="utf-8")
    (root / "tests" / "test_parser.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD").strip()
    (root / "src" / "parser.py").write_text("def parse(s):\n    parts = s.split()\n    if not parts:\n"
                                            "        return ''\n    return parts[0]\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "Fix the parser on empty input")
    fix = git(root, "rev-parse", "--short", "HEAD").strip()
    return base, fix


def fixture_copy(dest: Path, repo: Path, sha: str, *, sub: bool = False) -> Path:
    """The fixture with its placeholder repository path (and commit hash) pointing at a real temporary repo."""
    src = FIX / ("subagents/agent-a1.jsonl" if sub else "session.jsonl")
    text = src.read_text(encoding="utf-8").replace(PLACEHOLDER_ROOT, str(repo)).replace("abc1234", sha)
    text = text.replace("@@GITHUB_TOKEN@@", GH_TOKEN)        # built here: the repository's secret scanner
    if sub:
        (dest / "subagents").mkdir(parents=True, exist_ok=True)
        out = dest / "subagents" / "agent-a1.jsonl"
        shutil.copy(FIX / "subagents" / "agent-a1.meta.json", dest / "subagents" / "agent-a1.meta.json")
    else:
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / "session.jsonl"
    out.write_text(text, encoding="utf-8")
    return out


def showtime(*args, check=True, cwd=None, env=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=env or ENV, cwd=cwd,
                        timeout=900)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                  cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def all_text(folder: Path) -> str:
    out = []
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file() and p.suffix in (".md", ".json", ".html", ".txt", ".srt", ".vtt", ".ass", ""):
            out.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(out)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="st-recap-")))
        cls.repo = cls.tmp / "acme"
        cls.base, cls.fix = make_repo(cls.repo)
        cls.session = fixture_copy(cls.tmp / "t", cls.repo, cls.fix)
        cls.sub = fixture_copy(cls.tmp / "t", cls.repo, cls.fix, sub=True)
        cls.ses = rc.parse_session(cls.session)
        cls.top, cls.roots = rc.repo_roots(cls.ses)
        cls.facts = rc.collect(cls.ses, cls.top, cls.roots)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestParser(Base):
    def test_events_and_unknown_types(self):
        s = self.ses
        self.assertEqual(s["events"], 30)                  # 31 lines: the broken one is skipped, the unknown kept
        self.assertEqual(len(s["uses"]), 12)
        self.assertEqual(len(s["results"]), 12)
        self.assertEqual(len(s["turns"]), 14)              # message ids: one per assistant response
        self.assertEqual(s["kind"], "session")
        self.assertIn("Fix the flaky parser test", s["request"])     # the reminder block is not the request
        self.assertGreater(s["end"], s["start"])

    def test_sub_agent_and_its_description(self):
        s = rc.parse_session(self.sub)
        self.assertEqual(s["kind"], "sub-agent")
        f = rc.collect(s, self.top, self.roots)
        sugg = rc.suggestions_for(s)
        self.assertIn(("the sub-agent's description", "Fix the parser flake"), sugg)   # a suggestion only
        self.assertNotIn("parser flake", json.dumps(f))
        lines = rc.script_lines(f)
        self.assertEqual(lines["hook.title"]["text"], rc.facts_title(f))
        self.assertNotIn("parser flake", json.dumps(lines))
        md = rc.write_script(lines, f["ref"], sugg)
        self.assertIn("# show hook.title: Fix the parser flake", md)
        _ref, back = rc.read_script(md)
        self.assertEqual(back["hook.title"]["text"], rc.facts_title(f))              # commented: not used
        _ref, back = rc.read_script(md.replace("# show hook.title: Fix", "show hook.title: Fix"))
        self.assertEqual(back["hook.title"]["text"], "Fix the parser flake")       # uncommented: used
        # N-g: two hook.title lines become one, in the first one's place
        self.assertEqual(sum(1 for k in back if k == "hook.title"), 1)
        self.assertEqual([k for k in back if back[k]["scene"] == "hook"][:2], ["hook.kicker", "hook.title"])

    def test_tolerates_any_line(self):
        p = self.tmp / "odd.jsonl"
        p.write_text('[1,2]\n"x"\n{"type": "assistant", "message": "not a dict"}\n'
                     '{"type": "user", "message": {"content": 5}}\n{"type": "assistant", "message": {"content": '
                     '[{"type": "tool_use", "name": "Bash", "input": "not a dict"}]}}\n', encoding="utf-8")
        s = rc.parse_session(p)
        self.assertEqual(len(s["uses"]), 1)
        (self.tmp / "empty.jsonl").write_text("\n\nnot json\n", encoding="utf-8")
        with self.assertRaises(ShowtimeError):
            rc.parse_session(self.tmp / "empty.jsonl")


class TestAllowList(Base):
    def test_only_repo_files_relative(self):
        f = self.facts
        self.assertEqual([x["path"] for x in f["files"]], ["src/parser.py"])
        self.assertEqual((f["files"][0]["read"], f["files"][0]["edited"]), (1, 1))
        self.assertEqual(f["files_outside"], 2)            # the memory file and the .env

    def test_tools_and_commands(self):
        f = self.facts
        tools = dict(f["tools"])
        self.assertEqual(tools["Bash"], 5)
        self.assertEqual(tools["MCP tool"], 1)             # never the server's or the tool's own name (RS9)
        self.assertEqual(rc.tool_display("mcp__zorgcrm__lookup_zorgcorp_invoices"), "MCP tool")
        self.assertEqual(rc.tool_display("ZorgCustomTool"), rc.OTHER)
        self.assertEqual(rc.tool_display("Edit"), "Edit")
        cmds = dict(f["commands"])
        for want in ("python -m pytest", "tail", "curl", "jq", "ssh", "python3", "git add",
                     "git commit"):
            self.assertIn(want, cmds)
        self.assertNotIn("export", cmds)
        self.assertNotIn("cd", cmds)

    def test_tests_red_to_green(self):
        t = self.facts["tests"]
        self.assertEqual([(x["passed"], x["failed"], x["ok"]) for x in t],
                         [(11, 1, False), (12, 0, True), (12, 0, True)])
        self.assertEqual(t[-1]["unit"], "test files")
        st = rc.test_story(t)
        self.assertTrue(st["red_to_green"])
        self.assertEqual(st["red"], 1)

    def test_diff_from_the_commit_it_made(self):
        d = self.facts["diff"]
        self.assertEqual(self.facts["commits"], 1)
        self.assertEqual((d["source"], d["files"], d["additions"], d["deletions"]), ("commits", 1, 4, 1))
        self.assertEqual(d["per_file"], {"src/parser.py": [4, 1]})

    def test_diff_since(self):
        f = rc.collect(self.ses, self.top, self.roots, since=self.base)
        self.assertEqual((f["diff"]["source"], f["diff"]["additions"]), ("since", 4))
        with self.assertRaises(ShowtimeError):
            rc.collect(self.ses, self.top, self.roots, since="no-such-ref")

    def test_request_without_paths_keys_or_urls(self):
        r = dict(rc.suggestions_for(self.ses))["your first message"]
        self.assertTrue(r.startswith("Fix the flaky parser test in acme."), r)
        for bad in ("/", "sk-", "http", "Zorblax"):
            self.assertNotIn(bad, r)
        # RS5: free text is never kept in the facts (facts.json, the project's recap.json)
        self.assertNotIn("request", self.facts)
        self.assertNotIn("suggested_title", self.facts)
        self.assertNotIn("flaky parser", json.dumps(self.facts))

    def test_nothing_planted_reaches_the_script_or_the_facts(self):
        lines, _ = rc.hard_filter(rc.script_lines(self.facts))
        text = rc.write_script(lines, self.facts["ref"]) + json.dumps(self.facts)
        for bad in PLANTED + (str(self.repo),):
            self.assertNotIn(bad, text, bad)

    def test_repo_must_be_known(self):
        ses = dict(self.ses, cwds=rc.Counter({"/nonexistent/folder": 3}))
        with self.assertRaises(ShowtimeError):
            rc.repo_roots(ses)
        top, roots = rc.repo_roots(ses, str(self.repo))
        self.assertEqual(top, str(self.repo))

    def test_removed_worktree_paths(self):
        roots = [str(self.repo) + "/.claude/worktrees/agent-x", str(self.repo)]
        self.assertEqual(rc.rel_path(str(self.repo) + "/.claude/worktrees/agent-x/src/a.py", roots), "src/a.py")
        self.assertEqual(rc.rel_path(str(self.repo) + "/.claude/worktrees/agent-y/src/b.py", roots), "src/b.py")
        self.assertIsNone(rc.rel_path(str(self.repo) + "/.git/config", roots))
        self.assertIsNone(rc.rel_path(str(self.repo) + "/config/.env", roots))
        self.assertIsNone(rc.rel_path("/elsewhere/src/a.py", roots))
        self.assertIsNone(rc.rel_path("~/notes.md", roots))


class TestCommands(Base):
    def test_program_and_subcommand_only(self):
        L = rc.command_labels
        self.assertEqual(L("cd /x/y && git -C /x/y commit -q -m 'secret message'"), ["git commit"])
        self.assertEqual(L("ssh -o ConnectTimeout=5 buildhost 'pytest -q'"), ["ssh"])
        self.assertEqual(L("scp a.txt host:/tmp/"), ["scp"])
        self.assertEqual(L("curl -s https://x.example/api?token=abc | jq ."), ["curl", "jq"])
        # never a script path, inside the repository or not (the director's allow-list pivot)
        self.assertEqual(L("FOO=1 BAR=2 timeout 600 python3 tests/run_all.py -k x 2>&1 | tail -5"), ["python3", "tail"])
        self.assertEqual(L("cd sub && python3 run.py"), ["python3"])
        self.assertEqual(L("python - <<'EOF'\nimport os; os.system('rm -rf x')\nprint(1)\nEOF\necho done"),
                         ["python", "echo"])
        self.assertEqual(L('cat <<< "word"; ls'), ["cat", "ls"])                      # a here-string is not a heredoc
        self.assertEqual(L("grep -n foo src/a.py 2>/dev/null; ls"), ["grep", "ls"])
        self.assertEqual(L("~/.venv/bin/python3.12 -m pytest -q"), ["python3 -m pytest"])
        self.assertEqual(L("npm run build && npm test"), ["npm run", "npm test"])
        self.assertEqual(L("echo 'unterminated"), ["echo"])
        self.assertEqual(L("python -m clientname.tool --x"), ["python"])          # a project's own package
        self.assertEqual(L("python3 -m http.server 8000"), ["python3"])             # not a runner module
        self.assertEqual(L("make deploy-clientname && make test"), ["make", "make test"])
        self.assertEqual(L("rake secret_task; bundle exec rspec"), ["rake", "bundle exec"])
        self.assertEqual(L("./bin/tool --x"), ["other"])                              # the user's own program

    # two adversarial review grids: every command row shows nothing private
    ADVERSARIAL_COMMANDS = [
        "python3 tools/zorg_export_persisted_cwd.py", "cd /outside && ./zorg_deploy_prod.sh",
        "/Users/me/clients/zorgcorp/bin/zorgsync --push", "/Users/me/clients/zorgcorp/bin/zorgabsrun.py",
        "cd C:\\Users\\me\\zorgwin && python tools\\zorgwin.py", "cd C:/zorgfwd && python tools/zorgfwd.py",
        "& 'C:\\zorgps\\zorgpsrun.ps1'", "Set-Location C:\\zorgsl; python tools\\zorgsl.py",
        "Push-Location C:\\zorgpush; python tools\\zorgpushps.py",
        "Set-Location -Path C:\\zorgslp; python tools\\zorgslp.py", "cd -Path C:\\zorgcdp; python tools\\zorgcdp.py",
        "cd -P /out && python3 tools/zorgcdP.py", "command cd /out && python3 tools/zorgcommand.py",
        "builtin cd /out && python3 tools/zorgbuiltin.py", "cd -- /out && python3 tools/zorgcddash.py",
        "{ cd /out; python3 tools/zorgbrace.py; }", "env -C /out python3 tools/zorgenvC.py",
        "CDPATH=/parent cd zorgcorp && python3 tools/zorgcdpath.py", "zorgctl sync --all", "acme-zorg-deploy --prod",
        "git -C /out commit -qm zorgmsg", 'cd "/out/Zorg Client" && python3 tools/zorgspace.py',
        'python3 "/out/Zorg Client/zorgspace2.py"', "pushd /out && popd && python3 tools/zorgpopd.py",
        "cd /out; cd -; python3 zorgdash.py", "(cd /out && python3 zorgsub.py)", "bash -c 'cd /out && ./zorgx.sh'",
        "cd /repo/../outside && python3 zorgup.py", "make -C /out zorg-deploy", "npx zorg-cli", "uv run zorg-tool",
        "docker exec zorgcontainer ls", "git switch zorg-client-branch", "git zorg-alias", "cargo zorg-deploy",
        "kubectl zorgctl-plugin", "gh zorg-ext run", "showtime zorg"]

    def test_adversarial_command_rows_show_nothing_private(self):
        for cmd in self.ADVERSARIAL_COMMANDS:
            for cwd in ("/repo", "/outside"):
                labels = rc.command_labels(cmd, cwd=cwd, roots=["/repo"])
                text = " ".join(labels)
                self.assertNotIn("zorg", text.lower(), cmd)
                self.assertNotRegex(text, r"[/\\\\]", cmd)
                for lab in labels:
                    self.assertTrue(lab == rc.OTHER or lab.split()[0] in rc.ALLOWED_PROGRAMS, (cmd, lab))

    def test_amended_reset_and_failing_follow_up_commits(self):
        """N-j: an amended or reset commit (its object still exists, outside the history) is not counted.
        N-i: a real commit counts even when a later step of the same call fails (a rejected push)."""
        repo = self.tmp / "nj-repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "one")
        (repo / "a.txt").write_text("b\n", encoding="utf-8")
        git(repo, "commit", "-q", "-am", "two")
        two = git(repo, "rev-parse", "HEAD").strip()
        git(repo, "commit", "-q", "--amend", "-m", "two, amended")
        amended = git(repo, "rev-parse", "HEAD").strip()
        (repo / "a.txt").write_text("c\n", encoding="utf-8")
        git(repo, "commit", "-q", "-am", "three")
        three = git(repo, "rev-parse", "HEAD").strip()
        git(repo, "reset", "-q", "--hard", "HEAD~1")
        top = rc.git_toplevel(str(repo))
        self.assertEqual(rc.verified_commits(top, [two[:7], three[:7], amended[:7]]), [amended])
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(repo), "sessionId": "s",
               "message": {"content": "Commit and push."}},
              {"type": "assistant", "timestamp": "2026-10-01T10:00:05Z", "cwd": str(repo), "sessionId": "s",
               "message": {"id": "m", "content": [{"type": "tool_use", "id": "t", "name": "Bash",
                                                   "input": {"command": "git commit -am x && git push"}}]}},
              {"type": "user", "timestamp": "2026-10-01T10:00:09Z", "cwd": str(repo), "sessionId": "s",
               "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "is_error": True,
                                        "content": "[main %s] x\n 1 file changed\n! [rejected] main -> main" %
                                        amended[:7]}]}}]
        p = self.tmp / "nj.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
        ses = rc.parse_session(p)
        self.assertEqual(rc.collect(ses, *rc.repo_roots(ses))["commits"], 1)

    def test_commits_count_only_inside_the_repository(self):
        """RS6 (and N3, N-a): a commit counts only when the hash `git commit` printed exists in this
        repository's history. A commit made in another repository, however the command got there (GIT_DIR, eval cd,
        source, a function, if cd, pushd +1, a nested git init, git -C), prints a hash this repository does not have."""
        other = self.tmp / "other-repo"
        if not other.exists():
            other.mkdir()
            git(other, "init", "-q", "-b", "main")
            (other / "x.txt").write_text("x\n", encoding="utf-8")
            git(other, "add", "-A")
            git(other, "commit", "-q", "-m", "zorg outside")
        outside_sha = git(other, "rev-parse", "--short", "HEAD").strip()
        self.assertEqual(rc.verified_commits(self.top, [outside_sha, "deadbee", self.fix]),
                         [git(self.repo, "rev-parse", self.fix).strip()])
        evasions = ["GIT_DIR=%s/.git git commit -m x" % other, "env GIT_DIR=%s/.git git commit -m x" % other,
                    "export GIT_DIR=%s/.git; git commit -m x" % other, "eval cd %s && git commit -m x" % other,
                    "source %s/go.sh && git commit -m x" % other, "f() { cd %s; }; f; git commit -m x" % other,
                    "if cd %s; then git commit -m x; fi" % other, "pushd %s; pushd %s; pushd +1; git commit" % (other, self.repo),
                    "mkdir d && cd d && git init && git commit -m x", "git -C %s commit -qm zorgmsg" % other]
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo), "sessionId": "s",
               "message": {"content": "Commit things."}}]
        for i, cmd in enumerate(evasions):
            ev.append({"type": "assistant", "timestamp": "2026-10-01T10:01:%02dZ" % i, "cwd": str(self.repo),
                       "sessionId": "s", "message": {"id": "m%d" % i, "content": [
                           {"type": "tool_use", "id": "c%d" % i, "name": "Bash", "input": {"command": cmd}}]}})
            ev.append({"type": "user", "timestamp": "2026-10-01T10:01:%02dZ" % i, "cwd": str(self.repo),
                       "sessionId": "s", "message": {"content": [{"type": "tool_result", "tool_use_id": "c%d" % i,
                                                                  "content": "[main %s] zorg\n 1 file changed" %
                                                                  outside_sha}]}})
        p = self.tmp / "commits.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
        ses = rc.parse_session(p)
        f = rc.collect(ses, self.top, self.roots)
        self.assertEqual((f["commits"], f["diff"]["source"]), (0, "none"))
        self.assertEqual(self.facts["commits"], 1)                     # the fixture's own commit, printed and real

    def test_only_worktree_folders_become_roots(self):
        """N2: a removed folder under the repository that is not a worktree is not a root of its own."""
        ses = dict(self.ses, cwds=rc.Counter({str(self.repo): 5, str(self.repo / "build" / "gone"): 2,
                                              str(self.repo / ".claude" / "worktrees" / "agent-x"): 1}))
        top, roots = rc.repo_roots(ses)
        self.assertNotIn(str(self.repo / "build" / "gone"), roots)
        self.assertIn(str(self.repo / ".claude" / "worktrees" / "agent-x"), roots)
        self.assertEqual(rc.rel_path(str(self.repo / "build" / "x.py"), roots), "build/x.py")

    def test_outside_cwd_in_a_transcript(self):
        """B1 end to end: a call whose recorded working folder is outside the repository."""
        outside = self.tmp / "outside"
        outside.mkdir(exist_ok=True)
        p = self.tmp / "b1.jsonl"
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo), "sessionId": "s",
               "message": {"content": "Fix the build."}},
              {"type": "assistant", "timestamp": "2026-10-01T10:00:05Z", "cwd": str(outside), "sessionId": "s",
               "message": {"id": "m1", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                    "input": {"command": "python3 tools/zorg_export.py && ./zorg.sh"}}]}},
              {"type": "user", "timestamp": "2026-10-01T10:00:06Z", "cwd": str(outside), "sessionId": "s",
               "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}]
        p.write_text("\r\n".join(json.dumps(e) for e in ev) + "\r\n", encoding="utf-8")   # CRLF on purpose
        ses = rc.parse_session(p)
        f = rc.collect(ses, *rc.repo_roots(ses, str(self.repo)))
        self.assertNotIn("zorg", json.dumps(f))
        self.assertEqual(dict(f["commands"]), {"python3": 1, rc.OTHER: 1})

    def test_known_subcommands_only(self):
        """S7: aliases, plugins and extensions are the user's own names."""
        L = rc.command_labels
        for cmd, want in (("git zorg-alias", "git"), ("cargo zorg-deploy", "cargo"), ("kubectl zorgctl-plugin", "kubectl"),
                          ("gh zorg-ext run", "gh"), ("git status", "git status"), ("gh pr view 3", "gh pr"),
                          ("showtime render x", "showtime render"), ("showtime zorg", "showtime"),
                          ("docker compose up", "docker compose")):
            self.assertEqual(L(cmd), [want], cmd)

    def test_test_commands(self):
        T = rc.is_test_command
        for yes in ("pytest -q", "python -m unittest discover", "python3 tests/run_all.py", "npm test",
                    "cd x && python3 tests/test_voice.py -v", "ssh box 'cd w && python3 tests/run_all.py --fast'",
                    "bash -c 'go test ./...'", "cargo test", "node --test", "npx jest --ci", "uv run pytest",
                    "poetry run pytest -x", "docker exec -it app pytest", "sudo -u ci python3 -m pytest",
                    "npm run test:unit", "make test"):
            self.assertTrue(T(yes), yes)
        for no in ("grep -n test_voice tests/test_voice.py", "sed -n 1,40p tests/test_x.py", "cat pytest.ini",
                   "git add tests/test_x.py", "ls tests",
                   # S3: installs, lint and type checks of test files, version and info queries
                   "pip install pytest", "uv pip install pytest", "npm i -D jest", "pip show pytest",
                   "ruff check tests/test_parser.py", "black tests/test_x.py", "mypy tests/test_x.py",
                   "flake8 tests/test_x.py", "python -m py_compile tests/test_x.py", "pytest --version",
                   "echo pytest", "npm install"):
            self.assertFalse(T(no), no)

    def test_counts_per_runner(self):
        C = rc.test_counts
        self.assertEqual(C("...\n59/60 test files passed in 12.0s wall"), {"passed": 59, "failed": 1, "unit": "test files"})
        self.assertEqual(C("Ran 12 tests in 0.3s\n\nFAILED (failures=2, errors=1, skipped=1)")["passed"], 8)
        self.assertEqual(C("Ran 5 tests in 0.1s\n\nOK"), {"passed": 5, "failed": 0, "unit": "tests"})
        self.assertEqual(C("===== 3 failed, 40 passed, 2 skipped in 1.20s ====="), {"passed": 40, "failed": 3,
                                                                                   "unit": "tests"})
        self.assertEqual(C("Tests:       1 failed, 9 passed, 10 total"), {"passed": 9, "failed": 1, "unit": "tests"})
        self.assertEqual(C("test result: ok. 7 passed; 0 failed; 0 ignored"), {"passed": 7, "failed": 0, "unit": "tests"})
        self.assertEqual(C("# pass 4\n# fail 1\n"), {"passed": 4, "failed": 1, "unit": "tests"})
        self.assertEqual(C("ok  \tacme/x\t0.1s\nFAIL\tacme/y\t0.2s\n"), {"passed": 1, "failed": 1, "unit": "packages"})
        self.assertEqual(C("FAILED (failures=1)")["status"], "fail")
        self.assertIsNone(C("no counts here"))


class TestHardFilter(Base):
    def test_keys_and_tokens(self):
        hexrun = "0123456789abcdef" * 2
        for line in ("key sk-test-notarealkey0000000000", "AKIAIOSFODNN7EXAMPLE", "token gh" + "p_" + "A1b2C3d4" * 5,
                     "commit " + hexrun, "blob " + "QmFzZTY0IGlzIG5vdCBhIGtleSBidXQgbG9va3MgbGlrZSBvbmU9",
                     'password = "hunter22hunter"', "xo" + "xb-1234567890-abcdefghij",
                     # B2: labelled values mid-sentence, AWS's slashed secret shape, lower-case+digit tokens,
                     # hex of 20-31 characters
                     "use password: hunter2xyz for it", "token: abcd1234efgh5678ijkl please",
                     "the api key 9f8e7d6c5b4a3210fedc here", "secret=s3cr3tvalue", "Authorization: Bearer abcdefghij123456",
                     "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "a1b2c3d4e5f6" * 3 + "a1b2",
                     "deadbeef0123456789ab", "x " + "0f" * 12 + " y"):
            self.assertEqual(rc.unsafe_reason(line), "key", line)

    def test_request_drops_secrets_hosts_and_paths(self):
        """B2 + S1: a key's name goes with its value; hosts, IPs, user@host, slashed words and ~user go."""
        r = rc.clean_request("Deploy to zorg-prod.internal (10.1.2.3) now. Use password: hunter2xyz and token: "
                             "abcd1234efgh5678ijkl, the api key 9f8e7d6c5b4a3210fedc, notes in ../zorg-client/plan.md "
                             "and ~favio/notes, then ssh deploy@zorgbox to 10.9.8.7 or fe80::1:2:3 and zorgcorp.com "
                             "and /zorgsecret. Keep it small. Reach me via ops@zorg.dev today.", limit=400)
        for bad in ("zorg", "10.1.2.3", "hunter2xyz", "abcd1234", "9f8e7d6c", "favio", "deploy@", "10.9.8.7",
                    "fe80", "secret", "password", "token"):
            self.assertNotIn(bad, r.lower(), r)
        self.assertEqual(r, "")                  # the first sentence names a host: no later sentence takes its place
        self.assertEqual(rc.clean_request("Fix the parser. Keep it small. Use password: hunter2xyz now. Then ship."),
                         "Fix the parser. Keep it small.")
        for line in ("zorg-prod.internal", "at 10.1.2.3", "deploy@zorgbox", "zorgcorp.com/admin/keys", "~favio/notes",
                     "see /zorgsecret now"):
            self.assertIsNotNone(rc.unsafe_reason(line), line)

    def test_request_suggestion_rows(self):
        """RS1-RS3: the request is never film text; as a suggestion it keeps ordinary sentences
        (CI/CD, versions) and drops split keys, passcodes, licence keys, value-like words and hosts on any TLD."""
        R = rc.clean_request
        self.assertEqual(R("Fix the CI/CD flow so the release job stops failing. Keep the changes small."),
                         "Fix the CI/CD flow so the release job stops failing. Keep the changes small.")
        self.assertEqual(R("Update the v1.2/v1.3 notes in the changelog."), "Update the v1.2/v1.3 notes in the changelog.")
        # RS5: a key word with anything after it, letters mixed with digits whatever the punctuation, x:y,
        # three or more digit groups
        for bad in ("Fix the token counting bug in the tokenizer.", "Make it fail when the password is wrong.",
                    "Log in with zorgadmin:Zx9Qw8Er7Ty6 now.", "Log in as admin:Zx9Qw8Er7Ty6 now.",
                    "Use zorgadmin:hunter2 now.", "Use Tr0ub4dor&3 there.", "Use Hunter2! now.",
                    "Key Q9w8E7r6,T5y4U3i2 here.", "The password is swordfish.",
                    "The password is CorrectHorseBatteryStaple today.", "Card 4111 1111 1111 1111 ok.",
                    "Pay with card 4111 1111 1111 1111 today.", "Pay with card 4111-1111-1111-1111 today."):          # N-j: a sentence long enough to be kept
            self.assertEqual(R(bad), "", bad)
        for bad in ("The value is Q9w8E7r6T5y4U3i2 O1p0A9s8D7f6G5h4 for prod.", "Use the passcode Zx9Qw8Er7Ty6 for the box.",
                    "The license key is Q9W8-E7R6-T5Y4-U3I2 now.", "Log in as zorgadmin with Zx9Qw8Er7Ty6Ab today.",
                    "Open portal.zorgagency.gov to check.", "Mirror at zorgmirror.cl for Chile.",
                    "Deploy to zorg-prod.internal now.", "Ping 10.1.2.3 first.", "ssh deploy@zorgbox now.",
                    "See zorgcorp.com/admin/keys today.", "Read ../zorg-client/plan.md first.", "Check ~zorguser/notes.",
                    "Look in /zorgsecret now.", "Use password: hunter2xyz for it.", "token: abcd1234efgh5678ijkl here.",
                    "Use api key 9f8e7d6c5b4a3210fedc here.", "The key is wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY ok.",
                    "Token a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2 ok.", "Hex deadbeef0123456789abcdef01 ok.",
                    "Run it at socket.io now.", "Long " + "a-" * 300 + " word."):
            self.assertEqual(R(bad), "", bad)

    def test_absolute_paths_urls_and_mail(self):
        for line, why in (("see /Users/someone/x.py", "absolute path"), ("/etc/hosts", "absolute path"),
                          ("in ~/notes", "absolute path"), ("C:\\Users\\me\\a.txt", "absolute path"),
                          ("run /opt/tool/bin/x", "absolute path"), ("at /srv/app", "absolute path"),
                          ("https://example.com/a", "URL"), ("mail me@example.com", "e-mail")):
            self.assertEqual(rc.unsafe_reason(line), why, line)

    def test_safe_lines_stay(self):
        for line in ("skills/showtime/runtime/stage.js", "59/60", "+12 \u221203", "git commit \u00d74",
                     "43 min \u00b7 80 turns \u00b7 83 tool calls", "Fix the nightly css_clock flake",
                     "python3 tests/run_all.py \u00d74", "read/edit/run", "Recap \u00b7 Claude Code session \u00b7 2 Oct 2026",
                     "tests/test_parser.py", "a_very_long_snake_case_identifier_name_in_a_path/x.py"):
            self.assertIsNone(rc.unsafe_reason(line), line)

    def test_long_tokens_stay_fast(self):
        """Review 2 #1: one long unbroken run (60 KB of `a.`) through every pattern and the request cleaner."""
        import time
        for x in ("a." * 30000, "a" * 60000, "a-" * 30000, "a.a" * 20000 + "@", "www." * 15000, "x://" * 15000):
            t = time.time()
            self.assertEqual(rc.unsafe_reason(x), "key")
            self.assertEqual(rc.clean_request("Fix it. Then " + x + " now."), "Fix it.")
            rc._URL.search(x)                     # the patterns themselves, unguarded, on the whole run
            rc._EMAIL.search(x)
            self.assertLess(time.time() - t, 1.5, x[:8])

    def test_pasted_code_and_long_commands_stay_fast(self):
        """RS8 and N-f: a 218 KB TypeScript paste as the request; a 1 MB command token."""
        import time
        ts = ("function f(m: Map<string, Array<number>>): Promise<Result> { return g<T>(m); }\n" * 2800)
        t = time.time()
        rc.clean_request("Refactor the parser. " + ts)
        rc._strip_tags(ts)
        self.assertLess(time.time() - t, 1.0)
        t = time.time()
        rc.command_labels("python3 -c " + "x" * 1000000)
        self.assertLess(time.time() - t, 2.0)

    def test_long_tagged_blocks_never_become_the_request(self):
        """RS11: a tagged block longer than the 8 KB cut is removed whole before the cut; an unclosed block
        ends the text. N-o: a 6+ digit run ends the suggestion."""
        p = self.tmp / "tagged.jsonl"
        note = "Zorg private note: the client is Zorgcorp and the launch slips to Friday because of the audit. "
        texts = ["<system-reminder>\n" + note + "x " * 6000 + "\n</system-reminder>\nFix the parser bug.",
                 "<ide_selection>The user selected these lines: " + note + "y " * 6000 + "\nFix the parser bug."]
        for i, text in enumerate(texts):
            ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo), "sessionId": "s",
                   "message": {"content": text}},
                  {"type": "assistant", "timestamp": "2026-10-01T10:01:00Z", "cwd": str(self.repo), "sessionId": "s",
                   "message": {"id": "m", "content": [{"type": "text", "text": "ok"}]}}]
            p.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
            ses = rc.parse_session(p)
            self.assertNotIn("Zorg", ses["request"], i)
            sugg = dict(rc.suggestions_for(ses)).get("your first message", "")
            self.assertNotIn("Zorg", sugg, i)
        self.assertEqual(dict(rc.suggestions_for(rc.parse_session(p))).get("your first message"), None)  # unclosed
        self.assertEqual(rc.clean_request("Ticket 482193 is due. Ship it."), "")
        self.assertEqual(rc.clean_request("Fix it. Ref 12345678901234 here."), "Fix it.")

    def test_digit_groups_any_separator(self):
        """RS20: digit groups split by separators of any length (-- , ...) are refused, in a line and as a request
        suggestion."""
        for text in ("Card 4111 -- 1111 -- 1111 -- 1111 here", "SSN 123 -- 45 -- 6789", "4111 ... 1111 ... 1111 ... 1111"):
            with self.subTest(text=text):
                self.assertTrue(rc.free_text_refused(text), text)
                self.assertEqual(rc.clean_request("Fix it. Pay " + text + ". Keep it small."), "Fix it.")

    def test_digit_groups_stay_linear(self):
        """The digit-group rule on long digit runs (it was quadratic: 20 KB took 11-15 s), and on long separator runs."""
        import time
        t = time.time()
        rc._DIGIT_GROUPS.search("1 -- " * 40000)                          # 200 KB of separators: linear
        self.assertLess(time.time() - t, 1.0)
        for big in ("1" * 20000, "1" * 100000 + "-12-34", ("12-" * 20000) + "x"):
            t = time.time()
            rc._clean_words("Fix it " + big + " now.")
            with self.subTest(n=len(big)):
                self.assertLess(time.time() - t, 1.0)

    def test_hidden_characters_lookalikes_and_digit_chains(self):
        """B1: a format or bidi control character (zero-width space, word joiner, soft hyphen, ...) refuses the line in
        the hard filter, and every rule judges an NFKC-folded copy. S1/S2: digit groups that make a long number across
        short words or side by side. S3: lookalike digits and punctuation. The review's adversarial inputs."""
        zw = "\u200b"
        refused = ["Card " + zw.join("4111111111111111") + " ends it.",
                   "Card " + "\u2060".join("4111111111111111") + " ends it.",
                   "Card " + "\u00ad".join("4111111111111111") + " ends it.",
                   "Deploy to 10" + zw + ".1.2.3 now.", "Pay \u202e1111 4111\u202c now.",
                   "4111 1111", "1111 1111", "55512 34567", "4111 1111 turns \u00b7 1111 1111 tool calls \u00b7 5 commands",
                   "Card 4111 x 1111 x 1111 x 1111 here.", "Pay 4111 then 1111 then 1111 then 1111 now.",
                   "SSN 123 and 45 and 6789.", "\u2463\u2460\u2460\u2460 \u2460\u2460\u2460\u2460 \u2460\u2460\u2460\u2460",
                   "\u2074\u00b9\u00b9\u00b9 \u00b9\u00b9\u00b9\u00b9 \u00b9\u00b9\u00b9\u00b9 \u00b9\u00b9\u00b9\u00b9",
                   "\uff0fUsers\uff0ffavio\uff0f.ssh\uff0fid rsa", "\u2215Users\u2215favio\u2215.ssh\u2215id rsa",
                   "favio\uff20example\uff0ecom", "\uff14\uff11\uff11\uff11 \uff11\uff11\uff11\uff11 \uff11\uff11\uff11\uff11"]
        for text in refused:
            with self.subTest(refused=text):
                self.assertTrue(rc.free_text_refused(text), repr(text))
        for text in refused[:5]:
            with self.subTest(hard_filter=text):
                self.assertEqual(rc.unsafe_reason(text), "hidden character")
        for text in ("between 2024 and 2026", "12 34", "Ended green: 5/5 tests passed \u00b7 1 commit",
                     "140 turns \u00b7 155 tool calls \u00b7 128 commands", "+305 \u221217", "Read 5",
                     "In 42 minutes, a sub-agent edited 6 files and took the tests from red to green."):
            with self.subTest(kept=text):
                self.assertFalse(rc.free_text_refused(text), text)
        # the kept text is never rewritten: a refused line is dropped, a kept one stays as written
        self.assertEqual(rc.clean_request("Fix the \uff32EADME docs."), "Fix the \uff32EADME docs.")

    def test_natural_numbers_pass_and_spread_numbers_do_not(self):
        """The guard targets accidental private text in natural forms. Ordinary lines with numbers pass (they passed
        before the digit-chain rule); a number spread with single spaces, invisible marks or across sentences is
        refused; the chain rule and the folding stay linear."""
        R = rc.free_text_refused
        for text in ("From 2024-2026.", "Renders at 1920\u00d71080.", "Closes #1234 #5678.",
                     "Tested on Python 3.11, 3.12 and 3.13.", "Node 18, 20 and 22 pass.", "between 2024 and 2026",
                     "12 of 34 tests, 56 skipped.", "Edited 3 files in 2 commits, 45 lines.", "Ship it \U0001F468\u200d\U0001F4BB today.",
                     "Proud \U0001F3F3\ufe0f\u200d\U0001F308 flag."):
            with self.subTest(passes=text):
                self.assertFalse(R(text), text)
        card = "4111111111111111"
        spread = ["Card " + " ".join(card) + " ends it.", "Card 4111. Then 1111. Then 1111. Then 1111.",
                  "Re\u200bfactor"] + ["Card " + sep.join(card) + " ends it." for sep in (
                      "\u0301", "\ufe0f", "\u034f", "\u115f", "\u1160", "\u3164", "\uffa0", "\u2800", "\U000e0000",
                      "\U000e0080")]
        for text in spread:
            with self.subTest(refused=text):
                self.assertTrue(R(text), repr(text))
        import time
        for f, big in ((R, "4 1 " * 75000), (rc._digit_chain, "1 xxxxx " * 37500), (rc._digit_chain, "4 1 " * 75000),
                       (R, "4\u0301" * 150000), (rc._clean_words, "4 1 " * 75000)):
            t = time.time()
            f(big)
            with self.subTest(timing=(f.__name__, big[:6])):
                self.assertLess(time.time() - t, 1.0)

    def test_most_used_is_capped(self):
        """S4: a "Most used" line is recap's own only with at most 4 parts, distinct labels and counts 1-99999."""
        F = {"files": []}
        own = lambda t: rc.own_line("timeline.commands", t, {}, F)  # noqa: E731
        self.assertEqual(own("Most used:  git commit \u00d72  \u00b7  python3 -m pytest \u00d74"), "own")
        for text in ("Most used:  " + "  \u00b7  ".join("git \u00d74111" for _ in range(30)),
                     "Most used:  git \u00d74111  \u00b7  git \u00d71111",
                     "Most used:  git \u00d74111  \u00b7  npm \u00d71111  \u00b7  make \u00d71111  \u00b7  cargo \u00d71111  \u00b7  ls \u00d71",
                     "Most used:  git \u00d704111", "Most used:  git \u00d70"):
            with self.subTest(text=text):
                self.assertNotEqual(own(text), "own")

    def test_prefixed_key_shapes(self):
        """Review 2 #2: vendor-prefixed keys are caught by their prefix, whatever the rest looks like (assembled here:
        the repository's secret scanner refuses them as literals)."""
        tail16 = "abcdefghijklmnop"
        for key in ("sk" + "_live_" + tail16 + "qrst", "sk" + "_test_" + tail16, "rk" + "_live_" + tail16,
                    "pk" + "_live_" + tail16, "gh" + "o_" + tail16 + "abcd", "gh" + "s_" + tail16 + "abcd",
                    "gh" + "u_" + tail16 + "abcd", "github" + "_pat_" + tail16 + "_x", "xo" + "xp-1234-" + tail16,
                    "xo" + "xb-" + tail16, "gl" + "pat-" + tail16, "AI" + "za" + tail16 + "ABCDEFGHIJKLMN",
                    "AS" + "IA" + "ABCDEFGHIJKLMNOP", "hf" + "_" + tail16 + "abcdef", "SG" + "." + tail16 + "x",
                    "np" + "m_" + tail16 + "abcdefgh", "py" + "pi-" + tail16, "wh" + "sec_" + tail16):
            self.assertEqual(rc.unsafe_reason("the key " + key + " here"), "key", key)
            self.assertEqual(rc.unsafe_reason(key), "key", key)
        for ok in ("pk_reader is a name", "sk-like words", "ghost_writer.py", "skills/showtime/x.py"):
            self.assertIsNone(rc.unsafe_reason(ok), ok)

    def test_user_edits_are_filtered_too(self):
        facts = {"ref": "abcdef1234"}
        L = rc.OrderedDict([("hook.title", {"scene": "hook", "kind": "show", "text": "A title"})])
        md = rc.write_script(L, facts["ref"])
        md = md.replace("show hook.title: A title", "show hook.title: A title\nshow hook.request: see /Users/me/secret.txt"
                        "\nsay hook.say: the key is sk-test-notarealkey0000000000\nshow hook.meta: fine line")
        ref, lines = rc.read_script(md)
        kept, dropped = rc.hard_filter(lines)
        self.assertEqual(ref, "abcdef1234")
        self.assertEqual(list(kept), ["hook.title", "hook.meta"])
        self.assertEqual(dict(dropped), {"absolute path": 1, "key": 1})


class TestRobustness(Base):
    def test_compact_summary_is_not_the_request(self):
        """S2: a compaction summary is assistant-written; the request is the next real message."""
        p = self.tmp / "compact.jsonl"
        ev = [{"type": "user", "isCompactSummary": True, "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo),
               "message": {"content": "This session is being continued from a previous conversation. Summary..."}},
              {"type": "user", "timestamp": "2026-10-01T10:01:00Z", "cwd": str(self.repo),
               "message": {"content": "Now add the docs page."}}]
        p.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
        self.assertEqual(rc.parse_session(p)["request"], "Now add the docs page.")

    def test_only_command_output_is_kept_and_cut(self):
        """S4: Read output is never kept; a command's output keeps its last 64 KB; long lines stay fast."""
        p = self.tmp / "big.jsonl"
        long_line = "= passed " * 40000 + "\n========== 3 passed in 0.10s =========="
        ev = [{"type": "assistant", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo),
               "message": {"id": "m1", "content": [
                   {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": str(self.repo / "a.py")}},
                   {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
              {"type": "user", "timestamp": "2026-10-01T10:00:09Z", "cwd": str(self.repo), "message": {"content": [
                  {"type": "tool_result", "tool_use_id": "r1", "content": "R" * 100000},
                  {"type": "tool_result", "tool_use_id": "b1", "content": long_line}]}}]
        p.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
        ses = rc.parse_session(p)
        self.assertEqual(ses["results"]["r1"]["text"], "")
        self.assertLessEqual(len(ses["results"]["b1"]["text"]), rc.RESULT_KEEP)
        import time
        t = time.time()
        c = rc.test_counts("= passed " * 35000)                     # one 300 KB line, no summary
        self.assertIsNone(c)
        self.assertLess(time.time() - t, 2.0)
        f = rc.collect(ses, *rc.repo_roots(ses))
        self.assertEqual((f["tests"][0]["passed"], f["tests"][0]["ok"]), (3, True))

    def test_active_time_leaves_out_idle_gaps(self):
        """S6: a session resumed the next morning is not hours "of work"."""
        self.assertEqual(rc.active_seconds([0, 60, 120, 120 + 8 * 3600, 120 + 8 * 3600 + 30]), 150.0)
        self.assertLessEqual(self.facts["duration"], self.facts["span"])

    def test_symlinked_paths(self):
        """S8: a transcript that names the repository through a symlink still maps its files."""
        link = self.tmp / "link-to-acme"
        if not link.exists():
            os.symlink(str(self.repo), str(link))
        self.assertEqual(rc.rel_path(str(link / "src" / "parser.py"), self.roots), "src/parser.py")

    def test_since_is_checked(self):
        """N1: --since never reaches git as an option."""
        for bad in ("--output=/tmp/x", "no-such-ref"):
            with self.assertRaises(ShowtimeError):
                rc.collect(self.ses, self.top, self.roots, since=bad)


class TestScriptAndPage(Base):
    def test_round_trip(self):
        lines = rc.script_lines(self.facts)
        ref, back = rc.read_script(rc.write_script(lines, self.facts["ref"]))
        self.assertEqual(ref, self.facts["ref"])
        self.assertEqual(back, lines)
        self.assertEqual([k for k in lines if lines[k]["kind"] == "say"],
                         ["hook.say", "numbers.say", "timeline.say", "files.say", "tests.say", "diff.say", "end.say"])
        # the critic's round 1: the voice uses the lanes' own counts, the outcome is said, 8 vs 6 files is explained
        self.assertEqual(lines["timeline.say"]["text"], "It edited 1 file, ran 2 commands and 3 test runs.")
        self.assertEqual(lines["end.outcome"]["text"], "Ended green: 12/12 test files passed · 1 commit")

    def test_page_shows_only_script_lines(self):
        lines = rc.script_lines(self.facts)
        lines["hook.title"]["text"] = "An edited title"
        scenes = rc.scenes_for(self.facts)
        durs = rc.durations(self.facts, lines, scenes)
        files = rc.project_files(self.facts, lines, scenes, durs)
        page = files["index.html"]
        self.assertIn("An edited title", page)
        self.assertNotIn("Keep the change small", page)
        self.assertEqual(page.count('class="scene"'), len(scenes))
        self.assertGreaterEqual(files["duration"], 30.0)
        self.assertLessEqual(files["duration"], 60.0)

    def test_sound_differs_per_session_and_is_stable(self):
        """0.4.3: the bed and the effects come from the session: the same one sounds the same, another one not."""
        lines = rc.script_lines(self.facts)
        scenes = rc.scenes_for(self.facts)
        durs = rc.durations(self.facts, lines, scenes)

        def mix(ref, **kw):
            facts = dict(self.facts, ref=ref)
            with mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1", "SHOWTIME_MUSIC_CACHE": str(self.tmp / "nomusic")}):
                f = rc.project_files(facts, lines, scenes, durs, **kw)
            return json.loads(f["audio/mix.json"])["tracks"]
        a, b = mix("session-a"), mix("session-b")
        self.assertEqual(a, mix("session-a"))
        self.assertNotEqual(a[0], b[0])                                             # the bed
        self.assertEqual([x["id"] for x in a], ["bed"])                             # no sound on the cuts by default
        with mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1", "SHOWTIME_MUSIC_CACHE": str(self.tmp / "nomusic")}):
            f = rc.project_files(dict(self.facts, ref="session-a"), lines, scenes, durs)
        self.assertNotIn("sounds", json.loads(f["audio/mix.json"])["_comment"])
        self.assertEqual(a[0]["gain_db"], -2)
        sfx = lambda t: [x["synth"] for x in t if x.get("kind") == "sfx"]           # noqa: E731
        ca, cb = mix("session-a", cut_sounds=True), mix("session-b", cut_sounds=True)    # --cut-sounds: opt in
        self.assertEqual(len(sfx(ca)), len(scenes) - 1)
        self.assertNotEqual(sfx(ca), sfx(cb))
        self.assertTrue(all(x["type"] in ("swoosh-in", "swoosh-out") and
                            x["gain_db"] == -18.0 for x in [dict(t["synth"], gain_db=t["gain_db"]) for t in ca if t.get("synth")]))
        self.assertEqual(mix("session-a", music="lofi-chill")[0]["compose"]["style"], "lofi-chill")
        self.assertEqual(mix("session-a", music="none"), [])

    def test_bed_under_narration_ducks_10_db(self):
        """The bed under the voice dips 10 dB (not the mixer's 12): about 1.5-2 dB louder; no duck without narration."""
        lines = rc.script_lines(self.facts)
        scenes = rc.scenes_for(self.facts)
        durs = rc.durations(self.facts, lines, scenes)
        with mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1", "SHOWTIME_MUSIC_CACHE": str(self.tmp / "nomusic")}):
            voiced = json.loads(rc.project_files(self.facts, lines, scenes, durs, captions=True)["audio/mix.json"])
            silent = json.loads(rc.project_files(self.facts, lines, scenes, durs)["audio/mix.json"])
        self.assertEqual(voiced["tracks"][0]["duck"], {"under": "voice", "depth_db": 10.0})
        self.assertNotIn("duck", silent["tracks"][0])

    def test_callouts_never_overlap(self):
        items = [(30.0, "stage.js"), (31.0, "stage-api.md"), (32.0, "check.mjs"), (33.0, "test_cut_frames.py"),
                 (99.0, "CHANGELOG.md")]
        placed = rc._callout_tiers(items)
        for tier in (0, 1):
            spans = sorted((x, x + (len(t) * 0.95 + 1.8) / 72.6 * 100) for (x, tr), (_x, t) in zip(placed, items)
                           if tr == tier)
            for (a0, a1), (b0, _b1) in zip(spans, spans[1:]):
                self.assertLessEqual(a1, b0 + 1e-6)
        self.assertTrue(all(x + (len(t) * 0.95 + 1.8) / 72.6 * 100 <= 100.01 for (x, _), (_x, t) in zip(placed, items)))

    def test_vertical_project(self):
        lines = rc.script_lines(self.facts)
        scenes = rc.scenes_for(self.facts)
        files = rc.project_files(self.facts, lines, scenes, rc.durations(self.facts, lines, scenes), aspect="9:16")
        cfg = json.loads(files["showtime.json"])
        self.assertEqual((cfg["width"], cfg["height"], cfg["background"]), (1080, 1920, "#F4F3EF"))

    def test_test_dots_arrive_after_the_cut_settles(self):
        """The 16:9 sample's qa dead_stop: the first dot popped (with an overshoot) right after the cut; dots now arrive
        after the dip and the heading, easing in without an overshoot."""
        lines = rc.script_lines(self.facts)
        scenes = rc.scenes_for(self.facts)
        page = rc.project_files(self.facts, lines, scenes, rc.durations(self.facts, lines, scenes))["index.html"]
        dots = re.search(r'<div class="dots">(.*?)</div>', page).group(1)
        first = float(re.search(r"--at:([\d.]+)s", dots).group(1))
        self.assertGreaterEqual(first, 0.9)
        self.assertNotRegex(page, r"\.dots i \{[^}]*animation: pop")

    def test_narration_lines_match_scenes(self):
        lines = rc.script_lines(self.facts)
        md = rc.narration_md(lines, rc.scenes_for(self.facts), pauses={"timeline": 1.0})
        self.assertIn("## hook\n", md)
        self.assertIn("## timeline {pause_after=1.45}", md)
        self.assertIn("## end\nIt ended green, in 1 commit.", md)


class TestCli(Base):
    def test_script_first_then_project(self):
        out = self.tmp / "out1"
        cp = showtime("recap", self.session, "--out", out)
        self.assertTrue((out / "script.md").is_file())
        self.assertFalse((out / "project").exists())
        self.assertIn("--yes", cp.stderr)
        # the user edits the script; --yes uses it as left
        md = (out / "script.md").read_text(encoding="utf-8")
        md = md.replace("show hook.title: ", "show hook.title: Edited: ").replace(
            "show hook.meta: ", "show hook.meta: /Users/me/secret ")
        (out / "script.md").write_text(md, encoding="utf-8")
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render", "--json")
        res = json.loads(cp.stdout)
        self.assertTrue(res["kept_script"])
        self.assertNotIn("edited_script", res)                    # Linux smoke: the key said "edited" when only kept
        self.assertEqual(res["refused"], ["hook.meta"])            # the person's line, refused; recap's own kept
        self.assertEqual(res["dropped"], {})
        page = (out / "project" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Edited: ", page)
        text = all_text(out / "project") + (out / "facts.json").read_text(encoding="utf-8")   # script.md is the user's
        for bad in PLANTED + (str(self.repo),):
            self.assertNotIn(bad, text, bad)

    def test_yes_never_renders_the_script_it_writes(self):
        """S5: --yes on a first run (or with --fresh) writes script.md and stops for the read."""
        out = self.tmp / "out-yes"
        for flags in ([], ["--fresh"]):
            cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", *flags)
            self.assertTrue((out / "script.md").is_file())
            self.assertFalse((out / "project").exists())
            self.assertIn("rerun with --yes", cp.stderr)
        showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render")
        self.assertTrue((out / "project" / "index.html").is_file())

    def test_only_transcripts_are_read(self):
        """Review 2 #3: a file that is not a Claude Code transcript is refused."""
        for name, text in (("notes.txt", "hello"), ("data.jsonl", '{"a": 1}\n{"type": "user"}\n'),
                           ("other.jsonl", '{"type": "user", "message": {"content": "x"}}\n')):
            p = self.tmp / name
            p.write_text(text, encoding="utf-8")
            with self.assertRaises(ShowtimeError):
                rc.find_session(str(p))
            cp = showtime("recap", p, "--out", self.tmp / ("o-" + name), check=False)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("not a Claude Code session transcript", cp.stderr)
        self.assertEqual(rc.find_session(str(self.session)), self.session)

    def test_default_out_is_a_job_folder_never_tracked_by_git(self):
        """Review 2 #3: no --out inside a repository refuses (git would track it); with SHOWTIME_OUT elsewhere, the
        default is <SHOWTIME_OUT>/showtime-out/recap-<session>."""
        cp = showtime("recap", self.session, check=False, cwd=self.repo, env={k: v for k, v in ENV.items() if k != "SHOWTIME_OUT"})
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("inside a git repository", cp.stderr)
        self.assertFalse((self.repo / "showtime-out").exists())
        (self.repo / ".gitignore").write_text("showtime-out/\n", encoding="utf-8")
        try:
            showtime("recap", self.session, cwd=self.repo)
            self.assertTrue((self.repo / "showtime-out" / ("recap-" + self.facts["ref"]) / "script.md").is_file())
        finally:
            (self.repo / ".gitignore").unlink()
            shutil.rmtree(self.repo / "showtime-out", ignore_errors=True)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        showtime("recap", self.session, cwd=self.repo, env=dict(ENV, SHOWTIME_OUT=str(elsewhere)))
        self.assertTrue((elsewhere / "showtime-out" / ("recap-" + self.facts["ref"]) / "script.md").is_file())

    def test_adversarial_grid_end_to_end(self):
        """Every row of the two adversarial leak grids in one CRLF transcript: nothing of them in any file recap writes."""
        outside = self.tmp / "out-zorg"
        outside.mkdir(exist_ok=True)
        request = ("Fix the parser bug. Deploy to zorg-prod.internal (10.1.2.3) now. Use password: hunter2xyz and "
                   "token: abcd1234efgh5678ijkl. The value is Q9w8E7r6T5y4U3i2 O1p0A9s8D7f6G5h4 for prod. Open "
                   "portal.zorgagency.gov and zorgmirror.cl. Ask deploy@zorgbox about ~zorguser/notes.")
        ev = [{"type": "user", "isCompactSummary": True, "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo),
               "sessionId": "s", "message": {"content": "ZORGSUMMARY of the earlier part"}},
              {"type": "user", "timestamp": "2026-10-01T10:00:01Z", "cwd": str(self.repo), "sessionId": "s",
               "message": {"content": request}}]
        t = 2
        for i, cmd in enumerate(TestCommands.ADVERSARIAL_COMMANDS):
            cwd = str(self.repo if i % 2 else outside)
            ev.append({"type": "assistant", "timestamp": "2026-10-01T10:%02d:%02dZ" % (t // 60, t % 60), "cwd": cwd,
                       "sessionId": "s", "message": {"id": "m%d" % i, "content": [
                           {"type": "tool_use", "id": "t%d" % i, "name": "PowerShell" if "Location" in cmd else "Bash",
                            "input": {"command": cmd}}]}})
            ev.append({"type": "user", "timestamp": "2026-10-01T10:%02d:%02dZ" % (t // 60, t % 60 + 1), "cwd": cwd,
                       "sessionId": "s", "message": {"content": [{"type": "tool_result", "tool_use_id": "t%d" % i,
                                                                  "content": "ok zorg"}]}})
            t += 5
        for j, name in enumerate(("mcp__zorgcrm__lookup_zorgcorp_invoices", "ZorgCustomTool")):     # RS9
            ev.append({"type": "assistant", "timestamp": "2026-10-01T11:00:0%dZ" % j, "cwd": str(self.repo),
                       "sessionId": "s", "message": {"id": "z%d" % j, "content": [
                           {"type": "tool_use", "id": "z%d" % j, "name": name, "input": {}}]}})
        p = self.tmp / "grid.jsonl"
        p.write_text("\r\n".join(json.dumps(e) for e in ev) + "\r\n", encoding="utf-8")
        out = self.tmp / "grid-out"
        showtime("recap", p, "--repo", self.repo, "--out", out)
        showtime("recap", p, "--repo", self.repo, "--out", out, "--yes", "--no-voice", "--no-render")
        text = all_text(out).lower()
        for bad in ("zorg", "hunter2", "abcd1234", "q9w8", "10.1.2.3", "deploy@", "summary"):
            self.assertNotIn(bad, text, bad)
        self.assertIn("# show hook.request: fix the parser bug.", text)     # the one clean sentence, offered only

    def test_only_script_md_changes_the_screen(self):
        """RB2: there is no --title; a title or request line the person writes into script.md goes through the
        strict request rule and the hard filter, and the CLI says what it refused."""
        cp = showtime("recap", self.session, "--out", self.tmp / "t0", "--title", "x", check=False)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("--title", cp.stderr)
        for i, title in enumerate(("Use passcode Zx9Qw8Er7Ty6", "Ship portal.zorgagency.gov fix",
                                   "Log in with zorgadmin:Zx9Qw8Er7Ty6", "Key Q9W8-E7R6-T5Y4-U3I2",
                                   "Read ../zorg-client/plan.md", "The password is swordfish")):
            out = self.tmp / ("rb2-%d" % i)
            showtime("recap", self.session, "--out", out)
            md = (out / "script.md").read_text(encoding="utf-8")
            md = md.replace("# show hook.request: ", "show hook.request: " + title + " ")
            md = md.replace(re.search(r"show hook.title: [^\n]*", md).group(0), "show hook.title: " + title)
            (out / "script.md").write_text(md, encoding="utf-8")
            cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render")
            self.assertIn("refused hook.title", cp.stderr, title)
            self.assertIn("refused hook.request", cp.stderr, title)
            page = (out / "project" / "index.html").read_text(encoding="utf-8").lower()
            for w in ("zorg", "zx9q", "q9w8", "swordfish", "passcode"):
                self.assertNotIn(w, page, title)
        # a clean title the person writes is used
        out = self.tmp / "rb2-ok"
        showtime("recap", self.session, "--out", out)
        md = (out / "script.md").read_text(encoding="utf-8")
        md = md.replace(re.search(r"show hook.title: [^\n]*", md).group(0), "show hook.title: The parser fix")
        (out / "script.md").write_text(md, encoding="utf-8")
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render")
        self.assertNotIn("refused", cp.stderr)
        self.assertIn("The parser fix", (out / "project" / "index.html").read_text(encoding="utf-8"))
        self.assertNotIn("parser test", (out / "facts.json").read_text(encoding="utf-8"))

    def test_every_line_the_person_writes_is_checked(self):
        """RS10: the strict rule and the hard filter on any line of script.md recap did not write (captions,
        narration, labels, any key), each refusal named."""
        out = self.tmp / "rs10"
        showtime("recap", self.session, "--out", out)
        md = (out / "script.md").read_text(encoding="utf-8")
        shapes = {"end.note": "Log in with zorgadmin:Zx9Qw8Er7Ty6", "hook.say": "Use passcode Zx9Qw8Er7Ty6 now.",
                  "stat.calls.label": "Ship portal.zorgagency.gov fix", "files.kicker": "Ticket 4821937 here"}
        for key, text in shapes.items():
            md = re.sub(r"(?m)^((?:show|say) %s:) .*$" % re.escape(key), lambda m: m.group(1) + " " + text, md)
        md = md.replace("## end\n", "## end\n\nshow end.extra: Key Q9W8-E7R6-T5Y4-U3I2\n")   # a key recap never writes
        md = md.replace(re.search(r"show stat\.turns\.label: [^\n]*", md).group(0), "show stat.turns.label: rounds")
        (out / "script.md").write_text(md, encoding="utf-8")
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render")
        for key in list(shapes) + ["end.extra"]:
            self.assertIn("refused %s from script.md" % key, cp.stderr, key)
        self.assertNotIn("refused stat.turns.label", cp.stderr)
        page = (out / "project" / "index.html").read_text(encoding="utf-8").lower()
        for w in ("zorg", "zx9q", "q9w8", "passcode", "4821937"):
            self.assertNotIn(w, page, w)
        self.assertIn("rounds", page)                              # a clean edit is used

    def test_a_growing_session_keeps_recaps_own_lines(self):
        """RS12: the transcript grows between the two calls (a recap run inside the live session). recap's own
        earlier lines (file paths, a "Most used" line with python3) are kept as the person left them, never
        "refused", and the page shows what script.md says."""
        p = self.tmp / "growing.jsonl"
        shutil.copy(self.session, p)
        first = []
        for i in range(3):                        # python3 tops the "Most used" line (the strict rule refuses python3)
            first.append({"type": "assistant", "timestamp": "2026-10-01T10:3%d:00.000Z" % i, "cwd": str(self.repo),
                          "sessionId": "0000-fixture", "message": {"id": "f%d" % i, "content": [
                              {"type": "tool_use", "id": "f%d" % i, "name": "Bash",
                               "input": {"command": "python3 tools/x.py"}}]}})
            first.append({"type": "user", "timestamp": "2026-10-01T10:3%d:02.000Z" % i, "cwd": str(self.repo),
                          "sessionId": "0000-fixture", "message": {"content": [
                              {"type": "tool_result", "tool_use_id": "f%d" % i, "content": "ok"}]}})
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(e) for e in first) + "\n")
        out = self.tmp / "rs12"
        showtime("recap", p, "--out", out)
        md = (out / "script.md").read_text(encoding="utf-8")
        cmds = re.search(r"show timeline\.commands: ([^\n]*)", md).group(1)
        self.assertIn("python3", cmds)
        extra = []
        for i in range(2):                        # two more test runs and a python3 call, an hour later
            extra.append({"type": "assistant", "timestamp": "2026-10-01T11:0%d:00.000Z" % i, "cwd": str(self.repo),
                          "sessionId": "0000-fixture", "message": {"id": "g%d" % i, "content": [
                              {"type": "tool_use", "id": "g%d" % i, "name": "Bash",
                               "input": {"command": "python3 -m pytest -q && python3 tools/x.py"}}]}})
            extra.append({"type": "user", "timestamp": "2026-10-01T11:0%d:05.000Z" % i, "cwd": str(self.repo),
                          "sessionId": "0000-fixture", "message": {"content": [
                              {"type": "tool_result", "tool_use_id": "g%d" % i,
                               "content": "========== 12 passed in 0.40s =========="}]}})
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(e) for e in extra) + "\n")
        cp = showtime("recap", p, "--out", out, "--yes", "--no-voice", "--no-render")
        self.assertNotIn("refused", cp.stderr)
        page = (out / "project" / "index.html").read_text(encoding="utf-8")
        self.assertIn(rc._e(cmds.replace("Most used:", "").strip().split("  ·  ")[0]), page)
        self.assertIn("parser.py", page)
        # a deliberate edit that recap would not write is still checked
        md = md.replace("show timeline.commands: " + cmds, "show timeline.commands: Most used: zorgctl@zorg-prod.internal ×3")
        (out / "script.md").write_text(md, encoding="utf-8")
        cp = showtime("recap", p, "--out", out, "--yes", "--no-voice", "--no-render")
        self.assertIn("refused timeline.commands", cp.stderr)
        F = {"files": [{"path": "src/parser.py", "edited": 1}, {"path": "src/read_only.py", "read": 1, "edited": 0}]}
        self.assertTrue(rc.own_line("file.3", "src/parser.py", {}, F))
        self.assertFalse(rc.own_line("file.3", "src/zorg/secret.py", {}, F))
        self.assertFalse(rc.own_line("file.3", "src/read_only.py", {}, F))      # a read file is not recap's row
        self.assertTrue(rc.own_line("timeline.commands", "Most used:  git commit ×2  ·  python3 -m pytest ×4", {}, F))
        self.assertFalse(rc.own_line("timeline.commands", "Most used:  ssh deploy@zorgbox ×2", {}, F))
        # N-t: a count is at most 5 digits; a longer one is checked like any number
        self.assertFalse(rc.own_line("timeline.commands", "Most used:  git commit ×4821937", {}, F))
        self.assertFalse(rc.own_line("timeline.commands", "Most used:  git commit ×12345678901234", {}, F))

    def _tf_session(self, path: Path, upto: int) -> None:
        """A session in a Terraform repository whose most edited file is infra/main.tf; `upto` stages."""
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo), "sessionId": "tf",
               "message": {"content": "Tidy the infra."}}]
        n = 0
        for stage in range(upto):
            for target in ["infra/main.tf"] * (3 + stage) + ["README.md"] * (stage + 1):
                n += 1
                ts = "2026-10-01T1%d:%02d:%02dZ" % (stage, n // 60, n % 60)
                ev.append({"type": "assistant", "timestamp": ts, "cwd": str(self.repo), "sessionId": "tf",
                           "message": {"id": "e%d" % n, "content": [
                               {"type": "tool_use", "id": "e%d" % n, "name": "Edit",
                                "input": {"file_path": str(self.repo / target), "old_string": "a", "new_string": "b"}}]}})
                ev.append({"type": "user", "timestamp": ts, "cwd": str(self.repo), "sessionId": "tf",
                           "message": {"content": [{"type": "tool_result", "tool_use_id": "e%d" % n,
                                                    "content": "The file has been updated."}]}})
        path.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")

    def test_three_calls_on_a_growing_session(self):
        """RS12-rest: call 1 writes script.md, calls 2 and 3 render while the session grows (most edited:
        main.tf, which the strict rule alone would take for a host). Nothing is refused; the page shows script.md."""
        p = self.tmp / "tf.jsonl"
        out = self.tmp / "tf-out"
        self._tf_session(p, 1)
        showtime("recap", p, "--out", out)
        md = (out / "script.md").read_text(encoding="utf-8")
        self.assertIn("main.tf", re.search(r"say files\.say: ([^\n]*)", md).group(1))
        for upto in (2, 3):
            self._tf_session(p, upto)
            cp = showtime("recap", p, "--out", out, "--yes", "--no-voice", "--no-render")
            self.assertNotIn("refused", cp.stderr, upto)
        page = (out / "project" / "index.html").read_text(encoding="utf-8")
        for key in ("hook.title", "file.1.stat", "stat.calls.value", "lane.edit"):
            text = re.search(r"show %s: ([^\n]*)" % re.escape(key), md).group(1)
            self.assertIn(rc._e(text) if key != "lane.edit" else text.split()[-1], page, key)

    def test_shapes_not_masks(self):
        """RS14/RS15: lines are compared by shape with what recap writes, never erased and re-judged. Digits
        inside words, a key word or user name that is also a file stem, and a read-only file's stem exempt nothing.
        N-y: a snake_case files line with a stale count is recap's own."""
        repo = self.tmp / "shapes-repo"
        if not repo.exists():
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            (repo / "x.txt").write_text("x\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "x")
        edits = ["api.py", "admin.py", "infra/deploy_infra.tf", "infra/deploy_infra.tf", "infra/deploy_infra.tf",
                 "notes/2026-10-12-1530.md", "notes/2026-10-12.md", "logs/2026/10/12/run.md",
                 "notes/Report 2026 10 12 1530.md", "notes/Minutes 2026 10 12.md", "notes/Plan  2026  10  12.md"]
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(repo), "sessionId": "sh",
               "message": {"content": "Tidy up."}}]
        for i, f in enumerate(edits + ["hunter2xyz.txt"]):
            name = "Read" if f.endswith(".txt") else "Edit"
            ev.append({"type": "assistant", "timestamp": "2026-10-01T10:00:%02dZ" % (i + 1), "cwd": str(repo),
                       "sessionId": "sh", "message": {"id": "s%d" % i, "content": [
                           {"type": "tool_use", "id": "s%d" % i, "name": name,
                            "input": {"file_path": str(repo / f), "old_string": "a", "new_string": "b"}}]}})
            ev.append({"type": "user", "timestamp": "2026-10-01T10:00:%02dZ" % (i + 1), "cwd": str(repo),
                       "sessionId": "sh", "message": {"content": [{"type": "tool_result", "tool_use_id": "s%d" % i,
                                                                   "content": "ok"}]}})
        p = self.tmp / "shapes.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
        ses = rc.parse_session(p)
        facts = rc.collect(ses, *rc.repo_roots(ses))
        fresh = rc.script_lines(facts)
        own = lambda k, t: rc.own_line(k, t, fresh, facts)  # noqa: E731
        for key, text in (("stat.calls.value", "Ticket 4,821,937 here"), ("lane.read", "Account 4 821 937"),
                          ("stat.calls.value", "Ticket 4821937 here"), ("lane.read", "Account 48 21 93 77"),
                          ("stat.files.value", "Log in with Q7x2Lm9Kp4Rt"), ("stat.time.label", "api key swordfish"),
                          ("stat.turns.label", "admin:swordfish"), ("files.kicker", "password hunter2xyz")):
            with self.subTest(key=key, text=text):
                self.assertIsNone(own(key, text), (key, text))
                self.assertTrue(rc.free_text_refused(text), (key, text))
        for key in ("file.1", "callout.1"):          # a file the session only read is never recap's row
            with self.subTest(read_only=key):
                self.assertIsNone(own(key, "hunter2xyz.txt"), key)
        self.assertEqual(own("stat.calls.value", "12"), "own")                         # a stale count
        self.assertEqual(own("stat.calls.value", "12,345"), "own")                     # 5 digits, grouped
        # RS16: a stale count is 1-5 digits in all, grouping included; longer comma numbers are never own
        for value in ("4,111,111,111,111,111", "123,456,789", "5,551,234,567", "123,456"):
            for key in ("stat.calls.value", "hook.meta", "diff.adds"):
                if key not in fresh:
                    continue
                with self.subTest(key=key, value=value):
                    self.assertNotEqual(own(key, fresh[key]["text"].replace(
                        re.findall(r"[0-9][0-9,]*", fresh[key]["text"])[0], value, 1)), "own")
        import time
        t = time.time()
        rc._shape("1," + "111," * 75000 + "111a")                                     # 300 KB: linear
        self.assertLess(time.time() - t, 1.0)
        for big in ("9" * 300000, "a." * 150000, "1" * 40000 + "a"):                  # RS19: digits, a.a.
            for key in ("stat.calls.value", "files.say", "file.1"):
                t = time.time()
                rc.own_line(key, big, fresh, facts)
                with self.subTest(rs19=(key, big[:6])):
                    self.assertLess(time.time() - t, 1.0)
        self.assertEqual(own("stat.calls.value", "1234567"), "stale")                  # a 6+ digit count: today's
        # RS17: digits inside a path (a dated note, a dated folder) are never counts. Another number written
        # there (a card, an SSN) is not recap's row, in file.N, callout.N or the files line
        by_path = {ln["text"]: k for k, ln in fresh.items() if re.fullmatch(r"(file|callout)\.\d+", k)}
        for real, fake in (("notes/2026-10-12-1530.md", "notes/5500-0000-0000-0004.md"),
                           ("notes/2026-10-12.md", "notes/123-45-6789.md"),
                           ("logs/2026/10/12/run.md", "logs/4111/1111/1111/run.md"),
                           ("2026-10-12-1530.md", "5500-0000-0000-0004.md"), ("2026-10-12.md", "123-45-6789.md")):
            key = by_path.get(real) or ("callout.1" if "/" not in real else "file.1")
            row = dict(fresh, **{key: {"scene": "files", "kind": "show", "text": real}})   # recap's row for it
            with self.subTest(real=real, fake=fake):
                self.assertEqual(rc.own_line(key, real, row, facts), "own")
                self.assertNotEqual(rc.own_line(key, fake, row, facts), "own")
                self.assertTrue(rc.free_text_refused(fake), fake)          # not own: the strict rule refuses it
            f = next((x for x in facts["files"] if x["path"].endswith(real)), None)
            if f and real.rsplit("/", 1)[-1] != fake.rsplit("/", 1)[-1]:
                say = rc.files_say(f, {}, 3)
                with self.subTest(files_say=say):
                    self.assertEqual(own("files.say", say), "own")
                    faked = say.replace(real.rsplit("/", 1)[-1][:-3], fake.rsplit("/", 1)[-1][:-3])
                    self.assertNotEqual(own("files.say", faked), "own")
                    self.assertTrue(rc.free_text_refused(faked), faked)
        # RS18: a file's name is never shape-compared, whatever separates its digit runs (spaces, several
        # spaces, a tab, NBSP, a thin space): only the exact name of an edited file is recap's
        n_ed = sum(1 for x in facts["files"] if x["edited"])
        for real, fake in (("notes/Report 2026 10 12 1530.md", "notes/Report 5500 0000 0000 0004.md"),
                           ("notes/Minutes 2026 10 12.md", "notes/Minutes 123 45 6789.md"),
                           ("notes/Plan  2026  10  12.md", "notes/Plan  4111  1111  1111.md"),
                           ("notes/Report 2026 10 12 1530.md", "notes/Report\t5500\t0000\t0000\t0004.md"),
                           ("notes/Report 2026 10 12 1530.md", "notes/Report\u00a05500\u00a00000\u00a00000\u00a00004.md"),
                           ("notes/Report 2026 10 12 1530.md", "notes/Report\u20095500\u20090000\u20090000\u20090004.md")):
            f = next(x for x in facts["files"] if x["path"] == real)
            name_real, name_fake = real.rsplit("/", 1)[-1], fake.rsplit("/", 1)[-1]
            row = dict(fresh, **{"file.1": {"scene": "files", "kind": "show", "text": real},
                                 "callout.1": {"scene": "timeline", "kind": "show", "text": name_real}})
            with self.subTest(rs18=fake):
                self.assertEqual(rc.own_line("file.1", real, row, facts), "own")
                self.assertNotEqual(rc.own_line("file.1", fake, row, facts), "own")
                self.assertTrue(rc.free_text_refused(fake), fake)
                self.assertEqual(rc.own_line("callout.1", name_real, row, facts), "own")
                self.assertNotEqual(rc.own_line("callout.1", name_fake, row, facts), "own")
                self.assertTrue(rc.free_text_refused(name_fake), name_fake)
                for p_ in ({}, {real: [30, 1]}):
                    say, spoken = rc.files_say_parts(f, p_, n_ed)
                    fake_spoken = rc.files_say_parts(dict(f, path=fake), p_, n_ed)[1]
                    self.assertEqual(rc.own_line("files.say", say, row, dict(facts, diff=dict(facts["diff"], per_file=p_))),
                                     "own")
                    self.assertNotEqual(rc.own_line("files.say", say.replace(spoken, fake_spoken), row,
                                                    dict(facts, diff=dict(facts["diff"], per_file=p_))), "own")
                    self.assertTrue(rc.free_text_refused(say.replace(spoken, fake_spoken)))
        # N-ag: script.md lines are read with their whitespace runs collapsed; an edited name with two spaces still
        # matches at any key (a row that moved in a growing session)
        self.assertEqual(rc.own_line("file.7", "notes/Plan 2026 10 12.md", {}, facts), "own")
        self.assertEqual(rc.own_line("callout.4", "Plan 2026 10 12.md", {}, facts), "own")
        self.assertIn("deploy infra.tf", fresh["files.say"]["text"])
        self.assertEqual(own("files.say", fresh["files.say"]["text"].replace("3 of them", "2 of them")), "own")
        self.assertEqual(own("files.say", "Most edits went into zorg.internal: 2 of them."), None)

    def test_hand_edited_facts_json_is_not_trusted(self):
        """RS13: facts.json is output, never trusted. Private text put into it, with matching script.md lines,
        is refused on --yes. N-u: a malformed facts.json does not crash the call."""
        out = self.tmp / "rs13"
        showtime("recap", self.session, "--out", out)
        facts = json.loads((out / "facts.json").read_text(encoding="utf-8"))
        facts["files"][0]["path"] = "Use passcode Zx9Qw8Er7Ty6"
        facts["tests"][-1]["unit"] = "ZORG zorgadmin:Zx9Qw8Er7Ty6"
        facts["commands"][0][0] = "Ship portal.zorgagency.gov fix"
        (out / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
        md = (out / "script.md").read_text(encoding="utf-8")
        md = re.sub(r"(?m)^show file\.1: .*$", "show file.1: Use passcode Zx9Qw8Er7Ty6", md)
        md = re.sub(r"(?m)^show tests\.label: .*$", "show tests.label: ZORG zorgadmin:Zx9Qw8Er7Ty6 tests passed", md)
        md = re.sub(r"(?m)^show timeline\.commands: .*$", "show timeline.commands: Most used:  Ship portal.zorgagency.gov fix ×1", md)
        (out / "script.md").write_text(md, encoding="utf-8")
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render")
        for key in ("file.1", "tests.label", "timeline.commands"):
            self.assertIn("refused %s from script.md" % key, cp.stderr, key)
        page = (out / "project" / "index.html").read_text(encoding="utf-8").lower()
        for w in ("passcode", "zorg", "zx9q"):
            self.assertNotIn(w, page, w)
        (out / "facts.json").write_text("[1, 2, {\"path\": 5}]", encoding="utf-8")
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--no-render", check=False)
        self.assertEqual(cp.returncode, 0, cp.stderr[-800:])

    def test_wrappers_anywhere_and_linear_line_starts(self):
        """N-v: a known wrapper ends the text wherever it sits (mid-line, after a no-break space or U+2028).
        N-w: the line-start test is linear."""
        import time
        for text in ("Fix it. <system-reminder>Zorg note", "Fix it.\u00a0<system-reminder>Zorg note",
                     "Fix it.\u2028<ide_selection>Zorg note"):
            self.assertNotIn("Zorg", rc._strip_tags(text), repr(text))
        for big in ("x\t<a-b>" * 70000, "<a-b>" * 100000):
            t = time.time()
            rc._strip_tags(big)
            self.assertLess(time.time() - t, 1.0)

    def test_wrapper_tags_and_inline_tags(self):
        """N-p: an unclosed dashed tag inside the person's sentence is dropped alone; a wrapper that starts a
        line still ends the text. N-q: a text block that starts with a block-style tag goes whole (nested reminders)."""
        self.assertIn("hover state in the header", rc._strip_tags("Please fix the <my-button> hover state in the header."))
        self.assertNotIn("Zorg", rc._strip_tags("Fix it.\n<ide_selection>Zorg note runs on"))
        p = self.tmp / "nested.jsonl"
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.repo), "sessionId": "s",
               "message": {"content": [
                   {"type": "text", "text": "<system-reminder> a <system-reminder> b </system-reminder> Zorg note "
                                            "</system-reminder>"},
                   {"type": "text", "text": "Fix the parser bug."}]}}]
        p.write_text(json.dumps(ev[0]) + "\n", encoding="utf-8")
        ses = rc.parse_session(p)
        self.assertEqual(ses["request"].strip(), "Fix the parser bug.")

    def test_spoken_file_name_and_plurals(self):
        """N-m: the most edited file is spoken as its stem's words and its extension. Linux smoke: "1 path"."""
        f = json.loads(json.dumps(self.facts))
        f["files"] = [{"path": "src/test_cut_frames.py", "read": 0, "edited": 4, "first": 1, "first_edit": 1},
                      {"path": "src/b.py", "read": 0, "edited": 1, "first": 2, "first_edit": 2}]
        f["diff"]["per_file"] = {}
        say = rc.script_lines(f)["files.say"]["text"]
        self.assertIn("test cut frames.py", say)
        self.assertNotIn("_", say)
        f["files_outside"] = 1
        self.assertIn("1 path outside", rc.summary(f))

    def test_default_out_missing_folder_inside_a_repo(self):
        """RS7: a SHOWTIME_OUT that does not exist yet, inside a repository that would track it, is refused."""
        for sub in ("newdir", "a/b/showtime-out"):
            cp = showtime("recap", self.session, check=False, cwd=self.tmp,
                          env=dict(ENV, SHOWTIME_OUT=str(self.repo / sub)))
            self.assertNotEqual(cp.returncode, 0, sub)
            self.assertIn("inside a git repository", cp.stderr)
            self.assertFalse((self.repo / sub.split("/")[0]).exists(), sub)

    def test_script_from_another_session(self):
        out = self.tmp / "out2"
        showtime("recap", self.session, "--out", out)
        cp = showtime("recap", self.sub, "--out", out, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("another session", cp.stderr)
        showtime("recap", self.sub, "--out", out, "--fresh")

    def test_latest(self):
        home = self.tmp / "claude"
        proj = home / "projects" / rc.project_slug(self.repo)
        proj.mkdir(parents=True)
        shutil.copy(self.session, proj / "0000aaaa-fixture.jsonl")
        env_old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(home)
        try:
            self.assertEqual(rc.latest_session(self.repo / "src"), proj / "0000aaaa-fixture.jsonl")
            self.assertEqual(rc.find_session("0000aaaa-fixture"), proj / "0000aaaa-fixture.jsonl")
        finally:
            if env_old is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = env_old

    @unittest.skipIf(FAST, "--fast: the voice is synthesized")
    def test_a_persons_say_line_reaches_neither_page_nor_voice(self):
        """A person's say and show lines with a hidden-character card are refused: neither index.html nor the
        narration (voice/narration.md, the captions' source) holds them."""
        out = self.tmp / "say-cli"
        showtime("recap", self.session, "--out", out)
        md = (out / "script.md").read_text(encoding="utf-8")
        card = "\u200b".join("4111111111111111")
        md = re.sub(r"(?m)^say hook\.say: .*$", "say hook.say: Pay with " + card + " today.", md)
        md = re.sub(r"(?m)^show end\.note: .*$", "show end.note: Card " + card + " ends it.", md)
        md = re.sub(r"(?m)^say numbers\.say: .*$", "say numbers.say: Pay 4111 then 1111 then 1111 then 1111 now.", md)
        (out / "script.md").write_text(md, encoding="utf-8")
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-render")
        for key in ("hook.say", "end.note", "numbers.say"):
            self.assertIn("refused %s from script.md" % key, cp.stderr, key)
        page = (out / "project" / "index.html").read_text(encoding="utf-8")
        narration = (out / "project" / "voice" / "narration.md").read_text(encoding="utf-8")
        for text in (page, narration):
            self.assertNotIn("4111", text.replace("\u200b", ""))
            self.assertNotIn("\u200b", text)

    @unittest.skipIf(FAST, "--fast: no render")
    def test_end_to_end_render_and_qa(self):
        out = self.tmp / "e2e"
        showtime("recap", self.session, "--out", out)                              # the script, read first
        cp = showtime("recap", self.session, "--out", out, "--yes", "--no-voice", "--preview", "--json",
                      "--music", "minimal-pulse", check=False)
        res = json.loads(cp.stdout[cp.stdout.index("{"):])
        self.assertTrue(Path(res["video"]).is_file(), cp.stderr[-2000:])
        self.assertIn(res["qa"]["verdict"], ("PASS", "WARN"), res["qa"])
        text = all_text(out)
        for bad in PLANTED + (str(self.repo),):
            self.assertNotIn(bad, text, bad)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
