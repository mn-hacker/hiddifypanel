
from celery import shared_task
from sqlalchemy import func
from typing import Dict
import datetime

from hiddifypanel.drivers import user_driver
from hiddifypanel.models import *
from hiddifypanel.panel import hiddify
from hiddifypanel.database import db, db_execute, text
from hiddifypanel import cache, hutils
from loguru import logger
import json
to_gig_d = 1024**3

# ------------------------------------------------------------ watashi v12.2.47
# get_users_usage() drains the cores, and draining resets their counters. From
# that moment the only copy of those bytes lives in this process, so a failed
# database write used to throw them away: the user kept browsing and the panel
# never learned about the traffic. Every drained batch is written to a small
# redis journal first and cleared only after the database has taken it.
WS_PENDING_KEY = "ws:usage:pending"
WS_LAST_RUN_KEY = "ws:usage:last-run"
WS_APPLY_KEY = "ws:usage:apply-users"
WS_DEFAULT_INTERVAL = 30
_ws_mem_pending: Dict[str, int] = {}


def ws_usage_interval() -> int:
    """Seconds between two usage polls. Owner configurable, clamped to 10..600."""
    try:
        value = int(hconfig(ConfigEnum.usage_update_interval) or WS_DEFAULT_INTERVAL)
    except Exception:
        value = WS_DEFAULT_INTERVAL
    return min(600, max(10, value))


def ws_load_pending() -> Dict[str, int]:
    """Bytes drained by an earlier run that the database has not taken yet."""
    try:
        raw = cache.redis_client.get(WS_PENDING_KEY)
        if raw:
            return {str(u): int(v) for u, v in json.loads(raw).items() if int(v) > 0}
    except Exception as e:
        logger.warning(f"watashi: cannot read the usage journal ({e}); using the in-process copy")
        return dict(_ws_mem_pending)
    return {}


def ws_save_pending(pending: Dict[str, int]) -> None:
    _ws_mem_pending.clear()
    _ws_mem_pending.update(pending)
    try:
        if pending:
            cache.redis_client.set(WS_PENDING_KEY, json.dumps(pending))
        else:
            cache.redis_client.delete(WS_PENDING_KEY)
    except Exception as e:
        logger.warning(f"watashi: cannot write the usage journal ({e}); memory copy only")


def ws_apply_users_once(min_gap: int = 20) -> None:
    """apply-users rebuilds every config and reloads the cores, so it must not be
    started twice in the same breath when several users run out together."""
    try:
        if not cache.redis_client.set(WS_APPLY_KEY, "1", nx=True, ex=min_gap):
            logger.info("watashi: apply-users was just started; not starting a second one")
            return
    except Exception:
        pass
    hiddify.quick_apply_users()


@shared_task(ignore_result=True)
def update_local_usage():
    lock_key = "lock-update-local-usage"
    have_lock = True
    try:
        have_lock = bool(cache.redis_client.set(lock_key, "locked", nx=True, ex=max(120, ws_usage_interval() * 4)))
    except Exception as e:
        # a redis hiccup must never stop the accounting, or nobody gets cut off
        logger.warning(f"watashi: the usage lock is unavailable ({e}); running without it")
    if not have_lock:
        return {"msg": "last update task is not finished yet."}
    try:
        return update_local_usage_not_lock()
    except Exception as e:
        logger.exception("Exception in update usage")
        return {"msg": f"Exception in update usage: {e}"}
    finally:
        # watashi v12.2.47: the lock is released here instead of being left
        # behind with a fixed 60s life, which used to block the next run
        # whenever the interval was shorter than that.
        import time as _time
        try:
            cache.redis_client.delete(lock_key)
            cache.redis_client.set(WS_LAST_RUN_KEY, int(_time.time()), ex=86400)
        except Exception:
            pass


