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
from hiddifypanel.panel.run_commander import commander, Command


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
            if not os.path.exists(worker_path):
                 print(f"Error: restore_job.py not found at {worker_path}")
                 hutils.flask.flash(_('Error: restore job script not found'), category='error')
                 return render_template('backup.html', restore_form=restore_form)

            cmd = [sys.executable, worker_path, tmp_file.name, json.dumps(options)]
            
            # Pass current environment to subprocess to ensure PYTHONPATH and config are correct
            env = os.environ.copy()
            # Explicitly pass HIDDIFY_CONFIG_PATH from app config to subprocess environment
            if 'HIDDIFY_CONFIG_PATH' in app.config:
                env['HIDDIFY_CONFIG_PATH'] = app.config['HIDDIFY_CONFIG_PATH']

            # Explicitly add src to PYTHONPATH if not present
            src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))
            if 'PYTHONPATH' in env:
                env['PYTHONPATH'] = src_path + os.pathsep + env['PYTHONPATH']
            else:
                env['PYTHONPATH'] = src_path

            # Truncate log file synchronously to fix race condition
            commander(Command.truncate, run_in_background=False, log_file="0-install")

            # Log the command we are about to run
            print(f"Restore CMD: {cmd}")
            print(f"Restore CWD: {src_path}")
            print(f"Restore ENV PYTHONPATH: {env.get('PYTHONPATH')}")
            print(f"Restore ENV HIDDIFY_CONFIG_PATH: {env.get('HIDDIFY_CONFIG_PATH')}")

            # Start subprocess detached but capture output for debugging if it fails immediately
            # We use a log file for stdout/stderr to capture early failures
            # Use the panel's log directory which should be writable
            log_dir = os.path.join(app.config['HIDDIFY_CONFIG_PATH'], 'log', 'system')
            # Ensure log dir exists (subprocess might fail if dir is missing logic inside script, but here we need it for stderr)
            if not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
                
            debug_log_path = os.path.join(log_dir, 'restore_process_output.log')
            
            with open(debug_log_path, 'w') as log_file:
                subprocess.Popen(cmd, start_new_session=True, cwd=src_path, env=env, stdout=log_file, stderr=log_file)
            
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
