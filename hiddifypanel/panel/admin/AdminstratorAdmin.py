from hiddifypanel.auth import login_required

from wtforms.validators import Regexp
from hiddifypanel.models import *
from wtforms.validators import Regexp, ValidationError
from .adminlte import AdminLTEModelView
from flask_babel import lazy_gettext as _
from wtforms.validators import Regexp
from flask_babel import gettext as __
from flask import request, redirect, jsonify  # type: ignore
from flask_admin import expose
from hiddifypanel.database import db
import uuid as uuid_mod
from markupsafe import Markup

from flask import g
import datetime
from wtforms import SelectField, FloatField

from hiddifypanel.panel import hiddify
from hiddifypanel import hutils


class AdminModeField(SelectField):
    def __init__(self, label=None, validators=None, **kwargs):
        super(AdminModeField, self).__init__(label, validators, **kwargs)
        if g.account.mode in [AdminMode.agent, AdminMode.admin]:
            self.choices = [(AdminMode.agent.value, 'agent')]
        elif g.account.mode == AdminMode.admin:
            self.choices = [(AdminMode.agent.value, 'agent'), (AdminMode.admin.value, 'Admin'),]
        elif g.account.mode == AdminMode.super_admin:
            self.choices = [(AdminMode.agent.value, 'agent'), (AdminMode.admin.value, 'Admin'),
                            (AdminMode.super_admin.value, 'Super Admin'), (AdminMode.custom.value, 'Custom')]


class SubAdminsField(SelectField):
    def __init__(self, label=None, validators=None, *args, **kwargs):
        kwargs.pop("allow_blank")
        super().__init__(label, validators, *args, **kwargs)
        self.choices = [(admin.id, admin.name) for admin in g.account.sub_admins]
        self.choices += [(g.account.id, g.account.name)]


WS_ONE_GIG = 1024 * 1024 * 1024
WS_ADMIN_ONLINE_WINDOW = 120  # seconds; the very same window the users list uses
WS_ADMIN_MODE_ORDER = {'super_admin': 0, 'admin': 1, 'agent': 2, 'custom': 3}
WS_ADMIN_SORT_KEYS = ('name', 'mode', 'data', 'data_pct', 'users', 'users_pct', 'online')


def ws_admin_mode_labels():
    """Human names for the three admin modes, translated at call time."""
    return {
        'super_admin': _('Owner'),
        'admin': _('Admin'),
        'agent': _('Agent'),
        'custom': _('Custom'),
    }


def ws_perm_can(cap):
    """May the signed in account do this?"""
    from hiddifypanel.models.admin_perms import ws_can
    return ws_can(cap)


def ws_perm_catalog():
    """The switches of the hand made mode, grouped and translated."""
    from hiddifypanel.models.admin_perms import WS_CAP_GROUPS
    groups = {
        'overview': _('Overview'),
        'access': _('Access'),
        'network': _('Network'),
        'system': _('System'),
        'user_actions': _('What may be done to users'),
        'admin_actions': _('What may be done to admins'),
    }
    caps = {
        'dashboard': _('Dashboard'),
        'monitoring': _('Monitoring'),
        'usage': _('Usage'),
        'users': _('Users'),
        'admins': _('Admins'),
        'account': _('My Account'),
        'domains': _('Domains'),
        'proxies': _('Proxies'),
        'tunnel': _('Tunnel'),
        'settings': _('Settings'),
        'actions': _('Actions'),
        'backup': _('Backup'),
        'nodes': _('Nodes'),
        'user_add': _('Create user'),
        'user_edit': _('Edit user'),
        'user_delete': _('Delete user'),
        'user_reset': _('Reset user usage'),
        'admin_add': _('Create admin'),
        'admin_edit': _('Edit admin'),
        'admin_delete': _('Delete admin'),
    }
    out = []
    for name, keys in WS_CAP_GROUPS:
        out.append({
            'key': name,
            'label': groups.get(name, name),
            'caps': [{'key': key, 'label': caps.get(key, key)} for key in keys],
        })
    return out


def ws_admin_mode_key(model):
    mode = getattr(model, 'mode', None)
    return getattr(mode, 'name', None) or (str(mode) if mode else 'agent')


