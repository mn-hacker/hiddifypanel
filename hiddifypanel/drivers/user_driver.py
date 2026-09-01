from .ssh_liberty_bridge_api import SSHLibertyBridgeApi
from .xray_api import XrayApi
from .singbox_api import SingboxApi
from .wireguard_api import WireguardApi
from .amnezia_api import AmneziaApi  # watashi v12.2.64
from hiddifypanel.models import *
from hiddifypanel.panel import hiddify
from collections import defaultdict
from loguru import logger

drivers = [XrayApi(), SingboxApi(), SSHLibertyBridgeApi(), WireguardApi(), AmneziaApi()]  # watashi v12.2.64


def enabled_drivers():
    return [d for d in drivers if d.is_enabled()]


def ws_call_get_all_usage(driver, reset: bool):
    """Ask a driver for its counters, honouring reset when it can.

    watashi v12.2.47: reset used to stop right here, so every driver always
    drained. Drivers that declare the argument get it; the rest keep draining,
    which is what the panel wants anyway, and we say so in the log.
    """
    import inspect
    try:
        if 'reset' in inspect.signature(driver.get_all_usage).parameters:
            return driver.get_all_usage(reset=reset)
    except (TypeError, ValueError):
        pass
    if not reset:
        logger.debug(f'{driver.__class__.__name__} cannot read its counters without resetting them')
    return driver.get_all_usage()


def get_users_usage(reset=True):
    res = {}
    from hiddifypanel.database import db

    # users = db.session.query(User).all()
    # users = list(User.query.all())
    res = defaultdict(lambda: {'usage': 0, 'devices': ''})
    for driver in enabled_drivers():
        try:
            all_usage = ws_call_get_all_usage(driver, reset)
            for uuid, usage in all_usage.items():
                # print(f"{driver.__class__.__name__} {uuid} usage={usage}")
                # watashi: type hardening v12.2.56 - a driver that answers
                # with a string (redis does) used to raise TypeError here and
                # take the whole batch down with it. One bad value is skipped
                # and named instead.
                if not usage:
                    continue
                try:
                    res[uuid]['usage'] += int(usage)
                except (TypeError, ValueError):
                    logger.warning(f'{driver.__class__.__name__} reported a non-numeric usage for {uuid}: {usage!r}')
                    continue
                # res[user]['devices'] +=usage
        except Exception as e:
            print(driver)
            hiddify.error(f'ERROR! {driver.__class__.__name__} has error in update usage {e}')
            logger.exception(f'ERROR! {driver.__class__.__name__} has error in update usage {e}')
    return res


def get_enabled_users():
    from collections import defaultdict
    d = defaultdict(int)
    total = 0
    for driver in enabled_drivers():
        try:
            for u, v in driver.get_enabled_users().items():
                # print(u, "enabled", v, driver)
                if not v:
                    continue
                d[u] += 1
            total += 1
        except Exception as e:
            print(driver)
            hiddify.error(f'ERROR! {driver.__class__.__name__} has error in get_enabled users {e}')
            logger.exception(f'ERROR! {driver.__class__.__name__} has error in get_enabled users {e}')
    # print(d, total)
    res = defaultdict(bool)
    for u, v in d.items():
        # res[u] = v >= total  # ignore singbox
        res[u] = v >= 1
    return res


def add_client(user: User):
    for driver in enabled_drivers():
        try:
            driver.add_client(user)
        except Exception as e:
            hiddify.error(f'ERROR! {driver.__class__.__name__} has error {e} in add client for user={user.uuid} {e}')
            logger.exception(f'ERROR! {driver.__class__.__name__} has error {e} in add client for user={user.uuid} {e}')


def remove_client(user: User):
    for driver in enabled_drivers():
        try:
            driver.remove_client(user)
        except Exception as e:
            hiddify.error(f'ERROR! {driver.__class__.__name__} has error {e} in remove client for user={user.uuid}')
            logger.exception(f'ERROR! {driver.__class__.__name__} has error {e} in remove client for user={user.uuid}')


def get_user_ips(uuid: str) -> set:
    """The IP based limiter was removed, so there is nothing to report.

    watashi v12.2.47: the ~25 lines of unreachable code that used to sit after
    the return were deleted. Callers already treat an empty set as unknown.
    """
    return set()


def is_user_online(uuid: str) -> bool:
    """
    Check if a user is currently online (has active connections).
    Uses get_enabled_users which checks with xray/singbox.
    """
    try:
        enabled = get_enabled_users()
        return enabled.get(uuid, False)
    except Exception as e:
        logger.debug(f"Error checking online status for {uuid}: {e}")
        return False

