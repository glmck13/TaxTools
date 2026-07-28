#!/usr/bin/env python3
import csv
import datetime
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

# ==============================================================================
# CONFIGURATION
# ==============================================================================
# Adobe REST v6 Config
ADOBE_APIBASE = os.environ.get("ADOBE_APIBASE", "")
ADOBE_TOKEN = os.environ.get("ADOBE_ACCESS_TOKEN", "")

# SharePoint Target Parameters
SP_WEB_URL = os.environ.get("SP_WEB_URL", "https://tarrantadvisors.sharepoint.com/sites/Company")
SP_TARGET_FOLDER = os.environ.get("SP_TARGET_FOLDER", "Shared Documents/!Adobe Signed Agreements")

# Customer Match Config
QBOSP_MATCH_FILE = os.environ.get("QBOSP_MATCH_FILE", "../etc/qbosp.csv")
TAX_YEAR = os.environ.get("TAX_YEAR", "2026")

def run_m365_command(args):
    """Executes an m365 CLI command using the pre-authenticated active session."""
    cmd = ["m365"] + args
    print(f"DEBUG: Executing M365 CLI command: {' '.join(cmd)}", file=sys.stderr)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("DEBUG: M365 CLI command completed successfully.", file=sys.stderr)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"M365 CLI execution failed!\nCommand: {' '.join(cmd)}\nError output: {e.stderr}", file=sys.stderr)
        raise RuntimeError(f"CLI command failed: {e.stderr}")


def download_signed_pdf(agreement_id):
    """Downloads the combined signed PDF from Acrobat Sign v6 API."""
    url = f"{ADOBE_APIBASE}/agreements/{agreement_id}/combinedDocument"
    print(f"DEBUG: Initializing PDF download from Adobe Sign API for Agreement ID: {agreement_id}", file=sys.stderr)

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {ADOBE_TOKEN}",
        "Accept": "application/pdf"
    })
    try:
        with urllib.request.urlopen(req) as response:
            pdf_content = response.read()
            print(f"DEBUG: Successfully downloaded {len(pdf_content)} bytes from Adobe.", file=sys.stderr)
            return pdf_content
    except Exception as e:
        print(f"Error downloading agreement {agreement_id} from Adobe: {e}", file=sys.stderr)
        raise


def lookup_sp_folder(qbo_customer_id):
    """Looks up QBO customer ID in QBOSP_MATCH_FILE.

    Returns folder path string if matched, else None.
    """
    if not os.path.exists(QBOSP_MATCH_FILE):
        print(f"DEBUG: Match file '{QBOSP_MATCH_FILE}' not found.", file=sys.stderr)
        return None

    try:
        with open(QBOSP_MATCH_FILE, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=":")
            for row in reader:
                if str(row.get("qbo_id", "")).strip() == str(qbo_customer_id).strip():
                    folder = row.get("matched_sp_folder", "").strip()
                    return folder.replace(" - SHARED", "").strip() if folder else None
    except Exception as e:
        print(f"DEBUG: Error reading match file '{QBOSP_MATCH_FILE}': {e}", file=sys.stderr)

    return None


