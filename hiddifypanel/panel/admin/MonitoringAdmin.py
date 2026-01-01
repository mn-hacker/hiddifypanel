"""
Connection Monitoring Admin Page
Displays active connections, IPs, and allows disconnecting users.
"""

from flask import render_template, request, jsonify
from flask_classful import FlaskView, route
from flask_babel import gettext as _
from collections import defaultdict
from loguru import logger

from hiddifypanel.auth import login_required
from hiddifypanel.models import User, Role, hconfig, ConfigEnum
from hiddifypanel.drivers import user_driver
from hiddifypanel import hutils


class MonitoringAdmin(FlaskView):
    """Admin view for monitoring active connections."""
    
    decorators = [login_required({Role.super_admin, Role.admin})]
    
    def index(self):
        """Main monitoring page."""
        connections_data = get_all_active_connections()
        stats = {
            'total_users_online': len(connections_data),
            'total_connections': sum(len(u.get('ips', [])) for u in connections_data),
            'users_over_limit': sum(1 for u in connections_data if u.get('over_limit', False)),
            'limit_enabled': hconfig(ConfigEnum.user_limit_enable)
        }
        return render_template('monitoring.html', connections=connections_data, stats=stats)
    
    @route('/api/connections', methods=['GET'])
    def api_connections(self):
        """API endpoint for getting active connections (for AJAX refresh)."""
        connections_data = get_all_active_connections()
        stats = {
            'total_users_online': len(connections_data),
            'total_connections': sum(len(u.get('ips', [])) for u in connections_data),
            'users_over_limit': sum(1 for u in connections_data if u.get('over_limit', False)),
            'limit_enabled': hconfig(ConfigEnum.user_limit_enable)
        }
        return jsonify({'connections': connections_data, 'stats': stats})
    
    @route('/disconnect/<uuid>', methods=['POST'])
    def disconnect_user(self, uuid):
        """Disconnect all connections for a user."""
        try:
            user = User.query.filter(User.uuid == uuid).first()
            if not user:
                return jsonify({'success': False, 'message': _('User not found')})
            
            # Remove and re-add user to disconnect
            user_driver.remove_client(user)
            import time
            time.sleep(0.5)
            if user.is_active:
                user_driver.add_client(user)
            
            return jsonify({'success': True, 'message': _('User disconnected successfully')})
        except Exception as e:
            logger.error(f"Error disconnecting user {uuid}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/user/<uuid>', methods=['GET'])
    def user_logs(self, uuid):
        """View logs for a specific user."""
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


def get_all_active_connections():
    """
    Get detailed active connections for all users.
    Returns list of dicts with user info and their connected IPs.
    """
    try:
        from hiddifypanel.drivers.xray_api import XrayApi
        xray = XrayApi()
        
        if not xray.is_enabled():
            return []
        
        xray_client = xray.get_xray_client()
        
        # Get online users with their IPs
        user_ips = defaultdict(set)
        
        try:
            # Try to get stats that include IP info
            stats = xray_client.stats_query('user', reset=False)
            for stat in stats:
                if "user>>>" not in stat.name:
                    continue
                parts = stat.name.split(">>>")
                if len(parts) >= 2:
                    uuid_part = parts[1].split("@")[0]
                    if uuid_part:
                        user_ips[uuid_part].add("connected")
        except Exception as e:
            logger.debug(f"Stats query failed: {e}")
        
        # Alternative: Try to get IPs from access log or API
        try:
            online_ips = xray.get_user_ips()  # This might need to be implemented
            for uuid, ips in online_ips.items():
                user_ips[uuid].update(ips)
        except Exception:
            pass
        
        # Build result with user details
        result = []
        for uuid, ips in user_ips.items():
            user = User.query.filter(User.uuid == uuid).first()
            if not user:
                continue
            
            # Get max connections limit
            max_connections = 0
            if user.max_ips and user.max_ips > 0 and user.max_ips < 10000:
                max_connections = user.max_ips
            else:
                try:
                    max_connections = int(hconfig(ConfigEnum.user_limit_default) or "0")
                except (ValueError, TypeError):
                    max_connections = 0
            
            ip_list = list(ips) if ips else ["unknown"]
            connection_count = len(ip_list) if ip_list[0] != "connected" else 1
            
            result.append({
                'uuid': uuid,
                'name': user.name,
                'max_connections': max_connections,
                'current_connections': connection_count,
                'over_limit': max_connections > 0 and connection_count > max_connections,
                'ips': ip_list,
                'is_active': user.is_active
            })
        
        # Sort by over_limit first, then by connection count
        result.sort(key=lambda x: (-x['over_limit'], -x['current_connections']))
        
        return result
        
    except Exception as e:
        logger.exception(f"Error getting active connections: {e}")
        return []


def get_ip_location(ip):
    """
    Get location info for an IP address.
    Uses free IP geolocation service.
    """
    try:
        import requests
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,countryCode", timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return {
                    'country': data.get('country', 'Unknown'),
                    'city': data.get('city', ''),
                    'country_code': data.get('countryCode', '').lower()
                }
    except Exception:
        pass
    return {'country': 'Unknown', 'city': '', 'country_code': ''}


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
                        'message': f'Current session traffic: {format_bytes(usage)}',
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
                    'message': f'Daily usage: {format_bytes(du.usage)}',
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
                'message': 'Currently online' if is_online else 'Currently offline',
                'details': {'online': is_online}
            })
        except Exception:
            pass
            
    except Exception as e:
        logger.error(f"Error getting user logs for {uuid}: {e}")
        logs.append({
            'time': datetime.datetime.now().strftime('%H:%M:%S') if 'datetime' in dir() else 'now',
            'type': 'error',
            'message': f'Error fetching logs: {str(e)}',
            'details': {}
        })
    
    return logs


