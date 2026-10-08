// Turn a website into video material (screenshots, copy, brand tokens, assets, scroll video)
//
//   showtime site capture <url> [outdir]      screenshots per aspect, full-page tiles, dark variant,
//                                             site.json (copy, CTAs, testimonials, tokens, fonts),
//                                             downloaded images/logos/videos, contact sheets, inventory.md
//   showtime site component <url> <selector>  element screenshots (hero, pricing table, a card...)
//   showtime site record <url> [outdir]       paced scroll-through frames + scroll.mp4
//   --serve DIR (instead of <url>)            serve a static folder on 127.0.0.1 for the capture
//
// Bot walls (Cloudflare/"verify you are human" pages) are detected and reported, never bypassed.
// Landing on showtime's own preview player (/_st/...) or on a directory listing is an error.
import fs from 'node:fs';
import path from 'node:path';
import { launchGuarded, openGuarded, closeSoon } from './lib/stagehost.mjs';
import { parseCli, runMain, UserError, info, warn, c, jobDir, freshPath, fmtBytes, fmtDuration, printHelp, Progress } from './lib/cli.mjs';
import {
  aspectViewport, newCaptureContext, installConsent, waitConsent, cleanupOverlays, robustGoto, detectBotWall,
  blockedMarkdown, lazyScroll, scrollMetrics, neutralizeFixed, safeDownload, privateAssetsAllowed, isTracker,
  canonicalAssetUrl, contactSheet, slug, relPath, sleep, serveStatic, landingProblem,
} from './lib/capture.mjs';
import { extractPage } from './lib/extract.mjs';
import { resolveFF, ffmpeg, fpsArg } from './lib/ff.mjs';

const TOP = {
  name: 'site',
  usage: 'showtime site <capture|component|record> ...',
  summary: 'Turn a website into video material. Run `showtime site <command> --help` for details.',
  description: 'commands:\n' +
    '  capture <url> [outdir]       screenshots (per aspect), full-page tiles, dark variant, copy + brand tokens\n' +
    '                               (site.json), images/logos/videos, contact sheets and inventory.md\n' +
    '  component <url> <selector>   screenshot one element (or all matches with --all)\n' +
    '  record <url> [outdir]        paced scroll-through frames and scroll.mp4\n' +
    'A static folder (index.html, no dev server): --serve <dir> instead of <url>, e.g.\n' +
    '  showtime site capture --serve ./dist [outdir]. Never capture through `showtime server`/`preview`.\n' +
    'Outputs: ./showtime-out/<name>-site-<time>/ (capture), <name>-scroll-<time>/ (record),\n' +
    '<name>-component-<time>/ (component); <name> = the host, or the served folder.',
  examples: [
    'showtime site capture https://example.com',
    'showtime site capture --serve ./dist ./capture --aspect 16:9',
    'showtime site capture https://myapp.dev ./capture --aspect 16:9,9:16 --dark on',
    'showtime site component https://myapp.dev "#pricing" -o pricing.png',
    'showtime site record https://myapp.dev --duration 8 --aspect 9:16',
  ],
};

const COMMON = {
  serve: { help: 'serve this static folder (or .html file) on 127.0.0.1 and capture it instead of a <url>', metavar: 'DIR' },
  page: { help: 'with --serve: the page to open, e.g. /pricing.html (default: index.html)', metavar: 'PATH' },
  force: { type: 'boolean', help: 'keep going on HTTP 4xx/5xx pages, showtime preview pages and directory listings' },
  aspect: { short: 'a', default: '16:9', help: 'aspect ratio(s), comma list: 16:9, 9:16, 1:1, 4:5 (default 16:9)', metavar: 'W:H[,W:H]' },
  dpr: { help: 'device pixel ratio (default 2 desktop, 3 phone)', metavar: 'N' },
  width: { help: 'CSS viewport width (default 1440 landscape, 1080 square, 390 portrait); the height follows the aspect (--width 1280 at 16:9 = 1280x720)', metavar: 'PX' },
  timeout: { default: '60', help: 'page load timeout in seconds (default 60)', metavar: 'S' },
  wait: { default: '1.5', help: 'extra settle time after load, seconds (default 1.5)', metavar: 'S' },
  'no-consent': { type: 'boolean', help: 'do not dismiss cookie/consent banners' },
  'keep-overlays': { type: 'boolean', help: 'do not hide chat widgets / popups / sticky overlays' },
  locale: { default: 'en-US', help: 'browser locale (default en-US)' },
  'user-agent': { help: 'custom User-Agent string' },
  gpu: { default: 'auto', help: 'auto | off (software rendering)' },
  headed: { type: 'boolean', help: 'show the browser window' },
  json: { type: 'boolean', help: 'print a JSON summary on stdout' },
};

function sec(v, name) {
  const n = Number(v);
  if (!(n >= 0)) throw new UserError(`--${name} must be a number of seconds`);
  return n;
}

function normalizeUrl(u) {
  if (!u) throw new UserError('missing <url>', 'example: showtime site capture https://example.com');
  let s = String(u).trim();
  if (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i.test(s)) s = 'http://' + s;
  else if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = 'https://' + s;
  let url;
  try { url = new URL(s); } catch { throw new UserError(`not a URL: ${u}`); }
  if (!['http:', 'https:', 'file:'].includes(url.protocol)) throw new UserError(`unsupported URL scheme: ${url.protocol}`, 'use http(s):// or file://');
  return url.href;
}

const GENERIC_DIRS = new Set(['dist', 'build', 'out', 'public', 'site', 'www', 'html', '_site', 'docs', 'static', 'export']);

/** Folder label for output names: "dist" -> "<parent>-dist". */
function dirLabel(root) {
  const b = path.basename(root);
  return GENERIC_DIRS.has(b.toLowerCase()) ? `${path.basename(path.dirname(root))}-${b}` : b;
}

/** Output-name stem for a URL: the host (www. dropped), or localhost-<port> for local servers. */
function hostLabel(url) {
  try {
    const u = new URL(url);
    if (u.protocol === 'file:') return path.basename(path.dirname(u.pathname)) || 'page';
    const h = u.hostname.replace(/^www\./, '').replace(/^\[|\]$/g, '');
    if (/^(localhost|127\.\d+\.\d+\.\d+|::1)$/.test(h)) return `localhost${u.port ? '-' + u.port : ''}`;
    return h || 'page';
  } catch { return 'page'; }
}

/**
 * Resolve what to capture: --serve DIR (plain static server, stopped by the caller), a local folder or
 * .html file given as <url> (served the same way), or a URL. -> { url, server, args, name }
 * `args` = the remaining positionals (outdir, selector...).
 */
