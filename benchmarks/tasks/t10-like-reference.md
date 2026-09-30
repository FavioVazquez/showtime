# T10 · Make it like this reference

The person has a video whose look they like and wants a new one, about something else, in the same style.

```json
{
  "id": "t10-like-reference",
  "title": "Same style as a reference video",
  "prompt": "Make a 20-second video announcing our spring plant swap (details in swap.md) in the same style as reference.mp4.",
  "inputs": [{"fetch": "style-reference", "to": "reference.mp4"}, {"from": "fixtures/notes/plant-swap.md", "to": "swap.md"}],
  "deliverable": "video",
  "expect": {"duration": [17, 23], "aspect": ["16:9"], "audio": "required", "captions": null, "platform": null},
  "facts": ["fixtures/notes/plant-swap.md"],
  "judge_reference": {"fetch": "style-reference", "label": "reference"},
  "cap_minutes": 25
}
```

**Workspace:** `reference.mp4` (20 s, 1920x1080, made for this benchmark by `fixtures/make_reference.py`: an
announcement for a fictional evening run club) and `swap.md` (the plant swap's details), committed to a fresh
git repository.

**The reference's style** (what "the same style" means here; the agent is not told this list, it has to see it):

| Element | In the reference |
|---|---|
| Palette | three flat colours only: warm paper `#F2EEE3`, ink `#141414`, one vermilion accent `#E4412B`; no gradients, photos or textures |
| Type | one heavy condensed sans (Anton), all caps, huge, left-aligned on a wide margin (120 px); small index numbers `01/04` top left |
| Structure | a 4 s hook of single words, one per beat (0.5 s), the ground flipping paper/ink on alternate beats; three 4 s cards (a small accent label such as WHAT / WHEN / WHERE over a two-line statement); a 4 s ink end card with the name in the accent colour |
| Motion | hard cuts on the beat; card lines slide up 60 px and fade in over 0.25 s, the second line one beat later; a vermilion panel wipes left to right between sections; a thin accent progress bar fills along the bottom edge during each card |
| Sound | a 120 BPM kick on every beat with an off-beat tick, a simple bass line under the cards, one low hit on the end card, silence at the very end |
| Length | 20 s, 16:9 |

**What the judges look for** (the ranking judge also gets stills of the reference, in a `reference/` folder,
and is asked to judge style match, not subject):

- **Style match:** the palette, type, layout grid, structure, motion vocabulary and rhythm above carried over
  recognisably, without copying the reference's words or subject (a run-club video is off brief).
- **New subject, right facts:** the plant swap's name, date, time, place and rules exactly as in `swap.md`;
  nothing invented (no extra dates, prices, sponsors or plant names beyond the notes).
- **Legibility:** every card readable at phone size while it is on screen (the reference holds each card 4 s).
- **Sound:** a beat-driven bed in the reference's spirit; cuts that land on the beat.
- **Length and format:** 17-23 s, 16:9.

**Fact sources:** `swap.md` only. The reference supplies style, not facts.
