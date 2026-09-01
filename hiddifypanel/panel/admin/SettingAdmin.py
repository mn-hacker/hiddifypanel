from hiddifypanel.cache import cache
from hiddifypanel import __version__
from hiddifypanel.panel import hiddify, custom_widgets
from hiddifypanel.database import db
from hiddifypanel.models import *
from hiddifypanel.models import BoolConfig, StrConfig, ConfigEnum, hconfig, ConfigCategory
import re
import uuid as ws_uuid
import flask_babel
import flask_babel
from flask_babel import lazy_gettext as _
# from flask_babelex import gettext as _
from flask import render_template, g  # type: ignore
from markupsafe import Markup

from hiddifypanel.hutils.flask import hurl_for
from flask import current_app as app
from hiddifypanel import hutils
from hiddifypanel.auth import login_required
import wtforms as wtf
from flask_bootstrap import SwitchField
from wtforms import SelectMultipleField

# from gettext import gettext as _
from flask_classful import FlaskView
from flask_wtf import FlaskForm
from bleach import clean as bleach_clean, ALLOWED_TAGS as BLEACH_ALLOWED_TAGS
ALLOWED_TAGS = set([*BLEACH_ALLOWED_TAGS, "h1", "h2", "h3", "h4", "p"])



class SwitchListWidget(wtf.widgets.ListWidget):
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        html = []
        for subfield in field:
            checked = ' checked' if subfield.checked else ''
            html.append(f'''
            <div class="d-flex align-items-center mb-2">
                <div class="custom-control custom-switch">
                    <input type="checkbox" class="custom-control-input" id="{subfield.id}" name="{subfield.name}" value="{subfield._value()}"{checked}>
                    <label class="custom-control-label" for="{subfield.id}">{subfield.label.text}</label>
                </div>
            </div>
            ''')
        return Markup(''.join(html))

class SettingAdmin(FlaskView):

    @login_required(roles={Role.super_admin, Role.custom})
    def index(self):
        form = get_config_form()
        return ws_render_settings(form)

    @login_required(roles={Role.super_admin, Role.custom})
    def post(self):
        set_hconfig(ConfigEnum.first_setup, False)
        form = get_config_form()
        reset_action = None
        ws_bad = set()
        if form.is_submitted() and not form.validate():
            ws_bad = ws_bad_fields(form)
            if 'csrf_token' in form.errors:
                hutils.flask.flash(str(_('Your page was open for too long. Please try again.')), 'danger')
                return ws_render_settings(form)
        if form.is_submitted():

            boolconfigs = BoolConfig.query.filter(BoolConfig.child_id == Child.current().id).all()
            bool_types = {c.key: 'bool' for c in boolconfigs}

            # old_configs = get_hconfigs()
            # Use raw DB values to avoid logic overrides (e.g. access_log_enable forced True) masking user changes
            strconfigs = StrConfig.query.filter(StrConfig.child_id == Child.current().id).all()
            old_configs = {**{u.key: u.value for u in boolconfigs},
                           **{u.key: int(u.value) if u.key.type == int and u.value is not None else u.value for u in strconfigs}}
            changed_configs = {}

            for category, c_items in form.data.items():  # [c for c in ConfigEnum]:

                if isinstance(c_items, dict):
                    for k in ConfigEnum:
                        if k.name not in c_items:
                            continue
                        if k.name in ws_bad:
                            continue
                        v = c_items[k.name]
                        if k.type == str:
                            if k == ConfigEnum.ech_domains:
                                v = ",".join(v)
                            if "_domain" in k.name or "_fakedomain" in k.name:
                                v = v.lower()
                            if k == ConfigEnum.warp_sites and 'https://' in v:
                                hutils.flask.flash(_("config.warp-https-domain-for-warp-site"), 'error')
                                ws_bad.add(k.name)
                                continue
                            if "port" in k.name and "transport" not in k.name:
                                for p in v.split(","):
                                    if (k != ConfigEnum.tls_ports and p == "443") or (k != ConfigEnum.http_ports and p == "80"):
                                        hutils.flask.flash(ws_port_reserved_msg(), 'error')
                                        ws_bad.add(k.name)
                                        break
                                    for c_, c_items2 in form.data.items():
                                        if not isinstance(c_items2, dict):continue
                                        for k2, v2 in c_items2.items():
                                                if "port" in k2 and "transport" not in k2 and k.name != k2 and v2 and p in str(v2).strip().split(","):
                                                    hutils.flask.flash(ws_port_taken_msg(form, p, k2), 'error')
                                                    ws_bad.add(k.name)
                                                    break
                            if k == ConfigEnum.parent_panel and v != '':
                                # v=(v+"/").replace("/admin",'')
                                v = re.sub("(/admin/.*)", "/", v) + ("/" if not v.endswith("/") else "")


                        if k.name in ws_bad:
                            continue
                        if not ws_same(old_configs.get(k), v):
                            changed_configs[k] = v

                # print(cat,vs)

            merged_configs = {**old_configs, **changed_configs}
            ws_paths = [merged_configs.get(ConfigEnum.proxy_path), merged_configs.get(ConfigEnum.proxy_path_client), merged_configs.get(ConfigEnum.proxy_path_admin)]
            ws_paths = [str(p) for p in ws_paths if p]
            if len(set(ws_paths)) != len(ws_paths):
                hutils.flask.flash(ws_same_path_msg(), 'error')  # type: ignore
                return ws_render_settings(form)

            # validate parent_panel value
            parent_apikey = ''
            if p_p := changed_configs.get(ConfigEnum.parent_panel):
                domain, proxy_path, uuid = hutils.flask.extract_parent_info_from_url(p_p)
                if not domain or not proxy_path or not uuid or not hutils.node.is_panel_active(domain, proxy_path, uuid):
                    hutils.flask.flash(_('parent.invalid-parent-url'), 'danger')  # type: ignore
                    return ws_render_settings(form)
                else:
                    set_hconfig(ConfigEnum.parent_domain, domain)
                    set_hconfig(ConfigEnum.parent_admin_proxy_path, proxy_path)
                    parent_apikey = uuid

            for k, v in changed_configs.items():
                # html inputs santitizing
                if k in {ConfigEnum.branding_title, ConfigEnum.branding_site, ConfigEnum.branding_freetext}:
                    v = bleach_clean(v, tags=ALLOWED_TAGS)
                set_hconfig(k, v, commit=False)

            db.session.commit()
            flask_babel.refresh()

            # set panel mode
            p_mode = hconfig(ConfigEnum.panel_mode)
            if p_mode != PanelMode.parent:
                if hconfig(ConfigEnum.parent_panel):
                    if p_mode == PanelMode.standalone:
                        set_hconfig(ConfigEnum.panel_mode, PanelMode.child)
                else:
                    if p_mode != PanelMode.standalone:
                        set_hconfig(ConfigEnum.panel_mode, PanelMode.standalone)

            cache.invalidate_all_cached_functions()
            # hutils.proxy.get_proxies.invalidate_all()
            from hiddifypanel.panel.commercial.telegrambot import register_bot
            register_bot(set_hook=True)

            # sync with parent if needed
            if hutils.node.is_child():
                if hutils.node.child.is_registered():
                    hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.hconfigs])
                else:
                    name = hconfig(ConfigEnum.unique_id)
                    parent_info = hutils.node.get_panel_info(hconfig(ConfigEnum.parent_domain), hconfig(ConfigEnum.parent_admin_proxy_path), parent_apikey)
                    if parent_info.get('version') != __version__:
                        hutils.flask.flash(_('node.diff-version'), 'danger')  # type: ignore
                    if not hutils.node.child.register_to_parent(name, parent_apikey, mode=ChildMode.remote):
                        hutils.flask.flash(_('child.register-failed'), 'danger')  # type: ignore
                    else:  # TODO: it's just for debuging
                        hutils.flask.flash(_('child.register-success'))  # type: ignore

            reset_action = ws_check_need_reset(old_configs)
            ws_tell_skipped(form, ws_bad)

            if old_configs.get(ConfigEnum.admin_lang) != hconfig(ConfigEnum.admin_lang):
                form = get_config_form()
        else:
            hutils.flask.flash(_('config.validation-error'), 'danger')  # type: ignore

        return reset_action or ws_render_settings(form)

    def get_babel_string(self):
        res = ""
        strconfigs = StrConfig.query.all()
        boolconfigs = BoolConfig.query.all()
        bool_types = {c.key: 'bool' for c in boolconfigs}

        configs = [*boolconfigs, *strconfigs]
        for cat in ConfigCategory:
            if cat == 'hidden':
                continue

            cat_configs = [c for c in configs if c.key.category == cat]

            for c in cat_configs:
                res += f'{{{{_("config.{c.key}.label")}}}} {{{{_("config.{c.key}.description")}}}}'

            res += f'{{{{_("config.{cat}.label")}}}}{{{{_("config.{cat}.description")}}}}'
        for c in ConfigEnum:
            res += f'{{{{_("config.{c}.label")}}}} {{{{_("config.{c}.description")}}}}'
        return res


