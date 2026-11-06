# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
import traceback
from flask import render_template, request, jsonify
from flask import g, send_from_directory, session
from flask_babel import gettext as _
import watashipanel
from watashipanel.models import *
from watashipanel.panel import watashi
from watashipanel import hutils
import watashipanel.auth as auth
from watashipanel.auth import current_account
from apiflask import APIFlask, HTTPError, abort
from watashipanel import hutils
from loguru import logger


WS_PHOTO_EXTS = ('png', 'jpg', 'jpeg', 'webp')
_ws_photo_home = {}


def ws_package_root():
    import os
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ws_photo_root():
    """The first folder the panel may really write in, proven by a probe file."""
    import os
    import tempfile
    if _ws_photo_home.get('dir'):
        return _ws_photo_home['dir']
    # watashi v12.2.124: the folder that outlives an upgrade comes first. The one
    # inside the installed package belongs to root, so probing it first only
    # wrote a permission complaint into the log on every single call.
    tries = [
        '/opt/watashi-manager/watashi-panel/uploads/avatars',
        os.path.join(ws_package_root(), 'static', 'uploads', 'avatars'),
        '/opt/watashi-manager/uploads/avatars',
        os.path.join(tempfile.gettempdir(), 'watashi-avatars'),
    ]
    for folder in tries:
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, '.watashi-probe')
            with open(probe, 'wb') as handle:
                handle.write(b'ok')
            os.remove(probe)
        except BaseException as err:
            logger.debug(f"watashi: cannot keep pictures in {folder}: {err}")
            continue
        _ws_photo_home['dir'] = folder
        return folder
    return ''


def ws_photo_in_static(folder=None):
    import os
    place = folder or ws_photo_root()
    if not place:
        return False
    return os.path.abspath(place).startswith(os.path.join(ws_package_root(), 'static'))


def ws_avatar_name(account=None):
    """The file name of the saved picture, wherever the panel keeps it."""
    import os
    from flask import g as _g
    who = account or getattr(_g, 'account', None)
    uuid = str(getattr(who, 'uuid', '') or '')
    if not uuid:
        return ''
    folder = ws_photo_root()
    if not folder:
        return ''
    for ext in WS_PHOTO_EXTS:
        if os.path.exists(os.path.join(folder, uuid + '.' + ext)):
            return uuid + '.' + ext
    return ''


def ws_avatar_url(account=None):
    """A ready address for the picture, static folder or not."""
    import os
    name = ws_avatar_name(account)
    if not name:
        return ''
    # watashi v12.2.124: the address carries the moment the file was written, so a
    # freshly chosen picture is never hidden behind the old one in the cache.

    stamp = ''
    try:
        stamp = str(int(os.path.getmtime(os.path.join(ws_photo_root(), name))))
    except BaseException as err:
        logger.debug(f"watashi: no time stamp for the picture: {err}")
    address = ''
    if ws_photo_in_static():
        address = hutils.flask.static_url_for(filename='uploads/avatars/' + name)
    else:
        try:
            address = hutils.flask.hurl_for('admin.AccountAdmin:photo_file', name=name)
        except BaseException as err:
            logger.debug(f"watashi: no address for the picture: {err}")
            return ''
    if address and stamp:
        address += ('&' if '?' in address else '?') + 'v=' + stamp
    return address


def ws_avatar_file(account=None):
    import os
    from flask import g as _g
    who = account or getattr(_g, 'account', None)
    uuid = str(getattr(who, 'uuid', '') or '')
    if not uuid:
        return ''
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folder = os.path.join(root, 'static', 'uploads', 'avatars')
    for ext in ('png', 'jpg', 'jpeg', 'webp'):
        if os.path.exists(os.path.join(folder, uuid + '.' + ext)):
            return 'uploads/avatars/' + uuid + '.' + ext
    return ''


def ws_avatar_index(account=None):
    from flask import g as _g
    who = account or getattr(_g, 'account', None)
    uuid = str(getattr(who, 'uuid', '') or '')
    if not uuid:
        return 0
    total = 0
    for letter in uuid:
        total += ord(letter)
    return total % 12


def ws_avatar_letter(account=None):
    from flask import g as _g
    who = account or getattr(_g, 'account', None)
    name = str(getattr(who, 'name', '') or '').strip()
    return (name[:1] or 'A').upper()


def ws_panel_mode():
    """watashi v12.3.41dev: the face of the panel for the header switch: the
    simple or the advanced mode, what leaving the advanced mode does to the
    hand built inbounds, and how many of them there are."""
    out = {'advanced': False, 'keep': False, 'custom': 0}
    try:
        out['advanced'] = bool(hconfig(ConfigEnum.advanced_mode))
        out['keep'] = bool(hconfig(ConfigEnum.custom_inbounds_keep))
        from watashipanel.models.custom_inbound import CustomInbound
        out['custom'] = len(CustomInbound.all_rows())
    except Exception as err:
        logger.debug(f"watashi: the panel mode could not be read: {err}")
    return out


