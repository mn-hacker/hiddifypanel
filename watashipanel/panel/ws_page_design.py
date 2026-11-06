"""watashi v12.3.44dev: the design of the user page, one for every admin.

Every admin can dress the page their own customers open: the name and the
logo on top, the support and bot links, the words of the greeting and of the
notice, the colours, light or dark, the language and which parts are shown.

What an admin leaves empty is taken from the admin above them, up to the
owner, so a reseller who only uploads a logo keeps everything else the owner
picked. The owner's name, support link and support text are the very same
values as the three branding settings of the Settings page, so the two pages
can never disagree. Below the owner sits the old hand written settings file
of the user page, and below that the page as it always looked.
"""
import base64
import binascii
import html
import json
import re

# every value an admin can write, with its longest length
TEXTS = {'brand': 60, 'note_title': 60, 'hello': 60, 'sub_hello': 140, 'foot': 200}
LINKS = {'support': 300, 'bot': 300}
NOTE_ROOM = 1500
PICKS = {'skin': ('dark', 'light'), 'lang': ('fa', 'en'), 'app_title': ('domain', 'brand')}
SECTIONS = ('notice', 'stats', 'links', 'guide', 'rhythm', 'short', 'powered')
# a logo is shrunk in the browser before it is sent; this is the ceiling
LOGO_ROOM = 90000
LOGO_HEAD = re.compile(r'^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$')
LOGO_MAGIC = {'png': (b'\x89PNG\r\n\x1a\n',), 'jpeg': (b'\xff\xd8\xff',), 'webp': (b'RIFF',)}
# the owner's three values live in the settings of the panel
OWNER_CONFIGS = {'brand': 'branding_title', 'support': 'branding_site', 'note': 'branding_freetext'}
# where each value sat in the old settings file of the user page
LEGACY_TEXTS = {'brand': 'brand', 'support': 'support_url', 'bot': 'bot_url', 'note': 'notice_text',
                'note_title': 'notice_title', 'hello': 'hello', 'sub_hello': 'sub_hello', 'foot': 'footer'}
FIELDS = tuple(TEXTS) + tuple(LINKS) + ('note', 'logo', 'palette') + tuple(PICKS)


def palette_names():
    try:
        from watashipanel.panel.common import WS_PALETTE_NAMES
        return tuple(WS_PALETTE_NAMES)
    except Exception:
        return ('violet',)


def plain(text):
    """The support text as plain words.

    The text used to be written in an html editor and was stored escaped, so
    an old value can carry tags and entities; a new one is plain already."""
    out = str(text or '')
    if '<' in out or '&' in out:
        out = re.sub(r'(?i)<br\s*/?>', '\n', out)
        out = re.sub(r'(?i)</(p|div|li|h[1-6])\s*>', '\n', out)
        out = re.sub(r'<[^>]*>', '', out)
        out = html.unescape(out)
    out = out.replace('\r\n', '\n').replace('\r', '\n')
    out = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', out)
    out = re.sub(r'[ \t]+\n', '\n', out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


def one_line(text, room):
    out = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(text or ''))
    out = re.sub(r'\s+', ' ', out).strip()
    return out[:room].strip()


def link(text, room=300):
    """A support or bot address, or '' when it is not one.

    @name and t.me/name are what people type for Telegram, so both are
    turned into the full address."""
    out = str(text or '').strip()
    if not out:
        return ''
    if re.match(r'^@[A-Za-z0-9_]{3,64}$', out):
        out = 'https://t.me/' + out[1:]
    elif re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', out):
        out = 'mailto:' + out
    elif re.match(r'^(t\.me|telegram\.me|wa\.me)/', out, re.I) or re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/|$)', out):
        out = 'https://' + out
    if len(out) > room or re.search(r'[\s"\'<>`\\]', out):
        return ''
    if re.match(r'^https?://[A-Za-z0-9.-]+(:\d+)?(/|\?|#|$)', out, re.I):
        return out
    if re.match(r'^tg://[A-Za-z]', out, re.I):
        return out
    if re.match(r'^mailto:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', out, re.I):
        return out
    return ''


def logo(text):
    """A small picture written as a data address, or '' when it is not one."""
    out = str(text or '').strip()
    if not out or len(out) > LOGO_ROOM:
        return ''
    found = LOGO_HEAD.match(out)
    if not found:
        return ''
    try:
        body = base64.b64decode(found.group(2), validate=True)
    except (binascii.Error, ValueError):
        return ''
    kind = found.group(1)
    if not any(body.startswith(head) for head in LOGO_MAGIC[kind]):
        return ''
    if kind == 'webp' and body[8:12] != b'WEBP':
        return ''
    return out


