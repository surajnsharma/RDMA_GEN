# prometheus_exporter.py
from prometheus_client import start_http_server, Gauge
import threading

def start_prometheus_exporter(port=9100):
    def _run():
        from prometheus_client import REGISTRY
        start_http_server(port)
        print(f"[Prometheus Exporter] Started at http://0.0.0.0:{port}/metrics")
        threading.Event().wait()  # Keeps it alive

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
