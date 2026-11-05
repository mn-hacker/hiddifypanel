#!/opt/watashi-manager/.venv313/bin/python
# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)

from watashipanel import create_app_wsgi

app = application = create_app_wsgi()  # noqa
from asgiref.wsgi import WsgiToAsgi
asgi_app = WsgiToAsgi(app)
celery_app=app.extensions["celery"]
if __name__ == "__main__":
    app.run()
