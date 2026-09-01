from flask_classful import FlaskView, route
from hiddifypanel import hutils
from hiddifypanel.auth import login_required, current_account, login_user, logout_user, login_by_uuid
from flask import redirect, request, g, render_template, flash, jsonify
from hiddifypanel.hutils.flask import hurl_for
from flask import current_app as app
from flask_babel import lazy_gettext as _
from apiflask import abort
import hiddifypanel.panel.hiddify as hiddify
from hiddifypanel.models import *

from flask_wtf import FlaskForm
import wtforms as wtf

import re
import time  # watashi v12.2.52: the door works on deadlines now
import hashlib  # watashi v12.2.60: the lock sits on the account now


# --- Watashi v12.2.36: the entrance of the panel ------------------------------
# The address of the panel never changes: a link that already carries the
# secret uuid still walks straight in. What is new is that the same box also
# takes the sign in name, so a bare proxy path link is enough to come home.
WS_UUID_SHAPE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
WS_TRIES = 3  # wrong keys the door forgives
WS_LOCK_TIME = 600  # and how long it stays shut afterwards, in seconds
WS_LOCK_CAP = WS_LOCK_TIME  # watashi v12.2.52: nobody ever waits longer than this


def ws_is_uuid(text):
    return bool(WS_UUID_SHAPE.match((text or '').strip()))


def ws_brand_title():
    return (hconfig(ConfigEnum.branding_title) or '').strip() or 'Watashi Manager'


def ws_brand_parts():
    words = ws_brand_title().split()
    if len(words) < 2:
        return ws_brand_title(), ''
    return ' '.join(words[:-1]), words[-1]


def ws_store():
    """The shared memory the whole panel already leans on."""
    try:
        from hiddifypanel.cache import redis_client
        return redis_client
    except BaseException:
        return None


def ws_who_key(identity):
    """One counter per account, and nowhere else.

    watashi v12.2.60: the key used to carry the visitor address, so every
    account reached from one address shared a single counter, and a wrong key
    typed at one account shut the others as well. The owner asked for the
    timer to sit on the account somebody was trying to open, so that is what
    the key is now. The name is hashed, so redis never holds a login name.
    An empty name is nobody, and nobody is never counted or shut out.
    """
    who = (identity or '').strip().lower()
    if not who:
        return ''
    return 'watashi:door:acct:%s' % hashlib.sha256(who.encode('utf-8', 'ignore')).hexdigest()[:16]


def ws_wait_left(identity=''):
    """Seconds the door stays shut for one account, zero when it is open.

    watashi v12.2.52: the answer comes from a written deadline instead of the
    lifetime of a key, it is capped at WS_LOCK_CAP, and anything unreadable
    or already past is thrown away on sight. A leftover key can no longer
    keep anybody waiting.
    """
    store = ws_store()
    base = ws_who_key(identity)
    if store is None or not base:
        return 0
    key = base + ':until'
    try:
        raw = store.get(key)
        if raw is None:
            return 0
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'ignore')
        left = int(float(raw) - time.time())
    except BaseException:
        ws_drop_key(key)
        return 0
    if left <= 0:
        ws_drop_key(key)
        return 0
    return left if left < WS_LOCK_CAP else WS_LOCK_CAP


def ws_count_miss(store, key):
    """Counts one wrong key against one account and keeps it perishable.

    watashi v12.2.65: this used to be an incr followed by a bare expire. Two
    faults lived in those two lines. If the expire threw, the exception left
    ws_note_miss through its own guard and the caller was told zero, so the
    strike was real in redis but the door never shut; the counter then climbed
    unseen until one ordinary mistake weeks later met a pile of three and shut
    the door on what felt like a first attempt. And if the expire was merely
    lost, the counter stayed behind with no deadline and never faded.

    So: incr is one atomic command and is never retried, because counting the
    same wrong password twice would shut the door too early, which is the same
    complaint wearing different clothes. Everything after it is sealed, and a
    counter found without a deadline is given one on the spot, so a lost expire
    repairs itself at the next strike instead of lasting forever.
    """
    count = int(store.incr(key))
    try:
        if int(store.ttl(key) or -1) < 0:
            store.expire(key, WS_LOCK_TIME)
    except BaseException:
        try:
            store.expire(key, WS_LOCK_TIME)
        except BaseException:
            pass
    return count
