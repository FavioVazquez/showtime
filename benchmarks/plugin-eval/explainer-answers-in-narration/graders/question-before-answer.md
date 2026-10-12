---
type: llm
focus: trace
---

The user's narration (L1 to L8) already contains the answers: L4 gives the reason for the SYN-ACK and L6 to L7 give
the reason for the third step. The viewer must be asked before they are told.
PASS if every planned question is placed (`at`) on a line before the line that tells its answer, and the plan
deals with answers that sit inside the user's own lines: it moves or splits the line, or says which line it
cuts to or reorders, so nothing reveals the answer before the question. The user's narration may be changed for
this, if the plan says so.
FAIL if a question is placed on or after a line that already states its answer (for example the question about the
second step placed after L4, or a question about the third step placed after L6), if the plan keeps all eight
lines in order with questions at the end, or if there is no plan.
