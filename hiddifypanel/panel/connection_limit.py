"""
Connection Limit System - Real-time IP Tracking & Blocking
Tracks and limits concurrent connections per user using unique IP addresses.

This module:
1. Monitors active IPs per user from xray access logs
2. Tracks unique IPs in Redis with TTL
3. Blocks excess IPs (not the user) when limit is exceeded
4. Runs every 5 seconds via Celery for enforcement
5. Provides API for managing blocked IPs
"""

import os
import re
import time
import glob
import json
import hashlib
import ipaddress
from collections import defaultdict
from datetime import datetime, timedelta
from celery import shared_task
from loguru import logger

from hiddifypanel.database import db
from hiddifypanel.models import User, hconfig, ConfigEnum
from hiddifypanel.drivers import user_driver
from hiddifypanel import cache

# Redis key patterns
USER_IPS_KEY = "conn_limit:ips:{uuid}"
BLOCKED_IPS_KEY = "conn_limit:blocked_ips"  # Hash: ip -> {"uuid": uuid, "user_name": name, "blocked_at": timestamp}
VIOLATION_KEY = "conn_limit:violation:{uuid}"
LAST_LOG_POSITION_KEY = "conn_limit:log_position"

# Firewall enforcement state keys
FW_HASH_KEY = "conn_limit:fw_hash"            # md5 of the last desired blocked-IP set written to firewall
FW_LAST_FULL_KEY = "conn_limit:fw_last_full"  # unix ts of the last full firewall resync (self-heal)

# Handoff file: the panel (running as hiddify-panel) writes the desired blocked IP
# list here; the privileged commander (running as root) reads it and reconciles the
# HIDDIFY_CONNLIMIT iptables/ip6tables chain. One IP per line.
CONNLIMIT_BLOCKED_FILE = "/opt/hiddify-manager/log/connlimit_blocked_ips.txt"

# Force a full firewall resync at least this often (seconds) so rules self-heal
# after a server reboot or a manual iptables flush even when nothing changed.
FW_SELF_HEAL_INTERVAL = 60

# sing-box Clash API (experimental.clash_api) — used to discover the source IP of
# every CURRENTLY-OPEN connection together with its authenticated user, so that
# sing-box-only protocols (AmneziaWG / Hysteria2 / TUIC / Mieru / Naive / ...) are
# also covered by the connection limit. xray is covered via xray_access.log; this
# is the sing-box counterpart. Bound to loopback only (no secret needed).
SINGBOX_CLASH_API_URL = "http://127.0.0.1:10087/connections"
SINGBOX_CLASH_API_SECRET = ""  # empty: loopback-only controller needs no token

# Connection tracking settings
IP_TTL = 60  # Seconds before an IP is considered disconnected
CHECK_INTERVAL = 5  # Seconds between checks
LIMIT_GRACE_PERIOD = 120  # Grace period in seconds before blocking

# Access log paths - check both Xray and Singbox logs
ACCESS_LOG_PATHS = [
    "/opt/hiddify-manager/log/xray_access.log",
    "/opt/hiddify-manager/log/singbox.log",
    "/opt/hiddify-manager/log/system/singbox.log",
    "/opt/hiddify-manager/xray/access.log",
    "/opt/hiddify-manager/singbox/singbox.log",
    "/opt/hiddify-manager/singbox/access.log",
    "/var/log/xray/access.log",
    "/var/log/singbox/access.log",
]


def get_redis():
    """Get Redis client."""
    return cache.redis_client


def get_block_duration_seconds():
    """Get block duration from config (in seconds)."""
    try:
        hours = int(hconfig(ConfigEnum.user_limit_block_hours) or "24")
        return hours * 3600
    except (ValueError, TypeError):
        return 24 * 3600  # Default 24 hours


# ============================================================
# Firewall Enforcement (actually drop traffic from blocked IPs)
# ============================================================

def _is_valid_ip(ip: str) -> bool:
    """Strictly validate an IPv4/IPv6 address (defense-in-depth before it ever
    reaches the privileged commander / iptables)."""
    try:
        ipaddress.ip_address(ip)
        return True
    except (ValueError, TypeError):
        return False


