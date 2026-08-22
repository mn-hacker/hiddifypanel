from hiddifypanel import hutils
from hiddifypanel.models.config_enum import ApplyMode
from hiddifypanel.models.role import Role
import wtforms as wtf
from flask_wtf import FlaskForm
from flask_bootstrap import SwitchField
from flask_babel import gettext as _
from flask import render_template, request, jsonify
from loguru import logger


from hiddifypanel.models import ConfigEnum, Child, get_hconfigs, BoolConfig, ConfigEnum, hconfig, Proxy, set_hconfig
from hiddifypanel.database import db
from wtforms.fields import *
from hiddifypanel.panel import hiddify
from flask_classful import FlaskView, route
from hiddifypanel.auth import login_required


# Where every panel wide switch belongs on the page, with the face it wears.
# A switch that is not named here still shows up, in the last group, so a
# switch can never go missing when the panel gains a new one.
# Switches the panel gained later than the database of an older install.
# Only what is named here is ever written, so no unused switch creeps onto the page.
WS_MUST_EXIST = ('amnezia_enable',)

WS_SWITCH_META = {
    'vless_enable': {'group': 'core', 'icon': 'fa-bolt', 'rgb': '124, 58, 237'},
    'vmess_enable': {'group': 'core', 'icon': 'fa-shield', 'rgb': '59, 130, 246'},
    'trojan_enable': {'group': 'core', 'icon': 'fa-mask', 'rgb': '16, 185, 129'},
    'reality_enable': {'group': 'core', 'icon': 'fa-eye-slash', 'rgb': '6, 182, 212'},

    'tcp_enable': {'group': 'transport', 'icon': 'fa-arrows-left-right', 'rgb': '99, 102, 241'},
    'ws_enable': {'group': 'transport', 'icon': 'fa-plug', 'rgb': '16, 185, 129'},
    'grpc_enable': {'group': 'transport', 'icon': 'fa-code-branch', 'rgb': '245, 158, 11'},
    'httpupgrade_enable': {'group': 'transport', 'icon': 'fa-arrow-up-right-dots', 'rgb': '168, 85, 247'},
    'xhttp_enable': {'group': 'transport', 'icon': 'fa-diagram-project', 'rgb': '236, 72, 153'},
    'quic_enable': {'group': 'transport', 'icon': 'fa-gauge-high', 'rgb': '14, 165, 233'},
    'h2_enable': {'group': 'transport', 'icon': 'fa-layer-group', 'rgb': '20, 184, 166'},
    'kcp_enable': {'group': 'transport', 'icon': 'fa-water', 'rgb': '129, 140, 248'},

    'tuic_enable': {'group': 'extra', 'icon': 'fa-rocket', 'rgb': '244, 63, 94'},
    'hysteria_enable': {'group': 'extra', 'icon': 'fa-wind', 'rgb': '34, 197, 94'},
    'mieru_enable': {'group': 'extra', 'icon': 'fa-feather', 'rgb': '249, 115, 22'},
    'naive_enable': {'group': 'extra', 'icon': 'fa-feather-pointed', 'rgb': '132, 204, 22'},
    'amnezia_enable': {'group': 'extra', 'icon': 'fa-user-secret', 'rgb': '217, 70, 239'},
    'wireguard_enable': {'group': 'extra', 'icon': 'fa-shield-halved', 'rgb': '251, 146, 60'},
    'ssh_server_enable': {'group': 'extra', 'icon': 'fa-terminal', 'rgb': '100, 116, 139'},
    'shadowsocks2022_enable': {'group': 'extra', 'icon': 'fa-key', 'rgb': '45, 212, 191'},
    'ssfaketls_enable': {'group': 'extra', 'icon': 'fa-mask', 'rgb': '148, 163, 184'},
    'shadowtls_enable': {'group': 'extra', 'icon': 'fa-clone', 'rgb': '96, 165, 250'},
    'ssr_enable': {'group': 'extra', 'icon': 'fa-shuffle', 'rgb': '167, 139, 250'},
    'v2ray_enable': {'group': 'extra', 'icon': 'fa-v', 'rgb': '56, 189, 248'},
    'telegram_enable': {'group': 'extra', 'icon': 'fa-paper-plane', 'rgb': '14, 165, 233'},
    'http_proxy_enable': {'group': 'extra', 'icon': 'fa-globe', 'rgb': '234, 179, 8'},

    'mux_enable': {'group': 'feature', 'icon': 'fa-code-merge', 'rgb': '245, 158, 11'},
    'tls_fragment_enable': {'group': 'feature', 'icon': 'fa-scissors', 'rgb': '6, 182, 212'},
    'tls_padding_enable': {'group': 'feature', 'icon': 'fa-braille', 'rgb': '139, 92, 246'},
    'ech_enable': {'group': 'feature', 'icon': 'fa-lock', 'rgb': '16, 185, 129'},
    'sub_full_xray_json_enable': {'group': 'feature', 'icon': 'fa-file-code', 'rgb': '59, 130, 246'},
    'warp_enable': {'group': 'feature', 'icon': 'fa-cloud', 'rgb': '251, 146, 60'},
}

