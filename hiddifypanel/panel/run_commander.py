from typing import List
from strenum import StrEnum
import subprocess
import os


class Command(StrEnum):
    apply = 'apply'
    install = 'install'
    # reinstall = 'reinstall'
    update = 'update'
    status = 'status'
    restart_services = 'restart-services'
    temporary_short_link = 'temporary-short-link'
    temporary_access = 'temporary-access'
    update_usage = 'update-usage'
    get_cert = 'get-cert'
    apply_users = 'apply-users'
    update_wg_usage = 'update-wg-usage'
    install_rathole = 'install-rathole'
    uninstall_rathole = 'uninstall-rathole'
    create_tunnel = 'create-tunnel'
    delete_tunnel = 'delete-tunnel'
    control_tunnel = 'control-tunnel'


def commander(command: Command, run_in_background=True, **kwargs: str | int) -> str | None:
    """
    Run the commander based on the given command type.
    Args:
        command: The type of command to run.
        run_in_background: Whether to run the command in the background.
        **kwargs: Additional arguments to pass to the commander. Accepts the following:
                  url, slug, period for the temporary-short-link command.
                  port for the temporary-access command.
                  domain for the get-cert command
    """
    base_cmd: List[str] = [
        'sudo',
        os.path.join(
            os.environ['HIDDIFY_CONFIG_PATH'], 'common/commander.py')
    ]

    if command == Command.apply:
        base_cmd.append('apply')
    elif command == Command.install:
        base_cmd.append('install')
    elif command == Command.update:
        base_cmd.append('update')
    elif command == Command.status:
        base_cmd.append('status')
    elif command == Command.restart_services:
        base_cmd.append('restart-services')
    elif command == Command.apply_users:
        base_cmd.append('apply-users')
    elif command == Command.temporary_short_link:
        url = str(kwargs.get('url', ''))
        slug = str(kwargs.get('slug', ''))
        period = kwargs.get('period', '')

        if not url or not slug:
            raise Exception("Invalid input passed to the run_commander function for temporary-short-link command")

        base_cmd.append('temporary-short-link')
        base_cmd.extend(['--url', url, '--slug', slug])
        if period:
            base_cmd.extend(['--period', str(period)])
    elif command == Command.temporary_access:
        port = str(kwargs.get('port'))
        if not port or not port.isnumeric():
            raise Exception("Invalid input passed to the run_commander function for temporary-access command")

        base_cmd.append('temporary-access')
        base_cmd.extend(['--port', port])
    elif command == Command.update_usage:
        base_cmd.append('update-usage')
    elif command == Command.get_cert:
        domain = str(kwargs.get('domain'))
        if not domain:
            raise Exception("Invalid input passed to the run_commander function for get-cert command")
        base_cmd.extend(['get-cert', '--domain', domain])
    elif command == Command.update_wg_usage:
        base_cmd.append('update-wg-usage')
    elif command == Command.install_rathole:
        base_cmd.append('install-rathole')
    elif command == Command.uninstall_rathole:
        base_cmd.append('uninstall-rathole')
    elif command == Command.create_tunnel:
        tunnel_type = str(kwargs.get('tunnel_type', ''))
        tunnel_port = str(kwargs.get('tunnel_port', ''))
        config_ports = str(kwargs.get('config_ports', ''))
        token = str(kwargs.get('token', 'musixal'))
        server_ip = str(kwargs.get('server_ip', ''))
        transport = str(kwargs.get('transport', 'tcp'))
        nodelay = str(kwargs.get('nodelay', 'true'))
        heartbeat = str(kwargs.get('heartbeat', 'true'))
        ipv6 = str(kwargs.get('ipv6', 'false'))
        
        if not tunnel_type or not tunnel_port or not config_ports:
            raise Exception("Invalid input: tunnel_type, tunnel_port, and config_ports are required")
        
        base_cmd.extend(['create-tunnel', '--type', tunnel_type, '--tunnel-port', tunnel_port,
                        '--config-ports', config_ports, '--token', token])
        if server_ip:
            base_cmd.extend(['--server-ip', server_ip])
        base_cmd.extend(['--transport', transport, '--nodelay', nodelay, 
                        '--heartbeat', heartbeat, '--ipv6', ipv6])
    elif command == Command.delete_tunnel:
        tunnel_type = str(kwargs.get('tunnel_type', ''))
        tunnel_port = str(kwargs.get('tunnel_port', ''))
        
        if not tunnel_type or not tunnel_port:
            raise Exception("Invalid input: tunnel_type and tunnel_port are required")
        
        base_cmd.extend(['delete-tunnel', '--type', tunnel_type, '--tunnel-port', tunnel_port])
    elif command == Command.control_tunnel:
        action = str(kwargs.get('action', ''))
        tunnel_type = str(kwargs.get('tunnel_type', ''))
        tunnel_port = str(kwargs.get('tunnel_port', ''))
        
        if not action or not tunnel_type or not tunnel_port:
            raise Exception("Invalid input: action, tunnel_type, and tunnel_port are required")
        
        base_cmd.extend(['control-tunnel', '--action', action, '--type', tunnel_type, '--tunnel-port', tunnel_port])
    else:
        raise Exception('WTF is happening!')
    if run_in_background:
        subprocess.Popen(base_cmd, cwd=str(os.environ['HIDDIFY_CONFIG_PATH']), start_new_session=True)
    else:
        return subprocess.check_output(base_cmd, cwd=str(os.environ['HIDDIFY_CONFIG_PATH'])).decode()
