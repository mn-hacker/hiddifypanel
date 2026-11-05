# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
import xtlsapi
from watashipanel.models import *
from .abstract_driver import DriverABS
from collections import defaultdict
from watashipanel.cache import cache
from loguru import logger


def ws_add_trojan(xray_client, tag: str, password: str, email: str):
    """watashi v12.3.41dev: a trojan user, added while xray runs.

    xtlsapi hands every trojan account a flow, a field the trojan account of
    xray does not have, so protobuf refused the account before anything was
    sent. That refusal is a ValueError, which add_client below reads as "this
    tag is not ours", so no trojan inbound ever got a user while xray ran,
    neither the panel's own nor one built on the Inbounds page; the user only
    appeared at the next apply. This is the same request without the flow.
    """
    from grpc._channel import _InactiveRpcError
    from xtlsapi import exceptions
    from xtlsapi.ext import utils
    from xtlsapi.xray_api.app.proxyman.command import command_pb2
    from xtlsapi.xray_api.common.protocol import user_pb2
    from xtlsapi.xray_api.proxy.trojan import config_pb2
    account = utils.to_typed_message(config_pb2.Account(password=password))
    operation = command_pb2.AddUserOperation(user=user_pb2.User(email=email, level=0, account=account))
    try:
        xray_client.handler_stub.AlterInbound(
            command_pb2.AlterInboundRequest(tag=tag, operation=utils.to_typed_message(operation)))
    except _InactiveRpcError as e:
        details = e.details()
        if details.endswith(f"User {email} already exists."):
            raise exceptions.EmailAlreadyExists(details, email)
        if details.endswith(f"handler not found: {tag}"):
            raise exceptions.InboundNotFound(details, tag)
        raise exceptions.XRayException(details)


