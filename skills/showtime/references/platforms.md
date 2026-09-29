# Platforms: delivery specs and cut-downs

Read this when you choose a format for a platform, plan cut-downs, check safe zones, or write share
copy for the post.

Numbers checked in September 2026. Platforms change limits often, so when a spec decides a hard
cutoff (a length cap, a file-size cap), say it's "as of 2026" and suggest the user double-check.
`showtime deliver exports <video|job> --targets ...` builds the platform variants (`--help` lists the targets; a job means its latest final, and the job logs a `deliver` stage).

## 1. Master encode (every export starts here)

- MP4, H.264 High profile, `yuv420p`, progressive, BT.709 primaries/transfer/matrix **tagged**, limited
  (TV) range, `+faststart` (index at the front), closed GOP of half the frame rate.
- Audio: AAC-LC, 48 kHz stereo, 256 kbps (what `showtime render` and `deliver exports` write; the encoded
  true peak is re-checked after the AAC encode). Drafts use 128 kbps.
- Frame rate: **30 fps** by default. Use 60 fps only for scroll- or cursor-heavy screen recordings, and 24 fps only for
  footage-led cinematic pieces. Never mix rates inside one timeline. Conform footage to the project rate.
- Quality: CRF 16 for normal finals, **CRF 14–16 plus 1.5–3% grain** for anything a platform will
  re-encode (flat graphics at CRF 18 end up around 1 Mbps and band after re-encoding).
- Even pixel dimensions only (odd sizes break 4:2:0 encoding).
- Loudness: **−14 LUFS integrated, ≤ −1.0 dBTP true peak, LRA ≤ 8 LU** (the house default for every web platform).

## 2. Spec table

| Target | Size / aspect | Max length | Video bitrate | Notes |
|---|---|---|---|---|
| YouTube | 1920×1080 or 3840×2160, 16:9 | 12 h (15 min for unverified accounts) | 1080p30 8 Mbps, 1080p60 12, 1440p30 16, 2160p30 35–45 | Normalizes loud audio down, never quiet audio up |
| YouTube Shorts | 1080×1920 (1:1 also counts) | 3 min | 8–12 Mbps | Vertical or square ≤3 min is classified as a Short |
| TikTok | 1080×1920 | 60 min upload, 10 min in-app recording | 8–12 Mbps | iOS app upload about 287 MB; desktop web allows multi-GB |
| Instagram Reels | 1080×1920 | 3 min for reach to non-followers (longer uploads exist on some accounts, followers only) | 5–10 Mbps | Profile grid crops the cover to the center 3:4 |
| Instagram feed | 1080×1350 (4:5) or 1080×1080 | Videos now post as Reels, so the Reels caps apply | 5–10 Mbps | 4:5 takes the most feed height |
| X | 1920×1080, 1080×1080, 1080×1350 | 2:20 without a paid tier (512 MB) | 6–10 Mbps | ≤60 fps; prefer 4:5 over 9:16 for vertical on X |
| LinkedIn | 16:9, 1:1, 4:5, 9:16 | 15 min desktop, 10 min mobile, 3 s minimum, ≤5 GB | about 8 Mbps | 30 fps; 4:5 or 1:1 fills the mobile feed best |
| Website hero loop | 1280–1920 wide, 16:9 or 21:9 | 6–20 s | 2–4 Mbps | No audio track at all; seamless loop; autoplay muted inline |
| GitHub README / PR | 1280×720 or 1920×1080 | — | Fit the file size | ≤10 MB on free plans (100 MB paid); MP4, MOV or WebM |
| Chat (Slack, Discord, email) | 1280×720 or 1080×1080 | — | Fit the file size | Keep ≤10 MB to fit every free tier; frame 0 becomes the thumbnail |
| Event screen / broadcast | 1920×1080 or 3840×2160 | — | 20–50 Mbps | −23 LUFS / −1 dBTP (EBU R128) or −24 LKFS / −2 dBTP (US broadcast), only if asked |

File-size budget: `video_kbps = (MB × 8000 / seconds) − audio_kbps`, then take 5% off for container overhead
(upload limits are decimal MB, and every showtime command prints decimal MB). `showtime deliver exports
<video> --targets github` (or `chat`, `web`, or `original --max-mb 20`) does this for you: a two-pass
encode at the master's size that lands just under the cap. Example: 10 MB, 30 s, 128 kbps audio gives about
2,400 kbps video. Below about 1,500 kbps at 1080p, drop to 720p rather than starving the encoder.
A master already under the budget is never inflated toward the cap: it gets a quality (CRF) encode capped
at the budget's rate, so a 2.5 MB sting stays about 2.5 MB as a `web` export.

