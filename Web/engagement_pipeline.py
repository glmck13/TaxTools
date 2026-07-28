#!/usr/bin/env python3
import os
import sys
import json
import html
import re
import io
import urllib.parse
import urllib.request
import datetime
import time
import unicodedata
import stat

from jinja2 import Template

# ReportLab Layout Engine & Platypus Flowable Components
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# CONFIGURATION & GLOBAL STATE
# ==========================================
ENGAGEMENT_SANDBOX = os.environ.get("ENGAGEMENT_SANDBOX")
if ENGAGEMENT_SANDBOX:
    JS_FILE = "engagement_sandbox.js"
    CSS_FILE = "engagement_sandbox.css"
    ENGAGEMENT_TEMPLATE = "engagement_sandbox.md"
    SERVICES_TEMPLATE = "services_sandbox.md"
    OWNER_EMAIL = "dropmeaclick@gmail.com"
    OWNER_SIGNATURE = "Where's Waldo"
    OWNER_CORPNAME = "Software Services"
    CARBON_COPIES = []
else:
    JS_FILE = "engagement_pipeline.js"
    CSS_FILE = "engagement_pipeline.css"
    ENGAGEMENT_TEMPLATE = "engagement_template.md"
    SERVICES_TEMPLATE = "services_template.md"
    OWNER_EMAIL = "steve@tarrantadvisors.com"
    OWNER_SIGNATURE = "Steve Tarrant"
    OWNER_CORPNAME = "Managing Member - Tarrant Advisors, LLC"
    CARBON_COPIES = ["katie@tarrantadvisors.com"]

TAX_YEAR = os.environ.get("TAX_YEAR", "2026")
SCRIPT_URL = os.environ.get("SCRIPT_NAME", "")
DRAFTS_DIR = os.environ.get("DRAFTS_DIR", os.environ.get("DOCUMENT_ROOT", "") + "/drafts")

QBO_APIBASE = os.environ.get("QBO_APIBASE", "")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

ADOBE_APIBASE = os.environ.get("ADOBE_APIBASE", "")
ADOBE_TOKEN = os.environ.get("ADOBE_ACCESS_TOKEN", "")

# ==========================================
# FORM DATA EXTRACTION HELPERS
# ==========================================
def get_form_val(form, key, default=""):
    """Safely extracts a string value from form data dictionary regardless of list wrapping."""
    if not form or key not in form:
        return default
    val = form[key]
    if isinstance(val, list):
        return str(val[0]) if val else default
    return str(val) if val is not None else default

def get_form_list(form, key):
    """Safely extracts a list of values from form data dictionary."""
    if not form or key not in form:
        return []
    val = form[key]
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]

# ==========================================
# POSIX FILE PERMISSION HELPERS
# ==========================================
def is_draft_locked(draft_path):
    """Checks if draft exists and has revoked write permissions (chmod ug-w)."""
    if not os.path.exists(draft_path):
        return False, None
    st = os.stat(draft_path)
    is_readonly = not bool(st.st_mode & (stat.S_IWUSR | stat.S_IWGRP))
    mtime_str = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%B %d, %Y at %I:%M %p")
    return is_readonly, mtime_str

def lock_draft(draft_path):
    """Revokes user and group write permissions on draft (chmod ug-w)."""
    if os.path.exists(draft_path):
        current_mode = os.stat(draft_path).st_mode
        os.chmod(draft_path, current_mode & ~(stat.S_IWUSR | stat.S_IWGRP))

def unlock_draft(draft_path):
    """Restores user and group write permissions on draft (chmod ug+w)."""
    if os.path.exists(draft_path):
        current_mode = os.stat(draft_path).st_mode
        os.chmod(draft_path, current_mode | (stat.S_IWUSR | stat.S_IWGRP))

def load_exposed_services_from_template():
    """Parses services template dynamically on startup to build EXPOSED_SERVICES."""
    services = []
    template_path = SERVICES_TEMPLATE
    
    if not os.path.exists(template_path):
        print(f"DEBUG: {template_path} not found. Fallback initialized.", file=sys.stderr)
        return []

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        raw_blocks = re.split(r'^##\s+', content, flags=re.MULTILINE)
        
        for block in raw_blocks:
            if not block.strip() or block.startswith('#'):
                continue
            
            lines = block.split('\n')
            service_name = lines[0].strip()
            item_id = ""
            entity_type = "both"
            notes_lines = []
            
            for line in lines[1:]:
                clean_line = line.strip()
                if not clean_line:
                    if notes_lines:
                        notes_lines.append("")
                    continue
                
                id_match = re.match(r'^-\s*ID:\s*(\d+)', clean_line, re.IGNORECASE)
                type_match = re.match(r'^-\s*Type:\s*(\w+)', clean_line, re.IGNORECASE)
                
                if id_match:
                    item_id = id_match.group(1)
                elif type_match:
                    entity_type = type_match.group(1).lower()
                else:
                    notes_lines.append(clean_line)
            
            notes_text = "\n".join(notes_lines).strip() if notes_lines else ""
            if item_id and service_name:
                services.append({
                    "id": item_id,
                    "name": service_name,
                    "type": entity_type,
                    "notes": notes_text
                })
        return sorted(services, key=lambda x: x["name"].lower())
    except Exception as e:
        print(f"ERROR: Failed parsing {template_path}: {str(e)}", file=sys.stderr)
        return []

EXPOSED_SERVICES = load_exposed_services_from_template()

# ==========================================
# QUICKBOOKS ONLINE REST WRAPPERS
# ==========================================
def qbo_api_request(endpoint, method="GET", payload=None):
    """Executes REST calls directly against QuickBooks Online endpoints."""
    if "?" in endpoint:
        path, query = endpoint.split("?", 1)
        endpoint = f"{path}?{urllib.parse.quote(query, safe='=/')}"
    else:
        endpoint = urllib.parse.quote(endpoint, safe='/')

    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {QBO_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"QBO API HTTP Error [{e.code}]: {error_body}", file=sys.stderr)
        raise Exception(f"QBO API Call Failed: {error_body}")

def extract_qbo_id(client_name_str):
    """Extracts numeric QuickBooks ID from the composite selection label."""
    match = re.search(r'Customer ID:\s*(\d+)', client_name_str)
    if match:
        return match.group(1)
    raise ValueError(f"Unable to parse unique Customer ID from label: {client_name_str}")

def parse_acct_num(acct_num_str):
    """Extracts signature configurations and entity definitions from QBO Notes."""
    meta = {"signature_type": "single", "entity_type": "individual", "co_signer_name": ""}
    if not acct_num_str:
        return meta

    matches = re.findall(r'(SIGNATURE|ENTITY|COSIGNER):([^,\n]+)', acct_num_str, re.IGNORECASE)
    for key, value in matches:
        k, v = key.upper(), value.strip()
        if k == "SIGNATURE":
            meta["signature_type"] = v
        elif k == "ENTITY":
            raw_ent = v.lower()
            meta["entity_type"] = raw_ent if raw_ent in ["individual", "s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"] else "individual"
        elif k == "COSIGNER":
            meta["co_signer_name"] = v
    return meta

