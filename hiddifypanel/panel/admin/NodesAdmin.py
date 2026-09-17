"""Watashi v12.2.129: the nodes page.

A node is an exit this server can send traffic through. WARP is the first one,
and Psiphon, Tor and a plain WireGuard peer for a paid provider are meant to
sit beside it later, which is why nothing here is written as "the warp page".

Everything this page has to know needs root: engine.conf is owned by root with
mode 600 and systemctl is not something the panel user may call. So reading
and writing both go through sudo common/commander.py, which validates its own
input again and lands in other/warp/node.sh, which validates it a third time.
A broken form on this page can never turn into a shell command.

What goes behind a node is a panel decision, not a hardcoded one any more. Up
to this round both routing templates carried a fixed list of about forty five
sites that were forced through WARP with no way to take anything out of it.
The list is grouped now, the groups live in the warp_presets config key, and
the only group that is on by default is the local one, which goes THROUGH the
node on purpose so the real address of this server never touches an Iranian
site and never gets it blocked.
"""
import json
import re
import subprocess

from flask import render_template, request
from flask_classful import FlaskView, route
from flask_babel import gettext as _
from flask import current_app as app

from hiddifypanel.auth import login_required
from hiddifypanel.models import ConfigEnum, Role, hconfig, set_hconfig
from hiddifypanel.panel.run_commander import commander, Command

# The groups both routing templates know. The names are the contract between
# this file, the templates and the warp_presets key, so they are checked here
# and never taken from the browser as they came.
WS_PRESETS = ('ir', 'google', 'ai', 'streaming', 'social', 'dev', 'tools')

# The engine settings that live in engine.conf. node.sh refuses anything else.
WS_MODES = ('warp', 'gool', 'cfon')
WS_IPVS = ('auto', '4', '6')
WS_COUNTRIES = ('AT', 'AU', 'BE', 'BG', 'CA', 'CH', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI',
                'FR', 'GB', 'HR', 'HU', 'IE', 'IN', 'IT', 'JP', 'LV', 'NL', 'NO', 'PL',
                'PT', 'RO', 'RS', 'SE', 'SG', 'SK', 'US')
WS_DNS_RE = re.compile(r'^[0-9a-fA-F:.]{3,45}$')
# Measured in round 128 and kept as a rule: an https readiness address never
# lets the socks port open, so only a plain http one is accepted.
WS_TEST_URL_RE = re.compile(r'^http://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]{3,120}$')
# A WARP+ key looks like 4YHZ86Q7-D9xT82P1-62E8P0ZT. Empty clears it.
WS_KEY_RE = re.compile(r'^[A-Za-z0-9]{8}-[A-Za-z0-9]{8}-[A-Za-z0-9]{8}$')
WS_SITE_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$')
WS_SITES_MAX = 300
WS_READ_TIMEOUT = 30
WS_MODE_KEYS = ('MODE', 'COUNTRY', 'IPV', 'SCAN', 'DNS', 'TEST_URL')


def ws_form_token():
    """The token every write on this page carries, the same habit the account
    and the backup pages already keep."""
    try:
        from flask_wtf.csrf import generate_csrf
        return generate_csrf()
    except BaseException:
        return ''


def ws_signed():
    sent = (request.form.get('csrf_token')
            or request.headers.get('X-CSRFToken')
            or request.headers.get('X-CSRF-Token') or '')
    if not sent:
        body = request.get_json(silent=True) or {}
        sent = str(body.get('csrf_token', '') or '')
    if not sent:
        return False
    try:
        from flask_wtf.csrf import validate_csrf
        validate_csrf(sent)
        return True
    except BaseException:
        return False


def ws_presets_now():
    """The groups that are on, cleaned of anything this panel does not know."""
    raw = str(hconfig(ConfigEnum.warp_presets) or '')
    picked = [p.strip() for p in raw.split(',') if p.strip()]
    return [p for p in WS_PRESETS if p in picked]


