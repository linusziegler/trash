# script triggers ComfyUI workflow when a new folder with 4 input images is added to WATCH_DIR
# and periodically syncs COMFY_OUTPUT -> OBJECT_OUT using robocopy (every 10 seconds)
# CHANGE COMFY_ROOT to your ComfyUI installation path !!!!!!!

import json
import time
import shutil
import requests
import subprocess
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

# Directory of this script (trashsite3D/)
SCRIPT_DIR = Path(__file__).resolve().parent
# Project root (one level above script dir)
BASE_DIR = SCRIPT_DIR.parent
print(f"Specified Base directory: {BASE_DIR}")

# Source folder that images end up in
WATCH_DIR = BASE_DIR / "image_in"

COMFY_ROOT = Path("C:/Users/duraX/Documents/ComfyUI")  # <-- CHANGE THIS !!!
print(f"Specified ComfyUI root: {COMFY_ROOT}")

COMFY_INPUT = COMFY_ROOT / "input"
OUTPUT_FOLDER = "trashscans"
COMFY_OUTPUT = COMFY_ROOT / "output" / OUTPUT_FOLDER
OBJECT_OUT = BASE_DIR / "object_out"

WORKFLOW_JSON = Path("3d_hunyuan3d_multiview_to_model_turbo.json")
COMFY_API = "http://127.0.0.1:8000/prompt"

# -----------------------------------------------------------------------------
# View mapping
# -----------------------------------------------------------------------------

SUFFIX_MAP = {
    "front": "front",
    "left": "left",
    "right": "right",
    "back": "back",
}

# -----------------------------------------------------------------------------
# Robocopy sync (every 10 seconds)
# -----------------------------------------------------------------------------

def run_robocopy_once():
    cmd = [
        "robocopy",
        str(COMFY_OUTPUT),
        str(OBJECT_OUT),
        "/E",        # copy new & updated files, no deletes
        "/R:0",      # no retries
        "/W:0",      # no wait
        "/NFL",      # no file list
        "/NDL",      # no dir list
        "/NJH",      # no job header
        "/NJS",      # no job summary
    ]

    # robocopy uses non-zero exit codes for success -> suppress output
    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True
    )


def robocopy_sync_loop(interval=10):
    COMFY_OUTPUT.mkdir(parents=True, exist_ok=True)
    OBJECT_OUT.mkdir(parents=True, exist_ok=True)

    print(f"Robocopy sync started (every {interval}s)")

    while True:
        run_robocopy_once()
        time.sleep(interval)

# -----------------------------------------------------------------------------
# Watchdog handler
# -----------------------------------------------------------------------------

class NewFolderHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            return

        folder = Path(event.src_path)
        print(f"New folder detected: {folder.name}")

        # wait briefly for files to finish copying
        time.sleep(1)

        images = {}
        for img in folder.iterdir():
            if not img.is_file():
                continue
            for suffix in SUFFIX_MAP:
                if img.stem.endswith(suffix):
                    images[suffix] = img

        if len(images) != 4:
            print(f"Skipping {folder.name}: missing views")
            return

        print(f"Found all 4 views for {folder.name}")
        self.run_comfy(folder.name, images)

    def run_comfy(self, name, images):
        # copy images into ComfyUI/input
        for view, path in images.items():
            target = COMFY_INPUT / f"{view}.png"
            shutil.copy(path, target)

        # load workflow
        with open(WORKFLOW_JSON, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        # update image nodes
        workflow["56"]["inputs"]["image"] = "front.png"
        workflow["85"]["inputs"]["image"] = "left.png"
        workflow["87"]["inputs"]["image"] = "right.png"
        workflow["82"]["inputs"]["image"] = "back.png"

        # output name
        workflow["67"]["inputs"]["filename_prefix"] = f"{OUTPUT_FOLDER}/{name}"

        # send to ComfyUI
        r = requests.post(COMFY_API, json={"prompt": workflow})
        r.raise_for_status()

        print(f"Started ComfyUI job for {name}")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    OBJECT_OUT.mkdir(parents=True, exist_ok=True)

    # start robocopy sync thread
    sync_thread = threading.Thread(
        target=robocopy_sync_loop,
        args=(10,),
        daemon=True
    )
    sync_thread.start()

    observer = Observer()
    observer.schedule(NewFolderHandler(), str(WATCH_DIR), recursive=False)
    observer.start()

    print(f"Watching {WATCH_DIR}")
    print(f"Syncing files between {COMFY_OUTPUT} and {OBJECT_OUT}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()