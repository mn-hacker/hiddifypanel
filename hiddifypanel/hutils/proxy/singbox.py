from flask import render_template, request, g
import json

from hiddifypanel import hutils
from hiddifypanel.hutils.proxy.xrayjson import to_xray
from hiddifypanel.models import ProxyProto, ProxyTransport, Domain, ConfigEnum


def configs_as_json(domains: list[Domain], **kwargs) -> str:
    ua = hutils.flask.get_user_agent()
    base_config = json.loads(render_template('base_singbox_config.json.j2'))
    allphttp = [p for p in request.args.get("phttp", "").split(',') if p]
    allptls = [p for p in request.args.get("ptls", "").split(',') if p]

    allp = []
    for d in domains:
        base_config['dns']['rules'][0]['domain'].append(d.domain)
    for pinfo in hutils.proxy.get_valid_proxies(domains):
        sing = to_singbox(pinfo)
        if 'msg' not in sing:
            allp += sing
    base_config['outbounds'] += allp

    select = {
        "type": "selector",
        "tag": "Select",
        "outbounds": [p['tag'] for p in allp if 'shadowtls-out' not in p['tag']],
        "default": "Auto"
    }
    select['outbounds'].insert(0, "Auto")
    base_config['outbounds'].insert(0, select)
    smart = {
        "type": "urltest",
        "tag": "Auto",
        "outbounds": [p['tag'] for p in allp if 'shadowtls-out' not in p],
        "url": "https://www.gstatic.com/generate_204",
        "interval": "10m",
        "tolerance": 200
    }
    base_config['outbounds'].insert(1, smart)
    res = json.dumps(base_config, indent=4, cls=hutils.proxy.ProxyJsonEncoder)
    # if ua['is_hiddify']:
    #     res = res[:-1]+',"experimental": {}}'
    return res


def is_xray_proxy(proxy: dict):
    if g.user_agent.get('is_hiddify_prefere_xray'):
        return True
    if proxy['transport'] == ProxyTransport.xhttp:
        return True
    return False


def to_singbox(proxy: dict) -> list[dict] | dict:
    name = proxy['name']

    all_base = []
    if proxy['l3'] == "kcp":
        return {'name': name, 'msg': "clash does not support kcp", 'type': 'debug'}

    base = {}
    all_base.append(base)
    # vmess ws
    base["tag"] = f"""{proxy['extra_info']} {proxy["name"]} § {proxy['port']} {proxy["dbdomain"].id}"""
    if is_xray_proxy(proxy):
        if hutils.flask.is_client_version(hutils.flask.ClientVersion.hiddify_next, 1, 9, 0):
            base['type'] = "xray"
            xp = to_xray(proxy)
            xp['streamSettings']['sockopt'] = {}
            base['xray_outbound_raw'] = xp
            if proxy.get('tls_fragment_enable'):
                base['xray_fragment'] = {
                    'packets': "tlshello",
                    'length': proxy["tls_fragment_size"],
                    'interval': proxy["tls_fragment_sleep"]
                }
            return all_base
        return {'name': name, 'msg': "xray proxy does not support in this client version", 'type': 'debug'}
    base["type"] = str(proxy["proto"])
    base["server"] = proxy["server"]
    base["server_port"] = int(proxy["port"])
    # base['alpn'] = proxy['alpn'].split(',')
    if proxy["proto"] == "ssr":
        add_ssr(base, proxy)
        return all_base
    if proxy["proto"] == ProxyProto.wireguard:
        add_wireguard(base, proxy)
        return all_base

    if proxy['proto']==ProxyProto.mieru:
        add_mieru(base, proxy)
        return all_base
    if proxy['proto']==ProxyProto.naive:
        add_naive(base, proxy)
        return all_base

    if proxy["proto"] in ["ss", "v2ray"]:
        add_shadowsocks_base(all_base, proxy)
        return all_base
    if proxy["proto"] == "ssh":
        add_ssh(all_base, proxy)
        return all_base

    if proxy["proto"] == "trojan":
        base["password"] = proxy["password"]

    if proxy['proto'] in ['vmess', 'vless']:
        base["uuid"] = proxy["uuid"]

    if proxy['proto'] in ['vmess', 'vless', 'trojan']:
        add_multiplex(base, proxy)

    add_tls(base, proxy)

    if g.user_agent.get('is_hiddify'):
        add_tls_tricks(base, proxy)

    if proxy.get('flow'):
        base["flow"] = proxy['flow']
        # base["flow-show"] = True

    if proxy["proto"] == "vmess":
        base["alter_id"] = 0
        base["security"] = proxy["cipher"]

    # base["udp"] = True
    if proxy["proto"] in ["vmess", "vless"]:
        base["packet_encoding"] = "xudp"  # udp packet encoding

    if proxy["proto"] == "tuic":
        add_tuic(base, proxy)
    elif proxy["proto"] == "hysteria2":
        add_hysteria(base, proxy)
    elif proxy["proto"] == "amnezia":
        add_amnezia(base, proxy)
    else:
        add_transport(base, proxy)
        if not base.get('transport'):
            base.pop('transport', None)

    return all_base


