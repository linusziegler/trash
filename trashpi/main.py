# Script that runs on the pi. Once the pi is connected via cable, you can start the script through ssh trash@10.12.194.1
import pygame
import sys
import os
import time
import cv2
from threading import Thread
from collections import deque
from datetime import datetime
import RPi.GPIO as GPIO
from adafruit_servokit import ServoKit

# -----------------------------
# CONFIG
# -----------------------------
VISIBLE_LINES = 8
FPS = 5

BG_COLOR = (0, 0, 0)
TEXT_COLOR = (255, 255, 255)

FONT_SIZE = 36
LINE_SPACING = 12
MARGIN = 20

# Storage config
MAX_CAPACITY_MB = 2048
PROGRESS_BAR_LENGTH = 28

# Capture config
CAPTURE_ROOT = "/home/trash/trash_imgs"
SHOT_DELAY = 3               # seconds between image and motor movement
MOTOR_DELAY = 3              # seconds for motor move
VIEWS = ["front", "left", "back", "right"]

CAMERA_INDEX = 0
CAM_WIDTH = 1280
CAM_HEIGHT = 720

# GPIO Button config
BUTTON_PIN = 17              # GPIO pin for the capture button

# -----------------------------
# SERVO CONFIG
# -----------------------------
SERVO_CHANNEL = 0
SERVO_STEP_DEG = 60
SERVO_STEP_DELAY = 0.01      # adjust servo speed
SERVO_MIN = 0
SERVO_MAX = 180

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
# TERMINAL FUNCTIONS
# -----------------------------
def add_text(text):
    lines.append(str(text))
    print(text)

def update_storage():
    size_mb = 5  # assume each capture uses ~5mb
    global used_space_mb
    used_space_mb = min(MAX_CAPACITY_MB, used_space_mb + size_mb)

# -----------------------------
# STORAGE RENDERING
# -----------------------------
def draw_storage_indicator():
    percent = used_space_mb / MAX_CAPACITY_MB if MAX_CAPACITY_MB else 0
    filled = int(PROGRESS_BAR_LENGTH * percent)
    empty = PROGRESS_BAR_LENGTH - filled

    bar = "[" + "#" * filled + "-" * empty + "]"
    percent_text = f"{int(percent * 100)}%"
    
    lines_local = [
        f"used Space: {used_space_mb} mb",
        f"maximum capacity: {MAX_CAPACITY_MB} mb",
        f"{bar} {percent_text}",
        "",
        "ur_trash"
    ]

    y_start = screen_h - MARGIN - ((FONT_SIZE + LINE_SPACING) * len(lines_local))

    for i, line in enumerate(lines_local):
        surf = font.render(line, True, TEXT_COLOR)
        screen.blit(surf, (MARGIN, y_start + i * (FONT_SIZE + LINE_SPACING)))

# -----------------------------
# RENDERING
# -----------------------------
def draw_terminal():
    screen.fill(BG_COLOR)
    y = MARGIN
    for line in lines:
        surf = font.render(line, True, TEXT_COLOR)
        screen.blit(surf, (MARGIN, y))
        y += FONT_SIZE + LINE_SPACING
    draw_storage_indicator()

# -----------------------------
# CAMERA CAPTURE
# -----------------------------
def take_photo(path):
    frame = camera.read()
    if frame is None:
        add_text("!! camera frame missing")
        return

    cv2.imwrite(path, frame)
    update_storage()

# -----------------------------
# SERVO CONTROL
# -----------------------------
def move_servo(target_angle):
    global current_servo_angle

    target_angle = max(SERVO_MIN, min(SERVO_MAX, target_angle))
    step = 1 if target_angle > current_servo_angle else -1

    for angle in range(int(current_servo_angle), int(target_angle), step):
        kit.servo[SERVO_CHANNEL].angle = angle
        time.sleep(SERVO_STEP_DELAY)

    # final snap
    kit.servo[SERVO_CHANNEL].angle = target_angle
    current_servo_angle = target_angle

    # allow servo to settle
    time.sleep(0.15)

    # RELEASE torque to prevent endstop hunting
    kit.servo[SERVO_CHANNEL].angle = None


