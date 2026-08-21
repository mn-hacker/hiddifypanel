import ipaddress
from hiddifypanel.auth import login_required, current_account
from hiddifypanel.database import db

from hiddifypanel.models import *
import re
from flask import g, flash, redirect  # type: ignore
from markupsafe import Markup

from flask_babel import gettext as __
from flask_babel import lazy_gettext as _
from hiddifypanel.panel.run_commander import Command, commander
from wtforms.validators import Regexp, ValidationError

from hiddifypanel.models import *
from hiddifypanel.panel import hiddify, custom_widgets
from .adminlte import AdminLTEModelView
from hiddifypanel import hutils

from loguru import logger
from flask import current_app
import ssl
import socket
import datetime as ws_dt
from flask import request, jsonify
from flask_admin import expose
# Define a custom field type for the related domains


# class ConfigDomainsField(SelectField):
#     def __init__(self, label=None, validators=None,*args, **kwargs):
#         kwargs.pop("allow_blank")
#         super().__init__(label, validators,*args, **kwargs)
#         self.choices=[(d.id,d.domain) for d in Doamin.query.filter(Domain.sub_link_only!=True).all()]


# --------------------------------------------------------------------------
# watashi: the new domains page
# Nothing here is allowed to be slow: the page itself only uses the cheap
# helpers. Anything that touches the network runs on demand from the routes
# at the bottom of this file.
# --------------------------------------------------------------------------

# Modes that the panel still supports but no longer recommends. They stay
# fully usable, they are only marked so nobody picks them by accident.
WS_OLD_MODES = ('reality', 'old_xtls_direct')
# What each mode expects the dns answer of the domain to be.
WS_MODE_HERE = ('direct', 'sub_link_only')          # the ip of this server
WS_MODE_CDN = ('cdn', 'auto_cdn_ip', 'worker')      # the ip of the cdn
WS_MODE_RELAY = ('relay',)                          # the ip of the relay machine
WS_MODE_DECOY = ('reality', 'special_reality_tcp', 'special_reality_xhttp',
                 'special_reality_grpc', 'old_xtls_direct')  # a foreign site
WS_MODE_NOWHERE = ('fake',)                         # nothing is asked at all
# kept because the older parts of this file still read them
WS_INDIRECT_MODES = ('cdn', 'auto_cdn_ip', 'relay', 'worker', 'fake')
WS_STRAIGHT_MODES = ('direct', 'reality', 'old_xtls_direct',
                     'special_reality_tcp', 'special_reality_xhttp', 'special_reality_grpc')

# A test answer is kept this long, so opening the page does not start the whole
# network work again. The admin can always ask for a fresh answer.
WS_HEALTH_TTL = 6 * 60 * 60
WS_HEALTH_FILE = '/tmp/hiddify_watashi_domain_health.json'


def ws_mode_name(mode):
    return mode.name if hasattr(mode, 'name') else str(mode or '')


def ws_mode_label(mode):
    name = ws_mode_name(mode)
    known = {
        'direct': __('Direct mode'),
        'sub_link_only': __('Subscription link only'),
        'cdn': __('CDN'),
        'auto_cdn_ip': __('CDN with auto clean IP'),
        'relay': __('Relay'),
        'worker': __('Cloudflare Worker'),
        'fake': __('Fake name'),
        'reality': __('Reality (old)'),
        'special_reality_tcp': __('Reality TCP'),
        'special_reality_xhttp': __('Reality XHTTP'),
        'special_reality_grpc': __('Reality gRPC'),
        'old_xtls_direct': __('XTLS Direct (old)'),
    }
    return known.get(name, name.replace('_', ' '))


def ws_mode_family(mode):
    name = ws_mode_name(mode)
    if name in WS_MODE_CDN:
        return 'cdn'
    if name in WS_MODE_DECOY:
        return 'reality'
    if name == 'sub_link_only':
        return 'sub'
    if name in ('relay', 'fake'):
        return 'helper'
    return 'direct'


def ws_mode_tone(mode):
    'The colour the page paints for this mode.'
    name = ws_mode_name(mode)
    tones = {
        'direct': 'direct',
        'sub_link_only': 'sub',
        'cdn': 'cdn',
        'auto_cdn_ip': 'autocdn',
        'relay': 'relay',
        'worker': 'relay',
        'fake': 'fake',
        'reality': 'oldxtls',
        'special_reality_tcp': 'reality',
        'special_reality_xhttp': 'reality',
        'special_reality_grpc': 'reality',
        'old_xtls_direct': 'oldxtls',
    }
    return tones.get(name, 'direct')


WS_MODE_HINTS = {
    'direct': _('The DNS record of this domain must hold the IP of this server. Use it when the server IP is not blocked.'),
    'sub_link_only': _('This domain only serves the subscription link and carries no user traffic.'),
    'cdn': _('The domain is proxied by a CDN such as Cloudflare, so its DNS record holds a CDN IP.'),
    'auto_cdn_ip': _('Same as CDN, and the panel keeps looking for a clean CDN IP on its own.'),
    'relay': _('The domain belongs to a relay server that forwards the traffic to this server.'),
    'worker': _('The traffic of this domain arrives through a Cloudflare Worker.'),
    'fake': _('A name that exists only inside the configs. It needs no DNS record at all.'),
    'reality': _('The old Reality setup. Prefer Reality TCP, XHTTP or gRPC for new domains.'),
    'special_reality_tcp': _('Reality over TCP. Here the domain is a foreign website used as a cover.'),
    'special_reality_xhttp': _('Reality over XHTTP. Here the domain is a foreign website used as a cover.'),
    'special_reality_grpc': _('Reality over gRPC. Here the domain is a foreign website used as a cover.'),
    'old_xtls_direct': _('The old XTLS setup, kept only for old client apps.'),
}