def compile_acct_num(signature_type, entity_type, co_signer_name=""):
    """Serializes structured parameters into standard QBO Notes string."""
    clean_sig = signature_type.strip()
    if clean_sig.lower() in ["undefined", "null", "none", ""]:
        clean_sig = "single"
    
    notes_str = f"SIGNATURE:{clean_sig},ENTITY:{entity_type.strip().lower()}"
    if co_signer_name and co_signer_name.strip():
        notes_str += f",COSIGNER:{co_signer_name.strip()}"
    return notes_str

def extract_base_out_of_scope_boilerplate():
    """Reads engagement_template.md to extract standard out-of-scope items from the Jinja2 else block."""
    try:
        if os.path.exists(ENGAGEMENT_TEMPLATE):
            with open(ENGAGEMENT_TEMPLATE, "r", encoding="utf-8") as f:
                content = f.read()
            
            else_match = re.search(r'\{%\s*else\s*%\}(.*?)\{%\s*endif\s*\%}', content, re.DOTALL)
            if else_match:
                raw_block = else_match.group(1).strip()
                items = [line.strip("* ").strip() for line in raw_block.split("\n") if line.strip().startswith("*")]
                if items:
                    return items
            else:
                print(f"ERROR: Could not find Jinja2 {{% else %}} block inside {ENGAGEMENT_TEMPLATE}", file=sys.stderr)
        else:
            print(f"ERROR: Template file {ENGAGEMENT_TEMPLATE} does not exist.", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Failed parsing out-of-scope items from {ENGAGEMENT_TEMPLATE}: {str(e)}", file=sys.stderr)
        
    return []

# ==========================================
# ADOBE SIGN API WRAPPERS
# ==========================================
def adobe_sign_api_request(endpoint, method="POST", payload=None, files=None):
    """Executes communications directly with the Adobe Sign v6 REST API."""
    url = f"{ADOBE_APIBASE}/{endpoint}"
    headers = {"Authorization": f"Bearer {ADOBE_TOKEN}"}

    if payload and not files:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
    elif files:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        filename, mime_type, file_bytes = files
        header_part = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="File"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        footer_part = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = header_part + file_bytes + footer_part
        headers["Content-Length"] = str(len(body))
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Adobe Sign HTTP Error [{e.code}]: {error_body}", file=sys.stderr)
        raise Exception(f"Adobe Sign Call Failed: {error_body}")

def submit_adobe_sign_transaction(client_qbo_id, estimate_id, pdf_binary_data, additional_signer_email=None, is_organization=False):
    """Handles envelope transmission and routing parameters for Adobe Sign."""
    try:
        fresh_customer = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
        primary_email = fresh_customer.get("PrimaryEmailAddr", {}).get("Address", "")

        if not primary_email:
            return False, "Customer record is missing a valid Primary Email Address inside QBO."

        files_payload = (f"Tax_Engagement_Terms_Est_{estimate_id}.pdf", "application/pdf", pdf_binary_data)
        transient_res = adobe_sign_api_request("transientDocuments", method="POST", files=files_payload)
        transient_id = transient_res.get("transientDocumentId")
        
        if not transient_id:
            return False, "Adobe Sign Gateway rejected binary buffer authentication check."

        participant_sets = [{"memberInfos": [{"email": primary_email}], "order": 1, "role": "SIGNER"}]
        current_order = 2

        if additional_signer_email and "@" in additional_signer_email:
            participant_sets.append({
                "memberInfos": [{"email": additional_signer_email.strip()}],
                "order": current_order,
                "role": "SIGNER"
            })
            current_order += 1

        if is_organization:
            participant_sets.append({
                "memberInfos": [{"email": OWNER_EMAIL}],
                "order": current_order,
                "role": "SIGNER"
            })

        agreement_payload = {
            "fileInfos": [{"transientDocumentId": transient_id}],
            "name": f"Tarrant Advisors {TAX_YEAR} Engagement Agreement",
            "participantSetsInfo": participant_sets,
            "externalId": {"id": client_qbo_id},
            "signatureType": "ESIGN",
            "state": "IN_PROCESS"
        }

        if CARBON_COPIES:
            agreement_payload["ccs"] = [
                {"email": email, "label": "Executed Contract Copy"} 
                for email in CARBON_COPIES if email.strip()
            ]

        agreement_res = adobe_sign_api_request("agreements", method="POST", payload=agreement_payload)
        agreement_id = agreement_res.get("id")

        if agreement_id:
            for attempt in range(3):
                try:
                    time.sleep(2)
                    signing_urls_res = adobe_sign_api_request(f"agreements/{agreement_id}/signingUrls", method="GET")
                    urls_set = signing_urls_res.get("signingUrlSetInfos", [])
                    if urls_set and urls_set[0].get("signingUrls"):
                        live_signing_url = urls_set[0]["signingUrls"][0].get("esignUrl", "")
                        if live_signing_url:
                            return True, live_signing_url
                except Exception as url_err:
                    print(f"DEBUG: Attempt {attempt + 1} - Link generation pending: {url_err}", file=sys.stderr)
            return True, ""

        return False, "Adobe Sign accepted envelope configuration but failed to allocate an Agreement ID."
    except Exception as ex:
        return False, str(ex)

# ==========================================
# CGI FORM DATA PARSER
# ==========================================
def get_form_data():
    """Alternative to deprecated cgi.FieldStorage for CGI environments."""
    form_data = {}
    query_string = os.environ.get("QUERY_STRING", "")
    if query_string:
        form_data.update(urllib.parse.parse_qs(query_string))

    if os.environ.get("REQUEST_METHOD", "").upper() == "POST":
        try:
            content_length = int(os.environ.get("CONTENT_LENGTH", 0))
        except ValueError:
            content_length = 0

        if content_length > 0:
            body = sys.stdin.read(content_length)
            post_data = urllib.parse.parse_qs(body)
            for k, v in post_data.items():
                form_data[k] = v
    return form_data

# ==========================================
# INTERACTIVE WORKSPACE RENDERERS
# ==========================================
def render_phase1_workspace(error_msg=None, preserved_form=None):
    """Phase 1: Displays QBO customers and constructs the interactive workspace."""
    print("Content-Type: text/html\n")

    try:
        query_res = qbo_api_request("query?query=select * from Customer where Active=true maxresults 1000")
        customers = query_res.get("QueryResponse", {}).get("Customer", [])
    except Exception as e:
        customers = []
        error_msg = f"Failed to retrieve customer catalog from QBO. Verify tokens. Details: {str(e)}"

    client_data_map = {}
    for c in customers:
        c_id = c["Id"]
        c_name = c["DisplayName"]
        acct_num = c.get("Notes", "")
        addr_obj = c.get("BillAddr", {})
        c_email = c.get("PrimaryEmailAddr", {}).get("Address", "")

        meta = parse_acct_num(acct_num)
        has_addr = addr_obj.get("Line1") and addr_obj.get("City") and addr_obj.get("CountrySubDivisionCode") and addr_obj.get("PostalCode")
        has_meta = "SIGNATURE" in acct_num and "ENTITY" in acct_num

        saved_draft = None
        draft_path = os.path.join(DRAFTS_DIR, f"draft_{c_id}.json")
        is_locked, locked_mtime = is_draft_locked(draft_path)

        if os.path.exists(draft_path):
            try:
                with open(draft_path, "r", encoding="utf-8") as df:
                    saved_draft = json.load(df)
                    saved_draft["is_locked"] = is_locked
                    saved_draft["locked_mtime"] = locked_mtime
            except Exception:
                pass

        client_key = f"{c_name} (Customer ID: {c_id})"
        client_data_map[client_key] = {
            "id": c_id,
            "sync_token": c["SyncToken"],
            "email": c_email,
            "metadata": meta if (has_addr and has_meta) else {},
            "address": {
                "street": addr_obj.get("Line1", ""),
                "city": addr_obj.get("City", ""),
                "state": addr_obj.get("CountrySubDivisionCode", ""),
                "zip": addr_obj.get("PostalCode", "")
            } if has_addr else {},
            "exposed_services": EXPOSED_SERVICES,
            "saved_draft": saved_draft
        }

    selected_client = ""
    reconstructed_rows_json = "[]"
    preserved_heal_data_json = "{}"
    out_of_scope_items = extract_base_out_of_scope_boilerplate()
    estimate_date_option = "next_year"

    custom_items_to_render = {}

    if preserved_form:
        selected_client = get_form_val(preserved_form, "client_name")
        estimate_date_option = get_form_val(preserved_form, "estimate_date_option", "next_year")
        
        add_signer = get_form_val(preserved_form, "meta_additional_signer")
        clean_add_signer = add_signer if "@" in add_signer else ""

        heal_data = {
            "friendly_name": get_form_val(preserved_form, "friendly_name"),
            "heal_street": get_form_val(preserved_form, "heal_street"),
            "heal_city": get_form_val(preserved_form, "heal_city"),
            "heal_state": get_form_val(preserved_form, "heal_state"),
            "heal_zip": get_form_val(preserved_form, "heal_zip"),
            "meta_entity_type": get_form_val(preserved_form, "meta_entity_type"),
            "meta_signature_type": get_form_val(preserved_form, "meta_signature_type", "single"),
            "meta_additional_signer": clean_add_signer,
            "meta_co_signer_name": get_form_val(preserved_form, "meta_co_signer_name"),
            "out_of_scope_items": {k: get_form_val(preserved_form, k) for k in preserved_form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}
        }
        preserved_heal_data_json = json.dumps(heal_data)

        row_ids = get_form_list(preserved_form, "selected_rows")
        rows_list = [
            {
                "item_id": get_form_val(preserved_form, f"row_item_id_{rid}"),
                "service": urllib.parse.unquote(get_form_val(preserved_form, f"row_service_{rid}")),
                "fee": get_form_val(preserved_form, f"row_fee_{rid}", "0.00"),
                "notes": urllib.parse.unquote(get_form_val(preserved_form, f"row_notes_{rid}"))
            }
            for rid in row_ids
        ]
        reconstructed_rows_json = json.dumps(rows_list)

        for k in preserved_form:
            if "custom" in k:
                custom_items_to_render[k] = get_form_val(preserved_form, k)

    elif selected_client and selected_client in client_data_map:
        draft = client_data_map[selected_client].get("saved_draft")
        if draft and "out_of_scope_items" in draft:
            for k, val in draft["out_of_scope_items"].items():
                if "custom" in k:
                    custom_items_to_render[k] = val

    checklist_html = '<div id="out-of-scope-checklist-container" style="background: #fafbfc; border: 1px solid #cbd5e0; border-radius: 4px; padding: 15px; margin-top: 10px;">\n'
    if out_of_scope_items:
        for idx, item in enumerate(out_of_scope_items):
            item_key = f"out_of_scope_item_{idx}"
            is_checked = "checked"
            
            if preserved_form:
                preserved_vals = [get_form_val(preserved_form, k) for k in preserved_form if k.startswith("out_of_scope_item_")]
                if item_key not in preserved_form and item not in preserved_vals:
                    is_checked = ""
            elif selected_client and selected_client in client_data_map:
                draft = client_data_map[selected_client].get("saved_draft")
                if draft and "out_of_scope_items" in draft:
                    oos_draft = draft["out_of_scope_items"]
                    if item_key not in oos_draft and item not in oos_draft.values():
                        is_checked = ""

            checklist_html += f"""            <div style="margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0;">
                <label style="font-weight: normal; display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="{item_key}" value="{html.escape(item)}" {is_checked}>
                    {html.escape(item)}
                </label>
            </div>\n"""

    for k, val in custom_items_to_render.items():
        checklist_html += f"""            <div class="out-of-scope-checklist-item custom-out-of-scope-item" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0;">
                <label style="font-weight: normal; display: flex; align-items: center; gap: 8px; cursor: pointer; flex-grow: 1;">
                    <input type="checkbox" name="{html.escape(k)}" value="{html.escape(val)}" checked>
                    <span>{html.escape(val)}</span>
                </label>
                <button type="button" class="btn-remove-row" onclick="this.parentElement.remove()" title="Remove Custom Exclusion" style="margin-left: 10px;">×</button>
            </div>\n"""

    checklist_html += "        </div>\n"
    checklist_html += """
        <div class="add-out-of-scope-row" style="display: flex; gap: 10px; margin-top: 12px;">
            <input type="text" id="new-out-of-scope-input" placeholder="Enter custom out-of-scope item (e.g., Prior year 1040-X amendment)..." style="flex-grow: 1; padding: 8px 12px; font-size: 13px; border: 1px solid #cbd5e0; border-radius: 4px;">
            <button type="button" class="btn-add-row" onclick="addCustomOutOfScopeItem()" style="white-space: nowrap;">&Leftarrow; Add Out-of-Scope Item</button>
        </div>
        <div style="height: 12px;"></div>
    """

    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Tarrant Advisors - 2026 Estimate Builder</title>
    <link rel="stylesheet" type="text/css" href="/css/{CSS_FILE}">
    <script>
        window.clientData = {json.dumps(client_data_map)};
        window.reconstructedRows = {reconstructed_rows_json};
        window.preservedHealData = {preserved_heal_data_json};

        document.addEventListener("DOMContentLoaded", function() {{
            const clientSelect = document.getElementById('client-select');
            if (clientSelect && clientSelect.value) {{
                onClientChange();
            }}
        }});
    </script>
    <script src="/js/{JS_FILE}"></script>
</head>
<body>
<div class="wrapper">
    <h1>Tarrant Advisors LLC — Account Engagement Portal</h1>
    
    <div id="lock-banner-container" style="display:none;"></div>

    <form method="POST" action="{SCRIPT_URL}">
        <div class="form-group" style="margin-bottom: 25px;">
            <label for="estimate-date-option">Date for Estimate:</label>
            <select name="estimate_date_option" id="estimate-date-option" style="width: 100%; padding: 12px; font-size: 14px; border: 1px solid #ccd1d9; border-radius: 4px;">
                <option value="next_year"{" selected" if estimate_date_option == "next_year" else ""}>Next Year</option>
                <option value="today"{" selected" if estimate_date_option == "today" else ""}>Today</option>
            </select>
        </div>

        {f'<div style="background:#fde8e8; border:1px solid #e53e3e; color:#9b2c2c; padding:15px; margin-bottom:20px; border-radius:4px;">{html.escape(error_msg)}</div>' if error_msg else ''}

        <div class="form-group">
            <label for="client-select">Select QuickBooks Online Customer Account Record:</label>
            <select name="client_name" id="client-select" onchange="onClientChange()" required>
                <option value="">-- Choose Active Customer --</option>
                {"".join([f'<option value="{html.escape(k)}"{" selected" if k == selected_client else ""}>{html.escape(k)}</option>' for k in client_data_map.keys()])}
            </select>
        </div>

        <div id="profile-healing-container" style="display:none;"></div>

        <table id="service-table" class="service-table" style="display:none;">
            <thead>
                <tr>
                    <th style="text-align:center;">Action</th>
                    <th>Service Item Offering</th>
                    <th>Proposed Amount</th>
                    <th>Scope Specification / Notes</th>
                </tr>
            </thead>
            <tbody id="service-tbody"></tbody>
            <tfoot>
                <tr style="background:#fafafa;">
                    <td colspan="2" style="text-align:right; font-weight:700; padding:10px; color:#b76200;">Client Discount:</td>
                    <td id="ui-total-discount" class="calc-val" style="padding:10px; color:#b76200;">$0.00</td>
                    <td></td>
                </tr>
                <tr class="calc-row-balance">
                    <td colspan="2" style="text-align:right; font-weight:700; padding:10px;">TOTAL FEES:</td>
                    <td id="ui-total-balance" class="calc-val" style="padding:10px;">$0.00</td>
                    <td></td>
                </tr>
            </tfoot>
        </table>

        <div id="actions-container" class="actions-container" style="display:none;">
            <button type="button" class="btn-add-row" onclick="addServiceRow()">+ Add Service Line Item</button>
        </div>

        <div id="out-of-scope-container" class="out-of-scope-editor-group" style="display:none;">
            <label class="field-label" style="font-size:14px; margin-bottom:6px;">Select Applicable Out-of-Scope Services:</label>
            {checklist_html}
        </div>

        <div class="submit-container">
            <button type="submit" id="btn-submit-main" name="action" value="generate_preview" class="btn-submit" style="display:none;"></button>
        </div>
    </form>
</div>
</body>
</html>""")

def handle_generate_preview(form):
    """Phase 2: Renders split preview view with live iframe PDF document."""
    client_name = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(client_name)
    clean_client_title = client_name.split(" (Customer")[0].strip()

    row_ids = get_form_list(form, "selected_rows")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")

    heal_profile_flag = get_form_val(form, "heal_profile_flag", "false")
    
    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    
    meta_co_signer_name = get_form_val(form, "meta_co_signer_name")
    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    heal_street = get_form_val(form, "heal_street")
    heal_city = get_form_val(form, "heal_city")
    heal_state = get_form_val(form, "heal_state")
    heal_zip = get_form_val(form, "heal_zip")

    prior_estimate_id = ""
    existing_draft = {}
    draft_path = os.path.join(DRAFTS_DIR, f"draft_{client_qbo_id}.json")
    is_locked = False

    try:
        is_locked, _ = is_draft_locked(draft_path)
        if os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as df:
                existing_draft = json.load(df)
                prior_estimate_id = existing_draft.get("estimate_id", "")
    except Exception as de:
        print(f"DEBUG: Draft reading failure: {str(de)}", file=sys.stderr)

    friendly_name = get_form_val(form, "friendly_name").strip()
    if not friendly_name and existing_draft.get("friendly_name"):
        friendly_name = existing_draft.get("friendly_name", "").strip()
    if not friendly_name:
        friendly_name = clean_client_title

    if not heal_street or not meta_co_signer_name:
        try:
            fresh_c = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
            c_addr = fresh_c.get("BillAddr", {})
            c_meta = parse_acct_num(fresh_c.get("Notes", ""))
            
            if not heal_street:
                heal_street, heal_city = c_addr.get("Line1", ""), c_addr.get("City", "")
                heal_state, heal_zip = c_addr.get("CountrySubDivisionCode", ""), c_addr.get("PostalCode", "")
            if not meta_co_signer_name:
                meta_co_signer_name = c_meta.get("co_signer_name", "")
        except Exception as fe:
            print(f"DEBUG: QBO fallback data extraction failed: {str(fe)}", file=sys.stderr)

    posted_oos = {k: get_form_val(form, k) for k in form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}
    if not posted_oos and existing_draft.get("out_of_scope_items"):
        posted_oos = existing_draft["out_of_scope_items"]

    disk_rows_map = {str(r.get("item_id", "")): r for r in existing_draft.get("rows", []) if r.get("item_id")}

    processed_rows = []
    for rid in row_ids:
        item_id = get_form_val(form, f"row_item_id_{rid}")
        svc = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}"))
        fee_val = get_form_val(form, f"row_fee_{rid}", "")
        notes_val = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}"))
        bp_val = get_form_val(form, f"row_bp_{rid}", "individual")

        if (not fee_val or fee_val == "0.00") and item_id in disk_rows_map:
            fee_val = disk_rows_map[item_id].get("fee", "0.00")
            if not notes_val:
                notes_val = disk_rows_map[item_id].get("notes", "")

        processed_rows.append({
            "item_id": item_id,
            "service": svc,
            "fee": fee_val if fee_val else "0.00",
            "notes": notes_val,
            "bp": bp_val
        })

    if not is_locked:
        try:
            os.makedirs(DRAFTS_DIR, exist_ok=True)
            draft_payload = {
                "estimate_date_option": estimate_date_option,
                "friendly_name": friendly_name,
                "heal_profile_flag": heal_profile_flag,
                "meta_additional_signer": meta_sig if "@" in meta_sig else "",
                "meta_signature_type": meta_sig if meta_sig else "single",
                "meta_co_signer_name": meta_co_signer_name,
                "meta_entity_type": meta_ent,
                "heal_street": heal_street,
                "heal_city": heal_city,
                "heal_state": heal_state,
                "heal_zip": heal_zip,
                "out_of_scope_items": posted_oos,
                "estimate_id": prior_estimate_id,
                "rows": processed_rows
            }
            with open(draft_path, "w", encoding="utf-8") as df:
                json.dump(draft_payload, df, indent=2)
        except Exception as de:
            print(f"DEBUG: Server-side draft writing handling: {str(de)}", file=sys.stderr)

    pdf_query_args = [
        ("action", "render_live_pdf"), 
        ("client_name", client_name),
        ("friendly_name", friendly_name),
        ("heal_profile_flag", heal_profile_flag), 
        ("meta_additional_signer", meta_sig if "@" in meta_sig else ""),
        ("meta_signature_type", meta_sig if meta_sig else "single"), 
        ("meta_co_signer_name", meta_co_signer_name), 
        ("meta_entity_type", meta_ent),
        ("heal_street", heal_street),
        ("heal_city", heal_city),
        ("heal_state", heal_state),
        ("heal_zip", heal_zip)
    ]
    pdf_query_args.extend([("selected_rows", rid) for rid in row_ids])

    oos_to_pass = {k: get_form_val(form, k) for k in form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}
    if not oos_to_pass and existing_draft.get("out_of_scope_items"):
        oos_to_pass = existing_draft["out_of_scope_items"]

    for k, v in oos_to_pass.items():
        pdf_query_args.append((k, v))

    for rid in row_ids:
        item_id = get_form_val(form, f"row_item_id_{rid}")
        raw_fee_val = get_form_val(form, f"row_fee_{rid}", "")
        if (not raw_fee_val or raw_fee_val == "0.00") and item_id in disk_rows_map:
            raw_fee_val = disk_rows_map[item_id].get("fee", "0.00")
            
        fee = float(raw_fee_val) if (raw_fee_val and raw_fee_val.strip()) else 0.0
        pdf_query_args.extend([
            (f"row_item_id_{rid}", item_id),
            (f"row_service_{rid}", get_form_val(form, f"row_service_{rid}")),
            (f"row_fee_{rid}", fee),
            (f"row_notes_{rid}", get_form_val(form, f"row_notes_{rid}")),
            (f"row_bp_{rid}", get_form_val(form, f"row_bp_{rid}", "individual"))
        ])

    iframe_src = f"{SCRIPT_URL}?{urllib.parse.urlencode(pdf_query_args)}"

    hidden_checklist_fields = f'<input type="hidden" name="estimate_date_option" value="{html.escape(estimate_date_option)}">\n'
    for k, v in oos_to_pass.items():
        hidden_checklist_fields += f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">\n'

    print("Content-Type: text/html\n")
    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Review Proposed Engagement Document</title>
    <link rel="stylesheet" type="text/css" href="/css/{CSS_FILE}">
</head>
<body>
<div class="split-container">
    <div class="editor-panel" style="padding:25px; overflow-y:auto;">
        <form method="POST" action="{SCRIPT_URL}">
            <input type="hidden" name="client_name" value="{html.escape(client_name)}">
            <input type="hidden" name="friendly_name" value="{html.escape(friendly_name)}">
            <input type="hidden" name="heal_profile_flag" value="{html.escape(heal_profile_flag)}">
            <input type="hidden" name="meta_additional_signer" value="{html.escape(meta_sig if '@' in meta_sig else '')}">
            <input type="hidden" name="meta_signature_type" value="{html.escape(meta_sig if meta_sig else 'single')}">
            <input type="hidden" name="meta_co_signer_name" value="{html.escape(meta_co_signer_name)}">
            <input type="hidden" name="meta_entity_type" value="{html.escape(meta_ent)}">
            <input type="hidden" name="estimate_date_option" value="{html.escape(estimate_date_option)}">
            <input type="hidden" name="prior_estimate_id" value="{html.escape(prior_estimate_id)}">
            <input type="hidden" name="heal_street" value="{html.escape(heal_street)}">
            <input type="hidden" name="heal_city" value="{html.escape(heal_city)}">
            <input type="hidden" name="heal_state" value="{html.escape(heal_state)}">
            <input type="hidden" name="heal_zip" value="{html.escape(heal_zip)}">
            {hidden_checklist_fields}

            {"".join([f'<input type="hidden" name="selected_rows" value="{html.escape(rid)}">' for rid in row_ids])}
            {"".join([f'''
            <input type="hidden" name="row_item_id_{rid}" value="{html.escape(get_form_val(form, f"row_item_id_{rid}"))}">
            <input type="hidden" name="row_service_{rid}" value="{html.escape(get_form_val(form, f"row_service_{rid}"))}">
            <input type="hidden" name="row_fee_{rid}" value="{float(get_form_val(form, f"row_fee_{rid}", "0.00").replace('$', '').replace(',', '').strip()):.2f}">
            <input type="hidden" name="row_notes_{rid}" value="{html.escape(get_form_val(form, f"row_notes_{rid}"))}">
            <input type="hidden" name="row_bp_{rid}" value="{html.escape(get_form_val(form, f"row_bp_{rid}", "individual"))}">
            ''' for rid in row_ids])}

            <div style="display:flex; flex-direction:column; gap:12px; margin-top:15px;">
                <button type="submit" name="action" value="revert_to_workspace" class="btn-submit btn-action-grey" style="text-align:center; padding:12px;">← Go Back & Make Edits</button>
                <button type="submit" name="action" value="download_draft_pdf" class="btn-submit btn-action-yellow" style="text-align:center; padding:12px;">⬇ Download Draft Agreement</button>
                <button type="submit" name="action" value="execute_transactional_pipeline_paper" class="btn-submit btn-action-lightgreen" style="text-align:center; padding:12px;">✓ Submit Agreement for Paper Signature</button>
                <button type="submit" name="action" value="execute_transactional_pipeline" class="btn-submit btn-action-green" style="text-align:center; padding:12px;">⚡ Submit Agreement for Electronic Signature</button>
            </div>
        </form>
    </div>
    <div class="pdf-panel">
        <iframe src="{html.escape(iframe_src)}"></iframe>
    </div>
</div>
</body>
</html>""")

