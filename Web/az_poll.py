#!/usr/bin/env python3
import os
import json
import time

# --- Config: Must match az_start.cgi ---
AZ_DIR = os.environ.get("AZ_DIR", "")
PID_FILE = os.path.join(AZ_DIR, 'az_login.pid')

# Azure CLI token files (checks for both modern and legacy)
TOKEN_FILES = [
    os.path.join(AZ_DIR, 'msal_token_cache.json'),
]

print("Content-Type: application/json\n")

def is_authenticated():
    """Checks if any valid token cache file exists and is non-empty."""
    for token_file in TOKEN_FILES:
        if os.path.exists(token_file) and os.path.getsize(token_file) > 0:
            return True
    return False

def check_status():
    if not os.path.exists(PID_FILE):
        # If the process is gone and we have a token, it's a success
        if is_authenticated():
            return {"status": "success"}
        return {"status": "error", "message": "No session found"}

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # Signal 0: check if the process is alive
        os.kill(pid, 0)
        return {"status": "pending"}
    
    except (OSError, ValueError):
        # Process is dead. Let's see if it died successfully.
        if is_authenticated():
            # Clean up the PID file now that we're done
            if os.path.exists(PID_FILE): os.remove(PID_FILE)
            return {"status": "success"}
        else:
            if os.path.exists(PID_FILE): os.remove(PID_FILE)
            return {"status": "error", "message": "Login failed or was cancelled"}

print(json.dumps(check_status()))
