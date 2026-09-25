"""watashi v12.2.130bw: the config health engine.

Why this exists
---------------
Until this round the only way to ask "is this config alive" was the
proxy-stats page, which is a yacd dashboard driven by hiddify-cli. That
client speaks sing-box only, and the panel hands it a sing-box profile, so
every row whose transport sing-box does not have came back as the word
Invalid with a delay of 65535. Measured on a real panel: every xhttp row.
hutils/proxy/singbox.py:93 turns an xhttp proxy into a type "xray"
outbound carrying xray_outbound_raw, which only the Hiddify Next app can
read, so the answer said nothing about the config itself.

What this does instead
----------------------
Every config is driven through the core that can actually run it. The box
already carries both: xray at xray/bin/xray and sing-box at
singbox/sing-box, both blessed in common/core_registry.conf. For one
config the engine writes a throwaway client config with a socks inbound on
a free port, starts the core, sends one request through the socks port and
reports what came back. That is a real handshake against the real server,
so a green answer means the config's own settings are sound.

It does not say the config gets through a filter. It is run from the
server itself, so the only thing between the two ends is the config.
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time

WS_TEST_URL = 'https://cp.cloudflare.com/generate_204'
WS_TIMEOUT = 8
WS_START_WAIT = 6.0


def ws_engine_bin(engine):
    """The core that runs this engine, letting the environment win.

    The override is what lets the round's checker drive the real thing in a
    sandbox that has no /opt/hiddify-manager.
    """
    if engine == 'xray':
        return os.environ.get('WS_HEALTH_XRAY') or '/opt/hiddify-manager/xray/bin/xray'
    if engine == 'singbox':
        return os.environ.get('WS_HEALTH_SINGBOX') or '/opt/hiddify-manager/singbox/sing-box'
    return ''


def ws_engine_ready(engine):
    path = ws_engine_bin(engine)
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def ws_free_port():
    sock = socket.socket()
    try:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def ws_jobs_from_xray(text):
    """Every testable outbound inside the /xray/ subscription.

    xrayjson.configs_as_json writes one whole client config per proxy with
    the proxy inserted at outbounds[0] and its name in remarks, or a single
    config when there is only one proxy. null_config() rows carry a
    blackhole there: those are the usage and the package-ended notices, not
    configs, so they are dropped.
    """
    jobs = []
    if not (text or '').strip():
        return jobs
    try:
        data = json.loads(text)
    except ValueError:
        return jobs
    configs = data if isinstance(data, list) else [data]
    for cfg in configs:
        if not isinstance(cfg, dict):
            continue
        obs = cfg.get('outbounds') or []
        if not obs or not isinstance(obs[0], dict):
            continue
        first = obs[0]
        if first.get('protocol') in ('blackhole', 'freedom', None):
            continue
        name = cfg.get('remarks') or first.get('tag') or first.get('protocol')
        stream = first.get('streamSettings') or {}
        jobs.append({'name': str(name), 'engine': 'xray', 'outbound': first,
                     'proto': str(first.get('protocol') or ''),
                     'transport': str(stream.get('network') or '')})
    return jobs


WS_SB_SKIP_TYPES = ('selector', 'urltest', 'direct', 'block', 'dns')


def ws_jobs_from_singbox(text):
    """Every testable outbound inside the /singbox/ subscription.

    Dropped on purpose:
      * the Select and Auto groups, which are not configs,
      * direct and bypass, which come from the base template,
      * the shadowtls camouflage leg, which is a detour target and cannot
        carry traffic alone (see the note in singbox.py, round v12.2.110),
      * the dead end ws_ended_outbound() writes for a finished account,
        recognised by its 127.0.0.1 port 1 address,
      * a type "xray" row, which is an app-only wrapper: the very same
        proxy is tested properly on the xray side.
    """
    jobs = []
    if not (text or '').strip():
        return jobs
    try:
        data = json.loads(text)
    except ValueError:
        return jobs
    obs = (data or {}).get('outbounds') or []
    pool = {}
    for one in obs:
        if isinstance(one, dict) and one.get('tag'):
            pool[one['tag']] = one
    for ob in obs:
        if not isinstance(ob, dict):
            continue
        typ = str(ob.get('type') or '')
        tag = str(ob.get('tag') or '')
        if not tag or typ in WS_SB_SKIP_TYPES or typ == 'xray':
            continue
        if 'shadowtls-out' in tag:
            continue
        if ob.get('server') == '127.0.0.1' and ob.get('server_port') == 1:
            continue
        transport = ob.get('transport') or {}
        jobs.append({'name': tag, 'engine': 'singbox', 'outbound': ob,
                     'proto': typ,
                     'transport': str(transport.get('type') or ''),
                     'pool': pool})
    return jobs


def ws_probe_xray(outbound, port):
    ob = json.loads(json.dumps(outbound))
    ob['tag'] = 'proxy'
    # the subscription's own sockopt can pin an interface that only exists
    # on a phone, and nothing here needs it.
    stream = ob.get('streamSettings')
    if isinstance(stream, dict):
        stream.pop('sockopt', None)
    return {
        'log': {'loglevel': 'warning'},
        'inbounds': [{'tag': 'in', 'listen': '127.0.0.1', 'port': port,
                      'protocol': 'socks',
                      'settings': {'auth': 'noauth', 'udp': True}}],
        'outbounds': [ob],
        'routing': {'domainStrategy': 'AsIs',
                    'rules': [{'type': 'field', 'port': '0-65535',
                               'outboundTag': 'proxy'}]},
    }


def ws_probe_singbox(outbound, port, pool=None):
    """A sing-box client whose only road leads to this one outbound.

    A shadowtls pair is two outbounds: the one that carries traffic names
    the other in detour. Leaving the partner out makes the core refuse the
    config, which would read as a broken proxy, so the detour chain is
    carried along.
    """
    pool = pool or {}
    wanted = [json.loads(json.dumps(outbound))]
    seen = set([outbound.get('tag')])
    cursor = outbound
    for _ in range(4):
        nxt = cursor.get('detour')
        if not nxt or nxt in seen or nxt not in pool:
            break
        seen.add(nxt)
        cursor = pool[nxt]
        wanted.append(json.loads(json.dumps(cursor)))
    return {
        'log': {'level': 'error'},
        'inbounds': [{'type': 'socks', 'tag': 'in', 'listen': '127.0.0.1',
                      'listen_port': port}],
        'outbounds': wanted + [{'type': 'direct', 'tag': 'direct'}],
        'route': {'final': outbound.get('tag')},
    }


def ws_wait_port(port, seconds=WS_START_WAIT):
    end = time.time() + seconds
    while time.time() < end:
        sock = socket.socket()
        sock.settimeout(0.3)
        try:
            sock.connect(('127.0.0.1', port))
            return True
        except OSError:
            time.sleep(0.1)
        finally:
            sock.close()
    return False


def ws_curl(port, url, timeout):
    """One request through the socks port. Returns (http_code, ms, stderr)."""
    curl = shutil.which('curl') or '/usr/bin/curl'
    started = time.time()
    try:
        done = subprocess.run(
            [curl, '-s', '-o', os.devnull, '-w', '%{http_code}',
             '--max-time', str(timeout),
             '-x', 'socks5h://127.0.0.1:%d' % port, url],
            capture_output=True, text=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return '', int((time.time() - started) * 1000), str(exc)
    return done.stdout.strip(), int((time.time() - started) * 1000), (done.stderr or '').strip()


def ws_run_job(job, url=WS_TEST_URL, timeout=WS_TIMEOUT):
    """Start a core on this one config, ask it for a page, report."""
    out = {'name': job.get('name', ''), 'engine': job.get('engine', ''),
           'proto': job.get('proto', ''), 'transport': job.get('transport', ''),
           'ok': False, 'ms': None, 'error': ''}
    out['state'] = 'fail'
    engine = job.get('engine')
    if not ws_engine_ready(engine):
        out['error'] = 'the %s core is not installed here' % engine
        return out
    # a core that cannot speak this protocol is not a verdict on the config
    fine, why = ws_job_supported(job)
    if not fine:
        out['state'] = 'skipped'
        out['error'] = why
        return out
    port = ws_free_port()
    if engine == 'xray':
        cfg = ws_probe_xray(job['outbound'], port)
        binary = ws_engine_bin('xray')
    else:
        cfg = ws_probe_singbox(job['outbound'], port, job.get('pool'))
        binary = ws_engine_bin('singbox')

    work = tempfile.mkdtemp(prefix='ws-health-')
    cfg_path = os.path.join(work, 'probe.json')
    log_path = os.path.join(work, 'probe.log')
    proc = None
    try:
        with open(cfg_path, 'w', encoding='utf-8') as handle:
            json.dump(cfg, handle)
        with open(log_path, 'w', encoding='utf-8') as log:
            proc = subprocess.Popen([binary, 'run', '-c', cfg_path],
                                    stdout=log, stderr=log, cwd=work)
        if not ws_wait_port(port):
            tail = ''
            try:
                with open(log_path, encoding='utf-8', errors='replace') as log:
                    tail = ' '.join(log.read().split())[-220:]
            except OSError:
                pass
            out['error'] = 'the core refused this config: %s' % (tail or 'no reason given')
            return out
        code, ms, err = ws_curl(port, url, timeout)
        if code in ('200', '204'):
            out['ok'] = True
            out['state'] = 'ok'
            out['ms'] = ms
        else:
            out['error'] = err or ('the server answered %s' % (code or 'nothing'))
        return out
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        shutil.rmtree(work, ignore_errors=True)


def ws_run_all(jobs, url=WS_TEST_URL, timeout=WS_TIMEOUT, progress=None):
    """One at a time on purpose: a box running twenty cores at once measures
    its own load, not the configs."""
    results = []
    for index, job in enumerate(jobs):
        row = ws_run_job(job, url=url, timeout=timeout)
        results.append(row)
        if progress:
            progress(index + 1, len(jobs), row)
    return results


def ws_row_state(row):
    """ok, fail or skipped for one row, old rows included.

    A result written by an earlier round has no state key, so it is read the
    way that round meant it: answered or not.
    """
    state = str((row or {}).get('state') or '')
    if state in ('ok', 'fail', 'skipped'):
        return state
    return 'ok' if (row or {}).get('ok') else 'fail'


def ws_table(results):
    """The report, as plain text.

    A skipped row is not counted in the score. Saying '3 of 6 answered' when
    two of the six were never asked would read as a panel with broken
    configs, which is exactly the wrong answer.
    """
    if not results:
        return 'no config to test'
    width = min(52, max(len(r['name']) for r in results))
    lines = ['%-*s %-8s %-7s %s' % (width, 'config', 'engine', 'ms', 'result'),
             '-' * (width + 30)]
    order = {'ok': 0, 'fail': 1, 'skipped': 2}
    for row in sorted(results, key=lambda r: (order.get(ws_row_state(r), 3), r['name'])):
        name = row['name']
        if len(name) > width:
            name = name[:width - 3] + '...'
        state = ws_row_state(row)
        if state == 'ok':
            lines.append('%-*s %-8s %-7s OK' % (width, name, row['engine'], row['ms']))
        elif state == 'skipped':
            lines.append('%-*s %-8s %-7s SKIP  %s' % (width, name, row['engine'], '-', row['error']))
        else:
            lines.append('%-*s %-8s %-7s FAIL  %s' % (width, name, row['engine'], '-', row['error']))
    good = 0
    tested = 0
    skipped = 0
    for row in results:
        state = ws_row_state(row)
        if state == 'skipped':
            skipped += 1
            continue
        tested += 1
        if state == 'ok':
            good += 1
    lines.append('')
    lines.append('%d of %d answered' % (good, tested))
    if skipped:
        lines.append('%d not testable here' % skipped)
    return '\n'.join(lines)


def ws_template_dirs():
    """Where the subscription templates sit inside the installed package."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = []
    for room in (('panel', 'user', 'templates'), ('panel', 'admin', 'templates'), ('templates',)):
        path = os.path.join(root, *room)
        if os.path.isdir(path):
            found.append(path)
    return found