async function resolveTarget(o, what = 'capture') {
  const pos = [...o._];
  let serveDir = o.serve || null;
  if (!serveDir && pos[0] && !/^[a-z][a-z0-9+.-]*:\/\//i.test(pos[0]) && fs.existsSync(pos[0]) &&
      (fs.statSync(pos[0]).isDirectory() || /\.html?$/i.test(pos[0]))) {
    serveDir = pos.shift();
    info(c.dim(`  ${serveDir} is a local folder/file: serving it (same as --serve ${serveDir})`));
  } else if (serveDir && pos[0] && /^[a-z][a-z0-9+.-]*:\/\//i.test(pos[0])) {
    throw new UserError(`pass either a URL or --serve, not both (got ${pos[0]} and --serve ${serveDir})`,
      `example: showtime site ${what} --serve ./dist${what === 'component' ? ' "#pricing"' : ''}`);
  }
  if (serveDir) {
    const server = await serveStatic(serveDir);
    const url = o.page ? new URL(String(o.page).replace(/^\/?/, '/'), server.url).href : server.page;
    info(c.dim(`  serving ${server.root} at ${server.url} (plain static server, stopped when done)`));
    return { url, server, args: pos, name: slug(dirLabel(server.root)) };
  }
  let url = normalizeUrl(pos.shift());
  if (o.page) url = new URL(String(o.page), url).href;
  if (url.startsWith('file:')) warn('file:// pages break root-relative links (/logo.svg) and fetch(); `--serve <folder>` serves it like a web host');
  return { url, server: null, args: pos, name: slug(hostLabel(url)) };
}

/** Fail (or warn with --force) when the browser shows showtime's preview player or a directory listing. */
async function guardLanding(page, o, warnings) {
  const p = await landingProblem(page);
  if (!p) return null;
  if (o.force) {
    const msg = `${p.reason} (kept because of --force)`;
    warn(msg);
    if (warnings) warnings.push(msg);
    return p;
  }
  throw new UserError(`wrong page: ${p.reason}`, p.hint);
}

async function openPage(B, vp, o, url, { dark = false } = {}) {
  // the context and the tab under the page-open deadline (once more in a new browser); the site's own load
  // has --timeout
  const { ctx, consent, page } = await openGuarded(B, async (browser, track) => {
    track.step = 'creating the browser context';
    const ctx = await newCaptureContext(browser, vp, { dark, locale: o.locale, userAgent: o['user-agent'] });
    track.step = 'setting up the consent clicker';
    const consent = o['no-consent'] ? [] : await installConsent(ctx);
    track.step = 'opening a tab';
    return { ctx, consent, page: await ctx.newPage(), close: () => ctx.close() };
  }, { label: 'opening a tab for the site' });
  const responses = [];
  page.on('response', (r) => {
    try {
      const ct = (r.headers()['content-type'] || '').toLowerCase();
      const u = r.url();
      if (ct.startsWith('video/') || /\.(mp4|webm|mov|m4v)(\?|$)/i.test(u)) responses.push({ url: u, type: ct, status: r.status() });
    } catch { /* ignore */ }
  });
  const nav = await robustGoto(page, url, { timeout: sec(o.timeout, 'timeout') * 1000, settle: sec(o.wait, 'wait') * 1000 });
  if (!o['no-consent']) await waitConsent(consent, 4000);
  return { ctx, page, nav, consent, videoResponses: responses };
}

// ------------------------------------------------------------------------------------------- capture

async function capture(argv) {
  const spec = {
    name: 'site capture',
    usage: 'showtime site capture <url> [outdir] [options]\n       showtime site capture --serve <dir> [outdir] [options]',
    summary: 'Capture a website as video material: screenshots, copy, brand tokens and assets.',
    description: 'Target: a URL (https://..., localhost:3000) or, for a static folder with an index.html and no dev\n' +
      'server, --serve <dir> (a plain static server on 127.0.0.1, stopped when done; a folder path given\n' +
      'as <url> is served the same way). Never capture through `showtime server`/`preview`: they wrap\n' +
      'pages in the preview player; landing on it (or on a directory listing) is an error.\n' +
      'Output (default ./showtime-out/<name>-site-<time>/, <name> = host or served folder; printed at the end):\n' +
      '  inventory.md             start here: what was captured and how to use it\n' +
      '  contact-sheet.jpg        every screenshot on one image (look at this first)\n' +
      '  assets-sheet.jpg         downloaded images/logos on one image\n' +
      '  site.json                title/meta/og, headings, copy, CTAs, testimonials, stats, colours with roles,\n' +
      '                           CSS variables, fonts, radii/shadows, asset list\n' +
      '  shots/<aspect>/          viewport screenshots top to bottom (scroll-000.png = hero)\n' +
      '  sections/                one screenshot per page section (hero, features, pricing...)\n' +
      '  full/                    full-page tiles (+ plate.jpg at 1x for scroll-through shots)\n' +
      '  dark/                    dark-mode hero + shots (when the site has a dark theme)\n' +
      '  assets/{images,logos,videos}/  downloaded media (size-capped), og-image, favicons\n' +
      'Exit code 3 = blocked by a bot check (BLOCKED.md explains what to ask the user).',
    options: {
      ...COMMON,
      dark: { default: 'auto', help: 'dark-mode variant: auto (only if the site has one) | on | off' },
      'max-shots': { default: '10', help: 'max viewport screenshots per aspect (default 10)', metavar: 'N' },
      'tile-height': { default: '2400', help: 'full-page tile height in CSS px (default 2400)', metavar: 'PX' },
      'max-height': { default: '24000', help: 'stop full-page tiles after this many CSS px (default 24000)', metavar: 'PX' },
      'no-full': { type: 'boolean', help: 'skip full-page tiles' },
      'no-sections': { type: 'boolean', help: 'skip per-section screenshots' },
      'no-assets': { type: 'boolean', help: 'do not download images/logos/videos' },
      budget: { default: '100', help: 'total download budget in MB (default 100)', metavar: 'MB' },
      'max-assets': { default: '60', help: 'max files to download (default 60)', metavar: 'N' },
      'max-video-mb': { default: '60', help: 'per-video size cap in MB (default 60)', metavar: 'MB' },
      format: { default: 'png', help: 'viewport screenshot format: png | jpg (default png)' },
    },
    examples: [
      'showtime site capture https://example.com',
      'showtime site capture --serve ./dist ./capture --aspect 16:9',
      'showtime site capture localhost:3000 ./capture --aspect 16:9,9:16',
      'showtime site capture https://myapp.dev --dark on --budget 40 --json',
    ],
  };
  const o = parseCli(spec, argv);
  const tgt = await resolveTarget(o, 'capture');
  try {
    return await captureRun(o, tgt);
  } finally {
    if (tgt.server) await tgt.server.close().catch(() => {});
  }
}

