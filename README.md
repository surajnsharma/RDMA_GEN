# RDMA Performance Benchmarking Tool

This is a flexible and NUMA-aware RDMA benchmarking framework using `ib_write_bw`, `ib_read_bw`, and `ib_send_bw` tools. It supports multi-threaded testing across CPUs and ports with CSV/JSON logging and Prometheus monitoring.

---

## Requirements

- Python 3.6+
- RDMA stack installed (e.g., `rdma-core`, `perftest`)
- Root privileges to access debugfs and bind interfaces
- NVIDIA/Mellanox NIC with RoCEv2 support (e.g., ConnectX-6/7)

---

## 🧰 Components

- `run_rdma_test.py`: CLI runner for client and server RDMA benchmarking
- `rdma_perf_tool.py`: Core RDMA orchestration logic
- CSV/JSON logging
- Prometheus metric exports (optional)
- Auto NUMA-aware CPU pinning
- Persistent server mode for multi-client testing
- Auto-port allocation via client IDs

---

## Install

### Install Prometheus

```bash
sudo apt update
sudo apt install prometheus -y
```

#### Configure Prometheus to Scrape RDMA Exporter

Edit `/etc/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'rdma_perf_server'
    static_configs:
      - targets: ['<server-ip>:9100']
```

```bash
sudo systemctl restart prometheus
curl http://localhost:9100/metrics
```
## Install Grafana on Ubuntu
Install prerequisites:
sudo apt install -y software-properties-common gnupg2 curl

Add Grafana GPG key:
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/grafana.gpg

Add the Grafana APT repository:
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list

sudo apt update
sudo apt install -y grafana

sudo systemctl start grafana-server
sudo systemctl enable grafana-server

Access Grafana UI
http://<your-server-ip>:3000
Default login:
    Username: admin
    Password: admin

---

### Install Grafana

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt update
sudo apt install grafana -y
sudo systemctl enable --now grafana-server
```

---

### Add Prometheus as a Grafana Data Source

1. Go to Grafana → ⚙️ Settings → Data Sources
2. Click "Add data source"
3. Choose "Prometheus"
4. Set URL to `http://localhost:9090`
5. Save & test

---

### Import RDMA Grafana Dashboard

Go to 🧩 Dashboards → Import → Paste the JSON below or use downloadable version.

#### 📄 Example Panel JSON Snippet

```json
{
  "title": "RDMA Benchmark Overview",
  "panels": [
    { "type": "graph", "title": "TX Bandwidth (Gbps)", "targets": [{"expr": "rdma_tx_bytes"}] },
    { "type": "graph", "title": "RX Bandwidth (Gbps)", "targets": [{"expr": "rdma_rx_bytes"}] },
    { "type": "graph", "title": "TX PPS", "targets": [{"expr": "rdma_tx_pps"}] },
    { "type": "graph", "title": "RX PPS", "targets": [{"expr": "rdma_rx_pps"}] },
    { "type": "stat", "title": "Active Threads", "targets": [{"expr": "rdma_active_threads"}] }
  ]
}
```

---

### Metrics Available

| Metric Name         | Description                          |
|---------------------|--------------------------------------|
| `rdma_tx_bytes`     | Total bytes transmitted              |
| `rdma_rx_bytes`     | Total bytes received                 |
| `rdma_tx_pps`       | Transmit packets per second          |
| `rdma_rx_pps`       | Receive packets per second           |
| `rdma_active_threads`| Number of active RDMA threads       |

---

## 🚀 Usage

### 🔹 Server Mode

```bash
python3 run_rdma_test.py \
  --role server \
  --device rocep160s0 \
  --size 4096 \
  --qdepth 1024 \
  --multi-port-server \
  --threads 16 \
  --base-port 18515 \
  --log-csv \
  --log-json \
  --test-type write
```
## To enable server-side logging:
    Option A: Only feasible if you run the server in non-persistent mode and use subprocess.Popen(...).\
            communicate() to capture output like the client.\
    Option B: If you're running persistent background listeners (e.g., while true; do ib_write_bw ...),\ 
            you’ll need to redirect stdout/stderr to per-port log files and optionally post-process them later.

### 🔹 Client Mode

```bash
python3 run_rdma_test.py \
  --role client \
  --device rocep160s0 \
  --server-ip 10.200.10.13 \
  --size 4096 \
  --qdepth 1024 \
  --duration 60 \
  --link-speed 400 \
  --per-thread-gbps 50 \
  --base-port 18515 \
  --client-id 0 \
  --test-type write \
  --log-csv
```

### 🔹 Enable Prometheus

