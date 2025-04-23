import os
import subprocess
import threading
import time
import json
import csv
from datetime import datetime
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
        self.results = []

        self.cpu_cores = self.get_cpu_cores()
        self.supports_report_per_second = self.check_binary_supports("--report_per_second", "ib_write_bw")
        self.use_report_gbits = True
        self.report_per_second = True

        self.active_threads = {}
        self.monitor_stop = threading.Event()
        self.server_thread_log = {}

        # Prometheus metrics
        self.thread_count = Gauge('rdma_active_threads', 'RDMA listener threads')
        self.port_binary = Gauge('rdma_server_port_binary', 'RDMA binary used per port', ['port', 'binary'])
        self.port_core = Gauge('rdma_server_thread_core', 'CPU core per RDMA port', ['port', 'core'])
        self.port_respawns = Gauge('rdma_server_thread_respawns', 'Number of times server thread respawned', ['port'])

        os.makedirs("logs", exist_ok=True)

    def auto_detect_rdma_device(self):
        base_path = "/sys/class/infiniband"
        for dev in os.listdir(base_path):
            if os.path.isdir(os.path.join(base_path, dev, "device/net")):
                return dev
        raise RuntimeError("No RDMA device found.")

    def get_cpu_cores(self):
        try:
            output = subprocess.check_output("nproc", shell=True).decode()
            return list(range(int(output.strip())))
        except:
            return list(range(64))

    def check_binary_supports(self, flag, binary):
        try:
            out = subprocess.check_output([binary, "--help"], stderr=subprocess.STDOUT, text=True)
            return flag in out
        except:
            return False

    def build_common_args(self, binary=None):
        args = []
        if self.use_report_gbits:
            args.append("--report_gbits")
        if self.report_per_second and binary == "ib_write_bw" and self.supports_report_per_second:
            args.append("--report_per_second")
        return " ".join(args)

    def parse_ib_output(self, output):
        lines = output.strip().splitlines()
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 5:
                try:
                    return {
                        "bytes": int(parts[0]),
                        "iterations": int(parts[1]),
                        "bw_avg_gbps": float(parts[3]),
                        "msg_rate_mpps": float(parts[4])
                    }
                except:
                    continue
        return {}

    def run_thread(self, cmd, thread_id, meta_file=None):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
        stdout, stderr = proc.communicate()

        if meta_file:
            with open(meta_file, "w") as f:
                f.write(stdout + "\n" + stderr)

        result = self.parse_ib_output(stdout)
        if result:
            result["thread_id"] = thread_id
            self.results[thread_id] = result
            print(
                f"[Thread {thread_id}] BW_avg = {result['bw_avg_gbps']} Gbps, MsgRate = {result['msg_rate_mpps']} Mpps")
        else:
            print(f"[Thread {thread_id}] Failed to parse output")

    def run(self):
        print(f"Role: {self.role}  Device: {self.device}  Threads: {self.threads}  Duration: {self.duration}s")
        binary = {
            "write": "ib_write_bw",
            "read": "ib_read_bw",
            "send": "ib_send_bw"
        }.get(self.test_type, "ib_write_bw")

        if self.role == "client":
            threads = []
            for i in range(self.threads):
                port = self.base_port + (self.client_id * self.threads) + i
                core = self.cpu_cores[i % len(self.cpu_cores)]
                args = self.build_common_args(binary)
                cmd = (
                    f"taskset -c {core} {binary} -d {self.device} -i 1 -F -s {self.size} "
                    f"-q {self.qdepth} {args} --duration {self.duration} --port {port} {self.server_ip}"
                )
                print(f"[Client {i}] Launching: {cmd}")
                t = threading.Thread(target=self.run_thread, args=(cmd, i))
                t.start()
                threads.append(t)
                time.sleep(0.1)
            for t in threads:
                t.join()
            self.log_results("client", self.client_id)



        elif self.role == "server" and not self.persistent_server:
            print("[One-shot] Starting server...")
            self.results = [None] * self.threads
            threads = []

            for i in range(self.threads):
                port = self.base_port + i
                core = self.cpu_cores[i % len(self.cpu_cores)]
                args = self.build_common_args(binary)
                cmd = (
                    f"taskset -c {core} {binary} -d {self.device} -i 1 -F -s {self.size} "
                    f"-q {self.qdepth} {args} --port {port}"
                )
                print(f"[Server {i}] Launching: {cmd}")
                meta_path = f"logs/server_meta_{port}.txt"
                t = threading.Thread(target=self.run_thread, args=(cmd, i, meta_path))
                t.start()
                threads.append(t)
                time.sleep(0.1)

            try:
                for t in threads:
                    t.join()
            except KeyboardInterrupt:
                print("\n[!] Interrupted. Attempting to collect partial results...")
                for t in threads:
                    t.join(timeout=1)

            self.results = [r for r in self.results if r]
            self.log_results("server", f"{self.base_port}_{self.threads}")


        elif self.role == "server" and self.persistent_server:
            print("Starting persistent server...")
            if self.enable_prometheus:
                print(f"[Prometheus] Starting metrics server on port {self.prometheus_port}")
                start_http_server(self.prometheus_port)
                print("[Prometheus] Metrics HTTP server started")
                threading.Thread(target=self.monitor_loop, daemon=True).start()
            for i in range(self.threads):
                port = self.base_port + i
                core = self.cpu_cores[i % len(self.cpu_cores)]
                self.launch_persistent_server_thread(core, port, binary)
                time.sleep(1.0)
    def log_results(self, role, id_val):
        if not self.log_csv and not self.log_json:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.log_csv:
            csv_file = f"logs/{role}_{id_val}_{ts}.csv"
            with open(csv_file, "w", newline="") as f:
                writer = csv.DictWriter(f,
                                        fieldnames=["thread_id", "bytes", "iterations", "bw_avg_gbps", "msg_rate_mpps"])
                writer.writeheader()
                for row in self.results:
                    writer.writerow(row)
        if self.log_json:
            json_file = f"logs/{role}_{id_val}_{ts}.json"
            with open(json_file, "w") as f:
                json.dump(self.results, f, indent=2)

    def launch_persistent_server_thread(self, core, port, binary):
        args = self.build_common_args(binary)
        cmd = f"taskset -c {core} bash -c 'while true; do {binary} -d {self.device} -i 1 -F -s {self.size} -q {self.qdepth} {args} --port {port}; sleep 1; done'"
        print(f"[Persistent Thread] {cmd}")
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

    def monitor_loop(self):
        while not self.monitor_stop.is_set():
            for port, proc in list(self.active_threads.items()):
                if proc.poll() is not None:
                    print(f"[Monitor] Respawning port {port}")
                    data = self.server_thread_log[port]
                    self.launch_persistent_server_thread(data["core"], port, data["binary"])
            time.sleep(5)
