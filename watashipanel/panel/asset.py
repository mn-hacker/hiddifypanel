# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask import g, send_from_directory
from watashipanel.hutils.flask import hurl_for


def send_static(path):
    return send_from_directory('static/assets', path)


def init_app(app):
    @app.url_defaults
    def add_asset(endpoint, values):
        def get_asset(path):
            return hurl_for('asset', proxy_path=g.proxy_path, path=path)
        g.asset_url = get_asset

    app.add_url_rule('/<proxy_path>/asset/<path:path>',
                     'asset', view_func=send_static)
    pass
