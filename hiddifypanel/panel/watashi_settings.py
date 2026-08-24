"""Settings for the Watashi user page, kept in one small json file.

The admin page writes this file, the user page reads it. Nothing here touches
the database, so a panel update never needs a migration for it.
"""

import json
import os
import threading

FILE_NAME = 'watashi_user_page.json'

_guard = threading.Lock()
_seen = {'stamp': -1.0, 'data': None}

# Every client app the page knows about. 'on' is the state before an admin
# touches anything. Hiddify apps are left out on purpose.
APP_BOOK = [
    {'id': 'v2rayng', 'os': 'android', 'name': 'v2rayNG', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/2dust/v2rayNG/releases/latest'},
    {'id': 'nekobox', 'os': 'android', 'name': 'NekoBox', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest'},
    {'id': 'flclash', 'os': 'android', 'name': 'FlClash', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/chen08209/FlClash/releases/latest'},
    {'id': 'sfa', 'os': 'android', 'name': 'sing-box', 'note': 'Google Play', 'on': False,
     'url': 'https://play.google.com/store/apps/details?id=io.nekohasekai.sfa'},
    {'id': 'karing_and', 'os': 'android', 'name': 'Karing', 'note': 'GitHub', 'on': False,
     'url': 'https://github.com/KaringX/karing/releases/latest'},

    {'id': 'streisand', 'os': 'ios', 'name': 'Streisand', 'note': 'App Store', 'on': True,
     'url': 'https://apps.apple.com/app/streisand/id6450534064'},
    {'id': 'shadowrocket', 'os': 'ios', 'name': 'Shadowrocket', 'note': 'App Store', 'on': True,
     'url': 'https://apps.apple.com/app/shadowrocket/id932747118'},
    {'id': 'v2box', 'os': 'ios', 'name': 'V2Box', 'note': 'App Store', 'on': True,
     'url': 'https://apps.apple.com/app/v2box-v2ray-client/id6446814690'},
    {'id': 'foxray', 'os': 'ios', 'name': 'FoXray', 'note': 'App Store', 'on': False,
     'url': 'https://apps.apple.com/app/foxray/id6448898396'},
    {'id': 'sfi', 'os': 'ios', 'name': 'sing-box', 'note': 'App Store', 'on': False,
     'url': 'https://apps.apple.com/app/sing-box/id6451272673'},

    {'id': 'v2rayn', 'os': 'windows', 'name': 'v2rayN', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/2dust/v2rayN/releases/latest'},
    {'id': 'verge_win', 'os': 'windows', 'name': 'Clash Verge Rev', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/clash-verge-rev/clash-verge-rev/releases/latest'},
    {'id': 'nekoray_win', 'os': 'windows', 'name': 'NekoRay', 'note': 'GitHub', 'on': False,
     'url': 'https://github.com/MatsuriDayo/nekoray/releases/latest'},

    {'id': 'v2box_mac', 'os': 'mac', 'name': 'V2Box', 'note': 'App Store', 'on': True,
     'url': 'https://apps.apple.com/app/v2box-v2ray-client/id6446814690'},
    {'id': 'verge_mac', 'os': 'mac', 'name': 'Clash Verge Rev', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/clash-verge-rev/clash-verge-rev/releases/latest'},
    {'id': 'sfm', 'os': 'mac', 'name': 'sing-box', 'note': 'App Store', 'on': False,
     'url': 'https://apps.apple.com/app/sing-box/id6451272673'},

    {'id': 'verge_linux', 'os': 'linux', 'name': 'Clash Verge Rev', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/clash-verge-rev/clash-verge-rev/releases/latest'},
    {'id': 'nekoray_linux', 'os': 'linux', 'name': 'NekoRay', 'note': 'GitHub', 'on': True,
     'url': 'https://github.com/MatsuriDayo/nekoray/releases/latest'},
    {'id': 'flclash_linux', 'os': 'linux', 'name': 'FlClash', 'note': 'GitHub', 'on': False,
     'url': 'https://github.com/chen08209/FlClash/releases/latest'},
]

OS_BOOK = [
    {'id': 'android', 'pack': 'brands', 'icon': 'android'},
    {'id': 'ios', 'pack': 'brands', 'icon': 'apple'},
    {'id': 'windows', 'pack': 'brands', 'icon': 'windows'},
    {'id': 'mac', 'pack': 'brands', 'icon': 'apple'},
    {'id': 'linux', 'pack': 'brands', 'icon': 'linux'},
]

# Rows of the smart link list. 'path' is added to the account link.
LINK_BOOK = [
    {'id': 'sub', 'path': 'sub/', 'tag': 'AUTO', 'tone': 'purple', 'deep': 'app', 'on': True},
    {'id': 'sub64', 'path': 'sub64/', 'tag': 'B64', 'tone': 'blue', 'deep': '', 'on': True},
    {'id': 'xray', 'path': 'xray/', 'tag': 'XRAY', 'tone': 'green', 'deep': '', 'on': True},
    {'id': 'singbox', 'path': 'full-singbox.json', 'tag': 'SBOX', 'tone': 'orange', 'deep': '', 'on': True},
    {'id': 'meta', 'path': 'clash/meta/all.yml', 'tag': 'META', 'tone': 'purple', 'deep': 'clash', 'on': True},
    {'id': 'clash', 'path': 'clash/all.yml', 'tag': 'CLASH', 'tone': 'blue', 'deep': '', 'on': True},
    {'id': 'text', 'path': 'all.txt', 'tag': 'TEXT', 'tone': 'green', 'deep': '', 'on': True},
    {'id': 'ssh', 'path': 'singbox.json', 'tag': 'SSH', 'tone': 'orange', 'deep': '', 'on': True},
    {'id': 'wg', 'path': 'wireguard/', 'tag': 'WG', 'tone': 'red', 'deep': '', 'on': True},
    {'id': 'panel', 'path': '', 'tag': 'PAGE', 'tone': 'purple', 'deep': '', 'on': True},
]


def fresh():
    '''The settings of a panel where nobody changed anything yet.'''
    return {
        'show': {'notice': True, 'stats': True, 'configs': True, 'apps': True, 'reset': True},
        'texts': {'hello': '', 'sub_hello': '', 'notice_title': '', 'notice_text': '',
                  'notice_site': '', 'footer': ''},
        'links': dict([(row['id'], row['on']) for row in LINK_BOOK]),
        'domains': [],
        'apps': dict([(app['id'], app['on']) for app in APP_BOOK]),
        'extra_apps': [],
        'skin': 'dark',
        'lang': '',
    }


def store_path():
    '''Where the json file lives.'''
    base = os.environ.get('HIDDIFY_CONFIG_PATH') or ''
    if not base:
        try:
            from flask import current_app
            base = current_app.config.get('HIDDIFY_CONFIG_PATH') or ''
        except Exception:
            base = ''
    if not base:
        base = '/opt/hiddify-manager/'
    if not base.endswith('/'):
        base += '/'
    return base + 'hiddify-panel/' + FILE_NAME


def blend(base, extra):
    '''Lays saved values over the built in ones without losing keys.'''
    if not isinstance(extra, dict):
        return base
    for key, value in extra.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            blend(base[key], value)
        else:
            base[key] = value
    return base


def load():
    '''Reads the settings, remembering the file until it changes on disk.'''
    spot = store_path()
    try:
        stamp = os.path.getmtime(spot)
    except Exception:
        stamp = -1.0
    with _guard:
        if _seen['data'] is not None and _seen['stamp'] == stamp:
            return json.loads(json.dumps(_seen['data']))
        data = fresh()
        if stamp > 0:
            try:
                with open(spot, 'r', encoding='utf-8') as handle:
                    blend(data, json.load(handle))
            except Exception as trouble:
                print('watashi user page: the settings file could not be read', trouble)
        _seen['stamp'] = stamp
        _seen['data'] = json.loads(json.dumps(data))
        return data


def save(data):
    '''Writes the settings and forgets the remembered copy.'''
    spot = store_path()
    folder = os.path.dirname(spot)
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as trouble:
        print('watashi user page: the settings folder could not be made', trouble)
    body = blend(fresh(), data)
    side = spot + '.tmp'
    with open(side, 'w', encoding='utf-8') as handle:
        json.dump(body, handle, ensure_ascii=False, indent=2)
    os.replace(side, spot)
    with _guard:
        _seen['stamp'] = -1.0
        _seen['data'] = None
    return body


def link_on(settings, name):
    '''Says whether one smart link row should be drawn.'''
    try:
        return bool(settings.get('links', {}).get(name, True))
    except Exception:
        return True


def part_on(settings, name):
    '''Says whether one part of the page should be drawn.'''
    try:
        return bool(settings.get('show', {}).get(name, True))
    except Exception:
        return True


def word_from(settings, name):
    '''Reads one admin written sentence.'''
    try:
        return str(settings.get('texts', {}).get(name, '') or '').strip()
    except Exception:
        return ''
