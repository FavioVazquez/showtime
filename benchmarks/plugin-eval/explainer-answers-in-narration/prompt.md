---
max_turns: 8
timeout_seconds: 600
runs: 3
tags: [trigger, contract]
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
---

Make a 3-minute explainer on why TCP needs a three-way handshake, using my narration below. It should stop and ask the viewer a question or two so they think before the answer. Show me the plan before you build it.

L1: Every web page you load starts with a tiny negotiation.
L2: Two computers cannot talk until each knows the other is listening.
L3: The first computer sends a SYN: "I want to talk, and my numbering starts here."
L4: The second answers with a SYN-ACK. Why not just one reply? Because it must also pick its own starting number.
L5: The first confirms with an ACK, and only then does data flow.
L6: Without the third step the second computer could never be sure its SYN-ACK arrived.
L7: Two steps would leave one side guessing; three leave both sides certain.
L8: That is the handshake: three messages so both sides agree on where to start counting.