# ==========================================
# REPORTLAB PDF GENERATION LEG (PURE / STATELESS)
# ==========================================
def xml_safe_escape(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for tag in ["strong", "b", "i", "u"]:
        text = text.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return text.replace("&lt;br/&gt;", "<br/>").replace("&lt;br&gt;", "<br/>")

def compile_reportlab_pdf_buffer(form, include_esign_tags=False):
    """Pure rendering function: Compiles Markdown template into ReportLab PDF binary buffer."""
    client_name = get_form_val(form, "client_name", "Unknown Client")
    row_ids = get_form_list(form, "selected_rows")
    if not row_ids:
        row_ids = [k.replace("row_item_id_", "") for k in form if k.startswith("row_item_id_")]

    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type", "single")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    meta_co_signer_name = get_form_val(form, "meta_co_signer_name")
    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    clean_client_title = client_name.split(" (Customer")[0].strip()
    friendly_name = get_form_val(form, "friendly_name").strip() or clean_client_title

    street = get_form_val(form, "heal_street")
    city = get_form_val(form, "heal_city")
    state = get_form_val(form, "heal_state")
    zip_val = get_form_val(form, "heal_zip")

    if not street:
        try:
            c_id = extract_qbo_id(client_name)
            c_data = qbo_api_request(f"customer/{c_id}").get("Customer", {})
            addr_obj = c_data.get("BillAddr", {})
            street, city = addr_obj.get('Line1',''), addr_obj.get('City','')
            state, zip_val = addr_obj.get('CountrySubDivisionCode',''), addr_obj.get('PostalCode','')
        except Exception:
            street = city = state = zip_val = ""

    address_parts = [p.strip() for p in [street, city, state, zip_val] if p and p.strip()]
    billing_address = ", ".join(address_parts) if address_parts else "<i>[Billing Address Sourced on Execution]</i>"

    try:
        with open(ENGAGEMENT_TEMPLATE, "r", encoding="utf-8") as f:
            raw_markdown = f.read()
    except FileNotFoundError:
        raw_markdown = "# Tarrant Advisors LLC\n## {{TAX_YEAR}} ENGAGEMENT AGREEMENT\n{{DYNAMIC_ESTIMATES_TABLE}}\n{{DYNAMIC_SERVICES_TEXT}}"

    total_base = discount_val = deposit_val = 0.0
    table_rows_data = [["Proposed Service Offering", "Fee Amount"]]
    services_annotation_blocks = []

    for rid in row_ids:
        raw_svc = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}", ""))
        raw_fee_val = get_form_val(form, f"row_fee_{rid}", "")
        notes = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}", ""))
        item_id = get_form_val(form, f"row_item_id_{rid}", "")

        if not raw_svc and item_id:
            for s in EXPOSED_SERVICES:
                if str(s.get("id")) == str(item_id):
                    raw_svc = s.get("name", "Service Item")
                    if not notes:
                        notes = s.get("notes", "")
                    break

        if not raw_svc:
            raw_svc = "Service Item"

        try:
            fee = float(str(raw_fee_val).replace('$', '').replace(',', '').strip()) if raw_fee_val else 0.0
        except ValueError:
            fee = 0.0

        svc_lower = raw_svc.lower()
        if "discount" in svc_lower or "referral" in svc_lower:
            discount_val += abs(fee)
        elif "deposit" in svc_lower or "retainer" in svc_lower:
            deposit_val += abs(fee)
        else:
            table_rows_data.append([raw_svc, f"${fee:,.2f}"])
            total_base += fee

        if notes:
            services_annotation_blocks.append(f"• <strong>{raw_svc}:</strong> {xml_safe_escape(notes)}")

    total_net = total_base - discount_val
    if discount_val > 0: table_rows_data.append(["Client Discount:", f"-${discount_val:,.2f}"])
    table_rows_data.append(["TOTAL FEES:", f"${total_net:,.2f}"])
    if deposit_val > 0: table_rows_data.append(["DEPOSIT DUE UPON COMMENCEMENT OF SERVICE:", f"${deposit_val:,.2f}"])

    is_org_type = meta_ent.lower() in ["s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"]

    oos_dict = {k: get_form_val(form, k) for k in form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}
    out_of_scope_list = [v for v in oos_dict.values() if v and v.strip()]
    
    # Pure Jinja2 template rendering
    # Explicitly pass DYNAMIC_ESTIMATES_TABLE & DYNAMIC_SERVICES_TEXT so Jinja doesn't strip them!
    jinja_tmpl = Template(raw_markdown)
    markdown_content = jinja_tmpl.render(
        TAX_YEAR=TAX_YEAR,
        TODAY_DATE=datetime.date.today().strftime('%B %d, %Y'),
        CLIENT_ADDRESS=billing_address,
        CLIENT_LEGAL_NAME=xml_safe_escape(clean_client_title),
        FRIENDLY_NAME=xml_safe_escape(friendly_name),
        meta_entity_type=meta_ent.lower(),
        out_of_scope_items=out_of_scope_list,
        DYNAMIC_ESTIMATES_TABLE="{{DYNAMIC_ESTIMATES_TABLE}}",
        DYNAMIC_SERVICES_TEXT="{{DYNAMIC_SERVICES_TEXT}}"
    )

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40, title=f"{TAX_YEAR} Tax Engagement Agreement - {clean_client_title}")
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle('CustomBody', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#333333'))
    h1_style = ParagraphStyle('CustomH1', parent=styles['Heading1'], fontSize=20, leading=24, textColor=colors.HexColor('#0078d4'), spaceAfter=12)
    h2_style = ParagraphStyle('CustomH2', parent=styles['Heading2'], fontSize=14, leading=18, textColor=colors.HexColor('#111111'), spaceBefore=14, spaceAfter=8)

    cell_style = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#333333'))
    cell_bold = ParagraphStyle('TableCellBold', parent=styles['Normal'], fontSize=9, leading=12, fontName='Helvetica-Bold', textColor=colors.HexColor('#111111'))
    cell_summary_green = ParagraphStyle('TableCellGreen', parent=styles['Normal'], fontSize=9, leading=12, fontName='Helvetica-Bold', textColor=colors.HexColor('#107c41'))

    formatted_table_data = []
    for r, row in enumerate(table_rows_data):
        row_label = str(row[0]).upper()
        is_green_row = row_label.startswith("TOTAL FEES") or row_label.startswith("DEPOSIT DUE")
        formatted_table_data.append([
            Paragraph(xml_safe_escape(str(cell)), cell_summary_green if is_green_row else (cell_bold if r == 0 else cell_style))
            for cell in row
        ])

    story = []

    for line in markdown_content.split('\n'):
        line_str = line.strip()
        if not line_str or line_str.startswith("{%") or line_str.startswith("%}"):
            continue

        if line_str.startswith("# "):
            story.append(Paragraph(line_str[2:], h1_style))
        elif line_str.startswith("## ") or line_str.startswith("### "):
            story.append(Paragraph(re.sub(r'^#+\s*', '', line_str), h2_style))
        elif "{{DYNAMIC_ESTIMATES_TABLE}}" in line_str:
            t = Table(formatted_table_data, colWidths=[390, 140])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f3f4f6')),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ]))
            story.append(t)
            story.append(Spacer(1, 15))
        elif "{{DYNAMIC_SERVICES_TEXT}}" in line_str:
            if services_annotation_blocks:
                for block in services_annotation_blocks:
                    story.append(Paragraph(block, body_style))
                    story.append(Spacer(1, 4))
            else:
                story.append(Paragraph("<i>No specific custom exclusions logged. Standard filing scope parameters apply.</i>", body_style))
            story.append(Spacer(1, 10))
        else:
            story.append(Paragraph(xml_safe_escape(line_str), body_style))
            story.append(Spacer(1, 6))

    def render_sig_line(label, tag, underscore_len=27):
        return f"{label}: {tag}" if include_esign_tags else f"{label}: " + "_" * underscore_len

    sig_elements = [Spacer(1, 15)]
    signer1_label = f"<strong>{xml_safe_escape(friendly_name)}<br/>Signing on behalf of {xml_safe_escape(clean_client_title)}</strong>" if is_org_type else f"<strong>{xml_safe_escape(friendly_name)}</strong>"

    sig_elements.extend([
        Paragraph(render_sig_line("Signature", "{{_es_signer1_signature}}"), body_style),
        Spacer(1, 4),
        Paragraph(render_sig_line("Date Verified", "{{_es_signer1_date}}", 24), body_style),
        Spacer(1, 4),
        Paragraph(signer1_label, body_style),
    ])

    if meta_sig and "@" in meta_sig:
        co_signer_label = meta_co_signer_name.strip() if meta_co_signer_name.strip() else meta_sig.strip()
        sig_elements.extend([
            Spacer(1, 15),
            Paragraph(render_sig_line("Signature", "{{_es_signer2_signature}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Verified", "{{_es_signer2_date}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{xml_safe_escape(co_signer_label)}</strong>", body_style),
        ])

    if is_org_type:
        firm_idx = "3" if (meta_sig and "@" in meta_sig) else "2"
        sig_elements.extend([
            Spacer(1, 15),
            Paragraph(render_sig_line("Authorized Signature", f"{{{{_es_signer{firm_idx}_signature}}}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Counter-Signed", f"{{{{_es_signer{firm_idx}_date}}}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{OWNER_SIGNATURE}<br/>{OWNER_CORPNAME}</strong>", body_style),
        ])

    story.append(KeepTogether(sig_elements))
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer

def handle_render_live_pdf(form):
    """Phase 2: Streams PDF binary to iframe preview."""
    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    sys.stdout.buffer.write(b"Content-Type: application/pdf\n\n")
    sys.stdout.buffer.write(generated_buffer.read())

def handle_download_pdf(form, prefix="DRAFT"):
    """Unified handler for PDF downloads (Draft or Final)."""
    client_name = get_form_val(form, "client_name", "Unknown Client")
    clean_client_title = client_name.split(" (Customer")[0].strip()
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"Tax Agreement {clean_client_title} ({prefix} {timestamp_str}).pdf"
    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    
    sys.stdout.buffer.write(b"Content-Type: application/pdf\n")
    sys.stdout.buffer.write(f"Content-Disposition: attachment; filename={urllib.parse.quote(filename)}\n\n".encode('utf-8'))
    sys.stdout.buffer.write(generated_buffer.read())

# ==========================================
# TRANSACTION PIPELINE (PHASE 3)
# ==========================================
def execute_transactional_pipeline(form):
    """Executes QBO Estimate creation and Adobe Sign routing."""
    client_name = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(client_name)
    row_ids = get_form_list(form, "selected_rows")
    friendly_name = get_form_val(form, "friendly_name")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")

    heal_flag = get_form_val(form, "heal_profile_flag", "false")
    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    meta_co_signer_name = get_form_val(form, "meta_co_signer_name")
    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    delivery_method = get_form_val(form, "delivery_method")
    is_paper_mode = (delivery_method == "paper")
    is_org_type = meta_ent.lower() in ["s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"]

    prior_estimate_id = get_form_val(form, "prior_estimate_id")
    if prior_estimate_id and prior_estimate_id.strip():
        try:
            prior_txn = qbo_api_request(f"estimate/{prior_estimate_id}").get("Estimate", {})
            prior_sync_token = prior_txn.get("SyncToken")
            if prior_sync_token:
                qbo_api_request("estimate?operation=delete", method="POST", payload={"Id": prior_estimate_id, "SyncToken": prior_sync_token})
                print(f"DEBUG: Deleted Estimate #{prior_estimate_id}", file=sys.stderr)
        except Exception as rollback_err:
            print(f"Warning: Could not wipe prior Estimate #{prior_estimate_id}: {str(rollback_err)}", file=sys.stderr)

    try:
        fresh_customer = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
    except Exception as e:
        return render_phase1_workspace(error_msg=f"Pipeline Execution Halted: Unable to verify Customer record from QBO. ({str(e)})")

    current_notes = fresh_customer.get("Notes", "")
    current_addr = fresh_customer.get("BillAddr", {})
    current_name = fresh_customer.get("DisplayName", "")
    
    proposed_notes = compile_acct_num(meta_sig if meta_sig else "single", meta_ent, meta_co_signer_name)
    form_street = get_form_val(form, "heal_street") or current_addr.get("Line1", "")
    form_city = get_form_val(form, "heal_city") or current_addr.get("City", "")
    form_state = get_form_val(form, "heal_state") or current_addr.get("CountrySubDivisionCode", "")
    form_zip = get_form_val(form, "heal_zip") or current_addr.get("PostalCode", "")

    has_notes_drifted = (current_notes.strip() != proposed_notes.strip())
    has_address_drifted = (
        current_addr.get("Line1", "") != form_street or
        current_addr.get("City", "") != form_city or
        current_addr.get("CountrySubDivisionCode", "") != form_state or
        current_addr.get("PostalCode", "") != form_zip
    )

    if heal_flag == "true" or has_notes_drifted or has_address_drifted:
        try:
            patch_payload = {
                "Id": client_qbo_id,
                "SyncToken": fresh_customer["SyncToken"],
                "sparse": True,
                "Notes": proposed_notes,
                "CompanyName": current_name if is_org_type else "",
                "BillAddr": {
                    "Line1": form_street,
                    "City": form_city,
                    "CountrySubDivisionCode": form_state,
                    "PostalCode": form_zip
                }
            }
            qbo_api_request("customer", method="POST", payload=patch_payload)
        except Exception as e:
            return render_phase1_workspace(error_msg=f"Auto-Sync Data Healing Failure: Unable to update Customer record in QBO. ({str(e)})")

    estimate_lines = []
    deposit_val = 0.0

    disk_rows_map = {}
    draft_path = os.path.join(DRAFTS_DIR, f"draft_{client_qbo_id}.json")
    if os.path.exists(draft_path):
        try:
            with open(draft_path, "r", encoding="utf-8") as df:
                disk_draft = json.load(df)
                for d_row in disk_draft.get("rows", []):
                    item_key = str(d_row.get("item_id", ""))
                    if item_key:
                        disk_rows_map[item_key] = d_row
        except Exception:
            pass

    for rid in row_ids:
        item_id = get_form_val(form, f"row_item_id_{rid}")
        svc_name = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}", "Service Listing"))
        raw_fee_val = get_form_val(form, f"row_fee_{rid}", "")
        notes = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}"))

        if (not raw_fee_val or raw_fee_val == "0.00") and item_id in disk_rows_map:
            raw_fee_val = disk_rows_map[item_id].get("fee", "0.00")
            if not notes:
                notes = disk_rows_map[item_id].get("notes", "")

        fee = float(raw_fee_val) if (raw_fee_val and raw_fee_val.strip()) else 0.0

        svc_lower = svc_name.lower()
        if item_id == "00000" or "deposit" in svc_lower or "retainer" in svc_lower:
            deposit_val += abs(fee)
            continue 

        if "discount" in svc_lower or "referral" in svc_lower:
            fee = -abs(fee)

        description = f"{svc_name} | Scope: {notes}" if notes else svc_name
        estimate_lines.append({
            "Description": description,
            "Amount": fee,
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {
                "ItemRef": {"value": item_id},
                "UnitPrice": fee,
                "Qty": 1
            }
        })

    if not estimate_lines:
        return render_phase1_workspace(error_msg="Pipeline Halted: Add at least one Service Line Item before submitting.")

    estimate_payload = {
        "CustomerRef": {"value": client_qbo_id},
        "TxnStatus": "Pending",
        "Line": estimate_lines,
        "CustomField": [{"DefinitionId": "1", "StringValue": "JOINT" if (meta_sig and "@" in meta_sig) else "SINGLE", "Name": "Signers"}]
    }

    if deposit_val > 0:
        estimate_payload["PrivateNote"] = f"Deposit Due: ${deposit_val:,.2f}"

    if estimate_date_option == "next_year":
        next_year = datetime.date.today().year + 1
        estimate_payload["TxnDate"] = f"{next_year}-01-01"

    try:
        qbo_response = qbo_api_request("estimate", method="POST", payload=estimate_payload)
        generated_estimate = qbo_response.get("Estimate", {})
        estimate_id = generated_estimate.get("Id")
        sync_token = generated_estimate.get("SyncToken")
    except Exception as e:
        return render_phase1_workspace(error_msg=f"QuickBooks Error: Failed to generate transaction record. ({str(e)})")

    try:
        if os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as df:
                active_draft = json.load(df)
            active_draft["estimate_id"] = estimate_id
            with open(draft_path, "w", encoding="utf-8") as df:
                json.dump(active_draft, df, indent=2)
            lock_draft(draft_path)
    except Exception as de:
        print(f"DEBUG: Post-transaction draft locking failed: {str(de)}", file=sys.stderr)

    live_pdf_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=not is_paper_mode)
    live_pdf_buffer.seek(0)

    if is_paper_mode:
        adobe_sign_routing_success, adobe_error_context = True, ""
    else:
        adobe_sign_routing_success, adobe_error_context = submit_adobe_sign_transaction(
            client_qbo_id=client_qbo_id,
            estimate_id=estimate_id,
            pdf_binary_data=live_pdf_buffer.read(),
            additional_signer_email=meta_sig,
            is_organization=is_org_type
        )

    if not adobe_sign_routing_success:
        try:
            qbo_api_request("estimate?operation=delete", method="POST", payload={"Id": estimate_id, "SyncToken": sync_token})
            unlock_draft(draft_path)
        except Exception as rollback_err:
            print(f"CRITICAL ERROR: Rollback failed for Estimate {estimate_id}: {str(rollback_err)}", file=sys.stderr)
        return render_phase1_workspace(error_msg=f"Adobe Sign Routing Error: Contract delivery failed. QuickBooks transaction backed out. Details: {adobe_error_context}")

    success_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Pipeline Execution Complete</title>
    <link rel="stylesheet" type="text/css" href="/css/{CSS_FILE}">
