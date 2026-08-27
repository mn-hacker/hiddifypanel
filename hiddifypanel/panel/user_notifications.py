"""
User Notification System
Sends automatic Telegram notifications to users for:
1. Expiry warning (X days before)
2. Usage warning (80% consumed)
3. Subscription ended
"""

import datetime
from celery import shared_task
from loguru import logger

from hiddifypanel.database import db
from hiddifypanel.models import User, hconfig, ConfigEnum
from hiddifypanel import hutils


@shared_task(ignore_result=True)
def check_user_notifications():
    """
    Celery task to check and send notifications to users.
    Only sends to users with telegram_id connected.
    """
    if not hconfig(ConfigEnum.telegram_bot_token):
        return {"status": "skipped", "reason": "No Telegram bot token configured"}

    # watashi v12.2.48: tgbot.py builds the bot with the placeholder token "1:2"
    # and only the web views ever called register_bot(). In this worker the
    # token was dead, so every send answered 404 and nobody was notified.
    if not ws_ensure_bot():
        logger.error("watashi: the telegram bot could not be woken, so no notification was sent")
        return {"status": "skipped", "reason": "the bot could not be woken with the saved token"}

    # while we are awake once an hour anyway, check that the usage
    # accounting is still ticking (the v12.2.47 heartbeat).
    ws_usage_heartbeat_alarm()
    
    results = {
        "expiry_notifications": 0,
        "usage_notifications": 0,
        "finished_notifications": 0,
        "errors": []
    }
    
    try:
        # Get notification settings
        notify_expiry_enable = hconfig(ConfigEnum.notify_expiry_enable)
        notify_usage_enable = hconfig(ConfigEnum.notify_usage_enable)
        notify_finished_enable = hconfig(ConfigEnum.notify_finished_enable)
        
        try:
            notify_expiry_days = int(hconfig(ConfigEnum.notify_expiry_days) or "3")
        except (ValueError, TypeError):
            notify_expiry_days = 3
        
        try:
            notify_usage_percent = int(hconfig(ConfigEnum.notify_usage_percent) or "80")
        except (ValueError, TypeError):
            notify_usage_percent = 80
        
        # Query users with telegram_id (connected to Telegram)
        users_with_telegram = db.session.query(User).filter(
            User.telegram_id != None,
            User.telegram_id != 0
        ).all()
        
        for user in users_with_telegram:
            try:
                # 1. Check expiry notification
                if notify_expiry_enable and not user.notified_expiry:
                    # watashi v12.2.48: 0 < ... skipped the very last day, the day
                    # the warning matters most.
                    if user.is_active and 0 <= user.remaining_days <= notify_expiry_days:
                        send_expiry_notification(user, user.remaining_days)
                        user.notified_expiry = True
                        results["expiry_notifications"] += 1
                
                # 2. Check usage notification (80%)
                if notify_usage_enable and not user.notified_usage_80:
                    if user.usage_limit > 0:
                        usage_percent = (user.current_usage / user.usage_limit) * 100
                        if usage_percent >= notify_usage_percent:
                            send_usage_notification(user, usage_percent)
                            user.notified_usage_80 = True
                            results["usage_notifications"] += 1
                
                # 3. Check subscription finished notification
                if notify_finished_enable and not user.notified_finished:
                    if not user.is_active and user.start_date is not None:
                        send_finished_notification(user)
                        user.notified_finished = True
                        results["finished_notifications"] += 1
                
                # Reset notification flags when user becomes active again
                if user.is_active:
                    if user.notified_finished:
                        user.notified_finished = False
                    # Reset usage notification if usage is reset
                    if user.usage_limit > 0:
                        usage_percent = (user.current_usage / user.usage_limit) * 100
                        # watashi v12.2.48: a hard 50% was wrong for an owner who
                        # warns at 30%; the gap follows the setting now.
                        if usage_percent < max(10, notify_usage_percent - 30):
                            user.notified_usage_80 = False
                    # Reset expiry notification if days increased
                    if user.remaining_days > notify_expiry_days:
                        user.notified_expiry = False
                        
            except Exception as e:
                logger.error(f"Error processing notifications for user {user.uuid}: {e}")
                results["errors"].append(f"{user.name}: {str(e)}")
        
        db.session.commit()
        logger.info(
            "watashi: notifications sent - expiry {}, usage {}, finished {}; "
            "errors {}; telegram users {}".format(
                results["expiry_notifications"], results["usage_notifications"],
                results["finished_notifications"], len(results["errors"]),
                len(users_with_telegram)))
        
    except Exception as e:
        logger.exception(f"Error in check_user_notifications: {e}")
        results["errors"].append(str(e))
    
    return results


