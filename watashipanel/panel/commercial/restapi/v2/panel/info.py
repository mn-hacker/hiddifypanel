# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask.views import MethodView
from flask import current_app as app

from watashipanel.auth import login_required
from watashipanel.models import Role
from watashipanel import __version__

from .schema import PanelInfoOutputSchema


class PanelInfoApi(MethodView):
    decorators = [login_required(roles={Role.super_admin, Role.admin, Role.agent}, node_auth=True)]

    @app.output(PanelInfoOutputSchema)  # type: ignore
    def get(self):
        res = PanelInfoOutputSchema()
        res.version = __version__  # type: ignore
        return res
