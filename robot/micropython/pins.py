"""Pin assignments and motion constants for the AE1 CoreXY gantry.

The logical origin is the top-left corner of the work area, with +X to the
right and +Y downward.
"""

# Stepper motor pins.
STEP_A_PIN = 11
DIR_A_PIN  = 12
STEP_B_PIN = 20
DIR_B_PIN  = 19

# Limit switches are active-low with internal pull-ups.
SW_X_MIN_PIN = 27   # left rail   (carriage end-stop on the bridge)
SW_X_MAX_PIN = 26   # right rail
SW_Y_MIN_PIN = 28   # top rail    (bridge end-stop in the frame)
SW_Y_MAX_PIN = 17   # bottom rail

# Servo constants stay here even though the current Pen implementation is a stub.
SERVO_PIN           = 13
SERVO_FREQ_HZ       = 50
SERVO_PEN_UP_DUTY   = 2000   # Placeholder; calibrate when the mechanism is mounted.
SERVO_PEN_DOWN_DUTY = 8000   # Placeholder; calibrate when the mechanism is mounted.
SERVO_PUNCH_HOLD_MS = 60

# 200 full steps/rev * 8 microsteps / (20-tooth pulley * 2 mm pitch).
# This is a hardware constant — only changes if you swap pulleys or belts.
STEPS_PER_MM = 40

# After homing, the carriage backs off from the min rails before treating that
# position as logical (0, 0).
HOME_BACKOFF_MM = 5.0

# Extra safety buffer below the max rails when checking soft limits.
SOFT_LIMIT_MARGIN_MM = 2.0

# Travel distances are NOT hardcoded — they're measured by calibrate_sweep()
# and saved to CALIBRATION_PATH on flash. motion.py loads them on init and
# computes the usable work area dynamically:
#   work_area = travel - HOME_BACKOFF_MM - SOFT_LIMIT_MARGIN_MM
CALIBRATION_PATH = "calibration.json"

# Half-periods in microseconds. 500 us yields a 1 kHz step rate (~25 mm/s).
DEFAULT_HALF_PERIOD_US = 500
HOMING_HALF_PERIOD_US  = 500
