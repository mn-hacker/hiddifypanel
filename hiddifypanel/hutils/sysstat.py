"""watashi v12.2.129.4: one honest reading of this machine.

Every figure on the dashboard used to be a difference between two calls of a
function, with the previous call's numbers kept on the function object and no
record of *when* that call happened. Three things followed from that, and all
three were on screen:

  * the difference was never divided by the time it covered, so a counter read
    two seconds apart and a counter read thirty seconds apart produced numbers
    that looked like the same kind of thing and were not;
  * whoever asked first consumed the baseline, so a second reader a moment
    later measured a fraction of a second and saw either nothing or everything
    - the spikes users reported;
  * nothing survived a restart of the process, so the panel's own uptime went
    back to zero while the panel kept running.

This module answers differently. Counters are read straight from /proc, which
is where the kernel keeps them, and every reading is stored together with the
clock time it was taken at. A rate is therefore always bytes (or jiffies) per
second over a measured interval, and it is the same number no matter who asks
or how often. The store is redis when redis is there - the panel already
depends on it - so all readers and all restarts share one baseline; a plain
dict stands in when it is not, which is no worse than what came before.

No psutil here. Not because psutil is bad, but because its cpu_percent and its
per process counters keep exactly the kind of hidden per process baseline this
module exists to remove.
"""

import json
import os
import time

# ------------------------------------------------------------------ the store
# redis is shared by every worker and survives a restart of the panel, which is
# what makes a baseline a baseline. It is asked for lazily and never required.
_LOCAL = {}
_PREFIX = 'ws:stat:'
_TTL = 3600


def _redis():
    try:
        from hiddifypanel.cache import redis_client
        return redis_client
    except Exception:
        return None


def remember(key, data):
    """Keep one reading. Silence on failure: a lost baseline is not an error."""
    raw = json.dumps(data)
    client = _redis()
    if client is not None:
        try:
            client.setex(_PREFIX + key, _TTL, raw)
            return
        except Exception:
            pass
    _LOCAL[key] = raw


def recall(key):
    """The last reading, or None. Never raises."""
    client = _redis()
    if client is not None:
        try:
            raw = client.get(_PREFIX + key)
            if raw is not None:
                return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            pass
    raw = _LOCAL.get(key)
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


def rate(key, value, now=None, floor=0.4):
    """How fast a counter is growing, per second, over the time it really took.

    A counter that went backwards means the machine rebooted or the interface
    was recreated: there is no honest rate to report for that step, so the
    baseline is moved and zero is returned rather than a made up spike.

    Two calls closer together than `floor` seconds cannot measure a rate
    usefully - a hundredth of a second of jitter would become a hundredfold
    error - so the last rate is repeated instead of inventing a new one.
    """
    now = time.time() if now is None else now
    was = recall(key)
    if not was or 'v' not in was or 't' not in was:
        remember(key, {'v': value, 't': now, 'r': 0.0})
        return 0.0
    span = now - float(was['t'])
    if span < floor:
        return float(was.get('r', 0.0) or 0.0)
    if value < float(was['v']):
        remember(key, {'v': value, 't': now, 'r': 0.0})
        return 0.0
    out = (value - float(was['v'])) / span
    remember(key, {'v': value, 't': now, 'r': out})
    return out


# ------------------------------------------------------------------- /proc bits
def _text(path):
    try:
        with open(path, 'r') as handle:
            return handle.read()
    except Exception:
        return ''


def cpu_jiffies():
    """(busy, total) from the first line of /proc/stat, in jiffies."""
    for line in _text('/proc/stat').splitlines():
        if line.startswith('cpu '):
            parts = [int(x) for x in line.split()[1:] if x.isdigit()]
            if len(parts) < 4:
                break
            total = sum(parts)
            # idle + iowait: a cpu waiting for a disk is not a cpu doing work
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            return total - idle, total
    return 0, 0


def cpu_percent(key='cpu', now=None):
    """The share of the whole machine that was busy since the last reading.

    Jiffies are absolute since boot, so this is exact: no interval has to be
    guessed and no baseline is hidden inside a library.
    """
    busy, total = cpu_jiffies()
    if total <= 0:
        return 0.0
    now = time.time() if now is None else now
    was = recall(key)
    remember(key, {'b': busy, 'c': total, 't': now, 'p': None})
    if not was or 'c' not in was:
        return 0.0
    span = total - float(was['c'])
    if span <= 0:
        return float(was.get('p') or 0.0)
    out = max(0.0, min(100.0, (busy - float(was['b'])) / span * 100.0))
    remember(key, {'b': busy, 'c': total, 't': now, 'p': out})
    return out


def meminfo():
    """/proc/meminfo as a dict of kilobytes."""
    out = {}
    for line in _text('/proc/meminfo').splitlines():
        bits = line.split(':', 1)
        if len(bits) == 2:
            digits = bits[1].strip().split()
            if digits and digits[0].isdigit():
                out[bits[0]] = int(digits[0])
    return out


def memory():
    """What `free -h` calls used, total and available, in bytes.

    MemAvailable is the kernel's own answer to "how much can a new process
    have", which is the only definition an operator can act on. used is total
    minus that, so cache and buffers are not counted as occupied.
    """
    info = meminfo()
    total = info.get('MemTotal', 0) * 1024
    avail = info.get('MemAvailable', info.get('MemFree', 0)) * 1024
    used = max(0, total - avail)
    swap_total = info.get('SwapTotal', 0) * 1024
    swap_used = max(0, swap_total - info.get('SwapFree', 0) * 1024)
    return {
        'total': total, 'available': avail, 'used': used,
        'percent': (used / total * 100.0) if total else 0.0,
        'swap_total': swap_total, 'swap_used': swap_used,
        'swap_percent': (swap_used / swap_total * 100.0) if swap_total else 0.0,
    }