def get_config_form():
    strconfigs = StrConfig.query.filter(StrConfig.child_id == Child.current().id).all()
    boolconfigs = BoolConfig.query.filter(BoolConfig.child_id == Child.current().id).all()
    bool_types = {c.key: 'bool' for c in boolconfigs}

    configs = [*boolconfigs, *strconfigs]
    configs_key = {k.key: k for k in configs}
    # categories=sorted([ c for c in {c.key.category:1 for c in configs}])
    # dict_configs={cat:[c for c in configs if c.category==cat] for cat in categories}

    class DynamicForm(FlaskForm):
        pass
    is_parent = hutils.node.is_parent()

    for cat in ConfigCategory:
        if cat == 'hidden':
            continue

        cat_configs = [c for c in ConfigEnum if c.category == cat and (not is_parent or c.show_in_parent)]
        if len(cat_configs) == 0:
            continue

        class CategoryForm(FlaskForm):
            class Meta:
                csrf = False
            description_for_fieldset = wtf.TextAreaField("", description=_(f'config.{cat}.description'), render_kw={"class": "d-none"})
        for c2 in cat_configs:
            if c2 == ConfigEnum.parent_panel and hutils.node.is_parent():
                continue
            c = configs_key.get(c2) or type('C', (), {'key': c2, 'value': None})
            if hutils.node.is_parent():
                if c.key == ConfigEnum.parent_panel:
                    continue
            extra_info = ''
            if c.key.type == bool:
                default_val = c.value if isinstance(c.value, bool) else str(c.value).lower() in ["true", "1"] if c.value is not None else False
                field = SwitchField(ws_label(c.key), default=default_val, description=ws_desc(c.key))
            elif c.key == ConfigEnum.core_type:
                field = wtf.SelectField(ws_label(c.key),
                                        choices=[("xray", _("Xray")), ("singbox", _("SingBox"))],
                                        description=ws_desc(c.key),
                                        default=hconfig(c.key))
            elif c.key == ConfigEnum.warp_mode:
                field = wtf.SelectField(ws_label(c.key),
                                        choices=[("disable", _("Disable")), ("all", _("All")), ("custom", _("Only Blocked and Local websites"))],
                                        description=ws_desc(c.key),
                                        default=hconfig(c.key))

            elif c.key == ConfigEnum.ech_domains:
                domains = Domain.query.all()
                choices = [(d.domain, d.domain) for d in domains]
                default_val = hconfig(c.key).split(",") if hconfig(c.key) else []
                field = SelectMultipleField(
                    ws_label(c.key),
                    choices=choices,
                    description=ws_desc(c.key),
                    default=default_val,

                    option_widget=wtf.widgets.CheckboxInput(),
                    widget=SwitchListWidget(prefix_label=False),
                    render_kw={'class': "ltr"}
                )



            elif c.key == ConfigEnum.lang or c.key == ConfigEnum.admin_lang:
                field = wtf.SelectField(
                    ws_label(c.key),
                    choices=[("en", _("lang.en")), ("fa", Markup(_("lang.fa"))), ("zh", _("lang.zh")), ("pt", _("lang.pt")), ("ru", _("lang.ru")), ("my", _("lang.my"))],
                    description=ws_desc(c.key),
                    default=hconfig(c.key))
            elif c.key == ConfigEnum.country:
                field = wtf.SelectField(ws_label(c.key), choices=[
                    ("ir", _("Iran")), ("zh", _("China")), ("ru", _("Russia")), ("other", _("Others"))], description=ws_desc(c.key), default=hconfig(c.key))
            elif c.key == ConfigEnum.package_mode:
                package_modes = [("release", _("Release")), ("beta", _("Beta"))]
                if hconfig(c.key) == "develop":
                    package_modes.append(("develop", _("Develop")))
                field = wtf.SelectField(ws_label(c.key), choices=package_modes, description=ws_desc(c.key), default=hconfig(c.key))
            elif c.key == ConfigEnum.mieru_multiplexing:
                choices = [
                    ("MULTIPLEXING_DEFAULT", "Default"),
                    ("MULTIPLEXING_LOW", "Low"),
                    ("MULTIPLEXING_MIDDLE", "Middle"),
                    ("MULTIPLEXING_HIGH", "High")
                ]
                field = wtf.SelectField(ws_label(c.key), choices=choices, description=ws_desc(c.key), default=hconfig(c.key))
            elif c.key == ConfigEnum.mieru_handshake:
                choices = [
                    ("HANDSHAKE_DEFAULT", "Default"),
                    ("HANDSHAKE_NO_WAIT", "No Wait"),
                    ("HANDSHAKE_STANDARD", "Standard")
                ]
                field = wtf.SelectField(ws_label(c.key), choices=choices, description=ws_desc(c.key), default=hconfig(c.key))
            elif c.key == ConfigEnum.mieru_transport:
                choices = [
                    ("brutal", "TCP Brutal"),
                    ("bbr", "BBR"),
                ]
                field = wtf.SelectField(ws_label(c.key), choices=choices, description=ws_desc(c.key), default=hconfig(c.key))

            # the shadowsocks2022_method is hidden now, because it only has one option to choose
            # elif c.key == ConfigEnum.shadowsocks2022_method:
            #     field = wtf.SelectField(
            #         ws_label(c.key),
            #         choices=[
            #             ("2022-blake3-aes-256-gcm", "2022-blake3-aes-256-gcm"),
            #             # ("2022-blake3-chacha20-poly1305", "2022-blake3-chacha20-poly1305"),
            #         ],
            #         description=ws_desc(c.key), default=hconfig(c.key))

            elif c.key == ConfigEnum.utls:
                field = wtf.SelectField(
                    ws_label(c.key),
                    choices=[
                        ("none", "None"), ("chrome", "Chrome"), ("edge", "Edge"), ("ios", "iOS"), ("android", "Android"),
                        ("safari", "Safari"), ("firefox", "Firefox"), ('random', 'random'), ('randomized', 'randomized')],
                    description=ws_desc(c.key),
                    default=hconfig(c.key)
                )
            elif c.key == ConfigEnum.telegram_lib:
                # watashi v12.2.53: telemt is the only engine that can carry an ad
                # tag - mtg dropped that feature in its v2 - so it leads the list.
                # Plain labels on purpose: no new translation key to go missing.
                libs = [
                    ("telemt", "telemt - ad tag + fake tls (recommended)"),
                    ("tgo", "mtg - light, cannot carry an ad tag"),
                ]
                chosen = hconfig(c.key)
                if chosen not in ("telemt", "tgo"):
                    chosen = "telemt"
                field = wtf.SelectField(ws_label(c.key), choices=libs, description=ws_desc(c.key), default=chosen)
            elif c.key == ConfigEnum.mux_protocol:
                choices = [("smux", 'smux'), ("yamux", "yamux"), ("h2mux", "h2mux")]
                field = wtf.SelectField(ws_label(c.key), choices=choices, description=ws_desc(c.key), default=hconfig(c.key))

            elif c.key == ConfigEnum.warp_sites:
                validators = [wtf.validators.Length(max=2048),
                              wtf.validators.Regexp(r'^(?:[\w.-]+\.\w+(?:\.\w+)?(?:\r?\n|$)|^$)', 0, _("config.invalid-pattern-for-warp-sites") + f' {c.key}')
                              ]
                render_kw = {'class': "ltr", 'maxlength': 2048}
                field = wtf.TextAreaField(ws_label(c.key), validators, default=c.value,
                                          description=ws_desc(c.key), render_kw=render_kw)
            elif c.key == ConfigEnum.branding_freetext:
                validators = [wtf.validators.Length(max=2048)]
                render_kw = {'class': "ltr", 'maxlength': 2048}
                field = custom_widgets.CKTextAreaField(ws_label(c.key), validators, default=c.value,
                                                       description=ws_desc(c.key), render_kw=render_kw)
            else:
                render_kw = {'class': "ltr"}
                validators = []
                if c.key == ConfigEnum.domain_fronting_domain:
                    validators.append(wtf.validators.Regexp("^([A-Za-z0-9\\-\\.]+\\.[a-zA-Z]{2,})|$", re.IGNORECASE, ws_domain_msg(c.key)))
                elif '_domain' in c.key.name or "_fakedomain" in c.key.name:
                    validators.append(wtf.validators.Regexp("^([A-Za-z0-9\\-\\.]+\\.[a-zA-Z]{2,})$|^$", re.IGNORECASE, ws_domain_msg(c.key)))
                    if not c.value or len(str(c.value)) < 3:
                        c.value = ws_default_for(c.key)
                        ws_note_fresh(c.key)

                # if c.key ==ConfigEnum.reality_short_ids:
                #     extra_info=f" <a target='_blank' href='{hurl_for('admin.Actions:get_some_random_reality_friendly_domain',test_domain=c.value)}'>"+_('Example Domains')+"</a>"
                # if c.key ==ConfigEnum.reality_server_names:
                #     validators.append(wtf.validators.Regexp("^([\w-]+\.)+[\w-]+(,\s*([\w-]+\.)+[\w-]+)*$",re.IGNORECASE,_("Invalid REALITY hostnames")))
                    # gauge width gate lamp weasel jaguar minute enough few attitude endorse situate usdt trc20 doge bep20 trx doge ltc bnb eth btc bnb
                    # enjoy control list debris chronic few door broken way negative daring life season recipe profit switch bitter casual frame aunt plate brush aerobic display

                if c.key == ConfigEnum.parent_panel:
                    validators.append(wtf.validators.Regexp("()|(http(s|)://([A-Za-z0-9\\-\\.]+\\.[a-zA-Z]{2,})/.*)", re.IGNORECASE, _("Invalid admin link")))
                if c.key == ConfigEnum.telegram_bot_token:
                    validators.append(wtf.validators.Regexp("()|^([0-9]{8,12}:[a-zA-Z0-9_-]{30,40})|$", re.IGNORECASE, _("config.Invalid_telegram_bot_token")))
                if c.key == ConfigEnum.branding_site:
                    validators.append(wtf.validators.Regexp(
                        "()|(http(s|)://([A-Za-z0-9\\-\\.]+\\.[a-zA-Z]{2,})/?.*)", re.IGNORECASE, _("config.Invalid_brand_link")))
                    # render_kw['required']=""

                if 'secret' in c.key.name:
                    validators.append(wtf.validators.Regexp(
                        "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$|^$", re.IGNORECASE, ws_uuid_msg(c.key)))
                    if not c.value:
                        c.value = str(ws_uuid.uuid4())
                        ws_note_fresh(c.key)

                if c.key == ConfigEnum.proxy_path:
                    validators.append(wtf.validators.Regexp("^[a-zA-Z0-9]*$", re.IGNORECASE, ws_path_msg(c.key)))
                    if not c.value:
                        c.value = ws_new_path()
                        ws_note_fresh(c.key)

                if 'port' in c.key.name and 'transport' not in c.key.name:
                    if c.key in [ConfigEnum.http_ports, ConfigEnum.tls_ports]:
                        validators.append(wtf.validators.Regexp("^(\\d+)(,\\d+)*$|^$", re.IGNORECASE, ws_port_msg(c.key)))
                        if not c.value:
                            c.value = "80" if c.key == ConfigEnum.http_ports else "443"
                            ws_note_fresh(c.key)
                    else:
                        validators.append(wtf.validators.Regexp("^(\\d+)(,\\d+)*$|^$", re.IGNORECASE, ws_port_msg(c.key)))
                    # validators.append(wtf.validators.Regexp("^(\d+)(,\d+)*$",re.IGNORECASE,_("config.port is required")))

                # tls tricks validations
                # watashi v12.2.77: the new max split is a range like the rest
                if c.key in [ConfigEnum.tls_fragment_size, ConfigEnum.tls_fragment_sleep, ConfigEnum.tls_padding_length, ConfigEnum.wireguard_noise_trick, ConfigEnum.xray_finalmask_maxsplit]:
                    validators.append(wtf.validators.Regexp("^\\d+-\\d+$|^$", re.IGNORECASE, ws_pair_msg(c.key)))
                # mux and hysteria validations
                if c.key in [ConfigEnum.hysteria_up_mbps, ConfigEnum.hysteria_down_mbps, ConfigEnum.mux_max_connections, ConfigEnum.mux_min_streams, ConfigEnum.mux_max_streams,
                             ConfigEnum.mux_brutal_down_mbps, ConfigEnum.mux_brutal_up_mbps, ConfigEnum.user_limit_block_hours, ConfigEnum.user_limit_default, ConfigEnum.hwid_limit_default,
                             ConfigEnum.amnezia_s1, ConfigEnum.amnezia_s2, ConfigEnum.amnezia_h1, ConfigEnum.amnezia_h2, ConfigEnum.amnezia_h3, ConfigEnum.amnezia_h4,
                             ConfigEnum.amnezia_jc, ConfigEnum.amnezia_jmin, ConfigEnum.amnezia_jmax]:
                    validators.append(wtf.validators.Regexp("^\\d+$|^$", re.IGNORECASE, ws_num_msg(c.key)))

                for val in validators:
                    if hasattr(val, "regex"):
                        render_kw['pattern'] = val.regex.pattern
                        render_kw['title'] = val.message

                if c.key == ConfigEnum.reality_public_key and g.account.mode in [AdminMode.super_admin]:
                    extra_info = f" <a href='{hurl_for('admin.Actions:change_reality_keys')}'>{_('Change')}</a>"

                field = wtf.StringField(ws_label(c.key), validators, default=c.value,
                                        description=ws_desc(c.key) + extra_info, render_kw=render_kw)
            setattr(CategoryForm, f'{c.key}', field)

        multifield = wtf.FormField(CategoryForm, Markup('<i class="fa-solid fa-plus"></i>&nbsp' + _(f'config.{cat}.label')))

        setattr(DynamicForm, cat, multifield)

    setattr(DynamicForm, "submit", wtf.SubmitField(_('Submit')))

    return DynamicForm()


