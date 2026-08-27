import os
import xtlsapi
from hiddifypanel.models import *
from .abstract_driver import DriverABS
from flask import current_app
import json
from collections import defaultdict
from hiddifypanel.cache import cache
from loguru import logger


class SingboxApi(DriverABS):
    def is_enabled(self) -> bool: return True

    def get_singbox_client(self):
        return xtlsapi.SingboxClient('127.0.0.1', 10086)

    def get_enabled_users(self):
        # watashi v12.2.47: this file is rewritten by apply-users, so a read can
        # land on a missing or half written file. That used to raise on every
        # poll; an unknown list is answered as empty instead, and the bare uuid
        # spelling (naive, mieru) maps onto the same user as uuid@hiddify.com.
        config_dir = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager')
        path = f"{config_dir}/singbox/configs/01_api.json"
        try:
            with open(path) as f:
                json_data = json.load(f)
            names = json_data['experimental']['v2ray_api']['stats']['users']
        except FileNotFoundError:
            logger.debug(f"singbox: {path} does not exist yet")
            return {}
        except Exception as e:
            logger.warning(f"singbox: cannot read {path} ({e})")
            return {}
        return {str(n).split("@")[0]: 1 for n in names if str(n).strip()}

    @cache.cache(ttl=300)
    def get_inbound_tags(self):
        try:
            xray_client = self.get_singbox_client()
            inbounds = [inb.name.split(">>>")[1] for inb in xray_client.stats_query('inbound')]
            # print(f"Success in get inbound tags {inbounds}")
        except Exception as e:
            print(f"error in get inbound tags {e}")
            inbounds = []
        return list(set(inbounds))

    def _ws_queue(self, action, user):
        # watashi v12.2.47: sing-box has no live user management. Its V2Ray API
        # is StatsService only (GetStats/QueryStats/GetSysStats), so a user can
        # be added or cut off only by rebuilding the configs and reloading the
        # service, which is what hiddify.quick_apply_users() does. We record the
        # request here so the log shows why the change is not instant, and so a
        # later round can rebuild only what changed.
        uuid = getattr(user, 'uuid', user)
        try:
            key = f"ws:singbox:pending-{action}"
            cache.redis_client.sadd(key, str(uuid))
            cache.redis_client.expire(key, 3600)
        except Exception:
            pass
        logger.info(f"singbox: {action} {uuid} queued; sing-box needs a config rebuild to apply it")

    def add_client(self, user):
        self._ws_queue('add', user)

    def remove_client(self, user):
        self._ws_queue('remove', user)

    def get_all_usage(self, reset: bool = True):
        # watashi v12.2.47: reset=False lets a caller read the counters
        # without draining them. The usage task still drains, as it must.
        xray_client = self.get_singbox_client()
        usages = xray_client.stats_query('user', reset=reset)
        
        res = defaultdict(int)
        for use in usages:
            if "user>>>" not in use.name:
                continue
            # print(use.name, use.value)
            uuid = use.name.split(">>>")[1].split("@")[0]
            res[uuid] += use.value  # uplink + downlink
        return res
        # return {u: self.get_usage_imp(u.uuid) for u in users}

    def get_usage_imp(self, uuid):
        xray_client = self.get_singbox_client()
        d = xray_client.get_client_download_traffic(f'{uuid}@hiddify.com', reset=True)
        u = xray_client.get_client_upload_traffic(f'{uuid}@hiddify.com', reset=True)

        res = None
        if d is None:
            res = u
        elif u is None:
            res = d
        else:
            res = d + u
        if res:
            logger.debug(f"singbox {uuid} d={d} u={u} sum={res}")
        return res
