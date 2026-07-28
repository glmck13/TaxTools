#!/usr/bin/env python3

import os
import subprocess
import extract_msg
import sys
import traceback
import uuid
import urllib.parse

def run_m365(command_list):
    """Executes M365 CLI using list-based arguments to bypass shell parsing."""
    full_cmd = ["m365"] + command_list + ["--output", "text"]

    # SANITY LOG: Show exactly what is being sent
    # This will appear in your OneDrive log file
    log.append(f"EXECUTE: {' '.join(full_cmd)}")

    # shell=False is the default and is CRITICAL here for quote safety
    result = subprocess.run(full_cmd, capture_output=True, text=True, shell=False)

    if result.returncode != 0:
        raise Exception(f"M365 CLI Error: {result.stderr}")
    return result.stdout

log = ["--- Sanity Check Processing Started ---"]

try:
    # 2. PARAMETER PARSING
    raw_qs = os.environ.get('QUERY_STRING', '')
    parsed_qs = urllib.parse.parse_qs(raw_qs)

    def get_val(key):
        val_list = parsed_qs.get(key, [None])
        val = val_list[0]
        # unquote_plus handles the %27 (apostrophe) and + (spaces)
        return urllib.parse.unquote_plus(val).strip() if val else None

    site_url = get_val("siteUrl")
    file_url = get_val("fileUrl")   
    folder_url = get_val("folderUrl")

    log.append(f"INPUT - Site: {site_url}")
    log.append(f"INPUT - File Path: {file_url}")
    log.append(f"INPUT - Folder Path: {folder_url}")

    if not all([site_url, file_url, folder_url]):
        raise Exception("Missing parameters. Check Power Automate URL construction.")

    # 3. WORKSPACE SETUP
    run_id = str(uuid.uuid4())
    work_dir = os.path.join("/tmp", f"msg_work_{run_id}")
    os.makedirs(work_dir, exist_ok=True)

    # Local disk only sees 'target.msg' - no special characters here
    local_msg_path = os.path.join(work_dir, "target.msg")
    extract_output_dir = os.path.join(work_dir, "extracted")
    os.makedirs(extract_output_dir, exist_ok=True)

    # 4. DOWNLOAD (The Quote Test)
    log.append("Step: Downloading .msg file...")
    run_m365([
        "spo", "file", "get", 
        "--webUrl", site_url, 
        "--url", file_url,      
        "--asFile",           
        "--path", local_msg_path 
    ])
    log.append("Download successful.")

    # 5. EXTRACTION
    msg = extract_msg.Message(local_msg_path)
    log.append(f"Email Subject: {msg.subject}")

    for attachment in msg.attachments:
        attachment.save(customPath=extract_output_dir)
        att_name = attachment.getFilename()
        local_att_path = os.path.join(extract_output_dir, att_name)

        log.append(f"Processing Attachment: {att_name}")

        # 6. UPLOAD BACK
        run_m365([
            "spo", "file", "add", 
            "--webUrl", site_url, 
            "--folder", folder_url, 
            "--path", local_att_path
        ])
        log.append(f"Uploaded: {att_name}")

    msg.close()

    # 7. CLEANUP
    for root, dirs, files in os.walk(work_dir, topdown=False):
        for name in files: os.remove(os.path.join(root, name))
        for name in dirs: os.rmdir(os.path.join(root, name))
    os.rmdir(work_dir)

    log.append("--- Process Completed Successfully ---")

except Exception:
    log.append("--- CRITICAL FAILURE ---")
    log.append(traceback.format_exc())

log = "\n".join(log)

# 1. HEADERS
byte_length = len(log.encode('utf-8'))
print("HTTP/1.1 200 OK", end="\r\n")
print("Content-Type: text/plain", end="\r\n")
print(f"Content-Length: {byte_length}", end="\r\n")
print("Content-Disposition: attachment; filename=\"attachment_log.txt\"", end="\r\n")
print("", end="\r\n")

print(log, end='')
