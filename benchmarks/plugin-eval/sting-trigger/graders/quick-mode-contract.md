---
type: llm
focus: trace
---

The user asked for a 5-second logo sting with sound, giving the brand name and colours.
PASS if Claude moves toward making the video without blocking on questions: it either starts the work or
states its assumptions (e.g. logo treatment, sound) and asks at most one short question.
FAIL if it asks the user to specify things the request already answered (length, colours, sound), asks more
than two questions, or refuses.
