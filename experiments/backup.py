"""
Zip .logs/ into backups/logs_YYYYMMDD_HHMM.zip. Callable as a script, or
import backup_logs() to call it from a runner after a batch finishes.
"""

import glob
import os
import zipfile
from datetime import datetime

LOGS_DIR = ".logs"
BACKUP_DIR = "backups"


def backup_logs(logs_dir=LOGS_DIR, backup_dir=BACKUP_DIR):
    if not os.path.isdir(logs_dir):
        print(f"{logs_dir} does not exist, nothing to back up.")
        return None

    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    zip_path = os.path.join(backup_dir, f"logs_{stamp}.zip")

    game_state_files = glob.glob(
        os.path.join(logs_dir, "**", "game_state.json"), recursive=True
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(logs_dir):
            for name in files:
                full_path = os.path.join(root, name)
                arcname = os.path.relpath(full_path, os.path.dirname(logs_dir))
                zf.write(full_path, arcname)

    size_bytes = os.path.getsize(zip_path)
    size_mb = size_bytes / (1024 * 1024)
    print(
        f"Backed up {logs_dir} -> {zip_path} "
        f"({size_mb:.2f} MB, {len(game_state_files)} games)"
    )
    return zip_path


if __name__ == "__main__":
    backup_logs()
