import yaml
from hiddifypanel.models import ProxyCDN, ProxyL3, ProxyProto, ProxyTransport, Domain
from hiddifypanel import hutils
# https://wiki.metacubex.one/en/


def get_clash_config_names(meta_or_normal, domains: list[Domain]):
    allp = []
    for pinfo in hutils.proxy.get_valid_proxies(domains):
        clash = to_clash(pinfo, meta_or_normal)
        if 'msg' not in clash:
            allp.append(clash['name'])

    return yaml.dump(allp, sort_keys=False)


def get_all_clash_configs(meta_or_normal, domains: list[Domain]):
    allp = []
    for pinfo in hutils.proxy.get_valid_proxies(domains):
        clash = to_clash(pinfo, meta_or_normal)
        if 'msg' not in clash:
            allp.append(clash)

    return yaml.dump({"proxies": allp}, sort_keys=False)

# def to_clash_yml(proxy):
#     return yaml.dump(to_clash(proxy,'normal'))


def to_clash(proxy, meta_or_normal):

    name = proxy['name']

    if proxy['l3'] in ["kcp", ProxyL3.h3_quic]:
        return {'name': name, 'msg': f"clash does not support {proxy['l3']}", 'type': 'debug'}
    if proxy['transport'] in [ProxyTransport.xhttp, ProxyTransport.httpupgrade]:
        return {'name': name, 'msg': f"clash does not support {proxy['transport']}", 'type': 'debug'}
    # if proxy['proto'] in [Proxy.shado]:

    if meta_or_normal == "normal":
        if proxy.get('flow'):
            return {'name': name, 'msg': "xtls not supported in clash", 'type': 'debug'}
        if proxy['proto'] in [ProxyProto.ssh, ProxyProto.wireguard, ProxyProto.tuic, ProxyProto.hysteria2, ProxyProto.anytls, ProxyProto.snell]:
            return {'name': name, 'msg': f"clash does not support {proxy['proto']}", 'type': 'debug'}
        if proxy['proto'] in ["vless", 'tuic', 'hysteria2']:
            return {'name': name, 'msg': f"{proxy['proto']} not supported in clash", 'type': 'debug'}
        if proxy['transport'] in ["shadowtls", "xhttp"]:
            return {'name': name, 'msg': f"{proxy['transport']} not supported in clash", 'type': 'debug'}
    if proxy['l3'] == ProxyL3.tls_h2 and proxy['proto'] in [ProxyProto.vmess, ProxyProto.vless] and proxy['dbe'].cdn == ProxyCDN.direct:
        return {'name': name, 'msg': "bug tls_h2 vmess and vless in clash meta", 'type': 'warning'}
    # watashi v12.2.101: mihomo speaks snell 1 to 4 only, and the server
    # this panel runs is v6, so a snell row in a clash file would be a
    # config the client cannot connect with. the row is dropped instead of
    # written broken; sing-box based clients still get it from the json.
    if proxy['proto'] == ProxyProto.snell:
        return {'name': name, 'msg': 'snell v6 needs a sing-box based client', 'type': 'debug'}
    # watashi v12.2.108: the generic path below wrote a mieru row as a proxy
    # of type mieru carrying transport fields, and mihomo rejects a profile
    # that holds a row it cannot read instead of skipping that one entry, so
    # a single mieru row took the whole clash subscription down with it.
    #
    # watashi v12.2.112: round 108 dropped every mieru row on the belief that
    # mihomo has no mieru protocol. That is wrong, and it was checked against
    # wiki.metacubex.one/en/config/proxies/mieru: mihomo takes a row of type
    # mieru with server, port or port-range, transport, username, password,
    # multiplexing and handshake-mode. Those are the fields hutils.proxy.mieru
    # writes now, so Clash Verge Rev, Mihomo Party, ClashMi and the other
    # mihomo based clients can connect. Plain clash, which has no such type,
    # still gets a note instead of a row.
    # watashi v12.2.115: the generic path below wrote a naive row as a
    # proxy of type naive, and no such type exists in clash or in
    # mihomo: the proxy list on wiki.metacubex.one has no naive entry
    # and mihomo answers unsupport proxy type: naive. mihomo refuses the
    # whole profile over one row it cannot read instead of skipping that
    # row, so a single naive entry took the entire clash subscription
    # down with it and every other config in the file stopped working
    # until the admin turned naive off by hand. naive stays in the
    # sing-box json and in its own client link; only the clash file
    # loses a row it could never have connected with.
    if proxy['proto'] == ProxyProto.naive:
        return {'name': name, 'msg': 'clash and mihomo have no naive type', 'type': 'debug'}
    if proxy['proto'] == ProxyProto.mieru:
        if meta_or_normal == "normal":
            return {'name': name, 'msg': 'clash has no mieru, use a mihomo based client', 'type': 'debug'}
        return hutils.proxy.mieru.to_clash_mieru(proxy)
    base = {}
    # vmess ws
    base["name"] = f"""{proxy['extra_info']} {proxy["name"]} § {proxy['port']} {proxy["dbdomain"].id}"""
    base["type"] = str(proxy["proto"])
    base["server"] = proxy["server"]
    base["port"] = proxy["port"]
    if proxy["proto"] == "ssh":
        base["username"] = proxy["uuid"]
        base["private-key"] = proxy['private_key']
        base["host-key"] = proxy.get('host_keys', [])
        return base
    base["udp"] = True
    if proxy["proto"] == ProxyProto.wireguard:
        base["private-key"] = proxy["wg_pk"]
        base["ip"] = f'{proxy["wg_ipv4"]}/32'
        # base["ipv6"]
        base["public-key"] = proxy["wg_server_pub"]
        base["pre-shared-key"] = proxy["wg_psk"]
        # base["allowed-ips"]
        return base
    if proxy["proto"] == ProxyProto.tuic:
        # base['congestion_control'] = "cubic"
        base['udp-relay-mode'] = 'native'
        base['reduce-rtt'] = True
        base["skip-cert-verify"] = proxy['allow_insecure']
        base['sni'] = proxy['sni']
        # base['heartbeat'] = "10s"
        base['password'] = proxy['uuid']
        base['uuid'] = proxy['uuid']
        return base

    # watashi v12.2.101: anytls in mihomo takes the password and the sni and
    # nothing from the transport section, so it returns here before the
    # generic tls path writes network and alpn fields it does not read.
    if proxy["proto"] == ProxyProto.anytls:
        base["password"] = proxy.get("password") or proxy["uuid"]
        base["sni"] = proxy["sni"]
        base["skip-cert-verify"] = proxy["mode"] == "Fake" or proxy["allow_insecure"]
        return base

    if proxy["proto"] == "ssr":
        base["cipher"] = proxy["cipher"]
        base["password"] = proxy["uuid"]
        base["udp"] = True
        base["obfs"] = proxy["ssr-obfs"]
        base["protocol"] = proxy["ssr-protocol"]
        base["obfs-param"] = proxy["fakedomain"]
        return base
    elif proxy["proto"] in ["ss", "v2ray"]:
        base["cipher"] = proxy["cipher"]
        base["password"] = proxy["password"]
        # watashi v12.2.113: this wrote udp_over_tcp. mihomo spells the
        # option udp-over-tcp (wiki.metacubex.one, proxies/ss), so the
        # underscore form was dropped on the floor by every client that
        # read the file. Writing the documented name instead would have
        # been worse: udp over tcp only works when the server offers it,
        # and singbox/configs/common/protocols/ss.pj2 sets no
        # udp_over_tcp, so a client that really turned it on would lose
        # udp altogether. The row now says what the server actually
        # does: plain udp, which mihomo has on by default anyway.
        base["udp"] = True
        if proxy["transport"] == "faketls":
            base["plugin"] = "obfs"
            base["plugin-opts"] = {
                "mode": 'tls',
                "host": proxy["fakedomain"]
            }
        elif proxy["transport"] == "shadowtls":
            base["plugin"] = "shadow-tls"
            base["plugin-opts"] = {
                "host": proxy["fakedomain"],
                "password": proxy["shared_secret"],
                "version": 3  # support 1/2/3

            }

        elif proxy["proto"] == "v2ray":
            base["plugin"] = "v2ray-plugin"
            base["type"] = "ss"
            base["plugin-opts"] = {
                "mode": "websocket",
                "tls": "tls" in proxy["l3"],
                "skip-cert-verify": proxy["mode"] == "Fake" or proxy['allow_insecure'],
                "host": proxy['sni'],
                "path": proxy["path"]
            }
        return base
    base['alpn'] = proxy['alpn'].split(',')
    base["skip-cert-verify"] = proxy["mode"] == "Fake"
    if meta_or_normal == "meta" and proxy.get('fingerprint'):
        base['client-fingerprint'] = proxy['fingerprint']

    if proxy["proto"] == "trojan":
        base["password"] = proxy["uuid"]
        base["sni"] = proxy["sni"]
    elif proxy["proto"] == "hysteria2":
        base["password"] = proxy["uuid"]
        # watashi v12.2.79: the obfs layer was handed out unconditionally
        # while the server only opens it when hysteria_obfs_enable is on, and
        # a server without salamander drops the wrapped packets it cannot
        # unwrap. the link now follows the server instead of guessing.
        # watashi v12.2.97: without a password mihomo is handed obfs-password
        # null, wraps its packets anyway, and the server drops them. the
        # layer is offered only when there is a secret to offer.
        if proxy.get('hysteria_obfs_enable') and proxy.get('hysteria_obfs_password'):
            base["obfs"] = "salamander"
            base["obfs-password"] = proxy.get('hysteria_obfs_password')
        # watashi v12.2.79: mihomo reads the brutal rates from up and down and
        # runs plain bbr without them, and it does port jumping through ports
        # plus hop-interval, where ports makes it ignore the single port.
        up = proxy.get('hysteria_up_mbps')
        down = proxy.get('hysteria_down_mbps')
        if up:
            base["up"] = '%s Mbps' % up
        if down:
            base["down"] = '%s Mbps' % down
        span = hutils.proxy.port_hop.active_range()
        if span:
            base["ports"] = '%d-%d' % (span[0], span[1])
            base["hop-interval"] = 30
        return base
    else:
        base["uuid"] = proxy["uuid"]
        base["servername"] = proxy["sni"]
        base["tls"] = "tls" in proxy["l3"] or "reality" in proxy["l3"]
    if proxy["proto"] in ["vless", "vmess"]:
        base["packet-encoding"] = "xudp"

    if proxy.get('flow'):
        base["flow"] = proxy['flow']
        # base["flow-show"] = True

    if proxy["proto"] == "vmess":
        base["alterId"] = 0
        base["cipher"] = proxy["cipher"]

    base["network"] = str(proxy["transport"])

    if base["network"] == "ws":
        base["ws-opts"] = {
            "path": proxy["path"]
        }
        if "host" in proxy:
            base["ws-opts"]["headers"] = {"Host": proxy["host"]}

    if base["network"] == "tcp" and proxy['alpn'] != 'h2':
        if proxy['transport'] != ProxyL3.reality:
            base["network"] = "http"

        if "path" in proxy:
            base["http-opts"] = {
                "path": [proxy["path"]]
            }
            if 'host' in proxy:
                base["http-opts"]["host"] = [proxy["host"]]
    if base["network"] == "tcp" and proxy['alpn'] == 'h2':
        base["network"] = "h2"

        if "path" in proxy:
            base["h2-opts"] = {
                "path": proxy["path"]
            }
            if 'host' in proxy:
                base["h2-opts"]["host"] = [proxy["host"]]
    if base["network"] == "grpc":
        base["grpc-opts"] = {
            "grpc-service-name": proxy["grpc_service_name"]
        }
    if proxy['l3'] == ProxyL3.reality:
        base["reality-opts"] = {
            "public-key": proxy['reality_pbk'],
            "short-id": proxy['reality_short_id'],
        }
        if proxy["transport"] != 'grpc':
            base["network"] = 'tcp'

    return base