def add_multiplex(base: dict, proxy: dict):
    if proxy.get('mux_enable') != "singbox":
        return
    base['multiplex'] = {
        "enabled": True,
        "protocol": proxy['mux_protocol'],
        "padding": proxy['mux_padding_enable']
    }
    # Conflicts: max_streams with max_connections and min_streams
    mux_max_streams = proxy.get('mux_max_streams', 0)
    if mux_max_streams and mux_max_streams != 0:
        base['multiplex']['max_streams'] = mux_max_streams
    else:
        base['multiplex']['max_connections'] = proxy.get('mux_max_connections', 0)
        base['multiplex']['min_streams'] = proxy.get('mux_min_streams', 0)

    add_tcp_brutal(base, proxy)


def add_tcp_brutal(base: dict, proxy: dict):
    if 'multiplex' in base:
        if proxy.get('mux_brutal_enable'):
            base['multiplex']['brutal'] = {
                "enabled": proxy.get('mux_brutal_enable', False),
                "up_mbps": proxy.get('mux_brutal_up_mbps', 10),
                "down_mbps": proxy.get('mux_brutal_down_mbps', 10)
            }


def add_udp_over_tcp(base: dict):
    base['udp_over_tcp'] = {
        "enabled": True,
        "version": 2
    }


def add_tls(base: dict, proxy: dict):
    if proxy['proto'] in ['mieru', 'amnezia', 'wireguard'] or not ("tls" in proxy["l3"] or "reality" in proxy["l3"]):
        return
    base["tls"] = {
        "enabled": True,
        "server_name": proxy["sni"]
    }
    if proxy['proto'] not in ["tuic", "hysteria2"]:
        base["tls"]["utls"] = {
            "enabled": True,
            "fingerprint": proxy.get('fingerprint', 'none')
        }

    if "reality" in proxy["l3"]:
        base["tls"]["reality"] = {
            "enabled": True,
            "public_key": proxy['reality_pbk'],
            "short_id": proxy['reality_short_id']
        }
    base["tls"]['insecure'] = proxy['allow_insecure'] or (proxy["mode"] == "Fake")
    base["tls"]["alpn"] = proxy['alpn'].split(',')
    # base['ech'] = {
    #     "enabled": True,
    # }


def add_tls_tricks(base: dict, proxy: dict):
    if proxy.get('tls_fragment_enable'):
        base['tls_fragment'] = {
            'enabled': True,
            'length': proxy["tls_fragment_size"],
            'interval': proxy["tls_fragment_sleep"]
        }

    if 'tls' in base:
        if proxy.get("tls_padding_enable") or proxy.get("tls_mixed_case"):
            base['tls']['tls_tricks'] = {}
        if proxy.get("tls_padding_enable"):
            base['tls']['tls_tricks']['padding_size'] = proxy["tls_padding_length"]

        if proxy.get("tls_mixed_case"):
            base['tls']['tls_tricks']['mixedcase_sni'] = True


