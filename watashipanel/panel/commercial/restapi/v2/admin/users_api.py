# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask.views import MethodView
from flask import current_app as app, g
from apiflask import abort
from watashipanel.auth import login_required
from watashipanel.models.role import Role
from watashipanel.panel import watashi
from watashipanel.drivers import user_driver
from watashipanel.models import User
from .user_api import UserSchema, PostUserSchema
from . import has_permission


class UsersApi(MethodView):
    decorators = [login_required({Role.super_admin, Role.admin, Role.agent})]

    @app.output(UserSchema(many=True))  # type: ignore
    def get(self):
        """User: List users of current admin"""

        users = User.query.filter(User.added_by.in_(g.account.recursive_sub_admins_ids())).all() or abort(404, "You have no user")
        return [user.to_schema() for user in users]  # type: ignore

    @app.input(PostUserSchema, arg_name="data")  # type: ignore
    @app.output(UserSchema)  # type: ignore
    def post(self, data):
        """User: Create a user"""

        if data.get("uuid") and User.by_uuid(data['uuid']):
            abort(400, 'The user exists')

        if not data.get('added_by_uuid'):
            data['added_by_uuid'] = g.account.uuid

        dbuser = User.add_or_update(**data) or abort(502, "Unknown issue: User is not added")
        user_driver.add_client(dbuser)
        watashi.quick_apply_users()
        return dbuser.to_schema()
