# T5 · Narrated explainer from notes

```json
{
  "id": "t5-explainer",
  "title": "Narrated explainer",
  "prompt": "Using notes.md, make a 60-second narrated explainer video about why the sea has tides.",
  "inputs": [{"from": "fixtures/notes/tides.md", "to": "notes.md"}],
  "deliverable": "video",
  "expect": {"duration": [50, 70], "aspect": ["16:9"], "audio": "required", "voice": true, "captions": null, "platform": "youtube"},
  "facts": ["fixtures/notes/tides.md"],
  "cap_minutes": 25
}
```

**What good looks like:** a narrated, illustrated explanation (Earth, Moon, the two bulges, spring vs neap)
where the pictures show what the voice says at the moment it says it, correct physics from the notes only,
pronunciation and pacing a viewer can follow, music under the voice (if any) ducked.
