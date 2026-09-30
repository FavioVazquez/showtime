# T9 · Repo explainer

A developer wants a short video that explains a small project to people who have never seen it.

```json
{
  "id": "t9-repo-explainer",
  "title": "Explain a repo",
  "prompt": "Make a 60-90 second video that explains what this repo does and how it works, for developers seeing it for the first time.",
  "inputs": [{"from": "fixtures/keelson", "to": "."}],
  "deliverable": "video",
  "expect": {"duration": [60, 90], "aspect": ["16:9"], "audio": "preferred", "captions": null, "platform": "youtube"},
  "facts": ["fixtures/keelson/README.md", "fixtures/keelson/CHANGELOG.md", "fixtures/keelson/pyproject.toml",
            "fixtures/keelson/keelson/cli.py", "fixtures/keelson/keelson/envfile.py", "fixtures/keelson/keelson/rules.py",
            "fixtures/keelson/keelson/report.py", "fixtures/keelson/examples/.env", "fixtures/keelson/examples/.env.example"],
  "cap_minutes": 30
}
```

**Workspace:** the fixture repo at the workspace root (README, CHANGELOG, `pyproject.toml`, the `keelson/`
package with `cli.py`, `envfile.py`, `rules.py` and `report.py`, `tests/`, and an `examples/` folder with a
`.env` and a `.env.example`), committed to a fresh git repository. keelson is fictional; the code works.

**What the judges look for** (the ranking judge sees only the request, frames, transcript and measurements):

- **What it is, first:** within the first 10-15 s a newcomer knows the problem (a `.env` drifting from the
  committed `.env.example`) and what keelson does about it.
- **How it works:** the pipeline the README and code describe, in order: parse both files (`envfile.py`),
  compare them with rules (`rules.py`: missing, extra, duplicate, empty), report as text or JSON with an exit
  code (`report.py`), wired up by the `check` / `diff` / `init` commands (`cli.py`). Showing real code or the
  real file layout counts; an invented architecture does not.
- **A real run:** the example report (2 errors, 2 warnings on the files in `examples/`) or another command
  exactly as the code would print it; exit codes 0 / 1 / 2 with their meanings.
- **Accuracy:** version 0.3.0 and its changes (`init`, the duplicate rule, `--strict`, line numbers) only as
  the CHANGELOG states them; install command `pip install keelson`; Python 3.8+; no dependencies. Invented
  numbers (downloads, stars, speed, users, companies) are invented claims. keelson never prints values: a video
  that shows it printing secret values is wrong.
- **Legible code:** code and terminal text large enough to read on a laptop, on screen long enough to read.
- **Length and pacing:** 60-90 s, 16:9, a clear order (problem, what, how, try it), no long static holds.
- Sound is preferred (voice-over or music); captions are welcome but not required.

**Fact sources:** the README, CHANGELOG, `pyproject.toml`, the four modules and the two example files.
Anything else stated as fact is an invented claim.
