#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import json
import time

# --- Configuration ---
M365_DIR = os.environ.get("M365_DIR", "")
os.environ['CLIMICROSOFT365_CONFIG_DIR'] = M365_DIR
os.environ['HOME'] = M365_DIR

PID_FILE = os.path.join(M365_DIR, 'm365_login.pid')
LOG_FILE = os.path.join(M365_DIR, 'm365_output.log')

def main():
    sys.stdout.write("Content-Type: application/json\r\n\r\n")
    sys.stdout.flush()

    try:
        # Ensure directory exists
        os.makedirs(M365_DIR, exist_ok=True)
        
        log_fd = os.open(LOG_FILE, os.O_RDWR | os.O_CREAT | os.O_TRUNC)

        # Updated M365 command
        process = subprocess.Popen(
            ['m365', 'login', '--authType', 'deviceCode'],
            stdout=log_fd,
            stderr=log_fd,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            text=True
        )
        
        os.close(log_fd)

        with open(PID_FILE, 'w') as f_pid:
            f_pid.write(str(process.pid))

        device_code = None
        start_time = time.time()
        while time.time() - start_time < 15:
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r') as f_read:
                    content = f_read.read()
                    # M365 CLI uses a similar string format for device codes
                    match = re.search(r"code ([A-Z0-9]+) to", content)
                    if match:
                        device_code = match.group(1)
                        break
            time.sleep(1)

        if device_code:
            print(json.dumps({"status": "success", "code": device_code}))
        else:
            print(json.dumps({"status": "error", "message": "Timed out waiting for M365 CLI code."}))

    except Exception as e:
        print(json.dumps({"status": "error", "message": f"CGI Execution Error: {str(e)}"}))

if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
