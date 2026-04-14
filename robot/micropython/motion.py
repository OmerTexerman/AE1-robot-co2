"""CoreXY motion controller for the AE1 robot."""

from machine import Pin
import time
import ujson

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
        self.calibrated = False

        self.travel_x_mm = None
        self.travel_y_mm = None
        self.work_area_x_mm = None
        self.work_area_y_mm = None
        self._load_calibration()

        self._job_state = {
            "status":   STATUS_IDLE,
            "kind":     None,
            "job_id":   None,
            "op_index": 0,
            "total_ops": 0,
            "error":    None,
            "result":   None,
        }
        self._abort_requested = False

    def _load_calibration(self):
        """Try to load saved calibration from flash. Non-fatal if missing."""
        try:
            with open(pins.CALIBRATION_PATH, "r") as f:
                data = ujson.load(f)
            tx = data.get("travel_x_mm")
            ty = data.get("travel_y_mm")
            if tx is not None and ty is not None:
                self._apply_calibration(float(tx), float(ty))
        except (OSError, ValueError, KeyError):
            pass

    def _save_calibration(self, travel_x_mm, travel_y_mm):
        """Persist calibration to flash so it survives power cycles."""
        data = {
            "travel_x_mm": travel_x_mm,
            "travel_y_mm": travel_y_mm,
            "steps_per_mm": pins.STEPS_PER_MM,
        }
        with open(pins.CALIBRATION_PATH, "w") as f:
            ujson.dump(data, f)

    def _apply_calibration(self, travel_x_mm, travel_y_mm):
        self.travel_x_mm = travel_x_mm
        self.travel_y_mm = travel_y_mm
        self.work_area_x_mm = travel_x_mm - pins.HOME_BACKOFF_MM - pins.SOFT_LIMIT_MARGIN_MM
        self.work_area_y_mm = travel_y_mm - pins.HOME_BACKOFF_MM - pins.SOFT_LIMIT_MARGIN_MM
        self.calibrated = True

    def position_mm(self):
        return [self.position_steps[0] / pins.STEPS_PER_MM,
                self.position_steps[1] / pins.STEPS_PER_MM]

    def get_status(self):
        total = self._job_state["total_ops"]
        op_idx = self._job_state["op_index"]
        progress_pct = round(100.0 * op_idx / total, 1) if total else 0.0
        status = {
            "status":       self._job_state["status"],
            "kind":         self._job_state["kind"],
            "job_id":       self._job_state["job_id"],
            "op_index":     op_idx,
            "total_ops":    total,
            "progress_pct": progress_pct,
            "position_mm":  self.position_mm(),
            "homed":        self.homed,
            "calibrated":   self.calibrated,
            "pen":          self.pen.state,
            "switches":     self.switch_state(),
            "error":        self._job_state["error"],
        }
        if self._job_state["result"] is not None:
            status["result"] = self._job_state["result"]
        if self.calibrated:
            status["work_area_mm"] = [self.work_area_x_mm, self.work_area_y_mm]
        return status

    def request_abort(self):
        """Abort the running job at the next yield point."""
        self._abort_requested = True

    def _raise_if_aborted(self):
        if self._abort_requested:
            self.homed = False
            raise MotionError("aborted")

    def reset_job_state(self):
        self._job_state["status"]   = STATUS_IDLE
        self._job_state["kind"]     = None
        self._job_state["job_id"]   = None
        self._job_state["op_index"] = 0
        self._job_state["total_ops"] = 0
        self._job_state["error"]    = None
        self._job_state["result"]   = None
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
            self._raise_if_aborted()
            self._stepA.value(1); self._stepB.value(1)
            time.sleep_us(half_us)
            self._stepA.value(0); self._stepB.value(0)
            time.sleep_us(half_us)

    def _move_until_switch(self, dA, dB, target_switch, max_steps=20000, half_us=None, abort_other_switches=True):
        """Drive in (dA, dB) direction until target_switch is pressed."""
        if half_us is None:
            half_us = pins.HOMING_HALF_PERIOD_US
        self._dirA.value(dA); self._dirB.value(dB)
        self._stepA.value(0); self._stepB.value(0)
        time.sleep_ms(2)
        for i in range(max_steps):
            self._raise_if_aborted()
            if target_switch.value() == 0:
                self._stepA.value(0); self._stepB.value(0)
                time.sleep_ms(pins.HOME_SWITCH_SETTLE_MS)
                return ("hit", i)
            if abort_other_switches:
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
        self.pen.up()
        self.homed = False

        backoff_steps = int(pins.HOME_BACKOFF_MM * pins.STEPS_PER_MM)

        result, _ = self._move_until_switch(1, 0, self._sw_y_min, abort_other_switches=False)
        if result != "hit":
            raise MotionError("Y homing failed: " + result)
        self._move_open_loop(0, 1, backoff_steps, half_us=pins.HOMING_HALF_PERIOD_US)

        result, _ = self._move_until_switch(1, 1, self._sw_x_min, abort_other_switches=False)
        if result != "hit":
            raise MotionError("X homing failed: " + result)
        self._move_open_loop(0, 0, backoff_steps, half_us=pins.HOMING_HALF_PERIOD_US)

        self.position_steps = [0, 0]
        self.homed = True

    def move_by_steps(self, dx_steps, dy_steps, half_us=None):
        """Move by signed step deltas and update the tracked position."""
        if half_us is None:
            half_us = pins.DEFAULT_HALF_PERIOD_US

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
        """Move by relative millimeter deltas."""
        dx_steps = int(round(dx_mm * pins.STEPS_PER_MM))
        dy_steps = int(round(dy_mm * pins.STEPS_PER_MM))
        return self.move_by_steps(dx_steps, dy_steps, half_us)

    def move_to_mm(self, x_mm, y_mm, half_us=None):
        """Move to an absolute millimeter position."""
        if not self.homed:
            raise MotionError("Cannot move_to: robot is not homed")
        if not self.calibrated:
            raise MotionError("Cannot move_to: robot is not calibrated")
        if not (0 <= x_mm <= self.work_area_x_mm):
            raise MotionError("X out of bounds: {} (range 0..{})".format(
                round(x_mm, 2), round(self.work_area_x_mm, 2)))
        if not (0 <= y_mm <= self.work_area_y_mm):
            raise MotionError("Y out of bounds: {} (range 0..{})".format(
                round(y_mm, 2), round(self.work_area_y_mm, 2)))

        target_x_steps = int(round(x_mm * pins.STEPS_PER_MM))
        target_y_steps = int(round(y_mm * pins.STEPS_PER_MM))
        dx_steps = target_x_steps - self.position_steps[0]
        dy_steps = target_y_steps - self.position_steps[1]
        return self.move_by_steps(dx_steps, dy_steps, half_us)

    def _travel_half_us(self, half_us):
        return pins.TRAVEL_HALF_PERIOD_US if half_us is None else half_us

    def _draw_half_us(self, half_us):
        return pins.DRAW_HALF_PERIOD_US if half_us is None else half_us

    def _validated_point(self, point, label):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise MotionError("{} must contain exactly 2 coordinates".format(label))
        x_mm, y_mm = point[0], point[1]
        if isinstance(x_mm, bool) or not isinstance(x_mm, (int, float)):
            raise MotionError("{} x coordinate must be numeric".format(label))
        if isinstance(y_mm, bool) or not isinstance(y_mm, (int, float)):
            raise MotionError("{} y coordinate must be numeric".format(label))
        return x_mm, y_mm

    def _validate_operation(self, op):
        op_type = op.get("type")
        if op_type == "draw":
            points = op.get("points")
            if not isinstance(points, list) or len(points) < 2:
                raise MotionError("draw operation needs at least 2 points")
            for index, point in enumerate(points):
                x_mm, y_mm = self._validated_point(point, "draw point {}".format(index))
                self._check_bounds(x_mm, y_mm)
        elif op_type == "travel":
            points = op.get("points")
            if not isinstance(points, list) or not points:
                raise MotionError("travel operation needs at least 1 point")
            for index, point in enumerate(points):
                x_mm, y_mm = self._validated_point(point, "travel point {}".format(index))
                self._check_bounds(x_mm, y_mm)
        elif op_type == "punch":
            x_mm, y_mm = self._validated_point(op.get("point"), "punch point")
            self._check_bounds(x_mm, y_mm)
        else:
            raise MotionError("unknown operation type: {}".format(op_type))

    def execute_operations(self, operations, job_id=None, half_us=None):
        """Execute a validated toolpath."""
        if not self.homed:
            raise MotionError("Cannot execute: robot is not homed")
        if not self.calibrated:
            raise MotionError("Cannot execute: robot is not calibrated")

        for op in operations:
            self._validate_operation(op)

        self._job_state["status"]    = STATUS_RUNNING
        self._job_state["job_id"]    = job_id
        self._job_state["op_index"]  = 0
        self._job_state["total_ops"] = len(operations)
        self._job_state["error"]     = None
        self._abort_requested = False

        try:
            for i, op in enumerate(operations):
                op_type = op.get("type")

                if op_type == "draw":
                    self._execute_draw(op, half_us)
                elif op_type == "travel":
                    self._execute_travel(op, half_us)
                elif op_type == "punch":
                    self._execute_punch(op, half_us)
                self._job_state["op_index"] = i + 1

            self.pen.up()
            self._job_state["op_index"] = len(operations)
            self._job_state["status"] = STATUS_COMPLETE
        except MotionError as exc:
            if self._abort_requested:
                self._job_state["status"] = STATUS_ABORTED
            else:
                self._job_state["status"] = STATUS_FAILED
                self._job_state["error"] = str(exc)
            try:
                self.pen.up()
            except Exception:
                pass
            raise

    def _execute_draw(self, op, half_us):
        pts = op.get("points") or []
        if len(pts) < 2:
            return
        start = pts[0]
        self.pen.up()
        self.move_to_mm(start[0], start[1], self._travel_half_us(half_us))
        self.pen.down()
        time.sleep_ms(pins.PEN_DOWN_SETTLE_MS)
        for pt in pts[1:]:
            self.move_to_mm(pt[0], pt[1], self._draw_half_us(half_us))
        self.pen.up()

    def _execute_travel(self, op, half_us):
        pts = op.get("points") or []
        if not pts:
            return
        target = pts[-1]
        self.pen.up()
        self.move_to_mm(target[0], target[1], self._travel_half_us(half_us))

    def _execute_punch(self, op, half_us):
        pt = op.get("point")
        if pt is None:
            return
        self.pen.up()
        self.move_to_mm(pt[0], pt[1], self._travel_half_us(half_us))
        self.pen.punch()

    def _check_bounds(self, x_mm, y_mm):
        if not self.calibrated:
            raise MotionError("Cannot check bounds: robot is not calibrated")
        if not (0 <= x_mm <= self.work_area_x_mm):
            raise MotionError("Op out of X bounds at ({}, {}): max {}".format(
                round(x_mm, 2), round(y_mm, 2), round(self.work_area_x_mm, 2)))
        if not (0 <= y_mm <= self.work_area_y_mm):
            raise MotionError("Op out of Y bounds at ({}, {}): max {}".format(
                round(x_mm, 2), round(y_mm, 2), round(self.work_area_y_mm, 2)))

    def calibrate_sweep(self):
        """Measure full X/Y travel and persist the resulting work area."""
        self.pen.up()
        self.home()
        self.homed = False
        backoff_steps = int(pins.HOME_BACKOFF_MM * pins.STEPS_PER_MM)
        try:
            self.pen.up()
            r, travel_y = self._move_until_switch(0, 1, self._sw_y_max, abort_other_switches=False)
            if r != "hit":
                raise MotionError("Y calibration failed: " + r)
            self._move_open_loop(1, 0, backoff_steps, half_us=pins.HOMING_HALF_PERIOD_US)

            r, travel_x = self._move_until_switch(0, 0, self._sw_x_max, abort_other_switches=False)
            if r != "hit":
                raise MotionError("X calibration failed: " + r)
            self._move_open_loop(1, 1, backoff_steps, half_us=pins.HOMING_HALF_PERIOD_US)

            self.home()

            full_x_steps = travel_x + backoff_steps
            full_y_steps = travel_y + backoff_steps
            travel_x_mm = full_x_steps / pins.STEPS_PER_MM
            travel_y_mm = full_y_steps / pins.STEPS_PER_MM

            try:
                self._save_calibration(travel_x_mm, travel_y_mm)
            except OSError as exc:
                raise MotionError("calibration save failed: {}".format(exc))
            self._apply_calibration(travel_x_mm, travel_y_mm)

            return {
                "travel_x_steps": full_x_steps,
                "travel_y_steps": full_y_steps,
                "travel_x_mm":    travel_x_mm,
                "travel_y_mm":    travel_y_mm,
                "work_area_x_mm": self.work_area_x_mm,
                "work_area_y_mm": self.work_area_y_mm,
                "steps_per_mm":   pins.STEPS_PER_MM,
            }
        except MotionError:
            self.homed = False
            raise
