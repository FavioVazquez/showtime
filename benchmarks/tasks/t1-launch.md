# T1 · Launch video from a repo

A developer wants a launch clip for a new release, straight from the project folder.

```json
{
  "id": "t1-launch",
  "title": "Launch video from a repo",
  "prompt": "Make a 30-second launch video for quillsort 2.0 from this repo that I can post on X.",
  "inputs": [{"from": "fixtures/quillsort", "to": "."}],
  "deliverable": "video",
  "expect": {"duration": [25, 35], "aspect": ["16:9", "1:1"], "audio": "preferred", "captions": null, "platform": "x"},
  "facts": ["fixtures/quillsort/README.md", "fixtures/quillsort/CHANGELOG.md", "fixtures/quillsort/site/index.html"],
  "cap_minutes": 25
}
```

**Workspace:** the fixture repo at the workspace root (README, CHANGELOG, `quillsort.py`, `site/index.html`),
committed to a fresh git repository.

**What good looks like:** the 2.0 features (natural sort, in-place with `.bak`, `--strip-blank`,
first-occurrence `--unique`) shown clearly, a real command example, readable type on a phone, a call to
action that matches the repo (`pip install quillsort`), no invented numbers (speed claims, users, stars).

**Fact sources:** README, CHANGELOG, site. Anything else stated as fact is an invented claim.
