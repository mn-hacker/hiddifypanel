# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
import os
from .abstract_driver import DriverABS
from watashipanel.models import *
import redis

USERS_SET = "ssh-server:users"
USERS_USAGE = "ssh-server:users-usage"
from loguru import logger


class SSHLibertyBridgeApi(DriverABS):
    def is_enabled(self) -> bool:
        return hconfig(ConfigEnum.ssh_server_enable)

    def get_ssh_redis_client(self):
        if not hasattr(self, 'redis_client'):
            self.redis_client = redis.from_url(os.environ.get("REDIS_URI_SSH",""), decode_responses=True)

        return self.redis_client

    def get_enabled_users(self):
        redis_client = self.get_ssh_redis_client()
        members = redis_client.smembers(USERS_SET)
        return {m.split("::")[0]: 1 for m in members}

    def add_client(self, user):
        print(f'Adding SSH {user}')
        redis_client = self.get_ssh_redis_client()
        redis_client.sadd(USERS_SET, f'{user.uuid}::{user.ed25519_public_key}')
        redis_client.save()

    def remove_client(self, user):
        redis_client = self.get_ssh_redis_client()
        if user.ed25519_public_key is None:
            members = redis_client.smembers(USERS_SET)
            for member in members:
                if member.startswith(user.uuid):
                    redis_client.srem(USERS_SET, member)

        redis_client.srem(USERS_SET, f'{user.uuid}::{user.ed25519_public_key}')
        redis_client.hdel(USERS_USAGE, f'{user.uuid}')
        redis_client.save()

    def get_all_usage(self, reset: bool = True) -> dict:
        # watashi: ssh accounting v12.2.56 - three faults lived in the four
        # lines this replaces:
        #  1. this client is built with decode_responses=True, so hgetall
        #     returns strings. drivers/user_driver.py does
        #     res[uuid]['usage'] += usage on an int, so every cycle raised
        #     TypeError and the whole ssh batch was thrown away.
        #  2. delete(USERS_USAGE) also discarded the increments that
        #     ssh-liberty-bridge wrote between hgetall and delete. Only what
        #     was actually read may be drained - which is exactly what
        #     get_usage_imp() below already does with hincrby.
        #  3. there was no 'reset' parameter, so user_driver could not ask
        #     for a read-only peek and every peek drained the counters.
        redis_client = self.get_ssh_redis_client()
        raw = redis_client.hgetall(USERS_USAGE) or {}
        res = {}
        for uuid, value in raw.items():
            try:
                counted = int(value)
            except (TypeError, ValueError):
                logger.warning(f'ssh usage for {uuid} is not a number: {value!r}')
                continue
            if counted <= 0:
                continue
            res[uuid] = counted
            if reset:
                redis_client.hincrby(USERS_USAGE, uuid, -counted)
        if reset and res:
            redis_client.save()
        return res
        # return {u: int(allusage.get(u.uuid) or 0) for u in users}
        # return {u: self.get_usage_imp(u.uuid) for u in users}

    def get_usage_imp(self, client_uuid: str, reset: bool = True) -> int:
        redis_client = self.get_ssh_redis_client()
        value = redis_client.hget(USERS_USAGE, client_uuid)

        if value is None:
            return 0

        value = int(value)

        if reset:
            redis_client.hincrby(USERS_USAGE, client_uuid, -value)
            redis_client.save()
        if value:
            logger.debug(f'ssh usage {client_uuid} {value}')
        return value
