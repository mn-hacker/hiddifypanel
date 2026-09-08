"""Watashi v12.2.88: the live proxy dashboard, on an address of its own.

Round 86 hung this door on the cores view, because that view was already
registered and already carried a permission, so no blueprint had to change.
The address it produced read <admin>/cores/proxy-stats/, which says the page
belongs to the cores page. It does not. The dashboard lists every config the
panel hands out and pings each one, so it answers a network question: is this
config actually alive. That is why the view moved here with its own route
base, and why the menu row moved next to Proxies instead of sitting under
System.

The dashboard itself is a yacd build that hiddify-cli serves on
127.0.0.1:16756. The web server publishes it under <proxy path>/proxy-stats/
with its api under <proxy path>/proxy-stats/api/. That page reads its own
login out of the query string, so this one hands it the address, the port and
the secret, and the admin never meets a form. The secret has to be the same
word in three places: here, in hutils/flask.py and in
other/hiddify-cli/h_client_config.json.
"""
import re

from flask import g, render_template, request
from flask_classful import FlaskView

from hiddifypanel.auth import login_required
from hiddifypanel.models import ConfigEnum, Role, hconfig

WS_STATS_SECRET = 'watashi'
WS_STATS_PATH = 'proxy-stats'
WS_STATS_PORT = 443
WS_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,39}$')


def ws_stats_targets():
    """Every address the dashboard may answer behind on this box.

    haproxy and nginx publish it under proxy_path_admin, but a panel that was
    installed before those paths split still answers on the plain proxy_path,
    and the path the admin is browsing right now is the one already proven to
    reach this process. All of them are handed to the page, which knocks on
    each door and walks through the first that opens, so nobody has to guess
    which spelling this server was built with.
    """
    found = []
    guesses = [getattr(g, 'proxy_path', None)]
    for key in (ConfigEnum.proxy_path_admin, ConfigEnum.proxy_path, ConfigEnum.proxy_path_client):
        try:
            guesses.append(hconfig(key))
        except Exception:
            pass
    for guess in guesses:
        if not guess or not isinstance(guess, str):
            continue
        path = guess.strip().strip('/')
        if not path or path in found or not WS_NAME_RE.match(path.lower()):
            continue
        found.append(path)
    base = (request.host_url or '').replace('http://', 'https://')
    if not base.endswith('/'):
        base = base + '/'
    rows = []
    for path in found:
        ui = base + path + '/' + WS_STATS_PATH + '/'
        rows.append({'path': path, 'ui': ui, 'api': ui + 'api/'})
    return rows


class ProxyStatsAdmin(FlaskView):
    """The door to the live proxy dashboard, with the login already filled in."""

    # the same pair the proxies page beside it allows, so a custom admin who
    # may look at proxies may also check whether they are alive.
    decorators = [login_required({Role.super_admin, Role.custom})]

    def index(self):
        return render_template(
            'proxy_stats.html',
            targets=ws_stats_targets(),
            stats_secret=WS_STATS_SECRET,
            stats_port=WS_STATS_PORT,
        )
