// world-map: a world map or spinning globe drawn as SVG from the locally installed
// world-atlas data (Natural Earth, public domain) with d3-geo projections. The camera flies
// between places, countries fill in on cue, markers pop with a pulse and routes draw along
// great circles. Everything is recomputed from t, so any frame can be rendered alone.
//
//   <div data-st="world-map" data-projection="orthographic" data-spin="6"
//        data-camera='[{"at":0,"center":[-40,25],"zoom":1},{"at":2,"center":[10,48],"zoom":2.4,"dur":1.6}]'
//        data-highlight='[{"at":2.6,"names":["France","Germany","Spain"]}]'
//        data-markers='[{"at":3,"lon":2.35,"lat":48.86,"label":"Paris"}]'
//        data-routes='[{"at":3.4,"from":[-74,40.7],"to":[2.35,48.86],"dur":1.4}]'></div>
import { define, svg, clamp, ease, lerp, d3 as loadD3, loadJSON } from './core.js';

/** Minimal TopoJSON -> GeoJSON features decoder (Polygon / MultiPolygon / Point types). */
export function topoFeatures(topo, name) {
  const obj = topo.objects[name || Object.keys(topo.objects)[0]];
  const tf = topo.transform;
  const arcs = topo.arcs.map((arc) => {
    let x = 0, y = 0;
    return arc.map((p) => {
      if (!tf) return [p[0], p[1]];
      x += p[0]; y += p[1];
      return [x * tf.scale[0] + tf.translate[0], y * tf.scale[1] + tf.translate[1]];
    });
  });
  const ring = (idx) => {
    const out = [];
    idx.forEach((i, k) => {
      const a = i < 0 ? arcs[~i].slice().reverse() : arcs[i];
      out.push(...(k ? a.slice(1) : a));
    });
    return out;
  };
  const geom = (g) => {
    if (g.type === 'Polygon') return { type: 'Polygon', coordinates: g.arcs.map(ring) };
    if (g.type === 'MultiPolygon') return { type: 'MultiPolygon', coordinates: g.arcs.map((p) => p.map(ring)) };
    if (g.type === 'Point') return { type: 'Point', coordinates: g.coordinates };
    return null;
  };
  const list = obj.type === 'GeometryCollection' ? obj.geometries : [obj];
  return list.map((g) => ({ type: 'Feature', id: g.id, properties: g.properties || {}, geometry: geom(g) })).filter((f) => f.geometry);
}

const PROJ = { naturalEarth: 'geoNaturalEarth1', equalEarth: 'geoEqualEarth', mercator: 'geoMercator', orthographic: 'geoOrthographic', globe: 'geoOrthographic' };

