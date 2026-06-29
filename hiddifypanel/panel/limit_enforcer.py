import time
import json
import redis
import subprocess
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/hiddify-manager/log/system/ip_limiter.log')
    ]
)
logger = logging.getLogger("ip_limiter")

# Constants — use the SAME chain name as commander.py so both systems
# converge on one set of rules instead of creating two competing chains.
BLOCKED_IPS_KEY = "conn_limit:blocked_ips"
CHAIN_NAME = "HIDDIFY_CONNLIMIT"
CHECK_INTERVAL = 10  # Seconds
IPV4_CMD = "iptables"
IPV6_CMD = "ip6tables"

def get_redis_client():
    try:
        uri = os.environ.get("REDIS_URI_MAIN", "redis://127.0.0.1:6379/0")
        return redis.from_url(uri)
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return None

def run_command(cmd, ignore_error=False):
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        if not ignore_error:
            logger.error(f"Command failed: {cmd}")
        return False

def ensure_chain_at_top(cmd):
    """Ensure our chain exists and its jump rule sits at position 1 in INPUT.

    common/run.sh re-inserts ESTABLISHED,RELATED accept rules at position 1
    every time apply_configs runs.  If our jump ends up BELOW those rules,
    already-open TCP sessions from blocked IPs are accepted before they
    reach our DROP rules.  By unconditionally deleting + re-inserting our
    jump we guarantee it is always rule #1 in INPUT.
    """
    # Create chain if missing
    run_command(f"{cmd} -N {CHAIN_NAME}", ignore_error=True)
    # Remove existing jump (may not exist — that's fine)
    run_command(f"{cmd} -D INPUT -j {CHAIN_NAME}", ignore_error=True)
    # (Re-)insert at position 1
    run_command(f"{cmd} -I INPUT 1 -j {CHAIN_NAME}")

def init_firewall():
    """Initialize firewall chains and jumps."""
    # Also clean up the legacy chain name if it exists
    for cmd in [IPV4_CMD, IPV6_CMD]:
        run_command(f"{cmd} -D INPUT -j HIDDIFY_LIMIT", ignore_error=True)
        run_command(f"{cmd} -F HIDDIFY_LIMIT", ignore_error=True)
        run_command(f"{cmd} -X HIDDIFY_LIMIT", ignore_error=True)

    ensure_chain_at_top(IPV4_CMD)
    ensure_chain_at_top(IPV6_CMD)

def get_current_iptables_rules(cmd):
    """Get current blocked IPs from iptables to minimize calls."""
    try:
        output = subprocess.check_output(f"{cmd} -n -L {CHAIN_NAME}", shell=True).decode()
        import re
        ips = set()
        for line in output.split('\n')[2:]:
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "DROP":
                ip = parts[3]
                if ip != "0.0.0.0/0":
                    ips.add(ip)
        return ips
    except Exception as e:
        logger.error(f"Error reading iptables: {e}")
        return set()

def is_ipv6(ip):
    return ':' in ip

def kill_conntrack(ip):
    """Remove conntrack entries for an IP so ESTABLISHED sessions are broken."""
    run_command(f"conntrack -D -s {ip}", ignore_error=True)

def sync_rules(redis_client):
    try:
        # Re-ensure our chain jump is at position 1 every cycle so that
        # any concurrent run.sh invocation cannot push us below ESTABLISHED.
        ensure_chain_at_top(IPV4_CMD)
        ensure_chain_at_top(IPV6_CMD)

        # 1. Get Blocked IPs from Redis
        blocked_data = redis_client.hgetall(BLOCKED_IPS_KEY)
        active_blocked_ips = set()
        
        current_time = time.time()
        
        for ip_bytes, data_bytes in blocked_data.items():
            ip = ip_bytes.decode()
            try:
                data = json.loads(data_bytes)
                expires_at = data.get("expires_at", 0)
                if current_time < expires_at:
                    active_blocked_ips.add(ip)
            except:
                pass

        # 2. Get current rules
        current_v4 = get_current_iptables_rules(IPV4_CMD)
        current_v6 = get_current_iptables_rules(IPV6_CMD)
        
        # 3. Apply changes
        active_v4 = {ip for ip in active_blocked_ips if not is_ipv6(ip)}
        active_v6 = {ip for ip in active_blocked_ips if is_ipv6(ip)}
        
        # Sync IPv4
        for ip in active_v4 - current_v4:
            logger.info(f"Blocking IPv4: {ip}")
            run_command(f"{IPV4_CMD} -A {CHAIN_NAME} -s {ip} -j DROP")
            kill_conntrack(ip)
            
        for ip in current_v4 - active_v4:
            logger.info(f"Unblocking IPv4: {ip}")
            run_command(f"{IPV4_CMD} -D {CHAIN_NAME} -s {ip} -j DROP")
            
        # Sync IPv6
        for ip in active_v6 - current_v6:
            logger.info(f"Blocking IPv6: {ip}")
            run_command(f"{IPV6_CMD} -A {CHAIN_NAME} -s {ip} -j DROP")
            kill_conntrack(ip)
            
        for ip in current_v6 - active_v6:
            logger.info(f"Unblocking IPv6: {ip}")
            run_command(f"{IPV6_CMD} -D {CHAIN_NAME} -s {ip} -j DROP")
            
    except Exception as e:
        logger.error(f"Error in sync_rules: {e}")

def main():
    logger.info("Starting Hiddify IP Limiter...")
    
    # Wait for dependencies
    time.sleep(5)
    
    # Init Firewall
    init_firewall()
    
    redis_client = get_redis_client()
    if not redis_client:
        logger.critical("Could not connect to Redis. Exiting.")
        return

    logger.info("Firewall initialized. Starting sync loop.")
    
    while True:
        sync_rules(redis_client)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
