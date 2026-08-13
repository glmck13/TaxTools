#!/usr/bin/env python3
import sys
import os
import json
import re
import requests
import subprocess
from urllib.parse import parse_qs

# Configuration constants
TENANT_URL = "https://tarrantadvisors.sharepoint.com"
BASE_SITE = ""
QBOSP_FILE = f"{os.environ.get('DOCUMENT_ROOT', '')}/etc/{os.environ.get('QBO_SANDBOX', '')}qbosp.csv"

reply = ""

try:
    # Extract 'uuid' from CGI environment query string
    query_string = os.environ.get("QUERY_STRING", "")
    parsed_qs = parse_qs(query_string)
    uuid_list = parsed_qs.get("uuid")

    if not uuid_list or not uuid_list[0]:
        raise ValueError("Missing required 'uuid' parameter in query string.")

    uuid_val = uuid_list[0]

    # Execute the CLI command directly to fetch file content
    m365_cmd = [
        "m365", "spo", "file", "get",
        "--webUrl", f"{TENANT_URL}{BASE_SITE}",
        "--id", uuid_val,
        "--asFile",
        "--path", "/dev/stdout"
    ]

    # Run command and capture standard output
    result = subprocess.run(
        m365_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False
    )

    body = result.stdout.strip()

    if not body:
        error_msg = result.stderr.strip() or "Empty input received. File download failed or returned empty content."
        raise ValueError(error_msg)

    if body.startswith('<'):
        raise ValueError("SharePoint API returned an XML error instead of the JSON payload. Check authentication or file permissions.")

    # Parse JSON payload
    payload = json.loads(body)

    raw_name = payload.get('customer_name', '')
    customer_name = raw_name.strip().replace(':', '-').replace('\n', ' ')

    if not customer_name:
        raise ValueError("customer_name cannot be empty after sanitization.")

    raw_email_input = payload.get('customer_email', '').strip()
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_email_input)
    customer_email = email_match.group(0).strip() if email_match else raw_email_input

    customer_phone = payload.get('customer_phone', '').strip()
    item_id = payload.get('item_id', '').strip()
    estimate_amount = payload.get('estimate_amount', '').strip()
    memo = payload.get('memo', '').strip()

    access_token = os.environ.get('QBO_ACCESS_TOKEN')
    realm_id = os.environ.get('QBO_REALMID') 

    if not access_token or not realm_id:
        raise ValueError("Missing QBO_ACCESS_TOKEN or QBO_REALMID environment variable.")

    base_url = f"{os.environ.get('QBO_APIBASE')}/company/{realm_id}"
    query_url = f"{base_url}/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    customer_id = None

    safe_customer_name = customer_name.replace("'", "\\'")
    qbo_query = f"SELECT * FROM Customer WHERE DisplayName = '{safe_customer_name}'"

    query_params = {
        "query": qbo_query,
        "minorversion": "75" 
    }

    search_resp = requests.get(query_url, headers=headers, params=query_params)
    search_resp.raise_for_status()
    query_results = search_resp.json().get('QueryResponse', {})

    if 'Customer' in query_results and len(query_results['Customer']) > 0:
        customer_id = str(query_results['Customer'][0].get('Id'))
        customer_action = f"Found: {customer_name}"
    else:
        customer_data = {
            "DisplayName": customer_name
        }
        if customer_email:
            customer_data["PrimaryEmailAddr"] = {"Address": customer_email}
        if customer_phone:
            customer_data["PrimaryPhone"] = {"FreeFormNumber": customer_phone}

        cust_resp = requests.post(f"{base_url}/customer?minorversion=75", headers=headers, json=customer_data)
        cust_resp.raise_for_status()
        customer_id = str(cust_resp.json().get('Customer', {}).get('Id'))
        customer_action = f"Created: {customer_name}"

        with open(QBOSP_FILE, "a", encoding="utf-8") as f:
            f.write(f"{customer_id}:{customer_name}:{customer_name} - SHARED:::\n")

    response_data = {
        "status": "success",
        "customer_id": customer_id,
        "message": f"{customer_action}"
    }

    reply = json.dumps(response_data)

except Exception as e:
    error_data = {
        "status": "error",
        "message": str(e)
    }
    reply = json.dumps(error_data)

# Print HTTP Response headers and body
byte_length = len(reply.encode('utf-8'))
print("HTTP/1.1 200 OK", end="\r\n")
print("Content-Type: text/plain", end="\r\n")
print(f"Content-Length: {byte_length}", end="\r\n")
print("Content-Disposition: attachment; filename=\"qbo.txt\"", end="\r\n")
print("", end="\r\n")

print(reply, end='')
