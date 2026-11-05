# watashi v12.3.41dev: the inbounds the owner builds by hand in the advanced mode.
"""Everything the panel knows about a hand built inbound lives here: what a
valid one looks like, the xray inbound it turns into on the server, the row it
turns into in every subscription format, and which ports it may not take.

Nothing in this file touches the running server. The Inbounds page saves a
row, the commander tests it with the real xray binary before it is kept, and
xray/run.sh takes the whole file out again if xray would not start with it, so
one bad inbound can never take the panel's own configs down with it.

The vocabulary is kept small on purpose. Every protocol, transport and
security below is something xray serves and the usual clients (v2rayNG,
Hiddify, sing-box, mihomo) can read from a link; the raw JSON box covers the
rest for whoever needs it.
"""
import base64
import copy
import hashlib
import ipaddress
import json
import random
import re
import secrets
import socket
import string
from types import SimpleNamespace

from loguru import logger

from watashipanel.models import ConfigEnum, hconfig, Domain, DomainType, ProxyCDN
from watashipanel.models.custom_inbound import CustomInbound

PROTOCOLS = ('vless', 'vmess', 'trojan', 'shadowsocks')
NETWORKS = ('tcp', 'ws', 'grpc', 'httpupgrade', 'xhttp')
SECURITIES = ('none', 'tls', 'reality')
XHTTP_MODES = ('auto', 'packet-up', 'stream-up', 'stream-one')
# Only the methods xray can be told about through its api: a user added
# while xray runs has to get the very same method the file gave the others.
# The 2022 family takes a server key of its own and cannot be added that way.
SS_METHODS = {
    'aes-128-gcm': 'aes_128_gcm',
    'aes-256-gcm': 'aes_256_gcm',
    'chacha20-ietf-poly1305': 'chacha20_poly1305',
    'xchacha20-ietf-poly1305': 'xchacha20_poly1305',
}
FINGERPRINTS = ('', 'chrome', 'firefox', 'safari', 'ios', 'android', 'edge', 'random', 'randomized')
ALPNS = ('h2,http/1.1', 'h2', 'http/1.1')
OUTBOUNDS = ('default', 'direct', 'warp')
FLOW_VISION = 'xtls-rprx-vision'
CLIENTS_MARK = '@@WS_CLIENTS@@'
TAG_PREFIX = 'custom-'
# The users of these inbounds carry a label of their own. xray counts traffic
# per label, so the sing-box mode can read exactly the traffic of these
# inbounds and nothing that other xray inbounds carried before they existed.
EMAIL_DOMAIN = 'custom.watashi.cyou'
STATUS_FILE = '/opt/watashi-manager/log/custom_inbounds.status'
EXTRA_MAX = 16384
# Ports the stack itself uses on loopback or keeps for later. A listener on
# 0.0.0.0 cannot share a port with one on 127.0.0.1, so these are taken even
# while the service behind them happens to be off.
WS_STACK_PORTS = {
    22: 'ssh', 53: 'dns', 438: 'nginx', 501: 'nginx', 502: 'nginx', 1001: 'telegram proxy',
    1010: 'ssfaketls', 1234: 'xray', 2000: 'sing-box', 2039: 'sing-box', 3000: 'WARP',
    3306: 'mysql', 6379: 'redis', 8181: 'haproxy', 8388: 'shadowsocks', 9000: 'panel',
    9091: 'telegram proxy', 10085: 'xray api', 10086: 'sing-box api', 10087: 'sing-box api',
}

PATH_RE = re.compile(r'^/[A-Za-z0-9._~\-/]{0,120}$')
SERVICE_RE = re.compile(r'^[A-Za-z0-9._\-]{1,100}$')
HOST_RE = re.compile(r'^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$')
SHORT_ID_RE = re.compile(r'^(?:[0-9a-f]{2}){0,8}$')
KEY_RE = re.compile(r'^[A-Za-z0-9_-]{43}$')
REMARK_RE = re.compile(r'^[^\x00-\x1f<>"\'`\\]{0,64}$')


def _(text, **kw):
    """The page language when there is a request, the plain text when not."""
    try:
        from flask_babel import gettext
        return gettext(text, **kw)
    except Exception:
        return text % kw if kw else text


def ws_mode_on() -> bool:
    """Whether hand built inbounds serve at all right now: always in the
    advanced mode, and in the simple mode only when the owner asked to keep
    them when leaving it."""
    try:
        return bool(hconfig(ConfigEnum.advanced_mode)) or bool(hconfig(ConfigEnum.custom_inbounds_keep))
    except Exception:
        return False


def ws_is_active(row: CustomInbound, mode_on: bool | None = None) -> bool:
    if mode_on is None:
        mode_on = ws_mode_on()
    return bool(row.enable) and bool(mode_on)


def ws_is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(str(text))
        return True
    except ValueError:
        return False


