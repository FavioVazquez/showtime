# Captions for real footage

Read this when a footage edit needs burned-in captions or subtitle files: choosing a style,
the grouping rules, sizes and safe zones per aspect, fonts, and how to check timing. The commands
are `showtime captions` (stand-alone) and the EDL field `captions` (rendered last by
`showtime edit render`). For captions inside HTML/canvas projects use the runtime caption component
instead (`components.md`; `clean-pop` for 9:16 shorts: sentence-case heavy sans, the spoken word in
the accent). Both writers group the same way: phrase-sized cards that never end on a weak word.

## 1. Pick a style

| Style | Looks like | Use for | Avoid for |
|---|---|---|---|
| `bold-pop` | 1-3 heavy uppercase words (Anton), active word pops in yellow `#FFE500`, black outline | Shorts / Reels / TikTok, hype, fast talkers | long explanations, calm or premium tone |
| `clean` | sentence-case lines (Inter, semi-bold), max 2 lines, soft outline + shadow, 120 ms fades | YouTube, interviews, tutorials, LinkedIn | very busy or bright footage |
| `boxed` | words on one translucent dark plate per caption (drawn as a single shape, so no darker bars between words or lines), active word tinted cyan | bright/busy backgrounds, screen recordings | cinematic pieces |
| `minimal` | small light text, no outline, soft blurred shadow | premium / calm product pieces, B-roll heavy edits | muted-autoplay social (too quiet) |
| `cinematic` | serif (Instrument Serif) lower lines, slow 250 ms fades | documentary, story, founder films | fast cuts |

Default when unsure: `bold-pop` for vertical social, `clean` for everything else. Most feed video
plays muted, so social edits always get captions.

Options (CLI flags or keys in the EDL `captions` object): `font` (family or .ttf/.otf path),
`highlight` and `color` (`#RRGGBB`), `position` (`bottom`, `middle`, `top`), `max_words`,
`upper` (force caps), `fillers` (show um/uh; hidden by default), `srt` (EDL: also write
`<out>.srt`, default true). The EDL object also takes any style key from the tables below:
`size` (`{"portrait": 0.135}`), `chars`, `margin_v`, `max_dur`, `gap`, `lead`, `tail`, `min_dur`,
`min_show`. A bigger `size` without `chars` lowers the character cap to match (ASS lines never wrap).
`edit render --captions <style>` starts from that style's own defaults (the EDL's position and
size were for its style); `--caption-position middle` moves them.

For a tight talking-head crop in 9:16, `position: middle` keeps bold captions off the chest (a
name tag or a patch sits right where the default bottom band is).

## 2. Grouping rules

A new caption starts at: a sentence end (`. ! ? …`), a comma/colon followed by a pause of 0.15 s
(or once 2 words are shown), a pause of at least the style's gap, a speaker change, or the
style's word / character / duration cap. When speech is fast the word cap tightens (more than 3.5
words/s in a 2 s window -> 2 words, more than 2.5 -> 3). A caption does not end on a weak word
(articles, prepositions, conjunctions, auxiliaries: "the", "to", "before", "is", and the common
Spanish, French, Portuguese and German ones): the word moves to the next caption, or the next
caption's first word moves back, when the result fits and neither half would flash ("CLEARS EMPTY
LINES BEFORE" / "SORTING." becomes "CLEARS EMPTY LINES" / "BEFORE SORTING."). A single leftover word
joins the previous caption when it fits. Word timings are never moved; only caption in/out times are.

Flashes: a caption on screen for less than the style's `min_show` (0.7 s for sentence styles, 0.4 s
for karaoke) joins a neighbour when the words fit; the reading-speed pass never splits a caption into
halves shorter than that (a fast speaker then gets an honest qa `caption_fast`, not 1-word blinks).
In sentence styles a tail of 3 words or fewer ("into a gas.") joins the caption before it when that is
the same sentence and it still reads in time. With an EDL, a caption that would start just after a
cut (up to 0.25 s) starts on the cut and the one before ends there, so no text hangs over into the
next shot. Lines do not end on a function word ("the", "of", "de" ...) or split a capitalized name
when a nearly as balanced break exists.