def _get_active_blocked_ips(redis) -> list:
    """Return the sorted list of currently blocked (non-expired) IPs from Redis."""
    ips = set()
    try:
        all_blocked = redis.hgetall(BLOCKED_IPS_KEY)
        now = time.time()
        for ip, data in all_blocked.items():
            ip_str = ip.decode() if isinstance(ip, bytes) else ip
            try:
                info = json.loads(data.decode() if isinstance(data, bytes) else data)
                if now < info.get("expires_at", 0) and _is_valid_ip(ip_str):
                    ips.add(ip_str)
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"conn_limit: error collecting blocked IPs: {e}")
    return sorted(ips)


def sync_firewall_rules(desired_ips=None, force=False):
    """Reconcile the OS firewall (iptables/ip6tables) with the set of blocked IPs.

    The panel itself runs unprivileged, so it writes the desired IP list to a
    handoff file and asks the privileged ``commander`` (root, via sudo) to apply
    it to the dedicated HIDDIFY_CONNLIMIT chain. This is the step that actually
    drops the traffic of over-limit IPs.

    To keep the cost low this only invokes the privileged commander when the
    desired set changed, plus a periodic self-heal so the rules are rebuilt
    after a reboot / manual flush.
    """
    redis = get_redis()
    if not redis:
        return False

    if desired_ips is None:
        desired_ips = _get_active_blocked_ips(redis)
    else:
        desired_ips = sorted({ip for ip in desired_ips if _is_valid_ip(ip)})

    digest = hashlib.md5(json.dumps(desired_ips).encode()).hexdigest()

    try:
        last_hash = redis.get(FW_HASH_KEY)
        last_hash = last_hash.decode() if isinstance(last_hash, bytes) else last_hash
        last_full = float(redis.get(FW_LAST_FULL_KEY) or 0)
    except Exception:
        last_hash, last_full = None, 0

    now = time.time()
    changed = (digest != last_hash)
    # Self-heal only matters while there is something to enforce.
    needs_self_heal = bool(desired_ips) and (now - last_full > FW_SELF_HEAL_INTERVAL)

    if not (force or changed or needs_self_heal):
        return False

    # Write the handoff file atomically.
    try:
        os.makedirs(os.path.dirname(CONNLIMIT_BLOCKED_FILE), exist_ok=True)
        tmp = CONNLIMIT_BLOCKED_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(desired_ips) + ("\n" if desired_ips else ""))
        os.replace(tmp, CONNLIMIT_BLOCKED_FILE)
    except Exception as e:
        logger.error(f"conn_limit: failed writing blocked-IP handoff file: {e}")
        return False

    # Ask the privileged commander to apply the rules.
    try:
        from hiddifypanel.panel.run_commander import commander, Command
        commander(Command.connlimit_sync, run_in_background=False)
    except Exception as e:
        logger.error(f"conn_limit: failed invoking commander connlimit-sync: {e}")
        return False

    try:
        redis.set(FW_HASH_KEY, digest)
        redis.set(FW_LAST_FULL_KEY, now)
    except Exception:
        pass

    logger.info(f"conn_limit: firewall synced with {len(desired_ips)} blocked IP(s).")
    return True


