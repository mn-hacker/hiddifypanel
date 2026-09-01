# watashi: udp port hopping v12.2.63
#
# A filter that has learned to hate one UDP port only has to drown that one
# port. Hysteria2's answer is to let the client spray its packets across a
# whole range while the server quietly folds them all back onto the single
# port it really listens on. The spraying costs the client nothing and costs
# the censor a thousand ports' worth of attention.
#
# This module owns only the arithmetic: which ports this server already
# answers on, whether a proposed range would swallow one of them, and which
# range is safe. It never touches the firewall - common/utils.sh does that.

from hiddifypanel.models import ConfigEnum, hconfig

# The band sits deliberately above everything else this machine can hand out.
# hutils/random.py draws every random panel port from 11000-60000, and the
# kernel's ephemeral range ends at 60999. Starting at 61001 makes a collision
# impossible by construction rather than by luck.
BAND_LO = 61001
BAND_HI = 65000
WIDTH = 1000
FLOOR = 1024
CEILING = 65535

# Ports this panel answers on regardless of how it has been configured:
# ssh, dns, http, https, the panel itself, mysql, redis, and the two sing-box
# api sockets.
ALWAYS_OURS = (22, 53, 80, 443, 9000, 3306, 6379, 10086, 10087)

_SINGLE_KEYS = (
    'wireguard_port',
    'ssh_server_port',
    'tuic_port',
    'hysteria_port',
    'mieru_port',
    'naive_port',
    'shadowtls_port',
    'amnezia_port',
    'special_port',
    'reality_port',
    'shadowsocks2022_port',
)

_CSV_KEYS = (
    'tls_ports',
    'http_ports',
    'kcp_ports',
    'mieru_tcp_ports',
    'mieru_udp_ports',
)

# Each domain shifts its own listeners by port_index, so the same protocol can
# sit on a different port per domain. Those shifted ports are ours too.
_DOMAIN_PORTS = (
    'internal_port_hysteria2',
    'internal_port_tuic',
    'internal_port_mieru',
    'internal_port_naive',
    'internal_port_amnezia',
    'internal_port_special',
)


def _int(value):
    """Read value as a port number, or None when it is not one."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= CEILING else None


def parse_range(text):
    """Turn '61001-62000' into (61001, 62000), or None when it is nonsense."""
    if not text:
        return None
    parts = str(text).replace(' ', '').split('-')
    if len(parts) != 2:
        return None
    lo = _int(parts[0])
    hi = _int(parts[1])
    if lo is None or hi is None:
        return None
    if lo < FLOOR or hi > CEILING or lo >= hi:
        return None
    return (lo, hi)


def format_range(pair):
    """Turn (61001, 62000) back into the string the config stores."""
    return '%d-%d' % (pair[0], pair[1])


def default_range():
    """The first window of the band: 61001-62000."""
    return (BAND_LO, BAND_LO + WIDTH - 1)


def owned_ports(child_id=None, domains=None):
    """Every port this server already answers on.

    Each config key is looked up through getattr so that an older or thinner
    ConfigEnum cannot bring the whole panel down over a key it never had.
    """
    ports = set(ALWAYS_OURS)
    for name in _SINGLE_KEYS:
        key = getattr(ConfigEnum, name, None)
        if key is None:
            continue
        port = _int(hconfig(key, child_id))
        if port:
            ports.add(port)
    for name in _CSV_KEYS:
        key = getattr(ConfigEnum, name, None)
        if key is None:
            continue
        listed = hconfig(key, child_id)
        if not listed:
            continue
        for chunk in str(listed).split(','):
            port = _int(chunk)
            if port:
                ports.add(port)
    for domain in (domains or []):
        for name in _DOMAIN_PORTS:
            port = _int(getattr(domain, name, None))
            if port:
                ports.add(port)
    return ports


def collisions(pair, owned):
    """The ports of ours that the given range would swallow."""
    if not pair:
        return []
    lo, hi = pair
    return sorted(port for port in owned if lo <= port <= hi)


def pick_safe_range(owned, width=WIDTH):
    """Walk the band and return the first window that hits nothing of ours.

    On a hit the walk restarts just past the highest offender rather than
    creeping forward one port at a time.
    """
    lo = BAND_LO
    while lo + width - 1 <= BAND_HI:
        hi = lo + width - 1
        hits = collisions((lo, hi), owned)
        if not hits:
            return (lo, hi)
        lo = max(hits) + 1
    return None


def active_range(child_id=None, domains=None):
    """The range hopping should actually advertise, or None for 'do not'.

    A blank or malformed range falls back to the default rather than turning
    the feature into a silent no-op. A range that would swallow one of our own
    ports turns hopping off completely: telling a client to spray at a range
    the server refused to open is worse than never offering hopping at all.
    """
    switch = getattr(ConfigEnum, 'port_hop_enable', None)
    if switch is None or not hconfig(switch, child_id):
        return None
    holder = getattr(ConfigEnum, 'port_hop_range', None)
    if holder is None:
        return None
    pair = parse_range(hconfig(holder, child_id))
    if pair is None:
        pair = default_range()
    if collisions(pair, owned_ports(child_id, domains)):
        return None
    return pair