# watashi v12.3.41dev: a name of its own. The Domains and the Account pages hand
# their templates a ws_csrf string, and under the name ws_csrf this global was
# hidden by it there, so the layout called a string and both pages answered 500.
def ws_layout_csrf():
    """watashi v12.3.41dev: the form token for the writes the layout itself makes."""
    try:
        from flask_wtf.csrf import generate_csrf
        return generate_csrf()
    except Exception:
        return ''


# watashi v12.3.43dev: the look each admin picks on the Personalization page.
# It is kept per account, so every browser this admin signs in with opens the
# same way. An empty mode means the admin never picked one, and the browser
# keeps the light or dark it showed last time.
# watashi v12.3.44dev: the colour palettes. Each row is the name, the accent, its
# lighter step, the second accent and the dark background of one palette, the
# same values static/css/watashi-palettes.css holds. The first row is the look
# the panel always had.
WS_PALETTES = (
    ('violet', '#7c3aed', '#a78bfa', '#22d3ee', '#0b0f19'),
    ('neon', '#c026d3', '#e879f9', '#22d3ee', '#08060f'),
    ('mint', '#0d9488', '#2dd4bf', '#a3e635', '#050d0c'),
    ('aqua', '#0891b2', '#22d3ee', '#a78bfa', '#061017'),
    ('rose', '#db2777', '#f472b6', '#a78bfa', '#0f0a10'),
    ('sunset', '#ea580c', '#fb923c', '#f472b6', '#100b0a'),
    ('gold', '#d97706', '#fbbf24', '#facc15', '#0c0a09'),
    ('graphite', '#52525b', '#a1a1aa', '#94a3b8', '#09090b'),
)
WS_PALETTE_NAMES = tuple(row[0] for row in WS_PALETTES)
# watashi v12.3.44dev: the languages written from right to left
WS_RTL_LANGS = ('fa', 'ar', 'he', 'ur', 'ps', 'ckb', 'dv', 'yi')

WS_UI_CHOICES = {
    'mode': ('dark', 'light', 'system'),
    'cursor': ('system', 'orbit', 'neon', 'dot', 'reticle', 'stardust'),
    'scrollbar': ('auto', 'always', 'classic'),
    'motion': ('system', 'full', 'calm'),
    'palette': WS_PALETTE_NAMES,  # watashi v12.3.44dev
    'direction': ('auto', 'rtl', 'ltr'),  # watashi v12.3.44dev
}
WS_UI_DEFAULTS = {'mode': '', 'cursor': 'system', 'scrollbar': 'auto', 'motion': 'system',
                  'palette': 'violet', 'direction': 'auto'}  # watashi v12.3.44dev: palette, direction


def ws_ui_clean(raw):
    """watashi v12.3.43dev: only the values this build knows, the default for the rest."""
    out = dict(WS_UI_DEFAULTS)
    if isinstance(raw, dict):
        for key, allowed in WS_UI_CHOICES.items():
            value = str(raw.get(key) or '')
            if value in allowed:
                out[key] = value
    return out


def ws_ui_prefs(account=None):
    """watashi v12.3.43dev: the look of the signed in admin, always complete."""
    import json
    if account is None:
        account = getattr(g, 'account', None)
    raw = getattr(account, 'ui_prefs', None) if account is not None else None
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    return ws_ui_clean(data)


def ws_palette_bg(name):
    """watashi v12.3.44dev: the dark background of a palette, painted before any stylesheet."""
    for row in WS_PALETTES:
        if row[0] == name:
            return row[4]
    return WS_PALETTES[0][4]


def ws_lang_dir(lang=None):
    """watashi v12.3.44dev: rtl for a language written from right to left, else ltr."""
    if lang is None:
        lang = g.get('locale', None) if g else None
        if not lang:
            try:
                from flask_babel import get_locale
                lang = get_locale()
            except Exception:
                lang = ''
    name = str(getattr(lang, 'language', None) or lang or '').strip().replace('-', '_').split('_')[0].lower()
    return 'rtl' if name in WS_RTL_LANGS else 'ltr'


def ws_ui_dir(prefs=None):
    """watashi v12.3.44dev: the direction of the panel for the signed in admin.

    auto follows the language: Persian opens from the right, English from the
    left. rtl and ltr are what the admin picked on the Personalization page."""
    if prefs is None:
        prefs = ws_ui_prefs()
    picked = str((prefs or {}).get('direction') or 'auto')
    if picked in ('rtl', 'ltr'):
        return picked
    return ws_lang_dir()