async function captureRun(o, tgt) {
  const { url } = tgt;
  const t0 = Date.now();
  const host = tgt.name;
  const out = tgt.args[0] ? path.resolve(tgt.args[0]) : jobDir(`${tgt.name}-site`);
  fs.mkdirSync(out, { recursive: true });
  const aspects = String(o.aspect).split(',').map((s) => s.trim()).filter(Boolean)
    .map((a) => aspectViewport(a, { dpr: o.dpr ? Number(o.dpr) : undefined, width: o.width ? Number(o.width) : undefined }));
  const fmt = o.format === 'jpg' || o.format === 'jpeg' ? 'jpg' : 'png';
  const shotOpts = (file) => (fmt === 'jpg' ? { path: file, type: 'jpeg', quality: 92 } : { path: file, type: 'png' });
  const warnings = [];
  const phase = (n, total, label) => info(c.dim(`  [${n}/${total}] ${label}`));
  const allowPrivate = await privateAssetsAllowed(url);   // never for a host DNS cannot place ('unknown')

  info(`${c.bold('site capture')} ${url}`);
  info(c.dim(`  output ${out}`));
  const B = await launchGuarded({ gpu: o.gpu, headless: !o.headed });
  const result = {
    url, finalUrl: null, served: tgt.server ? tgt.server.root : null, status: null, capturedAt: new Date().toISOString(), aspects: aspects.map((a) => a.spec),
    shots: {}, sections: [], full: null, dark: null, consent: [], overlays: null, warnings,
  };
  try {
    // ---------------------------------------------------------------- primary aspect
    const vp = aspects[0];
    phase(1, 7, `loading (${vp.spec}, ${vp.css.width}x${vp.css.height} @${vp.dpr}x)`);
    let opened;
    try {
      opened = await openPage(B, vp, o, url);
    } catch (e) {
      if (/Timeout|crash|closed/i.test(String(e.message)) && o.gpu !== 'off') {
        warn('page load failed; retrying once with GPU/WebGL off');
        await closeSoon(B.browser.close());
        Object.assign(B, await launchGuarded({ gpu: 'off', headless: !o.headed, args: ['--disable-webgl', '--disable-3d-apis'] }));
        opened = await openPage(B, vp, o, url);
        warnings.push('loaded with WebGL disabled after a first failed attempt');
      } else throw e;
    }
    const { page, nav, consent } = opened;
    result.finalUrl = page.url() || nav.finalUrl;
    result.status = nav.status;
    warnings.push(...nav.warnings);
    const wrong = await guardLanding(page, o, warnings);
    if (wrong) result.wrongPage = wrong;
    const wall = await detectBotWall(page, nav.status);
    if (wall.blocked) {
      fs.writeFileSync(path.join(out, 'BLOCKED.md'), blockedMarkdown(url, wall));
      await page.screenshot({ path: path.join(out, 'blocked.png') }).catch(() => {});
      const summary = { ok: false, blocked: true, url, reasons: wall.reasons, out, blockedFile: path.join(out, 'BLOCKED.md') };
      if (tgt.server) summary.served = tgt.server.root;
      fs.writeFileSync(path.join(out, 'site.json'), JSON.stringify({ ...result, blocked: true, wall }, null, 2));
      if (o.json) console.log(JSON.stringify(summary, null, 2));
      process.stderr.write(`${c.yellow('showtime site: blocked:')} ${url} shows a bot check (${wall.reasons.join(', ')}).\n` +
        `  showtime does not bypass these. Ask the user for screenshots/recordings or another URL.\n  details: ${path.join(out, 'BLOCKED.md')}\n`);
      return 3;
    }
    if (wall.lowText) warnings.push('very little text on the page (image-led site or a JavaScript app that did not render)');
    if (nav.status && nav.status >= 400 && !o.force) {
      throw new UserError(`the page returned HTTP ${nav.status}`, 'check the URL, or pass --force to capture the error page anyway');
    }

    phase(2, 7, 'dismissing banners and loading lazy content');
    result.overlays = await cleanupOverlays(page, { hide: !o['keep-overlays'] });
    const ls = await lazyScroll(page, { budgetMs: 15000 });
    result.lazyScroll = ls;
    // run the cleanup again: some popups appear only after scrolling
    const again = await cleanupOverlays(page, { hide: !o['keep-overlays'] });
    result.overlays.clicked.push(...again.clicked); result.overlays.hidden.push(...again.hidden);
    result.overlays.kept = [...new Set([...(result.overlays.kept || []), ...(again.kept || [])])];

    phase(3, 7, 'extracting copy, brand tokens and assets list');
    const data = await page.evaluate(extractPage, { maxElements: 2500 });
    result.consent = consent.filter((e) => e.type !== 'report');
    const metrics = await scrollMetrics(page);

    phase(4, 7, `screenshots (${aspects.map((a) => a.spec).join(', ')})`);
    result.shots[vp.name] = await viewportSeries(page, vp, path.join(out, 'shots', vp.name), Number(o['max-shots']), fmt, shotOpts, out);
    // sticky headers would cover section shots: make fixed/sticky elements static meanwhile
    const restoreFixed = await neutralizeFixed(page);
    if (!o['no-sections'] && data.sections.length) {
      const secDir = path.join(out, 'sections');
      fs.mkdirSync(secDir, { recursive: true });
      let i = 0;
      for (const s of data.sections.slice(0, 14)) {
        const file = path.join(secDir, `${String(++i).padStart(2, '0')}-${slug(s.label, 32)}.${fmt}`);
        try {
          const loc = page.locator(`[data-st-section="${data.sections.indexOf(s)}"]`);
          await loc.scrollIntoViewIfNeeded({ timeout: 3000 });
          await sleep(250);
          await loc.screenshot({ ...shotOpts(file), timeout: 10000, animations: 'disabled' });
          result.sections.push({ file: relPath(out, file), label: s.label, box: s.box });
        } catch (e) {
          warnings.push(`section "${s.label}" screenshot failed: ${String(e.message).split('\n')[0]}`);
        }
      }
    }
    if (!o['no-full']) {
      result.full = await fullPage(page, vp, path.join(out, 'full'), Number(o['tile-height']), Number(o['max-height']), out, warnings);
    }
    await restoreFixed();
    // ---------------------------------------------------------------- dark variant
    const wantDark = o.dark === 'on' || (o.dark === 'auto' && data.layout.darkSupport);
    if (wantDark && o.dark !== 'off') {
      phase(5, 7, 'dark-mode variant');
      try {
        const d = await openPage(B, vp, o, url, { dark: true });
        await cleanupOverlays(d.page, { hide: !o['keep-overlays'] });
        await lazyScroll(d.page, { budgetMs: 8000 });
        const lumDark = await d.page.evaluate(() => {
          const cs = getComputedStyle(document.body); const c = cs.backgroundColor === 'rgba(0, 0, 0, 0)' ? getComputedStyle(document.documentElement).backgroundColor : cs.backgroundColor;
          const m = /(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(c); return m ? (0.2126 * m[1] + 0.7152 * m[2] + 0.0722 * m[3]) / 255 : null;
        });
        const lightLum = data.layout.bgLuminance;
        if (o.dark === 'on' || lumDark === null || lightLum === null || Math.abs(lumDark - lightLum) > 0.25) {
          result.dark = { shots: await viewportSeries(d.page, vp, path.join(out, 'dark'), Math.min(4, Number(o['max-shots'])), fmt, shotOpts, out), bgLuminance: lumDark };
        } else {
          warnings.push('the site advertises a dark theme but it looked the same; dark shots skipped');
        }
        await d.ctx.close();
      } catch (e) {
        warnings.push(`dark variant failed: ${String(e.message).split('\n')[0]}`);
      }
    } else {
      phase(5, 7, o.dark === 'off' ? 'dark-mode variant skipped (--dark off)' : 'no dark theme detected');
    }
    // ---------------------------------------------------------------- other aspects
    for (const avp of aspects.slice(1)) {
      info(c.dim(`        ${avp.spec}: ${avp.css.width}x${avp.css.height} @${avp.dpr}x${avp.mobile ? ' (phone layout)' : ''}`));
      try {
        const a = await openPage(B, avp, o, url);
        await cleanupOverlays(a.page, { hide: !o['keep-overlays'] });
        await lazyScroll(a.page, { budgetMs: 10000 });
        result.shots[avp.name] = await viewportSeries(a.page, avp, path.join(out, 'shots', avp.name), Number(o['max-shots']), fmt, shotOpts, out);
        await a.ctx.close();
      } catch (e) {
        warnings.push(`${avp.spec} capture failed: ${String(e.message).split('\n')[0]}`);
      }
    }
    // ---------------------------------------------------------------- assets
    let assets = { files: [], dropped: {}, bytes: 0 };
    if (!o['no-assets']) {
      phase(6, 7, 'downloading images, logos and videos');
      const ua = await page.evaluate(() => navigator.userAgent);
      assets = await downloadAssets(data, opened.videoResponses, out, {
        allowPrivate, ua, referer: nav.finalUrl || url, budgetMB: Number(o.budget), maxFiles: Number(o['max-assets']),
        maxVideoMB: Number(o['max-video-mb']),
      });
      for (const [i, s] of data.svgs.entries()) {
        const f = path.join(out, 'assets', 'logos', `inline-${i + 1}${s.logo ? '-logo' : ''}.svg`);
        fs.mkdirSync(path.dirname(f), { recursive: true });
        fs.writeFileSync(f, s.svg);
        assets.files.push({ file: relPath(out, f), kind: s.logo ? 'logo' : 'svg', source: 'inline-svg', rendered: s.rendered, bytes: Buffer.byteLength(s.svg) });
      }
    } else {
      phase(6, 7, 'asset downloads skipped (--no-assets)');
    }
    // ---------------------------------------------------------------- write outputs
    phase(7, 7, 'contact sheets and inventory');
    const { svgs, ...rest } = data;
    const siteJson = {
      ...result, ...rest, inlineSvgCount: svgs.length, page: { height: metrics.height, viewport: vp.css, dpr: vp.dpr },
      assets: assets.files, assetsDropped: assets.dropped, assetsBytes: assets.bytes,
    };
    fs.writeFileSync(path.join(out, 'site.json'), JSON.stringify(siteJson, null, 2));
    fs.writeFileSync(path.join(out, 'visible-text.txt'), data.text + '\n');
    const sheetItems = [];
    for (const [name, list] of Object.entries(result.shots)) for (const s of list) sheetItems.push({ file: s.file, label: `${name} ${s.label}` });
    for (const s of result.sections) sheetItems.push({ file: s.file, label: `section: ${s.label}` });
    if (result.dark) for (const s of result.dark.shots) sheetItems.push({ file: s.file, label: `dark ${s.label}` });
    const sheet = await contactSheet(B.browser, sheetItems.slice(0, 36), path.join(out, 'contact-sheet.jpg'), { title: `${data.meta.title || host} - screens`, dir: out });
    const assetItems = assets.files.filter((f) => /\.(png|jpe?g|webp|gif|svg|avif|ico)$/i.test(f.file))
      .sort((a, b) => (b.kind === 'logo') - (a.kind === 'logo')).slice(0, 36)
      .map((f) => ({ file: f.file, label: `${f.kind}: ${path.basename(f.file)}` }));
    const aSheet = await contactSheet(B.browser, assetItems, path.join(out, 'assets-sheet.jpg'), { title: `${data.meta.title || host} - assets`, dir: out, cols: 4, cell: 360 });
    fs.writeFileSync(path.join(out, 'inventory.md'), inventory(out, url, siteJson, { sheet, aSheet, seconds: (Date.now() - t0) / 1000 }));
    const summary = {
      ok: true, url, finalUrl: result.finalUrl, served: tgt.server ? tgt.server.root : null, title: data.meta.title || null,
      out, inventory: path.join(out, 'inventory.md'), siteJson: path.join(out, 'site.json'),
      contactSheet: sheet, assetsSheet: aSheet, shots: Object.fromEntries(Object.entries(result.shots).map(([k, v]) => [k, v.length])),
      sections: result.sections.length, fullTiles: result.full ? result.full.tiles.length : 0, plate: result.full?.plate || null,
      dark: !!result.dark, assets: assets.files.length, assetsMB: Number((assets.bytes / 1e6).toFixed(1)),
      consent: result.consent.map((e) => e.type + (e.cmp ? `:${e.cmp}` : '')), warnings, seconds: Number(((Date.now() - t0) / 1000).toFixed(1)),
    };
    if (o.json) console.log(JSON.stringify(summary, null, 2));
    else {
      info(`${c.green('done')} in ${fmtDuration(Date.now() - t0)}: ${Object.values(summary.shots).reduce((a, b) => a + b, 0)} shots, ` +
        `${summary.sections} sections, ${summary.fullTiles} full-page tiles, ${summary.assets} assets (${fmtBytes(assets.bytes)})`);
      for (const w of warnings) warn(w);
      info(`  title: ${data.meta.title || '(none)'}`);
      console.log(out);
      console.log(path.join(out, 'inventory.md'));
      if (sheet) console.log(sheet);
      console.log(path.join(out, 'site.json'));
    }
    return 0;
  } finally {
    await closeSoon(B.browser.close());
  }
}

async function viewportSeries(page, vp, dir, maxShots, fmt, shotOpts, out) {
  fs.mkdirSync(dir, { recursive: true });
  const m = await scrollMetrics(page);
  const maxY = Math.max(0, m.height - m.vh);
  const step = Math.max(1, Math.floor(m.vh * 0.7));
  let ys = [];
  for (let y = 0; y < maxY; y += step) ys.push(y);
  ys.push(maxY);
  ys = [...new Set(ys)];
  if (ys.length > maxShots) {
    const pick = [];
    for (let i = 0; i < maxShots; i++) pick.push(ys[Math.round((i * (ys.length - 1)) / Math.max(1, maxShots - 1))]);
    ys = [...new Set(pick)];
  }
  const shots = [];
  for (const y of ys) {
    await page.evaluate((yy) => { document.documentElement.style.scrollBehavior = 'auto'; window.scrollTo(0, yy); }, y);
    await sleep(380);
    const pct = maxY ? Math.round((100 * y) / maxY) : 0;
    const file = path.join(dir, `scroll-${String(pct).padStart(3, '0')}.${fmt}`);
    await page.screenshot({ ...shotOpts(file), animations: 'disabled', caret: 'hide' });
    shots.push({ file: relPath(out, file), y, pct, label: pct === 0 ? 'hero (top)' : `${pct}%`, size: [vp.css.width * vp.dpr, vp.css.height * vp.dpr] });
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  return shots;
}

async function fullPage(page, vp, dir, tileH, maxH, out, warnings) {
  fs.mkdirSync(dir, { recursive: true });
  try {
    await sleep(300);
    const m = await scrollMetrics(page);
    const total = Math.min(m.height, maxH);
    if (m.height > maxH) warnings.push(`page is ${m.height}px tall; full-page tiles stop at ${maxH}px (--max-height)`);
    const tiles = [];
    for (let y = 0, i = 1; y < total; y += tileH, i++) {
      const h = Math.min(tileH, total - y);
      const file = path.join(dir, `tile-${String(i).padStart(2, '0')}.jpg`);
      await page.screenshot({ path: file, type: 'jpeg', quality: 88, fullPage: true, clip: { x: 0, y, width: m.vw, height: h }, animations: 'disabled' });
      tiles.push({ file: relPath(out, file), y, height: h });
    }
    let plate = null;
    if (m.height <= 16000) {
      const file = path.join(dir, 'plate.jpg');
      await page.screenshot({ path: file, type: 'jpeg', quality: 90, fullPage: true, scale: 'css', animations: 'disabled' });
      plate = relPath(out, file);
    } else {
      warnings.push('page is taller than 16000px: no single plate (use the tiles)');
    }
    return { tiles, plate, height: m.height, width: m.vw, tileCssHeight: tileH, dpr: vp.dpr };
  } catch (e) {
    warnings.push(`full-page capture failed: ${String(e.message).split('\n')[0]}`);
    return null;
  }
}

async function downloadAssets(data, videoResponses, out, o) {
  const budget = { used: 0, max: Math.max(1, o.budgetMB) * 1e6 };
  const headers = { 'User-Agent': o.ua, Referer: o.referer, Accept: 'image/avif,image/webp,image/png,image/svg+xml,image/*,video/*;q=0.8,*/*;q=0.5' };
  const jobs = [];
  const seen = new Set();
  const push = (url, kind, meta = {}) => {
    if (!url || /^(data|blob|about):/.test(url) || isTracker(url)) return;
    const key = canonicalAssetUrl(url);
    if (seen.has(key)) return;
    seen.add(key);
    jobs.push({ url, kind, ...meta });
  };
  for (const im of data.images.filter((x) => x.logo)) push(im.url, 'logo', { name: `logo-${slug(im.alt || 'logo', 24)}`, alt: im.alt });
  push(data.meta.ogImage, 'og-image', { name: 'og-image' });
  const icons = [...data.meta.icons].filter((i) => i.rel !== 'mask-icon')
    .sort((a, b) => ((/svg/.test(b.type || b.href) ? 1e4 : 0) + (parseInt(b.sizes, 10) || (b.rel.includes('apple') ? 180 : 16))) -
      ((/svg/.test(a.type || a.href) ? 1e4 : 0) + (parseInt(a.sizes, 10) || (a.rel.includes('apple') ? 180 : 16))));
  for (const [i, ic] of icons.slice(0, 3).entries()) push(ic.href, 'icon', { name: `favicon-${i + 1}` });
  const imgs = data.images.filter((x) => !x.logo && Math.max(...x.rendered) >= 64)
    .sort((a, b) => (b.rendered[0] * b.rendered[1] * (b.aboveFold ? 2 : 1)) - (a.rendered[0] * a.rendered[1] * (a.aboveFold ? 2 : 1)));
  for (const im of imgs) push(im.url, 'image', { alt: im.alt, section: im.section, rendered: im.rendered });
  for (const bg of data.backgrounds) push(bg.url, 'background', { section: bg.section, rendered: bg.rendered });
  for (const v of data.videos) { for (const u of v.urls.slice(0, 1)) push(u, 'video', { section: v.section, rendered: v.rendered }); push(v.poster, 'poster', { section: v.section }); }
  for (const r of videoResponses) push(r.url, 'video', { note: 'seen on the network' });
  const files = [];
  const dropped = {};
  const limit = Math.max(0, o.maxFiles);
  let idx = 0, count = 0;
  const dirs = { 'og-image': 'assets', icon: 'assets/logos', logo: 'assets/logos', image: 'assets/images', background: 'assets/images', video: 'assets/videos', poster: 'assets/videos' };
  const prog = new Progress('assets', Math.min(jobs.length, limit));
  async function worker() {
    while (idx < jobs.length && count < limit) {
      const j = jobs[idx++];
      const n = String(idx).padStart(2, '0');
      const base = j.name || `${n}-${slug(j.alt || j.section || path.basename(new URL(j.url).pathname).replace(/\.[a-z0-9]+$/i, ''), 32)}`;
      const r = await safeDownload(j.url, path.join(out, dirs[j.kind], base), {
        allowPrivate: o.allowPrivate, maxBytes: (j.kind === 'video' ? o.maxVideoMB : 20) * 1e6, budget, headers, timeout: j.kind === 'video' ? 120000 : 15000,
      });
      if (!r.ok) { dropped[r.reason] = (dropped[r.reason] || 0) + 1; continue; }
      const raster = /^(png|jpg|gif|webp|avif)$/.test(r.ext);
      if ((raster && r.bytes < 3000 && !['logo', 'icon', 'og-image'].includes(j.kind)) || (r.ext === 'svg' && r.bytes < 150)) {
        try { fs.unlinkSync(r.file); } catch { /* */ }
        budget.used -= r.bytes;
        dropped['too-small'] = (dropped['too-small'] || 0) + 1;
        continue;
      }
      count++;
      prog.tick();
      files.push({ file: relPath(out, r.file), kind: j.kind, url: j.url, bytes: r.bytes, ext: r.ext, alt: j.alt || null, section: j.section || null, rendered: j.rendered || null, note: j.note });
    }
  }
  await Promise.all(Array.from({ length: 5 }, worker));
  prog.end();
  if (idx < jobs.length) dropped['limit'] = jobs.length - idx;
  files.sort((a, b) => a.file.localeCompare(b.file));
  return { files, dropped, bytes: budget.used };
}

function inventory(out, url, s, { sheet, aSheet, seconds }) {
  const L = [];
  const rel = (p) => (p ? relPath(out, p) : null);
  L.push(`# Site capture: ${s.meta.title || url}`, '');
  if (s.served) L.push(`- Source: the static folder \`${s.served}\`, served for this capture at ${url} (a temporary address)`);
  else L.push(`- URL: ${url}${s.finalUrl && s.finalUrl !== url ? ` (landed on ${s.finalUrl})` : ''}`);
  L.push(`- Captured: ${s.capturedAt} in ${seconds.toFixed(0)} s; HTTP ${s.status ?? '?'}; page height ${s.page.height}px at ${s.page.viewport.width}px wide`);
  if (s.meta.description) L.push(`- Description: ${s.meta.description}`);
  L.push('', '## Look at these first', '');
  if (sheet) L.push(`- \`${rel(sheet)}\`: every screenshot on one image`);
  if (aSheet) L.push(`- \`${rel(aSheet)}\`: downloaded images and logos`);
  L.push('- `site.json`: all extracted data (copy, CTAs, colours, fonts, assets); `visible-text.txt`: the page text', '');
  L.push('## Files', '', '| file(s) | what |', '|---|---|');
  for (const [name, list] of Object.entries(s.shots)) {
    if (list.length) L.push(`| \`${path.posix.dirname(list[0].file)}/scroll-*.${path.extname(list[0].file).slice(1)}\` | ${list.length} viewport shots at ${name.replace('x', ':')} (${list[0].size.join('x')} px), top to bottom; scroll-000 is the hero |`);
  }
  if (s.sections.length) L.push(`| \`sections/\` | ${s.sections.length} section screenshots: ${s.sections.map((x) => x.label).slice(0, 8).join('; ')} |`);
  if (s.full) {
    L.push(`| \`full/tile-*.jpg\` | ${s.full.tiles.length} full-page tiles (${s.full.tileCssHeight} CSS px each, @${s.full.dpr}x) |`);
    if (s.full.plate) L.push(`| \`${s.full.plate}\` | whole page at 1x (${s.full.width}x${s.full.height}); animate translateY for a scroll-through shot |`);
  }
  if (s.dark) L.push(`| \`dark/\` | ${s.dark.shots.length} dark-mode shots |`);
  const kinds = {};
  for (const f of s.assets) kinds[f.kind] = (kinds[f.kind] || 0) + 1;
  if (s.assets.length) L.push(`| \`assets/\` | ${Object.entries(kinds).map(([k, v]) => `${v} ${k}`).join(', ')} (${(s.assetsBytes / 1e6).toFixed(1)} MB) |`);
  L.push('', '## Brand', '');
  const r = s.colors.roles;
  L.push('| role | colour |', '|---|---|');
  for (const k of ['background', 'text', 'primary', 'onPrimary', 'accent', 'surface', 'themeColor']) if (r[k]) L.push(`| ${k} | \`${r[k]}\` |`);
  L.push('', `Palette (by visual weight): ${s.colors.palette.slice(0, 10).map((p) => `\`${p.hex}\` ${p.role}`).join(', ')}`);
  const cv = Object.entries(s.tokens.colorVariables).slice(0, 12);
  if (cv.length) L.push('', `CSS colour variables: ${cv.map(([k, v]) => `\`${k}: ${v}\``).join(', ')}${Object.keys(s.tokens.colorVariables).length > 12 ? ' ...' : ''}`);
  const fams = [...new Set(s.fonts.loaded.map((f) => f.family))];
  L.push('', `Fonts loaded: ${fams.length ? fams.slice(0, 8).join(', ') : '(none reported)'}`);
  for (const [k, v] of Object.entries(s.fonts.roles)) if (v) L.push(`- ${k}: ${v.family.split(',')[0]} ${v.weight} ${v.size}`);
  const SYSTEM_FONT = /^(ui-sans-serif|ui-serif|ui-monospace|ui-rounded|system-ui|-apple-system|blinkmacsystemfont|segoe ui|roboto|helvetica neue|helvetica|arial|sans-serif|serif|monospace)$/i;
  const firstFamily = (f) => String(f || '').split(',')[0].trim().replace(/^["']|["']$/g, '');
  const roleFams = Object.values(s.fonts.roles).filter(Boolean).map((v) => firstFamily(v.family));
  const systemOnly = roleFams.length && roleFams.every((f) => SYSTEM_FONT.test(f)) && !fams.length;
  if (systemOnly) {
    L.push('', `The site uses the system font stack (${[...new Set(roleFams)].join(', ')}), which looks different on every OS: ` +
      'use Inter (or Geist) in the video and say so: `showtime assets font inter --copy-to <project>/fonts`.');
  }
  L.push('', 'To use a font in the video, install it as files (never rely on system fonts): `showtime assets font "<family>"`.',
    'Only Google/open fonts can be installed that way; for a commercial brand font pick the closest open family.');
  if (s.tokens.radii.length) L.push('', `Corner radii: ${s.tokens.radii.map((x) => x.value).join(', ')}`);
  L.push('', '## Copy', '');
  const h1 = s.headings.find((h) => h.level === 1);
  if (h1) L.push(`- Headline (h1): "${h1.text}"`);
  const h2s = s.headings.filter((h) => h.level === 2).slice(0, 10);
  if (h2s.length) L.push(`- Section headings: ${h2s.map((h) => `"${h.text}"`).join('; ')}`);
  const ctas = s.ctas.slice(0, 6);
  if (ctas.length) L.push(`- CTAs: ${ctas.map((x) => `"${x.text}"${x.primary ? ' (primary)' : ''}`).join(', ')}`);
  if (s.stats.length) L.push(`- Numbers: ${s.stats.slice(0, 8).map((x) => `${x.value}${x.label ? ` (${x.label.slice(0, 40)})` : ''}`).join('; ')}`);
  if (s.testimonials.length) {
    L.push('', '### Testimonials', '');
    for (const t of s.testimonials.slice(0, 5)) L.push(`> ${t.text.slice(0, 280)}${t.author ? `\n> - ${t.author}` : ''}`, '');
    L.push('Quote testimonials verbatim with the name as shown, or not at all.');
  }
  if (s.copy.length) {
    L.push('', '### Key copy blocks', '');
    for (const b of s.copy.slice(0, 8)) L.push(`- ${b.text.slice(0, 220)}${b.section ? ` _(${b.section})_` : ''}`);
  }
  L.push('', '## Notes', '');
  if (s.consent.length) L.push(`- Consent banner: ${[...new Set(s.consent.map((e) => e.type + (e.cmp ? ` (${e.cmp})` : '')))].join(', ')} (opted out of non-essential cookies)`);
  if (s.overlays && (s.overlays.clicked.length || s.overlays.hidden.length)) L.push(`- Overlays: clicked ${s.overlays.clicked.join(', ') || 'nothing'}; hid ${s.overlays.hidden.slice(0, 6).join(', ') || 'nothing'}${s.overlays.hidden.length ? ' (not in the shots; `--keep-overlays` keeps them)' : ''}`);
  if (s.overlays && s.overlays.kept && s.overlays.kept.length) L.push(`- Kept on screen: ${s.overlays.kept.slice(0, 6).join(', ')}`);
  const libs = Object.entries(s.layout.libraries).filter(([k, v]) => v && k !== 'canvasCount').map(([k]) => k);
  if (libs.length) L.push(`- Built with: ${libs.join(', ')}${s.layout.libraries.canvasCount ? `; ${s.layout.libraries.canvasCount} canvas element(s)` : ''}`);
  if (Object.keys(s.assetsDropped || {}).length) L.push(`- Skipped downloads: ${Object.entries(s.assetsDropped).map(([k, v]) => `${v} ${k}`).join(', ')}`);
  for (const w of s.warnings) L.push(`- Warning: ${w}`);
  const src = s.served ? `--serve "${s.served}"` : url;
  L.push('', '## Using this material', '',
    '- Screens are real UI: frame them (browser chrome / device frame) and move them (pan, zoom, parallax) rather than recreating them.',
    `- Scroll-through: put \`full/plate.jpg\` in a viewport-sized box and animate its translateY, or record one: \`showtime site record ${src}\`.`,
    `- A single element: \`showtime site component ${src} "<css selector>"\`.`,
    '- Copy: use the headline and CTAs as written; never invent claims, numbers or quotes the site does not make.',
    '- Assets were fetched from the site for reference in a video about this site; logos and product images belong to their owners.', '');
  return L.join('\n');
}

