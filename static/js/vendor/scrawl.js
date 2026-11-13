/*!
 * scrawl v0.1.0 — handmade UI design system
 * MIT License
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  // ─────────────────────────────────────────────────────────────────────────
  // FILTERS
  //
  // Key to smooth lines: feTurbulence → feGaussianBlur → feDisplacementMap
  // Raw turbulence noise has high-frequency components that create jagged
  // pixel-level jitter. Blurring the noise map first removes those, leaving
  // only long-wavelength variation → smooth, organic hand-drawn curves.
  // ─────────────────────────────────────────────────────────────────────────

  function makeFilter(id, freq, octaves, seed, scale, expand, preBlur) {
    var f = document.createElementNS(NS, 'filter');
    f.id = id;
    f.setAttribute('x', '-' + expand + '%');
    f.setAttribute('y', '-' + expand + '%');
    f.setAttribute('width',  (100 + expand * 2) + '%');
    f.setAttribute('height', (100 + expand * 2) + '%');
    f.setAttribute('color-interpolation-filters', 'sRGB');

    var t = document.createElementNS(NS, 'feTurbulence');
    t.setAttribute('type', 'fractalNoise');
    t.setAttribute('baseFrequency', freq);
    t.setAttribute('numOctaves', octaves);
    t.setAttribute('seed', seed);
    t.setAttribute('result', 'rawNoise');

    // Blur the noise map BEFORE displacement so the displacement field
    // follows smooth organic curves instead of pixel-level jitter.
    // This is the only blur — no post-displacement blur (that blurs content).
    var pre = document.createElementNS(NS, 'feGaussianBlur');
    pre.setAttribute('in', 'rawNoise');
    pre.setAttribute('stdDeviation', String(preBlur));
    pre.setAttribute('result', 'n');

    var d = document.createElementNS(NS, 'feDisplacementMap');
    d.setAttribute('in', 'SourceGraphic');
    d.setAttribute('in2', 'n');
    d.setAttribute('scale', scale);
    d.setAttribute('xChannelSelector', 'R');
    d.setAttribute('yChannelSelector', 'G');

    f.appendChild(t); f.appendChild(pre); f.appendChild(d);
    return f;
  }

  function makeGrainFilter() {
    var f = document.createElementNS(NS, 'filter');
    f.id = 'sw-grain';
    f.setAttribute('x', '0%'); f.setAttribute('y', '0%');
    f.setAttribute('width', '100%'); f.setAttribute('height', '100%');

    var t = document.createElementNS(NS, 'feTurbulence');
    t.setAttribute('type', 'fractalNoise');
    t.setAttribute('baseFrequency', '0.65');
    t.setAttribute('numOctaves', '3');
    t.setAttribute('stitchTiles', 'stitch');
    t.setAttribute('result', 'n');

    var m = document.createElementNS(NS, 'feColorMatrix');
    m.setAttribute('type', 'saturate');
    m.setAttribute('values', '0');
    m.setAttribute('in', 'n');
    m.setAttribute('result', 'g');

    var bld = document.createElementNS(NS, 'feBlend');
    bld.setAttribute('in', 'SourceGraphic');
    bld.setAttribute('in2', 'g');
    bld.setAttribute('mode', 'multiply');
    bld.setAttribute('result', 'bl');

    var c = document.createElementNS(NS, 'feComposite');
    c.setAttribute('in', 'bl');
    c.setAttribute('in2', 'SourceGraphic');
    c.setAttribute('operator', 'in');

    f.appendChild(t); f.appendChild(m); f.appendChild(bld); f.appendChild(c);
    return f;
  }

  function injectFilterSVG() {
    if (document.getElementById('sw-filter-svg')) return;
    var svg = document.createElementNS(NS, 'svg');
    svg.id = 'sw-filter-svg';
    svg.setAttribute('aria-hidden', 'true');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';

    var defs = document.createElementNS(NS, 'defs');
    //                     id      freq    oct seed scale expand preBlur
    defs.appendChild(makeFilter('sw-f1', '0.009', 2, 1,  3,  8,  7)); // whisper
    defs.appendChild(makeFilter('sw-f2', '0.008', 2, 2,  5,  8,  6)); // doodle
    defs.appendChild(makeFilter('sw-f3', '0.007', 3, 3,  9, 12,  5)); // sketch
    defs.appendChild(makeFilter('sw-f4', '0.006', 3, 4, 14, 18,  4)); // chaos
    defs.appendChild(makeGrainFilter());

    svg.appendChild(defs);
    document.body.insertBefore(svg, document.body.firstChild);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // STICKER SYMBOLS
  //
  // Each sticker has three layers for the crayon-fill look:
  //   1. Solid filled base shape
  //   2. Hatch lines (simulate visible pencil strokes inside the shape)
  //   3. Bold irregular outline on top
  // ─────────────────────────────────────────────────────────────────────────

  function el(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function sym(id, vb, children) {
    var s = el('symbol', { id: id, viewBox: vb });
    children.forEach(function (c) { s.appendChild(c); });
    return s;
  }

  function buildStickers() {
    var stroke  = { stroke: 'currentColor', fill: 'none',    'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
    var hatches = { stroke: 'currentColor', fill: 'none',    'stroke-linecap': 'round', opacity: '0.22', 'stroke-width': '3' };
    var outline = { stroke: 'currentColor', fill: 'none',    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '5' };
    var base    = { fill:   'currentColor', stroke: 'none' };

    return [
      // ── STAR ──
      sym('sw-star', '0 0 100 100', [
        el('path', Object.assign({}, base, {
          d: 'M50 4 L62 36 L96 36 L70 56 L81 89 L50 70 L19 89 L30 56 L4 36 L38 36 Z'
        })),
        el('path', Object.assign({}, hatches, {
          d: 'M28 44 C38 42 58 44 68 42 M27 52 C35 50 58 52 70 50 M30 60 C40 58 56 60 66 58 M36 68 C43 66 54 68 60 66'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M50 4 L62 36 L96 36 L70 56 L81 89 L50 70 L19 89 L30 56 L4 36 L38 36 Z'
        })),
      ]),

      // ── HEART ──
      sym('sw-heart', '0 0 100 100', [
        el('path', Object.assign({}, base, {
          d: 'M50 84 C48 82 8 58 8 32 C8 17 20 6 33 6 C41 6 47 10 50 16 C53 10 59 6 67 6 C80 6 92 17 92 32 C92 58 52 82 50 84 Z'
        })),
        el('path', Object.assign({}, hatches, {
          d: 'M16 36 C26 34 44 36 54 34 C64 36 74 34 82 35 M14 44 C24 42 44 44 54 42 C64 44 76 42 84 43 M13 52 C24 50 44 52 54 50 C64 52 76 50 85 51 M14 60 C24 58 44 60 54 58 C63 60 74 58 83 59 M20 68 C28 66 44 68 54 66 C62 68 72 66 79 67 M30 76 C38 74 46 76 54 74 C60 76 66 74 70 75'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M50 84 C48 82 8 58 8 32 C8 17 20 6 33 6 C41 6 47 10 50 16 C53 10 59 6 67 6 C80 6 92 17 92 32 C92 58 52 82 50 84 Z'
        })),
      ]),

      // ── SPARKLES ──
      sym('sw-sparkles', '0 0 100 100', [
        el('path', Object.assign({}, base, {
          d: 'M50 4 L54 44 L94 50 L54 56 L50 96 L46 56 L6 50 L46 44 Z'
        })),
        el('path', Object.assign({}, base, {
          d: 'M22 12 L25 28 L40 30 L25 32 L22 48 L19 32 L4 30 L19 28 Z', opacity: '0.8'
        })),
        el('path', Object.assign({}, base, {
          d: 'M80 56 L82.5 68 L94 70 L82.5 72 L80 84 L77.5 72 L66 70 L77.5 68 Z', opacity: '0.8'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M50 4 L54 44 L94 50 L54 56 L50 96 L46 56 L6 50 L46 44 Z'
        })),
      ]),

      // ── ARROW ──
      sym('sw-arrow', '0 0 100 60', [
        el('path', Object.assign({}, base, {
          d: 'M4 32 C10 24 26 12 50 18 C64 22 72 26 80 30 C72 34 64 38 50 42 C26 48 10 36 4 28 Z'
        })),
        el('path', Object.assign({}, base, {
          d: 'M72 14 L96 30 L72 46 Z'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M4 30 C10 22 28 10 52 17 C66 22 74 26 80 30 C74 34 66 38 52 43 C28 50 10 38 4 30 M72 14 L96 30 L72 46'
        })),
      ]),

      // ── FLOWER ──
      sym('sw-flower', '0 0 100 100', [
        el('ellipse', Object.assign({}, base, { cx: '50', cy: '23', rx: '10', ry: '18' })),
        el('ellipse', Object.assign({}, base, { cx: '77', cy: '50', rx: '18', ry: '10' })),
        el('ellipse', Object.assign({}, base, { cx: '50', cy: '77', rx: '10', ry: '18' })),
        el('ellipse', Object.assign({}, base, { cx: '23', cy: '50', rx: '18', ry: '10' })),
        el('ellipse', Object.assign({}, base, { cx: '73', cy: '27', rx: '10', ry: '18', transform: 'rotate(45 73 27)', opacity: '0.85' })),
        el('ellipse', Object.assign({}, base, { cx: '73', cy: '73', rx: '10', ry: '18', transform: 'rotate(-45 73 73)', opacity: '0.85' })),
        el('ellipse', Object.assign({}, base, { cx: '27', cy: '73', rx: '10', ry: '18', transform: 'rotate(45 27 73)', opacity: '0.85' })),
        el('ellipse', Object.assign({}, base, { cx: '27', cy: '27', rx: '10', ry: '18', transform: 'rotate(-45 27 27)', opacity: '0.85' })),
        el('circle', { cx: '50', cy: '50', r: '18', fill: '#f7c948', stroke: 'none' }),
        el('circle', { cx: '50', cy: '50', r: '10', fill: '#e8a200', stroke: 'none' }),
        el('path', Object.assign({}, hatches, {
          d: 'M44 45 C47 43 52 45 56 43 M43 50 C47 48 53 50 57 48 M44 55 C47 53 52 55 56 53'
        })),
      ]),

      // ── BURST ──
      sym('sw-burst', '0 0 100 100', [
        el('path', Object.assign({}, base, {
          d: 'M50 2 L54 36 L68 6 L60 38 L82 18 L64 44 L95 38 L68 54 L98 58 L68 62 L94 76 L64 64 L78 90 L56 70 L60 98 L48 72 L42 98 L46 70 L24 90 L38 64 L8 76 L32 62 L2 58 L32 54 L6 38 L38 44 L20 18 L40 38 L34 6 L46 36 Z'
        })),
        el('path', Object.assign({}, hatches, {
          d: 'M44 44 C47 42 53 44 56 42 M43 50 C47 48 53 50 57 48 M44 56 C47 54 53 56 56 54'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M50 2 L54 36 L68 6 L60 38 L82 18 L64 44 L95 38 L68 54 L98 58 L68 62 L94 76 L64 64 L78 90 L56 70 L60 98 L48 72 L42 98 L46 70 L24 90 L38 64 L8 76 L32 62 L2 58 L32 54 L6 38 L38 44 L20 18 L40 38 L34 6 L46 36 Z'
        })),
      ]),

      // ── WAVE ──
      sym('sw-wave', '0 0 120 20', [
        el('path', Object.assign({}, stroke, {
          'stroke-width': '4',
          d: 'M0 10 C12 3 22 17 34 10 C46 3 56 17 68 10 C80 3 90 17 102 10 C108 7 114 13 120 10'
        })),
      ]),

      // ── CIRCLE (highlight ring) ──
      sym('sw-circle', '0 0 110 80', [
        el('ellipse', Object.assign({}, stroke, {
          cx: '55', cy: '40', rx: '50', ry: '32',
          'stroke-width': '5',
          transform: 'rotate(3 55 40)'
        })),
      ]),

      // ── CHECK ──
      sym('sw-check', '0 0 100 80', [
        el('path', Object.assign({}, base, {
          d: 'M5 45 C14 36 34 57 44 67 C54 50 70 22 92 8 C94 6 96 6 97 9 C82 25 68 44 52 70 C50 73 46 73 44 70 C34 60 14 42 3 48 Z'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M8 45 C20 36 36 55 46 66 C55 48 72 22 92 10'
        })),
      ]),

      // ── LIGHTNING ──
      sym('sw-lightning', '0 0 60 100', [
        el('path', Object.assign({}, base, {
          d: 'M38 2 L14 52 L30 52 L22 98 L50 44 L34 44 Z'
        })),
        el('path', Object.assign({}, hatches, {
          d: 'M22 30 L30 28 M20 40 L30 38 M24 52 L32 50'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M38 2 L14 52 L30 52 L22 98 L50 44 L34 44 Z'
        })),
      ]),

      // ── PIN ──
      sym('sw-pin', '0 0 60 100', [
        el('circle', Object.assign({}, base, { cx: '30', cy: '26', r: '22' })),
        el('path', Object.assign({}, hatches, {
          d: 'M20 22 C24 20 34 22 38 20 M18 28 C22 26 36 28 40 26 M20 34 C24 32 34 34 38 32'
        })),
        el('circle', { cx: '30', cy: '26', r: '8', fill: 'none', stroke: 'rgba(255,255,255,0.5)', 'stroke-width': '3' }),
        el('line', Object.assign({}, stroke, { x1: '30', y1: '48', x2: '30', y2: '96', 'stroke-width': '5' })),
        el('circle', Object.assign({}, stroke, { cx: '30', cy: '26', r: '22', 'stroke-width': '4' })),
      ]),

      // ── CLOUD ──
      sym('sw-cloud', '0 0 120 80', [
        el('path', Object.assign({}, base, {
          d: 'M22 62 C10 62 4 52 4 44 C4 34 12 26 22 26 C22 14 32 6 46 8 C52 2 64 2 72 8 C84 4 96 14 94 28 C106 30 118 40 114 54 C112 62 102 66 92 64 Z'
        })),
        el('path', Object.assign({}, hatches, {
          d: 'M22 42 C32 40 52 42 72 40 C82 42 90 40 96 41 M18 52 C28 50 52 52 72 50 C82 52 90 50 100 51'
        })),
        el('path', Object.assign({}, outline, {
          d: 'M22 62 C10 62 4 52 4 44 C4 34 12 26 22 26 C22 14 32 6 46 8 C52 2 64 2 72 8 C84 4 96 14 94 28 C106 30 118 40 114 54 C112 62 102 66 92 64 Z'
        })),
      ]),
    ];
  }

  function injectSpriteSVG() {
    if (document.getElementById('sw-sprite-svg')) return;
    var svg = document.createElementNS(NS, 'svg');
    svg.id = 'sw-sprite-svg';
    svg.setAttribute('aria-hidden', 'true');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';

    var defs = document.createElementNS(NS, 'defs');
    buildStickers().forEach(function (s) { defs.appendChild(s); });
    svg.appendChild(defs);
    document.body.insertBefore(svg, document.body.firstChild);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // STICKER MOUNTING  data-sticker="name"
  // ─────────────────────────────────────────────────────────────────────────

  function initStickers() {
    document.querySelectorAll('[data-sticker]').forEach(function (host) {
      if (host.dataset.stickerInit) return;
      host.dataset.stickerInit = '1';

      var name  = host.dataset.sticker;
      var color = host.dataset.color || 'currentColor';
      var size  = host.dataset.size  || '2em';

      var svg  = document.createElementNS(NS, 'svg');
      svg.setAttribute('width',  size);
      svg.setAttribute('height', size);
      svg.setAttribute('aria-hidden', 'true');
      svg.style.cssText = 'color:' + color + ';display:block;overflow:visible';

      var use = document.createElementNS(NS, 'use');
      use.setAttribute('href', '#sw-' + name);
      svg.appendChild(use);

      while (host.firstChild) host.removeChild(host.firstChild);
      host.appendChild(svg);
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // CANVAS GRAIN OVERLAY
  // ─────────────────────────────────────────────────────────────────────────

  var _grainCvs = null;
  function grainCanvas() {
    if (_grainCvs) return _grainCvs;
    _grainCvs = document.createElement('canvas');
    _grainCvs.width = 256; _grainCvs.height = 256;
    var ctx = _grainCvs.getContext('2d');
    var img = ctx.createImageData(256, 256);
    var d = img.data;
    for (var i = 0; i < d.length; i += 4) {
      var v = (Math.random() * 255) | 0;
      d[i] = d[i + 1] = d[i + 2] = v;
      d[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    return _grainCvs;
  }

  function initGrain() {
    var targets = document.querySelectorAll('.sw-grain,.sw-texture-pencil,.sw-texture-marker,.sw-texture-watercolor');
    targets.forEach(function (host) {
      if (host.dataset.grainInit) return;
      host.dataset.grainInit = '1';

      var c = document.createElement('canvas');
      c.width = 256; c.height = 256;
      c.getContext('2d').drawImage(grainCanvas(), 0, 0);

      var opacity = host.classList.contains('sw-texture-watercolor') ? '0.06'
                  : host.classList.contains('sw-texture-pencil')     ? '0.14' : '0.09';

      c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;' +
                        'border-radius:inherit;z-index:0;opacity:' + opacity + ';mix-blend-mode:multiply';
      if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
      host.appendChild(c);
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // SPIRAL BINDING  .sw-spiral-binding
  // ─────────────────────────────────────────────────────────────────────────

  function initSpiral() {
    document.querySelectorAll('.sw-spiral-binding, .sw-spiral-left').forEach(function (host) {
      if (host.dataset.spiralInit) return;
      host.dataset.spiralInit = '1';

      var isLeft = host.classList.contains('sw-spiral-left');
      var size = isLeft ? host.offsetHeight : host.offsetWidth;
      var ringSpacing = 28;
      var rings = Math.max(2, Math.floor(size / ringSpacing));
      var w = isLeft ? 30 : size;
      var h = isLeft ? size : 30;

      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('class', 'sw-spiral-rings');
      svg.setAttribute('width',  isLeft ? '30' : '100%');
      svg.setAttribute('height', isLeft ? '100%' : '30');
      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      svg.setAttribute('preserveAspectRatio', 'none');
      svg.setAttribute('aria-hidden', 'true');

      for (var i = 0; i < rings; i++) {
        var pos = (size / rings) * i + (size / rings) / 2;
        var cx = isLeft ? 14 : pos;
        var cy = isLeft ? pos : 14;

        /* coil arc */
        var arc = document.createElementNS(NS, 'path');
        if (isLeft) {
          arc.setAttribute('d', 'M 26 '+(cy-10)+' C 30 '+(cy-10)+' 30 '+(cy+10)+' 26 '+(cy+10));
        } else {
          arc.setAttribute('d', 'M '+(cx-10)+' 26 C '+(cx-10)+' 30 '+(cx+10)+' 30 '+(cx+10)+' 26');
        }
        arc.setAttribute('fill', 'none');
        arc.setAttribute('stroke', '#999');
        arc.setAttribute('stroke-width', '2.5');
        arc.setAttribute('stroke-linecap', 'round');

        /* ring oval */
        var oval = document.createElementNS(NS, 'ellipse');
        oval.setAttribute('cx', String(cx));
        oval.setAttribute('cy', String(cy));
        oval.setAttribute(isLeft ? 'rx' : 'rx', '9');
        oval.setAttribute(isLeft ? 'ry' : 'ry', '9');
        oval.setAttribute('rx', isLeft ? '6' : '9');
        oval.setAttribute('ry', isLeft ? '9' : '6');
        oval.setAttribute('fill', '#f0f0f0');
        oval.setAttribute('stroke', '#aaa');
        oval.setAttribute('stroke-width', '2');

        svg.appendChild(oval);
        svg.appendChild(arc);
      }

      host.insertBefore(svg, host.firstChild);
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ARC TEXT  data-arc-text  data-arc-radius="80"  data-arc-flip="1"
  // ─────────────────────────────────────────────────────────────────────────

  function initArcText() {
    document.querySelectorAll('[data-arc-text]').forEach(function (host) {
      if (host.dataset.arcInit) return;
      host.dataset.arcInit = '1';

      var text   = (host.dataset.arcText || host.textContent).trim();
      var r      = parseInt(host.dataset.arcRadius || '80', 10);
      var flip   = host.dataset.arcFlip === '1';
      var fs     = host.dataset.arcSize  || getComputedStyle(host).fontSize || '22px';
      var ff     = host.dataset.arcFont  || getComputedStyle(host).fontFamily || "'Permanent Marker',cursive";
      var color  = host.dataset.arcColor || 'currentColor';

      var svgW = r * 2 + 40;
      var svgH = r + parseInt(fs, 10) + 20;

      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('width',  svgW);
      svg.setAttribute('height', svgH);
      svg.setAttribute('viewBox', '0 0 ' + svgW + ' ' + svgH);
      svg.setAttribute('overflow', 'visible');
      svg.setAttribute('aria-label', text);

      var defs = document.createElementNS(NS, 'defs');
      var pid  = 'sw-arc-' + Math.random().toString(36).slice(2, 8);
      var path = document.createElementNS(NS, 'path');
      var oy   = flip ? parseInt(fs, 10) + 10 : svgH;

      path.setAttribute('id', pid);
      path.setAttribute('d',
        flip
          ? 'M 20 ' + oy + ' A ' + r + ' ' + r + ' 0 0 0 ' + (svgW - 20) + ' ' + oy
          : 'M 20 ' + oy + ' A ' + r + ' ' + r + ' 0 0 1 ' + (svgW - 20) + ' ' + oy
      );
      defs.appendChild(path);

      var textEl = document.createElementNS(NS, 'text');
      textEl.setAttribute('font-family', ff);
      textEl.setAttribute('font-size',   fs);
      textEl.setAttribute('fill',        color);
      textEl.setAttribute('text-anchor', 'middle');

      var tp = document.createElementNS(NS, 'textPath');
      tp.setAttribute('href', '#' + pid);
      tp.setAttribute('startOffset', '50%');
      tp.textContent = text;

      textEl.appendChild(tp);
      svg.appendChild(defs);
      svg.appendChild(textEl);

      host.textContent = '';
      host.appendChild(svg);
      host.style.display = 'inline-block';
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // INIT
  // ─────────────────────────────────────────────────────────────────────────

  function init() {
    injectFilterSVG();
    injectSpriteSVG();
    initStickers();
    initGrain();
    initSpiral();
    initArcText();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  if (typeof window !== 'undefined') {
    window.scrawl = window.scrawl || {};
    Object.assign(window.scrawl, { init: init, initStickers: initStickers, initGrain: initGrain, initSpiral: initSpiral, initArcText: initArcText });
  }
})();