def send_expiry_notification(user: User, days_remaining: int):
    """Send expiry warning notification to user"""
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    
    try:
        msg = _("⚠️ Subscription Expiry Warning") + "\n\n"
        msg += _("Your subscription will expire in %(days)s days.", days=days_remaining) + "\n\n"
        msg += ws_usage_block(user)
        
        keyboard = Usage.user_keyboard(user.uuid)
        bot.send_message(user.telegram_id, msg, reply_markup=keyboard)
        logger.info(f"Sent expiry notification to user {user.name} ({user.telegram_id})")
    except Exception as e:
        logger.error(f"Failed to send expiry notification to {user.name}: {e}")
        raise


def send_usage_notification(user: User, usage_percent: float):
    """Send usage warning notification to user"""
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    
    try:
        msg = _("📊 Usage Warning") + "\n\n"
        msg += _("You have used %(percent).1f%% of your data allowance.", percent=usage_percent) + "\n\n"
        msg += ws_usage_block(user)
        
        keyboard = Usage.user_keyboard(user.uuid)
        bot.send_message(user.telegram_id, msg, reply_markup=keyboard)
        logger.info(f"Sent usage notification to user {user.name} ({user.telegram_id})")
    except Exception as e:
        logger.error(f"Failed to send usage notification to {user.name}: {e}")
        raise


def send_finished_notification(user: User):
    """Send subscription ended notification to user"""
    from flask_babel import lazy_gettext as _
    from hiddifypanel.panel.commercial.telegrambot import bot, Usage
    
    try:
        msg = _("❌ Subscription Ended") + "\n\n"
        
        # Determine why subscription ended
        if user.usage_limit > 0 and user.current_usage >= user.usage_limit:
            msg += _("Your data allowance has been exhausted.") + "\n"
        elif user.remaining_days < 0:
            msg += _("Your subscription time has expired.") + "\n"
        else:
            msg += _("Your subscription has ended.") + "\n"
        
        msg += "\n" + _("Please renew your subscription to continue using the service.") + "\n\n"
        msg += ws_usage_block(user)
        
        keyboard = Usage.user_keyboard(user.uuid)
        bot.send_message(user.telegram_id, msg, reply_markup=keyboard)
        logger.info(f"Sent finished notification to user {user.name} ({user.telegram_id})")
    except Exception as e:
        logger.error(f"Failed to send finished notification to {user.name}: {e}")
        raise


# ---------------------------------------------------------------------------
# watashi v12.2.48 helpers
# ---------------------------------------------------------------------------


def ws_ensure_bot() -> bool:
    """Make sure the TeleBot in THIS process carries the real token.

    tgbot.py builds the object with the placeholder token "1:2"; register_bot()
    is what turns it into a real bot. The web side calls that, the celery worker
    never did. We call it here without touching the webhook, because the webhook
    belongs to the web side.
    """
    try:
        from hiddifypanel.panel.commercial.telegrambot import bot, register_bot
    except Exception as e:
        logger.error(f"watashi: the telegram bot module could not be loaded ({e})")
        return False
    token = hconfig(ConfigEnum.telegram_bot_token)
    if not token:
        return False
    if bot.token != token or not bot.username:
        register_bot()
    if bot.token != token:
        bot.token = token
    return bool(bot.token) and bot.token != "1:2"


