"""CoreXY motion controller for the AE1 robot.

Responsibilities:
  - Homing to top-left corner via X_MIN and Y_MIN switches.
  - Logical (x, y) mm motion via CoreXY kinematics + Bresenham step interleaving.
  - Soft-limit safety using calibrated work area from pins.py.
  - Cooperative yield callback every N pulses so the HTTP/serial server
    can stay responsive during long jobs.
  - Job state tracking (idle / running / complete / failed / aborted)
    exposed via .get_status() for the /job endpoint to read.
  - Pen abstraction calls (currently no-ops; pen.py is a stub) at the
    correct points so the servo wiring is a one-file change later.

Kinematics — empirically verified during bring-up (2026-04-09):
  Both motors spinning forward (A+ B+) → carriage moves -X (left).
  A+ B-                                → carriage moves -Y (up).
  Inverting and solving:
      sA = -(dx + dy)         # signed motor-A step count
      sB =  dy - dx           # signed motor-B step count
  Where positive sA/sB means forward (DIR pin = 1).
"""

from machine import Pin
import time

import pins
import pen as pen_module


class MotionError(Exception):
    pass


STATUS_IDLE     = "idle"
STATUS_RUNNING  = "running"
STATUS_COMPLETE = "complete"
STATUS_FAILED   = "failed"
STATUS_ABORTED  = "aborted"