def ws_is_local_ip(text: str) -> bool:
    """Whether xray could listen on this address: one this server has (or the
    any address). Binding port 0 asks the kernel without taking anything."""
    try:
        ip = ipaddress.ip_address(str(text))
    except ValueError:
        return False
    if ip.is_unspecified:
        return True
    probe = socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind((str(ip), 0))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def ws_is_host(text: str) -> bool:
    text = str(text or '')
    return bool(HOST_RE.match(text)) or ws_is_ip(text)


def ws_reality_public(private_key: str) -> str:
    """The public half of a REALITY key, worked out instead of typed in, so the
    pair in the link and the key on the server can never disagree."""
    from cryptography.hazmat.primitives.asymmetric import x25519
    from cryptography.hazmat.primitives import serialization
    raw = base64.urlsafe_b64decode(private_key + '=' * (-len(private_key) % 4))
    if len(raw) != 32:
        raise ValueError('a REALITY private key is 32 bytes')
    pub = x25519.X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return base64.urlsafe_b64encode(pub).decode().rstrip('=')


def ws_new_keys() -> dict:
    from watashipanel import hutils
    keys = hutils.crypto.generate_x25519_keys()
    return {'reality_private_key': keys['private_key'],
            'reality_public_key': ws_reality_public(keys['private_key']),
            'reality_short_ids': secrets.token_hex(4)}


def ws_random_path() -> str:
    alphabet = string.ascii_letters + string.digits
    return '/' + ''.join(secrets.choice(alphabet) for _x in range(14))


def ws_random_service() -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _x in range(12))


def ws_tls_domains() -> list[str]:
    """The domains of this panel a TLS inbound can borrow a certificate from."""
    skip = {DomainType.fake, DomainType.reality, DomainType.special_reality_tcp,
            DomainType.special_reality_xhttp, DomainType.special_reality_grpc,
            DomainType.old_xtls_direct}
    out = []
    try:
        for d in Domain.query.filter(Domain.child_id == 0).all():
            if '*' in d.domain or d.mode in skip:
                continue
            if d.domain not in out:
                out.append(d.domain)
    except Exception as problem:
        logger.warning(f'watashi: the domains could not be read ({problem})')
    return out


def ws_default_address() -> str:
    from watashipanel import hutils
    try:
        return str(hutils.network.get_direct_host_or_ip(4) or '')
    except Exception:
        return ''


def _merge(base: dict, extra: dict):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def _ports_of(text) -> list[tuple[int, int]]:
    """'443,8443' or '2000-2010' as (low, high) pairs; nonsense is skipped."""
    out = []
    for piece in str(text or '').replace(' ', '').split(','):
        if not piece:
            continue
        try:
            if '-' in piece:
                lo, hi = piece.split('-', 1)
                lo, hi = int(lo), int(hi)
            else:
                lo = hi = int(piece)
        except ValueError:
            continue
        if 0 < lo <= hi <= 65535:
            out.append((lo, hi))
    return out


def ws_panel_ports() -> list[tuple[int, int, str, str]]:
    """Every port the panel's own configs use: (low, high, proto, owner).
    proto is tcp, udp or both. A feature that is switched off still keeps its
    port, because switching it on later must not fail on a hand built inbound."""
    taken = []
    try:
        from watashipanel.models import get_hconfigs
        conf = get_hconfigs(0)
    except Exception:
        conf = {}
    for key, value in conf.items():
        name = getattr(key, 'name', str(key))
        if not (name.endswith('_port') or name.endswith('_ports')) or 'transport' in name:
            continue
        for lo, hi in _ports_of(value):
            taken.append((lo, hi, 'both', name))
    try:
        if conf.get(ConfigEnum.port_hop_enable) and conf.get(ConfigEnum.port_hop_range):
            for lo, hi in _ports_of(conf.get(ConfigEnum.port_hop_range)):
                taken.append((lo, hi, 'udp', 'port_hop_range'))
    except Exception:
        pass
    try:
        for d in Domain.query.filter(Domain.child_id == 0).all():
            for attr in ('internal_port_hysteria2', 'internal_port_tuic', 'internal_port_special',
                         'internal_port_mieru', 'internal_port_naive', 'internal_port_amnezia',
                         'internal_port_anytls', 'internal_port_snell'):
                try:
                    value = int(getattr(d, attr) or 0)
                except Exception:
                    value = 0
                if value > 0:
                    taken.append((value, value, 'both', f'{d.domain} ({attr.replace("internal_port_", "")})'))
    except Exception as problem:
        logger.warning(f'watashi: the domain ports could not be read ({problem})')
    for port, owner in WS_STACK_PORTS.items():
        taken.append((port, port, 'both', owner))
    return taken


