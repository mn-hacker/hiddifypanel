import os
import sys
from celery import Celery, Task
from celery.schedules import crontab
from dotenv import dotenv_values
from loguru import logger


# watashi v12.2.130ak: the three periodic jobs used to be written out twice,
# once for the flask app and once for the no-flask app, so backup_task
# was registered under the same name from two places. One definition
# now, and the guard keeps a single app from taking them twice.
_WS_JOBS_DONE = set()


def ws_periodic_jobs(celery_app):
    if id(celery_app) in _WS_JOBS_DONE:
        logger.info("watashi: the periodic jobs are already on this app")
        return celery_app
    from hiddifypanel.panel import usage
    from hiddifypanel.panel.cli import backup_task
    from hiddifypanel.panel.user_notifications import check_user_notifications

    # watashi v12.2.47: the cut-off can never be faster than this poll, so
    # 60s hard coded meant a user could burn several GB between two polls.
    # The owner sets it in the panel now (usage_update_interval, 10..600s).
    ws_interval = float(usage.WS_DEFAULT_INTERVAL)
    try:
        ws_interval = float(usage.ws_usage_interval())
    except Exception as e:
        logger.warning(f"watashi: cannot read usage_update_interval ({e}); staying at {ws_interval:.0f}s")
    logger.info(f"watashi: the usage task runs every {ws_interval:.0f} seconds")
    celery_app.add_periodic_task(ws_interval, usage.update_local_usage.s(), name='update usage')
    celery_app.autodiscover_tasks()

    # watashi v12.2.48: the task is woken every hour and decides for itself,
    # from ConfigEnum.backup_interval, whether this hour is a backup hour.
    celery_app.add_periodic_task(
        crontab(minute="30"),
        backup_task.s(),
        name="backup_task"
    )

    # User notification task - runs every hour
    celery_app.add_periodic_task(
        crontab(minute="30"),  # Run at :30 every hour
        check_user_notifications.s(),
        name="check_user_notifications"
    )
    _WS_JOBS_DONE.add(id(celery_app))
    return celery_app


def init_app(app):
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    
    celery_app.config_from_object(dict(
        broker_url=app.config['REDIS_URI_MAIN'],
        result_backend=app.config['REDIS_URI_MAIN'],
        task_ignore_result=True,
        result_expires=3600,
        broker_transport_options={'visibility_timeout': 43200},
    ))
    app.extensions["celery"] = celery_app


    ws_periodic_jobs(celery_app)

    celery_app.set_default()
    return celery_app



def init_app_no_flask():
    config={}
    for c, v in dotenv_values(os.environ.get("HIDDIFY_CFG_PATH", 'app.cfg')).items():
        if v.isdecimal():
            v = int(v)
        else:
            v = True if v.lower() == "true" else (False if v.lower() == "false" else v)
        config[c] = v
    import hiddifypanel.database 
    hiddifypanel.database.init_no_flask()

    from hiddifypanel.panel import init_db
    while not init_db.is_db_latest():
        logger.error("The database upgrade is required before proceeding. Retrying...")
        import time
        time.sleep(20)
    
    logger.info("Starting background tasks")

    celery_app = Celery()
    
    celery_app.config_from_object(dict(
        broker_url=config['REDIS_URI_MAIN'],
        result_backend=config['REDIS_URI_MAIN'],
        task_ignore_result=True,
        result_expires=3600,
        broker_transport_options={'visibility_timeout': 43200},
    ))
    

    
    ws_periodic_jobs(celery_app)

    celery_app.set_default()
    
    return celery_app


    