# The face of every proxy family in the detailed part.
WS_CDN_META = {
    'direct': {'icon': 'fa-bolt', 'rgb': '16, 185, 129'},
    'CDN': {'icon': 'fa-cloud', 'rgb': '59, 130, 246'},
    'relay': {'icon': 'fa-diagram-project', 'rgb': '245, 158, 11'},
    'Fake': {'icon': 'fa-mask', 'rgb': '107, 114, 128'},
}

WS_PROTO_META = {
    'vless': {'icon': 'fa-bolt', 'rgb': '124, 58, 237'},
    'vmess': {'icon': 'fa-shield', 'rgb': '59, 130, 246'},
    'trojan': {'icon': 'fa-mask', 'rgb': '16, 185, 129'},
    'ss': {'icon': 'fa-key', 'rgb': '45, 212, 191'},
    'ssr': {'icon': 'fa-shuffle', 'rgb': '167, 139, 250'},
    'v2ray': {'icon': 'fa-v', 'rgb': '56, 189, 248'},
    'mieru': {'icon': 'fa-feather', 'rgb': '249, 115, 22'},
    'naive': {'icon': 'fa-feather-pointed', 'rgb': '132, 204, 22'},
    'amnezia': {'icon': 'fa-user-secret', 'rgb': '217, 70, 239'},
    'other': {'icon': 'fa-layer-group', 'rgb': '148, 163, 184'},
}


def ws_group_titles():
    'The four groups the switches are gathered in, in the order they are shown.'
    return [
        {'key': 'core', 'label': str(_('Core Protocols')), 'icon': 'fa-shield-halved', 'rgb': '124, 58, 237'},
        {'key': 'transport', 'label': str(_('Transport Layers')), 'icon': 'fa-arrows-left-right', 'rgb': '59, 130, 246'},
        {'key': 'extra', 'label': str(_('Extra Protocols')), 'icon': 'fa-layer-group', 'rgb': '16, 185, 129'},
        {'key': 'feature', 'label': str(_('Panel Features')), 'icon': 'fa-sliders', 'rgb': '245, 158, 11'},
        {'key': 'other', 'label': str(_('Other Switches')), 'icon': 'fa-ellipsis', 'rgb': '148, 163, 184'},
    ]