def clean(raw):
    """Only what is valid and not empty; every other value is inherited."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, room in TEXTS.items():
        value = one_line(raw.get(key), room)
        if value:
            out[key] = value
    for key, room in LINKS.items():
        value = link(raw.get(key), room)
        if value:
            out[key] = value
    note = plain(raw.get('note'))[:NOTE_ROOM].strip()
    if note:
        out['note'] = note
    picture = logo(raw.get('logo'))
    if picture:
        out['logo'] = picture
    palette = str(raw.get('palette') or '')
    if palette in palette_names():
        out['palette'] = palette
    for key, allowed in PICKS.items():
        value = str(raw.get(key) or '')
        if value in allowed:
            out[key] = value
    show = raw.get('show')
    if isinstance(show, dict):
        kept = {name: bool(show[name]) for name in SECTIONS if isinstance(show.get(name), bool)}
        if kept:
            out['show'] = kept
    return out


def problems(raw):
    """The names of the values that were sent but could not be kept."""
    bad = []
    if not isinstance(raw, dict):
        return bad
    for key in LINKS:
        if str(raw.get(key) or '').strip() and not link(raw.get(key), LINKS[key]):
            bad.append(key)
    if str(raw.get('logo') or '').strip() and not logo(raw.get('logo')):
        bad.append('logo')
    return bad


def is_owner(admin):
    return admin is not None and getattr(admin, 'id', None) == 1


def owner_value(key):
    try:
        from watashipanel.models import ConfigEnum, hconfig
        value = str(hconfig(getattr(ConfigEnum, OWNER_CONFIGS[key])) or '')
    except Exception:
        return ''
    if key == 'note':
        return plain(value)[:NOTE_ROOM].strip()
    if key == 'support':
        return link(html.unescape(value)) or ''
    return one_line(html.unescape(value), 200)


def own(admin):
    """The design one admin wrote, without anything inherited."""
    if admin is None:
        return {}
    try:
        stored = json.loads(getattr(admin, 'page_design', None) or '{}')
    except Exception:
        stored = {}
    out = clean(stored)
    if is_owner(admin):
        for key in OWNER_CONFIGS:
            out.pop(key, None)
            value = owner_value(key)
            if value:
                out[key] = value
    return out


def chain(admin):
    """This admin, the admin above them and so on up to the owner."""
    rows = []
    seen = set()
    while admin is not None and getattr(admin, 'id', None) not in seen and len(rows) < 32:
        rows.append(admin)
        seen.add(admin.id)
        if is_owner(admin):
            break
        try:
            admin = admin.parent_admin
        except Exception:
            admin = None
    if not rows or not is_owner(rows[-1]):
        try:
            from watashipanel.models import AdminUser
            top = AdminUser.query.filter(AdminUser.id == 1).first()
            if top is not None and top.id not in seen:
                rows.append(top)
        except Exception:
            pass
    return rows


def legacy():
    try:
        from watashipanel.panel import watashi_settings
        return watashi_settings.load()
    except Exception:
        return {}


def blend(admins, old=None):
    """The design that is in force for the given chain of admins.

    Returns (design, origin): origin tells for every value which admin it
    came from (their name), or '' when it came from the file or the default."""
    designs = [(admin, own(admin)) for admin in admins]
    old = legacy() if old is None else old
    words = old.get('texts') if isinstance(old.get('texts'), dict) else {}
    out = {}
    origin = {}
    for key in FIELDS:
        for admin, design in designs:
            if design.get(key):
                out[key] = design[key]
                origin[key] = str(getattr(admin, 'name', '') or '')
                break
        else:
            value = ''
            if key in LEGACY_TEXTS:
                value = str(words.get(LEGACY_TEXTS[key]) or '').strip()
                if key == 'note':
                    value = plain(value)
                elif key in LINKS:
                    value = link(value) or value
            elif key == 'skin':
                value = str(old.get('skin') or '')
            elif key == 'lang':
                value = str(old.get('lang') or '')
                value = value if value in PICKS['lang'] else ''
            out[key] = value
            origin[key] = ''
    shown = old.get('show') if isinstance(old.get('show'), dict) else {}
    out['show'] = {}
    origin['show'] = {}
    for name in SECTIONS:
        for admin, design in designs:
            if name in (design.get('show') or {}):
                out['show'][name] = bool(design['show'][name])
                origin['show'][name] = str(getattr(admin, 'name', '') or '')
                break
        else:
            out['show'][name] = bool(shown.get(name, True))
            origin['show'][name] = ''
    out['skin'] = out['skin'] if out['skin'] in PICKS['skin'] else 'dark'
    out['app_title'] = out['app_title'] or 'domain'
    return out, origin


def for_admin(admin):
    """The design the users of this admin see."""
    return blend(chain(admin))[0]


def for_user(user):
    """The design the given user sees: the one of the admin who added them."""
    admin = None
    try:
        admin = getattr(user, 'admin', None)
    except Exception:
        admin = None
    try:
        return for_admin(admin)
    except Exception as err:
        from loguru import logger
        logger.warning(f'watashi: the design of the user page could not be read: {err}')
        return blend([], {})[0]


def inherited(admin):
    """What this admin gets when they leave a value empty."""
    return blend(chain(admin)[1:])


def save(admin, raw):
    """Keeps the design of one admin. The owner's name, support link and
    support text go to the settings of the panel, the rest to the admin row."""
    design = clean(raw)
    if is_owner(admin):
        from watashipanel.models import ConfigEnum, set_hconfig
        for key, config in OWNER_CONFIGS.items():
            set_hconfig(getattr(ConfigEnum, config), design.pop(key, ''), commit=False)
    admin.page_design = json.dumps(design, ensure_ascii=False, sort_keys=True) if design else None
    return design


def kept_text(raw):
    """A design read from a backup, as the text the column keeps (or None)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except Exception:
            raw = {}
    design = clean(raw)
    return json.dumps(design, ensure_ascii=False, sort_keys=True) if design else None
