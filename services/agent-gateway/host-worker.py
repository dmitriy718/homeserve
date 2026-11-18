import json
import shlex
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"status": "ok"})
        else:
            self.respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/exec":
            return self.respond(404, {"error": "not found"})
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            command = request["command"]
            cwd = request.get("cwd", "/home/dima")
            timeout = int(request.get("timeout_seconds", 120))
            if not isinstance(command, str) or not isinstance(cwd, str) or not 1 <= timeout <= 14400:
                return self.respond(400, {"error": "invalid request"})
            script = f"cd -- {shlex.quote(cwd)} && exec /bin/bash -lc {shlex.quote(command)}"
            result = subprocess.run(
                ["chroot", "/host", "/usr/bin/nsenter", "--net=/proc/1/ns/net", "/bin/bash", "-lc", script],
                capture_output=True, text=True, timeout=timeout,
            )
            self.respond(200, {"exit_code": result.returncode, "stdout": result.stdout[-20000:], "stderr": result.stderr[-20000:]})
        except subprocess.TimeoutExpired:
            self.respond(408, {"error": "command timed out"})
        except Exception as error:
            self.respond(400, {"error": f"{type(error).__name__}: {error}"})


ThreadingHTTPServer(("0.0.0.0", 8092), Handler).serve_forever()