def parse_access_log_for_user(uuid, max_entries=50):
    """
    Parse xray access log and return entries for a specific user.
    """
    import os
    import re
    
    ACCESS_LOG_PATH = "/opt/hiddify-manager/log/xray_access.log"
    logs = []
    
    try:
        if not os.path.exists(ACCESS_LOG_PATH):
            return logs
        
        # Read last N lines efficiently
        with open(ACCESS_LOG_PATH, 'rb') as f:
            # Seek to end and read backwards to get last lines
            f.seek(0, 2)
            file_size = f.tell()
            
            # Read last 100KB or whole file
            read_size = min(file_size, 100 * 1024)
            f.seek(-read_size, 2)
            content = f.read().decode('utf-8', errors='ignore')
        
        lines = content.strip().split('\n')
        
        # Parse each line for this user
        # Format: "2026/01/02 14:32:15 [email] from [ip:port] accepted [dest]"
        user_email = f"{uuid}@hiddify.com"
        user_lines = [l for l in lines if user_email in l]
        
        # Get last max_entries
        for line in user_lines[-max_entries:]:
            try:
                # Extract timestamp and destination
                parts = line.split(' ')
                if len(parts) >= 6:
                    timestamp = f"{parts[0]} {parts[1]}"
                    
                    # Find destination (usually after "accepted")
                    dest = ""
                    if 'accepted' in line:
                        dest_match = re.search(r'accepted\s+(\S+)', line)
                        if dest_match:
                            dest = dest_match.group(1)
                    elif '->' in line:
                        dest_match = re.search(r'->\s*(\S+)', line)
                        if dest_match:
                            dest = dest_match.group(1)
                    
                    # Extract domain from destination
                    if dest:
                        # Remove port if exists
                        domain = dest.split(':')[0] if ':' in dest else dest
                        
                        logs.append({
                            'time': timestamp.split(' ')[1] if ' ' in timestamp else timestamp,
                            'type': 'access',
                            'message': f'Visited: {domain}',
                            'details': {'destination': dest, 'full_line': line[:200]}
                        })
            except Exception:
                continue
        
        logs.reverse()  # Newest first
        
    except Exception as e:
        logger.debug(f"Error parsing access log: {e}")
    
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
