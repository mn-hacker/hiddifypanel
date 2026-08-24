"""The little settings store behind the Watashi user page.

Everything an owner may want to change on the page a customer opens lives in one
small json file, so no database change is ever needed for it.
"""

import json
import os
import threading

FILE_NAME = 'watashi_user_page.json'

# The four link cards of the page, beside the auto connect card on top of them.
LINK_BOOK = [
    {'id': 'meta', 'path': 'clash/meta/all.yml', 'tag': 'clash', 'icon': 'fa-solid fa-shield-halved', 'on': True},
    {'id': 'singbox', 'path': 'singbox.json', 'tag': 'singbox', 'icon': 'fa-solid fa-box', 'on': True},
    {'id': 'xray', 'path': 'all.txt', 'tag': 'v2ray', 'icon': 'fa-solid fa-bolt', 'on': True},
    {'id': 'wg', 'path': 'wg.conf', 'tag': 'wireguard', 'icon': 'fa-solid fa-lock', 'on': True},
]

OS_BOOK = [
    {'id': 'android', 'icon': 'fa-brands fa-android'},
    {'id': 'ios', 'icon': 'fa-brands fa-apple'},
    {'id': 'windows', 'icon': 'fa-brands fa-windows'},
    {'id': 'mac', 'icon': 'fa-brands fa-apple'},
    {'id': 'linux', 'icon': 'fa-brands fa-linux'},
]

# Not one hiddify app is offered here on purpose.
APP_BOOK = [
    {'id': 'v2rayng', 'os': 'android', 'name': 'v2rayNG', 'on': True,
     'url': 'https://github.com/2dust/v2rayNG/releases/latest'},
    {'id': 'nekobox', 'os': 'android', 'name': 'NekoBox', 'on': False,
     'url': 'https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest'},
    {'id': 'flclash', 'os': 'android', 'name': 'FlClash', 'on': False,
     'url': 'https://github.com/chen08209/FlClash/releases/latest'},
    {'id': 'karing_and', 'os': 'android', 'name': 'Karing', 'on': False,
     'url': 'https://github.com/KaringX/karing/releases/latest'},
    {'id': 'streisand', 'os': 'ios', 'name': 'Streisand', 'on': True,
     'url': 'https://apps.apple.com/app/streisand/id6450534064'},
    {'id': 'shadowrocket', 'os': 'ios', 'name': 'Shadowrocket', 'on': False,
     'url': 'https://apps.apple.com/app/shadowrocket/id932747118'},
    {'id': 'v2box_ios', 'os': 'ios', 'name': 'V2Box', 'on': False,
     'url': 'https://apps.apple.com/app/v2box-v2ray-client/id6446814690'},
    {'id': 'sfi', 'os': 'ios', 'name': 'sing-box', 'on': False,
     'url': 'https://apps.apple.com/app/sing-box/id6451272673'},
    {'id': 'v2rayn', 'os': 'windows', 'name': 'v2rayN', 'on': True,
     'url': 'https://github.com/2dust/v2rayN/releases/latest'},
    {'id': 'verge_win', 'os': 'windows', 'name': 'Clash Verge Rev', 'on': False,
     'url': 'https://github.com/clash-verge-rev/clash-verge-rev/releases/latest'},
    {'id': 'nekoray_win', 'os': 'windows', 'name': 'NekoRay', 'on': False,
     'url': 'https://github.com/MatsuriDayo/nekoray/releases/latest'},
    {'id': 'v2box_mac', 'os': 'mac', 'name': 'V2Box', 'on': True,
     'url': 'https://apps.apple.com/app/v2box-v2ray-client/id6446814690'},
    {'id': 'verge_mac', 'os': 'mac', 'name': 'Clash Verge Rev', 'on': False,
     'url': 'https://github.com/clash-verge-rev/clash-verge-rev/releases/latest'},
    {'id': 'sfm', 'os': 'mac', 'name': 'sing-box', 'on': False,
     'url': 'https://apps.apple.com/app/sing-box/id6451272673'},
    {'id': 'nekoray_linux', 'os': 'linux', 'name': 'NekoRay', 'on': True,
     'url': 'https://github.com/MatsuriDayo/nekoray/releases/latest'},
    {'id': 'verge_linux', 'os': 'linux', 'name': 'Clash Verge Rev', 'on': False,
     'url': 'https://github.com/clash-verge-rev/clash-verge-rev/releases/latest'},
    {'id': 'flclash_linux', 'os': 'linux', 'name': 'FlClash', 'on': False,
     'url': 'https://github.com/chen08209/FlClash/releases/latest'},
]