@shared_task(ignore_result=False)
def check_connection_limits():
    """
    Main Celery task - runs every 5 seconds.
    1. Parse new access log entries
    2. Update IP tracking in Redis
    3. Check each user's IP count
    4. Block excess IPs (not the user)
    """
    if not hconfig(ConfigEnum.user_limit_enable):
        # Feature is off: make sure no stale firewall rules remain.
        try:
            sync_firewall_rules(desired_ips=[])
        except Exception as e:
            logger.debug(f"conn_limit: firewall flush on disable failed: {e}")
        return {"status": "disabled", "message": "Connection limits are disabled"}
    
    results = {
        "checked_users": 0,
        "limited_users": 0,
        "blocked_ips": [],
        "new_ips_tracked": 0,
        "errors": []
    }
    
    try:
        redis = get_redis()
        if not redis:
            return {"status": "error", "message": "Redis not available"}
        
        # Step 1: Clean up expired blocked IPs
        cleanup_expired_blocked_ips(redis)
        
        # Step 2: Parse access log (xray) AND query sing-box Clash API, then merge.
        new_connections = parse_access_log_incremental()

        # sing-box-only protocols don't appear in xray_access.log; pull their live
        # connections (source IP + user) from the sing-box Clash API snapshot.
        for uuid, ips in parse_singbox_connections().items():
            for ip in ips:
                new_connections[uuid].add(ip)
        
        for uuid, ips in new_connections.items():
            for ip in ips:
                # Skip if IP is already blocked
                if is_ip_blocked(redis, ip):
                    continue
                track_user_ip(redis, uuid, ip)
                results["new_ips_tracked"] += 1
        
        # Step 3: Get all active users with their IP info
        active_users = get_all_user_ip_info(redis)
        
        # Step 4: Check limits and block excess IPs
        for uuid, ip_info in active_users.items():
            try:
                user = User.query.filter(User.uuid == uuid).first()
                if not user:
                    continue
                
                results["checked_users"] += 1
                max_ips = get_user_max_connections(user)
                
                # 0 means unlimited
                if max_ips == 0:
                    continue
                
                ip_list = ip_info["ips"]
                ip_count = len(ip_list)
                
                # Check if user exceeds limit
                if ip_count > max_ips:
                    # Immediate Blocking (Grace Period Removed)
                    # Support immediate action when limit is exceeded
                    pass # Placeholder to maintain indentation flow if needed, but we just proceed to block line below


                    # Sort IPs by timestamp (newest first) and block the excess ones
                    sorted_ips = sorted(ip_info["ips_with_time"], key=lambda x: x[1], reverse=True)
                    
                    # Block IPs beyond the limit (the newest ones get blocked)
                    ips_to_block = sorted_ips[:ip_count - max_ips]
                    
                    for ip, timestamp in ips_to_block:
                        block_ip(redis, ip, uuid, user.name)
                        results["blocked_ips"].append({
                            "ip": ip,
                            "user_name": user.name,
                            "uuid": uuid
                        })
                    
                    logger.warning(
                        f"User {user.name} ({uuid}) has {ip_count} IPs, limit is {max_ips}. "
                        f"Blocked {len(ips_to_block)} excess IPs."
                    )
                    results["limited_users"] += 1
                else:
                    # User is within limits, clear any violation
                    redis.delete(VIOLATION_KEY.format(uuid=uuid))
                    
            except Exception as e:
                logger.error(f"Error checking limits for user {uuid}: {e}")
                results["errors"].append(f"{uuid}: {str(e)}")

        # Step 5: Enforce. Push the current block list to the OS firewall so the
        # blocked IPs are ACTUALLY dropped at the kernel level (works for every
        # protocol: xray, singbox, wireguard, ...), not merely recorded in Redis.
        try:
            sync_firewall_rules()
        except Exception as e:
            logger.error(f"conn_limit: firewall sync failed: {e}")
            results["errors"].append(f"firewall_sync: {str(e)}")

    except Exception as e:
        logger.exception(f"Error in check_connection_limits: {e}")
        results["errors"].append(str(e))
    
    return {"status": "success", **results}


def parse_singbox_connections():
    """Query the sing-box Clash API for the live connection snapshot and return
    {uuid: set(ips)} for every currently-open connection.

    Requires the custom sing-box build to expose ``metadata.user`` in the
    /connections response (patch to experimental/clashapi/trafficontrol/tracker.go)
    and ``experimental.clash_api`` enabled in the sing-box config. If the API is
    unavailable this returns an empty mapping and the caller silently continues.
    """
    import urllib.request
    connections = defaultdict(set)
    try:
        req = urllib.request.Request(SINGBOX_CLASH_API_URL)
        if SINGBOX_CLASH_API_SECRET:
            req.add_header("Authorization", f"Bearer {SINGBOX_CLASH_API_SECRET}")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug(f"conn_limit: sing-box clash api query failed: {e}")
        return connections

    for conn in (data.get("connections") or []):
        try:
            md = conn.get("metadata", {}) or {}
            user = (md.get("user") or "").strip()
            ip = (md.get("sourceIP") or "").strip()
            if not user or not ip:
                continue
            # user is "<uuid>@hiddify.com" (or with a numeric prefix); extract uuid
            uuid = user.split("@")[0]
            uuid = re.sub(r"^\d+\.", "", uuid)
            if not _is_valid_ip(ip) or ip.startswith("127.") or ip == "::1":
                continue
            connections[uuid].add(ip)
        except Exception:
            continue

    if connections:
        logger.debug(f"conn_limit: sing-box clash api -> {sum(len(v) for v in connections.values())} live IP(s) for {len(connections)} user(s).")
    return connections


