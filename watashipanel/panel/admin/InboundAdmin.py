# watashi v12.3.41dev: the Inbounds page of the advanced mode.
"""Hand built xray inbounds, the way x-ui, Marzban and Pasargad let you build
them: a port, a protocol, a transport and a security layer, and every user of
the panel is a client of every inbound that serves.

Nothing on this page reaches the server on its own. A row is checked here
(hutils.proxy.custom.ws_clean), then tried with the real xray binary next to
every other xray config of this server (commander custom-inbounds test), and
only then kept. Keeping it starts an apply of these inbounds alone
(xray/custom_apply.sh), which restarts xray once, about a second, the way x-ui
and Marzban do it too; the safety net in xray/custom_guard.sh takes out again
whatever xray would not run, so the panel's own inbounds always start.

The page is a door of the settings capability, like the cores and the nodes.

watashi v12.3.42dev: the protocols only sing-box speaks (Hysteria2, TUIC,
AnyTLS, Naive, ShadowTLS, Shadowsocks 2022, Snell) are built here as well. Such
a row is tried with the real sing-box binary (commander custom-inbounds
test-singbox), singbox/custom_guard.sh is its safety net, and the apply
restarts only the core whose rows changed. Each core keeps its own status; the
page shows both as one.
"""
import json
import re
import subprocess

from flask import render_template, request
from flask import current_app as app
from flask_babel import gettext as _
from flask_classful import FlaskView, route
from loguru import logger

from watashipanel.auth import login_required
from watashipanel.database import db
from watashipanel.models import ConfigEnum, Role, hconfig, set_hconfig
from watashipanel.models.custom_inbound import CustomInbound
from watashipanel.hutils.proxy import custom as wc
from watashipanel.panel.run_commander import ws_custom_inbounds
from watashipanel.panel.admin.NodesAdmin import ws_form_token, ws_signed

WS_SAMPLE_UUID = '00000000-0000-4000-8000-000000000000'
WS_JOB_UNIT = 'watashi-job-custom.service'
WS_JOB_LOG = '/opt/watashi-manager/log/system/custom-inbounds.log'
WS_MAX_ROWS = 50
WS_NOISE = re.compile(r'^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d(\.\d+)? ')
# watashi v12.3.42dev: the colours and the level sing-box puts in front of a line
WS_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
WS_SB_LEVEL = re.compile(r'^(FATAL|ERROR|WARN|INFO|DEBUG|TRACE)\[\d+\]\s*')


