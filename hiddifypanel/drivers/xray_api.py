import xtlsapi
from hiddifypanel.models import *
from .abstract_driver import DriverABS
from collections import defaultdict
from hiddifypanel.cache import cache
from loguru import logger


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
        #         xray_client.add_client(t, f'{uuid}', f'{uuid}@hiddify.com', protocol=protocol, flow='xtls-rprx-vision', alter_id=0, cipher='chacha20_poly1305')
        #         xray_client.remove_client(t, f'{uuid}@hiddify.com')
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
        #     xray_client.add_client(t, f'{uuid}', f'{uuid}@hiddify.com', protocol=protocol, flow='\0',)
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
        xray_client.add_client(t, f'{uuid}', f'{uuid}@hiddify.com', protocol=protocol, flow=flow, alter_id=0, cipher=cipher)

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
                xray_client.remove_client(t, f'{uuid}@hiddify.com')
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

    def get_usage_imp(self, uuid):
        xray_client = self.get_xray_client()
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
            logger.debug(f"Xray usage {uuid} d={d} u={u} sum={res}")
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
                users= [splt[0] for splt in [u.get('email','').split("@") for u in data.get('users',[])] if len(splt)==2 and splt[1]=="hiddify.com"]
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