def ws_ask(action, key='', value='', background=False):
    """Hand one node action to the commander. Returns (ok, text)."""
    try:
        out = commander(Command.node, run_in_background=background,
                        action=action, key=key, value=value)
        return True, (out or '').strip()[-4000:]
    except subprocess.CalledProcessError as problem:
        raw = problem.output
        text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw or '')
        return False, text.strip()[-4000:] or _('The node refused this change.')
    except Exception as problem:
        app.logger.error(f'the node action {action} failed: {problem}')
        return False, str(problem)[-400:]


def ws_server_ip():
    """The public address of this machine with no node in the way.

    watashi v12.2.129.3: the node script asks cloudflare's trace endpoint for
    this, and on a server whose own traffic is warped that answer is either the
    node address or nothing at all. The panel already knows its own public
    address - QuickSetup writes it on every domain - so the page asks the panel
    instead. hutils caches the answer for ten minutes, so opening this page in a
    loop does not talk to the network in a loop.
    """
    try:
        from hiddifypanel import hutils
        return str(hutils.network.get_ip_str(4) or '')
    except Exception as problem:
        app.logger.error(f'the server ip could not be read: {problem}')
        return ''


def ws_job_now():
    """The name of the node job running right now, or an empty string.

    watashi v12.2.129.3: every write on this page takes longer than a click
    feels, so an impatient second click - or a second tab, or a refresh in the
    middle - used to start the same work twice. The page guards itself, but the
    page is not the only caller, so the door checks as well. This asks the node
    for its job file only: no network, no systemctl, so it is cheap enough to
    run before every write.
    """
    ok, text = ws_ask('job')
    if not ok:
        # a node that cannot even be asked is not a node that is busy; the
        # write below will fail on its own and say why.
        return ''
    try:
        line = [x for x in text.splitlines() if x.strip().startswith('{')]
        return str((json.loads(line[-1]) if line else {}).get('job', '') or '').strip()
    except Exception as problem:
        app.logger.error(f'the node job file could not be read: {problem}')
        return ''


def ws_state():
    """What the WARP node is doing right now, plus what the panel asked of it.

    Never raises: a server where the engine was never installed still has to
    be able to open this page and read why.
    """
    node = {
        'name': 'warp', 'installed': 'no', 'engine': '', 'state': 'absent',
        'enabled': '', 'warp': '', 'ip': '', 'colo': '', 'loc': '', 'org': '',
        'city': '', 'job': '', 'job_log': '', 'settings': {},
        # watashi v12.2.129.2: carrying says the proxy moved real traffic,
        # server_ip is what this server looks like with no node at all.
        'carrying': '', 'server_ip': '',
    }
    error = ''
    ok, text = ws_ask('show')
    if ok:
        try:
            # the commander prints nothing else, but a stray line from sudo
            # would be enough to break a strict parse, so the object is taken
            # from the last line that looks like one.
            line = [x for x in text.splitlines() if x.strip().startswith('{')]
            node.update(json.loads(line[-1]) if line else {})
        except Exception as problem:
            app.logger.error(f'the node state could not be read: {problem}')
            error = _('The node did not answer in a way this page can read.')
    else:
        error = text or _('The node state could not be read.')

    settings = node.get('settings') or {}
    node['settings'] = {k: str(settings.get(k, '') or '') for k in WS_MODE_KEYS}
    node['panel_mode'] = str(hconfig(ConfigEnum.warp_mode) or 'disable')
    node['on'] = node['panel_mode'] != 'disable'
    node['all'] = node['panel_mode'] == 'all'
    # watashi v12.2.129.2: working used to mean "cloudflare says warp=on". In
    # psiphon mode the traffic leaves through a psiphon server, so cloudflare
    # answers warp=off and a perfectly healthy node was reported as dead. The
    # node tells us whether it is carrying traffic; for the cloudflare modes we
    # still ask for the warp flag, because there it is the whole point.
    carrying = str(node.get('carrying', '')) == 'yes'
    mode = str(node['settings'].get('MODE', '') or 'warp')
    if mode == 'cfon':
        node['working'] = carrying
    else:
        node['working'] = str(node.get('warp', '')) in ('on', 'plus')
    node['plus'] = str(node.get('warp', '')) == 'plus'
    node['presets'] = ws_presets_now()
    node['sites'] = str(hconfig(ConfigEnum.warp_sites) or '')
    node['has_key'] = bool(str(hconfig(ConfigEnum.warp_plus_code) or '').strip())
    node['busy'] = bool(node.get('job'))
    if not str(node.get('server_ip', '') or '').strip():
        node['server_ip'] = ws_server_ip()
    return node, error