| Style | Words | Lines x chars (portrait / square / landscape) | Max on screen | Break at pause | Lead / tail | Min on screen |
|---|---|---|---|---|---|---|
| bold-pop | 3 (2 when fast) | 1 x 18 / 20 / 26 | 2.2 s | 0.25 s | 40 / 120 ms | 0.3 s (0.4 s before merging) |
| clean | 12 | 2 x 26 / 30 / 42 | 6.0 s | 0.6 s | 80 / 450 ms | 0.8 s |
| boxed | 6 | 2 x 22 / 26 / 34 | 3.5 s | 0.4 s | 60 / 250 ms | 0.5 s |
| minimal | 10 | 2 x 30 / 34 / 48 | 5.0 s | 0.6 s | 80 / 400 ms | 0.8 s |
| cinematic | 10 | 2 x 26 / 32 / 44 | 5.5 s | 0.7 s | 120 / 500 ms | 1.0 s |

Every style stays inside the limits `showtime qa` checks (one shared module, `lib/st/captions_rules.py`):
lines of at most 42 characters, 32 on vertical video (4:5 included), so wider style values above are
capped. The cap is per line: a caption only takes the next word when its lines still wrap within it
(two long French or German compounds can fill 84 characters and still need a 45-character line, so they
become two captions); and a caption of 3 or more words stays on screen long enough to read at 20 characters/s or
slower, borrowing free time before and after it, or splitting in two when there is none. Karaoke
styles write one ASS event per caption group with the active word animated inside it.

Timing: a caption appears `lead` before its first word and stays until `tail` after its last word,
never overlapping the next one, and at least the minimum time. Two-line captions break at the
most balanced point and never leave a one-word line. Fades only happen when the screen was empty
before (or will be after), so back-to-back captions do not flicker.

SRT/VTT files (for platforms and accessibility) always use the `clean` rules: at most 2 lines of
42 characters (32 on vertical video), 0.83-7 s per cue, the same reading speed, fillers removed;
`--max-words` applies to them too. An `.srt`/`.vtt` input keeps its own cues and line breaks, in the
ASS and the sidecars alike (restyle only); `--regroup` regroups its words instead.
`voice script`'s `vo.srt` follows the same rules.

## 3. Sizes and safe zones

