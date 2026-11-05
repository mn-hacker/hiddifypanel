# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask import request, g
# from watashipanel.cache import cache



import datetime

from dotenv import dotenv_values
import os
import sys

def create_app(*args, app_mode="web", **config):
    from apiflask import APIFlask
    from loguru import logger


    from dynaconf import FlaskDynaconf
    
    app = APIFlask(__name__, static_url_path="/<proxy_path>/static/", instance_relative_config=True, version='2.2.0', title="Watashi API",
                   openapi_blueprint_url_prefix="/<proxy_path>/api", docs_ui='elements', json_errors=False, enable_openapi=app_mode=="web")
    # app = Flask(__name__, static_url_path="/<proxy_path>/static/", instance_relative_config=True)
    # app.asgi_app = WsgiToAsgi(app)
    
    for c, v in dotenv_values(os.environ.get("WATASHI_CFG_PATH", 'app.cfg')).items():
        if v.isdecimal():
            v = int(v)
        else:
            v = True if v.lower() == "true" else (False if v.lower() == "false" else v)
        app.config[c] = v
    dyn=FlaskDynaconf(app,settings_files=[os.environ.get("WATASHI_CFG_PATH", 'app.cfg')])
    
    extensions=[
        # "watashipanel.cache:init_app",
        "watashipanel.database:init_app",
        "watashipanel.panel.hlogger:init_cli",
    ]
    
    if app_mode=="celery":
        extensions=["watashipanel.celery:init_app"]
    elif app_mode=="cli":
        extensions.append("watashipanel.panel.cli:init_app")
    else:
        extensions.extend([
            "watashipanel.base_setup:init_app",
            "watashipanel.panel.common:init_app",
            "watashipanel.panel.common_bp:init_app",
            "watashipanel.panel.admin:init_app",
            "watashipanel.panel.user:init_app",
            "watashipanel.panel.commercial:init_app",
            "watashipanel.panel.node:init_app",
            "watashipanel.celery:init_app",
        ])
    
    app.config['EXTENSIONS']=extensions

    app.config.update(config)  # Override with passed config
    
    app.config.load_extensions("EXTENSIONS")
    return app


def create_app_wsgi(*args, **kwargs):
    # workaround for Flask issue
    # that doesn't allow **config
    # to be passed to create_app
    # https://github.com/pallets/flask/issues/4170
    cli = ("watashipanel" in sys.argv[0] ) or (sys.argv[1] in ["update-usage", "all-configs", "admin_links", "admin_path"])

    app = create_app(app_mode="cli" if cli else "web")
    return app



def create_celery_app():
    #     # workaround for Flask issue
    #     # that doesn't allow **config
    #     # to be passed to create_app
    #     # https://github.com/pallets/flask/issues/4170
    # print(kwargs)
    app = create_app(app_mode="celery")
    return app.extensions["celery"]
