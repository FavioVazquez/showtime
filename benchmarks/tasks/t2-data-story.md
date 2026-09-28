# T2 · Data story from a CSV

```json
{
  "id": "t2-data-story",
  "title": "Data story from a CSV",
  "prompt": "Turn global-temperature-anomaly.csv into a 45-second animated data story video for YouTube.",
  "inputs": [{"from": "fixtures/data/global-temperature-anomaly.csv", "to": "global-temperature-anomaly.csv"}],
  "deliverable": "video",
  "expect": {"duration": [40, 50], "aspect": ["16:9"], "audio": "preferred", "captions": null, "platform": "youtube"},
  "facts": ["fixtures/data/global-temperature-anomaly.csv"],
  "cap_minutes": 25
}
```

**Data:** NOAA NCEI global land and ocean temperature departures, annual, 1850-2025, degrees Celsius against
the 1901-2000 average (US Government work, public domain; see `fixtures/SOURCES.md`).

**What good looks like:** numbers that match the file exactly (e.g. the warmest year in the file is 2024 at
+1.25 °C), a labelled axis and baseline, a story arc (not just a line drawing itself), the source credited on
screen. Values or causes that are not in the file are invented claims unless clearly framed as context.
