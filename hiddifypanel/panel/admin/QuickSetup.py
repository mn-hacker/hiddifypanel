import re
import flask_babel
import uuid
# from flask_babelex import lazy_gettext as _
from flask import render_template, g, request, session
from flask_babel import gettext as _
from markupsafe import Markup
import wtforms as wtf
from flask_wtf import FlaskForm
from flask_bootstrap import SwitchField
from hiddifypanel.panel import hiddify
from flask_classful import FlaskView
from wtforms.validators import ValidationError, Length, InputRequired
# from gettext import gettext as _

from hiddifypanel.models import Domain, DomainType, StrConfig, ConfigEnum, get_hconfigs
from hiddifypanel.database import db
from hiddifypanel.auth import login_required
from hiddifypanel import hutils
from hiddifypanel.models import *


class QuickSetup(FlaskView):
    decorators = [login_required({Role.super_admin, Role.custom})]

    def current_form(self, step=None, empty=False, next=False):
        step = int(step or request.form.get("step") or request.args.get('step', "1"))
        if next:
            step = step + 1
        form = {1: get_lang_form,
                2: get_password_form,
                3: get_quick_setup_form,
                4: get_proxy_form}

        return form[step](empty=empty or next)

    def index(self):

        return render_template(
            'quick_setup.html',
            form=self.current_form(),
            # ipv4=hutils.network.get_ip_str(4),
            # ipv6=hutils.network.get_ip_str(6),
            admin_link=admin_link(),
            show_domain_info=True)

    def post(self):
        if request.args.get('changepw') == "true":
            AdminUser.current_admin_or_owner().uuid = str(uuid.uuid4())
            # AdminUser.current_admin_or_owner().password = hutils.random.get_random_password()
            db.session.commit()
            
            # Re-register Telegram bot webhook with new admin UUID
            # This fixes the issue where bot stops working after UUID/password change
            try:
                from hiddifypanel.panel.commercial.telegrambot import register_bot
                from hiddifypanel.panel.commercial.restapi.v1.tgbot import register_bot_cached
                # Clear cache and re-register with new webhook
                register_bot_cached.invalidate_all()
                register_bot(set_hook=True, remove_hook=True)
            except Exception as e:
                # Log but don't fail
                import logging
                logging.warning(f"Could not re-register Telegram bot webhook: {e}")
        # watashi v12.2.66: a step back must not validate and must not write.
        # It rebuilds the earlier step empty, so every box shows what was really
        # saved for that step instead of whatever was typed on this one.
        if request.form.get('qs_back'):
            here = int(request.form.get('step') or '1')
            back = here - 1 if here > 1 else 1
            return render_template(
                'quick_setup.html', form=self.current_form(step=back, empty=True),
                admin_link=admin_link(),
                ipv4=hutils.network.get_ip_str(4),
                ipv6=hutils.network.get_ip_str(6),
                show_domain_info=False)
        set_hconfig(ConfigEnum.first_setup, False)
        form = self.current_form()
        if not form.validate_on_submit() or form.step.data not in ["1", "2", "3","4"]:
            hutils.flask.flash(_('config.validation-error'), 'danger')
            return render_template(
                'quick_setup.html', form=form,
                admin_link=admin_link(),
                ipv4=hutils.network.get_ip_str(4),
                ipv6=hutils.network.get_ip_str(6),
                show_domain_info=False)
        return form.post(self)


