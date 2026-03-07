"""Mock robot server that mimics the Pico 2 W HTTP API for testing."""

import json
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

DEVICE_NAME = "MockPico2W"
DEVICE_ID = "mock-pico-001"
PAIRED_CLIENTS = {}
JOBS = {}


class MockRobotHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def do_GET(self):
        if self.path == "/hello":
            self._send_json({
                "device_name": DEVICE_NAME,
                "device_id": DEVICE_ID,
                "firmware": "mock-1.0",
            })
        elif self.path == "/status":
            self._send_json({
                "device_name": DEVICE_NAME,
                "device_id": DEVICE_ID,
                "status": "idle",
                "paired_clients": len(PAIRED_CLIENTS),
            })
        elif self.path.startswith("/job"):
            job_id = self.path.split("?id=")[-1] if "?id=" in self.path else None
            if job_id and job_id in JOBS:
                self._send_json(JOBS[job_id])
            else:
                self._send_json({"error": "Job not found"}, 404)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path == "/pair":
            body = self._read_body()
            client_name = body.get("client_name", "unknown")
            pairing_code = body.get("pairing_code", "")
            # Accept any pairing code for mock
            token = str(uuid.uuid4())
            PAIRED_CLIENTS[token] = client_name
            self._send_json({
                "device_name": DEVICE_NAME,
                "device_id": DEVICE_ID,
                "pair_token": token,
            })
        elif self.path == "/unpair":
            body = self._read_body()
            token = body.get("token", "")
            PAIRED_CLIENTS.pop(token, None)
            self._send_json({"status": "unpaired"})
        elif self.path == "/render":
            body = self._read_body()
            job_id = str(uuid.uuid4())[:8]
            operations = body.get("operations", [])
            JOBS[job_id] = {
                "job_id": job_id,
                "status": "accepted",
                "mode": body.get("mode", "write"),
                "operation_count": len(operations),
            }
            print(f"[MOCK] Accepted job {job_id}: {len(operations)} operations")
            self._send_json({"job_id": job_id, "status": "accepted"})
        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        print(f"[MOCK] {format % args}")


def main():
    port = 8080
    server = HTTPServer(("0.0.0.0", port), MockRobotHandler)
    print(f"[MOCK] Robot server running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