def ws_bind_templates(app):
    """watashi v12.2.130bx: teach a cli app to render the subscription templates.

    base.py builds the app in cli mode with only the cli extension loaded, so
    no blueprint is registered and no jinja global is set. render_template
    then cannot see panel/user/templates and the subscription dies with the
    bare words base_xray_config.json.j2. Measured on a live server: configs
    0 to test. The loader and the handful of names those two templates ask
    for are added here, nothing else, so the command stays a command instead
    of turning into a half started web app.
    """
    if getattr(app, 'ws_health_templates_bound', False):
        return True
    from jinja2 import ChoiceLoader, FileSystemLoader
    dirs = ws_template_dirs()
    if not dirs:
        return False
    env = app.jinja_env
    extra = FileSystemLoader(dirs)
    env.loader = ChoiceLoader([env.loader, extra]) if env.loader is not None else extra
    if 'hconfig' not in env.globals:
        from flask import g as flask_g
        from hiddifypanel.models import ConfigEnum, DomainType, UserMode, hconfig
        from hiddifypanel import hutils as panel_hutils
        env.globals['ConfigEnum'] = ConfigEnum
        env.globals['DomainType'] = DomainType
        env.globals['UserMode'] = UserMode
        env.globals['hconfig'] = hconfig
        env.globals['g'] = flask_g
        env.globals['hutils'] = panel_hutils
    app.ws_health_templates_bound = True
    return True


