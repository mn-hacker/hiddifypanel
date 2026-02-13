from flask import render_template, request, jsonify, g, redirect, current_app as app
from flask_wtf.file import FileField, FileRequired
from flask_bootstrap import SwitchField
from flask_babel import gettext as _
from flask_classful import FlaskView
from urllib.parse import urlparse
from flask_wtf import FlaskForm
from datetime import datetime
import wtforms as wtf
import json


from hiddifypanel.auth import login_required
from hiddifypanel.panel import hiddify
from hiddifypanel.models import *
from hiddifypanel import hutils


class Backup(FlaskView):
    decorators = [login_required({Role.super_admin})]

    def index(self):
        return render_template('backup.html', restore_form=get_restore_form())

    # @route("/backupfile")
    def backupfile(self):
        response = jsonify(hiddify.dump_db_to_dict())
        domain = urlparse(request.base_url).hostname
        filename = f'hiddify-{domain}-{datetime.now()}.json'
        response.headers.add('Content-disposition', f'attachment; filename={filename}')

        return response

    def post(self):

        restore_form = get_restore_form()

        if restore_form.validate_on_submit():
            set_hconfig(ConfigEnum.first_setup, False)
            file = restore_form.restore_file.data
            if isinstance(file, list):
                file = file[0]
            # Save file to temp location
            import os
            import tempfile
            import subprocess
            import sys
            
            # Save the uploaded file to a temporary file
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
            file.seek(0)
            tmp_file.write(file.read())
            tmp_file.close()
            
            # Prepare options
            options = {
                'enable_user_restore': restore_form.enable_user_restore.data,
                'enable_domain_restore': restore_form.enable_domain_restore.data,
                'enable_config_restore': restore_form.enable_config_restore.data,
                'override_root_admin': restore_form.override_root_admin.data
            }
            
            # Run restore job in separate process
            worker_path = os.path.join(os.path.dirname(__file__), 'restore_job.py')
            cmd = [sys.executable, worker_path, tmp_file.name, json.dumps(options)]
            
            # Start subprocess detached
            subprocess.Popen(cmd, start_new_session=True)
            
            from hiddifypanel.panel.admin.Actions import get_log_api_url, get_domains
            return render_template("result.html",
                            out_type="info",
                            out_msg=_("Restoring Backup... Please wait."),
                            log_file_url=get_log_api_url(),
                            log_file="0-install.log",
                            show_success=True,
                            domains=get_domains())
        else:
            hutils.flask.flash(_('Config file is incorrect'), category='error')
        return render_template('backup.html', restore_form=restore_form)


def get_restore_form(empty=False):
    class RestoreForm(FlaskForm):
        restore_file = FileField(_("Restore File"), description=_("Restore File Description"), validators=[FileRequired()])
        enable_config_restore = SwitchField(_("Restore Settings"), description=_("Restore Settings description"), default=False)
        enable_user_restore = SwitchField(_("Restore Users"), description=_("Restore Users description"), default=False)
        enable_domain_restore = SwitchField(_("Restore Domain"), description=_("Restore Domain description"), default=False)
        override_root_admin = SwitchField(_("Override Root Admin"), description=_("It will override the root admin to the current user"), default=False)
        submit = wtf.fields.SubmitField(_('Submit'))

    return RestoreForm(None) if empty else RestoreForm()
