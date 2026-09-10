import random
import socket
import string
from hiddifypanel.models import hconfig, ConfigEnum


def get_random_string(min_: int = 10, max_: int = 30) -> str:
    # With combination of lower and upper case
    length = random.randint(min_, max_)
    characters = string.ascii_letters + string.digits
    result_str = ''.join(random.choice(characters) for i in range(length))
    return result_str


def get_random_password(length: int = 16) -> str:
    '''Retunrns a random password with fixed length'''
    characters = string.ascii_letters + string.digits  # + '-'
    while True:
        passwd = ''.join(random.choice(characters) for i in range(length))
        if (any(c.islower() for c in passwd) and any(c.isupper() for c in passwd) and sum(c.isdigit() for c in passwd) > 1):
            return passwd


def __is_port_in_range(port, start_port: int | str | None, count: int):
    if start_port is None:
        return False
    start_port = int(start_port)
    if port < start_port:
        return False

    if port > start_port + count:
        return False
    return True


def __is_in_used_port(port):
    if __is_port_in_range(port, hconfig(ConfigEnum.reality_port, warn_missing=False), 100):
        return True
    if __is_port_in_range(port, hconfig(ConfigEnum.hysteria_port, warn_missing=False), 100):
        return True
    if __is_port_in_range(port, hconfig(ConfigEnum.tuic_port, warn_missing=False), 100):
        return True
    # watashi v12.2.100: the fixed list knew about a handful of ports only,
    # so the panel handed out a port the api, the clash api, the local
    # mixed listener or shadowtls already held.
    if port in [22, 53, 80, 443, 1010, 1030, 3000, 3306, 6379, 9000, 10085, 10086,
                10087, 12334, 16756, hconfig(ConfigEnum.ssh_server_port, warn_missing=False),
                hconfig(ConfigEnum.shadowsocks2022_port, warn_missing=False)]:
        return True


# watashi v12.2.100: nobody ever asked the kernel whether the port was
# free, so a port another service already held could be written into the
# config. sing-box then failed to bind it and exited, and every config on
# that server went dark at once. the port is tried before it is handed out.
def __is_bindable(port: int) -> bool:
    for family, addr in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            try:
                sock = socket.socket(family, kind)
            except OSError:
                continue
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((addr, port))
            except OSError:
                return False
            finally:
                sock.close()
    return True


def get_random_unused_port():
    for _ in range(200):
        port = random.randint(11000, 60000)
        if not __is_in_used_port(port) and __is_bindable(port):
            return port
    port = random.randint(11000, 60000)
    while __is_in_used_port(port):
        port = random.randint(11000, 60000)
    return port


def random_case(string):
    return ''.join(random.choice((str.upper, str.lower))(c) for c in string)