_ws_asset_seal = {}


def ws_asset(path):
    """watashi v12.3.43dev: the address of a static file with a seal of its content.

    Static files are cached for a year, so a changed file needs a changed
    address; the seal changes exactly when the content does.
    """
    seal = _ws_asset_seal.get(path)
    if seal is None:
        import hashlib
        import os
        try:
            from flask import current_app
            with open(os.path.join(current_app.static_folder, path), 'rb') as fh:
                seal = hashlib.sha1(fh.read()).hexdigest()[:10]
        except Exception:
            seal = str(watashipanel.__version__)
        _ws_asset_seal[path] = seal
    return hutils.flask.static_url_for(filename=path, v=seal)


def init_app(app: APIFlask):
    app.jinja_env.globals['ConfigEnum'] = ConfigEnum
    app.jinja_env.globals['DomainType'] = DomainType
    app.jinja_env.globals['UserMode'] = UserMode
    app.jinja_env.globals['hconfig'] = hconfig
    app.jinja_env.globals['g'] = g
    app.jinja_env.globals['hutils'] = hutils
    app.jinja_env.globals['watashi'] = watashi
    app.jinja_env.globals['version'] = watashipanel.__version__
    # if not watashipanel.is_released_version:
    #     app.jinja_env.globals['version'] = f"{watashipanel.__version__}-dev"
    
    app.jinja_env.globals['static_url_for'] = hutils.flask.static_url_for
    app.jinja_env.globals['ws_avatar_file'] = ws_avatar_file
    app.jinja_env.globals['ws_avatar_url'] = ws_avatar_url
    app.jinja_env.globals['ws_avatar_index'] = ws_avatar_index
    app.jinja_env.globals['ws_avatar_letter'] = ws_avatar_letter
    app.jinja_env.globals['hurl_for'] = hutils.flask.hurl_for
    app.jinja_env.globals['_gettext'] = lambda x: print("==========", x)
    # watashi v12.2.130ch: proxy_stats_url went with the live dashboard
    # the menu only shows what the signed in account may actually open
    app.jinja_env.globals['ws_can'] = ws_can
    # watashi v12.3.41dev: the simple / advanced switch in the header
    app.jinja_env.globals['ws_panel_mode'] = ws_panel_mode
    app.jinja_env.globals['ws_layout_csrf'] = ws_layout_csrf
    # watashi v12.3.43dev: the Personalization page and the frame's cached files
    app.jinja_env.globals['ws_ui_prefs'] = ws_ui_prefs
    app.jinja_env.globals['ws_asset'] = ws_asset
    # watashi v12.3.44dev: the palettes and the direction of the panel
    app.jinja_env.globals['ws_ui_dir'] = ws_ui_dir
    app.jinja_env.globals['ws_lang_dir'] = ws_lang_dir
    app.jinja_env.globals['ws_palette_bg'] = ws_palette_bg
    app.jinja_env.globals['WS_PALETTES'] = WS_PALETTES

    @app.after_request
    def apply_no_robot(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.status_code == 401:
            response.headers['WWW-Authenticate'] = 'Basic realm="Watashi"'
        return response

    @app.errorhandler(Exception)
    def internal_server_error(e):
        if hasattr(e, 'code') and e.code == 404:
            logger.error(f'{e} {request.url}')
        else:
            logger.exception(e)
        
        if isinstance(e, Exception):
            if hutils.flask.is_api_call(request.path):
                return jsonify({
                    'msg': str(e),
                }), 500

        if hasattr(e, 'code') and e.code == 404:
            return jsonify({
                'message': 'Not Found',
            }), 404

        has_update = hutils.utils.is_panel_outdated()

        if not request.accept_mimetypes.accept_html:
            if has_update:
                return jsonify({
                    'message': 'This version of Watashi Panel is outdated. please update it from admin area.',
                }), 500

            return jsonify({'message': str(e),
                            'detail': [f'{filename}:{line} {function}: {text}' for filename, line, function, text in traceback.extract_tb(e.__traceback__)],
                            'version': watashipanel.__version__,
                            }), 500

        trace = traceback.format_exc()

        # Create github issue link
        issue_link = hutils.github_issue.generate_github_issue_link_for_500_error(e, trace)
        last_version = watashi.ws_newest_for_this_box()  # watashi v12.2.69

        return render_template('500.html', error=e, trace=trace, has_update=has_update, last_version=last_version, issue_link=issue_link), 500

    @app.errorhandler(HTTPError)
    def internal_server_error(e):
        # print(request.headers)
        if not request.accept_mimetypes.accept_html:
            return app.error_callback(e)
        # if it's interval server error
        if e.status_code == 500:
            trace = traceback.format_exc()

            # Create github issue link
            issue_link = hutils.github_issue.generate_github_issue_link_for_500_error(e, trace)

            has_update = hutils.utils.is_panel_outdated()
            last_version = watashi.ws_newest_for_this_box()  # watashi v12.2.69

            return render_template('500.html', error=e, trace=trace, has_update=has_update, last_version=last_version, issue_link=issue_link), 500

        # if it's access denied error
        # if e.status_code in [400,401,403]:
        #     return render_template('access-denied.html',error=e), e.status_code

        # if it's api error
        if hutils.flask.is_api_call(request.path):
            return {
                'msg': e.message,
            }, e.status_code

        return render_template('error.html', error=e), e.status_code

    @app.url_defaults
    def add_proxy_path_user(endpoint, values):
        if 'static' in endpoint:
            values['proxy_path'] = g.proxy_path
        if 'proxy_path' not in values:
            if force_path := g.get('force_proxy_path'):
                values['proxy_path'] = force_path
            elif hutils.flask.is_admin_role(current_account.role):  # type: ignore
                values['proxy_path'] = hconfig(ConfigEnum.proxy_path_admin)
            elif hutils.flask.is_user_panel_call():
                values['proxy_path'] = hconfig(ConfigEnum.proxy_path_client)
            elif current_account and hutils.flask.is_admin_role(current_account.role):  # type: ignore
                values['proxy_path'] = hconfig(ConfigEnum.proxy_path_admin)
            else:
                values['proxy_path'] = g.proxy_path or "A"
        if "child_id" not in values and g.__child_id != 0:
            values['child_id'] = g.child.id

        if hutils.flask.is_api_v1_call(endpoint=endpoint) and 'admin_uuid' not in values:
            values['admin_uuid'] = AdminUser.get_super_admin_uuid()

        # if 'secret_uuid' not in values and g.account and ".webmanifest" in request.path:
        #     values['secret_uuid'] = g.account.uuid

    @app.route("/<proxy_path>/videos/<file>")
    @app.doc(hide=True)
    def videos(file):
        print("file", file, app.config['WATASHI_CONFIG_PATH'] +
              '/watashi-panel/videos/' + file)
        return send_from_directory(app.config['WATASHI_CONFIG_PATH'] + '/watashi-panel/videos/', file)

    @app.url_value_preprocessor
    def pull_default(endpoint, values):
        g.__child_id = 0
        g.uuid = None
        g.proxy_path = None
        g.user_agent = hutils.flask.get_user_agent()

        if values:
            g.proxy_path = values.pop('proxy_path', None)
            if 'secret_uuid' in values:
                g.uuid = values.pop('secret_uuid', None)

            g.__child_id = values.pop('child_id', 0)
        g.child = Child.by_id(g.__child_id) or abort(404, "Child not found")
        g.account = current_account

    @app.before_request
    def base_middleware():
        if "generate_204" in request.path:
            return "", 204
        if request.endpoint == 'static' or request.endpoint == "videos":
            return

        if g.user_agent['is_bot']:
            abort(400, "invalid")

        g.proxy_path = hutils.flask.get_proxy_path_from_url(request.url)
        hutils.flask.proxy_path_validator(g.proxy_path)

        # setup dark mode
        if request.args.get('darkmode') is not None:
            session['darkmode'] = request.args.get('darkmode', '').lower() == 'true'
        g.darkmode = session.get('darkmode', False)

        # setup pwa
        import random
        g.install_pwa = random.random() <= 0.05
        if request.args.get('pwa') is not None:
            session['pwa'] = request.args.get('pwa', '').lower() == 'true'
        g.pwa = session.get('pwa', False)

        # setup telegram bot
        if hconfig(ConfigEnum.telegram_bot_token):
            import watashipanel.panel.commercial.telegrambot as telegrambot
            g.bot = telegrambot.bot
        else:
            g.bot = None

        if auth_before := auth.auth_before_request():
            return auth_before

    app.jinja_env.globals['generate_github_issue_link_for_admin_sidebar'] = hutils.github_issue.generate_github_issue_link_for_admin_sidebar
    with app.app_context():
        import watashipanel.panel.commercial.telegrambot as telegrambot
        # watashi v12.2.130cf: the old test was "register the bot when it has no
        # username", but tgbot.init_app() fills the username a moment earlier, so on
        # a healthy token set_webhook() was never reached and the bot stayed mute.
        # Now every boot costs one cheap getWebhookInfo call and a changed domain,
        # admin path or super-admin uuid heals itself.
        try:
            telegrambot.ws_ensure_webhook()  # type: ignore
        except BaseException:
            pass
