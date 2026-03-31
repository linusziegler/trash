# script triggers ComfyUI workflow when a new folder with 4 input images is added to WATCH_DIR
# and periodically syncs COMFY_OUTPUT -> OBJECT_OUT using robocopy (every 10 seconds)
# CHANGE COMFY_ROOT to your ComfyUI installation path !!!!!!!

import json
import time
import requests
import subprocess
import threading
import numpy as np
import torch
import cv2
from pathlib import Path
from PIL import Image
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from sam2.build_sam import build_sam2_hf
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

WORKFLOW_JSON = Path("3d_hunyuan3d_multiview_to_model_turbo.json")
COMFY_API = "http://127.0.0.1:8000/prompt"

SAM2_HF_MODEL_ID = "facebook/sam2-hiera-small"

_SAM2_PREDICTOR = None
_SAM2_MODEL = None
ALPHA_THRESHOLD = 64

# Background subtraction config (negative mask before SAM2)
BACKGROUND_REFERENCE_IMAGE = WATCH_DIR / "background_reference.png"
NEG_MASK_THRESHOLD = 20
NEG_MASK_BLUR = 5
USE_SAM2 = True

# Debug windows
DEBUG_MASK_WINDOWS = True
DEBUG_WAIT_MS = 1

# -----------------------------------------------------------------------------
# View mapping
# -----------------------------------------------------------------------------

SUFFIX_MAP = {
    "front": "front",
    "left": "left",
    "right": "right",
    "back": "back",
}


def get_sam2_device():
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def get_sam2_predictor():
    global _SAM2_PREDICTOR, _SAM2_MODEL

    if _SAM2_PREDICTOR is not None:
        return _SAM2_PREDICTOR

    device = get_sam2_device()
    _SAM2_MODEL = build_sam2_hf(SAM2_HF_MODEL_ID, device=device)
    _SAM2_PREDICTOR = SAM2ImagePredictor(_SAM2_MODEL)
    print(f"SAM2 loaded from Hugging Face model: {SAM2_HF_MODEL_ID}")
    print(f"SAM2 initialized on device: {device}")
    return _SAM2_PREDICTOR


def load_background_reference_for_shape(shape_hw):
    if not BACKGROUND_REFERENCE_IMAGE.exists():
        print(f"[MASK] Warning: reference image not found at {BACKGROUND_REFERENCE_IMAGE}")
        return None

    ref_bgr = cv2.imread(str(BACKGROUND_REFERENCE_IMAGE), cv2.IMREAD_COLOR)
    if ref_bgr is None:
        print(f"[MASK] Warning: failed to load reference image {BACKGROUND_REFERENCE_IMAGE}")
        return None

    h, w = shape_hw
    if ref_bgr.shape[:2] != (h, w):
        ref_bgr = cv2.resize(ref_bgr, (w, h), interpolation=cv2.INTER_AREA)

    return cv2.cvtColor(ref_bgr, cv2.COLOR_BGR2RGB)


def create_negative_mask_from_reference(image_np):
    h, w = image_np.shape[:2]
    ref_rgb = load_background_reference_for_shape((h, w))

    if ref_rgb is None:
        return np.ones((h, w), dtype=bool)

    diff = cv2.absdiff(image_np, ref_rgb)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)

    blur_ksize = NEG_MASK_BLUR if NEG_MASK_BLUR % 2 == 1 else NEG_MASK_BLUR + 1
    diff_gray = cv2.GaussianBlur(diff_gray, (blur_ksize, blur_ksize), 0)

    _, fg_mask_u8 = cv2.threshold(diff_gray, NEG_MASK_THRESHOLD, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg_mask_u8 = cv2.morphologyEx(fg_mask_u8, cv2.MORPH_OPEN, kernel, iterations=1)
    fg_mask_u8 = cv2.morphologyEx(fg_mask_u8, cv2.MORPH_CLOSE, kernel, iterations=2)

    return fg_mask_u8 > 0


def show_mask_debug_views(source_path, image_np, negative_mask, final_mask):
    if not DEBUG_MASK_WINDOWS:
        return

    negative_masked = image_np.copy()
    negative_masked[~negative_mask] = 0

    cv2.imshow(
        "debug_original",
        cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR),
    )
    cv2.imshow(
        "debug_negative_masked",
        cv2.cvtColor(negative_masked, cv2.COLOR_RGB2BGR),
    )
    cv2.imshow(
        "debug_final_mask",
        (final_mask.astype(np.uint8) * 255),
    )
    cv2.waitKey(DEBUG_WAIT_MS)