class XrayApi(DriverABS):
    def is_enabled(self) -> bool:
        return hconfig(ConfigEnum.core_type) == "xray"

    def get_xray_client(self):
        if not hasattr(self, 'xray_client'):
            self.xray_client = xtlsapi.XrayClient('127.0.0.1', 10085)
        return self.xray_client

    def get_enabled_users(self):
        return {u:1 for u in self.get_enabled_users_terminal()}
        # xray_client = self.get_xray_client()
        # usages = xray_client.stats_query('user', reset=True)
        # res = defaultdict(int)
        # tags = set(self.get_inbound_tags())
        # for use in usages:
        #     if "user>>>" not in use.name:
        #         continue
        #     uuid = use.name.split(">>>")[1].split("@")[0]
        #     res[uuid]=1

        #     #TODO use xtls api
        #     for t in tags.copy():
        #         try:
        #             self.__add_uuid_to_tag(uuid, t)
        #             self._remove_client(uuid, [t], False)
        #             # print(f"Success add  {uuid} {t}")
        #             res[uuid] = 0
        #             break
        #         except ValueError:
        #             # tag invalid
        #             tags.remove(t)
        #             pass
        #         except xtlsapi.xtlsapi.exceptions.EmailAlreadyExists as e:
        #             res[uuid] = 1
        #             break
        #         except Exception as e:
        #             print(f"error {e}")
        #             # res[uuid] = 1
        #             break

        # return res

        # xray_client = self.get_xray_client()
        # users = User.query.all() # t = "xtls"
        # protocol = "vless"
        # enabled = {}
        # for u in users:
        #     uuid = u.uuid
        #     try:
        #         xray_client.add_client(t, f'{uuid}', f'{uuid}@watashi.cyou', protocol=protocol, flow='xtls-rprx-vision', alter_id=0, cipher='chacha20_poly1305')
        #         xray_client.remove_client(t, f'{uuid}@watashi.cyou')
        #         enabled[uuid] = 0
        #     except xtlsapi.xtlsapi.exceptions.EmailAlreadyExists as e:
        #         enabled[uuid] = 1
        #     except Exception as e:
        #         print(f"error {e}")
        #         enabled[uuid] = e
        # return enabled

    # @cache.cache(ttl=300)
    # watashi v12.2.130bi: this is the list every add and every remove walks
    # over, and it was allowed to come back empty without a word. When the
    # xray api hiccups, remove_client then loops over nothing, removes
    # nothing, raises nothing and logs nothing - the panel believes the user
    # was cut off while the running core still lets them in. xray is also the
    # one core that apply_users never re-renders (install.sh only re-applies
    # sing-box, mieru and ssfaketls on that path), so nothing later corrects
    # it either. The last list that did work is kept and reused, and an empty
    # answer is now said out loud.
    _ws_last_tags: list = []

    def get_inbound_tags(self):
        try:
            xray_client = self.get_xray_client()
            inbounds = {inb.name.split(">>>")[1] for inb in xray_client.stats_query('inbound')}
        except Exception as e:
            logger.warning(f'xray: cannot read the inbound list ({e})')
            inbounds = set()
        if inbounds:
            XrayApi._ws_last_tags = sorted(inbounds)
        elif XrayApi._ws_last_tags:
            logger.warning('xray: the inbound list came back empty; using the last one that worked')
            return list(XrayApi._ws_last_tags)
        else:
            logger.error('xray: no inbound is known, so adding and removing users does nothing right now')
        return list(inbounds)

    def __add_uuid_to_tag(self, uuid, t):
        xray_client = self.get_xray_client()
        # watashi v12.3.41dev: an inbound built by hand on the Inbounds page is
        # tagged custom-<id>, a name that matches none of the words below on
        # purpose. Its protocol, flow and cipher come from its own row, so a
        # user added while xray runs looks exactly like the template wrote it.
        if str(t).startswith('custom-'):
            from watashipanel.hutils.proxy.custom import ws_api_cipher_of, ws_email
            known = ws_api_cipher_of(t)
            if not known:
                raise ValueError("unknown custom inbound")
            protocol, flow, cipher = known
            if protocol == 'trojan':
                ws_add_trojan(xray_client, t, f'{uuid}', ws_email(uuid))
                return
            xray_client.add_client(t, f'{uuid}', ws_email(uuid), protocol=protocol, flow=flow, alter_id=0, cipher=cipher)
            return
        proto_map = {
            'vless': 'vless',
            'realityin': 'vless',
            'xtls': 'vless',
            'quic': 'vless',
            'trojan': 'trojan',
            'vmess': 'vmess',
            'ss': 'shadowsocks',
            'v2ray': 'shadowsocks',
            'kcp': 'vless',
            'dispatcher': 'trojan',
            'reality': 'vless'
        }

        def proto(t):
            res = '', ''
            for p, protocol in proto_map.items():
                if p in t:
                    res = p, protocol
                    break
            return res
        p, protocol = proto(t)
        if not p:
            raise ValueError("incorrect tag")
        flow='xtls-rprx-vision' if 'realityin_tcp' in t else '\0'
        # if (protocol == "vless" and p != "xtls" and p != "realityin") or "realityingrpc" in t:
        #     xray_client.add_client(t, f'{uuid}', f'{uuid}@watashi.cyou', protocol=protocol, flow='\0',)
        # else:
        # watashi v12.2.74: every shadowsocks tag was handed the cipher
        # chacha20_poly1305, while SettingAdmin.py:564 and init_db.py:747 both
        # set shadowsocks2022_method to 2022-blake3-aes-256-gcm. xray refused
        # the client, and the refusal was thrown away by the empty except in
        # add_client below, so the user never appeared in the running core and
        # nothing anywhere said why. The configured method is used now.
        cipher = 'chacha20_poly1305'
        if protocol == 'shadowsocks':
            cipher = hconfig(ConfigEnum.shadowsocks2022_method) or cipher
        if protocol == 'trojan':  # watashi v12.3.41dev: see ws_add_trojan
            ws_add_trojan(xray_client, t, f'{uuid}', f'{uuid}@watashi.cyou')
            return
        xray_client.add_client(t, f'{uuid}', f'{uuid}@watashi.cyou', protocol=protocol, flow=flow, alter_id=0, cipher=cipher)

    def add_client(self, user):
        uuid = user.uuid
        xray_client = self.get_xray_client()
        tags = self.get_inbound_tags()

        for t in tags:
            try:
                self.__add_uuid_to_tag(uuid, t)
                # print(f"Success add  {uuid} {t}")
            except ValueError:
                # tag invalid
                pass
            except Exception as e:
                # watashi v12.2.74: this was a bare pass with its log commented
                # out, so a client xray refused was completely invisible. A
                # shadowsocks user could be missing from the running core for
                # days with nothing in the journal to show it. sing-box is
                # already honest about this in singbox_api._ws_queue.
                logger.warning(f'xray: refused client {uuid} on {t} ({e}); this inbound carries the user only after a config rebuild')

    def remove_client(self, user):
        return self._remove_client(user.uuid)

    def _remove_client(self, uuid, tags=None, dolog=True):
        xray_client = self.get_xray_client()
        tags = tags or self.get_inbound_tags()
        # watashi v12.2.130bi: silence here used to read like success.
        if not tags and dolog:
            logger.error(f'xray: {uuid} was NOT removed, there is no inbound to remove it from')

        for t in tags:
            try:
                # watashi v12.3.41dev: the users of a hand built inbound carry the
                # label of hutils.proxy.custom.ws_email.
                email = f'{uuid}@custom.watashi.cyou' if str(t).startswith('custom-') else f'{uuid}@watashi.cyou'
                xray_client.remove_client(t, email)
                # if dolog:
                #     logger.info(f"Success remove  {uuid} {t}")
            except Exception as e:
                if dolog:
                    logger.info(f"error in remove  {uuid} {t} {e}")
                pass

    def get_all_usage(self, reset: bool = True) -> dict:
        # watashi: reset pass-through v12.2.55 - user_driver.py checks for a
        # 'reset' parameter before asking. Without it every read drained the
        # xray counters, so a reset=False peek destroyed the very bytes it
        # reported and the panel under-charged the user.
        xray_client = self.get_xray_client()
        usages = xray_client.stats_query('user', reset=reset)
        # uuid_user_map = {u.uuid: u for u in users}
        res = defaultdict(int)
        for use in usages:
            if "user>>>" not in use.name:
                continue
            uuid = use.name.split(">>>")[1].split("@")[0]
            # if u := uuid_user_map.get(uuid):
            res[uuid] += use.value
            # else:
            #     self._remove_client(uuid)
        return res

    def get_usage_imp(self, uuid, reset: bool = True):
        # watashi v12.3.41dev: reset is a choice now, and the label of the hand
        # built inbounds is counted as well. The live log of the Monitoring page
        # read this with a reset, so merely opening it wiped the traffic the
        # next usage run should have charged to the user.
        xray_client = self.get_xray_client()
        res = None
        for email in (f'{uuid}@watashi.cyou', f'{uuid}@custom.watashi.cyou'):
            d = xray_client.get_client_download_traffic(email, reset=reset)
            u = xray_client.get_client_upload_traffic(email, reset=reset)
            for part in (d, u):
                if part is not None:
                    res = (res or 0) + part
        if res:
            logger.debug(f"Xray usage {uuid} sum={res}")
        return res




    def get_enabled_users_terminal(self):
        import subprocess
        import json
        tags=self.get_inbound_tags()
        found = set()
        for t in tags:
        # Command to execute
            cmd = [
                'xray',
                'api',
                'inbounduser',
                '--server=127.0.0.1:10085',
                f'-tag={t}'
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)

                # Parse JSON output
                data = json.loads(result.stdout)
                # watashi v12.3.40dev: users are labelled uuid@watashi.cyou now. The
                # label of the release before the rename is still read, because
                # while a server is moved over its old xray keeps serving with
                # the old labels until the new one replaces it.
                # watashi v12.3.41dev: and the label of the hand built inbounds.
                users= [splt[0] for splt in [u.get('email','').split("@") for u in data.get('users',[])] if len(splt)==2 and splt[1] in ("watashi.cyou", "hiddify.com", "custom.watashi.cyou")]
                # watashi v12.2.130bi: this used to return at the first tag
                # that answered, so the panel's picture of "who is in the
                # core" was one inbound wide. A user sitting on an inbound
                # that was never asked about counted as absent, and the
                # "was enabled, is not active any more" branch in usage.py,
                # which is what cuts a finished package off, never fired for
                # them. Every inbound is asked now.
                found.update(users)

            except subprocess.CalledProcessError as e:
                logger.warning(f'xray: cannot list the users of {t} ({e.stderr or e})')
            except json.JSONDecodeError as e:
                logger.warning(f'xray: the user list of {t} is not json ({e})')
        return sorted(found)