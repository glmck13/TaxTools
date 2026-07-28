#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import json
import time

# --- Configuration ---
# Ensure the Apache user (www-data) has full ownership of this folder
AZ_DIR = '/var/www/azure'
os.environ['AZURE_CONFIG_DIR'] = AZ_DIR
os.environ['HOME'] = AZ_DIR
os.environ['AZURE_CORE_COLLECT_TELEMETRY'] = '0'

PID_FILE = os.path.join(AZ_DIR, 'az_login.pid')
LOG_FILE = os.path.join(AZ_DIR, 'az_output.log')

def main():
    # 1. Immediate JSON Headers
    sys.stdout.write("Content-Type: application/json\r\n\r\n")
    sys.stdout.flush()

    try:
        # 2. Open a physical log file to redirect output
        # This prevents the "Apache Hang" by avoiding pipes
        log_fd = os.open(LOG_FILE, os.O_RDWR | os.O_CREAT | os.O_TRUNC)

        # 3. Spawn the background process
        process = subprocess.Popen(
            ['az', 'login', '--use-device-code', '--allow-no-subscriptions'],
            stdout=log_fd,
            stderr=log_fd,
            stdin=subprocess.DEVNULL,
            start_new_session=True, # Create a new session so it persists
            close_fds=True,         # Close inherited Apache file descriptors
            text=True
        )
        
        # Close our local handle to the log file; az has its own now
        os.close(log_fd)

        # 4. Save the PID for the polling script
        with open(PID_FILE, 'w') as f_pid:
            f_pid.write(str(process.pid))

        # 5. Tail the log file to find the Device Code
        device_code = None
        start_time = time.time()
        while time.time() - start_time < 15:  # 15 second timeout to find code
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r') as f_read:
                    content = f_read.read()
                    # Pattern matches: "enter the code ABC123XYZ to authenticate"
                    match = re.search(r"code ([A-Z0-9]+) to", content)
                    if match:
                        device_code = match.group(1)
                        break
            time.sleep(1)

        # 6. Return the result to the dashboard
        if device_code:
            print(json.dumps({
                "status": "success", 
                "code": device_code
            }))
        else:
            print(json.dumps({
                "status": "error", 
                "message": "Timed out waiting for Azure CLI to generate a code."
            }))

    except Exception as e:
        print(json.dumps({
            "status": "error", 
            "message": f"CGI Execution Error: {str(e)}"
        }))

if __name__ == "__main__":
    main()
    # 7. Force an immediate exit to release Apache threads
    sys.stdout.flush()
    os._exit(0)
