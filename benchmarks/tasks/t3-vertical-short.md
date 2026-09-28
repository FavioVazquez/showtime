# T3 · Vertical short with voiceover and captions

```json
{
  "id": "t3-vertical-short",
  "title": "Vertical short with voiceover and captions",
  "prompt": "Make a 30-second vertical short for Instagram Reels announcing what's new in quillsort 2.0 (see CHANGELOG.md), with a voiceover and captions.",
  "inputs": [{"from": "fixtures/quillsort", "to": "."}],
  "deliverable": "video",
  "expect": {"duration": [25, 35], "aspect": ["9:16"], "audio": "required", "voice": true, "captions": "required", "platform": "reels", "lufs": -14},
  "facts": ["fixtures/quillsort/CHANGELOG.md", "fixtures/quillsort/README.md"],
  "cap_minutes": 25
}
```

**What good looks like:** 9:16 at 1080x1920 (or at least 720x1280), speech that says what the CHANGELOG says,
captions that match the speech word for word and stay inside the Reels safe zone, loudness near -14 LUFS,
no clipped peaks.

**Automatic checks specific to this task:** local ASR of the output compared with the captions (sidecar or
burned-in, the latter judged from frames), voice present, caption timing offset.
