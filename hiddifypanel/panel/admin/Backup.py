from flask import render_template, request, jsonify, g, redirect, current_app as app
from flask_wtf.file import FileField, FileRequired
from flask_bootstrap import SwitchField
from flask_babel import gettext as _
from flask_classful import FlaskView, route
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
    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        return render_template('backup.html',
                               restore_form=get_restore_form(),
                               stats=ws_backup_stats(),
                               bk_urls=ws_backup_urls(),
                               bk_text=ws_backup_text(),
                               bk_key=ws_backup_key(),
                               bk_csrf=ws_backup_csrf(),
                               bk_log_file='0-install.log')

    # @route("/backupfile")
    def backupfile(self):
        response = jsonify(hiddify.dump_db_to_dict())
        domain = urlparse(request.base_url).hostname
        filename = f'hiddify-{domain}-{datetime.now()}.json'
        response.headers.add('Content-disposition', f'attachment; filename={filename}')

        return response

    @route('ws_restore', methods=['POST'])
    def ws_restore(self):
        """Takes a backup file over ajax and starts the restore without leaving the page."""
        sent = request.files.get('restore_file')
        if sent is None or not sent.filename:
            return jsonify({'success': False, 'message': _('No file was given.')})
        try:
            raw = sent.read()
        except Exception:
            return jsonify({'success': False, 'message': _('The file could not be read.')})
        if not raw:
            return jsonify({'success': False, 'message': _('The file could not be read.')})
        if len(raw) > 64 * 1024 * 1024:
            return jsonify({'success': False, 'message': _('This file is too big to be a panel backup.')})
        try:
            bag = json.loads(raw.decode('utf-8', 'ignore'))
        except Exception:
            return jsonify({'success': False, 'message': _('This file is not a sound json file.')})
        wanted_keys = ('users', 'domains', 'hconfigs', 'admin_users', 'proxies', 'childs')
        if not isinstance(bag, dict) or not any(isinstance(bag.get(key), list) for key in wanted_keys):
            return jsonify({'success': False, 'message': _('This file does not look like a panel backup.')})
        wants = {
            'enable_config_restore': bool(request.form.get('enable_config_restore')),
            'enable_user_restore': bool(request.form.get('enable_user_restore')),
            'enable_domain_restore': bool(request.form.get('enable_domain_restore')),
            'override_root_admin': bool(request.form.get('override_root_admin')),
        }
        if not (wants['enable_config_restore'] or wants['enable_user_restore'] or wants['enable_domain_restore']):
            return jsonify({'success': False, 'message': _('Nothing was picked to bring back.')})
        try:
            set_hconfig(ConfigEnum.first_setup, False)
        except Exception as problem:
            print('first_setup could not be written', problem)
        if not ws_launch_restore(raw, wants):
            return jsonify({'success': False, 'message': _('The restore could not be started.')})
        return jsonify({'success': True, 'message': _('The restore has started.'), 'log_file': '0-install.log'})

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
            # Use fixed path in /tmp so user can find it easily without checking journal
            debug_log_path = "/tmp/hiddify_restore_debug.log"
            
            try:
                with open(debug_log_path, 'w') as log_file:
                    log_file.write(f"Starting Restore Process at {datetime.now()}\n")
                    log_file.write(f"CMD: {cmd}\n")
                    log_file.write(f"CWD: {src_path}\n")
                    log_file.write(f"ENV PYTHONPATH: {env.get('PYTHONPATH')}\n")
                    log_file.write(f"ENV HIDDIFY_CONFIG_PATH: {env.get('HIDDIFY_CONFIG_PATH')}\n")
                    log_file.flush()
                    
                    subprocess.Popen(cmd, start_new_session=True, cwd=src_path, env=env, stdout=log_file, stderr=log_file)
                    log_file.write("Subprocess started successfully.\n")
            except Exception as e:
                with open(debug_log_path, 'a') as f:
                    f.write(f"FAILED TO START SUBPROCESS: {e}\n")
                print(f"FAILED TO START RESTORE SUBPROCESS: {e}")
            
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


