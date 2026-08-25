"""
Device (HWID) Monitoring Admin Page

Shows each user's registered devices (HWID / model / OS / last-seen), their
device-limit status, and lets an admin remove a single device or reset all of
a user's devices. Replaces the old IP-based connection monitoring, which was
unreliable under Iran's CG-NAT.
"""

from flask import render_template, request, jsonify
from flask_classful import FlaskView, route
from flask_babel import gettext as _
from loguru import logger

from hiddifypanel.auth import login_required
# Watashi v12.2.34b: hconfig and ConfigEnum belonged to the access-log
# reader, so they are not imported any more.
from hiddifypanel.models import User, Role
from hiddifypanel.models import get_user_hwids, get_user_hwid_count, delete_user_hwid, reset_user_hwids
from hiddifypanel.panel import hwid_limit


class MonitoringAdmin(FlaskView):
    """Admin view for monitoring user devices (HWID)."""

    decorators = [login_required({Role.super_admin, Role.admin, Role.custom})]

    def index(self):
        """Main device-monitoring page."""
        users = get_all_device_data()
        stats = _build_stats(users)
        os_distribution, device_trend, trend_spike = _build_device_analytics()
        return render_template('monitoring.html', users=users, stats=stats,
                               os_distribution=os_distribution, device_trend=device_trend,
                               trend_spike=trend_spike)

    @route('/api/devices', methods=['GET'])
    def api_devices(self):
        """JSON endpoint for AJAX refresh of the device table."""
        users = get_all_device_data()
        stats = _build_stats(users)
        return jsonify({'users': users, 'stats': stats})

    @route('/device/<uuid>/remove', methods=['POST'])
    def remove_device(self, uuid):
        """Remove a single device (by HWID) from a user."""
        user = User.query.filter(User.uuid == uuid).first()
        if not user:
            return jsonify({'success': False, 'message': _('User not found')})
        hwid = (request.form.get('hwid') or request.values.get('hwid') or '').strip()
        if not hwid:
            return jsonify({'success': False, 'message': _('Device not found')})
        try:
            ok = delete_user_hwid(user.id, hwid)
            if ok:
                return jsonify({'success': True, 'message': _('Device removed successfully')})
            return jsonify({'success': False, 'message': _('Device not found')})
        except Exception as e:
            logger.error(f"Error removing device for {uuid}: {e}")
            return jsonify({'success': False, 'message': str(e)})

    @route('/user/<uuid>/reset-devices', methods=['POST'])
    def reset_devices(self, uuid):
        """Remove all devices for a user."""
        user = User.query.filter(User.uuid == uuid).first()
        if not user:
            return jsonify({'success': False, 'message': _('User not found')})
        try:
            count = reset_user_hwids(user.id)
            return jsonify({'success': True, 'message': _('Removed %(count)s device(s)', count=count)})
        except Exception as e:
            logger.error(f"Error resetting devices for {uuid}: {e}")
            return jsonify({'success': False, 'message': str(e)})

    @route('/devices/reset-over-limit', methods=['POST'])
    def reset_over_limit(self):
        """Reset (remove all) devices for every user currently over their limit."""
        try:
            users = get_all_device_data()
        except Exception as e:
            logger.error(f"Error listing users for bulk reset: {e}")
            return jsonify({'success': False, 'message': str(e)})
        over = [u for u in users if u.get('over_limit')]
        affected = 0
        removed = 0
        for u in over:
            try:
                user = User.query.filter(User.uuid == u['uuid']).first()
                if not user:
                    continue
                cnt = reset_user_hwids(user.id)
                removed += int(cnt or 0)
                affected += 1
            except Exception as e:
                logger.error(f"Bulk reset error for {u.get('uuid')}: {e}")
        if affected == 0:
            return jsonify({'success': True, 'affected': 0, 'removed': 0, 'message': _('No users are over their device limit')})
        return jsonify({'success': True, 'affected': affected, 'removed': removed, 'message': _('Reset %(a)s user(s) and removed %(d)s device(s)', a=affected, d=removed)})

    # Watashi v12.2.34: the standalone per-user log page is gone. It was the
    # last page still wearing the old theme, nothing in the panel linked to
    # it, and the feed it showed is served by the api route below, which the
    # monitoring page opens in a themed dialog.
    @route('/api/user/<uuid>/logs', methods=['GET'])
    def api_user_logs(self, uuid):
        """API endpoint for user logs (for AJAX refresh)."""
        user = User.query.filter(User.uuid == uuid).first()
        if not user:
            return jsonify({'error': _('User not found'), 'logs': []})

        logs = get_user_activity_logs(uuid, user.name)
        return jsonify({'logs': logs, 'user': {'name': user.name, 'uuid': uuid}})