def ws_usage_block(user) -> str:
    """The usage summary, with a plain fallback.

    Usage.get_usage_msg() needs a domain and an app context; on a fresh panel it
    raises IndexError on Domain.get_domains()[0] and took the whole notification
    down with it. A short line is better than no message at all.
    """
    try:
        from hiddifypanel.panel.commercial.telegrambot import Usage
        return Usage.get_usage_msg(user.uuid)
    except Exception as e:
        logger.warning(f"watashi: the usage message could not be built for {user.uuid} ({e})")
        try:
            return "{:.2f} GB / {:.2f} GB".format(user.current_usage_GB, user.usage_limit_GB)
        except Exception:
            return ""


def ws_notify_admins(text: str) -> int:
    """One short message to every super admin who connected the bot."""
    if not ws_ensure_bot():
        return 0
    sent = 0
    try:
        from hiddifypanel.models import AdminUser, AdminMode
        from hiddifypanel.panel.commercial.telegrambot import bot
        for admin in db.session.query(AdminUser).filter(
                AdminUser.mode == AdminMode.super_admin,
                AdminUser.telegram_id.isnot(None),
                AdminUser.telegram_id != 0).all():
            try:
                bot.send_message(admin.telegram_id, text)
                sent += 1
            except Exception as e:
                logger.error(f"watashi: an admin could not be reached on telegram ({e})")
    except Exception as e:
        logger.exception(f"watashi: the admin notification failed ({e})")
    return sent


def ws_usage_heartbeat_alarm(max_missed: int = 10) -> bool:
    """Report a frozen usage accounting instead of staying silent.

    v12.2.47 stamps ws:usage:last-run on every usage run. If that stamp is far
    older than the configured interval, nobody is being counted and nobody is
    being cut off, while people keep downloading.
    """
    try:
        from hiddifypanel.panel import usage as ws_usage
        from hiddifypanel.cache import redis_client
        raw = redis_client.get(ws_usage.WS_LAST_RUN_KEY)
        if not raw:
            return False
        last = float(raw.decode() if isinstance(raw, bytes) else raw)
        interval = ws_usage.ws_usage_interval()
        idle = datetime.datetime.now().timestamp() - last
        if idle > max(600, interval * max_missed):
            logger.error(f"watashi: the usage accounting has not run for {idle / 60:.0f} minute(s)")
            ws_notify_admins(
                "\u26a0\ufe0f Watashi: the usage accounting has not run for "
                f"{idle / 60:.0f} minutes. Please check hiddify-panel-background-tasks.")
            return True
    except Exception as e:
        logger.warning(f"watashi: the usage heartbeat could not be read ({e})")
    return False


def ws_send_test_notification(uuid: str = None) -> dict:
    """Send one test message, so the bot can be proved without waiting for 80%.

    Used by the "Send a test notification" button on the actions page and by
    `hiddify-panel-cli test-notification`.
    """
    out = {"bot": False, "admins": 0, "user": None, "errors": []}
    if not hconfig(ConfigEnum.telegram_bot_token):
        out["errors"].append("no telegram bot token is saved")
        return out
    if not ws_ensure_bot():
        out["errors"].append("the bot could not be woken with the saved token")
        return out
    out["bot"] = True
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"Watashi test notification\n{when}\nThe telegram notifications are working."
    if uuid:
        user = User.by_uuid(uuid)
        if not user:
            out["errors"].append("no user has that uuid")
        elif not user.telegram_id:
            out["errors"].append("that user has not connected the bot")
        else:
            try:
                from hiddifypanel.panel.commercial.telegrambot import bot
                bot.send_message(user.telegram_id, text + "\n\n" + ws_usage_block(user))
                out["user"] = user.name
            except Exception as e:
                out["errors"].append(str(e))
    out["admins"] = ws_notify_admins(text)
    if not out["admins"] and not out["user"]:
        out["errors"].append("nobody has connected the bot yet: open the bot and press start")
    return out
