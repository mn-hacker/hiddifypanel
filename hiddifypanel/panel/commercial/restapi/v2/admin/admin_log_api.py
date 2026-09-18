from apiflask import Schema, fields, abort
from flask.views import MethodView
from hiddifypanel import hutils
from hiddifypanel.models.role import Role
from flask import current_app as app, make_response, g, request
import os
from ansi2html import Ansi2HTMLConverter
from hiddifypanel.auth import login_required
from hiddifypanel.models import *


class AdminInputLogfileSchema(Schema):
    file = fields.String(description="The log file name", required=True)
    domain = fields.String(description="Domain", required=False)

class AdminInputLogfileSchemaGet(Schema):
    file = fields.String(description="The log file name", required=True)
    domain = fields.String(description="Domain", required=False)


# watashi v12.2.130m: reading the file is its own function now. It used to live
# inside post(), and get() called post() to reuse it — but post() carries a
# validator that wants a form body, so every GET was validated once against the
# query string, accepted, and then refused by the second validator with
# {"msg":"Validation error"}. That is what the "open the whole log" button hit.
def ws_read_log(file_name):
    if not file_name:
        return abort(400, "Parameter issue: 'file'")
    log_dir = f"{app.config['HIDDIFY_CONFIG_PATH']}log/system/"
    log_files = hutils.flask.list_dir_files(log_dir)

    file_path = f"{log_dir}{file_name}"
    if file_name not in log_files or not os.path.exists(file_path):
        return abort(404, "Invalid log file")

    logs = ''
    with open(file_path, 'r') as f:
        lines = [line for line in f]
        logs = "".join(lines)

    conv = Ansi2HTMLConverter()
    html_log = f'<div style="background-color:black; color:white;padding:10px">{conv.convert(logs)}</div>'
    resp = make_response(html_log)
    resp.headers["Access-Control-Allow-Origin"] = f'*'
    return resp


class AdminLogApi(MethodView):
    @app.input(AdminInputLogfileSchema, arg_name="data", location='form')  # type: ignore
    @app.output(fields.String(description="The html of the log", many=True))  # type: ignore
    @login_required({Role.super_admin})
    def post(self, data):
        """System: View Log file"""
        return ws_read_log(data.get('file'))

    @app.input(AdminInputLogfileSchemaGet, arg_name="data", location='query')  # type: ignore
    @app.output(fields.String(description="The html of the log", many=True))  # type: ignore
    @login_required({Role.super_admin})
    def get(self, data):
        """System: View Log file"""
        return ws_read_log(data.get('file'))

    def options(self):
        # domain = request.args.get("domain")
        # Domain.query.filter(Domain.domain == domain).first() or abort(404)
        if g.proxy_path != hconfig(ConfigEnum.proxy_path_admin):
            abort(403)
        resp = make_response("")
        resp.headers["Allow"] = "POST, GET"
        resp.headers["Access-Control-Allow-Origin"] = f'*'
        resp.headers["Access-Control-Allow-Headers"] = "Hiddify-API-Key"
        return resp
