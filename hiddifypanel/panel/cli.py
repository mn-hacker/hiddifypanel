import datetime
import uuid
import json
import os
import re
import click
from dateutil import relativedelta


from hiddifypanel import hutils

from hiddifypanel.models import *
from hiddifypanel.panel import hiddify, usage
from hiddifypanel.database import db
from hiddifypanel.panel.init_db import init_db

from loguru import logger

def drop_db():
    """Cleans database"""
    db.drop_all()


def downgrade():
    if (hconfig(ConfigEnum.db_version) >= "49"):
        set_hconfig(ConfigEnum.db_version, '42', commit=False)
        StrConfig.query.filter(StrConfig.key.in_([ConfigEnum.tuic_enable, ConfigEnum.tuic_port, ConfigEnum.hysteria_enable,
                               ConfigEnum.hysteria_port, ConfigEnum.ssh_server_enable, ConfigEnum.ssh_server_port, ConfigEnum.ssh_server_redis_url])).delete()
        Proxy.query.filter(Proxy.l3.in_([ProxyL3.ssh, ProxyL3.h3_quic, ProxyL3.custom])).delete()
        db.session.commit()
        os.rename("/opt/hiddify-manager/hiddify-panel/hiddifypanel.db.old", "/opt/hiddify-manager/hiddify-panel/hiddifypanel.db")


from celery import shared_task

# watashi v12.2.48: the interval the owner picks in the panel is honoured here, at
# run time, instead of being baked into the celery schedule at start up.
WS_BACKUP_LAST_KEY = "ws:backup:last-run"
WS_BACKUP_KEEP = 48

# watashi v12.2.130x: an update takes a forced backup, the hourly cron used to take
# a forced one as well, and the celery schedule is registered by two app
# factories. Any two of them landing in the same minute wrote two nearly
# identical files. A backup that is younger than this is simply reused.
WS_BACKUP_MIN_GAP = 180  # seconds

# watashi v12.2.130d: the folder was written as the relative string "backup", so a
# backup landed wherever the caller happened to stand. update.sh calls
# backup.sh, which cds into hiddify-panel first, so every backup taken
# before an update went to hiddify-panel/backup/ while the panel page reads
# /opt/hiddify-manager/backup and showed nothing. Worse, the pruning ran on
# that same accidental folder, so it could delete json files that were never
# ours. One absolute home fixes all three.
WS_BACKUP_NAME = re.compile(r'^[0-9]{4}_[0-9]{2}_[0-9]{2}__[0-9]{2}_[0-9]{2}_[0-9]{2}\.json$')


def ws_backup_root() -> str:
    """watashi v12.2.130o: asked of panel/ws_guard.py, which the guard asks too.

    The folder used to be worked out here and a second time inside the
    backup guard, so part N fixed this one and the snapshot before a
    restore still died on the same permission. One answer, two callers.
    """
    from hiddifypanel.panel.ws_guard import pick_backup_root
    return pick_backup_root(note=logger.warning)


def ws_backup_files(root: str | None = None) -> list:
    """Only the files this panel wrote. Anything else is none of our business."""
    root = root or ws_backup_root()
    try:
        return [os.path.join(root, n) for n in os.listdir(root) if WS_BACKUP_NAME.match(n)]
    except Exception:
        return []


def ws_adopt_stray_backups() -> int:
    """Collect the backups the relative path left in other folders.

    Runs once per backup and costs nothing when there is nothing to move, so
    the files taken before every past update finally show up in the panel.
    """
    root = ws_backup_root()
    moved = 0
    others = [os.path.join(os.getcwd(), 'backup'),
              '/opt/hiddify-manager/hiddify-panel/backup',
              '/opt/hiddify-manager/hiddify-panel/src/backup']
    for folder in others:
        if not os.path.isdir(folder) or os.path.abspath(folder) == os.path.abspath(root):
            continue
        for path in ws_backup_files(folder):
            target = os.path.join(root, os.path.basename(path))
            try:
                if os.path.exists(target):
                    os.remove(path)
                else:
                    os.replace(path, target)
                    moved += 1
            except Exception as problem:
                logger.warning(f"watashi: {path} could not be moved to the backup folder ({problem})")
        try:
            os.rmdir(folder)
        except Exception:
            pass
    if moved:
        logger.info(f"watashi: {moved} backup(s) found outside the backup folder were moved into it")
    return moved