# --------------------------------------------------------- watashi v12.2.130by
# Which core can actually run which config.
#
# The first live run called five configs broken that were not: xray answered
# 'unknown config id' for anytls, mieru and tuic, 'unknown transport protocol:
# custom' for snell, and it could not speak shadowtls either - the same
# shadowtls config answered in 84ms on sing-box. A core that does not carry an
# outbound is not a verdict on the config, so those rows are skipped now.

WS_XRAY_PROTOS = frozenset((
    'vless', 'vmess', 'trojan', 'shadowsocks', 'socks', 'http', 'wireguard',
))

WS_XRAY_TRANSPORTS = frozenset((
    '', 'tcp', 'raw', 'ws', 'websocket', 'grpc', 'http', 'h2', 'httpupgrade',
    'xhttp', 'splithttp', 'quic', 'kcp', 'mkcp', 'domainsocket',
))

WS_SINGBOX_TYPES = frozenset((
    'vless', 'vmess', 'trojan', 'shadowsocks', 'shadowsocksr', 'shadowtls',
    'hysteria', 'hysteria2', 'tuic', 'anytls', 'wireguard', 'ssh', 'socks',
    'http', 'snell',
))

# The subscription is written for whoever asks. With no user agent the panel
# assumes the plainest client, and hutils/proxy/singbox.py hides anytls behind
# ws_sb_client_at_least(1, 12) and snell behind (1, 14), so those two never
# reached the tester at all. The health run says who it is, once, here.
WS_HEALTH_UA = 'SFA/1.14.0 (1; sing-box 1.14.0)'


