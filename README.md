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
```

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

---
