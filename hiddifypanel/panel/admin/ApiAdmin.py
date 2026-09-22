"""watashi v12.2.130aq: the API page.

The panel had a raw OpenAPI page and nothing else. It listed the parent and
child machinery beside the two calls a telegram bot really needs, never said
how a key is sent, and spoke no persian. This page answers the question the
people who build bots and reseller sites keep asking, with their own address
and their own key already filled in.

The page only reads. Nothing here can change anything, so the worst a broken
form could do is show the wrong sentence.
"""
from flask import render_template
from flask_classful import FlaskView, route

from hiddifypanel.auth import login_required
from hiddifypanel.models import Role
from hiddifypanel.panel.admin import ws_api_book


class ApiAdmin(FlaskView):
    decorators = [login_required({Role.super_admin, Role.admin, Role.agent})]

    @route('/')
    def index(self):
        return render_template('api_guide.html', **ws_api_book.page_data())
