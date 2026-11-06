/* watashi v12.3.43dev: the scripts of the panel frame. They were written into
   every page, so the browser downloaded and parsed them again on every click;
   as a file the browser keeps them. They run where they ran before, once the
   page is read (this file is deferred), each part on its own as each sat in
   a script tag of its own. The old cursor loop, the overlay scrollbars and
   the hover listeners that fed the cursor are gone: watashi-ui.js does the
   pointer and the bars now, and nothing in it runs while the page is idle. */
// ---- the sidebar groups (was in the page head) ----
try {
        // watashi v12.2.80: the open group is measured instead of guessed, so
        // a fifth or sixth row can be added later without anyone having to
        // remember a pixel ceiling. The open group and the current page are
        // pulled into view as well, so a row cannot be parked below the fold
        // where nobody looks. The phone drawer never carries the expanded
        // class, which is why it is answered here too.
        (function () {
            var rail = function () {
                return document.getElementById('sidebar');
            };
            var measure = function () {
                var bar = rail();
                if (!bar) {
                    return;
                }
                var wide = bar.classList.contains('expanded');
                if (!wide && bar.classList.contains('active') && window.innerWidth <= 768) {
                    wide = true;
                }
                var groups = bar.querySelectorAll('.nav-item-group');
                for (var i = 0; i < groups.length; i++) {
                    var acc = groups[i].querySelector('.nav-accordion');
                    if (!acc) {
                        continue;
                    }
                    // watashi v12.2.89: the measured height must be set with
                    // an important flag of its own. the round 80 stylesheet
                    // pins an open accordion at 420px with an important of
                    // its own, so this plain inline style always lost. the
                    // ceiling stayed at 420px for a group whose rows are
                    // barely half that, so the first half of every collapse
                    // moved nothing at all and the rest snapped shut. that
                    // dead pause followed by a snap is the kick.
                    if (wide && groups[i].classList.contains('open')) {
                        acc.style.setProperty('max-height', (acc.scrollHeight + 10) + 'px', 'important');
                    } else if (wide) {
                        acc.style.setProperty('max-height', '0px', 'important');
                    } else {
                        acc.style.removeProperty('max-height');
                    }
                }
            };
            var reveal = function () {
                var bar = rail();
                if (!bar) {
                    return;
                }
                var hit = bar.querySelector('.nav-item.active');
                if (!hit) {
                    hit = bar.querySelector('.nav-item-group.open');
                }
                if (!hit || !hit.scrollIntoView) {
                    return;
                }
                // watashi v12.2.89: only scroll when the row really is out
                // of sight, and glide when it is. jumping the list on every
                // class change was a second small jolt of its own.
                var menu = bar.querySelector('.nav-menu');
                if (menu) {
                    var seen = hit.getBoundingClientRect();
                    var frame = menu.getBoundingClientRect();
                    if (seen.top >= frame.top && seen.bottom <= frame.bottom) {
                        return;
                    }
                }
                // watashi v12.3.43dev: the motion picked on the Personalization page comes first
                var motion = document.documentElement.getAttribute('data-motion');
                var calm = motion === 'calm' || (motion !== 'full' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
                hit.scrollIntoView(calm ? { block: 'nearest' } : { block: 'nearest', behavior: 'smooth' });
            };
            var boot = function () {
                var bar = rail();
                if (!bar) {
                    return;
                }
                measure();
                reveal();
                if (window.MutationObserver) {
                    var watch = new MutationObserver(function () {
                        measure();
                        window.setTimeout(reveal, 470);  // watashi v12.2.89: after the glide, not during it
                    });
                    watch.observe(bar, { attributes: true, attributeFilter: ['class'], subtree: true });
                }
                window.addEventListener('resize', measure);
            };
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', boot);
            } else {
                boot();
            }
        })();
} catch (err) { if (window.console) { console.error(err); } }
// ---- the GitHub stars ----
try {
    // watashi v12.3.43dev: the star count was asked of GitHub on every page load.
    // GitHub answers one address 60 times an hour, and from a filtered network
    // the call only hung. It is kept for six hours now and asked when the page
    // is idle, so it never competes with the page itself.
    (function () {
        var el = document.getElementById('gh-star-count');
        if (!el) { return; }
        var KEY = 'ws-gh-stars', HOLD = 6 * 3600 * 1000, hit = null;
        try { hit = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { }
        if (hit && typeof hit.n === 'number') { el.textContent = '\u2605 ' + hit.n; }
        if (hit && Date.now() - (hit.t || 0) < HOLD) { return; }
        var keep = function (n, t) {
            try { localStorage.setItem(KEY, JSON.stringify({ n: n, t: t })); } catch (e) { }
        };
        var ask = function () {
            window.fetch('https://api.github.com/repos/mn-hacker/Watashi-Manager').then(function (res) { return res.json(); }).then(function (data) {
                if (data && typeof data.stargazers_count === 'number') {
                    el.textContent = '\u2605 ' + data.stargazers_count;
                    keep(data.stargazers_count, Date.now());
                } else {
                    keep(hit && hit.n, Date.now() - HOLD + 30 * 60 * 1000);  // try again in half an hour
                }
            }).catch(function () { keep(hit && hit.n, Date.now() - HOLD + 30 * 60 * 1000); });
        };
        if (window.requestIdleCallback) { window.requestIdleCallback(ask, { timeout: 4000 }); } else { window.setTimeout(ask, 1500); }
    })();
} catch (err) { if (window.console) { console.error(err); } }
// ---- theme switch and phone menu (was the main script of the page) ----
        // watashi v12.2.130bs: the head script already set data-theme before the
        // first paint, so here we only mirror it onto the switch.
        const toggleSwitch = document.querySelector('.theme-switch input[type="checkbox"]');
        const currentTheme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        if (toggleSwitch) { toggleSwitch.checked = (currentTheme === 'light'); }

        function watashiPaintTheme(name) {
            var h = document.documentElement;
            h.setAttribute('data-theme', name);
            h.style.backgroundColor = (name === 'light') ? '#e6eaf0' : '#0b0f19';
            h.style.colorScheme = name;
            try { localStorage.setItem('theme', name); } catch (e) { }
        }

        // watashi v12.3.43dev: the switch is the quick way to the light or dark of the
        // Personalization page, so the choice is kept on the account and every
        // browser this admin signs in with opens the same way.
        function switchTheme(e) {
            var mode = e.target.checked ? 'light' : 'dark';
            if (window.wsUI) { window.wsUI.apply({ mode: mode }); window.wsUI.save({ mode: mode }); }
            else { watashiPaintTheme(mode); }
        }
        if (toggleSwitch) { toggleSwitch.addEventListener('change', switchTheme); }


        const menuToggle = document.getElementById('menuToggle');
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('overlay');

        function toggleMenu() {
            const opening = !sidebar.classList.contains('active');
            sidebar.classList.toggle('active');
            overlay.classList.toggle('active');
            // In drawer (touch) mode, also expand so nav labels & sub-menus are visible
            sidebar.classList.toggle('expanded', opening);
        }

        menuToggle.addEventListener('click', toggleMenu);
        overlay.addEventListener('click', toggleMenu);


            
        
        /* watashi v12.2.130al: the card value keeps its colour transition. The
           simulated sparkline and bar chart movement is gone. */
        
        const style = document.createElement('style');
        style.textContent = `
            .card-value {
                transition: color 0.3s ease;
            }
        `;
        document.head.appendChild(style);

        /* watashi v12.2.130al: a demo feeder used to sit here, the same family
           as the card writer below. It pushed the last point of every
           sparkline up or down by a random amount every two seconds.
           Nothing in the panel feeds those shapes with real numbers, so
           the only thing it could ever draw was noise. */

        /* watashi v12.2.130af: a demo script used to sit here. It found cards by
           the English text of their title and, every two seconds, wrote a
           random number into .card-value. In English that overwrote the real
           readings and destroyed the rings drawn inside the CPU and memory
           cards; in Persian the titles never matched, which is why the
           dashboard only misbehaved in one language. The dashboard template
           updates these cards from the server. */

        /* watashi v12.2.130al: a second timer used to sit here and resized the
           bars of every chart at random, exactly like the sparkline
           feeder above. The dashboard draws its own charts from the
           server readings. */

// ---- toasts ----
try {
        /* ===== Watashi toast notifications =====
           Available everywhere as window.wsToast(message, type, duration).
           type: success | error | warning | info (default info). */
        (function watashiToasts() {
            var ICONS = {
                success: 'fa-solid fa-check',
                error: 'fa-solid fa-xmark',
                warning: 'fa-solid fa-triangle-exclamation',
                info: 'fa-solid fa-info'
            };

            function host() {
                var h = document.getElementById('ws-toast-host');
                if (!h) {
                    h = document.createElement('div');
                    h.id = 'ws-toast-host';
                    document.body.appendChild(h);
                }
                return h;
            }

            function postTo(url) {
                // The panel expects these buttons to arrive as a form post, the
                // same way the old theme sent them, so a hidden form carries it.
                var form = document.createElement('form');
                form.method = 'post';
                form.action = url;
                form.style.display = 'none';
                document.body.appendChild(form);
                form.submit();
            }

            /* wsToast(message, type, duration, extra)
               extra.sticky  -> the message waits until it is closed
               extra.action  -> { url, label, busy, method } drawn as a button
               A message with a button never leaves on its own, because the
               change it talks about only lands once that button is pressed. */
            function alreadyUp(message) {
                /* watashi v12.2.130bu: the same sentence twice in a row is not
                   news. The bubble already on screen gets a small counter and
                   stays where it is, so nothing can pile up and cover the page. */
                var up = host().querySelectorAll('.ws-toast');
                for (var s = 0; s < up.length; s++) {
                    if (up[s].getAttribute('data-ws-text') === String(message)) { return up[s]; }
                }
                return null;
            }

            function bumpCount(el) {
                var seen = (parseInt(el.getAttribute('data-ws-seen') || '1', 10) || 1) + 1;
                el.setAttribute('data-ws-seen', String(seen));
                var tag = el.querySelector('.ws-toast-count');
                if (!tag) {
                    tag = document.createElement('span');
                    tag.className = 'ws-toast-count';
                    tag.style.opacity = '0.7';
                    tag.style.fontSize = '0.78em';
                    tag.style.marginInlineStart = '0.4em';
                    var where = el.querySelector('.ws-toast-text');
                    if (where) { where.appendChild(tag); } else { el.appendChild(tag); }
                }
                tag.textContent = '\u00d7' + seen;
                return el;
            }

            window.wsToast = function (message, type, duration, extra) {
                if (!message) return null;
                var twin = alreadyUp(message);
                if (twin) { return bumpCount(twin); }
                var more = extra || {};
                var act = more.action && more.action.url ? more.action : null;
                var waits = more.sticky === true || duration === 0 || !!act;
                var kind = ICONS[type] ? type : 'info';
                var el = document.createElement('div');
                el.className = 'ws-toast ws-toast-' + kind + (waits ? ' ws-toast-stick' : '');
                el.setAttribute('data-ws-text', String(message));  // watashi v12.2.130bu
                var icon = document.createElement('div');
                icon.className = 'ws-toast-icon';
                var i = document.createElement('i');
                i.className = ICONS[kind];
                icon.appendChild(i);
                var body = document.createElement('div');
                body.className = 'ws-toast-body';
                var text = document.createElement('div');
                text.className = 'ws-toast-text';
                text.textContent = String(message);
                body.appendChild(text);
                el.appendChild(icon);
                el.appendChild(body);
                host().appendChild(el);
                requestAnimationFrame(function () {
                    el.classList.add('ws-toast-in');
                });
                var killed = false;
                function kill() {
                    if (killed) return;
                    killed = true;
                    el.classList.remove('ws-toast-in');
                    setTimeout(function () {
                        if (el.parentNode) el.parentNode.removeChild(el);
                    }, 320);
                }
                var life = typeof duration === 'number' && duration > 0 ? duration : 2600;
                var left = life;
                var since = 0;
                var timer = null;
                function run() {
                    if (waits || killed) return;
                    since = Date.now();
                    timer = setTimeout(kill, left);
                }
                function hold() {
                    // A pointer resting on a message means it is being read, so
                    // the countdown stops and later picks up where it left off.
                    if (waits || timer === null) return;
                    clearTimeout(timer);
                    timer = null;
                    left = Math.max(left - (Date.now() - since), 1000);
                }
                el.addEventListener('mouseenter', hold);
                el.addEventListener('mouseleave', run);
                el.addEventListener('focusin', hold);
                el.addEventListener('focusout', run);
                if (act) {
                    var acts = document.createElement('div');
                    acts.className = 'ws-toast-acts';
                    var go = document.createElement('button');
                    go.type = 'button';
                    go.className = 'ws-toast-act';
                    go.textContent = String(act.label || '');
                    go.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        if (go.disabled) return;
                        go.disabled = true;
                        if (act.busy) { go.textContent = String(act.busy); }
                        if (String(act.method || 'post').toLowerCase() === 'get') {
                            window.location.href = act.url;
                        } else {
                            postTo(act.url);
                        }
                    });
                    acts.appendChild(go);
                    body.appendChild(acts);
                }
                if (waits) {
                    var shut = document.createElement('button');
                    shut.type = 'button';
                    shut.className = 'ws-toast-close';
                    shut.setAttribute('aria-label', 'x');
                    var mark = document.createElement('i');
                    mark.className = 'fa-solid fa-xmark';
                    shut.appendChild(mark);
                    shut.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        kill();
                    });
                    el.appendChild(shut);
                } else {
                    el.addEventListener('click', function () {
                        if (timer !== null) clearTimeout(timer);
                        kill();
                    });
                }
                run();
                return el;
            };
        })();
} catch (err) { if (window.console) { console.error(err); } }
// ---- compact sidebar ----
    document.addEventListener('DOMContentLoaded', () => {
        const sidebar = document.getElementById('sidebar');
        const toggleBtn = document.getElementById('sidebarToggleBtn');
        
        if (!sidebar) return;

        // Load preference
        const isCompact = localStorage.getItem('compactSidebar') === 'true';
        if (isCompact) {
            document.body.classList.add('compact-mode');
        }

        // Detect hover-capable (mouse) devices. Touch devices (phones/tablets)
        // use the hamburger toggle instead of auto hover-expand.
        // watashi v12.2.130cd: any-hover / any-pointer, so a touch screen does not take
        // the mouse away from a machine that has one.
        const canHover = window.matchMedia('(any-hover: hover) and (any-pointer: fine)').matches;

        // Auto expand-on-hover only on real mouse devices (and unless in compact mode)
        if (canHover) {
            // watashi v12.2.90: the rail used to close on the bare mouseleave
            // event, and reaching for its own scrollbar is precisely the move
            // that fires it. the thumb sits at the very edge of the rail, the
            // pointer clips that edge on the way to it, and while the thumb is
            // being dragged the pointer wanders outside the rail the whole
            // time. the wheel worked because the wheel never leaves the rows.
            // four things settle it. a press that started inside the rail holds
            // it open until the button comes back up, wherever the pointer
            // goes. leaving through the edge zone counts as staying, not as
            // leaving. every real departure waits out a short grace period that
            // a return cancels, so a brushed border closes nothing. and
            // scrolling the menu itself keeps the rail awake.
            // watashi v12.2.91: round 90 stopped the rail closing when the
            // pointer reached for its own scrollbar, but it bought that with a
            // grace period on every departure and a 24px tolerance band, so an
            // ordinary move away from the menu took 320ms at best and 900ms
            // whenever the pointer was still near the edge, which it always is
            // for the first 24px. that is the delay being reported. the second
            // fault is worse: the pointerup handler only scheduled a close when
            // the release landed outside the rail AND outside the band, so
            // letting go of the scrollbar just next to the rail scheduled
            // nothing at all and the rail stayed open until some later
            // mouseleave that never came. both faults come from guessing intent
            // from coordinates. this asks the plain question instead: is the
            // pointer inside the rail right now. leaving closes it at once with
            // no timer of any kind, a drag that began inside holds it open only
            // until the button comes back up, and a document level watchdog
            // closes it whenever the pointer is seen outside with no drag in
            // hand, so no swallowed event can leave it stuck open again.
            var railHeld = false;
            var railIn = function (ev) {
                if (!ev || ev.clientX === undefined || ev.clientY === undefined) { return false; }
                var box = sidebar.getBoundingClientRect();
                return ev.clientX >= box.left && ev.clientX <= box.right &&
                       ev.clientY >= box.top && ev.clientY <= box.bottom;
            };
            var railWake = function () {
                if (document.body.classList.contains('compact-mode')) { return; }
                sidebar.classList.add('expanded');
            };
            var railShut = function () {
                if (railHeld) { return; }
                if (document.body.classList.contains('compact-mode')) { return; }
                sidebar.classList.remove('expanded');
            };
            sidebar.addEventListener('mouseenter', railWake);
            sidebar.addEventListener('mousemove', railWake);
            sidebar.addEventListener('mouseleave', railShut);
            sidebar.addEventListener('pointerdown', function () {
                railHeld = true;
                railWake();
            });
            window.addEventListener('pointerup', function (ev) {
                if (!railHeld) { return; }
                railHeld = false;
                if (!railIn(ev)) { railShut(); }
            });
            window.addEventListener('blur', function () {
                railHeld = false;
                railShut();
            });
            document.addEventListener('mousemove', function (ev) {
                if (railHeld) { return; }
                if (!sidebar.classList.contains('expanded')) { return; }
                if (railIn(ev)) { return; }
                railShut();
            }, true);
            var railMenu = sidebar.querySelector('.nav-menu');
            if (railMenu) {
                railMenu.addEventListener('scroll', railWake);
            }
        }

        // Toggle button logic
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                sidebar.classList.toggle('expanded');
            });
        }
    });
