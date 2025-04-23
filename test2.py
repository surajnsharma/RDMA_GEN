import os,re
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
        self.results = {}

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

    def build_common_args(self, binary=None):
        args = []
        if self.use_report_gbits:
            args.append("--report_gbits")
        if self.report_per_second and binary == "ib_write_bw" and self.supports_report_per_second:
            args.append("--report_per_second")
        return " ".join(args)



    def parse_ib_output(self, output, is_server=False):
        lines = output.strip().splitlines()
        result = {}
        conn_info = []
        parsed_conns = []

        for line in lines:
            if "GID:" in line or "remote address" in line:
                conn_info.append(line.strip())

            if "remote address" in line:
                parts = line.strip().split()
                try:
                    qpn = parts[5]
                    psn = parts[7]
                    rkey = parts[9]
                    vaddr = parts[11]
                    parsed_conns.append({
                        "qpn": qpn,
                        "psn": psn,
                        "rkey": rkey,
                        "vaddr": vaddr
                    })
                except (IndexError, ValueError):
                    continue

        if conn_info:
            result["conn_info"] = conn_info
        if parsed_conns:
            result["parsed_connections"] = parsed_conns

        # Handle performance result (client only)
        if not is_server:
            for line in lines:
                if re.match(r"^\s*\d+\s+\d+\s+[\d.]+\s+[\d.]+", line):
                    try:
                        parts = line.strip().split()
                        result.update({
                            "bytes": int(parts[0]),
                            "iterations": int(parts[1]),
                            "bw_avg_gbps": float(parts[3]),
                            "msg_rate_mpps": float(parts[4])
                        })
                        return result
                    except (IndexError, ValueError):
                        continue

        return result

    def run_thread(self, cmd, thread_id, meta_file=None):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
        stdout, stderr = proc.communicate()

        is_server = self.role == "server" and not self.persistent_server
        result = self.parse_ib_output(stdout, is_server=is_server)

        result["thread_id"] = thread_id
        result["stderr"] = stderr.strip()

        # Save to metadata file if provided
        if meta_file:
            with open(meta_file, "w") as f:
                f.write(stdout + "\n" + stderr)

        # Store result safely (dict-based)
        if isinstance(self.results, dict):
            self.results[thread_id] = result

        port = str(self.base_port + thread_id)

        # Metrics: bandwidth and msg_rate
        if "bw_avg_gbps" in result:
            self.port_bw_gbps.labels(port=port).set(result["bw_avg_gbps"])
        if "msg_rate_mpps" in result:
            self.port_msg_rate_mpps.labels(port=port).set(result["msg_rate_mpps"])

        # Metrics: connection metadata
        if "parsed_connections" in result:
            for conn in result["parsed_connections"]:
                try:
                    self.port_rkey.labels(port=port).set(int(conn["rkey"], 16))
                    self.port_vaddr.labels(port=port).set(int(conn["vaddr"], 16))
                except Exception:
                    pass

        # Console output
        if "bw_avg_gbps" in result:
            print(
                f"[Thread {thread_id}] BW_avg = {result['bw_avg_gbps']} Gbps, MsgRate = {result.get('msg_rate_mpps', '')} Mpps")
        elif "parsed_connections" in result:
            print(f"[Thread {thread_id}] No performance results. Connection info:")
            for conn in result["parsed_connections"]:
                print(
                    f"[Thread {thread_id}] QPN: {conn['qpn']}, PSN: {conn['psn']}, RKey: {conn['rkey']}, VAddr: {conn['vaddr']}")
        elif "conn_info" in result:
            for line in result["conn_info"]:
                print(f"[Thread {thread_id}] {line}")
        else:
            print(f"[Thread {thread_id}] Failed to parse output")
            print("---- Raw stderr ----")
            print(stderr.strip())

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
            self.results = {}
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
                start_prometheus_exporter(self.prometheus_port)
                print("[Prometheus] Metrics HTTP server started")
                threading.Thread(target=self.monitor_bw_output, daemon=True).start()
            for i in range(self.threads):
                port = self.base_port + i
                core = self.cpu_cores[i % len(self.cpu_cores)]
                self.launch_persistent_server_thread(core, port, binary)
                time.sleep(1.0)
            threading.Event().wait()

    def log_results(self, role, id_val):
        if not self.log_csv and not self.log_json:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = f"logs/{role}_{id_val}_{ts}.csv"
        json_file = f"logs/{role}_{id_val}_{ts}.json"

        fieldnames = [
            "thread_id", "bytes", "iterations", "bw_avg_gbps",
            "msg_rate_mpps", "parsed_connections", "stderr", "status"
        ]

        if self.log_csv:
            with open(csv_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for thread_id, row in self.results.items():
                    status = "success" if "bw_avg_gbps" in row else "no_bw"
                    flat_row = {
                        "thread_id": thread_id,
                        "bytes": row.get("bytes", ""),
                        "iterations": row.get("iterations", ""),
                        "bw_avg_gbps": row.get("bw_avg_gbps", ""),
                        "msg_rate_mpps": row.get("msg_rate_mpps", ""),
                        "parsed_connections": json.dumps(row.get("parsed_connections", "")),
                        "stderr": row.get("stderr", ""),
                        "status": status
                    }
                    writer.writerow(flat_row)

        if self.log_json:
            # Add status to JSON entries too
            output = []
            for thread_id, row in self.results.items():
                row_copy = dict(row)
                row_copy["thread_id"] = thread_id
                if "bw_avg_gbps" in row:
                    row_copy["status"] = "success"
                else:
                    row_copy["status"] = "no_bw"
                output.append(row_copy)

            with open(json_file, "w") as f:
                json.dump(output, f, indent=2)

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
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.monitor_bw_output(port, proc.stdout)
                proc.wait()
                time.sleep(1)

        print(f"[Persistent Thread] Starting monitor thread for port {port}")
        t = threading.Thread(target=loop_runner, daemon=True)
        t.start()

        self.port_binary.labels(port=str(port), binary=binary).set(1)
        self.port_core.labels(port=str(port), core=str(core)).set(1)
        self.port_respawns.labels(port=str(port)).inc()

    def monitor_bw_output(self, port, stream):
        for line in stream:
            line = line.strip()
            # Skip non-data lines (like headers)
            if line.startswith("#") or "BW average" in line or "MsgRate" in line:
                continue

            try:
                parts = line.split()
                if len(parts) < 5:
                    continue
                bw_gbps = float(parts[3])
                mpps = float(parts[4])
                self.port_bw_gbps.labels(port=str(port)).set(bw_gbps)
                self.port_msg_rate_mpps.labels(port=str(port)).set(mpps)
                print(f"[Metrics] Port {port} BW: {bw_gbps} Gbps, MsgRate: {mpps} Mpps")
            except Exception as e:
                print(f"[WARN] Failed to parse line: {line} - {e}")
