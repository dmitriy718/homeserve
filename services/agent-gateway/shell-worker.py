import json
import os
import signal
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path("/srv/agent-workspaces").resolve()
MAX_COMMAND_CHARS = 20_000


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/exec":
            self.send_error(404)
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            command = request["command"]
            project = request["project"]
            timeout = int(request["timeout_seconds"])
            cwd = (ROOT / project).resolve()
            if not isinstance(command, str) or len(command) > MAX_COMMAND_CHARS:
                raise ValueError("invalid command")
            if not isinstance(project, str) or (cwd != ROOT and ROOT not in cwd.parents):
                raise ValueError("invalid project")
            if not 1 <= timeout <= 14400:
                raise ValueError("invalid timeout")
            cwd.mkdir(parents=True, exist_ok=True)
            started = time.time()
            environment = {
                "PATH": os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": "/srv/agent-cache",
                "TMPDIR": "/tmp",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "AGENT_PROJECT": project,
            }
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(
                    ["bash", "-lc", command], cwd=cwd, stdout=stdout, stderr=stderr,
                    env=environment, start_new_session=True, umask=0o002,
                )
                timed_out = False
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                result = {
                    "project": project,
                    "command": command,
                    "exit_code": 124 if timed_out else process.returncode,
                    "stdout": tail(stdout),
                    "stderr": tail(stderr),
                    "duration_seconds": round(time.time() - started, 3),
                }
                if timed_out:
                    result["timed_out"] = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(400, "invalid shell request")

    def log_message(self, format, *args):
        return


def tail(file, limit=20000):
    file.seek(0, os.SEEK_END)
    file.seek(max(0, file.tell() - limit))
    return file.read().decode("utf-8", errors="replace")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
