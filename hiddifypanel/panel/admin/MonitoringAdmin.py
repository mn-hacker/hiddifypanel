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
from hiddifypanel.models import User, Role, hconfig, ConfigEnum
from hiddifypanel.models import get_user_hwids, get_user_hwid_count, delete_user_hwid, reset_user_hwids
from hiddifypanel.panel import hwid_limit


class MonitoringAdmin(FlaskView):
    """Admin view for monitoring user devices (HWID)."""

    decorators = [login_required({Role.super_admin, Role.admin})]

    def index(self):
        """Main device-monitoring page."""
        users = get_all_device_data()
        stats = _build_stats(users)
        return render_template('monitoring.html', users=users, stats=stats)

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

    @route('/user/<uuid>', methods=['GET'])
    def user_logs(self, uuid):
        """View activity logs for a specific user (preserved from the old page)."""
        user = User.query.filter(User.uuid == uuid).first()
        if not user:
            return render_template('user_logs.html', user=None, logs=[], error=_('User not found'))

        logs = get_user_activity_logs(uuid, user.name)
        return render_template('user_logs.html', user=user, logs=logs, error=None)

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
        'users_over_limit': sum(1 for u in users if u['over_limit']),
        'limit_enabled': hwid_limit.is_enabled(),
        'forced': hwid_limit.is_forced(),
    }


def get_user_activity_logs(uuid, user_name):
    """
    Get activity logs for a specific user.
    Returns list of log entries with timestamp, action, and details.
    """
    logs = []

    try:
        from hiddifypanel.drivers.xray_api import XrayApi
        from hiddifypanel.models import DailyUsage, hconfig, ConfigEnum
        import datetime
        import os
        import re

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

        # Parse access log if enabled
        if hconfig(ConfigEnum.access_log_enable):
            access_logs = parse_access_log_for_user(uuid)
            logs.extend(access_logs)

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


def parse_access_log_for_user(uuid, max_entries=100):
    """
    Parse xray/singbox access log and return entries for a specific user.
    Supports multiple log locations and formats.
    """
    import os
    import re
    import glob
    from datetime import datetime

    logs = []

    # Multiple possible log locations
    LOG_PATHS = [
        "/opt/hiddify-manager/log/xray_access.log",
        "/opt/hiddify-manager/xray/access.log",
        "/var/log/xray/access.log",
        "/opt/hiddify-manager/singbox/access.log",
        "/var/log/singbox/access.log",
    ]

    # Also check for rotated logs
    LOG_PATTERNS = [
        "/opt/hiddify-manager/log/xray_access*.log",
        "/opt/hiddify-manager/xray/access*.log",
    ]

    log_files = []

    # Find existing log files
    for path in LOG_PATHS:
        if os.path.exists(path):
            log_files.append(path)

    for pattern in LOG_PATTERNS:
        log_files.extend(glob.glob(pattern))

    log_files = list(set(log_files))  # Remove duplicates

    if not log_files:
        logs.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'type': 'error',
            'message': _('Access log not found. Make sure access logging is enabled in xray config.'),
            'details': {'searched_paths': LOG_PATHS}
        })
        return logs

    try:
        # User identifiers to search for
        user_patterns = [
            f"{uuid}@",
            f"email:{uuid}",
            f"user:{uuid}",
            uuid[:8],  # Short UUID match
        ]

        all_lines = []

        for log_path in log_files:
            try:
                with open(log_path, 'rb') as f:
                    # Read last 500KB or whole file
                    f.seek(0, 2)
                    file_size = f.tell()
                    read_size = min(file_size, 500 * 1024)
                    f.seek(max(0, file_size - read_size))
                    content = f.read().decode('utf-8', errors='ignore')

                lines = content.strip().split('\n')

                # Filter lines for this user
                for line in lines:
                    if any(pattern in line for pattern in user_patterns):
                        all_lines.append(line)
            except Exception as e:
                logger.debug(f"Error reading {log_path}: {e}")
                continue

        if not all_lines:
            logs.append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'status',
                'message': _('No access logs found for this user yet.'),
                'details': {'files_checked': log_files}
            })
            return logs

        # Parse each line - support multiple formats
        for line in all_lines[-max_entries:]:
            try:
                log_entry = None

                # Format 1: "2026/01/02 14:32:15 [email] from [ip:port] accepted [dest]"
                if 'accepted' in line.lower():
                    match = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2})', line)
                    timestamp = match.group(1) if match else datetime.now().strftime('%H:%M:%S')

                    dest_match = re.search(r'(?:accepted|->)\s+(\S+)', line)
                    dest = dest_match.group(1) if dest_match else "unknown"

                    # Extract domain (remove protocol prefix like tcp: or udp:)
                    clean_dest = re.sub(r'^(tcp|udp):', '', dest)
                    domain = clean_dest.split(':')[0]

                    # Extract source IP
                    src_match = re.search(r'from\s+(\d+\.\d+\.\d+\.\d+)', line)
                    src_ip = src_match.group(1) if src_match else ""

                    log_entry = {
                        'time': timestamp.split(' ')[-1] if ' ' in timestamp else timestamp,
                        'type': 'access',
                        'message': f'\U0001F310 {domain}',
                        'details': {
                            'destination': dest,
                            'source_ip': src_ip,
                            'full_timestamp': timestamp
                        }
                    }

                # Format 2: JSON format (singbox)
                elif line.strip().startswith('{'):
                    try:
                        import json
                        data = json.loads(line)
                        log_entry = {
                            'time': data.get('time', datetime.now().strftime('%H:%M:%S')),
                            'type': 'access',
                            'message': f"\U0001F310 {data.get('destination', 'unknown')}",
                            'details': data
                        }
                    except Exception:
                        pass

                # Format 3: Simple format
                else:
                    parts = line.split()
                    if len(parts) >= 4:
                        # Try to extract timestamp
                        timestamp = parts[0] if ':' in parts[0] else datetime.now().strftime('%H:%M:%S')
                        # Get message (rest of line)
                        message = ' '.join(parts[1:4]) if len(parts) > 4 else line[:100]

                        log_entry = {
                            'time': timestamp,
                            'type': 'access',
                            'message': f'\U0001F310 {message}',
                            'details': {'raw': line[:200]}
                        }

                if log_entry:
                    logs.append(log_entry)

            except Exception as e:
                logger.debug(f"Error parsing log line: {e}")
                continue

        logs.reverse()  # Newest first

        # Add summary
        if logs:
            logs.insert(0, {
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'status',
                'message': _('Found %(count)s access log entries', count=len(logs)),
                'details': {'total_entries': len(logs)}
            })

    except Exception as e:
        logger.error(f"Error parsing access log: {e}")
        logs.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'type': 'error',
            'message': f"{_('Error reading logs')}: {str(e)}",
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
