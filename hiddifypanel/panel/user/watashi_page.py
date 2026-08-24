"""Everything the Watashi user page needs, gathered in plain helpers.

The view hands the common data over, this module turns it into words, rows and
numbers the template can draw without thinking.
"""

import base64
import datetime
import json
import urllib.parse

from flask import g, request
from flask_babel import gettext as _

from hiddifypanel import hutils
from hiddifypanel.models import ConfigEnum, hconfig
from hiddifypanel.panel import watashi_settings

J_MONTH_DAYS = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
G_MONTH_SUM = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def flag(name):
    '''Reads one panel switch without ever raising.'''
    try:
        return bool(hconfig(getattr(ConfigEnum, name)))
    except Exception:
        return False


def word_of(name):
    '''Reads one branding sentence of the panel.'''
    try:
        return str(hconfig(getattr(ConfigEnum, name)) or '').strip()
    except Exception:
        return ''


def size_words(num):
    '''Turns a byte count into something a person can read.'''
    try:
        num = float(num or 0)
    except Exception:
        num = 0.0
    if num < 0:
        num = 0.0
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if num < 1024 or unit == 'PB':
            if unit == 'B':
                return '%d %s' % (int(num), unit)
            return '%.2f %s' % (num, unit)
        num = num / 1024.0
    return '0 B'


def to_jalali(day):
    '''Turns a western date into the Iranian one.'''
    year = day.year - 621
    leap = (day.year % 4 == 0 and day.year % 100 != 0) or day.year % 400 == 0
    doy = G_MONTH_SUM[day.month - 1] + day.day + (1 if (leap and day.month > 2) else 0)
    march = 80 if leap else 79
    if doy > march:
        doy = doy - march
    else:
        year = year - 1
        past_leap = ((day.year - 1) % 4 == 0 and (day.year - 1) % 100 != 0) or (day.year - 1) % 400 == 0
        doy = doy + (366 if past_leap else 365) - march
    month = 1
    for length in J_MONTH_DAYS:
        if doy <= length:
            break
        doy = doy - length
        month = month + 1
    return year, month, doy


def day_words(day, lang):
    '''Writes a date the way the reader expects it.'''
    if not day:
        return '—'
    try:
        if lang == 'fa':
            year, month, rest = to_jalali(day)
            return '%04d/%02d/%02d' % (year, month, rest)
        return day.strftime('%Y-%m-%d')
    except Exception:
        return '—'


def ago_words(when):
    '''Says how long ago something happened.'''
    try:
        if not when or when.year < 1900:
            return _('No connection has been seen yet')
        gap = datetime.datetime.utcnow() - when
        hours = gap.days * 24 + int(gap.seconds / 3600)
        if gap.days > 365:
            return _('A long time ago')
        if gap.days >= 1:
            return _('@N@ days ago').replace('@N@', str(gap.days))
        if hours >= 1:
            return _('@N@ hours ago').replace('@N@', str(hours))
        return _('A few minutes ago')
    except Exception:
        return _('No connection has been seen yet')


def hello_words():
    '''Greets by the clock of the reader.'''
    try:
        hour = datetime.datetime.now().hour
    except Exception:
        hour = 10
    if hour < 5:
        return _('Good night')
    if hour < 12:
        return _('Good morning')
    if hour < 17:
        return _('Good afternoon')
    if hour < 21:
        return _('Good evening')
    return _('Good night')


def tone_of_proto(proto):
    '''Gives every protocol its own colour.'''
    name = str(proto or '').lower()
    if 'vless' in name or 'reality' in name:
        return 'purple'
    if 'vmess' in name:
        return 'blue'
    if 'trojan' in name:
        return 'green'
    if 'hy' in name or 'tuic' in name:
        return 'orange'
    if 'ss' in name or 'wire' in name or 'ssh' in name:
        return 'red'
    return 'blue'


def short_of(value):
    '''Keeps a badge short enough for the layout.'''
    text = str(value or '').strip()
    text = text.replace('_', ' ')
    if len(text) > 12:
        text = text[:12]
    return text


def kind_words(mode):
    '''Names the sort of address in plain words.'''
    name = str(mode or '').lower()
    if 'auto_cdn' in name:
        return _('Auto CDN')
    if 'cdn' in name:
        return _('CDN')
    if 'relay' in name:
        return _('Relay')
    if 'reality' in name:
        return 'Reality'
    if 'fake' in name:
        return _('Fake')
    if 'old' in name:
        return _('Backup')
    return _('Direct')