`PlayResX/PlayResY` equal the video size, so sizes are real pixels. Size is a fraction of the
frame's short side; the bottom margin is a fraction of the height. `showtime captions ... --text-scale 1.2`
(same flag: `--size-scale`) makes a style's text 20 % larger (0.5-2.5) and lowers its line cap to match: use
it when the captions will be watched small (a 16:9 video in a phone's portrait player) or a critic asks for
bigger burned Shorts captions (`--size-scale 1.4 --max-words 4`).

| Style | Size portrait / square / landscape | Bottom margin portrait / square / landscape |
|---|---|---|
| bold-pop | 0.105 (113 px at 1080x1920) / 0.092 / 0.08 (86 px at 1920x1080) | 0.30 / 0.18 / 0.14 |
| clean | 0.052 (56 px) / 0.05 / 0.046 (50 px) | 0.27 / 0.10 / 0.075 |
| boxed | 0.058 / 0.054 / 0.05 | 0.28 / 0.12 / 0.08 |
| minimal | 0.04 / 0.038 / 0.034 | 0.25 / 0.08 / 0.06 |
| cinematic | 0.062 / 0.06 / 0.056 | 0.26 / 0.10 / 0.085 |

- **Vertical (9:16):** platform UI covers roughly the bottom 25 % (caption, buttons) and the right
  ~15 % (action rail) and the top ~7 %. Captions sit with their baseline 25-30 % above the bottom,
  left margin 6 %, right margin 15 %. Move them to `position: top` or `middle` when the lower frame
  holds the key visual (a product, a face low in frame).
- **Square / 4:5:** 6 % side margins, 8-18 % bottom margin.
- **Landscape:** 6 % side margins (inside the 90 % title-safe area); clean subtitles sit in the
  lower 8 %; bold captions higher (14 %) so they do not collide with player controls.

Portrait = height/width above 1.3, square = 0.77-1.3, landscape below 0.77.

## 4. Fonts

libass only uses fonts handed to it as TTF/OTF files. showtime always passes explicit files:
fonts fetched with `showtime assets font ...` (in `~/.showtime/assets/fonts`), otherwise the OFL
Fontsource packages installed by setup, converted once from WOFF/WOFF2 to TTF in
`~/.showtime/cache/fonts`. Families that work out of the box: anton, bebas-neue, inter, geist,
space-grotesk, bricolage-grotesque, fraunces, unbounded, ibm-plex-sans, ibm-plex-mono,
jetbrains-mono, instrument-serif, noto-sans-jp. Never name a system font; it renders differently
on every machine.

An asset font is used only when it has the exact weight the style asks for (400, or 700 for bold
styles; a bold style fetches the static 700 cut once when online), otherwise the setup copy is used.
Every caption character is checked against the font's files: when the latin-only asset copy lacks
one (é is fine, Ω or 日本 are not), the setup's multi-subset copy is used if it covers more, and what
is still missing is reported (`missing_glyphs`) with a hint (e.g. `--font noto-sans-jp`). Emoji are
removed from burned captions (libass would draw them from each OS's own font); `--keep-emoji` (or
`"emoji": true` in the EDL `captions` object) keeps them.

## 5. Checking captions

- `showtime edit render` reports `captions.timing`: `words_outside_group`, `overlaps` and
  `words_missing` must all be 0.
- `showtime qa` prints the shortest cue and WARNs `caption_flash` when cues last under 0.4 s.
- Grab frames where words are spoken: `showtime footage view final.mp4 --from 4 --to 7` or
  `showtime footage scenes final.mp4 --every 1`. Check size, position against the safe zone,
  legibility over the background (switch to `boxed` over bright or busy footage).
- Reading speed: captions that carry the whole message (no voice) need at least
  `0.5 s + characters / 13` on screen.
- Emphasis: one highlighted word per caption at most, and a handful per video (3-5 in a 30 s short:
  the words that carry the message, not every product term); never animate every word's position.
  The runtime component shows only the first emphasised word of a card and `check` warns past that.

## 6. Commands

```bash
showtime captions edit/transcripts/take1.json --style clean --aspect 16:9 -o subs.ass --srt subs.srt
showtime captions t.json --edl edit/edl.json --style bold-pop -o edit/caps.ass   # edited timeline
showtime captions t.json --style boxed --burn clip.mp4 -o clip.captioned.mp4     # burn directly
showtime captions old.srt --style cinematic --size 1920x1080 -o styled.ass        # restyle a file
```

An `--srt`/`--vtt` written into the job folder itself becomes the job's latest captions (the command
says `job <name>: captions -> <file>`), which `showtime qa <job>` checks along with the latest final;
one written into a subfolder (`<job>/deliver/captions.en.srt`, a per-language upload copy) or anywhere
else never re-points the job, and the command says so. A video with its own `<stem>.srt/.vtt/.ass`
(a `final-16x9.mp4` variant) is checked against that, never the job's pointer (see qa.md).

`--burn` into a job: the captioned copy of the job's final (the default name `<final>.captioned.mp4`, or
any `final*.mp4` name) becomes the job's latest final, like `deliver poster --bake`, so `qa <job>`,
`review-pack` and `deliver exports` use it; the command prints `job <name>: latest final -> <file>`.
Burned onto another clip (a `broll.captioned.mp4`), it is logged as a variant and the final is unchanged.
The `.ass` it burned sits beside it with the same stem, so qa checks the burned captions' placement.

Podcasts and interviews with a published transcript (a show's own page, a press transcript): diarization
(`transcribe --speakers 2`) can label a whole window as one voice or give a host's "Yeah." to the guest.
When the text exists, align it instead of guessing: `showtime voice align <clip audio> -f transcript.txt
-o clip.words.json` gives word times for the known words, and the speaker of each turn comes from the
transcript's own labels (copy them onto the words of that turn as `"speaker": "S0"`). Caption grouping
then breaks at every real speaker change. When the video already burns captions (a
project page with `caption-karaoke`, `data-st="captions"` or `F.caption`, or an EDL with `captions`),
the command warns that the files it wrote are optional: keep an `.srt` only for platforms that take
a caption upload (YouTube, LinkedIn, X); Reels, TikTok and Shorts need nothing more.
