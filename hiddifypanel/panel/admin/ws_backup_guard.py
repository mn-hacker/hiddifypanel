"""watashi v12.2.130: the part of a restore that thinks before it writes.

Until now a restore read a file, saw that one of six keys held a list, and
handed the whole thing to the database. Everything that went wrong after that
went wrong silently: a file from a newer panel carrying settings this one has
never heard of, a half finished download, a backup whose settings section is
missing the keys that keep the services switched on. The owner only found out
when the panel came back with the services off.

So every restore now walks through the same gates, in this order:

  1. read      - is this json, is it a backup at all
  2. inspect   - what is in it, what is wrong with it, what will it change
  3. snapshot  - the panel as it stands right now, written to disk first
  4. apply     - the old path, unchanged
  5. health    - can an admin still sign in, are the core settings there
  6. rollback  - if health failed, the snapshot goes back in

Nothing here talks to the page or the log directly. It returns plain data and
lets the caller decide what to say.
"""

import json
import os
import datetime

WS_SECTIONS = ('childs', 'users', 'domains', 'proxies', 'admin_users', 'hconfigs')

# A settings section that does not carry these is not a settings section worth
# restoring: without them the panel comes back on defaults, which is exactly
# how owners ended up with their services switched off after a restore.
WS_CORE_SETTINGS = ('unique_id', 'proxy_path_admin', 'proxy_path_client', 'proxy_path')


def ws_backup_dir():
    """Where backups live, next to the ones the nightly job writes."""
    base = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager/')
    try:
        from flask import current_app
        base = current_app.config.get('HIDDIFY_CONFIG_PATH', base)
    except Exception:
        pass
    return os.path.join(base, 'backup')


def ws_read(raw):
    """json in, bag out. Raises ValueError with a word the caller can act on."""
    if not raw:
        raise ValueError('empty')
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'ignore')
    try:
        bag = json.loads(raw)
    except Exception:
        raise ValueError('not_json')
    if not isinstance(bag, dict):
        raise ValueError('not_backup')
    if not any(isinstance(bag.get(name), list) for name in WS_SECTIONS):
        raise ValueError('not_backup')
    return bag


def _known_config_names():
    try:
        from hiddifypanel.models import ConfigEnum
        return {str(item) for item in ConfigEnum}
    except Exception:
        return set()


def _checksum_of(body):
    import hashlib
    canon = json.dumps(body, sort_keys=True, default=str).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canon).hexdigest()


