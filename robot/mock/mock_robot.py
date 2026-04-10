"""Mock Pico HTTP API for exercising the speech app without hardware."""

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

DEVICE_NAME = "MockPico2W"
DEVICE_ID = "mock-pico-001"
LISTEN_PORT = 8080

# Match the firmware defaults from pins.py.
WORK_AREA_X_MM = 247.0
WORK_AREA_Y_MM = 205.0
STEPS_PER_MM = 40

# Shared motion state in the same shape returned by the real firmware.
MOTION_LOCK = threading.Lock()
MOTION = {
    "status": "idle",
    "kind": None,
    "job_id": None,
    "op_index": 0,
    "total_ops": 0,
    "progress_pct": 0.0,
    "position_mm": [0.0, 0.0],
    "homed": False,
    "pen": "up",
    "error": None,
    "result": None,
}
ABORT_REQUESTED = False
PAIRED_CLIENTS = {}


def _set_motion(**fields):
    with MOTION_LOCK:
        MOTION.update(fields)


def _snapshot():
    with MOTION_LOCK:
        return dict(MOTION)


def _run_fake_job(kind, payload):
    """Simulate a motion job in the background."""
    global ABORT_REQUESTED

    if kind == "home":
        time.sleep(0.4)
        _set_motion(position_mm=[0.0, 0.0], homed=True, status="complete")
        return

    if kind == "calibrate":
        time.sleep(1.0)
        result = {
            "travel_x_steps": int(WORK_AREA_X_MM * STEPS_PER_MM),
            "travel_y_steps": int(WORK_AREA_Y_MM * STEPS_PER_MM),
            "travel_x_mm": WORK_AREA_X_MM,
            "travel_y_mm": WORK_AREA_Y_MM,
            "steps_per_mm": STEPS_PER_MM,
        }
        _set_motion(status="complete", result=result, position_mm=[0.0, 0.0], homed=True)
        return

    if kind == "jog":
        snap = _snapshot()
        x, y = snap["position_mm"]
        x += payload.get("dx", 0)
        y += payload.get("dy", 0)
        time.sleep(0.3)
        _set_motion(position_mm=[x, y], status="complete")
        return

    if kind == "move":
        time.sleep(0.4)
        _set_motion(position_mm=[payload.get("x", 0), payload.get("y", 0)], status="complete")
        return

    if kind == "render":
        operations = payload.get("operations", [])
        total = len(operations)
        for i, op in enumerate(operations):
            if ABORT_REQUESTED:
                _set_motion(status="aborted")
                ABORT_REQUESTED = False
                return
            pts = op.get("points") or []
            if op.get("type") == "punch":
                pt = op.get("point")
                if pt is not None:
                    pts = [pt]
            new_pos = MOTION["position_mm"]
            if pts:
                last = pts[-1]
                new_pos = [float(last[0]), float(last[1])]
            _set_motion(
                op_index=i,
                position_mm=new_pos,
                progress_pct=round(100.0 * i / total, 1) if total else 0.0,
            )
            time.sleep(0.05)  # 50ms per op — visible but not slow
        _set_motion(op_index=total, progress_pct=100.0, status="complete")
        return

    _set_motion(status="failed", error="unknown kind: " + str(kind))


def _queue_job(kind, payload):
    global ABORT_REQUESTED
    with MOTION_LOCK:
        if MOTION["status"] == "running":
            return None, "robot is busy"
        ABORT_REQUESTED = False
        job_id = "{}-{}".format(kind, uuid.uuid4().hex[:6])
        MOTION.update({
            "status": "running",
            "kind": kind,
            "job_id": job_id,
            "op_index": 0,
            "total_ops": len(payload.get("operations", [])) if kind == "render" else 0,
            "progress_pct": 0.0,
            "error": None,
            "result": None,
        })
    threading.Thread(target=_run_fake_job, args=(kind, payload), daemon=True).start()
    return job_id, None


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
        path = self.path.split("?")[0]

        if path == "/hello":
            self._send_json({
                "device_name": DEVICE_NAME,
                "device_id": DEVICE_ID,
                "ip_address": "127.0.0.1",
                "listen_port": LISTEN_PORT,
                "paired": bool(PAIRED_CLIENTS),
                "work_area_mm": [WORK_AREA_X_MM, WORK_AREA_Y_MM],
                "steps_per_mm": STEPS_PER_MM,
            })
        elif path == "/status":
            self._send_json({
                "device_name": DEVICE_NAME,
                "device_id": DEVICE_ID,
                "paired_client": next(iter(PAIRED_CLIENTS.values()), None),
                "motion": _snapshot(),
                "work_area_mm": [WORK_AREA_X_MM, WORK_AREA_Y_MM],
            })
        elif path == "/job":
            self._send_json(_snapshot())
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        global ABORT_REQUESTED
        path = self.path.split("?")[0]
        body = self._read_body()

        if path == "/pair":
            client_name = body.get("client_name", "unknown")
            token = str(uuid.uuid4())
            PAIRED_CLIENTS[token] = client_name
            self._send_json({
                "device_name": DEVICE_NAME,
                "device_id": DEVICE_ID,
                "pair_token": token,
            })
        elif path == "/unpair":
            PAIRED_CLIENTS.clear()
            self._send_json({"ok": True})
        elif path == "/home":
            job_id, err = _queue_job("home", {})
            if err:
                self._send_json({"error": err}, 409)
            else:
                self._send_json({"accepted": True, "job_id": job_id, "kind": "home"}, 202)
        elif path == "/calibrate":
            job_id, err = _queue_job("calibrate", {})
            if err:
                self._send_json({"error": err}, 409)
            else:
                self._send_json({"accepted": True, "job_id": job_id, "kind": "calibrate"}, 202)
        elif path == "/jog":
            job_id, err = _queue_job("jog", body)
            if err:
                self._send_json({"error": err}, 409)
            else:
                self._send_json({"accepted": True, "job_id": job_id, "kind": "jog"}, 202)
        elif path == "/move":
            job_id, err = _queue_job("move", body)
            if err:
                self._send_json({"error": err}, 409)
            else:
                self._send_json({"accepted": True, "job_id": job_id, "kind": "move"}, 202)
        elif path == "/render":
            operations = body.get("operations", [])
            job_id, err = _queue_job("render", {"operations": operations})
            if err:
                self._send_json({"error": err}, 409)
            else:
                print(f"[MOCK] Accepted render job {job_id}: {len(operations)} operations")
                self._send_json({
                    "accepted": True,
                    "job_id": job_id,
                    "kind": "render",
                    "operation_count": len(operations),
                }, 202)
        elif path == "/job/abort":
            ABORT_REQUESTED = True
            self._send_json({"aborted": True})
        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        print(f"[MOCK] {format % args}")


def main():
    server = HTTPServer(("0.0.0.0", LISTEN_PORT), MockRobotHandler)
    print(f"[MOCK] Robot server running on port {LISTEN_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