def ws_clean_sites(text):
    """The hand written domain box. One domain per line, nothing exotic."""
    lines = [l.strip().lower() for l in str(text or '').replace('\r', '').split('\n')]
    lines = [l for l in lines if l]
    if len(lines) > WS_SITES_MAX:
        return None, _('That is more domains than this box takes.')
    for line in lines:
        if not WS_SITE_RE.match(line):
            return None, _('This does not look like a domain: %(n)s', n=line)
    seen = []
    for line in lines:
        if line not in seen:
            seen.append(line)
    return '\n'.join(seen), ''


class NodesAdmin(FlaskView):
    """Nodes: the exits this server can send traffic through."""

    # the same door the cores page keeps: a super admin, or a custom admin
    # who was given the system capability.
    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        node, error = ws_state()
        return render_template('nodes.html', node=node, node_error=error,
                               nd_presets=WS_PRESETS, nd_countries=WS_COUNTRIES,
                               nd_csrf=ws_form_token())

    def _json(self, payload, code=200):
        return app.response_class(json.dumps(payload), mimetype='application/json', status=code)

    def _with_state(self, ok, log, code=200, applied=False):
        node, error = ws_state()
        return self._json({'ok': ok, 'log': log, 'node': node,
                           'error': error, 'needs_apply': applied}, code)

    @route('state')
    def state(self):
        """The same card, for the page to refresh itself without a reload."""
        node, error = ws_state()
        return self._json({'ok': not error, 'node': node, 'error': error})

    @route('change', methods=['POST'])
    def change(self):
        """Every write this page can do, one door."""
        if not ws_signed():
            return self._json({'ok': False, 'log': _('This form was not sent by this page.')}, 400)
        data = request.get_json(silent=True) or request.form or {}
        action = str(data.get('action', '')).strip()

        # watashi v12.2.129.3: one job at a time. 409 is the honest code here -
        # the request is fine, the node is simply not free - and the page shows
        # the log line of the job that is still running instead of starting a
        # second one on top of it.
        if action in ('on', 'off', 'change-ip', 'routing', 'engine'):
            # the state is deliberately not read here: ws_state talks to the
            # network and a refusal has to come back at once. The page keeps
            # polling anyway, so nothing is lost.
            if ws_job_now():
                return self._json({'ok': False, 'log': _(
                    'This node is still working on the last thing you asked. Wait for it to finish.')}, 409)

        if action in ('on', 'off'):
            # The database decides what the routing templates do, the unit
            # decides whether the tunnel exists. Writing only one of the two
            # is how a panel ends up claiming WARP is on while every rule
            # points somewhere else, so both move together.
            if action == 'on':
                mode = str(hconfig(ConfigEnum.warp_mode) or '')
                set_hconfig(ConfigEnum.warp_mode, mode if mode in ('all',) else 'custom')
            else:
                set_hconfig(ConfigEnum.warp_mode, 'disable')
            ok, log = ws_ask(action, background=True)
            return self._with_state(ok, log, 200 if ok else 400, applied=True)

        if action == 'change-ip':
            ok, log = ws_ask('change-ip', background=True)
            return self._with_state(ok, log, 200 if ok else 400)

        if action == 'routing':
            mode = str(data.get('mode', '')).strip()
            if mode not in ('custom', 'all'):
                return self._json({'ok': False, 'log': _('That is not a routing mode this page knows.')}, 400)
            raw = data.get('presets')
            if isinstance(raw, str):
                raw = [p for p in raw.split(',') if p.strip()]
            picked = [str(p).strip() for p in (raw or [])]
            unknown = [p for p in picked if p not in WS_PRESETS]
            if unknown:
                return self._json({'ok': False, 'log': _('This group does not exist: %(n)s', n=unknown[0])}, 400)
            sites, problem = ws_clean_sites(data.get('sites', ''))
            if problem:
                return self._json({'ok': False, 'log': problem}, 400)
            keep = [p for p in WS_PRESETS if p in picked]
            set_hconfig(ConfigEnum.warp_presets, ','.join(keep))
            set_hconfig(ConfigEnum.warp_sites, sites)
            # a node that is off stays off: the routing mode only picks
            # between "the chosen groups" and "everything".
            if str(hconfig(ConfigEnum.warp_mode) or 'disable') != 'disable':
                set_hconfig(ConfigEnum.warp_mode, mode)
            return self._with_state(True, _('The routing of this node was saved.'), applied=True)

        if action == 'engine':
            changes = data.get('settings') or {}
            if not isinstance(changes, dict):
                return self._json({'ok': False, 'log': _('This form was not sent by this page.')}, 400)
            wanted = {}
            for key in WS_MODE_KEYS:
                if key not in changes:
                    continue
                value = str(changes.get(key, '') or '').strip()
                if key == 'MODE' and value not in WS_MODES:
                    return self._json({'ok': False, 'log': _('That is not a mode the engine has.')}, 400)
                if key == 'IPV' and value not in WS_IPVS:
                    return self._json({'ok': False, 'log': _('That is not an IP version the engine has.')}, 400)
                if key == 'SCAN' and value not in ('0', '1'):
                    return self._json({'ok': False, 'log': _('The endpoint scan is either on or off.')}, 400)
                if key == 'COUNTRY' and value not in WS_COUNTRIES:
                    return self._json({'ok': False, 'log': _('The engine cannot use that country.')}, 400)
                if key == 'DNS' and not WS_DNS_RE.match(value):
                    return self._json({'ok': False, 'log': _('The DNS of a node has to be an IP address.')}, 400)
                if key == 'TEST_URL' and not WS_TEST_URL_RE.match(value):
                    return self._json(
                        {'ok': False,
                         'log': _('The readiness address has to be a plain http address, for example http://1.1.1.1')}, 400)
                wanted[key] = value
            key_code = data.get('plus_code', None)
            if key_code is not None:
                code = str(key_code or '').strip()
                if code and not WS_KEY_RE.match(code):
                    return self._json({'ok': False, 'log': _('That does not look like a WARP+ key.')}, 400)
                set_hconfig(ConfigEnum.warp_plus_code, code)
            log = []
            for key, value in wanted.items():
                ok, text = ws_ask('set', key=key, value=value)
                log.append(text or f'{key}={value}')
                if not ok:
                    return self._with_state(False, '\n'.join(log), 400)
            # engine.args is built by run.sh, so a saved setting only becomes
            # real when the node is brought up again. Doing it here is the
            # difference between a settings window that works and one that
            # quietly lies.
            restarted = False
            if (wanted or key_code is not None) and str(hconfig(ConfigEnum.warp_mode) or 'disable') != 'disable':
                ok, text = ws_ask('on', background=True)
                restarted = ok
                if text:
                    log.append(text)
            if not log:
                log.append(_('Nothing was changed.'))
            if restarted:
                log.append(_('The node is coming up again with the new settings.'))
            return self._with_state(True, '\n'.join(log))

        return self._json({'ok': False, 'log': _('That is not something this page can do.')}, 400)