// ------------------------------------------------------------------------------------------- component

async function component(argv) {
  const spec = {
    name: 'site component',
    usage: 'showtime site component <url> <selector> [options]\n       showtime site component --serve <dir> <selector> [options]',
    summary: 'Screenshot one element of a page (a hero, a pricing table, a card) with transparent-free padding.',
    description: 'The selector is any Playwright selector: CSS ("#pricing", ".card:nth-child(2)"), text ("text=Pricing")\n' +
      'or role ("role=button[name=\\"Sign up\\"]"). Files: -o <file> (never overwritten: file-2.png...) or\n' +
      './showtime-out/<name>-component-<time>/<selector>.png (numbered with --all).',
    options: {
      ...COMMON,
      output: { short: 'o', help: 'output file (.png or .jpg)', metavar: 'FILE' },
      pad: { default: '0', help: 'extra pixels around the element (CSS px, default 0)', metavar: 'PX' },
      all: { type: 'boolean', help: 'capture every match (up to --max)' },
      max: { default: '8', help: 'max matches with --all (default 8)', metavar: 'N' },
      dark: { type: 'boolean', help: 'dark colour scheme' },
      hide: { help: 'comma list of selectors to hide first (e.g. ".chat-widget,#promo")', metavar: 'SEL' },
    },
    examples: [
      'showtime site component https://example.com h1 -o headline.png',
      'showtime site component https://myapp.dev "#pricing" --pad 24 --dark',
      'showtime site component --serve ./dist ".hero" -o hero.png',
      'showtime site component https://myapp.dev ".testimonial" --all --max 4',
    ],
  };
  const o = parseCli(spec, argv);
  const tgt = await resolveTarget(o, 'component');
  const { url } = tgt;
  const sel = tgt.args[0];
  if (!sel) {
    if (tgt.server) await tgt.server.close().catch(() => {});
    throw new UserError('missing <selector>', 'example: showtime site component https://example.com "#pricing"');
  }
  const vp = aspectViewport(String(o.aspect).split(',')[0], { dpr: o.dpr ? Number(o.dpr) : undefined, width: o.width ? Number(o.width) : undefined });
  const B = await launchGuarded({ gpu: o.gpu, headless: !o.headed });
  try {
    const { page, nav } = await openPage(B, vp, o, url, { dark: !!o.dark });
    await guardLanding(page, o, null);
    const wall = await detectBotWall(page, nav.status);
    if (wall.blocked) {
      process.stderr.write(`${c.yellow('showtime site: blocked:')} ${url} shows a bot check (${wall.reasons.join(', ')}); not bypassing it.\n` +
        '  Ask the user for a screenshot of that element, or another URL.\n');
      return 3;
    }
    await cleanupOverlays(page, { hide: !o['keep-overlays'] });
    if (o.hide) await page.evaluate((list) => { for (const s of list) for (const e of document.querySelectorAll(s)) e.style.setProperty('visibility', 'hidden', 'important'); }, String(o.hide).split(',').map((s) => s.trim()).filter(Boolean)).catch(() => {});
    const loc = page.locator(sel);
    let n = await loc.count().catch((e) => { throw new UserError(`invalid selector ${sel}: ${String(e.message).split('\n')[0]}`); });
    if (!n) {
      await lazyScroll(page, { budgetMs: 8000 });
      n = await loc.count();
    }
    if (!n) {
      const hints = await page.evaluate(() => [...document.querySelectorAll('[id]')].map((e) => '#' + e.id).filter((s) => s.length < 30).slice(0, 12));
      throw new UserError(`no element matches ${sel}`, hints.length ? `ids on the page: ${hints.join(' ')}` : 'check the selector in the browser dev tools');
    }
    const count = o.all ? Math.min(n, Number(o.max)) : 1;
    const outBase = o.output ? path.resolve(o.output) : path.join(jobDir(`${tgt.name}-component`), `${slug(sel.replace(/^[#.]/, ''), 30)}.png`);
    const ext = /\.jpe?g$/i.test(outBase) ? 'jpg' : 'png';
    const pad = Number(o.pad) || 0;
    const files = [];
    for (let i = 0; i < count; i++) {
      const el = loc.nth(i);
      await el.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
      await sleep(300);
      const b = await el.boundingBox();
      if (!b) continue;
      const want = count > 1 ? outBase.replace(/(\.[a-z]+)$/i, `-${i + 1}$1`) : outBase;
      const file = freshPath(want);
      if (file !== want) warn(`${path.basename(want)} exists; wrote ${path.basename(file)} (outputs are never overwritten)`);
      fs.mkdirSync(path.dirname(file), { recursive: true });
      const opts = ext === 'jpg' ? { type: 'jpeg', quality: 92 } : { type: 'png' };
      if (pad) {
        const m = await scrollMetrics(page);
        const clip = { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: Math.min(m.vw, b.width + 2 * pad), height: b.height + 2 * pad };
        await page.screenshot({ path: file, clip, ...opts, animations: 'disabled' });
      } else {
        await el.screenshot({ path: file, ...opts, animations: 'disabled' });
      }
      files.push({ file, box: [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)], size: [Math.round(b.width * vp.dpr), Math.round(b.height * vp.dpr)] });
    }
    if (o.json) console.log(JSON.stringify({ ok: true, url, served: tgt.server ? tgt.server.root : null, selector: sel, matches: n, out: path.dirname(outBase), files }, null, 2));
    else { info(`${c.green('done')}: ${files.length} of ${n} match(es)`); for (const f of files) console.log(f.file); }
    return files.length ? 0 : 1;
  } finally {
    await closeSoon(B.browser.close());
    if (tgt.server) await tgt.server.close().catch(() => {});
  }
}