export const WorldMap = define({
  name: 'world-map',
  defaults: {
    at: 0, src: '/_lib/world-atlas/countries-110m.json', object: 'countries', projection: 'naturalEarth',
    camera: [], spin: 0, highlight: [], markers: [], routes: [], graticule: null, labels: true,
  },
  async setup(el, o, { motion }) {
    const d3 = await loadD3();
    const data = await loadJSON(o.src);
    const features = data.type === 'Topology' ? topoFeatures(data, o.object) : (data.features || []);
    const W = el.clientWidth || 800, H = el.clientHeight || 450;
    const kind = PROJ[o.projection] || 'geoNaturalEarth1';
    const globe = kind === 'geoOrthographic';
    const proj = d3[kind]();
    proj.fitSize([W * (globe ? 0.92 : 1), H * (globe ? 0.92 : 1)], { type: 'Sphere' });
    const s0 = proj.scale();
    const path = d3.geoPath(proj);
    el.textContent = '';
    const root = svg('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'st-map-svg' });
    const sphere = svg('path', { class: 'st-map-sphere' });
    const grat = (o.graticule ?? globe) ? svg('path', { class: 'st-map-graticule' }) : null;
    const land = svg('g', { class: 'st-map-land' });
    const routesG = svg('g', { class: 'st-map-routes' });
    const markersG = svg('g', { class: 'st-map-markers' });
    root.append(sphere, ...(grat ? [grat] : []), land, routesG, markersG);
    el.append(root);
    const graticule = d3.geoGraticule10();
    const countryEls = features.map((f) => { const p = svg('path', { class: 'st-map-country' }); land.append(p); return p; });
    const nameOf = (f) => String(f.properties.name || '').toLowerCase();
    const hl = (Array.isArray(o.highlight) ? o.highlight : []).map((x) => {
      const names = new Set((x.names || []).map((n) => String(n).toLowerCase()));
      const ids = new Set((x.ids || []).map(String));
      return { at: Number(x.at) || 0, color: x.color || null, match: features.map((f) => names.has(nameOf(f)) || ids.has(String(f.id))) };
    });
    const markers = (Array.isArray(o.markers) ? o.markers : []).map((m) => {
      const g = svg('g', { class: 'st-map-marker' });
      const pulse = svg('circle', { class: 'st-map-pulse', r: 10 });
      const dot = svg('circle', { class: 'st-map-dot', r: 5 });
      g.append(pulse, dot);
      let label = null;
      if (o.labels && m.label) { label = svg('text', { class: 'st-map-label', x: 12, y: 5 }, m.label); g.append(label); }
      markersG.append(g);
      return { ...m, at: Number(m.at) || 0, g, pulse, dot, label };
    });
    const routes = (Array.isArray(o.routes) ? o.routes : []).map((r) => {
      const line = svg('path', { class: 'st-map-route' });
      const head = svg('circle', { class: 'st-map-routehead', r: 4 });
      routesG.append(line, head);
      const interp = d3.geoInterpolate(r.from, r.to);
      const samples = Array.from({ length: 65 }, (_, i) => interp(i / 64));
      return { at: Number(r.at) || 0, dur: Number(r.dur) || 1.4, line, head, samples };
    });
    const cams = (Array.isArray(o.camera) && o.camera.length ? o.camera : [{ at: 0, center: [0, globe ? 20 : 0], zoom: 1 }])
      .map((c) => ({ at: Number(c.at) || 0, center: c.center || [0, 0], zoom: Number(c.zoom) || 1, dur: Number(c.dur) || 1.4 }));
    const M = ease(motion.easeMove), E = ease(motion.easeOut), S = ease('spring(0.4,0.55)');
    const pxScale = Math.min(W, H) / 540;

    const camera = (lt) => {
      let c = cams[0].center, z = cams[0].zoom;
      for (const k of cams.slice(1)) {
        if (lt < k.at) break;
        const p = M(clamp((lt - k.at) / k.dur));
        const gi = d3.geoInterpolate(c, k.center);
        c = gi(p);
        z = Math.exp(lerp(Math.log(z), Math.log(k.zoom), p));
      }
      return { c, z };
    };

    return {
      duration: Math.max(0.5, ...cams.map((c) => c.at + c.dur), ...routes.map((r) => r.at + r.dur), ...markers.map((m) => m.at + 0.6), ...hl.map((x) => x.at + 0.6)),
      sync: Object.fromEntries([...markers.map((m, i) => ['marker' + (i + 1), m.at]), ...routes.map((r, i) => ['route' + (i + 1), r.at + r.dur])]),
      update(lt) {
        const { c, z } = camera(lt);
        const lon = c[0] + Number(o.spin) * Math.max(0, lt);
        proj.scale(s0 * z);
        if (globe) {
          proj.rotate([-lon, -c[1]]).translate([W / 2, H / 2]);
        } else {
          proj.rotate([-lon, 0]).translate([W / 2, H / 2]);
          const py = proj([lon, c[1]]);
          if (py) proj.translate([W / 2, H / 2 + (H / 2 - py[1])]);
        }
        el.style.opacity = E(clamp(lt / 0.4)).toFixed(3);
        sphere.setAttribute('d', path({ type: 'Sphere' }) || '');
        if (grat) grat.setAttribute('d', path(graticule) || '');
        features.forEach((f, i) => {
          countryEls[i].setAttribute('d', path(f) || '');
          let fill = 0, color = null;
          for (const x of hl) if (x.match[i]) { const p = E(clamp((lt - x.at - (i % 7) * 0.03) / 0.5)); if (p > fill) { fill = p; color = x.color; } }
          countryEls[i].style.setProperty('--hl', fill.toFixed(3));
          if (color) countryEls[i].style.setProperty('--hl-color', color);
        });
        for (const m of markers) {
          const p = proj([m.lon, m.lat]);
          const visible = p && (!globe || d3.geoDistance([m.lon, m.lat], [lon, c[1]]) < Math.PI / 2 - 0.05);
          const k = S(clamp((lt - m.at) / 0.45));
          m.g.style.display = visible && lt >= m.at ? '' : 'none';
          if (!visible) continue;
          m.g.setAttribute('transform', `translate(${p[0].toFixed(2)},${p[1].toFixed(2)}) scale(${(pxScale * k).toFixed(4)})`);
          const q = lt >= m.at ? ((lt - m.at) % 1.6) / 1.6 : 0;
          m.pulse.setAttribute('r', (6 + q * 16).toFixed(2));
          m.pulse.style.opacity = (lt >= m.at ? (1 - q) * 0.6 : 0).toFixed(3);
          if (m.label) m.label.style.opacity = E(clamp((lt - m.at - 0.2) / 0.4)).toFixed(3);
        }
        for (const r of routes) {
          const p = ease('power2.inOut')(clamp((lt - r.at) / r.dur));
          const n = Math.max(2, Math.round(p * (r.samples.length - 1)) + 1);
          const coords = r.samples.slice(0, n);
          r.line.setAttribute('d', p > 0 ? path({ type: 'LineString', coordinates: coords }) || '' : '');
          const tip = proj(coords[coords.length - 1]);
          r.head.style.display = p > 0 && p < 1 && tip ? '' : 'none';
          if (tip) { r.head.setAttribute('cx', tip[0].toFixed(2)); r.head.setAttribute('cy', tip[1].toFixed(2)); r.head.setAttribute('r', (3.5 * pxScale).toFixed(2)); }
        }
      },
    };
  },
});

export default WorldMap;
