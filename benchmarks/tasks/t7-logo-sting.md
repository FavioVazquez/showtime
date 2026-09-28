# T7 · Animated logo sting (smoke-test task)

```json
{
  "id": "t7-logo-sting",
  "title": "Animated logo sting",
  "prompt": "Make a 5-second animated logo sting for brightloom.svg, with sound.",
  "inputs": [{"from": "fixtures/logo/brightloom.svg", "to": "brightloom.svg"}, {"from": "fixtures/logo/brand.md", "to": "brand.md"}],
  "deliverable": "video",
  "expect": {"duration": [4, 7], "aspect": ["16:9"], "audio": "required", "captions": null, "platform": null, "lufs": -14},
  "facts": ["fixtures/logo/brand.md"],
  "cap_minutes": 15
}
```

**What good looks like:** the real logo (not a redraw with different shapes), brand colours, a motion idea
with a clear resolve and a hold on the final lockup, a sound that lands on the resolve, no clipping, no black
first frame. Short and cheap: this is the task the smoke run uses.
