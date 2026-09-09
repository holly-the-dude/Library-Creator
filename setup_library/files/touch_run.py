#!/usr/bin/python3
import evdev
from evdev import InputDevice, categorize, ecodes
import time
import subprocess

# Replace with your touchscreen device path
device_path = '/dev/input/event0'

# Target X and Y position ranges and thresholds for both areas
TARGET_1_X = 790
TARGET_1_Y = 512
TARGET_2_X = 2520
TARGET_2_Y = 1792
TARGET_3_X = 471
TARGET_3_Y = 3646
TOLERANCE = 150
HOLD_TIME = 5  # seconds for both areas
HOLD_TIME2 = 15

x_pos = None
y_pos = None

# Initialize timing and state variables for both areas
start_time_1 = None
start_time_2 = None
start_time_3 = None
holding_1 = False
holding_2 = False
holding_3 = False

# Create an InputDevice instance
device = InputDevice(device_path)

def in_range(value, target, tolerance):
    return target - tolerance <= value <= target + tolerance

print("Listening for touch events...")

try:
    for event in device.read_loop():
        # Only consider absolute position events
        if event.type == ecodes.EV_ABS:
            if event.code == ecodes.ABS_X:
                x_pos = event.value
            elif event.code == ecodes.ABS_Y:
                y_pos = event.value

            # Ensure both x_pos and y_pos are defined before checking
            if x_pos is not None and y_pos is not None:
                # Check if X and Y are within the target range for Area 1
                if in_range(x_pos, TARGET_1_X, TOLERANCE) and in_range(y_pos, TARGET_1_Y, TOLERANCE):
                    if not holding_1:
                        holding_1 = True
                        start_time_1 = time.time()
                        print("Area 1: Position in range, started timing...")
                    elif holding_1 and (time.time() - start_time_1 >= HOLD_TIME):
                        print("Area 1: Position held for 5 seconds, executing script...")
                        subprocess.run(['/usr/local/bin/touch_run1.sh'])
                        holding_1 = False  # Reset after running the script
                else:
                    holding_1 = False  # Reset if position goes out of range

                # Check if X and Y are within the target range for Area 2
                if in_range(x_pos, TARGET_2_X, TOLERANCE) and in_range(y_pos, TARGET_2_Y, TOLERANCE):
                    if not holding_2:
                        holding_2 = True
                        start_time_2 = time.time()
                        print("Area 2: Position in range, started timing...")
                    elif holding_2 and (time.time() - start_time_2 >= HOLD_TIME):
                        print("Area 2: Position held for 5 seconds, executing script...")
                        subprocess.run(['/usr/local/bin/touch_run2.sh'])
                        holding_2 = False  # Reset after running the script
                else:
                    holding_2 = False  # Reset if position goes out of range

                # Check if X and Y are within the target range for Area 3
                if in_range(x_pos, TARGET_3_X, TOLERANCE) and in_range(y_pos, TARGET_3_Y, TOLERANCE):
                    if not holding_3:
                        holding_3 = True
                        start_time_3 = time.time()
                        print("Area 3: Position in range, started timing...")
                    elif holding_3 and (time.time() - start_time_3 >= HOLD_TIME2):
                        print("Area 2: Position held for 15 seconds, executing script...")
                        subprocess.run(['/usr/local/bin/displayit file_me_invert.jpg'])
                        holding_2 = False  # Reset after running the script
                else:
                    holding_3 = False  # Reset if position goes out of range
except KeyboardInterrupt:
    print("\nExiting touch event listener.")