def ws_admin_filter_args(args):
    """Read the toolbar filters for the admins list out of the query string.

    Everything is optional and anything unreadable falls back to a safe value,
    so a hand edited address can never break the page.
    """
    def text(key, default='all'):
        raw = (args.get(key) or '').strip()
        return raw or default

    mode = text('ws_mode')
    can_add = text('ws_can_add')
    quota = text('ws_quota')
    note = text('ws_note')
    sort = text('ws_sort', '')
    f = {
        'mode': mode if mode in ('all',) + tuple(WS_ADMIN_MODE_ORDER) else 'all',
        'can_add': can_add if can_add in ('all', 'yes', 'no') else 'all',
        'quota': quota if quota in ('all', 'limited', 'unlimited', 'full') else 'all',
        'note': note if note in ('all', 'with', 'without') else 'all',
        'online': text('ws_online', '') in ('1', 'true', 'on', 'yes'),
        'sort': sort if sort in WS_ADMIN_SORT_KEYS else '',
        'dir': 'desc' if text('ws_dir', 'asc') == 'desc' else 'asc',
    }
    n = 0
    for key in ('mode', 'can_add', 'quota', 'note'):
        if f[key] != 'all':
            n += 1
    if f['online']:
        n += 1
    f['count'] = n
    return f


def ws_admin_has_custom_list(f):
    """True when we must take over listing instead of the stock query."""
    return bool(f.get('count')) or f.get('sort') in WS_ADMIN_SORT_KEYS


def ws_admin_used_bytes(model):
    try:
        return int(model.recursive_usage())
    except BaseException:
        return 0


def ws_admin_users_count(model):
    try:
        return int(model.recursive_users_query().count())
    except BaseException:
        return 0


def ws_admin_online_count(model):
    try:
        edge = datetime.datetime.now() - datetime.timedelta(seconds=WS_ADMIN_ONLINE_WINDOW)
        return int(model.recursive_users_query().filter(User.last_online > edge).count())
    except BaseException:
        return 0


def ws_admin_extra(model):
    """Counts and freshest activity for one admin, straight from the database."""
    out = {'active_users': 0, 'disabled_users': 0, 'last_activity': '', 'last_activity_ts': 0}
    try:
        from sqlalchemy import func
        q = model.recursive_users_query()
        total = int(q.count())
        disabled = int(q.filter(User.enable == False).count())  # noqa: E712
        out['disabled_users'] = disabled
        out['active_users'] = max(0, total - disabled)
        newest = db.session.query(func.max(User.last_online)).filter(
            User.added_by.in_(model.recursive_sub_admins_ids())).scalar()
        if newest is not None and getattr(newest, 'year', 0) > 1900:
            out['last_activity'] = newest.strftime('%Y-%m-%d %H:%M:%S')
            out['last_activity_ts'] = int(newest.timestamp())
    except BaseException:
        pass
    return out


def ws_admin_links(model):
    """Every domain this admin can sign in through, newest panel link first."""
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
        out.append({'domain': domain, 'label': domain, 'link': link,
                    'kind': kind, 'current': domain == host})

    add(host, 'direct')
    try:
        from hiddifypanel.models import Domain
        for d in Domain.query.all():
            mode = (getattr(getattr(d, 'mode', None), 'name', '') or '').lower()
            if any(bad in mode for bad in ('fake', 'reality', 'relay', 'old')):
                continue
            add(getattr(d, 'domain', ''), 'cdn' if 'cdn' in mode else 'direct')
    except BaseException:
        pass
    return out


def ws_admin_keep(model, f):
    """Does this admin survive the toolbar filters?"""
    if f.get('mode', 'all') != 'all' and ws_admin_mode_key(model) != f['mode']:
        return False
    if f.get('can_add', 'all') != 'all':
        want = f['can_add'] == 'yes'
        if bool(model.can_add_admin) != want:
            return False
    quota = f.get('quota', 'all')
    if quota != 'all':
        unlimited = bool(model.is_data_unlimited)
        if quota == 'unlimited' and not unlimited:
            return False
        if quota == 'limited' and unlimited:
            return False
        if quota == 'full' and (unlimited or model.can_have_more_data()):
            return False
    note = f.get('note', 'all')
    if note != 'all':
        has = bool((model.comment or '').strip())
        if note == 'with' and not has:
            return False
        if note == 'without' and has:
            return False
    if f.get('online') and ws_admin_online_count(model) <= 0:
        return False
    return True


