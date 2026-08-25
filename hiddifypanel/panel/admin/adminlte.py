from flask import redirect
from flask_admin.contrib.sqla import ModelView
from hiddifypanel import auth
from flask_admin.form import SecureForm



class AdminLTEModelView(ModelView):
    form_base_class = SecureForm
    edit_modal = True
    create_modal = True

    list_template = 'hiddify-flask-admin/list.html'
    create_template = 'flask-admin/model/create.html'
    edit_template = 'flask-admin/model/edit.html'
    details_template = 'flask-admin/model/details.html'

    create_modal_template = 'flask-admin/model/modals/create.html'
    edit_modal_template = 'flask-admin/model/modals/edit.html'
    details_modal_template = 'flask-admin/model/modals/details.html'

    # Watashi v12.2.35: pages this panel has left behind.
    #
    # When a save is refused, flask-admin asks for its own create, edit or
    # details page. Those pages wear the theme the panel replaced, so they
    # are never drawn: the admin is sent back to the list they came from,
    # where the reason is already waiting as a message.
    #
    # This sits on render() and not on create_view or edit_view, because
    # flask-admin reads its routes from those two methods and overriding
    # them takes their addresses away.
    #
    # A list page is never redirected, so a view whose own list template is
    # one of the old ones cannot bounce forever.
    ws_old_pages = (
        'flask-admin/',
        'admin/',
        'hiddify-flask-admin/',
        'admin-layout.html',
        'ltemaster.html',
        'base2.html',
    )

    def render(self, template, **kwargs):
        if isinstance(template, str) \
                and template.startswith(self.ws_old_pages) \
                and template != getattr(self, 'list_template', None):
            return redirect(self.get_url('.index_view'))
        return super().render(template, **kwargs)

    def inaccessible_callback(self, name, **kwargs):
        return auth.redirect_to_login()  # type: ignore
