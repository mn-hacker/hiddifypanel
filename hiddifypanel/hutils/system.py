"""watashi v12.2.129.4: the figures behind the dashboard.

What changed in this round, and why every line of it was needed:

  * every rate is now bytes or jiffies per second over a measured interval,
    taken from hutils.sysstat, which keeps its baselines in redis. Before this,
    a difference between two calls was shown as a speed without ever being
    divided by the time it covered, and whichever caller asked first consumed
    the baseline for everyone else. That is where the spikes came from.
  * cpu is the share of the whole machine, straight from /proc/stat, so two
    readers a moment apart cannot see 0% and 100% for the same second.
  * the size of /opt/hiddify-manager is not walked on every request any more.
    It was a full directory walk every two seconds, which made the answer late
    and the graph stutter as a consequence.
  * open connections count ESTABLISHED sockets only. Counting every state made
    the TIME_WAIT a proxy leaves behind look like a crowd of users.
  * load average is reported as the kernel writes it, and the per core ratio is
    offered beside it under its own name instead of being passed off as load.
  * the protocol split is measured from the core's own counters. It used to be
    generated with random.Random(time/10): an invented number on a page whose
    whole purpose is to be believed.
"""

import os
import statistics
import time

from . import sysstat

WS_PANEL_DIR = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager') + '/'
WS_FOLDER_TTL = 600      # the panel folder grows by the hour, not by the second
WS_CONN_TTL = 4          # /proc/net/tcp is cheap but not free
WS_PING_TTL = 30
GB = 1024 ** 3
MB = 1024 ** 2


def get_folder_size(folder_path: str) -> int:
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for file in filenames:
                file_path = os.path.join(dirpath, file)
                try:
                    total_size += os.path.getsize(file_path)
                except BaseException:
                    pass
    except BaseException:
        pass
    return total_size


def _cached(key, ttl, build):
    """One answer kept for `ttl` seconds, shared by every reader through redis."""
    now = time.time()
    was = sysstat.recall(key)
    if was and 'v' in was and (now - float(was.get('t', 0))) < ttl:
        return was['v']
    try:
        value = build()
    except Exception:
        return was['v'] if was and 'v' in was else None
    sysstat.remember(key, {'v': value, 't': now})
    return value


def panel_folder_size() -> int:
    return _cached('folder', WS_FOLDER_TTL, lambda: get_folder_size(WS_PANEL_DIR)) or 0


def _connections():
    return _cached('conns', WS_CONN_TTL, sysstat.connections) or (0, 0)


def _proc_age(pid) -> int:
    """How long a process has been running, in seconds, from /proc alone."""
    try:
        raw = open('/proc/%s/stat' % pid).read()
        started = float(raw[raw.rindex(')') + 2:].split()[19]) / os.sysconf('SC_CLK_TCK')
        return max(0, int(float(open('/proc/uptime').read().split()[0]) - started))
    except Exception:
        return 0


def panel_uptime() -> int:
    """This panel process, exactly. Not "since somebody first asked"."""
    return _proc_age('self')


def core_uptime() -> int:
    """The proxy core, whichever of the two is running."""
    wanted = ('xray', 'sing-box')
    try:
        pids = [p for p in os.listdir('/proc') if p.isdigit()]
    except Exception:
        return 0
    for pid in pids:
        try:
            name = open('/proc/%s/comm' % pid).read().strip().lower()
        except Exception:
            continue
        if name in wanted:
            return _proc_age(pid)
    return 0


def _proc_footprint(pid, page: int) -> int:
    """Bytes a process really holds: pss when the kernel offers it, else rss."""
    try:
        with open('/proc/%s/smaps_rollup' % pid) as handle:
            for row in handle:
                if row.startswith('Pss:'):
                    return int(row.split()[1]) * 1024
    except Exception:
        pass
    try:
        raw = open('/proc/%s/stat' % pid).read()
        return int(raw[raw.rindex(')') + 2:].split()[21]) * page
    except Exception:
        return 0