def base_of(link, host):
    '''Swaps the address of a link, keeping the rest of it.'''
    try:
        bits = urllib.parse.urlsplit(link)
        path = bits.path if bits.path.endswith('/') else bits.path + '/'
        return urllib.parse.urlunsplit((bits.scheme, host, path, '', ''))
    except Exception:
        return link


def server_rows(common, settings):
    '''Builds the address chooser of the smart link box.'''
    home = str(common.get('profile_url') or '')
    if home and not home.endswith('/'):
        home += '/'
    host = ''
    try:
        host = urllib.parse.urlsplit(home).netloc
    except Exception:
        host = ''
    rows = [{'label': host or '—', 'kind': _('Your current address'), 'base': home, 'panel': home}]
    seen = set([str(host).lower()])
    wanted = set()
    for one in (settings.get('domains') or []):
        wanted.add(str(one).strip().lower())
    if not wanted:
        return rows
    book = common.get('hdomains') or {}
    pairs = []
    try:
        for mode, doms in book.items():
            for dom in (doms or []):
                pairs.append((mode, dom))
    except Exception:
        pairs = []
    for mode, dom in pairs:
        name = str(getattr(dom, 'domain', '') or '').strip()
        if not name or '*' in name:
            continue
        if name.lower() in seen or name.lower() not in wanted:
            continue
        seen.add(name.lower())
        spot = base_of(home, name)
        alias = str(getattr(dom, 'alias', '') or '').strip()
        rows.append({'label': name, 'kind': alias or kind_words(getattr(dom, 'mode', mode)),
                     'base': spot, 'panel': spot})
    return rows


LINK_WORDS = {
    'sub': ('Smart link', 'Best choice for the Watashi and sing-box apps'),
    'sub64': ('Subscription link (Base64)', 'For V2rayNG, Streisand, V2Box and similar apps'),
    'xray': ('Full Xray config', 'A ready JSON config for Xray based apps'),
    'singbox': ('Full Sing-box config', 'A ready JSON config for Sing-box based apps'),
    'meta': ('Clash Meta', 'For Clash Meta, Clash Verge and Stash'),
    'clash': ('Clash', 'For the classic Clash apps'),
    'text': ('Plain config links', 'Every config as plain text, one per line'),
    'ssh': ('Sing-box over SSH', 'Only for the SSH tunnel'),
    'wg': ('WireGuard', 'A ready config for WireGuard apps'),
    'panel': ('My panel address', 'This very page, keep it for yourself'),
}


def sub_rows(settings):
    '''Builds the rows of the all links column.'''
    rows = []
    for row in watashi_settings.LINK_BOOK:
        name = row['id']
        if not watashi_settings.link_on(settings, name):
            continue
        if name == 'ssh' and not flag('ssh_server_enable'):
            continue
        if name == 'wg' and not flag('wireguard_enable'):
            continue
        title, note = LINK_WORDS.get(name, (name, ''))
        rows.append({
            'path': row['path'],
            'deep': row['deep'] if row['deep'] != 'app' else 'sbox',
            'tag': row['tag'],
            'tone': row['tone'],
            'name': _(title),
            'note': _(note),
        })
    return rows


def plain_row(proto, body):
    '''Reads one ready made config link.'''
    name = ''
    if '#' in body:
        body, tail = body.split('#', 1)
        name = urllib.parse.unquote(tail).strip()
    ask = {}
    if '?' in body:
        body, tail = body.split('?', 1)
        try:
            ask = dict(urllib.parse.parse_qsl(tail))
        except Exception:
            ask = {}
    spot = body.split('@')[-1].split('/')[0]
    if spot.startswith('['):
        server = spot.split(']')[0].strip('[')
    elif ':' in spot:
        server = spot.rsplit(':', 1)[0]
    else:
        server = spot
    guard = ask.get('security') or ''
    if not guard and proto in ['trojan', 'hysteria2', 'hy2', 'tuic']:
        guard = 'tls'
    return {
        'name': name or proto.upper(),
        'server': server,
        'proto': short_of(proto.upper()),
        'transport': short_of(ask.get('type') or ask.get('obfs') or ''),
        'l3': short_of(guard),
        'tone': tone_of_proto(proto),
    }


