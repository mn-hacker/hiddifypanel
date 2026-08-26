from flask import render_template, request, g, redirect, jsonify
from hiddifypanel.hutils.flask import hurl_for
from flask_classful import FlaskView, route
from flask_babel import lazy_gettext as _
from flask_babel import gettext as __
from apiflask import abort
import datetime
import uuid as uuid_mod
import re

from hiddifypanel.auth import login_required, current_account
from hiddifypanel.database import db
from hiddifypanel.models import *
from hiddifypanel.panel import hiddify
from hiddifypanel.panel.common import ws_avatar_url
from hiddifypanel import hutils

WS_ONE_GIG = 1024 * 1024 * 1024
WS_ONLINE_WINDOW = 120  # seconds, the same window the other pages use


def ws_clean_username(raw):
    """Keeps a sign in name the panel can really use.

    Returns the trimmed name, or None when the shape is wrong. Latin letters,
    numbers and the three quiet marks are allowed, because this name will later
    be typed into the sign in box together with the password.
    """
    name = (raw or '').strip()
    if not name:
        return ''
    if not re.match(r'^[A-Za-z0-9._-]{3,100}$', name):
        return None
    return name

def ws_mode_labels():
    return {
        'super_admin': _('Owner'),
        'admin': _('Admin'),
        'agent': _('Agent'),
        'custom': _('Custom'),
    }


def ws_lang_labels():
    return {
        'en': _('English'),
        'fa': _('Persian'),
        'ru': _('Russian'),
        'zh': _('Chinese'),
    }


def ws_avatar_index(model):
    """A steady colour for this account, taken from its own identifier."""
    seed = (getattr(model, 'uuid', '') or getattr(model, 'name', '') or '')
    total = 0
    for ch in str(seed):
        total = (total + ord(ch)) % 4096
    return total % 12


def ws_initial(name):
    text = (name or '').strip()
    return (text[0].upper() if text else '?')


def ws_gb(value):
    return round((value or 0) / WS_ONE_GIG, 2)


def ws_account_links(model):
    """Every domain this account may sign in through."""
    out = []
    try:
        host = request.host
    except BaseException:
        host = ''
    seen = set()
    label = (model.name or '').strip()

    def add(domain, kind):
        domain = (domain or '').strip()
        if not domain or '*' in domain or domain in seen:
            return
        seen.add(domain)
        try:
            link = hiddify.get_account_panel_link(model, domain) + '#' + hutils.encode.url_encode(label)
        except BaseException:
            return
        out.append({'domain': domain, 'link': link, 'kind': kind, 'current': domain == host})

    add(host, 'direct')
    try:
        for d in Domain.query.all():
            mode = (getattr(getattr(d, 'mode', None), 'name', '') or '').lower()
            if any(bad in mode for bad in ('fake', 'reality', 'relay', 'old')):
                continue
            add(getattr(d, 'domain', ''), 'cdn' if 'cdn' in mode else 'direct')
    except BaseException:
        pass
    return out


def ws_catalog():
    """The same rights catalogue the admins page uses, borrowed as is."""
    try:
        from hiddifypanel.panel.admin.AdminstratorAdmin import ws_perm_catalog
        return ws_perm_catalog()
    except BaseException:
        return []


