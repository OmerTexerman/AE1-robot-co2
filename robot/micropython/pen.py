"""Pen lift / braille punch abstraction.

v1 STUB — the servo and pen mechanism are not mounted yet, so every method is
a no-op that just tracks state. The rest of the firmware (motion.py,
main.py) drives the pen through this interface in all the correct places, so
when the servo is wired the only change needed is to flesh out the methods
below.

Migration path when servo arrives:
  - Replace this file with a real implementation that drives PWM on
    pins.SERVO_PIN at pins.SERVO_FREQ_HZ, using duty values
    pins.SERVO_PEN_UP_DUTY / pins.SERVO_PEN_DOWN_DUTY.
  - Calibrate those duty values empirically.
  - punch() should drive down, sleep pins.SERVO_PUNCH_HOLD_MS, drive up.
  - Keep the public method signatures identical so callers don't change.
"""

import pins


PEN_UP   = "up"
PEN_DOWN = "down"


class Pen:
    """Stub pen — methods record intent but do not actuate hardware yet."""

    def __init__(self):
        self._state = PEN_UP
        # When the real implementation lands, it will configure PWM here:
        # from machine import Pin, PWM
        # self._pwm = PWM(Pin(pins.SERVO_PIN))
        # self._pwm.freq(pins.SERVO_FREQ_HZ)
        # self._pwm.duty_u16(pins.SERVO_PEN_UP_DUTY)

    @property
    def state(self):
        return self._state

    def up(self):
        """Lift the pen off the surface. No-op in v1."""
        self._state = PEN_UP

    def down(self):
        """Lower the pen onto the surface. No-op in v1."""
        self._state = PEN_DOWN

    def punch(self):
        """Quickly tap the pen down then up — used for braille dots.
        No-op in v1."""
        self._state = PEN_UP
