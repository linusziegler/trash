# Runs on main machine, controls motor via ESP through serial
# Keyboard-triggered state machine for object capture and rotation
import sys
import os
import time
import cv2
import serial
import queue
from threading import Thread
from datetime import datetime
from pynput import keyboard
import requests

# -----------------------------
# CONFIG
# -----------------------------
FPS = 5

# Capture config
CAPTURE_ROOT = "../image_in"
SHOT_DELAY = 3               # seconds between image and motor movement
MOTOR_DELAY = 3              # seconds for motor settle
VIEWS = ["front", "left", "back", "right"]

CAMERA_INDEX = 0
CAM_WIDTH = 1280
CAM_HEIGHT = 720

# Serial config for ESP communication
SERIAL_PORT = "/dev/ttyUSB0"  # adjust based on your system
SERIAL_BAUD = 115200
SERIAL_TIMEOUT = 1.0

# Keyboard triggers
TRIGGER_KEY = 'q'

# Website notification
WEBSITE_URL = "http://localhost:5000"
NOTIFY_LOADING = True  # Set to False if offline

# -----------------------------
# WEBCAM THREAD
# -----------------------------
class WebcamStream:
    def __init__(self, src=0, width=640, height=480):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

        self.grabbed, self.frame = self.cap.read()
        self.stopped = False

    def start(self):
        Thread(target=self.update, daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            self.grabbed, self.frame = self.cap.read()

    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True
        self.cap.release()

# -----------------------------
# SERIAL COMMUNICATION
# -----------------------------
class SerialMotorControl:
    def __init__(self, port, baudrate, timeout):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.connected = False
        
    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.connected = True
            time.sleep(1)  # wait for Arduino to reset
            print(f"[SERIAL] Connected to {self.port}")
            return True
        except Exception as e:
            print(f"[SERIAL] ERROR: {e}")
            self.connected = False
            return False
    
    def send_command(self, command):
        if not self.connected or self.ser is None:
            return False
        
        try:
            self.ser.write(f"{command}\n".encode())
            return True
        except Exception as e:
            print(f"[SERIAL] ERROR: {e}")
            return False
    
    def increment(self):
        """Send increment command to ESP"""
        return self.send_command("increment")
    
    def disconnect(self):
        if self.ser:
            self.ser.close()
            self.connected = False



# -----------------------------
# CAMERA CAPTURE
# -----------------------------
def take_photo(path):
    frame = camera.read()
    if frame is None:
        print("[CAPTURE] ERROR: Camera frame missing")
        return False

    cv2.imwrite(path, frame)
    return True

# -----------------------------
# MOTOR CONTROL
# -----------------------------
def increment_motor():
    if not motor_control.connected:
        print("[MOTOR] ERROR: Motor not connected, skipping increment")
        return False
    
    if motor_control.increment():
        time.sleep(MOTOR_DELAY)
        return True
    
    return False

# -----------------------------
# CAPTURE STATE MACHINE
# -----------------------------
capture_active = False
capture_state = "IDLE"
state_start_time = 0
view_index = 0
object_dir = ""

def start_capture():
    global capture_active, capture_state, state_start_time
    global view_index, object_dir

    object_id = datetime.now().strftime("object_%Y%m%d_%H%M%S")
    object_dir = os.path.join(CAPTURE_ROOT, object_id)
    os.makedirs(object_dir, exist_ok=True)

    print(f"[CAPTURE] START: {object_id}")
    
    # Notify website of loading
    if NOTIFY_LOADING:
        try:
            response = requests.post(
                f"{WEBSITE_URL}/api/notify-loading",
                json={"object_id": object_id},
                timeout=2
            )
            if response.status_code in [200, 201]:
                print(f"[WEBSITE] Notified website of loading for {object_id}")
            else:
                print(f"[WEBSITE] Warning: HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"[WEBSITE] Warning: Could not notify website: {e}")

    capture_active = True
    capture_state = "CAPTURE"
    state_start_time = time.time()
    view_index = 0

def update_capture():
    global capture_active, capture_state, state_start_time, view_index

    now = time.time()
    view = VIEWS[view_index]

    # CAPTURE IMAGE
    if capture_state == "CAPTURE":
        img_path = os.path.join(object_dir, f"{view}.png")
        take_photo(img_path)
        capture_state = "CAPTURE_WAIT"

    # WAIT AFTER CAPTURE
    elif capture_state == "CAPTURE_WAIT":
        if now - state_start_time >= SHOT_DELAY:
            if view_index < len(VIEWS) - 1:
                # Not last view: rotate and capture next
                increment_motor()
                view_index += 1
                capture_state = "CAPTURE"
            else:
                # Last view: done
                print(f"[CAPTURE] COMPLETE: {object_dir}")
                capture_active = False

# -----------------------------
# KEYBOARD INPUT HANDLING
# -----------------------------
def enable_input_mode():
    pass

input_queue = queue.Queue()

def on_key_press(key):
    """Callback for key press events"""
    try:
        char = key.char
        if char:
            input_queue.put(char.lower())
    except AttributeError:
        pass  # Special keys (shift, ctrl, etc)

def disable_input_mode():
    pass

def check_keyboard_input():
    """Non-blocking check for queued input"""
    try:
        return input_queue.get_nowait()
    except queue.Empty:
        return None

# -----------------------------
# INIT
# -----------------------------
print("TRASHCAM - Starting...")

# Create output directory
os.makedirs(CAPTURE_ROOT, exist_ok=True)

# Initialize camera
camera = WebcamStream(
    src=CAMERA_INDEX,
    width=CAM_WIDTH,
    height=CAM_HEIGHT
).start()

# Initialize motor control via serial
motor_control = SerialMotorControl(SERIAL_PORT, SERIAL_BAUD, SERIAL_TIMEOUT)
motor_connected = motor_control.connect()

if not motor_connected:
        print("[INIT] WARNING: Motor not connected")

print(f"Press '{TRIGGER_KEY}' to capture")

# Start keyboard listener
listener = keyboard.Listener(on_press=on_key_press)
listener.start()

# Main loop variables
running = True

# Clock-like timing
last_time = time.time()
try:
    while running:
        now = time.time()
        
        # Throttle to FPS
        elapsed = now - last_time
        if elapsed < (1.0 / FPS):
            time.sleep((1.0 / FPS) - elapsed)
            continue
        
        last_time = time.time()
        
        # Check keyboard input
        key = check_keyboard_input()
        
        if key:
            if key == TRIGGER_KEY:
                if not capture_active:
                    start_capture()
                else:
                    print(f"[WARN] Capture already in progress")
        
        # Update capture state machine
        if capture_active:
            update_capture()

except KeyboardInterrupt:
    print("\n[QUIT] Interrupted by user")

except Exception as e:
    print(f"[ERROR] {e}")

finally:
    # Stop camera
    camera.stop()
    
    # Disconnect motor if connected
    if motor_connected:
        motor_control.disconnect()
    
    sys.exit()
