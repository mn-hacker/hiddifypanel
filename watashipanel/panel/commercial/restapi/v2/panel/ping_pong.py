# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask.views import MethodView

from watashipanel.auth import login_required
from watashipanel.models import Role
from .schema import PongOutputSchema
from flask import current_app as app


class PingPongApi(MethodView):
    decorators = [login_required(roles={Role.super_admin, Role.admin, Role.agent}, node_auth=True)]

    @app.output(PongOutputSchema)  # type: ignore
    def get(self):
        """Ping Pong: Get"""
        return {'msg': 'GET: PONG'}

    @app.output(PongOutputSchema)  # type: ignore
    def post(self):
        """Ping Pong: Post"""
        return {'msg': 'POST: PONG'}

    @app.output(PongOutputSchema)  # type: ignore
    def patch(self):
        """Ping Pong: Patch"""
        return {'msg': 'PATCH: PONG'}

    @app.output(PongOutputSchema)  # type: ignore
    def delete(self):
        """Ping Pong: Delete"""
        return {'msg': 'DELETE: PONG'}

    @app.output(PongOutputSchema)  # type: ignore
    def put(self):
        """Ping Pong: Put"""
        return {'msg': 'PUT: PONG'}
