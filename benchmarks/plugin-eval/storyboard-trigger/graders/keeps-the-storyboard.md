---
type: llm
focus: trace
---

The user gave a four-shot storyboard table (4 s, 6 s, 5 s, 3 s: 18 s in all) with a Visual and a Narration
column, and asked for it to be rendered.
PASS if the plan keeps the four shots in order with their lengths and their narration as written, and treats
each Visual cell as a brief for what to build (not as words to put on screen), adding no claims the table does
not make.
FAIL if it rewrites or drops narration lines, reorders shots or changes lengths without saying why, prints the
Visual descriptions as on-screen text, or adds claims (numbers, users, features) that are not in the table.
