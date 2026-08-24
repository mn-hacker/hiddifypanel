import urllib.request
import json
from flask_classful import FlaskView, route
from flask import render_template, request, redirect, g
from hiddifypanel.hutils.flask import hurl_for
from hiddifypanel.auth import login_required
from flask import current_app as app
from flask_babel import gettext as _


from hiddifypanel import hutils
from hiddifypanel.models import *
from hiddifypanel.panel import hiddify, usage
from hiddifypanel.panel.run_commander import commander, Command


class Actions(FlaskView):

    @login_required(roles={Role.super_admin, Role.custom})
    def index(self):
        return render_template('actions.html', **ac_page_data())

    @login_required(roles={Role.super_admin, Role.custom})
    def viewlogs(self):
        # the log reader lives on the actions page now, so send people there
        try:
            return redirect(hurl_for('admin.Actions:index'))
        except Exception as problem:
            print('the actions page address could not be built', problem)
            log_files = hutils.flask.list_dir_files(f"{app.config['HIDDIFY_CONFIG_PATH']}log/system/")
            return render_template('view_logs.html', log_files=log_files)

    @login_required(roles={Role.super_admin, Role.custom})
    @route('apply_configs', methods=['POST'])
    def apply_configs(self):
        return self.reinstall(False)

    @route('ping')
    @login_required(roles={Role.super_admin, Role.custom})
    def ping(self):
        # the result page asks this over and over to learn when the panel is back on its feet
        return app.response_class(json.dumps({'ok': True}), mimetype='application/json')

    @route('reset', methods=['POST'])
    @login_required(roles={Role.super_admin, Role.custom})
    def reset(self):
        return self.reset2()

    @login_required(roles={Role.super_admin, Role.custom})
    def reset2(self):
        # empty the old restart log first, otherwise the page shows the run before this one
        try:
            commander(Command.truncate, run_in_background=False, log_file='restart')
        except Exception as problem:
            print('the old restart log could not be emptied', problem)

        res = render_template("result.html",
                              out_type="info",
                              out_msg=_("The services are restarting one by one. The panel restarts itself as well, so this page loses touch with it for a few seconds and then picks up on its own."),
                              log_file_url=get_log_api_url(),
                              log_file='restart.log',
                              show_success=True,
                              rs_mode='restart',
                              rs_ping=ac_url('ping'),
                              domains=get_domains())

        # run restart.sh
        commander(Command.restart_services)

        return res

    @login_required(roles={Role.super_admin, Role.custom})
    @route('reinstall', methods=['POST'])
    def reinstall(self, complete_install=True, domain_changed=False):
        return self.reinstall2(complete_install, domain_changed)

    @login_required(roles={Role.super_admin, Role.custom})
    def reinstall2(self, complete_install=True, domain_changed=False):
        if int(hconfig(ConfigEnum.db_version)) < 9:
            return ("Please update your panel before this action.")
        if hutils.node.is_child():
            hutils.node.run_node_op_in_bg(hutils.node.child.sync_with_parent)

        domain_changed = request.args.get("domain_changed", str(domain_changed)).lower() == "true"
        complete_install = request.args.get("complete_install", str(complete_install)).lower() == "true"
        if domain_changed:
            hutils.flask.flash((_('domain.changed_in_domain_warning')), 'info')
        # hutils.flask.flash(f'complete_install={complete_install} domain_changed={domain_changed} ', 'info')
        # return render_template("result.html")
        # hiddify.add_temporary_access()
        file = "install.sh" if complete_install else "apply_configs.sh"
        try:
            server_ip = urllib.request.urlopen('https://v4.ident.me/').read().decode('utf8')
        except BaseException:
            server_ip = "server_ip"

        admin_links = f"<h5 >{_('Admin Links')}</h5><ul>"

        admin_links += f"<li><span class='badge badge-danger'>{_('Not Secure')}</span>: <a class='badge ltr share-link' href='{hiddify.get_account_panel_link(g.account, server_ip,is_https=False)}'>{hiddify.get_account_panel_link(g.account, server_ip,is_https=False)}</a></li>"
        domains = Domain.get_domains()
        # domains=[*domains,f'{server_ip}.sslip.io']

        for d in domains:
            link = hiddify.get_account_panel_link(g.account, d)
            admin_links += f"<li><a target='_blank' class='badge ltr' href='{link}'>{link}</a></li>"

        resp = render_template("result.html",
                               out_type="info",
                               out_msg=_("admin.waiting_for_update") +
                               admin_links,
                               log_file_url=get_log_api_url(),
                               log_file="0-install.log",
                               show_success=True,
                               rs_mode='install',
                               domains=get_domains())

        # subprocess.Popen(f"sudo {config['HIDDIFY_CONFIG_PATH']}/{file} --no-gui".split(" "), cwd=f"{config['HIDDIFY_CONFIG_PATH']}", start_new_session=True)

        # Truncate log file synchronously to fix race condition
        commander(Command.truncate, run_in_background=False, log_file="0-install")

        # run install.sh or apply_configs.sh
        commander(Command.install if complete_install else Command.apply)

        # import time
        # time.sleep(1)
        return resp

    @login_required(roles={Role.super_admin, Role.custom})
    def change_reality_keys(self):
        key = hutils.crypto.generate_x25519_keys()
        set_hconfig(ConfigEnum.reality_private_key, key['private_key'])
        set_hconfig(ConfigEnum.reality_public_key, key['public_key'])
        hutils.flask.flash_config_success(restart_mode=ApplyMode.apply_config, domain_changed=False)
        return redirect(hurl_for('admin.SettingAdmin:index'))

    @ login_required(roles={Role.super_admin, Role.custom})
    def status(self):
        # empty the old status log first, otherwise the page shows the run before this one
        try:
            commander(Command.truncate, run_in_background=False, log_file='status')
        except Exception as problem:
            print('the old status log could not be emptied', problem)

        # run status.sh
        commander(Command.status)
        return render_template("result.html",
                               out_type="info",
                               out_msg=_("The state of every service is being read. The table below fills in as soon as the file lands."),
                               log_file_url=get_log_api_url(),
                               log_file="status.log",
                               show_success=False,
                               rs_mode='status',
                               rs_ping=ac_url('ping'),
                               domains=get_domains())

    @ route('update', methods=['POST'])
    @ login_required(roles={Role.super_admin, Role.custom})
    def update(self):
        return self.update2()

    def update2(self):
        # hiddify.add_temporary_access()
        # run update.sh

        commander(Command.update)

        return render_template("result.html",
                               out_type="success",
                               out_msg=_("Success! Please wait around 5 minutes to make sure everything is updated."),
                               show_success=True,
                               log_file_url=get_log_api_url(),
                               log_file="update.log",
                               rs_mode='install',
                               domains=get_domains())

    def get_some_random_reality_friendly_domain(self):
        test_domain = request.args.get("test_domain")
        import ping3
        from hiddifypanel.hutils.network.auto_ip_selector import IPASN, IPCOUNTRY
        ipv4 = hutils.network.get_ip_str(4)
        server_country = (IPCOUNTRY.get(ipv4) or {}).get('country', {}).get('iso_code', 'unknown')
        server_asn = (IPASN.get(ipv4) or {}).get('autonomous_system_organization', 'unknown')
        res = "<table><tr><th>Domain</th><th>IP</th><th>Country</th><th>ASN</th><th>Ping (ms)</th><th>TCP ping (ms)</th></tr>"
        res += f"<tr><td>Your Server</td><td>{ipv4}</td><td>{server_country}</td><td>{server_asn}</td><td>0</td></tr>"
        import time
        start = time.time()
        for d in [test_domain, *hutils.network.get_random_domains(30)]:
            if not d:
                continue
            if time.time() - start > 20:
                break

            tcp_ping = hutils.network.is_domain_reality_friendly(d)
            if tcp_ping:
                dip = str(hutils.network.get_domain_ip(d))
                dip_country = (IPCOUNTRY.get(dip) or {}).get('country', {}).get('iso_code', 'unknown')
                if dip_country == "IR":
                    continue
                response_time = -1
                try:
                    response_time = ping3.ping(d, unit='ms')
                    if response_time:
                        response_time = int(response_time)
                except BaseException:
                    pass
                dip_asn = (IPASN.get(dip) or {}).get('autonomous_system_organization', 'unknown')
                res += f"<tr><td>{d}</td><td>{dip}</td><td>{dip_country}</td><td>{dip_asn}</td><td>{response_time}</td><td>{tcp_ping}<td></tr>"

        return res + "</table>"

    @login_required(roles={Role.super_admin, Role.custom})
    @route('apply_users', methods=['POST'])
    def apply_users(self):
        """Hand the current user list to the running services."""
        try:
            commander(Command.apply_users)
            told = _('The user list was handed to the services.')
            kind = 'success'
        except Exception as problem:
            print('the user list could not be pushed', problem)
            told = _('The user list could not be handed over. Please look at the log.')
            kind = 'error'
        return render_template("result.html",
                               out_type=kind,
                               out_msg=told,
                               log_file_url=None)

    @login_required(roles={Role.super_admin, Role.custom})
    @route('update_wg_usage', methods=['POST'])
    def update_wg_usage(self):
        """Read the traffic WireGuard users have spent."""
        try:
            commander(Command.update_wg_usage)
            told = _('The WireGuard counters are being read.')
            kind = 'success'
        except Exception as problem:
            print('the wireguard usage could not be read', problem)
            told = _('The WireGuard counters could not be read. Please look at the log.')
            kind = 'error'
        return render_template("result.html",
                               out_type=kind,
                               out_msg=told,
                               log_file_url=None)

    @ login_required(roles={Role.super_admin, Role.custom})
    def update_usage(self):
        color = 'white' if g.darkmode else 'black'
        return render_template("result.html",
                               out_type="info",
                               out_msg=f'<pre class="ltr" style="color:{color};">{json.dumps(usage.update_local_usage(),indent=2)}</pre>',
                               log_file_url=None
                               )


