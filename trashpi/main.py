import pygame
import sys
import os
import time
import cv2
from threading import Thread
from collections import deque
from datetime import datetime

# -----------------------------
# CONFIG
# -----------------------------
VISIBLE_LINES = 8
FPS = 30

BG_COLOR = (0, 0, 0)
TEXT_COLOR = (255, 255, 255)

FONT_SIZE = 32
LINE_SPACING = 8
MARGIN = 20

# Storage config
MAX_CAPACITY_MB = 2048
PROGRESS_BAR_LENGTH = 30

# Capture config
CAPTURE_ROOT = "/home/trash/trash_imgs"
CAPTURE_INTERVAL = 45        # seconds between objects
SHOT_DELAY = 1               # seconds between images
MOTOR_DELAY = 5           # seconds for motor move
VIEWS = ["front", "left", "back", "right"]

CAMERA_INDEX = 0
CAM_WIDTH = 1280
CAM_HEIGHT = 720

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
# INIT
# -----------------------------
pygame.init()
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.mouse.set_visible(False)

screen_w, screen_h = screen.get_size()
clock = pygame.time.Clock()

font = pygame.font.Font("SGr-IosevkaTerm-ExtraBold.ttc", FONT_SIZE)

lines = deque(maxlen=VISIBLE_LINES)
used_space_mb = 0

os.makedirs(CAPTURE_ROOT, exist_ok=True)

# Start webcam
camera = WebcamStream(
    src=CAMERA_INDEX,
    width=CAM_WIDTH,
    height=CAM_HEIGHT
).start()

# -----------------------------
# TERMINAL FUNCTIONS
# -----------------------------
def add_text(text):
    lines.append(str(text))

def update_storage_from_file(path):
    size_mb = os.path.getsize(path) // (1024 * 1024)
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

    y_start = screen_h - MARGIN - (FONT_SIZE * 3)

    for i, line in enumerate([
        f"Used Space: {used_space_mb} mb",
        f"Maximum Capacity: {MAX_CAPACITY_MB} mb",
        f"{bar} {percent_text}"
    ]):
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
        add_text("!! CAMERA FRAME MISSING")
        return

    cv2.imwrite(path, frame)
    update_storage_from_file(path)

# -----------------------------
# CAPTURE STATE MACHINE
# -----------------------------
capture_active = False
capture_state = "IDLE"
state_start_time = 0
view_index = 0
object_dir = ""
last_object_time = time.time() - CAPTURE_INTERVAL

def start_capture():
    global capture_active, capture_state, state_start_time
    global view_index, object_dir

    object_id = datetime.now().strftime("object_%Y%m%d_%H%M%S")
    object_dir = os.path.join(CAPTURE_ROOT, object_id)
    os.makedirs(object_dir, exist_ok=True)

    add_text(f"CAPTURE START: {object_id}")

    capture_active = True
    capture_state = "MOVE"
    state_start_time = time.time()
    view_index = 0

def update_capture():
    global capture_active, capture_state, state_start_time, view_index

    now = time.time()
    view = VIEWS[view_index]

    if capture_state == "MOVE":
        add_text(f">> positioning for {view}")
        capture_state = "MOVE_WAIT"
        state_start_time = now

    elif capture_state == "MOVE_WAIT":
        if now - state_start_time >= MOTOR_DELAY:
            capture_state = "CAPTURE"

    elif capture_state == "CAPTURE":
        add_text(f">> capturing {view}.png")
        img_path = os.path.join(object_dir, f"{view}.png")
        take_photo(img_path)

        if view_index < len(VIEWS) - 1:
            capture_state = "SHOT_WAIT"
            state_start_time = now
        else:
            capture_state = "DONE"

    elif capture_state == "SHOT_WAIT":
        if now - state_start_time >= SHOT_DELAY:
            view_index += 1
            capture_state = "MOVE"

    elif capture_state == "DONE":
        add_text("CAPTURE COMPLETE")
        capture_active = False

# -----------------------------
# MAIN LOOP
# -----------------------------
add_text("SYSTEM READY")
add_text("AUTO MODE ENABLED")
add_text(f"INTERVAL: {CAPTURE_INTERVAL}s")

running = True
while running:
    clock.tick(FPS)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    now = time.time()

    if not capture_active and now - last_object_time >= CAPTURE_INTERVAL:
        add_text(">> AUTO TRIGGER")
        start_capture()
        last_object_time = now

    if capture_active:
        update_capture()

    draw_terminal()
    pygame.display.flip()

# -----------------------------
# CLEANUP
# -----------------------------
camera.stop()
pygame.quit()
sys.exit()