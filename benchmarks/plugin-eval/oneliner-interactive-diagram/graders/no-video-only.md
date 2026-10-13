---
type: llm
focus: trace
---

The user typed "/showtime explain how a heat pump works, interactive." The word "interactive" means they want a
living figure they can touch in a browser, not a finished video file.
PASS if the run built a diagram project (`showtime new diagram`), exported the live page with
`showtime export html <project> --interactive` (a `*-figure.html` file) and the final reply says where that file is
and what the viewer can touch (a knob, steps, or the scene's parts).
FAIL if the run only renders an MP4 (or only plans one) and never produces the live figure, or if it stops after
asking the user questions without making anything.
