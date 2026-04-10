"""Pin assignments and motion constants for the AE1 CoreXY gantry.

Single source of truth — derived empirically from the bring-up bench session
on 2026-04-09 (limit-switch mapping + jog tests + calibration sweep).

Logical coordinate convention:
  - Origin (0, 0) is the top-left corner of the work area.
  - +X is to the right (carriage along the bridge).
  - +Y is downward (bridge through the frame).
  This matches SVG / HTML canvas conventions and the existing toolpath
  pipeline in speech-app/.
"""

# --- Stepper motor pins (TMC2209 STEP/DIR drivers, no enable pin wired) ---
STEP_A_PIN = 11
DIR_A_PIN  = 12
STEP_B_PIN = 20
DIR_B_PIN  = 19

# --- Limit switches (active-low with internal pull-up; pressed → value() == 0) ---
SW_X_MIN_PIN = 27   # left rail   (carriage end-stop on the bridge)
SW_X_MAX_PIN = 26   # right rail
SW_Y_MIN_PIN = 28   # top rail    (bridge end-stop in the frame)
SW_Y_MAX_PIN = 17   # bottom rail

# --- Servo (pen lift / braille punch) ---
# Pin is wired but the lift mechanism isn't mounted yet. The Pen class in
# pen.py is currently a stub; these constants will be used (and re-tuned)
# when the servo is integrated. Duty values are duty_u16 (16-bit) for
# machine.PWM at 50 Hz; the placeholder values come from the original
# bring-up scratch code and are NOT calibrated yet.
SERVO_PIN           = 13
SERVO_FREQ_HZ       = 50
SERVO_PEN_UP_DUTY   = 2000   # placeholder — calibrate when mounted
SERVO_PEN_DOWN_DUTY = 8000   # placeholder — calibrate when mounted
SERVO_PUNCH_HOLD_MS = 60     # how long to keep the pen down for a braille dot

# --- Motion calibration ---
# 1.8°/step × 1/8 microstepping × 20T GT2 pulley × 2 mm belt pitch
#   microsteps/rev = 200 × 8 = 1600
#   mm/rev         = 20 × 2  = 40
#   steps/mm       = 1600 / 40 = 40
STEPS_PER_MM = 40

# Measured travel between switch contact points from the calibration sweep.
TRAVEL_X_MM = 254.225   # 10169 microsteps end-to-end
TRAVEL_Y_MM = 212.475   #  8499 microsteps end-to-end

# After homing, the carriage backs off this far from each min rail and that
# becomes logical (0, 0). Gives soft margin so a soft-limit clamp at 0 still
# leaves the switch unpressed.
HOME_BACKOFF_MM = 5.0

# Extra safety buffer below the max rails when checking soft limits.
SOFT_LIMIT_MARGIN_MM = 2.0

# Maximum reachable logical coordinate from (0, 0).
#   travel - HOME_BACKOFF (consumed by the start-side backoff)
#          - SOFT_LIMIT_MARGIN (safety from the far-side rail)
WORK_AREA_X_MM = TRAVEL_X_MM - HOME_BACKOFF_MM - SOFT_LIMIT_MARGIN_MM   # ~247.2
WORK_AREA_Y_MM = TRAVEL_Y_MM - HOME_BACKOFF_MM - SOFT_LIMIT_MARGIN_MM   # ~205.5

# --- Motion timing ---
# Half-period in microseconds. 500 µs each = 1 ms period = 1 kHz step rate
# = 25 mm/s carriage speed.
DEFAULT_HALF_PERIOD_US = 500
HOMING_HALF_PERIOD_US  = 500