def kill_singbox_connections_by_ip(ip):
    """Kill all active sing-box connections from a specific IP address.

    Uses the Clash API ``DELETE /connections/{id}`` endpoint to forcefully
    close every open connection whose ``metadata.sourceIP`` matches *ip*.
    This is necessary because iptables ``ESTABLISHED,RELATED`` rules allow
    already-open TCP sessions to survive a DROP rule; we must actively
    tear them down.
    """
    import urllib.request
    killed = 0
    try:
        req = urllib.request.Request(SINGBOX_CLASH_API_URL)
        if SINGBOX_CLASH_API_SECRET:
            req.add_header("Authorization", f"Bearer {SINGBOX_CLASH_API_SECRET}")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug(f"conn_limit: clash api query for kill failed: {e}")
        return 0

    for conn in (data.get("connections") or []):
        try:
            md = conn.get("metadata", {}) or {}
            source_ip = (md.get("sourceIP") or "").strip()
            if source_ip == ip:
                conn_id = conn.get("id", "")
                if conn_id:
                    try:
                        del_req = urllib.request.Request(
                            f"{SINGBOX_CLASH_API_URL}/{conn_id}",
                            method="DELETE"
                        )
                        if SINGBOX_CLASH_API_SECRET:
                            del_req.add_header("Authorization", f"Bearer {SINGBOX_CLASH_API_SECRET}")
                        urllib.request.urlopen(del_req, timeout=2)
                        killed += 1
                    except Exception:
                        pass
        except Exception:
            continue

    if killed:
        logger.info(f"conn_limit: killed {killed} sing-box connection(s) from blocked IP {ip}")
    return killed


def parse_access_log_incremental():
    """
    Parse access logs incrementally - only new entries since last check.
    Checks ALL available log files (Xray and Singbox) for better coverage.
    
    Returns:
        dict: {uuid: set(ips)}
    """
    redis = get_redis()
    connections = defaultdict(set)
    
    if not redis:
        return connections
    
    # Find all existing log files (check both Xray and Singbox)
    log_files = [path for path in ACCESS_LOG_PATHS if os.path.exists(path)]
    
    if not log_files:
        logger.warning("Connection limit: No access log file found! Make sure user_limit_enable is active and xray/singbox is running.")
        return connections
    
    total_parsed = 0
    for log_file in log_files:
        try:
            # Use separate position key for each log file
            position_key = f"{LAST_LOG_POSITION_KEY}:{os.path.basename(log_file)}"
            last_position = int(redis.get(position_key) or 0)
            
            with open(log_file, 'rb') as f:
                # Get file size
                f.seek(0, 2)
                file_size = f.tell()
                
                # If file is smaller than last position, it was rotated
                if file_size < last_position:
                    last_position = 0
                    logger.debug(f"Log file rotated: {log_file}")
                
                # Seek to last position
                f.seek(last_position)
                content = f.read().decode('utf-8', errors='ignore')
                
                # Save new position
                redis.set(position_key, f.tell())
            
    # Parse new log entries
            lines_parsed = 0
            now = time.time()
            cutoff_time = now - IP_TTL
            
            for line in content.split('\n'):
                if not line.strip():
                    continue
                
                # Only process lines with 'accepted' or 'from' (connection lines)
                if 'accepted' not in line.lower() and 'from' not in line.lower() and 'email' not in line.lower():
                    continue
                
                # Try to extract UUID, IP and Timestamp
                uuid, ip, log_time = parse_log_line(line)
                
                if uuid and ip:
                    # If log has timestamp, check if it's recent
                    if log_time:
                        if log_time < cutoff_time:
                            continue # Skip old logs
                    
                    connections[uuid].add(ip)
                    lines_parsed += 1
            
            if lines_parsed > 0:
                logger.debug(f"Parsed {lines_parsed} recent connections from {log_file}")
                total_parsed += lines_parsed
                    
        except Exception as e:
            logger.debug(f"Error parsing access log {log_file}: {e}")
    
    if total_parsed > 0:
        logger.debug(f"Total connections parsed: {total_parsed} for {len(connections)} users")
    
    return connections