# ---------- Watashi Manager: the new settings page ----------

WS_FILLER_DOMAINS = [
    "www.google.com", "www.cloudflare.com", "www.bing.com", "www.microsoft.com",
    "www.wikipedia.org", "www.amazon.com", "www.apple.com", "www.yahoo.com",
    "www.reddit.com", "www.speedtest.net", "www.office.com", "www.icloud.com",
]

WS_GROUP_DEFS = [
    ("general", "fa-house", "Basics",
     ["general", "admin", "branding", "user_limit"]),
    ("protocols", "fa-shuffle", "Protocols",
     ["proxies", "shadowsocks", "ssfaketls", "shadowtls", "reality", "tuic",
      "hysteria", "mieru", "naive", "amnezia", "wireguard", "ssh", "ssr",
      "kcp", "restls"]),
    ("network", "fa-network-wired", "Network and transport",
     ["tls", "http", "tls_trick", "mux"]),
    ("telegram", "fa-paper-plane", "Telegram",
     ["telegram", "telegram_bot"]),
    ("guard", "fa-shield-halved", "Safety and filtering",
     ["adblock", "warp", "domain_fronting"]),
    ("advanced", "fa-screwdriver-wrench", "Advanced",
     ["advanced", "too_advanced"]),
]

# A handful of settings sit in an odd place in the old panel. This map moves
# each one onto the card it actually belongs to.
# Every setting stays inside the card it belongs to. The cards themselves are
# what we sort into sections, further down in WS_GROUP_DEFS.
WS_KEY_HOME = {}