def ws_inspect(bag, wants=None):
    """Everything that can be said about a file without writing a single row.

    fatal  - the restore must not start
    warn   - it may start, but the owner should know first
    plan   - what each chosen section would bring in
    """
    wants = wants or {}
    report = {'fatal': [], 'warn': [], 'counts': {}, 'plan': {}, 'meta': {},
              'unknown_settings': [], 'missing_core_settings': []}

    for name in WS_SECTIONS:
        rows = bag.get(name)
        if rows is None:
            continue
        if not isinstance(rows, list):
            report['fatal'].append('section_not_list:' + name)
            continue
        if any(not isinstance(row, dict) for row in rows):
            report['fatal'].append('section_rows_broken:' + name)
            continue
        report['counts'][name] = len(rows)

    meta = bag.get('meta')
    if isinstance(meta, dict):
        report['meta'] = meta
        stamped = meta.get('checksum')
        if stamped:
            body = {key: value for key, value in bag.items() if key != 'meta'}
            try:
                if _checksum_of(body) != stamped:
                    report['fatal'].append('checksum_mismatch')
            except Exception:
                report['warn'].append('checksum_unreadable')
        theirs = meta.get('db_version')
        try:
            from hiddifypanel.panel.init_db import MAX_DB_VERSION
            if isinstance(theirs, int) and theirs > int(MAX_DB_VERSION):
                report['fatal'].append('newer_panel:%s>%s' % (theirs, MAX_DB_VERSION))
        except Exception:
            pass
    else:
        # Every file written before this round is in this shape. It is still a
        # good backup, it just cannot prove anything about itself.
        report['warn'].append('no_meta')

    settings = bag.get('hconfigs')
    if isinstance(settings, list) and settings:
        known = _known_config_names()
        seen = set()
        for row in settings:
            if not isinstance(row, dict):
                continue
            name = str(row.get('key'))
            seen.add(name)
            if known and name not in known:
                if name not in report['unknown_settings']:
                    report['unknown_settings'].append(name)
        missing = [name for name in WS_CORE_SETTINGS if name not in seen]
        # proxy_path counts either way, older panels used the single key.
        if 'proxy_path' in missing and ('proxy_path_admin' in seen or 'proxy_path_client' in seen):
            missing.remove('proxy_path')
        report['missing_core_settings'] = missing
        if missing:
            report['warn'].append('core_settings_missing')
        if report['unknown_settings']:
            report['warn'].append('unknown_settings')

    admins = bag.get('admin_users')
    if isinstance(admins, list):
        if not admins:
            report['warn'].append('no_admins')
        else:
            with_uuid = [a for a in admins if isinstance(a, dict) and a.get('uuid')]
            if not with_uuid:
                report['fatal'].append('admins_without_uuid')
            named = [a for a in with_uuid if (a.get('username') or '').strip()]
            if not named:
                # Files written before this round never carried the sign-in
                # details, so the way in stays whatever this server has.
                report['warn'].append('no_admin_credentials')

    users = bag.get('users')
    if isinstance(users, list):
        broken = [u for u in users if not isinstance(u, dict) or not u.get('uuid')]
        if broken:
            report['warn'].append('users_without_uuid:%s' % len(broken))

    domains = bag.get('domains')
    if isinstance(domains, list) and domains:
        names = [str(d.get('domain') or '') for d in domains if isinstance(d, dict)]
        blank = [name for name in names if not name.strip()]
        if blank:
            report['warn'].append('domains_without_name:%s' % len(blank))
        if len(set(names)) != len(names):
            report['warn'].append('domains_repeated')

    if wants:
        if wants.get('enable_config_restore'):
            report['plan']['settings'] = report['counts'].get('hconfigs', 0)
        if wants.get('enable_user_restore'):
            report['plan']['users'] = report['counts'].get('users', 0)
        if wants.get('enable_domain_restore'):
            report['plan']['domains'] = report['counts'].get('domains', 0)
        if not report['plan']:
            report['fatal'].append('nothing_picked')
        if wants.get('enable_config_restore') and not report['counts'].get('hconfigs'):
            report['fatal'].append('settings_asked_but_absent')
        if wants.get('enable_user_restore') and 'users' not in report['counts']:
            report['fatal'].append('users_asked_but_absent')
        if wants.get('enable_domain_restore') and 'domains' not in report['counts']:
            report['fatal'].append('domains_asked_but_absent')

    report['ok'] = not report['fatal']
    return report


def ws_snapshot(tag='pre-restore'):
    """The panel as it stands, on disk, before anything is written.

    This is the one thing that was missing every time a restore went wrong:
    there was nothing to go back to.
    """
    from hiddifypanel.panel import hiddify
    folder = os.path.join(ws_backup_dir(), 'pre-restore')
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y_%m_%d__%H_%M_%S')
    path = os.path.join(folder, '%s_%s.json' % (stamp, tag))
    with open(path, 'w') as handle:
        json.dump(hiddify.dump_db_to_dict(), handle, indent=2, sort_keys=True, default=str)
    _prune(folder, keep=10)
    return path


def _prune(folder, keep=10):
    try:
        files = [os.path.join(folder, name) for name in os.listdir(folder) if name.endswith('.json')]
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old in files[keep:]:
            os.remove(old)
    except Exception as problem:
        print('the old snapshots could not be cleaned', problem)


