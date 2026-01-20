from flask import Flask, render_template, jsonify, send_file
from flask_cors import CORS
from pathlib import Path
import json
from datetime import datetime
import shutil

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

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
        dst_path = OBJECTS_FOLDER / f"{obj_id}.glb"

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
    glb_files = {file.stem: file for file in SCANS_FOLDER.glob("*.glb")}

    # Sync GLBs to web folder
    sync_objects_folder(glb_files)

    updated = False

    # Add new objects
    for obj_id, glb_path in glb_files.items():
        if obj_id not in metadata:
            metadata[obj_id] = {
                "id": obj_id,
                "name": obj_id,
                "added": datetime.now().isoformat(),
                "type": "glb",
                "path": f"/objects/{obj_id}.glb",
                "size": glb_path.stat().st_size,
            }
            updated = True

    # Remove deleted objects
    removed = [obj for obj in metadata if obj not in glb_files]
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


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)