def ws_admin_sort_value(model, key):
    name = (model.name or '').strip().lower()
    if key == 'mode':
        return (WS_ADMIN_MODE_ORDER.get(ws_admin_mode_key(model), 9), name)
    if key == 'data':
        return (ws_admin_used_bytes(model), name)
    if key == 'data_pct':
        try:
            return (-1.0 if model.is_data_unlimited else float(model.data_usage_percent()), name)
        except BaseException:
            return (-1.0, name)
    if key == 'users':
        return (ws_admin_users_count(model), name)
    if key == 'users_pct':
        total = int(model.max_users or 0)
        if ws_admin_mode_key(model) == 'super_admin' or total <= 0:
            return (-1.0, name)
        return (ws_admin_users_count(model) * 100.0 / total, name)
    if key == 'online':
        return (ws_admin_online_count(model), name)
    return (name, '')


def ws_admin_sort(rows, f):
    key = f.get('sort')
    if key not in WS_ADMIN_SORT_KEYS:
        return list(rows)
    return sorted(rows, key=lambda m: ws_admin_sort_value(m, key),
                  reverse=(f.get('dir') == 'desc'))


def ws_admin_page_slice(rows, page, page_size):
    try:
        page = int(page or 0)
    except (TypeError, ValueError):
        page = 0
    try:
        page_size = int(page_size or 20)
    except (TypeError, ValueError):
        page_size = 20
    if page < 0:
        page = 0
    if page_size <= 0:
        page_size = 20
    start = page * page_size
    return rows[start:start + page_size]


