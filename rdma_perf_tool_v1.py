import os
import socket
import subprocess
import multiprocessing
import threading
import time
import signal
from prometheus_client import start_http_server, Gauge

class RDMAPerf:
    def __init__(self, role, device=None, threads=1, qdepth=512, size=65536, duration=60,
                 server_ip=None, base_port=18515, log_csv=False, log_json=False,
                 persistent_server=False, enable_prometheus=False, prometheus_port=9100,
                 client_id=0):
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
        self.port = 1
        self.max_dynamic_threads = 64
        self.active_threads = {}
        self.monitor_thread = None
        self.monitor_stop = threading.Event()

        self.tx_bytes = Gauge('rdma_tx_bytes', 'Total transmitted bytes')
        self.rx_bytes = Gauge('rdma_rx_bytes', 'Total received bytes')
        self.tx_pps = Gauge('rdma_tx_pps', 'Transmitted packets per second')
        self.rx_pps = Gauge('rdma_rx_pps', 'Received packets per second')
        self.thread_count = Gauge('rdma_active_threads', 'RDMA listener threads')

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

    def read_interface_stats(self):
        iface = self.interface
        try:
            with open(f"/sys/class/net/{iface}/statistics/tx_bytes") as f:
                tx_bytes = int(f.read().strip())
            with open(f"/sys/class/net/{iface}/statistics/rx_bytes") as f:
                rx_bytes = int(f.read().strip())
            with open(f"/sys/class/net/{iface}/statistics/tx_packets") as f:
                tx_pkts = int(f.read().strip())
            with open(f"/sys/class/net/{iface}/statistics/rx_packets") as f:
                rx_pkts = int(f.read().strip())
            return {
                'tx_bytes': tx_bytes,
                'rx_bytes': rx_bytes,
                'tx_pps': tx_pkts,
                'rx_pps': rx_pkts,
            }
        except:
            return {'tx_bytes': 0, 'rx_bytes': 0, 'tx_pps': 0, 'rx_pps': 0}

    def update_metrics_loop(self):
        while not self.monitor_stop.is_set():
            stats = self.read_interface_stats()
            self.tx_bytes.set(stats['tx_bytes'])
            self.rx_bytes.set(stats['rx_bytes'])
            self.tx_pps.set(stats['tx_pps'])
            self.rx_pps.set(stats['rx_pps'])
            self.thread_count.set(len(self.active_threads))
            time.sleep(5)

    def find_free_port(self, start):
        port = start
        while port < 65535:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(('', port))
                    return port
                except OSError:
                    port += 1
        raise RuntimeError("No free ports available in range.")

    def launch_persistent_server_thread(self, core, port):
        cmd = ["taskset", "-c", str(core), "bash", "-c",
               f"while true; do ib_write_bw -d {self.device} -i {self.port} -F -s {self.size} -q {self.qdepth} --report_gbits --port {port}; sleep 1; done"]
        print(f"[Thread Dynamic] {' '.join(cmd)}")
        proc = subprocess.Popen(cmd)
        self.active_threads[port] = proc

    def monitor_loop(self):
        try:
            while not self.monitor_stop.is_set():
                for port, proc in list(self.active_threads.items()):
                    retcode = proc.poll()
                    if retcode is not None:
                        print(f"[Monitor] Restarting dead thread on port {port}")
                        core = self.cpu_cores[len(self.active_threads) % len(self.cpu_cores)]
                        self.launch_persistent_server_thread(core, port)
                time.sleep(5)
        except Exception as e:
            print(f"[Monitor] Error: {e}")

    def run(self):
        print(f"Role: {self.role}  Device: {self.device}  Port: {self.port}")
        print(f"Interface: {self.interface}  Link: {'UP' if self.check_link_status() else 'DOWN'}")
        print(f"Threads: {self.threads}  QDepth: {self.qdepth}  Size: {self.size} bytes  Duration: {self.duration} sec")
        print(f"Binding to CPU cores: {','.join(map(str, self.cpu_cores))} (NUMA node {self.numa_node})")

        if self.role == "server" and self.persistent_server:
            print("Starting dynamic persistent server accepting unlimited clients...")
            if self.enable_prometheus:
                start_http_server(self.prometheus_port)
                threading.Thread(target=self.update_metrics_loop, daemon=True).start()
            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.monitor_thread.start()

            try:
                i = 0
                while True:
                    if len(self.active_threads) >= self.max_dynamic_threads:
                        time.sleep(5)
                        continue
                    core = self.cpu_cores[i % len(self.cpu_cores)]
                    port = self.find_free_port(self.base_port + i)
                    self.launch_persistent_server_thread(core, port)
                    print(f"Started listener on port {port}")
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
        else:
            processes = []
            assigned_ports = []

            for i in range(self.threads):
                core = self.cpu_cores[i % len(self.cpu_cores)]
                if self.role == "server":
                    port = self.find_free_port(self.base_port + i)
                    assigned_ports.append(port)
                    cmd = f"taskset -c {core} ib_write_bw -d {self.device} -i {self.port} -F -s {self.size} " \
                          f"-q {self.qdepth} --report_gbits --port {port}"
                else:
                    port = self.base_port + (self.client_id * self.threads) + i
                    cmd = f"taskset -c {core} ib_write_bw -d {self.device} -i {self.port} -F -s {self.size} " \
                          f"-q {self.qdepth} --report_gbits --duration {self.duration} --port {port} {self.server_ip}"

                print(f"[Thread {i}] {cmd}")
                proc = multiprocessing.Process(target=os.system, args=(cmd,))
                proc.start()
                processes.append(proc)
                time.sleep(0.1)

            if self.role == "server" and assigned_ports:
                print("Assigned server ports:", ", ".join(map(str, assigned_ports)))

            if self.role == "client":
                for p in processes:
                    p.join()