from flask import render_template, request, g, redirect
from hiddifypanel.hutils.flask import hurl_for
from flask_classful import FlaskView, route
from flask_babel import lazy_gettext as _
from apiflask import abort
import datetime

from hiddifypanel.auth import login_required
from hiddifypanel.database import db
from hiddifypanel.models import *

class UsageAdmin(FlaskView):

    @login_required(roles={Role.super_admin, Role.admin, Role.agent})
    def index(self):
        return render_template('usage.html')