_guard = threading.Lock()
_cache = {'when': None, 'body': None}


def fresh():
    '''The page as it looks before any owner has touched it.'''
    return {
        'show': {'notice': True, 'stats': True, 'links': True, 'guide': True, 'rhythm': True},
        'links': {row['id']: row['on'] for row in LINK_BOOK},
        'apps': {app['id']: app['on'] for app in APP_BOOK},
        'extra_apps': [],
        'texts': {'hello': '', 'sub_hello': '', 'notice_title': '', 'notice_text': '',
                  'brand': '', 'bot_url': '', 'support_url': ''},
        'skin': 'dark',
        'lang': '',
    }


def store_path():
    '''Where the settings file of this panel lives.'''
    base = ''
    try:
        from flask import current_app
        base = str(current_app.config.get('HIDDIFY_CONFIG_PATH') or '')
    except Exception:
        base = ''
    if not base:
        base = os.environ.get('HIDDIFY_CONFIG_PATH') or '/opt/hiddify-manager/'
    if not base.endswith('/'):
        base += '/'
    return base + 'hiddify-panel/' + FILE_NAME


def blend(saved):
    '''Lays what was saved over the defaults, key by key.'''
    out = fresh()
    if not isinstance(saved, dict):
        return out
    for key in ['show', 'links', 'apps', 'texts']:
        part = saved.get(key)
        if isinstance(part, dict):
            for name, value in part.items():
                if name in out[key] or key in ['links', 'apps']:
                    out[key][name] = value
    if isinstance(saved.get('extra_apps'), list):
        out['extra_apps'] = saved['extra_apps']
    for key in ['skin', 'lang']:
        if isinstance(saved.get(key), str):
            out[key] = saved[key]
    return out


def load():
    '''Reads the settings, remembering them until the file changes.'''
    spot = store_path()
    try:
        when = os.path.getmtime(spot)
    except Exception:
        return fresh()
    with _guard:
        if _cache['when'] == when and _cache['body'] is not None:
            return _cache['body']
    body = fresh()
    try:
        with open(spot, encoding='utf-8') as door:
            body = blend(json.load(door))
    except Exception as trouble:
        print('watashi user page: the settings file could not be read', trouble)
        return fresh()
    with _guard:
        _cache['when'] = when
        _cache['body'] = body
    return body


def save(body):
    '''Writes the settings in one go, so a reader never sees half a file.'''
    spot = store_path()
    os.makedirs(os.path.dirname(spot), exist_ok=True)
    step = spot + '.tmp'
    with open(step, 'w', encoding='utf-8') as door:
        json.dump(blend(body), door, ensure_ascii=False, indent=2)
    os.replace(step, spot)
    with _guard:
        _cache['when'] = None
        _cache['body'] = None
    return True


def link_on(settings, name):
    '''Tells whether one link card was left on.'''
    try:
        return bool((settings.get('links') or {}).get(name, True))
    except Exception:
        return True


def part_on(settings, name):
    '''Tells whether one part of the page was left on.'''
    try:
        return bool((settings.get('show') or {}).get(name, True))
    except Exception:
        return True


def word_from(settings, name):
    '''Reads one sentence the owner wrote, if there is one.'''
    try:
        return str((settings.get('texts') or {}).get(name) or '').strip()
    except Exception:
        return ''


def apps_of(settings, os_name):
    '''The apps the owner keeps for one kind of device.'''
    picked = settings.get('apps') or {}
    out = []
    for app in APP_BOOK:
        if app['os'] != os_name or not picked.get(app['id'], app['on']):
            continue
        out.append({'name': app['name'], 'url': app['url']})
    for app in (settings.get('extra_apps') or []):
        try:
            if str(app.get('os') or '') == os_name and app.get('url'):
                out.append({'name': str(app.get('name') or ''), 'url': str(app.get('url'))})
        except Exception:
            continue
    return out
