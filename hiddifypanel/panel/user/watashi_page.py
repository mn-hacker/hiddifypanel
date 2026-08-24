"""Everything the Watashi user page needs, gathered in plain helpers.

The view hands the common data over, this module turns it into words, rows and
numbers the template can draw without thinking.
"""

import datetime
import urllib.parse

from flask import request
from flask_babel import gettext as _

from hiddifypanel.models import ConfigEnum, hconfig
from hiddifypanel.panel import watashi_settings

J_MONTH_DAYS = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
G_MONTH_SUM = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
WAVE_BARS = 14

OS_WORDS = {
    'android': 'Android',
    'ios': 'iPhone and iPad',
    'windows': 'Windows',
    'mac': 'macOS',
    'linux': 'Linux',
}

LINK_WORDS = {
    'meta': ('Clash / Meta', 'YAML config'),
    'singbox': ('Sing-Box', 'JSON config'),
    'xray': ('V2Ray / Xray', 'Base64 subscription'),
    'wg': ('WireGuard', 'WireGuard config'),
}


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


def rel_words(days):
    '''Says how far the end of the package is, in our own words and digits.'''
    try:
        days = int(days or 0)
    except Exception:
        days = 0
    if days <= 0:
        return 0, _('Already over')
    if days < 45:
        return days, _('days')
    if days < 365:
        return int(round(days / 30.0)), _('months')
    return int(round(days / 365.0)), _('years')


def brand_parts(settings):
    '''Splits the brand title, so its last word may wear the accent colour.'''
    title = watashi_settings.word_from(settings, 'brand') or word_of('branding_title') or 'Watashi Manager'
    bits = title.split()
    if len(bits) < 2:
        return title, '', title
    return ' '.join(bits[:-1]), bits[-1], title


def home_base(common):
    '''The address every link of this user starts with.'''
    home = str(common.get('profile_url') or '')
    if home and not home.endswith('/'):
        home += '/'
    return home


def short_url(link, room=44):
    '''Shows a long address without breaking the layout.'''
    text = str(link or '')
    if len(text) <= room:
        return text
    return text[:room - 12] + '…' + text[-10:]


def link_rows(common, settings):
    '''The four link cards under the auto connect card.'''
    home = home_base(common)
    rows = []
    for row in watashi_settings.LINK_BOOK:
        name = row['id']
        if not watashi_settings.link_on(settings, name):
            continue
        if name == 'wg' and not flag('wireguard_enable'):
            continue
        title, note = LINK_WORDS.get(name, (name, ''))
        rows.append({
            'name': title,
            'note': _(note),
            'url': urllib.parse.urljoin(home, row['path']) if home else '',
            'tag': row['tag'],
            'icon': row['icon'],
        })
    return rows


def guide_rows(settings):
    '''One setup card for every kind of device that has an app.'''
    packs = []
    for shape in watashi_settings.OS_BOOK:
        apps = watashi_settings.apps_of(settings, shape['id'])
        if not apps:
            continue
        first = apps[0]
        os_name = _(OS_WORDS.get(shape['id'], shape['id']))
        steps = [
            _('Install @APP@ with the button below.').replace('@APP@', '<code>' + first['name'] + '</code>'),
            _('Press the copy button of the Auto Connect card, then add that link inside the app as a new subscription.'),
            _('Refresh the list, pick a server and press connect.'),
        ]
        packs.append({
            'id': shape['id'],
            'icon': shape['icon'],
            'os_name': os_name,
            'app_name': first['name'],
            'app_url': first['url'],
            'app_note': _('The client we suggest for @OS@').replace('@OS@', os_name),
            'get_word': _('Download @APP@').replace('@APP@', first['name']),
            'steps': steps,
            'more': apps[1:],
        })
    return packs


def wave_rows(days_used, days_total):
    '''Draws the days already spent as a small living strip.'''
    bars = []
    if days_total <= 0:
        days_total = max(1, days_used)
    share = max(0.0, min(1.0, float(days_used) / float(days_total)))
    burnt = int(round(share * WAVE_BARS))
    for step in range(WAVE_BARS):
        if step < burnt - 1:
            bars.append({'cls': '', 'h': 100, 'wait': step * 60})
        elif step == max(0, burnt - 1):
            bars.append({'cls': 'now', 'h': 100, 'wait': step * 60})
        else:
            bars.append({'cls': 'soft', 'h': 34, 'wait': step * 60})
    return bars


