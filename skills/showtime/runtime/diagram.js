/* showtime living diagrams: an isometric (or flat) system drawn as a pure function of time.
 *
 * Classic script, one global: `Diagram` (alias `LD`). Load after /_st/stage.js:
 *
 *   <html data-theme="light">            light (paper, the default) or dark (night schematic)
 *   <link rel="stylesheet" href="/_st/diagram.css">
 *   <script src="/_st/stage.js"></script>
 *   <script src="/_st/diagram.js"></script>
 *   ... <div class="ld-stage"><div id="ld"></div> ...page chrome... </div>
 *   <script src="scene.js"></script>      window.SCENE = { world, items, flows, labels, ... }
 *   <script>Diagram.mount(SCENE);</script>
 *
 * One SVG at 1920x1080 design px. World = isometric units (x to the lower right, y to the lower left,
 * z up). The world group is redrawn from t on every seek; every text (labels, tags, floor text) is a
 * persistent node created at mount and only moved or faded, so `showtime check` reads it as one text.
 * No CSS transitions, no timers, no state carried between frames; randomness only through ST.rand.
 * Full reference: references/workflows/diagram.md (spec) and DESIGN notes in the template README.
 */
(function (root) {
  'use strict';
  var C = Math.cos(Math.PI / 6);
  var W = 1920, H = 1080;
  var TEXT_FADE = 0.2;       // every text fades in or out over at most this (a mid-fade frame fails contrast)
  var MIN_TEXT_PX = 25;      // the check's readable minimum at 1080p (2.2 % of the frame height, rounded up)
  var clamp = function (x, a, b) { return Math.min(b, Math.max(a, x)); };
  var lerp = function (a, b, p) { return a + (b - a) * p; };
  var E = {
    linear: function (p) { return p; },
    outCubic: function (p) { return 1 - Math.pow(1 - p, 3); },
    outQuint: function (p) { return 1 - Math.pow(1 - p, 5); },
    inOutCubic: function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; },
    inOutSine: function (p) { return -(Math.cos(Math.PI * p) - 1) / 2; },
    outBack: function (p) { var c1 = 1.4, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
  };
  function seg(t, a, d, e) { var p = d > 0 ? clamp((t - a) / d, 0, 1) : (t >= a ? 1 : 0); return e ? e(p) : p; }
  function f1(n) { return String(Math.round(n * 10) / 10); }
  function f3(n) { return String(Math.round(n * 1000) / 1000); }
  function hexRgb(h) { var v = parseInt(h.slice(1), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255]; }
  function mixHex(a, b, p) {
    if (p <= 0) return a; if (p >= 1) return b;
    var pa = hexRgb(a), pb = hexRgb(b);
    var ch = function (i) { return Math.round(lerp(pa[i], pb[i], p)); };
    return '#' + ((1 << 24) + (ch(0) << 16) + (ch(1) << 8) + ch(2)).toString(16).slice(1);
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function warn(msg) { if (root.console) console.warn('[showtime] diagram: ' + msg); }

  /* ------------------------------------------------------------------ themes
     A theme is tokens plus a few drawing switches (flow: dashes or glowing beads; tags: solid or outlined
     pills; tokens: pucks or beads). The same scene renders in both. */
  var THEMES = {
    light: {
      name: 'light', ground: '#F4F3EF',
      lw: 1.6, ink: '#2A2C30', detail: '#9C998F', hatch: '#B0ACA2', grid: '#E9E7E1', floorInk: '#46443F',
      faces: { top: '#FFFFFF', left: '#F2F1ED', right: '#E4E2DC', recess: '#ECEBE6', deep: '#E1DFD8', blade: '#FAFAF8' },
      plateFaces: { top: '#FBFAF7', left: '#ECEAE4', right: '#E0DED7' },
      coolFaces: { top: '#EEF3F9', left: '#DFE6EF', right: '#D3DBE6' },
      glass: { top: '#E6F0FC', left: '#D6E5F7', right: '#C7D9F0' }, glassLine: '#3F6FAE', glassOpacity: 0.78, glassGlow: false,
      padFaces: { top: '#F4F3EF', left: '#E6E4DE', right: '#DAD8D1' },
      wallFaces: { top: '#F7F6F2', left: '#EAE8E2', right: '#F0EFEA' },
      floorFaces: { top: '#F6EFE4', left: '#E8E0D2', right: '#DDD4C5' }, plank: '#E6DCCB', ghost: '#9C998F',
      roofFaces: { top: '#EFEDE7', left: '#E7E4DC', right: '#DCD9D0' },
      cylStops: '<stop offset="0" stop-color="#FFFFFF"/><stop offset="0.45" stop-color="#F3F2EE"/><stop offset="1" stop-color="#DCDAD3"/>',
      domeStops: '<stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#E2E0D9"/>',
      shadow: 'rgba(70,60,40,0.16)', shadowBlur: 8,
      pipe: { body: '#FFFFFF', sheen: 'rgba(255,255,255,0.75)', collar: '#F7F6F2' },
      tones: {
        cold: { tint: '#D3E3F6', flow: '#1F66C2', air: '#5B8FD0', tag: '#1F66C2', tagInk: '#FFFFFF', face: '#E4EEFA' },
        hot: { tint: '#F8D5C6', flow: '#C8441C', air: '#D9764F', tag: '#BE3F19', tagInk: '#FFFFFF', face: '#FBE6DC' },
        warm: { tint: '#F6E6D2', flow: '#C9822B', air: '#D9764F', tag: '#94540F', tagInk: '#FFFFFF', face: '#FAF0E2' },
        mute: { tint: '#E6E4DE', flow: '#8C897F', air: '#9C998F', tag: '#5F5C55', tagInk: '#FFFFFF', face: '#EFEEEA' },
        ok: { tint: '#D5EBDD', flow: '#2E8A55', air: '#4FA06F', tag: '#23744A', tagInk: '#FFFFFF', face: '#E6F3EA' },
      },
      flowStyle: 'dash', tagStyle: 'solid', tokenStyle: 'puck', airOpacity: 0.85,
      leader: '#2A2C30', leaderW: 1.6, dotFill: '#FFFFFF',
      labelPlate: '#F4F3EF', labelPlateOpacity: 0.86, labelInk: '#1E2024', subInk: '#4A4C50',
      font: { label: 'Geist', sub: 'Geist', mono: 'Geist Mono' },
      size: { label: 31, sub: 25, tag: 25 }, weight: { label: 600 }, track: { label: '-0.01em' },
      dimTo: 0.42, veil: '#F4F3EF', bloom: '#EDB08A', bloomOpacity: 0.32,
    },
    dark: {
      name: 'dark', ground: '#0A0F19',
      lw: 1.5, ink: '#9FB4CF', detail: '#4E6585', hatch: '#3B4F6E', grid: '#152238', floorInk: '#A8B8CE',
      faces: { top: '#18253B', left: '#121C2E', right: '#0D1523', recess: '#0B121E', deep: '#09101A', blade: '#22324D' },
      plateFaces: { top: '#0F1828', left: '#0C1421', right: '#0A111C' },
      coolFaces: { top: '#11203A', left: '#0D192D', right: '#0A1424' },
      glass: { top: '#10345A', left: '#0C2848', right: '#091E38' }, glassLine: '#5CD3FF', glassOpacity: 0.62, glassGlow: true,
      padFaces: { top: '#152034', left: '#0F1828', right: '#0B1220' },
      wallFaces: { top: '#162236', left: '#101A2A', right: '#131E31' },
      floorFaces: { top: '#17151A', left: '#120F13', right: '#0E0C10' }, plank: '#262027', ghost: '#4E6585',
      roofFaces: { top: '#1C2A42', left: '#142035', right: '#0F182A' },
      cylStops: '<stop offset="0" stop-color="#22324D"/><stop offset="0.45" stop-color="#16233A"/><stop offset="1" stop-color="#0C1422"/>',
      domeStops: '<stop offset="0" stop-color="#2B3E5E"/><stop offset="1" stop-color="#111B2C"/>',
      shadow: 'rgba(0,0,0,0.55)', shadowBlur: 10,
      pipe: { body: '#121C2D', sheen: null, collar: '#1A2740' },
      tones: {
        cold: { tint: '#0F3149', flow: '#5CD3FF', air: '#3FA9E0', tag: '#0A0F19', tagInk: '#7FDCFF', face: '#13283F' },
        hot: { tint: '#3D1A12', flow: '#FF6A3D', air: '#FF8A4C', tag: '#0A0F19', tagInk: '#FF8F66', face: '#2E1A1A' },
        warm: { tint: '#33240F', flow: '#FFB04A', air: '#FFB04A', tag: '#0A0F19', tagInk: '#FFC271', face: '#2A2216' },
        mute: { tint: '#1A2436', flow: '#7D8FA8', air: '#5A6E8C', tag: '#0A0F19', tagInk: '#A9B6C8', face: '#172133' },
        ok: { tint: '#0F3324', flow: '#4ADE8A', air: '#3FBF75', tag: '#0A0F19', tagInk: '#6EEBA3', face: '#122B22' },
      },
      flowStyle: 'bead', tagStyle: 'outline', tokenStyle: 'bead', airOpacity: 0.9,
      leader: '#8FA6C4', leaderW: 1.5, dotFill: '#0A0F19',
      labelPlate: '#0A0F19', labelPlateOpacity: 0.62, labelInk: '#EEF2F8', subInk: '#A9B6C8',
      font: { label: 'IBM Plex Sans', sub: 'IBM Plex Sans', mono: 'IBM Plex Mono' },
      size: { label: 31, sub: 25, tag: 25 }, weight: { label: 600 }, track: { label: '0' },
      dimTo: 0.38, veil: '#0B111C', bloom: '#FF8A3D', bloomOpacity: 0.5,
    },
  };
  // white: a white ground and neutral greys for everything structural; colour only where it means something
  // (cold = blue: what flows, what is selected; hot = warm orange: a rise, an alert). Inter and JetBrains Mono.
  THEMES.white = {
    name: 'white', ground: '#FFFFFF',
    lw: 1.5, ink: '#1F2328', detail: '#A3A9B1', hatch: '#C3C8CF', grid: '#F0F2F5', floorInk: '#4B5563',
    faces: { top: '#FFFFFF', left: '#F4F5F7', right: '#E7E9ED', recess: '#EEF0F3', deep: '#E5E7EB', blade: '#FAFBFC' },
    plateFaces: { top: '#FCFCFD', left: '#EEF0F3', right: '#E3E6EA' },
    coolFaces: { top: '#F1F5FE', left: '#E3EAF9', right: '#D7E0F4' },
    glass: { top: '#EEF4FF', left: '#E0EAFB', right: '#D3E0F7' }, glassLine: '#2563EB', glassOpacity: 0.78, glassGlow: false,
    padFaces: { top: '#F6F7F9', left: '#E9EBEF', right: '#DDE0E5' },
    wallFaces: { top: '#F8F9FA', left: '#ECEEF1', right: '#F2F3F5' },
    floorFaces: { top: '#F8F9FA', left: '#ECEEF1', right: '#E2E5E9' }, plank: '#E5E7EB', ghost: '#A3A9B1',
    roofFaces: { top: '#F3F4F6', left: '#E9EBEE', right: '#DEE1E6' },
    cylStops: '<stop offset="0" stop-color="#FFFFFF"/><stop offset="0.45" stop-color="#F3F4F6"/><stop offset="1" stop-color="#DADDE2"/>',
    domeStops: '<stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#E3E5E9"/>',
    shadow: 'rgba(15,23,42,0.10)', shadowBlur: 10,
    pipe: { body: '#FFFFFF', sheen: 'rgba(255,255,255,0.8)', collar: '#F6F7F9' },
    tones: {
      cold: { tint: '#DCE7FD', flow: '#2563EB', air: '#5B8DEF', tag: '#2563EB', tagInk: '#FFFFFF', face: '#EAF1FE' },
      hot: { tint: '#FDDCCB', flow: '#D9480F', air: '#E8703A', tag: '#C2410C', tagInk: '#FFFFFF', face: '#FEEDE4' },
      warm: { tint: '#FDE7C8', flow: '#C2710C', air: '#D98B2B', tag: '#9A5A08', tagInk: '#FFFFFF', face: '#FEF3E2' },
      mute: { tint: '#ECEEF1', flow: '#9AA1AB', air: '#AEB4BC', tag: '#F1F3F5', tagInk: '#374151', face: '#F3F4F6' },
      ok: { tint: '#D7F0E0', flow: '#15803D', air: '#3A9A5E', tag: '#15803D', tagInk: '#FFFFFF', face: '#E8F6EE' },
    },
    flowStyle: 'dash', tagStyle: 'solid', tokenStyle: 'puck', airOpacity: 0.85,
    leader: '#6B7280', leaderW: 1.4, dotFill: '#FFFFFF',
    labelPlate: '#FFFFFF', labelPlateOpacity: 0.92, labelInk: '#111827', subInk: '#4B5563',
    font: { label: 'Inter', sub: 'Inter', mono: 'JetBrains Mono' },
    size: { label: 32, sub: 26, tag: 27 }, weight: { label: 600 }, track: { label: '-0.01em' },
    dimTo: 0.38, veil: '#FFFFFF', bloom: '#93B4F5', bloomOpacity: 0.25,
  };
  THEMES.paper = THEMES.light; THEMES.night = THEMES.dark;
  function toneOf(L, name) { return L.tones[name] || L.tones[{ a: 'cold', b: 'hot', c: 'warm', no: 'hot', yes: 'ok', green: 'ok' }[name]] || L.tones.mute; }

  /* ------------------------------------------------------------------ the parts library
     Each entry turns {at, size, ...} into shapes (drawn in order), a world bbox, an anchor (where a label
     points), a footprint (the contact shadow) and named ports (where pipes and links attach). Ports are
     {at:[x,y,z], face:'x+'|'x-'|'y+'|'y-'|'top'|'bottom'}: a pipe on a back face (x-, y-, bottom) is drawn
     behind its part, on a front face (x+, y+, top) in front of it. */
  function boxPorts(x0, y0, z0, w, d, h) {
    var cx = x0 + w / 2, cy = y0 + d / 2, cz = z0 + h / 2;
    return {
      top: { at: [cx, cy, z0 + h], face: 'top' }, bottom: { at: [cx, cy, z0], face: 'bottom' },
      'x+': { at: [x0 + w, cy, cz], face: 'x+' }, 'x-': { at: [x0, cy, cz], face: 'x-' },
      'y+': { at: [cx, y0 + d, cz], face: 'y+' }, 'y-': { at: [cx, y0, cz], face: 'y-' },
    };
  }
  var LIB = {
    box: function (o) {
      var a = o.at, s = o.size || [10, 10, 10];
      return { shapes: [{ kind: 'box', at: a, size: s, bevel: o.bevel == null ? 0.6 : o.bevel, tone: o.faces }],
        bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + s[2]]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + s[2]],
        footprint: [a[0], a[1], s[0], s[1]], ports: boxPorts(a[0], a[1], a[2], s[0], s[1], s[2]) };
    },
    slab: function (o) { return LIB.box(Object.assign({ bevel: 0, faces: 'padFaces' }, o, { size: o.size || [12, 12, 1.2] })); },
    plate: function (o) {
      var a = o.at || [-2, -2, -2.4], s = o.size || [100, 64, 2.4];
      return { layer: 'floor', shapes: [{ kind: 'plate', at: a, size: s, grid: o.grid == null ? 6 : o.grid, ruler: o.ruler !== false && !o.glass, faces: o.faces, glass: o.glass }],
        bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + s[2]]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, 0] };
    },
    floor: function (o) { // a raised floor area (indoor), planks optional
      var a = o.at, s = o.size;
      var sh = [{ kind: 'box', at: a, size: [s[0], s[1], s[2] || 0.35], tone: o.faces || 'floorFaces' }];
      if (o.planks !== false) sh.push({ kind: 'planks', at: [a[0], a[1], a[2] + (s[2] || 0.35)], size: s, step: o.planks || 3.2 });
      return { layer: 'floor', shapes: sh, bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + (s[2] || 0.35)]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2]] };
    },
    wall: function (o) { // a cut wall: hatched section on top (+ the end face), the removed part as a dashed ghost
      var a = o.at, s = o.size, sh = [{ kind: 'box', at: a, size: s, tone: 'wallFaces' }, { kind: 'hatch', at: a, size: s, endFace: o.endFace !== false }];
      return { shapes: sh, bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + s[2]]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + s[2]],
        footprint: [a[0], a[1], s[0], s[1]], ports: boxPorts(a[0], a[1], a[2], s[0], s[1], s[2]) };
    },
    unit: function (o) { // an outdoor unit: fan on the y+ face, coil fins on the x+ face, a grille on top, bolts
      var a = o.at, s = o.size || [24, 18, 24], x0 = a[0], y0 = a[1], z0 = a[2], w = s[0], d = s[1], h = s[2];
      var R = Math.min(w, h) * 0.34, sh = [{ kind: 'box', at: a, size: s, bevel: 1.1 }];
      sh.push({ kind: 'fins', face: 'x+', plane: x0 + w, c: [y0 + d * 0.61, z0 + h * 0.56], u0: -d * 0.26, u1: d * 0.26, v0: -h * 0.29, v1: h * 0.31, step: 0.42 });
      sh.push({ kind: 'fan', face: 'y+', plane: y0 + d, c: [x0 + w / 2, z0 + h * 0.52], R: R, spin: o.spin });
      for (var i = 0; i < 4; i++) sh.push({ kind: 'line', pts: [[x0 + 3 + i * 2.2, y0 + 3, z0 + h], [x0 + 3 + i * 2.2, y0 + d - 3, z0 + h]], lw: 0.5 });
      [[x0 + 1.3, z0 + 1.5], [x0 + w - 1.3, z0 + 1.5], [x0 + 1.3, z0 + h - 1.5], [x0 + w - 1.3, z0 + h - 1.5]].forEach(function (b) { sh.push({ kind: 'bolt', at: [b[0], y0 + d, b[1]] }); });
      var P = boxPorts(x0, y0, z0, w, d, h);
      P.out = { at: [x0 + w, y0 + 3, z0 + h * 0.48], face: 'x+' }; P.in = { at: [x0 + w, y0 + d - 4, z0 + h * 0.19], face: 'x+' };
      return { shapes: sh, bbox: [a, [x0 + w, y0 + d, z0 + h]], anchor: [x0 + 0.5, y0 + d, z0 + h * 0.62], footprint: [x0, y0, w, d], ports: P };
    },
    compressor: function (o) { // a pad, a domed shell with bands, a terminal box
      var a = o.at, r = o.r || 4.6, h = o.h || 13.5, cx = a[0], cy = a[1], z0 = a[2], pad = r * 1.2;
      var sh = [{ kind: 'box', at: [cx - pad, cy - pad, z0], size: [pad * 2, pad * 2, 1.4], tone: 'padFaces' },
        { kind: 'cyl', at: [cx, cy, z0 + 1.4], r: r, h: h, dome: r * 0.65, bands: [h * 0.24, h * 0.78] },
        { kind: 'box', at: [cx + r * 0.57, cy + r * 0.57, z0 + h * 0.4], size: [r * 0.57, r * 0.57, r * 0.7], bevel: 0.4 }];
      var top = z0 + 1.4 + h + r * 0.65;
      return { shapes: sh, bbox: [[cx - pad, cy - pad, z0], [cx + pad, cy + pad, top]], anchor: [cx, cy, top - 0.4], footprint: [cx - pad, cy - pad, pad * 2, pad * 2],
        ports: { top: { at: [cx, cy, top - 0.8], face: 'top' }, 'y+': { at: [cx, cy + r, z0 + 1.4 + h * 0.75], face: 'y+' }, 'x+': { at: [cx + r, cy, z0 + 1.4 + h * 0.75], face: 'x+' },
          'x-': { at: [cx - r, cy, z0 + 1.4 + h * 0.75], face: 'x-' }, in: { at: [cx, cy + r, z0 + 1.4 + h * 0.75], face: 'y+' }, out: { at: [cx, cy, top - 0.8], face: 'top' } } };
    },
    tank: function (o) { // a vertical vessel
      var a = o.at, r = o.r || 4, h = o.h || 12;
      return { shapes: [{ kind: 'cyl', at: a, r: r, h: h, dome: o.dome == null ? r * 0.5 : o.dome, bands: o.bands || [h * 0.2, h * 0.8], cap: o.cap }],
        bbox: [[a[0] - r, a[1] - r, a[2]], [a[0] + r, a[1] + r, a[2] + h + (o.dome == null ? r * 0.5 : o.dome)]], anchor: [a[0], a[1], a[2] + h],
        footprint: [a[0] - r, a[1] - r, r * 2, r * 2], ports: { top: { at: [a[0], a[1], a[2] + h], face: 'top' }, 'x+': { at: [a[0] + r, a[1], a[2] + h / 2], face: 'x+' },
          'y+': { at: [a[0], a[1] + r, a[2] + h / 2], face: 'y+' }, 'x-': { at: [a[0] - r, a[1], a[2] + h / 2], face: 'x-' }, 'y-': { at: [a[0], a[1] - r, a[2] + h / 2], face: 'y-' } } };
    },
    valve: function (o) { // a small body with a bonnet
      var a = o.at, s = o.size || [3.6, 3.4, 4.2];
      return { shapes: [{ kind: 'box', at: a, size: s, bevel: 0.5 }, { kind: 'cyl', at: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + s[2]], r: 1.1, h: 2.4, cap: 0.5 }],
        bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + s[2] + 2.4]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + s[2] + 2.4],
        footprint: [a[0], a[1], s[0], s[1]], ports: boxPorts(a[0], a[1], a[2], s[0], s[1], s[2]) };
    },
    cassette: function (o) { // a wall-mounted indoor unit: grille slot on its x+ face
      var a = o.at, s = o.size || [4.4, 18, 7], x1 = a[0] + s[0];
      var sh = [{ kind: 'box', at: a, size: s, bevel: 0.6 },
        { kind: 'face', pts: [[x1, a[1] + 1.2, a[2] + 0.8], [x1, a[1] + s[1] - 1.2, a[2] + 0.8], [x1, a[1] + s[1] - 1.2, a[2] + 2.8], [x1, a[1] + 1.2, a[2] + 2.8]], tone: 'recess', lw: 0.6, stroke: 'detail' },
        { kind: 'line', pts: [[x1, a[1] + 1.2, a[2] + 1.8], [x1, a[1] + s[1] - 1.2, a[2] + 1.8]], lw: 0.45 },
        { kind: 'line', pts: [[x1, a[1] + 2, a[2] + 5.4], [x1, a[1] + 5.5, a[2] + 5.4]], lw: 0.6 }];
      return { shapes: sh, bbox: [a, [x1, a[1] + s[1], a[2] + s[2]]], anchor: [x1, a[1] + s[1] * 0.25, a[2] + s[2]], ports: boxPorts(a[0], a[1], a[2], s[0], s[1], s[2]) };
    },
    /* abstract system pieces: the same line, faces and shadow, for entities that are not machines */
    node: function (o) { // an entity on a round pedestal: icon person | building | school | bank | firm | server | house
      var a = o.at, r = o.r || 4.2, ph = o.pedestal == null ? 1.2 : o.pedestal, cx = a[0], cy = a[1], z0 = a[2] || 0;
      var sh = o.glass ? [{ kind: 'box', at: [cx - r * 0.8, cy - r * 0.8, z0], size: [r * 1.6, r * 1.6, ph], glass: true }] : [{ kind: 'cyl', at: [cx, cy, z0], r: r, h: ph, flat: true }], top = z0 + ph, icon = o.icon || 'person', ih;
      var k = o.scale || 1;
      if (icon === 'person') {
        sh.push({ kind: 'cyl', at: [cx, cy, top], r: 1.55 * k, h: 3.6 * k, dome: 0.9 * k });
        sh.push({ kind: 'ball', at: [cx, cy, top + 3.6 * k + 0.9 * k + 1.5 * k], r: 1.45 * k });
        ih = 3.6 * k + 0.9 * k + 3.0 * k;
      } else if (icon === 'terminal') { // a screen on a stand: the prompt lines on its y+ face
        var tw = 7.2 * k, th = 5 * k, td = 1.2 * k, tx0 = cx - tw / 2, ty0 = cy - td / 2, tz = top + 1.1 * k;
        sh.push({ kind: 'box', at: [cx - 0.5 * k, cy - 0.5 * k, top], size: [1 * k, 1 * k, 1.1 * k], bevel: 0 });
        sh.push({ kind: 'box', at: [tx0, ty0, tz], size: [tw, td, th], bevel: 0 });
        sh.push({ kind: 'face', pts: [[tx0 + 0.5 * k, ty0 + td, tz + 0.5 * k], [tx0 + tw - 0.5 * k, ty0 + td, tz + 0.5 * k], [tx0 + tw - 0.5 * k, ty0 + td, tz + th - 0.5 * k], [tx0 + 0.5 * k, ty0 + td, tz + th - 0.5 * k]], tone: 'deep', lw: 0.7 });
        [0.72, 0.5, 0.28].forEach(function (f, i) { sh.push({ kind: 'line', pts: [[tx0 + 1.1 * k, ty0 + td, tz + th * f], [tx0 + (i === 2 ? 2.4 : 4.6 - i * 0.9) * k, ty0 + td, tz + th * f]], lw: 1.1, stroke: 'ink' }); });
        ih = 1.1 * k + th;
      } else if (icon === 'hub') { // a program: a block with a recessed top and four port nubs
        var hw = 6.4 * k, hh = 3.2 * k, hx = cx - hw / 2, hy = cy - hw / 2;
        sh.push({ kind: 'box', at: [hx, hy, top], size: [hw, hw, hh], bevel: 0.7 * k });
        sh.push({ kind: 'box', at: [cx - 1.4 * k, cy - 1.4 * k, top + hh], size: [2.8 * k, 2.8 * k, 0.9 * k], bevel: 0.3 });
        ih = hh + 0.9 * k;
      } else if (icon === 'core' && o.glass) { // a model in its own material: a glowing core inside a glass shell
        var gw2 = 7.6 * k, gz = 6.4 * k, ic = 3.2 * k;
        sh.push({ kind: 'box', at: [cx - ic / 2, cy - ic / 2, top + 0.6 * k], size: [ic, ic, ic], bevel: 0.3, lamp: true, tone: 'padFaces' });
        sh.push({ kind: 'box', at: [cx - gw2 / 2, cy - gw2 / 2, top], size: [gw2, gw2, gz], glass: true });
        ih = gz;
      } else if (icon === 'core') { // an engine or a model: a cube with a raised core and edge lines
        var cw = 7.6 * k, cz = 6.2 * k, ccx = cx - cw / 2, ccy = cy - cw / 2;
        sh.push({ kind: 'box', at: [ccx, ccy, top], size: [cw, cw, cz], bevel: 0.9 * k });
        for (var q = 1; q < 4; q++) sh.push({ kind: 'line', pts: [[ccx + cw, ccy + cw * q / 4, top + 0.8 * k], [ccx + cw, ccy + cw * q / 4, top + cz - 0.8 * k]], lw: 0.6 },
          { kind: 'line', pts: [[ccx + cw * q / 4, ccy + cw, top + 0.8 * k], [ccx + cw * q / 4, ccy + cw, top + cz - 0.8 * k]], lw: 0.6 });
        sh.push({ kind: 'cyl', at: [cx, cy, top + cz], r: 1.8 * k, h: 1.2 * k, cap: 0.55 });
        ih = cz + 1.2 * k;
      } else if (icon === 'gate') { // a checkpoint: two posts and a bar across them
        var gw = 3.2 * k, gh = 4.6 * k;
        sh.push({ kind: 'box', at: [cx - 0.6 * k, cy - gw - 0.6 * k, top], size: [1.2 * k, 1.2 * k, gh], bevel: 0 });
        sh.push({ kind: 'box', at: [cx - 0.6 * k, cy + gw - 0.6 * k, top], size: [1.2 * k, 1.2 * k, gh], bevel: 0 });
        sh.push({ kind: 'box', at: [cx - 0.35 * k, cy - gw, top + gh * 0.62], size: [0.7 * k, gw * 2, 0.9 * k], bevel: 0, tone: 'padFaces' });
        sh.push({ kind: 'ball', at: [cx, cy - gw, top + gh + 0.8 * k], r: 0.8 * k, lamp: true });
        ih = gh + 1.6 * k;
      } else if (icon === 'files') { // a folder of documents: three sheets, fanned
        for (var f = 0; f < 3; f++) sh.push({ kind: 'box', at: [cx - 2.6 * k + f * 0.7 * k, cy - 3.2 * k + f * 0.5 * k, top + f * 0.9 * k], size: [4.6 * k, 5.8 * k, 0.6 * k], bevel: 0 });
        for (var fl = 0; fl < 3; fl++) sh.push({ kind: 'line', pts: [[cx - 1.2 * k, cy - 2 * k + fl * 1.2 * k, top + 2.4 * k], [cx + 1.6 * k, cy - 2 * k + fl * 1.2 * k, top + 2.4 * k]], lw: 0.7 });
        ih = 2.4 * k;
      } else if (icon === 'lamp') { // a status light on a small housing (the state tints the light)
        sh.push({ kind: 'box', at: [cx - 2.4 * k, cy - 2.4 * k, top], size: [4.8 * k, 4.8 * k, 2.4 * k], bevel: 0.4 });
        sh.push({ kind: 'ball', at: [cx, cy, top + 2.4 * k + 1.6 * k], r: 1.6 * k, lamp: true });
        ih = 2.4 * k + 3.2 * k;
      } else if (icon === 'tool') { // a small instrument block
        sh.push({ kind: 'box', at: [cx - 1.9 * k, cy - 1.9 * k, top], size: [3.8 * k, 3.8 * k, 2.6 * k], bevel: 0.4 });
        ih = 2.6 * k;
      } else if (icon === 'server') {
        for (var i = 0; i < 3; i++) sh.push({ kind: 'box', at: [cx - 2.4 * k, cy - 2.4 * k, top + i * 2.1 * k], size: [4.8 * k, 4.8 * k, 1.9 * k], bevel: 0.25 },
          { kind: 'line', pts: [[cx + 2.4 * k, cy - 1.6 * k, top + i * 2.1 * k + 0.95 * k], [cx + 2.4 * k, cy + 0.4 * k, top + i * 2.1 * k + 0.95 * k]], lw: 0.8 });
        ih = 6.3 * k;
      } else {
        var bw = 6.4 * k, bd = 5 * k, bh = icon === 'firm' ? 3.6 * k : 4.2 * k, x0 = cx - bw / 2, y0 = cy - bd / 2;
        sh.push({ kind: 'box', at: [x0, y0, top], size: [bw, bd, bh], bevel: 0 });
        if (icon === 'bank') {
          for (var c = 0; c < 4; c++) sh.push({ kind: 'line', pts: [[x0 + 0.9 * k + c * 1.55 * k, y0 + bd, top + 0.3], [x0 + 0.9 * k + c * 1.55 * k, y0 + bd, top + bh - 0.6 * k]], lw: 0.9 });
          sh.push({ kind: 'gable', at: [x0, y0, top + bh], size: [bw, bd, 1.8 * k], ridge: 'x' });
          ih = bh + 1.8 * k;
        } else if (icon === 'firm') {
          sh.push({ kind: 'saw', at: [x0, y0, top + bh], size: [bw, bd, 1.6 * k], n: 3 });
          sh.push({ kind: 'cyl', at: [x0 + bw * 0.78, y0 + bd * 0.25, top + bh], r: 0.6 * k, h: 3.4 * k });
          ih = bh + 3.4 * k;
        } else { // building, school, house: a gable roof (school: a door and a flag mast)
          sh.push({ kind: 'gable', at: [x0, y0, top + bh], size: [bw, bd, 2.6 * k], ridge: 'x' });
          sh.push({ kind: 'face', pts: [[x0 + bw * 0.42, y0 + bd, top], [x0 + bw * 0.58, y0 + bd, top], [x0 + bw * 0.58, y0 + bd, top + bh * 0.55], [x0 + bw * 0.42, y0 + bd, top + bh * 0.55]], tone: 'recess', lw: 0.7 });
          if (icon === 'school') sh.push({ kind: 'line', pts: [[x0 + bw * 0.5, y0 + bd * 0.5, top + bh + 2.6 * k], [x0 + bw * 0.5, y0 + bd * 0.5, top + bh + 5 * k]], lw: 0.9, stroke: 'ink' },
            { kind: 'face', pts: [[x0 + bw * 0.5, y0 + bd * 0.5, top + bh + 5 * k], [x0 + bw * 0.5 + 1.8 * k, y0 + bd * 0.5, top + bh + 4.4 * k], [x0 + bw * 0.5, y0 + bd * 0.5, top + bh + 3.8 * k]], tone: 'flag', lw: 0.7 });
          ih = bh + (icon === 'school' ? 5 * k : 2.6 * k);
        }
      }
      var seats = [], ports = { top: { at: [cx, cy, top + ih], face: 'top' }, center: { at: [cx, cy, top], face: 'top' },
        'x+': { at: [cx + r, cy, z0 + ph / 2], face: 'x+' }, 'x-': { at: [cx - r, cy, z0 + ph / 2], face: 'x-' },
        'y+': { at: [cx, cy + r, z0 + ph / 2], face: 'y+' }, 'y-': { at: [cx, cy - r, z0 + ph / 2], face: 'y-' } };
      var sw = o.seatSize || 2.8;
      if (o.seats) { // capacity: seat tiles in a row beside the node (seatSide y+ or x+), each a slot tokens rest in
        var n = o.seats, gap = 0.9, row = n * sw + (n - 1) * gap, alongX = (o.seatSide || 'y+') === 'y+';
        for (var j = 0; j < n; j++) {
          var sa = alongX ? [cx - row / 2 + j * (sw + gap), cy + r + 1.4, z0] : [cx + r + 1.4, cy - row / 2 + j * (sw + gap), z0];
          sh.push({ kind: 'box', at: sa, size: [sw, sw, 0.5], tone: 'padFaces', bevel: 0 });
          seats.push([sa[0] + sw / 2, sa[1] + sw / 2, z0 + 0.5]);
          ports['seat' + (j + 1)] = { at: seats[j], face: 'top' };
        }
      }
      var ext = o.seats ? r + 1.4 + sw : r, sx2 = o.seats && o.seatSide === 'x+' ? ext : r, sy2 = o.seats && o.seatSide !== 'x+' ? ext : r;
      return { shapes: sh, bbox: [[cx - r, cy - r, z0], [cx + sx2, cy + sy2, top + ih]], anchor: [cx, cy, top + ih], footprint: [cx - r, cy - r, r * 2, r * 2], ports: ports, seats: seats };
    },
    store: function (o) { // a pool or reservoir: an open tray whose level is keyed in time (fill: [[t, 0..1], ...])
      var a = o.at, s = o.size || [12, 8, 3];
      return { shapes: [{ kind: 'tray', at: a, size: s, fill: o.fill, tone: o.tone || 'cold' }],
        bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + s[2]]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + s[2]],
        footprint: [a[0], a[1], s[0], s[1]], ports: boxPorts(a[0], a[1], a[2], s[0], s[1], s[2]) };
    },
    stack: function (o) { // a store that grows: cells stacked up, count keyed in time ([[t, n], ...])
      var a = o.at, s = o.size || [8, 8], ch = o.cell || 1.1, gap = o.gap == null ? 0.35 : o.gap, n = o.max || 8, cells = [], ports = {};
      for (var i = 0; i < n; i++) { var z = a[2] + i * (ch + gap); cells.push({ kind: 'cell', at: [a[0], a[1], z], size: [s[0], s[1], ch], i: i, count: o.count, tone: o.tone }); ports['cell' + (i + 1)] = { at: [a[0] + s[0] / 2, a[1] + s[1] / 2, z + ch], face: 'top' }; }
      var hgt = n * (ch + gap);
      Object.assign(ports, boxPorts(a[0], a[1], a[2], s[0], s[1], hgt));
      return { shapes: [{ kind: 'box', at: [a[0] - 0.8, a[1] - 0.8, a[2] - 0.5], size: [s[0] + 1.6, s[1] + 1.6, 0.5], tone: 'padFaces', bevel: 0 }].concat(cells),
        bbox: [[a[0] - 0.8, a[1] - 0.8, a[2] - 0.5], [a[0] + s[0] + 0.8, a[1] + s[1] + 0.8, a[2] + hgt]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + hgt * 0.5],
        footprint: [a[0] - 0.8, a[1] - 0.8, s[0] + 1.6, s[1] + 1.6], ports: ports };
    },
    queue: function (o) { // a line of n slots along x (or y): tokens wait in them
      var a = o.at, n = o.n || 5, sw = o.slot || 2.8, gap = o.gap == null ? 0.8 : o.gap, along = o.along || 'x', sh = [], slots = [], ports = {};
      for (var i = 0; i < n; i++) {
        var off = i * (sw + gap), at = along === 'x' ? [a[0] + off, a[1], a[2]] : [a[0], a[1] + off, a[2]];
        sh.push({ kind: 'box', at: at, size: [sw, sw, 0.6], tone: 'padFaces', bevel: 0 });
        slots.push([at[0] + sw / 2, at[1] + sw / 2, at[2] + 0.6]); ports['slot' + (i + 1)] = { at: slots[i], face: 'top' };
      }
      var len = n * sw + (n - 1) * gap, s = along === 'x' ? [len, sw, 0.6] : [sw, len, 0.6];
      Object.assign(ports, boxPorts(a[0], a[1], a[2], s[0], s[1], s[2]));
      return { shapes: sh, bbox: [a, [a[0] + s[0], a[1] + s[1], a[2] + 0.6]], anchor: [a[0] + s[0] / 2, a[1] + s[1] / 2, a[2] + 0.6], ports: ports, seats: slots, footprint: [a[0], a[1], s[0], s[1]] };
    },
  };

  /* ------------------------------------------------------------------ helpers on boxes and screen shapes */
  function hull(pts) { // monotone chain
    var p = pts.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    if (p.length < 3) return p;
    var cross = function (o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); };
    var lo = [], up = [], i;
    for (i = 0; i < p.length; i++) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p[i]) <= 0) lo.pop(); lo.push(p[i]); }
    for (i = p.length - 1; i >= 0; i--) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], p[i]) <= 0) up.pop(); up.push(p[i]); }
    up.pop(); lo.pop(); return lo.concat(up);
  }
  function inPoly(x, y, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) inside = !inside;
    }
    return inside;
  }
  function rectOverlap(a, b) { // fraction of a covered by b ({x,y,w,h})
    var w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return w > 0 && h > 0 ? (w * h) / (a.w * a.h) : 0;
  }
  function segHitsRect(p, q, r) { // sampled: enough for a leader against a label plate
    for (var i = 1; i < 12; i++) { var x = lerp(p[0], q[0], i / 12), y = lerp(p[1], q[1], i / 12); if (x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.h) return true; }
    return false;
  }

  /* ------------------------------------------------------------------ validation */
  function validate(spec) {
    var errs = [], ids = {};
    if (!spec || typeof spec !== 'object') return ['the scene is not an object (window.SCENE = {...})'];
    if (!spec.world || !Array.isArray(spec.world.origin) || !(spec.world.scale > 0)) errs.push('world needs {scale: > 0, origin: [x, y]}');
    (spec.items || []).forEach(function (it, i) {
      var where = 'items[' + i + ']' + (it && it.id ? ' "' + it.id + '"' : '');
      if (!it || typeof it !== 'object') { errs.push(where + ' is not an object'); return; }
      if (it.id) { if (ids[it.id]) errs.push(where + ': duplicate id'); ids[it.id] = it; }
      if (it.part && !LIB[it.part]) errs.push(where + ': unknown part "' + it.part + '" (known: ' + Object.keys(LIB).join(', ') + ')');
      if (it.part && !Array.isArray(it.at)) errs.push(where + ': a part needs at: [x, y, z]');
      if ((it.kind === 'pipe' || it.kind === 'link') && !it.path && !(it.from && it.to)) errs.push(where + ': a ' + it.kind + ' needs path: [[x,y,z], ...] or from/to ports');
      if (!it.part && !it.kind && !it.shapes) errs.push(where + ': needs part, kind or shapes');
    });
    var portOk = function (ref, where) {
      if (Array.isArray(ref)) return;
      var m = String(ref).split('.'), it = ids[m[0]];
      if (!it) errs.push(where + ': unknown part "' + m[0] + '"');
    };
    (spec.items || []).forEach(function (it, i) {
      if (it && (it.kind === 'pipe' || it.kind === 'link') && it.from) { portOk(it.from, 'items[' + i + '].from'); portOk(it.to, 'items[' + i + '].to'); }
    });
    flowsOf(spec).forEach(function (f, i) {
      (f.path || []).forEach(function (e) { if (e.pipe && !(ids[e.pipe] && (ids[e.pipe].kind === 'pipe' || ids[e.pipe].kind === 'link'))) errs.push('flows[' + i + ']: unknown pipe "' + e.pipe + '"'); });
      if (!(f.at >= 0) && f.at !== 0) errs.push('flows[' + i + ']: at must be a time in seconds');
    });
    (spec.labels || []).forEach(function (lb, i) {
      if (!lb.anchor && !(lb.for && ids[lb.for])) errs.push('labels[' + i + ']' + (lb.title ? ' "' + lb.title + '"' : '') + ': needs anchor: [x,y,z] or for: a part id' + (lb.for ? ' ("' + lb.for + '" is not one)' : ''));
      if (typeof lb.at !== 'number') errs.push('labels[' + i + ']: at must be a number of seconds');
    });
    (spec.tags || []).forEach(function (tg, i) {
      if (tg.pipe && !ids[tg.pipe]) errs.push('tags[' + i + ']: unknown pipe "' + tg.pipe + '"');
      if (tg.for && !ids[tg.for]) errs.push('tags[' + i + ']: unknown part "' + tg.for + '"');
      if (!tg.pipe && !tg.for && !tg.anchor && !tg.token) errs.push('tags[' + i + ']: needs pipe, for, anchor or token');
    });
    focusesOf(spec).forEach(function (fc, i) { if (!ids[fc.part]) errs.push('focus[' + i + ']: unknown part "' + fc.part + '"'); });
    (spec.camera || []).forEach(function (k, i) { if (typeof k.focus === 'string' && !ids[k.focus]) errs.push('camera[' + i + ']: unknown part "' + k.focus + '"'); });
    (spec.tokens || []).forEach(function (tk, i) {
      (tk.moves || []).forEach(function (mv, j) { if (mv.along && !ids[mv.along]) errs.push('tokens[' + i + '].moves[' + j + ']: unknown link "' + mv.along + '"'); });
    });
    return errs;
  }
  function flowsOf(spec) {
    if (spec.flows) return spec.flows;
    return spec.flow ? [Object.assign({ id: 'flow' }, spec.flow, { path: spec.flow.path || spec.flow.loop })] : [];
  }
  function focusesOf(spec) { return !spec.focus ? [] : Array.isArray(spec.focus) ? spec.focus : [spec.focus]; }

  /* ------------------------------------------------------------------ mount */
  function mount(spec, opts) {
    opts = opts || {};
    // live mode (Diagram.live): the page runs its own clock and writes keys at the moment the viewer acts (set, fire,
    // focus); everything is still drawn as a pure function of that clock. A film mount never takes these paths.
    var LIVE = opts.live ? (opts.live === true ? {} : opts.live) : null;
    var liveLevels = {};
    var themeName = opts.theme || spec.theme || (document.documentElement.getAttribute('data-theme')) || 'light';
    var L = Object.assign({}, THEMES[themeName] || THEMES.light, opts.look || {});
    if (!THEMES[themeName]) warn('unknown theme "' + themeName + '" (light or dark): using light');
    var problems = validate(spec);
    problems.forEach(warn);
    if (!spec.world || !Array.isArray(spec.world.origin) || !(spec.world.scale > 0)) return null;
    var S = spec.world.scale, O = spec.world.origin;
    var P = function (x, y, z) { return [O[0] + (x - y) * C * S, O[1] + (x + y) * 0.5 * S - (z || 0) * S]; };
    var V = function (dx, dy, dz) { return [(dx - dy) * C * S, (dx + dy) * 0.5 * S - (dz || 0) * S]; }; // a world offset on screen
    var pts = function (a) { return a.map(function (p) { return f1(p[0]) + ',' + f1(p[1]); }).join(' '); };
    var dpath = function (a) { return 'M' + a.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L'); };
    var clip = (spec.clip || [45, 45, 1830, 990]).map(function (v) { return Number(v) || 0; });
    // labels stay inside [x0, y0, x1, y1]; never looser than the text-safe zone the renderer fades text out of
    var safe = (function (a) { return [Math.max(a[0], 64), Math.max(a[1], 58), Math.min(a[2], 1856), Math.min(a[3], 990)]; })(spec.safe || [100, 92, 1820, 990]);

    /* ---- the page's words from the scene (spec.page), so one scene file carries its own title block ---- */
    if (spec.page) {
      var put = function (sel, text, html) { var e = document.querySelector(sel); if (!e || text == null) return; if (html) e.innerHTML = html; else e.textContent = text; };
      var pg = spec.page, k = pg.kicker != null ? String(pg.kicker).split(' · ') : null;
      if (k) put('.ld-kicker', pg.kicker, k.length > 1 ? '<b>' + esc(k[0]) + '</b> &nbsp;·&nbsp; ' + esc(k.slice(1).join(' · ')) : null);
      put('.ld-figno', pg.figno);
      if (pg.title != null) put('.ld-title', pg.title, esc(pg.title).replace(/\*([^*]+)\*/g, '<em>$1</em>'));
      put('.ld-dek', pg.dek);
      put('.ld-foot.l', pg.footL);
      var sh = document.querySelector('.ld-steps');
      if (sh && pg.steps) { // where the beat lines sit: {at: [x, y], width} in design px (default under the dek)
        if (pg.steps.at) { sh.style.left = pg.steps.at[0] + 'px'; sh.style.top = pg.steps.at[1] + 'px'; }
        if (pg.steps.width) sh.style.width = pg.steps.width + 'px';
      }
      if (pg.footR != null) { var fr = String(pg.footR).split(' · '); put('.ld-foot.r', pg.footR, fr.length > 1 ? '<span class="k">' + esc(fr[0]) + ' ·</span> ' + esc(fr.slice(1).join(' · ')) : null); }
    }

    /* ---- items: expand library parts, index by id ---- */
    var items = [], byId = {};
    (spec.items || []).forEach(function (raw, i) {
      if (!raw || (raw.part && !LIB[raw.part])) return;
      var it = Object.assign({}, raw);
      it._i = i;
      if (LIVE && it.id && (it.part === 'store' || it.part === 'stack')) { // live: its own keys, which set() rewrites
        var key = it.part === 'store' ? 'fill' : 'count', v0 = it[key];
        it[key] = Array.isArray(v0) ? v0.map(function (k) { return k.slice(); }) : [[-1e9, typeof v0 === 'number' ? v0 : 0]];
        liveLevels[it.id] = { keys: it[key], stack: it.part === 'stack' };
      }
      if (it.part) {
        var g = LIB[it.part](it);
        it.shapes = (g.shapes || []).concat(it.shapes || []);
        it.bbox = it.bbox || g.bbox; it.anchor = it.anchor || g.anchor; it.footprint = it.footprint === false ? null : (it.footprint || g.footprint);
        var rel = {};
        Object.keys(it.ports || {}).forEach(function (k) { // custom ports: relative to at
          var pv = it.ports[k], at = Array.isArray(pv) ? pv : pv.at;
          rel[k] = { at: [it.at[0] + at[0], it.at[1] + at[1], (it.at[2] || 0) + at[2]], face: (pv && pv.face) || 'top' };
        });
        it.ports = Object.assign({}, g.ports || {}, rel);
        it.seats = g.seats || [];
        it.layer = it.layer || g.layer;
      }
      if (!it.kind) it.kind = 'solid';
      if (it.kind === 'solid' && !it.bbox) it.bbox = shapesBBox(it.shapes || []);
      items.push(it);
      if (it.id) byId[it.id] = it;
    });
    function shapesBBox(shapes) {
      var lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      var add = function (p) { for (var k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p[k] || 0); hi[k] = Math.max(hi[k], p[k] || 0); } };
      shapes.forEach(function (s) {
        if (s.kind === 'box' || s.kind === 'plate' || s.kind === 'tray' || s.kind === 'gable' || s.kind === 'saw') { add(s.at); add([s.at[0] + s.size[0], s.at[1] + s.size[1], s.at[2] + (s.size[2] || 0)]); }
        else if (s.kind === 'cyl' || s.kind === 'ball') { var r = s.r; add([s.at[0] - r, s.at[1] - r, s.at[2] - (s.kind === 'ball' ? r : 0)]); add([s.at[0] + r, s.at[1] + r, s.at[2] + (s.h || r) + (s.dome || 0)]); }
        else if (s.pts) s.pts.forEach(add);
        else if (s.at) add(s.at);
      });
      return isFinite(lo[0]) ? [lo, hi] : null;
    }
    function portOf(ref) { // 'part.port' | 'part' (its anchor) | [x,y,z] -> {at, face, part}
      if (Array.isArray(ref)) return { at: ref, face: null, part: null };
      var m = String(ref).split('.'), it = byId[m[0]];
      if (!it) return { at: [0, 0, 0], face: null, part: null };
      var name = m.slice(1).join('.');
      if (!name) return { at: it.anchor || [0, 0, 0], face: null, part: it };
      var p = it.ports && it.ports[name];
      if (!p) { warn('part "' + m[0] + '" has no port "' + name + '" (ports: ' + Object.keys(it.ports || {}).join(', ') + ')'); return { at: it.anchor || [0, 0, 0], face: null, part: it }; }
      return { at: p.at, face: p.face, part: it };
    }
    var NORMAL = { 'x+': [1, 0, 0], 'x-': [-1, 0, 0], 'y+': [0, 1, 0], 'y-': [0, -1, 0], top: [0, 0, 1], bottom: [0, 0, -1] };
    function manhattan(a, b, order) { // from a to b moving one axis at a time, in `order` ('xyz', 'zx', ...)
      var out = [], cur = a.slice();
      (order || 'xyz').split('').forEach(function (ax) {
        var k = { x: 0, y: 1, z: 2 }[ax]; if (k == null || Math.abs(cur[k] - b[k]) < 1e-6) return;
        cur = cur.slice(); cur[k] = b[k]; out.push(cur);
      });
      if (!out.length || out[out.length - 1].some(function (v, k) { return Math.abs(v - b[k]) > 1e-6; })) out.push(b.slice());
      return out;
    }
    /* ---- pipes and links: rounded 3D polylines, routed between ports ---- */
    var pipes = {};
    items.forEach(function (it) {
      if (it.kind !== 'pipe' && it.kind !== 'link') return;
      var path = it.path, fromP = null, toP = null;
      if (!path) {
        fromP = portOf(it.from); toP = portOf(it.to);
        var stub = it.stub == null ? (it.kind === 'link' ? 0 : 1.6) : it.stub;
        var a = fromP.at.slice(), b = toP.at.slice(), path3 = [a];
        var na = fromP.face && NORMAL[fromP.face], nb = toP.face && NORMAL[toP.face];
        var a1 = na && stub ? a.map(function (v, k) { return v + na[k] * stub; }) : a;
        var b1 = nb && stub ? b.map(function (v, k) { return v + nb[k] * stub; }) : b;
        if (a1 !== a) path3.push(a1);
        var mids = [a1].concat((it.via || []).map(function (v) { return Array.isArray(v) ? v : portOf(v).at; })).concat([b1]);
        for (var i = 1; i < mids.length; i++) path3 = path3.concat(it.kind === 'link' && !it.route ? [mids[i]] : manhattan(mids[i - 1], mids[i], it.route));
        if (b1 !== b) path3.push(b);
        path = path3.filter(function (p, k) { return k === 0 || Math.hypot(p[0] - path3[k - 1][0], p[1] - path3[k - 1][1], p[2] - path3[k - 1][2]) > 1e-6; });
        it.path = path;
        if (it.ends == null && it.kind === 'pipe') it.ends = ['start', 'end'];
      }
      if (it.arc && path.length === 2) { // a link that arcs over the floor: a raised quadratic curve
        var p0 = path[0], p1 = path[1], mid = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2 + it.arc], q = [];
        for (var j = 0; j <= 24; j++) { var u = j / 24; q.push([0, 1, 2].map(function (k) { return (1 - u) * (1 - u) * p0[k] + 2 * (1 - u) * u * mid[k] + u * u * p1[k]; })); }
        path = q;
      }
      var r3 = it.arc ? path : roundPath(path, it.bend == null ? 2.4 : it.bend), scr = r3.map(function (p) { return P(p[0], p[1], p[2]); }), cum = measure(scr);
      pipes[it.id] = { it: it, p3: r3, scr: scr, cum: cum, len: cum[cum.length - 1], from: fromP, to: toP };
      var w = (it.w || (it.kind === 'link' ? 4 : 11)) / S / 2;
      var lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      path.forEach(function (p) { for (var k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p[k] - w); hi[k] = Math.max(hi[k], p[k] + w); } });
      it.bbox = [lo, hi];
      if (it.kind === 'link' && !it.layer && Math.max(Math.abs(lo[2]), Math.abs(hi[2])) < 1.2 && !it.arc) it.layer = 'floor';
    });
    function roundPath(p3, r) {
      var out = [p3[0]];
      for (var i = 1; i < p3.length - 1; i++) {
        var a = p3[i - 1], b = p3[i], c = p3[i + 1];
        var v1 = b.map(function (x, k) { return x - a[k]; }), v2 = c.map(function (x, k) { return x - b[k]; });
        var l1 = Math.hypot(v1[0], v1[1], v1[2]), l2 = Math.hypot(v2[0], v2[1], v2[2]), rr = Math.min(r, l1 / 2, l2 / 2);
        var s0 = b.map(function (x, k) { return x - (v1[k] / l1) * rr; }), s1 = b.map(function (x, k) { return x + (v2[k] / l2) * rr; });
        for (var j = 0; j <= 8; j++) { var q = j / 8; out.push(s0.map(function (x, k) { return (1 - q) * (1 - q) * x + 2 * (1 - q) * q * b[k] + q * q * s1[k]; })); }
      }
      out.push(p3[p3.length - 1]);
      return out;
    }
    function measure(scr) { var cum = [0]; for (var i = 1; i < scr.length; i++) cum.push(cum[i - 1] + Math.hypot(scr[i][0] - scr[i - 1][0], scr[i][1] - scr[i - 1][1])); return cum; }
    function atLen(pp, s) { // point + tangent at arc length s (screen px)
      var c = pp.cum, i = 1; while (i < c.length - 1 && c[i] < s) i++;
      var q = clamp((s - c[i - 1]) / (c[i] - c[i - 1] || 1), 0, 1), a = pp.scr[i - 1], b = pp.scr[i];
      return { x: lerp(a[0], b[0], q), y: lerp(a[1], b[1], q), ang: Math.atan2(b[1] - a[1], b[0] - a[0]), w3: pp.p3[i - 1].map(function (v, k) { return lerp(v, pp.p3[i][k], q); }) };
    }
    function trimmed(pp, s0, s1) { var out = [], a = atLen(pp, s0); out.push([a.x, a.y]); for (var i = 0; i < pp.scr.length; i++) if (pp.cum[i] > s0 && pp.cum[i] < s1) out.push(pp.scr[i]); var e = atLen(pp, s1); out.push([e.x, e.y]); return out; }

    /* ---- flows: one arc length over pipes and the bodies (gaps) between them ---- */
    var flows = flowsOf(spec).map(function (f) {
      var segs = [], len = 0;
      (f.path || []).forEach(function (e) { var l = e.pipe ? (pipes[e.pipe] ? pipes[e.pipe].len : 0) : (e.gap || 0); segs.push(Object.assign({}, e, { s0: len, len: l })); len += l; });
      return Object.assign({ speed: 150, spacing: 34, dash: 14, loop: true }, f, { segs: segs, len: len });
    });
    var flowOn = {}; // pipe id -> [{flow, seg}]
    flows.forEach(function (f) { f.segs.forEach(function (s) { if (s.pipe) (flowOn[s.pipe] = flowOn[s.pipe] || []).push({ f: f, s: s }); }); });

    /* ---- tones over time: a pipe or part starts neutral and takes its tone when its flow starts; states change it ---- */
    var states = (spec.states || []).slice().sort(function (a, b) { return a.at - b.at; });
    function toneAt(id, t, base, start) { // -> {from, to, p}: lerp target names
      var cur = null, prev = null, p = 1;
      if (start != null) { cur = base; prev = null; p = seg(t, start, 0.6, E.inOutSine); }
      states.forEach(function (st) {
        if (st.target !== id || t < st.at) return;
        prev = cur; cur = st.tone; p = seg(t, st.at, st.dur == null ? 0.6 : st.dur, E.inOutSine);
      });
      return { from: prev, to: cur, p: p };
    }
    var pulses = states.filter(function (st) { return st.pulse; });
    states = states.filter(function (st) { return !st.pulse; });
    function pulseAt(id, t) { // -> {c, p}: the strongest pulse on this item now
      var best = null;
      pulses.forEach(function (st) {
        if (st.target !== id || t < st.at) return;
        var d = st.dur == null ? 0.6 : st.dur, p = Math.sin(Math.PI * seg(t, st.at, d));
        if (p > 0 && (!best || p > best.p)) best = { c: toneOf(L, st.tone || 'cold').flow, p: p * (st.amount == null ? 0.3 : st.amount) };
      });
      return best;
    }
    function tintOf(tn, key, neutral) {
      var a = tn.from ? toneOf(L, tn.from)[key] : neutral, b = tn.to ? toneOf(L, tn.to)[key] : neutral;
      return mixHex(a, b, tn.p);
    }

    /* ---- focus windows and the text fade they drive ---- */
    var focuses = focusesOf(spec).map(function (fc) { return Object.assign({ dur: 0.7, out: 0.7, until: Infinity, with: [] }, fc); });
    function focusAt(t) { // the strongest window now: {amount, fc}
      var best = { amount: 0, fc: null };
      focuses.forEach(function (fc) {
        var a = seg(t, fc.at, fc.dur, E.inOutSine) * (1 - seg(t, fc.until, fc.out, E.inOutSine));
        if (a > best.amount) best = { amount: a, fc: fc };
      });
      return best;
    }
    function inFocus(fc, id) { return !!fc && (fc.part === id || fc.with.indexOf(id) >= 0); }
    function textHide(t, ids, always) { // how hidden a non-focus text is: 0.2 s ramps at focus in and out
      if (always) return 0;
      var h = 0;
      focuses.forEach(function (fc) {
        if (ids.some(function (id) { return inFocus(fc, id); })) return;
        var a = seg(t, fc.at, TEXT_FADE) * (1 - seg(t, fc.until + fc.out * 0.6, TEXT_FADE));
        h = Math.max(h, a);
      });
      return h;
    }

    /* ---- explode: part offsets keyed in t ---- */
    var explodes = (spec.explode ? (Array.isArray(spec.explode) ? spec.explode : [spec.explode]) : []).map(function (x) { return Object.assign({ dur: 1 }, x); });
    function offsetOf(id, t) {
      var o = [0, 0, 0];
      explodes.forEach(function (x) {
        var v = x.offsets && x.offsets[id]; if (!v) return;
        var p = seg(t, x.at, x.dur, E.inOutCubic) * (x.back != null ? 1 - seg(t, x.back, x.dur, E.inOutCubic) : 1);
        for (var k = 0; k < 3; k++) o[k] += (v[k] || 0) * p;
      });
      return o;
    }

    /* ---- depth: a topological sort of the solids and pipes ---- */
    var BACK = { 'x-': 1, 'y-': 1, bottom: 1 }, cycleMsg = null;
    function sortDepth() {
      var list = items.filter(function (it) { return it.layer !== 'floor' && it.layer !== 'front' && it.kind !== 'floortext' && it.kind !== 'air'; });
      var n = list.length, idx = new Map(), edges = list.map(function () { return []; }), indeg = list.map(function () { return 0; }), eps = 0.05;
      list.forEach(function (it, i) { idx.set(it, i); });
      var addEdge = function (a, b) { if (a === b || a == null || b == null) return; if (edges[a].indexOf(b) >= 0) return; edges[a].push(b); indeg[b]++; };
      var behind = function (A, B) { // A entirely on the far side of B along some axis (the viewer is at +x +y +z)
        if (!A.bbox || !B.bbox) return false;
        for (var k = 0; k < 3; k++) if (A.bbox[1][k] <= B.bbox[0][k] + eps) return true;
        return false;
      };
      for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) {
        if (i === j) continue;
        var A = list[i], B = list[j];
        if (behind(A, B) && !behind(B, A)) addEdge(i, j);
      }
      list.forEach(function (it, i) { // pipes on a part's back face go behind it, on a front face in front of it
        var pp = pipes[it.id]; if (!pp) return;
        [pp.from, pp.to].forEach(function (end) {
          if (!end || !end.part || !idx.has(end.part)) return;
          var j = idx.get(end.part);
          if (BACK[end.face]) { removeEdge(j, i); addEdge(i, j); } else if (end.face) { removeEdge(i, j); addEdge(j, i); }
        });
      });
      list.forEach(function (it, i) { // explicit escape hatches
        (it.behind || []).forEach(function (id) { if (byId[id] && idx.has(byId[id])) { removeEdge(idx.get(byId[id]), i); addEdge(i, idx.get(byId[id])); } });
        (it.front || []).forEach(function (id) { if (byId[id] && idx.has(byId[id])) { removeEdge(i, idx.get(byId[id])); addEdge(idx.get(byId[id]), i); } });
      });
      function removeEdge(a, b) { var k = edges[a].indexOf(b); if (k >= 0) { edges[a].splice(k, 1); indeg[b]--; } }
      var key = function (it) { var b = it.bbox; return b ? (b[0][0] + b[1][0] + b[0][1] + b[1][1]) / 2 + (b[0][2] + b[1][2]) / 4 : 0; };
      var out = [], done = list.map(function () { return false; }), cycles = 0;
      while (out.length < n) {
        var pick = -1;
        for (var a = 0; a < n; a++) if (!done[a] && indeg[a] === 0 && (pick < 0 || (list[a].order || 0) < (list[pick].order || 0) || ((list[a].order || 0) === (list[pick].order || 0) && key(list[a]) < key(list[pick]) - 1e-9))) pick = a;
        if (pick < 0) { // a cycle: break it at the farthest remaining item
          cycles++;
          for (var b2 = 0; b2 < n; b2++) if (!done[b2] && (pick < 0 || key(list[b2]) < key(list[pick]))) pick = b2;
        }
        done[pick] = true; out.push(list[pick]);
        edges[pick].forEach(function (b) { indeg[b]--; });
      }
      if (cycles) { cycleMsg = 'depth order has ' + cycles + ' cycle(s) (overlapping parts); give an item behind: [ids] or front: [ids] to settle it'; warn(cycleMsg); }
      return out;
    }
    var sorted = spec.depth === 'list' ? items.filter(function (it) { return it.layer !== 'floor' && it.layer !== 'front' && it.kind !== 'floortext' && it.kind !== 'air'; }) : sortDepth();
    var floorItems = items.filter(function (it) { return it.layer === 'floor' && it.kind !== 'floortext'; });
    var frontItems = items.filter(function (it) { return (it.layer === 'front' || it.kind === 'air') && it.kind !== 'floortext'; });

    /* ---------- drawing (all return SVG strings in zoom-1 screen px) ---------- */
    function poly(a, fill, lw, stroke, extra) {
      return '<polygon points="' + pts(a) + '" fill="' + fill + '" stroke="' + (stroke || L.ink) + '" stroke-width="' + f3(lw) + '" stroke-linejoin="round" ' + (extra || '') + '/>';
    }
    function line(a, lw, stroke, extra) {
      return '<path d="' + dpath(a) + '" fill="none" stroke="' + stroke + '" stroke-width="' + f3(lw) + '" stroke-linecap="round" stroke-linejoin="round" ' + (extra || '') + '/>';
    }
    function faceTone(name) { return (name && L[name]) || L.faces; }
    function glassBox(b, lw, tint) { // a different material: translucent faces, the hidden edges show through
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], x1 = x0 + b.size[0], y1 = y0 + b.size[1], z1 = z0 + b.size[2], G = L.glass, gl = L.glassLine, op = 'fill-opacity="' + L.glassOpacity + '"';
      var m = function (c) { return tint ? mixHex(c, tint.c, tint.p * 0.6) : c; }, s = '';
      s += line([P(x0, y0, z0), P(x1, y0, z0)], lw * 0.7, gl, 'stroke-opacity="0.45"') + line([P(x0, y0, z0), P(x0, y1, z0)], lw * 0.7, gl, 'stroke-opacity="0.45"') + line([P(x0, y0, z0), P(x0, y0, z1)], lw * 0.7, gl, 'stroke-opacity="0.45"');
      var f = poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], m(G.right), lw, gl, op);
      f += poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], m(G.left), lw, gl, op);
      f += poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], m(G.top), lw, gl, op);
      return s + (L.glassGlow ? '<g filter="url(#ld-glowsoft)">' + f + '</g>' : f);
    }
    function box(b, lw, tone, tint) {
      if (b.glass) return glassBox(b, lw, tint);
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], w = b.size[0], d = b.size[1], h = b.size[2], x1 = x0 + w, y1 = y0 + d, z1 = z0 + h;
      var T = faceTone(tone), m = function (c) { return tint ? mixHex(c, tint.c, tint.p) : c; }, s = '';
      s += poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], m(T.right), lw);
      s += poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], m(T.left), lw);
      s += poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], m(T.top), lw);
      if (b.bevel) { var k = b.bevel; s += poly([P(x0 + k, y0 + k, z1), P(x1 - k, y0 + k, z1), P(x1 - k, y1 - k, z1), P(x0 + k, y1 - k, z1)], 'none', lw * 0.6, L.detail); }
      return s;
    }
    function cyl(c, lw, tint) {
      var cx = c.at[0], cy = c.at[1], z0 = c.at[2], r = c.r, h = c.h, rx = 1.2247 * r * S, ry = 0.7071 * r * S;
      var B = P(cx, cy, z0), T = P(cx, cy, z0 + h);
      var body = c.flat ? (tint ? mixHex(L.padFaces.left, tint.c, tint.p) : L.padFaces.left) : 'url(#ld-cyl)';
      var s = '<path d="M' + f1(T[0] - rx) + ' ' + f1(T[1]) + 'L' + f1(B[0] - rx) + ' ' + f1(B[1]) + 'A' + f1(rx) + ' ' + f1(ry) + ' 0 0 0 ' + f1(B[0] + rx) + ' ' + f1(B[1]) + 'L' + f1(T[0] + rx) + ' ' + f1(T[1]) + 'Z" fill="' + body + '" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '" stroke-linejoin="round"/>';
      (c.bands || []).forEach(function (bz) { var Q = P(cx, cy, z0 + bz); s += '<path d="M' + f1(Q[0] - rx) + ' ' + f1(Q[1]) + 'A' + f1(rx) + ' ' + f1(ry) + ' 0 0 0 ' + f1(Q[0] + rx) + ' ' + f1(Q[1]) + '" fill="none" stroke="' + L.detail + '" stroke-width="' + f3(lw * 0.6) + '"/>'; });
      if (c.dome) {
        var dh = c.dome * S;
        s += '<path d="M' + f1(T[0] - rx) + ' ' + f1(T[1]) + 'A' + f1(rx) + ' ' + f1(dh + ry * 0.2) + ' 0 0 1 ' + f1(T[0] + rx) + ' ' + f1(T[1]) + 'A' + f1(rx) + ' ' + f1(ry) + ' 0 0 1 ' + f1(T[0] - rx) + ' ' + f1(T[1]) + 'Z" fill="url(#ld-dome)" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '" stroke-linejoin="round"/>';
        s += '<path d="M' + f1(T[0] - rx) + ' ' + f1(T[1]) + 'A' + f1(rx) + ' ' + f1(ry) + ' 0 0 0 ' + f1(T[0] + rx) + ' ' + f1(T[1]) + '" fill="none" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '"/>';
      } else {
        var top = tint ? mixHex(c.flat ? L.padFaces.top : L.faces.top, tint.c, tint.p) : (c.flat ? L.padFaces.top : L.faces.top);
        s += '<ellipse cx="' + f1(T[0]) + '" cy="' + f1(T[1]) + '" rx="' + f1(rx) + '" ry="' + f1(ry) + '" fill="' + top + '" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '"/>';
        if (c.cap) s += '<ellipse cx="' + f1(T[0]) + '" cy="' + f1(T[1]) + '" rx="' + f1(rx * c.cap) + '" ry="' + f1(ry * c.cap) + '" fill="none" stroke="' + L.detail + '" stroke-width="' + f3(lw * 0.6) + '"/>';
      }
      return s;
    }
    function ball(b, lw, tint) {
      var q = P(b.at[0], b.at[1], b.at[2]), lit = b.lamp && tint, fill = lit ? (tint.p >= 0.999 ? tint.c : mixHex(L.faces.top, tint.c, tint.p)) : 'url(#ld-dome)';
      var glow = lit && L.tokenStyle === 'bead' ? ' filter="url(#ld-glow)"' : '';
      return '<circle cx="' + f1(q[0]) + '" cy="' + f1(q[1]) + '" r="' + f1(b.r * S * 1.12) + '" fill="' + fill + '" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '"' + glow + '/>';
    }
    function gable(b, lw) { // a pitched roof, ridge along x: back slope, front slope, gable end
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], w = b.size[0], d = b.size[1], h = b.size[2], ym = y0 + d / 2, o = 0.35, R = L.roofFaces, s = '';
      s += poly([P(x0 - o, y0 - o, z0 - o * 0.6), P(x1(), y0 - o, z0 - o * 0.6), P(x1(), ym, z0 + h), P(x0 - o, ym, z0 + h)], R.top, lw);
      s += poly([P(x0 - o, y0 + d + o, z0 - o * 0.6), P(x1(), y0 + d + o, z0 - o * 0.6), P(x1(), ym, z0 + h), P(x0 - o, ym, z0 + h)], R.left, lw);
      s += poly([P(x0 + w, y0, z0), P(x0 + w, y0 + d, z0), P(x0 + w, ym, z0 + h)], R.right, lw);
      function x1() { return x0 + w + o; }
      return s;
    }
    function saw(b, lw) { // a sawtooth (factory) roof along x
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], w = b.size[0], d = b.size[1], h = b.size[2], n = b.n || 3, s = '';
      for (var i = 0; i < n; i++) {
        var a = x0 + (w / n) * i, c = a + w / n;
        s += poly([P(a, y0, z0), P(a, y0 + d, z0), P(c, y0 + d, z0 + h), P(c, y0, z0 + h)], L.roofFaces.top, lw);
        s += poly([P(c, y0, z0 + h), P(c, y0 + d, z0 + h), P(c, y0 + d, z0), P(c, y0, z0)], L.roofFaces.right, lw);
        s += poly([P(a, y0 + d, z0), P(c, y0 + d, z0 + h), P(c, y0 + d, z0)], L.roofFaces.left, lw);
      }
      return s;
    }
    function tray(b, t, lw) { // an open store: walls, the inner floor, a level of its tone
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], w = b.size[0], d = b.size[1], h = b.size[2], k = 0.7, s = box(b, lw, 'padFaces');
      s += poly([P(x0 + k, y0 + k, z0 + h), P(x0 + w - k, y0 + k, z0 + h), P(x0 + w - k, y0 + d - k, z0 + h), P(x0 + k, y0 + d - k, z0 + h)], L.faces.deep, lw * 0.7);
      var lv = keyed(b.fill, t, 0);
      if (lv > 0.001) {
        var tn = toneOf(L, b.tone), zl = z0 + h - 0.05, y1 = y0 + d - k, x1 = x0 + w - k, zz = z0 + 0.4 + (h - 0.6) * lv;
        s += poly([P(x0 + k, y1, zl), P(x1, y1, zl), P(x1, y1, zz), P(x0 + k, y1, zz)], mixHex(tn.tint, L.ground, 0.15), lw * 0.5, tn.flow, 'stroke-opacity="0.6"');
        s += poly([P(x0 + k, y0 + k, zz), P(x1, y0 + k, zz), P(x1, y1, zz), P(x0 + k, y1, zz)], tn.tint, lw * 0.6, tn.flow);
      }
      return s;
    }
    function keyed(keys, t, dflt) { // [[t, v], ...] -> v at t, eased between keys
      if (!keys || !keys.length) return dflt;
      if (typeof keys === 'number') return keys;
      if (t <= keys[0][0]) return keys[0][1];
      for (var i = 1; i < keys.length; i++) if (t < keys[i][0]) return lerp(keys[i - 1][1], keys[i][1], E.inOutSine((t - keys[i - 1][0]) / (keys[i][0] - keys[i - 1][0])));
      return keys[keys.length - 1][1];
    }
    function faceP(f, u, v) { return f.face === 'y+' ? P(f.c[0] + u, f.plane, f.c[1] + v) : P(f.plane, f.c[0] - u, f.c[1] + v); }
    function ring(f, R, n) { var a = []; n = n || 56; for (var i = 0; i <= n; i++) { var th = (i / n) * Math.PI * 2; a.push(faceP(f, R * Math.cos(th), R * Math.sin(th))); } return a; }
    function fan(f, t, lw) {
      var s = poly(ring(f, f.R + 0.9), L.faces.recess, lw);
      s += poly(ring(f, f.R), L.faces.deep, lw * 0.6, L.detail);
      var spin = typeof f.spin === 'function' ? f.spin(t) : (f.spin && f.spin.at != null ? -Math.pow(seg(t, f.spin.at, 1.6), 2) * 4.4 - Math.max(0, t - f.spin.at - 1.6) * (f.spin.rate || 5.5) : 0);
      for (var k = 0; k < 5; k++) {
        var a0 = spin + (k / 5) * Math.PI * 2, bl = [], i, th, rr;
        for (i = 0; i <= 10; i++) { th = a0 + i * 0.075; rr = lerp(f.R * 0.22, f.R * 0.92, i / 10); bl.push(faceP(f, rr * Math.cos(th), rr * Math.sin(th))); }
        for (i = 10; i >= 0; i--) { th = a0 + 0.52 + i * 0.03; rr = lerp(f.R * 0.22, f.R * 0.88, i / 10); bl.push(faceP(f, rr * Math.cos(th), rr * Math.sin(th))); }
        s += poly(bl, L.faces.blade, lw * 0.6, L.detail);
      }
      s += poly(ring(f, f.R * 0.2, 28), L.faces.top, lw * 0.7);
      for (var g = 1; g <= 3; g++) s += '<path d="' + dpath(ring(f, f.R * g / 3.15)) + '" fill="none" stroke="' + L.ink + '" stroke-opacity="0.55" stroke-width="' + f3(lw * 0.5) + '"/>';
      s += line([faceP(f, -f.R, 0), faceP(f, f.R, 0)], lw * 0.5, L.ink, 'stroke-opacity="0.55"');
      s += line([faceP(f, 0, -f.R), faceP(f, 0, f.R)], lw * 0.5, L.ink, 'stroke-opacity="0.55"');
      return s;
    }
    function fins(f, lw) {
      var s = '';
      for (var u = f.u0; u <= f.u1 + 1e-6; u += f.step) s += line([faceP(f, u, f.v0), faceP(f, u, f.v1)], lw * 0.45, L.detail);
      s += poly([faceP(f, f.u0 - 0.6, f.v0 - 0.6), faceP(f, f.u1 + 0.6, f.v0 - 0.6), faceP(f, f.u1 + 0.6, f.v1 + 0.6), faceP(f, f.u0 - 0.6, f.v1 + 0.6)], 'none', lw * 0.7);
      return s;
    }
    function hatch(b, lw) {
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], w = b.size[0], d = b.size[1], h = b.size[2], z1 = z0 + h, s = '', y, z;
      for (y = y0 + 0.6; y < y0 + d - w; y += 1.1) s += line([P(x0, y, z1), P(x0 + w, y + w, z1)], lw * 0.45, L.hatch);
      if (b.endFace) for (z = 0.6; z < h - w; z += 1.1) s += line([P(x0, y0 + d, z0 + z), P(x0 + w, y0 + d, z0 + z + w)], lw * 0.45, L.hatch);
      return s;
    }
    function ghost(b, lw) {
      var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], x1 = x0 + b.size[0], y1 = y0 + b.size[1], z1 = z0 + b.size[2], da = 'stroke-dasharray="7 6"', s = '';
      s += line([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1), P(x0, y0, z1)], lw * 0.7, L.ghost, da);
      s += line([P(x1, y1, z0), P(x1, y1, z1)], lw * 0.7, L.ghost, da) + line([P(x0, y1, z0), P(x0, y1, z1)], lw * 0.7, L.ghost, da);
      s += line([P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0)], lw * 0.7, L.ghost, da);
      return s;
    }
    function planks(b, lw) { var s = '', x0 = b.at[0], y0 = b.at[1], z = b.at[2]; for (var y = y0 + b.step; y < y0 + b.size[1] - 0.1; y += b.step) s += line([P(x0, y, z), P(x0 + b.size[0], y, z)], lw * 0.4, L.plank); return s; }
    function plate(b, lw) {
      var s = box(b.glass ? b : b, lw, b.faces || 'plateFaces'), x0 = b.at[0], y0 = b.at[1], x1 = x0 + b.size[0], y1 = y0 + b.size[1], z = b.at[2] + b.size[2], x, y, i;
      if (b.grid) {
        var gc = b.glass ? L.glassLine : L.grid, ga = b.glass ? 'stroke-opacity="0.22"' : '';
        for (x = x0 + b.grid; x < x1 - 0.1; x += b.grid) s += line([P(x, y0 + 0.01, z), P(x, y1, z)], lw * 0.4, gc, ga);
        for (y = y0 + b.grid; y < y1 - 0.1; y += b.grid) s += line([P(x0, y, z), P(x1, y, z)], lw * 0.4, gc, ga);
      }
      if (b.ruler) for (x = x0 + 2, i = 1; x < x1 - 1; x += 2, i++) s += line([P(x, y1, b.at[2] + b.size[2] * 0.83), P(x, y1, b.at[2] + b.size[2] * (i % 5 === 0 ? 0.2 : 0.5))], lw * 0.45, L.detail);
      return s;
    }
    function ringShape(sh, t, lw) { // a state ring on the floor around a node (matched, active, chosen)
      var a = seg(t, sh.from, sh.dur || 0.5, E.outCubic) * (sh.until != null ? 1 - seg(t, sh.until, 0.4) : 1); if (a <= 0) return '';
      var q = P(sh.at[0], sh.at[1], sh.at[2] || 0), r = sh.r * (0.85 + 0.15 * a), tn = toneOf(L, sh.tone || 'warm');
      return '<ellipse cx="' + f1(q[0]) + '" cy="' + f1(q[1]) + '" rx="' + f1(1.2247 * r * S) + '" ry="' + f1(0.7071 * r * S) + '" fill="' + tn.tint + '" fill-opacity="' + f3(0.55 * a) + '" stroke="' + tn.flow + '" stroke-width="' + f3(lw * 1.6) + '" stroke-opacity="' + f3(a) + '"/>';
    }
    function shapeSVG(sh, t, lw, tint) {
      switch (sh.kind) {
        case 'box': return box(sh, lw, sh.tone, tint);
        case 'cyl': return cyl(sh, lw, tint);
        case 'ball': return ball(sh, lw, tint);
        case 'gable': return gable(sh, lw);
        case 'saw': return saw(sh, lw);
        case 'tray': return tray(sh, t, lw);
        case 'fan': return fan(sh, t, lw);
        case 'fins': return fins(sh, lw);
        case 'hatch': return hatch(sh, lw);
        case 'plate': return plate(sh, lw);
        case 'ghost': return ghost(sh, lw);
        case 'ring': return ringShape(sh, t, lw);
        case 'cell': { // one cell of a stack: shown once the keyed count reaches it, dropping in over 0.35 s
          // the count is a step function of t: a cell shows while the latest key at or before t is above it, and it
          // drops in from the key that started that run (a count that goes down takes cells away; it comes back
          // with the next key above it)
          var when = null, ks = sh.count || [];
          for (var ci = 0; ci < ks.length && ks[ci][0] <= t; ci++) { if (ks[ci][1] > sh.i) { if (when == null) when = ks[ci][0]; } else when = null; }
          if (when == null) return '';
          var pc = seg(t, when + sh.i * 0.05, 0.35, E.outCubic), dz = (1 - pc) * 2.5 * S, tnc = toneOf(L, sh.tone || 'cold');
          var fresh = 1 - seg(t, when + 0.35, 0.8);
          return '<g transform="translate(0 ' + f1(-dz) + ')" opacity="' + f3(clamp(pc * 1.6, 0, 1)) + '">' + box(sh, lw, null, { c: tnc.flow, p: 0.12 + 0.35 * fresh }) + '</g>';
        }
        case 'bloom': {
          var a = seg(t, sh.from, sh.dur, E.inOutSine) * (L.bloomOpacity || 0.3); if (a <= 0) return '';
          var q = P(sh.at[0], sh.at[1], sh.at[2]), r = sh.r * (0.7 + 0.3 * a / (L.bloomOpacity || 0.3));
          return '<ellipse cx="' + f1(q[0]) + '" cy="' + f1(q[1]) + '" rx="' + f1(1.2247 * r * S) + '" ry="' + f1(0.7071 * r * S) + '" fill="url(#ld-bloom)" opacity="' + f3(a) + '"/>';
        }
        case 'planks': return planks(sh, lw);
        case 'face': return poly(sh.pts.map(function (p) { return P(p[0], p[1], p[2]); }), sh.tone === 'flag' ? toneOf(L, 'hot').flow : (L.faces[sh.tone || 'top'] || L.faces.top), lw * (sh.lw || 1), sh.stroke ? (L[sh.stroke] || 'none') : L.ink);
        case 'line': return line(sh.pts.map(function (p) { return P(p[0], p[1], p[2]); }), lw * (sh.lw || 0.6), L[sh.stroke || 'detail']);
        case 'bolt': { var b = P(sh.at[0], sh.at[1], sh.at[2]); return '<circle cx="' + f1(b[0]) + '" cy="' + f1(b[1]) + '" r="2.6" fill="' + L.faces.top + '" stroke="' + L.detail + '" stroke-width="' + f3(lw * 0.6) + '"/>'; }
        default: return '';
      }
    }
    function shadowSVG(fp, p, z) { // on the ground the part stands on (z: its base)
      var x0 = fp[0], y0 = fp[1], w = fp[2], d = fp[3], k = 1.4; z = z || 0;
      var a = [P(x0 + k, y0 + k, z), P(x0 + w + k * 2, y0 + k, z), P(x0 + w + k * 2, y0 + d + k * 2, z), P(x0 + k, y0 + d + k * 2, z)];
      return '<polygon points="' + pts(a) + '" fill="' + L.shadow + '" opacity="' + f3(p) + '" filter="url(#ld-soft)"/>';
    }

    function pipeSVG(pp, t, lw) {
      var it = pp.it, bd = it.build || [0, 0.4], b = Array.isArray(bd) ? seg(t, bd[0], bd[1], E.inOutSine) : seg(t, bd, 0.4, E.inOutSine);
      if (b <= 0) return '';
      var isLink = it.kind === 'link', w = it.w || (isLink ? 4 : 11);
      var start = it.tintAt != null ? it.tintAt : (flowOn[it.id] ? Math.min.apply(null, flowOn[it.id].map(function (x) { return x.f.at; })) : null);
      var tn = toneAt(it.id, t, it.tone || it.temp || null, (it.tone || it.temp) ? start : null);
      var a = trimmed(pp, 0, pp.len * b), d = dpath(a), s = '', collars = '';
      if (isLink) {
        var lc = tn.to ? tintOf(tn, 'flow', L.detail) : (L[it.stroke] || L.detail);
        var dash = it.dash ? ' stroke-dasharray="' + String(it.dash).replace(/[^0-9., ]/g, '') + '"' : '';
        s += '<path d="' + d + '" fill="none" stroke="' + lc + '" stroke-width="' + f3(w * (tn.to ? lerp(1, 1.5, tn.p) : 1)) + '" stroke-linecap="round" stroke-linejoin="round"' + dash + (it.opacity != null ? ' opacity="' + f3(Number(it.opacity) || 0) + '"' : '') + '/>';
      } else {
        var tint = tintOf(tn, 'tint', L.pipe.body);
        s += '<path d="' + d + '" fill="none" stroke="' + L.ink + '" stroke-width="' + f3(w + 2 * lw) + '" stroke-linecap="round" stroke-linejoin="round"/>';
        s += '<path d="' + d + '" fill="none" stroke="' + tint + '" stroke-width="' + w + '" stroke-linecap="round" stroke-linejoin="round"/>';
        (it.ends || []).forEach(function (e) {
          if (e === 'end' && b < 1) return;
          var s0 = e === 'start' ? 0 : pp.len - 9, q0 = atLen(pp, s0), q1 = atLen(pp, s0 + 9), cd = 'M' + f1(q0.x) + ' ' + f1(q0.y) + 'L' + f1(q1.x) + ' ' + f1(q1.y);
          collars += '<path d="' + cd + '" stroke="' + L.ink + '" stroke-width="' + f3(w + 7 + 2 * lw) + '" fill="none"/><path d="' + cd + '" stroke="' + (L.pipe.collar || L.faces.top) + '" stroke-width="' + f3(w + 7) + '" fill="none"/>';
        });
        if (L.pipe.sheen) s += '<path d="' + d + '" fill="none" stroke="' + L.pipe.sheen + '" stroke-width="' + f1(w * 0.22) + '" stroke-linecap="round" stroke-linejoin="round" transform="translate(0 ' + f1(-w * 0.2) + ')"/>';
      }
      (flowOn[it.id] || []).forEach(function (on) { s += particles(on.f, on.s, pp, t, b, w, tn, isLink ? lc : null); });
      return s + collars;
    }
    function particles(F, sg, pp, t, b, w, tn, line) {
      var fo = seg(t, F.at, 0.5) * (F.until != null ? 1 - seg(t, F.until, 0.5) : 1); if (fo <= 0) return '';
      var col = sg.tone ? toneOf(L, sg.tone).flow : tintOf(tn, 'flow', L.detail), out = '', n = Math.max(1, Math.floor(F.len / F.spacing)), bead = L.flowStyle === 'bead';
      // dashes the colour of the link under them would not show: they become gaps that travel along it
      if (line && !bead && String(col).toLowerCase() === String(line).toLowerCase()) col = (L.pipe && L.pipe.body) || L.ground;
      var tf = (t - F.at) * F.speed + F.speed * 20; // phase from the flow's own start (so retiming it keeps the look)
      for (var k = 0; k < n; k++) {
        var s = (((k * F.spacing + tf) % F.len) + F.len) % F.len - sg.s0;
        if (s < 0 || s > pp.len * b) continue;
        var q = atLen(pp, s), edge = Math.min(1, s / 18, (pp.len - s) / 18), deg = (q.ang * 180) / Math.PI, lp = F.dash, hw = Math.max(2, w * 0.21);
        out += '<rect x="' + f1(-lp / 2) + '" y="' + f1(-hw) + '" width="' + lp + '" height="' + f1(hw * 2) + '" rx="' + f1(hw) + '" transform="translate(' + f1(q.x) + ' ' + f1(q.y) + ') rotate(' + f1(deg) + ')" fill="' + col + '" opacity="' + f3(Math.max(0, edge)) + '"/>';
      }
      return '<g opacity="' + f3(fo) + '"' + (bead ? ' filter="url(#ld-glow)"' : '') + '>' + out + '</g>';
    }
    function airSVG(it, t, lw) {
      var o = seg(t, it.at, 0.6) * (it.until != null ? 1 - seg(t, it.until, 0.5) : 1); if (o <= 0) return '';
      var tn = toneOf(L, it.tone || it.temp), s = '';
      it.lines.forEach(function (ln, i) {
        var a = [];
        for (var k = 0; k <= 30; k++) { var q = k / 30, p = ln.map(function (v) { return lerp(v[0], v[1], q); }), wob = Math.sin(q * Math.PI * 2 * (it.waves || 1) + i * 1.7) * (it.amp || 0.5); a.push(P(p[0] + wob * it.wob[0], p[1] + wob * it.wob[1], p[2])); }
        var off = -(t * it.speed + i * 23) % 52;
        s += line(a, lw * 1.25, tn.air, 'stroke-dasharray="' + (it.dash || '30 22') + '" stroke-dashoffset="' + f1(off) + '"');
        var e = a[a.length - 1], pr = a[a.length - 3], ang = Math.atan2(e[1] - pr[1], e[0] - pr[0]), hl = 11;
        s += line([[e[0] - hl * Math.cos(ang - 0.5), e[1] - hl * Math.sin(ang - 0.5)], e, [e[0] - hl * Math.cos(ang + 0.5), e[1] - hl * Math.sin(ang + 0.5)]], lw * 1.2, tn.air);
      });
      return '<g opacity="' + f3(o * (L.airOpacity || 1)) + '">' + s + '</g>';
    }

    /* ---------- tokens: discrete things moving between nodes (offers, money, goods, signals) ---------- */
    var tokens = (spec.tokens || []).map(function (tk, i) { return Object.assign({ id: 'tok' + i, tone: 'cold', r: 1.3 }, tk); });
    var tokById = {}; tokens.forEach(function (tk) { tokById[tk.id] = tk; });
    function tokenAt(tk, t) { // -> {pos:[x,y,z], tone, o} or null (closed form: the last move that started wins)
      if (tk.routes) { // live: the route that started last at or before t
        var rt = null; for (var ri = 0; ri < tk.routes.length && tk.routes[ri].start <= t; ri++) rt = tk.routes[ri];
        if (!rt || !rt.moves.length) return null;
        tk = { moves: rt.moves, until: rt.until, tone: tk.tone, tones: tk.tones, from: tk.from };
      }
      var moves = tk.moves || [], pos = tk.from ? (Array.isArray(tk.from) ? tk.from : portOf(tk.from).at) : null, show = tk.at != null ? tk.at : (moves[0] ? moves[0].at : 0);
      if (t < show) return null;
      for (var i = 0; i < moves.length; i++) {
        var mv = moves[i]; if (t < mv.at) break;
        var p = seg(t, mv.at, mv.dur || 0.8, E.inOutCubic);
        if (mv.along) {
          var pp = pipes[mv.along]; if (!pp) continue;
          var f = mv.reverse ? 1 - p * (mv.span == null ? 1 : mv.span) : p * (mv.span == null ? 1 : mv.span);
          if (mv.bounce) f = (mv.reverse ? 1 : 0) + (mv.reverse ? -1 : 1) * mv.bounce * Math.sin(Math.PI * p);
          var q = atLen(pp, clamp(f, 0, 1) * pp.len); pos = addOff(q.w3, mv.off);
        } else if (mv.to) {
          var dst = addOff(Array.isArray(mv.to) ? mv.to : portOf(mv.to).at, mv.off), src = mv.from ? portOf(mv.from).at : (prevEnd(tk, i) || dst), lift = mv.hop || 0;
          pos = [0, 1, 2].map(function (k) { return lerp(src[k], dst[k], p); }); pos[2] += Math.sin(Math.PI * p) * lift;
        }
      }
      var tone = tk.tone;
      (tk.tones || []).forEach(function (x) { if (t >= x.at) tone = x.tone; });
      var o = seg(t, show, 0.25) * (tk.until != null ? 1 - seg(t, tk.until, 0.3) : 1);
      return pos && o > 0 ? { pos: pos, tone: tone, o: o } : null;
    }
    function addOff(p, o) { return o ? [p[0] + (o[0] || 0), p[1] + (o[1] || 0), p[2] + (o[2] || 0)] : p; }
    function prevEnd(tk, i) {
      for (var j = i - 1; j >= 0; j--) {
        var mv = tk.moves[j];
        if (mv.to) return addOff(Array.isArray(mv.to) ? mv.to : portOf(mv.to).at, mv.off);
        if (mv.along) { var pp = pipes[mv.along]; if (pp) return addOff(pp.p3[mv.reverse ? 0 : pp.p3.length - 1], mv.off); }
      }
      return tk.from ? (Array.isArray(tk.from) ? tk.from : portOf(tk.from).at) : null;
    }
    function tokenSVG(tk, st, lw) {
      var tn = toneOf(L, st.tone), r = tk.r, q = P(st.pos[0], st.pos[1], st.pos[2]), s = '';
      if (tk.shape === 'chip' || tk.shape === 'envelope') {
        var sz = tk.size || [3.2, 2.2, 0.55], b = { at: [st.pos[0] - sz[0] / 2, st.pos[1] - sz[1] / 2, st.pos[2]], size: sz };
        var faces = { top: mixHex(tn.flow, L.name === 'dark' ? '#000000' : '#FFFFFF', L.name === 'dark' ? 0.15 : 0.55), left: mixHex(tn.flow, '#000000', 0.08), right: mixHex(tn.flow, '#000000', 0.22) };
        var x0 = b.at[0], y0 = b.at[1], z0 = b.at[2], x1 = x0 + sz[0], y1 = y0 + sz[1], z1 = z0 + sz[2];
        s += poly([P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)], faces.right, lw);
        s += poly([P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)], faces.left, lw);
        s += poly([P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)], faces.top, lw);
        if (tk.shape === 'envelope') s += line([P(x0, y0, z1), P((x0 + x1) / 2, (y0 + y1) / 2, z1), P(x0, y1, z1)], lw * 0.8, L.ink);
        else s += line([P(x0 + sz[0] * 0.25, (y0 + y1) / 2, z1), P(x1 - sz[0] * 0.25, (y0 + y1) / 2, z1)], lw * 0.8, tn.flow);
        return '<g opacity="' + f3(st.o) + '"' + (L.tokenStyle === 'bead' ? ' filter="url(#ld-glowsoft)"' : '') + '>' + s + '</g>';
      }
      if (L.tokenStyle === 'bead') {
        s += '<g filter="url(#ld-glow)"><ellipse cx="' + f1(q[0]) + '" cy="' + f1(q[1] - 2) + '" rx="' + f1(1.2247 * r * S) + '" ry="' + f1(0.7071 * r * S) + '" fill="' + tn.flow + '"/></g>';
      } else { // a puck: side band, top ellipse, ink outline
        var rx = 1.2247 * r * S, ry = 0.7071 * r * S, h = 0.7 * S, top = q[1] - h;
        s += '<path d="M' + f1(q[0] - rx) + ' ' + f1(top) + 'L' + f1(q[0] - rx) + ' ' + f1(q[1]) + 'A' + f1(rx) + ' ' + f1(ry) + ' 0 0 0 ' + f1(q[0] + rx) + ' ' + f1(q[1]) + 'L' + f1(q[0] + rx) + ' ' + f1(top) + 'Z" fill="' + tn.flow + '" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '"/>';
        s += '<ellipse cx="' + f1(q[0]) + '" cy="' + f1(top) + '" rx="' + f1(rx) + '" ry="' + f1(ry) + '" fill="' + mixHex(tn.flow, '#FFFFFF', 0.35) + '" stroke="' + L.ink + '" stroke-width="' + f3(lw) + '"/>';
      }
      return '<g opacity="' + f3(st.o) + '">' + s + '</g>';
    }

    /* ---------- camera ---------- */
    function focusPoint(fc) {
      if (Array.isArray(fc)) return fc.length === 3 ? P(fc[0], fc[1], fc[2]) : fc;
      var p = byId[fc]; return p && p.anchor ? P(p.anchor[0], p.anchor[1], p.anchor[2]) : [W / 2, H / 2];
    }
    function camera(t) {
      var z = 1, fx = W / 2, fy = H / 2, tx = W / 2, ty = H / 2, moving = false;
      (spec.camera || []).forEach(function (k) {
        var p = seg(t, k.at, k.dur || 1.2, E.inOutCubic); if (p <= 0) return;
        if (p < 1) moving = true;
        var fp = k.focus != null ? focusPoint(k.focus) : [W / 2, H / 2], to = k.to || [W / 2, H / 2];
        z = Math.exp(lerp(Math.log(z), Math.log(k.zoom || 1), p)); fx = lerp(fx, fp[0], p); fy = lerp(fy, fp[1], p); tx = lerp(tx, to[0], p); ty = lerp(ty, to[1], p);
      });
      var ex = tx - fx * z, ey = ty - fy * z;
      if (!moving) { ex = Math.round(ex); ey = Math.round(ey); } // at rest: whole pixels, no shimmer
      return { z: z, ex: ex, ey: ey, map: function (q) { return [ex + q[0] * z, ey + q[1] * z]; } };
    }
    var zMin = (spec.camera || []).reduce(function (m, k) { return Math.min(m, k.zoom || 1); }, 1);

    /* ---------- DOM ---------- */
    var host = typeof opts.host === 'string' || spec.host ? document.querySelector(opts.host || spec.host) : (opts.host || document.querySelector('#ld'));
    if (!host) { warn('no host element (#ld) on the page'); return null; }
    var stage = host.closest('.ld-stage') || host.parentElement;
    var NS = 'http://www.w3.org/2000/svg';
    host.innerHTML = '<svg xmlns="' + NS + '" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">' +
      '<defs>' +
      '<linearGradient id="ld-cyl" x1="0" x2="1" y1="0" y2="0">' + L.cylStops + '</linearGradient>' +
      '<radialGradient id="ld-dome" cx="0.38" cy="0.35" r="0.85">' + L.domeStops + '</radialGradient>' +
      '<filter id="ld-soft" x="-20%" y="-40%" width="140%" height="180%"><feGaussianBlur stdDeviation="' + (L.shadowBlur || 9) + '"/></filter>' +
      '<filter id="ld-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>' +
      '<filter id="ld-glowsoft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>' +
      '<clipPath id="ld-clip"><rect x="' + clip[0] + '" y="' + clip[1] + '" width="' + clip[2] + '" height="' + clip[3] + '" rx="4"/></clipPath>' +
      '<linearGradient id="ld-band-t" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="' + L.veil + '" stop-opacity="1"/><stop offset="0.62" stop-color="' + L.veil + '" stop-opacity="0.9"/><stop offset="1" stop-color="' + L.veil + '" stop-opacity="0"/></linearGradient>' +
      '<linearGradient id="ld-band-b" x1="0" x2="0" y1="1" y2="0"><stop offset="0" stop-color="' + L.veil + '" stop-opacity="1"/><stop offset="0.5" stop-color="' + L.veil + '" stop-opacity="0.92"/><stop offset="1" stop-color="' + L.veil + '" stop-opacity="0"/></linearGradient>' +
      '<radialGradient id="ld-bloom"><stop offset="0" stop-color="' + L.bloom + '" stop-opacity="1"/><stop offset="0.55" stop-color="' + L.bloom + '" stop-opacity="0.45"/><stop offset="1" stop-color="' + L.bloom + '" stop-opacity="0"/></radialGradient>' +
      // the footers' mask: plates and floors (only) fade out under the page's footer lines, so a plate edge never cuts
      // their text; parts, packets, tags and text are never masked (filled in at mount from the footers' boxes)
      '<filter id="ld-feather" filterUnits="userSpaceOnUse" x="0" y="0" width="' + W + '" height="' + H + '"><feGaussianBlur stdDeviation="7"/></filter>' +
      '<mask id="ld-footmask" maskUnits="userSpaceOnUse" maskContentUnits="userSpaceOnUse" x="0" y="0" width="' + W + '" height="' + H + '">' +
      '<rect x="0" y="0" width="' + W + '" height="' + H + '" fill="#fff"/><g id="ld-footholes" filter="url(#ld-feather)"></g></mask>' +
      '</defs><g clip-path="url(#ld-clip)"><g id="ld-floormask"><g id="ld-floorcam"><g id="ld-floor"></g></g></g>' +
      '<g id="ld-world"><g id="ld-wtext"></g><g id="ld-draw"></g></g></g><g id="ld-bands"></g><g id="ld-over"></g></svg>';
    var gWorld = host.querySelector('#ld-world'), gFloor = host.querySelector('#ld-floor'), gDraw = host.querySelector('#ld-draw');
    var gFloorCam = host.querySelector('#ld-floorcam'), gFloorMask = host.querySelector('#ld-floormask'), gHoles = host.querySelector('#ld-footholes');
    var gWText = host.querySelector('#ld-wtext'), gBands = host.querySelector('#ld-bands'), gOver = host.querySelector('#ld-over');
    var mk = function (tag, attrs, parent) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };

    // floor text: persistent nodes set in the floor plane, at least the readable minimum on screen
    var floorMin = Math.ceil(MIN_TEXT_PX / (0.7071 * Math.max(0.2, zMin)));
    var floorTexts = items.filter(function (it) { return it.kind === 'floortext'; }).map(function (it) {
      var size = it.size || 36;
      if (size < floorMin) { warn('floor text "' + it.text + '" raised from ' + size + ' to ' + floorMin + ' (it shows at ' + Math.round(size * 0.7071 * zMin) + ' px; readable text needs ' + MIN_TEXT_PX + ')'); size = floorMin; }
      var p = P(it.at[0], it.at[1], it.at[2] || 0), m = it.dir === 'y' ? [C, -0.5, C, 0.5] : [C, 0.5, -C, 0.5];
      var e = mk('text', { transform: 'matrix(' + m.map(f3).join(' ') + ' ' + f1(p[0]) + ' ' + f1(p[1]) + ')', 'font-family': L.font.mono, 'font-size': size, 'font-weight': 500, 'letter-spacing': 2.5, fill: L.floorInk, opacity: 0, visibility: 'hidden' }, gWText);
      e.textContent = it.text;
      return { it: it, el: e, m: m, size: size, len: it.text.length * size * 0.62 };
    });

    // labels and tags: built once, measured once after fonts load, placed by the layout pass
    var labels = (spec.labels || []).filter(function (lb) { return lb.anchor || byId[lb.for]; }).map(function (lb, i) {
      var g = mk('g', { 'data-ld-label': lb.id || lb.for || String(i) }, gOver);
      var plate = mk('rect', { rx: 6, fill: L.labelPlate, opacity: 0 }, g);
      var lead = mk('path', { fill: 'none', stroke: L.leader, 'stroke-width': L.leaderW, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, g);
      var dot = mk('circle', { r: 5, fill: L.dotFill, stroke: L.leader, 'stroke-width': L.leaderW }, g);
      var tt = mk('text', { 'font-family': L.font.label, 'font-size': L.size.label, 'font-weight': L.weight.label, fill: L.labelInk, 'letter-spacing': L.track.label }, g);
      tt.textContent = lb.title;
      var sub = mk('text', { 'font-family': L.font.sub, 'font-size': L.size.sub, 'font-weight': 450, fill: L.subInk }, g);
      sub.textContent = lb.sub || '';
      return { lb: lb, g: g, plate: plate, lead: lead, dot: dot, tt: tt, sub: sub, w: 0, ids: [lb.for].concat(lb.with || []).filter(Boolean) };
    });
    var tags = (spec.tags || []).map(function (tg, i) {
      var g = mk('g', { 'data-ld-tag': tg.id || String(i) }, gOver), tn = toneOf(L, tg.tone || tg.temp);
      var outline = L.tagStyle === 'outline';
      var r = mk('rect', { rx: 19, fill: tn.tag, stroke: outline ? tn.tagInk : 'none', 'stroke-width': 2 }, g);
      var keys = tg.keys || [[tg.at, tg.text]], fs = Math.max(L.size.tag, tg.size || 0), clip = null, caret = null;
      if (tg.type) { var cp = mk('clipPath', { id: 'ld-type-' + i }, g); clip = mk('rect', { x: 0, y: 0, width: 0, height: 0 }, cp); }
      var tx = keys.map(function (k) { // one persistent text per value: a value change is a new reading, never a rebuilt node
        var e = mk('text', { 'font-family': L.font.mono, 'font-size': fs, 'font-weight': 600, fill: (k[2] ? toneOf(L, k[2]) : tn).tagInk, 'text-anchor': tg.type ? 'start' : 'middle', opacity: 0 }, g);
        if (tg.type) e.setAttribute('clip-path', 'url(#ld-type-' + i + ')');
        e.textContent = k[1]; return e;
      });
      if (tg.type) caret = mk('rect', { fill: tn.tagInk, opacity: 0 }, g);
      return { tg: tg, g: g, r: r, tx: tx, keys: keys, ws: [], fs: fs, h: Math.max(38, Math.round(fs * 1.55)), clip: clip, caret: caret, ids: [tg.for || tg.pipe].filter(Boolean) };
    });
    var lay = { done: false };
    var report = { theme: L.name, order: sorted.map(function (it) { return it.id || ('#' + it._i); }), labels: [], warnings: problems.concat(cycleMsg ? [cycleMsg] : []) };

    var ready = (async function () {
      try { await document.fonts.ready; } catch (e) { /* fonts optional in a bare test page */ }
      fitStage();
      labels.forEach(function (l) { l.w = Math.max(l.tt.getComputedTextLength(), l.sub.getComputedTextLength()); });
      tags.forEach(function (g) { g.ws = g.tx.map(function (e) { return e.getComputedTextLength(); }); });
      floorTexts.forEach(function (ft) { try { ft.len = ft.el.getComputedTextLength(); } catch (e) { /* keep the estimate */ } });
      footerMask();
      layout();
      audit();
      lay.done = true;
    })();
    if (root.ST && ST.waitFor) ST.waitFor(ready, 'living diagram: fonts and label layout');

    function fitStage() { // the design is 1920x1080: scale the stage to the page size
      if (!stage || !stage.style) return;
      var dk = document.querySelector('.ld-dek'), st = document.querySelector('.ld-steps');
      if (dk && st && !(spec.page && spec.page.steps && spec.page.steps.at) && String(dk.textContent || '').trim()) {
        var bottom = dk.offsetTop + dk.offsetHeight + 30;
        if (st.offsetTop < bottom) st.style.top = bottom + 'px';
      }
      var k = (root.innerWidth || W) / W;
      if (Math.abs(k - 1) > 1e-3) { stage.style.transformOrigin = '0 0'; stage.style.transform = 'scale(' + k + ')'; }
      lay.k = k;
    }

    /* ---------- the label layout pass: candidates around each anchor, scored on what they cover ---------- */
    function figure(pose) { // the floor pieces (plate, floors) as screen hulls: labels prefer the empty page
      return floorItems.filter(function (it) { return it.bbox && it.kind !== 'link'; }).map(function (it) {
        var lo = it.bbox[0], hi = it.bbox[1], c = [];
        for (var a = 0; a < 8; a++) c.push(pose.cam.map(P((a & 1 ? hi : lo)[0], (a & 2 ? hi : lo)[1], (a & 4 ? hi : lo)[2])));
        return { poly: hull(c) };
      });
    }
    function segsCross(p1, p2, p3, p4) {
      var d = function (a, b, c) { return (c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0]); };
      var d1 = d(p3, p4, p1), d2 = d(p3, p4, p2), d3 = d(p1, p2, p3), d4 = d(p1, p2, p4);
      return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
    }
    function avoidRects() {
      var sel = spec.avoid || '.ld-avoid, [data-ld-avoid], .ld-title, .ld-dek, .ld-kicker, .ld-figno, .ld-foot, .ld-steps';
      var k = lay.k || 1, out = [];
      var base = stage && stage.getBoundingClientRect ? stage.getBoundingClientRect() : { left: 0, top: 0 };
      document.querySelectorAll(sel).forEach(function (el) {
        var r = el.getBoundingClientRect(); if (!r.width || !r.height || !String(el.textContent || '').trim()) return;
        var name = el.className && typeof el.className === 'string' ? el.className.split(' ')[0] : el.tagName.toLowerCase();
        if (el.classList.contains('ld-steps')) { // the step line area: the box its widest step takes
          r = { left: r.left, top: r.top, width: Math.max(r.width, 10), height: Math.max(r.height, 10) };
        }
        out.push({ x: (r.left - base.left) / k - 8, y: (r.top - base.top) / k - 8, w: r.width / k + 16, h: r.height / k + 16, name: name });
      });
      return out;
    }
    function partHulls(cam, t) {
      return sorted.concat(floorItems.filter(function (it) { return it.kind !== 'link' && it.part && it.part !== 'plate' && it.part !== 'floor'; })).filter(function (it) {
        return it.bbox && it.kind !== 'pipe' && it.kind !== 'link' && (it.build == null || it.build <= t);
      }).map(function (it) {
        var lo = it.bbox[0], hi = it.bbox[1], off = offsetOf(it.id, t), c = [];
        for (var a = 0; a < 8; a++) c.push(cam.map(P((a & 1 ? hi : lo)[0] + off[0], (a & 2 ? hi : lo)[1] + off[1], (a & 4 ? hi : lo)[2] + off[2])));
        return { id: it.id || ('#' + it._i), poly: hull(c) };
      });
    }
    function pipeLines(cam, t) {
      return Object.keys(pipes).filter(function (id) { var b = pipes[id].it.build; return (Array.isArray(b) ? b[0] : b || 0) <= t; }).map(function (id) {
        return { id: id, pts: pipes[id].scr.filter(function (p, i) { return i % 3 === 0; }).map(cam.map) };
      });
    }
    function anchorOf(lb, t) {
      var a = lb.anchor || byId[lb.for].anchor, off = lb.for ? offsetOf(lb.for, t) : [0, 0, 0];
      return P(a[0] + off[0], a[1] + off[1], a[2] + off[2]);
    }
    function labelGeom(l, a, el, side) { // anchor (screen), elbow offset, side -> leader points and the plate rect
      var dir = side === 'left' ? -1 : 1, e = [a[0] + el[0], a[1] + el[1]], sh = [e[0] + dir * 28, e[1]], tx = sh[0] + dir * 12;
      var x = dir < 0 ? tx - l.w - 14 : tx - 14, y = sh[1] - L.size.label - 10;
      return { dir: dir, e: e, sh: sh, tx: tx, rect: { x: x, y: y, w: l.w + 28, h: L.size.label + L.size.sub + 34 } };
    }
    function labelWindow(lb, t) { // shown from at to until, and again from back (a label returns for the end)
      var a = lb.until != null ? 1 - seg(t, lb.until, TEXT_FADE) : 1;
      return lb.back != null && t >= lb.back ? Math.max(a, seg(t, lb.back, TEXT_FADE)) : a;
    }
    function poses(l) { // camera poses at which this label is on screen and at rest
      var lb = l.lb, times = [lb.at + 0.8];
      if (lb.back != null) times.push(lb.back + 0.6);
      (spec.camera || []).forEach(function (k) { var te = k.at + (k.dur || 1.2) + 0.05; if (te > lb.at) times.push(te); });
      return times.filter(function (t) { return t >= lb.at && labelWindow(lb, t) > 0.5 && textHide(t, l.ids, lb.focus) < 0.5; })
        .map(function (t) { return { t: t, cam: camera(t) }; });
    }
    function layout() {
      var avoid = avoidRects(), placed = [], cx = W / 2, cy = H / 2;
      // the scene's centre of mass on screen at rest: labels prefer to sit outward from it
      var hs = partHulls(camera(0), Infinity); if (hs.length) { var sx = 0, sy = 0, n = 0; hs.forEach(function (h) { h.poly.forEach(function (p) { sx += p[0]; sy += p[1]; n++; }); }); cx = sx / n; cy = sy / n; }
      var order = labels.slice().sort(function (a, b) { return (a.lb.elbow ? 0 : 1) - (b.lb.elbow ? 0 : 1) || a.lb.at - b.lb.at; });
      var DX = [40, 70, 110, 160, 220, 290], DY = [-230, -170, -120, -80, -45, 45, 80, 120, 170, 230];
      order.forEach(function (l) {
        var lb = l.lb, ps = poses(l); if (!ps.length) ps = [{ t: lb.at + 0.8, cam: camera(lb.at + 0.8) }];
        var cands = [];
        if (lb.elbow) cands.push({ el: lb.elbow, side: lb.side || (lb.elbow[0] < 0 ? 'left' : 'right'), fixed: true });
        else DX.forEach(function (dx) { DY.forEach(function (dy) { [-1, 1].forEach(function (sg) { cands.push({ el: [sg * dx, dy], side: sg < 0 ? 'left' : 'right' }); }); }); });
        var best = null, alts = [], debug = !!spec.debugLayout;
        cands.forEach(function (cd) {
          var cost = 0, hits = {};
          ps.forEach(function (pose, pi) {
            // the first pose (the label as it lands) counts in full; later camera poses less: a label the camera
            // carries off the frame fades out there (onScreen), and parts under a focus veil may be covered
            var main = pi === 0, w = main ? 1 : 0.4, hit = function (k, v) { if (main || k.indexOf('label') === 0) hits[k] = Math.max(hits[k] || 0, v); };
            var fa = focusAt(pose.t), veiled = function (id) { return fa.amount > 0.5 && !inFocus(fa.fc, id); };
            var a = pose.cam.map(anchorOf(lb, pose.t)), gm = labelGeom(l, a, cd.el, cd.side), r = gm.rect;
            var hulls = partHulls(pose.cam, pose.t), lines = pipeLines(pose.cam, pose.t), NX = 14, NY = 5, tot = NX * NY;
            var covered = function (poly) { var c = 0; for (var i = 0; i < NX; i++) for (var j = 0; j < NY; j++) if (inPoly(r.x + (i + 0.5) * r.w / NX, r.y + (j + 0.5) * r.h / NY, poly)) c++; return c / tot; };
            hulls.forEach(function (h) { var c = covered(h.poly); if (c) { cost += w * c * (veiled(h.id) ? 1200 : 5000); if (!veiled(h.id)) hit('part ' + h.id, c); } });
            figure(pose).forEach(function (h) { cost += w * covered(h.poly) * 1400; });
            floorTexts.forEach(function (ft) { if (pose.t < (ft.it.at0 || 0) || fa.amount > 0.5) return; var o = rectOverlap(r, floorRect(ft, pose.t)); if (o > 0) { cost += w * (12000 + o * 20000); hit('floor text ' + ft.it.text, o); } });
            lines.forEach(function (ln) { if (veiled(ln.id)) return; var c = 0; ln.pts.forEach(function (p) { if (p[0] > r.x && p[0] < r.x + r.w && p[1] > r.y && p[1] < r.y + r.h) c++; }); if (c) { cost += w * (900 + c * 60); hit('pipe ' + ln.id, 1); } });
            tags.forEach(function (g) { var tt = Math.max(pose.t, g.keys[0][0] + 0.01), tr = (lb.until == null || tt < lb.until) ? tagRect(g, pose.cam, tt) : null; if (!tr) return; var o = rectOverlap(r, tr); if (o > 0) { cost += 12000 + o * 20000; hit('tag ' + g.keys[0][1], o); } });
            avoid.forEach(function (av) { var o = rectOverlap(r, av); if (o > 0) { cost += w * (20000 + o * 20000); hit('page ' + av.name, o); } });
            placed.forEach(function (pl) {
              if (!samePose(pl, pose) && Math.abs(pl.t - pose.t) > 0.01) return;
              if (pl.lb && labelWindow(pl.lb, pose.t) < 0.5) return;
              var o = rectOverlap(r, pl.rect); if (o > 0) { cost += 15000 + o * 20000; hit('label ' + pl.title, o); }
              if (segHitsRect(gm.e, a, pl.rect) || segHitsRect(gm.e, gm.sh, pl.rect) || segHitsRect(pl.e, pl.a, r)) cost += 4000;
              if (segsCross(a, gm.e, pl.a, pl.e) || segsCross(gm.e, gm.sh, pl.a, pl.e) || segsCross(a, gm.e, pl.e, pl.sh)) cost += 6000;
            });
            var out = Math.max(0, safe[0] - r.x) + Math.max(0, r.x + r.w - safe[2]) + Math.max(0, safe[1] - r.y) + Math.max(0, r.y + r.h - safe[3]);
            if (out > 0) { cost += main ? 8000 + out * 60 : 1500 + out * 8; hit('outside', out); }
            hulls.forEach(function (h) { // a leader across a part (its own too, past the first stretch) reads as clutter
              // a part whose silhouette already holds the anchor (a unit mounted on a wall) is treated like the
              // label's own part: a leader leaving it is expected, a long run across it (past halfway) is not
              if (veiled(h.id)) return; var own = h.id === lb.for || inPoly(a[0], a[1], h.poly), c = 0;
              for (var i = own ? 5 : 1; i < 10; i++) if (inPoly(lerp(a[0], gm.e[0], i / 10), lerp(a[1], gm.e[1], i / 10), h.poly)) c++;
              if (inPoly(gm.sh[0], gm.sh[1], h.poly)) c += 3;
              cost += w * c * 160;
              if (c >= 2) hit('leader across part ' + h.id, Math.min(1, c / 10));   // reported where the label lands
            });
            // labels radiate outward from the figure's centre
            var dx = r.x + r.w / 2 - a[0], dy = r.y + r.h / 2 - a[1], ox = a[0] - cx, oy = a[1] - cy, dl = Math.hypot(dx, dy) || 1, ol = Math.hypot(ox, oy) || 1;
            cost += w * 900 * (1 - (dx * ox + dy * oy) / (dl * ol)) / 2;
          });
          cost += (Math.abs(cd.el[0]) + Math.abs(cd.el[1])) * (spec.leaderCost || 4);
          if (lb.side && lb.side !== cd.side) cost += 600;
          if (cd.fixed) cost -= 1e6; // an explicit elbow wins; it is still audited below
          if (debug) alts.push({ el: cd.el, side: cd.side, cost: Math.round(cost), hits: hits, poses: ps.map(function (x) { return x.t; }) });
          if (!best || cost < best.cost) best = { cd: cd, cost: cost, hits: hits };
        });
        l.el = best.cd.el; l.side = best.cd.side;
        ps.forEach(function (pose) { var a = pose.cam.map(anchorOf(lb, pose.t)), gm = labelGeom(l, a, l.el, l.side); placed.push({ t: pose.t, cam: pose.cam, rect: gm.rect, e: gm.e, sh: gm.sh, a: a, title: lb.title, lb: lb }); });
        var hits = best.hits, bad = Object.keys(hits).filter(function (k) { return k.indexOf('pipe') !== 0 && (k.indexOf('part') !== 0 || hits[k] > 0.04); });
        report.labels.push({ id: lb.id || lb.for, title: lb.title, side: l.side, elbow: l.el, auto: !lb.elbow, hits: hits, cost: Math.round(best.cost),
          alts: debug ? alts.sort(function (x, y) { return x.cost - y.cost; }) : undefined });
        if (bad.length) {
          var msg = 'label "' + lb.title + '" collides: ' + bad.map(function (k) { return k + (typeof hits[k] === 'number' && hits[k] <= 1 && k !== 'outside' ? ' (' + Math.round(hits[k] * 100) + '%)' : ''); }).join(', ') + '; move it (elbow/side), move the part, or shorten the text';
          report.warnings.push(msg); warn(msg);
        }
      });
    }
    function tagRect(g, cam, t) { // where a tag sits at rest at t (null while hidden)
      var tg = g.tg;
      if (t < g.keys[0][0] || textHide(t, g.ids, tg.focus) > 0.5 || (tg.until != null && t > tg.until)) return null;
      return tagRectRaw(g, cam, t);
    }
    function tagAnchor(g, cam, t) { // the tag's anchor on screen at t (null: nothing to pin it to now)
      var tg = g.tg;
      if (tg.token) { var st = tokById[tg.token] && tokenAt(tokById[tg.token], t); return st ? cam.map(P(st.pos[0], st.pos[1], st.pos[2])) : null; }
      if (tg.pipe) { var pp = pipes[tg.pipe], q = atLen(pp, pp.len * (tg.f == null ? 0.5 : tg.f)); return cam.map([q.x, q.y]); }
      var w3 = tg.anchor || byId[tg.for].anchor, off = tg.for ? offsetOf(tg.for, t) : [0, 0, 0];
      return cam.map(P(w3[0] + off[0], w3[1] + off[1], w3[2] + off[2]));
    }
    function tagRectRaw(g, cam, t) {
      var tg = g.tg, a;
      var lv0 = g.log ? liveTagAt(g, t) : null, wmax = lv0 ? (g.ws[lv0.i] || 0) : Math.max.apply(null, g.ws.concat([0]));
      if (tg.token) { a = tagAnchor(g, cam, t); if (!a) return null; var o3 = tg.off || [0, -36], w3 = wmax + 30; return { x: a[0] + o3[0] - w3 / 2 - 6, y: a[1] + o3[1] - g.h / 2 - 6, w: w3 + 12, h: g.h + 12 }; }
      if (tg.pipe) { var pp = pipes[tg.pipe], q = atLen(pp, pp.len * (tg.f == null ? 0.5 : tg.f)); a = cam.map([q.x, q.y]); }
      else { var w3 = tg.anchor || byId[tg.for].anchor, off = tg.for ? offsetOf(tg.for, t) : [0, 0, 0]; a = cam.map(P(w3[0] + off[0], w3[1] + off[1], w3[2] + off[2])); }
      var off2 = tg.off || [0, -36], w = wmax + 30, sh = tg.align === 'right' ? -w / 2 : tg.align === 'left' ? w / 2 : 0;
      return { x: a[0] + off2[0] + sh - w / 2 - 6, y: a[1] + off2[1] - g.h / 2 - 6, w: w + 12, h: g.h + 12 };
    }
    var TEXT_SAFE = [64, 58, 1856, 990];  // text keeps clear of the frame edges (the check: 3 %; the bottom 8 % is under phone player controls)
    function inside(r, box) { return r && r.x >= box[0] && r.y >= box[1] && r.x + r.w <= box[2] && r.y + r.h <= box[3]; }
    function onScreen(rectAt, t, box) { // min of the share of samples on screen in [t-0.2, t] and in [t, t+0.2]
      var back = 0, fwd = 0, n = 4;
      for (var k = 0; k <= n; k++) {
        if (inside(rectAt(t - TEXT_FADE * k / n), box)) back++;
        if (inside(rectAt(t + TEXT_FADE * k / n), box)) fwd++;
      }
      return Math.min(back, fwd) / (n + 1);
    }
    function floorRect(ft, t) { // the floor text's screen box under the camera at t
      var cam = camera(t), it = ft.it, p = P(it.at[0], it.at[1], it.at[2] || 0), m = ft.m, len = ft.len, sz = ft.size, x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      [[0, -sz * 0.78], [len, -sz * 0.78], [len, sz * 0.22], [0, sz * 0.22]].forEach(function (c) {
        var q = cam.map([p[0] + m[0] * c[0] + m[2] * c[1], p[1] + m[1] * c[0] + m[3] * c[1]]);
        x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]);
      });
      return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    }
    var footHoles = [];  // [{el, rect}]: each hole stays paired with its footer, so it follows the footer's reveal
    function footerMask() { // a feathered hole in the floor layer under each footer line that has text
      var k = lay.k || 1, base = stage && stage.getBoundingClientRect ? stage.getBoundingClientRect() : { left: 0, top: 0 };
      report.footerMask = []; footHoles = []; gHoles.innerHTML = '';
      document.querySelectorAll('.ld-foot').forEach(function (el) {
        if (!String(el.textContent || '').trim()) return;
        var r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
        var x = (r.left - base.left) / k - 10, y = (r.top - base.top) / k - 8, w = r.width / k + 20, h = r.height / k + 16;
        report.footerMask.push([Math.round(x), Math.round(y), Math.round(w), Math.round(h)]);
        footHoles.push({ el: el, rect: mk('rect', { x: f1(x), y: f1(y), width: f1(w), height: f1(h), rx: 6, fill: '#000' }, gHoles) });
      });
    }
    function footerHoles() { // each hole as strong as its footer is visible now (a footer revealed later is not cut yet)
      var any = false;
      footHoles.forEach(function (fh) {
        var st = fh.el.style, o = st.visibility === 'hidden' ? 0 : (st.opacity === '' ? 1 : parseFloat(st.opacity) || 0);
        fh.rect.setAttribute('opacity', f3(o));
        if (o > 0) any = true;
      });
      if (any) gFloorMask.setAttribute('mask', 'url(#ld-footmask)'); else gFloorMask.removeAttribute('mask');
    }
    function audit() { // every text must be fully on screen at some moment of its window, or it is reported
      var never = function (from, to, rectAt) {
        var seen = false, any = false;
        for (var u = from; u <= to + 1e-6 && !seen; u += 0.25) { var r = rectAt(u); if (!r) continue; any = true; if (inside(r, TEXT_SAFE)) seen = true; }
        return any && !seen;
      };
      var say = function (text, from, widest) {
        var msg = '"' + text + '" never shows fully inside the text safe zone (from ' + (Math.round(from * 10) / 10) + ' s): it would be cut by the frame or sit under phone controls in the bottom 8 %; move it' +
          (widest && widest !== text ? ' (its widest value, "' + widest + '", sets the size it is checked at: shorten that one, or give it more room)' : '');
        report.warnings.push(msg); warn(msg);
      };
      var END = 40;
      labels.forEach(function (l) {
        var lb = l.lb, ok = function (u) { return labelWindow(lb, u) > 0.5 && textHide(u, l.ids, lb.focus) < 0.5 ? labelGeom(l, camera(u).map(anchorOf(lb, u)), l.el, l.side).rect : null; };
        var to = lb.back != null ? lb.back + END : (lb.until != null ? lb.until : lb.at + END);
        if (never(lb.at + 0.3, to, ok)) say(lb.title, lb.at);
      });
      tags.forEach(function (g) {
        var tg = g.tg, t0 = g.keys[0][0];
        var ok = function (u) { return u >= t0 && (tg.until == null || u < tg.until) && textHide(u, g.ids, tg.focus) < 0.5 ? tagRectRaw(g, camera(u), u) : null; };
        var wi = g.ws.indexOf(Math.max.apply(null, g.ws.concat([0])));
        if (never(Math.max(t0, 0) + 0.3, tg.until != null ? tg.until : t0 + END, ok)) say(g.keys[0][1], t0, g.keys.length > 1 && wi >= 0 ? g.keys[wi][1] : null);
      });
      floorTexts.forEach(function (ft) {
        var it = ft.it, t0 = it.at0 != null ? it.at0 : (it.show || 0);
        var ok = function (u) { return textHide(u, [], false) < 0.5 ? floorRect(ft, u) : null; };
        if (never(t0 + 0.3, it.until != null ? it.until : t0 + END, ok)) say(it.text, t0);
      });
    }
    function samePose(a, b) { return a.cam && b.cam && Math.abs(a.cam.z - b.cam.z) < 1e-3 && Math.abs(a.cam.ex - b.cam.ex) < 0.5 && Math.abs(a.cam.ey - b.cam.ey) < 0.5; }

    /* ---------- render(t): the world as a pure function of t ---------- */
    function render(t) {
      var cam = camera(t), lw = L.lw / cam.z, fa = focusAt(t), F = fa.fc;
      var camT = 'translate(' + f1(cam.ex) + ' ' + f1(cam.ey) + ') scale(' + (Math.round(cam.z * 10000) / 10000) + ')';
      gWorld.setAttribute('transform', camT); gFloorCam.setAttribute('transform', camT);
      var shadows = '';
      var drawItem = function (it) {
        if (it.kind === 'pipe' || it.kind === 'link') return pipes[it.id] ? pipeSVG(pipes[it.id], t, lw) : '';
        if (it.kind === 'air') return airSVG(it, t, lw);
        var p = it.build == null ? 1 : seg(t, it.build, it.dur || 0.6, E.outCubic);
        if (p <= 0) return '';
        var shown = it.vis ? visAt(it.vis, t) : 1; if (shown <= 0) return '';   // live: shown or hidden (show())
        var lift = (1 - p) * (it.lift == null ? 9 : it.lift), off = offsetOf(it.id, t), v = V(off[0], off[1], off[2] + lift), op = clamp(p * 1.8, 0, 1) * shown;
        if (it.footprint && it.shadow !== false) shadows += '<g transform="translate(' + f1(V(off[0], off[1], 0)[0]) + ' ' + f1(V(off[0], off[1], 0)[1]) + ')">' + shadowSVG(it.footprint, p, it.bbox ? it.bbox[0][2] : 0) + '</g>';
        var fkey = it.icon === 'lamp' || it.icon === 'gate' || (it.icon === 'core' && it.glass) ? 'flow' : 'face';
        var tn = it.id ? toneAt(it.id, t, null, null) : null, tint = tn && tn.to ? { c: toneOf(L, tn.to)[fkey], p: tn.p } : null;
        if (tint && tn.from) tint = { c: mixHex(toneOf(L, tn.from)[fkey], toneOf(L, tn.to)[fkey], tn.p), p: 1 };
        var pl = it.id ? pulseAt(it.id, t) : null;
        if (pl) tint = tint ? { c: mixHex(tint.c, pl.c, pl.p), p: Math.max(tint.p, pl.p) } : pl;
        var lampOnly = it.icon === 'lamp' || it.icon === 'gate' || (it.icon === 'core' && it.glass);
        return '<g transform="translate(' + f1(v[0]) + ' ' + f1(v[1]) + ')" opacity="' + f3(op) + '">' + (it.shapes || []).map(function (sh) { return shapeSVG(sh, t, lw, lampOnly && !sh.lamp ? null : tint); }).join('') + '</g>';
      };
      gFloor.innerHTML = floorItems.map(drawItem).join('');
      var body = sorted.map(drawItem).join('') + frontItems.map(drawItem).join('');
      var toks = '';
      tokens.forEach(function (tk) { var st = tokenAt(tk, t); if (st) toks += tokenSVG(tk, st, lw); });
      var top = '';
      if (fa.amount > 0) { // focus: veil the world in the ground colour, then lift the focus part and its own pipes above it
        var keep = shadows;
        top = '<rect x="-4000" y="-4000" width="10000" height="10000" fill="' + L.veil + '" opacity="' + f3((1 - (L.dimTo || 0.45)) * fa.amount) + '"/>';
        items.forEach(function (it) { if (it.id && inFocus(F, it.id)) top += drawItem(it); });
        shadows = keep;
      }
      gDraw.innerHTML = shadows + body + toks + top;
      var B = spec.bands, bo = f3(fa.amount);
      gBands.innerHTML = fa.amount > 0 && B ? '<rect x="45" y="45" width="1830" height="' + B[0] + '" fill="url(#ld-band-t)" opacity="' + bo + '"/><rect x="45" y="' + (1035 - B[1]) + '" width="1830" height="' + B[1] + '" fill="url(#ld-band-b)" opacity="' + bo + '"/>' : '';

      floorTexts.forEach(function (ft) {
        var it = ft.it, o = seg(t, it.at0 != null ? it.at0 : (it.show || 0), TEXT_FADE) * (it.until != null ? 1 - seg(t, it.until, TEXT_FADE) : 1) * (1 - textHide(t, [], false));
        if (o > 0 && lay.done) o *= onScreen(function (u) { return floorRect(ft, u); }, t, TEXT_SAFE);
        ft.el.setAttribute('opacity', f3(o)); ft.el.setAttribute('visibility', o > 0 ? 'visible' : 'hidden');
      });
      if (!lay.done) return;
      labels.forEach(function (l) {
        var lb = l.lb, a = cam.map(anchorOf(lb, t));
        var pin = seg(t, lb.at, 0.38, E.inOutCubic), tin = seg(t, lb.at + 0.22, TEXT_FADE), rise = (1 - seg(t, lb.at + 0.22, 0.45, E.outCubic)) * 10;
        var o = (1 - textHide(t, l.ids, lb.focus)) * labelWindow(lb, t);
        if (o > 0 && pin > 0) o *= onScreen(function (u) { var c = camera(u); return labelGeom(l, c.map(anchorOf(lb, u)), l.el, l.side).rect; }, t, TEXT_SAFE);
        l.g.setAttribute('opacity', f3(o));
        // hidden or not, every attribute is set from t, so the DOM is the same whatever frame came before
        l.g.setAttribute('visibility', pin <= 0 || o <= 0 ? 'hidden' : 'visible');
        var gm = labelGeom(l, a, l.el, l.side), L1 = Math.hypot(gm.e[0] - a[0], gm.e[1] - a[1]), want = (L1 + 28) * pin;
        var d = 'M' + f1(a[0]) + ' ' + f1(a[1]);
        if (want <= L1) { var q = want / (L1 || 1); d += 'L' + f1(lerp(a[0], gm.e[0], q)) + ' ' + f1(lerp(a[1], gm.e[1], q)); }
        else d += 'L' + f1(gm.e[0]) + ' ' + f1(gm.e[1]) + 'L' + f1(gm.e[0] + gm.dir * (want - L1)) + ' ' + f1(gm.e[1]);
        l.lead.setAttribute('d', d);
        l.dot.setAttribute('cx', f1(a[0])); l.dot.setAttribute('cy', f1(a[1])); l.dot.setAttribute('r', f1(5 * E.outCubic(seg(t, lb.at, 0.25))));
        var anchor = gm.dir < 0 ? 'end' : 'start';
        [l.tt, l.sub].forEach(function (e) { e.setAttribute('text-anchor', anchor); e.setAttribute('x', f1(gm.tx)); e.setAttribute('opacity', f3(tin)); });
        l.tt.setAttribute('y', f1(gm.sh[1] - 4 + rise)); l.sub.setAttribute('y', f1(gm.sh[1] + L.size.sub + 8 + rise));
        var r = gm.rect;
        l.plate.setAttribute('x', f1(r.x)); l.plate.setAttribute('y', f1(r.y)); l.plate.setAttribute('width', f1(r.w)); l.plate.setAttribute('height', f1(r.h));
        l.plate.setAttribute('opacity', f3(tin * (L.labelPlateOpacity || 0.9)));
      });
      tags.forEach(function (g) {
        var tg = g.tg, a = tagAnchor(g, cam, t), fs = g.fs, h = g.h;
        var lv = g.log ? liveTagAt(g, t) : null, first = lv ? lv.at : g.keys[0][0], until = lv ? lv.until : tg.until;
        var o = a ? seg(t, first, TEXT_FADE) * (1 - textHide(t, g.ids, tg.focus)) * (until != null ? 1 - seg(t, until, TEXT_FADE) : 1) : 0;
        if (tg.token && a) { var stk = tokenAt(tokById[tg.token], t); o *= stk ? clamp(stk.o * 1.5, 0, 1) : 0; }
        var rise = (1 - seg(t, first, 0.35, E.outCubic)) * 8 + (tg.press != null ? 5 * Math.sin(Math.PI * seg(t, tg.press, 0.22)) : 0);
        if (o > 0) o *= onScreen(function (u) { return tagRectRaw(g, camera(u), u); }, t, TEXT_SAFE);
        if (!a) a = [0, 0];
        g.g.setAttribute('opacity', f3(o)); g.g.setAttribute('visibility', o > 0 ? 'visible' : 'hidden');
        var cur = 0; if (lv) cur = lv.i; else g.keys.forEach(function (k, i) { if (t >= k[0]) cur = i; });
        var off2 = tg.off || [0, -36], w = (tg.type ? Math.max.apply(null, g.ws) + 30 + fs * 0.7 : (g.ws[cur] || 0) + 30), cy = a[1] + off2[1] + rise;
        var cx = a[0] + off2[0] + (tg.align === 'right' ? -w / 2 : tg.align === 'left' ? w / 2 : 0);  // align: the pill's edge sits on the offset
        g.r.setAttribute('x', f1(cx - w / 2)); g.r.setAttribute('y', f1(cy - h / 2)); g.r.setAttribute('width', f1(w)); g.r.setAttribute('height', f1(h)); g.r.setAttribute('rx', f1(h / 2));
        var ktn = lv && lv.tone ? toneOf(L, lv.tone) : g.keys[cur][2] ? toneOf(L, g.keys[cur][2]) : toneOf(L, tg.tone || tg.temp);
        if (lv) g.tx[cur].setAttribute('fill', ktn.tagInk);
        if (tg.press != null && t >= tg.press && t < tg.press + 0.3) ktn = toneOf(L, tg.pressTone || 'warm');
        g.r.setAttribute('fill', ktn.tag); if (L.tagStyle === 'outline') g.r.setAttribute('stroke', ktn.tagInk);
        g.tx.forEach(function (e, i) {
          var tx0 = tg.type ? cx - w / 2 + 15 : cx;
          e.setAttribute('x', f1(tx0)); e.setAttribute('y', f1(cy + fs * 0.36)); e.setAttribute('opacity', i === cur ? 1 : 0); e.setAttribute('visibility', i === cur ? 'visible' : 'hidden');
          if (tg.press != null) e.setAttribute('fill', (t >= tg.press && t < tg.press + 0.3 ? toneOf(L, tg.pressTone || 'warm') : (g.keys[i][2] ? toneOf(L, g.keys[i][2]) : toneOf(L, tg.tone || tg.temp))).tagInk);
        });
        if (tg.type) { // typed: the text is revealed left to right, a caret follows it and blinks while it waits
          var t0f = tg.typeFrom ? tg.typeFrom / Math.max(1, String(g.keys[0][1]).length) : 0;  // typeFrom: characters already there before typing starts (a prompt)
          var tp = lerp(t0f, 1, seg(t, tg.type[0], tg.type[1] - tg.type[0])), tw = (g.ws[cur] || 0) * (cur === 0 ? tp : 1), x0 = cx - w / 2 + 15;
          g.clip.setAttribute('x', f1(x0 - 2)); g.clip.setAttribute('y', f1(cy - h / 2)); g.clip.setAttribute('width', f1(tw + 2)); g.clip.setAttribute('height', f1(h));
          var typing = t >= tg.type[0] && t < tg.type[1], blink = ((Math.floor((t - tg.type[0]) * 2.4) % 2) + 2) % 2 === 0;
          var showCaret = (typing || blink || t < tg.type[0]) && (tg.caretUntil == null || t < tg.caretUntil);
          g.caret.setAttribute('x', f1(x0 + tw + 3)); g.caret.setAttribute('y', f1(cy - fs * 0.55)); g.caret.setAttribute('width', f1(fs * 0.5)); g.caret.setAttribute('height', f1(fs * 1.1));
          g.caret.setAttribute('opacity', showCaret ? 1 : 0);
        }
      });
      steps(t);
      reveals.forEach(function (rv) {
        var o = seg(t, rv.at, TEXT_FADE) * (rv.until != null ? 1 - seg(t, rv.until, TEXT_FADE) : 1);
        rv.els.forEach(function (e) { e.style.opacity = f3(o); e.style.visibility = o > 0 ? 'visible' : 'hidden'; });
      });
      footerHoles();
      if (spec.onFrame) spec.onFrame(t, { cam: cam, P: P, seg: seg, E: E, focus: fa });
    }

    /* ---------- steps: one persistent line per beat in the page (.ld-steps), shown in its window ---------- */
    var stepHost = document.querySelector('.ld-steps');
    var stepEls = (spec.steps || []).map(function (st, i) {
      if (!stepHost) return null;
      var e = document.createElement('div'); e.className = 'ld-step'; e.setAttribute('data-ld-step', String(i));
      if (st.kicker) { var k = document.createElement('span'); k.className = 'ld-step-k'; k.textContent = st.kicker; e.appendChild(k); }
      var tx = document.createElement('span'); tx.className = 'ld-step-t'; tx.textContent = st.text; e.appendChild(tx);
      stepHost.appendChild(e); return e;
    });
    if ((spec.steps || []).length && !stepHost) warn('the scene has steps but the page has no .ld-steps element to show them in');
    function steps(t) {
      (spec.steps || []).forEach(function (st, i) {
        var e = stepEls[i]; if (!e) return;
        var next = spec.steps[i + 1], end = st.until != null ? st.until : (next ? next.at : Infinity);
        var o = seg(t, st.at, TEXT_FADE) * (1 - seg(t, end - TEXT_FADE, TEXT_FADE)), rise = (1 - seg(t, st.at, 0.4, E.outCubic)) * 10;
        e.style.opacity = f3(o); e.style.visibility = o > 0 ? 'visible' : 'hidden'; e.style.transform = 'translateY(' + f1(rise) + 'px)';
      });
    }

    var reveals = (spec.reveal || []).map(function (rv) {
      var els = Array.prototype.slice.call(document.querySelectorAll(rv.sel));
      if (!els.length) warn('reveal: nothing on the page matches "' + rv.sel + '"');
      return { at: rv.at, until: rv.until, els: els };
    });
    /* ---------- live mode: keys written at the moment the viewer acts (Diagram.live) ----------
       set(target, value, {at, dur, tone}): a number is a store's level (0..1) or a stack's count; a string is a tag's
       text (null hides it);
       fire(target, {at, tone, dur} | {at, moves, stay}): a pulse on a part, or a token's route (moves as in
       spec.tokens, `at` relative to the call; no moves hides it); focus(part | null, {at, with}): the veil on every
       other part, the part's own pipes and links lit with it; hit(x, y, t): the topmost part under a stage point.
       `at` defaults to the page's clock (opts.live.now). Each call only appends or rewrites keys, so any t is
       still drawn the same way whatever came before. */
    function visAt(log, t) { // a live show/hide log [{at, on}] -> 0..1 (0.3 s fades)
      var k = -1; for (var j = 0; j < log.length && log[j].at <= t; j++) k = j;
      if (k < 0) return 1;
      var e = log[k], was = k > 0 ? log[k - 1].on : true;
      if (e.on === was) return e.on ? 1 : 0;
      return e.on ? seg(t, e.at, 0.3) : 1 - seg(t, e.at, 0.3);
    }
    function liveTagAt(g, t) { // -> null (no live value yet at t: the scene's own keys) | {i, at, until, tone}
      var log = g.log, k = -1; for (var j = 0; j < log.length && log[j].at <= t; j++) k = j;
      if (k < 0) return null;
      var e = log[k];
      if (e.i == null) { // hidden from e.at: fading out what showed before (a live value or the scene's own)
        var p = k > 0 ? log[k - 1] : null, wasOn = p ? p.i != null : (e.at >= g.keys[0][0] && (g.tg.until == null || g.tg.until > e.at));
        var fi = 0; if (!p) g.keys.forEach(function (kk, ii) { if (e.at >= kk[0]) fi = ii; });
        return wasOn ? { i: p ? p.i : fi, at: -1e9, until: e.at, tone: p ? p.tone : null } : { i: 0, at: 1e12, until: null, tone: null };
      }
      // shown since: the start of the run of shown values this one belongs to (a new value replaces the old at once)
      var since = e.at, m = k;
      while (m > 0 && log[m - 1].i != null) { m--; since = log[m].at; }
      if (m === 0) { var on0 = since >= g.keys[0][0] && (g.tg.until == null || g.tg.until > since); if (on0) since = -1e9; }
      return { i: e.i, at: since, until: null, tone: e.tone };
    }
    var liveApi = null;
    if (LIVE) {
      var tagById = {}; tags.forEach(function (g) { if (g.tg.id && !tagById[g.tg.id]) tagById[g.tg.id] = g; });
      var liveFocus = null;
      var when = function (o) { return o && o.at != null ? o.at : (LIVE.now ? LIVE.now() : 0); };
      var incident = function (id) { // the pipes and links that end on a part: they light with it
        return items.filter(function (it) {
          return (it.kind === 'pipe' || it.kind === 'link') && it.id && [it.from, it.to].some(function (r) { return typeof r === 'string' && r.split('.')[0] === id; });
        }).map(function (it) { return it.id; });
      };
      // a tag's live log: [{at, i | null (hidden), tone}], in time; a call at `at` drops what was scheduled after it
      var liveTag = function (g, text, at, tone) {
        var log = g.log || (g.log = []);
        while (log.length && log[log.length - 1].at > at) log.pop();
        if (text == null) { log.push({ at: at, i: null, tone: null }); return; }
        text = String(text);
        var i = -1; for (var j = 0; j < g.tx.length; j++) if (g.tx[j].textContent === text) { i = j; break; }
        if (i < 0) { // a value the scene did not list: one more persistent text, measured once
          var tn0 = toneOf(L, tone || g.tg.tone || g.tg.temp);
          var e = mk('text', { 'font-family': L.font.mono, 'font-size': g.fs, 'font-weight': 600, fill: tn0.tagInk, 'text-anchor': 'middle', opacity: 0, visibility: 'hidden' }, g.g);
          e.textContent = text; g.tx.push(e); g.keys.push([1e12, text]); g.ws.push(lay.done ? e.getComputedTextLength() : text.length * g.fs * 0.6);
          i = g.tx.length - 1;
        }
        log.push({ at: at, i: i, tone: tone || null });
        if (log.length > 400) log.splice(0, log.length - 400);
      };
      liveApi = {
        set: function (target, value, o) {
          // a number moves a store's level or a stack's count; a string (or null) is a tag's text: a tag may share
          // its id with the part it names
          o = o || {}; var at = when(o), num = typeof value === 'number', lv = num ? liveLevels[target] : null, g = num ? null : tagById[target];
          if (lv && lv.stack) {
            var k = lv.keys; while (k.length > 1 && k[k.length - 1][0] > at) k.pop();
            k.push([at, Math.max(0, Math.round(Number(value) || 0))]);
            return;
          }
          if (lv) {
            var kk = lv.keys, v0 = keyed(kk, at, 0), d = o.dur == null ? 0.8 : o.dur;
            while (kk.length > 1 && kk[kk.length - 1][0] >= at) kk.pop();
            kk.push([at, v0], [at + Math.max(0.001, d), clamp(Number(value) || 0, 0, 1)]);
            return;
          }
          if (g) { liveTag(g, value, at, o.tone); return; }
          warn('set: "' + target + '" is not ' + (num ? 'a store or a stack (a number sets a level or a count)' : 'a tag id (a string sets a tag\'s text)'));
        },
        fire: function (target, o) {
          o = o || {}; var at = when(o), tk = tokById[target];
          if (tk) { // a route (no moves: hidden from `at`); the routes stay in time, a call drops the ones after it
            var routes = tk.routes || (tk.routes = [{ start: -1e12, moves: tk.moves || [], until: tk.until }]);
            while (routes.length > 1 && routes[routes.length - 1].start >= at) routes.pop();
            var mv = (o.moves || []).map(function (m) { return Object.assign({}, m, { at: at + (m.at || 0) }); }), last = mv[mv.length - 1];
            routes.push({ start: at, moves: mv, until: !last || o.stay === true ? null : last.at + (last.dur == null ? 0.8 : last.dur) + (o.stay == null ? 0.3 : o.stay) });
            return;
          }
          if (byId[target]) {
            if (pulses.length > 600) pulses = pulses.filter(function (st) { return !st.live || st.at > at - 60; });
            pulses.push({ target: target, at: at, tone: o.tone || 'cold', dur: o.dur == null ? 0.8 : o.dur, amount: o.amount, pulse: true, live: true });
            return;
          }
          warn('fire: "' + target + '" is not a token or a part');
        },
        focus: function (id, o) {
          o = o || {}; var at = when(o), d = o.dur == null ? 0.15 : o.dur;
          if (liveFocus && liveFocus.part === id) return;
          if (liveFocus) liveFocus.until = at;
          liveFocus = null;
          if (focuses.length > 400) focuses = focuses.filter(function (fc) { return !fc.live || fc.until === Infinity || fc.until + fc.out + 60 > at; });
          if (id && byId[id]) { liveFocus = { part: id, with: incident(id).concat(o.with || []), at: at, dur: d, out: d, until: Infinity, live: true }; focuses.push(liveFocus); }
          else if (id) warn('focus: unknown part "' + id + '"');
        },
        hit: function (x, y, t, only) {
          var rank = {}; sorted.forEach(function (it, i) { if (it.id) rank[it.id] = i; });
          var best = null;
          partHulls(camera(t), t).forEach(function (h) {
            if (only && only.indexOf(h.id) < 0) return;
            if (!inPoly(x, y, h.poly)) return;
            var r = rank[h.id] == null ? -1 : rank[h.id]; if (!best || r > best.r) best = { id: h.id, r: r };
          });
          return best ? best.id : null;
        },
        box: function (id, t) {
          var h = partHulls(camera(t), t).filter(function (x) { return x.id === id; })[0]; if (!h) return null;
          var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
          h.poly.forEach(function (p) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); });
          return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
        },
        // tone(part | pipe, tone | null, {at, dur}): its colour from `at` (null: back to neutral), as a scene's states
        tone: function (target, tone, o) {
          o = o || {}; var at = when(o);
          if (!byId[target]) { warn('tone: unknown part or pipe "' + target + '"'); return; }
          for (var j = states.length - 1; j >= 0; j--) if (states[j].live && states[j].target === target && states[j].at > at) states.splice(j, 1);
          var st = { target: target, at: at, tone: tone || null, dur: o.dur == null ? 0.4 : o.dur, live: true }, k = states.length;
          while (k > 0 && states[k - 1].at > at) k--;
          states.splice(k, 0, st);
        },
        // show(part, on, {at}): a part shown or hidden from `at` (0.3 s fade); a scene's floor marks included
        show: function (target, on, o) {
          o = o || {}; var at = when(o), it = byId[target];
          if (!it) { warn('show: unknown item "' + target + '"'); return; }
          var log = it.vis || (it.vis = []);
          while (log.length && log[log.length - 1].at > at) log.pop();
          var last = log.length ? log[log.length - 1].on : true;
          if (last !== !!on) log.push({ at: at, on: !!on });
        },
        incident: incident,
        tags: function () { return Object.keys(tagById); },
      };
    }
    if (root.ST && ST.onSeek && !(LIVE && !LIVE.seek)) ST.onSeek(function (t) { render(t); });
    var api = { render: render, report: report, ready: ready, theme: L, project: P, camera: camera, order: sorted, pipes: pipes, validate: function () { return validate(spec); } };
    if (liveApi) Object.assign(api, liveApi);
    Diagram.current = api; Diagram.report = report;
    return api;
  }

  // a live figure: mount(spec) whose keys the page writes as the viewer acts. opts.live: {now: fn -> seconds (the
  // page's clock, the default `at` of set/fire/focus), seek: true to follow ST.seek (a film made from a live scene)}
  function live(spec, opts) { opts = Object.assign({}, opts || {}); opts.live = opts.live && opts.live !== true ? opts.live : {}; return mount(spec, opts); }
  var Diagram = { mount: mount, live: live, validate: validate, themes: THEMES, parts: LIB, seg: seg, E: E, version: '0.2.0' };
  root.Diagram = Diagram; root.LD = Diagram;
})(typeof window !== 'undefined' ? window : this);