def ws_note_miss(identity=''):
    """Counts a wrong key for one account and shuts that one door on WS_TRIES."""
    store = ws_store()
    base = ws_who_key(identity)
    if store is None or not base:
        return 0
    try:
        key = base + ':miss'
        count = ws_count_miss(store, key)  # watashi v12.2.65
        if count >= WS_TRIES and not ws_wait_left(identity):
            # watashi v12.2.52: a deadline, written once. Knocking again while
            # the door is shut can never push it further away.
            store.setex(base + ':until', WS_LOCK_TIME + 30, '%d' % int(time.time() + WS_LOCK_TIME))
            store.delete(key)
            ws_door_log('shut for %d seconds after %d wrong keys' % (WS_LOCK_TIME, count))
        return count
    except BaseException:
        return 0


def ws_forget_misses(identity=''):
    store = ws_store()
    base = ws_who_key(identity)
    if store is None or not base:
        return
    try:
        store.delete(base + ':miss')
        store.delete(base + ':until')
    except BaseException:
        pass


def ws_drop_key(key):
    """Throws a key away without ever letting redis break the page."""
    store = ws_store()
    if store is None:
        return
    try:
        store.delete(key)
    except BaseException:
        pass


def ws_door_log(words):
    """Every shut door leaves a line behind, so it can be explained later."""
    try:
        app.logger.warning('watashi door: %s' % words)
    except BaseException:
        pass


