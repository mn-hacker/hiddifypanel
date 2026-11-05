# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
source /opt/watashi-manager/common/utils.sh
activate_python_venv
while true; do
    FLASK_RUN_HOST=0.0.0.0 FLASK_RUN_PORT=9000 watashi-panel-cli run
done