def get_lang_form(empty=False):
    class LangForm(FlaskForm):
        step = wtf.HiddenField(default="1")
        admin_lang = wtf.SelectField(
            _("config.admin_lang.label"), choices=[("en", _("lang.en")), ("fa", _("lang.fa")), ("pt", _("lang.pt")), ("zh", _("lang.zh")), ("ru", _("lang.ru")), ("my", _("lang.my"))],
            description=_("config.admin_lang.description"),
            default=hconfig(ConfigEnum.admin_lang))
        # lang=wtf.SelectField(_("config.lang.label"),choices=[("en",_("lang.en")),("fa",_("lang.fa"))],description=_("config.lang.description"),default=hconfig(ConfigEnum.lang))
        country = wtf.SelectField(
            _("config.country.label"), choices=[("ir", _("Iran")), ("zh", _("China")), ("ru", _("Russia")),  ("other", "Others")],
            description=_("config.country.description"),
            default=hconfig(ConfigEnum.country))
        lang_submit = wtf.SubmitField(_('Submit'))

        def post(self, view):
            set_hconfig(ConfigEnum.lang, self.admin_lang.data)
            set_hconfig(ConfigEnum.admin_lang, self.admin_lang.data)
            set_hconfig(ConfigEnum.country, self.country.data)

            flask_babel.refresh()
            hutils.flask.flash((_('quicksetup.setlang.success')), 'success')

            return render_template(
                'quick_setup.html', form=view.current_form(next=True),
                admin_link=admin_link(),  # watashi v12.2.66: the card used to vanish here
                ipv4=hutils.network.get_ip_str(4),
                ipv6=hutils.network.get_ip_str(6),
                show_domain_info=False)

    form = LangForm(None)if empty else LangForm()
    form.step.data = "1"
    return form


def get_password_form(empty=False):
    class PasswordForm(FlaskForm):
        step = wtf.HiddenField(default="2")  # watashi v12.2.66: was "1"
        admin_pass = wtf.PasswordField(
            _("user.password.title"),
            description=_("user.password.description"),
            default="",validators=[
                
                InputRequired(message=_("user.password.validation-required")), 
                Length(min=8, message=_("user.password.validation-lenght"))
        
            ])
        password_submit = wtf.SubmitField(_('Submit'))

        def post(self, view):
            AdminUser.current_admin_or_owner().update_password(self.admin_pass.data)
            
            # Re-register Telegram bot webhook with updated admin URL
            # This fixes the issue where bot stops working after password is set
            try:
                from hiddifypanel.panel.commercial.telegrambot import register_bot
                from hiddifypanel.panel.commercial.restapi.v1.tgbot import register_bot_cached
                # Clear cache and re-register with new webhook
                register_bot_cached.invalidate_all()
                register_bot(set_hook=True, remove_hook=True)
            except Exception as e:
                # Log but don't fail - bot can be configured later
                import logging
                logging.warning(f"Could not re-register Telegram bot webhook: {e}")

            return render_template(
                'quick_setup.html', form=view.current_form(next=True),
                admin_link=admin_link(),
                ipv4=hutils.network.get_ip_str(4),
                ipv6=hutils.network.get_ip_str(6),
                show_domain_info=False)

    form = PasswordForm(None)if empty else PasswordForm()
    form.step.data = "2"
    return form

def get_proxy_form(empty=False):
    class ProxyForm(FlaskForm):
        step = wtf.HiddenField(default="4")  # watashi v12.2.66: was "3"
        description_for_fieldset = wtf.TextAreaField("", description=_(f'quicksetup.proxy_cat.description'), render_kw={"class": "d-none"})

        def post(self, view):

            for k, vs in self.data.items():
                ek = ConfigEnum[k]
                if ek != ConfigEnum.not_found:
                    set_hconfig(ek, vs, commit=False)

            db.session.commit()
            # print(cat,vs)
            hutils.proxy.get_proxies.invalidate_all()
            if hutils.node.is_child():
                hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.hconfigs])

            try:
                session.pop('ws_qs_domains', None)  # watashi v12.2.66
            except BaseException:
                pass
            from .Actions import Actions
            return Actions().reinstall(domain_changed=True)
    # watashi v12.2.67: this step used to draw EVERY switch whose name ends with
    # _enable, so the three telegram notification switches, the four adblock
    # switches, the device limit and the access log all stood on a page that only
    # asks which PROXIES to turn on. The Proxies page already owns that judgement,
    # so the wizard borrows it instead of keeping a second opinion.
    from .ProxyAdmin import ws_is_proxy_switch, ws_ensure_proxy_switch_rows
    try:
        # Mieru, AmneziaWG and port hopping have no row on an install older than
        # they are, and a switch with no row is simply never drawn.
        ws_ensure_proxy_switch_rows()
    except BaseException:
        pass

    boolconfigs = BoolConfig.query.filter(BoolConfig.child_id == Child.current().id).all()

    for cf in boolconfigs:
        if not ws_is_proxy_switch(cf.key):  # watashi v12.2.67
            continue
        field = SwitchField(_(f'config.{cf.key}.label'), default=cf.value, description=_(f'config.{cf.key}.description'))
        setattr(ProxyForm, f'{cf.key}', field)
    setattr(ProxyForm, "submit_global", wtf.fields.SubmitField(_('Submit')))
    form = ProxyForm(None) if empty else ProxyForm()
    form.step.data = "4"
    return form


