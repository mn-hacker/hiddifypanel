"""Every address of this panel a script may call, gathered in one place.

watashi v12.2.130aq: the panel shipped a raw OpenAPI page and nothing else.
It listed the parent and child machinery beside the two calls a telegram bot
actually needs, said nothing about how a key is sent, and was English only.
People asked their provider instead. This module is the catalogue the API
page draws: it knows nothing about html, so it can be read and tested on its
own.
"""
from flask import g, request
from flask_babel import gettext as _

from hiddifypanel.models import ConfigEnum, hconfig

# The modes that may call a group. 'user' means the key of a customer, not
# of an admin, so an admin key is refused there and the other way round.
OWNER = ('super_admin',)
ADMINS = ('super_admin', 'admin')
EVERY_ADMIN = ('super_admin', 'admin', 'agent')
CUSTOMER = ('user',)

MODE_WORDS = {
    'super_admin': 'Owner',
    'admin': 'Admin',
    'agent': 'Agent',
    'user': 'Customer',
}

# A sentence gets a persian translation. A token a machine reads - a field
# kind, a json answer, the name of a protocol - is the same in every
# language, so it is handed over untouched instead of being "translated"
# into itself.
RAW_WORDS = (
    'uuid', 'Ping', 'Auto', 'Sing-Box',
    '{"version": "..."}', '{"msg": "PONG"}', '{"uuid": "...", "name": "..."}',
    'fa or en.', 'super_admin, admin or agent.',
    'no_reset, monthly, weekly or daily.',
    'all, android, ios, windows, linux, mac or auto.',
    'YYYY-MM-DD HH:MM:SS.',
)


def word(text):
    """Translates a sentence and leaves a machine token alone."""
    if not text or text in RAW_WORDS:
        return text or ''
    return _(text)


METHOD_TONE = {
    'GET': 'green',
    'POST': 'blue',
    'PATCH': 'orange',
    'PUT': 'orange',
    'DELETE': 'red',
    'HEAD': 'grey',
}


def _row(key, method, path, title, note, roles, params=(), body=(), gives=''):
    return {
        'key': key,
        'method': method,
        'path': path,
        'title': title,
        'note': note,
        'roles': list(roles),
        'params': [dict(p) for p in params],
        'body': list(body),
        'gives': gives,
    }


