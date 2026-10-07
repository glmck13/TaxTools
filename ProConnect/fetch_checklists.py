#!/usr/bin/env python3

import json
import os
import re
import shlex
import sys
import urllib.parse
import requests

TAX_URL = "https://protaxdata.api.intuit.com"
DOC_URL = "https://protaxonlinecommon.api.intuit.com"
RAW_DIR = "./raw_checklists"


def parse_curl():
    """Parses cURL command input from stdin or CGI POST data to extract authorization headers."""
    if os.environ.get("REQUEST_METHOD") == "POST":
        length = int(os.environ.get("CONTENT_LENGTH", 0))
        body = sys.stdin.read(length)
        params = urllib.parse.parse_qs(body)
        curl_input = params.get("clipboard_content", [None])[0] or ""
    else:
        curl_input = sys.stdin.read()

    headers = {}
    try:
        tokens = shlex.split(curl_input)
    except ValueError:
        return headers

    for i, token in enumerate(tokens):
        if token in ('-H', '--header') and i + 1 < len(tokens):
            header_string = tokens[i + 1]
            if ':' in header_string:
                key, value = header_string.split(':', 1)
                headers[key.strip().lower()] = value.strip()
        elif token in ('-b', '--cookie') and i + 1 < len(tokens):
            if 'cookie' not in headers:
                headers['cookie'] = tokens[i + 1].strip()

    headers.pop('accept-encoding', None)
    headers.pop('host', None)
    return headers


def fetch_json(session, url, headers):
    """Queries Intuit API endpoints using a persistent requests session."""
    try:
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response is not None else "N/A"
        body = e.response.text if e.response is not None else "No response body"
        print(f"[FETCH ERROR] Failed request to: {url}", file=sys.stderr)
        print(f"  - Status Code: {status}", file=sys.stderr)
        print(f"  - Error: {e}", file=sys.stderr)
        print(f"  - Response: {body}\n", file=sys.stderr)
        return None


def slugify(text):
    """Converts client names to clean, cross-platform safe string tokens."""
    if not text:
        return "client"
    text = str(text).lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text.strip('_') or "client"


def main():
    headers = parse_curl()
    if 'authorization' not in headers:
        print("[ERROR] Missing 'authorization' header in cURL input.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(RAW_DIR, exist_ok=True)
    session = requests.Session()

    print("[INFO] Fetching 2025 tax returns...", file=sys.stderr)
    returns_list = fetch_json(session, f"{TAX_URL}/v1/returns/filter/2025?use-oii-client-id=true", headers)
    if not isinstance(returns_list, list):
        print("[ERROR] No valid returns list retrieved.", file=sys.stderr)
        sys.exit(1)

    total_returns = len(returns_list)
    print(f"[INFO] Found {total_returns} returns. Fetching raw JSON checklists...\n", file=sys.stderr)

    manifest = []

    for idx, ret in enumerate(returns_list, 1):
        if not isinstance(ret, dict):
            continue

        return_name = ret.get('name') or 'N/A'
        client_name = ret.get('client_name') or 'Unknown Client'
        client_id = ret.get('id_client') or ''

        if not client_id:
            print(f"[{idx}/{total_returns}] Skipping (Missing Client ID): {client_name}", file=sys.stderr)
            continue

        checklist_data = fetch_json(session, f"{DOC_URL}/v1/doc-checklist/{client_id}?currentYear=2026", headers)
        if checklist_data is None:
            print(f"[{idx}/{total_returns}] Warning: No checklist data for {client_name} ({client_id})", file=sys.stderr)
            continue

        slug = slugify(client_name)
        json_filename = f"{slug}_{client_id}.json"
        json_path = os.path.join(RAW_DIR, json_filename)

        payload = {
            "client_id": client_id,
            "client_name": client_name,
            "return_name": return_name,
            "checklist": checklist_data
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        manifest.append({
            "client_id": client_id,
            "client_name": client_name,
            "file_path": json_path
        })

        print(f"[{idx}/{total_returns}] Saved raw JSON: {json_path}", file=sys.stderr)

    manifest_path = os.path.join(RAW_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n[SUCCESS] Extraction completed!", file=sys.stderr)
    print(f"  - Raw JSON files saved to : {RAW_DIR}/", file=sys.stderr)


if __name__ == "__main__":
    main()