// ------------------------------------------------------------------------------------------- record

async function record(argv) {
  const spec = {
    name: 'site record',
    usage: 'showtime site record <url> [outdir] [options]\n       showtime site record --serve <dir> [outdir] [options]',
    summary: 'Scroll through a page and capture paced frames (not real time), then encode scroll.mp4.',
    description: 'Frames are taken at exact scroll positions for each output frame, so the motion is smooth\n' +
      'regardless of machine speed. The page is pre-scrolled once so lazy content and reveal animations\n' +
      'have fired. Output (default ./showtime-out/<name>-scroll-<time>/, printed at the end):\n' +
      'frames/%05d.jpg, scroll.mp4, record.json (scroll y per frame).',
    options: {
      ...COMMON,
      duration: { short: 'd', default: '8', help: 'seconds of scrolling (default 8)', metavar: 'S' },
      fps: { default: '30', help: 'frames per second (default 30)', metavar: 'N' },
      hold: { default: '0.8', help: 'seconds to hold at the start and the end (default 0.8)', metavar: 'S' },
      ease: { default: 'inout', help: 'inout | linear | out (default inout)' },
      from: { default: '0', help: 'start position, 0..1 of the page (default 0)' },
      to: { default: '1', help: 'end position, 0..1 of the page (default 1)' },
      dark: { type: 'boolean', help: 'dark colour scheme' },
      'no-mp4': { type: 'boolean', help: 'keep frames only' },
      quality: { default: '90', help: 'JPEG quality for frames (default 90)' },
    },
    examples: [
      'showtime site record https://example.com',
      'showtime site record https://myapp.dev ./scroll --duration 12 --aspect 9:16 --fps 30',
      'showtime site record localhost:3000 --from 0 --to 0.5 --ease out',
      'showtime site record --serve ./public --duration 6',
    ],
  };
  const o = parseCli(spec, argv);
  const fps = Number(o.fps);
  if (!(fps > 0 && fps <= 120)) throw new UserError('--fps must be between 1 and 120');
  const dur = sec(o.duration, 'duration'), hold = sec(o.hold, 'hold');
  if (dur <= 0) throw new UserError('--duration must be > 0');
  const vp = aspectViewport(String(o.aspect).split(',')[0], { dpr: o.dpr ? Number(o.dpr) : 1, width: o.width ? Number(o.width) : undefined });
  const tgt = await resolveTarget(o, 'record');
  const { url } = tgt;
  const out = tgt.args[0] ? path.resolve(tgt.args[0]) : jobDir(`${tgt.name}-scroll`);
  const framesDir = path.join(out, 'frames');
  fs.rmSync(framesDir, { recursive: true, force: true });   // stale frames from an earlier run would end up in scroll.mp4
  fs.mkdirSync(framesDir, { recursive: true });
  info(`${c.bold('site record')} ${url}`);
  info(c.dim(`  output ${out}`));
  const t0 = Date.now();
  const B = await launchGuarded({ gpu: o.gpu, headless: !o.headed });
  try {
    const { page, nav } = await openPage(B, vp, o, url, { dark: !!o.dark });
    await guardLanding(page, o, null);
    const wall = await detectBotWall(page, nav.status);
    if (wall.blocked) {
      fs.writeFileSync(path.join(out, 'BLOCKED.md'), blockedMarkdown(url, wall));
      process.stderr.write(`${c.yellow('showtime site: blocked:')} ${url} shows a bot check; not bypassing it. See ${path.join(out, 'BLOCKED.md')}\n`);
      return 3;
    }
    await cleanupOverlays(page, { hide: !o['keep-overlays'] });
    await lazyScroll(page, { budgetMs: 15000 });
    await page.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; if (document.body) document.body.style.scrollBehavior = 'auto'; });
    const m = await scrollMetrics(page);
    const maxY = Math.max(0, m.height - m.vh);
    const y0 = Math.round(maxY * Math.min(1, Math.max(0, Number(o.from)))), y1 = Math.round(maxY * Math.min(1, Math.max(0, Number(o.to))));
    const easeFn = { linear: (x) => x, out: (x) => 1 - Math.pow(1 - x, 3), inout: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2) }[o.ease] || ((x) => x);
    const holdN = Math.round(hold * fps), moveN = Math.max(2, Math.round(dur * fps));
    const total = holdN * 2 + moveN;
    const q = Math.min(100, Math.max(40, Number(o.quality)));
    const ys = [];
    const prog = new Progress('frames', total);
    for (let i = 0; i < total; i++) {
      const k = Math.min(1, Math.max(0, (i - holdN) / (moveN - 1)));
      const y = Math.round(y0 + (y1 - y0) * easeFn(k));
      await page.evaluate((yy) => new Promise((res) => { window.scrollTo(0, yy); requestAnimationFrame(() => requestAnimationFrame(res)); }), y);
      await page.screenshot({ path: path.join(framesDir, `${String(i + 1).padStart(5, '0')}.jpg`), type: 'jpeg', quality: q, caret: 'hide' });
      ys.push(y);
      prog.tick();
    }
    prog.end();
    let mp4 = null;
    if (!o['no-mp4']) {
      resolveFF();
      mp4 = path.join(out, 'scroll.mp4');
      const W = vp.css.width * vp.dpr, H = vp.css.height * vp.dpr;
      await ffmpeg(['-framerate', fpsArg(fps), '-i', path.join(framesDir, '%05d.jpg'),
        '-vf', `scale=${W + (W % 2)}:${H + (H % 2)}:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p`,
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
        '-movflags', '+faststart', mp4]);
    }
    const rec = { url, served: tgt.server ? tgt.server.root : null, fps, frames: total, duration: total / fps, viewport: vp.css, dpr: vp.dpr, pageHeight: m.height, from: y0, to: y1, ease: o.ease, hold, scrollY: ys, frame_pattern: 'frames/%05d.jpg', video: mp4 ? 'scroll.mp4' : null };
    fs.writeFileSync(path.join(out, 'record.json'), JSON.stringify(rec, null, 1));
    const summary = { ok: true, out, frames: total, duration: rec.duration, video: mp4, record: path.join(out, 'record.json'), seconds: Number(((Date.now() - t0) / 1000).toFixed(1)) };
    if (o.json) console.log(JSON.stringify(summary, null, 2));
    else { info(`${c.green('done')}: ${total} frames (${rec.duration.toFixed(1)} s) in ${fmtDuration(Date.now() - t0)}`); console.log(out); if (mp4) console.log(mp4); console.log(path.join(out, 'record.json')); }
    return 0;
  } finally {
    await closeSoon(B.browser.close());
    if (tgt.server) await tgt.server.close().catch(() => {});
  }
}

// ------------------------------------------------------------------------------------------- main

const [cmd, ...rest] = process.argv.slice(2);
const table = { capture, component, record };
if (!cmd || cmd === '--help' || cmd === '-h' || cmd === 'help') {
  printHelp({ ...TOP, options: {} });
  process.exit(cmd ? 0 : 2);
} else if (!table[cmd]) {
  process.stderr.write(`showtime site: unknown command "${cmd}"\n  commands: capture, component, record (see \`showtime site --help\`)\n`);
  process.exit(2);
} else {
  runMain(() => table[cmd](rest));
}