</head>
<body>
<div class="success-wrapper">
    <div class="success-card">
        <div class="icon-circle">✓</div>
        <h2>Engagement Dispatched Successfully</h2>
        <p>
            QuickBooks Online transaction has been established in a <strong>Pending</strong> state as <strong>Estimate #{html.escape(estimate_id)}</strong>.
        </p>
        <div style="background:#f9fafb; padding:15px; border-radius:4px; border:1px solid #e5e7eb; margin-bottom:20px; text-align:left; font-size:13px; font-family:monospace;">
            <strong>Execution Summary Matrix:</strong><br>
            • Customer Index: {html.escape(client_qbo_id)}<br>
            • Target Account Class: {html.escape(meta_ent.upper())}<br>
            • Assigned Tracking ID: {html.escape(estimate_id)}<br>
            • Signature Enforcement Layout: {"JOINT" if (meta_sig and "@" in meta_sig) else "SINGLE"}
        </div>
        <a href="{SCRIPT_URL}" class="btn-submit" style="background:#0078d4; text-decoration:none; display:inline-block;">Build New Customer Estimate</a>
    </div>
</div>
</body>
</html>"""

    if is_paper_mode:
        dl_query_args = [
            ("action", "download_final_pdf"), ("estimate_id", estimate_id),
            ("client_name", client_name), ("friendly_name", friendly_name),
            ("delivery_method", "paper"), ("heal_profile_flag", "false"),
            ("meta_additional_signer", meta_sig if "@" in meta_sig else ""),
            ("meta_signature_type", meta_sig if meta_sig else "single"), 
            ("meta_co_signer_name", meta_co_signer_name),
            ("meta_entity_type", meta_ent)
        ]
        for k in form:
            if k.startswith("out_of_scope_item_") or k.startswith("custom_"):
                dl_query_args.append((k, get_form_val(form, k)))

        for rid in row_ids:
            dl_query_args.append(("selected_rows", rid))
            dl_query_args.extend([
                (f"row_item_id_{rid}", get_form_val(form, f"row_item_id_{rid}")),
                (f"row_service_{rid}", get_form_val(form, f"row_service_{rid}")),
                (f"row_fee_{rid}", get_form_val(form, f"row_fee_{rid}", "0.00")),
                (f"row_notes_{rid}", get_form_val(form, f"row_notes_{rid}")),
                (f"row_bp_{rid}", get_form_val(form, f"row_bp_{rid}", "individual"))
            ])
            
        dl_link = f"{SCRIPT_URL}?{urllib.parse.urlencode(dl_query_args)}"
        sandbox_button_html = f"""
        <div style="margin: 20px 0; padding: 20px; background: #f0fdf4; border: 1px solid #16a34a; border-radius: 4px; text-align: center;">
            <p style="margin-top: 0; font-weight: 600; color: #16a34a; font-size: 14px;">Physical Delivery Flow Activated:</p>
            <a href="{html.escape(dl_link)}" style="background: #16a34a; color: white; padding: 12px 24px; text-decoration: none; display: inline-block; border-radius: 4px; font-weight: bold; font-size: 15px;">⬇ Download & Print Final PDF</a>
        </div>
        """
        success_html = success_html.replace("</p>", f"</p>{sandbox_button_html}", 1)
    elif adobe_error_context:
        sandbox_button_html = f"""
        <div style="margin: 20px 0; padding: 15px; background: #f0f7ff; border: 1px solid #0078d4; border-radius: 4px; text-align: center;">
            <p style="margin-top: 0; font-weight: 600; color: #0078d4; font-size: 14px;">Sandbox Environment Link:</p>
            <a href="{html.escape(adobe_error_context)}" target="_blank" style="background: #107c41; color: white; padding: 10px 20px; text-decoration: none; display: inline-block; border-radius: 4px; font-weight: bold; font-size: 14px;">Open Live Signing Document</a>
        </div>
        """
        success_html = success_html.replace("</p>", f"</p>{sandbox_button_html}", 1)

    print("Content-Type: text/html\n")
    print(success_html)

# ==========================================
# CGI ROUTING INTERFACE
# ==========================================
if __name__ == "__main__":
    form_data = get_form_data()
    action = get_form_val(form_data, "action")

    if action == "generate_preview":
        handle_generate_preview(form_data)
    elif action == "render_live_pdf":
        handle_render_live_pdf(form_data)
    elif action == "download_draft_pdf":
        handle_download_pdf(form_data, prefix="DRAFT")
    elif action == "download_final_pdf":
        handle_download_pdf(form_data, prefix="FINAL")
    elif action == "execute_transactional_pipeline_paper":
        form_data["delivery_method"] = "paper"
        execute_transactional_pipeline(form_data)
    elif action == "execute_transactional_pipeline":
        form_data["delivery_method"] = ""
        execute_transactional_pipeline(form_data)
    elif action == "revert_to_workspace":
        client_name = get_form_val(form_data, "client_name")
        if client_name:
            try:
                c_id = extract_qbo_id(client_name)
                unlock_draft(os.path.join(DRAFTS_DIR, f"draft_{c_id}.json"))
            except Exception as ex:
                print(f"DEBUG: Could not unlock draft on revert: {str(ex)}", file=sys.stderr)
        render_phase1_workspace(preserved_form=form_data)
    else:
        render_phase1_workspace()