class ProxyAdmin(FlaskView):
    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        self.ws_ensure_switches()
        return self.ws_render(get_global_config_form(), get_all_proxy_form())

    def ws_ensure_switches(self):
        """Gives a switch of WS_MUST_EXIST the database row it is missing.

        The form of this page is built from the rows in the database, so a
        switch that never got a row, like AmneziaWG on an install that is
        older than it, simply is not drawn. The row is written as off, so
        nothing changes for a single user until it is turned on by hand.
        """
        made = []
        try:
            child_id = Child.current().id
            for name in WS_MUST_EXIST:
                try:
                    ek = ConfigEnum[name]
                except BaseException:
                    logger.debug(f'watashi: this panel does not know the switch {name} at all')
                    continue
                if ek == ConfigEnum.not_found:
                    continue
                seen = BoolConfig.query.filter(BoolConfig.key == ek,
                                               BoolConfig.child_id == child_id).first()
                if seen is not None:
                    continue
                set_hconfig(ek, False, commit=False)
                made.append(name)
            if made:
                db.session.commit()
                logger.info(f'watashi: switches that had no row yet were written as off: {made}')
        except BaseException as err:
            db.session.rollback()
            logger.error(f'watashi: cannot make room for a missing switch: {err}')
        return made

    def ws_render(self, global_config_form, detailed_config_form):
        'Draws the page, always with everything the theme needs to lay it out.'
        return render_template(
            'proxy.html',
            global_config_form=global_config_form,
            detailed_config_form=detailed_config_form,
            ws_meta=WS_SWITCH_META,
            ws_groups=ws_group_titles(),
            ws_cdn_meta=WS_CDN_META,
            ws_proto_meta=WS_PROTO_META,
            ws_save_url=self.ws_save_url(),
            ws_links=self.ws_links(),
            ws_proxy_url=self.ws_url('ws_proxy'),
            ws_reset_url=self.ws_url('ws_reset'),
        )

    def ws_links(self):
        """The two older admin pages this page still sends the admin to.

        Their addresses are built here and never inside the template,
        because a template that cannot build an address takes the whole
        page down with it.
        """
        out = {}
        for name, endpoint in (('names', 'flask.proxy.index_view'),
                               ('reset', 'flask.proxy.reset_proxies')):
            try:
                out[name] = hutils.flask.hurl_for(endpoint)
            except BaseException as err:
                logger.debug(f'watashi: the proxy page cannot link to {endpoint}: {err}')
                out[name] = ''
        return out

    def ws_url(self, name):
        'One address of this very page, built here so the template cannot fail.'
        try:
            return hutils.flask.hurl_for(f'admin.ProxyAdmin:{name}')
        except BaseException as err:
            logger.debug(f'watashi: cannot build the {name} address: {err}')
            return ''

    def ws_sync_proxies(self):
        'A child node tells the parent that its proxies moved.'
        try:
            if hutils.node.is_child():
                hutils.node.run_node_op_in_bg(
                    hutils.node.child.sync_with_parent,
                    *[hutils.node.child.SyncFields.proxies])
        except BaseException as err:
            logger.debug(f'watashi: the proxies were saved but the parent was not told: {err}')

    def ws_proxy_dict(self, row):
        'Everything the popup shows about one single proxy.'
        import json
        return {
            'id': row.id,
            'name': row.name or '',
            'enable': bool(row.enable),
            'proto': str(row.proto or ''),
            'transport': str(row.transport or ''),
            'cdn': str(row.cdn or ''),
            'l3': str(row.l3 or ''),
            'params': json.dumps(row.params or {}, ensure_ascii=False, indent=2),
        }

    def ws_pick_proxy(self, num):
        'Only a proxy of this very node may be read or written from here.'
        return Proxy.query.filter(Proxy.id == num,
                                 Proxy.child_id == Child.current().id).first()

    @route('ws_proxy', methods=['POST'])
    def ws_proxy(self):
        """Reads or writes one single proxy, for the popup on the page.

        The protocol, the transport and the family are what make a proxy
        that proxy, so they are never written here. What can be changed is
        the name the user sees, the security layer, the extra parameters,
        and whether it is handed out at all.
        """
        import json
        from hiddifypanel.models.proxy import ProxyL3
        body = request.get_json(silent=True) or {}
        try:
            num = int(body.get('id'))
        except BaseException:
            return jsonify({'ok': False, 'msg': str(_('config.validation-error'))}), 400

        row = self.ws_pick_proxy(num)
        if row is None:
            return jsonify({'ok': False, 'msg': str(_('This proxy was not found any more. Refresh the page.'))}), 404

        levels = [str(x) for x in ProxyL3]
        if body.get('read'):
            return jsonify({'ok': True, 'proxy': self.ws_proxy_dict(row), 'levels': levels})

        name = str(body.get('name') or '').strip()
        if not name:
            return jsonify({'ok': False, 'msg': str(_('A name cannot be left empty.'))}), 400
        name = name[:200]

        level = str(body.get('l3') or '')
        if level and level not in levels:
            return jsonify({'ok': False, 'msg': str(_('config.validation-error'))}), 400

        raw = body.get('params')
        if isinstance(raw, dict):
            params = raw
        elif isinstance(raw, str):
            text = raw.strip()
            if not text:
                params = {}
            else:
                try:
                    params = json.loads(text)
                except BaseException:
                    return jsonify({'ok': False, 'msg': str(_('This has to be sound JSON.'))}), 400
        else:
            params = row.params or {}
        if not isinstance(params, dict):
            return jsonify({'ok': False, 'msg': str(_('This has to be sound JSON.'))}), 400

        wants_on = bool(body.get('enable'))
        moved = 0
        if (row.name or '') != name:
            row.name = name
            moved += 1
        if bool(row.enable) != wants_on:
            row.enable = wants_on
            moved += 1
        if level and str(row.l3 or '') != level:
            row.l3 = level
            moved += 1
        if (row.params or {}) != params:
            row.params = params
            moved += 1

        if not moved:
            return jsonify({'ok': True, 'saved': 0,
                            'proxy': self.ws_proxy_dict(row),
                            'msg': str(_('Nothing was left to save.'))})
        try:
            db.session.commit()
        except BaseException as err:
            db.session.rollback()
            logger.error(f'watashi: a single proxy could not be saved: {err}')
            return jsonify({'ok': False, 'msg': str(_('The proxy could not be saved.'))}), 500

        hutils.proxy.get_proxies.invalidate_all()
        self.ws_sync_proxies()
        return jsonify({'ok': True, 'saved': 1,
                        'proxy': self.ws_proxy_dict(row),
                        'msg': str(_('The proxy was saved.')),
                        'apply': self.ws_apply_ask(ApplyMode.apply_config)})

    @route('ws_reset', methods=['POST'])
    def ws_reset(self):
        """Puts back the proxies the panel ships with, and only those missing.

        The older page did this with a bulk insert, so every proxy that was
        already there got a second copy and the list slowly filled with
        twins. Here only what is missing is written, which makes pressing
        this twice harmless.
        """
        from hiddifypanel.panel.init_db import get_proxy_rows_v1
        child_id = Child.current().id
        try:
            wanted = list(get_proxy_rows_v1())
        except BaseException as err:
            logger.error(f'watashi: cannot read the proxies the panel ships with: {err}')
            return jsonify({'ok': False, 'msg': str(_('config.validation-error'))}), 500

        here = {(p.name or '') for p in Proxy.query.filter(Proxy.child_id == child_id).all()}
        added = 0
        for row in wanted:
            title = row.name or ''
            if not title or title in here:
                continue
            here.add(title)
            row.child_id = child_id
            db.session.add(row)
            added += 1

        if not added:
            db.session.rollback()
            return jsonify({'ok': True, 'added': 0,
                            'msg': str(_('Nothing was missing. Every default proxy is already here.'))})
        try:
            db.session.commit()
        except BaseException as err:
            db.session.rollback()
            logger.error(f'watashi: the default proxies could not be brought back: {err}')
            return jsonify({'ok': False, 'msg': str(_('config.validation-error'))}), 500

        hutils.proxy.get_proxies.invalidate_all()
        self.ws_sync_proxies()
        return jsonify({'ok': True, 'added': added,
                        'msg': str(_('@N@ proxies were brought back.')).replace('@N@', str(added)),
                        'apply': self.ws_apply_ask(ApplyMode.apply_config)})

    def ws_save_url(self):
        'The address the page saves to without leaving the page.'
        try:
            return hutils.flask.hurl_for('admin.ProxyAdmin:ws_save')
        except BaseException as err:
            logger.debug(f'watashi: cannot build the save address of the proxy page: {err}')
            return ''

    def ws_allowed_switches(self):
        'Only the switches this page really draws may be written by it.'
        names = set()
        try:
            for field in get_global_config_form():
                if field.name and field.name.endswith('_enable'):
                    names.add(field.name)
        except BaseException as err:
            logger.error(f'watashi: cannot read the switches of the proxy page: {err}')
        return names

    def ws_apply_ask(self, restart_mode):
        """The button the panel wants pressed before a change reaches the configs.

        Saving only writes the change in the database. The configs are built
        again when the settings are applied, so the page carries the button
        inside a message that waits until it is pressed.
        """
        if restart_mode == ApplyMode.nothing:
            return None
        try:
            url = hutils.flask.hurl_for('admin.Actions:reinstall',
                                        complete_install=restart_mode == ApplyMode.reinstall,
                                        domain_changed=False)
        except BaseException as err:
            logger.debug(f'watashi: cannot build the address of the apply button: {err}')
            return None
        return {
            'url': url,
            'label': str(_('admin.config.apply_configs')),
            'busy': str(_('Applying...')),
            'text': str(_('The change is saved. Press the button so it reaches the configs.')),
        }

    @route('ws_save', methods=['POST'])
    def ws_save(self):
        """Saves the switches and the single proxies in one go.

        The page hands over only what the admin really changed, so a save
        never writes a value that was already there, and the answer says
        whether the configs have to be applied afterwards.
        """
        body = request.get_json(silent=True) or {}
        wanted_switches = body.get('globals') or {}
        wanted_proxies = body.get('proxies') or {}
        if not isinstance(wanted_switches, dict) or not isinstance(wanted_proxies, dict):
            return jsonify({'ok': False, 'msg': str(_('config.validation-error'))}), 400

        old_configs = get_hconfigs()
        allowed = self.ws_allowed_switches()
        switch_count = 0
        for key, value in wanted_switches.items():
            name = str(key)
            if name not in allowed:
                logger.debug(f'watashi: the proxy page asked for a switch it does not draw: {name}')
                continue
            try:
                ek = ConfigEnum[name]
            except BaseException:
                continue
            if ek == ConfigEnum.not_found:
                continue
            if bool(hconfig(ek)) == bool(value):
                continue
            set_hconfig(ek, bool(value), commit=False)
            switch_count += 1

        child_id = Child.current().id
        proxy_count = 0
        if wanted_proxies:
            pool = {p.id: p for p in Proxy.query.filter(Proxy.child_id == child_id).all()}
            for key, value in wanted_proxies.items():
                try:
                    num = int(key)
                except BaseException:
                    continue
                row = pool.get(num)
                if row is None:
                    logger.debug(f'watashi: the proxy page asked about a proxy that is gone: {key}')
                    continue
                if bool(row.enable) == bool(value):
                    continue
                row.enable = bool(value)
                proxy_count += 1

        if not switch_count and not proxy_count:
            return jsonify({'ok': True, 'saved': 0, 'msg': str(_('Nothing was left to save.'))})

        try:
            db.session.commit()
        except BaseException as err:
            db.session.rollback()
            logger.error(f'watashi: cannot save the proxy page: {err}')
            return jsonify({'ok': False, 'msg': str(_('The change could not be saved.'))}), 500

        hutils.proxy.get_proxies.invalidate_all()
        try:
            if hutils.node.is_child():
                fields = []
                if switch_count:
                    fields.append(hutils.node.child.SyncFields.hconfigs)
                if proxy_count:
                    fields.append(hutils.node.child.SyncFields.proxies)
                if fields:
                    hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *fields)
        except BaseException as err:
            logger.debug(f'watashi: cannot tell the parent about the change: {err}')

        restart_mode = ApplyMode.nothing
        if proxy_count:
            restart_mode = ApplyMode.apply_config
        for c in old_configs:
            if c.apply_mode == ApplyMode.nothing:
                continue
            if restart_mode == ApplyMode.reinstall:
                break
            try:
                if old_configs[c] != hconfig(c):
                    restart_mode = c.apply_mode
            except BaseException:
                continue

        return jsonify({'ok': True,
                        'saved': switch_count + proxy_count,
                        'switches': switch_count,
                        'proxies': proxy_count,
                        'apply': self.ws_apply_ask(restart_mode)})

    def post(self):
        """The plain form save, kept for the case the page has no javascript."""
        global_config_form = get_global_config_form()
        all_proxy_form = get_all_proxy_form()

        if global_config_form.submit_global.data and global_config_form.validate_on_submit():
            old_configs = get_hconfigs()
            for k, vs in global_config_form.data.items():
                try:
                    ek = ConfigEnum[k]
                except BaseException:
                    # submit buttons and the token carry no config behind them
                    continue
                if ek != ConfigEnum.not_found:
                    set_hconfig(ek, vs, commit=False)

            db.session.commit()
            hutils.proxy.get_proxies.invalidate_all()
            if hutils.node.is_child():
                hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.hconfigs])
            hiddify.check_need_reset(old_configs)
            all_proxy_form = get_all_proxy_form(True)

        elif all_proxy_form.submit_detail.data and all_proxy_form.validate_on_submit():
            child_id = Child.current().id
            pool = {p.id: p for p in Proxy.query.filter(Proxy.child_id == child_id).all()}
            for cdn, vs in all_proxy_form.data.items():
                if not isinstance(vs, dict):
                    continue
                for proto, v in vs.items():
                    if not isinstance(v, dict):
                        continue
                    for proxy_id, enable in v.items():
                        if not proxy_id.startswith("p_"):
                            continue
                        try:
                            num = int(proxy_id.split('_')[-1])
                        except BaseException:
                            continue
                        row = pool.get(num)
                        if row is None:
                            # a proxy of another node, or one that was reset away
                            continue
                        row.enable = bool(enable)

            db.session.commit()
            hutils.proxy.get_proxies.invalidate_all()
            if hutils.node.is_child():
                hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.proxies])
            hutils.flask.flash_config_success(restart_mode=ApplyMode.apply_config, domain_changed=False)
            global_config_form = get_global_config_form(True)
        else:
            hutils.flask.flash((_('config.validation-error')), 'danger')

        return self.ws_render(global_config_form, all_proxy_form)


