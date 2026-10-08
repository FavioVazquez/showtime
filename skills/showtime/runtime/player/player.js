/* showtime export player (runtime/player/player.js)
 *
 * The page that wraps an exported HTML video (`showtime export html`). It:
 *   - loads the project page into an <iframe srcdoc> together with its packed files (inline JSON, or
 *     assets/vfs.js + media files with --folder) and boot.js, which unpacks them into blob: URLs in
 *     that document (no network request) and runs the stage runtime in render mode (the same virtual
 *     clock and seeded randomness as `showtime render`), so every frame matches the MP4;
 *   - talks to that document only through postMessage, so it also works when a host sandboxes the
 *     page and the two documents do not share an origin;
 *   - plays it with the sound as the clock: an <audio> element with the embedded soundtrack, or the
 *     procedural score (ST.score) streamed live: rendered in pieces ahead of the playhead (the first
 *     piece in a fraction of a second) and played through Web Audio, so a two-minute score starts
 *     at once and seeks land anywhere without waiting for the whole score;
 *   - draws the chrome: a start screen over the poster frame (title in the film's own font, Play + length),
 *     play/pause, scrubber with chapter ticks and a chapter menu, time, volume, loop, fullscreen,
 *     "copy a link to this moment" (or to a range picked with shift + drag), deep links (#t=12.5, #chapter=2,
 *     and ranges #t=10-20 that loop) and a keyboard map (? shows it).
 *
 * Public API for pages that embed the file: window.showtimePlayer (see references/html-export.md).
 */