def add_transport(base: dict, proxy: dict):
    if proxy['l3'] == 'reality' and proxy['transport'] not in ["grpc"]:
        return
    base["transport"] = {}
    if proxy['transport'] in ["ws", "WS"]:
        base["transport"] = {
            "type": "ws",
            "path": proxy["path"],
            "early_data_header_name": "Sec-WebSocket-Protocol"
        }
        if "host" in proxy:
            base["transport"]["headers"] = {"Host": proxy["host"]}

    if proxy['transport'] in [ProxyTransport.httpupgrade]:
        base["transport"] = {
            "type": "httpupgrade",
            "path": proxy["path"]
        }
        if "host" in proxy:
            base["transport"]["headers"] = {"Host": proxy["host"]}

    if proxy["transport"] in ["tcp", "h2"]:
        # Check if it's raw TCP (no http obfuscation)
        is_http_obfs = False
        headers = proxy.get('params', {}).get('headers', {})
        if proxy["transport"] == "h2":
             is_http_obfs = True
        elif headers and headers.get('type') != 'none':
             is_http_obfs = True
        
        if is_http_obfs:
            base["transport"] = {
                "type": "http",
                "path": proxy.get("path", "/"),
                "idle_timeout": "115s",
                "ping_timeout": "15s"
            }
            if 'host' in proxy:
                base["transport"]["host"] = [proxy["host"]]
            
            # Add headers if present
            if headers:
                 # Filter out internal keys if any
                 clean_headers = {k:v for k,v in headers.items() if k != 'type'}
                 if clean_headers:
                     base["transport"]["headers"] = clean_headers


    if proxy["transport"] == "grpc":
        base["transport"] = {
            "type": "grpc",
            "service_name": proxy["grpc_service_name"],
            "idle_timeout": "115s",
            "ping_timeout": "15s",
            # "permit_without_stream": false
        }

    if proxy['transport'] == ProxyTransport.xhttp:
        base["transport"] = {
            "type": "http",
            "path": proxy.get("path", "/"),
            "idle_timeout": "15s",
            # "method": "POST",
        }
        headers = proxy.get('params', {}).get('headers', {})
        if headers:
            base["transport"]["headers"] = headers
        if 'host' in proxy:
            base["transport"]["host"] = [proxy["host"]]


def add_ssr(base: dict, proxy: dict):

    base["method"] = proxy["cipher"]
    base["password"] = proxy["uuid"]
    # base["udp"] = True
    base["obfs"] = proxy["ssr-obfs"]
    base["protocol"] = proxy["ssr-protocol"]
    base["protocol-param"] = proxy["fakedomain"]


def add_wireguard(base: dict, proxy: dict):

    base["local_address"] = f'{proxy["wg_ipv4"]}/32'
    base["private_key"] = proxy["wg_pk"]
    base["peer_public_key"] = proxy["wg_server_pub"]

    base["pre_shared_key"] = proxy["wg_psk"]

    base["mtu"] = 1380
    if g.user_agent.get('is_hiddify') and hutils.flask.is_client_version(hutils.flask.ClientVersion.hiddify_next, 0, 15, 0):
        pass # base["fake_packets"] = proxy["wg_noise_trick"]


def add_shadowsocks_base(all_base: list[dict], proxy: dict):
    base = all_base[0]
    base["type"] = "shadowsocks"
    base["method"] = proxy["cipher"]
    base["password"] = proxy["password"]
    add_udp_over_tcp(base)
    add_multiplex(base, proxy)
    if proxy["transport"] == "faketls":
        base["plugin"] = "obfs-local"
        base["plugin_opts"] = f'obfs=tls;obfs-host={proxy["fakedomain"]}'
    if proxy['proto'] == 'v2ray':
        base["plugin"] = "v2ray-plugin"
        # "skip-cert-verify": proxy["mode"] == "Fake" or proxy['allow_insecure'],
        base["plugin_opts"] = f'mode=websocket;path={proxy["path"]};host={proxy["host"]};tls'

    if proxy["transport"] == "shadowtls":
        base['detour'] = base['tag'] + "_shadowtls-out §hide§"

        shadowtls_base = {
            "type": "shadowtls",
            "tag": base['detour'],
            "server": base['server'],
            "server_port": base['server_port'],
            "version": 3,
            "password": proxy["shared_secret"],
            "tls": {
                "enabled": True,
                "server_name": proxy["fakedomain"],
                "utls": {
                    "enabled": True,
                    "fingerprint": proxy.get('fingerprint', 'none')
                },
                # "alpn": proxy['alpn'].split(',')
            }
        }
        # add_utls(shadowtls_base)
        del base['server']
        del base['server_port']
        all_base.append(shadowtls_base)


def add_ssh(all_base: list[dict], proxy: dict):
    base = all_base[0]
    # base["client_version"]= "{{ssh_client_version}}"
    base["user"] = proxy['uuid']
    base["private_key"] = proxy['private_key']  # .replace('\n', '\\n')

    base["host_key"] = proxy.get('host_keys', [])

    socks_front = {
        "type": "socks",
        "tag": base['tag'] + "+UDP",
        "server": "127.0.0.1",
        "server_port": 2000,
        "version": "5",
        "udp_over_tcp": True,
        "network": "tcp",
        "detour": base['tag']
    }
    all_base.append(socks_front)


def add_tuic(base: dict, proxy: dict):
    base['congestion_control'] = "cubic"
    base['udp_relay_mode'] = 'native'
    base['zero_rtt_handshake'] = True
    base['heartbeat'] = "10s"
    base['password'] = proxy['uuid']
    base['uuid'] = proxy['uuid']


