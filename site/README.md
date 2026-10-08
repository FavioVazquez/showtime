# The showtime site

A companion site for the repository: a landing page with the hero film, a gallery that plays every
example, the crew, the documentation (rendered from `skills/showtime/references/`, with a sidebar and
search) and the interactive HTML videos. It is plain static files with relative links, built by one
Python script: no framework, no trackers, no cookies, no external requests (the fonts are served from
the site itself, under their OFL licenses in `static/fonts/`).

| Path | What it is |
|---|---|
| `build.py` | the build: Markdown to HTML (markdown-it-py), pages, search index, media copy |
| `config.json` | the one value to set: `repo` (`owner/name`); plus `site_url` (the published address), the version and the hero film (its folder, film, still, length and credit) |
| `content/crew.json` | the one-line job of each crew member, as the crew page shows it |
| `content/previews.json` | the 4-second window of each example the gallery previews on hover |
| `static/` | `style.css`, `app.js` (theme, gallery filters and players, copy buttons, search), fonts |
| `tools/hero_loop.py` | cuts a seamless loop (dissolving its end into its start) from a film; it made the 0.2.0 hero teaser in `examples/_launch/` |
| `tools/benchmark_pages.py` | the benchmark report pages at `/benchmark/` (one per version, from release assets), with a bar that links the versions and the newest rounds' write-up (`benchmarks/rounds/r5-allout.md`) |

## Build it locally

```bash
git clone https://github.com/FavioVazquez/showtime-examples ../showtime-examples   # the examples, next to this clone
python3 -m pip install markdown-it-py  # or use showtime's venv: ~/.showtime/venv/bin/python
python3 site/build.py --media-from ../showtime-examples/examples/    # writes site/_site/
python3 site/build.py --examples ../showtime-examples/examples --out /tmp/site --clean
```