def ws_backup_interval() -> int:
    """Hours between two automatic backups. 0 means the owner switched it off."""
    try:
        value = int(str(hconfig(ConfigEnum.backup_interval) or "6").strip())
    except (ValueError, TypeError):
        value = 6
    if value <= 0:
        return 0
    return min(720, max(1, value))


def ws_backup_last_run() -> float:
    """Unix time of the last backup. Redis first, then the files themselves."""
    try:
        from hiddifypanel.cache import redis_client
        raw = redis_client.get(WS_BACKUP_LAST_KEY)
        if raw:
            return float(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception:
        pass
    newest = 0.0
    for path in ws_backup_files():
        try:
            newest = max(newest, os.path.getmtime(path))
        except Exception:
            pass
    return newest


def ws_recent_backup(now: float, gap: int = WS_BACKUP_MIN_GAP):
    """The backup taken moments ago, if there is one, else None."""
    newest = None
    newest_at = 0.0
    for path in ws_backup_files():
        try:
            when = os.path.getmtime(path)
        except Exception:
            continue
        if when > newest_at:
            newest_at = when
            newest = path
    if newest is not None and 0 <= now - newest_at < gap:
        return newest
    return None


def ws_backup_mark_run(when: float) -> None:
    try:
        from hiddifypanel.cache import redis_client
        redis_client.set(WS_BACKUP_LAST_KEY, str(when))
    except Exception as e:
        logger.warning(f"watashi: the backup time could not be remembered in redis ({e})")


def ws_prune_backups(keep: int = WS_BACKUP_KEEP) -> int:
    """Nothing ever removed these, so a long lived panel filled its disk."""
    removed = 0
    try:
        # watashi v12.2.130d: named files only, in the one real folder. This used to
        # take any .json in whatever folder the process stood in.
        files = ws_backup_files()
        files.sort(key=os.path.getmtime, reverse=True)
        for old in files[keep:]:
            try:
                os.remove(old)
                removed += 1
            except Exception as e:
                logger.warning(f"watashi: an old backup could not be removed ({e})")
    except Exception:
        pass
    return removed


def backup():
    """The manual backup from the command line. It never waits for the clock."""
    # watashi v12.2.107: this used to print the raw python dict, so the install
    # and update logs showed {'status': 'ok', 'file': ...} next to the version
    # lines and looked like a stack trace fragment. the dict is still returned
    # by backup_task for celery; only the console line is human readable now.
    # watashi v12.2.130x: the hourly cron sets WS_BACKUP_IF_DUE, so it no longer
    # forces a backup every hour beside the schedule the panel keeps. A person
    # typing the command, and update.sh before an update, still get one now.
    # quiet=True keeps the task from logging the same sentence this prints.
    if_due = str(os.environ.get('WS_BACKUP_IF_DUE', '')).strip().lower() in ('1', 'true', 'yes')
    result = backup_task(force=not if_due, quiet=True) or {}
    status = result.get('status')
    if status == 'ok' and result.get('reused'):
        print(f"backup skipped: {result.get('file')} was written moments ago")
    elif status == 'ok':
        print(f"backup written to {result.get('file')} "
              f"(sent to {result.get('sent', 0)} admin(s), "
              f"{result.get('pruned', 0)} old file(s) removed)")
    elif status == 'skipped':
        print(f"backup skipped: {result.get('reason', 'unknown reason')}")
    else:
        print(f"backup did not finish: {result}")


def test_notification():
    """Send one test message, so the owner can see whether the bot really works."""
    from hiddifypanel.panel.user_notifications import ws_send_test_notification
    print(json.dumps(ws_send_test_notification(), indent=2, default=str))


@shared_task(ignore_result=True)
def backup_task(force: bool = False, quiet: bool = False):
    interval = ws_backup_interval()
    now = datetime.datetime.now().timestamp()
    if not force:
        if interval == 0:
            logger.info("watashi: the automatic backup is switched off (backup_interval=0)")
            return {'status': 'skipped', 'reason': 'disabled'}
        last = ws_backup_last_run()
        waited = now - last
        # five minutes of slack, so a task that wakes at :30:02 is not pushed a whole hour back
        if last and waited < interval * 3600 - 300:
            due_in = (interval * 3600 - waited) / 3600
            logger.info(f"watashi: the next backup is due in {due_in:.1f} hour(s) (every {interval}h)")
            return {'status': 'skipped', 'reason': 'too early', 'hours_waited': round(waited / 3600, 2)}
    # watashi v12.2.130x: whoever asked, a backup from moments ago is the same backup.
    fresh = ws_recent_backup(now)
    if fresh:
        if not quiet:
            logger.info(f'watashi: {fresh} was written moments ago, so it is kept instead of a second one')
        return {'status': 'ok', 'file': fresh, 'sent': 0, 'pruned': 0, 'reused': True}
    dbdict = hiddify.dump_db_to_dict()
    # watashi v12.2.130: the nightly file carries the sealed outside files too, when
    # the owner has set a passphrase. Without one it stays exactly as before.
    try:
        from hiddifypanel.panel.ws_guard import load_guard
        guard = load_guard()
        sealed = guard.ws_secret_bundle()
        if sealed:
            dbdict['secrets'] = sealed
    except Exception as problem:
        logger.warning(f'watashi: the secrets could not be added to the backup: {problem}')
    # watashi v12.2.130n: tidying up other folders is a courtesy, not a reason to
    # lose the backup of a panel that is about to be updated.
    try:
        ws_adopt_stray_backups()
    except Exception as problem:
        logger.warning(f'watashi: the stray backups could not be collected: {problem}')
    root = ws_backup_root()
    dst = os.path.join(root, f'{datetime.datetime.now().strftime("%Y_%m_%d__%H_%M_%S")}.json')
    try:
        with open(dst, 'w', encoding='utf-8') as fp:
            json.dump(dbdict, fp, indent=2, sort_keys=True, default=str)
    except Exception as problem:
        logger.error(f'watashi: the backup could not be written to {dst}: {problem}')
        return {'status': 'failed', 'reason': str(problem), 'file': dst}
    # watashi v12.2.107: the bare file name used to be printed here as well,
    # one line above the dict. the logger line at the end of this task already
    # carries the path.
    ws_backup_mark_run(now)
    pruned = ws_prune_backups()
    sent = 0
    if hconfig(ConfigEnum.telegram_bot_token):
        from hiddifypanel.panel.user_notifications import ws_ensure_bot
        from hiddifypanel.panel.commercial.telegrambot import bot
        ws_ensure_bot()
        # AdminUser.telegram_id is not None was plain python, always True, never SQL
        for admin in db.session.query(AdminUser).filter(
                AdminUser.mode == AdminMode.super_admin,
                AdminUser.telegram_id.isnot(None),
                AdminUser.telegram_id != 0).all():
            caption = ("Backup \n" + admin_links())
            with open(dst, 'rb') as document:
                try:
                    bot.send_document(admin.telegram_id, document, visible_file_name=os.path.basename(dst), caption=caption[:1000])
                    sent += 1
                except Exception as e:
                    logger.exception(e)
    if not quiet:  # watashi v12.2.130x: the console command prints this itself
        logger.info(f"watashi: a backup was written to {dst}; it went to {sent} admin(s); {pruned} old file(s) removed")
    return {'status': 'ok', 'file': dst, 'sent': sent, 'pruned': pruned}


def all_configs():
    print(json.dumps(hiddify.all_configs_for_cli(), indent=4))


def update_usage():
    print(usage.update_local_usage())


def admin_links():
    server_ip = hutils.network.get_ip_str(4)
    owner = AdminUser.get_super_admin()

    admin_links = f"Not Secure (do not use it - only if others not work):\n   {hiddify.get_account_panel_link(owner, server_ip,is_https=True)}\n"

    domains = Domain.get_domains()
    admin_links += f"Secure:\n"
    if not any([d for d in domains if 'sslip.io' not in d.domain]):
        admin_links += f"   (not signed) {hiddify.get_account_panel_link(owner, server_ip)}\n"

    for d in domains:
        admin_links += f"   {hiddify.get_account_panel_link(owner, d.domain)}\n"

    print(admin_links)
    return admin_links


def admin_path():
    admin = AdminUser.get_super_admin()
    # WTF is the owner and server_id?
    domain = Domain.get_domains()[0]
    print(hiddify.get_account_panel_link(admin, domain, prefere_path_only=True))


def hysteria_domain_port():
    if not hconfig(ConfigEnum.hysteria_enable):
        return
    out = []
    for domain in Domain.query.filter(Domain.mode.in_([DomainType.direct, DomainType.relay, DomainType.fake])).all():
        out.append(f"{domain.domain}:{int(hconfig(ConfigEnum.hysteria_port))+domain.id}")
    print(";".join(out))


def tuic_domain_port():
    if not hconfig(ConfigEnum.tuic_enable):
        return
    out = []
    for domain in Domain.query.filter(Domain.mode.in_([DomainType.direct, DomainType.relay, DomainType.fake])).all():
        out.append(f"{domain}:{int(hconfig(ConfigEnum.tuic_port))+domain.id}")
    print(";".join(out))


def init_app(app):
    for command in [hysteria_domain_port, tuic_domain_port, init_db, drop_db, all_configs, update_usage, admin_links, admin_path, backup, test_notification, downgrade]:
        app.cli.add_command(app.cli.command()(command))

    @ app.cli.command()
    @ click.option("--domain", "-d")
    @ click.option("--mode", "-m")
    def add_domain(domain, mode):
        if Domain.query.filter(Domain.domain == domain).first():
            return "Domain already exist."
        d = Domain()
        d.domain = domain
        d.mode = mode
        d.sub_link_only = True if mode == DomainType.sub_link_only else False
        db.session.add(d)
        db.session.commit()
        return "success"

    @ app.cli.command()
    @ click.option("--admin_secret", "-a")
    def set_admin_secret(admin_secret):
        StrConfig.query.filter(StrConfig.key == ConfigEnum.admin_secret).update({'value': admin_secret})
        db.session.commit()
        return "success"

    @ app.cli.command()
    @ click.option("--key", "-k")
    @ click.option("--val", "-v")
    def set_setting(key, val):
        old_hconfigs = get_hconfigs()
        hiddify.add_or_update_config(key=key, value=val)

        return "success"
    @app.cli.command()
    def reset_owner_password():
        AdminUser.get_super_admin().update_password("")
    @ app.cli.command()
    @ click.option("--config", "-c")
    def import_config(config):
        next10year = datetime.date.today() + relativedelta.relativedelta(years=10)
        data = []
        if "USER_SECRET" in config:
            secrets = config["USER_SECRET"].split(";")
            for i, s in enumerate(secrets):
                data.append(User(name=f"default {i}", uuid=uuid.UUID(s), usage_limit_GB=9000, package_days=3650))

        if "MAIN_DOMAIN" in config:
            domains = config["MAIN_DOMAIN"].split(";")
            for i, d in enumerate(domains):
                if not Domain.query.filter(Domain.domain == d).first():
                    data.append(Domain(domain=d, mode=DomainType.direct),)

        strmap = {
            "TELEGRAM_FAKE_TLS_DOMAIN": ConfigEnum.telegram_fakedomain,
            "TELEGRAM_SECRET": ConfigEnum.shared_secret,
            "SS_FAKE_TLS_DOMAIN": ConfigEnum.ssfaketls_fakedomain,
            "FAKE_CDN_DOMAIN": ConfigEnum.domain_fronting_domain,
            "BASE_PROXY_PATH": ConfigEnum.proxy_path,
            "ADMIN_SECRET": ConfigEnum.admin_secret,
            "TELEGRAM_AD_TAG": ConfigEnum.telegram_adtag
        }
        boolmap = {
            "ENABLE_SS": ConfigEnum.ssfaketls_enable,
            "ENABLE_TELEGRAM": ConfigEnum.telegram_enable,
            "ENABLE_VMESS": ConfigEnum.vmess_enable,
            # "ENABLE_MONITORING":ConfigEnum.ssfaketls_enable,
            "ENABLE_FIREWALL": ConfigEnum.firewall,
            "ENABLE_NETDATA": ConfigEnum.netdata,
            "ENABLE_HTTP_PROXY": ConfigEnum.http_proxy_enable,
            "ALLOW_ALL_SNI_TO_USE_PROXY": ConfigEnum.allow_invalid_sni,
            "ENABLE_AUTO_UPDATE": ConfigEnum.auto_update,
            "ENABLE_SPEED_TEST": ConfigEnum.speed_test,
            "BLOCK_IR_SITES": ConfigEnum.block_iran_sites,
            "ONLY_IPV4": ConfigEnum.only_ipv4
        }

        for k in config:
            if k in strmap:
                if hconfig(strmap[k]) is None:
                    data.append(StrConfig(key=strmap[k], value=config[k]))
                else:
                    StrConfig.query.filter(StrConfig.key == strmap[k]).update({
                        'value': config[k]
                    })
            if k in boolmap:
                if hconfig(boolmap[k]) is None:
                    data.append(BoolConfig(key=boolmap[k], value=config[k]))
                else:
                    BoolConfig.query.filter(BoolConfig.key == strmap[k]).update({
                        'value': config[k]
                    })
        if len(data):
            db.session.bulk_save_objects(data)
        db.session.commit()

    # watashi v12.2.52: two hands for the two bugs the testers found
    WS_HEAL_ON = ('vless_enable', 'vmess_enable', 'trojan_enable', 'ws_enable',
                  'grpc_enable', 'tcp_enable', 'h2_enable', 'xhttp_enable',
                  'httpupgrade_enable', 'quic_enable', 'reality_enable')

    @ app.cli.command('unlock-login')
    @ click.option('--who', default='', help='an account name or uuid, empty means everybody')
    @ click.option('--ip', default='', help='deprecated: the lock no longer sits on the visitor')
    def unlock_login(who, ip):
        """Opens the doors the wrong password lock has shut."""
        import hashlib
        from hiddifypanel.cache import redis_client
        name = (who or '').strip().lower()
        if name:
            shape = 'watashi:door:acct:%s*' % hashlib.sha256(name.encode('utf-8', 'ignore')).hexdigest()[:16]
        else:
            # watashi v12.2.60: every shape this lock has ever written, so one
            # command also clears the leftovers of the old per visitor keys
            shape = 'watashi:door:*'
        gone = 0
        try:
            for key in redis_client.scan_iter(match=shape, count=500):
                redis_client.delete(key)
                gone += 1
        except Exception as problem:
            print('could not reach redis: %s' % problem)
            return
        if ip:
            print('the --ip option does nothing now: the lock sits on the account')
        print('opened %d door keys for %s' % (gone, name or 'everybody'))

    @ app.cli.command('sub-doctor')
    @ click.option('--uuid', '-u', default='')
    @ click.option('--fix', is_flag=True, default=False)
    def sub_doctor(uuid, fix):
        """Explains, line by line, why a subscription link carries no config."""
        from flask import g
        from hiddifypanel.hutils.proxy.shared import ws_sub_reasons
        want = (uuid or '').strip()
        user = User.by_uuid(want) if want else User.query.first()
        if not user:
            print('no such user: %s' % (want or '(the table is empty)'))
            return
        print('user            : %s (%s)' % (user.name, user.uuid))
        print('enabled         : %s' % user.enable)
        print('usage           : %.3f of %.3f GB' % (user.current_usage_GB or 0, user.usage_limit_GB or 0))
        print('days left       : %s of %s' % (user.remaining_days, user.package_days))
        print('is_active       : %s' % user.is_active)
        if not user.is_active:
            print('  >> the link carries the ended package config only, which is the')
            print('     panel working as designed, not the empty link bug.')
        child = Child.current().id
        cfgs = get_hconfigs(child)
        switches = [k for k in ConfigEnum if k.type == bool and k.name.endswith('_enable')]
        missing = [k for k in switches if k not in cfgs]
        print('child           : %s' % child)
        print('switch keys     : %d, missing from the database: %d' % (len(switches), len(missing)))
        for key in missing:
            print('   ? %s' % key.name)
        if missing and not fix:
            print('  >> a missing switch reads as off, and get_proxies() then drops every')
            print('     proxy that needs it. Run again with --fix to write the safe')
            print('     defaults for the ones a working panel cannot live without.')
        if fix:
            healed = []
            for key in missing:
                if key.name in WS_HEAL_ON:
                    set_hconfig(key, True, child, commit=False)
                    healed.append(key.name)
            db.session.commit()
            print('wrote defaults  : %s' % (', '.join(healed) or 'nothing needed'))
        with app.test_request_context('/'):
            g.account = user
            g.user_agent = {'is_browser': False}
            rows = Proxy.query.filter(Proxy.child_id == child).count()
            kept = hutils.proxy.get_proxies(child, only_enabled=True)
            domains = Domain.query.filter(Domain.child_id == child).all()
            print('proxy rows      : %d, left after the switches: %d' % (rows, len(kept)))
            print('domains         : %d' % len(domains))
            for dom in domains[:20]:
                print('   - %-40s mode=%s' % (dom.domain, dom.mode))
            links = hutils.proxy.get_valid_proxies(domains)
            print('configs in link : %d' % len(links))
            for reason, count in sorted(ws_sub_reasons().items(), key=lambda pair: -pair[1])[:12]:
                print('   x %-46s %d' % (reason, count))
            if not links:
                print('  >> the line above with the biggest number is the answer.')

    @ app.cli.command()
    @ click.option("--xui_db_path", "-x")
    def xui_importer(xui_db_path):
        try:
            hutils.importer.xui.import_data(xui_db_path)
            print('success')
        except Exception as e:
            print(f'failed to import xui data: Error: {e}')

    @ app.cli.command()
    def tgbot_info():
        if not hconfig(ConfigEnum.telegram_bot_token):
            print('You didn\'t specified your telegram bot token')
            return

        from hiddifypanel.panel.commercial.telegrambot import bot, register_bot
        if not bot.username:
            register_bot(True)
        info = bot.get_me().to_dict()
        hook_data = bot.get_webhook_info()
        hook_info = {
            'url': hook_data.url,
            'ip': hook_data.ip_address,
            'last_error_msg': hook_data.last_error_message if hook_data.last_error_message else '',
            'last_error_time': datetime.datetime.fromtimestamp(int(hook_data.last_error_date)).strftime('%Y-%m-%d %H:%M:%S') if hook_data.last_error_date else ''
        }

        output = {
            'general': info,
            'webhook': hook_info
        }
        print(json.dumps(output, indent=4))