def panel_memory() -> int:
    """Resident bytes of the panel itself, which is what the card claims.

    The card used to show the size of /opt/hiddify-manager on disk under the
    title PANEL MEMORY. A folder is not memory.
    """
    # watashi v12.2.129.5: the page size was hard coded at 4096 and the same
    # shared pages were counted once per panel process, so the figure ran a
    # little high. smaps_rollup gives the proportional set size, which splits
    # shared pages between the processes holding them; rss is the fallback.
    total = 0
    try:
        page = os.sysconf("SC_PAGE_SIZE")
    except Exception:
        page = 4096
    try:
        pids = [p for p in os.listdir('/proc') if p.isdigit()]
    except Exception:
        return 0
    for pid in pids:
        try:
            with open('/proc/%s/cmdline' % pid, 'rb') as handle:
                line = handle.read().decode('utf-8', 'replace')
            if 'hiddifypanel' not in line and 'hiddify-panel' not in line:
                continue
            total += _proc_footprint(pid, page)
        except Exception:
            continue
    if not total:
        try:
            total = _proc_footprint('self', page)
        except Exception:
            total = 0
    return total


def top_processes() -> dict:
    """Every process by its real share of the machine and its real footprint.

    The shape is the one the dashboard already reads: a list of (name, value)
    with cpu as a percentage of the whole box and ram in gigabytes.
    """
    rows = sysstat.process_cpu()
    by_cpu = [(r['name'], round(r['cpu'], 2)) for r in rows]
    by_ram = sorted(((r['name'], r['ram'] / GB) for r in rows), key=lambda x: -x[1])
    return {'cpu': by_cpu, 'ram': by_ram, 'memory': by_ram}


def system_stats() -> dict:
    """One reading of the machine. Same keys as before, honest values."""
    now = time.time()
    cpu_percent = sysstat.cpu_percent(now=now)
    mem = sysstat.memory()
    dsk = sysstat.disk('/')
    recv_total, sent_total = sysstat.netdev()
    recv_rate = sysstat.rate('net_recv', recv_total, now=now)
    sent_rate = sysstat.rate('net_sent', sent_total, now=now)
    conns, peers = _connections()
    one, five, fifteen = sysstat.loadavg()
    cores = sysstat.cpu_count()
    folder = panel_folder_size()
    panel_ram = panel_memory()

    return {
        'cpu_percent': cpu_percent,
        'num_cpus': cores,

        'ram_used': mem['used'] / GB,
        'ram_total': mem['total'] / GB,
        'ram_available': mem['available'] / GB,
        'ram_percent': mem['percent'],

        'disk_used': dsk['used'] / GB,
        'disk_total': dsk['total'] / GB,
        'disk_free': dsk['free'] / GB,
        'disk_percent': dsk['percent'],

        'swap_used': mem['swap_used'] / MB,
        'swap_total': mem['swap_total'] / MB,
        'swap_percent': mem['swap_percent'],

        # watashi v12.2.129.4: bytes per second, measured. The old keys carried
        # "bytes since some earlier call" and the page divided them by a fixed
        # two seconds and multiplied by eight, so the speed on screen was eight
        # times too large and jumped by however late the last poll had been.
        'net_recv_rate': recv_rate,
        'net_sent_rate': sent_rate,
        'net_rate_unit': 'bytes/s',
        'bytes_recv': recv_rate,
        'bytes_sent': sent_rate,
        'bytes_recv_cumulative': recv_total,
        'bytes_sent_cumulative': sent_total,
        'net_recv_cumulative_GB': recv_total / GB,
        'net_sent_cumulative_GB': sent_total / GB,
        'net_total_cumulative_GB': (recv_total + sent_total) / GB,

        'total_connections': conns,
        'total_unique_ips': peers,

        # the kernel's own numbers, and the ratio under its own name
        'load_avg_1min': one,
        'load_avg_5min': five,
        'load_avg_15min': fifteen,
        'load_per_core_1min': one / cores,
        'load_per_core_5min': five / cores,
        'load_per_core_15min': fifteen / cores,

        'system_uptime': sysstat.uptime(),
        'panel_uptime': panel_uptime(),
        'xray_uptime': core_uptime(),

        'panel_ram': panel_ram / GB,
        # watashi v12.2.129.5: the card is in megabytes of panel memory while
        # every card beside it is gigabytes of the whole machine, so the share
        # travels with it and the card can name the whole it belongs to.
        'panel_ram_share': (panel_ram / mem['total'] * 100) if mem['total'] else 0,
        'hiddify_used': folder / GB,
        'hiddify_folder_GB': folder / GB,
    }


