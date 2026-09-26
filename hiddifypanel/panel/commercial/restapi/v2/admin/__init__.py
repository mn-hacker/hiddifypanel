from apiflask import APIBlueprint
from flask import g
from hiddifypanel.models import AdminUser, User, AdminMode

bp = APIBlueprint("api_admin", __name__, url_prefix="/<proxy_path>/api/v2/admin/", enable_openapi=True)


def init_app(app):

    with app.app_context():
        from .admin_info_api import AdminInfoApi
        from .server_status_api import AdminServerStatusApi
        from .admin_user_api import AdminUserApi
        from .admin_users_api import AdminUsersApi
        from .admin_log_api import AdminLogApi
        from .system_actions import UpdateUserUsageApi, AllConfigsApi
        bp.add_url_rule('/me/', view_func=AdminInfoApi)  # type: ignore
        bp.add_url_rule('/server_status/', view_func=AdminServerStatusApi)  # type: ignore
        bp.add_url_rule('/admin_user/<uuid:uuid>/', view_func=AdminUserApi)  # type: ignore
        bp.add_url_rule('/admin_user/', view_func=AdminUsersApi)  # type: ignore
        bp.add_url_rule('/log/', view_func=AdminLogApi)  # type: ignore
        bp.add_url_rule('/update_user_usage/', view_func=UpdateUserUsageApi)  # type: ignore
        bp.add_url_rule('/all-configs/', view_func=AllConfigsApi)  # type: ignore
        from .user_api import UserApi
        from .users_api import UsersApi
        bp.add_url_rule('/user/<uuid:uuid>/', view_func=UserApi)  # type: ignore
        bp.add_url_rule('/user/', view_func=UsersApi)  # type: ignore
    app.register_blueprint(bp)


def has_permission(model) -> bool:
    '''Check if the authenticated account has permission to do an action(get,insert,update,delete) on the another admin'''
    # watashi v12.2.130cb: two separate reasons this said no when it should have said yes.
    #
    # get_super_admin_uuid() is always admin id 1, so a second super_admin -
    # which admin/me happily reports as mode super_admin - was refused.
    #
    # And the ownership test only accepted a record one step down, while the
    # list endpoints next door select on recursive_sub_admins_ids(). GET
    # admin/user/ therefore listed a customer that GET admin/user/<uuid>/ then
    # answered 403 for. The single record view now uses the same reach as the
    # list it came from, so the two can no longer disagree.
    #
    # This only ever grants access it already granted through the list; nothing
    # that was allowed before is refused now.
    if g.account.uuid == AdminUser.get_super_admin_uuid():
        return True
    if getattr(g.account, 'mode', None) == AdminMode.super_admin:
        return True

    try:
        reach = set(g.account.recursive_sub_admins_ids())
    except Exception:
        reach = {g.account.id}

    if isinstance(model, AdminUser):
        if model.parent_admin_id == g.account.id or model.id in reach:
            return True
    elif isinstance(model, User):
        if model.added_by == g.account.id or model.added_by in reach:
            return True

    return False
