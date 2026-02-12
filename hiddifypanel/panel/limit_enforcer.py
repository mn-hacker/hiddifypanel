import time
import json
import redis
import subprocess
import logging
import os
from hiddifypanel.models.config_enum import ConfigEnum
from hiddifypanel.models.config import hconfig

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

# Constants
BLOCKED_IPS_KEY = "conn_limit:blocked_ips"
CHAIN_NAME = "HIDDIFY_LIMIT"
CHECK_INTERVAL = 10  # Seconds
IPV4_CMD = "iptables"
IPV6_CMD = "ip6tables"

def get_redis_client():
    try:
        return redis.Redis(host='127.0.0.1', port=6379, db=0)
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

def init_firewall():
    """Initialize firewall chains and jumps."""
    # IPv4
    run_command(f"{IPV4_CMD} -N {CHAIN_NAME}", ignore_error=True)
    run_command(f"{IPV4_CMD} -F {CHAIN_NAME}") # Flush chain
    # Ensure jump rule exists at top of INPUT
    if not run_command(f"{IPV4_CMD} -C INPUT -j {CHAIN_NAME}", ignore_error=True):
        run_command(f"{IPV4_CMD} -I INPUT 1 -j {CHAIN_NAME}")
    
    # IPv6
    run_command(f"{IPV6_CMD} -N {CHAIN_NAME}", ignore_error=True)
    run_command(f"{IPV6_CMD} -F {CHAIN_NAME}")
    if not run_command(f"{IPV6_CMD} -C INPUT -j {CHAIN_NAME}", ignore_error=True):
        run_command(f"{IPV6_CMD} -I INPUT 1 -j {CHAIN_NAME}")

def get_current_iptables_rules(cmd):
    """Get current blocked IPs from iptables to minimize calls."""
    try:
        output = subprocess.check_output(f"{cmd} -n -L {CHAIN_NAME}", shell=True).decode()
        # Parse output looking for source IPs
        # Example line: DROP       all  --  1.2.3.4              0.0.0.0/0
        import re
        ips = set()
        for line in output.split('\n')[2:]: # Skip header
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "DROP":
                ip = parts[3]
                if ip != "0.0.0.0/0": # Ignore non-IPs
                    ips.add(ip)
        return ips
    except Exception as e:
        logger.error(f"Error reading iptables: {e}")
        return set()

def is_ipv6(ip):
    return ':' in ip

def sync_rules(redis_client):
    try:
        # 1. Get Blocked IPs from Redis
        blocked_data = redis_client.hgetall(BLOCKED_IPS_KEY)
        active_blocked_ips = set()
        
        current_time = time.time()
        
        for ip_bytes, data_bytes in blocked_data.items():
            ip = ip_bytes.decode()
            try:
                data = json.loads(data_bytes)
                expires_at = data.get("expires_at", 0)
                
                # Check expiration (redundant with connection_limit.py cleanup, but safe)
                if current_time < expires_at:
                    active_blocked_ips.add(ip)
            except:
                pass

        # 2. Get current rules
        current_v4 = get_current_iptables_rules(IPV4_CMD)
        current_v6 = get_current_iptables_rules(IPV6_CMD)
        
        # 3. Apply changes
        # Separate v4 and v6
        active_v4 = {ip for ip in active_blocked_ips if not is_ipv6(ip)}
        active_v6 = {ip for ip in active_blocked_ips if is_ipv6(ip)}
        
        # Sync IPv4
        # Add missing
        for ip in active_v4 - current_v4:
            logger.info(f"Blocking IPv4: {ip}")
            run_command(f"{IPV4_CMD} -A {CHAIN_NAME} -s {ip} -j DROP")
            
        # Remove extra (unblocked/expired)
        for ip in current_v4 - active_v4:
            logger.info(f"Unblocking IPv4: {ip}")
            run_command(f"{IPV4_CMD} -D {CHAIN_NAME} -s {ip} -j DROP")
            
        # Sync IPv6
        for ip in active_v6 - current_v6:
            logger.info(f"Blocking IPv6: {ip}")
            run_command(f"{IPV6_CMD} -A {CHAIN_NAME} -s {ip} -j DROP")
            
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
