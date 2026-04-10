"""Pen lift / braille punch abstraction.

The servo is not mounted yet, so this stub only tracks pen state. Keep the
public interface stable so the real hardware implementation can drop in later.
"""


PEN_UP   = "up"
PEN_DOWN = "down"


class Pen:
    """Stub pen controller."""

    def __init__(self):
        self._state = PEN_UP

    @property
    def state(self):
        return self._state

    def up(self):
        self._state = PEN_UP

    def down(self):
        self._state = PEN_DOWN

    def punch(self):
        self._state = PEN_UP
