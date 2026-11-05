# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from apiflask import abort
from flask.views import MethodView
from flask_babel import lazy_gettext as _
from flask import g
from loguru import logger

from watashipanel.models.child import Child
from watashipanel.auth import login_required
from watashipanel import hutils


class SyncWithParentApi(MethodView):
    decorators = [login_required(node_auth=True)]

    def post(self):
        logger.info(f"Syncing panel with parent called by {Child.node.unique_id}")
        if not hutils.node.child.sync_with_parent():
            logger.error("Sync with parent failed")
            abort(400, _('child.sync-failed'))  # type: ignore
        logger.success(f"Synced panel with parent {Child.node.unique_id}")
        return {'status': 200, 'msg': 'ok'}
