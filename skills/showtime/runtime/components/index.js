// showtime motion components: import this one module to get every component, and every
// element with a data-st="<component>" attribute is mounted automatically.
//
//   <script src="/_st/stage.js"></script>
//   <script type="module" src="/_st/components/index.js"></script>
//   <h1 data-st="kinetic-type" data-style="blur">Hello</h1>
//
// Or import what you need and mount from JS:
//   import { KineticType, Captions } from '/_st/components/index.js';
// Scenes with data-transition="<type> [dir] [seconds]" are wired to the scene before them.
// Set window.ST_NO_AUTOMOUNT = true before this module runs to mount by hand (mountAll(),
// autoTransitions()).
export * from './core.js';
export { KineticType } from './kinetic-type.js';
export { Typewriter, typingTimeline } from './typewriter.js';
export { Captions, normalizeWords, groupWords } from './captions.js';
export { LowerThird } from './lower-third.js';
export { CountUp } from './count-up.js';
export { Chart } from './chart.js';
export { CodeBlock } from './code-block.js';
export { BrowserFrame, DeviceFrame } from './frames.js';
export { Cursor, Keystrokes } from './cursor.js';
export { LogoReveal, EndCard } from './end-card.js';
export { FeatureGrid } from './feature-grid.js';
export { ChatThread, Notifications } from './bubbles.js';
export { Steps } from './steps.js';
export { KenBurns } from './ken-burns.js';
export { Camera } from './camera.js';
export { Fit } from './fit.js';
export { portalShape, counterOf } from './portal.js';
export { WorldMap } from './map.js';
export { Grain } from './grain.js';

import { mountAll } from './core.js';
import { autoTransitions } from '../transitions/transitions.js';
export { transition, autoTransitions } from '../transitions/transitions.js';

function boot() {
  mountAll(document, { auto: true });
  autoTransitions();
}
if (!window.ST_NO_AUTOMOUNT) {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
}