def update_local_usage_not_lock():
    # 1. drain the cores; their counters are zero now, so these bytes are only here
    res = user_driver.get_users_usage(reset=True)
    fresh = {uuid: int(uinfo.get("usage") or 0) for uuid, uinfo in res.items() if (uinfo.get("usage") or 0) > 0}

    # 2. add whatever an earlier run drained but could not store
    merged = ws_load_pending()
    for uuid, value in fresh.items():
        merged[uuid] = merged.get(uuid, 0) + value

    # 3. journal first, database second
    if merged:
        ws_save_pending(merged)
        logger.debug(f"watashi: {len(merged)} users and {sum(merged.values())} bytes are waiting for the database")

    stored = {"done": False}

    def _stored():
        stored["done"] = True
        ws_save_pending({})

    result = add_users_usage_new(
        [{"uuid": uuid, "usage": value} for uuid, value in merged.items()],
        child_id=0,
        on_usage_committed=_stored,
    )
    if merged and not stored["done"]:
        logger.error("watashi: the usage was not stored; it stays in the journal for the next run")
    return result


def add_users_usage_uuid(uuids_bytes: Dict[str, Dict], child_id, sync=False):
    uuids_bytes = {u: v for u, v in uuids_bytes.items() if v and v.get('usage', 0) > 0}
    uuids = uuids_bytes.keys()
    users = db.session.query(User).filter(User.uuid.in_(uuids))
    dbusers_bytes = {u: uuids_bytes.get(u.uuid, {"usage": 0}) for u in users}
    _add_users_usage(dbusers_bytes, child_id, sync)  # type: ignore


def _reset_priodic_usage() -> bool:
    apply_changes = False
    last_usage_check: int = hconfig(ConfigEnum.last_priodic_usage_check) or 0
    import time
    current_time = int(time.time())
    if current_time - last_usage_check < 60 * 60 * 6:
        return apply_changes
    # reset as soon as possible in the day
    if datetime.datetime.now().hour > 5 and current_time - last_usage_check < 60 * 60 * 24:
        return apply_changes
    logger.debug("reseting user usage if needed")
    # for user in db.session.query(User).filter(User.mode != UserMode.no_reset).all():
    #     if user.user_should_reset():
    #         logger.info(f"reseting user usage for {user.uuid}")
    #         user.reset_usage(commit=False)

    today = datetime.date.today()

    db_change = False
    for user in db.session.query(User).filter(User.mode != UserMode.no_reset, User.start_date != None, User.start_date+User.package_days >= today).all():
        if user.user_should_reset():
            logger.info(f"reseting user usage for {user.uuid}")
            old_active = user.is_active
            user.reset_usage(commit=False)
            db_change = True

            if not old_active and user.is_active:
                logger.info(f"adding enabled client {user.uuid} ")
                user_driver.add_client(user)
                apply_changes = True
                send_bot_message(user)

    if db_change:
        db.session.commit()

    for user in db.session.query(User).filter(User.start_date != None, User.start_date+User.package_days < today).all():
        logger.info(f"Removing enabled client {user.uuid} ")
        if not user.is_active:
            user_driver.remove_client(user)
            apply_changes = True

    set_hconfig(ConfigEnum.last_priodic_usage_check, current_time, commit=True)
    return apply_changes


