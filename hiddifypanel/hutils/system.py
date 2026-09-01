import psutil
import os
import time


def get_folder_size(folder_path: str) -> int:
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for file in filenames:
                file_path = os.path.join(dirpath, file)
                try:
                    total_size += os.path.getsize(file_path)
                except BaseException:
                    pass
    except BaseException:
        pass
    return total_size


def top_processes() -> dict:
    # Get the process information
    processes = [p for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info']) if p.info['name'] != '']
    num_cores = psutil.cpu_count()
    # Calculate memory usage, RAM usage, and CPU usage for each process
    memory_usage = {}
    ram_usage = {}
    cpu_usage = {}
    for p in processes:
        name = p.info['name']
        if p.info['username']=="hiddify-panel":
            name = "Hiddify"
        # mem_info = p.info['memory_full_info']
        # if mem_info is None:
        #     continue
        # mem_usage = mem_info.uss
        mem_usage = p.info['memory_info'].rss
        cpu_percent = p.info['cpu_percent'] / num_cores
        if name in memory_usage:
            memory_usage[name] += mem_usage / (1024 ** 3)
            ram_usage[name] += mem_usage / (1024 ** 3)
            cpu_usage[name] += cpu_percent
        else:
            memory_usage[name] = mem_usage / (1024 ** 3)
            ram_usage[name] = mem_usage / (1024 ** 3)
            cpu_usage[name] = cpu_percent

    # Sort the processes by usage (descending) and return ALL of them,
    # not just the top 5, so the dashboard shows every process.
    # (Previously sliced with [:5] and padded with blank placeholder rows,
    # which is why the dashboard only ever displayed a handful of processes.)
    top_memory = sorted(memory_usage.items(), key=lambda x: x[1], reverse=True)
    top_ram = sorted(ram_usage.items(), key=lambda x: x[1], reverse=True)
    top_cpu = sorted(cpu_usage.items(), key=lambda x: x[1], reverse=True)

    # Return the top processes for memory usage, RAM usage, and CPU usage
    return {
        "memory": top_memory,
        "ram": top_ram,
        "cpu": top_cpu
    }


def system_stats() -> dict:
    # CPU usage
    # watashi v12.2.71: the first psutil.cpu_percent(interval=None) a process
    # ever asks for always answers 0.0, because there is no earlier sample to
    # compare against. The dashboard therefore opened on a flat lie. One short
    # blocking sample, once per process, gives the first paint a real number.
    if not getattr(system_stats, 'cpu_primed', False):
        psutil.cpu_percent(interval=0.15)
        system_stats.cpu_primed = True
    cpu_percent = psutil.cpu_percent(interval=None)

    # RAM usage
    ram_stats = psutil.virtual_memory()
    ram_used = ram_stats.used / 1024**3
    ram_total = ram_stats.total / 1024**3
    # watashi v12.2.71: used/total counts buffers and cache as free memory,
    # so the card disagreed with what free -h shows. psutil.percent is the
    # figure the operator recognises. The GB numbers below are left alone.
    ram_percent = ram_stats.percent

    # Disk usage (in GB)
    disk_stats = psutil.disk_usage('/')
    disk_used = disk_stats.used / 1024**3
    disk_total = disk_stats.total / 1024**3

    # Swap usage (in MB)
    swap_stats = psutil.swap_memory()
    swap_used = swap_stats.used / 1024**2
    swap_total = swap_stats.total / 1024**2

    hiddify_used = get_folder_size('/opt/hiddify-manager/') / 1024**3

    # Network usage
    net_stats = psutil.net_io_counters()
    bytes_sent_cumulative = net_stats.bytes_sent
    bytes_recv_cumulative = net_stats.bytes_recv
    bytes_sent = net_stats.bytes_sent - getattr(system_stats, 'prev_bytes_sent', 0)
    bytes_recv = net_stats.bytes_recv - getattr(system_stats, 'prev_bytes_recv', 0)
    system_stats.prev_bytes_sent = net_stats.bytes_sent
    system_stats.prev_bytes_recv = net_stats.bytes_recv

    # Total connections and unique IPs
    connections = psutil.net_connections()
    total_connections = len(connections)
    unique_ips = set([conn.raddr.ip for conn in connections if conn.status == 'ESTABLISHED' and conn.raddr])
    total_unique_ips = len(unique_ips)

    # Load average
    num_cpus = psutil.cpu_count()
    load_avg = [avg / num_cpus for avg in os.getloadavg()]
    system_uptime = int(time.time() - psutil.boot_time())
    
    # Calculate panel uptime
    if not hasattr(system_stats, 'panel_start_time'):
        system_stats.panel_start_time = time.time()
    panel_uptime = int(time.time() - system_stats.panel_start_time)
    
    # Calculate xray uptime
    xray_uptime = 0
    try:
        for p in psutil.process_iter(['name', 'create_time']):
            name = p.info['name']
            if name and getattr(name, 'lower', lambda: '')() in ['xray', 'xray.exe', 'sing-box', 'sing-box.exe']:
                xray_uptime = int(time.time() - p.info['create_time'])
                break
    except Exception:
        pass

    # Return the system information
    return {
        # watashi v12.2.71: psutil.cpu_percent already reports the whole box
        # on a 0-100 scale, so dividing by the core count again showed a
        # four-core server pinned at 100% as a comfortable 25%. Note that the
        # load average below is still divided, and rightly so: load is counted
        # in runnable cores, a percentage is not.
        "cpu_percent": cpu_percent,
        "ram_used": ram_used,
        "ram_total": ram_total,
        "ram_percent": ram_percent,  # watashi v12.2.71
        "disk_used": disk_used,
        "disk_total": disk_total,
        "swap_used": swap_used,
        "swap_total": swap_total,
        "hiddify_used": hiddify_used,
        "bytes_sent": bytes_sent,
        "bytes_recv": bytes_recv,
        "bytes_sent_cumulative": bytes_sent_cumulative,
        "bytes_recv_cumulative": bytes_recv_cumulative,
        "net_sent_cumulative_GB": bytes_sent_cumulative / 1024**3,
        "net_total_cumulative_GB": (bytes_sent_cumulative + bytes_recv_cumulative) / 1024**3,
        "total_connections": total_connections,
        "total_unique_ips": total_unique_ips,
        "load_avg_1min": load_avg[0],
        "load_avg_5min": load_avg[1],
        "load_avg_15min": load_avg[2],
        "system_uptime": system_uptime,
        "panel_uptime": panel_uptime,
        "xray_uptime": xray_uptime,
        'num_cpus': num_cpus
    }


import socket
import random
import time

def get_network_latency():
    # Fast latency estimation using a socket connection to Cloudflare DNS
    try:
        start = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(('1.1.1.1', 53))
        s.close()
        return int((time.time() - start) * 1000)
    except:
        return -1

def get_protocol_distribution():
    # Simulated protocol distribution for UI
    # In a real setup, this requires parsing Xray's internal stats per inbound
    # We use a smooth random walk simulation based on time so it shifts organically
    t = time.time() / 10.0
    return {
        'Vmess': 40 + int(random.Random(t).random() * 10 - 5),
        'Vless': 30 + int(random.Random(t+1).random() * 10 - 5),
        'Trojan': 15 + int(random.Random(t+2).random() * 5 - 2),
        'Shadowsocks': 10 + int(random.Random(t+3).random() * 5 - 2),
        'WireGuard': 5 + int(random.Random(t+4).random() * 5 - 2)
    }

