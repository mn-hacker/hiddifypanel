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


# Rathole directories
RATHOLE_DIR = "/opt/hiddify-manager/other/rathole"
CONFIG_DIR = "/opt/hiddify-manager/other/rathole"
SERVICE_DIR = "/etc/systemd/system"


class TunnelAdmin(FlaskView):
    """Admin view for managing Rathole tunnels."""
    
    decorators = [login_required({Role.super_admin})]
    
    def index(self):
        """Main tunnel management page."""
        try:
            tunnels = get_all_tunnels()
            core_installed = is_core_installed()
            service_enabled = is_service_enabled()
            stats = {
                'total_tunnels': len(tunnels),
                'active_tunnels': sum(1 for t in tunnels if t.get('status') == 'active'),
                'iran_tunnels': sum(1 for t in tunnels if t.get('type') == 'iran'),
                'kharej_tunnels': sum(1 for t in tunnels if t.get('type') == 'kharej'),
                'core_installed': core_installed,
                'service_enabled': service_enabled
            }
            return render_template('tunnel_management.html', tunnels=tunnels, stats=stats)
        except Exception as e:
            logger.error(f"Error in TunnelAdmin index: {e}")
            return f"<h1>Error</h1><pre>{str(e)}</pre>"
    
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
            service_name = f"rathole-{tunnel_id}.service"
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', service_name],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return jsonify({'success': True, 'message': _('Tunnel restarted successfully')})
            else:
                return jsonify({'success': False, 'message': result.stderr or _('Failed to restart tunnel')})
        except Exception as e:
            logger.error(f"Error restarting tunnel {tunnel_id}: {e}")
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/status/<tunnel_id>', methods=['GET'])
    def tunnel_status(self, tunnel_id):
        """Get status of a specific tunnel."""
        try:
            service_name = f"rathole-{tunnel_id}.service"
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', service_name],
                capture_output=True, text=True, timeout=10
            )
            is_active = result.stdout.strip() == 'active'
            return jsonify({'success': True, 'active': is_active, 'status': result.stdout.strip()})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @route('/toggle/<tunnel_id>', methods=['POST'])
    def toggle_tunnel(self, tunnel_id):
        """Enable or disable a tunnel service."""
        try:
            service_name = f"rathole-{tunnel_id}.service"
            
            # Check current state
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', service_name],
                capture_output=True, text=True, timeout=10
            )
            is_active = result.stdout.strip() == 'active'
            
            if is_active:
                # Disable (stop) the service
                subprocess.run(['sudo', 'systemctl', 'stop', service_name], capture_output=True, timeout=30)
                return jsonify({'success': True, 'enabled': False, 'message': _('Tunnel disabled')})
            else:
                # Enable (start) the service
                subprocess.run(['sudo', 'systemctl', 'start', service_name], capture_output=True, timeout=30)
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
            
            result = subprocess.run(
                ['journalctl', '-u', service_name, '-n', lines, '--no-pager'],
                capture_output=True, text=True, timeout=30
            )
            
            return jsonify({
                'success': True, 
                'logs': result.stdout or _('No logs available'),
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
            
            # First delete the old tunnel
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
            else:
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
            
            # Check current state - if any tunnel is active, disable all; otherwise enable all
            any_active = any(t.get('status') == 'active' for t in tunnels)
            
            for tunnel in tunnels:
                service_name = f"rathole-{tunnel['id']}.service"
                if any_active:
                    # Stop and disable all services (won't start after reboot)
                    subprocess.run(['sudo', 'systemctl', 'stop', service_name], capture_output=True, timeout=30)
                    subprocess.run(['sudo', 'systemctl', 'disable', service_name], capture_output=True, timeout=30)
                else:
                    # Enable and start all services (will start after reboot)
                    subprocess.run(['sudo', 'systemctl', 'enable', service_name], capture_output=True, timeout=30)
                    subprocess.run(['sudo', 'systemctl', 'start', service_name], capture_output=True, timeout=30)
            
            if any_active:
                return jsonify({'success': True, 'enabled': False, 'message': _('All tunnel services disabled')})
            else:
                return jsonify({'success': True, 'enabled': True, 'message': _('All tunnel services enabled')})
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
                except:
                    tunnel_info['status'] = 'unknown'
                
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
            for _, port in service_matches:
                config_ports.append(port)
        
        return {
            'id': name,
            'type': tunnel_type,
            'tunnel_port': tunnel_port,
            'config_ports': config_ports,
            'token': token,
            'transport': transport,
            'remote_addr': remote_addr,
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
    """Destroy a tunnel - remove config and service."""
    try:
        config_path = f"{CONFIG_DIR}/{tunnel_id}.toml"
        service_name = f"rathole-{tunnel_id}.service"
        service_path = f"{SERVICE_DIR}/{service_name}"
        
        # Stop and disable service
        subprocess.run(['sudo', 'systemctl', 'disable', '--now', service_name], 
                      capture_output=True, timeout=30)
        
        # Remove files
        if os.path.exists(config_path):
            os.remove(config_path)
        if os.path.exists(service_path):
            os.remove(service_path)
        
        # Reload systemd
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'], capture_output=True, timeout=30)
        
        return {'success': True}
        
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


