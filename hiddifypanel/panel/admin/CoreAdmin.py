"""Watashi v12.2.51: the core page.

The panel used to have no idea which version of Xray or sing-box it was
running, and the only way to change a core was to edit packages.lock by hand
and run the installer over ssh. This page reads the state from
common/core_manager.sh and asks it, through the commander, to install, upgrade,
downgrade or roll back a core.

Reading is done in this process because it only looks at files. Anything that
writes goes through sudo common/commander.py, which validates its own input
again, so a broken form on this page can never turn into a shell command.
"""
import json
import os
import re
import subprocess

from flask import render_template, request
from flask_classful import FlaskView, route
from flask_babel import gettext as _
from flask import current_app as app

from hiddifypanel.auth import login_required
from hiddifypanel.models import Role
from hiddifypanel.panel.run_commander import commander, Command

WS_MANAGER_DIR = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager')
WS_CORE_MANAGER = os.path.join(WS_MANAGER_DIR, 'common/core_manager.sh')
WS_CORE_REGISTRY = os.path.join(WS_MANAGER_DIR, 'common/core_registry.conf')
WS_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,39}$')
WS_VERSION_RE = re.compile(r'^[0-9][0-9A-Za-z.+_-]{0,39}$')
WS_WRITE_ACTIONS = ('install', 'upgrade', 'downgrade', 'rollback', 'prune')
WS_READ_TIMEOUT = 25


def ws_core_json():
    """What every registered core is doing right now. Never raises."""
    if not os.path.exists(WS_CORE_MANAGER):
        return [], _('The core manager is not installed on this server yet.')
    try:
        out = subprocess.check_output(
            ['bash', WS_CORE_MANAGER, 'json'],
            stderr=subprocess.DEVNULL,
            timeout=WS_READ_TIMEOUT,
        ).decode('utf-8', 'replace')
        rows = json.loads(out)
        if not isinstance(rows, list):
            return [], _('The core manager gave an answer this page cannot read.')
        return rows, ''
    except subprocess.TimeoutExpired:
        return [], _('The core manager did not answer in time.')
    except Exception as problem:
        app.logger.error(f'the core list could not be read: {problem}')
        return [], _('The core list could not be read. Look at log/system/core_manager.log.')


