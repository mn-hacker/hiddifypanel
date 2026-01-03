"""
Connection Limit System - Real-time IP Tracking
Tracks and limits concurrent connections per user using unique IP addresses.

This module:
1. Monitors active IPs per user from xray access logs
2. Tracks unique IPs in Redis with TTL
3. Disconnects users exceeding their max_ips limit immediately
4. Runs every 5 seconds via Celery for enforcement
"""

import os
import re
import time
import glob
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
USER_BLOCKED_KEY = "conn_limit:blocked:{uuid}"
LAST_LOG_POSITION_KEY = "conn_limit:log_position"

# Connection tracking settings
IP_TTL = 60  # Seconds before an IP is considered disconnected
BLOCK_DURATION = 30  # Seconds to block a user after exceeding limit
CHECK_INTERVAL = 5  # Seconds between checks

# Access log paths
ACCESS_LOG_PATHS = [
    "/opt/hiddify-manager/log/xray_access.log",
    "/opt/hiddify-manager/xray/access.log",
    "/var/log/xray/access.log",
]


def get_redis():
    """Get Redis client."""
    return cache.redis_client


@shared_task(ignore_result=False)
def check_connection_limits():
    """
    Main Celery task - runs every 5 seconds.
    1. Parse new access log entries
    2. Update IP tracking in Redis
    3. Check each user's IP count
    4. Disconnect users exceeding limits
    """
    if not hconfig(ConfigEnum.user_limit_enable):
        return {"status": "disabled", "message": "Connection limits are disabled"}
    
    results = {
        "checked_users": 0,
        "limited_users": 0,
        "disconnected_users": [],
        "new_ips_tracked": 0,
        "errors": []
    }
    
    try:
        redis = get_redis()
        
        # Step 1: Parse access log and track new IPs
        new_connections = parse_access_log_incremental()
        
        for uuid, ips in new_connections.items():
            for ip in ips:
                track_user_ip(redis, uuid, ip)
                results["new_ips_tracked"] += 1
        
        # Step 2: Get all active users with their IP counts
        active_users = get_all_user_ip_counts(redis)
        
        # Step 3: Check limits and disconnect if needed
        for uuid, ip_count in active_users.items():
            try:
                user = User.query.filter(User.uuid == uuid).first()
                if not user:
                    continue
                
                results["checked_users"] += 1
                max_ips = get_user_max_connections(user)
                
                # 0 means unlimited
                if max_ips == 0:
                    continue
                
                # Check if user exceeds limit
                if ip_count > max_ips:
                    logger.warning(
                        f"User {user.name} ({uuid}) has {ip_count} IPs, limit is {max_ips}. DISCONNECTING!"
                    )
                    
                    # Disconnect immediately
                    disconnect_and_block_user(redis, user, BLOCK_DURATION)
                    
                    results["limited_users"] += 1
                    results["disconnected_users"].append({
                        "name": user.name,
                        "uuid": uuid,
                        "ips": ip_count,
                        "limit": max_ips
                    })
                    
            except Exception as e:
                logger.error(f"Error checking limits for user {uuid}: {e}")
                results["errors"].append(f"{uuid}: {str(e)}")
        
        # Step 4: Cleanup expired blocked users
        cleanup_expired_blocks(redis)
        
    except Exception as e:
        logger.exception(f"Error in check_connection_limits: {e}")
        results["errors"].append(str(e))
    
    return {"status": "success", **results}