def ws_mode_catalog():
    out = []
    for mode in DomainType:
        out.append({
            'value': mode.name,
            'label': str(ws_mode_label(mode)),
            'family': ws_mode_family(mode),
            'tone': ws_mode_tone(mode.name),
            'old': mode.name in WS_OLD_MODES,
            'hint': str(WS_MODE_HINTS.get(mode.name, '')),
        })
    return out


def ws_server_ips():
    out = []
    try:
        for ip in hutils.network.get_ips():
            out.append(str(ip))
    except BaseException as err:
        logger.error(f'watashi: cannot read the addresses of this server: {err}')
    return out


def ws_is_cloudflare(ip):
    try:
        asn = hutils.network.get_ip_asn(ip) or ''
    except BaseException as err:
        logger.debug(f'watashi: cannot tell who owns {ip}: {err}')
        return False
    return 'cloudflare' in str(asn).lower()


def ws_cert_state(domain):
    'Reads how many days are left on the certificate the domain serves.'
    answer = {'days': None, 'issuer': '', 'trusted': None, 'note': ''}
    if not domain:
        return answer
    raw = None
    trusted = None
    try:
        strict = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as plain:
            with strict.wrap_socket(plain, server_hostname=domain) as tls:
                raw = tls.getpeercert()
                trusted = True
    except ssl.SSLCertVerificationError as err:
        trusted = False
        answer['note'] = str(getattr(err, 'verify_message', '') or err)
    except BaseException as err:
        answer['note'] = str(err)
        return answer
    if raw is None:
        # the certificate exists but no browser would trust it, so read it raw
        try:
            loose = ssl.create_default_context()
            loose.check_hostname = False
            loose.verify_mode = ssl.CERT_NONE
            with socket.create_connection((domain, 443), timeout=5) as plain:
                with loose.wrap_socket(plain, server_hostname=domain) as tls:
                    der = tls.getpeercert(binary_form=True)
            from cryptography import x509
            parsed = x509.load_der_x509_certificate(der)
            end = getattr(parsed, 'not_valid_after_utc', None) or parsed.not_valid_after
            answer['days'] = (end.replace(tzinfo=None) - ws_dt.datetime.utcnow()).days
            try:
                answer['issuer'] = parsed.issuer.rfc4514_string()
            except BaseException:
                answer['issuer'] = ''
        except BaseException as err:
            logger.debug(f'watashi: cannot read the certificate of {domain}: {err}')
        answer['trusted'] = trusted
        return answer
    try:
        end = ws_dt.datetime.strptime(raw.get('notAfter', ''), '%b %d %H:%M:%S %Y %Z')
        answer['days'] = (end - ws_dt.datetime.utcnow()).days
    except BaseException as err:
        logger.debug(f'watashi: cannot read the expiry date of {domain}: {err}')
    try:
        for group in raw.get('issuer', ()):
            for key, value in group:
                if key == 'organizationName':
                    answer['issuer'] = value
    except BaseException:
        pass
    answer['trusted'] = trusted
    return answer


def ws_now():
    return int(ws_dt.datetime.utcnow().timestamp())


def ws_health_store():
    'Reads the kept answers. Every worker of the panel shares this one file.'
    try:
        import json as ws_json
        with open(WS_HEALTH_FILE, encoding='utf-8') as fh:
            return ws_json.load(fh) or {}
    except BaseException:
        return {}


def ws_health_keep(model, report):
    'Writes one answer down so the page can show it again without any waiting.'
    store = ws_health_store()
    store[str(model.id)] = {
        'at': ws_now(),
        'domain': (model.domain or ''),
        'mode': ws_mode_name(model.mode),
        'health': report,
    }
    try:
        import json as ws_json
        with open(WS_HEALTH_FILE, 'w', encoding='utf-8') as fh:
            ws_json.dump(store, fh)
    except BaseException as err:
        logger.debug(f'watashi: cannot write the kept health answers: {err}')


def ws_health_recall(model, ttl=None):
    'Gives the last answer back while it is still young enough to trust.'
    kept = ws_health_store().get(str(model.id))
    if not kept:
        return None
    if kept.get('domain') != (model.domain or ''):
        return None
    if kept.get('mode') and kept.get('mode') != ws_mode_name(model.mode):
        return None
    age = ws_now() - int(kept.get('at') or 0)
    limit = WS_HEALTH_TTL if ttl is None else ttl
    if age < 0 or age > limit:
        return None
    report = dict(kept.get('health') or {})
    if not report:
        return None
    report['checked_at'] = int(kept.get('at') or 0)
    report['age'] = age
    report['kept'] = True
    return report


def ws_health_forget(model):
    store = ws_health_store()
    if store.pop(str(model.id), None) is None:
        return
    try:
        import json as ws_json
        with open(WS_HEALTH_FILE, 'w', encoding='utf-8') as fh:
            ws_json.dump(store, fh)
    except BaseException as err:
        logger.debug(f'watashi: cannot drop a kept health answer: {err}')


def ws_domain_lookup(name):
    try:
        return [str(ip) for ip in hutils.network.get_domain_ips(name)]
    except BaseException as err:
        logger.debug(f'watashi: cannot look up {name}: {err}')
        return []