def parse_log_line(line):
    """
    Parse a single log line to extract UUID, source IP and timestamp.
    Supports both Xray 'from' format and 'accepted' format.
    
    Returns:
        tuple: (uuid, ip, timestamp_unix) or (None, None, None)
    """
    try:
        uuid = None
        ip = None
        timestamp = None
        
        # Extract Timestamp (YYYY/MM/DD HH:MM:SS)
        # 2023/10/26 14:30:15
        time_match = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2})', line)
        if time_match:
            try:
                dt = datetime.strptime(time_match.group(1).replace('-', '/'), '%Y/%m/%d %H:%M:%S')
                timestamp = dt.timestamp()
            except:
                pass

        # Extract email/uuid - multiple patterns for compatibility
        # Pattern 1: email: user@hiddify.com format (nobetci style)
        email_match = re.search(r'email:\s*([A-Za-z0-9._-]+(?:@[A-Za-z0-9.-]+)?)', line, re.IGNORECASE)
        if email_match:
            email = email_match.group(1)
            # Extract UUID from email if it contains @
            if '@' in email:
                uuid = email.split('@')[0]
            else:
                uuid = email
            # Remove numeric prefix if present (e.g., "123.uuid" -> "uuid")
            uuid = re.sub(r'^\d+\.', '', uuid)
        
        # Pattern 2: uuid@hiddify.com directly (original pattern)
        if not uuid:
            uuid_email_match = re.search(r'([a-f0-9-]{36})@', line, re.IGNORECASE)
            if uuid_email_match:
                uuid = uuid_email_match.group(1)
        
        # Pattern 3: UUID pattern directly
        if not uuid:
            uuid_match = re.search(r'\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b', line, re.IGNORECASE)
            if uuid_match:
                uuid = uuid_match.group(1)
        
        # Extract source IP - multiple patterns
        # Pattern 1: "from IP:port" or "from [IP]:port" (Xray format)
        ip_match = re.search(r'from\s+\[?(\d+\.\d+\.\d+\.\d+)\]?:\d+', line)
        if ip_match:
            ip = ip_match.group(1)
        
        # Pattern 2: "[IP]:port accepted" (nobetci/Singbox style)
        if not ip:
            ip_accepted_match = re.search(r'\[?(\d+\.\d+\.\d+\.\d+)\]?:\d+\s+accepted', line)
            if ip_accepted_match:
                ip = ip_accepted_match.group(1)
        
        # Pattern 3: IPv6 "from [IPv6]:port"
        if not ip:
            ipv6_match = re.search(r'from\s+\[([a-fA-F0-9:]+)\]:\d+', line)
            if ipv6_match:
                ip = ipv6_match.group(1)
        
        # Pattern 4: IPv6 "[IPv6]:port accepted" 
        if not ip:
            ipv6_accepted_match = re.search(r'\[([a-fA-F0-9:]+)\]:\d+\s+accepted', line)
            if ipv6_accepted_match:
                ip = ipv6_accepted_match.group(1)

        # Pattern 5: Singbox generic "inbound/vless[tag]: inbound connection from 1.2.3.4:5678"
        if not ip:
            singbox_match = re.search(r'inbound connection from\s+\[?(\d+\.\d+\.\d+\.\d+)\]?:\d+', line)
            if singbox_match:
                ip = singbox_match.group(1)

        # Skip localhost IPs
        if ip and (ip.startswith('127.') or ip == '::1'):
            return None, None, None
        
        return uuid, ip, timestamp
        
    except Exception:
        return None, None, None


def track_user_ip(redis, uuid, ip):
    """
    Track an IP for a user in Redis with TTL.
    Uses a sorted set with timestamp as score for easy cleanup.
    """
    key = USER_IPS_KEY.format(uuid=uuid)
    now = time.time()
    
    # Add IP with current timestamp
    redis.zadd(key, {ip: now})
    
    # Remove old IPs (older than TTL)
    cutoff = now - IP_TTL
    redis.zremrangebyscore(key, '-inf', cutoff)
    
    # Set key expiry
    redis.expire(key, IP_TTL * 2)


def get_user_ip_count(redis, uuid):
    """
    Get the count of active unique IPs for a user.
    """
    key = USER_IPS_KEY.format(uuid=uuid)
    now = time.time()
    cutoff = now - IP_TTL
    
    # Count IPs with timestamp > cutoff
    return redis.zcount(key, cutoff, '+inf')


