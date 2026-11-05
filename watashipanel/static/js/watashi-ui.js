/* watashi v12.3.43dev: applies the look an admin picks on the Personalization
   page - the mouse pointer, the scrollbars, the motion and light or dark - and
   keeps it alive. Shared by the panel and the sign-in page.

   Nothing in here runs while the page is idle. The old pointer and the old
   overlay scrollbars each ran a loop on every frame for as long as a page was
   open (120 frames a second between them, and about 240 style reads a second
   with nobody touching the mouse). The orbit ring and the stardust below are
   only drawn while the pointer moves and stop by themselves at rest; the
   other pointers are plain CSS cursors, drawn by the operating system. */
(function () {
    'use strict';
    if (window.wsUI && window.wsUI.ready) { return; }
    var html = document.documentElement;
    var STORE = 'ws-ui';
    var CHOICES = {
        mode: ['dark', 'light', 'system'],
        cursor: ['system', 'orbit', 'neon', 'dot', 'reticle', 'stardust'],
        scrollbar: ['auto', 'always', 'classic'],
        motion: ['system', 'full', 'calm']
    };
    var DEFAULTS = { mode: 'dark', cursor: 'system', scrollbar: 'auto', motion: 'system' };
    var ATTR = { mode: 'data-ws-mode', cursor: 'data-cursor', scrollbar: 'data-sb', motion: 'data-motion' };

    function media(q) {
        try { return window.matchMedia(q); } catch (e) { return null; }
    }
    var lightQuery = media('(prefers-color-scheme: light)');
    var calmQuery = media('(prefers-reduced-motion: reduce)');
    var fineQuery = media('(hover: hover) and (pointer: fine)');

    function clean(p) {
        var out = {};
        for (var k in CHOICES) {
            var v = p ? p[k] : '';
            out[k] = CHOICES[k].indexOf(v) >= 0 ? v : DEFAULTS[k];
        }
        return out;
    }

    function read() {
        var p = {};
        for (var k in ATTR) { p[k] = html.getAttribute(ATTR[k]) || ''; }
        // no saved mode yet: the light or dark the head script already chose
        if (!p.mode) { p.mode = html.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }
        return clean(p);
    }

    function themeOf(mode) {
        if (mode === 'system') { return lightQuery && lightQuery.matches ? 'light' : 'dark'; }
        return mode === 'light' ? 'light' : 'dark';
    }

    function calm() {
        var m = html.getAttribute('data-motion');
        return m === 'calm' || (m === 'system' && !!(calmQuery && calmQuery.matches));
    }

    function paintTheme(name) {
        var was = html.getAttribute('data-theme');
        html.setAttribute('data-theme', name);
        html.style.backgroundColor = (name === 'light') ? '#e6eaf0' : '#0b0f19';
        html.style.colorScheme = name;
        try { localStorage.setItem('theme', name); } catch (e) { }
        var box = document.querySelector('.theme-switch input[type="checkbox"]');
        if (box) { box.checked = (name === 'light'); }
        if (was !== name) {
            try { document.dispatchEvent(new CustomEvent('ws:theme', { detail: name })); } catch (e) { }
        }
    }

    function mirror(p) {
        // the sign-in page has no account to ask, so it reads this copy
        try { localStorage.setItem(STORE, JSON.stringify(p)); } catch (e) { }
    }

    /* ---------------- mouse pointers ---------------- */
    var cursor = (function () {
        var name = 'system';
        var ring = null, dust = null, bound = false, mapped = false;
        var mx = 0, my = 0, rx = 0, ry = 0, seen = false, running = false, last = 0;

        // every rule of the page that asks for a hand (or the plain arrow) gets
        // the same pointer in the picked style, with the same strength it had
        function mapRules() {
            if (mapped) { return; }
            mapped = true;
            var P = ':where(html[data-cursor]:not([data-cursor="system"])) ';
            var out = [];
            var walk = function (list) {
                for (var i = 0; i < list.length; i++) {
                    var r = list[i];
                    if (!r.selectorText) {
                        if (r.cssRules) { try { walk(r.cssRules); } catch (e) { } }
                        continue;
                    }
                    var c = (r.style && r.style.getPropertyValue('cursor') || '').trim();
                    if (c !== 'pointer' && c !== 'default') { continue; }
                    var strong = r.style.getPropertyPriority('cursor') === 'important' ? ' !important' : '';
                    out.push(P + ':is(' + r.selectorText + ') { cursor: var(' + (c === 'pointer' ? '--ws-cur-hand' : '--ws-cur') + ')' + strong + '; }');
                }
            };
            for (var s = 0; s < document.styleSheets.length; s++) {
                try { walk(document.styleSheets[s].cssRules || []); } catch (e) { }
            }
            if (!out.length) { return; }
            var tag = document.createElement('style');
            tag.id = 'ws-cursor-map';
            tag.textContent = out.join('\n');
            // last in the document, so it wins every tie with the page's own rules
            (document.body || html).appendChild(tag);
        }

        function step(t) {
            if (!ring) { running = false; return; }
            var gap = last ? Math.min(t - last, 100) : 16.7;
            last = t;
            var pull = calm() ? 1 : 1 - Math.pow(0.6, gap / 16.7);
            rx += (mx - rx) * pull;
            ry += (my - ry) * pull;
            if (Math.abs(mx - rx) < 0.15 && Math.abs(my - ry) < 0.15) { rx = mx; ry = my; running = false; }
            ring.style.translate = rx + 'px ' + ry + 'px';
            if (running) { requestAnimationFrame(step); }
        }

        function onMove(e) {
            if (e.pointerType && e.pointerType !== 'mouse') { return; }
            mx = e.clientX; my = e.clientY;
            if (ring) {
                if (!seen) { rx = mx; ry = my; seen = true; ring.style.translate = rx + 'px ' + ry + 'px'; }
                ring.classList.add('ws-on');
                if (!running) { running = true; last = 0; requestAnimationFrame(step); }
            }
            if (dust) { dust.add(mx, my); }
        }
        function onOver(e) {
            if (!ring || !e.target || e.target.nodeType !== 1) { return; }
            var c = '';
            try { c = getComputedStyle(e.target).cursor || ''; } catch (x) { }
            ring.classList.toggle('ws-hot', c.indexOf('pointer') >= 0);
        }
        function onDown() { if (ring) { ring.classList.add('ws-down'); } }
        function onUp() { if (ring) { ring.classList.remove('ws-down'); } }
        function onOut(e) {
            if (!e.relatedTarget && ring) { ring.classList.remove('ws-on'); seen = false; }
        }
        function bind(on) {
            if (on === bound) { return; }
            bound = on;
            var f = on ? 'addEventListener' : 'removeEventListener';
            document[f]('pointermove', onMove, { passive: true });
            document[f]('pointerover', onOver, { passive: true });
            document[f]('pointerdown', onDown, { passive: true });
            document[f]('pointerup', onUp, { passive: true });
            document[f]('mouseout', onOut, { passive: true });
        }

        function makeDust() {
            var c = document.createElement('canvas');
            c.className = 'ws-dust';
            c.setAttribute('aria-hidden', 'true');
            document.body.appendChild(c);
            var ctx = c.getContext('2d');
            var W = 0, H = 0, parts = [], going = false, lastT = 0, lx = null, ly = null;
            var size = function () {
                var dpr = Math.min(window.devicePixelRatio || 1, 2);
                W = window.innerWidth; H = window.innerHeight;
                c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            };
            size();
            window.addEventListener('resize', size);
            var frame = function (t) {
                var dt = lastT ? Math.min(t - lastT, 50) : 16.7;
                lastT = t;
                ctx.clearRect(0, 0, W, H);
                var light = html.getAttribute('data-theme') === 'light';
                ctx.globalCompositeOperation = light ? 'source-over' : 'lighter';
                for (var i = parts.length - 1; i >= 0; i--) {
                    var p = parts[i];
                    p.life -= dt / p.span;
                    if (p.life <= 0) { parts.splice(i, 1); continue; }
                    p.x += p.vx * dt / 16.7; p.y += p.vy * dt / 16.7; p.vy += 0.012 * dt / 16.7;
                    var a = p.life * p.life;
                    ctx.fillStyle = 'rgba(' + p.c + ',' + (a * 0.22).toFixed(3) + ')';
                    ctx.beginPath(); ctx.arc(p.x, p.y, p.r * 2.6, 0, 6.2832); ctx.fill();
                    ctx.fillStyle = 'rgba(' + p.c + ',' + (a * 0.95).toFixed(3) + ')';
                    ctx.beginPath(); ctx.arc(p.x, p.y, p.r * (0.55 + p.life * 0.45), 0, 6.2832); ctx.fill();
                }
                if (parts.length) { requestAnimationFrame(frame); } else { going = false; lastT = 0; ctx.clearRect(0, 0, W, H); }
            };
            return {
                add: function (x, y) {
                    var light = html.getAttribute('data-theme') === 'light';
                    var tones = light ? ['124,58,237', '8,145,178', '219,39,119'] : ['167,139,250', '34,211,238', '244,114,182', '255,255,255'];
                    var n = 1;
                    if (lx !== null) { n = Math.min(3, 1 + Math.floor(Math.sqrt((x - lx) * (x - lx) + (y - ly) * (y - ly)) / 14)); }
                    lx = x; ly = y;
                    for (var i = 0; i < n; i++) {
                        parts.push({ x: x + (Math.random() - 0.5) * 6, y: y + (Math.random() - 0.5) * 6, vx: (Math.random() - 0.5) * 0.7, vy: (Math.random() - 0.5) * 0.7 - 0.15,
                            r: 0.8 + Math.random() * 1.5, life: 1, span: 520 + Math.random() * 420, c: tones[(Math.random() * tones.length) | 0] });
                    }
                    if (parts.length > 140) { parts.splice(0, parts.length - 140); }
                    if (!going) { going = true; requestAnimationFrame(frame); }
                },
                kill: function () { window.removeEventListener('resize', size); parts = []; if (c.parentNode) { c.parentNode.removeChild(c); } }
            };
        }

        function set(next) {
            name = next;
            if (name !== 'system') { mapRules(); }
            var fine = !fineQuery || fineQuery.matches;
            var wantRing = name === 'orbit' && fine && !!document.body;
            var wantDust = name === 'stardust' && fine && !calm() && !!document.body;
            if (wantRing && !ring) {
                ring = document.createElement('div');
                ring.className = 'ws-orbit';
                ring.setAttribute('aria-hidden', 'true');
                document.body.appendChild(ring);
                seen = false;
            } else if (!wantRing && ring) {
                if (ring.parentNode) { ring.parentNode.removeChild(ring); }
                ring = null;
            }
            if (wantDust && !dust) { dust = makeDust(); } else if (!wantDust && dust) { dust.kill(); dust = null; }
            bind(!!(ring || dust));
        }
        return { set: set };
    })();

    /* ---------------- scrollbars ---------------- */
    var bars = (function () {
        var mode = 'auto', touched = new Set(), near = null, pend = false, lastEv = null;
        var homes = new WeakMap();
        var HIDE = 'transparent transparent';

        function tone(hot) {
            var v = '';
            try { v = getComputedStyle(html).getPropertyValue(hot ? '--ws-sb-thumb-hot' : '--ws-sb-thumb').trim(); } catch (e) { }
            return (v || 'rgba(148, 163, 184, 0.42)') + ' transparent';
        }
        function paint(el, to) {
            var from = el.__wsSbNow || HIDE;
            if (from === to) { return; }
            if (el.__wsSbAnim) { try { el.__wsSbAnim.cancel(); } catch (e) { } }
            touched.add(el);
            el.__wsSbNow = to;
            if (calm() || !el.animate) {
                el.__wsSbAnim = null;
                el.style.scrollbarColor = (to === HIDE) ? '' : to;
                return;
            }
            var anim = el.animate([{ scrollbarColor: from }, { scrollbarColor: to }],
                { duration: to === HIDE ? 420 : 140, easing: 'ease-out', fill: 'forwards' });
            el.__wsSbAnim = anim;
            if (to === HIDE) {
                anim.onfinish = function () { if (el.__wsSbAnim === anim) { anim.cancel(); el.__wsSbAnim = null; } };
            }
        }
        function show(el, hot) {
            paint(el, tone(hot));
            clearTimeout(el.__wsSbT);
            el.__wsSbT = setTimeout(function () { if (near !== el) { paint(el, HIDE); } }, 900);
        }

        function onScroll(e) {
            if (mode !== 'auto') { return; }
            var el = e.target;
            if (el === document) { el = document.scrollingElement || html; }
            if (!el || el.nodeType !== 1) { return; }
            show(el, near === el);
        }

        // the scroll box an element lives in, read once per element
        function home(el) {
            var start = el, hops = 0;
            while (el && el.nodeType === 1 && hops < 12) {
                if (homes.has(el)) { var h = homes.get(el); homes.set(start, h); return h; }
                var cs = getComputedStyle(el);
                if (/(auto|scroll)/.test(cs.overflowY) || el === document.scrollingElement) {
                    var box = { el: el, rtl: cs.direction === 'rtl' };
                    homes.set(start, box);
                    return box;
                }
                el = el.parentElement; hops++;
            }
            homes.set(start, null);
            return null;
        }
        function checkNear() {
            pend = false;
            var e = lastEv, hit = null;
            if (!e || mode !== 'auto') { return; }
            var box = e.target && e.target.nodeType === 1 ? home(e.target) : null;
            if (box && box.el.scrollHeight > box.el.clientHeight + 1) {
                var r = box.el === document.scrollingElement ? { left: 0, right: window.innerWidth } : box.el.getBoundingClientRect();
                var x = e.clientX;
                var edge = box.rtl ? (x >= r.left - 2 && x <= r.left + 18) : (x <= r.right + 2 && x >= r.right - 18);
                if (edge) { hit = box.el; }
            }
            if (hit === near) { return; }
            var was = near;
            near = hit;
            if (was) { show(was, false); }
            if (hit) { clearTimeout(hit.__wsSbT); paint(hit, tone(true)); }
        }
        function onPointer(e) {
            if (e.pointerType && e.pointerType !== 'mouse') { return; }
            lastEv = e;
            if (!pend) { pend = true; requestAnimationFrame(checkNear); }
        }
        var bound = false;
        function set(next) {
            mode = next;
            if (mode !== 'auto') {
                touched.forEach(function (el) {
                    if (el.__wsSbAnim) { try { el.__wsSbAnim.cancel(); } catch (e) { } }
                    clearTimeout(el.__wsSbT);
                    el.__wsSbAnim = null; el.__wsSbNow = HIDE; el.style.scrollbarColor = '';
                });
                touched.clear();
                near = null;
            }
            if (!bound) {
                bound = true;
                document.addEventListener('scroll', onScroll, { capture: true, passive: true });
                document.addEventListener('pointermove', onPointer, { passive: true });
            }
        }
        return { set: set };
    })();

    /* ---------------- the whole look ---------------- */
    function apply(p) {
        var now = read();
        var want = clean(Object.assign({}, now, p || {}));
        html.setAttribute('data-ws-mode', want.mode);
        html.setAttribute('data-cursor', want.cursor);
        html.setAttribute('data-sb', want.scrollbar);
        html.setAttribute('data-motion', want.motion);
        paintTheme(themeOf(want.mode));
        cursor.set(want.cursor);
        bars.set(want.scrollbar);
        mirror(want);
        return want;
    }

    var saveTimer = null, pending = {}, waiting = [];
    function save(p, done) {
        var cfg = window.WS_UI_CFG || {};
        if (done) { waiting.push(done); }
        if (!cfg.save) {
            var cbs = waiting; waiting = [];
            cbs.forEach(function (f) { f(false); });
            return;
        }
        for (var k in p) { pending[k] = p[k]; }
        clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
            var body = pending, cbs = waiting;
            pending = {}; waiting = [];
            var end = function (ok, answer) { cbs.forEach(function (f) { f(ok, answer); }); };
            window.fetch(cfg.save, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrf || '', 'X-Requested-With': 'fetch' },
                body: JSON.stringify({ prefs: body, csrf_token: cfg.csrf || '' })
            }).then(function (r) {
                return r.json().then(function (j) { end(!!(j && j.ok), j); }, function () { end(false, null); });
            }).catch(function () { end(false, null); });
        }, 300);
    }

    if (lightQuery && lightQuery.addEventListener) {
        lightQuery.addEventListener('change', function () {
            if (html.getAttribute('data-ws-mode') === 'system') { paintTheme(themeOf('system')); }
        });
    }
    if (fineQuery && fineQuery.addEventListener) {
        fineQuery.addEventListener('change', function () { cursor.set(read().cursor); });
    }

    var start = function () {
        var p = read();
        cursor.set(p.cursor);
        bars.set(p.scrollbar);
        // only a panel page knows the account's choice; the sign-in page reads it
        if (window.WS_UI_CFG) { mirror(p); }
    };
    window.wsUI = { ready: true, apply: apply, save: save, read: read, clean: clean, CHOICES: CHOICES, DEFAULTS: DEFAULTS };
    if (document.body) { start(); } else { document.addEventListener('DOMContentLoaded', start); }
})();