```bash
python3 run_rdma_test.py \
  --role server \
  --device rocep160s0 \
  --size 4096 \
  --qdepth 1024 \
  --threads 16 \
  --multi-port-server \
  --base-port 18515 \
  --log-csv \
  --log-json \
  --test-type write \
  --enable-prometheus \
  --prometheus-port 9100
```

Threads | Safe qdepth
8 | ≥512
16 | ≥256
32 | ≥128
For Reads | Prefer ≥1024 in general

---
``` 
## Server options available using --multi-port-server.
## remove --multi-port-server, if not using multi-port-server. this will allow user generate bandwidht used per thread.
   - however , port will disconnect when clinet finish sending QP data. 
###write###
python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type write --base-port 18550
###read###
#python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type read --base-port 18560
###send###
#python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type send --base-port 18570


## client options available 
###write###
python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type write --base-port 18550 --client-id 0
###read###
#python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type read --base-port 18560 --client-id 0
###send###
#python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type send --base-port 18570 --client-id 0
---
```

## Command-Line Options

| Option                | Description                                                                                                       |
|-----------------------|-------------------------------------------------------------------------------------------------------------------|
| `--role`              | `server` or `client`                                                                                              |
| `--device`            | RDMA device name (e.g., rocep160s0); auto-detected if omitted                                                     |
| `--server-ip`         | IP address of the server (required in client mode)                                                                |
| `--qdepth`            | Queue depth per thread (default: 1024)                                                                            |
| `--size`              | RDMA message size in bytes (default: 65536)                                                                       |
| `--duration`          | Duration of test in seconds (default: 60)                                                                         |
| `--link-speed`        | Target total link speed in Gbps (default: 400)                                                                    |
| `--per-thread-gbps`   | Expected bandwidth per thread (default: 50.0)                                                                     |
| `--log-csv`           | Enable logging thread commands to `rdma_perf_log.csv`                                                             |
| `--log-json`          | Enable logging thread commands to `rdma_perf_log.json`                                                            |
| `--monitor-cnp`       | Enables live CNP/DCQCN stats using ethtool or debugfs                                                             |
| `--multi-port-server` | Enables persistent server that listens on many ports and restart port when client disconnect for multiple clients |
| `--enable-prometheus` | Enables Prometheus metrics exporter (server mode only)                                                            |
| `--prometheus-port`   | Port to expose Prometheus metrics (default: 9100)                                                                 |
| `--kill`              | This will kill the existing/stale ib process running and start all new                                            |
---


## 🧪 Multi-Test-Type & Multi-Client Example

### Start Servers (one per test-type)

```bash
# write
python3 run_rdma_test.py --role server --base-port 18500 --test-type write ...

# read
python3 run_rdma_test.py --role server --base-port 18550 --test-type read ...

# send
python3 run_rdma_test.py --role server --base-port 18600 --test-type send ...
```

### Run Clients

```bash
# write
python3 run_rdma_test.py --role client --base-port 18500 --client-id 0 --test-type write ...

# read
python3 run_rdma_test.py --role client --base-port 18550 --client-id 1 --test-type read ...

# send
python3 run_rdma_test.py --role client --base-port 18600 --client-id 2 --test-type send ...
```

---

## 🛠 Troubleshooting

- Check RDMA tools with `ib_write_bw --version`
- Override thread count using `--threads`
- Use unique `--base-port` per test type or client

---

## 🔥 Kill Stale RDMA Processes

root@svl-d-ai-srv04:~/RDMA# netstat -ntlp | grep  ib_
tcp        0      0 0.0.0.0:18561           0.0.0.0:*               LISTEN      3399007/ib_write_bw 
tcp        0      0 0.0.0.0:18560           0.0.0.0:*               LISTEN      3399005/ib_write_bw 
tcp        0      0 0.0.0.0:18563           0.0.0.0:*               LISTEN      3399009/ib_write_bw 

# Check all opened ib tcp socket
ps -ef | grep ib_.*_bw


```bash
sudo pkill -f ib_write_bw
sudo pkill -f ib_read_bw
sudo pkill -f ib_send_bw
#kill all 
pkill -f -e 'ib_.*_bw'

```

---

## 📁 Output Logs

- `rdma_client_summary_<timestamp>.csv/json`
- `rdma_server_summary_<timestamp>.csv/json`