# ------------------------------------------------------------- the book
def raw_book():
    """The catalogue itself, in plain english, with no request behind it."""
    return [
        {
            'id': 'panel',
            'name': 'Panel',
            'note': 'Is the panel up, and which version is it.',
            'icon': 'fa-solid fa-server',
            'base': 'admin',
            'rows': [
                _row('panel-info', 'GET', 'api/v2/panel/info/',
                     'Panel version',
                     'The version this panel runs. The cheapest call to prove a key works.',
                     EVERY_ADMIN, gives='{"version": "..."}'),
                _row('panel-ping', 'GET', 'api/v2/panel/ping/',
                     'Ping',
                     'Answers pong. Also answers POST, PUT, PATCH and DELETE, so a health check can use any of them.',
                     EVERY_ADMIN, gives='{"msg": "PONG"}'),
            ],
        },
        {
            'id': 'admin',
            'name': 'Admin API',
            'note': 'What a reseller panel or a telegram bot needs: read, add, change and remove customers.',
            'icon': 'fa-solid fa-user-shield',
            'base': 'admin',
            'rows': [
                _row('admin-me', 'GET', 'api/v2/admin/me/',
                     'Who am I',
                     'The admin the key belongs to: name, mode, quota and the parent admin.',
                     EVERY_ADMIN),
                _row('admin-status', 'GET', 'api/v2/admin/server_status/',
                     'Server status',
                     'Processor, memory, disk, the five heaviest processes, latency, and the daily usage history of this admin.',
                     EVERY_ADMIN,
                     params=[{'name': 'admin_id', 'kind': 'query',
                              'note': 'Whose history to read. Yours by default.'}]),
                _row('users-list', 'GET', 'api/v2/admin/user/',
                     'List the customers',
                     'Every customer this admin may see. An agent sees only their own.',
                     EVERY_ADMIN),
                _row('users-add', 'POST', 'api/v2/admin/user/',
                     'Add a customer',
                     'Makes a customer. Leave the uuid out and the panel makes one. Only name is required.',
                     EVERY_ADMIN,
                     body=['name', 'usage_limit_GB', 'package_days', 'mode', 'comment',
                           'telegram_id', 'lang', 'enable'],
                     gives='{"uuid": "...", "name": "..."}'),
                _row('user-one', 'GET', 'api/v2/admin/user/{uuid}/',
                     'One customer',
                     'Everything about one customer: usage, days left, keys, when they were last online.',
                     EVERY_ADMIN),
                _row('user-patch', 'PATCH', 'api/v2/admin/user/{uuid}/',
                     'Change a customer',
                     'Send only the fields you want changed. Sending start_date as null restarts the package.',
                     EVERY_ADMIN,
                     body=['name', 'usage_limit_GB', 'package_days', 'mode', 'comment',
                           'current_usage_GB', 'start_date', 'telegram_id', 'lang', 'enable']),
                _row('user-del', 'DELETE', 'api/v2/admin/user/{uuid}/',
                     'Remove a customer',
                     'Removes the customer and every config of theirs.',
                     EVERY_ADMIN),
                _row('admins-list', 'GET', 'api/v2/admin/admin_user/',
                     'List the admins',
                     'The admins under this one. An agent cannot call it.',
                     ADMINS),
                _row('admins-add', 'POST', 'api/v2/admin/admin_user/',
                     'Add an admin',
                     'Makes a reseller. mode is one of super_admin, admin or agent.',
                     ADMINS,
                     body=['name', 'mode', 'can_add_admin', 'lang', 'comment',
                           'telegram_id', 'max_users', 'max_active_users', 'data_limit']),
                _row('admin-one', 'GET', 'api/v2/admin/admin_user/{uuid}/',
                     'One admin', 'Everything about one admin.', ADMINS),
                _row('admin-patch', 'PATCH', 'api/v2/admin/admin_user/{uuid}/',
                     'Change an admin', 'Send only the fields you want changed.', ADMINS,
                     body=['name', 'mode', 'can_add_admin', 'max_users', 'data_limit']),
                _row('admin-del', 'DELETE', 'api/v2/admin/admin_user/{uuid}/',
                     'Remove an admin', 'Removes the admin.', ADMINS),
                _row('log-get', 'GET', 'api/v2/admin/log/',
                     'Read a log file',
                     'One file out of the system log folder, as html.',
                     OWNER,
                     params=[{'name': 'file', 'kind': 'query', 'note': 'The file name. Required.'},
                             {'name': 'domain', 'kind': 'query', 'note': 'Only the lines of one domain.'}]),
                _row('usage-update', 'GET', 'api/v2/admin/update_user_usage/',
                     'Refresh the usage',
                     'Reads the usage off the cores right now instead of waiting for the timer.',
                     OWNER),
                _row('all-configs', 'GET', 'api/v2/admin/all-configs/',
                     'Every setting of the panel',
                     'The whole configuration as the installer sees it. Large, and it carries secrets.',
                     OWNER),
            ],
        },
        {
            'id': 'user',
            'name': 'Customer API',
            'note': 'Called with the key of a customer, not of an admin. This is what an app or a bot shows a customer about their own account.',
            'icon': 'fa-solid fa-user',
            'base': 'user',
            'rows': [
                _row('me', 'GET', 'api/v2/user/me/',
                     'The account',
                     'Name, how much is used, how much is left, days remaining, brand and the telegram bot link.',
                     CUSTOMER),
                _row('me-patch', 'PATCH', 'api/v2/user/me/',
                     'Change the account',
                     'The only two things a customer may change about themselves.',
                     CUSTOMER, body=['language', 'telegram_id']),
                _row('user-configs', 'GET', 'api/v2/user/all-configs/',
                     'Every config',
                     'One row per config: name, domain, protocol, transport, security and the link itself.',
                     CUSTOMER),
                _row('user-mtproxies', 'GET', 'api/v2/user/mtproxies/',
                     'Telegram proxies',
                     'The mtproto links of this account. 404 when telegram proxy is off.',
                     CUSTOMER),
                _row('user-short', 'GET', 'api/v2/user/short/',
                     'A short link',
                     'A short address for the customer page, and how many seconds it lives.',
                     CUSTOMER),
                _row('user-apps', 'GET', 'api/v2/user/apps/',
                     'The apps',
                     'Every client app for one platform, with the download links and the deep link that imports the subscription.',
                     CUSTOMER,
                     params=[{'name': 'platform', 'kind': 'query',
                              'note': 'all, android, ios, windows, linux, mac or auto.'}]),
            ],
        },
        {
            'id': 'sub',
            'name': 'Subscription links',
            'note': 'No key and no header: the uuid of the customer is the address itself. This is what a client app is handed.',
            'icon': 'fa-solid fa-link',
            'base': 'sub',
            'rows': [
                _row('sub-auto', 'GET', 'sub/',
                     'Auto',
                     'Reads the app asking and answers in the format that app understands. The one link to hand out.',
                     CUSTOMER),
                _row('sub-all', 'GET', 'all.txt',
                     'Plain list',
                     'Every config as text, one per line.',
                     CUSTOMER,
                     params=[{'name': 'mode', 'kind': 'query', 'note': 'new or old.'},
                             {'name': 'name', 'kind': 'query', 'note': 'The name the app shows.'}]),
                _row('sub-b64', 'GET', 'sub64/',
                     'Base64 list', 'The same list, base64 encoded, for older v2ray apps.', CUSTOMER),
                _row('sub-clash', 'GET', 'clash/meta/all.yml',
                     'Clash and Meta',
                     'A yaml profile. Use clash/all.yml for plain Clash and meta for Mihomo.',
                     CUSTOMER),
                _row('sub-singbox', 'GET', 'full-singbox.json',
                     'Sing-Box', 'The whole profile as sing-box json.', CUSTOMER),
                _row('sub-wg', 'GET', 'wireguard',
                     'WireGuard file', 'The tunnel as a .conf file. No v2ray app can read it.', CUSTOMER),
                _row('sub-awg', 'GET', 'amnezia',
                     'AmneziaWG file', 'The AmneziaWG tunnel as a .conf file.', CUSTOMER),
                _row('sub-mieru', 'GET', 'mieru',
                     'Mieru file', 'The whole account as the json the Mieru client reads.', CUSTOMER),
                _row('sub-configs', 'GET', 'configs',
                     'The configs page', 'The page a customer opens to take one config at a time.', CUSTOMER),
            ],
        },
        {
            'id': 'v1',
            'name': 'Old API (v1)',
            'note': 'Kept so old bots keep working. Owner only, and every answer is a flat dictionary. Write new code against v2.',
            'icon': 'fa-solid fa-box-archive',
            'base': 'admin',
            'rows': [
                _row('v1-users', 'GET', 'api/v1/user/',
                     'Customers',
                     'Every customer, or one of them when uuid is given.',
                     OWNER,
                     params=[{'name': 'uuid', 'kind': 'query', 'note': 'One customer instead of all.'}]),
                _row('v1-user-add', 'POST', 'api/v1/user/',
                     'Add or change a customer',
                     'One call for both. uuid is required, so the caller decides it.',
                     OWNER, body=['uuid', 'name', 'usage_limit_GB', 'package_days', 'mode']),
                _row('v1-user-del', 'DELETE', 'api/v1/user/',
                     'Remove a customer', 'The uuid goes in the query string.', OWNER,
                     params=[{'name': 'uuid', 'kind': 'query', 'note': 'Required.'}]),
                _row('v1-admins', 'GET', 'api/v1/admin/',
                     'Admins', 'Every admin, or one of them when uuid is given.', OWNER,
                     params=[{'name': 'uuid', 'kind': 'query', 'note': 'One admin instead of all.'}]),
                _row('v1-msg', 'POST', 'api/v1/send_msg/',
                     'Send a telegram message', 'Sends a message through the bot of the panel.', OWNER),
            ],
        },
    ]


