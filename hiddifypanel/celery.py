import os
import sys
from celery import Celery, Task
from celery.schedules import crontab
from dotenv import dotenv_values
from loguru import logger


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


        # Calls test('hello') every 10 seconds.
    from hiddifypanel.panel import usage
    # watashi v12.2.47: the cut-off can never be faster than this poll, so 60s
    # hard coded meant a user could burn several GB between two polls. The owner
    # sets it in the panel now (ConfigEnum.usage_update_interval, 10..600s).
    ws_interval = float(usage.WS_DEFAULT_INTERVAL)
    try:
        ws_interval = float(usage.ws_usage_interval())
    except Exception as e:
        logger.warning(f"watashi: cannot read usage_update_interval ({e}); staying at {ws_interval:.0f}s")
    logger.info(f"watashi: the usage task runs every {ws_interval:.0f} seconds")
    celery_app.add_periodic_task(ws_interval, usage.update_local_usage.s(), name='update usage')
    # celery_app.conf.beat_schedule = {
    # 'update_usage': {
    #     'task': 'hiddifypanel.panel.usage.update_local_usage',
    #     'schedule': 30.0, 

    # },
# }
    from hiddifypanel.panel.cli import backup_task
    from hiddifypanel.models import hconfig, ConfigEnum
    celery_app.autodiscover_tasks()
    # celery_app.add_periodic_task(30.0, backup_task.s(), name='backup task')
    # celery_app.add_periodic_task(
    #     crontab(hour="*/6", minute=30),
    #     backup_task.delay(),
    # )

    # watashi v12.2.48: this is the schedule that really runs, because the
    # background tasks service starts create_app(). It was pinned to
    # hour="*/6", which is why the interval chosen in the panel changed
    # nothing. The task is woken every hour now and decides for itself,
    # from ConfigEnum.backup_interval, whether this hour is a backup hour.
    celery_app.add_periodic_task(
        crontab(minute="30"),
        backup_task.s(),
        name="backup_task"
    )
    
    # User notification task - runs every hour
    from hiddifypanel.panel.user_notifications import check_user_notifications
    celery_app.add_periodic_task(
        crontab(minute="30"),  # Run at :30 every hour
        check_user_notifications.s(),
        name="check_user_notifications"
    )
    
    
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
    

    
        # Calls test('hello') every 10 seconds.
    from hiddifypanel.panel import usage
    # watashi v12.2.47: the cut-off can never be faster than this poll, so 60s
    # hard coded meant a user could burn several GB between two polls. The owner
    # sets it in the panel now (ConfigEnum.usage_update_interval, 10..600s).
    ws_interval = float(usage.WS_DEFAULT_INTERVAL)
    try:
        ws_interval = float(usage.ws_usage_interval())
    except Exception as e:
        logger.warning(f"watashi: cannot read usage_update_interval ({e}); staying at {ws_interval:.0f}s")
    logger.info(f"watashi: the usage task runs every {ws_interval:.0f} seconds")
    celery_app.add_periodic_task(ws_interval, usage.update_local_usage.s(), name='update usage')
    # celery_app.conf.beat_schedule = {
    # 'update_usage': {
    #     'task': 'hiddifypanel.panel.usage.update_local_usage',
    #     'schedule': 30.0, 

    # },
# }
    from hiddifypanel.panel.cli import backup_task
    from hiddifypanel.models import hconfig, ConfigEnum
    celery_app.autodiscover_tasks()
    # celery_app.add_periodic_task(30.0, backup_task.s(), name='backup task')
    # celery_app.add_periodic_task(
    #     crontab(hour="*/6", minute=30),
    #     backup_task.delay(),
    # )

    # watashi v12.2.48: the 1/6/12 special cases read the interval once at
    # start up and produced uneven hours for every other number. One
    # hourly wake up, and the task itself keeps the time.
    celery_app.add_periodic_task(
        crontab(minute="30"),
        backup_task.s(),
        name="backup_task"
    )

    # User notification task - runs every hour
    from hiddifypanel.panel.user_notifications import check_user_notifications
    celery_app.add_periodic_task(
        crontab(minute="30"),  # Run at :30 every hour
        check_user_notifications.s(),
        name="check_user_notifications"
    )
    
    
    celery_app.set_default()
    
    return celery_app


    