## client logs
``` 
root@svl-d-ai-srv03:~/RDMA# python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --threads 8 --log-csv --log-json --test-type write --base-port 18550 --client-id 0 --duration 5
Auto-calculated thread count: 8 for target 400 Gbps
Role: client  Device: rocep160s0  Threads: 8  Duration: 5s
[Thread 0] Launching: taskset -c 0 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18550 10.200.10.13
[Thread 1] Launching: taskset -c 1 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18551 10.200.10.13
[Thread 2] Launching: taskset -c 2 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18552 10.200.10.13
[Thread 3] Launching: taskset -c 3 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18553 10.200.10.13
[Thread 4] Launching: taskset -c 4 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18554 10.200.10.13
[Thread 5] Launching: taskset -c 5 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18555 10.200.10.13
[Thread 6] Launching: taskset -c 6 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18556 10.200.10.13
[Thread 7] Launching: taskset -c 7 ib_write_bw -d rocep160s0 -i 1 -F -s 4096 -q 1024 --report_gbits --duration 5 --port 18557 10.200.10.13
[Thread 0] BW_avg = 57.49 Gbps, MsgRate = 1.754549 Mpps
[Thread 1] BW_avg = 54.26 Gbps, MsgRate = 1.65596 Mpps
[Thread 2] BW_avg = 52.12 Gbps, MsgRate = 1.590594 Mpps
[Thread 3] BW_avg = 49.19 Gbps, MsgRate = 1.501197 Mpps
[Thread 4] BW_avg = 49.27 Gbps, MsgRate = 1.503731 Mpps
[Thread 5] BW_avg = 49.89 Gbps, MsgRate = 1.522464 Mpps
[Thread 6] BW_avg = 53.69 Gbps, MsgRate = 1.638362 Mpps
[Thread 7] BW_avg = 62.95 Gbps, MsgRate = 1.921188 Mpps
root@svl-d-ai-srv03:~/RDMA# ls logs/
client_0_20250422_032446.csv  client_0_20250422_032446.json
root@svl-d-ai-srv03:~/RDMA# cat logs/client_0_20250422_032446.csv
thread_id,bytes,iterations,bw_avg_gbps,msg_rate_mpps
0,4096,5263700,57.49,1.754549
1,4096,4968000,54.26,1.65596
2,4096,4771900,52.12,1.590594
3,4096,4503700,49.19,1.501197
4,4096,4511300,49.27,1.503731
5,4096,4567500,49.89,1.522464
6,4096,4915200,53.69,1.638362
7,4096,5763700,62.95,1.921188
root@svl-d-ai-srv03:~/RDMA# cat logs/client_0_20250422_032446.json
[
  {
    "bytes": 4096,
    "iterations": 5263700,
    "bw_avg_gbps": 57.49,
    "msg_rate_mpps": 1.754549,
    "thread_id": 0
  },
  {
    "bytes": 4096,
    "iterations": 4968000,
    "bw_avg_gbps": 54.26,
    "msg_rate_mpps": 1.65596,
    "thread_id": 1
  },
  {
    "bytes": 4096,
    "iterations": 4771900,
    "bw_avg_gbps": 52.12,
    "msg_rate_mpps": 1.590594,
    "thread_id": 2
  },
  {
    "bytes": 4096,
    "iterations": 4503700,
    "bw_avg_gbps": 49.19,
    "msg_rate_mpps": 1.501197,
    "thread_id": 3
  },
  {
    "bytes": 4096,
    "iterations": 4511300,
    "bw_avg_gbps": 49.27,
    "msg_rate_mpps": 1.503731,
    "thread_id": 4
  },
  {
    "bytes": 4096,
    "iterations": 4567500,
    "bw_avg_gbps": 49.89,
    "msg_rate_mpps": 1.522464,
    "thread_id": 5
  },
  {
    "bytes": 4096,
    "iterations": 4915200,
    "bw_avg_gbps": 53.69,
    "msg_rate_mpps": 1.638362,
    "thread_id": 6
  },
  {
    "bytes": 4096,
    "iterations": 5763700,
    "bw_avg_gbps": 62.95,
    "msg_rate_mpps": 1.921188,
    "thread_id": 7
  }

```

## checking logs on Server. 
``` 
Server logs are saved only if server is running in non persistant mode . do not use --multi-port-server
root@svl-d-ai-srv04:~/RDMA# python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024  --threads 8 --log-csv --log-json --test-type write --base-port 18550 
root@svl-d-ai-srv04:~/RDMA# ls logs/
server_18550_8_20250422_032211.csv   server_meta_18550.txt  server_meta_18552.txt  server_meta_18554.txt  server_meta_18556.txt
server_18550_8_20250422_032211.json  server_meta_18551.txt  server_meta_18553.txt  server_meta_18555.txt  server_meta_18557.txt

```


---