def vmess_row(body):
    '''Reads a vmess link, whose body is packed json.'''
    raw = body.split('#')[0].strip()
    try:
        pad = raw + '=' * (-len(raw) % 4)
        bag = json.loads(base64.b64decode(pad).decode('utf-8', 'ignore'))
    except Exception:
        return None
    if not isinstance(bag, dict):
        return None
    return {
        'name': str(bag.get('ps') or 'VMESS').strip(),
        'server': str(bag.get('add') or ''),
        'proto': 'VMESS',
        'transport': short_of(bag.get('net') or ''),
        'l3': short_of(bag.get('tls') or ''),
        'tone': 'blue',
    }


def cfg_text(common):
    '''Asks the panel for the very same list the all.txt link returns.'''
    try:
        return hutils.proxy.xray.make_v2ray_configs(
            common.get('domains'), common.get('user'),
            common.get('expire_days'), common.get('ip_debug'))
    except Exception as trouble:
        print('watashi user page: the plain config list could not be made', trouble)
    return ''


def cfg_rows_slow(common):
    '''The older way, kept as a second chance.'''
    rows = []
    try:
        found = hutils.proxy.get_valid_proxies(common.get('domains') or [])
    except Exception as trouble:
        print('watashi user page: the proxy list could not be read', trouble)
        return rows
    for one in found:
        try:
            link = hutils.proxy.xray.to_link(one)
        except Exception as trouble:
            print('watashi user page: a config link could not be written', trouble)
            continue
        if not isinstance(link, str) or '://' not in link:
            continue
        rows.append({
            'url': link,
            'name': str(one.get('name') or '').replace('_', ' ').strip() or 'config',
            'server': str(one.get('server') or ''),
            'proto': short_of(one.get('proto')),
            'transport': short_of(one.get('transport')),
            'l3': short_of(one.get('l3')),
            'tone': tone_of_proto(one.get('proto')),
        })
        if len(rows) >= 200:
            break
    return rows


def cfg_rows(common):
    '''Builds one row for every single config the user may use.'''
    rows = []
    for line in str(cfg_text(common) or '').replace('\r', '').split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or '://' not in line:
            continue
        proto = line.split('://', 1)[0].lower()
        body = line.split('://', 1)[1]
        row = vmess_row(body) if proto == 'vmess' else plain_row(proto, body)
        if not row:
            continue
        if row['server'] in ['1.1.1.1', '127.0.0.1', '']:
            continue
        row['url'] = line
        rows.append(row)
        if len(rows) >= 200:
            break
    if not rows:
        rows = cfg_rows_slow(common)
    return rows


OS_WORDS = {
    'android': 'Android',
    'ios': 'iPhone and iPad',
    'windows': 'Windows',
    'mac': 'macOS',
    'linux': 'Linux',
}


def app_rows(settings):
    '''Groups the chosen apps by the system they run on.'''
    picked = settings.get('apps') or {}
    extra = settings.get('extra_apps') or []
    groups = []
    for shape in watashi_settings.OS_BOOK:
        items = []
        for app in watashi_settings.APP_BOOK:
            if app['os'] != shape['id']:
                continue
            if not picked.get(app['id'], app['on']):
                continue
            items.append({'name': app['name'], 'note': app['note'], 'url': app['url']})
        for app in extra:
            try:
                if str(app.get('os') or '') != shape['id'] or not app.get('url'):
                    continue
                items.append({'name': str(app.get('name') or ''), 'note': str(app.get('note') or ''),
                              'url': str(app.get('url') or '')})
            except Exception:
                continue
        if not items:
            continue
        groups.append({'name': _(OS_WORDS.get(shape['id'], shape['id'])), 'pack': shape['pack'],
                       'icon': shape['icon'], 'items': items})
    return groups


def js_words():
    '''The sentences the small script needs.'''
    return {
        'copied': _('Copied'),
        'copiedMain': _('The smart link was copied'),
        'copiedColumn': _('Every link of this column was copied'),
        'copyFailed': _('Copying did not work, please copy by hand'),
        'nothingToCopy': _('There is nothing to copy'),
        'qrTitle': _('QR code'),
        'qrFailed': _('The QR code could not be drawn'),
    }


