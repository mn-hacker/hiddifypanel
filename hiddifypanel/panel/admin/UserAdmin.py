import re
from flask_admin.actions import action
from flask_admin import expose
import datetime
import uuid
from apiflask import abort
from flask_bootstrap import SwitchField, BooleanField
from flask_babel import gettext as __
from .adminlte import AdminLTEModelView
from wtforms.validators import NumberRange
from flask_babel import lazy_gettext as _
from flask import g, request, redirect, jsonify, session
from markupsafe import Markup
from sqlalchemy import desc, func
from flask_admin.contrib.sqla import form, filters as sqla_filters, tools
from hiddifypanel.hutils.flask import hurl_for
from wtforms.validators import Regexp, ValidationError
from flask import current_app

import hiddifypanel
from hiddifypanel.models import *
from hiddifypanel.drivers import user_driver
from hiddifypanel.panel import hiddify, custom_widgets
from hiddifypanel.auth import login_required
from hiddifypanel import hutils


class UserAdmin(AdminLTEModelView):
    column_default_sort = ('id', False)  # Sort by username in ascending order

    column_sortable_list = ["is_active", "name", "current_usage", 'mode', "remaining_days", "comment", 'last_online', "uuid"]
    column_searchable_list = ["uuid", "name"]
    column_list = ["is_active", "name", "UserLinks", "current_usage", "remaining_days", "comment", "last_online", "mode", "admin", "Logs", "uuid"]
    column_editable_list = ["comment", "name", "uuid"]
    form_extra_fields = {
        'reset_days': SwitchField(_("Reset package days"), default=False),
        'reset_usage': SwitchField(_("Reset package usage"), default=False),
        # 'disable_user': SwitchField(_("Disable User"))
    }
    list_template = 'users_list.html'