def ws_account_view(model):
    """Everything the my account page shows, gathered in one plain dictionary."""
    labels = ws_mode_labels()
    mode_key = getattr(getattr(model, 'mode', None), 'name', '') or 'agent'
    used = 0
    users_total = 0
    users_online = 0
    users_active = 0
    users_disabled = 0
    last_activity = ''
    try:
        used = int(model.recursive_usage())
    except BaseException:
        used = 0
    try:
        q = model.recursive_users_query()
        users_total = int(q.count())
        users_disabled = int(q.filter(User.enable == False).count())  # noqa: E712
        users_active = max(0, users_total - users_disabled)
        edge = datetime.datetime.now() - datetime.timedelta(seconds=WS_ONLINE_WINDOW)
        users_online = int(q.filter(User.last_online > edge).count())
        from sqlalchemy import func
        newest = db.session.query(func.max(User.last_online)).filter(
            User.added_by.in_(model.recursive_sub_admins_ids())).scalar()
        if newest is not None and getattr(newest, 'year', 0) > 1900:
            last_activity = newest.strftime('%Y-%m-%d %H:%M:%S')
    except BaseException:
        pass

    limit = int(getattr(model, 'data_limit', 0) or 0)
    unlimited = limit <= 0
    pct = 0 if unlimited else min(100, round(used * 100.0 / limit, 1))
    max_users = int(getattr(model, 'max_users', 0) or 0)
    users_unlimited = max_users <= 0
    users_pct = 0 if users_unlimited else min(100, round(users_total * 100.0 / max_users, 1))

    created = ''
    try:
        stamp = getattr(model, 'created_at', None)
        if stamp is not None and getattr(stamp, 'year', 0) > 1900:
            created = stamp.strftime('%Y-%m-%d')
    except BaseException:
        pass

    lang_key = getattr(getattr(model, 'lang', None), 'name', '') or ''
    if not lang_key:
        try:
            lang_key = str(hconfig(ConfigEnum.admin_lang) or 'en')
        except BaseException:
            lang_key = 'en'

    perms = []
    try:
        if mode_key == 'custom':
            perms = list(model.ws_perm_list())
    except BaseException:
        perms = []

    parent = ''
    try:
        if model.parent_admin and model.parent_admin.id != model.id:
            parent = model.parent_admin.name or ''
    except BaseException:
        parent = ''

    return {
        'id': getattr(model, 'id', 0),
        'name': model.name or '',
        'username': getattr(model, 'username', '') or '',
        'uuid': getattr(model, 'uuid', '') or '',
        'telegram_id': getattr(model, 'telegram_id', None) or '',
        'comment': getattr(model, 'comment', '') or '',
        'mode': mode_key,
        'mode_label': labels.get(mode_key, mode_key),
        'lang': lang_key,
        'avatar': ws_avatar_index(model),
        'initial': ws_initial(model.name),
        'created': created,
        'parent': parent,
        'used': used,
        'used_gb': ws_gb(used),
        'limit_gb': ws_gb(limit),
        'data_unlimited': unlimited,
        'data_pct': pct,
        'data_left_gb': 0 if unlimited else max(0, ws_gb(limit - used)),
        'users': users_total,
        'users_active': users_active,
        'users_disabled': users_disabled,
        'users_online': users_online,
        'max_users': max_users,
        'users_unlimited': users_unlimited,
        'users_pct': users_pct,
        'sub_admins': len(getattr(model, 'sub_admins', []) or []),
        'last_activity': last_activity,
        'can_add_admin': bool(getattr(model, 'can_add_admin', False)) or str(getattr(model, 'mode', '')).endswith('super_admin'),
        'perms': perms,
    }


WS_PHOTO_EXTS = ('png', 'jpg', 'jpeg', 'webp')
WS_PHOTO_MAX = 3 * 1024 * 1024


def ws_photo_dir():
    """One shared place, chosen because the panel may really write there."""
    from hiddifypanel.panel.common import ws_photo_root
    return ws_photo_root()


def ws_photo_name(account):
    import os
    uuid = str(getattr(account, 'uuid', '') or '')
    if not uuid:
        return ''
    folder = ws_photo_dir()
    for ext in WS_PHOTO_EXTS:
        if os.path.exists(os.path.join(folder, uuid + '.' + ext)):
            return 'uploads/avatars/' + uuid + '.' + ext
    return ''


# --- Watashi v12.2.36b: the signature of the panel ----------------------------
# The account page can hand out a new sign in name and a new password, so
# every write of it must prove it truly came from our own page, the very
# habit the backup and the domain pages already keep.
def ws_form_token():
    try:
        from flask_wtf.csrf import generate_csrf
        return generate_csrf()
    except BaseException:
        return ''