def get_all_device_data():
    """Build the per-user device list shown on the monitoring page.

    Only users that have at least one registered device are included.
    Optimized to prevent N+1 query timeouts.
    """
    users = []
    
    from collections import defaultdict
    devices_by_user = defaultdict(list)
    try:
        from hiddifypanel.models.hwid import UserHWID
        # Fetch all devices at once
        all_devices = UserHWID.query.order_by(UserHWID.last_seen.desc()).all()
        for d in all_devices:
            devices_by_user[d.user_id].append(d)
    except Exception as e:
        logger.error(f"Error loading devices for monitoring: {e}")
        return []

    if not devices_by_user:
        return []

    try:
        # Fetch only the users that have devices
        user_ids_with_devices = list(devices_by_user.keys())
        # To avoid massive IN clauses, fetch all users or chunk them, but typically active users < 100k
        active_users = User.query.filter(User.id.in_(user_ids_with_devices)).all()
    except Exception as e:
        logger.error(f"Error loading users for device monitoring: {e}")
        active_users = []

    for user in active_users:
        if not hwid_limit.is_enabled_for_user(user):
            continue
            
        devices = devices_by_user.get(user.id, [])
        if not devices:
            continue

        limit = hwid_limit.get_effective_limit(user)
        device_count = len(devices)
        over_limit = bool(limit and limit > 0 and device_count > limit)

        device_list = []
        for d in devices:
            os_label = f"{d.device_os} {d.ver_os}".strip()
            device_list.append({
                'hwid': d.hwid,
                'model': d.device_model or _('Unknown device'),
                'os': os_label or _('Unknown device'),
                'last_seen': d.last_seen.strftime('%Y-%m-%d %H:%M') if d.last_seen else '',
                'created_at': d.created_at.strftime('%Y-%m-%d %H:%M') if d.created_at else '',
            })

        users.append({
            'uuid': user.uuid,
            'name': user.name,
            'is_active': bool(getattr(user, 'is_active', True)),
            'enabled': True,
            'limit': limit,
            'device_count': device_count,
            'over_limit': over_limit,
            'devices': device_list,
        })

    # Show users over their limit first, then by device count (desc).
    users.sort(key=lambda u: (not u['over_limit'], -u['device_count']))
    return users


def _build_stats(users):
    """Summary counters for the stat cards."""
    return {
        'users_with_devices': len(users),
        'total_devices': sum(u['device_count'] for u in users),
        'total_users': User.query.count(),
        'users_over_limit': sum(1 for u in users if u['over_limit']),
        'limit_enabled': hwid_limit.is_enabled(),
        'forced': hwid_limit.is_forced(),
    }


def _os_bucket(raw):
    r = str(raw or '').strip().lower()
    if not r:
        return 'Unknown'
    if 'android' in r:
        return 'Android'
    if 'ios' in r or 'iphone' in r or 'ipad' in r:
        return 'iOS'
    if 'mac' in r or 'darwin' in r:
        return 'macOS'
    if 'win' in r:
        return 'Windows'
    if 'linux' in r:
        return 'Linux'
    return str(raw).strip()[:16].title()