def get_user_active_ips(redis, uuid):
    """
    Get the list of active IPs for a user.
    """
    key = USER_IPS_KEY.format(uuid=uuid)
    now = time.time()
    cutoff = now - IP_TTL
    
    # Get IPs with timestamp > cutoff
    ips = redis.zrangebyscore(key, cutoff, '+inf')
    return [ip.decode() if isinstance(ip, bytes) else ip for ip in ips]


def get_all_user_ip_info(redis):
    """
    Get IP info for all tracked users.
    
    Returns:
        dict: {uuid: {"ips": [ip1, ip2], "ips_with_time": [(ip, timestamp), ...]}}
    """
    result = {}
    now = time.time()
    cutoff = now - IP_TTL
    
    # Find all user IP keys
    pattern = USER_IPS_KEY.format(uuid="*")
    keys = redis.keys(pattern)
    
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        uuid = key_str.split(":")[-1]
        
        # Get IPs with scores (timestamps)
        ips_with_scores = redis.zrangebyscore(key, cutoff, '+inf', withscores=True)
        
        if ips_with_scores:
            ips = []
            ips_with_time = []
            for ip, score in ips_with_scores:
                ip_str = ip.decode() if isinstance(ip, bytes) else ip
                ips.append(ip_str)
                ips_with_time.append((ip_str, score))
            
            result[uuid] = {
                "ips": ips,
                "ips_with_time": ips_with_time
            }
    
    return result


def get_all_user_ip_counts(redis):
    """
    Get IP counts for all tracked users.
    
    Returns:
        dict: {uuid: ip_count}
    """
    counts = {}
    now = time.time()
    cutoff = now - IP_TTL
    
    # Find all user IP keys
    pattern = USER_IPS_KEY.format(uuid="*")
    keys = redis.keys(pattern)
    
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        uuid = key_str.split(":")[-1]
        count = redis.zcount(key, cutoff, '+inf')
        if count > 0:
            counts[uuid] = count
    
    return counts


# ============================================================
# IP Blocking Functions
# ============================================================

def block_ip(redis, ip, uuid, user_name):
    """
    Block an IP address for the configured duration.
    Stores: ip -> {"uuid": uuid, "user_name": name, "blocked_at": timestamp, "expires_at": timestamp}
    """
    block_duration = get_block_duration_seconds()
    now = time.time()
    expires_at = now + block_duration
    
    import json
    data = json.dumps({
        "uuid": uuid,
        "user_name": user_name,
        "blocked_at": now,
        "expires_at": expires_at
    })
    
    redis.hset(BLOCKED_IPS_KEY, ip, data)
    
    # Also remove this IP from user's tracking
    user_key = USER_IPS_KEY.format(uuid=uuid)
    redis.zrem(user_key, ip)
    
    logger.info(f"Blocked IP {ip} for user {user_name} until {datetime.fromtimestamp(expires_at)}")
    
    # Actively kill existing sing-box connections from this IP so the block
    # takes effect immediately (iptables ESTABLISHED rules would otherwise
    # let already-open sessions continue).
    try:
        kill_singbox_connections_by_ip(ip)
    except Exception as e:
        logger.debug(f"conn_limit: failed to kill connections for {ip}: {e}")


def unblock_ip(ip):
    """
    Manually unblock an IP address.
    
    Returns:
        bool: True if IP was unblocked, False if not found
    """
    redis = get_redis()
    if not redis:
        return False
    
    result = redis.hdel(BLOCKED_IPS_KEY, ip)
    if result:
        logger.info(f"Manually unblocked IP {ip}")
        try:
            sync_firewall_rules(force=True)
        except Exception as e:
            logger.debug(f"conn_limit: firewall sync after unblock failed: {e}")
    return result > 0


def is_ip_blocked(redis, ip):
    """Check if an IP is currently blocked."""
    if not redis:
        return False
    
    data = redis.hget(BLOCKED_IPS_KEY, ip)
    if not data:
        return False
    
    import json
    try:
        info = json.loads(data.decode() if isinstance(data, bytes) else data)
        expires_at = info.get("expires_at", 0)
        return time.time() < expires_at
    except:
        return False


