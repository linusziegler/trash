import paramiko
from pathlib import Path
import os
import time
import stat

# Raspberry Pi SSH info
REMOTE_HOST = "10.12.194.1"
REMOTE_PORT = 22
USERNAME = "trash"
PASSWORD = "trash"
REMOTE_DIR = "/home/trash/trash_imgs/"  # contains subfolders like object_1, object_2

# Local folder
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOCAL_DIR = BASE_DIR / "image_in"
os.makedirs(LOCAL_DIR, exist_ok=True)

POLL_INTERVAL = 10  # seconds

def count_files(sftp, remote_path):
    """Count the number of files in a remote folder (ignores subfolders)."""
    return sum(1 for entry in sftp.listdir_attr(remote_path) if not stat.S_ISDIR(entry.st_mode))

def copy_folder(sftp, remote_path, local_path):
    """Copy all files in a remote folder to the local folder."""
    os.makedirs(local_path, exist_ok=True)
    for entry in sftp.listdir_attr(remote_path):
        if not stat.S_ISDIR(entry.st_mode):
            remote_file = remote_path.rstrip("/") + "/" + entry.filename
            local_file = local_path / entry.filename
            if not local_file.exists():
                sftp.get(remote_file, str(local_file))
                os.utime(local_file, (entry.st_mtime, entry.st_mtime))
                print(f"Copied {remote_file} → {local_file}")

def sync_images():
    try:
        transport = paramiko.Transport((REMOTE_HOST, REMOTE_PORT))
        transport.connect(username=USERNAME, password=PASSWORD)
        sftp : paramiko.SFTPClient = paramiko.SFTPClient.from_transport(transport)

        # Iterate over subfolders in REMOTE_DIR
        for entry in sftp.listdir_attr(REMOTE_DIR):
            remote_subfolder = REMOTE_DIR.rstrip("/") + "/" + entry.filename
            local_subfolder = LOCAL_DIR / entry.filename

            if stat.S_ISDIR(entry.st_mode):
                file_count = count_files(sftp, remote_subfolder)
                if file_count == 4:
                    copy_folder(sftp, remote_subfolder, local_subfolder)
                else:
                    print(f"Skipping {remote_subfolder}, contains {file_count} files")

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