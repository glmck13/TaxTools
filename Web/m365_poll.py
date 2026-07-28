#!/usr/bin/env python3
import os
import json
import subprocess

# --- Config ---
M365_DIR = '/var/www/m365'
PID_FILE = os.path.join(M365_DIR, 'm365_login.pid')
os.environ['CLIMICROSOFT365_CONFIG_DIR'] = M365_DIR
os.environ['HOME'] = M365_DIR

print("Content-Type: application/json\n")

def is_authenticated():
    """Checks M365 CLI status to see if login was successful."""
    try:
        result = subprocess.run(['m365', 'status', '--output', 'json'], capture_output=True, text=True)
        if result.returncode == 0:
            status_data = json.loads(result.stdout)
            # M365 status returns "Logged in" or "Logged out"
            return status_data != "Logged out"
    except:
        return False
    return False

def check_status():
    if not os.path.exists(PID_FILE):
        if is_authenticated():
            return {"status": "success"}
        return {"status": "error", "message": "No session found"}

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # Check if the process is still running
        os.kill(pid, 0)
        return {"status": "pending"}
    
    except (OSError, ValueError):
        # Process ended, check if it was successful
        if is_authenticated():
            if os.path.exists(PID_FILE): os.remove(PID_FILE)
            return {"status": "success"}
        else:
            if os.path.exists(PID_FILE): os.remove(PID_FILE)
            return {"status": "error", "message": "Login failed or was cancelled"}

print(json.dumps(check_status()))
