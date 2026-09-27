import telebot
from flask import request
from apiflask import abort
from flask_restful import Resource
import time

from hiddifypanel.models import *
from hiddifypanel import Events
from hiddifypanel.cache import cache
logger = telebot.logger


class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        """Improved error handling for Telegram bot exceptions"""
        error_msg = str(exception)
        logger.error(f"Telegram bot error: {error_msg}")
        
        try:
            # Attempt recovery based on error type
            if "webhook" in error_msg.lower():
                if hasattr(bot, 'remove_webhook'):
                    bot.remove_webhook()
                    logger.info("Removed webhook due to error")
            elif "connection" in error_msg.lower():
                # Wait and retry for connection issues
                time.sleep(5)
                return True  # Indicates retry
        except Exception as e:
            logger.error(f"Error during recovery attempt: {str(e)}")
        
        return False  # Don't retry for unknown errors


bot = telebot.TeleBot("1:2", parse_mode="HTML", threaded=False, exception_handler=ExceptionHandler())
bot.username = ''


# watashi v12.2.130cn: Domain.get_panel_link() hands back whatever row the
# database happens to return first. It does not look at enable, and it counts
# relay and worker domains, which never serve the admin panel. On one server
# the first row was the direct domain and the bot worked; on the next one it
# was a relay and telegram posted every update into a void. Same panel, same
# version, one bot alive and one dead. The webhook now asks for a domain that
# can really answer, in the order of how likely it is to answer.
WS_HOOK_ORDER = ['direct', 'old_xtls_direct', 'cdn', 'auto_cdn_ip', 'sub_link_only']


def ws_is_bare_ip(name):
    """True for 1.2.3.4 and for a v6 address, which cannot hold a public cert."""
    text = str(name or '')
    if ':' in text:
        return True
    bits = text.split('.')
    return len(bits) == 4 and all(b.isdigit() for b in bits)


def ws_panel_domain():
    """The domain telegram should post to, or None when there is nothing usable."""
    try:
        rows = Domain.query.filter(Domain.child_id == Child.current().id).all()
    except Exception as e:
        logger.error(f'watashi: cannot read the domains: {e}')
        rows = []
    seats = []
    for row in rows:
        if getattr(row, 'enable', True) is False:
            continue
        mode = str(getattr(row.mode, 'value', row.mode) or '')
        if mode not in WS_HOOK_ORDER:
            continue
        name = str(row.domain or '')
        if not name or ws_is_bare_ip(name):
            continue
        # a real name first, a free sslip.io name only if nothing else is there
        seats.append((WS_HOOK_ORDER.index(mode), 1 if 'sslip.io' in name else 0, row.id, name))
    if seats:
        seats.sort()
        return seats[0][3]
    return Domain.get_panel_link()


def ws_hook_url():
    """The address this panel wants telegram to post every update to."""
    domain = ws_panel_domain()
    if not domain:
        return ''
    return f"https://{domain}/{hconfig(ConfigEnum.proxy_path_admin)}/{AdminUser.get_super_admin_uuid()}/api/v1/tgbot/"


def ws_start_links(uuid=None):
    """The two ways an admin starts the bot, the deep one and the web one."""
    name = bot.username or ''
    who = str(uuid or AdminUser.get_super_admin_uuid() or '')
    if not name or not who:
        return {}
    return {
        'username': name,
        'deep': f'tg://resolve?domain={name}&start=admin_{who}',
        'web': f'https://t.me/{name}?start=admin_{who}',
    }


def ws_webhook_report():
    """What telegram itself says, next to what this panel wanted. Never raises."""
    out = {'token': False, 'username': '', 'want': '', 'have': '', 'ok': False,
           'pending': 0, 'last_error': '', 'last_error_at': '', 'ip': '',
           'domain': '', 'trouble': ''}
    try:
        token = hconfig(ConfigEnum.telegram_bot_token)
        if not token:
            out['trouble'] = 'no telegram bot token is set in this panel'
            return out
        out['token'] = True
        bot.token = token
        out['domain'] = ws_panel_domain() or ''
        out['want'] = ws_hook_url()
        try:
            out['username'] = bot.get_me().username or ''
        except BaseException as e:
            out['trouble'] = f'telegram will not say who this bot is: {e}'
            return out
        try:
            info = bot.get_webhook_info()
        except BaseException as e:
            out['trouble'] = f'telegram will not say where the webhook points: {e}'
            return out
        out['have'] = info.url or ''
        out['pending'] = int(getattr(info, 'pending_update_count', 0) or 0)
        out['ip'] = str(getattr(info, 'ip_address', '') or '')
        out['last_error'] = str(getattr(info, 'last_error_message', '') or '')
        stamp = getattr(info, 'last_error_date', None)
        if stamp:
            try:
                from datetime import datetime, timezone
                out['last_error_at'] = datetime.fromtimestamp(int(stamp), timezone.utc).isoformat()
            except Exception:
                out['last_error_at'] = str(stamp)
        out['ok'] = bool(out['want']) and out['have'] == out['want']
    except Exception as e:
        out['trouble'] = f'the check itself broke: {e}'
    return out


@cache.cache(1000)
def register_bot_cached(set_hook=False, remove_hook=False):
    return register_bot(set_hook, remove_hook)


def register_bot(set_hook=False, remove_hook=False):
    try:
        global bot
        token = hconfig(ConfigEnum.telegram_bot_token)
        if token:
            bot.token = hconfig(ConfigEnum.telegram_bot_token)
            try:
                bot.username = bot.get_me().username
            except BaseException:
                pass
            if remove_hook:
                bot.remove_webhook()
            # watashi v12.2.130cn: the picker, not the first row of the table
            hook = ws_hook_url()
            if not hook:
                raise Exception('Cannot get valid domain for setting telegram bot webhook')
            if set_hook:
                bot.set_webhook(url=hook)
    except Exception as e:
        logger.error(e)
        


def ws_ensure_webhook():
    """watashi v12.2.130cf: ask telegram where the webhook points and rewrite it
    only when it is wrong. Boot used to skip this whenever bot.username was already
    filled, which is the normal case, so the hook was only ever written by the
    settings form - the page the panel password reset walks through. That is why the
    bot looked like it needed the password removed before it would answer.
    Never raises: a dead telegram must not keep the panel from booting."""
    try:
        token = hconfig(ConfigEnum.telegram_bot_token)
        if not token:
            return False
        bot.token = token
        want = ws_hook_url()
        if not want:
            logger.error('watashi: no panel domain yet, telegram webhook left alone')
            return False
        try:
            here = bot.get_webhook_info().url or ''
        except BaseException as e:
            logger.error(f'watashi: cannot read the telegram webhook: {e}')
            return False
        if here == want:
            return False
        logger.error(f'watashi: telegram webhook was "{here}", setting it to "{want}"')
        try:
            register_bot_cached.invalidate_all()
        except BaseException:
            pass
        register_bot(set_hook=True)
        return True
    except Exception as e:
        logger.error(f'watashi: telegram webhook sync failed: {e}')
        return False


def init_app(app):
    with app.app_context():
        global bot
        token = hconfig(ConfigEnum.telegram_bot_token)
        if token:
            bot.token = token
            try:
                bot.username = bot.get_me().username
            except BaseException:
                pass


class TGBotResource(Resource):
    def post(self):
        try:
            if request.headers.get('content-type') == 'application/json':
                json_string = request.get_data().decode('utf-8')
                update = telebot.types.Update.de_json(json_string)
                bot.process_new_updates([update])
                return ''
            else:
                abort(403)
        except Exception as e:
            print("Error", e)
            import traceback
            traceback.print_exc()
            return "", 500