class AdminstratorAdmin(AdminLTEModelView):
    column_hide_backrefs = False
    column_list = ["name", 'mode', 'can_add_admin', 'data_limit', 'max_users', 'online_users', 'comment',]
    form_columns = ["name", 'mode', 'can_add_admin', 'data_limit_GB', 'max_users', 'comment', "uuid", "password"]
    form_extra_fields = {
        'data_limit_GB': FloatField(_('Data Limit (GB)'), default=0,
                                   description=_('Zero means unlimited traffic for this admin.')),
    }
    list_template = 'admins_list.html'
    # column_editable_list = ['name']
    # edit_modal = True
    # form_overrides = {'work_with': Select2Field}

    form_overrides = {
        'mode': AdminModeField,
        'parent_admin': SubAdminsField
    }
    column_labels = {
        "Actions": _("actions"),
        "UserLinks": _("user.user_links"),
        "name": _("user.name"),
        "mode": _("Mode"),
        "uuid": _("user.UUID"),
        "comment": _("Note"),
        'data_limit': _("Data Limit"),
        'data_limit_GB': _("Data Limit (GB)"),
        'max_users': _('Max Users'),
        "password":_("user.password.title"),
        "online_users": _("Online Users"),
        'can_add_admin': _("Can add sub admin")

    }
    form_args = {
        'uuid': {
            'validators': [Regexp(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', message=__("Should be a valid uuid"))]
            #     'label': 'First Name',
            #     'validators': [required()]
        }}

    column_descriptions = dict(
        comment=_("Add some text that is only visible to super_admin."),
        mode=_("admin.define_mode"),
    )
    # create_modal = True
    can_export = False

    # column_list = ["domain",'sub_link_only', "mode","alias", "domain_ip", "cdn_ip"]
    # column_editable_list=["domain"]
    # column_filters=["domain","mode"]

    column_searchable_list = ["name", "uuid"]

    # form_columns=['domain','sub_link_only','alias','mode','cdn_ip','show_domains']

    def _ul_formatter(view, context, model, name):

        return Markup(" ".join([hiddify.get_html_user_link(model, d) for d in Domain.get_domains()]))

    @property
    def can_create(self):
        return ws_perm_can('admin_add')

    @property
    def can_edit(self):
        return ws_perm_can('admin_edit')

    @property
    def can_delete(self):
        return ws_perm_can('admin_delete')

    def _name_formatter(view, context, model, name):

        d = request.host
        if d:

            href = hiddify.get_account_panel_link(model, d) + f'#{hutils.encode.url_encode(model.name)}'
            link = f"<a target='_blank' class='share-link' data-copy='{href}' href='{href}'>{model.name} <i class='fa-solid fa-arrow-up-right-from-square'></i></a>"
            if model.parent_admin:
                return Markup(model.parent_admin.name + "&rlm;&lrm; / &rlm;&lrm;" + link)
            return Markup(link)
        else:
            return model.name

    def _online_users_formatter(view, context, model, name):
        last_day = datetime.datetime.now() - datetime.timedelta(days=1)
        u = model.recursive_users_query().filter(User.last_online > last_day).count()
        t = model.recursive_users_query().count()
        # actives=[u for u in model.recursive_users_query().all() if u.is_active]
        # allusers=model.recursive_users_query().count()
        # onlines=[p for p in  users  if p.last_online and p.last_online>last_day]
        # return Markup(f"<a class='btn btn-xs btn-default' href='{hurl_for('flask.user.index_view',admin_id=model.id)}'> {_('Online')}: {onlines}</a>")
        rate = round(u * 100 / (t + 0.000001))
        state = "danger" if u >= t else ('warning' if rate > 80 else 'success')
        color = "#ff7e7e" if u >= t else ('#ffc107' if rate > 80 else '#9ee150')
        return Markup(f"""
        <div class="progress progress-lg position-relative" style="min-width: 100px;">
          <div class="progress-bar progress-bar-striped" role="progressbar" style="width: {rate}%;background-color: {color};" aria-valuenow="{rate}" aria-valuemin="0" aria-valuemax="100"></div>
              <span class='badge position-absolute' style="left:auto;right:auto;width: 100%;font-size:1em">{u} {_('user.home.usage.from')} {t}</span>

        </div>
        """)

    def _max_users_formatter(view, context, model, name):
        u = model.recursive_users_query().count()
        if model.mode == AdminMode.super_admin:
            return f"{u} / ∞"
        t = model.max_users
        rate = round(u * 100 / (t + 0.000001))
        state = "danger" if u >= t else ('warning' if rate > 80 else 'success')
        color = "#ff7e7e" if u >= t else ('#ffc107' if rate > 80 else '#9ee150')
        return Markup(f"""
        <div class="progress progress-lg position-relative" style="min-width: 100px;">
          <div class="progress-bar progress-bar-striped" role="progressbar" style="width: {rate}%;background-color: {color};" aria-valuenow="{rate}" aria-valuemin="0" aria-valuemax="100"></div>
              <span class='badge position-absolute' style="left:auto;right:auto;width: 100%;font-size:1em">{u} {_('user.home.usage.from')} {t}</span>

        </div>
        """)

    column_formatters = {
        'name': _name_formatter,
        'online_users': _online_users_formatter,
        'max_users': _max_users_formatter,
        'UserLinks': _ul_formatter

    }

    def search_placeholder(self):
        return f"{_('search')} {_('user.UUID')} {_('user.name')}"

    # @login_required(roles={Role.super_admin, Role.admin, Role.custom})
    def is_accessible(self):
        if login_required(roles={Role.super_admin, Role.admin, Role.agent, Role.custom})(lambda: True)() != True:
            return False
        return True

    def get_query(self):
        # Get the base query
        query = super().get_query()

        admin_ids = g.account.recursive_sub_admins_ids()
        query = query.filter(AdminUser.id.in_(admin_ids))

        return query

    # Override get_count_query() to include the filter condition in the count query
    def get_count_query(self):
        # Get the base count query
        query = super().get_count_query()

        admin_ids = g.account.recursive_sub_admins_ids()
        query = query.filter(AdminUser.id.in_(admin_ids))

        return query

    def on_model_change(self, form, model, is_created):

        # if model.id==1:
        #     model.parent_admin_id=0
        #     model.parent_admin=None
        # else:
        #     model.parent_admin_id=1
        #     model.parent_admin=AdminUser.query.filter(AdminUser.id==1).first()
        
        if model.id != 1 and model.parent_admin is None:
            model.parent_admin_id = g.account.id
            model.parent_admin = g.account

        if g.account.mode != AdminMode.super_admin and model.mode == AdminMode.super_admin:
            raise ValidationError("Sub-Admin can not have more power!!!!")
        if g.account.mode == AdminMode.agent and model.mode != AdminMode.agent:
            raise ValidationError("Sub-Admin can not have more power!!!!")
        
        if not model.password and not is_created:
            model.password=AdminUser.by_id(model.id).password

        # the quota arrives in gigabytes and is stored in bytes
        if hasattr(form, 'data_limit_GB'):
            try:
                model.data_limit_GB = float(form.data_limit_GB.data or 0)
            except (TypeError, ValueError):
                model.data_limit = 0


    def get_list(self, page, sort_column, sort_desc, search, filters, page_size=50, *args, **kwargs):
        """Honour the toolbar filters and ordering, then page over the result."""
        f = ws_admin_filter_args(request.args)
        if ws_admin_has_custom_list(f):
            query = self.get_query()
            if search:
                from sqlalchemy import or_
                query = query.filter(or_(self.model.name.contains(search),
                                         self.model.uuid == search))
            rows = [m for m in query.all() if ws_admin_keep(m, f)]
            count = len(rows)
            rows = ws_admin_sort(rows, f)
            return count, ws_admin_page_slice(rows, page, page_size)
        return super().get_list(page, sort_column, sort_desc, search=search,
                                filters=filters, page_size=page_size, *args, **kwargs)

    def ws_admin_row(self, model):
        """Everything the list template shows for one admin, already computed."""
        mode = ws_admin_mode_key(model)
        name = (model.name or '').strip()
        used = ws_admin_used_bytes(model)
        users = ws_admin_users_count(model)
        total_users = int(model.max_users or 0)
        unlimited_users = mode == 'super_admin' or total_users <= 0
        unlimited_data = bool(model.is_data_unlimited)
        limit = int(model.data_limit or 0)
        row = {
            'id': model.id,
            'name': name or __('Admin %(id)s', id=model.id),
            'uuid': model.uuid,
            'mode': mode,
            'mode_label': ws_admin_mode_labels().get(mode, ''),
            'can_add_admin': bool(model.can_add_admin) or mode == 'super_admin',
            'can_add_locked': mode == 'super_admin',
            'perms': ','.join(model.ws_perm_list()),
            'comment': (model.comment or '').strip(),
            'parent': (model.parent_admin.name or '').strip() if model.parent_admin else '',
            'is_you': bool(getattr(g, 'account', None)) and g.account.id == model.id,
            'sub_admins': len(getattr(model, 'sub_admins', []) or []),
            'used': used,
            'used_gb': round(used / WS_ONE_GIG, 2),
            'limit': limit,
            'limit_gb': round(limit / WS_ONE_GIG, 2),
            'data_unlimited': unlimited_data,
            'data_pct': 0.0 if unlimited_data else float(model.data_usage_percent()),
            'data_left_gb': None if unlimited_data else round(max(0, limit - used) / WS_ONE_GIG, 2),
            'data_full': (not unlimited_data) and not model.can_have_more_data(),
            'users': users,
            'max_users': 0 if unlimited_users else total_users,
            'users_unlimited': unlimited_users,
            'users_pct': 0.0 if unlimited_users else min(100.0, round(users * 100.0 / total_users, 1)),
            'online': ws_admin_online_count(model),
            'avatar': (sum(ord(c) for c in (name or str(model.id))) % 12),
            'initial': (name[:1].upper() if name else '#'),
            'link': '',
            'links': [],
            'created': '',
            'created_ts': 0,
        }
        row.update(ws_admin_extra(model))
        made = getattr(model, 'created_at', None)
        if made is not None and getattr(made, 'year', 0) > 1900:
            row['created'] = made.strftime('%Y-%m-%d %H:%M:%S')
            row['created_ts'] = int(made.timestamp())
        row['links'] = ws_admin_links(model)
        try:
            host = request.host
            if host:
                row['link'] = hiddify.get_account_panel_link(model, host) + '#' + hutils.encode.url_encode(name)
        except BaseException:
            row['link'] = ''
        return row

    def ws_admin_stats(self):
        """The three cards above the table, measured over every visible admin."""
        stats = {'total': 0, 'by_mode': {'super_admin': 0, 'admin': 0, 'agent': 0},
                 'users': 0, 'max_users': 0, 'users_pct': 0.0, 'users_left': 0,
                 'users_unlimited': False, 'online': 0, 'used_gb': 0.0}
        try:
            admins = self.get_query().all()
        except BaseException:
            return stats
        used = 0
        for m in admins:
            stats['total'] += 1
            key = ws_admin_mode_key(m)
            stats['by_mode'][key] = stats['by_mode'].get(key, 0) + 1
            if key == 'super_admin' or int(m.max_users or 0) <= 0:
                stats['users_unlimited'] = True
            else:
                stats['max_users'] += int(m.max_users or 0)
            used += ws_admin_used_bytes(m)
        account = getattr(g, 'account', None)
        if account is not None:
            stats['users'] = ws_admin_users_count(account)
            stats['online'] = ws_admin_online_count(account)
        stats['used_gb'] = round(used / WS_ONE_GIG, 2)
        if not stats['users_unlimited'] and stats['max_users'] > 0:
            stats['users_pct'] = min(100.0, round(stats['users'] * 100.0 / stats['max_users'], 1))
            stats['users_left'] = max(0, stats['max_users'] - stats['users'])
        return stats

    def render(self, template, **kwargs):
        kwargs['ws_list_filters'] = ws_admin_filter_args(request.args)
        kwargs['ws_admin_row'] = self.ws_admin_row
        kwargs['ws_admin_stats'] = self.ws_admin_stats
        kwargs['ws_admin_modes'] = ws_admin_mode_labels()
        kwargs['ws_perm_catalog'] = ws_perm_catalog()
        return super().render(template, **kwargs)

    # ------------------------------------------------------------------
    # Endpoints used by the themed admins page
    # ------------------------------------------------------------------
    def ws_can_touch(self, model=None):
        """Only admins inside my own tree may be changed, and never upward."""
        account = getattr(g, 'account', None)
        if account is None:
            return False
        if model is None:
            return bool(ws_perm_can('admin_add'))
        if not ws_perm_can('admin_edit'):
            return False
        try:
            return model.id in account.recursive_sub_admins_ids()
        except BaseException:
            return False

    def ws_allowed_mode(self, wanted):
        """Nobody may hand out more power than they hold themselves."""
        account = getattr(g, 'account', None)
        mine = getattr(account, 'mode', None)
        try:
            wanted_mode = AdminMode(wanted)
        except BaseException:
            wanted_mode = AdminMode.agent
        if mine == AdminMode.super_admin:
            return wanted_mode
        if mine == AdminMode.admin:
            # a plain admin may only hand out the two lower modes, never
            # the owner seat and never a hand made account
            if wanted_mode in (AdminMode.admin, AdminMode.agent):
                return wanted_mode
            return AdminMode.agent
        return AdminMode.agent

    @expose('/ws_save_admin', methods=['POST'])
    def ws_save_admin(self):
        """Create a new admin, or update an existing one, from the page modal."""
        back = redirect(self.get_url('.index_view'))
        raw_id = (request.form.get('id') or '').strip()
        editing = None
        if raw_id:
            editing = AdminUser.query.filter(AdminUser.id == raw_id).first()
            if editing is None or not self.ws_can_touch(editing):
                hutils.flask.flash(__('You are not allowed to change this admin.'), 'danger')
                return back
        elif not self.ws_can_touch():
            hutils.flask.flash(__('You are not allowed to add an admin.'), 'danger')
            return back

        name = (request.form.get('name') or '').strip()
        if not name:
            hutils.flask.flash(__('Please write a name for the admin.'), 'danger')
            return back

        def number(key, fallback=0.0):
            try:
                return float((request.form.get(key) or '').strip() or fallback)
            except (TypeError, ValueError):
                return float(fallback)

        comment = (request.form.get('comment') or '').strip()
        data_limit_GB = max(0.0, number('data_limit_GB', 0))
        max_users = int(max(0, number('max_users', 0)))
        can_add_admin = (request.form.get('can_add_admin') or '') in ('on', '1', 'true', 'yes', 'True')
        password = (request.form.get('password') or '').strip()
        given_uuid = (request.form.get('uuid') or '').strip()
        mode = self.ws_allowed_mode(request.form.get('mode') or AdminMode.agent.value)
        if mode == AdminMode.super_admin:
            can_add_admin = True  # the owner may always add admins
        wanted_perms = request.form.getlist('perm')
        if mode == AdminMode.custom:
            # the hand made mode carries its own list, and the sub admin
            # switch follows it so the two can never disagree
            can_add_admin = 'admin_add' in wanted_perms

        account = getattr(g, 'account', None)
        may_set_power = getattr(account, 'mode', None) == AdminMode.super_admin
        try:
            if editing is None:
                if given_uuid and not hutils.auth.is_uuid_valid(given_uuid):
                    hutils.flask.flash(__('Should be a valid uuid'), 'danger')
                    return back
                model = AdminUser(
                    uuid=given_uuid or str(uuid_mod.uuid4()),
                    name=name,
                    mode=mode,
                    can_add_admin=can_add_admin,
                    max_users=max_users,
                    comment=comment,
                    parent_admin_id=account.id if account else 1,
                )
                model.data_limit_GB = data_limit_GB
                if mode == AdminMode.custom:
                    model.ws_set_perms(wanted_perms)
                if password:
                    model.password = password
                db.session.add(model)
                db.session.commit()
                hutils.flask.flash(__('Admin %(name)s was created.', name=name), 'success')
            else:
                model = editing
                model.name = name
                model.comment = comment
                if given_uuid and given_uuid != model.uuid:
                    if not hutils.auth.is_uuid_valid(given_uuid):
                        hutils.flask.flash(__('Should be a valid uuid'), 'danger')
                        return back
                    taken = AdminUser.query.filter(AdminUser.uuid == given_uuid,
                                                  AdminUser.id != model.id).first()
                    if taken is not None:
                        hutils.flask.flash(__('Another admin already uses this uuid.'), 'danger')
                        return back
                    model.uuid = given_uuid
                is_self = bool(account) and account.id == model.id
                model.max_users = max_users
                model.data_limit_GB = data_limit_GB
                if may_set_power and not is_self:
                    # nobody may take their own powers away and lock the panel
                    model.mode = mode
                    model.can_add_admin = can_add_admin
                    if mode == AdminMode.custom:
                        model.ws_set_perms(wanted_perms)
                    else:
                        model.permissions = None
                if password:
                    model.password = password
                db.session.commit()
                hutils.flask.flash(__('Admin %(name)s was saved.', name=name), 'success')
            if hutils.node.is_parent():
                hutils.node.run_node_op_in_bg(hutils.node.parent.request_childs_to_sync)
        except BaseException as e:
            db.session.rollback()
            hutils.flask.flash(__('Could not save the admin: %(error)s', error=str(e)), 'danger')
        return back

    @expose('/save_note', methods=['POST'])
    def save_note(self):
        """Silent auto-save for the note field inside the details panel."""
        try:
            raw_id = (request.form.get('admin_id') or '').strip()
            model = AdminUser.query.filter(AdminUser.id == raw_id).first()
            if model is None or not self.ws_can_touch(model):
                return jsonify({'ok': False}), 403
            model.comment = (request.form.get('note') or '').strip()[:512]
            db.session.commit()
            return jsonify({'ok': True})
        except BaseException:
            db.session.rollback()
            return jsonify({'ok': False}), 500

    def on_model_delete(self, model):
        model.remove()

    def on_form_prefill(self, form, id=None):
        
        form.password.data=""
        # show the quota in gigabytes, the way the page displays it
        try:
            if hasattr(form, 'data_limit_GB'):
                form.data_limit_GB.data = round(float(form._obj.data_limit_GB or 0), 2)
        except BaseException:
            pass
        if g.account.mode != AdminMode.super_admin:
            del form.mode
            del form.can_add_admin

        if g.account.id == form._obj.id:
            del form.max_users
            del form.data_limit_GB
            del form.comment
            del form.can_add_admin
            if getattr(form, 'mode'):
                del form.mode
        elif form._obj.mode == AdminMode.super_admin:
            del form.max_users
            del form.data_limit_GB
            del form.can_add_admin

    def after_model_change(self, form, model, is_created):
        if hutils.node.is_parent():
            hutils.node.run_node_op_in_bg(hutils.node.parent.request_childs_to_sync)

    def after_model_delete(self, model):
        if hutils.node.is_parent():
            hutils.node.run_node_op_in_bg(hutils.node.parent.request_childs_to_sync)