class Motion:
    """Owns the steppers, switches, and pen. Single instance per process."""

    def __init__(self, on_yield=None, pen=None):
        # Yield from long moves so the server can keep servicing requests.
        self._on_yield = on_yield
        self._yield_interval = 50

        self._stepA = Pin(pins.STEP_A_PIN, Pin.OUT)
        self._dirA  = Pin(pins.DIR_A_PIN, Pin.OUT)
        self._stepB = Pin(pins.STEP_B_PIN, Pin.OUT)
        self._dirB  = Pin(pins.DIR_B_PIN, Pin.OUT)

        self._sw_x_min = Pin(pins.SW_X_MIN_PIN, Pin.IN, Pin.PULL_UP)
        self._sw_x_max = Pin(pins.SW_X_MAX_PIN, Pin.IN, Pin.PULL_UP)
        self._sw_y_min = Pin(pins.SW_Y_MIN_PIN, Pin.IN, Pin.PULL_UP)
        self._sw_y_max = Pin(pins.SW_Y_MAX_PIN, Pin.IN, Pin.PULL_UP)

        self.pen = pen if pen is not None else pen_module.Pen()

        self.position_steps = [0, 0]
        self.homed = False

        self._job_state = {
            "status":   STATUS_IDLE,
            "job_id":   None,
            "op_index": 0,
            "total_ops": 0,
            "error":    None,
        }
        self._abort_requested = False

    def position_mm(self):
        return [self.position_steps[0] / pins.STEPS_PER_MM,
                self.position_steps[1] / pins.STEPS_PER_MM]

    def get_status(self):
        total = self._job_state["total_ops"]
        op_idx = self._job_state["op_index"]
        progress_pct = round(100.0 * op_idx / total, 1) if total else 0.0
        return {
            "status":       self._job_state["status"],
            "job_id":       self._job_state["job_id"],
            "op_index":     op_idx,
            "total_ops":    total,
            "progress_pct": progress_pct,
            "position_mm":  self.position_mm(),
            "homed":        self.homed,
            "pen":          self.pen.state,
            "error":        self._job_state["error"],
        }

    def request_abort(self):
        """Abort the running job at the next yield point."""
        self._abort_requested = True

    def reset_job_state(self):
        self._job_state["status"]   = STATUS_IDLE
        self._job_state["job_id"]   = None
        self._job_state["op_index"] = 0
        self._job_state["total_ops"] = 0
        self._job_state["error"]    = None
        self._abort_requested = False

    def _yield(self):
        if self._on_yield is not None:
            self._on_yield()

    def _any_switch_pressed(self):
        return (self._sw_y_min.value() == 0 or self._sw_x_min.value() == 0
                or self._sw_y_max.value() == 0 or self._sw_x_max.value() == 0)

    def switch_state(self):
        """Return current switch state for debugging / status output."""
        return {
            "x_min": self._sw_x_min.value() == 0,
            "x_max": self._sw_x_max.value() == 0,
            "y_min": self._sw_y_min.value() == 0,
            "y_max": self._sw_y_max.value() == 0,
        }

    def _move_open_loop(self, dA, dB, steps, half_us=None):
        """Pulse motors without switch checks, yields, or position updates."""
        if half_us is None:
            half_us = pins.DEFAULT_HALF_PERIOD_US
        self._dirA.value(dA)
        self._dirB.value(dB)
        self._stepA.value(0); self._stepB.value(0)
        time.sleep_ms(2)
        for _ in range(steps):
            self._stepA.value(1); self._stepB.value(1)
            time.sleep_us(half_us)
            self._stepA.value(0); self._stepB.value(0)
            time.sleep_us(half_us)

    def _move_until_switch(self, dA, dB, target_switch, max_steps=20000, half_us=None):
        """Drive in (dA, dB) direction until target_switch is pressed."""
        if half_us is None:
            half_us = pins.HOMING_HALF_PERIOD_US
        self._dirA.value(dA); self._dirB.value(dB)
        self._stepA.value(0); self._stepB.value(0)
        time.sleep_ms(2)
        for i in range(max_steps):
            if target_switch.value() == 0:
                return ("hit", i)
            if self._sw_y_min is not target_switch and self._sw_y_min.value() == 0:
                return ("abort:YMIN", i)
            if self._sw_x_min is not target_switch and self._sw_x_min.value() == 0:
                return ("abort:XMIN", i)
            if self._sw_y_max is not target_switch and self._sw_y_max.value() == 0:
                return ("abort:YMAX", i)
            if self._sw_x_max is not target_switch and self._sw_x_max.value() == 0:
                return ("abort:XMAX", i)
            self._stepA.value(1); self._stepB.value(1)
            time.sleep_us(half_us)
            self._stepA.value(0); self._stepB.value(0)
            time.sleep_us(half_us)
            if (i % self._yield_interval) == 0:
                self._yield()
        return ("maxsteps", max_steps)

    def home(self):
        """Drive to top-left, set logical position to (0, 0). Pen lifted first."""
        self._abort_requested = False
        self.pen.up()

        backoff_steps = int(pins.HOME_BACKOFF_MM * pins.STEPS_PER_MM)

        # -Y (up) toward Y_MIN: A+ B-
        result, _ = self._move_until_switch(1, 0, self._sw_y_min)
        if result != "hit":
            self.homed = False
            raise MotionError("Y homing failed: " + result)
        # +Y backoff (A- B+) — raw open loop, ignores the still-pressed switch
        self._move_open_loop(0, 1, backoff_steps)

        # -X (left) toward X_MIN: A+ B+
        result, _ = self._move_until_switch(1, 1, self._sw_x_min)
        if result != "hit":
            self.homed = False
            raise MotionError("X homing failed: " + result)
        # +X backoff (A- B-)
        self._move_open_loop(0, 0, backoff_steps)

        self.position_steps = [0, 0]
        self.homed = True

    def move_by_steps(self, dx_steps, dy_steps, half_us=None):
        """CoreXY + Bresenham move by (dx, dy) microsteps from current position.
        Aborts on any limit switch contact or on a request_abort() call.
        On any abort, marks the position as no longer homed (must re-home).
        On clean completion, updates position_steps and returns the pulse count."""
        if half_us is None:
            half_us = pins.DEFAULT_HALF_PERIOD_US

        # CoreXY forward kinematics (sign convention verified empirically)
        sA = -(dx_steps + dy_steps)
        sB = dy_steps - dx_steps
        if sA == 0 and sB == 0:
            return 0

        self._dirA.value(1 if sA > 0 else 0)
        self._dirB.value(1 if sB > 0 else 0)
        self._stepA.value(0); self._stepB.value(0)
        time.sleep_us(50)

        nA = abs(sA)
        nB = abs(sB)
        n = nA if nA >= nB else nB

        # Bresenham-style interleaving keeps the slower axis evenly distributed.
        errA = n // 2
        errB = n // 2
        yi = self._yield_interval
        yc = yi

        for _ in range(n):
            if self._abort_requested:
                self.homed = False
                raise MotionError("aborted")
            if self._any_switch_pressed():
                self.homed = False
                raise MotionError("limit switch tripped during move")

            errA -= nA
            pulse_a = errA < 0
            if pulse_a:
                errA += n
            errB -= nB
            pulse_b = errB < 0
            if pulse_b:
                errB += n

            if pulse_a: self._stepA.value(1)
            if pulse_b: self._stepB.value(1)
            time.sleep_us(half_us)
            if pulse_a: self._stepA.value(0)
            if pulse_b: self._stepB.value(0)
            time.sleep_us(half_us)

            yc -= 1
            if yc == 0:
                yc = yi
                self._yield()

        self.position_steps[0] += dx_steps
        self.position_steps[1] += dy_steps
        return n

    def move_by_mm(self, dx_mm, dy_mm, half_us=None):
        """Relative mm move. For absolute targets prefer move_to_mm() — it
        avoids cumulative rounding error across many small moves."""
        dx_steps = int(round(dx_mm * pins.STEPS_PER_MM))
        dy_steps = int(round(dy_mm * pins.STEPS_PER_MM))
        return self.move_by_steps(dx_steps, dy_steps, half_us)

    def move_to_mm(self, x_mm, y_mm, half_us=None):
        """Absolute move. Step delta is computed from absolute target so
        repeated small moves don't accumulate rounding error."""
        if not self.homed:
            raise MotionError("Cannot move_to: robot is not homed")
        if not (0 <= x_mm <= pins.WORK_AREA_X_MM):
            raise MotionError("X out of bounds: {} (range 0..{})".format(
                round(x_mm, 2), round(pins.WORK_AREA_X_MM, 2)))
        if not (0 <= y_mm <= pins.WORK_AREA_Y_MM):
            raise MotionError("Y out of bounds: {} (range 0..{})".format(
                round(y_mm, 2), round(pins.WORK_AREA_Y_MM, 2)))

        target_x_steps = int(round(x_mm * pins.STEPS_PER_MM))
        target_y_steps = int(round(y_mm * pins.STEPS_PER_MM))
        dx_steps = target_x_steps - self.position_steps[0]
        dy_steps = target_y_steps - self.position_steps[1]
        return self.move_by_steps(dx_steps, dy_steps, half_us)

    def execute_operations(self, operations, job_id=None, half_us=None):
        """Execute a toolpath produced by speech-app/toolpath.py.

        Each operation is a dict with one of these shapes:
            {"type": "draw",   "points": [[x, y], ...]}   -> pen down trace
            {"type": "travel", "points": [[x, y], ...]}   -> pen up move
            {"type": "punch",  "point":  [x, y]}          -> braille dot

        Coordinates are in absolute machine mm (origin = home = top-left).
        Validates all coordinates against the work area before any motion.
        Raises MotionError on any failure; updates job_state throughout.
        """
        if not self.homed:
            raise MotionError("Cannot execute: robot is not homed")

        # Pre-validate so we don't half-draw and then fault.
        for op in operations:
            for pt in op.get("points", []) or []:
                self._check_bounds(pt[0], pt[1])
            pt = op.get("point")
            if pt is not None:
                self._check_bounds(pt[0], pt[1])

        self._job_state["status"]    = STATUS_RUNNING
        self._job_state["job_id"]    = job_id
        self._job_state["op_index"]  = 0
        self._job_state["total_ops"] = len(operations)
        self._job_state["error"]     = None
        self._abort_requested = False

        try:
            for i, op in enumerate(operations):
                self._job_state["op_index"] = i
                op_type = op.get("type", "draw")

                if op_type == "draw":
                    self._execute_draw(op, half_us)
                elif op_type == "travel":
                    self._execute_travel(op, half_us)
                elif op_type == "punch":
                    self._execute_punch(op, half_us)
                else:
                    pass

            self._job_state["op_index"] = len(operations)
            self._job_state["status"] = STATUS_COMPLETE
        except MotionError as exc:
            if self._abort_requested:
                self._job_state["status"] = STATUS_ABORTED
            else:
                self._job_state["status"] = STATUS_FAILED
                self._job_state["error"] = str(exc)
            # Always lift the pen on failure — physical safety once mounted.
            try:
                self.pen.up()
            except Exception:
                pass
            raise

    def _execute_draw(self, op, half_us):
        pts = op.get("points") or []
        if len(pts) < 2:
            return
        self.pen.up()
        self.move_to_mm(pts[0][0], pts[0][1], half_us)
        self.pen.down()
        for pt in pts[1:]:
            self.move_to_mm(pt[0], pt[1], half_us)

    def _execute_travel(self, op, half_us):
        pts = op.get("points") or []
        if not pts:
            return
        self.pen.up()
        for pt in pts:
            self.move_to_mm(pt[0], pt[1], half_us)

    def _execute_punch(self, op, half_us):
        pt = op.get("point")
        if pt is None:
            return
        self.pen.up()
        self.move_to_mm(pt[0], pt[1], half_us)
        self.pen.punch()

    def _check_bounds(self, x_mm, y_mm):
        if not (0 <= x_mm <= pins.WORK_AREA_X_MM):
            raise MotionError("Op out of X bounds at ({}, {}): max {}".format(
                round(x_mm, 2), round(y_mm, 2), round(pins.WORK_AREA_X_MM, 2)))
        if not (0 <= y_mm <= pins.WORK_AREA_Y_MM):
            raise MotionError("Op out of Y bounds at ({}, {}): max {}".format(
                round(x_mm, 2), round(y_mm, 2), round(pins.WORK_AREA_Y_MM, 2)))

    def calibrate_sweep(self):
        """Home, then drive to the far rails counting steps. Returns the
        measured travel in microsteps and mm. Updates `homed` to True at the
        end (re-homes). Useful as a diagnostic to verify steps_per_mm and
        detect mechanical wear / belt slip / step loss."""
        self.home()
        backoff_steps = int(pins.HOME_BACKOFF_MM * pins.STEPS_PER_MM)

        # +Y (down): A- B+
        r, travel_y = self._move_until_switch(0, 1, self._sw_y_max)
        if r != "hit":
            raise MotionError("Y calibration failed: " + r)
        self._move_open_loop(1, 0, backoff_steps)   # -Y backoff (A+ B-)

        # +X (right): A- B-
        r, travel_x = self._move_until_switch(0, 0, self._sw_x_max)
        if r != "hit":
            raise MotionError("X calibration failed: " + r)
        self._move_open_loop(1, 1, backoff_steps)   # -X backoff (A+ B+)

        self.home()

        full_x_steps = travel_x + backoff_steps
        full_y_steps = travel_y + backoff_steps
        return {
            "travel_x_steps": full_x_steps,
            "travel_y_steps": full_y_steps,
            "travel_x_mm":    full_x_steps / pins.STEPS_PER_MM,
            "travel_y_mm":    full_y_steps / pins.STEPS_PER_MM,
            "steps_per_mm":   pins.STEPS_PER_MM,
        }
