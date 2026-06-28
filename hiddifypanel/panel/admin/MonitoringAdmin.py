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
    
    @route('/blocked-ips', methods=['GET'])
    def blocked_ips(self):
        """Page showing all blocked IPs with unblock option."""
        from hiddifypanel.panel.connection_limit import get_all_blocked_ips, get_connection_limit_stats
        
        blocked = get_all_blocked_ips()
        stats = get_connection_limit_stats()
        
        return render_template('blocked_ips.html', 
                               blocked_ips=blocked, 
                               stats=stats)
    
    @route('/api/blocked-ips', methods=['GET'])
    def api_blocked_ips(self):
        """API endpoint for getting blocked IPs (for AJAX refresh)."""
        from hiddifypanel.panel.connection_limit import get_all_blocked_ips, get_connection_limit_stats
        
        blocked = get_all_blocked_ips()
        stats = get_connection_limit_stats()
        
        return jsonify({'blocked_ips': blocked, 'stats': stats})
    
    @route('/unblock-ip/<path:ip>', methods=['POST'])
    def unblock_single_ip(self, ip):
        """Unblock a single IP address."""
        from hiddifypanel.panel.connection_limit import unblock_ip
        
        try:
            result = unblock_ip(ip)
            if result:
                return jsonify({'success': True, 'message': _('IP unblocked successfully')})
            else:
                return jsonify({'success': False, 'message': _('IP not found in blocked list')})
        except Exception as e:
            logger.error(f"Error unblocking IP {ip}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/unblock-all', methods=['POST'])
    def unblock_all(self):
        """Unblock all blocked IPs."""
        from hiddifypanel.panel.connection_limit import unblock_all_ips
        
        try:
            count = unblock_all_ips()
            return jsonify({'success': True, 'message': _('Unblocked %(count)s IPs', count=count)})
        except Exception as e:
            logger.error(f"Error unblocking all IPs: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/unblock-user/<uuid>', methods=['POST'])
    def unblock_user_blocked_ips(self, uuid):
        """Unblock all IPs blocked for a specific user."""
        from hiddifypanel.panel.connection_limit import unblock_user_ips
        
        try:
            count = unblock_user_ips(uuid)
            if count > 0:
                return jsonify({'success': True, 'message': _('Unblocked %(count)s IPs for user', count=count)})
            else:
                return jsonify({'success': False, 'message': _('No blocked IPs found for this user')})
        except Exception as e:
            logger.error(f"Error unblocking user IPs {uuid}: {e}")
            return jsonify({'success': False, 'message': str(e)})


def get_all_active_connections():
    """
    Get detailed active connections for all users.
    Returns list of dicts with user info and their connected IPs.
    Shows ALL active users from database.
    """
    try:
        # Get all active users from database
        # NOTE: is_active is a Python @property (not a DB column), so we must
        # fetch all users first and filter in Python.
        all_users = [u for u in User.query.all() if u.is_active]
        
        # Get online users from user_driver (combines xray + singbox + other drivers)
        online_uuids = set()
        user_ips = defaultdict(set)
        
        try:
            # Primary method: get enabled/online users from all drivers
            enabled_users = user_driver.get_enabled_users()
            for uuid, is_enabled in enabled_users.items():
                if is_enabled:
                    online_uuids.add(uuid)
        except Exception as e:
            logger.debug(f"get_enabled_users failed: {e}")
        
        # Secondary method: get IPs from Redis cache (if connection limit is running)
        try:
            for user in all_users:
                ips = user_driver.get_user_ips(user.uuid)
                if ips:
                    online_uuids.add(user.uuid)
                    user_ips[user.uuid].update(ips)
        except Exception as e:
            logger.debug(f"Get user IPs failed: {e}")
        
        # Build result with ALL active users
        result = []
        for user in all_users:
            uuid = user.uuid
            
            # Get max connections limit
            max_connections = 0
            if user.max_ips and user.max_ips > 0 and user.max_ips < 10000:
                max_connections = user.max_ips
            else:
                try:
                    max_connections = int(hconfig(ConfigEnum.user_limit_default) or "0")
                except (ValueError, TypeError):
                    max_connections = 0
            
            # Get IP list and connection count
            ips = user_ips.get(uuid, set())
            ip_list = list(ips) if ips else []
            connection_count = len(ip_list) if ip_list else (1 if uuid in online_uuids else 0)
            
            # Determine if user is online
            is_online = uuid in online_uuids or connection_count > 0
            
            # Prepare display IP list
            display_ips = ip_list if ip_list else ([_('Online')] if is_online else [_('Offline')])
            
            result.append({
                'uuid': uuid,
                'name': user.name,
                'max_connections': max_connections,
                'current_connections': connection_count,
                'over_limit': max_connections > 0 and connection_count > max_connections,
                'ips': display_ips,
                'is_active': user.is_active,
                'is_online': is_online
            })
        
        # Sort by online first, then over_limit, then by connection count
        result.sort(key=lambda x: (-x['is_online'], -x['over_limit'], -x['current_connections']))
        
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
                        'message': _('Current session traffic') + f': {format_bytes(usage)}',
                        'details': {'bytes': usage}
                    })
            except Exception:
                pass
        
        # Parse access log if enabled (or if user limit is enabled, which requires access log)
        if hconfig(ConfigEnum.access_log_enable) or hconfig(ConfigEnum.user_limit_enable):
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
                    # Fix: Handle tcp:google.com:443 -> google.com
                    clean_dest = re.sub(r'^(tcp|udp):', '', dest) 
                    domain = clean_dest.split(':')[0]
                    
                    # Extract source IP
                    src_match = re.search(r'from\s+(\d+\.\d+\.\d+\.\d+)', line)
                    src_ip = src_match.group(1) if src_match else ""
                    
                    log_entry = {
                        'time': timestamp.split(' ')[-1] if ' ' in timestamp else timestamp,
                        'type': 'access',
                        'message': f'🌐 {domain}',
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
                            'message': f"🌐 {data.get('destination', 'unknown')}",
                            'details': data
                        }
                    except:
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
                            'message': f'📝 {message}',
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
