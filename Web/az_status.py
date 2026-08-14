#!/usr/bin/env python3
import subprocess
import os
import json
import sys

# --- Configuration ---
# Ensure this matches the directory used in your other scripts
AZ_DIR = os.environ.get("AZ_DIR", "")
os.environ['AZURE_CONFIG_DIR'] = AZ_DIR
os.environ['HOME'] = AZ_DIR

def get_azure_status():
    """Checks if we are already logged in and returns account info."""
    try:
        # We use a short timeout to ensure the dashboard remains snappy
        result = subprocess.run(
            ['az', 'account', 'show', '--output', 'json'],
            capture_output=True, 
            text=True, 
            check=False,
            timeout=5
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except:
        pass
    return None

# --- Application Logic ---
status = get_azure_status()

# Output the HTML
print("Content-Type: text/html\r\n\r\n")
print(f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Azure CLI Dashboard</title>
    <style>
        #body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f2f5; color: #333; display: flex; justify-content: center; padding-top: 10px; }}
        .card {{ background: white; padding: 10px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); max-width: 600px; width: 100%; text-align: center; }}
        .btn {{ background-color: #0078d4; color: white; padding: 12px 24px; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; transition: background 0.2s; margin: 5px; }}
        .btn:hover {{ background-color: #005a9e; }}
        .btn-logout {{ background-color: #d83b01; }}
        .btn-logout:hover {{ background-color: #a4262c; }}
        .status-badge {{ display: inline-block; padding: 5px 12px; border-radius: 20px; font-size: 0.9em; font-weight: bold; margin-bottom: 20px; }}
        .online {{ background: #dff6dd; color: #107c10; }}
        .offline {{ background: #fde7e9; color: #a4262c; }}
        .code-box {{ font-size: 2.5em; background: #222; color: #fff; padding: 15px; margin: 20px 0; letter-spacing: 4px; font-family: monospace; border-radius: 4px; }}
        auth-container {{ margin-top: 10px; }}
        #hr {{ border: 0; border-top: 1px solid #eee; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Azure CLI Management</h2>
""")

if status:
    # --- AUTHENTICATED VIEW ---
    print(f"""
        <div class="status-badge online">● AUTHENTICATED</div>
        <p>
        <strong>Subscription:</strong> {status.get('name')}<br>
        <strong>Tenant:</strong> {status.get('tenantId')}<br>
        <strong>User:</strong> {status.get('user', {}).get('name')}
        </p>
        <hr>
        <div id="auth-container">
            <button class="btn" onclick="location.reload()">Refresh Status</button>
            <button class="btn btn-logout" onclick="confirmLogout()">Logout</button>
        </div>
    """)
else:
    # --- NOT AUTHENTICATED VIEW ---
    print(f"""
        <div class="status-badge offline">○ DISCONNECTED</div>
        <p>This server is not currently authenticated with Azure.</p>
        <div id="auth-container">
            <button class="btn" onclick="startLogin()">Begin Azure Login</button>
        </div>
    """)

print("""
    </div>

    <script>
    let pollInterval = null;

    async function startLogin() {
        const container = document.getElementById('auth-container');
        container.innerHTML = '<p>🚀 Requesting Device Code...</p>';
        
        try {
            const response = await fetch('/cgi/az_start.cgi');
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
                startPolling();
            } else {
                container.innerHTML = `<p style="color:red">Error: ${data.message}</p>
                                      <button class="btn" onclick="location.reload()">Try Again</button>`;
            }
        } catch (e) {
            container.innerHTML = '<p style="color:red">Network error starting login.</p>';
        }
    }

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);
        
        pollInterval = setInterval(async () => {
            try {
                const resp = await fetch('/cgi/az_poll.cgi');
                const result = await resp.json();
                
                if (result.status === 'success') {
                    clearInterval(pollInterval);
                    document.getElementById('auth-container').innerHTML = 
                        '<h2 style="color:green">✅ Login Successful!</h2><p>Reloading dashboard...</p>';
                    setTimeout(() => location.reload(), 2000);
                } else if (result.status === 'error') {
                    clearInterval(pollInterval);
                    document.getElementById('poll-status').innerText = '❌ Session expired or failed.';
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 3000);
    }

    async function confirmLogout() {
        if (!confirm("Sign out of Azure?")) return;
        
        const container = document.getElementById('auth-container');
        container.innerHTML = '<p>🧹 Clearing session...</p>';
        
        try {
            const response = await fetch('/cgi/az_logout.cgi');
            const data = await response.json();
            if (data.status === 'success') {
                location.reload();
            } else {
                alert("Logout failed: " + data.message);
            }
        } catch (e) {
            alert("Network error during logout.");
        }
    }
    </script>
</body>
</html>
""")
