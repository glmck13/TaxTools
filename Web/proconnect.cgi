#!/usr/bin/env python3

import json
import requests
import re
import sys
import os
import shlex
import urllib.parse

# API Base URLs
USER_URL = "https://protaxonlineclientproxy.api.intuit.com"
TAX_URL = "https://protaxdata.api.intuit.com"

# Hardcoded Tax Type Mappings (Replaces taxtypes.csv)
TAX_TYPE_MAP = {
    "COR": "Form 1120",
    "EXM": "Form 990",
    "FID": "Form 1041",
    "GFT": "Form 709",
    "IND": "Form 1040",
    "PAR": "Form 1065",
    "SCO": "Form 1120-S"
}

def parse_curl():
    if os.environ.get("REQUEST_METHOD") == "POST":
        length = int(os.environ.get("CONTENT_LENGTH", 0))
        body = sys.stdin.read(length)
        params = urllib.parse.parse_qs(body)
        curl_input = params.get("clipboard_content", [None])[0]
    else:
        curl_input = sys.stdin.read()
    
    headers = {}
    
    # Safely split the curl command exactly like a bash shell would
    try:
        tokens = shlex.split(curl_input)
    except ValueError:
        # Fallback if there are unmatched quotes in the clipboard
        return headers

    for i, token in enumerate(tokens):
        # Extract headers (-H or --header)
        if token in ('-H', '--header') and i + 1 < len(tokens):
            header_string = tokens[i+1]
            if ':' in header_string:
                key, value = header_string.split(':', 1)
                headers[key.strip().lower()] = value.strip()
                
        # Extract cookies passed via -b
        elif token in ('-b', '--cookie') and i + 1 < len(tokens):
            if 'cookie' not in headers:
                headers['cookie'] = tokens[i+1].strip()

    # IMPORTANT: Delete 'accept-encoding' so Intuit doesn't send compressed/garbled data
    if 'accept-encoding' in headers:
        del headers['accept-encoding']
        
    return headers

def fetch_json(url, headers):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return None

def main():
    # 1. Get Headers from Stdin
    headers = parse_curl()
    if 'authorization' not in headers:
        print("Content-Type: text/html\n\n<h1>Parse Error</h1>")
        sys.exit(1)

    # 2. Map Assignees (Personas)
    personas_data = fetch_json(f"{USER_URL}/v1/realms/personas?roleType=offering&personaType=PROVISIONAL&qbnRole=true", headers)
    assignee_map = {}
    if personas_data and 'persona' in personas_data:
        for p in personas_data['persona']:
            name_list = p.get('fullName', [])
            if name_list:
                given = name_list[0].get('givenName', '')
                sur = name_list[0].get('surName', '')
                full_name = f"{given} {sur}".strip()
            else:
                full_name = p.get('personaName', 'Unknown')
            assignee_map[p.get('userId')] = full_name

    # 3. Map ID Status (Return Statuses)
    status_codes_data = fetch_json(f"{TAX_URL}/v1/returnstatus", headers)
    status_map = {}
    if status_codes_data and 'values' in status_codes_data:
        for s in status_codes_data['values']:
            status_map[s.get('id')] = s.get('description')

    # 4. Fetch Returns for 2025
    returns_list = fetch_json(f"{TAX_URL}/v1/returns/filter/2025?use-oii-client-id=true", headers)
    if not returns_list:
        return

    print("Content-Type: text/plain")
    print("Content-Disposition: attachment; filename=\"proconnect.csv\"")
    print()

    # 5. Build and Print Table
    cols = ["Return Name", "Client Name", "Form Type", "Assignee", "Status", "EFile", "Detail"]
    # Table formatting
    #header_fmt = "{:<25} | {:<25} | {:<20} | {:<20} | {:<25} | {:<15} | {}"
    header_fmt = "{}|{}|{}|{}|{}|{}|{}"
    print(header_fmt.format(*cols))
    #print("-" * 170)

    for ret in returns_list:
        name = ret.get('name', '')
        client_name = ret.get('client_name', '')
        from_type = TAX_TYPE_MAP.get(ret.get('type'), ret.get('type', ''))
        assignee = assignee_map.get(ret.get('id_assignee'), 'Unassigned')
        id_status = status_map.get(ret.get('id_status'), 'Unknown')
        ef_status = ret.get('ef_status', '')

        # New EfileStatuses logic: 
        # 1. Filter efileItems for included: true
        # 2. Match efileId to efileStatuses[id]
        # 3. Format: shortDesc:filingLevel:filingState
        efile_parts = []
        ef_items = ret.get('efileItems', [])
        ef_statuses = ret.get('efileStatuses', [])
        
        # Create a lookup for efileStatuses objects by their id
        status_lookup = {s.get('id'): s for s in ef_statuses if 'id' in s}
        
        for item in ef_items:
            if item.get('included') is True:
                efile_id = item.get('efileId')
                status_entry = status_lookup.get(efile_id)
                if status_entry:
                    s_desc = status_entry.get('shortDesc', '')
                    s_level = status_entry.get('filingLevel', '')
                    s_state = status_entry.get('filingState', '')
                    efile_parts.append(f"{s_desc}:{s_level}:{s_state}")
        
        efile_statuses_combined = "; ".join(efile_parts)

        # Truncate long strings for table view while keeping EfileStatuses full
        #print(header_fmt.format(
        #    name[:24], 
        #    client_name[:24], 
        #    from_type[:19], 
        #    assignee[:19], 
        #    id_status[:24], 
        #    ef_status[:14], 
        #    efile_statuses_combined
        #))
        print(header_fmt.format(name, client_name, from_type, assignee, id_status, ef_status, efile_statuses_combined))

if __name__ == "__main__":
    main()