def add_users_usage_new(usages: list[dict], child_id, sync=False, on_usage_committed=None):
    usages = [use for use in usages if use['usage'] > 0]
    # usages[0]['usage']=1000000000000
    before_enabled_users = user_driver.get_enabled_users()

    daily_usage = {}
    cur_time=datetime.datetime.now()
    today = cur_time.date()
    db_changes = False
    for adm in db.session.query(AdminUser).all():
        daily_usage[adm.id] = db.session.query(DailyUsage).filter(DailyUsage.date == today, DailyUsage.admin_id == adm.id, DailyUsage.child_id == child_id).first()
        if daily_usage[adm.id] is None:
            logger.info(f"creating a new daily usage {today} admin={adm.id} child={child_id}")
            daily_usage[adm.id] = DailyUsage(date=today, admin_id=adm.id, child_id=child_id, usage=0)
            db.session.add(daily_usage[adm.id])
            db_changes = True
        daily_usage[adm.id].online = db.session.query(User).filter(User.added_by == adm.id).filter(func.DATE(User.last_online) == today).count()
    if db_changes:
        db.session.commit()

    apply_changes = _reset_priodic_usage()
    
    # watashi v12.2.47: nothing to store is not an error, and the journal may be
    # cleared only after the database has really taken the bytes.
    if usages:
        db_execute("CALL add_usage_json(:usage_data,:cur_time)", usage_data=json.dumps(usages),cur_time=cur_time.strftime('%Y-%m-%d %H:%M:%S'), commit=True)
    if on_usage_committed is not None:
        try:
            on_usage_committed()
        except Exception:
            logger.exception("watashi: could not clear the usage journal")

    usage_map = {u['uuid']: u for u in usages}
    
    users = db.session.query(User).filter(User.uuid.in_(set(usage_map.keys()))).all()

    all_users_uuids = set()
    for user in users:
        all_users_uuids.add(user.uuid)

        user_before_active = before_enabled_users.get(user.uuid,False)
        user_active = user.is_active

        if not user_before_active and user_active:
            logger.info(f"Enabling disabled client {user.uuid} ")
            user_driver.add_client(user)
            send_bot_message(user)
            apply_changes = True
        elif user_before_active and not user_active:
            logger.info(f"Removing enabled client {user.uuid} ")
            user_driver.remove_client(user)
            send_bot_message(user)
            apply_changes = True

        daily_usage.get(user.added_by, daily_usage[1]).usage += usage_map[user.uuid]['usage']

    db.session.commit()

    if len(users) != len(usage_map):
        # check for zombie-users
        check_users = set(before_enabled_users.keys())-all_users_uuids
        all_db_users = {u.uuid for u in db.session.query(User).filter(User.uuid.in_(check_users)).all()}
        zombie_users = check_users-all_db_users

        for uuid in zombie_users:
            logger.info(f"Remove zombiee users {uuid} ")
            user_driver.remove_client(User(uuid=uuid))
            apply_changes = True

    # watashi v12.2.47: a user who runs out of quota while idle never shows up
    # in usage_map again, and a cut-off that failed once was never retried. Sweep
    # the core user list against the database so nobody keeps a finished package.
    try:
        core_only = [uuid for uuid, on in before_enabled_users.items() if on and uuid not in all_users_uuids]
        if core_only:
            for user in db.session.query(User).filter(User.uuid.in_(core_only)).all():
                if not user.is_active:
                    logger.info(f"watashi: cutting off {user.uuid}, its package is finished")
                    user_driver.remove_client(user)
                    apply_changes = True
    except Exception:
        logger.exception("watashi: the idle cut-off sweep failed")

    if apply_changes:
        ws_apply_users_once()

    return {"status": 'success', "comments": usages, "date": hutils.convert.time_to_json(cur_time)}


# def _add_users_usage(users_usage_data: Dict[User, Dict], child_id, sync=False):
#     '''
#     sync: when enabled, it means we have received usages from the parent panel
#     '''
#     res = {}
#     have_change = False
#     before_enabled_users = user_driver.get_enabled_users()
#     daily_usage = {}
#     today = datetime.date.today()
#     changes = False
#     for adm in db.session.query(AdminUser).all():
#         daily_usage[adm.id] = db.session.query(DailyUsage).filter(DailyUsage.date == today, DailyUsage.admin_id == adm.id, DailyUsage.child_id == child_id).first()
#         if daily_usage[adm.id] is None:
#             logger.info(f"creating a new daily usage {today} admin={adm.id} child={child_id}")
#             daily_usage[adm.id] = DailyUsage(date=today, admin_id=adm.id, child_id=child_id)
#             db.session.add(daily_usage[adm.id])
#             changes = True
#         daily_usage[adm.id].online = db.session.query(User).filter(User.added_by == adm.id).filter(func.DATE(User.last_online) == today).count()
#     if changes:
#         db.session.commit()
#     _reset_priodic_usage()

