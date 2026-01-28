import paramiko
from pathlib import Path
import os
import time

# Raspberry Pi SSH info
REMOTE_HOST = "10.12.194.1"
REMOTE_PORT = 22
USERNAME = "trash"
PASSWORD = "trash"
REMOTE_DIR = "/home/trash/trash_imgs/"

# Local folder
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOCAL_DIR = BASE_DIR / "image_in"
os.makedirs(LOCAL_DIR, exist_ok=True)

POLL_INTERVAL = 10  # seconds

def sync_images():
    try:
        transport = paramiko.Transport((REMOTE_HOST, REMOTE_PORT))
        transport.connect(username=USERNAME, password=PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)

        for remote_file in sftp.listdir_attr(REMOTE_DIR):
            remote_path = REMOTE_DIR + remote_file.filename
            local_path = LOCAL_DIR / remote_file.filename

            if not local_path.exists():  # copy only new files
                sftp.get(remote_path, str(local_path))
                print(f"Copied {remote_file.filename}")

        sftp.close()
        transport.close()
    except Exception as e:
        print("Error syncing images:", e)

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
