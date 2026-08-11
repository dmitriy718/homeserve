import csv
import io
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QUERY = "index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def metrics() -> tuple[str, bool]:
    lines = [
        "# HELP nvidia_gpu_up Whether nvidia-smi returned GPU data.",
        "# TYPE nvidia_gpu_up gauge",
    ]
    healthy = False
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        rows = list(csv.reader(io.StringIO(result.stdout)))
        healthy = bool(rows)
        lines.append(f"nvidia_gpu_up {1 if healthy else 0}")
        definitions = [
            ("nvidia_gpu_utilization_percent", "GPU utilization percentage.", 2, 1.0),
            ("nvidia_gpu_memory_used_bytes", "GPU memory used in bytes.", 3, 1024 * 1024),
            ("nvidia_gpu_memory_total_bytes", "Total GPU memory in bytes.", 4, 1024 * 1024),
            ("nvidia_gpu_temperature_celsius", "GPU temperature in Celsius.", 5, 1.0),
            ("nvidia_gpu_power_watts", "GPU power draw in watts.", 6, 1.0),
        ]
        for metric, help_text, _, _ in definitions:
            lines.extend([f"# HELP {metric} {help_text}", f"# TYPE {metric} gauge"])
        for row in rows:
            if len(row) != 7:
                continue
            labels = f'gpu="{escape_label(row[0].strip())}",name="{escape_label(row[1].strip())}"'
            for metric, _, index, multiplier in definitions:
                try:
                    value = float(row[index].strip()) * multiplier
                    lines.append(f"{metric}{{{labels}}} {value}")
                except ValueError:
                    continue
    except Exception:
        lines.append("nvidia_gpu_up 0")
    return "\n".join(lines) + "\n", healthy


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/metrics", "/health"):
            self.send_error(404)
            return
        body_text, healthy = metrics()
        body = body_text.encode()
        self.send_response(200 if self.path != "/health" or healthy else 503)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9400), Handler).serve_forever()
