# script triggers ComfyUI workflow when a new folder with 4 inputimages is added to WATCH_DIR

import json
import time
import shutil
import requests
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = Path("/absolute/path/to/watched_input")
COMFY_ROOT = Path("/absolute/path/to/ComfyUI")
COMFY_INPUT = COMFY_ROOT / "input"
WORKFLOW_JSON = Path("3d_hunyuan3d_multiview_to_model_turbo.json")
COMFY_API = "http://127.0.0.1:8000/prompt"

SUFFIX_MAP = {
    "front": "front",
    "left": "left",
    "right": "right",
    "back": "back",
}

class NewFolderHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            return

        folder = Path(event.src_path)
        print(f"New folder detected: {folder.name}")

        # wait for files to finish copying
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
        with open(WORKFLOW_JSON) as f:
            workflow = json.load(f)

        # update image nodes
        workflow["56"]["inputs"]["image"] = "front.png"
        workflow["85"]["inputs"]["image"] = "left.png"
        workflow["87"]["inputs"]["image"] = "right.png"
        workflow["82"]["inputs"]["image"] = "back.png"

        # output name
        workflow["67"]["inputs"]["filename_prefix"] = f"trashscans/{name}"

        # send to ComfyUI
        r = requests.post(COMFY_API, json={"prompt": workflow})
        r.raise_for_status()

        print(f"Started ComfyUI job for {name}")

if __name__ == "__main__":
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    observer = Observer()
    observer.schedule(NewFolderHandler(), str(WATCH_DIR), recursive=False)
    observer.start()

    print(f"Watching {WATCH_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()