// ---- the confirmation window ----
try {
        /* ===== Themed confirmation dialog =====
           window.wsConfirm(options) -> Promise that resolves true or false.
           window.wsConfirmDelete(button) -> use it from a submit button that
           lives inside a delete form: it always returns false and submits the
           form only after the user agrees. */
        (function watashiConfirm() {
            var overlay = null;
            var els = null;
            var active = null;

            function build() {
                overlay = document.createElement('div');
                overlay.className = 'ws-confirm-overlay';
                overlay.id = 'ws-confirm-overlay';
                overlay.setAttribute('role', 'dialog');
                overlay.setAttribute('aria-modal', 'true');
                overlay.innerHTML = [
                    '<div class="ws-confirm-box">',
                    '<div class="ws-confirm-head">',
                    '<div class="ws-confirm-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>',
                    '<div style="min-width: 0;">',
                    '<div class="ws-confirm-title"></div>',
                    '<div class="ws-confirm-message"></div>',
                    '</div>',
                    '</div>',
                    '<div class="ws-confirm-actions">',
                    '<button type="button" class="btn ws-confirm-cancel"></button>',
                    '<button type="button" class="btn ws-confirm-ok"></button>',
                    '</div>',
                    '</div>'
                ].join('');
                document.body.appendChild(overlay);

                els = {
                    icon: overlay.querySelector('.ws-confirm-icon i'),
                    title: overlay.querySelector('.ws-confirm-title'),
                    message: overlay.querySelector('.ws-confirm-message'),
                    cancel: overlay.querySelector('.ws-confirm-cancel'),
                    ok: overlay.querySelector('.ws-confirm-ok')
                };

                els.cancel.addEventListener('click', function () {
                    finish(false);
                });
                els.ok.addEventListener('click', function () {
                    finish(true);
                });
                overlay.addEventListener('click', function (e) {
                    if (e.target === overlay) finish(false);
                });
            }

            function onKey(e) {
                if (!active) return;
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopPropagation();
                    finish(false);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    e.stopPropagation();
                    finish(document.activeElement !== els.cancel);
                }
            }

            function finish(result) {
                if (!active) return;
                var current = active;
                active = null;
                document.removeEventListener('keydown', onKey, true);
                overlay.classList.remove('ws-confirm-open');
                window.setTimeout(function () {
                    if (!active) overlay.classList.remove('ws-confirm-danger');
                }, 260);
                if (current.restore && typeof current.restore.focus === 'function') {
                    try {
                        current.restore.focus();
                    } catch (err) {
                        /* the element may be gone, nothing to restore */
                    }
                }
                current.resolve(result);
            }

            window.wsConfirm = function (options) {
                var opts = options || {};
                if (!overlay) build();
                if (active) finish(false);
                return new Promise(function (resolve) {
                    active = { resolve: resolve, restore: document.activeElement };
                    els.title.textContent = opts.title || 'Please confirm';
                    els.message.textContent = opts.message || 'Are you sure you want to continue?';
                    els.ok.textContent = opts.confirmText || 'Confirm';
                    els.cancel.textContent = opts.cancelText || 'Cancel';
                    els.icon.className = opts.icon || (opts.danger ? 'fa-solid fa-triangle-exclamation' : 'fa-solid fa-circle-question');
                    overlay.classList.toggle('ws-confirm-danger', !!opts.danger);
                    document.addEventListener('keydown', onKey, true);
                    window.requestAnimationFrame(function () {
                        overlay.classList.add('ws-confirm-open');
                        window.setTimeout(function () {
                            if (els.ok) els.ok.focus();
                        }, 40);
                    });
                });
            };

            // watashi v12.3.43dev: the two words come translated from the page head now
            window.WS_CONFIRM_WORDS = window.WS_CONFIRM_WORDS || { remove: 'Delete', cancel: 'Cancel' };

            window.wsConfirmDelete = function (btn) {
                var form = btn && btn.closest ? btn.closest('form') : null;
                if (!form) return false;
                var kind = btn.getAttribute('data-confirm-kind') || 'item';
                var raw = btn.getAttribute('data-name');
                var name = '';
                if (raw) {
                    try {
                        name = JSON.parse(raw);
                    } catch (err) {
                        name = raw;
                    }
                }
                var subject = name ? 'the ' + kind + ' "' + name + '"' : 'this ' + kind;
                /* The page may hand us wording that is already in the reader's
                   own language; only fall back to English when it does not. */
                var words = window.WS_CONFIRM_WORDS || {};
                var spoken = function (key, fallback) {
                    var value = btn.getAttribute(key);
                    if (!value) { return fallback; }
                    if (value.charAt(0) === '"') {
                        try { return JSON.parse(value); } catch (err) { return value; }
                    }
                    return value;
                };
                var title = spoken('data-confirm-title', 'Delete ' + kind);
                var message = spoken('data-confirm-message',
                    'Are you sure you want to permanently delete ' + subject + '? This action cannot be undone.');
                var send = function () {
                    form.submit();
                };
                if (typeof window.wsConfirm !== 'function') {
                    if (window.confirm(title)) send();
                    return false;
                }
                window.wsConfirm({
                    title: title,
                    message: message,
                    confirmText: words.remove || 'Delete',
                    cancelText: words.cancel || 'Cancel',
                    danger: true
                }).then(function (agreed) {
                    if (agreed) send();
                });
                return false;
            };
        })();
} catch (err) { if (window.console) { console.error(err); } }
// ---- page jump ----
try {
        /* Type a page number, press enter or the arrow, land on that page.
           The current address already carries the search, sorting, filters and
           rows per page, so only the page number is swapped and everything else
           the admin had set up survives the jump. */
        (function watashiPageJump() {
            'use strict';

            function reject(box, input, max) {
                var msg = box.getAttribute('data-error') || '';
                if (typeof window.wsToast === 'function' && msg) {
                    window.wsToast(msg.replace('%(max)s', max), 'warning');
                }
                input.value = box.getAttribute('data-current') || '1';
                input.focus();
                input.select();
            }

            function go(box) {
                var input = box.querySelector('.pg-jump-input');
                if (!input) {
                    return;
                }
                var max = parseInt(box.getAttribute('data-pages'), 10) || 1;
                var wanted = parseInt(input.value, 10);
                if (isNaN(wanted) || wanted < 1 || wanted > max) {
                    reject(box, input, max);
                    return;
                }
                var current = parseInt(box.getAttribute('data-current'), 10) || 1;
                if (wanted === current) {
                    input.blur();
                    return;
                }
                var url = new URL(window.location.href);
                if (wanted === 1) {
                    url.searchParams.delete('page');
                } else {
                    url.searchParams.set('page', String(wanted - 1));
                }
                window.location.href = url.toString();
            }

            function bind() {
                var boxes = document.querySelectorAll('.pg-jump');
                for (var i = 0; i < boxes.length; i++) {
                    (function (box) {
                        var btn = box.querySelector('.pg-jump-go');
                        var input = box.querySelector('.pg-jump-input');
                        if (btn) {
                            btn.addEventListener('click', function () {
                                go(box);
                            });
                        }
                        if (input) {
                            input.addEventListener('keydown', function (e) {
                                if (e.key === 'Enter' || e.keyCode === 13) {
                                    e.preventDefault();
                                    go(box);
                                }
                            });
                        }
                    })(boxes[i]);
                }
            }

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', bind);
            } else {
                bind();
            }
        })();
} catch (err) { if (window.console) { console.error(err); } }
// ---- right-to-left text ----
try {
        // Reading order for right-to-left text, for the whole panel.
        //
        // Any element that directly holds right-to-left text is given a
        // right-to-left base direction. Structure is left untouched: flex and
        // grid rows, tables, lists and form fields only get the neutral
        // 'plaintext' treatment, so nothing in the layout mirrors.
        //
        // New content is picked up automatically, so pages, dialogs, toasts and
        // anything added later are covered without a second thought.
        (function watashiBidi() {
            var RTL = /[\u0590-\u05ff\u0600-\u06ff\u0700-\u074f\u0750-\u077f\u08a0-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]/;
            var MARK = 'ws-bidi';
            var SOFT = 'ws-bidi-soft';
            // watashi v12.3.44dev: a right-to-left page needs the opposite: a value
            // written only in latin letters (an address, a key, an english name)
            // reads from the left. It only gets the neutral 'plaintext' treatment,
            // so nothing in the layout moves.
            var LATIN = /[A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff]/;
            function rtlPage() {
                return document.documentElement.getAttribute('dir') === 'rtl';
            }
            function hit(text) {
                return rtlPage() ? LATIN.test(text) : RTL.test(text);
            }
            // never touched: code, media and anything not html
            var SKIP = {
                SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, CODE: 1, PRE: 1,
                SVG: 1, CANVAS: 1, IFRAME: 1, IMG: 1, BR: 1, HR: 1, TITLE: 1,
                HTML: 1, HEAD: 1, BODY: 1
            };
            // direction on these would move columns, bullets or items around,
            // so they only get the neutral treatment
            var STRUCTURE = {
                TABLE: 1, THEAD: 1, TBODY: 1, TFOOT: 1, TR: 1, COLGROUP: 1,
                COL: 1, UL: 1, OL: 1, DL: 1, SELECT: 1, OPTGROUP: 1
            };
            var FIELD = { INPUT: 1, TEXTAREA: 1, SELECT: 1, OPTION: 1 };

            var queue = [];
            var waiting = false;

            function isField(el) {
                return FIELD[el.tagName] === 1;
            }

            function ownText(el) {
                var out = '';
                for (var n = el.firstChild; n; n = n.nextSibling) {
                    if (n.nodeType === 3) out += n.nodeValue;
                }
                return out;
            }

            function fieldText(el) {
                var ph = el.getAttribute ? (el.getAttribute('placeholder') || '') : '';
                var val = typeof el.value === 'string' ? el.value : '';
                return ph + ' ' + val + ' ' + ownText(el);
            }

            function isMarked(el) {
                var cl = el.classList;
                return !!cl && (cl.contains(MARK) || cl.contains(SOFT));
            }

            function eligible(el) {
                if (!el || el.nodeType !== 1 || !el.classList) return false;
                var tag = el.tagName;
                if (!tag || SKIP[tag] === 1) return false;
                var ns = el.namespaceURI;
                if (ns && ns.indexOf('1999/xhtml') < 0) return false;
                if (!el.hasAttribute) return false;
                // an explicit direction, or an explicit opt out, is respected
                if (el.hasAttribute('dir') || el.hasAttribute('data-no-bidi')) return false;
                return true;
            }

            function consider(el) {
                if (!eligible(el)) return;
                var field = isField(el);
                var text = field ? fieldText(el) : ownText(el);
                // watashi v12.3.44dev: in a right-to-left page, latin text with no persian in it
                var wanted = rtlPage() ? (LATIN.test(text) && !RTL.test(text)) : RTL.test(text);
                if (!wanted) {
                    // a field can lose its persian value again
                    if (field && isMarked(el)) {
                        el.classList.remove(MARK);
                        el.classList.remove(SOFT);
                        el.classList.remove('ws-bidi-left');
                        el.classList.remove('ws-bidi-right');
                    }
                    return;
                }
                if (isMarked(el) || el.wsBidiQueued) return;
                el.wsBidiQueued = true;
                queue.push(el);
            }

            function apply() {
                waiting = false;
                var list = queue;
                queue = [];
                if (!list.length) return;
                var i, el, facts = [];
                // every measurement first, every change after, so the browser
                // lays the page out once instead of once per element
                for (i = 0; i < list.length; i++) {
                    el = list[i];
                    el.wsBidiQueued = false;
                    if (el.isConnected === false) { facts.push(null); continue; }
                    var cs = window.getComputedStyle ? window.getComputedStyle(el) : null;
                    facts.push({
                        display: (cs && cs.display) || '',
                        align: (cs && cs.textAlign) || '',
                        dir: (cs && cs.direction) || 'ltr'
                    });
                }
                for (i = 0; i < list.length; i++) {
                    if (!facts[i]) continue;
                    el = list[i];
                    if (isMarked(el)) continue;
                    var display = facts[i].display;
                    // The side is pinned before anything else, for the soft path
                    // as well. Reading order needs plaintext, but plaintext also
                    // makes a relative alignment follow the text itself, which
                    // sends a short persian value to the far edge and away from
                    // its own label. A pinned side keeps the design intact.
                    var align = facts[i].align;
                    var rtlBase = facts[i].dir === 'rtl';
                    var side = '';
                    if (align === 'left') { side = 'left'; }
                    else if (align === 'right') { side = 'right'; }
                    else if (align === 'start') { side = rtlBase ? 'right' : 'left'; }
                    else if (align === 'end') { side = rtlBase ? 'left' : 'right'; }
                    if (side) { el.classList.add('ws-bidi-' + side); }
                    var neutral = isField(el) || STRUCTURE[el.tagName] === 1 ||
                        display.indexOf('flex') >= 0 || display.indexOf('grid') >= 0 ||
                        rtlPage();// watashi v12.3.44dev: a right-to-left page never turns an element around
                    if (neutral) {
                        el.classList.add(SOFT);
                        continue;
                    }
                    el.classList.add(MARK);
                }
            }

            function schedule() {
                // watashi v12.3.43dev: nothing queued, nothing to do. The figures of
                // the dashboard are rewritten on every frame while they count, and
                // each rewrite used to book a frame and a timer here only for
                // apply() to find the queue empty.
                if (waiting || !queue.length) return;
                waiting = true;
                // the next painted frame is the cheapest moment to do this,
                // but a frame never comes while a tab is in the background, so
                // a timer backs it up. apply() drains the queue, so whichever
                // arrives first does the work and the other finds nothing.
                if (window.requestAnimationFrame) {
                    window.requestAnimationFrame(apply);
                }
                window.setTimeout(apply, 50);
            }

            function scan(root) {
                if (!root) return;
                if (root.nodeType === 3) {
                    if (hit(root.nodeValue || '')) consider(root.parentElement);// watashi v12.3.44dev: hit()
                    schedule();
                    return;
                }
                if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
                if (root.nodeType === 1) consider(root);
                if (document.createTreeWalker) {
                    var walker = document.createTreeWalker(root, 4, null);
                    var node;
                    while ((node = walker.nextNode())) {
                        if (hit(node.nodeValue || '')) consider(node.parentElement);// watashi v12.3.44dev: hit()
                    }
                } else if (root.getElementsByTagName) {
                    var all = root.getElementsByTagName('*');
                    for (var i = 0; i < all.length; i++) consider(all[i]);
                }
                if (root.querySelectorAll) {
                    var fields = root.querySelectorAll('input, textarea, select, option');
                    for (var f = 0; f < fields.length; f++) consider(fields[f]);
                }
                schedule();
            }

            function watch() {
                if (!window.MutationObserver) return;
                var observer = new MutationObserver(function (records) {
                    for (var i = 0; i < records.length; i++) {
                        var rec = records[i];
                        if (rec.type === 'characterData') {
                            if (hit((rec.target && rec.target.nodeValue) || '')) {// watashi v12.3.44dev: hit()
                                consider(rec.target.parentElement);
                            }
                            continue;
                        }
                        if (rec.type === 'attributes') {
                            consider(rec.target);
                            continue;
                        }
                        var added = rec.addedNodes || [];
                        for (var a = 0; a < added.length; a++) scan(added[a]);
                        if (added.length === 0 && rec.target) consider(rec.target);
                    }
                    schedule();
                });
                observer.observe(document.documentElement, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                    attributes: true,
                    // class and style are never watched, so our own changes
                    // cannot start a loop
                    attributeFilter: ['placeholder', 'value']
                });
            }

            function start() {
                scan(document.body || document.documentElement);
                watch();
                document.addEventListener('input', function (ev) {
                    if (ev && ev.target) consider(ev.target);
                    schedule();
                }, true);
            }

            // anything that builds markup later can ask for a fresh look
            window.wsBidi = {
                scan: scan,
                refresh: function () { scan(document.body || document.documentElement); }
            };

            // watashi v12.3.44dev: the direction was changed on the Personalization
            // page. What was marked for the other direction is taken off and the
            // page is read again.
            document.addEventListener('ws:dir', function () {
                var old = document.querySelectorAll('.' + MARK + ', .' + SOFT + ', .ws-bidi-left, .ws-bidi-right');
                for (var i = 0; i < old.length; i++) {
                    old[i].classList.remove(MARK, SOFT, 'ws-bidi-left', 'ws-bidi-right');
                }
                scan(document.body || document.documentElement);
            });

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', start);
            } else {
                start();
            }
        })();
} catch (err) { if (window.console) { console.error(err); } }
// ---- the profile menu ----
try {
    // the profile badge menu, alive on every page
    (function () {
        var btn = document.getElementById('wsProfBtn');
        var menu = document.getElementById('wsProfMenu');
        if (!btn || !menu) { return; }
        function shut() {
            menu.classList.remove('open');
            btn.setAttribute('aria-expanded', 'false');
        }
        function state() {
            var tag = document.getElementById('wsProfSidebarState');
            if (!tag) { return; }
            var on = document.body.classList.contains('compact-mode');
            tag.textContent = on ? WS_PROF_ON : WS_PROF_OFF;
        }
        btn.addEventListener('click', function (ev) {
            ev.stopPropagation();
            var open = menu.classList.toggle('open');
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            state();
        });
        document.addEventListener('click', function (ev) {
            if (!menu.contains(ev.target) && ev.target !== btn) { shut(); }
        });
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') { shut(); }
        });
        window.wsProfSidebar = function () {
            var on = !document.body.classList.contains('compact-mode');
            document.body.classList.toggle('compact-mode', on);
            localStorage.setItem('compactSidebar', on ? 'true' : 'false');
            var mirror = document.getElementById('accCompact');
            if (mirror) { mirror.checked = on; }
            state();
        };
        state();
    })();
} catch (err) { if (window.console) { console.error(err); } }