def create_center_object_mask(image_np, predictor):
    h, w = image_np.shape[:2]
    cx, cy = w // 2, h // 2
    img_area = float(h * w)

    margin = max(10, min(h, w) // 16)
    pos_points = np.array([[cx, cy]], dtype=np.float32)
    neg_points = np.array(
        [
            [margin, margin],
            [w - margin - 1, margin],
            [margin, h - margin - 1],
            [w - margin - 1, h - margin - 1],
        ],
        dtype=np.float32,
    )

    point_coords = np.vstack([pos_points, neg_points])
    point_labels = np.array([1, 0, 0, 0, 0], dtype=np.int32)

    predictor.set_image(image_np)
    masks, scores, _ = predictor.predict(
        point_coords=point_coords,
        point_labels=point_labels,
        multimask_output=True,
    )

    masks_bool = masks > 0
    areas = masks_bool.reshape(masks_bool.shape[0], -1).sum(axis=1)
    contains_center = masks_bool[:, cy, cx]

    candidate_idxs = np.where(contains_center)[0]
    if candidate_idxs.size > 0:
        best_idx = int(candidate_idxs[np.argmax(areas[candidate_idxs])])
    else:
        best_idx = int(np.argmax(areas))

    best_mask = masks_bool[best_idx]
    best_area_ratio = float(areas[best_idx]) / img_area

    # Fallback: if the selected mask is unrealistically small, use a centered box prompt.
    if best_area_ratio < 0.02:
        x0, y0 = int(w * 0.15), int(h * 0.15)
        x1, y1 = int(w * 0.85), int(h * 0.85)

        box_masks, box_scores, _ = predictor.predict(
            box=np.array([x0, y0, x1, y1], dtype=np.float32),
            point_coords=pos_points,
            point_labels=np.array([1], dtype=np.int32),
            multimask_output=True,
        )

        box_masks_bool = box_masks > 0
        box_areas = box_masks_bool.reshape(box_masks_bool.shape[0], -1).sum(axis=1)

        # Prefer larger masks, but still use score as tie-breaker.
        box_rank = box_areas.astype(np.float32) + (box_scores * 1e-3)
        best_box_idx = int(np.argmax(box_rank))
        best_mask = box_masks_bool[best_box_idx]

    return best_mask


def refine_mask(mask):
    h, w = mask.shape
    cy, cx = h // 2, w // 2

    mask_u8 = (mask.astype(np.uint8) * 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    bridge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    # Smooth small jaggies and remove isolated speckles.
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel, iterations=1)

    # Break thin accidental connections before picking the main component.
    cc_seed = cv2.erode(mask_u8, bridge_kernel, iterations=1)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cc_seed, connectivity=8)

    if num_labels <= 1:
        return mask_u8 > 0

    # Prefer the component touching center if it is substantial; otherwise keep largest.
    center_label = int(labels[cy, cx])
    center_area = int(stats[center_label, cv2.CC_STAT_AREA]) if center_label > 0 else 0
    min_center_area = int(0.005 * h * w)

    if center_label > 0 and center_area >= min_center_area:
        keep_label = center_label
    else:
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep_label = int(np.argmax(areas)) + 1

    seed_component = (labels == keep_label).astype(np.uint8) * 255
    restored_component = cv2.dilate(seed_component, bridge_kernel, iterations=1)
    refined = cv2.bitwise_and(mask_u8, restored_component)

    # Fill tiny holes inside the kept object.
    refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Fill enclosed holes so the object stays solid.
    flood = refined.copy()
    ff_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    cv2.floodFill(flood, ff_mask, seedPoint=(0, 0), newVal=255)
    holes = cv2.bitwise_not(flood)
    refined = cv2.bitwise_or(refined, holes)

    return refined > 0


def segment_center_object_to_black_bg(source_path, target_path):
    img = Image.open(source_path)
    alpha_np = None

    if "A" in img.getbands():
        rgba = img.convert("RGBA")
        alpha_np = np.array(rgba.getchannel("A"))
        image_np = np.array(rgba.convert("RGB"))
    else:
        image_np = np.array(img.convert("RGB"))

    negative_mask = create_negative_mask_from_reference(image_np)

    sam2_input = image_np.copy()
    sam2_input[~negative_mask] = 0

    if USE_SAM2:
        predictor = get_sam2_predictor()
        with torch.inference_mode():
            mask = create_center_object_mask(sam2_input, predictor)
        mask = refine_mask(mask)
        mask = mask & negative_mask
    else:
        mask = negative_mask

    # Enforce original alpha as hard background if present.
    if alpha_np is not None:
        mask = mask & (alpha_np >= ALPHA_THRESHOLD)

    masked = image_np.copy()
    masked[~mask] = 0

    show_mask_debug_views(source_path, image_np, negative_mask, mask)

    Image.fromarray(masked).save(target_path, format="PNG")

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

        folder = Path(str(event.src_path))
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
        # segment and write images into ComfyUI/input
        for view, path in images.items():
            target = COMFY_INPUT / f"{view}.png"
            segment_center_object_to_black_bg(path, target)

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