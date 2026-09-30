# Workflow: paper explainer (a research paper or technical PDF, explained with its own evidence)

Read this when the user wants a paper, preprint, thesis chapter or technical report explained: a PDF
path, an arXiv id or URL ("explain arXiv 2406.01234 in two minutes", "a video summary of this
whitepaper"). The film teaches the paper's one idea and shows its evidence, with every claim tied to a
page, equation, figure or table. For a report that is mostly numbers use `data-story.md` with the
extracted tables; for math with no paper behind it use `references/manim.md` directly.

## Essentials

- Defaults, stated not asked: 90 s (60-180), 16:9 1920x1080, voice at 2.5 words/s (2.2 for specialists),
  Manim for the math, a quiet `underscore` bed, captions; say how the figures are licensed (§ Defaults)
- Licenses first: CC BY or CC0 figures may be shown with credit and a `.license.json` sidecar; NC, ND, the
  default arXiv license or none: redraw the idea, never show the figure (§ Licenses first)
- Structure: the question, the idea, how they test it, what they found, what it does not show, the citation
  (§ The structure)
- `showtime doc extract` the PDF; every sentence and label has a page, equation, figure or table row in
  `work/claims.md`; numbers match the paper exactly on screen (§ Steps)
- Equations typeset from the paper with Manim, each term on the word that names it, labelled "Eq. N, p. M"
  (§ Steps)
- `showtime check`, `showtime look`, `showtime render <project> --job <job>`, `showtime qa <job>` (fails a CC-BY
  video without `credits.txt`) (§ Steps)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 35-39 |
| Defaults | 41-47 |
| Licenses first (before any figure goes on screen) | 49-63 |
| The structure | 65-74 |
| Steps | 76-108 |
| Pitfalls | 110-118 |
| Read next | 120-123 |

## Inputs

- The PDF, or an arXiv id: download the PDF from its arXiv abstract page (`https://arxiv.org/abs/<id>`,
  the "View PDF" link) into `<job>/sources/`, and save the abstract page's license line with it.
- Helpful: the audience (specialists, students, general), the length, what the user cares about.

## Defaults

60-180 s (90 s when nothing is said), 16:9 at 1920x1080, voice-led at the natural pace for a general
audience (2.5 words/s) or the technical pace for specialists (2.2 words/s); Manim for the equations
and anything the math can show moving, a DOM page or canvas film for the rest; a quiet `underscore`
bed; captions. State in the opening line: length, audience, the one idea you will explain, and how
the paper's figures are licensed (used and credited, or redrawn from the paper's data).

## Licenses first (before any figure goes on screen)

- The arXiv abstract page states the license. CC BY: figures may be shown with a credit. CC0 or
  public domain (for example a US government work): no credit needed, give one anyway. CC BY-SA: the
  video must carry the same license; say so and ask. Anything NC or ND, the default arXiv license,
  or no license stated: do not show the paper's figures; redraw the idea yourself (Manim, a chart
  from the numbers in the text, with the page cited) or ask the user for permission they hold.
- Facts, equations and numbers are not owned: restate them in your own drawing with a citation.
  Quote the paper's words only in short phrases, in quotation marks, with the page.
- Every figure used gets a sidecar next to the image file, `<figure>.png.license.json`:
  `{"source": "arXiv:<id>", "title": "<paper title>, Figure 3", "author": "<authors>", "license":
  "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/", "landing_url":
  "https://arxiv.org/abs/<id>", "attribution_required": true, "credit": "Figure 3 from <authors>,
  <title> (arXiv:<id>), CC BY 4.0"}`; `showtime assets credits <job>/project -o <job>/credits.txt`
  compiles them and `showtime qa` fails a CC-BY video without it.

## The structure

| Part | Share | On screen |
|---|---|---|
| 1. The question | 10-15 % | the problem in the reader's terms, why it was open (cited) |
| 2. The idea | 20-25 % | the one mechanism, built up one layer at a time (Manim when it is math) |
| 3. How they test it | 15-20 % | the setup in one picture: data, baseline, measure |
| 4. What they found | 20-25 % | one figure or one table row, with its page, the number read exactly |
| 5. What it does not show | 10 % | the limits the paper states (cite the page), never your own critique presented as theirs |
| Close | 5-10 % | the citation: authors, title, venue or arXiv id, year, license |

## Steps

1. **Job.** `showtime job init <short-title>-paper --goal "..."`.
2. **Extract.** `showtime doc extract <job>/sources/paper.pdf -o <job>/sources/paper` (text by
   page in `text.md`, figures and their captions and credit lines in `figures.md`, embedded images,
   page renders; `capture.md` section 5b). Read the abstract, introduction, the method's key
   equations, the main result, and the limitations section.
   *Done when:* you can state the one idea in a sentence and point to its page.
3. **Claims ledger.** `<job>/work/claims.md`: every sentence of narration and every label on screen,
   with its source as page (and equation, figure or table number). Numbers match the paper exactly on
   screen (round only in narration, "about four in five"). A claim with no row is cut.
4. **Script.** One paragraph per part, following the narration guide in `repo-explainer.md`
   ("Narration: explain like a good lecturer"): connected sentences, one concrete case, numbers only
   when they mean something, no fragment stacks. Save as `narration.md` with one `## id` per scene.
5. **Math with Manim.** For each equation or derivation that carries the idea:
   `showtime manim new <job>/manim --template equation` (or `graph`, `plane`), write the scene so each
   term appears on the word that names it (`showtime manim cues`), `showtime manim check`, then
   `showtime manim render <job>/manim` for a draft sheet. Typeset the equations from the paper
   (LaTeX), keeping its symbols so the viewer can find them in the PDF; label each with its number
   ("Eq. 4, p. 5"). `references/manim.md` has the craft rules and the 9:16 layout.
6. **Figures.** A licensed figure: use the extracted image (or crop a vector figure from the page
   render), shown whole first with its caption and credit, then a camera push onto the part the
   narration talks about (`ken-burns` or `camera` in `components.md`). An unlicensed one: redraw it.
7. **Assemble.** One page or one Manim project: a Manim clip can be a layer in a DOM page
   (`references/manim.md` section 11), so the usual build is a DOM page with the Manim clips, figures and
   the citation card; the voice drives the scene lengths (`showtime voice script ... --fit <target>`,
   then `showtime retime <project> --from-voice ...`).
8. **Check, render, verify.** `showtime check`, `showtime snap` (read the sheet against claims.md),
   `showtime render <project> --job <job>`, `showtime qa <job>` (it fails without `credits.txt` when a
   CC-BY figure is used). Quality mode (the default; lean: publish-bound only): the critic, and a
   researcher pass over claims.md.
9. **Deliver.** Share copy with the full citation and the arXiv or DOI link, `credits.txt`, and the
   delivery card.

## Pitfalls

- Explaining the abstract instead of the idea: the abstract is a list of results; the film needs the
  one mechanism that produces them.
- A number from the paper re-computed or rounded on screen ("30 %" where the table says 29.6 %).
- The paper's claims presented as settled fact: say "the authors report", and show their limits.
- Equations as screenshots of the PDF: blurry, unlabelled, and the figure license may not cover them.
  Typeset them in Manim.
- A figure used because it looks good, not because the narration needs it. One figure per point.

## Read next

`references/workflows/repo-explainer.md` (narration guide), `references/capture.md` (5b documents),
`references/manim.md`, `references/assets.md` (sidecars, credits), `references/story.md` (section 6).
