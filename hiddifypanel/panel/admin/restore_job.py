import sys
import json
import os

import traceback

# Ensure the current directory is in sys.path so we can import hiddifypanel
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, '../../../'))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

try:
    from hiddifypanel import create_app
    from hiddifypanel.panel import hiddify
    from hiddifypanel.models import *
    from hiddifypanel.database import db
    from hiddifypanel.panel.run_commander import commander, Command
except Exception as e:
    with open(os.path.join(current_dir, 'restore_error.log'), 'w') as f:
        f.write(f"Import Error: {str(e)}\n{traceback.format_exc()}")
    print(f"Import Error: {str(e)}")
    sys.exit(1)

def ws_load_guard():
    """watashi v12.2.130m: the backup guard, loaded without waking the admin package.

    This worker is a separate process with a cli app, which has no babel.
    "from hiddifypanel.panel.admin import ws_backup_guard" runs
    panel/admin/__init__.py on the way, that imports DomainAdmin, and
    DomainAdmin translates a message while its class body runs. With no babel
    registered that raised KeyError: 'babel' and the restore stopped before it
    read anything. The guard itself needs none of that, so it is loaded from
    its own file.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'ws_backup_guard.py')
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location('ws_backup_guard_worker', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    # a panel installed as a package still has the module in the usual place
    from hiddifypanel.panel.admin import ws_backup_guard as fallback
    return fallback


def restore_backup(json_path, restore_options):
    # Manually load configuration to ensure SQLALCHEMY_DATABASE_URI is set
    # Using the same logic as __init__.py but adapting to the subprocess environment
    from dotenv import load_dotenv
    
    config_path = os.environ.get("HIDDIFY_CONFIG_PATH", "/opt/hiddify-manager/")
    app_cfg = os.path.join(config_path, "hiddify-panel/app.cfg")
    
    if os.path.exists(app_cfg):
        # IMPORTANT: base.py uses HIDDIFY_CFG_PATH to read config into app.config
        # We must set this env var so create_app finds the file, otherwise it looks in CWD
        os.environ['HIDDIFY_CFG_PATH'] = app_cfg
        load_dotenv(app_cfg)
        print(f"Loaded configuration from {app_cfg}")
        print(f"Set HIDDIFY_CFG_PATH to {app_cfg}")
    else:
        print(f"WARNING: Configuration file {app_cfg} not found!")

    app = create_app(app_mode="cli")
    with app.app_context():
        # Setup logging to install.log to show progress in UI
        log_file = f"{app.config['HIDDIFY_CONFIG_PATH']}/log/system/0-install.log"
        
        def log(msg):
            try:
                with open(log_file, 'a') as f:
                    f.write(f"####{50}####Restoring Data####{msg}####\n")
            except Exception as e:
                print(f"Failed to write to UI log: {e}")
            print(msg)

        try:
            log("Reading backup file...")
            with open(json_path, 'r') as f:
                json_data = json.load(f)

            # watashi v12.2.130: the same gate the page used, run again here,
            # because this worker can also be started from the old form post.
            guard = ws_load_guard()
            wants = dict(restore_options)
            report = guard.ws_inspect(json_data, wants)
            for word in report.get('warn', []):
                log("note: %s" % word)
            if not report['ok']:
                for word in report['fatal']:
                    log("this backup cannot be restored: %s" % word)
                raise ValueError("the backup did not pass the checks: %s" % report['fatal'])

            # Nothing has been written yet, so this is the last moment at which
            # the panel as it stands can still be kept.
            snapshot = None
            try:
                snapshot = guard.ws_snapshot('pre-restore')
                log("the panel as it stands was saved to %s" % snapshot)
            except Exception as problem:
                log("the snapshot could not be taken: %s" % problem)

            try:
                from hiddifypanel.models.config import ws_unknown_configs
                ws_unknown_configs(clear=True)
            except Exception:
                pass

            log("Restoring database from backup (this may take a while)...")
            
            # Extract options
            enable_user_restore = restore_options.get('enable_user_restore', False)
            enable_domain_restore = restore_options.get('enable_domain_restore', False)
            enable_config_restore = restore_options.get('enable_config_restore', False)
            override_root_admin = restore_options.get('override_root_admin', False)

            hiddify.set_db_from_json(json_data,
                                     set_users=enable_user_restore,
                                     set_domains=enable_domain_restore,
                                     set_settings=enable_config_restore,
                                     override_unique_id=False,
                                     override_child_unique_id=True,
                                     override_root_admin=override_root_admin
                                     )

            # remove default user if exists
            if default := User.by_id(1):
                default.remove()

            # Remove default sslip.io domain if a direct domain exists
            direct_domains_count = Domain.query.filter(Domain.mode == DomainType.direct).count()
            if direct_domains_count > 0:
                sslip_domains = Domain.query.filter(Domain.domain.like('%sslip.io')).all()
                for d in sslip_domains:
                    log(f"Removing temporary domain: {d.domain}")
                    db.session.delete(d)
                db.session.commit()
                
            # watashi v12.2.130: what the database quietly refused to take.
            try:
                from hiddifypanel.models.config import ws_unknown_configs
                skipped = ws_unknown_configs(clear=True)
                if skipped:
                    log("these settings are unknown to this panel and were skipped: %s" % ', '.join(skipped))
            except Exception as problem:
                log("the skipped settings could not be listed: %s" % problem)

            # watashi v12.2.130: and the gate on the way out. A restore that leaves
            # the panel without an owner, a domain or its paths is worse than no
            # restore at all, so in that case the snapshot goes back in.
            health = guard.ws_health()
            if not health['ok']:
                log("the panel is not healthy after the restore: %s" % ', '.join(health['problems']))
                if snapshot:
                    log("putting back the panel as it was before the restore")
                    try:
                        guard.ws_rollback(snapshot)
                        log("the panel was put back. the backup file was not applied.")
                    except Exception as problem:
                        log("the panel could not be put back: %s" % problem)
                raise ValueError("the restore left the panel unhealthy: %s" % health['problems'])
            log("the panel is healthy after the restore")

            log("Database restoration complete. Triggering installation...")
            
            # Initial log for install to ensure UI switches to install phase
            with open(log_file, 'a') as f:
                 f.write(f"####{60}####Installation####Starting services...####\n")

            # Run installation
            commander(Command.install)
            
        except Exception as e:
            log(f"Error during restore: {str(e)}")
            raise e
        finally:
            # Clean up temp file if needed
            if os.path.exists(json_path):
                os.remove(json_path)

if __name__ == "__main__":
    # Simplified logging for startup errors
    # Try to find log dir relative to this script if env var is not set
    if os.environ.get("HIDDIFY_CONFIG_PATH"):
        log_dir = os.path.join(os.environ["HIDDIFY_CONFIG_PATH"], "log/system/")
    else:
        # fallback to relative path: src/hiddifypanel/panel/admin/restore_job.py -> .../log/system/
        log_dir = os.path.abspath(os.path.join(current_dir, '../../../../log/system/'))
    
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"Failed to create log dir: {e}")

    log_file = os.path.join(log_dir, "0-install.log")
    
    def dirty_log(msg):
        try:
            with open(log_file, 'a') as f:
                f.write(f"####{10}####Restore Job Startup####{msg}####\n")
            print(f"LOG: {msg}")
        except Exception as e:
            print(f"Failed to log: {e}")
            # Try fallback log in current dir
            try:
                with open(os.path.join(current_dir, 'restore_error.log'), 'a') as f:
                    f.write(f"{msg}\nLogging Error: {e}\n")
            except Exception as nested:  # watashi v12.2.60
                print(f"Failed to write the fallback log: {nested}")
            
    try:
        if len(sys.argv) < 3:
            dirty_log("Usage error: missing arguments")
            print("Usage: python restore_job.py <json_file_path> <options_json_string>")
            sys.exit(1)
            
        json_path = sys.argv[1]
        options = json.loads(sys.argv[2])
        
        restore_backup(json_path, options)
    except Exception as e:
        dirty_log(f"CRITICAL ERROR: {str(e)}")
        import traceback
        dirty_log(traceback.format_exc())
        sys.exit(1)