def ws_live_ports() -> dict:
    """The ports something on this machine listens on right now, read from
    /proc so the unprivileged panel can see them too: {'tcp': set, 'udp': set}."""
    live = {'tcp': set(), 'udp': set()}
    for proto, names in (('tcp', ('tcp', 'tcp6')), ('udp', ('udp', 'udp6'))):
        for name in names:
            try:
                with open(f'/proc/net/{name}') as handle:
                    next(handle, None)
                    for line in handle:
                        parts = line.split()
                        if len(parts) < 4:
                            continue
                        # tcp: only listeners (0A); udp: every bound socket
                        if proto == 'tcp' and parts[3] != '0A':
                            continue
                        live[proto].add(int(parts[1].rsplit(':', 1)[1], 16))
            except (OSError, ValueError, IndexError):
                continue
    return live


def ws_uses(row_like: dict) -> set:
    """tcp, udp or both, for a cleaned row or an export row."""
    protocol = row_like.get('protocol')
    settings = row_like.get('settings') or {}
    if protocol == 'shadowsocks' and settings.get('ss_network', 'tcp,udp') == 'tcp,udp':
        return {'tcp', 'udp'}
    return {'tcp'}


def ws_port_problem(port: int, uses: set, row_id: int | None = None, check_live: bool = True) -> str:
    """Why this port cannot be used, or an empty string when it can."""
    for lo, hi, proto, owner in ws_panel_ports():
        if lo <= port <= hi and (proto == 'both' or proto in uses):
            return _('Port %(p)s is already used by the panel itself (%(o)s).', p=port, o=owner)
    own_port = None
    for other in CustomInbound.all_rows():
        if row_id and other.id == row_id:
            own_port = int(other.port or 0)
            continue
        if int(other.port or 0) == port:
            other_uses = ws_uses(other.to_dict())
            if other_uses & uses:
                return _('Port %(p)s is already used by the inbound "%(o)s".', p=port, o=other.remark or other.tag)
    if check_live and port != own_port:
        live = ws_live_ports()
        for proto in uses:
            if port in live.get(proto, set()):
                return _('Something on this server already listens on %(p)s/%(t)s. If it is an inbound you just changed, apply first.', p=port, t=proto)
    return ''


def ws_random_port(row_id: int | None = None) -> int:
    for _try in range(200):
        port = random.randint(10000, 60000)
        if not ws_port_problem(port, {'tcp', 'udp'}, row_id):
            return port
    return 0


