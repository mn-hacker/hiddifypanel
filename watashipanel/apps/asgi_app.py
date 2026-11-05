#!/opt/watashi-manager/.venv313/bin/python
# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)

from watashipanel import create_app_wsgi
from asgiref.wsgi import WsgiToAsgi

app = create_app_wsgi()  # noqa
asgi_app = WsgiToAsgi(app)