`--max-mb` rules: a bare number (`--max-mb 20`) caps `original`, `github`, `chat`, `web` and the image loops,
never the upload platforms listed with them (`--targets youtube,original --max-mb 20` leaves YouTube at full
quality). With only platform targets (`--targets shorts --max-mb 19`) it caps those. Name a target to cap it
alone: `--max-mb shorts:19,original:20`.

Aspect: `x` and `linkedin` play 1:1 and 4:5 as they are, so a square or 4:5 master keeps its aspect there
(`--fit blur|crop|pad` converts to 16:9 anyway); the vertical targets and YouTube always convert.

Loudness: exports use each platform's −14 LUFS unless the job names another target (`qa --lufs -16` on the
job, or showtime.json `expect.lufs` / `loudness`), or `--lufs N` is given. The export says which one it
used. YouTube and the feeds turn louder files down and leave quieter ones as they are, so a −16 LUFS
tutorial stays −16.

### Image loops for READMEs, docs and chat (animated WebP + GIF)

A README cannot autoplay an MP4 inline, but it shows an animated image. `deliver exports` makes silent,
forever-looping images from any master:

| Target | Width | Rate | Cap | Use |
|---|---|---|---|---|
| `webp` | 960 px | 15 fps | 5 MB | README hero loop (lossy animated WebP, quality 80 to start) |
| `gif` | 960 px | 15 fps (14.3: GIF delays are whole 1/100 s) | 5 MB | its fallback, two-pass palette |
| `webp-small` | 480 px | 12 fps | 1.5 MB | showcase and docs loops |
| `gif-small` | 480 px | 12 fps (12.5) | 1.5 MB | their fallback |

```bash
showtime deliver exports final.mp4 --targets webp,gif --from 2 --to 8          # hero loop, 6 s window
showtime deliver exports final.mp4 --targets webp-small,gif-small --from 0:04 --to 0:09
showtime deliver exports final.mp4 --targets gif --width 640 --fps 12 --max-mb 2
```

- Files: `exports/<stem>.loop.webp`, `.loop.gif`, `.loop-small.*`, and `.loop-<N>mb.*` with `--max-mb`.
- `--from`/`--to` take seconds or mm:ss. Pick a 3–12 s window that starts and ends on similar frames (a
  settled title, a held UI state) so the jump back to the start is not noticed. Longer windows get a warning.
- `--width` is never enlarged past the master; `--fps` is capped at the master's rate.
- GIF: palettegen with `stats_mode=diff` (the palette favours what moves), paletteuse with Bayer dithering
  (clean flat colours, compresses well) and `diff_mode=rectangle` (only the changed area is re-coded).
- Over its cap, a loop is encoded again smaller: WebP quality first (down to 55), then the frame rate (down to
  10 fps), then the width (down to 240 px), each scaled to how far over it landed. The report lists every
  attempt; if it still does not fit, the error asks for a shorter window or a higher cap.
- In the README, use `<picture><source srcset="x.loop.webp" type="image/webp"><img src="x.loop.gif" alt="..."></picture>`,
  or just the WebP (GitHub renders it); keep a link to the full MP4 next to it for sound.
- These are image files: no audio and no loudness pass. `qa` judges MP4s, so qa the master before exporting.

## 3. Vertical safe zones (1080×1920)

Platform buttons, captions and bars cover the edges. Where it's unclear, use the **universal organic box**:
x 64 → 916, y 220 → 1440 (top 220, bottom 480, left 64, right 164).
| Platform | Keep clear: top | bottom | left | right |
|---|---|---|---|---|
| TikTok | 130–160 | 400–480 | 60 | 140–180 |
| Reels | 110–220 | 320–420 | 60 | 120 |
| Shorts | 120–380 (search bar varies) | 380–420 | 60 | 120–140 |
| Paid vertical ads (strict) | 14% (269) | 35% (672) | 6% (65) | 6% (65) |
- Hook text sits at y 300–700 and captions center on y 1150–1300. Nothing essential goes below y 1440 or in the right 164 px.
- For 16:9 on YouTube, the end screen can cover the last 5–20 s. Keep the end card's text center-top and leave room for 2–4 element slots.

## 4. Thumbnails, covers and posters

