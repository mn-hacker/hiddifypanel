# watashi v12.2.112: mieru is handed over on its own, the way WireGuard and
# AmneziaWG are, instead of being mixed into a subscription no client can read.
#
# What was checked before this file was written, not guessed:
#   sing-box has no mieru inbound or outbound at all, so the singbox json and
#   every v2ray style link are out of the question (rounds 108 and 111).
#   mihomo (Clash.Meta) does have a mieru proxy type, documented at
#   wiki.metacubex.one/en/config/proxies/mieru with the fields server,
#   port / port-range, transport, username, password, multiplexing and
#   handshake-mode, so a clash file can carry it and to_clash_mieru builds it.
#   the mieru client itself takes a json file (mieru apply config FILE) and a
#   sharing link, both described in enfein/mieru docs/client-install.md.
#
# The values here have to agree with other/mieru/run.sh.j2, which is what this
# server really runs: the mita user name and the password are both the account
# uuid, and mtu is 1400 on the listener, so the client must carry the same
# number. multiplexing and handshakeMode are client side only; mita answers
# 'unknown field "multiplexing"' for them, so they belong in this file.

import ipaddress
import json
from urllib.parse import quote

# The client reads these two as protobuf enum names, so a value it does not
# know refuses the whole configuration instead of falling back to a default.
# The panel keeps them as free text, and its own default for the handshake is
# written 'HANDSHAKE_Standard', which is not an enum name at all.
MULTIPLEXING_LEVELS = ('MULTIPLEXING_OFF', 'MULTIPLEXING_LOW',
                       'MULTIPLEXING_MIDDLE', 'MULTIPLEXING_HIGH')
HANDSHAKE_MODES = ('HANDSHAKE_STANDARD', 'HANDSHAKE_NO_WAIT')
MIERU_MTU = 1400
MIERU_RPC_PORT = 8964
MIERU_SOCKS5_PORT = 1080
MIERU_HTTP_PORT = 8080


def ws_mieru_level(proxy: dict) -> str:
    '''The multiplexing level of one row, folded onto a name mieru knows.'''
    level = str(proxy.get('multiplexing') or '').strip().upper()
    return level if level in MULTIPLEXING_LEVELS else 'MULTIPLEXING_LOW'


def ws_mieru_handshake(proxy: dict) -> str:
    '''The handshake mode of one row, folded onto a name mieru knows.'''
    mode = str(proxy.get('handshake') or '').strip().upper()
    return mode if mode in HANDSHAKE_MODES else 'HANDSHAKE_STANDARD'


def ws_mieru_bindings(proxy: dict) -> list:
    '''portBindings out of the tcp_ports / udp_ports that shared.py built.

    ports_to_ranges always answers with ranges, so a single port arrives as
    '443-443'. mieru takes either 'port' or 'portRange' and never both, and a
    one port range is written as the plain port so the file stays readable.'''
    binds = []
    for kind, key in (('TCP', 'tcp_ports'), ('UDP', 'udp_ports')):
        for entry in (proxy.get(key) or []):
            entry = str(entry).strip()
            if not entry:
                continue
            edge = entry.split('-')
            try:
                low = int(edge[0])
                high = int(edge[-1])
            except ValueError:
                continue
            if low == high:
                binds.append({'port': low, 'protocol': kind})
            else:
                binds.append({'portRange': f'{low}-{high}', 'protocol': kind})
    return binds


def ws_mieru_address(proxy: dict) -> dict:
    '''mieru keeps the address of a server in one of two fields, so which one
    it is has to be decided here: an ip goes to ipAddress, a name goes to
    domainName, and writing a name into ipAddress is refused by the client.'''
    server = str(proxy.get('server') or '').strip()
    try:
        ipaddress.ip_address(server)
        return {'ipAddress': server}
    except ValueError:
        return {'domainName': server}


def ws_mieru_user(proxy: dict) -> dict:
    '''The account this row belongs to. The server template writes the uuid as
    both the name and the password of every mieru user.'''
    uuid = str(proxy.get('uuid') or '')
    return {'name': uuid, 'password': str(proxy.get('password') or uuid)}


def generate_mieru_config(proxies: list) -> str:
    '''One client configuration file for every mieru row of this account.

    mieru itself picks a server and a port at random for each new connection,
    so several servers live in a single profile instead of a file per row.'''
    servers = []
    for proxy in (proxies or []):
        binds = ws_mieru_bindings(proxy)
        if not binds:
            continue
        server = ws_mieru_address(proxy)
        server['portBindings'] = binds
        servers.append(server)
    if not servers:
        return ''
    first = (proxies or [{}])[0]
    conf = {
        'profiles': [{
            'profileName': 'watashi',
            'user': ws_mieru_user(first),
            'servers': servers,
            'mtu': MIERU_MTU,
            'multiplexing': {'level': ws_mieru_level(first)},
            'handshakeMode': ws_mieru_handshake(first),
        }],
        'activeProfile': 'watashi',
        'rpcPort': MIERU_RPC_PORT,
        'socks5Port': MIERU_SOCKS5_PORT,
        'loggingLevel': 'INFO',
        'socks5ListenLAN': False,
        'httpProxyPort': MIERU_HTTP_PORT,
        'httpProxyListenLAN': False,
    }
    return json.dumps(conf, indent=4, ensure_ascii=False)


def generate_mieru_simple_link(proxy: dict) -> str:
    '''The simple sharing link of one row: mierus://user:pass@server?params.

    port and protocol appear once per binding and are read pairwise, so the
    two lists are written in the same order. This is the link an app that
    speaks mieru imports; the json file above is what the mieru command line
    client takes, because a simple link carries no socks5Port.'''
    binds = ws_mieru_bindings(proxy)
    if not binds:
        return ''
    user = ws_mieru_user(proxy)
    server = str(proxy.get('server') or '').strip()
    if not server or not user['name']:
        return ''
    parts = ['profile=watashi', f'mtu={MIERU_MTU}',
             f'multiplexing={ws_mieru_level(proxy)}',
             f'handshake-mode={ws_mieru_handshake(proxy)}']
    for bind in binds:
        port = bind.get('portRange') or bind.get('port')
        parts.append(f'port={port}')
        parts.append(f"protocol={bind['protocol']}")
    head = f"{quote(user['name'], safe='')}:{quote(user['password'], safe='')}"
    return f"mierus://{head}@{server}?" + '&'.join(parts)


def to_clash_mieru(proxy: dict) -> dict:
    '''The mihomo row of one mieru server.

    port and port-range cannot both be written, and one row carries one
    transport, so the tcp bindings are preferred and the udp ones are used
    when mieru listens on udp only. The name is built here because the
    generic clash path names a row after its port, and mieru rows have none.'''
    name = proxy.get('name')
    binds = ws_mieru_bindings(proxy)
    picked = [b for b in binds if b['protocol'] == 'TCP'] or binds
    if not picked:
        return {'name': name, 'msg': 'mieru has no tcp or udp port configured', 'type': 'debug'}
    row = {
        'name': f"{proxy.get('extra_info', '')} {name} \u00a7 mieru {proxy['dbdomain'].id}",
        'type': 'mieru',
        'server': proxy['server'],
        'transport': picked[0]['protocol'],
        'udp': True,
        'username': ws_mieru_user(proxy)['name'],
        'password': ws_mieru_user(proxy)['password'],
        'multiplexing': ws_mieru_level(proxy),
        'handshake-mode': ws_mieru_handshake(proxy),
    }
    if 'portRange' in picked[0]:
        row['port-range'] = picked[0]['portRange']
    else:
        row['port'] = picked[0]['port']
    return row