def page_data(common, lang):
    '''Turns the common data of the panel into everything the page draws.'''
    settings = watashi_settings.load()
    user = common.get('user')
    limit = float(common.get('usage_limit_b') or 0)
    used = float(common.get('usage_current_b') or 0)
    left = limit - used
    if left < 0:
        left = 0.0
    pct = 0.0
    if limit > 0:
        pct = round(min(100.0, max(0.0, used * 100.0 / limit)), 1)

    days = int(common.get('expire_days') or 0)
    whole = 0
    try:
        whole = int(getattr(user, 'package_days', 0) or 0)
    except Exception:
        whole = 0
    days_pct = 0
    if whole > 0:
        days_pct = int(min(100, max(0, days * 100 / whole)))
    elif days > 0:
        days_pct = 100

    live = bool(common.get('user_activate'))
    state = _('Active')
    tone = 'ok'
    if not live:
        if days <= 0:
            state = _('Expired')
        elif limit > 0 and used >= limit:
            state = _('Volume finished')
        else:
            state = _('Not active')
        tone = 'bad'
    elif pct >= 90 or (0 < days <= 3):
        tone = 'warn'

    name = str(getattr(user, 'name', '') or '').strip() or _('Guest')
    reset = 0
    try:
        reset = int(getattr(user, 'days_to_reset')() or 0)
    except Exception:
        reset = 0

    when = None
    try:
        when = getattr(user, 'last_online', None)
    except Exception:
        when = None
    last = '—'
    try:
        if when and when.year > 1900:
            last = when.strftime('%H:%M')
    except Exception:
        last = '—'

    ends = None
    try:
        ends = datetime.date.today() + datetime.timedelta(days=days)
    except Exception:
        ends = None

    lang_next = 'en' if lang == 'fa' else 'fa'
    here = ''
    try:
        here = request.path
    except Exception:
        here = ''

    words = {
        'hi': watashi_settings.word_from(settings, 'hello') or hello_words(),
        'sub_hi': watashi_settings.word_from(settings, 'sub_hello') or _('Welcome to your own dashboard'),
        'note_title': watashi_settings.word_from(settings, 'notice_title') or _('Notice'),
        'note_text': watashi_settings.word_from(settings, 'notice_text') or word_of('branding_freetext'),
        'note_site': watashi_settings.word_from(settings, 'notice_site') or word_of('branding_site'),
        'foot': watashi_settings.word_from(settings, 'footer') or _('Keep your links private, they belong to you only.'),
    }

    cfgs = cfg_rows(common) if watashi_settings.part_on(settings, 'configs') else []

    return {
        'up_lang': lang,
        'up_lang_url': here + '?lang=' + lang_next,
        'up_lang_next': lang_next.upper(),
        'up_brand': word_of('branding_title') or 'Watashi',
        'up_hi': words['hi'],
        'up_sub_hi': words['sub_hi'],
        'up_note_title': words['note_title'],
        'up_note_text': words['note_text'],
        'up_note_site': words['note_site'],
        'up_foot': words['foot'],
        'up_initial': name[:1].upper(),
        'up_name': name,
        'up_state': state,
        'up_tone': tone,
        'up_pct': pct,
        'up_limit_h': size_words(limit) if limit > 0 else _('Unlimited'),
        'up_used_h': size_words(used),
        'up_left_h': size_words(left) if limit > 0 else _('Unlimited'),
        'up_left_tone': 'red' if (limit > 0 and pct >= 90) else ('orange' if pct >= 75 else 'green'),
        'up_rel': common.get('expire_rel') or '—',
        'up_days_tone': 'red' if days <= 3 else ('orange' if days <= 10 else 'green'),
        'up_reset': reset if (reset and reset < 900) else 0,
        'up_expire_at': day_words(ends, lang),
        'up_days_pct': days_pct,
        'up_days_left': _('@N@ days').replace('@N@', str(max(0, days))),
        'up_last': last,
        'up_last_note': ago_words(when),
        'up_country': str(common.get('country') or '—').upper(),
        'up_net': str(common.get('asn') or '—'),
        'up_bases': server_rows(common, settings),
        'up_subs': sub_rows(settings),
        'up_cfgs': cfgs,
        'up_cfg_count': len(cfgs),
        'up_apps': app_rows(settings) if watashi_settings.part_on(settings, 'apps') else [],
        'up_show': {
            'notice': watashi_settings.part_on(settings, 'notice'),
            'stats': watashi_settings.part_on(settings, 'stats'),
            'configs': watashi_settings.part_on(settings, 'configs'),
            'apps': watashi_settings.part_on(settings, 'apps'),
            'reset': watashi_settings.part_on(settings, 'reset'),
        },
        'up_words': js_words(),
    }