def ws_clean(data: dict, row_id: int | None = None, check_live: bool = True) -> tuple[dict, list]:
    """The row as it will be stored, and every reason it cannot be."""
    errors = []
    data = data if isinstance(data, dict) else {}
    raw = data.get('settings') if isinstance(data.get('settings'), dict) else {}

    def s(key, limit=200, default=''):
        value = raw.get(key, default)
        return str(value if value is not None else default).strip()[:limit]

    remark = str(data.get('remark') or '').strip()
    if not REMARK_RE.match(remark):
        errors.append(_('The name may not contain quotes, angle brackets or control characters, and is at most 64 characters.'))
        remark = ''
    protocol = str(data.get('protocol') or '').strip().lower()
    if protocol not in PROTOCOLS:
        errors.append(_('Pick a protocol.'))
        protocol = 'vless'
    network = str(data.get('network') or 'tcp').strip().lower()
    if network not in NETWORKS:
        errors.append(_('Pick a transport.'))
        network = 'tcp'
    security = str(data.get('security') or 'none').strip().lower()
    if security not in SECURITIES:
        errors.append(_('Pick a security layer.'))
        security = 'none'
    try:
        port = int(str(data.get('port') or '0').strip())
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        errors.append(_('The port must be a number from 1 to 65535.'))
    listen = str(data.get('listen') or '').strip()
    if listen and not ws_is_ip(listen):
        errors.append(_('Listen must be empty (every address) or one IP address of this server.'))
    elif listen and not ws_is_local_ip(listen):
        errors.append(_('%(ip)s is not an address of this server, so xray could not listen on it.', ip=listen))

    opts = {}
    opts['sub'] = bool(raw.get('sub', True))
    opts['sniffing'] = bool(raw.get('sniffing', True))
    outbound = s('outbound', 16, 'default') or 'default'
    if outbound not in OUTBOUNDS:
        errors.append(_('Pick where the traffic of this inbound goes.'))
        outbound = 'default'
    if outbound == 'warp':
        try:
            if str(hconfig(ConfigEnum.warp_mode) or 'disable') == 'disable':
                errors.append(_('WARP is switched off on this server, so it cannot be the exit of an inbound. Turn it on in Nodes first.'))
        except Exception:
            pass
    opts['outbound'] = outbound

    if protocol == 'shadowsocks':
        if network != 'tcp' or security != 'none':
            errors.append(_('Shadowsocks is offered on plain TCP with no TLS, the way every Shadowsocks client expects it.'))
            network, security = 'tcp', 'none'
        method = s('ss_method', 40, 'chacha20-ietf-poly1305') or 'chacha20-ietf-poly1305'
        if method not in SS_METHODS:
            errors.append(_('Pick one of the Shadowsocks methods in the list.'))
            method = 'chacha20-ietf-poly1305'
        opts['ss_method'] = method
        ss_network = s('ss_network', 10, 'tcp,udp') or 'tcp,udp'
        opts['ss_network'] = ss_network if ss_network in ('tcp,udp', 'tcp') else 'tcp,udp'

    if security == 'reality':
        if protocol not in ('vless', 'trojan'):
            errors.append(_('REALITY works with VLESS and Trojan only.'))
        if network not in ('tcp', 'grpc', 'xhttp'):
            errors.append(_('REALITY works over TCP, gRPC or XHTTP only.'))

    # the transport
    host = s('host', 253)
    if host and not ws_is_host(host):
        errors.append(_('The host header has to be a domain name or an IP address.'))
    if network == 'tcp':
        header = s('tcp_header', 8, 'none') or 'none'
        if header not in ('none', 'http'):
            header = 'none'
        if header == 'http' and (security != 'none' or protocol == 'shadowsocks'):
            errors.append(_('The HTTP camouflage of plain TCP only works without TLS or REALITY.'))
            header = 'none'
        opts['tcp_header'] = header
        if header == 'http':
            path = s('path', 121, '/') or '/'
            if not PATH_RE.match(path):
                errors.append(_('A path starts with / and uses letters, digits and . _ ~ - / only.'))
            opts['path'] = path
            opts['host'] = host
    elif network in ('ws', 'httpupgrade', 'xhttp'):
        path = s('path', 121) or ws_random_path()
        if not PATH_RE.match(path):
            errors.append(_('A path starts with / and uses letters, digits and . _ ~ - / only.'))
        opts['path'] = path
        opts['host'] = host
        if network == 'xhttp':
            mode = s('xhttp_mode', 16, 'auto') or 'auto'
            opts['xhttp_mode'] = mode if mode in XHTTP_MODES else 'auto'
    elif network == 'grpc':
        service = s('service_name', 100) or ws_random_service()
        if not SERVICE_RE.match(service):
            errors.append(_('A gRPC service name uses letters, digits and . _ - only.'))
        opts['service_name'] = service

    # vless flow
    flow = s('flow', 32)
    if flow not in ('', FLOW_VISION):
        flow = ''
    if flow and not (protocol == 'vless' and network == 'tcp' and security in ('tls', 'reality')):
        errors.append(_('XTLS Vision needs VLESS on plain TCP with TLS or REALITY.'))
        flow = ''
    if protocol == 'vless':
        opts['flow'] = flow

    fingerprint = s('fingerprint', 16)
    if fingerprint not in FINGERPRINTS:
        fingerprint = ''
    if security in ('tls', 'reality'):
        opts['fingerprint'] = fingerprint

    if security == 'tls':
        domains = ws_tls_domains()
        tls_domain = s('tls_domain', 253).lower()
        if not tls_domain:
            errors.append(_('TLS needs one of the domains of this panel, its certificate is the one the inbound shows.'))
        elif tls_domain not in domains:
            errors.append(_('The domain %(d)s is not one of the domains of this panel.', d=tls_domain))
        opts['tls_domain'] = tls_domain
        sni = s('sni', 253).lower()
        if sni and not HOST_RE.match(sni):
            errors.append(_('The SNI has to be a domain name.'))
        opts['sni'] = sni
        default_alpn = {'grpc': 'h2', 'ws': 'http/1.1', 'httpupgrade': 'http/1.1'}.get(network, 'h2,http/1.1')
        alpn = s('alpn', 20, default_alpn) or default_alpn
        if alpn not in ALPNS:
            alpn = default_alpn
        if network == 'grpc' and 'h2' not in alpn:
            errors.append(_('gRPC runs over HTTP/2, so the ALPN has to offer h2.'))
        if network in ('ws', 'httpupgrade') and alpn != 'http/1.1':
            errors.append(_('WebSocket and HTTPUpgrade run over HTTP/1.1, so the ALPN has to be http/1.1.'))
        opts['alpn'] = alpn

    if security == 'reality':
        dest = s('reality_dest', 260)
        dest_host, _sep, dest_port = dest.rpartition(':')
        if not dest:
            errors.append(_('REALITY needs a destination site, for example www.speedtest.net:443.'))
        elif not (dest_host and ws_is_host(dest_host.strip('[]')) and dest_port.isdigit() and 0 < int(dest_port) < 65536):
            errors.append(_('The REALITY destination is a host and a port, for example www.speedtest.net:443.'))
        opts['reality_dest'] = dest
        names = [n.strip().lower() for n in s('reality_server_names', 1000).split(',') if n.strip()]
        if not names:
            errors.append(_('REALITY needs at least one server name.'))
        bad_names = [n for n in names if not HOST_RE.match(n)]
        if bad_names:
            errors.append(_('This is not a server name: %(n)s', n=bad_names[0]))
        opts['reality_server_names'] = ','.join(names)
        private_key = s('reality_private_key', 64)
        if not KEY_RE.match(private_key):
            errors.append(_('The REALITY private key is 43 characters of base64. Press "New keys" to make a pair.'))
            opts['reality_private_key'] = private_key
            opts['reality_public_key'] = ''
        else:
            opts['reality_private_key'] = private_key
            try:
                opts['reality_public_key'] = ws_reality_public(private_key)
            except Exception:
                errors.append(_('The REALITY private key is not a valid key. Press "New keys" to make a pair.'))
                opts['reality_public_key'] = ''
        short_ids = [x.strip().lower() for x in s('reality_short_ids', 300).split(',') if x.strip()]
        bad_ids = [x for x in short_ids if not SHORT_ID_RE.match(x)]
        if bad_ids:
            errors.append(_('A short id is up to 16 hex characters, an even number of them: %(n)s', n=bad_ids[0]))
        if not short_ids:
            short_ids = [secrets.token_hex(4)]
        opts['reality_short_ids'] = ','.join(short_ids)

    address = s('address', 253)
    if address and not ws_is_host(address):
        errors.append(_('The address clients connect to has to be a domain name or an IP address.'))
    opts['address'] = address

    extra_text = raw.get('extra', '')
    if isinstance(extra_text, dict):
        extra_text = json.dumps(extra_text, ensure_ascii=False)
    extra_text = str(extra_text or '').strip()
    if extra_text:
        if len(extra_text) > EXTRA_MAX:
            errors.append(_('The raw JSON is too long.'))
        else:
            try:
                extra = json.loads(extra_text)
                if not isinstance(extra, dict):
                    raise ValueError('not an object')
                fixed = [k for k in ('tag', 'port', 'listen', 'protocol') if k in extra]
                if fixed:
                    errors.append(_('The raw JSON may not change %(k)s, use the fields above for it.', k=fixed[0]))
                if isinstance(extra.get('settings'), dict) and 'clients' in extra['settings']:
                    errors.append(_('The clients are the users of the panel, the raw JSON may not list them.'))
                found = set()

                def walk(node):
                    if isinstance(node, dict):
                        for key, value in node.items():
                            found.add(key)
                            walk(value)
                    elif isinstance(node, list):
                        for value in node:
                            walk(value)
                walk(extra)
                if 'fallbacks' in found:
                    errors.append(_('Fallbacks are not offered for hand built inbounds, they could reach into the panel\'s own inbounds.'))
                if found & {'certificates', 'certificateFile', 'keyFile', 'certificate', 'key'}:
                    errors.append(_('The raw JSON may not name certificates, TLS takes the certificate of the domain picked above.'))
                opts['extra'] = json.dumps(extra, ensure_ascii=False, indent=2)
            except ValueError:
                errors.append(_('The raw JSON is not a valid JSON object.'))
    opts['extra'] = opts.get('extra', '')

    clean = {
        'id': row_id,
        'enable': bool(data.get('enable', True)),
        'remark': remark,
        'protocol': protocol,
        'port': port,
        'listen': listen,
        'network': network,
        'security': security,
        'settings': opts,
    }
    if not errors and 1 <= port <= 65535:
        problem = ws_port_problem(port, ws_uses(clean), row_id, check_live=check_live)
        if problem:
            errors.append(problem)
    return clean, errors