# "max_ips",
    form_columns = ["name","comment", "usage_limit", "reset_usage", "hwid_limit", "hwid_disabled", "package_days", "reset_days", "mode", "uuid", "enable"]
    # form_excluded_columns = ['current_usage', 'monthly', 'telegram_id', 'last_online', 'expiry_time', 'last_reset_time', 'current_usage_GB',
    #  'start_date', 'added_by', 'admin', 'details', 'max_ips', 'ed25519_private_key', 'ed25519_public_key', 'username', 'password']
    page_size = 20
    # edit_modal=True
    # create_modal=True
    # column_display_pk = True
    # can_export = True
    # form_overrides = dict(monthly=SwitchField)
    form_overrides = {
        'start_date': custom_widgets.DaysLeftField,
        'mode': custom_widgets.EnumSelectField,
        'usage_limit': custom_widgets.UsageField
    }

    # form_overrides = dict(expiry_time=custom_widgets.DaysLeftField,last_reset_time=custom_widgets.LastResetField)
    form_widget_args = {
        'current_usage_GB': {'min': '0'},
        'usage_limit_GB': {'min': '0'},
        'current_usage': {'min': '0'},
        'usage_limit': {'min': '0'},

    }
    form_args = {
        'hwid_limit': {
            'validators': [NumberRange(min=0, max=10000)],
            'label': _('Device limit'),
            'description': _('0 = use global default; >0 = max devices for this user')
        },
        'hwid_disabled': {
            'label': _('Bypass Device Limit'),
            'description': _('If enabled, this user is exempt from device limit restrictions.')
        },
        'mode': {'enum': UserMode},
        'uuid': {
            'validators': [Regexp(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', message=__("Should be a valid uuid"))]
            #     'label': 'First Name',
            #     'validators': [required()]
        },
        
        # ,
        # 'expiry_time':{
        # "":'%Y-%m-%d'
        # }
    }
    # column_labels={'uuid':_("user.UUID")}
    # column_filters=["usage_limit_GB","current_usage_GB",'admin','is_active']

    column_labels = {
        "Actions": _("actions"),
        "name": _("user.name"),
        "UserLinks": _("user.user_links"),
        "usage_limit": _("user.usage_limit_GB"),
        "monthly": _("Reset every month"),
        "mode": _("Mode"),
        "admin": _("Added by"),
        "current_usage": _("user.current_usage_GB"),
        "start_date": _("Start Date"),
        "remaining_days": _("user.expiry_time"),
        "last_reset_time": _("user.last_reset_time"),
        "uuid": _("user.UUID"),
        "comment": _("Note"),
        'last_online': _('Last Online'),
        "package_days": _('Package Days'),
        "hwid_limit": _('Device limit'),
        "hwid_disabled": _('Bypass Device Limit'),
        "enable": _('Enable'),
        "is_active": _('Active'),
        "Logs": _('Logs'),
    }
    
    can_set_page_size = True

    def search_placeholder(self):
        return f"{_('search')} {_('user.UUID')} {_('user.name')}"
    # def get_column_name(self,field):
    #         return "x"
    #  return column_labels[field]
    column_descriptions = dict(
        # name=_'just for remembering',
        # usage_limit_GB="in GB",
        # current_usage_GB="in GB"
        comment=_("Add some text that is only visible to you."),
        mode=_("user.define_mode"),
        last_reset_time=_("If monthly is enabled, the usage will be reset after 30 days from this date."),
        start_date=_("From when the user package will be started? Empty for start from first connection"),
        package_days=_("How many days this package should be available?")
    )
    # column_editable_list=["usage_limit_GB","current_usage_GB","expiry_time"]
    # form_extra_fields={
    #     'uuid': {'label_name':"D"}

    #     }

    # can_edit = False
    # def on_model_change(self, form, model, is_created):
    #     model.password = generate_password_hash(model.password)
    def _enable_formatter(view, context, model, name):
        if model.is_active:
            link = '<i class="fa-solid fa-circle-check text-success"></i> '
        elif len(model.devices):
            link = f'<i class="fa-solid fa-users-slash text-danger" title="{_("Too many Connected IPs")}"></i>'
        else:
            link = '<i class="fa-solid fa-circle-xmark text-danger"></i> '

        if hconfig(ConfigEnum.telegram_bot_token):
            if model.telegram_id:
                link += f'<button class="btn hbtn bg-h-blue btn-xs " onclick="show_send_message({model.id})" ><i class="fa-solid fa-paper-plane"></i></button> '
            else:
                link += f'<button class="btn hbtn bg-h-grey btn-xs disabled"><i class="fa-solid fa-paper-plane"></i></button> '

        return Markup(link)

    # def _name_formatter(view, context, model, name):
    #     # print("model.telegram_id",model.telegram_id)

    def _ul_formatter(view, context, model, name):
        href = f'{hiddify.get_account_panel_link(model, request.host, is_https=True)}#{hutils.encode.unicode_slug(model.name)}'

        link = f"""<a target='_blank' class='share-link btn btn-xs btn-primary' data-copy='{href}' href='{href}'>
        <i class='fa-solid fa-arrow-up-right-from-square'></i>
        {_("Current Domain")} </a>"""

        domains = [d for d in Domain.get_domains() if d.domain != request.host]
        return Markup(link + " ".join([hiddify.get_html_user_link(model, d) for d in domains]))

    # def _usage_formatter(view, context, model, name):
    #     return round(model.current_usage_GB,3)

    def _usage_formatter(view, context, model, name):
        u = round(model.current_usage_GB, 3)
        t = max(round(model.usage_limit_GB, 3), 0.001)  # Prevent division by zero
        rate = min(round(u * 100 / t), 100)  # Cap at 100%
        state = "danger" if u >= t else ('warning' if rate > 80 else 'success')
        color = "#ff7e7e" if u >= t else ('#ffc107' if rate > 80 else '#9ee150')
        return Markup(f"""
        <div class="progress progress-lg position-relative" style="min-width: 100px;">
          <div class="progress-bar progress-bar-striped" role="progressbar" style="width: {rate}%;background-color: {color};" aria-valuenow="{rate}" aria-valuemin="0" aria-valuemax="100"></div>
              <span class='badge position-absolute' style="left:auto;right:auto;width: 100%;font-size:1em">{u} {_('user.home.usage.from')} {t} GB</span>

        </div>
        """)

    def _expire_formatter(view, context, model: User, name):
        remaining = model.remaining_days

        diff = datetime.timedelta(days=remaining)

        state = 'success' if diff.days > 7 else ('warning' if diff.days > 0 else 'danger')
        formated = hutils.convert.format_timedelta(diff)
        return Markup(f"<span class='badge badge-{state}'>{'*' if not model.start_date else ''} {formated} </span>")
        # return Markup(f"<span class='badge ltr badge-}'>{days}</span> "+_('days'))

    def _admin_formatter(view, context, model, name):
        return Markup(f"<a href='{hurl_for('flask.user.index_view',admin_id=model.added_by)}' class='btn btn-xs btn-default'>{model.admin.name}</a>")

    def _online_formatter(view, context, model, name):
        if not model.last_online:
            return Markup("-")
        diff = model.last_online - datetime.datetime.now()

        if diff.days < -1000:
            return Markup("-")
        if diff.total_seconds() > -60 * 2:
            return Markup(f"<span class='badge badge-success'>{_('Online')}</span>")
        state = "danger" if diff.days < -3 else ("success" if diff.days >= -1 else "warning")
        return Markup(f"<span class='badge badge-{state}'>{hutils.convert.format_timedelta(diff,granularity='min')}</span>")

        # return Markup(f"<span class='badge ltr badge-{'success' if days>7 else ('warning' if days>0 else 'danger') }'>{days}</span> "+_('days'))

    column_formatters = {
        # 'name': _name_formatter,
        'UserLinks': _ul_formatter,
        # 'uuid': _uuid_formatter,
        'current_usage': _usage_formatter,
        "remaining_days": _expire_formatter,
        'last_online': _online_formatter,
        'admin': _admin_formatter,
        "is_active": _enable_formatter,
        'Logs': lambda v, c, m, p: Markup(
            f'<a href="{hurl_for("admin.MonitoringAdmin:user_logs", uuid=m.uuid)}" '
            f'class="btn btn-sm btn-info" title="{_("View Logs")}">'
            f'<i class="fa-solid fa-file-lines"></i> Log</a>'
        )
    }

    def on_model_delete(self, model):
        if len(User.query.all()) <= 1:
            raise ValidationError(f"at least one user should exist")
        user_driver.remove_client(model)
        # hutils.flask.flash_config_success()

    # ---- watashi: notifications that name what this panel manages -------
    def _ws_flash_mark(self):
        """How many messages were already queued before an operation ran."""
        try:
            return len(session.get('_flashes', []) or [])
        except Exception:
            return 0

    def _ws_flash_rewrite(self, mark, success_message):
        """Replace the generic messages queued by the admin library after
        `mark` with wording that names the user. Failure messages are kept
        untouched because they carry the real reason."""
        try:
            queued = list(session.get('_flashes', []) or [])
        except Exception:
            return
        if len(queued) <= mark:
            return
        rebuilt = list(queued[:mark])
        for item in queued[mark:]:
            try:
                category, message = item
            except Exception:
                rebuilt.append(item)
                continue
            kind = str(category or 'message').lower()
            if 'error' in kind or 'danger' in kind or 'warning' in kind:
                rebuilt.append((category, message))
            else:
                rebuilt.append((category, str(success_message)))
        try:
            session['_flashes'] = rebuilt
            session.modified = True
        except Exception:
            pass

    @expose('/delete/', methods=['POST'])
    def delete_view(self):
        name = ''
        try:
            rowid = request.form.get('id') or request.form.get('rowid') or ''
            if rowid:
                target = self.get_one(rowid)
                if target is not None:
                    name = (target.name or '').strip()
        except Exception:
            name = ''
        mark = self._ws_flash_mark()
        response = super().delete_view()
        if name:
            message = _('User %(name)s was successfully deleted.', name=name)
        else:
            message = _('The user was successfully deleted.')
        self._ws_flash_rewrite(mark, message)
        return response

    def is_accessible(self):
        if login_required(roles={Role.super_admin, Role.admin, Role.agent})(lambda: True)() != True:
            return False
        return True

    def on_form_prefill(self, form, id=None):
        # print("================",form._obj.start_date)
        if form._obj is None:
            return

        if id is None or form._obj.start_date is None or form._obj.current_usage==0:
            msg = _("Package not started yet.")
            # form.reset['class']="d-none"
        if form._obj.start_date is None:
            if hasattr(form, 'reset_days'):
                delattr(form, 'reset_days')
        else:
            remaining = form._obj.remaining_days
            relative_remaining = hutils.convert.format_timedelta(datetime.timedelta(days=remaining))
            msg = _("Remaining about %(relative)s, exactly %(days)s days", relative=relative_remaining, days=remaining)
            form.reset_days.label.text += f" ({msg})"
            form.reset_days.data = False

        # Handle reset_usage field
        if form._obj.current_usage == 0:
            if hasattr(form, 'reset_usage'):
                delattr(form, 'reset_usage')
        else:
            usr_usage = f" ({_('user.home.usage.title')} {round(form._obj.current_usage_GB,3)}GB)"
            if hasattr(form, 'reset_usage'):
                form.reset_usage.label.text += usr_usage
                form.reset_usage.data = False
            
            if hasattr(form, 'usage_limit'):
                form.usage_limit.label.text += usr_usage

        # Handle package days info
        if form._obj.start_date and hasattr(form, 'package_days'):
            started = form._obj.start_date - datetime.date.today()
            msg = _("Started from %(relative)s", relative=hutils.convert.format_timedelta(started))
            form.package_days.label.text += f" ({msg})"
            if started.days <= 0:
                exact_start = _("Started %(days)s days ago", days=-started.days)
            else:
                exact_start = _("Will Start in %(days)s days", days=started.days)
            form.package_days.description += f" ({exact_start})"

    def get_edit_form(self):
        form = super().get_edit_form()
        # print(form.__dict__)
        # user=User.query.filter(User.uuid==form.uuid).first()
        # if user and user.start_date:
        #     form.reset = SwitchField("Reset")
        return form

    def on_model_change(self, form, model, is_created):
        # Validate hwid_limit (0 = use global default)
        try:
            model.hwid_limit = max(0, min(int(model.hwid_limit or 0), 10000))
        except (ValueError, TypeError):
            model.hwid_limit = 0
            
        # Show donation message
        if len(User.query.all()) % 4 == 0:
            hutils.flask.flash(('<div id="show-modal-donation"></div>'), ' d-none')
            
        # Validate UUID
        if not re.match("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", model.uuid):
            raise ValidationError('Invalid UUID e.g.,' + str(uuid.uuid4()))
            
        # Handle reset flags
        if hasattr(form, 'reset_usage') and form.reset_usage.data:
            model.current_usage_GB = 0
            
        if hasattr(form, 'reset_days') and form.reset_days.data:
            model.start_date = None
            
        # Validate package days
        try:
            model.package_days = min(int(model.package_days), 10000)
        except (ValueError, TypeError):
            model.package_days = 10000
            
        # Handle user ownership
        old_user = User.by_id(model.id)
        if not model.added_by or model.added_by == 1:
            model.added_by = g.account.id
            
        # Validate user limits
        if not g.account.can_have_more_users():
            raise ValidationError(_('You have too much users! You can have only %(active)s active users and %(total)s users',
                                  active=g.account.max_active_users, total=g.account.max_users))
                                  
        # Handle UUID changes
        if old_user and old_user.uuid != model.uuid:
            user_driver.remove_client(old_user)

        # generated automatically
        # if not model.ed25519_private_key:
        #     priv, publ = hutils.crypto.get_ed25519_private_public_pair()
        #     model.ed25519_private_key = priv
        #     model.ed25519_public_key = publ
        # if not model.wg_pk:
        #     model.wg_pk, model.wg_pub, model.wg_psk = hutils.crypto.get_wg_private_public_psk_pair()

        # model.expiry_time=datetime.date.today()+datetime.timedelta(days=model.expiry_time)
        # if model.current_usage_GB < model.usage_limit_GB:
        #     xray_api.add_client(model.uuid)
        # else:
        #     xray_api.remove_client(model.uuid)
        # hutils.flask.flash_config_success()

    def after_model_change(self, form, model, is_created):
        if hconfig(ConfigEnum.first_setup):
            set_hconfig(ConfigEnum.first_setup, False)
        user = User.query.filter(User.uuid == model.uuid).first() or abort(404)
        if user.is_active:
            user_driver.add_client(model)
        else:
            user_driver.remove_client(model)
        hiddify.quick_apply_users()

        if hutils.node.is_parent():
            hutils.node.run_node_op_in_bg(hutils.node.parent.request_childs_to_sync)

    def after_model_delete(self, model):
        user_driver.remove_client(model)
        hiddify.quick_apply_users()

        if hutils.node.is_parent():
            hutils.node.run_node_op_in_bg(hutils.node.parent.request_childs_to_sync)

    def get_list(self, page, sort_column, sort_desc, search, filters, page_size=50, *args, **kwargs):
        res = None
        self._auto_joins = {}
        # print('aaa',args, kwargs)
        if sort_column in ['remaining_days', 'is_active']:
            query = self.get_query()

            if search:
                from sqlalchemy import or_
                search_conditions = or_(self.model.name.contains(search), self.model.uuid == search)
                query = query.filter(search_conditions)

            data = query.all()
            count = len(data)
            data = sorted(data, key=lambda p: getattr(p, sort_column), reverse=sort_desc)

            # Applying pagination
            start = page * page_size
            end = start + page_size
            data = data[start: end]
            res = count, data
        else:
            res = super().get_list(page, sort_column, sort_desc, search=search, filters=filters, page_size=page_size, *args, **kwargs)
        return res

        # Override the default get_list method to use the custom sort function
        # query = self.session.query(self.model)
        # if self._sortable_columns:
        #     # print("sor",self._sortable_columns['remaining_days'])
        #     for column, direction in self._get_default_order():
        #         # if column == 'remaining_days':
        #         #     # Use the custom sort function for 'remaining_days'
        #         #     query = query.order_by(self.model.remaining_days.asc() if direction == 'asc' else self.model.remaining_days.desc())
        #         # else:
        #         # Use the default sort function for other columns
        #         query = query.order_by(getattr(self.model, column).asc() if direction == 'asc' else getattr(self.model, column).desc())
        # count = query.count()
        # data = query.all()
        # return count, data

        # Override get_query() to filter rows based on a specific condition

    def get_query(self):
        # Get the base query
        query = super().get_query()

        admin_id = int(request.args.get("admin_id") or g.account.id)
        if admin_id not in g.account.recursive_sub_admins_ids():
            abort(403)
        admin = AdminUser.query.filter(AdminUser.id == admin_id).first()
        if not admin:
            abort(403)

        query = query.filter(User.added_by.in_(admin.recursive_sub_admins_ids()))

        return query

    # Override get_count_query() to include the filter condition in the count query
    def get_count_query(self):
        # Get the base count query

        # query = self.session.query(func.count(User.id)).

        query = super().get_count_query()

        admin_id = int(request.args.get("admin_id") or g.account.id)
        if admin_id not in g.account.recursive_sub_admins_ids():
            abort(403)
        admin = AdminUser.query.filter(AdminUser.id == admin_id).first()
        if not admin:
            abort(403)

        query = query.filter(User.added_by.in_(admin.recursive_sub_admins_ids()))

        # admin_id=int(request.args.get("admin_id") or g.account.id)
        # if admin_id not in g.account.recursive_sub_admins_ids():
        #     abort(403)
        # admin=AdminUser.query.filter(AdminUser.id==admin_id).first()
        # if not admin:
        #     abort(403)

        return query


    @expose('/bulk_create', methods=['POST'])
    def bulk_create(self):
        try:
            count = int(request.form.get('count', 1))
            mode = UserMode[request.form.get('mode', 'no_reset')]
            usage_limit_GB = float(request.form.get('usage_limit_GB', 0))
            package_days = int(request.form.get('package_days', 0))
            comment = request.form.get('comment', '')
            name_prefix = request.form.get('name_prefix', 'User')

            users = []
            for i in range(count):
                user = User(
                    name=f"{name_prefix}_{uuid.uuid4().hex[:4]}",
                    uuid=str(uuid.uuid4()),
                    mode=mode,
                    usage_limit_GB=usage_limit_GB,
                    package_days=package_days,
                    comment=comment,
                    added_by=g.account.id,
                    start_date=None
                )
                self.session.add(user)
                users.append(user)
            
            self.session.commit()
            self.apply(users)
            hutils.flask.flash(_('%(count)s users were successfully created.', count=count), 'success')
        except Exception as e:
            hutils.flask.flash(_('Error creating users: %(error)s', error=str(e)), 'danger')
        
        return redirect(hurl_for("flask.user.index_view"))

    @expose('/quick_create', methods=['POST'])
    def quick_create(self):
        try:
            if not g.account.can_have_more_users():
                hutils.flask.flash(_('You have too much users!'), 'danger')
                return redirect(hurl_for("flask.user.index_view"))
            name = (request.form.get('name') or '').strip() or f"User_{uuid.uuid4().hex[:4]}"
            comment = request.form.get('comment', '')
            usage_limit_GB = float(request.form.get('usage_limit_GB') or 0)
            hwid_limit = int(request.form.get('hwid_limit') or 0)
            package_days = int(request.form.get('package_days') or 0)
            mode = UserMode[request.form.get('mode') or 'no_reset']
            user_uuid = (request.form.get('uuid') or '').strip() or str(uuid.uuid4())
            enable = (request.form.get('enable') or '') in ('on', 'true', '1', 'True', 'yes')
            user = User(
                name=name,
                uuid=user_uuid,
                mode=mode,
                usage_limit_GB=usage_limit_GB,
                hwid_limit=hwid_limit,
                package_days=package_days,
                comment=comment,
                enable=enable,
                added_by=g.account.id,
                start_date=None,
            )
            self.session.add(user)
            self.session.commit()
            self.apply([user])
            hutils.flask.flash(_('User was successfully created.'), 'success')
        except Exception as e:
            self.session.rollback()
            hutils.flask.flash(_('Error creating user: %(error)s', error=str(e)), 'danger')
        return redirect(hurl_for("flask.user.index_view"))

    @expose('/edit_user', methods=['POST'])
    def edit_user(self):
        try:
            uid = request.form.get('user_id') or ''
            query = tools.get_query_for_ids(self.get_query(), self.model, [uid])
            user = query.first()
            if not user:
                hutils.flask.flash(_('User not found.'), 'danger')
                return redirect(hurl_for("flask.user.index_view"))
            name = (request.form.get('name') or '').strip()
            if name:
                user.name = name
            user.comment = request.form.get('comment') or None
            gb = request.form.get('usage_limit_GB')
            if gb not in (None, ''):
                user.usage_limit_GB = float(gb)
            hw = request.form.get('hwid_limit')
            if hw not in (None, ''):
                user.hwid_limit = int(hw)
            pd = request.form.get('package_days')
            if pd not in (None, ''):
                user.package_days = int(pd)
            mode = request.form.get('mode')
            if mode:
                user.mode = UserMode[mode]
            user_uuid = (request.form.get('uuid') or '').strip()
            if user_uuid:
                user.uuid = user_uuid
            user.enable = (request.form.get('enable') or '') in ('on', 'true', '1', 'True', 'yes')
            if (request.form.get('reset_usage') or '') in ('on', 'true', '1', 'True', 'yes'):
                user.current_usage = 0
            if (request.form.get('reset_days') or '') in ('on', 'true', '1', 'True', 'yes'):
                user.start_date = None
            self.session.commit()
            self.apply([user])
            hutils.flask.flash(_('User was successfully updated.'), 'success')
        except Exception as e:
            self.session.rollback()
            hutils.flask.flash(_('Error updating user: %(error)s', error=str(e)), 'danger')
        return redirect(hurl_for("flask.user.index_view"))

    def ws_user_links(self, user):
        """Every subscription link for this user, one entry per panel domain.

        The domain list is resolved once per request and cached on flask.g,
        otherwise a 50 row page would hit the database 50 times.
        """
        domains = getattr(g, '_ws_link_domains', None)
        if domains is None:
            try:
                domains = Domain.get_domains()
            except Exception:
                domains = []
            g._ws_link_domains = domains

        try:
            host = request.host
        except Exception:
            host = ''

        direct, cdn, seen = [], [], set()
        for d in domains:
            name = (d.domain or '').strip()
            if '*' in name:
                name = name.replace('*', hutils.random.get_random_string(5, 15))
            if not name or name in seen:
                continue
            seen.add(name)
            try:
                link = hiddify.get_account_panel_link(user, name, child_id=d.child_id)
                link += '#' + hutils.encode.unicode_slug(user.name or '')
            except Exception:
                continue
            mode = getattr(d.mode, 'name', str(d.mode or ''))
            is_cdn = mode in ('cdn', 'auto_cdn_ip')
            entry = {
                'label': (d.alias or name),
                'domain': name,
                'link': link,
                'kind': 'cdn' if is_cdn else 'direct',
                'current': name == host,
            }
            (cdn if is_cdn else direct).append(entry)
        return direct + cdn

    def ws_user_protocols(self, user):
        """Protocols the panel has enabled, flagged on/off for this user.

        The panel wide list decides WHAT is listed (so a protocol disabled in
        the panel never shows up here), the per-user list decides which of them
        are on. Resolved once per request and cached on flask.g, otherwise a 50
        row page would repeat the query 50 times.
        """
        proxies = getattr(g, '_ws_panel_proxies', None)
        if proxies is None:
            try:
                proxies = hutils.proxy.get_proxies(Child.current().id, only_enabled=True)
            except Exception:
                proxies = []
            g._ws_panel_proxies = proxies

        disabled = set()
        raw = getattr(user, 'ws_disabled_protos', None)
        if raw:
            disabled = set(x.strip() for x in str(raw).split(',') if x.strip())

        out, seen = [], set()
        for p in proxies:
            name = (p.name or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({'name': name, 'enabled': name not in disabled})
        out.sort(key=lambda x: x['name'].lower())
        return out

    def ws_user_expire(self, user):
        """Expiry information for one row of the list.

        The model has no expiry_time attribute: a package is a length in days
        (package_days) whose clock only starts on start_date. The template used
        to read row.expiry_time, which quietly resolved to undefined, so every
        row printed "Never" no matter what was configured.
        """
        days = user.package_days
        if days is None:
            return {'main': __('Unlimited'), 'sub': '', 'state': 'none'}
        if not user.start_date:
            return {'main': __('Not started'),
                    'sub': __('%(days)s day package', days=days),
                    'state': 'idle'}
        expire = user.start_date + datetime.timedelta(days=days)
        remaining = user.remaining_days
        if remaining < 0:
            sub, state = __('expired %(days)s days ago', days=abs(remaining)), 'over'
        elif remaining == 0:
            sub, state = __('expires today'), 'soon'
        elif remaining <= 7:
            sub, state = __('%(days)s days left', days=remaining), 'soon'
        else:
            sub, state = __('%(days)s days left', days=remaining), 'ok'
        return {'main': expire.strftime('%Y-%m-%d'), 'sub': sub, 'state': state}

    def render(self, template, **kwargs):
        kwargs['ws_user_expire'] = self.ws_user_expire
        kwargs['ws_user_links'] = self.ws_user_links
        kwargs['ws_user_protocols'] = self.ws_user_protocols
        return super().render(template, **kwargs)

    @expose('/save_note', methods=['POST'])
    def save_note(self):
        """Inline auto-save for the Note (comment) field in the user details panel.

        Returns JSON so the details panel can save silently without a page reload.
        The note is cosmetic metadata, so no config re-apply is needed here.
        """
        try:
            uid = request.form.get('user_id') or ''
            query = tools.get_query_for_ids(self.get_query(), self.model, [uid])
            user = query.first()
            if not user:
                return jsonify({'ok': False, 'error': 'User not found.'}), 404
            note = (request.form.get('comment') or '').strip()
            if len(note) > 512:
                note = note[:512]
            user.comment = note or None
            self.session.commit()
            return jsonify({'ok': True, 'comment': user.comment or ''})
        except Exception as e:
            self.session.rollback()
            return jsonify({'ok': False, 'error': str(e)}), 500

    @expose('/save_protocols', methods=['POST'])
    def save_protocols(self):
        """Persist the per-user protocol switches from the details panel.

        Only names the panel itself has enabled are accepted, so a stale page
        can never disable something that no longer exists. Client configs are
        generated per request, so nothing needs re-applying on the nodes.
        """
        try:
            uid = request.form.get('user_id') or ''
            query = tools.get_query_for_ids(self.get_query(), self.model, [uid])
            user = query.first()
            if not user:
                return jsonify({'ok': False, 'error': 'User not found.'}), 404

            valid = set(p['name'] for p in self.ws_user_protocols(user))
            disabled = []
            for name in (request.form.get('disabled') or '').split(','):
                name = name.strip()
                if name and name in valid and name not in disabled:
                    disabled.append(name)

            user.ws_disabled_protos = ','.join(disabled) or None
            self.session.commit()
            return jsonify({'ok': True, 'disabled': disabled, 'active': len(valid) - len(disabled)})
        except Exception as e:
            self.session.rollback()
            return jsonify({'ok': False, 'error': str(e)}), 500

    @expose('/bulk_action', methods=['POST'])
    def bulk_action(self):
        try:
            action_name = request.form.get('action') or ''
            ids = request.form.getlist('rowid')
            if not ids:
                hutils.flask.flash(_('No users were selected.'), 'warning')
                return redirect(hurl_for("flask.user.index_view"))
            query = tools.get_query_for_ids(self.get_query(), self.model, ids)
            if action_name == 'enable':
                count = query.update({'enable': True})
                self.session.commit()
                self.apply(query.all())
            elif action_name == 'disable':
                count = query.update({'enable': False})
                self.session.commit()
                self.apply(query.all())
            elif action_name == 'reset_usage':
                count = query.update({'current_usage': 0})
                self.session.commit()
                self.apply(query.all())
            elif action_name == 'reset_day':
                count = query.update({'start_date': None})
                self.session.commit()
                self.apply(query.all())
            elif action_name == 'delete':
                users = query.all()
                count = len(users)
                for u in users:
                    user_driver.remove_client(u)
                query.delete()
                self.session.commit()
                hiddify.quick_apply_users()
            else:
                hutils.flask.flash(_('Unknown action.'), 'danger')
                return redirect(hurl_for("flask.user.index_view"))
            done = {
                'enable': _('%(count)s users were successfully enabled.', count=count),
                'disable': _('%(count)s users were successfully disabled.', count=count),
                'reset_usage': _('The usage of %(count)s users was successfully reset.', count=count),
                'reset_day': _('The day counter of %(count)s users was successfully reset.', count=count),
                'delete': _('%(count)s users were successfully deleted.', count=count),
            }
            hutils.flask.flash(done.get(action_name) or _('%(count)s users were successfully updated.', count=count), 'success')
        except Exception as e:
            self.session.rollback()
            hutils.flask.flash(_('Error applying action: %(error)s', error=str(e)), 'danger')
        return redirect(hurl_for("flask.user.index_view"))

    @action('disable', 'Disable', 'Are you sure you want to disable selected users?')
    def action_disable(self, ids):
        query = tools.get_query_for_ids(self.get_query(), self.model, ids)
        count = query.update({'enable': False})

        self.session.commit()
        hutils.flask.flash(_('%(count)s users were successfully disabled.', count=count), 'success')
        self.apply(query.all())

    @action('enable', 'Enable', 'Are you sure you want to enable selected users?')
    def action_enable(self, ids):
        query = tools.get_query_for_ids(self.get_query(), self.model, ids)
        count = query.update({'enable': True})

        self.session.commit()
        hutils.flask.flash(_('%(count)s users were successfully enabled.', count=count), 'success')
        self.apply(query.all())
    
    @action('delete', 'Delete', 'Are you sure you want to delete selected users?')
    def action_delete(self, ids):
        query = tools.get_query_for_ids(self.get_query(), self.model, ids)
        count = query.update({'enable': False})
        self.session.commit()
        self.apply(query.all())
        count =query.delete()
        self.session.commit()
        hutils.flask.flash(_('%(count)s users were successfully deleted.', count=count), 'success')
    
    @action('reset usage', 'Reset Usage', 'Are you sure you want to reset usage of selected users?')
    def action_reset_usage(self, ids):
        query = tools.get_query_for_ids(self.get_query(), self.model, ids)
        count = query.update({'current_usage': 0})
        self.session.commit()
        hutils.flask.flash(_('The usage of %(count)s users was successfully reset.', count=count), 'success')
        self.apply(query.all())

    @action('reset day', 'Reset Day', 'Are you sure you want to reset day of selected users?')
    def action_reset_days(self, ids):
        query = tools.get_query_for_ids(self.get_query(), self.model, ids)
        count = query.update({'start_date': None})
        self.session.commit()
        hutils.flask.flash(_('The day counter of %(count)s users was successfully reset.', count=count), 'success')
        self.apply(query.all())

    def apply(self,users):
        for user in users:
        
            if user.is_active:
                user_driver.add_client(user)
            else:
                user_driver.remove_client(user) 
        hiddify.quick_apply_users()