# ------------------------------------------------------ the fields tables
FIELD_BOOK = [
    {
        'id': 'user',
        'name': 'The customer object',
        'rows': [
            ('uuid', 'uuid', 'The key of the customer. Also their API key.'),
            ('name', 'text', 'Required when a customer is made.'),
            ('usage_limit_GB', 'number', 'The quota in gigabytes. 0 means no limit.'),
            ('package_days', 'number', 'How many days the package lasts.'),
            ('current_usage_GB', 'number', 'How much is already spent. Set it to 0 to reset.'),
            ('start_date', 'date', 'YYYY-MM-DD. Null means the package starts on first use.'),
            ('last_reset_time', 'date', 'When the usage was last put back to zero.'),
            ('last_online', 'time', 'YYYY-MM-DD HH:MM:SS.'),
            ('mode', 'text', 'no_reset, monthly, weekly or daily.'),
            ('enable', 'yes or no', 'A switched off customer keeps their configs but cannot connect.'),
            ('is_active', 'yes or no', 'Read only: enabled, still has days and still has quota.'),
            ('comment', 'text', 'Yours to use. The panel never reads it.'),
            ('telegram_id', 'number', 'The telegram account of this customer.'),
            ('lang', 'text', 'fa or en.'),
            ('added_by_uuid', 'uuid', 'The admin who made this customer.'),
        ],
    },
    {
        'id': 'admin',
        'name': 'The admin object',
        'rows': [
            ('uuid', 'uuid', 'The key of the admin. Also their API key.'),
            ('name', 'text', 'Required.'),
            ('mode', 'text', 'super_admin, admin or agent.'),
            ('can_add_admin', 'yes or no', 'Whether this admin may make more admins.'),
            ('parent_admin_uuid', 'uuid', 'Who made this admin.'),
            ('max_users', 'number', 'How many customers this admin may have.'),
            ('max_active_users', 'number', 'How many of them may be active at once.'),
            ('data_limit', 'number', 'The quota of the admin in bytes. 0 means no limit.'),
            ('telegram_id', 'number', 'The telegram account of this admin.'),
            ('lang', 'text', 'fa or en.'),
        ],
    },
]

