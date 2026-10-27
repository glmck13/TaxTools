#!/usr/bin/env python3

import os
import sys
import json
import stat
import tempfile
import requests
from datetime import datetime

# ==============================================================================
# CONFIGURATION & PATH SETUP
# ==============================================================================
DOCUMENT_ROOT = os.environ.get("DOCUMENT_ROOT", "/var/www/tarrantadvisors")
PIPELINE_SANDBOX = os.environ.get("PIPELINE_SANDBOX")

if PIPELINE_SANDBOX:
    ENGAGEMENTS_DIR = os.path.join(DOCUMENT_ROOT, "sandbox")
else:
    ENGAGEMENTS_DIR = os.path.join(DOCUMENT_ROOT, "engagements")

ADOBE_APIBASE = os.environ.get("ADOBE_APIBASE", "")
ADOBE_TOKEN = os.environ.get("ADOBE_ACCESS_TOKEN", "")

# Standard status strings that denote an executed agreement in Adobe Sign
COMPLETED_STATUSES = {"SIGNED", "COMPLETED", "APPROVED", "DELIVERED", "ACCEPTED"}
TERMINAL_CANCELLED_STATUSES = {"CANCELLED", "REJECTED", "DECLINED", "EXPIRED"}


def log(msg):
    """Timestamped log messages to stdout for cron logging."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")


def check_adobe_status(agreement_id):
    """Queries Adobe Sign API for the current status of an agreement."""
    url = f"{ADOBE_APIBASE}/agreements/{agreement_id}"
    headers = {
        "Authorization": f"Bearer {ADOBE_TOKEN}",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "").upper()

            # Extract completion date/time with fallbacks
            completed_at = (
                data.get("completedAt") 
                or data.get("displayDate") 
                or datetime.now().isoformat()
            )

            return status, completed_at
        else:
            log(f"⚠️ Adobe API returned HTTP {resp.status_code} for agreement {agreement_id}")
            return None, None
    except Exception as e:
        log(f"❌ Error connecting to Adobe Sign API for {agreement_id}: {str(e)}")
        return None, None


def update_json_file(filepath, completed_at):
    """Safely unlocks, updates JSON atomically, and restores original permissions."""
    file_stat = os.stat(filepath)
    orig_mode = file_stat.st_mode
    dir_name = os.path.dirname(filepath)

    try:
        # 1. Grant temporary write permission (chmod u+w)
        os.chmod(filepath, orig_mode | stat.S_IWUSR)

        # 2. Read existing JSON content
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 3. Update completion timestamp and lock state
        data["adobe_completed_at"] = completed_at

        # 4. Atomic Write: Write to temporary file in the same directory
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            temp_path = tf.name
            json.dump(data, tf, indent=2)

        # 5. Atomic Replace
        os.replace(temp_path, filepath)

        log(f"  ✓ Updated {os.path.basename(filepath)} with adobe_completed_at='{completed_at}'")

    except Exception as e:
        log(f"  ❌ Failed updating {os.path.basename(filepath)}: {str(e)}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
    finally:
        # 6. Restore original file permissions
        os.chmod(filepath, orig_mode)


def main():
    if not ADOBE_APIBASE or not ADOBE_TOKEN:
        log("ERROR: ADOBE_APIBASE or ADOBE_ACCESS_TOKEN environment variables not set.")
        sys.exit(1)

    if not os.path.exists(ENGAGEMENTS_DIR):
        log(f"ERROR: Directory '{ENGAGEMENTS_DIR}' does not exist.")
        sys.exit(1)

    log(f"Starting Adobe signature sync scan in: {ENGAGEMENTS_DIR}")

    scanned_count = 0
    updated_count = 0

    for filename in sorted(os.listdir(ENGAGEMENTS_DIR)):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(ENGAGEMENTS_DIR, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                draft = json.load(f)
        except Exception as e:
            log(f"Skipping {filename}: Unable to parse JSON ({str(e)})")
            continue

        agr_id = draft.get("adobe_agreement_id")
        completed_at = draft.get("adobe_completed_at")

        # TARGET CONDITION: Has an agreement ID, but NOT yet marked completed
        if agr_id and not completed_at:
            scanned_count += 1
            log(f"Checking status for {filename} (Agreement ID: {agr_id})...")

            status, adobe_completed_time = check_adobe_status(agr_id)

            if status in COMPLETED_STATUSES:
                log(f"  🎉 Document {filename} is SIGNED! (Status: {status})")
                update_json_file(filepath, f"+{adobe_completed_time}")
                updated_count += 1
            elif status in TERMINAL_CANCELLED_STATUSES:
                log(f"  🛑 Document {filename} was {status}.")
                update_json_file(filepath, f"!{adobe_completed_time}")
                updated_count += 1
            else:
                log(f"  ⏳ Document {filename} status is '{status}'. No update needed.")

    log(f"Sync complete. Scanned: {scanned_count} pending file(s) | Updated: {updated_count} file(s).\n")


if __name__ == "__main__":
    main()