def ws_launch_restore(raw, options):
    """Writes the sent file to a temp path and runs the restore worker beside the panel."""
    import os
    import sys
    import tempfile
    import subprocess
    try:
        holder = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        holder.write(raw)
        holder.close()
        worker = os.path.join(os.path.dirname(__file__), 'restore_job.py')
        if not os.path.exists(worker):
            print('restore_job.py was not found beside Backup.py')
            return False
        cmd = [sys.executable, worker, holder.name, json.dumps(options)]
        env = os.environ.copy()
        try:
            if 'HIDDIFY_CONFIG_PATH' in app.config:
                env['HIDDIFY_CONFIG_PATH'] = app.config['HIDDIFY_CONFIG_PATH']
        except Exception:
            pass
        src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))
        if env.get('PYTHONPATH'):
            env['PYTHONPATH'] = src_path + os.pathsep + env['PYTHONPATH']
        else:
            env['PYTHONPATH'] = src_path
        try:
            commander(Command.truncate, run_in_background=False, log_file="0-install")
        except Exception as problem:
            print('the log could not be truncated', problem)
        note = open('/tmp/hiddify_restore_debug.log', 'w')
        note.write('Starting restore at %s\n' % datetime.now())
        note.write('CMD: %s\n' % cmd)
        note.flush()
        subprocess.Popen(cmd, start_new_session=True, cwd=src_path, env=env, stdout=note, stderr=note)
        return True
    except Exception as problem:
        print('the restore could not be started', problem)
        return False


def ws_backup_stats():
    """How much of each thing goes into a backup file."""
    out = {'users': 0, 'admins': 0, 'domains': 0, 'proxies': 0, 'settings': 0}
    try:
        from hiddifypanel.database import db
        out['users'] = db.session.query(User).count()
        out['admins'] = db.session.query(AdminUser).count()
        out['domains'] = db.session.query(Domain).count()
        out['proxies'] = db.session.query(Proxy).count()
        out['settings'] = db.session.query(BoolConfig).count() + db.session.query(StrConfig).count()
    except Exception as problem:
        print('the backup counts could not be read', problem)
    return out


def ws_backup_urls():
    """Every address the page needs, built here so the page never breaks on a missing route."""
    out = {}
    pairs = (('index', 'admin.Backup:index'),
             ('download', 'admin.Backup:backupfile'),
             ('restore', 'admin.Backup:ws_restore'))
    for name, target in pairs:
        try:
            out[name] = hutils.flask.hurl_for(target)
        except Exception as problem:
            print('address missing:', target, problem)
            out[name] = ''
    try:
        from hiddifypanel.panel.admin.Actions import get_log_api_url
        out['log'] = get_log_api_url()
    except Exception as problem:
        print('the log address could not be built', problem)
        out['log'] = ''
    return out


def ws_backup_key():
    """The key the log reader needs."""
    try:
        return str(g.account.uuid)
    except Exception:
        return ''


def ws_backup_csrf():
    try:
        from flask_wtf.csrf import generate_csrf
        return generate_csrf()
    except Exception as problem:
        print('the csrf token could not be built', problem)
        return ''


def ws_backup_text():
    """Every word the page says while it works, translated on the server."""
    return {
        'users': _('Users'),
        'domains': _('Domains'),
        'settings': _('Settings'),
        'fileOk': _('The file was read. It looks like a panel backup.'),
        'notJson': _('Only a json file can be restored.'),
        'tooBig': _('This file is too big to be a panel backup.'),
        'readFail': _('The file could not be read.'),
        'badJson': _('This file is not a sound json file.'),
        'notBackup': _('This file does not look like a panel backup.'),
        'getStarted': _('The download has started.'),
        'noFile': _('Choose a backup file first.'),
        'nothingPicked': _('Pick at least one thing to bring back.'),
        'willCome': _('comes back'),
        'staysAsIs': _('stays as it is'),
        'pickSet': _('Bring back the settings'),
        'pickUsr': _('Bring back the users'),
        'pickDom': _('Bring back the domains'),
        'pickRoot': _('Replace the main admin'),
        'working': _('Working...'),
        'allDone': _('The restore is finished.'),
        'wentWrong': _('Something did not go through.'),
        'failTtl': _('The restore did not finish'),
        'failTx': _('Something went wrong in the middle. Open the whole log to see the last lines.'),
        'doneTtl': _('The restore is finished'),
        'doneTx': _('The panel was installed again with the restored data. Open the panel and sign in.'),
        'panelBusy': _('The panel is busy installing, so it does not answer for a while.'),
        'firstLines': _('Waiting for the first lines...'),
        'noRoute': _('This address is not open on this panel.'),
        'netFail': _('The panel did not answer.'),
    }
