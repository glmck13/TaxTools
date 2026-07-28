#!/usr/bin/env python3

import subprocess
import os
import json
import shutil

# --- Config ---
# Updated directory for M365 config
M365_DIR = '/var/www/m365'
os.environ['CLIMICROSOFT365_CONFIG_DIR'] = M365_DIR
os.environ['HOME'] = M365_DIR

print("Content-Type: application/json\n")

response = {"status": "success", "message": "Logged out successfully"}

try:
    # 1. Tell M365 CLI to logout
    subprocess.run(['m365', 'logout'], check=False, capture_output=True)

    # 2. Cleanup M365 config files and lock files
    files_to_clear = [
        'm365_login.pid', 
        'm365_output.log'
    ]
    
    for f in files_to_clear:
        path = os.path.join(M365_DIR, f)
        if os.path.exists(path):
            os.remove(path)
            
    # M365 CLI often stores state in a nested directory; we can clear the config folder content if needed
    # but 'm365 logout' usually handles the credentials.

except Exception as e:
    response = {"status": "error", "message": str(e)}

print(json.dumps(response))