def ws_locked_words(waiting):
    """The sentence the door says, with the time left spelled out in numbers."""
    left = int(waiting or 0)
    return '%s %d:%02d' % (str(_('login.locked.flash')), left // 60, left % 60)


def ws_entrance_words():
    """Every word the entrance says in the browser, already translated."""
    return {
        'waiting': str(_('login.kind.waiting')),
        'name': str(_('login.kind.username')),
        'uuid': str(_('login.kind.uuid')),
        'hintId': str(_('login.identity.hint')),
        'hintPw': str(_('login.password.hint')),
        'show': str(_('login.password.show')),
        'hide': str(_('login.password.hide')),
        'wait': str(_('login.button.busy')),
        'needId': str(_('login.need.identity')),
        'needPass': str(_('login.need.password')),
        'open': str(_('login.door.open')),
        'skin': str(_('login.tool.theme')),
        'lang': str(_('login.tool.language')),
    }


def ws_entrance_data(form, picked_lang=None, waiting=0):
    """Everything the entrance page needs to draw itself."""
    from flask_babel import get_locale
    from urllib.parse import urlencode
    lang = str(picked_lang or get_locale() or 'en')
    right_to_left = lang.split('_')[0] in ('fa', 'ar', 'he', 'ur')
    other = 'en' if lang.startswith('fa') else 'fa'
    args = {}
    for name in request.args:
        args[name] = request.args.get(name)
    args['lang'] = other
    query = request.query_string.decode('utf-8', 'ignore') if request.query_string else ''
    first, second = ws_brand_parts()
    waiting = int(waiting or 0)  # watashi v12.2.60: the caller knows the account
    return {
        'lg_lang': lang,
        'lg_dir': 'rtl' if right_to_left else 'ltr',
        'lg_skin': 'dark',
        'lg_title': ws_brand_title(),
        'lg_brand_a': first,
        'lg_brand_b': second,
        'lg_sign': str(_('login.gate.sign')),
        'lg_lang_next': other,
        'lg_lang_url': request.path + '?' + urlencode(args),
        'lg_post_url': request.path + (('?' + query) if query else ''),
        'lg_identity': (form.secret_textbox.data or '') if form else '',
        "lg_locked": waiting > 0,
        'lg_wait': waiting,
        'lg_words': ws_entrance_words(),
    }


def ws_picked_lang():
    pick = (request.args.get('lang') or request.cookies.get('watashi_lang') or '').strip()
    return pick if pick in ('fa', 'en') else ''


def ws_render_entrance(form, status=200, retry_after=0, waiting=0):
    """Draws the door, in the tongue the visitor asked for."""
    from flask import make_response
    pick = ws_picked_lang()
    if pick:
        from flask_babel import force_locale
        with force_locale(pick):
            body = render_template('login.html', form=form, **ws_entrance_data(form, pick, waiting))
    else:
        body = render_template('login.html', form=form, **ws_entrance_data(form, None, waiting))
    answer = make_response(body, status)
    if retry_after:
        # watashi v12.2.52: a well behaved client waits instead of hammering
        answer.headers['Retry-After'] = str(int(retry_after))
    asked = request.args.get('lang')
    if asked in ('fa', 'en'):
        answer.set_cookie('watashi_lang', asked, max_age=60 * 60 * 24 * 365, samesite='Lax', httponly=False)
    return answer


def ws_login_page(identity=''):
    """The door itself, drawable from anywhere in the panel.

    watashi v12.2.60: auth.py leans on this to break a redirect loop. When the
    address that failed a guard is the sign in page itself, one more redirect
    only walks the same circle again, so the page is answered on the spot
    instead of being pointed at.
    """
    form = LoginForm()
    form.secret_textbox.data = form.secret_textbox.data or identity
    return ws_render_entrance(form, 200, 0, ws_wait_left(identity))


class LoginForm(FlaskForm):
    # the box takes a sign in name or the secret uuid, the page tells which
    secret_textbox = wtf.fields.StringField(_('login.identity.label'), [wtf.validators.Length(min=1, max=100)], default='',
        description=_('login.identity.description'), render_kw={
        'maxlength': '100',
        'autocomplete': 'username'
    })

    password_textbox = wtf.fields.PasswordField(_(f'login.password.label'), default='',
        description=_(f'login.password.description'), render_kw={    })
    submit = wtf.fields.SubmitField(_('login.button'))


class LoginView(FlaskView):

    # @route("/")
    def index(self, force=None, next=None):
        force_arg = request.args.get('force')
        redirect_arg = request.args.get('redirect')
        username_arg = request.args.get('user') or ''
        # watashi v12.2.60: force=1 means "show me the door". It used to be read
        # into a variable and then ignored, so a session that could not be
        # served here was handed to a page that bounced straight back to this
        # address, and the browser walked that circle until it gave up with
        # ERR_TOO_MANY_REDIRECTS. The session is dropped here instead.
        if force_arg and current_account:
            logout_user()
            ws_door_log('a forced visit dropped a session that could not be served here')
        if not current_account:
            form=LoginForm()
            form.secret_textbox.data=form.secret_textbox.data or username_arg
            return ws_render_entrance(form, 200, 0, ws_wait_left(username_arg))

            # abort(401, "Unauthorized1")

        if redirect_arg:
            return redirect(redirect_arg)
        if hutils.flask.is_admin_proxy_path() and hutils.flask.is_admin_role(current_account.role):
            return redirect(hurl_for('admin.Dashboard:index'))
        # watashi v12.2.60: only an end user account may be handed to the user
        # pages. Anything else is asked to sign in again, because those pages
        # answer a stranger with a redirect back to this very address, which is
        # the other half of the loop the owner walked into.
        if current_account.role != Role.user:
            logout_user()
            return ws_login_page()
        # if g.user_agent['is_browser'] and hutils.flask.is_client_proxy_path():
        #     return redirect(hurl_for('client.UserView:index'))

        from hiddifypanel.panel.user import UserView
        return UserView().auto_sub()

    def post(self):
        form = LoginForm()
        typed = (form.secret_textbox.data or '').strip()
        waiting = ws_wait_left(typed)
        if waiting > 0:
            # watashi v12.2.52: 200, not 429. A cdn in front of the panel turns a
            # 429 into an error page of its own, and that is what the tester saw
            # instead of the countdown.
            hutils.flask.flash(ws_locked_words(waiting), 'danger')  # type: ignore
            return ws_render_entrance(form, 200, waiting, waiting)
        if not form.validate_on_submit():
            # watashi v12.2.60: a page left open too long carries a stale csrf
            # token, and that is not a wrong password. It used to fall through
            # to the counter below, so a single mistake could reach the third
            # strike on its own.
            hutils.flask.flash(_('login.wrong.key'), 'danger')  # type: ignore
            return ws_render_entrance(form, 200)
        secret = form.password_textbox.data or ''
        admin_side = hutils.flask.is_admin_proxy_path()
        if ws_is_uuid(typed):
            if login_by_uuid(typed, secret, admin_side):
                ws_forget_misses(typed)
                return redirect(f'/{g.proxy_path}/')
        elif not secret.strip():
            # an account that carries no password of its own may only
            # enter through its own link, never by name alone
            hutils.flask.flash(_('login.need.password'), 'warning')  # type: ignore
            return ws_render_entrance(form, 200)
        elif len(typed) >= 3:
            model = AdminUser.by_username_password(typed, secret) if admin_side else User.by_username_password(typed, secret)
            if model and (model.username or '').strip() and (model.password or '').strip():
                login_user(model, force=True)
                ws_forget_misses(typed)
                return redirect(f'/{g.proxy_path}/')
        missed = ws_note_miss(typed)
        waiting = ws_wait_left(typed)
        if waiting > 0:
            hutils.flask.flash(ws_locked_words(waiting), 'danger')  # type: ignore
            return ws_render_entrance(form, 200, waiting, waiting)
        note = str(_('login.wrong.key'))
        left = WS_TRIES - missed
        if missed and left > 0:
            note = note + ' ' + str(_('login.tries.left')).replace('@N@', str(left))
        hutils.flask.flash(note, 'danger')  # type: ignore
        return ws_render_entrance(form, 200)

    @route('/logout')
    def logout(self):
        """Ends the browser session and sends the visitor back to the sign in form."""
        try:
            logout_user()
        except BaseException:
            pass
        # watashi v12.2.65: a line here used to read g.__account_store, and
        # inside a class python rewrites that to g._LoginView__account_store,
        # so it created a stranger attribute and cleared nothing at all.
        # logout_user already empties the real one, so the line is gone.
        return redirect(hurl_for('common_bp.LoginView:index', force=1))

    @ route("/l/<path:path>/")
    @ route("/l/<path:path>")
    @ route("/l/")
    @ route("/l")
    def basic(self, path=None):
        if path:
            redirect_arg = f"/{g.proxy_path}/{path}"
        else:
            redirect_arg = request.args.get('next')

        if not current_account or (not request.headers.get('Authorization')):
            username = request.authorization.username if request.authorization else g.uuid

            loginurl = hurl_for('common_bp.LoginView:index', next=redirect_arg, user=username)
            if g.user_agent['is_browser'] and request.headers.get('Authorization') or (current_account and len(username) > 0 and current_account.username != username):
                hutils.flask.flash(_('Incorrect Password'), 'error')  # type: ignore
                logout_user()  # watashi v12.2.65: the mangled clear was dead weight
                # hutils.flask.flash(request.authorization.username, 'error')
                return redirect(loginurl)

            return render_template("redirect.html", url=loginurl), 401
            # abort(401, "Unauthorized1")
        if redirect_arg:
            return redirect(redirect_arg)

        # watashi v12.2.65: every other branch of the door reads current_account.
        # g.account is only planted by a before_request hook, so a route that
        # arrives without it raised AttributeError here instead of answering.
        if hutils.flask.is_admin_proxy_path() and hutils.flask.is_admin_role(current_account.role):
            return redirect(hurl_for('admin.Dashboard:index'))

        if g.user_agent['is_browser'] and hutils.flask.is_client_proxy_path():
            return redirect(hurl_for('client.UserView:index'))

        from hiddifypanel.panel.user import UserView
        # return redirect(url_for("user.")) UserView().auto_sub()

    # @route('/<uuid:uuid>/<path:path>')
    # @route('/<uuid:uuid>/')

    # def uuid(self, uuid, path=''):
    #     proxy_path = hiddify.flask.get_proxy_path_from_url(request.url)
    #     g.__account_store = None
    #     uuid = str(uuid)
    #     if proxy_path == hconfig(ConfigEnum.proxy_path_client):
    #         g.__account_store = User.by_uuid(uuid)
    #         path = f'client/{path}'
    #     elif proxy_path == hconfig(ConfigEnum.proxy_path_admin):
    #         g.__account_store = AdminUser.by_uuid(uuid)
    #     if not g.account:
    #         abort(403)
    #     if not g.user_agent['is_browser'] and proxy_path == hconfig(ConfigEnum.proxy_path_client):
    #         userview = UserView()
    #         if "all.txt" in path:
    #             return userview.all_configs()
    #         if 'singbox.json' in path:
    #             return userview.singbox()
    #         if 'full-singbox.json' in path:
    #             return userview.full_singbox()
    #         if 'clash' in path:
    #             splt = path.split("/")
    #             meta_or_normal = 'meta' if splt[-2] == 'meta' else 'normal'
    #             typ = splt[-1].split('.yml')[0]
    #             return userview.clash_config(meta_or_normal=meta_or_normal, typ=typ)
    #         return userview.force_sub()

    #     login_user(g.account, force=True)

    #     return redirect(f"/{proxy_path}/{path}")

    @ route('/<secret_uuid>/manifest.webmanifest')
    def create_pwa_manifest(self):
        domain = request.host
        admin_call=hutils.flask.is_admin_panel_call()
        account=AdminUser.by_uuid(g.uuid) if admin_call else User.by_uuid(g.uuid)
        name = (domain if admin_call  else account.name)
        return jsonify({
            "name": f"{ws_brand_title()} {name}",
            "short_name": f"{name}"[:12],
            "theme_color": "#0b0f19",
            "background_color": "#0b0f19",
            "display": "standalone",
            "scope": f"/",
            "start_url": hiddify.get_account_panel_link(account, domain) + "?pwa=true",
            "description": "Watashi Manager, a panel with a pulse",
            "orientation": "any",
            "icons": [
                {
                    "src": hutils.flask.static_url_for(filename='images/hiddify-dark.png'),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable any"
                }
            ]
        })