def build_xray_inbound(row, clients=None) -> dict:
    """The xray inbound of one row. clients None leaves the marker the
    template swaps for the user list; a list puts that list in."""
    if isinstance(row, CustomInbound):
        data = row.to_dict()
    else:
        data = dict(row)
    o = data.get('settings') or {}
    protocol, network, security = data['protocol'], data['network'], data['security']
    tag = f"{TAG_PREFIX}{data['id']}"
    inbound = {'tag': tag, 'port': int(data['port']), 'protocol': protocol}
    if data.get('listen'):
        inbound['listen'] = data['listen']
    users = CLIENTS_MARK if clients is None else clients
    if protocol == 'vless':
        settings = {'clients': users, 'decryption': 'none'}
    elif protocol == 'shadowsocks':
        settings = {'clients': users, 'network': o.get('ss_network', 'tcp,udp')}
    else:
        settings = {'clients': users}
    inbound['settings'] = settings

    stream = {'network': network, 'security': security}
    if network == 'tcp':
        if o.get('tcp_header') == 'http':
            request = {'version': '1.1', 'method': 'GET', 'path': [o.get('path') or '/'],
                       'headers': {'Connection': ['keep-alive'], 'Pragma': 'no-cache'}}
            if o.get('host'):
                request['headers']['Host'] = [o['host']]
            stream['tcpSettings'] = {'header': {'type': 'http', 'request': request,
                                                'response': {'version': '1.1', 'status': '200', 'reason': 'OK',
                                                             'headers': {'Content-Type': ['application/octet-stream'],
                                                                         'Connection': ['keep-alive'],
                                                                         'Pragma': 'no-cache'}}}}
        else:
            stream['tcpSettings'] = {'header': {'type': 'none'}}
    elif network == 'ws':
        stream['wsSettings'] = {'path': o.get('path') or '/'}
        if o.get('host'):
            stream['wsSettings']['host'] = o['host']
    elif network == 'httpupgrade':
        stream['httpupgradeSettings'] = {'path': o.get('path') or '/'}
        if o.get('host'):
            stream['httpupgradeSettings']['host'] = o['host']
    elif network == 'xhttp':
        stream['xhttpSettings'] = {'path': o.get('path') or '/', 'mode': o.get('xhttp_mode') or 'auto'}
        if o.get('host'):
            stream['xhttpSettings']['host'] = o['host']
    elif network == 'grpc':
        stream['grpcSettings'] = {'serviceName': o.get('service_name') or 'grpc'}

    if security == 'tls':
        domain = o.get('tls_domain') or ''
        stream['tlsSettings'] = {
            'certificates': [{'certificateFile': f'/opt/watashi-manager/ssl/{domain}.crt',
                              'keyFile': f'/opt/watashi-manager/ssl/{domain}.crt.key'}],
            'alpn': (o.get('alpn') or 'h2,http/1.1').split(','),
            'minVersion': '1.2',
        }
    elif security == 'reality':
        stream['realitySettings'] = {
            'show': False,
            'dest': o.get('reality_dest') or '',
            'xver': 0,
            'serverNames': [n for n in (o.get('reality_server_names') or '').split(',') if n],
            'privateKey': o.get('reality_private_key') or '',
            'shortIds': [x for x in (o.get('reality_short_ids') or '').split(',') if x],
        }
    inbound['streamSettings'] = stream
    if o.get('sniffing', True):
        inbound['sniffing'] = {'enabled': True, 'destOverride': ['http', 'tls', 'quic']}
    else:
        inbound['sniffing'] = {'enabled': False}
    if o.get('extra'):
        try:
            extra = json.loads(o['extra'])
            if isinstance(extra, dict):
                for key in ('tag', 'port', 'listen', 'protocol'):
                    extra.pop(key, None)
                if isinstance(extra.get('settings'), dict):
                    extra['settings'].pop('clients', None)
                _merge(inbound, extra)
        except ValueError:
            pass
    return inbound


