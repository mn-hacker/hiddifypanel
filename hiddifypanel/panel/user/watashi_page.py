"""Data for the Watashi user page (the page a customer sees on their own link)."""

import datetime
import urllib.parse

from flask import g, request
from flask_babel import gettext as _

from hiddifypanel import hutils
from hiddifypanel.models import ConfigEnum, hconfig

J_MONTH_DAYS = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
G_MONTH_SUM = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def flag(name):
    '''Reads a panel switch without ever breaking the page.'''
    try:
        return bool(hconfig(getattr(ConfigEnum, name)))
    except Exception:
        return False


def word_of(name):
    '''Reads a panel text without ever breaking the page.'''
    try:
        return hconfig(getattr(ConfigEnum, name)) or ''
    except Exception:
        return ''


def size_words(num):
    '''Turns a byte count into a short human size.'''
    try:
        num = float(num or 0)
    except Exception:
        num = 0.0
    if num < 0:
        num = 0.0
    steps = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    step = 0
    while num >= 1024 and step < len(steps) - 1:
        num /= 1024.0
        step += 1
    if step == 0:
        return '%d %s' % (int(num), steps[step])
    return '%.2f %s' % (num, steps[step])


def to_jalali(day):
    '''Turns a gregorian date into the persian calendar.'''
    gy, gm, gd = day.year, day.month, day.day
    gy2 = gy - 1600
    total = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    total += G_MONTH_SUM[gm - 1] + gd - 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    if gm > 2 and leap:
        total += 1
    total -= 79
    cycles = total // 12053
    total = total % 12053
    jy = 979 + 33 * cycles + 4 * (total // 1461)
    total %= 1461
    if total >= 366:
        jy += (total - 1) // 365
        total = (total - 1) % 365
    jm = 12
    jd = total + 1
    for index in range(12):
        if total < J_MONTH_DAYS[index]:
            jm = index + 1
            jd = total + 1
            break
        total -= J_MONTH_DAYS[index]
    return jy, jm, jd


def day_words(day, lang):
    '''Writes a date the way the reader expects to read it.'''
    if not day:
        return '-'
    if lang == 'fa':
        jy, jm, jd = to_jalali(day)
        return '%04d/%02d/%02d' % (jy, jm, jd)
    return day.strftime('%Y-%m-%d')


def ago_words(when):
    '''Says how long ago something happened.'''
    if not when or when.year < 1990:
        return '', _('No connection has been seen yet')
    gap = datetime.datetime.now() - when
    hours = int(gap.total_seconds() // 3600)
    days = gap.days
    if hours < 1:
        return when.strftime('%H:%M'), _('A few minutes ago')
    if hours < 24:
        return when.strftime('%H:%M'), _('@N@ hours ago').replace('@N@', str(hours))
    if days < 31:
        return when.strftime('%Y-%m-%d'), _('@N@ days ago').replace('@N@', str(days))
    return when.strftime('%Y-%m-%d'), _('A long time ago')


def hello_words():
    '''Greets the reader by the clock.'''
    hour = datetime.datetime.now().hour
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
    '''Picks a colour for a protocol badge.'''
    name = str(proto or '').lower()
    if 'vless' in name:
        return 'purple'
    if 'vmess' in name:
        return 'blue'
    if 'trojan' in name:
        return 'green'
    if 'hysteria' in name or 'tuic' in name:
        return 'red'
    if 'ss' in name or 'shadow' in name:
        return 'orange'
    return 'blue'


def short_of(value):
    '''Keeps only the readable tail of an enum-ish value.'''
    text = str(value or '')
    if '.' in text:
        text = text.split('.')[-1]
    return text


def sub_rows(base, panel_link):
    '''Builds the smart link rows.'''
    rows = [
        {'tag': 'AUTO', 'tone': 'purple', 'name': _('Smart link'),
         'note': _('Best choice for the Watashi and Hiddify apps'),
         'url': base + 'sub/', 'deep': 'hiddify://import/' + panel_link},
        {'tag': 'B64', 'tone': 'blue', 'name': _('Subscription link (Base64)'),
         'note': _('For V2rayNG, Streisand, V2Box and similar apps'),
         'url': base + 'sub64/', 'deep': ''},
        {'tag': 'XRAY', 'tone': 'green', 'name': _('Full Xray config'),
         'note': _('A ready JSON config for Xray based apps'),
         'url': base + 'xray/', 'deep': ''},
        {'tag': 'SBOX', 'tone': 'orange', 'name': _('Full Sing-box config'),
         'note': _('A ready JSON config for Sing-box based apps'),
         'url': base + 'full-singbox.json', 'deep': ''},
        {'tag': 'META', 'tone': 'purple', 'name': _('Clash Meta'),
         'note': _('For Clash Meta, Clash Verge and Stash'),
         'url': base + 'clash/meta/all.yml',
         'deep': 'clash://install-config?url=' + urllib.parse.quote(base + 'clash/meta/all.yml', safe='')},
        {'tag': 'CLASH', 'tone': 'blue', 'name': _('Clash'),
         'note': _('For the classic Clash apps'),
         'url': base + 'clash/all.yml', 'deep': ''},
        {'tag': 'TEXT', 'tone': 'green', 'name': _('Plain config links'),
         'note': _('Every config as plain text, one per line'),
         'url': base + 'all.txt', 'deep': ''},
    ]
    if flag('ssh_server_enable'):
        rows.append({'tag': 'SSH', 'tone': 'orange', 'name': _('Sing-box over SSH'),
                     'note': _('Only for the SSH tunnel'),
                     'url': base + 'singbox.json', 'deep': ''})
    if flag('wireguard_enable'):
        rows.append({'tag': 'WG', 'tone': 'red', 'name': _('WireGuard'),
                     'note': _('A ready config for WireGuard apps'),
                     'url': base + 'wireguard/', 'deep': ''})
    rows.append({'tag': 'PAGE', 'tone': 'purple', 'name': _('My panel address'),
                 'note': _('This very page, keep it for yourself'),
                 'url': panel_link, 'deep': ''})
    return rows


def cfg_rows(domains):
    '''Builds one row per ready config.'''
    rows = []
    try:
        proxies = hutils.proxy.get_valid_proxies(domains)
    except Exception:
        return rows
    for pinfo in proxies:
        try:
            link = hutils.proxy.xray.to_link(pinfo)
        except Exception:
            continue
        if not isinstance(link, str) or not link.strip():
            continue
        proto = short_of(pinfo.get('proto'))
        rows.append({
            'name': str(pinfo.get('name', '')).replace('_', ' '),
            'server': str(pinfo.get('server', '')),
            'proto': proto.upper(),
            'transport': short_of(pinfo.get('transport')),
            'l3': short_of(pinfo.get('l3')),
            'tone': tone_of_proto(proto),
            'url': link.strip(),
        })
        if len(rows) >= 120:
            break
    return rows


def app_rows():
    '''Buttons that take the reader to a client app.'''
    store = 'https://github.com/hiddify/hiddify-app/releases/latest'
    return [
        {'name': _('Android'), 'note': _('Google Play'), 'pack': 'brands', 'icon': 'google-play',
         'url': 'https://play.google.com/store/apps/details?id=app.hiddify.com'},
        {'name': _('iPhone and iPad'), 'note': _('App Store'), 'pack': 'brands', 'icon': 'app-store-ios',
         'url': 'https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532'},
        {'name': _('Windows'), 'note': _('Desktop app'), 'pack': 'brands', 'icon': 'windows', 'url': store},
        {'name': _('macOS'), 'note': _('Desktop app'), 'pack': 'brands', 'icon': 'apple', 'url': store},
        {'name': _('Linux'), 'note': _('Desktop app'), 'pack': 'brands', 'icon': 'linux', 'url': store},
    ]


def js_words():
    '''Short sentences the page needs inside the browser.'''
    return {
        'copied': _('Copied'),
        'copiedMain': _('The smart link was copied'),
        'copiedAll': _('Every config link was copied'),
        'copyFailed': _('Copying did not work, please copy by hand'),
        'nothingToCopy': _('There is nothing to copy'),
        'qrTitle': _('QR code'),
        'qrFailed': _('The QR code could not be drawn'),
    }


def page_data(common, lang):
    '''Everything the Watashi user page needs, already worded.'''
    user = common['user']
    limit_b = int(common.get('usage_limit_b') or 0)
    used_b = int(common.get('usage_current_b') or 0)
    left_b = max(0, limit_b - used_b)
    pct = round(used_b * 100.0 / limit_b, 1) if limit_b > 0 else 0.0
    if pct > 100:
        pct = 100.0

    days = int(common.get('expire_days') or 0)
    whole_days = int(getattr(user, 'package_days', 0) or 0)
    days_pct = 0
    if whole_days > 0:
        days_pct = max(0, min(100, int(round(days * 100.0 / whole_days))))

    alive = bool(common.get('user_activate'))
    if not getattr(user, 'enable', True):
        state, tone = _('Disabled'), 'bad'
    elif days < 0:
        state, tone = _('Expired'), 'bad'
    elif limit_b and used_b >= limit_b:
        state, tone = _('Volume finished'), 'bad'
    elif alive:
        state, tone = _('Active'), 'ok'
    else:
        state, tone = _('Not active'), 'warn'

    left_tone = 'green'
    if pct >= 90:
        left_tone = 'red'
    elif pct >= 75:
        left_tone = 'orange'

    days_tone = 'green'
    if days < 0:
        days_tone = 'red'
    elif days <= 3:
        days_tone = 'orange'

    panel_link = common.get('profile_url') or ''
    base = panel_link if panel_link.endswith('/') else panel_link + '/'

    last_head, last_note = ago_words(getattr(user, 'last_online', None))
    if not last_head:
        last_head = _('Never')

    reset_days = int(common.get('reset_day') or 0)
    reset_text = ''
    if 0 < reset_days < 1000:
        reset_text = _('@N@ days').replace('@N@', str(reset_days))

    end_day = datetime.date.today() + datetime.timedelta(days=max(days, 0))
    other = 'en' if lang == 'fa' else 'fa'
    name = getattr(user, 'name', '') or _('Guest')
    configs = cfg_rows(common.get('domains') or [])

    return {
        'up_lang': lang,
        'up_lang_next': other.upper(),
        'up_lang_url': request.path + '?lang=' + other,
        'up_brand': word_of('branding_title') or 'Watashi',
        'up_hi': hello_words(),
        'up_sub_hi': _('Welcome to your own dashboard'),
        'up_name': name,
        'up_initial': name.strip()[:1].upper() or 'W',
        'up_state': state,
        'up_tone': tone,
        'up_pct': pct,
        'up_limit_h': size_words(limit_b) if limit_b else _('Unlimited'),
        'up_used_h': size_words(used_b),
        'up_left_h': size_words(left_b) if limit_b else _('Unlimited'),
        'up_left_tone': left_tone,
        'up_rel': common.get('expire_rel') or '-',
        'up_days_tone': days_tone,
        'up_days_pct': days_pct,
        'up_days_left': _('@N@ days left').replace('@N@', str(max(days, 0))),
        'up_expire_at': day_words(end_day, lang),
        'up_last': last_head,
        'up_last_note': last_note,
        'up_country': (common.get('country') or '-').upper(),
        'up_net': str(common.get('asn') or '-'),
        'up_reset': reset_text,
        'up_subs': sub_rows(base, panel_link),
        'up_cfgs': configs,
        'up_cfg_count': len(configs),
        'up_apps': app_rows(),
        'up_note_title': word_of('branding_title') or _('Notice'),
        'up_note_text': word_of('branding_freetext'),
        'up_note_site': word_of('branding_site'),
        'up_words': js_words(),
        'up_main_link': base + 'sub/',
    }