def ws_cert_notes(answer, name, hard):
    'Adds what the certificate of the domain says. hard means it must be valid.'
    cert = ws_cert_state(name)
    answer['cert'] = cert
    days = cert.get('days')
    if days is None:
        if hard:
            answer['state'] = 'bad'
            answer['notes'].append(__('Nothing answered TLS on port 443 for this domain.'))
        else:
            answer['notes'].append(__('No certificate could be read from this domain.'))
        return
    if days < 0:
        answer['state'] = 'bad'
        answer['notes'].append(__('The certificate of this domain has already expired.'))
        return
    if days <= 14:
        if answer['state'] == 'ok':
            answer['state'] = 'warn'
        answer['notes'].append(__('The certificate of this domain expires very soon.'))
        return
    if hard and cert.get('trusted') is False:
        if answer['state'] == 'ok':
            answer['state'] = 'warn'
        answer['notes'].append(__('The certificate of this domain is not trusted by browsers yet.'))


def ws_domain_health(model, want_cert=True):
    """Tests one domain the way its own mode asks to be tested.

    Every mode has its own idea of a healthy answer, so the same dns reply can
    be right in one mode and wrong in another:

    * direct and subscription link: the domain must answer with the ip of this
      server, otherwise the users cannot arrive here.
    * cdn, auto clean ip and worker: the domain must answer with a cdn ip. The
      ip of this server showing up here means the cdn proxy is switched off.
    * relay: the domain belongs to the relay machine, so a foreign ip is right
      and the ip of this server is the mistake.
    * reality and old xtls: the domain is a foreign website used as a cover, so
      it has nothing to do with this server. All it has to do is answer tls on
      port 443.
    * fake: nothing is ever asked from the dns.
    """
    name = (model.domain or '').strip()
    mode = ws_mode_name(model.mode)
    server_ips = ws_server_ips()
    answer = {
        'id': model.id,
        'domain': name,
        'mode': mode,
        'mode_label': str(ws_mode_label(model.mode)),
        'tone': ws_mode_tone(mode),
        'state': 'ok',
        'title': '',
        'notes': [],
        'ips': [],
        'server_ips': server_ips,
        'behind_cdn': False,
        'cert': None,
        'advice': '',
        'wants': '',
        'checked_at': ws_now(),
        'age': 0,
    }

    # nothing to ask the network about
    if mode in WS_MODE_NOWHERE or not name:
        answer['state'] = 'off'
        answer['wants'] = 'nothing'
        answer['title'] = __('No test needed')
        answer['notes'].append(__('A fake name lives only inside the configs, so no DNS record is asked for it.'))
        return answer
    if name.startswith('*.'):
        answer['state'] = 'off'
        answer['wants'] = 'nothing'
        answer['title'] = __('No test needed')
        answer['notes'].append(__('A wildcard domain cannot be looked up by itself.'))
        return answer

    found = ws_domain_lookup(name)
    answer['ips'] = found
    answer['behind_cdn'] = any(ws_is_cloudflare(ip) for ip in found)
    mine = [ip for ip in found if ip in server_ips]

    if not found:
        answer['state'] = 'bad'
        answer['title'] = __('This domain has no DNS record')
        answer['notes'].append(__('No address came back for this domain, so nobody can reach it.'))
        answer['advice'] = __('Add an A or AAAA record for this domain where your DNS is managed.')
        return answer

    # a foreign website used as a cover for reality
    if mode in WS_MODE_DECOY:
        answer['wants'] = 'foreign'
        if mine:
            answer['state'] = 'warn'
            answer['title'] = __('The cover site points at this server')
            answer['notes'].append(__('A Reality cover site has to be a foreign website, but this name answers with the IP of this server.'))
            answer['advice'] = __('Use a well known foreign website here, or choose a mode that belongs to your own domain.')
        else:
            answer['title'] = __('The cover site answers normally')
            answer['notes'].append(__('The IP of a cover site has nothing to do with this server, so a foreign address is the right answer here.'))
        if want_cert:
            ws_cert_notes(answer, name, hard=True)
        names = (model.servernames or '').strip()
        if names:
            answer['notes'].append(__('The configs send these cover names:') + ' ' + names)
        return answer

    # behind a cdn
    if mode in WS_MODE_CDN:
        answer['wants'] = 'cdn'
        if mine and not answer['behind_cdn']:
            answer['state'] = 'warn'
            answer['title'] = __('The CDN proxy looks switched off')
            answer['notes'].append(__('This domain answers with the IP of this server, so the traffic does not go through the CDN.'))
            answer['advice'] = __('Switch the proxy on at your CDN, or change the mode to Direct.')
        elif answer['behind_cdn']:
            answer['title'] = __('The domain is served through Cloudflare')
        else:
            answer['title'] = __('The domain is served by another network')
            answer['notes'].append(__('The address of this domain belongs neither to this server nor to Cloudflare, which is allowed when another CDN sits in front.'))
        if want_cert:
            ws_cert_notes(answer, name, hard=False)
        return answer

    # a relay machine in front of this server
    if mode in WS_MODE_RELAY:
        answer['wants'] = 'relay'
        if mine:
            answer['state'] = 'warn'
            answer['title'] = __('The relay domain points at this server')
            answer['notes'].append(__('A relay domain has to point at the relay machine, not at this server.'))
            answer['advice'] = __('Point this domain at the relay machine, or change the mode to Direct.')
        else:
            answer['title'] = __('The relay domain answers normally')
            answer['notes'].append(__('A relay domain is expected to answer with the IP of the relay machine.'))
        if want_cert:
            ws_cert_notes(answer, name, hard=False)
        return answer

    # straight to this server
    answer['wants'] = 'here'
    if mine:
        answer['title'] = __('The domain points at this server')
    elif answer['behind_cdn']:
        answer['state'] = 'warn'
        answer['title'] = __('Cloudflare answers for this domain')
        answer['notes'].append(__('This mode needs a straight connection, but Cloudflare answers for the domain.'))
        answer['advice'] = __('Switch the proxy off at Cloudflare, or change the mode to CDN.')
    else:
        answer['state'] = 'bad'
        answer['title'] = __('The domain points somewhere else')
        answer['notes'].append(__('None of the addresses of this domain belong to this server.'))
        answer['advice'] = __('Point this domain at the IP of this server.')
    if want_cert:
        ws_cert_notes(answer, name, hard=(answer['state'] != 'bad'))
    return answer


