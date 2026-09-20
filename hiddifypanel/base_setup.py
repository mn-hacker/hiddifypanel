from flask import request, g
import redis
# from hiddifypanel.cache import cache
from hiddifypanel.models import *

import flask_bootstrap
from flask_babel import Babel
from flask_session import Session

import datetime

from dotenv import dotenv_values
import os
import sys
from werkzeug.middleware.proxy_fix import ProxyFix
from loguru import logger
from sonora.wsgi import grpcWSGI

# watashi v12.2.130ad: the languages the panel actually carries a full
# catalogue for. Everything else falls back to English.
WS_SPOKEN = ('en', 'fa')



def init_app(app):
        from hiddifypanel import auth
        app.config["PREFERRED_URL_SCHEME"] = "https"
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1,
        )
        

        app.secret_key="asdsad"
        app.servers = {
            'name': 'current',
            'url': '',
        }  # type: ignore
        app.info = {
            'description': 'Hiddify is a free and open source software. It is as it is.',
            'termsOfService': 'https://hiddify.com',
            'contact': {
                'name': 'API Support',
                'url': 'https://www.hiddify.com/support',
                'email': 'panel@hiddify.com'
            },
            'license': {
                'name': 'Creative Commons Zero v1.0 Universal',
                'url': 'https://github.com/hiddify/Hiddify-Manager/blob/main/LICENSE'
            }
        }
        # setup flask server-side session
        # app.config['APPLICATION_ROOT'] = './'
        # app.config['SESSION_COOKIE_DOMAIN'] = '/'
        

        app.jinja_env.line_statement_prefix = '%'
        from hiddifypanel import hutils
        app.jinja_env.filters['b64encode'] = hutils.encode.do_base_64
        app.view_functions['admin.static'] = {}  # fix bug in apiflask
        flask_bootstrap.Bootstrap4(app)

        def get_locale():
            # watashi v12.2.130ad: which tongue this request is answered in.
            #
            # The admin side used to read the workspace-wide setting and
            # nothing else, so the language a person chose for their own
            # account was written to the database and then never looked
            # at. Both sides now ask the signed in account first and fall
            # back to the workspace setting, so one admin switching to
            # English does not drag everybody else along with them.
            #
            # Anything the panel cannot actually speak - an old value in
            # the database, a language that was offered once and has no
            # catalogue - lands on English rather than on a half
            # translated page.
            admin_side = 'admin' in request.base_url
            picked = None
            try:
                picked = getattr(auth.current_account, 'lang', None)
            except BaseException:
                picked = None
            fallback = hconfig(ConfigEnum.admin_lang if admin_side else ConfigEnum.lang)
            g.locale = ws_spoken(picked) or ws_spoken(fallback) or 'en'
            return g.locale
        def ws_spoken(value):
            """watashi v12.2.130ad: the value if the panel speaks it, else None."""
            name = getattr(value, 'name', None) or value
            name = str(name or '').strip().replace('-', '_').split('_')[0].lower()
            return name if name in WS_SPOKEN else None

        app.jinja_env.globals['get_locale'] = get_locale
        babel = Babel(app, locale_selector=get_locale)
        
        app.config['SESSION_TYPE'] = 'redis'
        
        app.config['SESSION_REDIS'] = redis.from_url(os.environ['REDIS_URI_MAIN'])
        app.config['SESSION_PERMANENT'] = True
        app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=10)
        app.security_schemes = {  # equals to use config SECURITY_SCHEMES
            'Hiddify-API-Key': {
                'type': 'apiKey',
                'in': 'header',
                'name': 'Hiddify-API-Key',
            }
        }
        Session(app)
        app.wsgi_app = grpcWSGI(app.wsgi_app)