def ws_email(uuid: str) -> str:
    return f'{uuid}@{EMAIL_DOMAIN}'


def ws_client_of(row_like: dict, uuid: str) -> dict:
    """One user as a client of this inbound, exactly as the template writes it."""
    email = ws_email(uuid)
    protocol = row_like['protocol']
    o = row_like.get('settings') or {}
    if protocol == 'vless':
        return {'id': uuid, 'email': email, 'flow': o.get('flow', '')}
    if protocol == 'vmess':
        return {'id': uuid, 'email': email}
    if protocol == 'trojan':
        return {'password': uuid, 'email': email}
    return {'password': uuid, 'method': o.get('ss_method', 'chacha20-ietf-poly1305'), 'email': email}


def ws_export_problem(data: dict, taken: list, held: dict, domains: set | None = None) -> str:
    """Why an otherwise active row is held back from the server: its port
    belongs to the panel's own configs (a panel port that was changed later, or
    a backup from another server) or to an earlier row, it listens on an
    address this server does not have, or its TLS domain is not a domain of
    this panel any more. The page saves nothing like that, so this only ever
    catches rows that got here another way."""
    port = int(data.get('port') or 0)
    uses = ws_uses(data)
    if not 1 <= port <= 65535:
        return _('The port must be a number from 1 to 65535.')
    if data.get('listen') and not ws_is_local_ip(data['listen']):
        return _('%(ip)s is not an address of this server, so xray could not listen on it.', ip=data['listen'])
    o = data.get('settings') or {}
    if domains is not None and data.get('security') == 'tls' and (o.get('tls_domain') or '') not in domains:
        return _('The domain %(d)s is not one of the domains of this panel any more, so there is no certificate for this inbound.', d=o.get('tls_domain') or '-')
    for lo, hi, proto, owner in taken:
        if lo <= port <= hi and (proto == 'both' or proto in uses):
            return _('Port %(p)s is already used by the panel itself (%(o)s).', p=port, o=owner)
    if held.get(port, set()) & uses:
        return _('Port %(p)s is already used by another inbound.', p=port)
    return ''