def _build_device_analytics():
    """OS distribution, 30-day new-device trend, and a recent-spike alert."""
    import datetime as _dt
    import statistics as _st
    os_counts = {}
    trend_map = {}
    today = _dt.date.today()
    start = today - _dt.timedelta(days=29)
    try:
        from hiddifypanel.models.hwid import UserHWID
        all_devices = UserHWID.query.all()
    except Exception as e:
        logger.error(f"Error loading devices for analytics: {e}")
        all_devices = []

    for d in all_devices:
        bucket = _os_bucket(getattr(d, 'device_os', '') or '')
        os_counts[bucket] = os_counts.get(bucket, 0) + 1
        c = getattr(d, 'created_at', None)
        if c is not None:
            try:
                cd = c.date()
            except Exception:
                cd = None
            if cd is not None and start <= cd <= today:
                trend_map[cd] = trend_map.get(cd, 0) + 1

    os_distribution = [{'label': k, 'count': v} for k, v in sorted(os_counts.items(), key=lambda kv: -kv[1])]

    device_trend = []
    for i in range(30):
        dd = start + _dt.timedelta(days=i)
        device_trend.append({'date': dd.strftime('%m/%d'), 'count': trend_map.get(dd, 0)})

    counts = [x['count'] for x in device_trend]
    trend_spike = None
    if counts:
        mean = sum(counts) / len(counts)
        stdev = _st.pstdev(counts) if len(counts) > 1 else 0
        threshold = max(mean + 2 * stdev, 5)
        for x in device_trend[-7:]:
            if x['count'] >= threshold and x['count'] > mean:
                if trend_spike is None or x['count'] > trend_spike['count']:
                    trend_spike = {'date': x['date'], 'count': x['count'], 'avg': round(mean, 1)}
    return os_distribution, device_trend, trend_spike


def get_user_activity_logs(uuid, user_name):
    """Build the activity feed for one user.

    Watashi v12.2.34: this used to parse the xray access log from disk, which
    reported the addresses a user reached and cost megabytes of reads on
    every open. Only panel-owned facts are reported now: whether the user
    is online, the traffic of the running session, and the last seven
    daily totals. Device statistics live on the monitoring page and are
    built from the device table, never from connection logs.
    """
    logs = []

    try:
        from hiddifypanel.drivers.xray_api import XrayApi
        from hiddifypanel.models import DailyUsage
        import datetime

        xray = XrayApi()

        # Get current traffic stats
        if xray.is_enabled():
            try:
                usage = xray.get_usage_imp(uuid)
                if usage:
                    logs.append({
                        'time': datetime.datetime.now().strftime('%H:%M:%S'),
                        'type': 'traffic',
                        'message': _('Current session traffic') + f': {format_bytes(usage)}',
                        'details': {'bytes': usage}
                    })
            except Exception:
                pass

        # Get daily usage history
        try:
            daily_usages = DailyUsage.query.filter(
                DailyUsage.user_uuid == uuid
            ).order_by(DailyUsage.date.desc()).limit(7).all()

            for du in daily_usages:
                logs.append({
                    'time': du.date.strftime('%Y-%m-%d'),
                    'type': 'daily_usage',
                    'message': _('Daily usage') + f': {format_bytes(du.usage)}',
                    'details': {'usage': du.usage, 'date': str(du.date)}
                })
        except Exception:
            pass

        # Add connection status
        try:
            enabled_users = xray.get_enabled_users() if xray.is_enabled() else {}
            is_online = uuid in enabled_users
            logs.insert(0, {
                'time': datetime.datetime.now().strftime('%H:%M:%S'),
                'type': 'status',
                'message': _('Currently online') if is_online else _('Currently offline'),
                'details': {'online': is_online}
            })
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error getting user logs for {uuid}: {e}")
        logs.append({
            'time': datetime.datetime.now().strftime('%H:%M:%S') if 'datetime' in dir() else 'now',
            'type': 'error',
            'message': _('Error fetching logs') + f': {str(e)}',
            'details': {}
        })

    return logs


def format_bytes(size):
    """Format bytes to human readable string."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"
