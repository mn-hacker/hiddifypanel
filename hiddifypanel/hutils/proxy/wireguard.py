
def generate_wireguard_config(proxy: dict) -> str:
    """
    Generates a WireGuard configuration from a given proxy dictionary.

    Args:
        proxy (dict): Dictionary containing WireGuard and proxy details.

    Returns:
        str: A WireGuard configuration string.
    """
    name=f'{proxy["extra_info"]} {proxy["name"]}'
    addrs = f"{proxy['wg_ipv4']}/32"
    if proxy['wg_ipv6']:
        addrs += f", {proxy['wg_ipv6']}/128"
    
    allowed_ips = proxy.get("allowed_ips", "0.0.0.0/0, ::/0")
    keep_alive = proxy.get("keep_alive", 25)
    
    config = f"""[Interface]
# Name = {name}
Address = {addrs}
PrivateKey = {proxy["wg_pk"]}
MTU = {proxy.get("mtu", 1380)}
DNS = {proxy.get("dns", "1.1.1.1")}

[Peer]
# Name = Public Peer for {name}
Endpoint = {proxy["server"]}:{proxy["port"]}
PublicKey = {proxy["wg_server_pub"]}
PresharedKey = {proxy['wg_psk']}
AllowedIPs = {allowed_ips}
PersistentKeepalive = {keep_alive}
"""

    return config


# watashi: amnezia .conf builder v12.2.59
# watashi v12.2.130y: what the panel installs on a fresh database, kept here so a
# client file can never be written with a knob left out.
# watashi v12.2.130ai: the numbers below are what the Amnezia app itself
# hands out for Iran, and what its own free profiles carry:
#   Jc 3..10 junk packets before the handshake, sized Jmin..Jmax
#   S1/S2 padding on the two handshake packets, never S1 + 56 == S2,
#     because a padded init that ends up the size of a response is a
#     signature of its own
#   H1..H4 the four packet types, which must be large and distinct or the
#     handshake still looks exactly like plain WireGuard to a filter
# 1,2,3,4 and 0,0 are the plain WireGuard values: they disguise nothing,
# which is why a tunnel built with them dies in Iran within minutes.
AMNEZIA_FALLBACK = {'jc': 5, 'jmin': 50, 'jmax': 1000, 's1': 86, 's2': 122,
                    'h1': 1148643543, 'h2': 1663162381, 'h3': 1301944243,
                    'h4': 1826109311}


def amnezia_defaults() -> dict:
    """A fresh set of obfuscation knobs for one install. Both ends read the
    same rows, so these are picked once and written to the database: the
    server interface and every client .conf are built from them."""
    import random as _random
    h1, h2, h3, h4 = _random.sample(range(5, 2000000000), 4)
    s1 = _random.randint(15, 150)
    s2 = _random.randint(15, 150)
    while s1 + 56 == s2 or s2 + 56 == s1:
        s2 = _random.randint(15, 150)
    return {'jc': _random.randint(3, 10), 'jmin': 50, 'jmax': 1000,
            's1': s1, 's2': s2, 'h1': h1, 'h2': h2, 'h3': h3, 'h4': h4}

AMNEZIA_KEYS = [('jc', 'Jc'), ('jmin', 'Jmin'), ('jmax', 'Jmax'), ('s1', 'S1'),
                ('s2', 'S2'), ('h1', 'H1'), ('h2', 'H2'), ('h3', 'H3'), ('h4', 'H4')]


def generate_amnezia_config(proxy: dict) -> str:
    """AmneziaWG is WireGuard plus obfuscation knobs. The official Amnezia
    apps read them from [Interface], so they are written there and nowhere
    else. Missing values are skipped instead of being emitted empty."""
    config = generate_wireguard_config(proxy)
    nl = '\r\n' if '\r\n' in config else '\n'
    # watashi v12.2.130y: a half written set of knobs is worse than none. The app
    # rejects a file that asks for junk packets without saying how large they
    # may get, and an interface whose numbers differ from ours never answers
    # the handshake. If one value is missing, the standing default of the
    # panel is used, which is what the server side was built with.
    values = {key: proxy.get(f'amnezia_{key}') for key, _label in AMNEZIA_KEYS}
    if any(v not in (None, '') for v in values.values()):
        for key, fallback in AMNEZIA_FALLBACK.items():
            if values.get(key) in (None, ''):
                values[key] = fallback
    extra = [f'{label} = {values[key]}' for key, label in AMNEZIA_KEYS
             if values.get(key) not in (None, '')]
    if not extra:
        return config
    head, sep, tail = config.partition('[Peer]')
    return head.rstrip('\r\n') + nl + nl.join(extra) + nl + nl + sep + tail
