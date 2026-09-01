# watashi: the AmneziaWG usage driver v12.2.64
import json
import os

from .abstract_driver import DriverABS
from hiddifypanel.models import User, hconfig, ConfigEnum
from hiddifypanel.panel.run_commander import Command, commander
import redis
from loguru import logger


# Deliberately not "wg:users-usage". WireguardApi owns that key, and the two
# tunnels hand out the same public key per user, so sharing one snapshot would
# make each driver read the other's counters as its own and hand out huge
# negative deltas the moment either one restarted.
USERS_USAGE = "awg:users-usage"


class AmneziaApi(DriverABS):
    """Traffic accounting for the separate AmneziaWG system of v12.2.62.

    watashi v12.2.64: the native tunnel is run by its own awg-quick unit, on
    the interface named in other/amnezia/awg_utils.sh, so nothing inside the
    sing-box core ever sees a byte of it. Until this driver existed, a user
    riding watashi-awg spent nothing against their quota, for ever.

    WireguardApi is the shape this follows on purpose. One user carries one
    public key across both tunnels, so somebody connected to both is counted
    by both drivers, and that is correct: they are two separate tunnels
    carrying two separate lots of traffic.
    """

    # awg-quick keeps wg-quick's interface naming, and other/amnezia/awg_utils.sh
    # fixes this name for install.sh, run.sh and disable.sh alike. It is stated
    # once here so the driver can never drift away from the shell side.
    NIC = 'watashi-awg'

    def __init__(self) -> None:
        super().__init__()
        self.pub_uuid_map = {}

    def get_redis_client(self):
        if not hasattr(self, 'redis_client'):
            self.redis_client = redis.from_url(os.environ.get("REDIS_URI_SSH", ""))
        return self.redis_client

    def is_enabled(self) -> bool:
        return bool(hconfig(ConfigEnum.amnezia_native_enable))

    def __load_pubkey_uuid_map(self):
        from hiddifypanel.database import db
        users = db.session.query(User).all()
        self.pub_uuid_map = {u.wg_pub: u.uuid for u in users}

    def __convert_pub_key_to_uuid(self, pubkeys):
        res = {}
        can_reload_map = True
        for key in pubkeys:
            if uuid := self.pub_uuid_map.get(key):
                res[key] = uuid
            elif can_reload_map:
                self.__load_pubkey_uuid_map()
                can_reload_map = False
                if uuid := self.pub_uuid_map.get(key):
                    res[key] = uuid
        return res

    def __get_awg_usages(self) -> dict:
        """Read the transfer table of the native interface.

        The columns are the same three that wg prints: public key, bytes
        received by the server, bytes sent by the server. An interface that is
        not up answers with nothing at all, which is not an error here, only an
        empty report.
        """
        raw_output = commander(Command.update_awg_usage, run_in_background=False)
        data = {}
        if not raw_output:
            return data
        for line in raw_output.split('\n'):
            if not line:
                continue
            sections = line.split()
            if len(sections) < 3:
                continue
            try:
                data[sections[0]] = {
                    'down': int(sections[1]),
                    'up': int(sections[2]),
                }
            except ValueError:
                # A header, a warning from awg, anything that is not a counter.
                logger.debug(f'amnezia: skipping an unreadable transfer line: {line!r}')
        return data

    def __get_local_usage(self) -> dict:
        usage_data = self.get_redis_client().get(USERS_USAGE)
        if usage_data:
            return json.loads(usage_data)
        return {}

    def __sync_local_usages(self, reset: bool = True) -> dict:
        local_usage = self.__get_local_usage()
        awg_usage = self.__get_awg_usages()

        res = {}
        # A peer that left the interface has no counter to compare against any
        # more, so its snapshot goes too.
        for local_pub in list(local_usage.keys()):
            if local_pub not in awg_usage:
                del local_usage[local_pub]

        uuid_map = self.__convert_pub_key_to_uuid(awg_usage.keys())
        # The loop variable is not named after the dict it walks. wireguard_api
        # rebinds its own dict here, which happens to survive only because the
        # iterator was already made.
        for pub, usage in awg_usage.items():
            uuid = uuid_map.get(pub)
            if not uuid:
                # A peer nobody in the database owns. Counting it would file
                # the traffic under a null user.
                continue
            if not local_usage.get(pub):
                local_usage[pub] = {"uuid": uuid, "usage": usage}
                continue
            res[uuid] = self.calculate_reset(local_usage[pub]['usage'], usage)
            local_usage[pub] = {"uuid": uuid, "usage": usage}

        # The snapshot write is the thing that consumes traffic, so it has to
        # obey reset or a read-only peek silently eats the delta.
        if reset:
            self.get_redis_client().set(USERS_USAGE, json.dumps(local_usage))

        return res

    def calculate_reset(self, last_usage: dict, current_usage: dict) -> dict:
        res = {
            'up': current_usage['up'] - last_usage['up'],
            'down': current_usage['down'] - last_usage['down'],
        }
        # awg-quick restarting takes the counters back to zero, which would
        # otherwise read as an enormous refund.
        if res['up'] < 0:
            res['up'] = 0
        if res['down'] < 0:
            res['down'] = 0
        return res

    def get_enabled_users(self):
        if not self.is_enabled():
            return {}
        usages = self.__get_awg_usages()
        new_pubs = set(usages.keys())
        old_usages = self.__get_local_usage()
        old_pubs = set(old_usages.keys())
        enabled = {u['uuid']: 1 for u in old_usages.values() if u.get('uuid')}
        not_included = new_pubs - old_pubs
        if not_included:
            users = User.query.filter(User.wg_pub.in_(not_included)).all()
            for u in users:
                enabled[u.uuid] = 1
        return enabled

    def add_client(self, user):
        # other/amnezia/run.sh.j2 writes the whole peer list from scratch on
        # every apply_users, so there is nothing to add one at a time.
        pass

    def remove_client(self, user):
        pass

    def get_all_usage(self, reset=True):
        if not self.is_enabled():
            return {}
        all_usages = self.__sync_local_usages(reset)
        res = {}
        for uuid, use in all_usages.items():
            res[uuid] = use['up'] + use['down']
        return res
