import os,re,socket
import subprocess
import threading
import time
import json
import csv
from datetime import datetime
from prometheus_client import start_http_server, Gauge

from prometheus_exporter import start_prometheus_exporter

class RDMAPerf:
    def __init__(self, role, device=None, threads=1, qdepth=512, size=65536, duration=60,
                 server_ip=None, base_port=18515, log_csv=False, log_json=False,
                 persistent_server=False, enable_prometheus=False, prometheus_port=9100,
                 client_id=0, test_type="write",use_report_gbits=True,latency="bw"):
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
        self.results = {}
        self.cpu_cores = self.get_cpu_cores()
        self.supports_report_per_second = self.check_binary_supports("--report_per_second", "ib_write_bw")
        self.use_report_gbits = use_report_gbits
        self.report_per_second = True
        self.latency = latency
        self.active_threads = {}
        self.monitor_stop = threading.Event()
        self.server_thread_log = {}

        # Prometheus metrics
        self.thread_count = Gauge('rdma_active_threads', 'RDMA listener threads')
        self.port_binary = Gauge('rdma_server_port_binary', 'RDMA binary used per port', ['port', 'binary'])
        self.port_core = Gauge('rdma_server_thread_core', 'CPU core per RDMA port', ['port', 'core'])
        self.port_respawns = Gauge('rdma_server_thread_respawns', 'Number of times server thread respawned', ['port'])
        self.port_bw_gbps = Gauge('rdma_port_bw_gbps', 'Average bandwidth per port in Gbps', ['port'])
        self.port_msg_rate_mpps = Gauge('rdma_port_msg_rate_mpps', 'Message rate per port in Mpps', ['port'])
        self.port_rkey = Gauge('rdma_port_rkey', 'Last seen RKey per RDMA server port', ['port'])
        self.port_vaddr = Gauge('rdma_port_vaddr', 'Last seen VAddr per RDMA server port', ['port'])

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




    def monitor_bw_output(self, port, stream):
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parts = line.split()
                if len(parts) < 5 or not parts[0].isdigit():
                    continue
                bw_gbps = float(parts[3])
                mpps = float(parts[4])
                self.port_bw_gbps.labels(port=str(port)).set(bw_gbps)
                self.port_msg_rate_mpps.labels(port=str(port)).set(mpps)
                self.results[port] = {
                    "thread_id": port,
                    "bw_avg_gbps": bw_gbps,
                    "msg_rate_mpps": mpps
                }
                print(f"[Metrics] Port {port} BW: {bw_gbps} Gbps, MsgRate: {mpps} Mpps")
            except Exception as e:
                print(f"[WARN] Failed to parse line: {line} - {e}")

    def launch_persistent_server_thread(self, core, port, binary):
        args = self.build_common_args(binary)
        cmd = [
            "taskset", "-c", str(core),
            binary, "-d", self.device, "-i", "1", "-F",
            "-s", str(self.size), "-q", str(self.qdepth),
            "--port", str(port), *args.split()
        ]

        def loop_runner():
            while True:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.monitor_bw_output(port, proc.stdout)
                proc.wait()
                time.sleep(1)

        print(f"[Persistent Thread] Starting monitor thread for port {port}")
        t = threading.Thread(target=loop_runner, daemon=True)
        t.start()

        self.port_binary.labels(port=str(port), binary=binary).set(1)
        self.port_core.labels(port=str(port), core=str(core)).set(1)
        self.port_respawns.labels(port=str(port)).inc()

    def build_common_args(self, binary=None):
        args = []
        if self.latency == "bw":
            args.append("--report_gbits")
        if self.report_per_second and binary == "ib_write_bw" and self.supports_report_per_second:
            args.append("--report_per_second")
        return " ".join(args)

    def is_port_in_use(self, port):
        """Check if TCP port is occupied on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
    def run(self):
        if self.latency != "bw":
            binary = {
                "write": "ib_write_lat",
                "read": "ib_read_lat",
                "send": "ib_send_lat"
            }.get(self.test_type, "ib_write_lat")
        else:
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

                if self.latency != "bw":
                    cmd = (
                        f"taskset -c {core} {binary} -d {self.device} -F -s {self.size} "
                        f"{args} --port {port} {self.server_ip}"
                    )
                else:
                    cmd = (
                        f"taskset -c {core} {binary} -d {self.device} -i 1 -F -s {self.size} "
                        f"-q {self.qdepth} {args} --duration {self.duration} --port {port} {self.server_ip}"
                    )

                print(f"[Client {i}] Launching: {cmd}")

                def thread_runner(cmd=cmd, thread_id=i):
                    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    stdout, stderr = proc.communicate()

                    if proc.returncode != 0:
                        print(f"[ERROR] Thread {thread_id} failed with return code {proc.returncode}")
                        print(f"[STDERR] {stderr.strip()}")
                        return

                    header_seen = False
                    for line in stdout.splitlines():
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            self.results.setdefault(thread_id, {"thread_id": thread_id})

                            if "QPN" in line and "RKey" in line:
                                match_qpn = re.search(r"QPN\s+(0x[0-9a-fA-F]+)", line)
                                match_rkey = re.search(r"RKey\s+(0x[0-9a-fA-F]+)", line)
                                match_vaddr = re.search(r"VAddr\s+(0x[0-9a-fA-F]+)", line)
                                if match_qpn and match_rkey and match_vaddr:
                                    self.results[thread_id].setdefault("connections", []).append({
                                        "qpn": match_qpn.group(1),
                                        "rkey": match_rkey.group(1),
                                        "vaddr": match_vaddr.group(1)
                                    })

                            elif line.startswith("GID:"):
                                gid = line.split("GID:")[1].strip()
                                self.results[thread_id]["gid"] = gid

                            elif line.startswith("-") and len(set(line)) == 1:
                                header_seen = True
                                continue

                            elif self.latency != "bw" and header_seen and re.match(r"^\d+\s+\d+", line):
                                parts = line.split()
                                if len(parts) >= 9:
                                    self.results[thread_id].update({
                                        "payload_size": int(parts[0]),
                                        "iterations": int(parts[1]),
                                        "t_min_usec": float(parts[2]),
                                        "t_max_usec": float(parts[3]),
                                        "t_typical_usec": float(parts[4]),
                                        "t_avg_usec": float(parts[5]),
                                        "t_stdev_usec": float(parts[6]),
                                        "t_99_percentile_usec": float(parts[7]),
                                        "t_999_percentile_usec": float(parts[8]),
                                    })
                                    print(f"[Thread {thread_id}] Avg Latency = {parts[5]} usec")

                            elif self.latency == "bw" and len(line.split()) >= 5 and line.split()[0].isdigit():
                                parts = line.split()
                                bw_gbps = float(parts[3])
                                mpps = float(parts[4])
                                self.results[thread_id].update({
                                    "bw_avg_gbps": bw_gbps,
                                    "msg_rate_mpps": mpps
                                })
                                print(f"[Thread {thread_id}] BW = {bw_gbps:.2f} Gbps, MsgRate = {mpps:.3f} Mpps")

                        except Exception as e:
                            print(f"[WARN] Parsing error on thread {thread_id}: {e}")
                            continue

                t = threading.Thread(target=thread_runner)
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

            if self.latency != "bw":
                all_latencies = [r["t_avg_usec"] for r in self.results.values() if "t_avg_usec" in r]
                if all_latencies:
                    avg_latency = sum(all_latencies) / len(all_latencies)
                    best_thread = min(self.results, key=lambda k: self.results[k].get("t_avg_usec", float('inf')))
                    worst_thread = max(self.results, key=lambda k: self.results[k].get("t_avg_usec", 0))
                    print("\n[Summary] Client Latency:")
                    print(f"- Avg across all threads: {avg_latency:.2f} usec")
                    print(f"- Best thread {best_thread}: {self.results[best_thread]['t_avg_usec']:.2f} usec")
                    print(f"- Worst thread {worst_thread}: {self.results[worst_thread]['t_avg_usec']:.2f} usec")

            self.log_results("client", self.client_id)

        elif self.role == "server" and not self.persistent_server:
            print("[One-shot] Starting server...")
            threads = []

            for i in range(self.threads):
                port = self.base_port + i
                core = self.cpu_cores[i % len(self.cpu_cores)]
                args = self.build_common_args(binary)

                if self.latency != "bw":
                    cmd = (
                        f"taskset -c {core} {binary} -d {self.device} -F -s {self.size} "
                        f"{args} --port {port}"
                    )
                else:
                    cmd = (
                        f"taskset -c {core} {binary} -d {self.device} -i 1 -F -s {self.size} "
                        f"-q {self.qdepth} {args} --port {port}"
                    )

                print(f"[Server {i}] Launching: {cmd}")

                def thread_runner(cmd=cmd, port=port):
                    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if self.latency != "bw":
                        stdout, stderr = proc.communicate()
                        if proc.returncode != 0:
                            print(f"[Server ERROR] Port {port} exited with {proc.returncode}")
                            print(stderr)
                        else:
                            print(f"[Server INFO] Port {port} latency test completed")
                    else:
                        self.monitor_bw_output(port, proc.stdout)
                        proc.wait()

                t = threading.Thread(target=thread_runner, daemon=True)
                t.start()
                threads.append(t)
                time.sleep(0.1)

            try:
                for t in threads:
                    t.join()
            except KeyboardInterrupt:
                print("\n[!] Interrupted. Dumping logs...")

            self.log_results("server", f"{self.base_port}_{self.threads}")

        elif self.role == "server" and self.persistent_server:
            # Prometheus Start Logic
            if self.enable_prometheus:
                if self.is_port_in_use(self.prometheus_port):
                    print(
                        f"[Prometheus] Port {self.prometheus_port} already in use. Skipping Prometheus exporter start.")
                    self.enable_prometheus = False
                else:
                    print(f"[Prometheus] Starting metrics server on port {self.prometheus_port}")
                    start_prometheus_exporter(self.prometheus_port)
            for i in range(self.threads):
                port = self.base_port + i
                core = self.cpu_cores[i % len(self.cpu_cores)]
                self.launch_persistent_server_thread(core, port, binary)

            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\n[!] Interrupted. Dumping logs...")
                self.log_results("server", f"{self.base_port}_{self.threads}")

    def log_results(self, role, id_val):
        if not self.log_csv and not self.log_json:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.latency != "bw":
            # Latency fields
            fieldnames = [
                "thread_id", "gid", "payload_size", "iterations",
                "t_min_usec", "t_max_usec", "t_typical_usec",
                "t_avg_usec", "t_stdev_usec", "t_99_percentile_usec",
                "t_999_percentile_usec"
            ]
        else:
            # Bandwidth fields
            fieldnames = [
                "thread_id", "gid", "bw_avg_gbps", "msg_rate_mpps", "connections"
            ]

        if self.log_csv:
            csv_file = f"logs/{role}_{id_val}_{ts}.csv"
            with open(csv_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in self.results.values():
                    row_out = row.copy()

                    if self.latency != "bw":
                        # Clean up: if connections accidentally exist, delete
                        if "connections" in row_out:
                            del row_out["connections"]
                    else:
                        # If bandwidth mode, convert connections list to string
                        if "connections" in row_out and isinstance(row_out["connections"], list):
                            row_out["connections"] = json.dumps(row_out["connections"])

                    writer.writerow(row_out)

        if self.log_json:
            json_file = f"logs/{role}_{id_val}_{ts}.json"
            with open(json_file, "w") as f:
                json.dump(list(self.results.values()), f, indent=2)
