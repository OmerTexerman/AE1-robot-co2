"""Minimal pen servo driver.

Keep a single PWM output open for the life of the process and drive the servo
with direct duty changes. No PWM teardown/recreation, no idle timers, no
cached early returns.
"""

from machine import Pin, PWM
import time
import ujson

import pins


PEN_UP = "up"
PEN_DOWN = "down"
PEN_CUSTOM = "custom"
PEN_IDLE = "idle"
PEN_CONFIG_PATH = "pen_config.json"


class Pen:
    def __init__(self):
        self._pwm = PWM(Pin(pins.SERVO_PIN, Pin.OUT))
        self._pwm.freq(pins.SERVO_FREQ_HZ)
        self._state = PEN_UP
        self._current_duty = None
        self._punch_tracks_down = True
        self.up_duty = pins.SERVO_PEN_UP_DUTY
        self.down_duty = pins.SERVO_PEN_DOWN_DUTY
        self.punch_duty = pins.SERVO_PUNCH_DUTY
        self._load_config()
        self.up()

    def _coerce_duty(self, duty):
        duty = int(duty)
        if duty < pins.SERVO_MIN_DUTY:
            return pins.SERVO_MIN_DUTY
        if duty > pins.SERVO_MAX_DUTY:
            return pins.SERVO_MAX_DUTY
        return duty

    def _apply_duty(self, duty, settle_ms=None):
        duty = self._coerce_duty(duty)
        self._pwm.duty_u16(duty)
        self._current_duty = duty
        if settle_ms is None:
            settle_ms = pins.SERVO_MOVE_SETTLE_MS
        if settle_ms > 0:
            time.sleep_ms(settle_ms)
        return duty

    def _load_config(self):
        try:
            with open(PEN_CONFIG_PATH, "r") as f:
                data = ujson.load(f)
        except (OSError, ValueError, KeyError):
            return

        if "pen_up_duty" in data:
            self.up_duty = self._coerce_duty(data["pen_up_duty"])
        if "pen_down_duty" in data:
            self.down_duty = self._coerce_duty(data["pen_down_duty"])
        if "punch_duty" in data:
            self.punch_duty = self._coerce_duty(data["punch_duty"])
            self._punch_tracks_down = False
        else:
            self.punch_duty = self.down_duty
            self._punch_tracks_down = True

    def save_config(self):
        self.up_duty = self._coerce_duty(self.up_duty)
        self.down_duty = self._coerce_duty(self.down_duty)
        self.punch_duty = self._coerce_duty(self.punch_duty)
        with open(PEN_CONFIG_PATH, "w") as f:
            ujson.dump({
                "pen_up_duty": self.up_duty,
                "pen_down_duty": self.down_duty,
                "punch_duty": self.punch_duty,
            }, f)

    @property
    def state(self):
        return self._state

    @property
    def current_duty(self):
        return self._current_duty

    def set_position(self, duty):
        self._apply_duty(duty, settle_ms=0)
        self._state = PEN_CUSTOM
        return self._current_duty

    def idle(self):
        self._pwm.duty_u16(0)
        self._current_duty = None
        self._state = PEN_IDLE

    def up(self):
        self._apply_duty(self.up_duty)
        self._state = PEN_UP
        return self._current_duty

    def down(self):
        self._apply_duty(self.down_duty)
        self._state = PEN_DOWN
        return self._current_duty

    def punch(self):
        self._apply_duty(self.punch_duty)
        self._state = PEN_DOWN
        if pins.SERVO_PUNCH_HOLD_MS > 0:
            time.sleep_ms(pins.SERVO_PUNCH_HOLD_MS)
        self.up()