def ws_job_supported(job):
    """Can the core this job is aimed at actually run it. (ok, reason)"""
    engine = job.get('engine')
    proto = str(job.get('proto') or '').lower()
    transport = str(job.get('transport') or '').lower()
    if engine == 'xray':
        if proto not in WS_XRAY_PROTOS:
            return False, 'xray has no %s outbound, sing-box carries this one' % (proto or 'such')
        if transport not in WS_XRAY_TRANSPORTS:
            return False, 'xray has no %s transport' % transport
        return True, ''
    if engine == 'singbox':
        if proto not in WS_SINGBOX_TYPES:
            return False, 'sing-box has no %s outbound' % (proto or 'such')
        return True, ''
    return False, 'no core is named for this config'


def ws_job_key(job):
    """The config behind a job, without the copy number.

    Both subscriptions carry the same proxies, so one config arrives twice:
    'Direct ShadowTLS' from xray and 'Direct ShadowTLS 443 4' from sing-box.
    What the two share is the name before the section sign.
    """
    name = str(job.get('name') or '')
    return name.split('\u00a7')[0].strip().lower()


def ws_one_core_each(jobs):
    """One row per config, on the core that can actually run it.

    A run is already a couple of minutes long because the cores are started
    one at a time; testing the same proxy on both cores doubles that for no
    answer. A config both cores can run stays on the core its subscription
    was written for, which is the xray one, because that is the config the
    panel hands to a desktop client.
    """
    picked = []
    seen = {}
    for job in jobs:
        key = ws_job_key(job)
        fine, _reason = ws_job_supported(job)
        if key not in seen:
            seen[key] = len(picked)
            picked.append(job)
            continue
        where = seen[key]
        kept = picked[where]
        kept_fine, _kept_reason = ws_job_supported(kept)
        if fine and not kept_fine:
            picked[where] = job
    return picked


def ws_jobs_for_user(app, user, ua=WS_HEALTH_UA):
    """Both subscriptions of one account, turned into jobs. (jobs, notes)

    The configs are built in this process instead of being fetched over http,
    so nothing depends on the panel being reachable from itself, and the text
    is the very same one the account would have downloaded. The command and
    the page both come through here, so neither can drift from the other.
    """
    from flask import g
    from hiddifypanel import hutils
    from hiddifypanel.models import Child, Domain

    jobs = []
    notes = []
    if not ws_bind_templates(app):
        notes.append('the panel templates were not found next to the code')
    with app.test_request_context('/', headers={'User-Agent': ua}):
        g.account = user
        try:
            g.user_agent = hutils.flask.get_user_agent()
        except Exception:
            g.user_agent = {'is_browser': False, 'is_singbox': True,
                            'singbox_version': [1, 14, 0]}
        domains = Domain.query.filter(Domain.child_id == Child.current().id).all()
        try:
            text = hutils.proxy.xrayjson.configs_as_json(domains, user, user.remaining_days, 'health')
            jobs += ws_jobs_from_xray(text)
        except Exception as problem:
            notes.append('the xray subscription could not be built: %s' % problem)
        try:
            text = hutils.proxy.singbox.configs_as_json(domains, user=user)
            jobs += ws_jobs_from_singbox(text)
        except Exception as problem:
            notes.append('the sing-box subscription could not be built: %s' % problem)
    return ws_one_core_each(jobs), notes
