#!/usr/bin/env python3
import os
import sys
import json
import urllib.parse
import urllib.request
import html

# Sourced automatically from qbo.cgi wrapper
QBO_APIBASE = os.environ.get("QBO_APIBASE", "").rstrip("/")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

ORGANIZATION_ENTITY_TYPES = {
    "sm_llc",
    "s_corp",
    "partnership",
    "c_corp",
    "non_profit",
    "trust",
    "organization",
}

def qbo_api_request(endpoint, method="GET", payload=None):
    """Executes authenticated HTTP requests against QuickBooks Online API."""
    if not QBO_APIBASE or not QBO_REALMID or not QBO_TOKEN:
        raise Exception("QBO Environment Variables (QBO_APIBASE, QBO_REALMID, QBO_ACCESS_TOKEN) are missing or empty.")

    if "?" in endpoint:
        path, query = endpoint.split("?", 1)
        # Properly encode SQL query strings for QBO
        if query.startswith("query="):
            sql_stmt = query[6:]
            encoded_query = "query=" + urllib.parse.quote(sql_stmt)
        else:
            encoded_query = urllib.parse.quote(query, safe='=/&')
        endpoint_url = f"{QBO_APIBASE}/company/{QBO_REALMID}/{path}?{encoded_query}"
    else:
        endpoint_url = f"{QBO_APIBASE}/company/{QBO_REALMID}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {QBO_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(endpoint_url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"QBO API HTTP Error [{e.code}]: {error_body}", file=sys.stderr)
        raise Exception(f"QBO API Call Failed (HTTP {e.code}): {error_body}")

def parse_acct_num(notes_str):
    """Parses JSON-encoded metadata from QBO Notes field into normalized dict."""
    meta = {
        "entity_type": "individual",
        "friendly_name": "",
        "primary_signer_email": "",
        "co_signer_name": "",
        "co_signer_email": ""
    }
    if not notes_str or not notes_str.strip():
        return meta

    try:
        data = json.loads(notes_str.strip())
        # If double-encoded string was stored, parse once more
        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, dict):
            raw_ent = str(data.get("entity", "")).lower().strip()
            meta["entity_type"] = raw_ent if raw_ent in ORGANIZATION_ENTITY_TYPES else "individual"
            
            signers = data.get("signers", [])
            if isinstance(signers, list) and len(signers) > 0:
                p_signer = signers[0] if isinstance(signers[0], dict) else {}
                meta["friendly_name"] = str(p_signer.get("name", "")).strip()
                meta["primary_signer_email"] = str(p_signer.get("email", "")).strip()

                if len(signers) > 1:
                    s_signer = signers[1] if isinstance(signers[1], dict) else {}
                    meta["co_signer_name"] = str(s_signer.get("name", "")).strip()
                    meta["co_signer_email"] = str(s_signer.get("email", "")).strip()
    except Exception as e:
        # Non-JSON standard notes stored on QBO client record
        pass

    return meta

def handle_customer_catalog():
    """Generates and outputs JSON customer catalog for front-end intake lookup."""
    sys.stdout.write("Content-Type: application/json\r\n\r\n")
    try:
        query_res = qbo_api_request("query?query=select * from Customer where Active=true maxresults 1000")
        customers = query_res.get("QueryResponse", {}).get("Customer", [])
        
        catalog = {}
        for c in customers:
            c_id = str(c.get("Id", ""))
            c_name = html.unescape(c.get("DisplayName", ""))
            acct_num = c.get("Notes", "")
            addr_obj = c.get("BillAddr", {})
            phone_obj = c.get("PrimaryPhone", {})
            email_obj = c.get("PrimaryEmailAddr", {})

            meta = parse_acct_num(acct_num)
            
            # Fallback friendly_name to DisplayName if metadata was not present
            if not meta["friendly_name"]:
                meta["friendly_name"] = c_name

            raw_c_email = email_obj.get("Address", "")
            primary_email = raw_c_email.split(",")[0].strip() if raw_c_email else ""
            
            # Format catalog key as "Client Name (ID: 12345)"
            catalog_key = f"{c_name} (ID: {c_id})"

            catalog[catalog_key] = {
                "id": c_id,
                "display_name": c_name,
                "email": meta.get("primary_signer_email") or primary_email,
                "phone": phone_obj.get("FreeFormNumber", ""),
                "metadata": meta,
                "address": {
                    "street": addr_obj.get("Line1", ""),
                    "city": addr_obj.get("City", ""),
                    "state": addr_obj.get("CountrySubDivisionCode", ""),
                    "zip": addr_obj.get("PostalCode", "")
                }
            }
        
        sys.stdout.write(json.dumps({"status": "success", "customers": catalog}))
    except Exception as e:
        sys.stdout.write(json.dumps({"status": "error", "message": str(e)}))

if __name__ == "__main__":
    handle_customer_catalog()