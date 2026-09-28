# Fixture sources and licences

Every input the benchmark hands to an agent is listed here. Nothing else is placed in a run's workspace.

| Fixture | Source | Licence |
|---|---|---|
| `quillsort/` | Written for this benchmark. quillsort is a fictional tool (the code works). | MIT (see `quillsort/LICENSE`) |
| `logo/brightloom.svg`, `logo/brand.md` | Written for this benchmark. Brightloom is a fictional brand. | CC0 |
| `notes/tides.md` | Written for this benchmark from standard textbook physics. | CC0 |
| `data/global-temperature-anomaly.csv` | NOAA National Centers for Environmental Information, Climate at a Glance: Global Time Series, land and ocean, January-December, 1850-2025, retrieved 2026-09-27 from `https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series/globe/land_ocean/12/12/1850-2025/data.csv` (file kept verbatim). | US Government work, public domain |
| `data/mauna-loa-co2-annual.csv` | NOAA Global Monitoring Laboratory, Mauna Loa annual mean CO2 (`https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.csv`, file created 2026-09-05, retrieved 2026-09-27). Header comments removed and columns renamed; values unchanged. Data before April 1974 were measured by C. David Keeling, Scripps Institution of Oceanography. Citation: Lan, X., Tans, P. and K.W. Thoning: Trends in globally-averaged CO2 determined from NOAA Global Monitoring Laboratory measurements. | NOAA GML data are "made freely available to the public"; credit NOAA GML and Scripps |
| `media/interview.mp4` (fetched, not in git) | NASA Image and Video Library, "Bob Crippen Interview on STS-1: Soundbites" (KSC, 2021), 63.8 s excerpt from 79.6 s; exact URL, SHA-256 and trim in `media/interview.source.json`. | NASA media, public domain; no endorsement implied |

`fetch_fixtures.py` downloads the one media file, checks its SHA-256 against the pinned value, trims and
re-encodes it with the benchmark's ffmpeg, and writes `media/interview.mp4` (ignored by git).
