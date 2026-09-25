"""watashi v12.2.130by: the config health page.

The engine landed in round bw as a command, which is the right place for the
work and the wrong place for an admin: nobody opens ssh to learn whether a
config answers. This is the same engine behind a page.

The run is a plain thread in this process on purpose. The panel is served by
bjoern in a single process (see app.py), so one background thread is enough
and nothing has to be taught to a queue that does not exist here. The
registry is guarded by a lock, only one run may be in flight, and the last
result is written next to the other logs so a reload does not lose it.
"""
import json
import os
import threading
import time

from flask import current_app, render_template, request
from flask_babel import gettext as _
from flask_classful import FlaskView, route

from hiddifypanel.auth import login_required
from hiddifypanel.hutils import ws_health
from hiddifypanel.models import Role, User

WS_HOME = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager')
WS_STATE_FILE = os.path.join(WS_HOME, 'log', 'system', 'ws_config_health.json')

_lock = threading.Lock()
_run = {
    'running': False,
    'account': '',
    'uuid': '',
    'total': 0,
    'done': 0,
    'now': '',
    'rows': [],
    'notes': [],
    'started': '',
    'finished': '',
}


def ws_form_token():
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


def ws_snapshot():
    with _lock:
        return json.loads(json.dumps(_run))


def ws_remember(state):
    """Keep the last finished run, so a reload still has something to show."""
    try:
        os.makedirs(os.path.dirname(WS_STATE_FILE), exist_ok=True)
        with open(WS_STATE_FILE, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False)
    except OSError:
        pass


def ws_recall():
    try:
        with open(WS_STATE_FILE, encoding='utf-8') as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    state['running'] = False
    return state


def ws_worker(app, user, timeout, only):
    """The whole run, off the request thread."""
    with app.app_context():
        try:
            jobs, notes = ws_health.ws_jobs_for_user(app, user)
            if only in ('xray', 'singbox'):
                jobs = [job for job in jobs if job['engine'] == only]
            with _lock:
                _run['total'] = len(jobs)
                _run['notes'] = notes
            for job in jobs:
                with _lock:
                    _run['now'] = job['name']
                row = ws_health.ws_run_job(job, timeout=timeout)
                with _lock:
                    _run['rows'].append(row)
                    _run['done'] = len(_run['rows'])
        except Exception as problem:
            app.logger.error('the config health run failed: %s' % problem)
            with _lock:
                _run['notes'] = list(_run['notes']) + [str(problem)[-300:]]
        finally:
            with _lock:
                _run['running'] = False
                _run['now'] = ''
                _run['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                state = json.loads(json.dumps(_run))
            ws_remember(state)


class ConfigHealthAdmin(FlaskView):
    """Config Health: every config, driven by the core that can run it."""

    # the same door the cores and the nodes pages keep.
    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        state = ws_snapshot()
        if not state['rows'] and not state['running']:
            state = ws_recall() or state
        accounts = []
        for user in User.query.all():
            accounts.append({'uuid': str(user.uuid), 'name': user.name,
                             'active': bool(user.is_active)})
        accounts.sort(key=lambda one: (not one['active'], one['name'].lower()))
        engines = {}
        for name in ('xray', 'singbox'):
            engines[name] = {'ready': ws_health.ws_engine_ready(name),
                             'path': ws_health.ws_engine_bin(name)}
        return render_template('config_health.html', ch_accounts=accounts,
                               ch_state=state, ch_engines=engines,
                               ch_csrf=ws_form_token())

    def _json(self, payload, code=200):
        return current_app.response_class(json.dumps(payload),
                                          mimetype='application/json', status=code)

    @route('state')
    def state(self):
        """What the run has finished so far."""
        state = ws_snapshot()
        if not state['rows'] and not state['running']:
            state = ws_recall() or state
        return self._json({'ok': True, 'state': state})

    @route('start', methods=['POST'])
    def start(self):
        if not ws_signed():
            return self._json({'ok': False, 'error': _('This page was left open too long. Reload it and try again.')}, 400)
        body = request.get_json(silent=True) or {}
        want = str(body.get('uuid', '') or '').strip()
        only = str(body.get('only', '') or '').strip().lower()
        if only not in ('xray', 'singbox'):
            only = ''
        try:
            timeout = int(body.get('timeout') or ws_health.WS_TIMEOUT)
        except (TypeError, ValueError):
            timeout = ws_health.WS_TIMEOUT
        timeout = max(3, min(30, timeout))

        user = User.by_uuid(want) if want else None
        if not user:
            return self._json({'ok': False, 'error': _('Pick an account first.')}, 400)

        with _lock:
            if _run['running']:
                return self._json({'ok': False, 'error': _('A test is already running. Wait for it to finish.')}, 409)
            _run.update({'running': True, 'account': user.name, 'uuid': str(user.uuid),
                         'total': 0, 'done': 0, 'now': '', 'rows': [], 'notes': [],
                         'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'finished': ''})

        app = current_app._get_current_object()
        thread = threading.Thread(target=ws_worker, args=(app, user, timeout, only),
                                  name='ws-config-health', daemon=True)
        thread.start()
        return self._json({'ok': True, 'state': ws_snapshot()})
