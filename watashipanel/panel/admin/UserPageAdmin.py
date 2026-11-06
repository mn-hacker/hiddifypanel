"""watashi v12.3.44dev: the designer of the user page.

Every admin dresses the page their own customers open from their link: the
name and the logo, the support and bot links, the words, the colours, light or
dark, the language and the parts that are shown. What an admin leaves empty
comes from the admin above them, up to the owner (see ws_page_design).

The page only writes the signed in admin's own design, so it asks for the same
right as the account page, which every kind of admin has.
"""
from flask import g, render_template, request
from flask_babel import gettext as _
from flask_classful import FlaskView, route
from loguru import logger

from watashipanel.auth import login_required
from watashipanel.database import db
from watashipanel.models import Role
from watashipanel.panel import ws_page_design
from watashipanel.panel.admin.PersonalizeAdmin import ws_signed


def ws_sample_link(admin):
    """The page of one customer of this admin, to see the real thing."""
    try:
        from watashipanel.models import User
        from watashipanel.panel import watashi
        user = User.query.filter(User.added_by == admin.id).order_by(User.id).first()
        if user is None and ws_page_design.is_owner(admin):
            user = User.query.order_by(User.id).first()
        if user is None:
            return ''
        return watashi.get_account_panel_link(user, request.host)
    except Exception as err:
        logger.warning(f"watashi: no sample user page for the designer: {err}")
        return ''


def ws_parent_name(admin):
    try:
        rows = ws_page_design.chain(admin)
        return str(getattr(rows[1], 'name', '') or '') if len(rows) > 1 else ''
    except Exception:
        return ''


class UserPageAdmin(FlaskView):
    decorators = [login_required({Role.super_admin, Role.admin, Role.agent, Role.custom})]

    @route('/')
    def index(self):
        admin = g.account
        mine = ws_page_design.own(admin)
        above, origin = ws_page_design.inherited(admin)
        return render_template('userpage.html', active_page='userpage',
                               up_mine=mine, up_above=above, up_origin=origin,
                               up_owner=ws_page_design.is_owner(admin),
                               up_parent=ws_parent_name(admin),
                               up_sample=ws_sample_link(admin),
                               up_rooms={**ws_page_design.TEXTS, **ws_page_design.LINKS,
                                         'note': ws_page_design.NOTE_ROOM},
                               up_logo_room=ws_page_design.LOGO_ROOM,
                               up_sections=ws_page_design.SECTIONS)

    @route('save', methods=['POST'])
    def save(self):
        if not ws_signed():
            return {'ok': False, 'msg': _('This page went stale, please reload it and try again.')}, 400
        body = request.get_json(silent=True)
        wanted = body.get('design') if isinstance(body, dict) else None
        if not isinstance(wanted, dict):
            return {'ok': False, 'msg': _('Nothing to save.')}, 400
        bad = ws_page_design.problems(wanted)
        if bad:
            return {'ok': False, 'bad': bad,
                    'msg': _('A link or the logo could not be used. The marked fields need another look.')}, 400
        admin = getattr(g, 'account', None)
        if admin is None or not hasattr(admin, 'page_design'):
            return {'ok': False, 'msg': _('Nothing to save.')}, 400
        try:
            ws_page_design.save(admin, wanted)
            db.session.commit()
        except Exception as err:
            db.session.rollback()
            logger.error(f"watashi: the user page design could not be saved: {err}")
            return {'ok': False, 'msg': _('That did not work.')}, 500
        return {'ok': True, 'design': ws_page_design.own(admin)}