def get_global_config_form(empty=False):
    boolconfigs = BoolConfig.query.filter(BoolConfig.child_id == Child.current().id).all()

    class DynamicForm(FlaskForm):
        pass

    # Categories that should NOT appear in Proxy page (only in Settings)
    excluded_categories = ['telegram_bot', 'user_limit', 'adblock', 'general', 'advanced']

    for cf in boolconfigs:
        if cf.key.category == 'hidden':
            continue
        # Exclude non-proxy categories from this page
        if str(cf.key.category) in excluded_categories:
            continue
        if not cf.key.endswith("_enable") or cf.key in [ConfigEnum.mux_brutal_enable, ConfigEnum.mux_padding_enable, ConfigEnum.hysteria_obfs_enable]:
            continue
        field = SwitchField(_(f'config.{cf.key}.label'), default=cf.value, description=_(f'config.{cf.key}.description'))
        setattr(DynamicForm, f'{cf.key}', field)
    setattr(DynamicForm, "submit_global", wtf.fields.SubmitField(_('Submit')))
    if empty:
        return DynamicForm(None)
    return DynamicForm()


def get_all_proxy_form(empty=False):
    proxies = hutils.proxy.get_proxies(Child.current().id)
    categories1 = sorted([c for c in {c.cdn: 1 for c in proxies}])

    class DynamicForm(FlaskForm):
        pass

    for cdn in categories1:
        class CDNForm(FlaskForm):
            class Meta:
                csrf = False
            pass
        cdn_proxies = [c for c in proxies if c.cdn == cdn]
        pgroup = {
            'wireguard': 'other',
            'tuic': 'other',
            'ssh': 'other',
            'hysteria2': 'other',
        }
        protos = sorted([c for c in {pgroup.get(c.proto, c.proto): 1 for c in cdn_proxies}])
        for proto in protos:
            class ProtoForm(FlaskForm):
                class Meta:
                    csrf = False
                pass
            proto_proxies = [c for c in cdn_proxies if pgroup.get(c.proto, c.proto) == proto]
            for proxy in proto_proxies:
                field = SwitchField(proxy.name, default=proxy.enable, description=f"l3:{proxy.l3} transport:{proxy.transport}")
                setattr(ProtoForm, f"p_{proxy.id}", field)

            multifield = wtf.fields.FormField(ProtoForm, proto)
            setattr(CDNForm, proto, multifield)
        field_name = cdn if cdn != "Fake" else _('config.domain_fronting.label')
        multifield = wtf.fields.FormField(CDNForm, field_name)
        setattr(DynamicForm, cdn, multifield)
    setattr(DynamicForm, "submit_detail", wtf.fields.SubmitField(_('Submit')))
    if empty:
        return DynamicForm(None)
    return DynamicForm()
