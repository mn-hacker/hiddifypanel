# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from .VERSION import __version__, __release_time__,is_released_version

from dotenv import load_dotenv
load_dotenv("/opt/watashi-manager/watashi-panel/app.cfg")

# from . import cache
from . import Events
from .base import create_app, create_app_wsgi
# from . import hutils
# from . import panel


__all__ = ["create_app", "create_app_wsgi"]

# application = create_app_wsgi()