def ws_signed():
    sent = request.form.get('csrf_token') or request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token') or ''
    if not sent:
        return False
    try:
        from flask_wtf.csrf import validate_csrf
        validate_csrf(sent)
        return True
    except BaseException:
        return False


class AccountAdmin(FlaskView):

    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def index(self):
        model = current_account
        return render_template(
            'account.html',
            ws_account=ws_account_view(model),
            ws_links=ws_account_links(model),
            ws_lang_labels=ws_lang_labels(),
            ws_mode_labels=ws_mode_labels(),
            ws_perm_catalog=ws_catalog(),
            ws_csrf=ws_form_token(),
        )

    @route('/save_profile', methods=['POST'])
    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def save_profile(self):
        """Name, telegram identifier, note and language of the signed in account."""
        if not ws_signed():
            return jsonify({'ok': False, 'msg': __('This page went stale, please reload it and try again.')}), 400
        model = current_account
        try:
            name = (request.form.get('name') or '').strip()
            if not name:
                return jsonify({'ok': False, 'msg': __('The name cannot be empty.')}), 400
            if len(name) > 500:
                name = name[:500]
            model.name = name

            # the sign in name: free to change, but it has to stay unique
            if 'username' in request.form:
                wanted = ws_clean_username(request.form.get('username'))
                if wanted is None:
                    return jsonify({'ok': False, 'msg': __('The sign in name may hold latin letters, numbers, dot, dash and underline only, at least three of them.')}), 400
                if not wanted:
                    return jsonify({'ok': False, 'msg': __('A sign in name is needed, it is one of the two keys of the panel.')}), 400
                if wanted != (model.username or ''):
                    if wanted:
                        taken = AdminUser.query.filter(AdminUser.username == wanted,
                                                      AdminUser.id != model.id).first()
                        if taken is None:
                            taken = User.query.filter(User.username == wanted).first()
                        if taken is not None:
                            return jsonify({'ok': False, 'msg': __('This sign in name is already taken.')}), 400
                    model.username = wanted

            comment = (request.form.get('comment') or '').strip()
            model.comment = comment[:500]

            raw_tg = (request.form.get('telegram_id') or '').strip()
            if raw_tg:
                digits = raw_tg.lstrip('@')
                if not digits.isdigit():
                    return jsonify({'ok': False, 'msg': __('The telegram identifier must be a number.')}), 400
                model.telegram_id = int(digits)
            else:
                model.telegram_id = None

            lang = (request.form.get('lang') or '').strip()
            if lang:
                try:
                    model.lang = Lang[lang]
                except BaseException:
                    pass
            db.session.commit()
            return jsonify({'ok': True, 'msg': __('Your account was saved.'),
                            'name': model.name,
                            'username': model.username or '',
                            'initial': ws_initial(model.name)})
        except BaseException as err:
            db.session.rollback()
            return jsonify({'ok': False, 'msg': str(err)}), 500

    @route('/change_password', methods=['POST'])
    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def change_password(self):
        """A new password for the signed in account."""
        if not ws_signed():
            return jsonify({'ok': False, 'msg': __('This page went stale, please reload it and try again.')}), 400
        model = current_account
        try:
            current = (request.form.get('current') or '').strip()
            fresh = (request.form.get('password') or '').strip()
            again = (request.form.get('confirm') or '').strip()
            stored = (getattr(model, 'password', '') or '').strip()
            if stored and current != stored:
                return jsonify({'ok': False, 'msg': __('The current password is wrong.')}), 400
            if len(fresh) > 100:
                return jsonify({'ok': False, 'msg': __('The new password cannot be longer than 100 characters.')}), 400
            if len(fresh) < 8:
                return jsonify({'ok': False, 'msg': __('The new password needs at least 8 characters.')}), 400
            if fresh != again:
                return jsonify({'ok': False, 'msg': __('The two passwords are not the same.')}), 400
            model.password = fresh
            db.session.commit()
            return jsonify({'ok': True, 'msg': __('Your password was changed.')})
        except BaseException as err:
            db.session.rollback()
            return jsonify({'ok': False, 'msg': str(err)}), 500

    @route('/upload_photo', methods=['POST'])
    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def upload_photo(self):
        if not ws_signed():
            return jsonify({'ok': False, 'msg': __('This page went stale, please reload it and try again.')}), 400
        import os
        try:
            from hiddifypanel import hutils
            item = request.files.get('photo')
            if item is None or not item.filename:
                return jsonify({'ok': False, 'msg': str(_('Pick a picture first.'))}), 400
            ext = item.filename.rsplit('.', 1)[-1].lower() if '.' in item.filename else ''
            if ext == 'jpe' or ext == 'jfif':
                ext = 'jpg'
            if ext not in WS_PHOTO_EXTS:
                return jsonify({'ok': False, 'msg': str(_('The picture has to be a png, jpg or webp file.'))}), 400
            raw = item.read()
            if not raw or len(raw) > WS_PHOTO_MAX:
                return jsonify({'ok': False, 'msg': str(_('The picture has to stay under three megabytes.'))}), 400
            folder = ws_photo_dir()
            if not folder:
                return jsonify({'ok': False, 'msg': str(_('No place to keep pictures could be found on this server.'))}), 500
            uuid = str(getattr(g.account, 'uuid', '') or '')
            if not uuid:
                return jsonify({'ok': False, 'msg': str(_('Saving failed.'))}), 400
            for old in WS_PHOTO_EXTS:
                try:
                    os.remove(os.path.join(folder, uuid + '.' + old))
                except BaseException:
                    pass
            with open(os.path.join(folder, uuid + '.' + ext), 'wb') as handle:
                handle.write(raw)
            name = ws_photo_name(g.account)
            return jsonify({'ok': True, 'photo': ws_avatar_url(g.account), 'msg': str(_('The picture was saved.'))})
        except BaseException as e:
            return jsonify({'ok': False, 'msg': str(e)}), 500

    @route('/photo/<name>', methods=['GET'])
    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def photo_file(self, name):
        """Serves a saved picture from wherever the panel could keep it."""
        import os
        from flask import send_from_directory
        safe = re.fullmatch(r'[0-9a-fA-F-]{6,60}[.](png|jpg|jpeg|webp)', name or '')
        if not safe:
            return '', 404
        folder = ws_photo_dir()
        if not folder or not os.path.exists(os.path.join(folder, name)):
            return '', 404
        return send_from_directory(folder, name, max_age=60)

    @route('/remove_photo', methods=['POST'])
    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def remove_photo(self):
        if not ws_signed():
            return jsonify({'ok': False, 'msg': __('This page went stale, please reload it and try again.')}), 400
        import os
        try:
            folder = ws_photo_dir()
            uuid = str(getattr(g.account, 'uuid', '') or '')
            for old in WS_PHOTO_EXTS:
                try:
                    os.remove(os.path.join(folder, uuid + '.' + old))
                except BaseException:
                    pass
            return jsonify({'ok': True, 'msg': str(_('The picture was removed.'))})
        except BaseException as e:
            return jsonify({'ok': False, 'msg': str(e)}), 500

    @route('/rotate_link', methods=['POST'])
    @login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})
    def rotate_link(self):
        """A brand new sign in link, which retires every old one."""
        if not ws_signed():
            return jsonify({'ok': False, 'msg': __('This page went stale, please reload it and try again.')}), 400
        model = current_account
        try:
            model.uuid = str(uuid_mod.uuid4())
            db.session.commit()
            try:
                fresh = hiddify.get_account_panel_link(model, request.host)
            except BaseException:
                fresh = ''
            return jsonify({'ok': True, 'msg': __('Your sign in link was replaced.'),
                            'uuid': model.uuid, 'link': fresh})
        except BaseException as err:
            db.session.rollback()
            return jsonify({'ok': False, 'msg': str(err)}), 500