def get_log_api_url():
    return f'/{g.get("new_proxy_path",g.proxy_path)}/api/v2/admin/log/'


def get_domains():
    return [str(d.domain).replace("*", hutils.random.get_random_string(3, 6)) for d in Domain.get_domains(always_add_all_domains=True, always_add_ip=False)]


# ---------------------------------------------------------------------------
# The actions page. Everything the page shows is worked out here, so a slow
# lookup or a missing route can never take the page down.
# ---------------------------------------------------------------------------


def ac_csrf():
    """The token the small forms on the page post along."""
    try:
        from flask_wtf.csrf import generate_csrf
        return generate_csrf()
    except Exception as problem:
        print('the csrf token could not be built', problem)
        return ''


def ac_url(name):
    """An address for one of our own views, or an empty string if it is gone."""
    try:
        return hurl_for('admin.Actions:' + name)
    except Exception as problem:
        print('the action address could not be built', name, problem)
        return ''


def ac_log_url():
    try:
        return get_log_api_url()
    except Exception as problem:
        print('the log address could not be built', problem)
        return ''


def ac_key():
    try:
        return str(g.account.uuid)
    except Exception:
        return ''


def ac_log_files():
    """The log files on disk, with the ones people ask for first up front."""
    try:
        files = hutils.flask.list_dir_files(f"{app.config['HIDDIFY_CONFIG_PATH']}log/system/")
    except Exception as problem:
        print('the log folder could not be read', problem)
        return []
    lead = ['0-install.log', 'update.log', 'status.log', 'restart.log']
    head = [name for name in lead if name in files]
    rest = [name for name in files if name not in head]
    return head + rest