# What the panel answers when a call goes wrong.
FAULT_BOOK = [
    ('200', 'Done.'),
    ('401', 'No key, or a key this panel does not know.'),
    ('403', 'A real key, but not allowed to do this.'),
    ('404', 'No such customer, admin or address.'),
    ('422', 'The body did not pass the check. The answer says which field.'),
    ('500', 'The panel itself broke. The system log has the reason.'),
]


# ----------------------------------------------------------- the facts
def api_facts():
    """The addresses and the key of whoever is reading the page."""
    try:
        host = request.host
    except Exception:
        host = ''
    try:
        path = str(g.proxy_path or '')
    except Exception:
        path = ''
    try:
        key = str(g.account.uuid or '')
    except Exception:
        key = ''
    try:
        mode = str(getattr(g.account, 'mode', '') or '')
    except Exception:
        mode = ''
    root = ('https://' + host + '/' + path) if (host and path) else ''
    return {
        'host': host,
        'proxy_path': path,
        'root': root,
        'admin_base': root + '/' if root else '',
        'user_base': (root + '/{USER-UUID}/') if root else '',
        'key': key,
        'mode': mode,
        'mode_word': word(MODE_WORDS.get(mode, mode or 'Admin')),
    }


def curl_of(row, facts):
    """The exact command this row is called with, ready to paste."""
    base = facts['user_base'] if row.get('base') == 'sub' else facts['admin_base']
    url = base + row['path']
    bits = ['curl -X ' + row['method'], "'" + url + "'"]
    if row.get('base') != 'sub':
        bits.append("-H 'Hiddify-API-Key: " + (facts['key'] or '{YOUR-API-KEY}') + "'")
    if row['method'] in ('POST', 'PATCH', 'PUT') and row.get('body'):
        bits.append("-H 'Content-Type: application/json'")
        pairs = ', '.join('"' + name + '": "..."' for name in row['body'][:3])
        bits.append("-d '{" + pairs + "}'")
    return ' \\\n  '.join(bits)


def can_call(row, mode):
    """Whether the admin reading the page may call this row with their key."""
    if 'user' in row['roles']:
        # a customer key, which an admin does not have
        return False
    return mode in row['roles']


def api_groups():
    """The whole book, told for the person reading it right now."""
    facts = api_facts()
    out = []
    for group in raw_book():
        rows = []
        for row in group['rows']:
            row = dict(row)
            row['base'] = group['base']
            row['title'] = word(row['title'])
            row['note'] = word(row['note'])
            row['gives'] = word(row.get('gives'))
            row['tone'] = METHOD_TONE.get(row['method'], 'grey')
            row['who'] = [word(MODE_WORDS.get(one, one)) for one in row['roles']]
            row['mine'] = can_call(row, facts['mode'])
            row['curl'] = curl_of(row, facts)
            row['url'] = (facts['user_base'] if group['base'] == 'sub'
                          else facts['admin_base']) + row['path']
            for one in row['params']:
                one['note'] = word(one['note'])
            rows.append(row)
        out.append({
            'id': group['id'],
            'name': word(group['name']),
            'note': word(group['note']),
            'icon': group['icon'],
            'rows': rows,
            'n': len(rows),
        })
    return out


def field_groups():
    return [{'id': one['id'], 'name': word(one['name']),
             'rows': [{'name': n, 'kind': word(k), 'note': word(t)} for n, k, t in one['rows']]}
            for one in FIELD_BOOK]


def fault_rows():
    return [{'code': code, 'note': word(note)} for code, note in FAULT_BOOK]


def docs_url():
    """The raw OpenAPI page, when this panel still draws one."""
    try:
        from hiddifypanel.hutils.flask import hurl_for
        return hurl_for('openapi.docs')
    except Exception:
        return ''


def page_data():
    """Everything the API page draws."""
    facts = api_facts()
    groups = api_groups()
    return {
        'ap_facts': facts,
        'ap_groups': groups,
        'ap_fields': field_groups(),
        'ap_faults': fault_rows(),
        'ap_total': sum(one['n'] for one in groups),
        'ap_mine': sum(1 for one in groups for row in one['rows'] if row['mine']),
        'ap_bot': bool(hconfig(ConfigEnum.telegram_bot_token)),
        'ap_docs': docs_url(),
    }