def parse_access_log_incremental():
    """
    Parse access log incrementally - only new entries since last check.
    
    Returns:
        dict: {uuid: set(ips)}
    """
    redis = get_redis()
    connections = defaultdict(set)
    
    # Find existing log file
    log_file = None
    for path in ACCESS_LOG_PATHS:
        if os.path.exists(path):
            log_file = path
            break
    
    if not log_file:
        return connections
    
    try:
        # Get last read position
        last_position = int(redis.get(LAST_LOG_POSITION_KEY) or 0)
        
        with open(log_file, 'rb') as f:
            # Get file size
            f.seek(0, 2)
            file_size = f.tell()
            
            # If file is smaller than last position, it was rotated
            if file_size < last_position:
                last_position = 0
            
            # Seek to last position
            f.seek(last_position)
            content = f.read().decode('utf-8', errors='ignore')
            
            # Save new position
            redis.set(LAST_LOG_POSITION_KEY, f.tell())
        
        # Parse log lines
        # Format: "2026/01/02 14:32:15 [email] from [ip:port] accepted [dest]"
        # Or: "timestamp email from ip:port..."
        
        for line in content.split('\n'):
            if not line.strip():
                continue
            
            # Try to extract UUID and IP
            uuid, ip = parse_log_line(line)
            if uuid and ip:
                connections[uuid].add(ip)
                
    except Exception as e:
        logger.debug(f"Error parsing access log: {e}")
    
    return connections


def parse_log_line(line):
    """
    Parse a single log line to extract UUID and source IP.
    
    Returns:
        tuple: (uuid, ip) or (None, None)
    """
    try:
        uuid = None
        ip = None
        
        # Extract email/uuid (format: uuid@hiddify.com or just uuid)
        email_match = re.search(r'([a-f0-9-]{36})@', line, re.IGNORECASE)
        if email_match:
            uuid = email_match.group(1)
        else:
            # Try to find UUID pattern directly
            uuid_match = re.search(r'\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b', line, re.IGNORECASE)
            if uuid_match:
                uuid = uuid_match.group(1)
        
        # Extract source IP (format: from IP:port or from [IP]:port)
        ip_match = re.search(r'from\s+\[?(\d+\.\d+\.\d+\.\d+)\]?:\d+', line)
        if ip_match:
            ip = ip_match.group(1)
        else:
            # Try IPv6 format
            ipv6_match = re.search(r'from\s+\[?([a-fA-F0-9:]+)\]?:\d+', line)
            if ipv6_match and ':' in ipv6_match.group(1):
                ip = ipv6_match.group(1)
        
        return uuid, ip
        
    except Exception:
        return None, None


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


def disconnect_and_block_user(redis, user: User, block_seconds: int):
    """
    Disconnect a user and block them temporarily.
    """
    try:
        uuid = str(user.uuid)
        
        # Set block flag
        block_key = USER_BLOCKED_KEY.format(uuid=uuid)
        redis.setex(block_key, block_seconds, "1")
        
        # Remove user from Xray (disconnects all connections)
        user_driver.remove_client(user)
        
        # Clear their tracked IPs
        ip_key = USER_IPS_KEY.format(uuid=uuid)
        redis.delete(ip_key)
        
        # Wait a moment
        time.sleep(0.5)
        
        # Re-add user if active (they can reconnect, but will be limited)
        if user.is_active:
            user_driver.add_client(user)
            
        logger.info(f"Disconnected and blocked user {user.name} for {block_seconds}s")
        
    except Exception as e:
        logger.error(f"Failed to disconnect user {user.name}: {e}")
        raise


def is_user_blocked(redis, uuid):
    """Check if user is currently blocked."""
    block_key = USER_BLOCKED_KEY.format(uuid=uuid)
    return redis.exists(block_key)


def cleanup_expired_blocks(redis):
    """Clean up expired block entries (Redis handles this automatically with SETEX)."""
    pass  # Redis TTL handles this


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


# API functions for external use
def get_user_connection_info(uuid):
    """
    Get connection info for a user (for monitoring page).
    
    Returns:
        dict: {"ip_count": int, "ips": list, "is_blocked": bool}
    """
    redis = get_redis()
    return {
        "ip_count": get_user_ip_count(redis, uuid),
        "ips": get_user_active_ips(redis, uuid),
        "is_blocked": is_user_blocked(redis, uuid)
    }


def force_disconnect_user(uuid):
    """
    Manually disconnect and block a user.
    """
    redis = get_redis()
    user = User.query.filter(User.uuid == uuid).first()
    if user:
        disconnect_and_block_user(redis, user, BLOCK_DURATION * 2)
        return True
    return False