(function () {
  'use strict';
  var W = window, D = document;
  var VORIGIN = 'http://st.invalid';
  var $ = function (s, r) { return (r || D).querySelector(s); };
  var now = function () { return W.performance && performance.now ? performance.now() : Date.now(); };
  var clamp = function (x, a, b) { return x < a ? a : x > b ? b : x; };

  // ------------------------------------------------------------------ manifest
  var M = JSON.parse(D.getElementById('st-manifest').textContent);
  var root = D.getElementById('stp');
  var reducedMotion = !!(W.matchMedia && W.matchMedia('(prefers-reduced-motion: reduce)').matches);
  function b64bytes(b64) {
    var bin = atob(b64), n = bin.length, u = new Uint8Array(n);
    for (var i = 0; i < n; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  function attr(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }

  // ------------------------------------------------------------------ the stage document
  /**
   * The compressed part of a single-file export (#st-zfiles: the page, boot.js and every text file,
   * gzip + base64), unpacked with the browser's DecompressionStream. -> Promise<JSON text of the
   * text files | null>
   */
  function unpack() {
    var z = D.getElementById('st-zfiles');
    if (!z) return Promise.resolve(null);
    var b = atob(z.textContent.trim()), u = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
    z.parentNode.removeChild(z);
    return new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream('gzip'))).text().then(function (t) {
      var p = JSON.parse(t);
      M.html = p.html; M.bootSrc = p.boot;
      return JSON.stringify(p.files || {}).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
    });
  }
  /** srcdoc: <base> on the virtual origin, the packed files, the config, boot.js (which writes the page). */
  function stageDoc(zfiles) {
    var assetBase = new URL('./', D.baseURI).href;
    var cfg = {
      vorigin: VORIGIN, page: M.page, html: M.html, stage: M.stage, generator: M.generator, assetBase: assetBase,
      renderConfig: { config: M.config, override: null, alpha: false, settle: 'none', layers: false, seed: M.seed },
    };
    // leading comments, then <!doctype ...>: a loop, not a regex (the regex backtracked on many '--><!--')
    var hadDoctype = (function (h) {
      h = h.replace(/^\s+/, '');
      while (h.slice(0, 4) === '<!--') { var e = h.indexOf('-->', 4); if (e < 0) return false; h = h.slice(e + 3).replace(/^\s+/, ''); }
      return /^<!doctype/i.test(h);
    })(String(M.html));
    var pack = D.getElementById('st-files');
    var packed = pack ? pack.textContent.trim() : '';
    if (zfiles && zfiles.length > 2) packed = packed.length > 2 ? packed.slice(0, -1) + ',' + zfiles.slice(1) : zfiles;
    var html = (hadDoctype ? '<!DOCTYPE html>' : '') + '<html><head><meta charset="utf-8"><base href="' + attr(VORIGIN + M.page) + '">' +
      (pack ? '<script type="application/json" id="st-pack">' + packed + '<\/script>'
        : '<script src="' + attr(new URL('assets/vfs.js', assetBase).href) + '"><\/script>') +
      '<script type="application/json" id="st-cfg">' + JSON.stringify(cfg).replace(/</g, '\\u003c') + '<\/script>' +
      '<script>' + M.bootSrc + '<\/script>';
    if (pack && pack.parentNode) pack.parentNode.removeChild(pack); // the frame holds the only copy now
    return html;
  }

  // ------------------------------------------------------------------ icons
  var P = function (d, extra) { return '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="' + d + '"' + (extra || '') + '/>'; };
  var ICON = {
    play: '<svg class="i-play" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7.5 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.3 0-1.7L9.1 3.9c-.7-.4-1.6.1-1.6.9z"/></svg>',
    pause: '<svg class="i-pause" viewBox="0 0 24 24" aria-hidden="true"><rect fill="currentColor" x="6" y="4.5" width="4.2" height="15" rx="1.2"/><rect fill="currentColor" x="13.8" y="4.5" width="4.2" height="15" rx="1.2"/></svg>',
    replay: '<svg class="i-replay" viewBox="0 0 24 24" aria-hidden="true">' + P('M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v4.4h4.4', ' stroke-width="2.2"') + '</svg>',
    vol: '<svg class="i-vol" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 9.2v5.6c0 .4.3.7.7.7h3l4.6 3.8c.5.4 1.2 0 1.2-.6V5.3c0-.6-.7-1-1.2-.6L7.7 8.5h-3c-.4 0-.7.3-.7.7z"/>' + P('M16.2 9a4.2 4.2 0 0 1 0 6M18.8 6.4a8 8 0 0 1 0 11.2', ' stroke-width="1.9"') + '</svg>',
    muted: '<svg class="i-muted" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 9.2v5.6c0 .4.3.7.7.7h3l4.6 3.8c.5.4 1.2 0 1.2-.6V5.3c0-.6-.7-1-1.2-.6L7.7 8.5h-3c-.4 0-.7.3-.7.7z"/>' + P('M16.5 9.5l5 5M21.5 9.5l-5 5', ' stroke-width="1.9"') + '</svg>',
    loop: '<svg viewBox="0 0 24 24" aria-hidden="true">' + P('M17 3.5l3 3-3 3M4 11.5v-1a4 4 0 0 1 4-4h12M7 20.5l-3-3 3-3M20 12.5v1a4 4 0 0 1-4 4H4', ' stroke-width="1.9"') + '</svg>',
    link: '<svg viewBox="0 0 24 24" aria-hidden="true">' + P('M10 14a4.5 4.5 0 0 0 6.4 0l3.2-3.2a4.5 4.5 0 0 0-6.4-6.4L11.7 6M14 10a4.5 4.5 0 0 0-6.4 0l-3.2 3.2a4.5 4.5 0 0 0 6.4 6.4l1.5-1.5', ' stroke-width="1.9"') + '</svg>',
    fsEnter: '<svg class="i-fs-enter" viewBox="0 0 24 24" aria-hidden="true">' + P('M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5') + '</svg>',
    fsExit: '<svg class="i-fs-exit" viewBox="0 0 24 24" aria-hidden="true">' + P('M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5') + '</svg>',
    rotate: '<svg viewBox="0 0 24 24" aria-hidden="true">' + P('M7.5 3.5h9a1.5 1.5 0 0 1 1.5 1.5v14a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1.5-1.5zM3 14.5a8 8 0 0 0 3 5M21 9.5a8 8 0 0 0-3-5', ' stroke-width="1.7"') + '</svg>',
  };

  // ------------------------------------------------------------------ words
  // The player's own words in the page's language (manifest lang, else <html lang>); English otherwise.
  // Keys rows follow the KEYS table order.
  var WORDS = {
    en: { play: 'Play', replay: 'Replay', playK: 'Play (k)', pauseK: 'Pause (k)', muteM: 'Mute (m)', unmuteM: 'Unmute (m)',
      seek: 'Seek', volume: 'Volume', linkC: 'Copy a link to this moment (c)', loop: 'Loop', keysQ: 'Keyboard shortcuts (?)',
      fsF: 'Full screen (f)', shortcuts: 'Keyboard shortcuts', chapters: 'Chapters', nChapters: '{n} chapters', soundOn: 'Sound on',
      startsAt: 'Starts at {t}', chapterN: 'Chapter {n}', rotate: 'Turn your phone sideways for full screen', tapSound: 'Tap for sound',
      linkCopied: 'Link to {t} copied', copiedHash: 'Copied {h}: add it to this file’s address', linkHere: 'Link to this moment: {u}',
      noSound: 'No sound: this browser cannot play the soundtrack ({c}). The picture plays silently.', cannotStart: 'This video could not start: {m}',
      keyboard: 'Keyboard', linksFoot: 'Links: add #t=1:05, #t=1:05-1:20 (that part, on a loop) or #chapter=2 to the address',
      rangeFrom: 'Plays {a} – {b} on a loop', rangeSet: 'Looping {a} – {b} · Esc clears', rangeOff: 'The whole video again',
      qOf: 'Question {n} of {m}', qPick: 'Pick an answer to go on', qRight: 'Right.', qWrong: 'Not quite.', qGo: 'Continue', qAuto: 'Going on in {s} s', qScore: '{r} of {n} right', qKeys: 'Answer the question · Enter: continue',
      keys: ['Play · pause', 'Back · forward 1 s', 'One frame (also , and .)', 'Back · forward 5 s', 'Jump to chapter 1 – 9 (no chapters: 10 – 90 %)',
        'Previous · next chapter (also Page Up / Down)', 'Start · End: last frame', 'Restart from the beginning', 'Mute · ↑ / ↓ volume',
        'Full screen', 'Copy a link to this moment (or to the part you picked)', 'On the bar: pick a part to loop and link (Esc clears)', 'Show · hide these keys'] },
    es: { play: 'Reproducir', replay: 'Volver a ver', playK: 'Reproducir (k)', pauseK: 'Pausa (k)', muteM: 'Silenciar (m)', unmuteM: 'Activar sonido (m)',
      seek: 'Posición', volume: 'Volumen', linkC: 'Copiar un enlace a este momento (c)', loop: 'Repetir', keysQ: 'Atajos de teclado (?)',
      fsF: 'Pantalla completa (f)', shortcuts: 'Atajos de teclado', chapters: 'Capítulos', nChapters: '{n} capítulos', soundOn: 'Con sonido',
      startsAt: 'Empieza en {t}', chapterN: 'Capítulo {n}', rotate: 'Gira el teléfono para verlo a pantalla completa', tapSound: 'Toca para activar el sonido',
      linkCopied: 'Enlace a {t} copiado', copiedHash: 'Copiado {h}: añádelo a la dirección de este archivo', linkHere: 'Enlace a este momento: {u}',
      noSound: 'Sin sonido: este navegador no puede reproducir el audio ({c}). La imagen se reproduce sin sonido.', cannotStart: 'Este vídeo no pudo empezar: {m}',
      keyboard: 'Teclado', linksFoot: 'Enlaces: añade #t=1:05, #t=1:05-1:20 (ese tramo, en bucle) o #chapter=2 a la dirección',
      rangeFrom: 'Reproduce {a} – {b} en bucle', rangeSet: 'En bucle: {a} – {b} · Esc lo quita', rangeOff: 'De nuevo el vídeo completo',
      qOf: 'Pregunta {n} de {m}', qPick: 'Elige una respuesta para seguir', qRight: 'Correcto.', qWrong: 'No exactamente.', qGo: 'Continuar', qAuto: 'Sigue en {s} s', qScore: '{r} de {n} correctas', qKeys: 'Responder la pregunta · Intro: continuar',
      keys: ['Reproducir · pausa', 'Atrás · adelante 1 s', 'Un fotograma (también , y .)', 'Atrás · adelante 5 s', 'Ir al capítulo 1 – 9 (sin capítulos: 10 – 90 %)',
        'Capítulo anterior · siguiente (también Re Pág / Av Pág)', 'Inicio · Fin: último fotograma', 'Empezar desde el principio', 'Silenciar · ↑ / ↓ volumen',
        'Pantalla completa', 'Copiar un enlace a este momento (o al tramo elegido)', 'En la barra: elige un tramo para repetirlo y enlazarlo (Esc lo quita)', 'Mostrar · ocultar estas teclas'] },
    fr: { play: 'Lire', replay: 'Revoir', playK: 'Lire (k)', pauseK: 'Pause (k)', muteM: 'Couper le son (m)', unmuteM: 'Rétablir le son (m)',
      seek: 'Position', volume: 'Volume', linkC: 'Copier un lien vers ce moment (c)', loop: 'Boucle', keysQ: 'Raccourcis clavier (?)',
      fsF: 'Plein écran (f)', shortcuts: 'Raccourcis clavier', chapters: 'Chapitres', nChapters: '{n} chapitres', soundOn: 'Avec son',
      startsAt: 'Commence à {t}', chapterN: 'Chapitre {n}', rotate: 'Tournez votre téléphone pour le plein écran', tapSound: 'Touchez pour le son',
      linkCopied: 'Lien vers {t} copié', copiedHash: '{h} copié : ajoutez-le à l’adresse de ce fichier', linkHere: 'Lien vers ce moment : {u}',
      noSound: 'Pas de son : ce navigateur ne peut pas lire la bande-son ({c}). L’image est lue sans son.', cannotStart: 'Cette vidéo n’a pas pu démarrer : {m}',
      keyboard: 'Clavier', linksFoot: 'Liens : ajoutez #t=1:05, #t=1:05-1:20 (ce passage, en boucle) ou #chapter=2 à l’adresse',
      rangeFrom: 'Lit {a} – {b} en boucle', rangeSet: 'En boucle : {a} – {b} · Échap pour annuler', rangeOff: 'Retour à la vidéo entière',
      qOf: 'Question {n} sur {m}', qPick: 'Choisissez une réponse pour continuer', qRight: 'Exact.', qWrong: 'Pas tout à fait.', qGo: 'Continuer', qAuto: 'Reprise dans {s} s', qScore: '{r} sur {n} justes', qKeys: 'Répondre à la question · Entrée : continuer',
      keys: ['Lecture · pause', 'Reculer · avancer de 1 s', 'Une image (aussi , et .)', 'Reculer · avancer de 5 s', 'Aller au chapitre 1 – 9 (sans chapitres : 10 – 90 %)',
        'Chapitre précédent · suivant (aussi Page préc. / suiv.)', 'Début · Fin : dernière image', 'Recommencer depuis le début', 'Couper le son · ↑ / ↓ volume',
        'Plein écran', 'Copier un lien vers ce moment (ou vers le passage choisi)', 'Sur la barre : choisir un passage à lire en boucle et à partager (Échap l’annule)', 'Afficher · masquer ces touches'] },
    pt: { play: 'Reproduzir', replay: 'Ver de novo', playK: 'Reproduzir (k)', pauseK: 'Pausar (k)', muteM: 'Silenciar (m)', unmuteM: 'Ativar som (m)',
      seek: 'Posição', volume: 'Volume', linkC: 'Copiar um link para este momento (c)', loop: 'Repetir', keysQ: 'Atalhos de teclado (?)',
      fsF: 'Tela cheia (f)', shortcuts: 'Atalhos de teclado', chapters: 'Capítulos', nChapters: '{n} capítulos', soundOn: 'Com som',
      startsAt: 'Começa em {t}', chapterN: 'Capítulo {n}', rotate: 'Gire o celular para ver em tela cheia', tapSound: 'Toque para ativar o som',
      linkCopied: 'Link para {t} copiado', copiedHash: '{h} copiado: adicione-o ao endereço deste arquivo', linkHere: 'Link para este momento: {u}',
      noSound: 'Sem som: este navegador não consegue reproduzir o áudio ({c}). A imagem é reproduzida sem som.', cannotStart: 'Não foi possível iniciar este vídeo: {m}',
      keyboard: 'Teclado', linksFoot: 'Links: adicione #t=1:05, #t=1:05-1:20 (esse trecho, em repetição) ou #chapter=2 ao endereço',
      rangeFrom: 'Reproduz {a} – {b} em repetição', rangeSet: 'Repetindo {a} – {b} · Esc para limpar', rangeOff: 'De volta ao vídeo inteiro',
      qOf: 'Pergunta {n} de {m}', qPick: 'Escolha uma resposta para continuar', qRight: 'Certo.', qWrong: 'Não exatamente.', qGo: 'Continuar', qAuto: 'Continua em {s} s', qScore: '{r} de {n} certas', qKeys: 'Responder à pergunta · Enter: continuar',
      keys: ['Reproduzir · pausar', 'Voltar · avançar 1 s', 'Um quadro (também , e .)', 'Voltar · avançar 5 s', 'Ir para o capítulo 1 – 9 (sem capítulos: 10 – 90 %)',
        'Capítulo anterior · próximo (também Page Up / Down)', 'Início · Fim: último quadro', 'Recomeçar do início', 'Silenciar · ↑ / ↓ volume',
        'Tela cheia', 'Copiar um link para este momento (ou para o trecho escolhido)', 'Na barra: escolha um trecho para repetir e compartilhar (Esc limpa)', 'Mostrar · ocultar estas teclas'] },
    de: { play: 'Abspielen', replay: 'Noch einmal', playK: 'Abspielen (k)', pauseK: 'Pause (k)', muteM: 'Stumm (m)', unmuteM: 'Ton an (m)',
      seek: 'Position', volume: 'Lautstärke', linkC: 'Link zu dieser Stelle kopieren (c)', loop: 'Schleife', keysQ: 'Tastenkürzel (?)',
      fsF: 'Vollbild (f)', shortcuts: 'Tastenkürzel', chapters: 'Kapitel', nChapters: '{n} Kapitel', soundOn: 'Mit Ton',
      startsAt: 'Beginnt bei {t}', chapterN: 'Kapitel {n}', rotate: 'Telefon für Vollbild quer halten', tapSound: 'Tippen für Ton',
      linkCopied: 'Link zu {t} kopiert', copiedHash: '{h} kopiert: an die Adresse dieser Datei anhängen', linkHere: 'Link zu dieser Stelle: {u}',
      noSound: 'Kein Ton: Dieser Browser kann die Tonspur nicht abspielen ({c}). Das Bild läuft ohne Ton.', cannotStart: 'Dieses Video konnte nicht starten: {m}',
      keyboard: 'Tastatur', linksFoot: 'Links: #t=1:05, #t=1:05-1:20 (dieser Abschnitt in Schleife) oder #chapter=2 an die Adresse anhängen',
      rangeFrom: 'Spielt {a} – {b} in Schleife', rangeSet: 'Schleife {a} – {b} · Esc hebt sie auf', rangeOff: 'Wieder das ganze Video',
      qOf: 'Frage {n} von {m}', qPick: 'Wähle eine Antwort, um weiterzumachen', qRight: 'Richtig.', qWrong: 'Nicht ganz.', qGo: 'Weiter', qAuto: 'Weiter in {s} s', qScore: '{r} von {n} richtig', qKeys: 'Frage beantworten · Enter: weiter',
      keys: ['Abspielen · Pause', 'Zurück · vor 1 s', 'Ein Bild (auch , und .)', 'Zurück · vor 5 s', 'Zu Kapitel 1 – 9 springen (ohne Kapitel: 10 – 90 %)',
        'Vorheriges · nächstes Kapitel (auch Bild ↑ / ↓)', 'Anfang · Ende: letztes Bild', 'Von vorn beginnen', 'Stumm · ↑ / ↓ Lautstärke',
        'Vollbild', 'Link zu dieser Stelle kopieren (oder zum gewählten Abschnitt)', 'Auf der Leiste: einen Abschnitt für Schleife und Link wählen (Esc hebt ihn auf)', 'Diese Tasten zeigen · ausblenden'] },
  };
  var LANG = String(M.lang || D.documentElement.getAttribute('lang') || 'en').toLowerCase().split('-')[0];
  var WD = WORDS[LANG] || WORDS.en;
  function tr(key, vars) {
    var s = WD[key] !== undefined ? WD[key] : WORDS.en[key];
    if (vars) for (var k in vars) s = s.split('{' + k + '}').join(vars[k]);
    return s;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  // ------------------------------------------------------------------ UI
  var controls = /^(full|minimal|none)$/.test(M.controls) ? M.controls : 'full';
  root.setAttribute('data-controls', controls);
  root.style.setProperty('--stp-ar', String(M.width / M.height));
  var TH = theme();
  applyTheme();
  // the start screen: the poster frame under a soft scrim, the title in the film's font, and a Play button
  var startScreen = controls !== 'none' && !M.autoplayMuted;
  if (startScreen) root.classList.add('has-start');
  // hosted: shown inside a host's sandboxed frame (an artifact viewer), where downloads and links
  // to the file do not work; `--target artifact` bakes it in, otherwise it is detected
  var hosted = M.host === 'artifact' || detectHosted();
  if (hosted) root.classList.add('is-hosted');
  var holder = $('.stp-holder', root);
  var poster = $('.stp-poster', root);
  var frame = D.createElement('iframe');
  frame.className = 'stp-frame';
  frame.title = M.title || 'video';
  frame.setAttribute('tabindex', '-1');
  frame.setAttribute('aria-hidden', 'true');
  // no allow="autoplay": the stage never plays media (footage is muted and seeked), and delegating
  // it logs a permissions-policy console error in some Chromium versions when opened from disk
  frame.width = M.width; frame.height = M.height;
  frame.style.width = M.width + 'px'; frame.style.height = M.height + 'px';
  holder.insertBefore(frame, holder.firstChild);

  var cover = D.createElement('div');
  cover.className = 'stp-cover';
  cover.innerHTML = '<button type="button" class="stp-big" aria-label="' + esc(tr('play')) + '">' + ICON.play + ICON.replay + '<span class="stp-big-l">' + esc(tr('replay')) + '</span></button>' +
    '<div class="stp-msg" role="status" hidden></div>';
  holder.appendChild(cover);
  var st = D.createElement('div');                  // start screen
  st.className = 'stp-start'; st.setAttribute('data-pos', 'bl');
  st.innerHTML = '<div class="stp-scrim"></div><div class="stp-sbox">' +
    '<div class="stp-kicker"></div><h1 class="stp-h"></h1><p class="stp-sub"></p>' +
    '<div class="stp-srow"><button type="button" class="stp-go">' + ICON.play + '<span class="l">' + esc(tr('play')) + '</span><span class="d"></span></button>' +
    '<span class="stp-smeta"></span></div><div class="stp-from"></div></div>';
  if (startScreen) holder.appendChild(st);
  var info = D.createElement('div');                // below the picture on a phone held upright
  info.className = 'stp-info';
  info.innerHTML = '<div class="stp-ihead"></div><ol class="stp-chlist" aria-label="' + esc(tr('chapters')) + '"></ol>' +
    '<p class="stp-rotate">' + ICON.rotate + '<span>' + esc(tr('rotate')) + '</span></p>';
  root.appendChild(info);
  var unmuteBtn = D.createElement('button');
  unmuteBtn.type = 'button'; unmuteBtn.className = 'stp-unmute'; unmuteBtn.hidden = true;
  unmuteBtn.innerHTML = ICON.muted + '<span>' + esc(tr('tapSound')) + '</span>';
  root.appendChild(unmuteBtn);
  var toastEl = D.createElement('div');
  toastEl.className = 'stp-toast'; toastEl.setAttribute('role', 'status'); toastEl.hidden = true;
  root.appendChild(toastEl);
  // what the stage reports as missing (a font, a stylesheet): always in the console, and on screen
  // when the address asks for it (#st-debug), for whoever checks an export in a host page
  var devNotes = [], devEl = null;
  var devOn = (function () { try { return /(^|[#&?])st-debug\b/.test(W.location.hash + '&' + W.location.search); } catch (e) { return false; } })();
  function devNote(m) {
    m = String(m || '');
    if (!m || devNotes.indexOf(m) >= 0 || devNotes.length >= 12) return;
    devNotes.push(m);
    try { console.warn('[showtime] ' + m); } catch (e) { /* ignore */ }
    if (!devOn) return;
    if (!devEl) { devEl = D.createElement('div'); devEl.className = 'stp-dev'; root.appendChild(devEl); }
    devEl.textContent = devNotes.join('\n');
  }

  var bar = D.createElement('div');
  bar.className = 'stp-bar';
  bar.innerHTML =
    '<div class="stp-scrub" role="slider" tabindex="0" aria-label="' + esc(tr('seek')) + '" aria-valuemin="0" aria-valuemax="' + (Number(M.duration) || 0) + '" aria-valuenow="0">' +
      '<div class="stp-rail"><div class="stp-buf"></div><div class="stp-hover"></div><div class="stp-fill"></div><div class="stp-range" hidden></div><div class="stp-ticks"></div></div>' +
      '<div class="stp-knob"></div><div class="stp-tip" hidden></div></div>' +
    '<div class="stp-row">' +
      '<button type="button" class="stp-btn stp-play" aria-label="' + esc(tr('playK')) + '">' + ICON.play + ICON.pause + '</button>' +
      '<button type="button" class="stp-btn stp-mute" aria-label="' + esc(tr('muteM')) + '">' + ICON.vol + ICON.muted + '</button>' +
      '<input class="stp-vol" type="range" min="0" max="1" step="0.05" value="1" aria-label="' + esc(tr('volume')) + '">' +
      '<div class="stp-time" aria-live="off"><b>0:00</b> <span>/ 0:00</span></div>' +
      '<button type="button" class="stp-chapter" aria-haspopup="true" aria-expanded="false" hidden></button>' +
      '<div class="stp-spacer"></div>' +
      '<button type="button" class="stp-btn stp-link" aria-label="' + esc(tr('linkC')) + '" title="' + esc(tr('linkC')) + '">' + ICON.link + '</button>' +
      '<button type="button" class="stp-btn stp-loop" aria-label="' + esc(tr('loop')) + '" aria-pressed="false" title="' + esc(tr('loop')) + '">' + ICON.loop + '</button>' +
      '<button type="button" class="stp-btn stp-keys" aria-label="' + esc(tr('keysQ')) + '" title="' + esc(tr('keysQ')) + '">?</button>' +
      '<button type="button" class="stp-btn stp-fs" aria-label="' + esc(tr('fsF')) + '" title="' + esc(tr('fsF')) + '">' + ICON.fsEnter + ICON.fsExit + '</button>' +
    '</div>' +
    '<div class="stp-chmenu" role="menu" hidden></div>';
  root.appendChild(bar);
  var help = D.createElement('div');
  help.className = 'stp-help'; help.hidden = true; help.setAttribute('role', 'dialog'); help.setAttribute('aria-label', tr('shortcuts'));
  root.appendChild(help);
  var bigBtn = $('.stp-big', cover), msgEl = $('.stp-msg', cover), goBtn = $('.stp-go', st), sbox = $('.stp-sbox', st), textBoxes = null, posterLuma = null;
  var scrub = $('.stp-scrub', bar), fillEl = $('.stp-fill', bar), hoverEl = $('.stp-hover', bar), knob = $('.stp-knob', bar), bufEl = $('.stp-buf', bar);
  var rangeEl = $('.stp-range', bar), tip = $('.stp-tip', bar), ticksEl = $('.stp-ticks', bar), timeEl = $('.stp-time', bar), chapEl = $('.stp-chapter', bar), chMenu = $('.stp-chmenu', bar);
  var playBtn = $('.stp-play', bar), muteBtn = $('.stp-mute', bar), volEl = $('.stp-vol', bar), loopBtn = $('.stp-loop', bar), fsBtn = $('.stp-fs', bar);
  var linkBtn = $('.stp-link', bar), keysBtn = $('.stp-keys', bar), chList = $('.stp-chlist', info), ihead = $('.stp-ihead', info);
  var fsOK = !!(D.fullscreenEnabled || D.webkitFullscreenEnabled);
  if (!fsOK) fsBtn.hidden = true;
  if (hosted) linkBtn.hidden = true;       // a link to the file means nothing inside a host's frame
  var coarse = !!(W.matchMedia && W.matchMedia('(pointer: coarse)').matches);
  if (coarse) root.classList.add('is-coarse');

  function cls(name, on) { root.classList[on ? 'add' : 'remove'](name); }
  function message(text) { msgEl.textContent = text || ''; msgEl.hidden = !text; }
  var toastTimer = null;
  function toast(text, ms) {
    toastEl.textContent = text; toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, ms || 2600);
  }
  function fmt(t) {
    t = Math.max(0, t || 0);
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60);
    var ss = (s < 10 ? '0' : '') + s;
    return h ? h + ':' + (m < 10 ? '0' : '') + m + ':' + ss : m + ':' + ss;
  }

  // ------------------------------------------------------------------ colours from the film
  function rgbOf(c) {
    c = String(c || '').trim();
    var m = /^#([0-9a-f]{3,8})$/i.exec(c);
    if (m) {
      var h = m[1];
      if (h.length === 3 || h.length === 4) h = h.replace(/./g, '$&$&');
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(c);
    return m ? [+m[1], +m[2], +m[3]] : null;
  }
  function lum(rgb) {
    var f = function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2]);
  }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function css(rgb, a) { return a === undefined ? 'rgb(' + rgb.join(' ') + ')' : 'rgb(' + rgb.join(' ') + ' / ' + a + ')'; }
  function mix(a, b, t) { return [0, 1, 2].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * t); }); }
  /** Chrome colours: the film's ground, ink and accent, each kept only where it reads (WCAG). */
  function theme() {
    var c = (M.start && M.start.colors) || {};
    var bg = rgbOf(M.background) || rgbOf(c.bg) || [0, 0, 0];
    var dark = lum(bg) < 0.4;
    var ink = rgbOf(c.ink);
    if (!ink || contrast(ink, bg) < 7) ink = dark ? [246, 246, 248] : [16, 17, 20];
    var muted = rgbOf(c.muted);
    if (!muted || contrast(muted, bg) < 5.5) muted = mix(ink, bg, 0.22);
    var accent = rgbOf(c.accent);
    if (!accent || contrast(accent, bg) < 3) accent = ink;         // the Play button must stand out as a shape
    var onAccent = contrast([255, 255, 255], accent) >= contrast([12, 12, 14], accent) ? [255, 255, 255] : [12, 12, 14];
    if (contrast(onAccent, accent) < 4.5) { accent = ink; onAccent = bg; }
    var accentText = contrast(accent, bg) >= 4.5 ? accent : ink;
    return { bg: bg, ink: ink, muted: muted, accent: accent, onAccent: onAccent, accentText: accentText, dark: dark, panel: mix(bg, ink, dark ? 0.07 : 0.05) };
  }
  function applyTheme() {
    var s = root.style;
    s.setProperty('--stp-bg', css(TH.bg));
    s.setProperty('--stp-bg-rgb', TH.bg.join(' '));
    s.setProperty('--stp-ink', css(TH.ink));
    s.setProperty('--stp-muted', css(TH.muted));
    s.setProperty('--stp-accent', css(TH.accent));
    s.setProperty('--stp-on-accent', css(TH.onAccent));
    s.setProperty('--stp-accent-text', css(TH.accentText));
    s.setProperty('--stp-panel2', css(TH.panel));
    s.setProperty('--stp-line', css(TH.ink, 0.12));
    root.setAttribute('data-ground', TH.dark ? 'dark' : 'light');
    D.documentElement.style.background = css(TH.bg);
    D.body.style.background = css(TH.bg);
    var tc = D.querySelector('meta[name="theme-color"]');
    if (!tc) { tc = D.createElement('meta'); tc.name = 'theme-color'; D.head.appendChild(tc); }
    tc.content = '#' + TH.bg.map(function (v) { return (v < 16 ? '0' : '') + v.toString(16); }).join('');
  }
  function detectHosted() {
    var inFrame = true;
    try { inFrame = W.self !== W.top; } catch (e) { inFrame = true; }
    if (!inFrame) return false;
    var origin = '';
    try { origin = String(W.origin !== undefined ? W.origin : W.location.origin); } catch (e) { origin = 'null'; }   // the document's origin: 'null' when sandboxed
    if (origin === 'null') return true;             // a sandboxed frame: no downloads, no address of its own
    var names = [];
    try { names.push(W.location.hostname); } catch (e) { /* ignore */ }
    try { var ao = W.location.ancestorOrigins; for (var i = 0; ao && i < ao.length; i++) names.push(ao[i]); } catch (e) { /* ignore */ }
    try { names.push(D.referrer); } catch (e) { /* ignore */ }
    return names.some(function (n) { return /(^|[./])(claude\.ai|claudeusercontent\.com|anthropic\.com)(?=$|[:/])/i.test(String(n || '')); });
  }

  // ------------------------------------------------------------------ layout
  // overlay: the picture fits the window and the controls float over it (auto-hiding);
  // stacked: a phone held upright with a landscape film: the picture full width at the top, the
  // title and chapters under it, the controls docked at the bottom within thumb reach
  var probe = D.createElement('div');
  probe.className = 'stp-safe';
  root.appendChild(probe);
  var mode = '';
  function insets() {
    var cs = getComputedStyle(probe);
    return { t: parseFloat(cs.paddingTop) || 0, r: parseFloat(cs.paddingRight) || 0, b: parseFloat(cs.paddingBottom) || 0, l: parseFloat(cs.paddingLeft) || 0 };
  }
  function layout() {
    var vw = root.clientWidth || W.innerWidth, vh = root.clientHeight || W.innerHeight;
    if (!(vw > 0 && vh > 0)) return;
    var ar = M.width / M.height, s = insets(), fs = !!(D.fullscreenElement || D.webkitFullscreenElement);
    var w, h, x, y;
    var stacked = !fs && controls !== 'none' && vh > vw && vw / ar + s.t + 260 <= vh;
    var m = stacked ? 'stacked' : 'overlay';
    if (stacked) {
      w = vw; h = Math.round(vw / ar); x = 0; y = s.t;
    } else {
      var aw = Math.max(1, vw - s.l - s.r), ah = Math.max(1, vh - s.t - s.b);
      w = Math.min(aw, ah * ar); h = w / ar;
      if (vw >= vh * ar - 1 && vh >= vw / ar - 1) { w = Math.min(vw, vh * ar); h = w / ar; } // fits whole: no need to dodge insets
      w = Math.round(w); h = Math.round(h);
      x = Math.round((vw - w) / 2); y = Math.round((vh - h) / 2);
    }
    holder.style.width = w + 'px'; holder.style.height = h + 'px';
    holder.style.left = x + 'px'; holder.style.top = y + 'px';
    root.style.setProperty('--stp-vh', h + 'px');
    root.style.setProperty('--stp-vy', y + 'px');
    if (m !== mode) {
      mode = m;
      root.setAttribute('data-layout', m);
      cls('is-stacked', m === 'stacked');
      placeStart();
      qPlace();
    }
    if (m === 'overlay') {
      bar.style.left = x + 'px'; bar.style.width = w + 'px'; bar.style.bottom = Math.max(0, vh - y - h) + 'px';
      // a question card floats over the bottom of the picture, above the controls
      root.style.setProperty('--stp-qb', (Math.max(0, vh - y - h) + (controls === 'none' ? 0 : (bar.offsetHeight || 92)) + 8) + 'px');
      root.style.setProperty('--stp-qx', (x + w / 2) + 'px');
      root.style.setProperty('--stp-qw', w + 'px');
    } else { bar.style.left = ''; bar.style.width = ''; bar.style.bottom = ''; }
    var sc = w / M.width;
    if (sc > 0) frame.style.transform = 'scale(' + sc + ')';
    if (m === 'overlay' && startScreen && !S.started) fitStart();
  }
  if (W.ResizeObserver) new ResizeObserver(layout).observe(root);
  W.addEventListener('resize', layout);
  W.addEventListener('orientationchange', function () { setTimeout(layout, 60); });

  // ------------------------------------------------------------------ chapters
  var chapters = (M.chapters || []).filter(function (c) { return c && isFinite(c.t) && c.t >= 0 && c.t < M.duration; })
    .sort(function (a, b) { return a.t - b.t; });
  function drawTicks() {
    ticksEl.innerHTML = chapters.filter(function (c) { return c.t > 0.05; }).map(function (c) {
      return '<i style="left:' + (100 * c.t / DUR).toFixed(3) + '%"></i>';
    }).join('');
    if (QST) qMarks();
    drawRange();
  }
  /** The range on the scrubber (a band from its start to its end); sel: a range being picked. */
  function drawRange(sel) {
    var r = sel || RANGE;
    if (!rangeEl) return;
    rangeEl.hidden = !r || !(DUR > 0);
    if (rangeEl.hidden) return;
    rangeEl.style.left = (100 * r.a / DUR).toFixed(3) + '%';
    rangeEl.style.width = (100 * (r.b - r.a) / DUR).toFixed(3) + '%';
    rangeEl.classList.toggle('is-picking', !!sel);
    scrub.setAttribute('aria-description', fmt(r.a) + ' – ' + fmt(r.b));
  }
  function chapterIndex(t) {
    var cur = -1;
    for (var i = 0; i < chapters.length; i++) if (t + 1e-6 >= chapters[i].t) cur = i;
    return cur;
  }
  function chapterAt(t) { var i = chapterIndex(t); return i >= 0 && chapters[i].label ? chapters[i].label : ''; }
  function chapterName(i) { return chapters[i] ? (chapters[i].label || tr('chapterN', { n: i + 1 })) : ''; }
  if (chapters.length > 1 || (chapters.length === 1 && chapters[0].label)) {
    chapEl.hidden = false;
    chMenu.innerHTML = chapters.map(function (c, i) {
      return '<button type="button" role="menuitem" data-i="' + i + '"><span class="n">' + (i < 9 ? i + 1 : '') + '</span>' +
        '<span class="l"></span><span class="t">' + fmt(c.t) + '</span></button>';
    }).join('');
    Array.prototype.forEach.call(chMenu.querySelectorAll('button'), function (b, i) { b.querySelector('.l').textContent = chapterName(i); });
  }

  // ------------------------------------------------------------------ deep links (#t=12.5, #t=1:05, #t=10-20, #chapter=2 or =name)
  function parseTime(v) {
    v = String(v || '').trim();
    var m;
    if ((m = /^(\d+(?:\.\d+)?)s?$/.exec(v))) return parseFloat(m[1]);
    if ((m = /^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$/.exec(v))) return (m[1] ? +m[1] * 3600 : 0) + +m[2] * 60 + parseFloat(m[3]);
    if ((m = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$/.exec(v)) && (m[1] || m[2] || m[3])) return (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (parseFloat(m[3]) || 0);
    return null;
  }
  function slug(s) { return String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }
  function findChapter(v) {
    v = decodeURIComponent(String(v || '')).trim();
    if (/^\d+$/.test(v)) { var i = +v - 1; return chapters[i] ? i : -1; }
    var want = slug(v);
    for (var k = 0; k < chapters.length; k++) if (slug(chapters[k].label) === want) return k;
    for (var j = 0; j < chapters.length; j++) if (want && slug(chapters[j].label).indexOf(want) === 0) return j;
    return -1;
  }
  /**
   * What a #fragment asks for: {t, range} (null if nothing). #t=10-20 (also 1:05-1:20, or 10,20 as in media
   * fragments) is a range {a, b}: it starts at a and loops back at b; a range shorter than two frames is a time.
   */
  function linkTarget(hash) {
    var q = String(hash || '').replace(/^#/, '');
    if (!q) return null;
    var out = null, range = null, end = Math.max(0, M.duration - 1 / (M.fps || 30));
    q.split('&').forEach(function (kv) {
      var p = kv.split('='), k = decodeURIComponent(p[0] || '').toLowerCase(), v = decodeURIComponent(p.slice(1).join('='));
      if (k === 't' || k === 'time' || k === 'at') {
        var m = /^([^,-]+)[-,]([^,-]+)$/.exec(v.trim());
        var a = m ? parseTime(m[1]) : parseTime(v), b = m ? parseTime(m[2]) : null;
        if (a === null) return;
        out = a; range = null;
        if (b !== null) {
          a = clamp(a, 0, end); b = clamp(b, 0, M.duration);
          if (b - a >= 2 / (M.fps || 30)) range = { a: a, b: b };
        }
      } else if (k === 'chapter' || k === 'ch' || k === 'c') { var i = findChapter(v); if (i >= 0) { out = chapters[i].t; range = null; } }
    });
    return out === null ? null : { t: clamp(out, 0, end), range: range };
  }
  /** Time a #fragment asks for (null if none): a range's start. */
  function linkTime(hash) { var x = linkTarget(hash); return x ? x.t : null; }
  function currentHash() { try { return W.location.hash || ''; } catch (e) { return ''; } }
  var startAt = linkTime(currentHash());
  var RANGE = (linkTarget(currentHash()) || {}).range || null, loopBefore = null;
  function secs(t) { return String(Math.round(t * 10) / 10); }
  function linkHere(t, r) {
    var h = r ? '#t=' + secs(r.a) + '-' + secs(r.b) : '#t=' + secs(t);
    var href = '';
    try { href = String(W.location.href || ''); } catch (e) { href = ''; }
    var base = /^(https?|file):/i.test(href) ? href.split('#')[0] : '';
    return { url: base + h, hash: h, full: !!base, range: r ? { a: r.a, b: r.b } : null };
  }
  function copyText(text) {
    var fallback = function () {
      try {
        var ta = D.createElement('textarea');
        ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;left:-9999px;top:0';
        D.body.appendChild(ta); ta.select();
        var ok = D.execCommand && D.execCommand('copy');
        D.body.removeChild(ta);
        return Promise.resolve(!!ok);
      } catch (e) { return Promise.resolve(false); }
    };
    try {
      if (W.navigator && navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(function () { return true; }, fallback);
      }
    } catch (e) { /* use the fallback */ }
    return fallback();
  }
  function copyLink() {
    var l = linkHere(S.t, RANGE);
    var what = RANGE ? fmt(RANGE.a) + ' – ' + fmt(RANGE.b) : fmt(S.t);
    copyText(l.url).then(function (ok) {
      if (ok && l.full) toast(tr('linkCopied', { t: what }));
      else if (ok) toast(tr('copiedHash', { h: l.hash }));
      else toast(tr('linkHere', { u: l.url }), 6000);
    });
    emit('link', l);
    return l;
  }

  // ------------------------------------------------------------------ state + clock
  var S = {
    t: 0, playing: false, ready: false, started: false, ended: false, loop: !!M.loop,
    muted: false, volume: 1, lastFrame: -1, busy: false, pending: false, wallT0: 0, wallP0: 0,
    child: null, wantPlay: false, error: null,
  };
  var fps = M.fps, DUR = M.duration;
  var lastFrameT = Math.max(0, (Math.round(DUR * fps) - 1) / fps);
  // A range (#t=10-20, or shift + drag on the scrubber) plays from its start and loops back at its end: the
  // loop button turns on with it (turned off, play stops at the end). Seeking outside the range leaves it.
  function setRange(r, quiet) {
    if (r && !(r.b - r.a >= 2 / fps)) r = null;
    if (r && !RANGE) loopBefore = S.loop;
    if (!r && RANGE && loopBefore !== null) { S.loop = loopBefore; loopBefore = null; }
    RANGE = r ? { a: clamp(r.a, 0, lastFrameT), b: clamp(r.b, 0, DUR) } : null;
    if (RANGE) S.loop = true;
    loopBtn.setAttribute('aria-pressed', String(S.loop));
    if (!RANGE) scrub.removeAttribute('aria-description');
    drawRange();
    if (!quiet) toast(RANGE ? tr('rangeSet', { a: fmt(RANGE.a), b: fmt(RANGE.b) }) : tr('rangeOff'), 2000);
    emit('range', RANGE ? { a: RANGE.a, b: RANGE.b } : null);
  }
  function inRange(t) { return !!RANGE && t >= RANGE.a - 0.5 / fps && t <= RANGE.b + 0.5 / fps; }
  /** The last frame inside the range (where play stops when the loop is off). */
  function rangeLast() { return Math.max(RANGE.a, Math.min(lastFrameT, Math.ceil(RANGE.b * fps - 1e-6) / fps - 1 / fps)); }
  drawTicks();
  drawChapterList();
  layout();
  var listeners = {};
  function emit(name, detail) {
    (listeners[name] || []).slice().forEach(function (fn) { try { fn(detail); } catch (e) { /* ignore */ } });
    try { root.dispatchEvent(new CustomEvent('showtime:' + name, { detail: detail })); } catch (e) { /* ignore */ }
  }
  try {
    var saved = JSON.parse(W.localStorage.getItem('showtime-player') || 'null');
    if (saved && typeof saved.volume === 'number') S.volume = clamp(saved.volume, 0, 1);
  } catch (e) { /* storage unavailable */ }
  volEl.value = String(S.volume);
  // before the first play the frame behind the start screen is the poster frame
  if (typeof M.poster === 'number' && isFinite(M.poster)) S.t = clamp(M.poster, 0, lastFrameT);
  else if (startScreen) S.t = clamp(DUR * 0.4, 0, lastFrameT);

  // The sound. Two kinds share one interface ({time(), play(t), pause(), seek(t), setVolume(),
  // unlock(), ready(), buffering(), facade}): an <audio> element (embedded soundtrack, or a score
  // rendered whole), and the live score stream. time() is the film time being heard now, or null
  // when the sound is not driving the clock (then the wall clock does).
  var SND = null;

  /** <audio> element sound. */
  function ElementSound(src) {
    var A = D.createElement('audio');
    A.preload = 'auto';
    A.setAttribute('playsinline', '');
    A.volume = S.volume;
    root.appendChild(A);
    var E = { el: A, kind: 'element', hasSrc: false, failed: false, lastT: -1, lastP: 0, t0: null, p0: 0, moving: false, holdT: 0,
      detached: false, blob: null, swapping: false };
    if (src) { A.src = src; E.hasSrc = true; }
    A.addEventListener('ended', function () { if (S.playing) anchorWall(S.t); });
    E.ready = function () { return !!(E.hasSrc && A.readyState >= 2 && !E.failed); };
    E.drives = function () { return !E.detached && !A.paused && !A.ended && E.ready(); };
    // A --folder export served without HTTP Range requests (python -m http.server and other simple servers):
    // the element cannot seek past what it has downloaded and plays on from where it was, so the clock stalled
    // after a seek. Then the soundtrack is read whole into a blob (always seekable) and swapped in; until it
    // is, the sound stops driving the clock (the picture plays on by the wall clock) and the element is paused.
    // When that read fails, the next seek tries it again (or seeks the element itself where it can get to).
    function remote() { return /^https?:/i.test(String(A.currentSrc || A.src || '')); }
    function canSeek(t) {
      try {
        var s = A.seekable;
        if (!s || !isFinite(A.duration)) return true;    // not known yet: the seek is tried as usual
        for (var i = 0; i < s.length; i++) if (s.start(i) <= t + 0.05 && t <= s.end(i) + 0.25) return true;
      } catch (e) { return true; }
      return false;
    }
    function fetchBlob() {
      if (!E.blob && remote() && typeof fetch === 'function') {
        E.blob = fetch(A.currentSrc || A.src).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); });
        E.blob.catch(function () {});
      }
      return E.blob;
    }
    function swapIn() {
      if (E.swapping) return;
      var p = fetchBlob();
      if (!p) { E.detached = false; return; }
      E.swapping = true;
      p.then(function (b) {
        A.addEventListener('canplay', function () {
          E.swapping = false;
          E.detached = false;
          E.reset();
          try { A.currentTime = Math.min(S.t, A.duration || S.t); } catch (e) { /* ignore */ }
          A.muted = S.muted;
          if (S.playing) A.play().catch(function () {});
        }, { once: true });
        A.src = URL.createObjectURL(b);
        try { A.load(); } catch (e) { /* ignore */ }
      }).catch(function (e) {
        // forget the failed read (kept, every later seek waited on it and the sound stayed detached for the rest
        // of the session); a plain seek where the element can get to, else the sound waits for the next seek
        E.swapping = false; E.blob = null;
        if (canSeek(S.t)) {
          E.reset();
          try { seekEl(Math.min(S.t, A.duration || S.t)); } catch (x) { /* ignore */ }
          A.muted = S.muted;
          if (S.playing) A.play().catch(function () {});
        }
        reportChild('the soundtrack could not be read whole for seeking: ' + (e && e.message || e));
      });
    }
    /** Seek the element to t, or, when it cannot get there (no Range support), detach it until the blob is in. */
    function seekEl(t) {
      if (!remote() || (!E.swapping && canSeek(t))) { E.detached = false; A.currentTime = t; return true; }   // blob:, data:, file: seek
      E.detached = true;
      if (!A.paused) A.pause();
      swapIn();
      return false;
    }
    A.addEventListener('loadedmetadata', function () {
      // not seekable to the end once the length is known: read the file whole now (swapped in at the first
      // seek it needs), so that seek waits for little or nothing
      if (remote() && isFinite(A.duration) && !canSeek(Math.max(0, A.duration - 1))) fetchBlob();
    });
    E.reset = function () { E.lastT = -1; E.t0 = null; E.moving = false; E.holdT = S.t; };
    E.time = function () {
      if (!E.drives()) return null;
      var at = A.currentTime, p = now();
      if (!E.moving) {
        // after play() or a seek the element's clock sits still until the sound actually starts
        if (E.t0 === null) { E.t0 = at; E.p0 = p; }
        if (at === E.t0 && p - E.p0 < 700) return E.holdT;
        E.moving = true; E.lastT = at; E.lastP = p;
      }
      if (at !== E.lastT) { E.lastT = at; E.lastP = p; }
      return at + Math.min(0.25, (p - E.lastP) / 1000);
    };
    E.play = function (t) {
      E.reset();
      if (!E.ready() || E.swapping) return;    // swapping: the swap starts it at the film's time
      try { if (Math.abs(A.currentTime - t) > 0.02 && !seekEl(Math.min(t, (A.duration || t)))) return; } catch (e) { /* ignore */ }
      A.muted = S.muted;
      var pr = A.play();
      if (pr && pr.catch) pr.catch(function () { if (S.playing && !A.muted) { S.muted = true; A.muted = true; unmuteBtn.hidden = false; renderUI(); A.play().catch(function () {}); } });
    };
    E.pause = function () { if (!A.paused) A.pause(); };
    E.seek = function (t) {
      E.reset();
      if (!E.ready() || E.swapping) return;
      try { if (!seekEl(t)) return; } catch (e) { /* ignore */ }
      if (S.playing && A.paused) A.play().catch(function () {});
    };
    E.setVolume = function () { A.volume = S.volume; A.muted = S.muted; };
    E.resumeIfPaused = function () { if (S.playing && A.paused && !E.detached) A.play().catch(function () {}); };
    E.buffering = function () { return false; };
    var SILENT = 'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAgLsAAAB3AQACABAAZGF0YQIAAAAAAA==';
    var unlocked = false;
    /** Safari only lets an element start sound inside a user gesture: play something short in it now. */
    E.unlock = function () {
      if (unlocked) return;
      unlocked = true;
      if (E.hasSrc) return; // a real source: play() inside the same gesture follows
      try { A.src = SILENT; var p = A.play(); if (p && p.catch) p.catch(function () {}); } catch (e) { /* ignore */ }
    };
    E.setSource = function (url) { A.src = url; E.hasSrc = true; };
    E.wait = function () {
      if (!E.hasSrc || A.readyState >= 3) return Promise.resolve();
      return new Promise(function (res) {
        var done = function () { res(); };
        A.addEventListener('canplay', done, { once: true });
        A.addEventListener('error', function () { E.failed = true; res(); }, { once: true });
        setTimeout(done, 8000);
        try { A.load(); } catch (e) { /* ignore */ }
      });
    };
    E.facade = A;
    return E;
  }

  /**
   * Live score: the page's ST.score rendered in pieces by the stage document (an OfflineAudioContext
   * per piece, each started a little early so reverb tails and compressors are settled where it
   * begins), limited to the export's loudness, and played through Web Audio. Pieces are rendered
   * ahead of the playhead first, then the rest of the film in the background; a seek plays at once
   * when that stretch is rendered, else as soon as its piece is (usually well under a second).
   */
  function LiveSound(child, o) {
    var sr = 48000, N = Math.max(1, Math.ceil(DUR * sr));
    var pcm = [new Float32Array(N), new Float32Array(N)];
    var have = [];                    // rendered sample ranges [a, b), sorted, merged
    var jobs = [];                    // pieces being rendered
    var PRE = 2.5, LEAD = 0.05, AHEAD = 3, PIECE = 4;
    var ctx = null, out = null, srcs = [];
    var L = {
      kind: 'score', playing: false, stalled: false, stallS: 0, anchorS: 0, anchorCtx: 0, schedS: 0, want: 0,
      speed: 0, pieces: 0, firstMs: null, error: null, t0: now(), feedTimer: null, seams: [],
    };
    function runEnd(s) {                // end of the rendered run holding sample s, or -1
      for (var i = 0; i < have.length; i++) if (s >= have[i][0] && s < have[i][1]) return have[i][1];
      return -1;
    }
    function addRange(a, b) {
      have.push([a, b]);
      have.sort(function (x, y) { return x[0] - y[0]; });
      var m = [];
      have.forEach(function (r) {
        var last = m[m.length - 1];
        if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]); else m.push([r[0], r[1]]);
      });
      have = m;
    }
    function firstGap(s) {
      for (var guard = 0; guard < 1000 && s < N; guard++) {
        var moved = false;
        for (var i = 0; i < have.length; i++) if (s >= have[i][0] && s < have[i][1]) { s = have[i][1]; moved = true; }
        for (var j = 0; j < jobs.length; j++) if (s >= jobs[j].a && s < jobs[j].b) { s = jobs[j].b; moved = true; }
        if (!moved) return s;
      }
      return s < N ? s : null;
    }
    function nextBoundary(a) {          // first rendered or rendering sample after a
      var b = N;
      have.forEach(function (r) { if (r[0] > a && r[0] < b) b = r[0]; });
      jobs.forEach(function (j) { if (j.a > a && j.a < b) b = j.a; });
      return b;
    }
    function pieceLen(urgent, first) {
      // the piece the playhead waits for is short (first sound fast); the others take about half a
      // second each to render on this machine
      var sec = first ? 1.5 : urgent ? 2.5 : clamp((L.speed || 4) * 0.6 - PRE, 3, 12);
      return Math.round(sec * sr);
    }
    function pump() {
      var p = L.want, e = runEnd(p);
      // while the playhead waits for sound, its piece renders alone (it gets the whole machine)
      var waiting = (e < 0 || e - p < sr * 1.5) && e < N;
      var busyUrgent = jobs.some(function (j) { return j.urgent; });
      while (jobs.length < (waiting && busyUrgent ? 1 : 2)) {
        var a = firstGap(p), urgent = true;
        if (a === null || a >= N) { a = firstGap(0); urgent = false; }
        if (a === null || a >= N) return;
        if (a - p > sr * 1.5) urgent = false;
        var b = Math.min(N, a + pieceLen(urgent, urgent && a === p && e < 0), nextBoundary(a));
        if (b <= a) return;
        render(a, b, urgent);
        if (urgent && waiting) busyUrgent = true;
      }
    }
    function render(a, b, urgent) {
      // the piece's render starts PRE seconds early (reverb tails and compressors settle), on a
      // multiple of the 128-sample render quantum: a render from 0 then has every sound at the same
      // place inside its quantum, so the pieces match it sample for sample
      var f0 = Math.floor(Math.max(0, a - PRE * sr) / 128) * 128, pre = a - f0, job = { a: a, b: b, urgent: !!urgent }, t0 = now();
      jobs.push(job);
      child.renderScore({ sampleRate: sr, from: f0 / sr, duration: (b - f0) / sr }).then(function (buf) {
        jobs.splice(jobs.indexOf(job), 1);
        if (!buf) throw new Error('the score rendered nothing');
        var chs = [buf.getChannelData(0), buf.getChannelData(Math.min(1, buf.numberOfChannels - 1))];
        var lim = W.__stLimit ? W.__stLimit(chs, sr, o.gainDb || 0, o.ceilDb === undefined ? -1.5 : o.ceilDb) : chs;
        var n = Math.min(b - a, lim[0].length - pre);
        for (var c = 0; c < 2; c++) pcm[c].set(lim[c].subarray(pre, pre + n), a);
        if (n > 0) { addRange(a, a + n); if (a > 0) L.seams.push(a / sr); }
        var wall = Math.max(1, now() - t0) / 1000, sp = ((b - f0) / sr) / wall;
        L.speed = L.speed ? L.speed * 0.6 + sp * 0.4 : sp;
        L.pieces++;
        if (L.firstMs === null) L.firstMs = Math.round(now() - L.t0);
        rendered();
        pump();
      }).catch(function (e) {
        var k = jobs.indexOf(job);
        if (k >= 0) jobs.splice(k, 1);
        L.error = String(e && e.message || e);
        reportChild('score: ' + L.error);
        // play on: this piece stays silent rather than being retried forever
        addRange(a, b);
        rendered();
        pump();
      });
    }
    function rendered() {
      if (L.playing && L.stalled) {
        var e = runEnd(L.stallS);
        if (e >= 0 && (e - L.stallS >= sr * 0.5 || e >= N)) begin(L.stallS);
      } else feed();
      renderBuf();
    }
    function ensureCtx() {
      if (ctx) return ctx;
      ctx = earlyCtx || makeCtx();
      if (!ctx) return null;
      out = ctx.createGain();
      out.connect(ctx.destination);
      L.setVolume();
      return ctx;
    }
    function running() { return !!(ctx && ctx.state === 'running'); }
    function audibleNow() {
      // the context time of the sound leaving the speakers now (currentTime runs ahead by the output latency)
      try {
        var ts = ctx.getOutputTimestamp && ctx.getOutputTimestamp();
        if (ts && ts.contextTime > 0 && ts.performanceTime > 0) return ts.contextTime + Math.max(0, now() - ts.performanceTime) / 1000;
      } catch (e) { /* fall through */ }
      return ctx.currentTime - (ctx.baseLatency || 0);
    }
    function stopAll() {
      srcs.forEach(function (s) { try { s.onended = null; s.stop(); s.disconnect(); } catch (e) { /* gone */ } });
      srcs = [];
    }
    function begin(s) {                 // start hearing sample s now (or wait for it)
      stopAll();
      var e = runEnd(s);
      if (e < 0 || (e - s < sr * 0.5 && e < N)) { L.stalled = true; L.stallS = s; L.want = s; pump(); return; }
      L.stalled = false;
      L.anchorS = s; L.schedS = s;
      L.anchorCtx = Math.ceil((ctx.currentTime + LEAD) * sr) / sr;
      feed();
    }
    function feed() {                   // keep a few seconds of sound queued (pieces meet sample-exactly)
      if (!L.playing || L.stalled || !running()) return;
      var playS = L.anchorS + Math.max(0, ctx.currentTime - L.anchorCtx) * sr;
      L.want = Math.round(playS);
      for (var guard = 0; guard < 16 && L.schedS < N && L.schedS - playS < AHEAD * sr; guard++) {
        var e = runEnd(L.schedS);
        if (e <= L.schedS) break;
        e = Math.min(e, L.schedS + PIECE * sr);
        var len = e - L.schedS, buf = ctx.createBuffer(2, len, sr);
        for (var c = 0; c < 2; c++) {
          var part = pcm[c].subarray(L.schedS, e);
          if (buf.copyToChannel) buf.copyToChannel(part, c); else buf.getChannelData(c).set(part);
        }
        var src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(out);
        src.start(L.anchorCtx + (L.schedS - L.anchorS) / sr);
        src.onended = (function (x) { return function () { var k = srcs.indexOf(x); if (k >= 0) srcs.splice(k, 1); }; })(src);
        srcs.push(src);
        L.schedS = e;
      }
      pump();
    }
    L.ready = function () { return !L.dead; };
    L.drives = function () { return L.playing && running() && !L.dead; };
    L.time = function () {
      if (!L.drives()) return null;
      if (L.stalled) return L.stallS / sr;
      var s = L.anchorS + (audibleNow() - L.anchorCtx) * sr;
      if (s < L.anchorS) s = L.anchorS;             // the first sound is still on its way
      if (s >= L.schedS && L.schedS < N) {          // ran out of rendered sound: wait for it
        stopAll(); L.stalled = true; L.stallS = L.schedS; L.want = L.schedS; pump();
        return L.stallS / sr;
      }
      return Math.min(s, N) / sr;
    };
    L.buffering = function () { return L.playing && L.stalled && running(); };
    L.play = function (t) {
      L.playing = true;
      L.want = Math.round(t * sr);
      ensureCtx();
      if (!running()) { if (ctx && ctx.resume) ctx.resume().then(function () { if (L.playing && !srcs.length) begin(Math.round(S.t * sr)); }, function () {}); pump(); return; }
      begin(Math.round(t * sr));
      clearInterval(L.feedTimer);
      L.feedTimer = setInterval(feed, 250);          // rAF stops in background tabs; the sound must not
    };
    L.pause = function () { L.playing = false; L.stalled = false; stopAll(); clearInterval(L.feedTimer); };
    L.seek = function (t) {
      L.want = Math.round(clamp(t, 0, DUR) * sr);
      if (L.playing && running()) begin(L.want); else pump();
    };
    L.setVolume = function () {
      if (!out) return;
      var v = S.muted ? 0 : S.volume;
      try { out.gain.setTargetAtTime(v, ctx.currentTime, 0.015); } catch (e) { out.gain.value = v; }
    };
    L.resumeIfPaused = function () {
      if (!ensureCtx()) return;
      var go = function () {
        if (!L.playing || !running() || srcs.length || L.stalled) return;
        begin(Math.round(S.t * sr));
        clearInterval(L.feedTimer);
        L.feedTimer = setInterval(feed, 250);
      };
      if (ctx.state !== 'running' && ctx.resume) ctx.resume().then(go, function () {}); else go();
    };
    L.unlock = function () {
      if (!ensureCtx()) return;
      if (ctx.state !== 'running' && ctx.resume) ctx.resume().catch(function () {});
      try {                               // iOS: a sound started inside the gesture unlocks the output
        var b = ctx.createBuffer(1, 1, ctx.sampleRate), s = ctx.createBufferSource();
        s.buffer = b; s.connect(out); s.start(0);
      } catch (e) { /* ignore */ }
    };
    L.start = function (t) { L.want = Math.round(clamp(t, 0, DUR) * sr); pump(); };
    L.rendered = function () { return have.map(function (r) { return [r[0] / sr, r[1] / sr]; }); };
    L.covered = function (t) { var e = runEnd(Math.round(t * sr)); return e < 0 ? 0 : (e / sr - t); };
    /** Level of the rendered sound over [t0, t1): {rms, peak, rendered (fraction of the span)}. */
    L.level = function (t0, t1) {
      var a = Math.max(0, Math.round(t0 * sr)), b = Math.min(N, Math.round(t1 * sr)), s2 = 0, pk = 0, n = 0, got = 0;
      for (var i = a; i < b; i++) {
        if (runEnd(i) < 0) { continue; }
        got++;
        for (var c = 0; c < 2; c++) { var x = pcm[c][i]; s2 += x * x; if (x > pk) pk = x; else if (-x > pk) pk = -x; n++; }
      }
      return { rms: n ? Math.sqrt(s2 / n) : 0, peak: pk, rendered: b > a ? got / (b - a) : 0 };
    };
    L.samples = function (t0, t1, ch) { return Array.prototype.slice.call(pcm[ch || 0].subarray(Math.round(t0 * sr), Math.round(t1 * sr))); };
    /**
     * Check the stream against a whole render of the score (same limiter): over the rendered part of
     * [t0, t1) -> {refDb (level of the whole render), diffDb (level of the difference), maxDiff,
     * seconds compared}. A clean stream sits tens of dB below the signal, across every seam and seek.
     */
    var refP = null;
    L.verify = function (t0, t1) {
      refP = refP || child.renderScore({ sampleRate: sr, from: 0, duration: DUR }).then(function (buf) {
        var chs = [buf.getChannelData(0), buf.getChannelData(Math.min(1, buf.numberOfChannels - 1))];
        return W.__stLimit ? W.__stLimit(chs, sr, o.gainDb || 0, o.ceilDb === undefined ? -1.5 : o.ceilDb) : chs;
      });
      return refP.then(function (ref) {
        var a = Math.max(0, Math.round((t0 || 0) * sr)), b = Math.min(N, Math.round((t1 === undefined ? DUR : t1) * sr), ref[0].length);
        var e = 0, d = 0, mx = 0, n = 0;
        for (var i = a; i < b; i++) {
          if (runEnd(i) < 0) continue;
          for (var c = 0; c < 2; c++) { var x = ref[c][i], y = pcm[c][i]; e += x * x; d += (x - y) * (x - y); if (Math.abs(x - y) > mx) mx = Math.abs(x - y); n++; }
        }
        var db = function (v) { return v > 0 ? 20 * Math.log10(Math.sqrt(v / Math.max(1, n))) : -200; };
        return { refDb: +db(e).toFixed(1), diffDb: +db(d).toFixed(1), maxDiff: +mx.toFixed(5), seconds: +(n / 2 / sr).toFixed(2) };
      });
    };
    /** An AnalyserNode on the live output (what the speakers get), for meters and tests. */
    L.tap = function () {
      if (!ensureCtx()) return null;
      var an = ctx.createAnalyser();
      an.fftSize = 2048;
      out.connect(an);
      return an;
    };
    L.facade = {
      kind: 'score',
      get currentTime() { var t = L.time(); return t === null ? L.want / sr : t; },
      get paused() { return !L.playing; },
      get duration() { return DUR; },
      get readyState() { return L.covered(L.want / sr) > 0.5 || runEnd(L.want) >= N ? 4 : 1; },
      get context() { return ctx; },
      get speed() { return L.speed; },
      get pieces() { return L.pieces; },
      get firstPieceMs() { return L.firstMs; },
      get seams() { return L.seams.slice(); },
      rendered: L.rendered, level: L.level, samples: L.samples, verify: L.verify, tap: L.tap,
    };
    return L;
  }

  function anchorWall(t) { S.wallT0 = t; S.wallP0 = now(); }
  function clockNow() {
    var at = SND ? SND.time() : null;
    if (at !== null && at !== undefined) { anchorWall(at); return at; }
    return S.wallT0 + (now() - S.wallP0) / 1000;
  }

  // ------------------------------------------------------------------ drawing
  function push() {
    var c = S.child;
    if (!c || !S.ready) return;
    var f = Math.min(Math.floor(S.t * fps + 1e-9), Math.round(DUR * fps) - 1);
    if (f === S.lastFrame && !S.pending) return;
    if (S.busy) { S.pending = true; return; }
    S.busy = true; S.pending = false; S.lastFrame = f;
    var drawn = function () {
      S.busy = false;
      if (S.pending) { S.pending = false; S.lastFrame = -1; push(); }
      else emit('frame', f);
    };
    c.seek(f / fps).then(drawn, function (e) { reportChild(e); drawn(); });
  }
  function reportChild(e) {
    if (!S.error) { S.error = String(e && e.message || e); try { console.warn('[showtime] ' + S.error); } catch (x) { /* ignore */ } }
  }
  function renderBuf() {
    if (!SND || SND.kind !== 'score' || !bufEl) return;
    var r = SND.rendered(), html = '';
    r.forEach(function (x) { html += '<i style="left:' + (100 * x[0] / DUR).toFixed(2) + '%;width:' + (100 * (x[1] - x[0]) / DUR).toFixed(2) + '%"></i>'; });
    bufEl.innerHTML = html;
  }
  function renderUI() {
    // before the first play the picture is the poster frame, but the controls show where play begins
    var ut = S.started ? S.t : (startAt !== null ? startAt : 0);
    var p = DUR > 0 ? clamp(ut / DUR, 0, 1) : 0;
    fillEl.style.width = (p * 100) + '%';
    knob.style.left = (p * 100) + '%';
    timeEl.firstChild.textContent = fmt(ut);
    timeEl.lastChild.textContent = '/ ' + fmt(DUR);
    var ci = chapterIndex(ut), ch = ci >= 0 && chapters[ci].label ? chapters[ci].label : '';
    var chText = ch ? (chapters.length > 1 ? (ci + 1) + '. ' : '') + ch : '';
    if (chapEl.textContent !== chText) chapEl.textContent = chText;
    markChapter(S.started || startAt !== null ? ci : -1);
    scrub.setAttribute('aria-valuenow', ut.toFixed(1));
    scrub.setAttribute('aria-valuetext', fmt(ut) + ' of ' + fmt(DUR) + (ch ? ', ' + ch : ''));
    playBtn.setAttribute('aria-label', S.playing ? tr('pauseK') : tr('playK'));
    bigBtn.setAttribute('aria-label', S.ended ? tr('replay') : tr('play'));
    muteBtn.setAttribute('aria-label', S.muted ? tr('unmuteM') : tr('muteM'));
    cls('is-playing', S.playing); cls('is-paused', !S.playing); cls('is-ended', S.ended);
    cls('has-started', S.started); cls('is-muted', S.muted || !SND || !!S.noSound);
    cls('is-buffering', !!(SND && SND.buffering()));
  }
  function tick() {
    if (S.playing) {
      var t = clockNow(), q = QS.length ? qCrossed(S.t, t) : null;
      if (q && RANGE && q.t >= RANGE.b - 0.5 / fps) q = null;   // a question after the range never asks
      if (q) qAsk(q);
      else if (RANGE && S.t < RANGE.b && t >= RANGE.b - 0.5 / fps) {
        if (S.loop) { seekTo(RANGE.a); emit('loop'); }
        else { pause(); S.t = rangeLast(); anchorWall(S.t); S.lastFrame = -1; push(); renderUI(); emit('rangeend'); }
      } else if (t >= DUR - 0.5 / fps) {
        if (S.loop) { seekTo(0); emit('loop'); }
        else { S.t = lastFrameT; pause(); S.ended = true; renderUI(); emit('ended'); }
      } else S.t = Math.max(0, S.t, t); // never backwards while playing (seeks set S.t themselves)
      push();
      renderUI();
    }
    W.requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------ transport
  function play() {
    if (!S.ready) { S.wantPlay = true; cls('is-loading', true); return; }
    if (qOpen) {
      // play while a question is open: answered, it is Continue; unanswered, the video plays on
      // through its own pause and think beat and the question counts as passed
      if (QST[qOpen.id].choice !== null) { qContinue(); return; }
      QST[qOpen.id].passed = true;
      qClose();
    }
    if (!S.started) {
      S.started = true;
      var t0 = startAt !== null ? startAt : 0;
      if (RANGE && !inRange(t0)) setRange(null, true);   // a chapter picked before the first play: not the range
      S.t = clamp(t0, 0, lastFrameT);
      S.lastFrame = -1;
      push();
      if (QS.length) qSeeked(S.t);   // a deep link past a question passes it
    }
    if (RANGE && (S.t >= rangeLast() - 1e-6 || S.t < RANGE.a - 0.5 / fps)) { S.t = RANGE.a; S.ended = false; S.lastFrame = -1; push(); if (QS.length) qSeeked(S.t); }
    else if (S.ended || S.t >= lastFrameT) { S.t = 0; S.ended = false; if (QS.length) { qReset(); qMarks(); } }
    S.playing = true;
    anchorWall(S.t);
    if (SND) SND.play(S.t);
    if (S.noSound && !S.noSoundShown) {
      S.noSoundShown = true;
      message(S.noSound);
      setTimeout(function () { if (msgEl.textContent === S.noSound) message(''); }, 6000);
    }
    idleSoon();
    renderUI();
    emit('play');
  }
  function pause() {
    if (S.playing) S.t = clockNow();
    S.playing = false;
    if (SND) SND.pause();
    S.t = Math.min(lastFrameT, Math.floor(S.t * fps + 1e-9) / fps);
    anchorWall(S.t);
    S.lastFrame = -1; push();
    showControls();
    renderUI();
    emit('pause');
  }
  function toggle() { if (S.playing) pause(); else play(); }
  function seekTo(t) {
    if (!S.started) S.started = true;
    if (RANGE && !inRange(clamp(t, 0, lastFrameT))) setRange(null, true);
    S.t = clamp(t, 0, lastFrameT);
    if (S.ended && S.t < lastFrameT) S.ended = false;
    anchorWall(S.t);
    if (SND) SND.seek(S.t);
    push();
    renderUI();
    if (QS.length) qSeeked(S.t);
    emit('seek', S.t);
  }
  function step(frames) { if (S.playing) pause(); seekTo((Math.floor(S.t * fps + 1e-9) + frames) / fps); }
  function restart() { if (QS.length) qReset(); seekTo(0); if (!S.playing) play(); emit('restart'); }
  function gotoChapter(i) {
    if (!chapters[i]) return false;
    seekTo(chapters[i].t);
    toast((chapters.length > 1 ? (i + 1) + '. ' : '') + chapterName(i), 1400);
    return true;
  }
  function chapterStep(dir) {
    if (!chapters.length) { seekTo(S.t + dir * DUR / 10); return; }
    var i = chapterIndex(S.t);
    if (dir < 0) {
      // like a CD player: back to the start of this chapter, or to the one before when near its start
      if (i >= 0 && S.t - chapters[i].t > 1.5) gotoChapter(i); else gotoChapter(Math.max(0, i - 1));
    } else if (i + 1 < chapters.length) gotoChapter(i + 1);
    else seekTo(lastFrameT);
  }
  function setMuted(m) {
    S.muted = !!m;
    if (SND) SND.setVolume();
    if (!S.muted) unmuteBtn.hidden = true;
    saveVol(); renderUI();
    emit('volumechange');
  }
  function setVolume(v) {
    S.volume = clamp(+v || 0, 0, 1);
    volEl.value = String(S.volume);
    if (SND) SND.setVolume();
    if (S.volume > 0 && S.muted) setMuted(false);
    saveVol();
    emit('volumechange');
  }
  function saveVol() { try { W.localStorage.setItem('showtime-player', JSON.stringify({ volume: S.volume })); } catch (e) { /* ignore */ } }
  function toggleFullscreen() {
    var fsEl = D.fullscreenElement || D.webkitFullscreenElement;
    if (fsEl) { (D.exitFullscreen || D.webkitExitFullscreen).call(D); return; }
    var el = D.documentElement;
    var req = el.requestFullscreen || el.webkitRequestFullscreen;
    if (req) { var r = req.call(el); if (r && r.catch) r.catch(function () {}); }
  }
  ['fullscreenchange', 'webkitfullscreenchange'].forEach(function (ev) {
    D.addEventListener(ev, function () { cls('is-fullscreen', !!(D.fullscreenElement || D.webkitFullscreenElement)); layout(); });
  });
  // An AudioContext only starts inside a click or key press: a click that comes while the page is
  // still loading makes one now for the live score to use.
  var earlyCtx = null;
  function makeCtx() {
    var AC = W.AudioContext || W.webkitAudioContext;
    if (!AC) return null;
    try { return new AC({ sampleRate: 48000, latencyHint: 'interactive' }); } catch (e) { try { return new AC(); } catch (e2) { return null; } }
  }
  function unlockAudio() {
    if (SND) { SND.unlock(); return; }
    if (M.audio && M.audio.mode === 'score' && !earlyCtx) {
      earlyCtx = makeCtx();
      if (earlyCtx && earlyCtx.state !== 'running' && earlyCtx.resume) earlyCtx.resume().catch(function () {});
    }
  }

  // ------------------------------------------------------------------ start screen
  // Before the first play: the poster frame, a soft scrim in the film's ground colour, and the title,
  // subtitle and Play button in a corner the poster frame leaves free of text (the stage reports
  // where its text sits). On a phone held upright the same block sits under the picture instead.
  function fillStart() {
    if (!startScreen) return;
    var s = M.start || {};
    $('.stp-kicker', sbox).textContent = s.kicker || '';
    if (s.showTitle === false) st.setAttribute('data-bare', ''); else st.removeAttribute('data-bare');
    $('.stp-h', sbox).textContent = s.title || M.title || '';
    $('.stp-sub', sbox).textContent = s.subtitle || '';
    $('.d', goBtn).textContent = fmt(DUR);
    var meta = [];
    if (chapters.length > 1) meta.push(tr('nChapters', { n: chapters.length }));
    if (M.audio && M.audio.mode && M.audio.mode !== 'none') meta.push(tr('soundOn'));
    $('.stp-smeta', sbox).textContent = meta.join(' · ');
    var from = '';
    if (RANGE) from = tr('rangeFrom', { a: fmt(RANGE.a), b: fmt(RANGE.b) });
    else if (startAt !== null && startAt > 0.05) {
      var ci = chapterIndex(startAt);
      from = tr('startsAt', { t: fmt(startAt) }) + (ci >= 0 && chapters[ci].label && Math.abs(chapters[ci].t - startAt) < 0.05 ? ' · ' + chapterName(ci) : '');
    }
    $('.stp-from', sbox).textContent = from;
    goBtn.setAttribute('aria-label', tr('play') + (s.title || M.title ? ' ' + (s.title || M.title) : '') + ' (' + fmt(DUR) + ')');
  }
  function placeStart() {
    if (!startScreen) return;
    if (mode === 'stacked') { if (sbox.parentNode !== ihead) ihead.appendChild(sbox); }
    else if (sbox.parentNode !== st) st.appendChild(sbox);
    fitStart();
  }
  /**
   * Put the start block in the corner that covers least of the poster frame (text counts double,
   * pictures and panels once). When every corner is busy, the block keeps the bottom-left corner on
   * a deeper scrim (data-dense), like a title over a busy poster.
   */
  function fitStart() {
    if (!startScreen || mode !== 'overlay' || !textBoxes) return;
    var hw = holder.clientWidth, hh = holder.clientHeight;
    if (!(hw > 0 && hh > 0)) return;
    var bw = Math.min(1, sbox.offsetWidth / hw), bh = Math.min(1, sbox.offsetHeight / hh);
    var spots = { bl: [0, 1 - bh], tl: [0, 0], br: [1 - bw, 1 - bh], tr: [1 - bw, 0] };
    var bias = { bl: 0, tl: 0.004, br: 0.006, tr: 0.01 };
    var best = 'bl', bestScore = Infinity, bestText = 0;
    Object.keys(spots).forEach(function (k) {
      var x0 = spots[k][0], y0 = spots[k][1], x1 = x0 + bw, y1 = y0 + bh, sc = bias[k], tx = 0;
      textBoxes.forEach(function (r) {
        var ix = Math.max(0, Math.min(x1, r[0] + r[2]) - Math.max(x0, r[0])), iy = Math.max(0, Math.min(y1, r[1] + r[3]) - Math.max(y0, r[1]));
        var w = r[4] === undefined ? 1 : r[4];
        sc += ix * iy * w;
        if (w >= 1) tx += ix * iy;
      });
      if (sc < bestScore) { bestScore = sc; best = k; bestText = tx; }
    });
    var dense = bestText > 0.1 * bw * bh || bestScore > 0.35 * bw * bh;
    // a light poster under a dark scrim (or the other way round) keeps the title unreadable: deepen it
    if (!dense && posterLuma && posterLuma.length === 32 * 18) {
      var sx0 = Math.floor(spots[best][0] * 32), sy0 = Math.floor(spots[best][1] * 18);
      var sx1 = Math.min(32, Math.ceil((spots[best][0] + bw) * 32)), sy1 = Math.min(18, Math.ceil((spots[best][1] + bh) * 18));
      var sum = 0, n = 0;
      for (var gy = sy0; gy < sy1; gy++) for (var gx = sx0; gx < sx1; gx++) { sum += posterLuma[gy * 32 + gx]; n++; }
      var bgL = (0.2126 * TH.bg[0] + 0.7152 * TH.bg[1] + 0.0722 * TH.bg[2]) / 255;
      if (n && Math.abs(sum / n - bgL) > 0.45) dense = true;
    }
    if (dense) best = 'bl';
    st.setAttribute('data-pos', best);
    st.style.setProperty('--stp-sh', (bh * 100).toFixed(1) + '%');
    if (dense) st.setAttribute('data-dense', ''); else st.removeAttribute('data-dense');
  }
  var GENERIC = /^(serif|sans-serif|monospace|cursive|fantasy|system-ui|ui-[a-z-]+|emoji|math|fangsong|inherit|initial|-apple-system|blinkmacsystemfont)$/i;
  function families(stack) {
    return String(stack || '').split(',').map(function (f) { return f.trim().replace(/^['"]|['"]$/g, ''); })
      .filter(function (f) { return f && !GENERIC.test(f); });
  }
  var loaded = {};
  /** Register the film's font files (sent by the stage) under private names, then use them. */
  function useFonts(fonts) {
    (fonts || []).forEach(function (f) {
      try {
        var d = { weight: String(f.weight || '400'), style: f.style || 'normal', display: 'swap' };
        if (f.range) d.unicodeRange = f.range;
        var face = new FontFace('stp ' + f.family, f.data, d);
        D.fonts.add(face);
        loaded[f.family] = true;
        face.load().catch(function () {});
      } catch (e) { /* unusable face */ }
    });
    var s = M.start || {};
    var pick = function (stack) {
      var fam = families(stack).filter(function (f) { return loaded[f.toLowerCase()]; })[0];
      return fam ? '"stp ' + fam.toLowerCase() + '", ' : '';
    };
    var tf = pick(s.font), bf = pick(s.bodyFont) || tf;
    if (tf) root.style.setProperty('--stp-title-font', tf + 'var(--stp-sys)');
    if (bf) root.style.setProperty('--stp-body-font', bf + 'var(--stp-sys)');
    if (s.fontWeight) root.style.setProperty('--stp-title-weight', String(s.fontWeight));
    return D.fonts && D.fonts.ready ? D.fonts.ready : Promise.resolve();
  }
  function readyStart() {
    if (!startScreen) return;
    var s = M.start || {}, shown = false;
    var show = function () { if (shown) return; shown = true; fitStart(); cls('start-set', true); };
    setTimeout(show, 2500);
    S.child.seek(S.t).then(function () {
      return S.child.look(families(s.font).concat(families(s.bodyFont)).slice(0, 6));
    }).then(function (v) {
      textBoxes = (v && v.rects) || [];
      posterLuma = (v && v.luma) || null;
      return useFonts(v && v.fonts);
    }).then(show, show);
  }
  function drawChapterList() {
    if (chapters.length < 2) { chList.innerHTML = ''; return; }
    chList.innerHTML = chapters.map(function (c, i) {
      return '<li><button type="button" data-i="' + i + '"><span class="n">' + (i + 1) + '</span><span class="l"></span><span class="t">' + fmt(c.t) + '</span></button></li>';
    }).join('');
    Array.prototype.forEach.call(chList.querySelectorAll('.l'), function (el, i) { el.textContent = chapterName(i); });
  }
  var listCur = -2;
  function markChapter(ci) {
    if (ci === listCur) return;
    listCur = ci;
    Array.prototype.forEach.call(chList.querySelectorAll('button'), function (b, i) {
      b.classList.toggle('is-cur', i === ci);
      if (i === ci) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
    });
  }

  // ------------------------------------------------------------------ help
  var KEYS = [
    ['Space / K', 'Play · pause'],
    ['← / →', 'Back · forward 1 s'],
    ['Shift + ← / →', 'One frame (also , and .)'],
    ['J / L', 'Back · forward 5 s'],
    ['1 – 9', 'Jump to chapter 1 – 9 (no chapters: 10 – 90 %)'],
    ['[ / ]', 'Previous · next chapter (also Page Up / Down)'],
    ['0 / Home', 'Start · End: last frame'],
    ['R', 'Restart from the beginning'],
    ['M', 'Mute · ↑ / ↓ volume'],
    ['F', 'Full screen'],
    ['C', 'Copy a link to this moment (or to the part you picked)'],
    ['Shift + drag', 'On the bar: pick a part to loop and link (Esc clears)'],
    ['?', 'Show · hide these keys'],
  ];
  help.innerHTML = '<div class="stp-help-box"><b>' + esc(tr('keyboard')) + '</b><table>' + KEYS.map(function (k, i) {
    return '<tr><th>' + k[0].split(' / ').map(function (x) { return '<kbd>' + x + '</kbd>'; }).join(' / ') + '</th><td>' + esc((WD.keys || [])[i] || k[1]) + '</td></tr>';
  }).join('') + '</table><div class="stp-help-foot">' + esc(tr('linksFoot')) + '</div></div>';
  function toggleHelp(on) {
    var show = on === undefined ? help.hidden : !!on;
    help.hidden = !show;
    if (show) showControls();
  }
  function toggleChapters(on) {
    var show = on === undefined ? chMenu.hidden : !!on;
    chMenu.hidden = !show;
    chapEl.setAttribute('aria-expanded', String(show));
    if (show) {
      var ci = chapterIndex(S.t);
      Array.prototype.forEach.call(chMenu.querySelectorAll('button'), function (b, i) { b.classList.toggle('is-cur', i === ci); });
    }
  }

  // ------------------------------------------------------------------ questions
  // Stop-and-ask questions (showtime.json "questions"): at a question's time the video pauses on that
  // frame and a card asks it; a pick marks right or wrong and shows the reply, and Continue plays on
  // from `resume` (the end of the MP4's "pause and think" beat). Seeking past a question passes it;
  // seeking back before it asks it again (unless it was answered); a restart or replay asks them all.
  // On a phone held upright the card sits under the picture, so the paused frame stays in view.
  var QS = (Array.isArray(M.questions) ? M.questions : []).filter(function (q) {
    return q && isFinite(q.t) && isFinite(q.resume) && Array.isArray(q.choices) && q.choices.length > 1;
  }).sort(function (a, b) { return a.t - b.t; });
  var QST = {}, qOpen = null, qAutoTimer = null;
  var qcard = D.createElement('div');
  qcard.className = 'stp-q'; qcard.hidden = true;
  qcard.setAttribute('role', 'dialog'); qcard.setAttribute('aria-live', 'polite');
  if (QS.length) {
    root.classList.add('has-questions');
    root.appendChild(qcard);
    if (KEYS.length && help.querySelector('table')) {
      var maxN = Math.max.apply(null, QS.map(function (q) { return q.choices.length; }));
      var qrow = D.createElement('tr');
      qrow.innerHTML = '<th><kbd>A</kbd> – <kbd>' + String.fromCharCode(64 + maxN) + '</kbd> / <kbd>1</kbd> – <kbd>' + maxN + '</kbd></th><td></td>';
      qrow.lastChild.textContent = tr('qKeys');
      help.querySelector('table').appendChild(qrow);
    }
  }
  function qReset() { QS.forEach(function (q) { QST[q.id] = { choice: null, passed: false }; }); }
  qReset();
  function qFrame(t) { return Math.min(lastFrameT, Math.round(t * fps) / fps); }
  /** The first question still to ask between the last shown time and t (a late frame still catches it). */
  function qCrossed(from, t) {
    for (var i = 0; i < QS.length; i++) {
      var q = QS[i], s = QST[q.id];
      if (s.choice === null && !s.passed && from <= q.t + 0.001 && t >= q.t - 0.02) return q;
    }
    return null;
  }
  /** After a seek to t: questions after t are asked again, the ones at or before it are passed. */
  function qSeeked(t) {
    if (qOpen) qClose();
    QS.forEach(function (q) {
      var s = QST[q.id];
      if (q.t > t + 0.05) s.passed = false;
      else if (s.choice === null) s.passed = true;
    });
    qMarks();
  }
  function qEl(tag, cls, text) {
    var e = D.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  // a choice's text; a path or URL may break after each slash before CSS breaks it mid-word
  function qText(c) {
    var e = qEl('span', 'stp-q-text'), parts = String(c).split('/');
    parts.forEach(function (p, j) {
      if (j < parts.length - 1) p += '/';
      e.appendChild(D.createTextNode(p));
      if (j < parts.length - 1 && parts[j + 1]) e.appendChild(D.createElement('wbr'));
    });
    return e;
  }
  function qScore() {
    var right = 0, done = 0;
    QS.forEach(function (q) { var c = QST[q.id].choice; if (c !== null) { done++; if (c === q.answer) right++; } });
    return { right: right, done: done };
  }
  /** Stop on the question's own frame (a late catch goes back to it) and ask. */
  function qAsk(q) {
    pause();
    S.t = qFrame(q.t);
    anchorWall(S.t);
    if (SND) SND.seek(S.t);
    S.lastFrame = -1; push(); renderUI();
    qOpen = q;
    qcard.innerHTML = '';
    qcard.appendChild(qEl('div', 'stp-q-kicker', tr('qOf', { n: QS.indexOf(q) + 1, m: QS.length })));
    qcard.appendChild(qEl('div', 'stp-q-prompt', q.prompt));
    var list = qEl('div', 'stp-q-choices');
    q.choices.forEach(function (c, i) {
      var b = qEl('button', 'stp-q-choice');
      b.type = 'button';
      b.appendChild(qEl('span', 'stp-q-key', String.fromCharCode(65 + i)));
      b.appendChild(qText(c));
      b.addEventListener('click', function (e) { e.stopPropagation(); qAnswer(i); });
      list.appendChild(b);
    });
    qcard.appendChild(list);
    qcard.appendChild(qEl('div', 'stp-q-hint', tr('qPick')));
    qcard.setAttribute('aria-label', q.prompt);
    qcard.hidden = false;
    cls('is-asking', true);
    qPlace();
    if (mode === 'stacked') { info.scrollTop = 0; if (qcard.scrollIntoView) qcard.scrollIntoView({ block: 'nearest' }); }
    var first = list.querySelector('button');
    if (first && first.focus) first.focus({ preventScroll: true });
    emit('question', { id: q.id, index: QS.indexOf(q), t: q.t });
  }
  function qAnswer(i) {
    var q = qOpen;
    if (!q || QST[q.id].choice !== null || !(i >= 0 && i < q.choices.length)) return;
    var right = i === q.answer;
    QST[q.id].choice = i;
    Array.prototype.forEach.call(qcard.querySelectorAll('.stp-q-choice'), function (b, j) {
      b.disabled = true;
      if (j === q.answer) b.classList.add('is-right');
      else if (j === i) b.classList.add('is-wrong');
    });
    var fb = qEl('div', 'stp-q-reply ' + (right ? 'is-right' : 'is-wrong'));
    fb.appendChild(qEl('strong', null, right ? tr('qRight') : tr('qWrong')));
    var reply = (q.reply && q.reply[i]) || '';
    if (reply) fb.appendChild(D.createTextNode(' ' + reply));
    var hint = qcard.querySelector('.stp-q-hint');
    if (hint) qcard.replaceChild(fb, hint); else qcard.appendChild(fb);
    var row = qEl('div', 'stp-q-row');
    var go = qEl('button', 'stp-q-go', tr('qGo'));
    go.type = 'button';
    go.addEventListener('click', function (e) { e.stopPropagation(); qContinue(); });
    row.appendChild(go);
    var sc = qScore();
    row.appendChild(qEl('span', 'stp-q-score', tr('qScore', { r: sc.right, n: sc.done })));
    qcard.appendChild(row);
    if (go.focus) go.focus({ preventScroll: true });
    qMarks();
    emit('answer', { id: q.id, choice: i, right: right });
    var auto = Number(M.autoContinue) || 0;
    if (auto > 0) {
      var until = now() + auto * 1000, note = qEl('span', 'stp-q-auto');
      row.appendChild(note);
      var step = function () {
        if (qOpen !== q) return;
        var left = Math.ceil((until - now()) / 1000);
        if (left <= 0) { qContinue(); return; }
        note.textContent = tr('qAuto', { s: left });
        qAutoTimer = setTimeout(step, 250);
      };
      step();
    }
  }
  function qClose() {
    clearTimeout(qAutoTimer);
    qOpen = null;
    qcard.hidden = true;
    cls('is-asking', false);
  }
  /** Continue: play on from the end of the pause and think beat. */
  function qContinue() {
    var q = qOpen;
    if (!q) return;
    qClose();
    QST[q.id].passed = true;
    var to = q.resume;
    if (RANGE && to >= RANGE.b - 0.5 / fps) {
      if (!S.loop) { seekTo(rangeLast()); emit('continue', { id: q.id, t: S.t }); emit('rangeend'); return; }
      to = RANGE.a;
    }
    seekTo(to);
    emit('continue', { id: q.id, t: to });
    if (S.t < lastFrameT) play();
  }
  /** Keys while a question is open: A-I or 1-9 answer it, Enter or Space go on. -> handled */
  function qKey(k) {
    var q = qOpen;
    if (!q) return false;
    if (QST[q.id].choice === null) {
      var i = /^[1-9]$/.test(k) ? +k - 1 : /^[a-i]$/i.test(k) ? k.toUpperCase().charCodeAt(0) - 65 : -1;
      if (i >= 0 && i < q.choices.length) { qAnswer(i); return true; }
      return false;
    }
    if (k === 'Enter' || k === ' ') { qContinue(); return true; }
    return false;
  }
  /** The card floats over the bottom of the picture, or sits under it on a phone held upright. */
  function qPlace() {
    if (!QS || !QS.length) return;   // (layout() runs once before this section has set up)
    if (mode === 'stacked') { if (qcard.parentNode !== info) info.insertBefore(qcard, info.firstChild); }
    else if (qcard.parentNode !== root) root.appendChild(qcard);
  }
  /** Question marks on the scrubber (answered ones in their colour). */
  function qMarks() {
    if (!QS.length || !(DUR > 0)) return;
    var rail = $('.stp-rail', bar), box = $('.stp-qmarks', rail);
    if (!box) { box = qEl('div', 'stp-qmarks'); rail.appendChild(box); }
    box.innerHTML = QS.map(function (q) {
      var c = QST[q.id].choice, st = c === null ? '' : c === q.answer ? ' is-right' : ' is-wrong';
      return '<i class="' + st.trim() + '" style="left:' + (100 * q.t / DUR).toFixed(3) + '%"></i>';
    }).join('');
  }
  qcard.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
  qcard.addEventListener('click', function (e) { e.stopPropagation(); });

  // ------------------------------------------------------------------ controls behaviour
  var idleTimer = null;
  function showControls() { cls('is-idle', false); idleSoon(); }
  function idleSoon() {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () {
      if (S.playing && mode !== 'stacked' && !scrub.classList.contains('is-drag') && chMenu.hidden && help.hidden) cls('is-idle', true);
    }, 2600);
  }
  root.addEventListener('pointermove', function (e) { if (e.pointerType !== 'touch') showControls(); });
  bigBtn.addEventListener('click', function (e) { e.stopPropagation(); unlockAudio(); play(); });
  goBtn.addEventListener('click', function (e) { e.stopPropagation(); unlockAudio(); play(); });
  chList.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button[data-i]') : null;
    if (!b) return;
    var i = +b.getAttribute('data-i');
    unlockAudio();
    if (!S.started) { startAt = chapters[i].t; play(); } else { gotoChapter(i); if (!S.playing) play(); }
  });
  unmuteBtn.addEventListener('click', function (e) { e.stopPropagation(); unlockAudio(); setMuted(false); if (SND) SND.resumeIfPaused(); });
  playBtn.addEventListener('click', function (e) { e.stopPropagation(); unlockAudio(); toggle(); });
  muteBtn.addEventListener('click', function (e) { e.stopPropagation(); unlockAudio(); setMuted(!S.muted); });
  volEl.addEventListener('input', function () { setVolume(volEl.value); });
  loopBtn.addEventListener('click', function (e) { e.stopPropagation(); S.loop = !S.loop; loopBtn.setAttribute('aria-pressed', String(S.loop)); });
  loopBtn.setAttribute('aria-pressed', String(S.loop));
  if (RANGE) { var linked = RANGE; RANGE = null; setRange(linked, true); }   // a #t=a-b link: the loop button shows it
  fsBtn.addEventListener('click', function (e) { e.stopPropagation(); toggleFullscreen(); });
  linkBtn.addEventListener('click', function (e) { e.stopPropagation(); copyLink(); });
  keysBtn.addEventListener('click', function (e) { e.stopPropagation(); toggleHelp(); });
  chapEl.addEventListener('click', function (e) { e.stopPropagation(); toggleChapters(); });
  chMenu.addEventListener('click', function (e) {
    e.stopPropagation();
    var b = e.target.closest ? e.target.closest('button[data-i]') : null;
    if (!b) return;
    toggleChapters(false);
    unlockAudio();
    gotoChapter(+b.getAttribute('data-i'));
  });
  help.addEventListener('pointerdown', function (e) { e.stopPropagation(); toggleHelp(false); });
  bar.addEventListener('click', function (e) { e.stopPropagation(); });
  [bar, bigBtn, unmuteBtn, goBtn, info].forEach(function (el) { el.addEventListener('pointerdown', function (e) { e.stopPropagation(); }); });
  var lastTap = 0;
  root.addEventListener('pointerdown', function (e) {
    if (e.button && e.button !== 0) return;
    if (!chMenu.hidden) { toggleChapters(false); return; }
    if (qOpen) { showControls(); return; }   // the picture is inert while a question waits
    if (e.pointerType === 'touch' && S.started && root.classList.contains('is-idle')) { showControls(); return; }
    if (!S.started && !S.ready) { S.wantPlay = true; cls('is-loading', true); unlockAudio(); return; }
    var t = now();
    if (e.pointerType !== 'touch' && t - lastTap < 300 && fsOK && S.started) { lastTap = 0; toggle(); toggleFullscreen(); return; } // double click: fullscreen, play state unchanged
    lastTap = t;
    unlockAudio();
    toggle();
    showControls();
  });
  root.addEventListener('dblclick', function (e) { e.preventDefault(); });

  // scrubber
  function scrubP(e) { var r = scrub.getBoundingClientRect(); return clamp((e.clientX - r.left) / r.width, 0, 1); }
  var dragWasPlaying = false;
  var pick = null;   // shift + drag on the scrubber: {from, to, moved}
  scrub.addEventListener('pointerdown', function (e) {
    e.stopPropagation();
    if (!S.ready) return;
    try { scrub.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
    scrub.classList.add('is-drag');
    dragWasPlaying = S.playing;
    if (e.shiftKey) {
      var t0 = scrubP(e) * DUR;
      pick = { from: t0, to: t0, moved: false, x: e.clientX, at: S.started ? S.t : (startAt || 0) };
      return;
    }
    pick = null;
    if (S.playing) pause();
    seekTo(scrubP(e) * DUR);
  });
  scrub.addEventListener('pointermove', function (e) {
    var p = scrubP(e), t = p * DUR;
    hoverEl.style.width = (p * 100) + '%';
    var ch = chapterAt(t);
    tip.textContent = (pick ? fmt(Math.min(pick.from, t)) + ' – ' + fmt(Math.max(pick.from, t)) : fmt(t)) + (ch && !pick ? '  ·  ' + ch : '');
    tip.hidden = false;
    var r = scrub.getBoundingClientRect(), half = tip.offsetWidth / 2;
    tip.style.left = clamp(p * r.width, half, r.width - half) + 'px';
    if (!scrub.classList.contains('is-drag')) return;
    if (pick) {
      pick.to = t;
      if (Math.abs(e.clientX - pick.x) > 4) pick.moved = true;
      if (pick.moved) drawRange({ a: Math.min(pick.from, t), b: Math.max(pick.from, t) });
      return;
    }
    seekTo(t);
  });
  function endDrag() {
    if (!scrub.classList.contains('is-drag')) return;
    scrub.classList.remove('is-drag');
    if (pick) {
      // dragged: that part; a shift + click: from the playhead to the click
      var a = pick.moved ? Math.min(pick.from, pick.to) : Math.min(pick.at, pick.from);
      var b = pick.moved ? Math.max(pick.from, pick.to) : Math.max(pick.at, pick.from);
      pick = null;
      if (b - a >= Math.max(0.25, 2 / fps)) {
        setRange(null, true);
        seekTo(a);
        setRange({ a: a, b: b });
        if (dragWasPlaying && !S.playing) play();
      } else drawRange();
      return;
    }
    if (dragWasPlaying) play();
  }
  scrub.addEventListener('pointerup', endDrag);
  scrub.addEventListener('pointercancel', endDrag);
  scrub.addEventListener('pointerleave', function () { tip.hidden = true; });

  // keyboard (the map is in KEYS above and in references/html-export.md)
  var PASSIVE = /^(Tab|Shift|Control|Alt|Meta|CapsLock|NumLock|ScrollLock|Escape|ContextMenu|OS|Dead|Unidentified|F\d+|Audio.*|Media.*|Volume.*|Browser.*|Launch.*)$/;
  function onKey(e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    var tg = e.target && e.target.tagName;
    if (tg === 'INPUT' && e.target !== volEl) return;
    if (e.target === volEl && /^(Arrow|Home|End|Page)/.test(e.key)) return; // the volume slider's own keys
    var k = e.key, handled = true, lower = String(k).length === 1 ? k.toLowerCase() : k;
    if (qOpen && !e.shiftKey && help.hidden && qKey(k)) { if (e.preventDefault) e.preventDefault(); return; }
    if (k === 'Escape') { if (!help.hidden) toggleHelp(false); else if (!chMenu.hidden) toggleChapters(false); else if (RANGE) setRange(null); else handled = false; }
    else if (k === '?') toggleHelp();
    else if (!help.hidden && k !== 'f' && k !== 'F') { toggleHelp(false); }
    else if (lower === 'f') { if (fsOK) toggleFullscreen(); }
    else if (lower === 'm') { unlockAudio(); setMuted(!S.muted); }
    else if (!S.started) {
      // before the first play any key begins (a digit begins at that chapter)
      if (PASSIVE.test(k)) handled = false;
      else {
        if (k === ' ' && tg === 'BUTTON') return;
        unlockAudio();
        if (/^[1-9]$/.test(k) && chapters[+k - 1]) startAt = chapters[+k - 1].t;
        play();
      }
    }
    else if (k === ' ' || lower === 'k') { if (tg === 'BUTTON' && k === ' ') return; unlockAudio(); toggle(); }
    else if (k === 'ArrowLeft') { if (e.shiftKey) step(-1); else seekTo(S.t - 1); }
    else if (k === 'ArrowRight') { if (e.shiftKey) step(1); else seekTo(S.t + 1); }
    else if (k === ',' || k === '<') step(-1);
    else if (k === '.' || k === '>') step(1);
    else if (lower === 'j') seekTo(S.t - 5);
    else if (lower === 'l') seekTo(S.t + 5);
    else if (/^[1-9]$/.test(k)) { if (chapters.length) { if (!gotoChapter(+k - 1)) handled = false; } else seekTo(DUR * Number(k) / 10); }
    else if (k === '0' || k === 'Home') seekTo(0);
    else if (k === 'End') { if (S.playing) pause(); seekTo(lastFrameT); }
    else if (k === 'PageUp' || k === '[') chapterStep(-1);
    else if (k === 'PageDown' || k === ']') chapterStep(1);
    else if (lower === 'r') { unlockAudio(); restart(); }
    else if (lower === 'c') copyLink();
    else if (k === 'ArrowUp' && tg !== 'INPUT') setVolume(S.volume + 0.1);
    else if (k === 'ArrowDown' && tg !== 'INPUT') setVolume(S.volume - 0.1);
    else handled = false;
    if (handled) { if (e.preventDefault) e.preventDefault(); showControls(); }
  }
  W.addEventListener('keydown', onKey);
  W.addEventListener('hashchange', function () {
    var x = linkTarget(currentHash());
    if (x === null) return;
    var t = x.t;
    if (!x.range && RANGE) setRange(null, true);
    if (!S.started) { startAt = t; if (x.range) setRange(x.range, true); fillStart(); return; }
    if (x.range) { setRange(null, true); seekTo(t); setRange(x.range, true); }
    else seekTo(t);
  });

  // ------------------------------------------------------------------ audio preparation
  function wavBlob(buf, gainDb, ceilDb) {
    var ch = Math.min(2, buf.numberOfChannels), n = buf.length, sr = buf.sampleRate;
    var g = 1;
    var data = [];
    for (var c = 0; c < 2; c++) data.push(buf.getChannelData(Math.min(c, ch - 1)));
    if (W.__stLimit) data = W.__stLimit(data, sr, gainDb || 0, ceilDb === undefined ? -1.5 : ceilDb);
    else g = Math.pow(10, Math.min(0, gainDb || 0) / 20);
    var bytes = 44 + n * 4, ab = new ArrayBuffer(bytes), v = new DataView(ab);
    var ws = function (o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    ws(0, 'RIFF'); v.setUint32(4, bytes - 8, true); ws(8, 'WAVE'); ws(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 2, true); v.setUint32(24, sr, true);
    v.setUint32(28, sr * 4, true); v.setUint16(32, 4, true); v.setUint16(34, 16, true); ws(36, 'data'); v.setUint32(40, n * 4, true);
    var o = 44;
    for (var i = 0; i < n; i++) {
      for (var k = 0; k < 2; k++) {
        var x = data[k][i] * g;
        x = x > 1 ? 1 : x < -1 ? -1 : x;
        v.setInt16(o, x < 0 ? x * 32768 : x * 32767, true); o += 2;
      }
    }
    return new Blob([ab], { type: 'audio/wav' });
  }
  // the element exists from the start (so a first click inside the loading time still unlocks it)
  if (M.audio && M.audio.mode === 'file') {
    var src = null;
    var aEl = D.getElementById('st-audio');
    if (aEl) {                      // one file: the soundtrack is packed beside the manifest
      var ae = JSON.parse(aEl.textContent);
      src = URL.createObjectURL(new Blob([b64bytes(ae.b)], { type: ae.t }));
      aEl.parentNode.removeChild(aEl);
    } else src = new URL(M.audio.url, D.baseURI).href; // --folder: a real file
    SND = ElementSound(src);
  }
  function prepareAudio(child) {
    if (!M.audio || M.audio.mode === 'none') return Promise.resolve();
    if (M.audio.mode === 'score') {
      if (!child.hasScore) return Promise.resolve();
      if (child.seekable && M.audio.live !== false && (W.AudioContext || W.webkitAudioContext)) {
        SND = LiveSound(child, { gainDb: M.audio.gainDb || 0, ceilDb: M.audio.ceilDb });
        SND.start(startAt !== null ? startAt : 0);           // the first piece renders before the click
        return Promise.resolve();
      }
      // a score that cannot start mid-way (a hand-written ST.score): render it whole, then play it
      SND = ElementSound(null);
      return child.renderScore({ sampleRate: 48000, duration: DUR }).then(function (buf) {
        if (!buf) { SND = null; return; }
        SND.setSource(URL.createObjectURL(wavBlob(buf, M.audio.gainDb || 0, M.audio.ceilDb)));
        return SND.wait();
      }).catch(function (e) { reportChild('score: ' + (e && e.message || e)); SND = null; });
    }
    // a browser without this codec (AAC in Chromium builds without proprietary codecs, some Linux
    // Firefox installs) says so up front; otherwise the element reports an error while loading
    var A = SND && SND.el;
    if (!A) return Promise.resolve();
    var full = /^audio\/mp4$/.test(M.audio.type || '') ? 'audio/mp4; codecs="mp4a.40.2"' : /^audio\/webm$/.test(M.audio.type || '') ? 'audio/webm; codecs="opus"' : M.audio.type;
    if (full && A.canPlayType && A.canPlayType(full) === '') SND.failed = true;
    return (SND.failed ? Promise.resolve() : SND.wait()).then(function () { if (SND.failed) noSound(); });
  }
  /** The soundtrack cannot play here: say so on screen (not only in the console) and show it as muted. */
  function noSound() {
    var codec = /webm/.test(M.audio.type || '') ? 'Opus' : 'AAC';
    reportChild('the soundtrack could not be decoded by this browser (' + (M.audio.type || '?') + ')');
    S.noSound = tr('noSound', { c: codec });
    muteBtn.disabled = true;
    muteBtn.setAttribute('title', S.noSound);
    volEl.disabled = true;
  }

  // ------------------------------------------------------------------ boot
  cls('is-loading', true);
  renderUI();
  var readyResolve, readyReject;
  var readyP = new Promise(function (res, rej) { readyResolve = res; readyReject = rej; });
  readyP.catch(function () {});
  function fail(msg) {
    cls('is-loading', false);
    cls('has-start', false);
    bigBtn.hidden = true;
    message(tr('cannotStart', { m: msg }));
    readyReject(new Error(msg));
  }
  // the stage document answers over postMessage (see boot.js)
  var calls = {}, callId = 0;
  function call(msg) {
    return new Promise(function (res, rej) {
      msg.id = ++callId;
      calls[msg.id] = { res: res, rej: rej };
      try { frame.contentWindow.postMessage(msg, '*'); } catch (e) { delete calls[msg.id]; rej(e); }
    });
  }
  var child = {
    hasScore: false, seekable: false,
    seek: function (t) { return call({ st: 'seek', t: t }); },
    paint: function () { return call({ st: 'paint' }); },
    look: function (fams) { return call({ st: 'look', families: fams }); },
    renderScore: function (o) {
      return call({ st: 'score', sampleRate: o.sampleRate, duration: o.duration, from: o.from || 0 }).then(function (v) {
        if (!v) return null;
        return { numberOfChannels: v.channels.length, length: v.channels[0].length, sampleRate: v.sampleRate,
          getChannelData: function (c) { return v.channels[c]; } };
      });
    },
  };
  W.addEventListener('message', function (e) {
    if (e.source !== frame.contentWindow) return;
    var d = e.data || {};
    if (d.st === 'done') {
      var c = calls[d.id];
      if (!c) return;
      delete calls[d.id];
      if (d.error) c.rej(new Error(d.error)); else c.res(d.value);
    } else if (d.st === 'ready') {
      var info = d.info || {};
      child.hasScore = !!info.hasScore;
      child.seekable = !!info.scoreSeekable;
      DUR = info.duration || DUR; fps = info.fps || fps;
      lastFrameT = Math.max(0, (Math.round(DUR * fps) - 1) / fps);
      drawTicks();
      prepareAudio(child).then(function () {
        S.child = child;
        S.ready = true;
        cls('is-ready', true);
        cls('is-loading', false);
        S.lastFrame = -1;
        push();
        renderUI();
        fillStart();
        readyStart();
        readyResolve(info);
        emit('ready', info);
        var auto = M.autoplayMuted && !reducedMotion;
        if (auto) { setMuted(true); if (SND) unmuteBtn.hidden = false; }
        if (auto || S.wantPlay) { S.wantPlay = false; play(); }
      }).catch(function (err) { fail(String(err && err.message || err)); });
    } else if (d.st === 'error') {
      fail(d.message);
    } else if (d.st === 'warn') {
      devNote(d.message);
    } else if (d.st === 'pageerror') {
      reportChild(d.message);
    } else if (d.st === 'key') {
      onKey({ key: d.key, code: d.code, shiftKey: d.shiftKey, metaKey: d.metaKey, ctrlKey: d.ctrlKey, altKey: d.altKey,
        target: null, defaultPrevented: false, preventDefault: function () {} });
    }
  });
  unpack().then(function (zfiles) { frame.srcdoc = stageDoc(zfiles); })
    .catch(function (e) { fail(String(e && e.message || e)); });
  W.requestAnimationFrame(tick);
  // background tabs stop requestAnimationFrame but not the sound: a timer still stops at every question
  if (QS.length) setInterval(function () { if (S.playing && !qOpen) { var q = qCrossed(S.t, clockNow()); if (q) qAsk(q); } }, 120);

  // ------------------------------------------------------------------ public API
  var API = {
    get ready() { return readyP; },
    get currentTime() { return S.t; },
    set currentTime(t) { seekTo(+t || 0); },
    get duration() { return DUR; },
    get fps() { return fps; },
    get paused() { return !S.playing; },
    get started() { return S.started; },
    get ended() { return S.ended; },
    /** What the stage reported as missing (fonts, stylesheets). */
    get warnings() { return devNotes.slice(); },
    get muted() { return S.muted; },
    set muted(m) { setMuted(m); },
    get volume() { return S.volume; },
    set volume(v) { setVolume(v); },
    get loop() { return S.loop; },
    set loop(v) { S.loop = !!v; loopBtn.setAttribute('aria-pressed', String(S.loop)); },
    get chapters() { return chapters.slice(); },
    /** Stop-and-ask questions: [{id, t, resume, prompt, choices, answer, reply, choice (null until answered), passed}]. */
    get questions() {
      return QS.map(function (q) {
        var s = QST[q.id];
        return { id: q.id, t: q.t, resume: q.resume, prompt: q.prompt, choices: q.choices.slice(), answer: q.answer, reply: (q.reply || []).slice(), choice: s.choice, passed: s.passed };
      });
    },
    /** The id of the question being asked now, or null. */
    get question() { return qOpen ? qOpen.id : null; },
    /** Answer the open question with choice i (0-based); continueQuestion() plays on from the end of its beat. */
    answer: function (i) { qAnswer(+i); },
    continueQuestion: function () { qContinue(); },
    get chapter() { var i = chapterIndex(S.t); return i >= 0 ? { index: i, t: chapters[i].t, label: chapters[i].label } : null; },
    /** The sound: the <audio> element, or for a live score {kind: 'score', currentTime, paused, duration, level(t0, t1), rendered()}. */
    get audio() { return SND ? SND.facade : null; },
    get frame() { return frame; },
    get error() { return S.error; },
    get startTime() { return startAt; },
    play: function () { play(); return readyP.then(function () {}); },
    pause: pause,
    restart: restart,
    chapterAt: function (t) { var i = chapterIndex(t === undefined ? S.t : t); return i; },
    goToChapter: function (i) { return gotoChapter(i); },
    /** Link to a moment: {url, hash, full (false when this page has no address of its own)}; with no time
     *  while a range is set, the link to that range (#t=a-b). */
    link: function (t) { return t === undefined && RANGE ? linkHere(S.t, RANGE) : linkHere(t === undefined ? S.t : t); },
    /** Link to a range: #t=a-b. */
    linkRange: function (a, b) { return linkHere(+a || 0, { a: +a || 0, b: +b || 0 }); },
    /** The range being looped ({a, b} in seconds), or null. */
    get range() { return RANGE ? { a: RANGE.a, b: RANGE.b } : null; },
    /** Loop a range (seeks to its start), or setRange(null) for the whole video again. */
    setRange: function (a, b) {
      if (a === null || a === undefined) { setRange(null, true); return null; }
      a = +a || 0; b = +b || 0;
      setRange(null, true);
      seekTo(Math.min(a, b));
      setRange({ a: Math.min(a, b), b: Math.max(a, b) }, true);
      return RANGE ? { a: RANGE.a, b: RANGE.b } : null;
    },
    copyLink: copyLink,
    /** Seek and resolve once that frame is drawn. */
    seek: function (t) {
      seekTo(+t || 0);
      return readyP.then(function () {
        return new Promise(function (res) {
          (function wait() {
            if (!S.busy && !S.pending) {
              return S.child ? S.child.paint().then(function () { res(S.t); }, function () { res(S.t); }) : res(S.t);
            }
            setTimeout(wait, 5);
          })();
        });
      });
    },
    on: function (name, fn) { (listeners[name] = listeners[name] || []).push(fn); return function () { listeners[name] = listeners[name].filter(function (f) { return f !== fn; }); }; },
    info: function () { return { title: M.title, width: M.width, height: M.height, fps: fps, duration: DUR, audio: M.audio ? M.audio.mode : 'none', live: !!(SND && SND.kind === 'score'), generator: M.generator }; },
  };
  // A compressed export defines a placeholder with `ready` before this script is unpacked: fill that
  // same object in, so references taken early keep working.
  var stub = W.showtimePlayer && W.showtimePlayer.__stub ? W.showtimePlayer : null;
  if (stub) {
    var early = W.__stpReady;
    delete stub.__stub; delete stub.ready;
    Object.defineProperties(stub, Object.getOwnPropertyDescriptors(API));
    if (early) early(readyP);
    try { delete W.__stpReady; } catch (e) { W.__stpReady = undefined; }
  } else W.showtimePlayer = API;
})();