def js_words():
    '''The sentences the small script needs.'''
    return {
        'copied': _('Copied'),
        'copiedMain': _('The Auto Connect link was copied'),
        'copyFailed': _('Copying did not work, please copy by hand'),
        'qrFailed': _('The QR code could not be drawn'),
        'picCopied': _('The QR image was copied'),
        'picFailed': _('Copying the image did not work, please save it by hand'),
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
    try:
        whole = int(getattr(user, 'package_days', 0) or 0)
    except Exception:
        whole = 0
    days_pct = 0
    if whole > 0:
        days_pct = int(min(100, max(0, days * 100 / whole)))
    elif days > 0:
        days_pct = 100
    spent = max(0, whole - max(0, days)) if whole > 0 else 0

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
    try:
        reset = int(getattr(user, 'days_to_reset')() or 0)
    except Exception:
        reset = 0
    try:
        caps = int(getattr(user, 'max_ips', 0) or 0)
    except Exception:
        caps = 0

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

    try:
        ends = datetime.date.today() + datetime.timedelta(days=days)
    except Exception:
        ends = None

    lang_next = 'en' if lang == 'fa' else 'fa'
    try:
        here = request.path
    except Exception:
        here = ''

    rel_n, rel_u = rel_words(days)
    rel_full = (str(rel_n) + ' ' + rel_u) if rel_n else rel_u
    if rel_n:
        rel_left = _('@N@ @U@ left').replace('@N@', str(rel_n)).replace('@U@', rel_u)
    else:
        rel_left = rel_u

    first_word, last_word, whole_brand = brand_parts(settings)
    home = home_base(common)
    auto = urllib.parse.urljoin(home, 'sub/') if home else ''
    daily = used / float(spent) if spent > 0 else used

    return {
        'up_lang': lang,
        'up_dir': 'rtl' if lang == 'fa' else 'ltr',
        'up_skin': 'light' if str(settings.get('skin') or 'dark') == 'light' else 'dark',
        'up_lang_url': here + '?lang=' + lang_next,
        'up_lang_next': lang_next.upper(),
        'up_brand': whole_brand,
        'up_brand_a': first_word,
        'up_brand_b': last_word,
        'up_hi': watashi_settings.word_from(settings, 'hello') or hello_words(),
        'up_sub_hi': watashi_settings.word_from(settings, 'sub_hello') or _('Welcome to your own dashboard'),
        'up_note_title': watashi_settings.word_from(settings, 'notice_title') or _('Notice'),
        'up_note_text': watashi_settings.word_from(settings, 'notice_text') or word_of('branding_freetext'),
        'up_note_site': word_of('branding_site'),
        'up_foot': watashi_settings.word_from(settings, 'footer'),
        'up_initial': name[:1].upper(),
        'up_name': name,
        'up_state': state,
        'up_tone': tone,
        'up_pct': pct,
        'up_limit_h': size_words(limit) if limit > 0 else _('Unlimited'),
        'up_used_h': size_words(used),
        'up_left_h': size_words(left) if limit > 0 else _('Unlimited'),
        'up_left_tone': 'red' if (limit > 0 and pct >= 90) else ('orange' if pct >= 75 else 'green'),
        'up_rel': rel_full,
        'up_rel_n': rel_n,
        'up_rel_u': rel_u,
        'up_days_tone': 'red' if days <= 3 else ('orange' if days <= 10 else 'green'),
        'up_reset': reset if (reset and reset < 900) else 0,
        'up_reset_h': _('@N@ days').replace('@N@', str(reset)),
        'up_expire_at': day_words(ends, lang),
        'up_days_pct': days_pct,
        'up_days_left': rel_left,
        'up_days_used': spent,
        'up_days_total': whole if whole > 0 else max(0, days),
        'up_daily_h': size_words(daily),
        'up_ip_cap': caps if caps > 0 else 0,
        'up_last': last,
        'up_last_note': ago_words(when),
        'up_country': str(common.get('country') or '—').upper(),
        'up_net': str(common.get('asn') or '—'),
        'up_wave': wave_rows(spent, whole if whole > 0 else max(1, days)),
        'up_auto': auto,
        'up_auto_short': short_url(auto),
        'up_links': link_rows(common, settings),
        'up_guide': guide_rows(settings) if watashi_settings.part_on(settings, 'guide') else [],
        'up_bot_url': watashi_settings.word_from(settings, 'bot_url'),
        'up_support_url': watashi_settings.word_from(settings, 'support_url') or word_of('branding_site'),
        'up_show': {
            'notice': watashi_settings.part_on(settings, 'notice'),
            'stats': watashi_settings.part_on(settings, 'stats'),
            'links': watashi_settings.part_on(settings, 'links'),
            'guide': watashi_settings.part_on(settings, 'guide'),
            'rhythm': watashi_settings.part_on(settings, 'rhythm'),
        },
        'up_words': js_words(),
    }