def get_network_latency():
    """Round trip to a fixed address, as the middle of several readings.

    One connect told the page whatever that one connect happened to cost, and
    it was paid for inside the request. Now three quick readings are taken at
    most twice a minute and the middle one is reported, which is the figure
    that does not move when a single packet is unlucky.
    """
    def build():
        import socket
        seen = []
        for _try in range(3):
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.8)
            try:
                sock.connect(('1.1.1.1', 53))
                seen.append((time.time() - start) * 1000.0)
            except Exception:
                pass
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        return int(statistics.median(seen)) if seen else -1
    out = _cached('ping', WS_PING_TTL, build)
    return -1 if out is None else out


# --------------------------------------------------------------- protocols
WS_PROTOCOLS = ('vless', 'vmess', 'trojan', 'shadowsocks', 'ss', 'hysteria', 'hysteria2',
                'tuic', 'wireguard', 'naive', 'mieru', 'anytls', 'shadowtls', 'http', 'socks')


def ws_protocol_of(tag: str) -> str:
    """The protocol a core inbound tag belongs to.

    Tags look like vless-tcp, trojan_ws, ss-inbound: the protocol is the first
    word. Anything unrecognised keeps its own name rather than being dropped,
    because a config the panel hands out and cannot name is worth seeing.
    """
    word = str(tag or '').strip().lower()
    for sep in ('-', '_', '.', ' ', '>'):
        word = word.replace(sep, '|')
    first = [w for w in word.split('|') if w]
    if not first:
        return ''
    head = first[0]
    if head in ('ss', 'shadowsocks'):
        return 'shadowsocks'
    if head in ('hy2', 'hysteria2'):
        return 'hysteria2'
    return head


# inbounds the core keeps for itself: the stats api, dns, and the
# direct/block outbound tags. None of them is user traffic.
WS_NOT_PROTOCOL = ('api', 'dns', 'direct', 'block', 'blackhole', 'freedom', 'warp', 'metrics')


def ws_protocol_share(rows) -> dict:
    """Bytes per protocol from raw (name, value) counter rows.

    Kept apart from the network call so it can be tested with known input.
    Only the inbound rows are looked at, uplink and downlink are added, and
    everything is grouped by protocol.
    """
    out = {}
    for name, value in rows:
        text = str(name or '')
        if not text.startswith('inbound>>>'):
            continue
        bits = text.split('>>>')
        if len(bits) < 2:
            continue
        proto = ws_protocol_of(bits[1])
        if not proto or proto in WS_NOT_PROTOCOL:
            continue
        try:
            out[proto] = out.get(proto, 0) + int(value or 0)
        except Exception:
            continue
    return out


def ws_protocol_rows():
    """The core's inbound counters, or an empty list if no core answers.

    reset is never asked for: these counters are also read by the usage
    accounting, and draining them here would quietly steal traffic from it.
    """
    try:
        import xtlsapi
    except Exception:
        return []
    for build in (lambda: xtlsapi.SingboxClient('127.0.0.1', 10086),
                  lambda: xtlsapi.XrayClient('127.0.0.1', 10085)):
        try:
            rows = [(r.name, r.value) for r in build().stats_query('inbound', reset=False)]
            if rows:
                return rows
        except Exception:
            continue
    return []


def get_protocol_distribution() -> dict:
    """The share of recent traffic each protocol carried, in percent.

    Measured, not invented. The counters are cumulative since the core started,
    so the growth of each one is taken over the interval between readings: that
    is what makes this the split of traffic happening now rather than the split
    of everything since the last restart. An empty answer means no core
    answered, and the page says so instead of drawing a number.
    """
    totals = ws_protocol_share(ws_protocol_rows())
    if not totals:
        return {}
    now = time.time()
    moved = {}
    for proto, value in totals.items():
        moved[proto] = sysstat.rate('proto_' + proto, value, now=now, floor=1.0)
    alive = sum(moved.values())
    if alive <= 0:
        # nothing moved between the two readings: fall back to the shape of the
        # traffic since the core came up, which is still a measurement.
        alive = sum(totals.values())
        moved = totals
        if alive <= 0:
            return {}
    share = {p: round(v / alive * 100.0, 1) for p, v in moved.items() if v > 0}
    return dict(sorted(share.items(), key=lambda kv: -kv[1]))
