# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
from flask.views import MethodView
from flask import current_app as app
from loguru import logger

from watashipanel.models import Child, Role
from watashipanel.auth import login_required

from .schema import ChildStatusInputSchema, ChildStatusOutputSchema


class StatusApi(MethodView):
    decorators = [login_required(node_auth=True)]

    @app.input(ChildStatusInputSchema, arg_name='data')  # type: ignore
    @app.output(ChildStatusOutputSchema)  # type: ignore
    def post(self, data):
        logger.info(f"Checking the existence of child with unique_id: {data['child_unique_id']}")
        res = ChildStatusOutputSchema()
        res.existance = False  # type: ignore

        child = Child.query.filter(Child.unique_id == data['child_unique_id']).first()
        if child:
            logger.info(f"Child with unique_id: {data['child_unique_id']} exists")
            res.existance = True  # type: ignore

        return res
