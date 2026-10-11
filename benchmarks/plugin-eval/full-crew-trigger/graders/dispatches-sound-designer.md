---
type: llm
focus: trace
---

The user asked for a 25-second film with a music bed and said "full crew", but also "build it straight away: no
concept pitch". Full crew keeps quick mode and dispatches every crew member the job can use.
PASS if the plan or final reply says the sound designer (`showtime:sound-designer`) will build or mix the music
bed, and it also plans a critic review (two rounds, or at least one) and does not open a studio board or wait
for a concept pick or a storyboard sign-off before building.
FAIL if it leaves the music to the director alone with no sound designer, treats "full crew" as studio mode
(a concept pitch, a board or a storyboard gate), or asks the user to pick a concept before building.
