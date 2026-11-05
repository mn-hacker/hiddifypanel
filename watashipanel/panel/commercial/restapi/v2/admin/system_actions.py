# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
import asyncio
import time
from flask import current_app as app, request
from flask import g
from flask.views import MethodView
from apiflask.fields import Dict
from apiflask import Schema
from watashipanel.models.usage import DailyUsage
from watashipanel.auth import login_required
from watashipanel.models import Role, DailyUsage
from watashipanel.panel import watashi, usage
from watashipanel import hutils
import json


class UpdateUserUsageApi(MethodView):
    decorators = [login_required({Role.super_admin})]

    def get(self):
        """System: Update User Usage"""
        # time.sleep(5)
        
        return json.dumps(usage.update_local_usage_not_lock(), indent=2)


class AllConfigsApi(MethodView):
    decorators = [login_required({Role.super_admin})]

    def get(self):
        """System: All Configs for configuration"""
        return json.dumps(watashi.all_configs_for_cli(), indent=2)
