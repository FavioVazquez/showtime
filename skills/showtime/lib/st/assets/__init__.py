"""Asset tools: fonts, icons, emoji, license-gated stock media and subject cutouts.

Everything is fetched key-free, cached under ~/.showtime/assets (or the
project folder you ask for) and written with a `<file>.license.json`
sidecar so credits can be compiled automatically.

Modules:
    net        HTTP with a descriptive User-Agent, retries, size caps, caching
    licenses   license policy (what is allowed by default), sidecars, CREDITS.txt
    fonts      Fontsource / Google Fonts families -> TTF/WOFF2 + @font-face css
    icons      Lucide, Phosphor, Tabler, simple-icons, Heroicons -> recoloured SVG
    emoji      Noto / Fluent emoji (no attribution) -> SVG or PNG
    media      Openverse, Wikimedia Commons, NASA and museum open-access search/fetch
    cutout     foreground cutout (macOS Vision, else rembg)
"""