def cleanup_expired_blocked_ips(redis):
    """Remove expired blocked IPs from the hash."""
    import json
    now = time.time()
    
    # Get all blocked IPs
    all_blocked = redis.hgetall(BLOCKED_IPS_KEY)
    
    for ip, data in all_blocked.items():
        try:
            ip_str = ip.decode() if isinstance(ip, bytes) else ip
            info = json.loads(data.decode() if isinstance(data, bytes) else data)
            
            expires_at = info.get("expires_at", 0)
            if now >= expires_at:
                redis.hdel(BLOCKED_IPS_KEY, ip_str)
                logger.debug(f"Unblocked expired IP {ip_str}")
        except Exception as e:
            logger.debug(f"Error cleaning up blocked IP: {e}")


def get_all_blocked_ips():
    """
    Get all currently blocked IPs with their info.
    
    Returns:
        list: [{"ip": ip, "uuid": uuid, "user_name": name, "blocked_at": datetime, "expires_at": datetime, "remaining_hours": float}, ...]
    """
    redis = get_redis()
    if not redis:
        return []
    
    import json
    result = []
    now = time.time()
    
    # First cleanup expired
    cleanup_expired_blocked_ips(redis)
    
    all_blocked = redis.hgetall(BLOCKED_IPS_KEY)
    
    for ip, data in all_blocked.items():
        try:
            ip_str = ip.decode() if isinstance(ip, bytes) else ip
            info = json.loads(data.decode() if isinstance(data, bytes) else data)
            
            expires_at = info.get("expires_at", 0)
            blocked_at = info.get("blocked_at", 0)
            
            # Only include if not expired
            if now < expires_at:
                remaining_seconds = expires_at - now
                remaining_hours = remaining_seconds / 3600
                
                result.append({
                    "ip": ip_str,
                    "uuid": info.get("uuid", ""),
                    "user_name": info.get("user_name", "Unknown"),
                    "blocked_at": datetime.fromtimestamp(blocked_at).strftime("%Y-%m-%d %H:%M:%S") if blocked_at else "",
                    "expires_at": datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M:%S") if expires_at else "",
                    "remaining_hours": round(remaining_hours, 1)
                })
        except Exception as e:
            logger.debug(f"Error parsing blocked IP data: {e}")
    
    # Sort by blocked_at (newest first)
    result.sort(key=lambda x: x["blocked_at"], reverse=True)
    
    return result


def get_blocked_ips_count():
    """Get the count of currently blocked IPs."""
    return len(get_all_blocked_ips())


def unblock_all_ips():
    """Unblock all blocked IPs."""
    redis = get_redis()
    if not redis:
        return 0
    
    count = redis.hlen(BLOCKED_IPS_KEY)
    redis.delete(BLOCKED_IPS_KEY)
    logger.info(f"Unblocked all {count} IPs")
    try:
        sync_firewall_rules(desired_ips=[], force=True)
    except Exception as e:
        logger.debug(f"conn_limit: firewall flush after unblock-all failed: {e}")
    return count


def unblock_user_ips(uuid):
    """Unblock all IPs blocked for a specific user."""
    redis = get_redis()
    if not redis:
        return 0
    
    import json
    count = 0
    all_blocked = redis.hgetall(BLOCKED_IPS_KEY)
    
    for ip, data in all_blocked.items():
        try:
            ip_str = ip.decode() if isinstance(ip, bytes) else ip
            info = json.loads(data.decode() if isinstance(data, bytes) else data)
            
            if info.get("uuid") == uuid:
                redis.hdel(BLOCKED_IPS_KEY, ip_str)
                count += 1
        except:
            pass
    
    if count > 0:
        logger.info(f"Unblocked {count} IPs for user {uuid}")
        try:
            sync_firewall_rules(force=True)
        except Exception as e:
            logger.debug(f"conn_limit: firewall sync after user-unblock failed: {e}")
    return count


# ============================================================
# Helper Functions
# ============================================================

def get_user_max_connections(user: User) -> int:
    """
    Get the maximum allowed IPs (connections) for a user.
    
    Returns:
        int: Maximum IPs (0 = unlimited)
    """
    # User-specific limit takes precedence
    if user.max_ips and user.max_ips > 0 and user.max_ips < 10000:
        return user.max_ips
    
    # Fall back to global default
    try:
        default = int(hconfig(ConfigEnum.user_limit_default) or "0")
        return max(0, default)
    except (ValueError, TypeError):
        return 0


# ============================================================
# API functions for external use
# ============================================================

