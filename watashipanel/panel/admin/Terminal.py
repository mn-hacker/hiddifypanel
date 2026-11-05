# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
# from watashipanel.database import db
# import uuid
# from flask_babel import gettext as _
# from flask_bootstrap import SwitchField
# # from flask_babel import gettext as _
# import wtforms as wtf
# from flask_wtf import FlaskForm
# import pathlib
# from watashipanel.models import BoolConfig,StrConfig,ConfigEnum,hconfig,Proxy,User,Domain,DomainType

# from datetime import datetime,timedelta,date
# import os,sys
# import json
# import urllib.request
# import subprocess
# import re
# from watashipanel.panel import watashi
# from flask import current_app,render_template,request,Response,Markup,hurl_for(
# from watashipanel.panel.watashi import flash
# from flask_wtf.file import FileField, FileRequired
# import json

# from flask_classful import FlaskView
# from flask import Flask, render_template
# from flask_socketio import SocketIO, send, emit
# from flask_socketio import Namespace, disconnect
# from flask import current_app as app

# class Terminal(Namespace):

#     def on_connect(self):
#         pass

#     def on_disconnect(self):
#         disconnect()
#         app.logger.info("socket disconnected")
#         db.session.remove() # this is important

#     def on_get_foo_details(self, **kwargs):
#         try:
#             # Do something useful like print statement
#             print("Hello! Awesome world")
#             # Then send a event back to the world
#             emit("event_name", dict(random_key="random_value"), namespace=self.namespace)
#             # or
#             emit("event_name", dict(random_key="random_value"))
#         except Exception as e:
#             print("Catch the exception")
#         # Db session remove is important
#     db.session.remove()