def ws_wizard_domains():
    """The domains this wizard wrote itself, so a step back can offer them again."""
    try:
        kept = session.get('ws_qs_domains') or []
    except BaseException:
        return []
    return [str(d).lower() for d in kept if d]


def get_quick_setup_form(empty=False):
    # watashi v12.2.66: get_used_domains() used to live here and was never
    # called once. The wizard's own domains take its place.
    mine = ws_wizard_domains()

    class BasicConfigs(FlaskForm):
        step = wtf.HiddenField(default="3")  # watashi v12.2.66: was "2"
        # watashi v12.2.66: this step used to carry the PROTOCOL step's
        # description, so the domain page sat there explaining protocols. The
        # card header already says what this step is for.
        domain_regex = "^([A-Za-z0-9\\-\\.]+\\.[a-zA-Z]{2,})$"

        # watashi v12.2.66: when the admin steps back to change a domain, the
        # row this wizard added a moment ago must not be counted against them.
        taken = [d.domain.lower() for d in Domain.query.all() if d.domain.lower() not in mine]

        domain_validators = [
            wtf.validators.Regexp(domain_regex, re.IGNORECASE, _("config.Invalid_domain")),
            validate_domain,
            wtf.validators.NoneOf(taken, _("config.Domain_already_used")),
            wtf.validators.NoneOf([c.value.lower() for c in StrConfig.query.all() if "fakedomain" in c.key and c.key != ConfigEnum.decoy_domain], _("config.Domain_already_used"))]

        cdn_domain_validators = [
            wtf.validators.Regexp(f'({domain_regex})|(^$)', re.IGNORECASE, _("config.Invalid_domain")),
            validate_domain_cdn,
            wtf.validators.NoneOf(taken, _("config.Domain_already_used")),
            wtf.validators.NoneOf([c.value.lower() for c in StrConfig.query.all() if "fakedomain" in c.key and c.key != ConfigEnum.decoy_domain], _("config.Domain_already_used"))]
        domain = wtf.StringField(
            _("domain.domain"),
            domain_validators,
            description=_("domain.description"),
            default=(mine[0] if mine else None),  # watashi v12.2.66
            render_kw={
                "class": "ltr",
                "pattern": domain_validators[0].regex.pattern,
                "title": domain_validators[0].message,
                "required": "",
                "placeholder": "sub.domain.com"})

        cdn_domain = wtf.StringField(
            _("quicksetup.cdn_domain.label"),
            cdn_domain_validators,
            description=_("quicksetup.cdn_domain.description"),
            default=(mine[1] if len(mine) > 1 else None),  # watashi v12.2.66
            render_kw={
                "class": "ltr",
                "pattern": domain_validators[0].regex.pattern,
                "title": domain_validators[0].message,
                "placeholder": "sub.domain.com"})
        # enable_telegram = SwitchField(_("config.telegram_enable.label"), description=_("config.telegram_enable.description"), default=hconfig(ConfigEnum.telegram_enable))
        # enable_firewall = SwitchField(_("config.firewall.label"), description=_("config.firewall.description"), default=hconfig(ConfigEnum.firewall))
        block_iran_sites = SwitchField(_("config.block_iran_sites.label"), description=_(
            "config.block_iran_sites.description"), default=hconfig(ConfigEnum.block_iran_sites))
        # enable_vmess = SwitchField(_("config.vmess_enable.label"), description=_("config.vmess_enable.description"), default=hconfig(ConfigEnum.vmess_enable))
        decoy_domain = wtf.StringField(_("config.decoy_domain.label"), description=_("config.decoy_domain.description"), default=hconfig(
            ConfigEnum.decoy_domain), validators=[wtf.validators.Regexp(domain_regex, re.IGNORECASE, _("config.Invalid_domain")), hutils.flask.validate_domain_exist])
        submit = wtf.SubmitField(_('Submit'))

        def post(self, view):
            Domain.query.filter(Domain.domain == f'{hutils.network.get_ip_str(4)}.sslip.io').delete()
            # watashi v12.2.66: whatever this wizard wrote on an earlier pass is
            # dropped first. Without this, stepping back and pressing submit a
            # second time leaves the panel serving both the old name and the new.
            for old_one in ws_wizard_domains():
                Domain.query.filter(Domain.domain == old_one).delete()
            db.session.add(Domain(domain=self.domain.data.lower(), mode=DomainType.direct))
            if self.cdn_domain.data:
                db.session.add(Domain(domain=self.cdn_domain.data.lower(), mode=DomainType.cdn))
            try:
                session['ws_qs_domains'] = [d for d in [
                    (self.domain.data or '').lower(),
                    (self.cdn_domain.data or '').lower()] if d]
            except BaseException:
                pass
            set_hconfig(ConfigEnum.block_iran_sites, self.block_iran_sites.data)
            set_hconfig(ConfigEnum.decoy_domain, self.decoy_domain.data)
            # hiddify.bulk_register_configs([
            #     # {"key": ConfigEnum.telegram_enable, "value": quick_form.enable_telegram.data == True},
            #     # {"key": ConfigEnum.vmess_enable, "value": quick_form.enable_vmess.data == True},
            #     # {"key": ConfigEnum.firewall, "value": quick_form.enable_firewall.data == True},
            #     {"key": ConfigEnum.block_iran_sites, "value": quick_form.block_iran_sites.data == True},
            #     # {"key":ConfigEnum.decoy_domain,"value":quick_form.decoy_domain.data}
            # ])

            return render_template(
                'quick_setup.html', form=view.current_form(next=True),
                # ipv4=hutils.network.get_ip_str(4),
                # ipv6=hutils.network.get_ip_str(6),
                admin_link=admin_link(),
                show_domain_info=False)

    form = BasicConfigs(None) if empty else BasicConfigs()
    form.step.data = "3"
    return form


def validate_domain(form, field):
    domain = field.data
    dip = hutils.network.get_domain_ip(domain)
    if dip is None:
        raise ValidationError(_("Domain can not be resolved! there is a problem in your domain"))

    myips = hutils.network.get_ips()
      # Fixed: Changed from get_ip(4) to get_ip(6)
    if dip not in myips:
        raise ValidationError(_("Domain (%(domain)s)-> IP=%(domain_ip)s is not matched with your ip=%(server_ip)s which is required in direct mode",
                              server_ip=myips, domain_ip=dip, domain=domain))


def validate_domain_cdn(form, field):
    domain = field.data
    if not domain:
        return
    dip = hutils.network.get_domain_ip(domain)
    if dip is None:
        raise ValidationError(_("Domain can not be resolved! there is a problem in your domain"))

    myips = hutils.network.get_ips()
    if dip in myips:
        raise ValidationError(_("In CDN mode, Domain IP=%(domain_ip)s should be different to your ip=%(server_ip)s",
                              server_ip=myips, domain_ip=dip, domain=domain))


def admin_link():
    domains = Domain.get_domains()
    return hiddify.get_account_panel_link(g.account, domains[0] if len(domains)else hutils.network.get_ip_str(4))