def ws_domain_usage(model):
    'Where a domain is used, so nobody deletes it blindly.'
    out = []
    try:
        others = Domain.query.filter(Domain.download_domain_id == model.id).all()
        for other in others:
            out.append({'kind': 'download', 'text': __('It is the download domain of') + ' ' + str(other.domain)})
    except BaseException as err:
        logger.debug(f'watashi: cannot tell which domain downloads from this one: {err}')
    try:
        for other in Domain.query.filter(Domain.child_id == model.child_id).all():
            if other.id == model.id:
                continue
            for shown in (other.show_domains or []):
                if shown.id == model.id:
                    out.append({'kind': 'show', 'text': __('It is offered in the links of') + ' ' + str(other.domain)})
    except BaseException as err:
        logger.debug(f'watashi: cannot tell which links offer this domain: {err}')
    try:
        names = (model.servernames or '').strip()
        if names:
            out.append({'kind': 'reality', 'text': __('It carries the decoy names') + ' ' + names})
    except BaseException:
        pass
    return out



class DomainAdmin(AdminLTEModelView):
    # edit_modal = False
    # create_modal = False
    column_hide_backrefs = False

    list_template = 'domains_list.html'
    # edit_modal = True
    form_overrides = {'mode': custom_widgets.EnumSelectField}
    form_widget_args = {
        'description': {
            'rows': 100,
            'style': 'font-family: monospace; direction:ltr'
        }
    }
    column_descriptions = dict(
        domain=_("domain.description"),
        mode=_("Direct mode means you want to use your server directly (for usual use), CDN means that you use your server on behind of a CDN provider."),
        cdn_ip=_("config.cdn_forced_host.description"),
        show_domains=_('domain.show_domains_description'),
        alias=_('The name shown in the configs for this domain.'),
        servernames=_('config.reality_server_names.description'),
        sub_link_only=_('This can be used for giving your users a permanent non blockable links.'),
        grpc=_('grpc-proxy.description'),
        download_domain=_('download_domain.description'),
        resolve_ip=_("domain.resolveip.description"),
        enable=_('When this is off, the domain stays in the panel but is left out of every link and config.')
    )
    # create_modal = True
    can_export = False
    form_widget_args = {'show_domains': {'class': 'form-control ltr'},'download_domain': {'class': 'form-control ltr'}}

    form_args = {
        'mode': {'enum': DomainType},
        'show_domains': {
            'query_factory': lambda: Domain.query.filter(     Domain.sub_link_only == False),
        },
        'domain': {
            'validators': [
                Regexp(r'^(\*\.)?([A-Za-z0-9\-\.]+\.[a-zA-Z]{2,})$|^$',message=__("Should be a valid domain"))]},
        "cdn_ip": {
            'validators': [
                Regexp(r"(((((25[0-5]|(2[0-4]|1\d|[1-9]|)\d).){3}(25[0-5]|(2[0-4]|1\d|[1-9]|)\d))|^([A-Za-z0-9\-\.]+\.[a-zA-Z]{2,}))[ \t\n,;]*\w{3}[ \t\n,;]*)*",message=__("Invalid IP or domain"))]},
        "servernames": {
            'validators': [
                Regexp(r"^([\w-]+\.)+[\w-]+(,\s*([\w-]+\.)+[\w-]+)*$",re.IGNORECASE,_("Invalid REALITY hostnames"))]}}
    column_list = ["domain", "alias", "mode", "domain_ip", "show_domains"]
    column_editable_list = ["alias"]
    # column_filters=["domain","mode"]
    # form_excluded_columns=['work_with']
    column_searchable_list = ["domain", "mode"]
    column_labels = {
        "domain": _("domain.domain"),
        'sub_link_only': _('Only for sublink?'),
        "mode": _("domain.mode"),
        "cdn_ip": _("config.cdn_forced_host.label"),
        'domain_ip': _('domain.ip'),
        'servernames': _('config.reality_server_names.label'),
        'show_domains': _('Show Domains'),
        'alias': _('Alias'),
        'grpc': _('gRPC'),
        "download_domain":_('download_domain.label'),
        'resolve_ip':_("domain.resolveip.label"),
        'enable': _('Active'),
    }

    form_columns = ['mode', 'domain', 'alias', 'servernames', 'cdn_ip', 'resolve_ip', 'enable', 'show_domains', 'download_domain',]

    def _domain_admin_link(view, context, model, name):
        if model.mode == DomainType.fake:
            return Markup(f"<span class='badge'>{model.domain}</span>")
        d = model.domain
        if "*" in d:
            d = d.replace("*", hutils.random.get_random_string(5, 15))
        admin_link = hiddify.get_account_panel_link(g.account, d)
        return Markup(
            f'<div class="btn-group"><a href="{admin_link}" class="btn btn-xs btn-secondary">' + _("admin link") +
            f'</a><a href="{admin_link}" class="btn btn-xs btn-info ltr" target="_blank">{model.domain}</a></div>')

    def _domain_ip(view, context, model, name):
        dips = hutils.network.get_domain_ips_cached(model.domain)
        # The get_domain_ip function uses the socket library, which relies on the system DNS resolver. So it may sometimes use cached data, which is not desirable
        # if not dips:
        #     dip = hutils.network.resolve_domain_with_api(model.domain)
        myips = set(hutils.network.get_ips())
        all_res = ""
        for dip in dips:
            if dip in myips and model.mode in [DomainType.direct, DomainType.sub_link_only]:
                badge_type = ''
            elif dip and dip not in myips and model.mode != DomainType.direct:
                badge_type = 'warning'
            else:
                badge_type = 'danger'
            res = f'<span class="badge badge-{badge_type}">{dip}</span>'
            if model.sub_link_only:
                res += f'<span class="badge badge-success">{_("SubLink")}</span>'
            all_res += res
        return Markup(all_res)

    def _show_domains_formater(view, context, model, name):
        if not len(model.show_domains):
            return _("All")
        else:
            return Markup(" ".join([hiddify.get_domain_btn_link(d) for d in model.show_domains]))

    column_formatters = {
        'domain_ip': _domain_ip,
        'domain': _domain_admin_link,
        'show_domains': _show_domains_formater
    }

    def search_placeholder(self):
        return f"{_('search')} {_('domain.domain')} {_('domain.mode')}"

    # def on_form_prefill(self, form, id):
        # Get the Domain object being edited
        # domain = self.session.query(Domain).get(id)

        # Pre-select the related domains in the checkbox list
        # form.show_domains = [d.id for d in Domain.query.all()]

    # TODO: refactor this function
    def on_model_change(self, form, model, is_created):
        # Whether the mode really changed has to be read BEFORE anything
        # queries the database, because the first query writes the change
        # out and the old value is gone after that.
        mode_changed = True
        try:
            from sqlalchemy import inspect as sa_inspect
            mode_changed = bool(sa_inspect(model).attrs.mode.history.has_changes())
        except BaseException as err:
            logger.debug(f"watashi: cannot tell whether the mode changed: {err}")
        # Sanitize domain input
        model.domain = (model.domain or '').lower().strip()
        if model.download_domain and model.domain==model.download_domain.domain:
            model.download_domain_id=None
            model.download_domain=None
        # Basic validation
        if model.domain == '' and model.mode != DomainType.fake:
            raise ValidationError(_("domain.empty.allowed_for_fake_only"))

        self._validate_not_used_before(model,is_created)
        ipv4_list = hutils.network.get_ips(4)
        ipv6_list = hutils.network.get_ips(6)
        server_ips = [*ipv4_list, *ipv6_list]

        if not server_ips:
            raise ValidationError(_("Couldn't find your ip addresses"))

        # Validate domain based on mode
        if "*" in model.domain and model.mode not in [DomainType.cdn, DomainType.auto_cdn_ip]:
            raise ValidationError(_("Domain can not be resolved! there is a problem in your domain"))

        cloudflare_updated=self._update_cloudflare(model, ipv4_list,ipv6_list)
        
        
        self._validate_domain_ips(model, server_ips)

        # Handle CDN IP settings
        if model.mode == DomainType.direct and model.cdn_ip:
            model.cdn_ip = ""
            raise ValidationError(_("Specifying CDN IP is only valid for CDN mode"))
            
        if model.mode == DomainType.fake and not model.cdn_ip:
            model.cdn_ip = str(server_ips[0])
            
        if model.cdn_ip:
            try:
                hutils.network.auto_ip_selector.get_clean_ip(str(model.cdn_ip))
            except Exception:
                raise ValidationError(_("Error in auto cdn format"))
                    
        # Update show domains
        # Only the domains this child really offers in the picker may be counted.
        offered = Domain.query.filter(Domain.child_id == model.child_id, Domain.sub_link_only == False).count()
        if offered and len(model.show_domains) == offered:
            model.show_domains = []
                
        # Handle mode-specific settings
        if model.mode == DomainType.old_xtls_direct and not hconfig(ConfigEnum.xtls_enable):
            set_hconfig(ConfigEnum.xtls_enable, True)
            hutils.proxy.get_proxies().invalidate_all()
        elif "reality" in  model.mode:
            self._validate_reality_settings(model, server_ips)
                
            # Signal config update if needed
        if is_created or mode_changed:
            # return hiddify.reinstall_action(complete_install=False, domain_changed=True)
            hutils.flask.flash_config_success(restart_mode=ApplyMode.apply_config, domain_changed=True)

            

    def _update_cloudflare(self, model, ipv4_list,ipv6_list):
        if hconfig(ConfigEnum.cloudflare) and model.mode not in [DomainType.fake, DomainType.relay, DomainType.reality]:
            try:
                proxied = model.mode in [DomainType.cdn, DomainType.auto_cdn_ip]
                if ipv4_list:
                    hutils.network.cf_api.add_or_update_dns_record(model.domain, str(ipv4_list[0]), "A", proxied=proxied)
                if ipv6_list:
                    hutils.network.cf_api.add_or_update_dns_record(model.domain, str(ipv6_list[0]), "AAAA", proxied=proxied)
                return True
            except Exception as e:
                raise ValidationError(__("cloudflare.error") + f' {e}')
        return False

    def _validate_reality_settings(self, model, server_ips):
        """Validate REALITY protocol settings with proper error handling"""
        if not hconfig(ConfigEnum.reality_enable):
            set_hconfig(ConfigEnum.reality_enable, True)
            hutils.proxy.get_proxies().invalidate_all()

        model.servernames = (model.servernames or model.domain).lower().strip()
        domains_to_check = set()
        for v in [model.domain, model.servernames]:
            domains_to_check.update(d.strip() for d in v.split(",") if d.strip())

        for d in domains_to_check:
            # Check REALITY compatibility
            if not hutils.network.is_domain_reality_friendly(d):
                raise ValidationError(_("Domain is not REALITY friendly!") + f' {d}')

            try:
                if not hutils.network.is_in_same_asn(d, server_ips[0]):
                    domain_ips = hutils.network.get_domain_ips(d)
                    if domain_ips:
                        dip = next(iter(domain_ips))
                        server_asn = hutils.network.get_ip_asn(server_ips[0])
                        domain_asn = hutils.network.get_ip_asn(dip)
                        msg = _("domain.reality.asn_issue")
                        if server_asn or domain_asn:
                            msg += f"<br> Server ASN={server_asn}<br>{d}_ASN={domain_asn}"
                        hutils.flask.flash(msg, 'warning')
            except Exception as e:
                logger.warning(f"ASN check failed for domain {d}: {str(e)}")

        # Check fallback compatibility
        for d in model.servernames.split(","):
            if d.strip() and not hutils.network.fallback_domain_compatible_with_servernames(model.domain, d):
                msg = _("REALITY Fallback domain is not compatible with server names!") + f' {d} != {model.domain}'
                hutils.flask.flash(msg, 'warning')


    def validate_form(self, form):
        '''Field errors used to be drawn by the old page, which we never show,
        so they are told to the admin here instead.'''
        answer = super().validate_form(form)
        if answer:
            return answer
        labels = self.column_labels or {}
        for name in (getattr(form, 'errors', None) or {}):
            field = getattr(form, name, None)
            title = labels.get(name, None)
            if title is None:
                title = getattr(getattr(field, 'label', None), 'text', None) or name
            for note in (form.errors.get(name) or []):
                flash(f'{title}: {note}', 'error')
        return answer

    def _validate_not_used_before(self, model,is_created):
        configs = get_hconfigs()
        for c in configs:
            if "domain" in c and c not in [ConfigEnum.decoy_domain, ConfigEnum.reality_fallback_domain] and c.category != 'hidden':
                if model.domain == configs[c]:
                    raise ValidationError(__('This domain is already used in the setting "%(name)s". Free it there first.', name=_(f"config.{c}.label")))

        for td in Domain.query.filter(Domain.mode.in_([DomainType.reality,DomainType.special_reality_xhttp,DomainType.special_reality_grpc,DomainType.special_reality_tcp]), Domain.domain != model.domain).all():
            # print(td)
            if td.servernames and (model.domain in td.servernames.split(",")):
                raise ValidationError(__('This domain is already a Reality server name (SNI) of the domain %(domain)s. Pick another domain or free it there first.', domain=td.domain))

        # Renaming a domain onto an existing one has to be refused too, so the
        # count is taken without flushing this very row into the table.
        with db.session.no_autoflush:
            twins = Domain.query.filter(Domain.domain == model.domain, Domain.child_id == model.child_id)
            if getattr(model, 'id', None):
                twins = twins.filter(Domain.id != model.id)
            if twins.count() >= 1:
                raise ValidationError(__('This domain is already in the panel. A domain can be added only once.'))

    def _validate_domain_ips(self, model, server_ips):
        """Validate domain IP resolution and matching"""
        
        # Skip validation for wildcard or empty domains
        if (model.domain.startswith('*') or not model.domain) and model.mode not in [DomainType.direct]:
            return True
        if model.mode in [DomainType.fake, DomainType.reality, DomainType.relay]:
            return True
        if "special" in model.mode:
            return True
        # Resolve domain IPs with timeout
        try:
            dips = hutils.network.get_domain_ips(model.domain)
        except Exception as e:
            logger.error(f"Error resolving domain {model.domain}: {str(e)}")
            raise ValidationError(_("Domain cannot be resolved! Please check DNS settings"))
        
        # Validate resolution success
        if not dips:
            raise ValidationError(_("Domain cannot be resolved! Please check DNS settings"))
        
        # Check IP matching based on mode
        domain_ip_matches_server = any(ip in dips for ip in server_ips)
        server_ips_str = ', '.join(map(str, server_ips))
        dips_str = ', '.join(map(str, dips))
    
        if not domain_ip_matches_server and model.mode in [DomainType.direct]:
            raise ValidationError(
                __("Domain IP=%(domain_ip)s is not matched with your ip=%(server_ip)s which is required in direct mode",
                    server_ip=server_ips_str, domain_ip=dips_str))
                
        if domain_ip_matches_server and model.mode in [DomainType.cdn, DomainType.relay, DomainType.fake, DomainType.auto_cdn_ip]:
            raise ValidationError(
                __("In CDN mode, Domain IP=%(domain_ip)s should be different to your ip=%(server_ip)s",
                    server_ip=server_ips_str, domain_ip=dips_str))
                
        return True
    
        
    # def after_model_change(self,form, model, is_created):
    #     if model.show_domains.count==0:
    #         db.session.bulk_save_objects(ShowDomain(model.id,model.id))

    def on_model_delete(self, model):
        if Domain.query.filter(Domain.child_id == model.child_id).count() <= 1:
            raise ValidationError(f"at least one domain should exist")
        if hconfig(ConfigEnum.cloudflare) and model.mode not in [DomainType.fake, DomainType.reality, DomainType.relay] and "special" not in model.mode:
            if not hutils.network.cf_api.delete_dns_record(model.domain):
                hutils.flask.flash(_('cf-delete.failed'), 'warning')  # type: ignore
        model.showed_by_domains = []
        # db.session.commit()
        hutils.flask.flash_config_success(restart_mode=ApplyMode.apply_config, domain_changed=True)

    def after_model_delete(self, model):
        if hutils.node.is_child():
            hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.domains])

    def after_model_change(self, form, model, is_created):
        if hconfig(ConfigEnum.first_setup):
            set_hconfig(ConfigEnum.first_setup, False)
        if model.need_valid_ssl and "*" not in model.domain:
            commander(Command.get_cert, domain=model.domain)
        if hutils.node.is_child():
            hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.domains])

    def is_accessible(self):
        if login_required(roles={Role.super_admin, Role.admin, Role.custom})(lambda: True)() != True:
            return False
        return True

    # def form_choices(self, field, *args, **kwargs):
    #     if field.type == "Enum":
    #         return [(enum_value.name, _(enum_value.name)) for enum_value in field.type.__members__.values()]
    #     return super().form_choices(field, *args, **kwargs)

    # @property
    # def server_ips(self):
    #     return hiddify.get_ip(4)

    def get_query(self):
        query = super().get_query()
        return query.filter(Domain.child_id == Child.current().id)
    # ------------------------------------------------------------------
    # watashi: what our own page needs
    # ------------------------------------------------------------------
    def ws_may_write(self):
        try:
            from hiddifypanel.models.admin_perms import ws_can as ws_capability
        except BaseException as err:
            logger.error(f'watashi: cannot read the permissions of this admin: {err}')
            return True
        return bool(ws_capability('domains'))

    def ws_domain_row(self, model):
        mode = ws_mode_name(model.mode)
        cdn_ips = []
        try:
            for ip in (model.cdn_ip or '').replace(',', ' ').split():
                cdn_ips.append(ip.strip())
        except BaseException:
            cdn_ips = []
        shown = []
        shown_ids = []
        try:
            for other in (model.show_domains or []):
                shown.append(other.domain)
                shown_ids.append(other.id)
        except BaseException as err:
            logger.debug(f'watashi: cannot read the offered domains: {err}')
        download = ''
        download_id = ''
        try:
            if model.download_domain_id:
                mate = Domain.query.filter(Domain.id == model.download_domain_id).first()
                download = mate.domain if mate else ''
                download_id = model.download_domain_id if mate else ''
        except BaseException as err:
            logger.debug(f'watashi: cannot read the download domain: {err}')
        return {
            'id': model.id,
            'domain': model.domain or '',
            'alias': model.alias or '',
            'mode': mode,
            'mode_label': ws_mode_label(model.mode),
            'family': ws_mode_family(model.mode),
            'old_mode': mode in WS_OLD_MODES,
            'cdn_ips': cdn_ips,
            'servernames': model.servernames or '',
            'grpc': bool(getattr(model, 'grpc', False)),
            'sub_only': bool(getattr(model, 'sub_link_only', False)),
            'resolve_ip': bool(getattr(model, 'resolve_ip', False)),
            'enable': getattr(model, 'enable', True) is not False,
            'tone': ws_mode_tone(mode),
            'hint': str(WS_MODE_HINTS.get(mode, '')),
            'health': ws_health_recall(model),
            'download': download,
            'download_id': download_id,
            'shown': shown,
            'shown_ids': shown_ids,
            'edit_url': self.get_url('.edit_view', id=model.id),
            'visit_url': 'https://' + (model.domain or ''),
        }

    def ws_domain_rows(self):
        rows = []
        try:
            for model in self.get_query().order_by(Domain.mode, Domain.domain).all():
                rows.append(self.ws_domain_row(model))
        except BaseException as err:
            logger.error(f'watashi: cannot read the domains of this node: {err}')
        return rows

    def ws_domain_stats(self, rows):
        """Counts the domains per mode, and only for the modes that exist.

        The page shows one small chip per mode, so a mode nobody uses should not
        take any room at all.
        """
        counts = {}
        for row in rows:
            counts[row['mode']] = counts.get(row['mode'], 0) + 1
        chips = []
        for mode in DomainType:
            many = counts.get(mode.name, 0)
            if not many:
                continue
            chips.append({
                'mode': mode.name,
                'label': str(ws_mode_label(mode)),
                'tone': ws_mode_tone(mode.name),
                'count': many,
            })
        off = 0
        old = 0
        for row in rows:
            if not row['enable']:
                off = off + 1
            if row['old_mode']:
                old = old + 1
        return {'total': len(rows), 'chips': chips, 'off': off, 'old': old}

    def ws_form_token(self):
        'Hands the page a token that the standard admin forms will accept.'
        try:
            form = self.get_delete_form()()
            field = getattr(form, 'csrf_token', None)
            if field is not None:
                return field.current_token or ''
        except BaseException as err:
            logger.error(f'watashi: cannot make a form token: {err}')
        return ''

    def render(self, template, **kwargs):
        # Whenever a save is refused, flask-admin asks for its own old page.
        # That page wears a theme the panel has left behind, so it is never
        # drawn: the admin goes back to our page instead, where the reason is
        # already waiting as a message. This has to sit here and not on
        # create_view or edit_view, because flask-admin reads its routes from
        # those two methods and overriding them takes their addresses away.
        old_pages = ('flask-admin/', 'admin/', 'hiddify-flask-admin/', 'ltemaster.html', 'base2.html')
        if isinstance(template, str) and template.startswith(old_pages):
            return redirect(self.get_url('.index_view'))
        if template == 'domains_list.html':
            rows = self.ws_domain_rows()
            kwargs['ws_rows'] = rows
            kwargs['ws_stats'] = self.ws_domain_stats(rows)
            kwargs['ws_modes'] = ws_mode_catalog()
            kwargs['ws_server_ips'] = ws_server_ips()
            kwargs['ws_may_write'] = self.ws_may_write()
            kwargs['ws_csrf'] = self.ws_form_token()
        return super().render(template, **kwargs)

    def ws_pick(self, body):
        'Finds one domain of this node from what the page asked about.'
        try:
            wanted = int(body.get('id') or 0)
        except BaseException:
            wanted = 0
        if not wanted:
            return None
        return self.get_query().filter(Domain.id == wanted).first()

    @expose('/ws_health/', methods=['POST'])
    def ws_health(self):
        """Tests one domain, or hands back the answer that is already kept.

        The page asks with fresh set when the admin really wants the network to
        be asked again, so an ordinary visit costs nothing.
        """
        if not self.is_accessible():
            return jsonify({'ok': False, 'msg': __('You are not allowed to see the domains.')}), 403
        body = request.get_json(silent=True) or {}
        model = self.ws_pick(body)
        if not model:
            return jsonify({'ok': False, 'msg': __('This domain is not on this server any more.')}), 404
        if not body.get('fresh'):
            kept = ws_health_recall(model)
            if kept:
                return jsonify({'ok': True, 'health': kept, 'kept': True})
        want_cert = bool(body.get('cert', True))
        report = ws_domain_health(model, want_cert=want_cert)
        ws_health_keep(model, report)
        return jsonify({'ok': True, 'health': report, 'kept': False})

    @expose('/ws_usage/', methods=['POST'])
    def ws_usage(self):
        if not self.is_accessible():
            return jsonify({'ok': False, 'msg': __('You are not allowed to see the domains.')}), 403
        body = request.get_json(silent=True) or {}
        model = self.ws_pick(body)
        if not model:
            return jsonify({'ok': False, 'msg': __('This domain is not on this server any more.')}), 404
        alone = Domain.query.filter(Domain.child_id == model.child_id).count() <= 1
        return jsonify({'ok': True, 'domain': model.domain, 'alone': alone,
                        'usage': ws_domain_usage(model)})

    def ws_apply_ask(self):
        """The button the panel wants pressed before a change reaches the configs.

        Saving a domain only writes it in the database. The configs are built
        again when the settings are applied, so the page shows this as a message
        that carries the button and waits until it is pressed.
        """
        try:
            url = hutils.flask.hurl_for('admin.Actions:reinstall', complete_install=False, domain_changed=True)
        except BaseException as err:
            logger.debug(f'watashi: cannot build the address of the apply button: {err}')
            return None
        return {
            'url': url,
            'label': str(_('admin.config.apply_configs')),
            'busy': str(_('Applying...')),
            'text': str(_('The change is saved. Press the button so it reaches the configs.')),
        }

    @expose('/ws_toggle/', methods=['POST'])
    def ws_toggle(self):
        """Switches a domain on or off without deleting anything.

        A domain that is off keeps all its settings but is left out of the
        subscription links and of the generated configs.
        """
        if not self.is_accessible() or not self.ws_may_write():
            return jsonify({'ok': False, 'msg': __('You are not allowed to change the domains.')}), 403
        body = request.get_json(silent=True) or {}
        model = self.ws_pick(body)
        if not model:
            return jsonify({'ok': False, 'msg': __('This domain is not on this server any more.')}), 404
        want = bool(body.get('enable'))
        if not want:
            live = self.get_query().filter(Domain.enable != False, Domain.id != model.id).count()
            if live < 1:
                return jsonify({'ok': False, 'msg': __('At least one domain has to stay on, otherwise nobody can reach the panel.')}), 400
        try:
            model.enable = want
            db.session.commit()
        except BaseException as err:
            db.session.rollback()
            logger.error(f'watashi: cannot switch the domain: {err}')
            return jsonify({'ok': False, 'msg': __('The change could not be saved.')}), 500
        try:
            if hutils.node.is_child():
                hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent, *[hutils.node.child.SyncFields.domains])
        except BaseException as err:
            logger.debug(f'watashi: cannot tell the parent about the change: {err}')
        return jsonify({'ok': True, 'enable': want, 'domain': model.domain,
                        'apply': self.ws_apply_ask()})

    @expose('/ws_forget/', methods=['POST'])
    def ws_forget(self):
        'Drops the kept test answer of one domain.'
        if not self.is_accessible():
            return jsonify({'ok': False, 'msg': __('You are not allowed to see the domains.')}), 403
        body = request.get_json(silent=True) or {}
        model = self.ws_pick(body)
        if not model:
            return jsonify({'ok': False, 'msg': __('This domain is not on this server any more.')}), 404
        ws_health_forget(model)
        return jsonify({'ok': True})