def ws_mbps(value):
    # watashi v12.2.79: a bandwidth setting arrives as text out of the config
    # table, while sing-box wants a number. anything unusable becomes None so
    # the field can be left out entirely rather than sent as null.
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def ws_add_port_hopping(base: dict, proxy: dict):
    # watashi v12.2.79: the share link has advertised the hop range since
    # v12.2.63 but the sing-box config never did, so every client that reads
    # json stayed nailed to the single udp port a filter only has to learn
    # once. server_ports and hop_interval arrived in sing-box 1.11.0 and both
    # conflict with server_port, so the single port has to go. sing-box
    # refuses a whole config over one field it does not know, so builds of
    # hiddify next older than 3.0.0 keep the shape their older core knows.
    legacy = g.user_agent.get(hutils.flask.ClientVersion.hiddify_next) and not hutils.flask.is_client_version(hutils.flask.ClientVersion.hiddify_next, 3, 0, 0)
    if legacy:
        return
    span = hutils.proxy.port_hop.active_range()
    if not span:
        return
    base['server_ports'] = ['%d:%d' % (span[0], span[1])]
    base['hop_interval'] = '30s'
    base.pop('server_port', None)


def add_hysteria(base: dict, proxy: dict):
    # watashi v12.2.79: these two were read with a ConfigEnum member as the
    # key while shared.py stores them under the plain string name. ConfigEnum
    # is built on FastEnum with no string base at all, so the lookup could
    # never match: both came out None, json wrote null, and sing-box read
    # that as no limit and quietly fell back to bbr instead of the brutal
    # rate control hysteria2 exists for.
    up = ws_mbps(proxy.get('hysteria_up_mbps'))
    down = ws_mbps(proxy.get('hysteria_down_mbps'))
    if up:
        base['up_mbps'] = up
    if down:
        base['down_mbps'] = down
    # TODO: check the obfs should be empty or not exists at all
    if proxy.get('hysteria_obfs_enable'):
        base['obfs'] = {
            "type": "salamander",
            "password": proxy.get('hysteria_obfs_password')
        }
    base['password'] = proxy['uuid']
    ws_add_port_hopping(base, proxy)


def add_mieru(base: dict, proxy: dict):
    base['type']="mieru"
    base['multiplexing']=proxy.get('multiplexing', 'MULTIPLEXING_MIDDLE')
    base['handshake_mode']=proxy.get('handshake', 'HANDSHAKE_Standard')
    base['username']=proxy.get('uuid', '')
    base['password']=proxy.get('password', 'h')
    base['portBindings']=[]
    
    for port in proxy.get("tcp_ports", []):
        if port:
            base['portBindings'].append({
                'protocol':"TCP",
                "port":0 if "-" in port else int(port),
                "portRange":port if "-" in port else ""
            })
    for port in proxy.get("udp_ports", []):
        if port:
            base['portBindings'].append({
                'protocol':"UDP",
                "port":0 if "-" in port else int(port),
                "portRange":port if "-" in port else ""
            })

    # When portBindings define the transport, the mieru client requires
    # server_port to be unset (0 with bindings is invalid: it must either be
    # absent or exactly match a single binding). to_singbox() sets
    # server_port=int(proxy['port']) which is 0 for mieru, so remove it.
    if base['portBindings']:
        base.pop('server_port', None)


def add_naive(base: dict, proxy: dict):
    base['type'] = 'http'
    base['username'] = proxy['uuid']
    base['password'] = proxy['uuid']
    # if proxy.get('naive_padding'):
    #     base['padding'] = True


def add_amnezia(base: dict, proxy: dict):
    base['type'] = "awg"
    base['server'] = proxy['server']
    base['server_port'] = int(proxy['port'])
    base['local_address'] = [f"{proxy.get('wg_ipv4', '10.111.0.2')}/32", f"{proxy.get('wg_ipv6', 'fc00::2')}/128"]
    base['private_key'] = proxy['wg_pk']
    base['peer_public_key'] = proxy['wg_server_pub']
    base['mtu'] = 1280
    
    # AmneziaWG specific params
    base['s1'] = proxy.get('amnezia_s1', 0)
    base['s2'] = proxy.get('amnezia_s2', 0)
    base['h1'] = str(proxy.get('amnezia_h1', 1))
    base['h2'] = str(proxy.get('amnezia_h2', 2))
    base['h3'] = str(proxy.get('amnezia_h3', 3))
    base['h4'] = str(proxy.get('amnezia_h4', 4))
    base['jc'] = proxy.get('amnezia_jc', 4)
    base['jmin'] = proxy.get('amnezia_jmin', 40)
    base['jmax'] = proxy.get('amnezia_jmax', 70)