#     # userDetails = {p.user_id: p for p in UserDetail.query.filter(UserDetail.child_id == child_id).all()}
#     for user, uinfo in users_usage_data.items():
#         usage_bytes = uinfo['usage']

#         # UserDetails things
#         # detail = UserDetail(user_id=user.id, child_id=child_id)
#         # detail = userDetails.get(user.id)
#         # if not detail:
#         #     detail = UserDetail(user_id=user.id, child_id=child_id)
#         #     db.session.add(detail)
#         # if uinfo['devices'] != detail.connected_devices:
#         #     detail.connected_devices = uinfo['devices']

#         # Enable the user if isn't already
#         if not before_enabled_users[user.uuid] and user.is_active:
#             logger.info(f"Enabling disabled client {user.uuid} ")
#             user_driver.add_client(user)
#             send_bot_message(user)
#             have_change = True

#         # Check if there's new usage value
#         if not isinstance(usage_bytes, int) or usage_bytes == 0:
#             res[user.uuid] = "No usage"
#         else:
#             # Set new daily usage of the user
#             if sync and daily_usage.get(user.added_by, daily_usage[1]).usage != usage_bytes:
#                 daily_usage.get(user.added_by, daily_usage[1]).usage = usage_bytes
#             else:
#                 daily_usage.get(user.added_by, daily_usage[1]).usage += usage_bytes

#             # Set new current usage of the user
#             if sync and user.current_usage != usage_bytes:
#                 user.current_usage = usage_bytes
#                 # detail.current_usage_GB = in_gig
#             else:
#                 user.current_usage += usage_bytes
#                 # detail.current_usage = detail.current_usage or 0
#                 # detail.current_usage += usage_bytes

#             # Change last online time of the user
#             user.last_online = datetime.datetime.now()
#             # detail.last_online = datetime.datetime.now()

#             # Set start date of user to the current datetime if it hasn't been set already
#             if user.start_date is None:
#                 user.start_date = datetime.date.today()

#             res[user.uuid] = f'{usage_bytes/1000000:0.3f}MB'

#         # Remove user from drivers(singbox, xray, wireguard etc.) if they're inactive
#         # print(before_enabled_users[user.uuid], user.is_active)
#         if before_enabled_users[user.uuid] and not user.is_active:
#             logger.info(f"Removing enabled client {user.uuid} ")

#             user_driver.remove_client(user)
#             have_change = True
#             res[user.uuid] = f"{res[user.uuid]} !OUT of USAGE! Client Removed"

#     db.session.commit()  # type: ignore

#     # Remove invalid users
#     for uuid in before_enabled_users:
#         if uuid in res:
#             continue

#         user = db.session.query(User).filter(User.uuid == uuid).first()
#         if not user:
#             user_driver.remove_client(User(uuid=uuid))
#         elif not user.is_active:
#             user_driver.remove_client(user)

#     # print("------------------", res)
#     # Apply the changes to the drivers
#     if have_change:
#         hiddify.quick_apply_users()

#     # Sync the new data with the parent node if the data has not been set by the parent node itself and the current panel is a child panel
#     if not sync and hutils.node.is_child():
#         hutils.node.child.sync_users_usage_with_parent()

#     return {"status": 'success', "comments": res, "date": hutils.convert.time_to_json(datetime.datetime.now())}


def send_bot_message(user):
    if not (hconfig(ConfigEnum.telegram_bot_token) or hutils.node.is_child()):
        return
    if not user.telegram_id:
        return
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    try:
        msg = Usage.get_usage_msg(user.uuid)
        msg = _("User activated!") if user.is_active else _("Package ended!") + "\n" + msg
        bot.send_message(user.telegram_id, msg, reply_markup=Usage.user_keyboard(user.uuid))
    except BaseException:
        pass
