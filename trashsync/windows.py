import wexpect
import time
from pathlib import Path
import os

REMOTE_USER = "trash"
REMOTE_HOST = "10.12.194.1"
REMOTE_DIR = "/home/trash/trash_imgs/"
LOCAL_DIR = Path(__file__).resolve().parent.parent / "image_in"
POLL_INTERVAL = 10  # seconds
SSH_PASSWORD = "trash"  # yes, still hard-coded

os.makedirs(LOCAL_DIR, exist_ok=True)

def sync_images():
    rsync_cmd = f'rsync -avz --ignore-existing {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_DIR} "{LOCAL_DIR}"'
    try:
        child = wexpect.spawn(rsync_cmd)
        child.expect("assword:")  # expect the password prompt
        child.sendline(SSH_PASSWORD)
        child.expect(wexpect.EOF)
        print("Synced images.")
    except Exception as e:
        print("Error running rsync:", e)


def main():
    print("Starting periodic rsync sync...")
    try:
        while True:
            sync_images()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("Stopping sync.")


if __name__ == "__main__":
    main()
