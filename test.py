import os
import socket
import subprocess
import threading
import time
import signal
import json
from prometheus_client import start_http_server, Gauge

class RDMAPerf:
    def __init__(self, role, device=None, threads=1, qdepth=512, size=65536, duration=60,
                 server_ip=None, base_port=18515, log_csv=False, log_json=False,
                 persistent_server=False, enable_prometheus=False, prometheus_port=9100,
                 client_id=0, test_type="write"):
        self.role = role
        self.device = device or self.auto_detect_rdma_device()
        self.threads = threads
        self.qdepth = qdepth
        self.size = size
        self.duration = duration
        self.server_ip = server_ip
        self.base_port = base_port
        self.log_csv = log_csv
        self.log_json = log_json
        self.persistent_server = persistent_server
        self.enable_prometheus = enable_prometheus
        self.prometheus_port = prometheus_port
        self.client_id = client_id
        self.test_type = test_type
        self.port = 1
        self.max_dynamic_threads = 64
        self.active_threads = {}
        self.monitor_thread = None
        self.monitor_stop = threading.Event()

        self.use_report_gbits = True
        self.report_per_second = True

        self.results = []
        self.server_thread_log = {}

        self.tx_bytes = Gauge('rdma_tx_bytes', 'Total transmitted bytes')
        self.rx_bytes = Gauge('rdma_rx_bytes', 'Total received bytes')
        self.tx_pps = Gauge('rdma_tx_pps', 'Transmitted packets per second')
        self.rx_pps = Gauge('rdma_rx_pps', 'Received packets per second')
        self.thread_count = Gauge('rdma_active_threads', 'RDMA listener threads')
        self.port_binary = Gauge('rdma_server_port_binary', 'RDMA binary used per port', ['port', 'binary'])
        self.port_core = Gauge('rdma_server_thread_core', 'CPU core per RDMA port', ['port', 'core'])
        self.port_respawns = Gauge('rdma_server_thread_respawns', 'Number of times server thread respawned', ['port'])

        self.numa_node = self.get_numa_node()
        self.cpu_cores = self.get_cpu_cores()
        self.interface = self.get_interface_from_device()

        if self.role == "client" and not self.server_ip:
            raise ValueError("Client mode requires --server-ip")

    def auto_detect_rdma_device(self):
        base_path = "/sys/class/infiniband"
        for dev in os.listdir(base_path):
            net_path = os.path.join(base_path, dev, "device/net")
            if os.path.exists(net_path):
                ifaces = os.listdir(net_path)
                if ifaces:
                    return dev
        raise RuntimeError("No RDMA device found.")

    def get_numa_node(self):
        try:
            with open(f"/sys/class/infiniband/{self.device}/device/numa_node") as f:
                return int(f.read().strip())
        except:
            return -1

    def get_cpu_cores(self):
        if self.numa_node == -1:
            return list(range(self.threads))
        try:
            output = subprocess.check_output(f"lscpu | grep 'NUMA node{self.numa_node} CPU(s)'", shell=True).decode()
            cpu_list = output.split(':')[1].strip()
            cores = []
            for part in cpu_list.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    cores.extend(range(start, end + 1))
                else:
                    cores.append(int(part))
            return cores[:max(self.threads, self.max_dynamic_threads)]
        except:
            return list(range(self.threads))

    def get_interface_from_device(self):
        try:
            path = f"/sys/class/infiniband/{self.device}/device/net"
            return os.listdir(path)[0] if os.path.exists(path) else "unknown"
        except:
            return "unknown"

    def check_link_status(self):
        try:
            if self.interface == "unknown":
                return False
            path = f"/sys/class/net/{self.interface}/operstate"
            with open(path) as f:
                return f.read().strip() == "up"
        except:
            return False

    def build_common_args(self):
        args = []
        if self.use_report_gbits:
            args.append("--report_gbits")
        if self.report_per_second:
            args.append("--report_per_second")
        return " ".join(args)

    def parse_ib_output(self, output):
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "BW" in line or "MsgRate" in line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                try:
                    return {
                        "bytes": int(parts[0]),
                        "iterations": int(parts[1]),
                        "bw_avg_gbps": float(parts[3]),
                        "msg_rate_mpps": float(parts[4]),
                    }
                except Exception:
                    continue
        return {}

    def run_client_thread(self, cmd, thread_id):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
        stdout, stderr = proc.communicate()
        result = self.parse_ib_output(stdout)
        if result:
            result["thread_id"] = thread_id
            self.results.append(result)
            print(f"[Thread {thread_id}] BW_avg = {result['bw_avg_gbps']} Gbps, MsgRate = {result['msg_rate_mpps']} Mpps")
        else:
            print(f"[Thread {thread_id}] Failed to parse output")

    def run(self):
        print(f"Role: {self.role}  Device: {self.device}  Port: {self.port}")
        print(f"Threads: {self.threads}  QDepth: {self.qdepth}  Size: {self.size} bytes  Duration: {self.duration} sec")

        if self.role == "client":
            threads = []
            for i in range(self.threads):
                if not self.rate_limit or not self.rate_units:
                    print(f"[Thread {i}] Skipping: Missing or invalid rate limit config")
                    continue
                core = self.cpu_cores[i % len(self.cpu_cores)]
                port = self.base_port + (self.client_id * self.threads) + i
                binary = {
                    "write": "ib_write_bw",
                    "read": "ib_read_bw",
                    "send": "ib_send_bw"
                }.get(self.test_type, "ib_write_bw")
                common_args = self.build_common_args()
                cmd = (
                    f"taskset -c {core} {binary} -d {self.device} -i {self.port} -F -s {self.size} "
                    f"-q {self.qdepth} {common_args} --duration {self.duration} --port {port} {self.server_ip}"
                )
                print(f"[Thread {i}] Launching: {cmd}")
                t = threading.Thread(target=self.run_client_thread, args=(cmd, i))
                t.start()
                threads.append(t)
                time.sleep(0.1)

            for t in threads:
                t.join()

            if self.log_csv or self.log_json:
                self.save_results()

        elif self.role == "server" and self.persistent_server:
            print("Starting dynamic persistent server accepting unlimited clients...")

            if self.enable_prometheus:
                start_http_server(self.prometheus_port)
                threading.Thread(target=self.update_metrics_loop, daemon=True).start()

            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.monitor_thread.start()

            try:
                i = 0
                binaries = ["ib_write_bw", "ib_read_bw", "ib_send_bw"]
                while True:
                    if len(self.active_threads) >= self.max_dynamic_threads:
                        time.sleep(5)
                        continue
                    core = self.cpu_cores[i % len(self.cpu_cores)]
                    port = self.base_port + i
                    binary = binaries[i % len(binaries)]
                    self.launch_persistent_server_thread(core, port, binary)
                    print(f"Started listener on port {port} using {binary}")
                    i += 1
                    time.sleep(1.0)
            except KeyboardInterrupt:
                print("Shutting down persistent server threads...")
                self.monitor_stop.set()
                for proc in self.active_threads.values():
                    try:
                        os.kill(proc.pid, signal.SIGTERM)
                    except:
                        pass
                if self.log_csv or self.log_json:
                    self.save_server_logs()

    def save_results(self):
        if self.log_csv:
            try:
                with open("rdma_summary.csv", "w") as f:
                    f.write("thread_id,bw_avg_gbps,msg_rate_mpps\n")
                    for r in self.results:
                        f.write(f"{r['thread_id']},{r['bw_avg_gbps']},{r['msg_rate_mpps']}\n")
                print("[CSV] Summary saved to rdma_summary.csv")
            except Exception as e:
                print(f"[CSV] Failed to write: {e}")
        if self.log_json:
            try:
                with open("rdma_summary.json", "w") as f:
                    json.dump(self.results, f, indent=2)
                print("[JSON] Summary saved to rdma_summary.json")
            except Exception as e:
                print(f"[JSON] Failed to write: {e}")

    def launch_persistent_server_thread(self, core, port, binary):
        common_args = self.build_common_args()
        cmd = f"taskset -c {core} bash -c 'while true; do {binary} -d {self.device} -i {self.port} -F -s {self.size} -q {self.qdepth} {common_args} --port {port}; sleep 1; done'"
        print(f"[Thread Dynamic] {cmd}")
        try:
            proc = subprocess.Popen(cmd, shell=True)
            self.active_threads[port] = proc
            self.port_binary.labels(port=str(port), binary=binary).set(1)
            self.port_core.labels(port=str(port), core=str(core)).set(1)
            if port not in self.port_respawns._metrics:
                self.port_respawns.labels(port=str(port)).set(0)
            else:
                self.port_respawns.labels(port=str(port)).inc()
            self.server_thread_log[port] = {
                "port": port,
                "binary": binary,
                "core": core,
                "respawns": int(self.port_respawns.labels(port=str(port))._value.get())
            }
        except Exception as e:
            print(f"[ERROR] Failed to start {binary} on port {port}: {e}")

    def save_server_logs(self):
        if self.log_csv:
            try:
                with open("rdma_server_log.csv", "w") as f:
                    f.write("port,binary,core,respawns\n")
                    for entry in self.server_thread_log.values():
                        f.write(f"{entry['port']},{entry['binary']},{entry['core']},{entry['respawns']}\n")
                print("[CSV] Server log saved to rdma_server_log.csv")
            except Exception as e:
                print(f"[CSV] Server log error: {e}")
        if self.log_json:
            try:
                with open("rdma_server_log.json", "w") as f:
                    json.dump(list(self.server_thread_log.values()), f, indent=2)
                print("[JSON] Server log saved to rdma_server_log.json")
            except Exception as e:
                print(f"[JSON] Server log error: {e}")

    def monitor_loop(self):
        while not self.monitor_stop.is_set():
            for port, proc in list(self.active_threads.items()):
                if proc.poll() is not None:
                    print(f"[Monitor] Restarting dead thread on port {port}")
                    binary = self.server_thread_log[port]["binary"]
                    core = self.server_thread_log[port]["core"]
                    self.launch_persistent_server_thread(core, port, binary)
            time.sleep(5)

    def update_metrics_loop(self):
        while not self.monitor_stop.is_set():
            self.thread_count.set(len(self.active_threads))
            time.sleep(5)