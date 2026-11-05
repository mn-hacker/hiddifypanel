# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask import current_app as app, request
from flask import g
from flask.views import MethodView
from apiflask.fields import Dict
from apiflask import Schema
from watashipanel.models.usage import DailyUsage
from watashipanel.auth import login_required
from watashipanel.models import Role, DailyUsage
from watashipanel.panel import watashi
from watashipanel import hutils


class ServerStatusOutputSchema(Schema):
    stats = Dict(required=True, description="System stats")
    usage_history = Dict(required=True, description="System usage history")


class AdminServerStatusApi(MethodView):
    decorators = [login_required({Role.super_admin, Role.admin, Role.agent})]

    @app.output(ServerStatusOutputSchema)  # type: ignore
    def get(self):
        """System: ServerStatus"""
        dto = ServerStatusOutputSchema()
        dto.stats = {  # type: ignore
            'system': hutils.system.system_stats(),
            'top5': hutils.system.top_processes(),
            'ping': hutils.system.get_network_latency(),
            'protocols': hutils.system.get_protocol_distribution()
        }
        admin_id = request.args.get("admin_id") or g.account.id
        dto.usage_history = DailyUsage.get_daily_usage_stats(admin_id)  # type: ignore
        return dto
