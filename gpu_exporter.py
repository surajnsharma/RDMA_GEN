# gpu_exporter.py
from prometheus_client import Gauge, start_http_server
import pynvml
import threading
import time

# Define Prometheus metrics
gpu_mem_total = Gauge('gpu_memory_total_bytes', 'Total GPU memory in bytes', ['gpu_index', 'gpu_name'])
gpu_mem_used = Gauge('gpu_memory_used_bytes', 'Used GPU memory in bytes', ['gpu_index', 'gpu_name'])
gpu_utilization = Gauge('gpu_utilization_percent', 'GPU utilization percentage', ['gpu_index', 'gpu_name'])
gpu_temp_celsius = Gauge('gpu_temperature_celsius', 'GPU temperature in Celsius', ['gpu_index', 'gpu_name'])

def start_gpu_monitor(interval=5):
    pynvml.nvmlInit()
    device_count = pynvml.nvmlDeviceGetCount()

    def monitor():
        while True:
            for i in range(device_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    try:
                        name = pynvml.nvmlDeviceGetName(handle)
                        print(f"[GPU Exporter] GPU {i}: {name}")
                    except Exception as e:
                        print(f"[GPU Exporter] Failed to get GPU name: {e}")
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

                    gpu_mem_total.labels(gpu_index=str(i), gpu_name=name).set(mem_info.total)
                    gpu_mem_used.labels(gpu_index=str(i), gpu_name=name).set(mem_info.used)
                    gpu_utilization.labels(gpu_index=str(i), gpu_name=name).set(util.gpu)
                    gpu_temp_celsius.labels(gpu_index=str(i), gpu_name=name).set(temp)

                except pynvml.NVMLError as e:
                    print(f"[GPU Exporter] Failed to query GPU {i}: {str(e)}")

            time.sleep(interval)

    t = threading.Thread(target=monitor, daemon=True)
    t.start()

def start_gpu_exporter(port=9100):
    """Start Prometheus GPU metrics server (default port 9200)."""
    start_http_server(port)
    print(f"[GPU Exporter] Prometheus GPU metrics available at http://localhost:{port}/metrics")
    start_gpu_monitor()
