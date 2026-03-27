# script triggers ComfyUI workflow when a new folder with 4 input images is added to WATCH_DIR
# Processes images with SAM2 to mask salient objects before sending to ComfyUI
# and periodically syncs COMFY_OUTPUT -> OBJECT_OUT using robocopy (every 10 seconds)
# CHANGE COMFY_ROOT to your ComfyUI installation path !!!!!!!

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

WORKFLOW_JSON = Path("3d_hunyuan3d_multiview_to_model_turbo_sam2.json")
COMFY_API = "http://127.0.0.1:8000/prompt"

# -----------------------------------------------------------------------------
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
    """Initialize SAM2 model for image segmentation."""
    global sam2_model, sam2_predictor
    
    if sam2_model is not None:
        return
    
    print("Initializing SAM2 model...")
    try:
        # Use cuda if available, otherwise cpu
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {device}")
        
        # Build SAM2 model
        sam2_model = build_sam2(
            config_file="sam2_hiera_b.yaml",
            ckpt_path=None,  # Will download automatically
            device=device
        )
        sam2_predictor = SAM2ImagePredictor(sam2_model)
        print("SAM2 model initialized successfully")
    except Exception as e:
        print(f"Error initializing SAM2: {e}")
        raise

def process_image_with_sam2(image_path, output_path):
    """
    Process an image with SAM2 to mask salient objects.
    Segments the image and saves with alpha channel (transparent background).
    
    Args:
        image_path: Path to input image
        output_path: Path to save masked image
    """
    global sam2_predictor
    
    try:
        print(f"Processing {image_path.name} with SAM2...")
        
        # Load image
        image = Image.open(image_path).convert("RGB")
        image_np = np.array(image)
        
        # Set image for SAM2
        sam2_predictor.set_image_size((image_np.shape[1], image_np.shape[0]))
        sam2_predictor.set_image(image_np)
        
        # Get automatic mask generation (finds all objects)
        masks, scores, logits = sam2_predictor.predict(
            point_coords=None,
            point_labels=None,
            box=None,
            multimask_output=False,
            return_logits=False,
        )
        
        if masks is None or len(masks) == 0:
            print(f"No objects detected in {image_path.name}, using original image")
            shutil.copy(image_path, output_path)
            return
        
        # Use the mask with highest confidence score
        best_mask_idx = np.argmax(scores)
        mask = masks[best_mask_idx]
        
        # Create RGBA image with the mask as alpha channel
        image_rgba = Image.new("RGBA", image.size)
        image_rgba.paste(image, (0, 0))
        
        # Create alpha channel from mask
        alpha = Image.fromarray((mask * 255).astype(np.uint8))
        image_rgba.putalpha(alpha)
        
        # Save masked image
        image_rgba.save(output_path, "PNG")
        print(f"Masked image saved to {output_path.name}")
        
    except Exception as e:
        print(f"Error processing {image_path.name}: {e}")
        # Fall back to copying original image
        shutil.copy(image_path, output_path)

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


def robocopy_sync_loop(interval):
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

        # keep retrying until all 4 views are found or timeout
        max_wait = 20  # seconds
        retry_interval = 2  # seconds
        elapsed = 0
        
        # wait briefly for files to finish copying
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

            print(f"Found {len(images)}/4 views for {folder.name}, retrying...")
            elapsed += retry_interval
            time.sleep(retry_interval)

        print(f"Timeout: {folder.name} still missing views after {max_wait}s")

    def run_comfy(self, name, images):
        # Initialize SAM2 if not already done
        initialize_sam2()
        
        # Process images with SAM2 to mask salient objects
        processed_images = {}
        for view, path in images.items():
            # Create temporary output for masked image
            masked_image_path = path.parent / f"{path.stem}_masked.png"
            process_image_with_sam2(path, masked_image_path)
            processed_images[view] = masked_image_path
        
        # Copy processed images into ComfyUI/input
        for view, path in processed_images.items():
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

        for node in workflow.values():
            node.pop("_meta", None)

        r = requests.post(
            COMFY_API,
            json={
                "prompt": workflow,
                "client_id": "watchdog-script"
            }
        )

        if not r.ok:
            print("COMFY ERROR:")
            print(r.text)

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
        args=(2,),
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