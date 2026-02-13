import sys
import json
import os
from hiddifypanel import create_app
from hiddifypanel.panel import hiddify
from hiddifypanel.models import *
from hiddifypanel.panel.run_commander import commander, Command

def restore_backup(json_path, restore_options):
    app = create_app()
    with app.app_context():
        # Setup logging to install.log to show progress in UI
        log_file = f"{app.config['HIDDIFY_CONFIG_PATH']}/log/system/0-install.log"
        
        def log(msg):
            with open(log_file, 'a') as f:
                f.write(f"####{50}####Restoring Data####{msg}####\n")
            print(msg)

        try:
            log("Reading backup file...")
            with open(json_path, 'r') as f:
                json_data = json.load(f)

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
    if len(sys.argv) < 3:
        print("Usage: python restore_job.py <json_file_path> <options_json_string>")
        sys.exit(1)
        
    json_path = sys.argv[1]
    options = json.loads(sys.argv[2])
    
    restore_backup(json_path, options)
