---
type: llm
focus: trace
---

The user typed "/showtime x-ray this clip of my typewriter, drawn on the machine." and gave typewriter.webm.
PASS if the run executed `showtime xray analyze` on the clip, made an xray project, rendered it, and ran
`showtime xray verify <job>` whose output (the receipt) shows every event on its frame (N of N), and the final reply
reports that result without overstating it.
FAIL if verify was never run, verify reported fewer than N of N events on their frame and the reply calls it a
success, or the numbers in the reply are not the ones verify printed.