Open `site/_site/index.html` in a browser (it works from disk) or serve the folder with
`python3 -m http.server -d site/_site`. The examples live in their own repository,
[showtime-examples](https://github.com/FavioVazquez/showtime-examples); the build reads them from
`--examples DIR`, else from a clone next to this one (`examples_dir` in `config.json`,
`../showtime-examples/examples`). `--media-from` says where the example videos are: that clone's
`examples/` folder (the release assets are there if you downloaded them), or a folder of release assets
named as in its `examples/MEDIA.json`; repeat it to look in several. A video that
is not found is skipped: its card shows the preview loop and links to the release asset instead.

- `--repo owner/name` turns links to repository files into GitHub links and adds release links.
  Without it (and with `config.json` `repo` empty) those links render as plain text.
- `--only 05,20,22` copies the full videos of those examples only: a small preview build.
- The gallery previews each example on hover with a silent 4-second clip and a still, cut with ffmpeg from
  the window in `content/previews.json` (showtime's own ffmpeg, `$SHOWTIME_FFMPEG`, or one on `PATH`;
  cached in `site/_cache/`). Without ffmpeg, or with `--no-previews`, it uses the README loops instead.
- Search: `search-index.js` holds each page whole, in sections (one per h2 and h3), so a hit opens its section.
  The index and the typed query share one rule (`SEARCH_SEPARATORS` in `build.py`, `norm()` in `app.js`):
  `` ` * _ > | # - `` become spaces, so `pr-video` finds "pr video". The build fails if the index names a page
  twice, a page it did not write, or an anchor the page does not have.
- Raw HTML in the Markdown is limited to the tags the docs use on purpose (`HTML_TAGS` in `build.py`: pictures,
  centred paragraphs, the example tables, `<kbd>`, `<details>` and a few more). Any other tag, such as a
  `<title>` or `<project>` placeholder in prose, is shown as text.
- Link previews: every page has `og:title`, an `og:description` of whole sentences (about 200 characters, never
  cut inside a sentence), `og:url` and a canonical link. The address comes from `site_url` in `config.json`, else
  the GitHub Pages address of `repo`. The HTML videos copied under `media/` get the same tags, with their
  example's description and poster: the exports in the media release are older than the export's own share
  tags (`share` in showtime.json, `references/html-export.md`). Tags an export wrote itself win where they can.
- `sitemap.xml` (every page and HTML video), `robots.txt` (allows everything and names the sitemap) and `llms.txt`
  (a short Markdown index for agents: what showtime is, how to install it, and every docs page with one
  sentence) are written at the site's root. On a project site such as `faviovazquez.github.io/showtime/`,
  crawlers read only the host's own robots.txt, so give the sitemap's address to a search console directly.
- Every build ends with a check: each page has one `<title>` and a footer, and a page made from one Markdown
  file has as many h2 headings as that file. A failure names the page and the cause, and the build exits
  with an error.
- `_site/` and `_media/` are git-ignored.

## Deploy to GitHub Pages

`.github/workflows/pages.yml` builds and deploys on every push to `main` that touches the site, the
docs or the art, on a `repository_dispatch` event named `examples-updated` (send one after changing
showtime-examples: `gh api repos/FavioVazquez/showtime/dispatches -f event_type=examples-updated`), and on
demand. It checks out showtime-examples into `_examples/`, downloads that repository's media release
(named in its `examples/MEDIA.json`; `gh release download <tag> --pattern '*.mp4' --pattern '*.html'`)
into `_media/`, then runs `python3 site/build.py --examples _examples/examples --media-from _media
--repo $GITHUB_REPOSITORY`. While showtime-examples is private, the workflow needs a secret
`EXAMPLES_TOKEN` with read access to it; once it is public, the default token is enough. A full build is about 580 MB, under the Pages limit of 1 GB.

## Publish checklist

Do these once, in order, when the repository goes public.

1. **Repository.** `site/config.json` already names `FavioVazquez/showtime` (CI passes
   `$GITHUB_REPOSITORY`, which wins). The site is served at `https://faviovazquez.github.io/showtime/`;
   Pages works while the repository is private on GitHub Pro, but a private repository's Pages site is
   still public to anyone with the link.
2. **Media release.** In showtime-examples, publish the example media as the release named in its
   `examples/MEDIA.json` (`python3 scripts/publish_media.py --upload`). The release lives in the examples repository (its `release`
   entry names it), so the links in `examples/README.md` and `README.md` already point at
   `https://github.com/FavioVazquez/showtime-examples/releases/download/<that tag>/`; if the tag changes,
   regenerate them (`python3 scripts/publish_media.py --links`).
3. **Launch film.** `python3 scripts/publish_media.py --upload` (in showtime-examples) publishes the films in `examples/_launch/`
   (16:9, 1:1, 9:16 and the HTML video) and `examples/_showreel/` (the 0.3.0 showreel and its HTML video)
   with the rest of the media. The landing page loops the showreel's silent teaser
   (`examples/_showreel/teaser-16x9.mp4` and `.webm`, in git) over its still (`teaser-16x9.jpg`), and its
   one button, "Watch the film", plays `showreel-16x9.mp4` with sound (downloaded from the release at deploy
   time); `hero` in `config.json` names these files. The 0.2.0 launch film plays at the top of the gallery
   (`gallery.html#launch-film`) and the crew film on the crew page (`crew.html#film`). Viewers who ask for
   reduced motion see the still only. Each film's music credit is under it and in the footer; the
   composer's terms mean the audio never ships as a separate file.
4. **Turn on Pages.** Settings > Pages > Build and deployment > Source: **GitHub Actions**. Then
   Actions > pages > Run workflow (or push to `main`). The site appears at
   `https://faviovazquez.github.io/showtime/`.
5. **Link the site.** `README.md` (navigation and Docs) and `docs/README.md` already link to that
   address; check the links once the first deploy is green, and add it as the repository's website
   (the gear next to "About").
6. **Hero video in the README.** Until this step, the README shows the film's poster
   (`assets/readme/launch-poster.jpg`: the wordmark, the promise, example 19's real request and a frame of its video, and a play label) linking
   to the release asset. The site's hero uses the same design without the play label (`launch-poster-plain.jpg`). GitHub plays an MP4 with sound in a
   README only when it is a user attachment:
   1. On github.com, open `README.md` and click the pencil (Edit).
   2. Find `<!-- HERO-VIDEO-URL -->` near the top. Delete the whole `<p align="center">...</p>` paragraph
      right under it (the poster image and its link). Leave the caption paragraph below it alone.
   3. With the cursor on the now-empty line, drag `launch-16x9.mp4` from your computer into the editor
      (68 MB, under the 100 MB limit; it can take a minute). GitHub inserts a line like
      `https://github.com/user-attachments/assets/1a2b3c...`.
   4. Make sure that URL is alone on its line, with an empty line before and after it (no brackets, no
      `<video>` tag), and commit. The README now plays the film with sound; the caption keeps the music
      credit.
7. **Social preview.** Settings > General > Social preview > Edit > Upload an image:
   `assets/readme/social/launch-1280x640.jpg` (1280x640: the wordmark and promise, with example 19's request and a frame of its video). The site
   already uses it as its `og:image`.
8. **Check the film in Safari.** Open the site on a Mac and an iPhone: the teaser should loop silently,
   and "Watch the film" should play the film with sound. (Chrome and the WebKit engine are checked
   automatically.)
9. **Benchmark.** When the benchmark is published, fill the hidden `BENCHMARK SECTION` in `README.md`
   (instructions inside the comment) and add it to the navigation line.
