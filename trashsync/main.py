import subprocess
import time
import os

REMOTE_USER = "trash"
REMOTE_HOST = "10.12.194.1"
REMOTE_DIR = "/home/trash/trash_imgs/" # <--- directory on raspberry pi 
LOCAL_DIR = "../image_in" # <--- directory on main machine
POLL_INTERVAL = 10  # seconds
SSH_PASSWORD = "trash"  # hard-coded password :-)


def sync_images():
    os.makedirs(LOCAL_DIR, exist_ok=True)

    cmd = [
        "sshpass",
        "-p",
        SSH_PASSWORD,
        "rsync",
        "-avz",
        "--ignore-existing",
        f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_DIR}",
        LOCAL_DIR
    ]

    try:
        subprocess.run(cmd, check=True)
        print("Synced images.")
    except subprocess.CalledProcessError as e:
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