def ws_job_running() -> bool:
    try:
        return subprocess.run(['systemctl', 'is-active', '--quiet', WS_JOB_UNIT],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def ws_job_log() -> str:
    try:
        with open(WS_JOB_LOG, errors='replace') as handle:
            return ''.join(handle.readlines()[-40:])
    except OSError:
        return ''


def ws_xray_says(output: str) -> str:
    """The lines of an xray test that explain a refusal, without the noise."""
    lines = []
    for line in str(output or '').splitlines():
        line = WS_NOISE.sub('', line.strip())
        if not line or 'deprecated' in line.lower() or line.startswith('Xray ') or line.startswith('A unified platform'):
            continue
        lines.append(line)
    # the commander refusing the candidate: its own sentence, not the traceback
    for line in reversed(lines):
        if line.startswith('AssertionError: '):
            return line[len('AssertionError: '):].removeprefix('Error: ')[:700]
    # xray: the reason is after the list of files it read
    for line in reversed(lines):
        if line.startswith('Failed to start') or 'failed to load config' in line:
            reason = line.rsplit('] > ', 1)[-1] if '] > ' in line else line
            return reason.replace('infra/conf: ', '').strip()[:700]
    text = ' '.join(lines[-3:])
    return text[:700]


def ws_singbox_says(output: str) -> str:
    """watashi v12.3.42dev: the line of a sing-box check that explains a refusal."""
    lines = [WS_ANSI.sub('', line).strip() for line in str(output or '').splitlines()]
    lines = [line for line in lines if line]
    for line in reversed(lines):
        if line.startswith('AssertionError: '):
            return line[len('AssertionError: '):].removeprefix('Error: ')[:700]
    for line in reversed(lines):
        level = WS_SB_LEVEL.match(line)
        if level and level.group(1) in ('FATAL', 'ERROR'):
            text = line[level.end():]
            # the file is the commander's temporary copy, the tag says more
            text = re.sub(r'^decode config at [^:]*: ', '', text)
            return text.strip()[:700]
    return ' '.join(lines[-3:])[:700]


def ws_refusal(clean: dict, output: str) -> str:
    """watashi v12.3.42dev: the refusal in the words of the core that refused."""
    if wc.ws_core_of(clean) == 'singbox':
        return _('sing-box does not accept this inbound:') + ' ' + ws_singbox_says(output)
    return _('xray does not accept this inbound:') + ' ' + ws_xray_says(output)


def ws_traffic() -> dict:
    """tag -> {'up', 'down'} in bytes since the core last started, from its own counters."""
    out = {}
    try:
        from watashipanel.drivers.xray_api import XrayApi
        client = XrayApi().get_xray_client()
        for stat in client.stats_query('inbound>>>custom-', reset=False) or []:
            parts = str(stat.name).split('>>>')
            if len(parts) != 4:
                continue
            one = out.setdefault(parts[1], {'up': 0, 'down': 0})
            one['up' if parts[3] == 'uplink' else 'down'] += int(stat.value or 0)
    except Exception as problem:
        logger.debug(f'watashi: the inbound counters could not be read ({problem})')
    # watashi v12.3.42dev: and sing-box's own counters of the sing-box rows,
    # which singbox/configs/01_api.json.j2 asks for by tag. A ShadowTLS row
    # routes its traffic from the inner inbound, custom-N-in, which counts
    # here as custom-N.
    try:
        from watashipanel.drivers.singbox_api import SingboxApi, ws_sb_query
        client = SingboxApi().get_singbox_client()
        for stat in ws_sb_query(client, 'inbound>>>custom-', reset=False) or []:
            parts = str(stat.name).split('>>>')
            if len(parts) != 4:
                continue
            tag = parts[1][:-3] if parts[1].endswith('-in') else parts[1]
            one = out.setdefault(tag, {'up': 0, 'down': 0})
            one['up' if parts[3] == 'uplink' else 'down'] += int(stat.value or 0)
    except Exception as problem:
        logger.debug(f'watashi: the sing-box inbound counters could not be read ({problem})')
    return out


def ws_sample_link(row: CustomInbound) -> str:
    try:
        from watashipanel.hutils.proxy import xray as xray_links
        proxy = wc.ws_proxy_row(row, WS_SAMPLE_UUID)
        if not proxy:
            return ''
        link = xray_links.to_link(proxy)
        return link if isinstance(link, str) else ''
    except Exception as problem:
        logger.debug(f'watashi: no sample link for {row.tag} ({problem})')
        return ''


def ws_state() -> dict:
    """Everything the page shows, in one answer the page can poll."""
    rows = CustomInbound.all_rows()
    # watashi v12.3.42dev: each core has its own rev and its own status file;
    # a row is applied when the core that serves it runs exactly this set
    status = wc.ws_status('xray')
    status_sb = wc.ws_status('singbox')
    base = wc.ws_export_base(rows, quiet=True)  # watashi v12.3.41dev: a look at the page does not write the log
    rev = wc.ws_rev(base, 'xray')
    rev_sb = wc.ws_rev(base, 'singbox')
    marked = wc.ws_mark_rejected(base, rev, status, 'xray')
    marked = wc.ws_mark_rejected(marked, rev_sb, status_sb, 'singbox')
    exported = {r['id']: r for r in marked}
    running = ws_job_running()
    applied_by = {'xray': (status.get('rev') or '') == rev, 'singbox': (status_sb.get('rev') or '') == rev_sb}
    applied = applied_by['xray'] and applied_by['singbox']
    live = wc.ws_live_ports()
    traffic = ws_traffic()
    mode_on = wc.ws_mode_on()
    views = []
    for row in rows:
        data = row.to_dict()
        e = exported.get(row.id) or {}
        if not row.enable:
            state = 'off'
        elif not mode_on:
            state = 'paused'
        elif e.get('rejected'):
            state = 'rejected'
        elif e.get('problem'):
            state = 'held'
        elif not applied_by.get(row.core, applied):
            state = 'pending'
        # watashi v12.3.42dev: Hysteria2 and TUIC listen on udp only
        elif int(row.port) in live.get('udp' if row.protocol in wc.SB_UDP_PROTOCOLS else 'tcp', set()):
            state = 'serving'
        else:
            state = 'down'
        data['tag'] = row.tag
        data['state'] = state
        data['problem'] = e.get('problem', '')
        data['traffic'] = traffic.get(row.tag, {'up': 0, 'down': 0})
        data['link'] = ws_sample_link(row) if row.enable else ''
        views.append(data)
    merged = ws_merged_status(status, status_sb, views)
    return {
        'rows': views,
        'rev': rev + ('/' + rev_sb if rev_sb else ''),
        'applied': applied,
        'running': running,
        'status': merged,
        'log': ws_job_log() if running or not applied or merged.get('state') in ('partial', 'rejected') else '',
        'mode': {'advanced': bool(hconfig(ConfigEnum.advanced_mode)),
                 'keep': bool(hconfig(ConfigEnum.custom_inbounds_keep)),
                 'on': mode_on},
    }


def ws_merged_status(status: dict, status_sb: dict, views: list[dict]) -> dict:
    """watashi v12.3.42dev: the two status files as the one the page shows:
    every inbound either core left out, and rejected only when nothing that
    was built by hand serves any more."""
    rejected = []
    for one in (status.get('rejected') or []) + (status_sb.get('rejected') or []):
        if isinstance(one, dict) and one.get('tag'):
            rejected.append({'tag': str(one['tag']), 'reason': str(one.get('reason') or '')})
    if not rejected:
        state = 'ok'
    elif any(v.get('state') in ('serving', 'down', 'pending') for v in views):
        state = 'partial'
    else:
        state = 'rejected'
    return {'state': state, 'rejected': rejected, 'rejected_tags': [one['tag'] for one in rejected],
            'xray': status, 'singbox': status_sb}


def ws_options() -> dict:
    """The choices of the editor, the same lists ws_clean checks against."""
    try:
        warp_on = str(hconfig(ConfigEnum.warp_mode) or 'disable') != 'disable'
    except Exception:
        warp_on = False
    return {
        'protocols': list(wc.PROTOCOLS),
        # watashi v12.3.42dev: the protocols sing-box serves and their choices
        'sb_protocols': list(wc.SINGBOX_PROTOCOLS),
        'ss2022_methods': list(wc.SS2022_METHODS.keys()),
        'tuic_ccs': list(wc.TUIC_CCS),
        'networks': list(wc.NETWORKS),
        'securities': list(wc.SECURITIES),
        'xhttp_modes': list(wc.XHTTP_MODES),
        'ss_methods': list(wc.SS_METHODS.keys()),
        'fingerprints': list(wc.FINGERPRINTS),
        'alpns': list(wc.ALPNS),
        'outbounds': list(wc.OUTBOUNDS),
        'tls_domains': wc.ws_tls_domains(),
        'address': wc.ws_default_address(),
        'warp_on': warp_on,
        'max_rows': WS_MAX_ROWS,
    }


def ws_try(clean: dict, row_id: int | None) -> tuple[bool, str]:
    """The candidate with the rows that serve now, tried by the real core that
    serves it: xray for an xray row, sing-box for a sing-box row."""
    candidate = dict(clean)
    candidate['id'] = row_id or 0
    # watashi v12.3.42dev: only the rows of the same core, and only the ones the
    # server really runs. A row held back or taken out at the last apply (its
    # domain is gone, its port is taken) is not on the server, and a sing-box
    # check reads every certificate, so such a row would fail every new one.
    core = wc.ws_core_of(candidate)
    serving = {r['id'] for r in wc.ws_export_rows(quiet=True) if r['active']}
    rows = [candidate]
    for other in CustomInbound.all_rows():
        if other.id == row_id or other.id not in serving or other.core != core:
            continue
        rows.append(other.to_dict())
    if core == 'singbox':
        return ws_custom_inbounds('test-singbox', wc.ws_test_file_singbox(rows), timeout=60)
    ok, output = ws_custom_inbounds('test', wc.ws_test_file(rows), timeout=60)
    return ok, output


def ws_fill(row: CustomInbound, clean: dict):
    row.child_id = 0
    row.enable = bool(clean['enable'])
    row.remark = clean['remark']
    row.protocol = clean['protocol']
    row.port = int(clean['port'])
    row.listen = clean['listen']
    row.network = clean['network']
    row.security = clean['security']
    row.opts = clean['settings']


def ws_apply(force: bool = False, retry: bool = False) -> str:
    """Start an apply of these inbounds when the server runs something else
    than what the panel holds now. started, queued, busy, error or none.
    retry also gives the inbounds the last apply took out another chance."""
    try:
        from watashipanel.cache import cache
        cache.invalidate_all_cached_functions()
    except Exception:
        pass
    if not force and not retry:
        base = wc.ws_export_base(quiet=True)  # watashi v12.3.41dev: the apply itself says what it holds back
        # watashi v12.3.42dev: nothing to do only when both cores run what the panel holds
        if (wc.ws_status('xray').get('rev') or '') == wc.ws_rev(base, 'xray') and \
                (wc.ws_status('singbox').get('rev') or '') == wc.ws_rev(base, 'singbox'):
            return 'none'
    ok, output = ws_custom_inbounds('retry' if retry else 'apply', timeout=30)
    if ok and 'once more' in output:
        return 'queued'
    if ok:
        return 'started'
    if 'install, apply or update is running' in output:
        return 'busy'
    logger.error(f'watashi: the inbounds could not be applied ({output})')
    return 'error'


class InboundAdmin(FlaskView):
    """Inbounds: the xray and sing-box inbounds built by hand in the advanced mode."""  # watashi v12.3.42dev

    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        return render_template('inbounds.html', ib_state=ws_state(), ib_options=ws_options(),
                               ib_csrf=ws_form_token(), ib_sample=WS_SAMPLE_UUID)

    def _json(self, payload, code=200):
        return app.response_class(json.dumps(payload, default=str), mimetype='application/json', status=code)

    def _refuse(self, errors, code=400, **more):
        payload = {'ok': False, 'errors': errors if isinstance(errors, list) else [str(errors)]}
        payload.update(more)
        return self._json(payload, code)

    def _body(self):
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}

    @route('state')
    def state(self):
        return self._json({'ok': True, 'state': ws_state()})

    @route('keys')
    def keys(self):
        """A fresh REALITY key pair and short id."""
        try:
            return self._json({'ok': True, **wc.ws_new_keys()})
        except Exception as problem:
            return self._refuse(str(problem), 500)

    @route('port')
    def port(self):
        """A free port: not the panel's, not another inbound's, not in use."""
        try:
            row_id = int(request.args.get('id') or 0) or None
        except ValueError:
            row_id = None
        found = wc.ws_random_port(row_id)
        if not found:
            return self._refuse(_('No free port was found, please type one.'), 409)
        return self._json({'ok': True, 'port': found})

    @route('check', methods=['POST'])
    def check(self):
        """The editor's "Test" button: everything a save does except keeping it."""
        if not ws_signed():
            return self._refuse(_('This form was not sent by this page.'))
        body = self._body()
        row_id = None
        if body.get('id'):
            try:
                row_id = int(body['id'])
            except (TypeError, ValueError):
                return self._refuse(_('This inbound does not exist any more.'), 404)
        clean, errors = wc.ws_clean(body, row_id, check_live=True)
        if errors:
            return self._refuse(errors)
        ok, output = ws_try(clean, row_id)
        if not ok:
            return self._refuse([ws_refusal(clean, output)], output=output[-3000:])  # watashi v12.3.42dev
        if wc.ws_core_of(clean) == 'singbox':
            # watashi v12.3.42dev: what sing-box gets, and the keys the panel made
            # for the empty fields, so the editor shows them before the save
            users, users_in = wc.ws_sb_clients_of(clean, WS_SAMPLE_UUID)
            preview = wc.build_singbox_inbound(dict(clean, id=row_id or 0), clients=users, clients_in=users_in)
            made = {k: clean['settings'][k] for k in ('ss2022_key', 'snell_psk') if clean['settings'].get(k)}
            return self._json({'ok': True, 'inbound': preview, 'public_key': '', 'made': made})
        preview = wc.build_xray_inbound(dict(clean, id=row_id or 0), clients=[wc.ws_client_of(clean, WS_SAMPLE_UUID)])
        return self._json({'ok': True, 'inbound': preview,
                           'public_key': clean['settings'].get('reality_public_key', '')})

    @route('save', methods=['POST'])
    def save(self):
        if not ws_signed():
            return self._refuse(_('This form was not sent by this page.'))
        body = self._body()
        row = None
        if body.get('id'):
            try:
                row = CustomInbound.query.get(int(body['id']))
            except (TypeError, ValueError):
                row = None
            if row is None:
                return self._refuse(_('This inbound does not exist any more.'), 404)
        elif len(CustomInbound.all_rows()) >= WS_MAX_ROWS:
            return self._refuse(_('There can be at most %(n)s hand built inbounds.', n=WS_MAX_ROWS))
        clean, errors = wc.ws_clean(body, row.id if row else None, check_live=True)
        if errors:
            return self._refuse(errors)
        ok, output = ws_try(clean, row.id if row else None)
        if not ok:
            return self._refuse([ws_refusal(clean, output)], output=output[-3000:])  # watashi v12.3.42dev
        if row is None:
            row = CustomInbound()
            db.session.add(row)
        ws_fill(row, clean)
        db.session.commit()
        applying = ws_apply()
        return self._json({'ok': True, 'id': row.id, 'applying': applying, 'state': ws_state()})

    @route('toggle', methods=['POST'])
    def toggle(self):
        if not ws_signed():
            return self._refuse(_('This form was not sent by this page.'))
        body = self._body()
        try:
            row = CustomInbound.query.get(int(body.get('id') or 0))
        except (TypeError, ValueError):
            row = None
        if row is None:
            return self._refuse(_('This inbound does not exist any more.'), 404)
        enable = bool(body.get('enable'))
        if enable and not row.enable:
            data = row.to_dict()
            data['enable'] = True
            clean, errors = wc.ws_clean(data, row.id, check_live=True)
            if errors:
                return self._refuse(errors)
            ok, output = ws_try(clean, row.id)
            if not ok:
                return self._refuse([ws_refusal(clean, output)], output=output[-3000:])  # watashi v12.3.42dev
        row.enable = enable
        db.session.commit()
        return self._json({'ok': True, 'applying': ws_apply(), 'state': ws_state()})

    @route('delete', methods=['POST'])
    def delete(self):
        if not ws_signed():
            return self._refuse(_('This form was not sent by this page.'))
        body = self._body()
        try:
            row = CustomInbound.query.get(int(body.get('id') or 0))
        except (TypeError, ValueError):
            row = None
        if row is None:
            return self._refuse(_('This inbound does not exist any more.'), 404)
        db.session.delete(row)
        db.session.commit()
        return self._json({'ok': True, 'applying': ws_apply(), 'state': ws_state()})

    @route('apply', methods=['POST'])
    def apply(self):
        if not ws_signed():
            return self._refuse(_('This form was not sent by this page.'))
        # "Try again" sends retry: the inbounds the last apply took out are judged once more
        retry = bool(self._body().get('retry'))
        return self._json({'ok': True, 'applying': ws_apply(force=True, retry=retry), 'state': ws_state()})

    @route('mode', methods=['POST'])
    def mode(self):
        """Simple or advanced. Leaving the advanced mode either keeps the hand
        built inbounds serving or pauses them, as the owner picks."""
        if not ws_signed():
            return self._refuse(_('This form was not sent by this page.'))
        body = self._body()
        want = str(body.get('mode') or '')
        if want == 'advanced':
            set_hconfig(ConfigEnum.advanced_mode, True)
        elif want == 'simple':
            set_hconfig(ConfigEnum.custom_inbounds_keep, bool(body.get('keep', True)), commit=False)
            set_hconfig(ConfigEnum.advanced_mode, False)
        else:
            return self._refuse(_('Pick the simple or the advanced mode.'))
        applying = ws_apply() if CustomInbound.all_rows() else 'none'
        from watashipanel import hutils
        target = hutils.flask.hurl_for('admin.InboundAdmin:index') if want == 'advanced' else ''
        return self._json({'ok': True, 'advanced': want == 'advanced', 'applying': applying, 'go': target})
