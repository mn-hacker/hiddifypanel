
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
