import json
import time
import shutil
import requests
import subprocess
import threading
import numpy as np
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PIL import Image
import torch
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
print(f"Specified Base directory: {BASE_DIR}")

WATCH_DIR = BASE_DIR / "image_in"

COMFY_ROOT = Path("C:/Users/duraX/Documents/ComfyUI")  # <-- CHANGE THIS
print(f"Specified ComfyUI root: {COMFY_ROOT}")

COMFY_INPUT = COMFY_ROOT / "input"
OUTPUT_FOLDER = "trashscans"
COMFY_OUTPUT = COMFY_ROOT / "output" / OUTPUT_FOLDER
OBJECT_OUT = BASE_DIR / "object_out"

WORKFLOW_JSON = Path("3d_hunyuan3d_multiview_to_model_turbo.json")
COMFY_API = "http://127.0.0.1:8000/prompt"

SUFFIX_MAP = {
    "front": "front",
    "left": "left",
    "right": "right",
    "back": "back",
}

# -----------------------------------------------------------------------------
# SAM2 Initialization
# -----------------------------------------------------------------------------

sam2_model = None
sam2_predictor = None

def initialize_sam2():
    global sam2_model, sam2_predictor

    if sam2_model is not None:
        return

    print("Initializing SAM2 model...")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    sam2_model = build_sam2(
        config_file="sam2_hiera_b+.yaml",
        ckpt_path=None,
        device=device
    )

    sam2_predictor = SAM2ImagePredictor(sam2_model)
    print("SAM2 model initialized successfully")

# -----------------------------------------------------------------------------
# SAM2 Processing (HIGHEST SCORE)
# -----------------------------------------------------------------------------

def process_image_with_sam2(image_path, output_path):
    global sam2_predictor

    try:
        print(f"Processing {image_path.name} with SAM2...")

        image = Image.open(image_path).convert("RGB")
        image_np = np.array(image)

        # Set image (correct SAM2 API)
        sam2_predictor.set_image(image_np)

        # Center point prompt
        h, w = image_np.shape[:2]
        point_coords = np.array([[w // 2, h // 2]])
        point_labels = np.array([1])

        masks, scores, logits = sam2_predictor.predict(
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=True,
        )

        if masks is None or len(masks) == 0:
            print(f"No mask detected, fallback copy: {image_path.name}")
            shutil.copy(image_path, output_path)
            return

        # ✅ HIGHEST SCORE SELECTION
        best_mask_idx = int(np.argmax(scores))
        mask = masks[best_mask_idx]

        # Apply mask directly to RGB image (black background)
        masked_np = image_np.copy()

        # Zero out background
        masked_np[mask == 0] = 0

        # Convert back to image
        masked_image = Image.fromarray(masked_np)

        masked_image.save(output_path, "PNG")
        print(f"Saved masked image: {output_path.name}")

    except Exception as e:
        print(f"Error processing {image_path.name}: {e}")
        shutil.copy(image_path, output_path)

# -----------------------------------------------------------------------------
# Robocopy sync
# -----------------------------------------------------------------------------

def run_robocopy_once():
    cmd = [
        "robocopy",
        str(COMFY_OUTPUT),
        str(OBJECT_OUT),
        "/E",
        "/R:0",
        "/W:0",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)

def robocopy_sync_loop(interval):
    COMFY_OUTPUT.mkdir(parents=True, exist_ok=True)
    OBJECT_OUT.mkdir(parents=True, exist_ok=True)

    print(f"Robocopy sync started ({interval}s)")

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

        max_wait = 20
        retry_interval = 2
        elapsed = 0

        time.sleep(1)

        while elapsed < max_wait:
            images = {}

            for img in folder.iterdir():
                if not img.is_file():
                    continue

                for suffix in SUFFIX_MAP:
                    if img.stem.endswith(suffix):
                        images[suffix] = img

            if len(images) == 4:
                print(f"Found all 4 views for {folder.name}")
                self.run_comfy(folder.name, images)
                return

            print(f"{folder.name}: {len(images)}/4 images found...")
            elapsed += retry_interval
            time.sleep(retry_interval)

        print(f"Timeout waiting for images in {folder.name}")

    def run_comfy(self, name, images):
        initialize_sam2()

        processed_images = {}

        for view, path in images.items():
            masked_path = path.parent / f"{path.stem}_masked.png"
            process_image_with_sam2(path, masked_path)
            processed_images[view] = masked_path

        for view, path in processed_images.items():
            shutil.copy(path, COMFY_INPUT / f"{view}.png")

        with open(WORKFLOW_JSON, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        workflow["56"]["inputs"]["image"] = "front.png"
        workflow["85"]["inputs"]["image"] = "left.png"
        workflow["87"]["inputs"]["image"] = "right.png"
        workflow["82"]["inputs"]["image"] = "back.png"

        workflow["67"]["inputs"]["filename_prefix"] = f"{OUTPUT_FOLDER}/{name}"

        for node in workflow.values():
            node.pop("_meta", None)

        r = requests.post(
            COMFY_API,
            json={"prompt": workflow, "client_id": "watchdog-script"}
        )

        if not r.ok:
            print("COMFY ERROR:", r.text)

        r.raise_for_status()
        print(f"Started ComfyUI job: {name}")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    OBJECT_OUT.mkdir(parents=True, exist_ok=True)

    threading.Thread(
        target=robocopy_sync_loop,
        args=(2,),
        daemon=True
    ).start()

    observer = Observer()
    observer.schedule(NewFolderHandler(), str(WATCH_DIR), recursive=False)
    observer.start()

    print(f"Watching {WATCH_DIR}")
    print(f"Syncing {COMFY_OUTPUT} -> {OBJECT_OUT}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()