def get_user_connection_info(uuid):
    """
    Get connection info for a user (for monitoring page).
    
    Returns:
        dict: {"ip_count": int, "ips": list}
    """
    redis = get_redis()
    if not redis:
        return {"ip_count": 0, "ips": []}
    
    return {
        "ip_count": get_user_ip_count(redis, uuid),
        "ips": get_user_active_ips(redis, uuid)
    }


def force_block_ip(ip, uuid=None, user_name=None):
    """
    Manually block an IP address.
    """
    redis = get_redis()
    if not redis:
        return False
    
    block_ip(redis, ip, uuid or "manual", user_name or "Manual Block")
    try:
        sync_firewall_rules(force=True)
    except Exception as e:
        logger.debug(f"conn_limit: firewall sync after force-block failed: {e}")
    return True


def get_connection_limit_stats():
    """
    Get overall connection limit statistics.
    
    Returns:
        dict: {"blocked_ips_count": int, "active_users_count": int, "block_duration_hours": int}
    """
    redis = get_redis()
    stats = {
        "blocked_ips_count": 0,
        "active_users_count": 0,
        "block_duration_hours": 24,
        "enabled": False
    }
    
    try:
        stats["enabled"] = bool(hconfig(ConfigEnum.user_limit_enable))
        stats["block_duration_hours"] = int(hconfig(ConfigEnum.user_limit_block_hours) or "24")
        
        if redis:
            stats["blocked_ips_count"] = get_blocked_ips_count()
            stats["active_users_count"] = len(get_all_user_ip_counts(redis))
    except Exception as e:
        logger.debug(f"Error getting connection limit stats: {e}")
    
    return stats


def get_connection_limit_diagnostic():
    """
    Get diagnostic info for debugging connection limit issues.
    Useful for troubleshooting when IP limits don't seem to work.
    
    Returns:
        dict: Detailed diagnostic information
    """
    diagnostic = {
        "enabled": False,
        "redis_available": False,
        "log_files_found": [],
        "log_files_missing": [],
        "log_files_readable": [],
        "sample_log_lines": [],
        "parsed_connections_count": 0,
        "issues": [],
        "recommendations": []
    }
    
    try:
        # Check if feature is enabled
        diagnostic["enabled"] = bool(hconfig(ConfigEnum.user_limit_enable))
        if not diagnostic["enabled"]:
            diagnostic["issues"].append("user_limit_enable is disabled in panel settings")
            diagnostic["recommendations"].append("Enable 'Connection Limit' in panel settings")
        
        # Check Redis
        redis = get_redis()
        diagnostic["redis_available"] = redis is not None
        if not redis:
            diagnostic["issues"].append("Redis is not available")
            diagnostic["recommendations"].append("Ensure Redis server is running")
        
        # Check log files
        for path in ACCESS_LOG_PATHS:
            if os.path.exists(path):
                diagnostic["log_files_found"].append(path)
                try:
                    with open(path, 'r') as f:
                        f.read(1)
                    diagnostic["log_files_readable"].append(path)
                    
                    # Get sample lines
                    with open(path, 'r') as f:
                        f.seek(0, 2)
                        size = f.tell()
                        # Read last 2KB
                        f.seek(max(0, size - 2048))
                        content = f.read()
                        lines = [l for l in content.split('\n') if l.strip()][-5:]
                        for line in lines:
                            uuid, ip, _ = parse_log_line(line)
                            diagnostic["sample_log_lines"].append({
                                "line": line[:200] + "..." if len(line) > 200 else line,
                                "parsed_uuid": uuid,
                                "parsed_ip": ip
                            })
                except Exception as e:
                    diagnostic["issues"].append(f"Cannot read {path}: {e}")
            else:
                diagnostic["log_files_missing"].append(path)
        
        if not diagnostic["log_files_found"]:
            diagnostic["issues"].append("No access log files found")
            diagnostic["recommendations"].append("Ensure Xray/Singbox is running with access logging enabled")
        
        # Try to parse current connections
        if redis and diagnostic["log_files_readable"]:
            connections = parse_access_log_incremental()
            diagnostic["parsed_connections_count"] = sum(len(ips) for ips in connections.values())
            if diagnostic["parsed_connections_count"] == 0:
                diagnostic["issues"].append("No connections could be parsed from logs")
                diagnostic["recommendations"].append("Check if log format contains 'email:' and IP addresses")
        
    except Exception as e:
        diagnostic["issues"].append(f"Diagnostic error: {e}")
    
    return diagnostic

