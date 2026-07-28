#!/usr/bin/env python3

import subprocess
import os
import json

# --- Config ---
AZ_DIR = '/var/www/azure'
os.environ['AZURE_CONFIG_DIR'] = AZ_DIR
os.environ['HOME'] = AZ_DIR

print("Content-Type: application/json\n")

response = {"status": "success", "message": "Logged out successfully"}

try:
    # 1. Tell Azure CLI to logout (removes local tokens)
    subprocess.run(['az', 'logout'], check=False, capture_output=True)

    # 2. Cleanup any leftover files just in case
    files_to_clear = [
        'msal_token_cache.bin', 
        'accessTokens.json', 
        'az_login.pid', 
        'az_output.log'
    ]
    
    for f in files_to_clear:
        path = os.path.join(AZ_DIR, f)
        if os.path.exists(path):
            os.remove(path)

except Exception as e:
    response = {"status": "error", "message": str(e)}

print(json.dumps(response))
