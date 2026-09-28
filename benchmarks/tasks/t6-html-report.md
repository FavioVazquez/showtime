# T6 · Shareable single-file HTML video report

```json
{
  "id": "t6-html-report",
  "title": "Single-file HTML video report",
  "prompt": "Make a shareable single-file HTML video report on the Mauna Loa CO2 record in mauna-loa-co2-annual.csv that I can send to my team.",
  "inputs": [{"from": "fixtures/data/mauna-loa-co2-annual.csv", "to": "mauna-loa-co2-annual.csv"}],
  "deliverable": "html",
  "expect": {"single_file": true, "network_requests": 0, "max_mb": 16, "plays": true},
  "facts": ["fixtures/data/mauna-loa-co2-annual.csv"],
  "cap_minutes": 25
}
```

**Data:** NOAA GML Mauna Loa annual mean CO2, 1959-2025, ppm (US Government work; the 1959-1974 part was
measured by Scripps Institution of Oceanography; see `fixtures/SOURCES.md`).

**What counts:** one `.html` file that opens offline (0 network requests when loaded from disk), plays as a
video or timed animation with at least play/pause, shows the data correctly (1959: 315.98 ppm, 2025:
427.35 ppm), works in a phone-width viewport. An MP4 plus a page that links to it does not count as single
file.

**Automatic checks:** `scoring/html_probe.mjs` loads the file in headless Chrome with the network blocked and
records requests attempted, console errors, page size, whether anything animates between t=0 s and t=3 s,
controls found, and a phone-width screenshot.