def ws_health():
    """Is this panel still usable after the write.

    Deliberately narrow: only the things whose absence means nobody can get
    back in or no service can come up.
    """
    out = {'ok': True, 'problems': []}
    try:
        from hiddifypanel.models import AdminUser, User, Domain, ConfigEnum, hconfig
        owner = AdminUser.get_super_admin()
        if owner is None or not owner.uuid:
            out['problems'].append('no_super_admin')
        if not Domain.query.count():
            out['problems'].append('no_domain')
        for key in (ConfigEnum.proxy_path_admin, ConfigEnum.proxy_path_client, ConfigEnum.unique_id):
            try:
                if not hconfig(key):
                    out['problems'].append('missing_setting:%s' % key)
            except Exception:
                out['problems'].append('missing_setting:%s' % key)
        try:
            User.query.count()
        except Exception:
            out['problems'].append('users_unreadable')
    except Exception as problem:
        out['problems'].append('health_check_failed:%s' % problem)
    out['ok'] = not out['problems']
    return out


def ws_rollback(path):
    """Put the snapshot back. Used only when the health gate said no."""
    from hiddifypanel.panel import hiddify
    with open(path) as handle:
        bag = json.load(handle)
    hiddify.set_db_from_json(bag,
                             set_users=True,
                             set_domains=True,
                             set_settings=True,
                             override_unique_id=True,
                             override_child_unique_id=True,
                             override_root_admin=True)
    return True


# ------------------------------------------------------------------ secrets
#
# The database is not the whole panel. The MySQL and Redis passwords and the
# flask secret live in app.cfg, and the warp engine keeps its own file. None of
# it was ever in a backup, so a backup could never rebuild a lost server.
#
# Two rules hold here, both on purpose:
#   - a secret is only written into a file when the owner has set a passphrase,
#     because these files travel to telegram
#   - a restore never writes secrets back by itself. They belong to the machine
#     they were made on: putting another server MySQL password into app.cfg
#     would take the panel down. They are reported, and the owner puts them
#     back if the machine really is the same one.

WS_SECRET_FILES = ('hiddify-panel/app.cfg', 'other/warp/warpplus/engine.conf')


def ws_passphrase():
    spot = os.environ.get('WATASHI_BACKUP_PASSPHRASE')
    if spot:
        return spot
    base = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager/')
    path = os.path.join(base, 'hiddify-panel/backup-passphrase')
    try:
        if os.path.exists(path):
            return open(path).read().strip() or None
    except Exception as problem:
        print('the backup passphrase could not be read', problem)
    return None


def _box(passphrase):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b'watashi-backup-v1', iterations=200000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode('utf-8'))))


def ws_secret_bundle():
    """The sealed envelope, or nothing at all. Never plain text."""
    passphrase = ws_passphrase()
    if not passphrase:
        return None
    base = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager/')
    try:
        from flask import current_app
        base = current_app.config.get('HIDDIFY_CONFIG_PATH', base)
    except Exception:
        pass
    body = {}
    for rel in WS_SECRET_FILES:
        path = os.path.join(base, rel)
        try:
            if os.path.exists(path):
                body[rel] = open(path, encoding='utf-8', errors='ignore').read()
        except Exception as problem:
            print('a secret file could not be read', rel, problem)
    if not body:
        return None
    try:
        sealed = _box(passphrase).encrypt(json.dumps(body).encode('utf-8'))
    except Exception as problem:
        print('the secrets could not be sealed, so they stay out of the file', problem)
        return None
    return {'cipher': 'fernet-pbkdf2-sha256-200000',
            'files': sorted(body.keys()),
            'sealed': sealed.decode('ascii')}


def ws_open_secrets(bundle, passphrase=None):
    """Read an envelope back, for showing the owner. Writes nothing."""
    if not isinstance(bundle, dict) or not bundle.get('sealed'):
        return None
    passphrase = passphrase or ws_passphrase()
    if not passphrase:
        return None
    try:
        opened = _box(passphrase).decrypt(bundle['sealed'].encode('ascii'))
        return json.loads(opened.decode('utf-8'))
    except Exception as problem:
        print('the secrets could not be opened with this passphrase', problem)
        return None
