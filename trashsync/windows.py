import paramiko
from pathlib import Path
import os
import time
import stat  # <--- needed for S_ISDIR

# Raspberry Pi SSH info
REMOTE_HOST = "10.12.194.1"
REMOTE_PORT = 22
USERNAME = "trash"
PASSWORD = "trash"
REMOTE_DIR = "/home/trash/trash_imgs/"  # folder containing subfolders like object_1, object_2

# Local folder
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOCAL_DIR = BASE_DIR / "image_in"
os.makedirs(LOCAL_DIR, exist_ok=True)

POLL_INTERVAL = 10  # seconds

def sync_remote_dir(sftp, remote_path, local_path):
    """
    Recursively copy remote directory to local path,
    preserving subfolder structure, skipping existing files,
    and preserving modification times.
    """
    os.makedirs(local_path, exist_ok=True)

    for entry in sftp.listdir_attr(remote_path):
        remote_entry = remote_path.rstrip("/") + "/" + entry.filename
        local_entry = local_path / entry.filename

        if stat.S_ISDIR(entry.st_mode):  # <-- use stat.S_ISDIR
            # It's a directory → recurse into it
            sync_remote_dir(sftp, remote_entry, local_entry)
        else:
            # It's a file → copy only if it doesn't exist
            if not local_entry.exists():
                sftp.get(remote_entry, str(local_entry))
                # Preserve modification time
                mtime = entry.st_mtime
                os.utime(local_entry, (mtime, mtime))
                print(f"Copied {remote_entry} → {local_entry}")

def sync_images():
    try:
        transport = paramiko.Transport((REMOTE_HOST, REMOTE_PORT))
        transport.connect(username=USERNAME, password=PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)

        sync_remote_dir(sftp, REMOTE_DIR, LOCAL_DIR)

        sftp.close()
        transport.close()
    except Exception as e:
        print("Error syncing:", e)

def main():
    print("Starting SSH-based periodic sync...")
    try:
        while True:
            sync_images()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("Stopping sync.")

if __name__ == "__main__":
    main()