def ac_span(seconds):
    """Read a length of time out in short, plain pieces."""
    try:
        seconds = int(seconds or 0)
    except Exception:
        return '-'
    if seconds < 60:
        return '1m'
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    mins = rest // 60
    out = []
    if days:
        out.append(f'{days}d')
    if hours:
        out.append(f'{hours}h')
    if mins and not days:
        out.append(f'{mins}m')
    return ' '.join(out) or '1m'


def ac_hcfg(name):
    """A setting read that never raises."""
    try:
        return hconfig(getattr(ConfigEnum, name))
    except Exception:
        return None


def ac_yes(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def ac_role():
    try:
        if hutils.node.is_parent():
            return _('Parent')
        if hutils.node.is_child():
            return _('Child')
    except Exception:
        pass
    return _('Standalone')


def ac_version_now():
    try:
        import hiddifypanel
        found = getattr(hiddifypanel, '__version__', '')
        if found:
            return str(found)
    except Exception:
        pass
    try:
        return str(app.jinja_env.globals.get('version', '') or '')
    except Exception:
        return ''


def ac_newest():
    try:
        return str(hutils.utils.get_latest_release_version('hiddifypanel') or '')
    except Exception:
        return ''


def ac_outdated():
    try:
        return bool(hutils.utils.is_panel_outdated())
    except Exception:
        return False


def ac_state():
    """The short server story shown at the top of the page."""
    try:
        figures = hutils.system.system_stats()
    except Exception as problem:
        print('the server figures could not be read', problem)
        figures = {}
    try:
        spare = float(figures.get('disk_total', 0) or 0) - float(figures.get('disk_used', 0) or 0)
        spare = f'{max(0.0, spare):.1f} GB'
    except Exception:
        spare = '-'
    facts = []
    facts.append({'k': _('Server up for'), 'v': ac_span(figures.get('system_uptime')), 'tone': 'g'})
    facts.append({'k': _('Panel up for'), 'v': ac_span(figures.get('panel_uptime')), 'tone': 'b'})
    facts.append({'k': _('Proxy core up for'), 'v': ac_span(figures.get('xray_uptime')), 'tone': 'o'})
    facts.append({'k': _('Open connections'), 'v': str(figures.get('total_connections', 0) or 0), 'tone': 'p'})
    facts.append({'k': _('Addresses connected now'), 'v': str(figures.get('total_unique_ips', 0) or 0), 'tone': 'g'})
    facts.append({'k': _('Free disk space'), 'v': spare, 'tone': 'b'})
    behind = ac_outdated()
    return {
        'version': ac_version_now(),
        'newest': ac_newest() if behind else '',
        'fresh_ready': behind,
        'role': ac_role(),
        'facts': facts,
    }


def ac_jobs_list():
    """Every action this panel can run, told in plain words."""
    jobs = []
    jobs.append({
        'key': 'apply',
        'group': 'daily',
        'icon': 'fa-bolt',
        'tone': 'green',
        'name': _('Apply saved settings'),
        'desc': _('Writes everything you saved into the running services. Run this after you change a setting, a domain or a proxy.'),
        'tag': _('Safe'),
        'tag_kind': 'safe',
        'note': '',
        'btn': _('Apply now'),
        'btn_icon': 'fa-play',
        'btn_kind': 'green',
        'method': 'post',
        'url': ac_url('apply_configs'),
        'ask': _('Apply the saved settings now?'),
        'body': _('The panel rebuilds the service files and loads them again.'),
        'effects': [
            _('Saved settings are written to every service.'),
            _('Services are reloaded one after another.'),
            _('Connected people may drop for a few seconds.'),
        ],
        'ok': _('Yes, apply'),
        'danger': False,
    })
    jobs.append({
        'key': 'restart',
        'group': 'daily',
        'icon': 'fa-rotate',
        'tone': 'orange',
        'name': _('Restart the services'),
        'desc': _('Stops and starts the proxy services again without touching any setting. A good first move when something stopped answering.'),
        'tag': '',
        'tag_kind': 'safe',
        'note': '',
        'btn': _('Restart'),
        'btn_icon': 'fa-rotate',
        'btn_kind': 'orange',
        'method': 'post',
        'url': ac_url('reset'),
        'ask': _('Restart the services now?'),
        'body': _('Nothing is reinstalled and no setting is changed.'),
        'effects': [
            _('Every proxy service stops and starts again.'),
            _('The panel itself restarts too, so it stops answering for a few seconds.'),
            _('The result page waits for the panel and opens the way back on its own.'),
            _('Connected people drop once and come back on their own.'),
            _('It usually takes less than a minute.'),
        ],
        'ok': _('Yes, restart'),
        'danger': False,
    })
    jobs.append({
        'key': 'users',
        'group': 'daily',
        'icon': 'fa-users-gear',
        'tone': 'cyan',
        'name': _('Push the user list'),
        'desc': _('Hands the current list of users to the running services. Use it when a new user cannot connect yet but the settings are already fine.'),
        'tag': _('Safe'),
        'tag_kind': 'safe',
        'note': '',
        'btn': _('Push users'),
        'btn_icon': 'fa-user-check',
        'btn_kind': 'line',
        'method': 'post',
        'url': ac_url('apply_users'),
        'ask': _('Push the user list to the services?'),
        'body': _('Only the user list is sent. Settings and services stay as they are.'),
        'effects': [
            _('Every service learns about the current users.'),
            _('Nobody is disconnected.'),
        ],
        'ok': _('Yes, push'),
        'danger': False,
    })
    jobs.append({
        'key': 'usage',
        'group': 'daily',
        'icon': 'fa-chart-simple',
        'tone': 'blue',
        'name': _('Read the usage counters'),
        'desc': _('Collects how much traffic each user has spent since the last read, and saves it in the panel.'),
        'tag': _('Safe'),
        'tag_kind': 'safe',
        'note': '',
        'btn': _('Read now'),
        'btn_icon': 'fa-arrows-rotate',
        'btn_kind': 'line',
        'method': 'get',
        'url': ac_url('update_usage'),
        'ask': _('Read the usage counters now?'),
        'body': _('The panel asks every service how much each user spent and stores the answer.'),
        'effects': [
            _('User usage numbers are brought up to date.'),
            _('Nothing is restarted.'),
        ],
        'ok': _('Yes, read'),
        'danger': False,
    })
    if ac_yes(ac_hcfg('wireguard_enable')):
        jobs.append({
            'key': 'wgusage',
            'group': 'daily',
            'icon': 'fa-shield-heart',
            'tone': 'cyan',
            'name': _('Read WireGuard usage'),
            'desc': _('Collects the traffic WireGuard users have spent. This one is only needed while WireGuard is switched on.'),
            'tag': _('Safe'),
            'tag_kind': 'safe',
            'note': '',
            'btn': _('Read now'),
            'btn_icon': 'fa-arrows-rotate',
            'btn_kind': 'line',
            'method': 'post',
            'url': ac_url('update_wg_usage'),
            'ask': _('Read the WireGuard usage now?'),
            'body': _('Only the WireGuard counters are read.'),
            'effects': [
                _('WireGuard usage numbers are brought up to date.'),
                _('Nothing is restarted.'),
            ],
            'ok': _('Yes, read'),
            'danger': False,
        })
    jobs.append({
        'key': 'status',
        'group': 'watch',
        'icon': 'fa-heart-pulse',
        'tone': 'cyan',
        'name': _('Check every service'),
        'desc': _('Asks the server which services are alive and prints the answer on the log screen.'),
        'tag': _('Safe'),
        'tag_kind': 'safe',
        'note': '',
        'btn': _('Run the check'),
        'btn_icon': 'fa-signal',
        'btn_kind': 'line',
        'method': 'get',
        'url': ac_url('status'),
        'ask': _('Check every service now?'),
        'body': _('This only looks. Nothing on the server is changed.'),
        'effects': [
            _('The state of every service is written to the log screen.'),
            _('Nothing is restarted.'),
        ],
        'ok': _('Yes, check'),
        'danger': False,
    })
    jobs.append({
        'key': 'logs',
        'group': 'watch',
        'icon': 'fa-file-lines',
        'tone': 'purple',
        'name': _('Open the log reader'),
        'desc': _('The log reader sits at the bottom of this page. Pick any log file and watch it fill in live.'),
        'tag': '',
        'tag_kind': 'safe',
        'note': '',
        'btn': _('Go to the logs'),
        'btn_icon': 'fa-arrow-down',
        'btn_kind': 'ghost',
        'method': 'jump',
        'url': '#ac-logs',
        'ask': '',
        'body': '',
        'effects': [],
        'ok': '',
        'danger': False,
        'quiet': True,
    })
    jobs.append({
        'key': 'update',
        'group': 'fresh',
        'icon': 'fa-cloud-arrow-down',
        'tone': 'blue',
        'name': _('Update the panel'),
        'desc': _('Fetches the newest panel release and installs it. Your settings, users and domains are kept.'),
        'tag': _('Takes a while'),
        'tag_kind': 'warn',
        'note': _('Give it around five minutes and do not close the page.'),
        'btn': _('Update'),
        'btn_icon': 'fa-cloud-arrow-down',
        'btn_kind': 'blue',
        'method': 'post',
        'url': ac_url('update'),
        'ask': _('Update the panel now?'),
        'body': _('The newest release is downloaded and installed on top of this one.'),
        'effects': [
            _('Settings, users and domains are kept.'),
            _('The panel and the services restart during the work.'),
            _('The page may look frozen for a few minutes.'),
        ],
        'ok': _('Yes, update'),
        'danger': False,
    })
    jobs.append({
        'key': 'reinstall',
        'group': 'fresh',
        'icon': 'fa-screwdriver-wrench',
        'tone': 'red',
        'name': _('Reinstall everything'),
        'desc': _('Installs the panel and all services again from scratch. Only reach for this when nothing else helped.'),
        'tag': _('Heavy'),
        'tag_kind': 'red',
        'note': _('Download a backup first, from the Backup page.'),
        'btn': _('Reinstall'),
        'btn_icon': 'fa-screwdriver-wrench',
        'btn_kind': 'red',
        'method': 'post',
        'url': ac_url('reinstall'),
        'ask': _('Reinstall the whole panel?'),
        'body': _('Every service is set up again from the beginning. This is the longest and heaviest job on this page.'),
        'effects': [
            _('All services are installed again.'),
            _('Everyone is disconnected until the work ends.'),
            _('It can take several minutes.'),
            _('Make sure you have a backup before you start.'),
        ],
        'ok': _('Yes, reinstall'),
        'danger': True,
    })
    jobs.append({
        'key': 'reality',
        'group': 'keys',
        'icon': 'fa-key',
        'tone': 'purple',
        'name': _('New Reality keys'),
        'desc': _('Makes a fresh Reality key pair. Use it when you think the old keys became known.'),
        'tag': _('Users must resubscribe'),
        'tag_kind': 'warn',
        'note': _('Everyone connected through Reality needs a new link afterwards.'),
        'btn': _('Make new keys'),
        'btn_icon': 'fa-key',
        'btn_kind': 'orange',
        'method': 'get',
        'url': ac_url('change_reality_keys'),
        'ask': _('Make a new Reality key pair?'),
        'body': _('The panel writes a new private and public key and asks you to apply the settings afterwards.'),
        'effects': [
            _('A new Reality key pair is stored.'),
            _('Every Reality link that is already handed out stops working.'),
            _('You are taken to Settings to apply the change.'),
        ],
        'ok': _('Yes, make new keys'),
        'danger': True,
    })
    jobs.append({
        'key': 'probe',
        'group': 'keys',
        'icon': 'fa-radar',
        'tone': 'cyan',
        'name': _('Find a Reality friendly site'),
        'desc': _('Tries a list of well known sites and shows which of them your server can borrow as a Reality front.'),
        'tag': _('Only looks'),
        'tag_kind': 'safe',
        'note': _('The test takes up to twenty seconds.'),
        'btn': _('Start the test'),
        'btn_icon': 'fa-magnifying-glass',
        'btn_kind': 'ghost',
        'method': 'probe',
        'url': ac_url('get_some_random_reality_friendly_domain'),
        'ask': _('Test sites for Reality now?'),
        'body': _('Nothing on the server is changed. The result is shown right here on this page.'),
        'effects': [
            _('A handful of sites are pinged from this server.'),
            _('The best answers are listed with their ping.'),
        ],
        'ok': _('Yes, test'),
        'danger': False,
    })
    return jobs


def ac_groups():
    plan = [
        ('daily', 'fa-bolt', _('Everyday jobs'), _('The short, safe jobs you reach for most often.')),
        ('watch', 'fa-magnifying-glass', _('Look and listen'), _('Ways to see what the server is doing right now.')),
        ('fresh', 'fa-cloud-arrow-down', _('Update and install'), _('Longer jobs that rebuild the panel. Read the warning before you start one.')),
        ('keys', 'fa-key', _('Keys and probing'), _('Reality keys and the site test that goes with them.')),
    ]
    jobs = ac_jobs_list()
    out = []
    for gid, icon, name, desc in plan:
        mine = [job for job in jobs if job.get('group') == gid]
        if not mine:
            continue
        out.append({'id': gid, 'icon': icon, 'name': name, 'desc': desc, 'n': len(mine), 'jobs': mine})
    return out


def ac_jobs_map():
    out = {}
    for job in ac_jobs_list():
        out[job['key']] = job
    return out


def ac_text():
    """Wording the page itself needs."""
    return {
        'title': _('Actions'),
        'lead': _('Every job the server can run for you, in one place. Each card says what it does before it does it.'),
        'logs_short': _('Logs'),
        'panel_version': _('Panel'),
        'newer_out': _('A newer release is out:'),
        'up_to_date': _('The panel is up to date'),
        'panel_role': _('Role'),
        'state_head': _('How the server is doing'),
        'running': _('Running'),
        'logs_head': _('Log reader'),
        'logs_lead': _('Pick a file and watch it fill in. The newest lines are at the bottom.'),
        'log_live': _('Live log'),
        'follow': _('Follow'),
        'refresh': _('Refresh'),
        'copy': _('Copy'),
        'lines_shown': _('Lines shown:'),
        'log_wait': _('Reading the log...'),
        'no_log_files': _('There is no log file yet.'),
        'what_happens': _('What happens'),
        'never_mind': _('Never mind'),
        'result_head': _('Test result'),
        'close': _('Close'),
    }


def ac_words():
    """Wording the page needs after it is already open."""
    return {
        'goOn': _('Go on'),
        'starting': _('Starting...'),
        'logEmpty': _('This log file is still empty.'),
        'logFail': _('The log could not be read right now.'),
        'noFiles': _('There is no log file yet.'),
        'lastRead': _('Last read at'),
        'copied': _('The log was copied.'),
        'copyFail': _('The log could not be copied.'),
        'nothingToCopy': _('There is nothing to copy yet.'),
        'probing': _('Testing sites, this can take twenty seconds...'),
        'probeFail': _('The test could not be finished.'),
        'levels': {
            'info': _('info'),
            'warn': _('warn'),
            'error': _('error'),
            'ok': _('ok'),
        },
    }


def ac_page_data():
    files = ac_log_files()
    first = files[0] if files else ''
    return {
        'ac_state': ac_state(),
        'ac_groups': ac_groups(),
        'ac_jobs': ac_jobs_map(),
        'ac_text': ac_text(),
        'ac_words': ac_words(),
        'ac_log_files': files,
        'ac_first_log': first,
        'ac_csrf': ac_csrf(),
        'ac_log': {'url': ac_log_url(), 'key': ac_key(), 'first': first},
    }
