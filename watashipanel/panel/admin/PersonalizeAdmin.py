"""watashi v12.3.43dev: the Personalization page.

Every admin picks the look of the panel for themself here: light or dark,
the mouse pointer, the scrollbars and how much moves on screen. The choice is
kept on the admin's own row, so every browser this admin signs in with opens
the same way, and nobody else's panel changes.

The page writes one thing only, the admin's own look, so it asks for the same
right as the account page, which every kind of admin has.
"""
import json

from flask import g, render_template, request
from flask_babel import gettext as _
from flask_classful import FlaskView, route
from loguru import logger

from watashipanel.auth import login_required
from watashipanel.database import db
from watashipanel.models import Role
from watashipanel.panel.common import WS_UI_CHOICES, ws_ui_clean, ws_ui_prefs


def ws_signed():
    """The page's own form token, sent in the header or in the body."""
    sent = (request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token') or '')
    if not sent:
        body = request.get_json(silent=True) or {}
        sent = str(body.get('csrf_token', '') or '') if isinstance(body, dict) else ''
    if not sent:
        return False
    try:
        from flask_wtf.csrf import validate_csrf
        validate_csrf(sent)
        return True
    except Exception:
        return False


class PersonalizeAdmin(FlaskView):
    decorators = [login_required({Role.super_admin, Role.admin, Role.agent, Role.custom})]

    @route('/')
    def index(self):
        return render_template('personalize.html', active_page='personalize', ws_ui=ws_ui_prefs())

    @route('save', methods=['POST'])
    def save(self):
        if not ws_signed():
            return {'ok': False, 'msg': _('This page went stale, please reload it and try again.')}, 400
        body = request.get_json(silent=True)
        wanted = body.get('prefs') if isinstance(body, dict) else None
        if not isinstance(wanted, dict):
            return {'ok': False, 'msg': _('Nothing to save.')}, 400
        account = getattr(g, 'account', None)
        if account is None or not hasattr(account, 'ui_prefs'):
            return {'ok': False, 'msg': _('Nothing to save.')}, 400
        now = ws_ui_prefs(account)
        for key, value in wanted.items():
            allowed = WS_UI_CHOICES.get(str(key))
            if allowed is None or str(value) not in allowed:
                return {'ok': False, 'msg': _('This choice is not available.')}, 400
            now[str(key)] = str(value)
        kept = {key: value for key, value in ws_ui_clean(now).items() if value}
        try:
            account.ui_prefs = json.dumps(kept, sort_keys=True)
            db.session.commit()
        except Exception as err:
            db.session.rollback()
            logger.error(f"watashi: the look of an admin could not be saved: {err}")
            return {'ok': False, 'msg': _('That did not work.')}, 500
        return {'ok': True, 'prefs': ws_ui_clean(kept)}
