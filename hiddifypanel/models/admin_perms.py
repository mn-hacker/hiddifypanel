"""Who is allowed to see and touch which part of the panel.

The panel has four admin modes. Owner, Admin and Agent carry a fixed set of
permissions. The fourth one, Custom, keeps its own list, so the owner can
hand craft a single account.

This file only knows about names. The granted keys of a custom account live
in one text column on the admin row.
"""
import json

# every page of the panel
WS_PAGE_CAPS = (
    'dashboard', 'monitoring', 'usage',
    'users', 'admins', 'account',
    'domains', 'proxies', 'tunnel',
    'settings', 'actions', 'backup', 'nodes',
)

# the things an account may do to rows, on top of simply opening a page
WS_ACTION_CAPS = (
    'user_add', 'user_edit', 'user_delete', 'user_reset',
    'admin_add', 'admin_edit', 'admin_delete',
)

WS_ALL_CAPS = WS_PAGE_CAPS + WS_ACTION_CAPS

# how the switches are grouped inside the create/edit window
WS_CAP_GROUPS = (
    ('overview', ('dashboard', 'monitoring', 'usage')),
    ('access', ('users', 'admins', 'account')),
    ('network', ('domains', 'proxies', 'tunnel')),
    ('system', ('settings', 'actions', 'backup', 'nodes')),
    ('user_actions', ('user_add', 'user_edit', 'user_delete', 'user_reset')),
    ('admin_actions', ('admin_add', 'admin_edit', 'admin_delete')),
)

# the power that follows the "can add sub admin" switch
WS_ADMIN_POWER_CAPS = ('admin_add', 'admin_edit', 'admin_delete')

WS_MODE_CAPS = {
    'super_admin': set(WS_ALL_CAPS),
    'admin': set((
        'dashboard', 'monitoring', 'usage', 'users', 'admins', 'account',
        'domains', 'proxies',
        'user_add', 'user_edit', 'user_delete', 'user_reset',
    )),
    'agent': set((
        'dashboard', 'usage', 'users', 'admins', 'account',
        'user_add', 'user_edit', 'user_delete', 'user_reset',
    )),
    'custom': set(),
}

# which part of the panel an endpoint belongs to; matched by prefix so every
# helper route of a page follows the page itself
WS_ENDPOINT_CAPS = (
    # removing a node is server work, not dashboard work
    ('admin.Dashboard:remove_child', 'nodes'),
    ('admin.Dashboard:', 'dashboard'),
    ('admin.MonitoringAdmin:', 'monitoring'),
    ('admin.UsageAdmin:', 'usage'),
    ('admin.AccountAdmin:', 'account'),
    ('admin.CommercialInfo:', 'dashboard'),
    ('admin.SettingAdmin:', 'settings'),
    ('admin.QuickSetup:', 'settings'),
    ('admin.ProxyAdmin:', 'proxies'),
    ('admin.Actions:', 'actions'),
    ('admin.Backup:', 'backup'),
    ('admin.TunnelAdmin:', 'tunnel'),
    ('flask.user.', 'users'),
    ('flask.adminuser.', 'admins'),
    ('flask.domain.', 'domains'),
    ('flask.child.', 'nodes'),
    ('flask.proxydetails.', 'proxies'),
    ('flask.strconfig.', 'settings'),
    ('flask.boolconfig.', 'settings'),
)


def ws_mode_name(account):
    """The mode of an account as a plain string, never raising."""
    mode = getattr(account, 'mode', None)
    name = getattr(mode, 'name', None) or (str(mode) if mode else '')
    return name if name in WS_MODE_CAPS else ''


def ws_read_perms(account):
    """The keys stored on a custom account, cleaned of anything unknown."""
    raw = getattr(account, 'permissions', None)
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        keys = list(raw)
    else:
        try:
            keys = json.loads(raw)
        except BaseException:
            keys = [part.strip() for part in str(raw).split(',')]
    known = set(WS_ALL_CAPS)
    return [str(key) for key in keys if str(key) in known]


def ws_write_perms(account, keys):
    """Store a granted list on an account. Order follows the catalog."""
    wanted = set(str(key) for key in (keys or []))
    kept = [cap for cap in WS_ALL_CAPS if cap in wanted]
    account.permissions = json.dumps(kept)
    return kept


def ws_granted(account):
    """Everything this account may do right now."""
    mode = ws_mode_name(account)
    if not mode:
        return set()
    if mode == 'custom':
        given = set(ws_read_perms(account))
        # a custom account always keeps its own page, otherwise signing in
        # would lead to a wall
        given.add('account')
        return given
    caps = set(WS_MODE_CAPS[mode])
    if mode != 'super_admin':
        if getattr(account, 'can_add_admin', False):
            caps |= set(WS_ADMIN_POWER_CAPS)
        else:
            caps -= set(WS_ADMIN_POWER_CAPS)
    return caps


def ws_account_can(account, cap):
    if account is None:
        return False
    return cap in ws_granted(account)


def ws_can(cap):
    """The same question for the account of the running request.

    Used by the templates, so the menu only shows what can be opened.
    """
    try:
        from flask import g
        return ws_account_can(getattr(g, 'account', None), cap)
    except BaseException:
        return False


def ws_plain_endpoint(endpoint):
    name = endpoint or ''
    if name.startswith('child_'):
        name = name[len('child_'):]
    return name


def ws_endpoint_cap(endpoint):
    name = ws_plain_endpoint(endpoint)
    for prefix, cap in WS_ENDPOINT_CAPS:
        if name.startswith(prefix):
            return cap
    return None


def ws_is_panel_endpoint(endpoint):
    name = ws_plain_endpoint(endpoint)
    if not name or name.endswith('.static'):
        return False
    return name.startswith('admin.') or name.startswith('flask.')


def ws_endpoint_allowed(account, endpoint):
    """Gate one request. End users and unknown corners are left alone."""
    mode = ws_mode_name(account)
    if not mode:
        return True  # not an admin account, other guards decide
    cap = ws_endpoint_cap(endpoint)
    if cap is None:
        # a corner nobody mapped: the three fixed modes keep whatever their
        # role already allowed, a hand made account gets nothing extra
        if mode == 'custom':
            return not ws_is_panel_endpoint(endpoint)
        return True
    return cap in ws_granted(account)