# -----------------------------
# CAPTURE STATE MACHINE
# -----------------------------
capture_active = False
capture_state = "IDLE"
state_start_time = 0
view_index = 0
object_dir = ""
last_object_time = time.time()

def start_capture():
    global capture_active, capture_state, state_start_time
    global view_index, object_dir

    object_id = datetime.now().strftime("object_%Y%m%d_%H%M%S")
    object_dir = os.path.join(CAPTURE_ROOT, object_id)
    os.makedirs(object_dir, exist_ok=True)

    add_text(f"capture start: {object_id}")

    capture_active = True
    capture_state = "CAPTURE"
    state_start_time = time.time()
    view_index = 0

def update_capture():
    global capture_active, capture_state, state_start_time, view_index

    view = VIEWS[view_index]

    # -----------------------------
    # CAPTURE IMAGE
    # -----------------------------
    if capture_state == "CAPTURE":
        add_text(f">> capturing {view}.png")
        img_path = os.path.join(object_dir, f"{view}.png")
        take_photo(img_path)

        capture_state = "CAPTURE_WAIT"

    # -----------------------------
    # WAIT AFTER CAPTURE
    # -----------------------------
    elif capture_state == "CAPTURE_WAIT":
        if now - state_start_time >= SHOT_DELAY:
            if view_index < len(VIEWS) - 1:
                capture_state = "MOVE"
            else:
                capture_state = "DONE"

    # -----------------------------
    # MOVE SERVO
    # -----------------------------
    elif capture_state == "MOVE":
        target_angle = current_servo_angle + SERVO_STEP_DEG
        add_text(f">> rotating to {target_angle * 1.5}°")
        move_servo(target_angle)

        capture_state = "MOVE_WAIT"
        state_start_time = now

    # -----------------------------
    # WAIT AFTER MOVE
    # -----------------------------
    elif capture_state == "MOVE_WAIT":
        if now - state_start_time >= MOTOR_DELAY:
            view_index += 1
            capture_state = "CAPTURE"

    # -----------------------------
    # FINISH
    # -----------------------------
    elif capture_state == "DONE":
        add_text(">> returning servo to 0°")
        move_servo(0)

        add_text("capture complete")
        capture_active = False
# -----------------------------
# INIT
# -----------------------------
pygame.init()
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.mouse.set_visible(False)

screen_w, screen_h = screen.get_size()
clock = pygame.time.Clock()

font = pygame.font.Font("DotGothic16-Regular.ttf", FONT_SIZE)

lines = deque(maxlen=VISIBLE_LINES)
used_space_mb = 0

os.makedirs(CAPTURE_ROOT, exist_ok=True)

# GPIO Button
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Servo init
kit = ServoKit(channels=8)
current_servo_angle = 0
kit.servo[SERVO_CHANNEL].angle = current_servo_angle

# Start webcam
camera = WebcamStream(
    src=CAMERA_INDEX,
    width=CAM_WIDTH,
    height=CAM_HEIGHT
).start()

# -----------------------------
# MAIN LOOP
# -----------------------------
add_text("system ready")

running = True
try:
    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        now = time.time()

        # trigger capture on button press
        if not capture_active and GPIO.input(BUTTON_PIN) == GPIO.LOW:
            add_text(">> button triggered")
            start_capture()
            last_object_time = now
            time.sleep(0.3)  # debounce

        if capture_active:
            update_capture()

        draw_terminal()
        pygame.display.flip()

except Exception as e:
    print(f"Error: {e}")

finally:
    camera.stop()
    kit.servo[SERVO_CHANNEL].angle = 0
    GPIO.cleanup()
    pygame.quit()
    sys.exit()