def ws_registry_extras():
    """The bits of the registry the json output does not carry: repository and
    the range of versions this panel was actually tested against."""
    extras = {}
    try:
        with open(WS_CORE_REGISTRY, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('|')
                if len(parts) < 10:
                    continue
                extras[parts[0]] = {
                    'repo': parts[1],
                    'tested_min': parts[8],
                    'tested_max': parts[9],
                    # watashi v12.2.82: the two fields the registry gained. an
                    # older registry has neither, so both have a fallback.
                    'stable_max': parts[10] if len(parts) > 10 else '',
                    'channel': (parts[11] if len(parts) > 11 else '') or 'stable',
                }
    except FileNotFoundError:
        pass
    except Exception as problem:
        app.logger.error(f'the core registry could not be read: {problem}')
    return extras


def ws_ver_key(text):
    """A version turned into something comparable. Digits compare as numbers,
    anything else keeps its place, so 1.13.0.h10 lands after 1.13.0."""
    key = []
    for chunk in re.split(r'[._+-]', str(text or '')):
        if chunk.isdigit():
            key.append((1, int(chunk), ''))
        elif chunk:
            key.append((0, 0, chunk))
    return key


def ws_is_pre(installed, stable):
    """Is what is running past the stable line this panel trusts."""
    if not installed or not stable or installed == stable:
        return False
    try:
        return ws_ver_key(installed) > ws_ver_key(stable)
    except Exception:
        return False


def ws_cores():
    """The table this page draws."""
    rows, error = ws_core_json()
    extras = ws_registry_extras()
    for row in rows:
        extra = extras.get(row.get('name', ''), {})
        row['repo'] = extra.get('repo', '')
        row['tested_min'] = extra.get('tested_min', '')
        row['tested_max'] = extra.get('tested_max', row.get('tested', ''))
        row['off_tested'] = bool(row.get('installed')) and row.get('installed') != row.get('tested')
        # watashi v12.2.82: the stable line and the channel belong to the core,
        # not to the panel. the core manager on disk may still be an older one,
        # so every field it may not send is worked out here as well.
        row['stable'] = row.get('stable') or extra.get('stable_max', '')
        row['channel'] = row.get('channel') or extra.get('channel', 'stable')
        if not isinstance(row.get('pre'), bool):
            row['pre'] = ws_is_pre(row.get('installed', ''), row.get('stable', ''))
        row['present'] = bool(row.get('present')) or bool(row.get('installed'))
    return rows, error


def ws_ask(action, name, version=''):
    """Hand a change to the commander. Returns (ok, text)."""
    if action not in WS_WRITE_ACTIONS:
        return False, _('That is not something this page can do.')
    if not WS_NAME_RE.match(name or ''):
        return False, _('That core name does not look like a core name.')
    if version and not WS_VERSION_RE.match(version):
        return False, _('That version does not look like a version.')
    try:
        out = commander(Command.core, run_in_background=False,
                        action=action, name=name, version=version) or ''
        return True, out.strip()[-4000:]
    except subprocess.CalledProcessError as problem:
        text = (problem.output or b'').decode('utf-8', 'replace') if isinstance(problem.output, bytes) else str(problem.output)
        return False, text.strip()[-4000:] or _('The core manager refused this change.')
    except Exception as problem:
        app.logger.error(f'the core change failed: {problem}')
        return False, str(problem)[-400:]


class CoreAdmin(FlaskView):
    """Cores: what is installed, what was tested, and the buttons to change it."""

    # watashi v12.2.80: the settings page beside it allows a custom admin, and
    # v12.2.68 already gave this page its own permission entry, so a custom
    # admin holding the settings capability saw a menu row that bounced
    # straight back to the login screen.
    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        cores, error = ws_cores()
        counts = {
            'total': len(cores),
            'installed': sum(1 for c in cores if c.get('installed')),
            'missing': sum(1 for c in cores if not c.get('installed')),
            'off_tested': sum(1 for c in cores if c.get('off_tested')),
        }
        return render_template('cores.html', cores=cores, counts=counts, core_error=error)

    def _json(self, payload, code=200):
        return app.response_class(json.dumps(payload), mimetype='application/json', status=code)

    @route('list')
    def list_cores(self):
        """The same table, for the page to refresh itself without a reload."""
        cores, error = ws_cores()
        return self._json({'ok': not error, 'cores': cores, 'error': error})

    @route('latest/<name>')
    def latest(self, name):
        """Ask the vendor what the newest release is. This one touches the
        network, so the page asks for it per core and only when told to."""
        if not WS_NAME_RE.match(name or ''):
            return self._json({'ok': False, 'error': _('That core name does not look like a core name.')}, 400)
        # watashi v12.2.82: two doors. the panel only ever walks through the
        # stable one by itself; the vendor of xray marks nearly every release
        # as a pre-release, so without the second door a test build cannot be
        # reached at all, and with it the reaching is deliberate.
        channel = (request.args.get('channel') or 'stable').strip()
        if channel not in ('stable', 'pre'):
            return self._json({'ok': False, 'error': _('That channel is not one this page knows.')}, 400)
        try:
            out = subprocess.check_output(
                ['bash', WS_CORE_MANAGER, 'latest' if channel == 'stable' else 'latest-pre', name],
                stderr=subprocess.DEVNULL,
                timeout=WS_READ_TIMEOUT,
            ).decode('utf-8', 'replace').strip()
        except Exception as problem:
            app.logger.error(f'the latest version of {name} could not be read: {problem}')
            return self._json({'ok': False, 'error': _('The vendor could not be reached.')})
        if not out or not WS_VERSION_RE.match(out):
            return self._json({'ok': False, 'error': _('The vendor did not name a version.')})
        return self._json({'ok': True, 'name': name, 'latest': out, 'channel': channel})

    @route('change', methods=['POST'])
    def change(self):
        """Install, upgrade, downgrade, roll back or prune one core."""
        data = request.get_json(silent=True) or request.form or {}
        action = str(data.get('action', '')).strip()
        name = str(data.get('name', '')).strip()
        version = str(data.get('version', '')).strip()
        ok, text = ws_ask(action, name, version)
        cores, _error = ws_cores()
        return self._json({'ok': ok, 'log': text, 'cores': cores}, 200 if ok else 400)
