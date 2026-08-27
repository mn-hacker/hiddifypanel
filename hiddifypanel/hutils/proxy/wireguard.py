
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
AMNEZIA_KEYS = [('jc', 'Jc'), ('jmin', 'Jmin'), ('jmax', 'Jmax'), ('s1', 'S1'),
                ('s2', 'S2'), ('h1', 'H1'), ('h2', 'H2'), ('h3', 'H3'), ('h4', 'H4')]


def generate_amnezia_config(proxy: dict) -> str:
    """AmneziaWG is WireGuard plus obfuscation knobs. The official Amnezia
    apps read them from [Interface], so they are written there and nowhere
    else. Missing values are skipped instead of being emitted empty."""
    config = generate_wireguard_config(proxy)
    nl = '\r\n' if '\r\n' in config else '\n'
    extra = [f'{label} = {proxy[f"amnezia_{key}"]}' for key, label in AMNEZIA_KEYS
             if proxy.get(f'amnezia_{key}') not in (None, '')]
    if not extra:
        return config
    head, sep, tail = config.partition('[Peer]')
    return head.rstrip('\r\n') + nl + nl.join(extra) + nl + nl + sep + tail
