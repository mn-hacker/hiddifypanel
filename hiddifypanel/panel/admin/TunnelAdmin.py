"""
Rathole Tunnel Management Admin Page
Manages Rathole v2 tunnels for Iran/Kharej servers.
"""

import os
import subprocess
import json
from flask import render_template, request, jsonify
from flask_classful import FlaskView, route
from flask_babel import gettext as _
from loguru import logger

from hiddifypanel.auth import login_required
from hiddifypanel.models import Role
from hiddifypanel import hutils


# Rathole directories
RATHOLE_DIR = "/opt/hiddify-manager/other/rathole"
CONFIG_DIR = "/opt/hiddify-manager/other/rathole"
SERVICE_DIR = "/etc/systemd/system"


class TunnelAdmin(FlaskView):
    """Admin view for managing Rathole tunnels."""
    
    decorators = [login_required({Role.super_admin, Role.custom})]
    
    def index(self):
        """Main tunnel management page."""
        tunnels = []
        core_installed = False
        try:
            tunnels = get_all_tunnels()
            core_installed = is_core_installed()
        except Exception as e:
            # A slow server must never turn this page into an error page.
            logger.error(f"Error reading the tunnels: {e}")
        stats = {
            'total_tunnels': len(tunnels),
            'active_tunnels': sum(1 for t in tunnels if t.get('status') == 'active'),
            'iran_tunnels': sum(1 for t in tunnels if t.get('type') == 'iran'),
            'kharej_tunnels': sum(1 for t in tunnels if t.get('type') == 'kharej'),
            'core_installed': core_installed,
            'service_enabled': any(t.get('status') == 'active' for t in tunnels),
        }
        return render_template(
            'tunnel_management.html',
            tunnels=tunnels,
            stats=stats,
            tn_urls=ws_tunnel_urls(),
            tn_text=ws_tunnel_text(),
        )
    
    @route('/api/tunnels', methods=['GET'])
    def api_tunnels(self):
        """API endpoint for getting tunnels (for AJAX refresh)."""
        tunnels = get_all_tunnels()
        core_installed = is_core_installed()
        stats = {
            'total_tunnels': len(tunnels),
            'active_tunnels': sum(1 for t in tunnels if t.get('status') == 'active'),
            'iran_tunnels': sum(1 for t in tunnels if t.get('type') == 'iran'),
            'kharej_tunnels': sum(1 for t in tunnels if t.get('type') == 'kharej'),
            'core_installed': core_installed
        }
        return jsonify({'tunnels': tunnels, 'stats': stats})
    
    @route('/install-core', methods=['POST'])
    def install_core(self):
        """Install Rathole Core."""
        try:
            result = run_rathole_command('install')
            if result['success']:
                return jsonify({'success': True, 'message': _('Rathole Core installed successfully')})
            else:
                return jsonify({'success': False, 'message': result.get('error', _('Installation failed'))})
        except Exception as e:
            logger.error(f"Error installing Rathole core: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/uninstall-core', methods=['POST'])
    def uninstall_core(self):
        """Uninstall Rathole Core."""
        try:
            result = run_rathole_command('uninstall')
            if result['success']:
                return jsonify({'success': True, 'message': _('Rathole Core uninstalled successfully')})
            else:
                return jsonify({'success': False, 'message': result.get('error', _('Uninstallation failed'))})
        except Exception as e:
            logger.error(f"Error uninstalling Rathole core: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/create/iran', methods=['POST'])
    def create_iran(self):
        """Create Iran (server) tunnel."""
        try:
            data = request.get_json() or request.form.to_dict()
            
            tunnel_port = data.get('tunnel_port', '').strip()
            config_ports = data.get('config_ports', '').strip()
            token = data.get('token', 'musixal').strip() or 'musixal'
            transport = data.get('transport', 'tcp').strip()
            nodelay = data.get('nodelay', 'true') == 'true'
            heartbeat = data.get('heartbeat', 'true') == 'true'
            ipv6 = data.get('ipv6', 'false') == 'true'
            
            if not tunnel_port or not config_ports:
                return jsonify({'success': False, 'message': _('Tunnel port and config ports are required')})
            
            result = create_iran_tunnel(
                tunnel_port=tunnel_port,
                config_ports=config_ports,
                token=token,
                transport=transport,
                nodelay=nodelay,
                heartbeat=heartbeat,
                ipv6=ipv6
            )
            
            if result['success']:
                return jsonify({'success': True, 'message': _('Iran tunnel created successfully')})
            else:
                return jsonify({'success': False, 'message': result.get('error', _('Failed to create tunnel'))})
                
        except Exception as e:
            logger.error(f"Error creating Iran tunnel: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/create/kharej', methods=['POST'])
    def create_kharej(self):
        """Create Kharej (client) tunnel."""
        try:
            data = request.get_json() or request.form.to_dict()
            
            server_ip = data.get('server_ip', '').strip()
            tunnel_port = data.get('tunnel_port', '').strip()
            config_ports = data.get('config_ports', '').strip()
            token = data.get('token', 'musixal').strip() or 'musixal'
            transport = data.get('transport', 'tcp').strip()
            nodelay = data.get('nodelay', 'true') == 'true'
            heartbeat = data.get('heartbeat', 'true') == 'true'
            
            if not server_ip or not tunnel_port or not config_ports:
                return jsonify({'success': False, 'message': _('Server IP, tunnel port and config ports are required')})
            
            result = create_kharej_tunnel(
                server_ip=server_ip,
                tunnel_port=tunnel_port,
                config_ports=config_ports,
                token=token,
                transport=transport,
                nodelay=nodelay,
                heartbeat=heartbeat
            )
            
            if result['success']:
                return jsonify({'success': True, 'message': _('Kharej tunnel created successfully')})
            else:
                return jsonify({'success': False, 'message': result.get('error', _('Failed to create tunnel'))})
                
        except Exception as e:
            logger.error(f"Error creating Kharej tunnel: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/delete/<tunnel_id>', methods=['POST'])
    def delete_tunnel(self, tunnel_id):
        """Delete a tunnel."""
        try:
            result = destroy_tunnel(tunnel_id)
            if result['success']:
                return jsonify({'success': True, 'message': _('Tunnel deleted successfully')})
            else:
                return jsonify({'success': False, 'message': result.get('error', _('Failed to delete tunnel'))})
        except Exception as e:
            logger.error(f"Error deleting tunnel {tunnel_id}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/restart/<tunnel_id>', methods=['POST'])
    def restart_tunnel(self, tunnel_id):
        """Restart a tunnel service."""
        try:
            side, port = split_tunnel_id(tunnel_id)
            if not side:
                return jsonify({'success': False, 'message': _('This tunnel was not found any more. Refresh the page.')})
            try:
                from hiddifypanel.panel.run_commander import commander, Command
                commander(
                    Command.control_tunnel,
                    run_in_background=False,
                    action='restart',
                    tunnel_type=side,
                    tunnel_port=port
                )
            except Exception as e:
                # If the commander cannot be reached, systemd is asked straight away.
                logger.error(f"Restart through the commander did not work: {e}")
                service_name = f"rathole-{tunnel_id}.service"
                result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', service_name],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode != 0:
                    return jsonify({'success': False, 'message': result.stderr or _('Failed to restart tunnel')})
            return jsonify({'success': True, 'message': _('Tunnel restarted successfully')})
        except Exception as e:
            logger.error(f"Error restarting tunnel {tunnel_id}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/status/<tunnel_id>', methods=['GET'])
    def tunnel_status(self, tunnel_id):
        """Get status of a specific tunnel using commander."""
        try:
            from hiddifypanel.panel.run_commander import commander, Command
            
            # Parse tunnel_id
            if tunnel_id.startswith('iran'):
                tunnel_type = 'iran'
                tunnel_port = tunnel_id[4:]
            elif tunnel_id.startswith('kharej'):
                tunnel_type = 'kharej'
                tunnel_port = tunnel_id[6:]
            else:
                return jsonify({'success': False, 'message': 'Invalid tunnel_id'})
            
            result = commander(
                Command.control_tunnel,
                run_in_background=False,
                action='status',
                tunnel_type=tunnel_type,
                tunnel_port=tunnel_port
            )
            is_active = result.strip() == 'active' if result else False
            return jsonify({'success': True, 'active': is_active, 'status': result.strip() if result else 'unknown'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/toggle/<tunnel_id>', methods=['POST'])
    def toggle_tunnel(self, tunnel_id):
        """Enable or disable a tunnel service using commander."""
        try:
            from hiddifypanel.panel.run_commander import commander, Command
            
            # Parse tunnel_id
            if tunnel_id.startswith('iran'):
                tunnel_type = 'iran'
                tunnel_port = tunnel_id[4:]
            elif tunnel_id.startswith('kharej'):
                tunnel_type = 'kharej'
                tunnel_port = tunnel_id[6:]
            else:
                return jsonify({'success': False, 'message': 'Invalid tunnel_id'})
            
            # Check current state
            result = commander(
                Command.control_tunnel,
                run_in_background=False,
                action='status',
                tunnel_type=tunnel_type,
                tunnel_port=tunnel_port
            )
            is_active = result.strip() == 'active' if result else False
            
            if is_active:
                # Stop the service
                commander(
                    Command.control_tunnel,
                    run_in_background=False,
                    action='stop',
                    tunnel_type=tunnel_type,
                    tunnel_port=tunnel_port
                )
                return jsonify({'success': True, 'enabled': False, 'message': _('Tunnel disabled')})
            else:
                # Start the service
                commander(
                    Command.control_tunnel,
                    run_in_background=False,
                    action='start',
                    tunnel_type=tunnel_type,
                    tunnel_port=tunnel_port
                )
                return jsonify({'success': True, 'enabled': True, 'message': _('Tunnel enabled')})
        except Exception as e:
            logger.error(f"Error toggling tunnel {tunnel_id}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/logs/<tunnel_id>', methods=['GET'])
    def tunnel_logs(self, tunnel_id):
        """Get logs for a tunnel service."""
        try:
            service_name = f"rathole-{tunnel_id}.service"
            lines = request.args.get('lines', '50')
            if not str(lines).isdigit():
                lines = '100'
            
            text = ''
            for how in (['sudo', 'journalctl'], ['journalctl']):
                try:
                    result = subprocess.run(
                        how + ['-u', service_name, '-n', str(lines), '--no-pager'],
                        capture_output=True, text=True, timeout=30
                    )
                    text = (result.stdout or '').strip()
                    if text:
                        break
                except Exception as e:
                    logger.error(f"The log could not be read with {how[0]}: {e}")
            
            return jsonify({
                'success': True, 
                'logs': text or _('No logs available'),
                'tunnel_id': tunnel_id
            })
        except Exception as e:
            logger.error(f"Error getting logs for tunnel {tunnel_id}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/edit/<tunnel_id>', methods=['POST'])
    def edit_tunnel(self, tunnel_id):
        """Edit a tunnel (delete and recreate with new settings)."""
        try:
            data = request.get_json() or request.form.to_dict()
            
            # Determine tunnel type from ID
            if tunnel_id.startswith('iran'):
                tunnel_type = 'iran'
            elif tunnel_id.startswith('kharej'):
                tunnel_type = 'kharej'
            else:
                return jsonify({'success': False, 'message': _('Unknown tunnel type')})
            
            # The old file is kept in hand, so a failed rebuild cannot lose the tunnel.
            old_path = f"{CONFIG_DIR}/{tunnel_id}.toml"
            kept = None
            try:
                if os.path.exists(old_path):
                    with open(old_path, 'r') as old_file:
                        kept = old_file.read()
            except Exception as e:
                logger.error(f"The old tunnel file could not be kept: {e}")

            destroy_result = destroy_tunnel(tunnel_id)
            if not destroy_result['success']:
                return jsonify({'success': False, 'message': _('Failed to remove old tunnel')})
            
            # Then create new tunnel with updated settings
            if tunnel_type == 'iran':
                result = create_iran_tunnel(
                    tunnel_port=data.get('tunnel_port', '').strip(),
                    config_ports=data.get('config_ports', '').strip(),
                    token=data.get('token', 'musixal').strip() or 'musixal',
                    transport=data.get('transport', 'tcp').strip(),
                    nodelay=data.get('nodelay', 'true') == 'true',
                    heartbeat=data.get('heartbeat', 'true') == 'true',
                    ipv6=data.get('ipv6', 'false') == 'true',
                    enabled=data.get('enabled', 'false') == 'true'
                )
            else:
                result = create_kharej_tunnel(
                    server_ip=data.get('server_ip', '').strip(),
                    tunnel_port=data.get('tunnel_port', '').strip(),
                    config_ports=data.get('config_ports', '').strip(),
                    token=data.get('token', 'musixal').strip() or 'musixal',
                    transport=data.get('transport', 'tcp').strip(),
                    nodelay=data.get('nodelay', 'true') == 'true',
                    heartbeat=data.get('heartbeat', 'true') == 'true',
                    enabled=data.get('enabled', 'false') == 'true'
                )
            
            if result['success']:
                return jsonify({'success': True, 'message': _('Tunnel updated successfully')})

            if kept:
                try:
                    with open(old_path, 'w') as old_file:
                        old_file.write(kept)
                    logger.info(f"The old settings of {tunnel_id} were put back.")
                except Exception as e:
                    logger.error(f"The old settings could not be put back: {e}")
            return jsonify({'success': False, 'message': result.get('error', _('Failed to update tunnel'))})
                
        except Exception as e:
            logger.error(f"Error editing tunnel {tunnel_id}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/get/<tunnel_id>', methods=['GET'])
    def get_tunnel(self, tunnel_id):
        """Get tunnel details for editing."""
        try:
            config_path = f"{CONFIG_DIR}/{tunnel_id}.toml"
            if not os.path.exists(config_path):
                return jsonify({'success': False, 'message': _('Tunnel not found')})
            
            tunnel_info = parse_tunnel_config(config_path)
            if tunnel_info:
                return jsonify({'success': True, 'tunnel': tunnel_info})
            else:
                return jsonify({'success': False, 'message': _('Failed to parse tunnel config')})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/master-toggle', methods=['POST'])
    def master_toggle(self):
        """Enable or disable all tunnel services at once."""
        try:
            tunnels = get_all_tunnels()
            if not tunnels:
                return jsonify({'success': False, 'message': _('No tunnels configured')})

            data = request.get_json(silent=True) or request.form.to_dict() or {}
            want = str(data.get('want', '')).strip().lower()
            if want in ('on', 'off'):
                # The page said which way it wants, so nothing has to be guessed.
                turn_on = want == 'on'
            else:
                turn_on = not any(t.get('status') == 'active' for t in tunnels)

            for tunnel in tunnels:
                side, port = split_tunnel_id(tunnel.get('id', ''))
                done = False
                if side:
                    try:
                        from hiddifypanel.panel.run_commander import commander, Command
                        commander(
                            Command.control_tunnel,
                            run_in_background=False,
                            action='enable' if turn_on else 'disable',
                            tunnel_type=side,
                            tunnel_port=port
                        )
                        done = True
                    except Exception as e:
                        logger.error(f"The commander could not switch {tunnel.get('id')}: {e}")
                if not done:
                    service_name = f"rathole-{tunnel['id']}.service"
                    first = 'enable' if turn_on else 'stop'
                    second = 'start' if turn_on else 'disable'
                    subprocess.run(['sudo', 'systemctl', first, service_name], capture_output=True, timeout=30)
                    subprocess.run(['sudo', 'systemctl', second, service_name], capture_output=True, timeout=30)

            if turn_on:
                return jsonify({'success': True, 'enabled': True, 'message': _('All tunnel services enabled')})
            return jsonify({'success': True, 'enabled': False, 'message': _('All tunnel services disabled')})
        except Exception as e:
            logger.error(f"Error toggling master switch: {e}")
            return jsonify({'success': False, 'message': str(e)})


def is_core_installed():
    """Check if Rathole core is installed."""
    return os.path.exists(f"{CONFIG_DIR}/rathole")


def is_service_enabled():
    """Check if any tunnel service is currently running."""
    tunnels = get_all_tunnels()
    return any(t.get('status') == 'active' for t in tunnels)


def get_all_tunnels():
    """Get list of all configured tunnels."""
    tunnels = []
    
    if not os.path.exists(CONFIG_DIR):
        return tunnels
    
    try:
        # Find all .toml config files
        for filename in os.listdir(CONFIG_DIR):
            if not filename.endswith('.toml'):
                continue
            
            config_path = os.path.join(CONFIG_DIR, filename)
            tunnel_info = parse_tunnel_config(config_path)
            
            if tunnel_info:
                # Get service status
                service_name = f"rathole-{tunnel_info['id']}.service"
                try:
                    result = subprocess.run(
                        ['sudo', 'systemctl', 'is-active', service_name],
                        capture_output=True, text=True, timeout=5
                    )
                    tunnel_info['status'] = result.stdout.strip()
                except Exception:
                    tunnel_info['status'] = 'unknown'

                try:
                    boot = subprocess.run(
                        ['sudo', 'systemctl', 'is-enabled', service_name],
                        capture_output=True, text=True, timeout=5
                    )
                    tunnel_info['boot'] = 'enabled' if boot.stdout.strip() == 'enabled' else 'disabled'
                except Exception:
                    tunnel_info['boot'] = 'unknown'
                
                tunnels.append(tunnel_info)
    except Exception as e:
        logger.error(f"Error getting tunnels: {e}")
    
    return tunnels


def parse_tunnel_config(config_path):
    """Parse a .toml config file and return tunnel info."""
    try:
        filename = os.path.basename(config_path)
        name = filename.replace('.toml', '')
        
        # Determine type (iran/kharej)
        if name.startswith('iran'):
            tunnel_type = 'iran'
            tunnel_port = name.replace('iran', '')
        elif name.startswith('kharej'):
            tunnel_type = 'kharej'
            tunnel_port = name.replace('kharej', '')
        else:
            return None
        
        # Parse config file for more details
        config_ports = []
        token = 'musixal'
        transport = 'tcp'
        remote_addr = ''
        nodelay = True
        heartbeat = True
        ipv6 = False
        
        with open(config_path, 'r') as f:
            content = f.read()
            
            # Extract token
            import re
            token_match = re.search(r'default_token\s*=\s*"([^"]+)"', content)
            if token_match:
                token = token_match.group(1)
            
            # Extract remote_addr for kharej
            remote_match = re.search(r'remote_addr\s*=\s*"([^"]+)"', content)
            if remote_match:
                remote_addr = remote_match.group(1)
            
            # Extract service ports
            service_matches = re.findall(r'\[(server|client)\.services\.(\d+)\]', content)
            for _side, port in service_matches:
                if port not in config_ports:
                    config_ports.append(port)

            # These were shown wrongly before, because nobody read them back from the file.
            transport_match = re.search(r'type\s*=\s*"(tcp|udp|tls|websocket|noise)"', content)
            if transport_match:
                transport = transport_match.group(1)
            nodelay = re.search(r'nodelay\s*=\s*false', content) is None
            heartbeat = re.search(r'heartbeat_interval\s*=\s*0', content) is None
            ipv6 = '"[::' in content
        
        return {
            'id': name,
            'type': tunnel_type,
            'tunnel_port': tunnel_port,
            'config_ports': config_ports,
            'token': token,
            'transport': transport,
            'remote_addr': remote_addr,
            'nodelay': nodelay,
            'heartbeat': heartbeat,
            'ipv6': ipv6,
            'config_path': config_path
        }
        
    except Exception as e:
        logger.error(f"Error parsing config {config_path}: {e}")
        return None


def create_iran_tunnel(tunnel_port, config_ports, token, transport, nodelay, heartbeat, ipv6, enabled=False):
    """Create Iran (server) tunnel configuration using commander."""
    try:
        from hiddifypanel.panel.run_commander import commander, Command
        
        # Use commander to create tunnel with root privileges
        result = commander(
            Command.create_tunnel,
            run_in_background=False,
            tunnel_type='iran',
            tunnel_port=tunnel_port,
            config_ports=config_ports,
            token=token,
            transport=transport,
            nodelay='true' if nodelay else 'false',
            heartbeat='true' if heartbeat else 'false',
            ipv6='true' if ipv6 else 'false'
        )
        
        # Check if config was created
        config_path = f"{CONFIG_DIR}/iran{tunnel_port}.toml"
        if os.path.exists(config_path):
            return {'success': True}
        else:
            return {'success': False, 'error': f'Tunnel creation failed. Output: {result}'}
        
    except Exception as e:
        logger.error(f"Error creating Iran tunnel: {e}")
        return {'success': False, 'error': str(e)}


def create_kharej_tunnel(server_ip, tunnel_port, config_ports, token, transport, nodelay, heartbeat, enabled=False):
    """Create Kharej (client) tunnel configuration using commander."""
    try:
        from hiddifypanel.panel.run_commander import commander, Command
        
        # Use commander to create tunnel with root privileges
        result = commander(
            Command.create_tunnel,
            run_in_background=False,
            tunnel_type='kharej',
            tunnel_port=tunnel_port,
            config_ports=config_ports,
            token=token,
            server_ip=server_ip,
            transport=transport,
            nodelay='true' if nodelay else 'false',
            heartbeat='true' if heartbeat else 'false'
        )
        
        # Check if config was created
        config_path = f"{CONFIG_DIR}/kharej{tunnel_port}.toml"
        if os.path.exists(config_path):
            return {'success': True}
        else:
            return {'success': False, 'error': f'Tunnel creation failed. Output: {result}'}
        
    except Exception as e:
        logger.error(f"Error creating Kharej tunnel: {e}")
        return {'success': False, 'error': str(e)}


def destroy_tunnel(tunnel_id):
    """Destroy a tunnel - remove config and service using commander."""
    try:
        from hiddifypanel.panel.run_commander import commander, Command
        
        # Parse tunnel_id to get type and port (e.g., "kharej8080" -> type="kharej", port="8080")
        if tunnel_id.startswith('iran'):
            tunnel_type = 'iran'
            tunnel_port = tunnel_id[4:]
        elif tunnel_id.startswith('kharej'):
            tunnel_type = 'kharej'
            tunnel_port = tunnel_id[6:]
        else:
            return {'success': False, 'error': f'Invalid tunnel_id format: {tunnel_id}'}
        
        # Use commander to delete tunnel with root privileges
        result = commander(
            Command.delete_tunnel,
            run_in_background=False,
            tunnel_type=tunnel_type,
            tunnel_port=tunnel_port
        )
        
        # Check if config was removed
        config_path = f"{CONFIG_DIR}/{tunnel_id}.toml"
        if not os.path.exists(config_path):
            return {'success': True}
        else:
            return {'success': False, 'error': f'Tunnel deletion failed. Output: {result}'}
        
    except Exception as e:
        logger.error(f"Error destroying tunnel {tunnel_id}: {e}")
        return {'success': False, 'error': str(e)}


def run_rathole_command(action):
    """Run Rathole installation/uninstallation using commander."""
    try:
        from hiddifypanel.panel.run_commander import commander, Command
        
        if action == 'install':
            # Use commander to run install-rathole (runs as root via sudoers)
            result = commander(Command.install_rathole, run_in_background=False)
            
            # Check if rathole was installed
            if os.path.exists(f"{CONFIG_DIR}/rathole"):
                return {'success': True}
            else:
                return {'success': False, 'error': f'Installation failed. Output: {result}'}
        
        elif action == 'uninstall':
            # Use commander to run uninstall-rathole (runs as root via sudoers)
            result = commander(Command.uninstall_rathole, run_in_background=False)
            
            # Check if rathole was removed
            if not os.path.exists(f"{CONFIG_DIR}/rathole"):
                return {'success': True}
            else:
                return {'success': False, 'error': f'Uninstallation failed. Output: {result}'}
        
        return {'success': False, 'error': f'Unknown action: {action}'}
        
    except Exception as e:
        logger.error(f"Error running rathole command: {e}")
        return {'success': False, 'error': str(e)}


def split_tunnel_id(tunnel_id):
    """Split a name such as kharej8080 into its side and its port."""
    name = str(tunnel_id or '')
    if name.startswith('iran'):
        return 'iran', name[4:]
    if name.startswith('kharej'):
        return 'kharej', name[6:]
    return '', ''


def ws_tunnel_urls():
    """Every address the page needs, built here, so a route that moved can never break the page."""
    plain = {
        'index': 'admin.TunnelAdmin:index',
        'list': 'admin.TunnelAdmin:api_tunnels',
        'install': 'admin.TunnelAdmin:install_core',
        'uninstall': 'admin.TunnelAdmin:uninstall_core',
        'iran': 'admin.TunnelAdmin:create_iran',
        'kharej': 'admin.TunnelAdmin:create_kharej',
        'master': 'admin.TunnelAdmin:master_toggle',
    }
    with_id = {
        'toggle': 'admin.TunnelAdmin:toggle_tunnel',
        'restart': 'admin.TunnelAdmin:restart_tunnel',
        'delete': 'admin.TunnelAdmin:delete_tunnel',
        'edit': 'admin.TunnelAdmin:edit_tunnel',
        'get': 'admin.TunnelAdmin:get_tunnel',
        'logs': 'admin.TunnelAdmin:tunnel_logs',
        'status': 'admin.TunnelAdmin:tunnel_status',
    }
    out = {}
    for key, endpoint in plain.items():
        try:
            out[key] = hutils.flask.hurl_for(endpoint)
        except Exception as e:
            logger.error(f"The address of {endpoint} could not be built: {e}")
            out[key] = ''
    for key, endpoint in with_id.items():
        try:
            out[key] = hutils.flask.hurl_for(endpoint, tunnel_id='__ID__')
        except Exception as e:
            logger.error(f"The address of {endpoint} could not be built: {e}")
            out[key] = ''
    return out


def ws_tunnel_text():
    """Every word the page says while it works, translated on the server."""
    return {
        'copied': _('It was copied.'),
        'copyFail': _('It could not be copied. Copy it by hand.'),
        'netFail': _('The panel did not answer.'),
        'noRoute': _('This address is not open on this panel.'),
        'reading': _('Reading...'),
        'wrong': _('Something did not go through.'),
        'done': _('It is done.'),
        'working': _('Working...'),
        'yes': _('Yes, go ahead'),
        'editTtl': _('Edit Tunnel'),
        'newIran': _('Build the Iran side'),
        'newKharej': _('Build the Kharej side'),
        'editHint': _('Saving means the tunnel is built again, so it goes quiet for a moment.'),
        'iranHint': _('This tunnel will listen for connections from Kharej servers.'),
        'kharejHint': _('This tunnel will connect to an Iran server.'),
        'save': _('Save'),
        'build': _('Build the tunnel'),
        'needIp': _('The address of the Iran server has to be filled in.'),
        'needPort': _('The tunnel port has to be filled in.'),
        'badPort': _('A port has to be a number between 1024 and 65535.'),
        'needPorts': _('The ports to forward have to be filled in.'),
        'isOn': _('The tunnel is on now.'),
        'isOff': _('The tunnel is off now.'),
        'running': _('Running'),
        'stopped': _('Stopped'),
        'restartTtl': _('Restart this tunnel?'),
        'restartTx': _('The tunnel goes down for a breath and comes back.'),
        'restartGo': _('Yes, restart it'),
        'dropTtl': _('Delete this tunnel?'),
        'dropTx': _('The tunnel and its service are removed for good.'),
        'dropGo': _('Yes, delete it'),
        'logTtl': _('The log of @ID@'),
        'logEmpty': _('The log is empty.'),
        'installGo': _('Install the core'),
        'uninstTtl': _('Remove the Rathole core?'),
        'uninstTx': _('Are you sure you want to uninstall Rathole Core? This will remove all tunnels and configurations.'),
        'uninstGo': _('Yes, remove the core'),
        'allOnTtl': _('Turn every tunnel on?'),
        'allOffTtl': _('Turn every tunnel off?'),
        'allOnTx': _('Every tunnel on this server starts, and comes up again after a reboot.'),
        'allOffTx': _('Every tunnel on this server stops, and stays down after a reboot.'),
        'goOn': _('Yes, turn them on'),
        'goOff': _('Yes, turn them off'),
        'noneYet': _('No tunnels configured'),
    }