def default_iface():
    """The interface the default route leaves by, or ''.

    Counting every interface would count the same packet more than once: a
    tunnel carries the traffic and the real card carries the tunnel. The card
    the default route uses is the one that sees everything exactly once.
    """
    best = ''
    for line in _text('/proc/net/route').splitlines()[1:]:
        cols = line.split()
        if len(cols) > 2 and cols[1] == '00000000':
            best = cols[0]
            break
    if best:
        return best
    for line in _text('/proc/net/ipv6_route').splitlines():
        cols = line.split()
        if len(cols) > 9 and cols[0] == '0' * 32 and cols[1] == '00':
            return cols[-1]
    return ''


_SKIP = ('lo', 'veth', 'docker', 'br-', 'virbr', 'tun', 'tap', 'wg', 'warp', 'sit', 'dummy')


def netdev():
    """(bytes received, bytes sent) since boot, counted once.

    The default route's interface is used when it can be found; otherwise every
    interface that is not a loopback, a bridge, a container pair or a tunnel is
    added up, which is the same set on a plain server.
    """
    want = default_iface()
    recv = sent = 0
    for line in _text('/proc/net/dev').splitlines():
        if ':' not in line:
            continue
        name, rest = line.split(':', 1)
        name = name.strip()
        cols = rest.split()
        if len(cols) < 9:
            continue
        if want:
            if name != want:
                continue
        elif name.startswith(_SKIP):
            continue
        recv += int(cols[0])
        sent += int(cols[8])
    return recv, sent


def loadavg():
    """The three load figures as the kernel writes them: runnable tasks.

    Not divided by the core count. A load of four on a four core box is a load
    of four; dividing it turns a number an operator knows into one nobody does.
    """
    bits = _text('/proc/loadavg').split()
    try:
        return float(bits[0]), float(bits[1]), float(bits[2])
    except Exception:
        return 0.0, 0.0, 0.0


def cpu_count():
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:
        return 1


def uptime():
    """Seconds since the machine booted."""
    try:
        return int(float(_text('/proc/uptime').split()[0]))
    except Exception:
        return 0


def disk(path='/'):
    """Used and total bytes of the filesystem holding `path`.

    df counts the reserved blocks as neither free nor available; the same
    arithmetic is used here so the card and `df -h` agree.
    """
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        return {'used': used, 'total': total, 'free': free,
                'percent': (used / (used + free) * 100.0) if (used + free) else 0.0}
    except Exception:
        return {'used': 0, 'total': 0, 'free': 0, 'percent': 0.0}


_TCP_ESTABLISHED = '01'


def connections():
    """(established, unique remote addresses) from /proc/net/tcp{,6}.

    Only ESTABLISHED is counted. The old figure included every socket in every
    state, so a burst of TIME_WAIT - which is what a proxy leaves behind after
    each connection closes - looked like a burst of users.
    """
    total = 0
    peers = set()
    for name in ('/proc/net/tcp', '/proc/net/tcp6'):
        for line in _text(name).splitlines()[1:]:
            cols = line.split()
            if len(cols) < 4 or cols[3] != _TCP_ESTABLISHED:
                continue
            total += 1
            remote = cols[2].split(':')[0]
            if remote and remote.strip('0') != '':
                peers.add(remote)
    return total, len(peers)


def process_cpu(now=None, limit=0):
    """Every process with a real cpu share and a real resident size.

    /proc/<pid>/stat holds the jiffies a process has spent on the cpu since it
    started. Dividing the growth of that by the growth of the machine's total
    jiffies gives the share of the whole box, which is what the card claims to
    show. psutil's per process percent is a difference against whatever moment
    that Process object last happened to be read, which is why the list used to
    be full of zeroes and impossible numbers.
    """
    now = time.time() if now is None else now
    _busy, total = cpu_jiffies()
    was = recall('procs') or {}
    old_total = float(was.get('total') or 0)
    old = was.get('p') or {}
    span = total - old_total
    fresh = {}
    rows = {}
    try:
        pids = [p for p in os.listdir('/proc') if p.isdigit()]
    except Exception:
        pids = []
    page = 4096
    for pid in pids:
        raw = _text('/proc/%s/stat' % pid)
        if not raw:
            continue
        try:
            close = raw.rindex(')')
            name = raw[raw.index('(') + 1:close]
            cols = raw[close + 2:].split()
            ticks = int(cols[11]) + int(cols[12])  # utime + stime
            rss = int(cols[21]) * page
        except Exception:
            continue
        fresh[pid] = ticks
        share = 0.0
        if span > 0 and pid in old:
            share = max(0.0, (ticks - float(old[pid])) / span * 100.0)
        row = rows.setdefault(name, {'name': name, 'cpu': 0.0, 'ram': 0})
        row['cpu'] += share
        row['ram'] += rss
    remember('procs', {'total': total, 't': now, 'p': fresh})
    out = list(rows.values())
    out.sort(key=lambda r: (-r['cpu'], -r['ram']))
    return out[:limit] if limit else out