def ws_export_base(rows=None, quiet=False) -> list[dict]:
    """Every row as current.json carries it, before the last apply had its say."""
    # watashi v12.3.41dev: quiet is for the Inbounds page, which asks for this
    # every few seconds; only the export of an apply says a row is held back,
    # so a held row is one line in the log and not one line per look at the page.
    mode_on = ws_mode_on()
    taken = ws_panel_ports() if mode_on else []
    domains = set(ws_tls_domains()) if mode_on else set()
    held = {}
    out = []
    for row in (CustomInbound.all_rows() if rows is None else rows):
        data = row.to_dict()
        o = data['settings']
        active = ws_is_active(row, mode_on)
        problem_text = ''
        try:
            text = json.dumps(build_xray_inbound(data), ensure_ascii=False, sort_keys=True)
        except Exception as problem:
            logger.error(f'watashi: the inbound {row.tag} could not be built ({problem})')
            text, active, problem_text = '', False, str(problem)
        if active:
            problem_text = ws_export_problem(data, taken, held, domains)
            if problem_text:
                (logger.debug if quiet else logger.warning)(f'watashi: the inbound {row.tag} is held back ({problem_text})')
                active = False
            else:
                held.setdefault(int(row.port), set()).update(ws_uses(data))
        out.append({
            'id': row.id,
            'tag': row.tag,
            'remark': row.remark or '',
            'port': int(row.port or 0),
            'protocol': row.protocol,
            'flow': o.get('flow', ''),
            'ss_method': o.get('ss_method', ''),
            'outbound': o.get('outbound', 'default'),
            'firewall': ','.join(sorted(ws_uses(data))),
            'active': active,
            'problem': problem_text,
            'inbound_json': text,
        })
    return out


def ws_rev(exported: list[dict]) -> str:
    """A fingerprint of what xray has to run. Only the active rows count, so
    editing a paused inbound never asks for an apply."""
    active = [[r['tag'], r['inbound_json'], r['outbound'], r['firewall']] for r in exported if r.get('active')]
    if not active:
        return ''
    return hashlib.sha256(json.dumps(active, sort_keys=True).encode()).hexdigest()[:16]


def ws_mark_rejected(exported: list[dict], rev: str, status: dict | None = None) -> list[dict]:
    """The rows xray/custom_guard.sh had to take out when exactly this set was
    applied stay out: out of the next render, so a later restart of xray cannot
    bring them back, and out of the subscriptions. Changing anything in the set
    changes the rev, and then every row gets its chance again."""
    status = ws_status() if status is None else status
    if not rev or status.get('rev') != rev:
        return exported
    reasons = {}
    for one in status.get('rejected') or []:
        if isinstance(one, dict) and one.get('tag'):
            reasons[str(one['tag'])] = str(one.get('reason') or '')
    for row in exported:
        if row.get('active') and row['tag'] in reasons:
            row['active'] = False
            row['problem'] = reasons[row['tag']] or _('xray did not take this inbound at the last apply.')
            row['rejected'] = True
    return exported


def ws_export_rows(rows=None, status=None) -> list[dict]:
    """What current.json carries for the templates and the root scripts."""
    out = ws_export_base(rows)
    return ws_mark_rejected(out, ws_rev(out), status)


def ws_export_for_cli() -> dict:
    rows = ws_export_base()
    rev = ws_rev(rows)
    # the rev is the one of the whole set the owner asked for, so a set that
    # lost a row at the last apply does not ask for the same apply again
    return {'custom_inbounds': ws_mark_rejected(rows, rev), 'custom_inbounds_rev': rev}


def ws_test_file(rows_data: list[dict]) -> str:
    """The custom file as xray would load it, with one stand in user, for the
    commander to test before anything is saved."""
    probe = '00000000-0000-4000-8000-000000000001'
    inbounds = []
    for data in rows_data:
        inbounds.append(build_xray_inbound(data, clients=[ws_client_of(data, probe)]))
    return json.dumps({'inbounds': inbounds}, ensure_ascii=False)


# ---------------------------------------------------------------- subscriptions

def _api_cipher(method: str) -> str:
    return SS_METHODS.get(method, 'chacha20_poly1305')