def upload_to_sharepoint_via_cli(pdf_bytes, filename, target_folder):
    """Saves PDF to a temporary file and uploads it to SharePoint via pre-authenticated m365 CLI."""
    print(f"DEBUG: Creating temporary staging file for {filename}", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
        temp_pdf.write(pdf_bytes)
        temp_path = temp_pdf.name
    print(f"DEBUG: Temporary file staged at path: {temp_path}", file=sys.stderr)

    try:
        print(f"Uploading file '{filename}' to folder '{target_folder}' on SharePoint...", file=sys.stderr)
        run_m365_command([
            "spo", "file", "add",
            "--webUrl", SP_WEB_URL,
            "--folder", target_folder,
            "--path", temp_path,
            "--fileName", filename
        ])
        print(f"Successfully uploaded: {filename} -> {target_folder}", file=sys.stderr)
    finally:
        if os.path.exists(temp_path):
            print(f"DEBUG: Cleaning up and deleting temp file: {temp_path}", file=sys.stderr)
            os.remove(temp_path)


def handle_get_verification():
    """Responds to Adobe Sign's webhook GET request to verify intent."""
    client_id = os.environ.get("HTTP_X_ADOBESIGN_CLIENTID", "")
    print(f"DEBUG: Received GET request for Intent Verification. Client ID: {client_id}", file=sys.stderr)

    response_body = json.dumps({"xAdobeSignClientId": client_id})

    print("Content-Type: application/json; charset=utf-8")
    print(f"X-AdobeSign-ClientId: {client_id}")
    print(f"Content-Length: {len(response_body)}")
    print("\r\n")
    print(response_body)
    print("DEBUG: Intent Verification handshake sent back to Adobe successfully.", file=sys.stderr)


def handle_post_notification():
    """Processes incoming webhook notifications, replying instantly before completing work."""
    print("DEBUG: Processing incoming POST notification from Adobe Sign.", file=sys.stderr)
    try:
        content_length = int(os.environ.get("CONTENT_LENGTH", 0))
        payload_data = sys.stdin.read(content_length)
        payload = json.loads(payload_data)
        print(f"DEBUG: Successfully parsed JSON payload. Event Type: {payload.get('event')}", file=sys.stderr)
    except Exception as e:
        print(f"DEBUG: JSON parsing failed: {e}", file=sys.stderr)
        print("Status: 400 Bad Request\r\n\r\nFailed to parse incoming JSON payload.")
        return

    # 1. Prepare and send the 200 OK response back to Adobe immediately
    client_id = os.environ.get("HTTP_X_ADOBESIGN_CLIENTID", "")
    response_body = json.dumps({"xAdobeSignClientId": client_id})

    print("Status: 200 OK")
    print("Content-Type: application/json; charset=utf-8")
    print(f"X-AdobeSign-ClientId: {client_id}")
    print(f"Content-Length: {len(response_body)}")
    print("\r\n")
    print(response_body)

    # Force flush output buffer so the web server receives the complete payload
    sys.stdout.flush()
    print("DEBUG: Instantly echoed 200 OK payload back to Adobe server.", file=sys.stderr)

    # 2. SEVER the connection: Close stdout so the web server disconnects Adobe
    try:
        print("DEBUG: Severing foreground HTTP connection to start silent background worker...", file=sys.stderr)
        sys.stdout.close()
        # Redirect stdout to devnull so subsequent print/sys.stdout calls don't crash the script
        sys.stdout = open(os.devnull, 'w')
    except Exception as e:
        print(f"DEBUG: Error while closing foreground connection channel: {e}", file=sys.stderr)
        pass

    # 3. Work on the transfer silently in the background
    event_type = payload.get("event")
    if event_type == "AGREEMENT_WORKFLOW_COMPLETED":
        agreement_info = payload.get("agreement", {})
        agreement_id = agreement_info.get("id")
        external_info = agreement_info.get("externalId", {})
        raw_external_id = str(external_info.get("id", "")).strip()

        # Parse Document Type and QBO ID strictly via externalId
        if ":" in raw_external_id:
            doc_type, qbo_customer_id = raw_external_id.split(":", 1)
            doc_type = doc_type.strip()
            qbo_customer_id = qbo_customer_id.strip()
        else:
            # Fallback if externalId is raw ID without prefix
            qbo_customer_id = raw_external_id if raw_external_id else "0"
            doc_type = "Unknown"

        filename = f"{doc_type} ({qbo_customer_id}).pdf"
        print(f"DEBUG: Webhook matched for QBO Customer: {qbo_customer_id} [{doc_type}]", file=sys.stderr)

        # Determine target SharePoint folder based on QBOSP_MATCH_FILE lookup
        matched_sp_folder = lookup_sp_folder(qbo_customer_id)
        if matched_sp_folder:
            target_folder = f"Shared Documents/{matched_sp_folder}/{TAX_YEAR}/Agreements & Invoices"
            print(f"DEBUG: Found match in CSV for QBO ID {qbo_customer_id}. Folder: {target_folder}", file=sys.stderr)
        else:
            target_folder = SP_TARGET_FOLDER
            print(f"DEBUG: No match found for QBO ID {qbo_customer_id}. Fallback folder: {target_folder}", file=sys.stderr)

        print(f"DEBUG: Targeted event matched. Ready to process contract pipeline for: {filename}", file=sys.stderr)

        try:
            pdf_data = download_signed_pdf(agreement_id)
            upload_to_sharepoint_via_cli(pdf_data, filename, target_folder)
            print(f"DEBUG: Background operational sequence finished perfectly for agreement: {agreement_id}", file=sys.stderr)
        except Exception as err:
            # Errors are still safely directed to the Apache/Nginx error log via sys.stderr
            print(f"Silent background task failed: {err}", file=sys.stderr)
    else:
        print(f"DEBUG: Ignoring event type '{event_type}' — no background action required.", file=sys.stderr)


if __name__ == "__main__":
    request_method = os.environ.get("REQUEST_METHOD", "GET")
    print(f"DEBUG: Webhook invoked via HTTP method: {request_method}", file=sys.stderr)

    if request_method == "GET":
        handle_get_verification()
    elif request_method == "POST":
        handle_post_notification()
    else:
        print(f"DEBUG: Received unhandled request method: {request_method}", file=sys.stderr)
        print("Status: 405 Method Not Allowed\r\n\r\n")
