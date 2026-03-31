from flask import Flask, render_template, jsonify, send_file
from flask_cors import CORS
from pathlib import Path
import json
from datetime import datetime
import shutil
import queue
import os
from pynput import keyboard

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# -------------------------------------------------------------------
# Global keyboard input (system-wide)
# -------------------------------------------------------------------

input_queue = queue.Queue()
keyboard_listener = None


def on_key_press(key):
    """Capture system-wide key presses and enqueue normalized key values."""
    try:
        if key == keyboard.Key.up:
            input_queue.put("ArrowUp")
        elif key == keyboard.Key.down:
            input_queue.put("ArrowDown")
        elif key == keyboard.Key.left:
            input_queue.put("ArrowLeft")
        elif key == keyboard.Key.right:
            input_queue.put("ArrowRight")
        elif key == keyboard.Key.space:
            input_queue.put(" ")
        elif hasattr(key, "char") and key.char:
            input_queue.put(key.char.lower())
    except Exception:
        # Ignore unsupported/special keys.
        pass


def start_keyboard_listener():
    global keyboard_listener

    if keyboard_listener is not None:
        return

    keyboard_listener = keyboard.Listener(on_press=on_key_press)
    keyboard_listener.daemon = True
    keyboard_listener.start()
    print("[INPUT] Global keyboard listener started")

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------

# Directory of this script (trashsite3D/)
SCRIPT_DIR = Path(__file__).resolve().parent

# Project root (one level above script dir)
BASE_DIR = SCRIPT_DIR.parent
print(f"Base directory: {BASE_DIR}")

# Source folder where GLBs are produced
SCANS_FOLDER = BASE_DIR / "object_out"

# Web-accessible folder (next to app.py)
OBJECTS_FOLDER = SCRIPT_DIR / "objects"

# Metadata now lives in objects/
METADATA_FILE = OBJECTS_FOLDER / "object_metadata.json"


# -------------------------------------------------------------------
# Initialization
# -------------------------------------------------------------------

def init_metadata():
    SCANS_FOLDER.mkdir(parents=True, exist_ok=True)
    OBJECTS_FOLDER.mkdir(parents=True, exist_ok=True)

    if not METADATA_FILE.exists():
        METADATA_FILE.write_text("{}")
        return

    if METADATA_FILE.stat().st_size == 0:
        METADATA_FILE.write_text("{}")


# -------------------------------------------------------------------
# File sync
# -------------------------------------------------------------------

def sync_objects_folder(glb_files: dict[str, Path]):
    """
    Copy GLB files from object_out -> ./objects
    Only copy when missing or updated
    """
    for obj_id, src_path in glb_files.items():
        dst_path = OBJECTS_FOLDER / f"{obj_id.removesuffix("_00001_")}.glb"

        if (
            not dst_path.exists()
            or src_path.stat().st_mtime > dst_path.stat().st_mtime
        ):
            shutil.copy2(src_path, dst_path)


# -------------------------------------------------------------------
# Metadata handling
# -------------------------------------------------------------------

def get_object_metadata():
    init_metadata()

    # Load metadata safely
    try:
        with open(METADATA_FILE, "r") as f:
            metadata = json.load(f)
    except json.JSONDecodeError:
        metadata = {}
        METADATA_FILE.write_text("{}")

    # Scan for GLB files in source folder
    glb_files = {file.stem.removesuffix("_00001_") : file for file in SCANS_FOLDER.glob("*.glb")}

    # Sync GLBs to web folder
    sync_objects_folder(glb_files)

    updated = False

    # Add new objects
    for idx, (obj_id, glb_path) in enumerate(sorted(glb_files.items(),)):
        if obj_id not in metadata:
            metadata[obj_id] = {
                "id": obj_id,
                "name": obj_id,
                "added": glb_path.stat().st_birthtime,
                "type": "glb",
                "path": f"/objects/{obj_id}.glb",
                "size": glb_path.stat().st_size,
                "status": "ready",
            }
            updated = True
        else:
            # Update status to ready if GLB now exists
            if metadata[obj_id].get("status") != "ready":
                metadata[obj_id]["status"] = "ready"
                updated = True

    # Remove deleted objects (but keep those still loading)
    removed = [obj for obj in metadata if obj not in glb_files and metadata[obj].get("status") != "loading"]
    for obj in removed:
        del metadata[obj]
        updated = True

    if updated:
        with open(METADATA_FILE, "w") as f:
            json.dump(metadata, f, indent=2)

    return metadata


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/objects")
def get_objects():
    metadata = get_object_metadata()
    return jsonify(list(metadata.values()))


@app.route("/api/objects/<object_id>")
def get_object(object_id):
    metadata = get_object_metadata()
    if object_id in metadata:
        return jsonify(metadata[object_id])
    return jsonify({"error": "Object not found"}), 404


@app.route("/objects/<object_id>.glb")
def get_glb_model(object_id):
    glb_path = OBJECTS_FOLDER / f"{object_id}.glb"
    if glb_path.exists():
        return send_file(glb_path, mimetype="model/gltf-binary")
    return jsonify({"error": "GLB file not found"}), 404


@app.route("/api/notify-loading", methods=["POST"])
def notify_loading():
    """Webhook called by trash3Dgen when a new folder is detected"""
    from flask import request
    
    try:
        data = request.get_json()
        object_id = data.get("object_id")
        
        if not object_id:
            return jsonify({"error": "Missing object_id"}), 400
        
        init_metadata()
        
        # Load current metadata
        try:
            with open(METADATA_FILE, "r") as f:
                metadata = json.load(f)
        except json.JSONDecodeError:
            metadata = {}
        
        # Create loading entry if it doesn't exist
        if object_id not in metadata:
            metadata[object_id] = {
                "id": object_id,
                "name": object_id,
                "added": datetime.now().isoformat(),
                "type": "glb",
                "path": f"/objects/{object_id}.glb",
                "status": "loading",
            }
            
            with open(METADATA_FILE, "w") as f:
                json.dump(metadata, f, indent=2)
            
            print(f"Created loading entry for {object_id}")
            return jsonify({"status": "created", "object_id": object_id}), 201
        else:
            # Entry already exists, just ensure status is loading if not ready
            if metadata[object_id].get("status") != "ready":
                metadata[object_id]["status"] = "loading"
                with open(METADATA_FILE, "w") as f:
                    json.dump(metadata, f, indent=2)
            
            return jsonify({"status": "exists", "object_id": object_id}), 200
    
    except Exception as e:
        print(f"Error in notify_loading: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/input/next-key")
def get_next_key():
    """Return one queued global key press (if available)."""
    try:
        key = input_queue.get_nowait()
        return jsonify({"key": key})
    except queue.Empty:
        return jsonify({"key": None})


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Start listener in the serving process only (avoids debug reloader duplicates).
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_keyboard_listener()
    app.run(debug=True, port=5000)
