# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask.views import MethodView
from apiflask import Schema, abort
from flask import g
from flask import current_app as app
from apiflask.fields import String
from watashipanel.auth import login_required

from watashipanel.models.config import get_hconfigs, hconfig
from watashipanel.models.config_enum import ConfigEnum
from watashipanel.models.domain import DomainType
from watashipanel.models.role import Role

from watashipanel.panel.user.user import get_common_data


class MtproxySchema(Schema):
    link = String(required=True)
    title = String(required=True)


class MTProxiesAPI(MethodView):
    decorators = [login_required({Role.user})]

    @app.output(MtproxySchema(many=True))
    def get(self):
        c = get_common_data(g.account.uuid, 'new')

        if not c['telegram_enable']:
            abort(status_code=404, message="Telegram mtproxy is not enable")

        dtos = []
        # TODO: Remove duplicated domains mapped to a same ipv4 and v6
        for d in c['domains']:
            if d.mode not in [DomainType.direct, DomainType.relay, DomainType.old_xtls_direct]:
                continue

            # make mtproxy link
            raw_sec = hconfig(ConfigEnum.shared_secret, d.child_id)
            secret_hex = str(raw_sec).replace('-', '')
            telegram_faketls_domain_hex = hconfig(ConfigEnum.telegram_fakedomain, d.child_id).encode('utf-8').hex()
            server_link = f'tg://proxy?server={d.domain}&port=443&secret=ee{secret_hex}{telegram_faketls_domain_hex}'

            dto = MtproxySchema()
            dto.title = d.alias or d.domain
            dto.link = server_link
            dtos.append(dto)
        return dtos