- **Poster frame:** choose the strongest *settled* frame (not mid-transition). The best default is a hook
  that is complete at t=0, with showtime.json `"poster": 0`: frame 0 is then the thumbnail and nothing
  flashes. A later poster time writes `poster.jpg`; `showtime render` bakes it into frame 0 only when it
  looks like the opening frame, because a video that builds in from empty would otherwise show the poster
  for one frame on autoplay and on every loop (qa: `poster_flash`). For YouTube, and for Reels/TikTok/Shorts
  covers, upload `poster.jpg` in the app instead of baking.
  For EDL renders and outside videos, `showtime deliver poster <video|job> --at <s> --bake` writes
  `<video>.poster.mp4`, which becomes the file that ships; inside a job it is recorded as the latest
  final (and the image as the poster), so qa and exports follow it. A poster already in frame 0 is
  not baked twice, and default outputs never overwrite (`final.poster-2.png`). Chat apps and many players use frame 0 as the
  thumbnail and ignore cover metadata; Reels, TikTok and Shorts let the user pick a cover in the app.
- **Thumbnail file:** `showtime deliver thumb <video|job> --at <s> -o thumb.jpg` (1280x720 by default,
  `--size 1080x1920 --fit crop` for a vertical cover).
- **YouTube thumbnail:** 16:9. Ship 1280×720 JPG under 2 MB as the universal file, plus 3840×2160 (≤50 MB,
  desktop upload) when the user targets TVs. One subject, ≤3–5 words at 100–200 px (at 1280 wide), high
  contrast, and nothing in the bottom-right corner (the duration badge sits there). Test legibility at 168×94.
- **Shorts/Reels/TikTok covers:** 1080×1920, with key content inside the center 1080×1440 and clear of the top and bottom UI.
- Offer 3 thumbnail variants (different crop, word and color) when the user posts to YouTube. The platform can A/B test them.
- The web `poster=` image is AVIF or WebP plus a JPG fallback, and it matches the video's first frame to avoid a flash on load.

## 5. Captions

- **Burn captions in** for TikTok, Reels, Shorts, X and LinkedIn feed posts. Most feed video plays muted.
- **Also ship a sidecar** (`.srt` or `.vtt`) for YouTube and LinkedIn, which index it and let viewers turn it off.
  If you burn captions in *and* upload a sidecar, tell the user to leave the platform's auto captions off.
- Caption styles, sizes and positions: see `typography.md` §6 and the captions reference.
- A video with narration but no captions is not finished for social delivery.

## 6. Cut-down strategy

Plan cut-downs up front, not after the render:
1. **Design the safe core.** Keep the story's essential content (hero UI, key words, logo) inside the center
   area that survives every crop: for a 16:9 master that's the center ~1080×1080 region, and for a
   9:16 master the center 1080×1350.
2. **Re-lay out; don't just crop.** A 16:9 layout cropped to 9:16 produces tiny type and amputated UI.
   Build aspect-specific layouts from the same scenes: stack side-by-side elements vertically, scale
   type up about 1.3×, and use fewer words per line. Put the width and height in `showtime.json` per
   variant and keep scene code relative (percentages, container units), so one project renders every aspect.
3. **Shorten from the middle.** Keep the hook and the close, then drop feature beats in reverse order of strength:
   60 s → 30 s (hook + 2 features + close) → 15 s (hook + 1 feature + close) → 6 s (one image, one line, logo).
   Re-time the music to end on its button (don't fade mid-phrase), and re-check readability holds.
4. **Per-platform tweaks:** loopable ending for Shorts/TikTok/Reels (the last frame flows into the first),
   a strong cover frame for Reels, 4:5 for X/LinkedIn/IG feed, and no audio plus a seamless loop for web heroes.
5. **Check each export** with the qa.md post-render list: duration cap, size, loudness, safe zones, captions and poster.

## 7. Share copy per platform

Always write `share.txt` in the job folder: 1–3 postable sentences in the video's tone. No "excited to share", no
hashtag walls, and no claims that aren't in the video. Add variants as needed:
- **X:** ≤280 characters (a link counts as 23), 0–2 hashtags, the hook line first.
- **LinkedIn:** the first ~140 characters show before "see more", so put the point there. 3–5 short lines.
- **YouTube:** title ≤100 characters with the key idea in the first ~60. The description's first 2 lines carry the value.
  Add chapters when the video is over 2 min (first at 0:00, ≥3 chapters, each ≥10 s).
- **TikTok / Reels:** one line and one question or CTA, 3–5 relevant hashtags.
- **GitHub README:** a one-line caption under the video plus alt text.
- If the video uses CC-BY assets, remind the user that the lines in `credits.txt` (written beside the final)
  must go in the description. Render keeps them in a `--- Credits (keep in the video description) ---`
  block at the end of `share.txt`: write the post copy above it and leave the block in (a Scott Buckley
  track without it gets a Content ID claim on YouTube).