# Boxes the panel owner has to fill in themselves. We never guess these.
WS_KEEP_EMPTY = set([
    "telegram_bot_token", "telegram_adtag", "telegram_bot_info",
    "branding_title", "branding_site", "branding_freetext",
    "cloudflare", "warp_plus_code", "warp_sites", "block_ads_custom",
    "parent_panel", "parent_domain", "parent_admin_proxy_path",
    "license", "ech_config", "ech_domains", "reality_short_ids",
    "reality_private_key", "reality_public_key", "reality_server_names",
    "wireguard_private_key", "wireguard_public_key", "wireguard_ipv4", "wireguard_ipv6",
    "ssh_host_rsa_pk", "ssh_host_rsa_pub", "ssh_host_ed25519_pk", "ssh_host_ed25519_pub",
    "ssh_host_ecdsa_pk", "ssh_host_ecdsa_pub", "ssh_host_dsa_pk", "ssh_host_dsa_pub",
    "ssh_server_redis_url", "unique_id", "last_hash", "admin_secret",
    "cdn_forced_host", "not_found", "restls1_2_domain", "restls1_3_domain",
])

# The value an empty box starts with. @uuid@, @path@ and @word@ are built fresh.
WS_BEST_DEFAULT = {
    "dns_server": "1.1.1.1",
    "tls_ports": "443",
    "http_ports": "80",
    "special_port": "2087",
    "shadowsocks2022_port": "2022",
    "shadowtls_port": "2094",
    "shadowtls_password": "@word@",
    "shadowtls_server_name": "www.speedtest.net",
    "ssfaketls_fakedomain": "www.speedtest.net",
    "shadowtls_fakedomain": "www.speedtest.net",
    "telegram_fakedomain": "www.wikipedia.org",
    "ssr_fakedomain": "www.wikipedia.org",
    "decoy_domain": "www.wikipedia.org",
    "reality_fallback_domain": "www.speedtest.net",
    "tuic_port": "2095",
    "hysteria_port": "2096",
    "naive_port": "2098",
    "mieru_port": "2099",
    "mieru_tcp_ports": "2103",
    "mieru_udp_ports": "2104",
    "amnezia_port": "2100",
    "wireguard_port": "2101",
    "ssh_server_port": "2222",
    "kcp_ports": "2105",
    "reality_port": "2087",
    "shared_secret": "@uuid@",
    "wireguard_noise_trick": "5-10",
    "tls_fragment_size": "10-100",
    "tls_fragment_sleep": "1-10",
    "xray_finalmask_maxsplit": "3-6",
    "tls_padding_length": "50-200",
    "mux_max_connections": "4",
    "mux_min_streams": "4",
    "mux_max_streams": "0",
    "mux_brutal_up_mbps": "100",
    "mux_brutal_down_mbps": "100",
    "hysteria_up_mbps": "100",
    "hysteria_down_mbps": "100",
    "amnezia_jc": "4",
    "amnezia_jmin": "40",
    "amnezia_jmax": "70",
    "amnezia_s1": "15",
    "amnezia_s2": "15",
    "amnezia_h1": "1234567",
    "amnezia_h2": "2345678",
    "amnezia_h3": "3456789",
    "amnezia_h4": "4567890",
    "notify_expiry_days": "3",
    "notify_usage_percent": "80",
    "backup_interval": "6",  # watashi v12.2.48: init_db seeds 6, so the box agrees now
    "hwid_limit_default": "3",
    "user_limit_default": "3",
    "user_limit_block_hours": "1",
    "path_vmess": "@path@",
    "path_vless": "@path@",
    "path_trojan": "@path@",
    "path_xhttp": "@path@",
    "path_httpupgrade": "@path@",
    "path_ws": "@path@",
    "path_tcp": "@path@",
    "path_grpc": "@path@",
    "path_v2ray": "@path@",
    "path_ss": "@path@",
    "proxy_path": "@path@",
    "proxy_path_admin": "@path@",
    "proxy_path_client": "@path@",
    "default_useragent_string": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# For drop-down boxes: the option we pick when nothing was chosen yet.
WS_BEST_CHOICE = {
    "core_type": "xray",
    "package_mode": "release",
    "telegram_lib": "telemt",
    "mux_protocol": "h2mux",
    "warp_mode": "custom",
    "mieru_transport": "TCP",
    "mieru_multiplexing": "MULTIPLEXING_LOW",
    "shadowsocks2022_method": "2022-blake3-aes-256-gcm",
    "lang": "en",
    "admin_lang": "en",
    "country": "ir",
    "log_level": "warning",
    "panel_mode": "standalone",
    "utls": "chrome",
}

WS_CAT_ICON = {
    "general": "fa-house",
    "admin": "fa-user-shield",
    "branding": "fa-palette",
    "user_limit": "fa-user-clock",
    "proxies": "fa-toggle-on",
    "shadowsocks": "fa-mask",
    "ssfaketls": "fa-mask",
    "shadowtls": "fa-user-secret",
    "tuic": "fa-bolt",
    "hysteria": "fa-gauge-high",
    "mieru": "fa-feather",
    "naive": "fa-ghost",
    "amnezia": "fa-shuffle",
    "wireguard": "fa-shield",
    "ssh": "fa-terminal",
    "ssr": "fa-mask",
    "kcp": "fa-wave-square",
    "restls": "fa-lock",
    "tls": "fa-lock",
    "http": "fa-globe",
    "tls_trick": "fa-wand-magic-sparkles",
    "mux": "fa-layer-group",
    "reality": "fa-gem",
    "telegram": "fa-paper-plane",
    "telegram_bot": "fa-robot",
    "adblock": "fa-ban",
    "warp": "fa-cloud",
    "domain_fronting": "fa-arrows-turn-right",
    "advanced": "fa-screwdriver-wrench",
    "too_advanced": "fa-triangle-exclamation",
}

WS_CAT_NAME = {
    "general": "General",
    "admin": "Admin area",
    "branding": "Your brand",
    "user_limit": "Limits for users",
    "proxies": "Which proxies are on",
    "shadowsocks": "Shadowsocks",
    "ssfaketls": "Shadowsocks FakeTLS",
    "shadowtls": "ShadowTLS",
    "tuic": "TUIC",
    "hysteria": "Hysteria",
    "mieru": "Mieru",
    "naive": "NaiveProxy",
    "amnezia": "AmneziaWG",
    "wireguard": "WireGuard",
    "ssh": "SSH",
    "ssr": "ShadowsocksR",
    "kcp": "KCP",
    "restls": "RestTLS",
    "tls": "TLS",
    "http": "HTTP",
    "tls_trick": "TLS tricks",
    "mux": "Multiplexing",
    "reality": "Reality",
    "telegram": "Telegram proxy",
    "telegram_bot": "Telegram bot",
    "adblock": "Blocking and filtering",
    "warp": "Cloudflare Warp",
    "domain_fronting": "Domain fronting",
    "advanced": "Advanced",
    "too_advanced": "For experts only",
}

WS_CAT_DESC = {
    "general": "Language, country and the settings the whole panel is built on.",
    "admin": "How the admin area behaves.",
    "branding": "The name, the link and the free text your users see.",
    "user_limit": "How much traffic and how many days a new user gets, and what happens when the limit is reached.",
    "proxies": "Turn each proxy type on or off and set the paths they use.",
    "tls": "Certificates and the secure layer between the client and the server.",
    "http": "Plain connections without a certificate.",
    "tls_trick": "Small tricks that break the traffic into pieces so filtering tools have a harder time.",
    "mux": "Carry several connections inside one, which makes things faster on a busy line.",
    "reality": "Reality keys and the fake sites the traffic hides behind.",
    "telegram": "The Telegram proxy that runs on this server.",
    "telegram_bot": "The bot your users can talk to.",
    "adblock": "Block ads, adult sites, torrent traffic and local addresses.",
    "warp": "Send some or all of the outgoing traffic through Cloudflare Warp.",
    "domain_fronting": "Show one domain to the outside world while talking to another.",
    "advanced": "Settings you only need in special cases.",
    "too_advanced": "Changing these without knowing what they do can break the panel.",
}


WS_CAT_ICON.update({
    "access": "fa-right-to-bracket",
    "paths": "fa-route",
    "ports": "fa-plug",
    "dns": "fa-globe",
    "guardserver": "fa-user-shield",
    "notify": "fa-bell",
    "parent": "fa-sitemap",
})

WS_CAT_NAME.update({
    "access": "Panel entrance links",
    "paths": "Address of each protocol",
    "ports": "Ports the server listens on",
    "dns": "DNS and Cloudflare",
    "guardserver": "Server protection",
    "notify": "Bot notifications",
    "parent": "Parent panel",
})

WS_CAT_DESC.update({
    "access": "The web address you open the panel with, and the one your users open.",
    "paths": "The piece of address each protocol is served on. Change these only if a link stopped working.",
    "ports": "Which ports the server answers on.",
    "dns": "Where domain names are looked up, and the key that lets the panel manage your Cloudflare records.",
    "guardserver": "Keeps the server quiet for anyone who is not one of your users.",
    "notify": "What the Telegram bot tells your users, and when.",
    "parent": "Only needed when this server is run by another panel.",
})


def ws_key_id(key):
    name = getattr(key, "name", None)
    if name:
        return str(name)
    return str(key)


def ws_txt(msg, fallback=""):
    try:
        out = str(msg)
    except Exception:
        return fallback
    if out.startswith("config.") or out.startswith("lang.") or out.startswith("lib."):
        return fallback
    return out


def ws_pretty_name(key):
    words = ws_key_id(key).replace("_", " ").strip()
    if not words:
        return ""
    return words[:1].upper() + words[1:]


def ws_label(key):
    return ws_txt(_("config." + ws_key_id(key) + ".label"), ws_pretty_name(key))


def ws_desc(key):
    return ws_txt(_("config." + ws_key_id(key) + ".description"), "")


def ws_kind_of(key):
    n = ws_key_id(key)
    if n == "warp_sites":
        return "long"
    if n == "branding_freetext":
        return "rich"
    if n == "ech_domains":
        return "list"
    if "secret" in n:
        return "uuid"
    if n.startswith("path_") or "proxy_path" in n:
        return "path"
    if "port" in n and "transport" not in n:
        return "port"
    return "text"


def ws_hint_for(key):
    n = ws_key_id(key)
    kind = ws_kind_of(key)
    if kind == "port":
        return "8443"
    if kind == "path":
        return "abc123"
    if "domain" in n:
        return "example.com"
    return ""


def ws_fresh_set():
    try:
        return getattr(g, "_ws_fresh", None) or set()
    except Exception:
        return set()


def ws_note_fresh(key):
    try:
        if not hasattr(g, "_ws_fresh"):
            g._ws_fresh = set()
        g._ws_fresh.add(ws_key_id(key))
    except Exception:
        pass


def ws_new_path():
    import random
    pool = "abcdefghijklmnopqrstuvwxyz0123456789"
    out = ""
    for _i in range(10):
        out += random.choice(pool)
    return out


def ws_as_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ["true", "1", "yes", "y", "on"]


def ws_same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return ws_as_bool(a) == ws_as_bool(b)
    left = "" if a is None else str(a).strip()
    right = "" if b is None else str(b).strip()
    return left == right


def ws_walk_fields(form):
    for name in list(getattr(form, "_fields", None) or []):
        holder = getattr(form._fields[name], "form", None)
        if holder is None:
            continue
        for one in holder:
            yield one


def ws_bad_fields(form):
    bad = set()
    for one in ws_walk_fields(form):
        if one.errors:
            bad.add(one.short_name)
    return bad


def ws_nice(form, key_name):
    for one in ws_walk_fields(form):
        if one.short_name == key_name:
            return str(one.label.text)
    return str(key_name).replace("_", " ")


def ws_domain_msg(key):
    return str(_("@F@ must be a plain domain like example.com, or left empty.")).replace("@F@", ws_label(key))


def ws_uuid_msg(key):
    return str(_("@F@ must be a UUID. Press the dice button to build a fresh one.")).replace("@F@", ws_label(key))


def ws_path_msg(key):
    return str(_("@F@ may only hold English letters and digits, with no slash or space.")).replace("@F@", ws_label(key))


def ws_port_msg(key):
    return str(_("@F@ must be a port number, or several of them split by a comma.")).replace("@F@", ws_label(key))


def ws_num_msg(key):
    return str(_("@F@ only takes digits.")).replace("@F@", ws_label(key))


def ws_pair_msg(key):
    return str(_("@F@ must be two numbers with a dash between them, for example 10-20.")).replace("@F@", ws_label(key))


def ws_port_reserved_msg():
    return str(_("Ports 80 and 443 belong to the panel itself, so no other service can take them. Please pick a different port."))


def ws_port_taken_msg(form, port, other_key):
    out = str(_("Port @P@ is already given to @F@. Please pick a different port."))
    return out.replace("@P@", str(port)).replace("@F@", ws_nice(form, other_key))


def ws_same_path_msg():
    return str(_("The admin path, the user path and the shared path must all be different from each other."))


def ws_tell_skipped(form, bad):
    if not bad:
        return
    names = ", ".join(sorted([ws_nice(form, one) for one in bad]))
    out = str(_("Everything else was saved. These settings kept their old value because what was typed is not valid: @LIST@"))
    hutils.flask.flash(out.replace("@LIST@", names), "warning")


def ws_check_need_reset(old_configs):
    restart_mode = ApplyMode.nothing
    for c in old_configs:
        try:
            if c.apply_mode == ApplyMode.nothing:
                continue
        except Exception:
            continue
        if restart_mode == ApplyMode.reinstall:
            break
        try:
            if not ws_same(old_configs.get(c), hconfig(c)):
                restart_mode = c.apply_mode
        except Exception:
            continue
    try:
        old_admin_path = old_configs.get(ConfigEnum.proxy_path_admin)
        if old_admin_path and old_admin_path != hconfig(ConfigEnum.proxy_path_admin):
            g.new_proxy_path = hconfig(ConfigEnum.proxy_path_admin)
            g.force_proxy_path = g.proxy_path
    except Exception:
        pass
    try:
        old_package = old_configs.get(ConfigEnum.package_mode)
        if old_package is not None and not ws_same(old_package, hconfig(ConfigEnum.package_mode)):
            return hiddify.reinstall_action(do_update=True)
    except Exception:
        pass
    return hutils.flask.flash_config_success(restart_mode=restart_mode, domain_changed=False)


def ws_meta_map():
    fresh = ws_fresh_set()
    meta = {}
    for k in ConfigEnum:
        try:
            mode_txt = str(k.apply_mode)
        except Exception:
            mode_txt = ""
        if "reinstall" in mode_txt:
            mode = "reinstall"
        elif not mode_txt or "nothing" in mode_txt:
            mode = ""
        else:
            mode = "apply"
        one = {}
        one["mode"] = mode
        one["kind"] = ws_kind_of(k)
        one["hint"] = ws_hint_for(k)
        one["fresh"] = ws_key_id(k) in fresh
        meta[ws_key_id(k)] = one
    return meta


def ws_ui_text():
    out = {}
    out["copied"] = str(_("Copied"))
    out["copyFail"] = str(_("Could not copy. Please select the text and copy it by hand."))
    out["nothingToCopy"] = str(_("This box is empty, there is nothing to copy."))
    out["madeNew"] = str(_("A fresh value was built for you. Do not forget to save."))
    out["on"] = str(_("On"))
    out["off"] = str(_("Off"))
    out["oneChange"] = str(_("1 setting was changed and is waiting to be saved"))
    out["someChanges"] = str(_("@N@ settings were changed and are waiting to be saved"))
    out["undone"] = str(_("Your changes were rolled back."))
    out["saving"] = str(_("Saving..."))
    out["oneFound"] = str(_("1 setting matches your search"))
    out["someFound"] = str(_("@N@ settings match your search"))
    return out


def ws_field_map(form):
    out = {}
    for one in ws_walk_fields(form):
        try:
            name = one.short_name
        except Exception:
            continue
        if not name or name == "description_for_fieldset":
            continue
        if name not in out:
            out[name] = one
    return out


def ws_rand_word(n):
    pool = "abcdefghijkmnpqrstuvwxyz23456789"
    out = ""
    for i in range(n):
        out += pool[ws_uuid.uuid4().int % len(pool)]
    return out


def ws_domain_pick(key):
    seed = 0
    for ch in ws_key_id(key):
        seed += ord(ch)
    return WS_FILLER_DOMAINS[seed % len(WS_FILLER_DOMAINS)]


def ws_choice_values(field):
    vals = []
    try:
        for pair in (field.choices or []):
            if isinstance(pair, (list, tuple)) and len(pair) > 0:
                vals.append(pair[0])
            else:
                vals.append(pair)
    except Exception:
        return []
    return vals


def ws_is_empty(val):
    if val is None:
        return True
    if isinstance(val, str):
        return not val.strip()
    if isinstance(val, (list, tuple, set, dict)):
        return len(val) == 0
    return False


def ws_best_for(key, field=None):
    """The value we hand a setting that was left empty, or None to keep it empty."""
    kid = ws_key_id(key)
    if kid in WS_KEEP_EMPTY:
        return None
    ftype = str(getattr(field, "type", "")) if field is not None else ""
    if ftype in ("SwitchField", "BooleanField", "SelectMultipleField"):
        return None
    if ftype == "SelectField":
        vals = ws_choice_values(field)
        if not vals:
            return None
        want = WS_BEST_CHOICE.get(kid)
        if want is not None:
            for v in vals:
                if str(v).lower() == str(want).lower():
                    return v
        for v in vals:
            if not ws_is_empty(v):
                return v
        return None
    if kid in WS_BEST_DEFAULT:
        val = WS_BEST_DEFAULT[kid]
        if val == "@uuid@":
            return str(ws_uuid.uuid4())
        if val == "@path@":
            return ws_new_path()
        if val == "@word@":
            return ws_rand_word(20)
        return val
    if kid.endswith("_fakedomain") or kid.endswith("_server_name"):
        return ws_domain_pick(kid)
    return None


def ws_default_for(key):
    pick = ws_best_for(key)
    if pick is None or ws_is_empty(pick):
        return ws_domain_pick(key)
    return pick


def ws_prefill(form):
    """Give every empty box a sensible starting value so nobody stares at a blank field."""
    for one in ws_walk_fields(form):
        try:
            name = one.short_name
        except Exception:
            continue
        if not name or name == "description_for_fieldset":
            continue
        if getattr(one, "errors", None):
            continue
        if not ws_is_empty(getattr(one, "data", None)):
            continue
        pick = ws_best_for(name, one)
        if pick is None or ws_is_empty(pick):
            continue
        try:
            one.data = pick
            ws_note_fresh(name)
        except Exception:
            pass


def ws_home_of(name, fallback):
    return WS_KEY_HOME.get(ws_key_id(name), fallback)


def ws_sort_fields(form):
    """Work out which card each setting belongs on."""
    homes = {}
    order = []
    seen = set()
    for cat_name in list(getattr(form, "_fields", None) or []):
        holder = getattr(form._fields[cat_name], "form", None)
        if holder is None:
            continue
        for one in holder:
            nm = getattr(one, "short_name", "")
            if not nm or nm == "description_for_fieldset":
                continue
            if nm in seen:
                continue
            seen.add(nm)
            home = ws_home_of(nm, str(cat_name))
            if home not in homes:
                homes[home] = []
                order.append(home)
            homes[home].append(one)
    return homes, order


def ws_build_cat(form, cat, fields=None):
    if fields is None:
        try:
            inner = form[cat]
        except Exception:
            return None
        if inner is None:
            return None
        fields = []
        try:
            for one in inner:
                if one.short_name == "description_for_fieldset":
                    continue
                fields.append(one)
        except Exception:
            return None
    if not fields:
        return None
    bad = 0
    for one in fields:
        if getattr(one, "errors", None):
            bad += 1
    item = {}
    item["id"] = cat
    item["icon"] = WS_CAT_ICON.get(cat, "fa-sliders")
    item["name"] = str(_(WS_CAT_NAME.get(cat, ws_pretty_name(cat))))
    hint = WS_CAT_DESC.get(cat, "")
    item["desc"] = str(_(hint)) if hint else ""
    item["fields"] = fields
    item["n"] = len(fields)
    item["bad"] = bad
    return item


def ws_render_settings(form):
    ws_prefill(form)
    homes, order = ws_sort_fields(form)

    groups = []
    used = set()
    field_count = 0
    bad_count = 0

    for gid, icon, title, cats in WS_GROUP_DEFS:
        picked = []
        total = 0
        for cat in cats:
            if cat not in homes:
                continue
            used.add(cat)
            item = ws_build_cat(form, cat, homes[cat])
            if item is None:
                continue
            picked.append(item)
            total += item["n"]
            bad_count += item["bad"]
        if not picked:
            continue
        one = {}
        one["id"] = gid
        one["icon"] = icon
        one["name"] = str(_(title))
        one["n"] = total
        one["cats"] = picked
        groups.append(one)
        field_count += total

    leftovers = []
    left_total = 0
    for cat in order:
        if cat in used or cat == "hidden":
            continue
        item = ws_build_cat(form, cat, homes[cat])
        if item is None:
            continue
        leftovers.append(item)
        left_total += item["n"]
        bad_count += item["bad"]
    if leftovers:
        one = {}
        one["id"] = "more"
        one["icon"] = "fa-ellipsis"
        one["name"] = str(_("Other settings"))
        one["n"] = left_total
        one["cats"] = leftovers
        groups.append(one)
        field_count += left_total

    stats = {}
    stats["groups"] = len(groups)
    stats["fields"] = field_count
    stats["fresh"] = len(ws_fresh_set())
    stats["bad"] = bad_count

    return render_template("config.html", form=form, st_groups=groups,
                           st_meta=ws_meta_map(), st_stats=stats, st_text=ws_ui_text())
