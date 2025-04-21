# run_rdma_test.py

import argparse
import subprocess
import threading
import time
import os
import signal
from rdma_perf_tool import RDMAPerf

def cleanup_stale_ib_write_bw():
    print("[Startup] Checking for stale RDMA benchmark listeners...")
    binaries = ["ib_write_bw", "ib_read_bw", "ib_send_bw"]
    for binary in binaries:
        try:
            result = subprocess.check_output(f"pgrep -f {binary}", shell=True).decode().strip().splitlines()
            pids = [int(pid) for pid in result]
            if pids:
                print(f"[Cleanup] Terminating {len(pids)} stale {binary} processes...")
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        except subprocess.CalledProcessError:
            continue  # No such processes found

def auto_select_active_mellanox_interface():
    base_path = "/sys/class/infiniband"
    for dev in os.listdir(base_path):
        net_dir = os.path.join(base_path, dev, "device/net")
        if os.path.isdir(net_dir):
            for iface in os.listdir(net_dir):
                operstate_path = f"/sys/class/net/{iface}/operstate"
                if os.path.exists(operstate_path):
                    with open(operstate_path) as f:
                        if f.read().strip() == "up":
                            return iface
    return None

def cnp_watch(interface, interval=5, stop_event=None):
    print(f"[CNP Watch] Monitoring CNP counters on {interface} every {interval}s...")
    debugfs_cc_dir = "/sys/kernel/debug/mlx5"

    while not stop_event.is_set():
        try:
            output = subprocess.check_output(
                f"ethtool -S {interface} 2>/dev/null | grep -i cnp",
                shell=True
            ).decode()
            if output.strip():
                print(f"[CNP] {time.strftime('%X')}\n{output.strip()}\n")
            else:
                print(f"[CNP] {time.strftime('%X')} - No CNP stats via ethtool")

        except subprocess.CalledProcessError:
            # fallback to debugfs
            try:
                for dev in os.listdir(debugfs_cc_dir):
                    cc_path = os.path.join(debugfs_cc_dir, dev, "cc_params")
                    if os.path.isdir(cc_path):
                        params = {}
                        for f in ["rp_threshold", "rp_clamp_tgt_rate", "rp_dce_tcp_g"]:
                            full = os.path.join(cc_path, f)
                            if os.path.exists(full):
                                with open(full) as fp:
                                    params[f] = fp.read().strip()
                        print(f"[CNP DebugFS] {time.strftime('%X')} {params}")
                        break
                else:
                    print("[CNP Watch] No cc_params found under debugfs/mlx5")
            except Exception as e:
                print(f"[CNP Watch] DebugFS fallback failed: {e}")
        time.sleep(interval)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RDMA traffic test using ib_write_bw")
    parser.add_argument("--role", choices=["server", "client"], required=True, help="Run as server or client")
    parser.add_argument("--device", help="RDMA device name (auto-detected if not set)")
    parser.add_argument("--server-ip", help="Server IP address (client mode only)")
    parser.add_argument("--qdepth", type=int, default=1024, help="Queue depth per thread")
    parser.add_argument("--size", type=int, default=65536, help="Message size in bytes")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--link-speed", type=int, default=400, help="Total link speed in Gbps")
    parser.add_argument("--per-thread-gbps", type=float, default=50.0, help="Expected Gbps per thread")
    parser.add_argument("--log-csv", action="store_true", help="Enable CSV logging")
    parser.add_argument("--log-json", action="store_true", help="Enable JSON logging")
    parser.add_argument("--monitor-cnp", action="store_true", help="Enable live CNP monitoring")
    parser.add_argument("--multi-port-server", action="store_true", help="Enable persistent multi-port server")
    parser.add_argument("--base-port", type=int, default=18515, help="Base TCP port for RDMA sessions")
    parser.add_argument("--client-id", type=int, default=0, help="Unique ID for client to compute port offset")

    args = parser.parse_args()
    threads = max(1, int(args.link_speed / args.per_thread_gbps))

    print(f"Auto-calculated thread count: {threads} for target {args.link_speed} Gbps")
    cleanup_stale_ib_write_bw()

    perf = RDMAPerf(
        role=args.role,
        device=args.device,
        threads=threads,
        qdepth=args.qdepth,
        size=args.size,
        duration=args.duration,
        server_ip=args.server_ip,
        base_port=args.base_port,
        log_csv=args.log_csv,
        log_json=args.log_json,
        persistent_server=args.multi_port_server,
        client_id=args.client_id
    )

    if args.monitor_cnp:
        if not perf.interface or perf.interface == "unknown":
            perf.interface = auto_select_active_mellanox_interface()

        if not perf.interface or perf.interface == "unknown":
            print("[CNP Watch] No active interface found for CNP monitoring")
        else:
            cnp_stop_event = threading.Event()
            cnp_thread = threading.Thread(target=cnp_watch, args=(perf.interface, 5, cnp_stop_event))
            cnp_thread.start()

    perf.run()

    if args.monitor_cnp and perf.interface:
        cnp_stop_event.set()
        cnp_thread.join()