def ws_proxy_row(row: CustomInbound, uuid: str) -> dict | None:
    """The row every subscription writer reads, shaped like make_proxy()."""
    data = row.to_dict()
    o = data['settings']
    protocol, network, security = data['protocol'], data['network'], data['security']
    tls_domain = o.get('tls_domain') or ''
    address = o.get('address') or (tls_domain if security == 'tls' else '') or ws_default_address()
    if not address:
        return None
    if security == 'reality':
        names = [n for n in (o.get('reality_server_names') or '').split(',') if n]
        sni = random.choice(names) if names else ''
        alpn = 'h2' if network == 'grpc' else 'http/1.1'
    elif security == 'tls':
        sni = o.get('sni') or tls_domain
        alpn = o.get('alpn') or 'h2,http/1.1'
    else:
        sni = address
        alpn = 'http/1.1'
    fingerprint = o.get('fingerprint') or str(hconfig(ConfigEnum.utls) or 'chrome')
    if fingerprint == 'none' and security == 'reality':
        fingerprint = 'chrome'
    allow_insecure = False
    if security == 'tls':
        try:
            dom = Domain.query.filter(Domain.domain == tls_domain).first()
            allow_insecure = bool(dom) and not dom.need_valid_ssl
        except Exception:
            allow_insecure = False
    name = row.remark or f'{protocol} {network} {row.port}'
    l3 = {'tls': 'tls', 'reality': 'reality'}.get(security, 'http')
    proto = 'ss' if protocol == 'shadowsocks' else protocol
    base = {
        'name': name,
        'extra_info': '',
        'l3': l3,
        'mode': 'reality' if security == 'reality' else 'direct',
        'cdn': False,
        'server': address,
        'port': int(row.port),
        'uuid': uuid,
        'proto': proto,
        'transport': 'shadowsocks' if protocol == 'shadowsocks' else network,
        'sni': sni,
        'host': o.get('host') or sni or address,
        'alpn': alpn,
        'fingerprint': fingerprint,
        'allow_insecure': allow_insecure,
        # no tcp camouflage unless the row asks for it: the xray json writer
        # puts a tcp header on every row without TLS, and an empty one there
        # makes xray refuse the whole client config
        'params': {'headers': {'type': 'none'}},
        'ws_custom': row.id,
        'dbe': SimpleNamespace(id=f'c{row.id}', name=name, proto=proto, transport=network, l3=l3,
                               cdn=ProxyCDN.direct, child_id=0, enable=True, params={}),
        'dbdomain': SimpleNamespace(id=f'c{row.id}', domain=address, alias=None, child_id=0,
                                    mode=DomainType.direct),
    }
    if protocol == 'vmess':
        base['cipher'] = 'auto'
    if protocol == 'trojan':
        base['password'] = uuid
    if protocol == 'shadowsocks':
        base['cipher'] = o.get('ss_method', 'chacha20-ietf-poly1305')
        base['password'] = uuid
        return base
    if protocol == 'vless' and o.get('flow'):
        base['flow'] = o['flow']
    if security == 'reality':
        base['reality_pbk'] = o.get('reality_public_key') or ''
        ids = [x for x in (o.get('reality_short_ids') or '').split(',') if x]
        base['reality_short_id'] = random.choice(ids) if ids else ''
    if network == 'tcp':
        if o.get('tcp_header') == 'http':
            from watashipanel.hutils.proxy.shared import put_default_header
            base['params'] = {'headers': {'type': 'http'}}
            put_default_header(base['params'])
            base['path'] = o.get('path') or '/'
            base['ws_tcp_header'] = 'http'
        else:
            base['params'] = {'headers': {'type': 'none'}}
            base['ws_tcp_header'] = 'none'
    elif network in ('ws', 'httpupgrade'):
        base['path'] = o.get('path') or '/'
    elif network == 'xhttp':
        base['path'] = o.get('path') or '/'
        base['xhttp_mode'] = o.get('xhttp_mode') or 'auto'
    elif network == 'grpc':
        base['grpc_service_name'] = o.get('service_name') or 'grpc'
        base['grpc_mode'] = 'gun'
        base['path'] = base['grpc_service_name']
    return base


def ws_status() -> dict:
    """What xray/run.sh wrote after the last apply: state ok, partial or
    rejected, the rev it applied, the tags it had to leave out and why."""
    try:
        with open(STATUS_FILE) as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def ws_rejected_tags(status: dict | None = None) -> set:
    status = ws_status() if status is None else status
    tags = status.get('rejected_tags')
    return {str(t) for t in tags} if isinstance(tags, list) else set()


def ws_sub_proxies(uuid: str) -> list[dict]:
    """The hand built inbounds a user's subscription carries. One that the
    server had to leave out at the last apply is not handed to clients."""
    if not ws_mode_on():
        return []
    out = []
    rejected = ws_rejected_tags()
    rows = CustomInbound.all_rows()
    if not rows:
        return []
    serving = {r['id'] for r in ws_export_rows(rows) if r['active']}
    for row in rows:
        if row.id not in serving or not row.opts.get('sub', True) or row.tag in rejected:
            continue
        try:
            one = ws_proxy_row(row, uuid)
            if one:
                out.append(one)
        except Exception as problem:
            logger.warning(f'watashi: the inbound {row.tag} was left out of the subscription ({problem})')
    return out


def ws_api_cipher_of(tag: str):
    """protocol, flow and api cipher for a user added to custom-N while xray
    runs, or None when the tag is not one of ours."""
    if not str(tag).startswith(TAG_PREFIX):
        return None
    try:
        row = CustomInbound.query.get(int(str(tag)[len(TAG_PREFIX):]))
    except Exception:
        return None
    if not row:
        return None
    o = row.opts
    flow = o.get('flow', '') if row.protocol == 'vless' else ''
    return row.protocol, flow, _api_cipher(o.get('ss_method', '')) if row.protocol == 'shadowsocks' else None


def ws_any_active() -> bool:
    if not ws_mode_on():
        return False
    try:
        return CustomInbound.query.filter(CustomInbound.enable == True, CustomInbound.child_id == 0).count() > 0  # noqa: E712
    except Exception:
        return False
