#!/usr/bin/env python3
import subprocess
import os
import json
import sys

# --- Configuration ---
# Ensure this directory exists and is writable by the web user (e.g., www-data)
M365_DIR = '/var/www/m365'
os.environ['CLIMICROSOFT365_CONFIG_DIR'] = M365_DIR
os.environ['HOME'] = M365_DIR

def get_m365_context():
    """
    Checks login status and the current SPO base URL.
    Returns a dictionary with status info or None if logged out.
    """
    context = {"user": None, "spo_url": "Not Set"}
    try:
        # 1. Check Login Status
        # v11.4.0 returns a JSON string of the UPN or "Logged out"
        login_res = subprocess.run(
            ['m365', 'status', '--output', 'json'],
            capture_output=True, text=True, timeout=5
        )
        login_data = json.loads(login_res.stdout)
        
        if login_data == "Logged out":
            return None
        
        context["user"] = login_data

        # 2. Check SPO Base URL (The "m365 spo set" value)
        spo_res = subprocess.run(
            ['m365', 'spo', 'get', '--output', 'json'],
            capture_output=True, text=True, timeout=5
        )
        if spo_res.returncode == 0:
            # v11.4.0 returns the URL string directly in JSON format
            context["spo_url"] = json.loads(spo_res.stdout)

        return context
    except Exception:
        return None

# Execute status check
ctx = get_m365_context()

# --- HTML Output ---
print("Content-Type: text/html\r\n\r\n")
print(f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>M365 CLI Dashboard</title>
    <style>
        #body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f2f5; color: #333; display: flex; justify-content: center; padding-top: 10px; }}
        .card {{ background: white; padding: 10px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 600px; width: 100%; text-align: center; }}
        .status-badge {{ display: inline-block; padding: 5px 12px; border-radius: 20px; font-size: 0.9em; font-weight: bold; margin-bottom: 20px; }}
        .online {{ background: #dff6dd; color: #107c10; }}
        .offline {{ background: #fde7e9; color: #a4262c; }}
        .btn {{ background-color: #0078d4; color: white; padding: 12px 24px; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; transition: background 0.2s; margin: 5px; }}
        .btn:hover {{ background-color: #005a9e; }}
        .btn-logout {{ background-color: #d83b01; }}
        .btn-logout:hover {{ background-color: #a4262c; }}
        .code-box {{ font-size: 2.5em; background: #222; color: #fff; padding: 15px; margin: 20px 0; letter-spacing: 4px; font-family: monospace; border-radius: 4px; }}
        auth-container {{ margin-top: 10px; }}
        poll-status {{ color: #666; font-style: italic; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>M365 CLI Management</h2>
""")

if ctx:
    print(f"""
        <div class="status-badge online">● AUTHENTICATED</div>
        <p> 
        <strong>Subscription:</strong> {ctx['spo_url']}<br>
        <strong>Tenant:</strong> {ctx['user'].get('appTenant')}<br>
        <strong>User:</strong> {ctx['user'].get('connectedAs')}
        </p>
        <hr>
        <div id="auth-container">
            <button class="btn" onclick="location.reload()">Refresh Status</button>
            <button class="btn btn-logout" onclick="confirmLogout()">Logout</button>
        </div>
    """)
else:
    print(f"""
        <div class="status-badge offline">○ DISCONNECTED</div>
        <p>This server is not currently authenticated with Microsoft 365.</p>
        <div id="auth-container">
            <button class="btn" onclick="startLogin()">Begin M365 Login</button>
        </div>
    """)

print("""
    </div>

    <script>
    async function startLogin() {
        const container = document.getElementById('auth-container');
        container.innerHTML = '<p>🔄 Requesting device code...</p>';
        
        try {
            const response = await fetch('/cgi/m365_start.cgi');
            const data = await response.json();
            
            if (data.status === 'success') {
                container.innerHTML = `
                    <div style="text-align: left; margin-top: 10px;">
                        <p>1. Go to: <a href="https://microsoft.com/devicelogin" target="_blank">microsoft.com/devicelogin</a></p>
                        <p>2. Enter this code:</p>
                        <div class="code-box">${data.code}</div>
                        <p id="poll-status">⏳ Checking authentication status...</p>
                    </div>
                `;
                pollStatus();
            } else {
                container.innerHTML = `<p style="color:red">Error: ${data.message}</p>
                                       <button class="btn" onclick="location.reload()">Retry</button>`;
            }
        } catch (e) {
            container.innerHTML = '<p style="color:red">Network error. Check server logs.</p>';
        }
    }

    function pollStatus() {
        const pollInterval = setInterval(async () => {
            try {
                const resp = await fetch('/cgi/m365_poll.cgi');
                const result = await resp.json();
                
                if (result.status === 'success') {
                    clearInterval(pollInterval);
                    document.getElementById('auth-container').innerHTML = 
                        '<h2 style="color:green">✅ Login Successful!</h2><p>Reloading dashboard...</p>';
                    setTimeout(() => location.reload(), 2000);
                } else if (result.status === 'error') {
                    clearInterval(pollInterval);
                    document.getElementById('poll-status').innerText = '❌ Session failed.';
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 3000);
    }

    async function confirmLogout() {
        if (!confirm("Sign out of Microsoft 365?")) return;

        const container = document.getElementById('auth-container');
        container.innerHTML = '<p>🧹 Clearing session...</p>';

        try {
            const response = await fetch('/cgi/m365_logout.cgi');
            const data = await response.json();
            if (data.status === 'success') location.reload();
        } catch (e) {
            alert("Logout failed.");
        }
    }
    </script>
</body>
</html>
""")
