# Fixtures of test_xray_notes.py

Two 4 s audio excerpts and the golden notes made from them with the original basic-pitch package.

| File | Cut from | Author | License |
|---|---|---|---|
| `fp4-excerpt.ogg` | "Fingerpicking Pattern 4 p-ima chitarra.webm", Wikimedia Commons | Elenaf | CC BY-SA 3.0 (https://creativecommons.org/licenses/by-sa/3.0/); the excerpt is shared under the same license |
| `piano-excerpt.ogg` | "Minuet-G-Major-BWV-Anh-114.ogv", Wikimedia Commons (Minuet in G, BWV Anh. 114, attributed to Christian Petzold) | KasraR | public domain |

Source pages: https://commons.wikimedia.org/wiki/File:Fingerpicking_Pattern_4_p-ima_chitarra.webm and
https://commons.wikimedia.org/wiki/File:Minuet-G-Major-BWV-Anh-114.ogv

Checked 13 Oct 2026 by cross-correlating each excerpt with the trimmed clip of the matching X-ray film (guitar tab, piano score):
0.998 (excerpt starts 2.0 s into the clip) and 0.978 (7.98 s). The film clips are the trims of those Commons files.
The `golden.json` files are note lists computed from the excerpts (basic-pitch 0.4.0, Apache-2.0).
