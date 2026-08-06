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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# CONFIGURATION & GLOBAL STATE
# ==========================================

PIPELINE_SANDBOX = os.environ.get("PIPELINE_SANDBOX")
if PIPELINE_SANDBOX:
    ENABLE_BATCH_MODE = False # Set to True when ready to expose/bill batch capabilities
    JS_FILE = "engagement_sandbox.js"
    CSS_FILE = "engagement_sandbox.css"
    ENGAGEMENT_TEMPLATE = "engagement_sandbox.md"
    SERVICES_TEMPLATE = "services_sandbox.md"
    OWNER_EMAIL = "dropmeaclick@gmail.com"
    OWNER_SIGNATURE = "Where's Waldo"
    OWNER_CORPNAME = "Software Services"
    CARBON_COPIES = []
    DRAFTS_DIR = os.environ.get("DOCUMENT_ROOT", ".") + "/sandbox"
else:
    ENABLE_BATCH_MODE = False  # Set to True when ready to expose/bill batch capabilities
    JS_FILE = "engagement_pipeline.js"
    CSS_FILE = "engagement_pipeline.css"
    ENGAGEMENT_TEMPLATE = "engagement_template.md"
    SERVICES_TEMPLATE = "services_template.md"
    OWNER_EMAIL = "steve@tarrantadvisors.com"
    OWNER_SIGNATURE = "Steve Tarrant"
    OWNER_CORPNAME = "Managing Member - Tarrant Advisors, LLC"
    CARBON_COPIES = ["katie@tarrantadvisors.com"]
    DRAFTS_DIR = os.environ.get("DOCUMENT_ROOT", ".") + "/engagements"

TAX_YEAR = os.environ.get("TAX_YEAR", "2026")
NEXT_YEAR = f"{int(TAX_YEAR) + 1}"
SCRIPT_URL = os.environ.get("SCRIPT_NAME", "")

QBO_APIBASE = os.environ.get("QBO_APIBASE", "")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

ADOBE_APIBASE = os.environ.get("ADOBE_APIBASE", "")
ADOBE_TOKEN = os.environ.get("ADOBE_ACCESS_TOKEN", "")

# ==========================================
# FORM DATA EXTRACTION & AJAX DETECTION HELPERS
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

def is_ajax_request(form):
    """Combo detection: Checks HTTP_X_REQUESTED_WITH header or explicit ajax=true form/query parameter."""
    header_ajax = os.environ.get("HTTP_X_REQUESTED_WITH", "").lower() == "xmlhttprequest"
    param_ajax = get_form_val(form, "ajax", "false").lower() in ["true", "1", "yes"]
    return header_ajax or param_ajax

def render_pipeline_error(form, error_msg, http_code=400):
    """Context-aware error handler: returns JSON for AJAX requests, HTML for direct POSTs."""
    if is_ajax_request(form):
        status_header = "400 Bad Request" if http_code == 400 else "500 Internal Server Error"
        print(f"Status: {status_header}")
        print("Content-Type: application/json\n")
        print(json.dumps({"status": "error", "message": error_msg}))
        return
    render_phase1_workspace(error_msg=error_msg)

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
            fee_val = "0"
            notes_lines = []
            
            for line in lines[1:]:
                clean_line = line.strip()
                if not clean_line:
                    if notes_lines:
                        notes_lines.append("")
                    continue
                
                id_match = re.match(r'^-\s*ID:\s*(\d+)', clean_line, re.IGNORECASE)
                type_match = re.match(r'^-\s*Type:\s*(\w+)', clean_line, re.IGNORECASE)
                fee_match = re.match(r'^-\s*Fee:\s*([0-9.]+)', clean_line, re.IGNORECASE)
                migrates_match = re.match(r'^-\s*Migrates-From:', clean_line, re.IGNORECASE)
                
                if id_match:
                    item_id = id_match.group(1)
                elif type_match:
                    entity_type = type_match.group(1).lower()
                elif fee_match:
                    fee_val = f"{int(round(float(fee_match.group(1))))}"
                elif migrates_match:
                    pass
                else:
                    notes_lines.append(clean_line)
            
            notes_text = "\n".join(notes_lines).strip() if notes_lines else ""
            if item_id and service_name:
                services.append({
                    "id": item_id,
                    "name": service_name,
                    "type": entity_type,
                    "fee": fee_val,
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
        raw_email = fresh_customer.get("PrimaryEmailAddr", {}).get("Address", "")
        primary_email = raw_email.split(",")[0].strip() if raw_email else ""

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
            "externalId": {"id": f"Tax Agreement:{client_qbo_id}"},
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
            time.sleep(3)
            for attempt in range(5):
                try:
                    signing_urls_res = adobe_sign_api_request(f"agreements/{agreement_id}/signingUrls", method="GET")
                    urls_set = signing_urls_res.get("signingUrlSetInfos", [])
                    if urls_set and urls_set[0].get("signingUrls"):
                        live_signing_url = urls_set[0]["signingUrls"][0].get("esignUrl", "")
                        if live_signing_url:
                            return True, live_signing_url
                except Exception as url_err:
                    print(f"DEBUG: Attempt {attempt + 1} - Link generation pending: {url_err}", file=sys.stderr)
                time.sleep(2)
            return True, ""

        return False, "Adobe Sign accepted envelope configuration but failed to allocate an Agreement ID."
    except Exception as ex:
        return False, str(ex)

# ==========================================
# CGI FORM DATA PARSER
# ==========================================
def get_form_data():
    """Extracts CGI parameters from QUERY_STRING or POST body reliably."""
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
            raw_body = sys.stdin.read(content_length)
            post_data = urllib.parse.parse_qs(raw_body, keep_blank_values=True)
            for k, v in post_data.items():
                form_data[k] = v
    return form_data

# ==========================================
# INTERACTIVE WORKSPACE RENDERERS
# ==========================================
def render_phase1_workspace(error_msg=None, preserved_form=None):
    """Phase 1: Displays QBO customers and constructs the dual-mode interactive workspace."""
    print("Content-Type: text/html\n")

    try:
        query_res = qbo_api_request("query?query=select * from Customer where Active=true maxresults 1000")
        customers = query_res.get("QueryResponse", {}).get("Customer", [])
    except Exception as e:
        customers = []
        error_msg = f"Failed to retrieve customer catalog from QBO. Verify tokens. Details: {str(e)}"

    client_data_map = {}
    draft_clients_map = {}

    for c in customers:
        c_id = c["Id"]
        c_name = html.unescape(c["DisplayName"])
        acct_num = c.get("Notes", "")
        addr_obj = c.get("BillAddr", {})
        c_email = c.get("PrimaryEmailAddr", {}).get("Address", "")

        meta = parse_acct_num(acct_num)
        has_addr = addr_obj.get("Line1") and addr_obj.get("City") and addr_obj.get("CountrySubDivisionCode") and addr_obj.get("PostalCode")
        has_meta = "SIGNATURE" in acct_num and "ENTITY" in acct_num

        saved_draft = None
        draft_path = os.path.join(DRAFTS_DIR, f"client_{c_id}.json")
        is_locked, locked_mtime = is_draft_locked(draft_path)

        if os.path.exists(draft_path):
            try:
                with open(draft_path, "r", encoding="utf-8") as df:
                    saved_draft = json.load(df)
                    saved_draft["is_locked"] = is_locked
                    saved_draft["locked_mtime"] = locked_mtime
            except Exception:
                pass

        delivery_fmt = "electronic"
        if saved_draft and "delivery_format" in saved_draft:
            delivery_fmt = saved_draft["delivery_format"]

        client_key = f"{c_name} (Customer ID: {c_id})"
        client_data_map[client_key] = {
            "id": c_id,
            "sync_token": c.get("SyncToken", ""),
            "email": c_email,
            "delivery_format": delivery_fmt,
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

        # Catalog clients that possess a saved draft with at least one service row for cloning
        if saved_draft and saved_draft.get("rows") and len(saved_draft["rows"]) > 0:
            row_count = len(saved_draft["rows"])
            total_fee = sum([float(r.get("fee", 0)) for r in saved_draft["rows"]])
            draft_clients_map[client_key] = f"{c_name} — {row_count} item(s) (${int(round(total_fee)):,})"

    selected_client = ""
    reconstructed_rows_json = "[]"
    preserved_heal_data_json = "{}"
    out_of_scope_items = extract_base_out_of_scope_boilerplate()
    estimate_date_option = "next_year"

    custom_items_to_render = {}

    if preserved_form:
        selected_client = html.unescape(get_form_val(preserved_form, "client_name"))
        estimate_date_option = get_form_val(preserved_form, "estimate_date_option", "next_year")
        
        add_signer = get_form_val(preserved_form, "meta_additional_signer")
        clean_add_signer = add_signer if "@" in add_signer else ""

        heal_data = {
            "friendly_name": html.unescape(get_form_val(preserved_form, "friendly_name")),
            "heal_legal_name": html.unescape(get_form_val(preserved_form, "heal_legal_name")),
            "heal_street": get_form_val(preserved_form, "heal_street"),
            "heal_city": get_form_val(preserved_form, "heal_city"),
            "heal_state": get_form_val(preserved_form, "heal_state"),
            "heal_zip": get_form_val(preserved_form, "heal_zip"),
            "meta_entity_type": get_form_val(preserved_form, "meta_entity_type"),
            "meta_signature_type": get_form_val(preserved_form, "meta_signature_type", "single"),
            "meta_additional_signer": clean_add_signer,
            "meta_co_signer_name": html.unescape(get_form_val(preserved_form, "meta_co_signer_name")),
            "out_of_scope_items": {k: get_form_val(preserved_form, k) for k in preserved_form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}
        }
        preserved_heal_data_json = json.dumps(heal_data)

        row_ids = get_form_list(preserved_form, "selected_rows")
        rows_list = [
            {
                "item_id": get_form_val(preserved_form, f"row_item_id_{rid}"),
                "service": urllib.parse.unquote(get_form_val(preserved_form, f"row_service_{rid}")),
                "fee": get_form_val(preserved_form, f"row_fee_{rid}", "0"),
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

    batch_mode_js = "true" if ENABLE_BATCH_MODE else "false"

    # Pre-build datalist options for source cloning (single and batch)
    clone_options_html = "".join([f'<option value="{html.escape(k)}">{html.escape(v)}</option>' for k, v in draft_clients_map.items()])

    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Tarrant Advisors - 2026 Engagement Portal</title>
    <link rel="stylesheet" type="text/css" href="/css/{CSS_FILE}">
    <script>
        window.APP_CONFIG = {{
            "enableBatchMode": {batch_mode_js}
        }};
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
    
    <!-- MODE TAB SWITCHER -->
    <div class="mode-tabs">
        <button type="button" id="tab-btn-single" class="tab-btn active" onclick="switchWorkspaceMode('single')">👤 Single Client Intake</button>
        <button type="button" id="tab-btn-batch" class="tab-btn" onclick="switchWorkspaceMode('batch')">📑 Seasonal Batch Dashboard</button>
    </div>

    <!-- WORKSPACE MODE 1: SINGLE CLIENT INTAKE -->
    <div id="single-client-workspace">
        <div id="lock-banner-container" style="display:none;"></div>

        <form method="POST" action="{SCRIPT_URL}">
            <div class="form-group" style="margin-bottom: 25px;">
                <label for="estimate-date-option">Date for Estimate:</label>
                <select name="estimate_date_option" id="estimate-date-option" style="width: 100%; padding: 12px; font-size: 14px; border: 1px solid #ccd1d9; border-radius: 4px;">
                    <option value="next_year"{" selected" if estimate_date_option == "next_year" else ""}>Next Year</option>
                    <option value="today"{" selected" if estimate_date_option == "today" else ""}>This Year</option>
                </select>
            </div>

            {f'<div style="background:#fde8e8; border:1px solid #e53e3e; color:#9b2c2c; padding:15px; margin-bottom:20px; border-radius:4px;">{html.escape(error_msg)}</div>' if error_msg else ''}

            <div class="form-group">
                <label for="client-select">Search & Select QuickBooks Online Customer Account Record:</label>
                <input type="text" 
                       name="client_name" 
                       id="client-select" 
                       list="client-options" 
                       value="{html.escape(selected_client)}" 
                       placeholder="Type client name, business entity, or QBO ID (e.g., Smith or 102)..." 
                       onchange="onClientChange()" 
                       oninput="onClientChange()" 
                       style="width: 100%; padding: 12px; font-size: 14px; border: 1px solid #ccd1d9; border-radius: 4px; box-sizing: border-box;" 
                       required>
                <datalist id="client-options">
                    {"".join([f'<option value="{html.escape(k)}">' for k in client_data_map.keys()])}
                </datalist>
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
                        <td id="ui-total-discount" class="calc-val" style="padding:10px; color:#b76200;">$0</td>
                        <td></td>
                    </tr>
                    <tr class="calc-row-balance">
                        <td colspan="2" style="text-align:right; font-weight:700; padding:10px;">TOTAL FEES:</td>
                        <td id="ui-total-balance" class="calc-val" style="padding:10px;">$0</td>
                        <td></td>
                    </tr>
                </tfoot>
            </table>

            <div id="actions-container" class="actions-container" style="display:none; flex-direction:column; gap:12px;">
                <div style="display:flex; gap:10px; align-items:center;">
                    <button type="button" class="btn-add-row" onclick="addServiceRow()">+ Add Service Line Item</button>
                    <button type="button" class="btn-add-row btn-action-copy-trigger" onclick="toggleInlineCopyBar(true)">📋 Copy Scope & Fees from Existing Client...</button>
                </div>

                <!-- INLINE CLONE CONTROL TOOLBAR -->
                <div id="inline-copy-toolbar" class="inline-copy-toolbar" style="display:none;">
                    <div style="font-weight:600; font-size:13px; color:#0078d4; margin-bottom:6px;">Copy Scope & Exclusions From Prior Draft:</div>
                    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                        <input type="text" 
                               id="clone-source-input" 
                               list="clone-client-options" 
                               placeholder="Type source client name or QBO ID to copy scope from..." 
                               style="flex-grow:1; min-width:280px; padding:8px 12px; font-size:13px; border:1px solid #cbd5e0; border-radius:4px;">
                        <datalist id="clone-client-options">
                            {clone_options_html}
                        </datalist>
                        <button type="button" onclick="applyClonedScopeFromSource()" class="btn-submit" style="width:auto; padding:8px 16px; font-size:13px;">Apply Scope</button>
                        <button type="button" onclick="toggleInlineCopyBar(false)" class="btn-add-row" style="padding:8px 12px; font-size:13px;">Cancel</button>
                    </div>
                </div>
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

    <!-- WORKSPACE MODE 2: SEASONAL BATCH DASHBOARD -->
    <div id="batch-dashboard-workspace" style="display: none;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px;">
            <div style="display: flex; gap: 10px; flex-grow: 1; max-width: 500px;">
                <input type="text" id="batch-search-input" placeholder="🔍 Search Client, Entity, QBO ID..." onkeyup="filterBatchTableGrid()" style="padding: 10px; font-size: 13px; border: 1px solid #cbd5e0; border-radius: 4px; flex-grow: 1;">
                <select id="batch-format-filter" onchange="filterBatchTableGrid()" style="width: 150px; padding: 10px; font-size: 13px; border: 1px solid #cbd5e0; border-radius: 4px;">
                    <option value="all">All Delivery Formats</option>
                    <option value="electronic">Electronic Only</option>
                    <option value="paper">Paper Only</option>
                </select>
            </div>
            
            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <button type="button" onclick="selectAllBatchRows(true)" class="btn-add-row">Select All Ready</button>
                <button type="button" onclick="selectAllBatchRows(false)" class="btn-add-row">Deselect All</button>
                <button type="button" onclick="toggleBatchBulkCopyToolbar(true)" class="btn-add-row btn-action-copy-trigger">📋 Copy Scope to Selected...</button>
                <button type="button" onclick="executeBatchPipelineSubmission()" class="btn-submit" style="width: auto; padding: 10px 20px;">⚡ Submit Selected Batch</button>
            </div>
        </div>

        <!-- BATCH BULK CLONE CONTROL TOOLBAR -->
        <div id="batch-bulk-copy-toolbar" class="inline-copy-toolbar" style="display:none; margin-bottom: 20px;">
            <div style="font-weight:600; font-size:13px; color:#0078d4; margin-bottom:6px;">Bulk Apply Scope & Exclusions to Checked Batch Clients:</div>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                <input type="text" 
                       id="batch-bulk-source-input" 
                       list="clone-client-options" 
                       placeholder="Select source client or draft package to apply to checked accounts..." 
                       style="flex-grow:1; min-width:280px; padding:8px 12px; font-size:13px; border:1px solid #cbd5e0; border-radius:4px;">
                <button type="button" onclick="applyBatchBulkClonedScope()" class="btn-submit" style="width:auto; padding:8px 16px; font-size:13px;">Apply Scope to Checked</button>
                <button type="button" onclick="toggleBatchBulkCopyToolbar(false)" class="btn-add-row" style="padding:8px 12px; font-size:13px;">Cancel</button>
            </div>
        </div>

        <table class="batch-table">
            <thead>
                <tr>
                    <th style="width: 35px; text-align: center;"><input type="checkbox" onclick="selectAllBatchRows(this.checked)"></th>
                    <th style="width: 80px;">QBO ID</th>
                    <th>Client / Legal Entity Name</th>
                    <th>Class</th>
                    <th>Signers</th>
                    <th style="text-align: right;">Total Fee</th>
                    <th>Format</th>
                    <th>Status</th>
                    <th style="text-align: center; width: 80px;">Actions</th>
                </tr>
            </thead>
            <tbody id="batch-tbody"></tbody>
        </table>

        <div id="batch-summary-bar" style="margin-top: 15px; padding: 12px 15px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; font-size: 13px; color: #4a5568;">
            Select items to view campaign totals.
        </div>
    </div>
</div>

<!-- EDIT DRAFT MODAL OVERLAY -->
<div id="batch-edit-modal" class="modal-overlay">
    <div class="modal-content">
        <button type="button" class="modal-close-btn" onclick="cancelBatchEditModal()">&times;</button>
        <h2 id="modal-client-title" style="margin-top: 0; color: #0078d4;">Edit Draft Parameters</h2>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin-bottom: 20px;">
        
        <div id="modal-workspace-container"></div>

        <div style="margin-top: 25px; display: flex; justify-content: flex-end; gap: 12px;">
            <button type="button" onclick="closeBatchEditModal()" class="btn-submit" style="width: auto; padding: 10px 24px;">Save & Return to Grid</button>
        </div>
    </div>
</div>

<!-- BATCH SUBMISSION PROGRESS OVERLAY -->
<div id="batch-progress-overlay" class="progress-overlay">
    <div class="progress-card">
        <h3 style="margin-top: 0; color: #0078d4;">Executing Batch Transaction Pipeline...</h3>
        <div class="progress-bar-bg">
            <div id="batch-progress-fill" class="progress-bar-fill"></div>
        </div>
        <div id="batch-terminal-log" class="terminal-log">Initializing pipeline...</div>
        <div style="margin-top: 20px; text-align: right;">
            <button type="button" id="btn-close-progress" onclick="location.reload()" class="btn-submit" style="display: none; width: auto; padding: 10px 24px;">Done & Reload Workspace</button>
        </div>
    </div>
</div>

</body>
</html>""")

def handle_generate_preview(form):
    """Phase 2: Renders split preview view with lightweight iframe PDF reference."""
    raw_client_name = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(raw_client_name)
    
    clean_client_title = re.split(r'\s*\(Customer', html.unescape(raw_client_name))[0].strip()
    client_name = raw_client_name

    row_ids = get_form_list(form, "selected_rows")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")
    heal_profile_flag = get_form_val(form, "heal_profile_flag", "false")

    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    meta_co_signer_name = html.unescape(get_form_val(form, "meta_co_signer_name"))
    
    if meta_co_signer_name.lower().strip() in ["none", "null", "single", "n/a"] or raw_sig.lower().strip() in ["none", "null", "single", "n/a"]:
        meta_sig = meta_co_signer_name = ""

    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    heal_street = get_form_val(form, "heal_street")
    heal_city = get_form_val(form, "heal_city")
    heal_state = get_form_val(form, "heal_state")
    heal_zip = get_form_val(form, "heal_zip")

    prior_estimate_id = ""
    existing_draft = {}
    draft_path = os.path.join(DRAFTS_DIR, f"client_{client_qbo_id}.json")
    is_locked = False

    try:
        is_locked, _ = is_draft_locked(draft_path)
        if os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as df:
                existing_draft = json.load(df)
                prior_estimate_id = existing_draft.get("estimate_id", "")
    except Exception as de:
        print(f"DEBUG: Draft reading failure: {str(de)}", file=sys.stderr)

    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip()
    if not friendly_name and existing_draft.get("friendly_name"):
        friendly_name = html.unescape(existing_draft.get("friendly_name", "")).strip()
    if not friendly_name:
        friendly_name = clean_client_title

    heal_legal_name = html.unescape(get_form_val(form, "heal_legal_name")).strip()
    if not heal_legal_name and existing_draft.get("heal_legal_name"):
        heal_legal_name = html.unescape(existing_draft.get("heal_legal_name", "")).strip()
    if not heal_legal_name:
        heal_legal_name = clean_client_title

    if not heal_street:
        try:
            fresh_c = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
            c_addr = fresh_c.get("BillAddr", {})
            heal_street, heal_city = c_addr.get("Line1", ""), c_addr.get("City", "")
            heal_state, heal_zip = c_addr.get("CountrySubDivisionCode", ""), c_addr.get("PostalCode", "")
        except Exception as fe:
            print(f"DEBUG: QBO fallback data extraction failed: {str(fe)}", file=sys.stderr)

    posted_oos = {k: get_form_val(form, k) for k in form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}
    if not posted_oos and existing_draft.get("out_of_scope_items"):
        posted_oos = existing_draft["out_of_scope_items"]

    disk_rows_list = existing_draft.get("rows", [])

    processed_rows = []
    for idx, rid in enumerate(row_ids):
        item_id = get_form_val(form, f"row_item_id_{rid}")
        svc = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}"))
        fee_val = get_form_val(form, f"row_fee_{rid}", "")
        notes_val = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}"))
        bp_val = get_form_val(form, f"row_bp_{rid}", "individual")

        if (fee_val is None or fee_val.strip() == "") and idx < len(disk_rows_list):
            fee_val = disk_rows_list[idx].get("fee", "0")
            if not notes_val:
                notes_val = disk_rows_list[idx].get("notes", "")

        processed_rows.append({
            "item_id": item_id,
            "service": svc,
            "fee": str(int(round(float(fee_val)))) if (fee_val and fee_val.strip()) else "0",
            "notes": notes_val,
            "bp": bp_val
        })

    # Save active workspace parameters to disk as single source of truth
    if not is_locked:
        try:
            os.makedirs(DRAFTS_DIR, exist_ok=True)
            draft_payload = {
                "estimate_date_option": estimate_date_option,
                "friendly_name": friendly_name,
                "heal_legal_name": heal_legal_name,
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
                "rows": processed_rows,
                "delivery_format": existing_draft.get("delivery_format", "electronic")
            }
            with open(draft_path, "w", encoding="utf-8") as df:
                json.dump(draft_payload, df, indent=2)
        except Exception as de:
            print(f"DEBUG: Server-side draft writing handling: {str(de)}", file=sys.stderr)

    # Clean, lightweight iframe source URL (reads full payload from disk)
    iframe_src = f"{SCRIPT_URL}?action=render_live_pdf&client_name={urllib.parse.quote(client_name)}"

    hidden_checklist_fields = f'<input type="hidden" name="estimate_date_option" value="{html.escape(estimate_date_option)}">\n'
    for k, v in posted_oos.items():
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
            <input type="hidden" name="heal_legal_name" value="{html.escape(heal_legal_name)}">
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
            <input type="hidden" name="row_fee_{rid}" value="{int(round(float((get_form_val(form, f"row_fee_{rid}") or "0").replace('$', '').replace(',', '').strip())))}">
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

def handle_save_draft_only(form):
    """AJAX Handler: Writes/updates client draft JSON on disk without rendering a preview page."""
    raw_client_name = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(raw_client_name)
    
    clean_client_title = re.split(r'\s*\(Customer', html.unescape(raw_client_name))[0].strip()
    row_ids = get_form_list(form, "selected_rows")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")
    heal_profile_flag = get_form_val(form, "heal_profile_flag", "false")

    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    meta_co_signer_name = html.unescape(get_form_val(form, "meta_co_signer_name"))
    
    if meta_co_signer_name.lower().strip() in ["none", "null", "single", "n/a"] or raw_sig.lower().strip() in ["none", "null", "single", "n/a"]:
        meta_sig = meta_co_signer_name = ""

    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    heal_street = get_form_val(form, "heal_street")
    heal_city = get_form_val(form, "heal_city")
    heal_state = get_form_val(form, "heal_state")
    heal_zip = get_form_val(form, "heal_zip")

    draft_path = os.path.join(DRAFTS_DIR, f"client_{client_qbo_id}.json")
    existing_draft = {}
    is_locked = False

    try:
        is_locked, _ = is_draft_locked(draft_path)
        if os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as df:
                existing_draft = json.load(df)
    except Exception as de:
        print(f"DEBUG: Draft reading failure: {str(de)}", file=sys.stderr)

    if is_locked:
        render_pipeline_error(form, "Draft is locked.", http_code=400)
        return

    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip() or clean_client_title
    heal_legal_name = html.unescape(get_form_val(form, "heal_legal_name")).strip() or clean_client_title

    posted_oos = {k: get_form_val(form, k) for k in form if k.startswith("out_of_scope_item_") or k.startswith("custom_")}

    processed_rows = []
    for rid in row_ids:
        item_id = get_form_val(form, f"row_item_id_{rid}")
        svc = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}"))
        fee_val = get_form_val(form, f"row_fee_{rid}", "0")
        notes_val = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}"))
        bp_val = get_form_val(form, f"row_bp_{rid}", "individual")

        processed_rows.append({
            "item_id": item_id,
            "service": svc,
            "fee": str(int(round(float(fee_val)))) if (fee_val and fee_val.strip()) else "0",
            "notes": notes_val,
            "bp": bp_val
        })

    try:
        os.makedirs(DRAFTS_DIR, exist_ok=True)
        
        # Sourced delivery_format override if passed via AJAX
        target_delivery_fmt = get_form_val(form, "delivery_format") or existing_draft.get("delivery_format", "electronic")

        draft_payload = {
            "estimate_date_option": estimate_date_option,
            "friendly_name": friendly_name,
            "heal_legal_name": heal_legal_name,
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
            "estimate_id": existing_draft.get("estimate_id", ""),
            "rows": processed_rows,
            "delivery_format": target_delivery_fmt
        }
        with open(draft_path, "w", encoding="utf-8") as df:
            json.dump(draft_payload, df, indent=2)

        print("Content-Type: application/json\n")
        print(json.dumps({"status": "success", "qbo_id": client_qbo_id, "draft": draft_payload}))
    except Exception as e:
        render_pipeline_error(form, str(e), http_code=500)

def build_salutation_name(friendly_name, co_signer_name=""):
    """Extracts first names and builds a friendly salutation (e.g., 'Jack and Jane')."""
    prefixes = ("dr.", "dr", "mr.", "mr", "mrs.", "mrs", "ms.", "ms", "prof.", "prof")

    def clean_first_name(name_str):
        if not name_str:
            return ""
        tokens = name_str.strip().split()
        if tokens and tokens[0].lower() in prefixes:
            tokens = tokens[1:]
        return tokens[0] if tokens else ""

    primary_clean = friendly_name.strip() if friendly_name else ""
    co_signer_clean = co_signer_name.strip() if co_signer_name else ""

    if " & " in primary_clean:
        parts = primary_clean.split(" & ", 1)
        p1 = clean_first_name(parts[0])
        p2 = clean_first_name(parts[1])
        return f"{p1} and {p2}" if p1 and p2 else p1
    elif " and " in primary_clean.lower():
        parts = re.split(r'\s+and\s+', primary_clean, flags=re.IGNORECASE, maxsplit=1)
        p1 = clean_first_name(parts[0])
        p2 = clean_first_name(parts[1])
        return f"{p1} and {p2}" if p1 and p2 else p1

    primary_first = clean_first_name(primary_clean)
    co_signer_first = clean_first_name(co_signer_clean)

    if primary_first and co_signer_first and primary_first.lower() != co_signer_first.lower():
        return f"{primary_first} and {co_signer_first}"

    return primary_first or primary_clean

# ==========================================
# REPORTLAB PDF GENERATION LEG (PURE / STATELESS)
# ==========================================
def xml_safe_escape(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = unicodedata.normalize('NFKD', text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for tag in ["strong", "b", "i", "u"]:
        text = text.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return text.replace("&lt;br/&gt;", "<br/>").replace("&lt;br&gt;", "<br/>")

def compile_reportlab_pdf_buffer(form, include_esign_tags=False):
    """Pure rendering function: Compiles Markdown template into ReportLab PDF binary buffer."""
    raw_client_name = get_form_val(form, "client_name", "Unknown Client")
    row_ids = get_form_list(form, "selected_rows")
    if not row_ids:
        row_ids = [k.replace("row_item_id_", "") for k in form if k.startswith("row_item_id_")]

    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type", "single")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    meta_co_signer_name = html.unescape(get_form_val(form, "meta_co_signer_name"))
    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    clean_client_title = re.split(r'\s*\(Customer', html.unescape(raw_client_name))[0].strip()
    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip() or clean_client_title
    legal_name = html.unescape(get_form_val(form, "heal_legal_name")).strip() or clean_client_title

    street = get_form_val(form, "heal_street")
    city = get_form_val(form, "heal_city")
    state = get_form_val(form, "heal_state")
    zip_val = get_form_val(form, "heal_zip")

    if not street:
        try:
            c_id = extract_qbo_id(raw_client_name)
            c_data = qbo_api_request(f"customer/{c_id}").get("Customer", {})
            addr_obj = c_data.get("BillAddr", {})
            street, city = addr_obj.get('Line1',''), addr_obj.get('City','')
            state, zip_val = addr_obj.get('CountrySubDivisionCode',''), addr_obj.get('PostalCode','')
        except Exception:
            street = city = state = zip_val = ""

    address_parts = [p.strip() for p in [street, city, state, zip_val] if p and p.strip()]
    billing_address = ", ".join(address_parts) if address_parts else "<i>[Billing Address Sourced on Execution]</i>"
    greeting_name = build_salutation_name(friendly_name, meta_co_signer_name)

    try:
        with open(ENGAGEMENT_TEMPLATE, "r", encoding="utf-8") as f:
            raw_markdown = f.read()
    except FileNotFoundError:
        raw_markdown = "# Tarrant Advisors LLC\n1875 Campus Commons Dr., Suite 203, Reston, VA 20191\n75 Port City Landing, Suite 110, Mt. Pleasant, SC 29464\n## {{TAX_YEAR}} ENGAGEMENT AGREEMENT\n{{DYNAMIC_ESTIMATES_TABLE}}\n{{DYNAMIC_SERVICES_TEXT}}"

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
            fee = float(str(raw_fee_val).replace('$', '').replace(',', '').strip()) if (raw_fee_val and str(raw_fee_val).strip()) else 0.0
        except ValueError:
            fee = 0.0

        svc_lower = raw_svc.lower()
        if "discount" in svc_lower or "referral" in svc_lower:
            discount_val += abs(fee)
        elif "deposit" in svc_lower or "retainer" in svc_lower:
            deposit_val += abs(fee)
        else:
            table_rows_data.append([raw_svc, f"${int(round(fee)):,}"])
            total_base += fee

        if notes:
            services_annotation_blocks.append(f"• <strong>{raw_svc}:</strong> {xml_safe_escape(notes)}")
        else:
            services_annotation_blocks.append(f"• <strong>{raw_svc}</strong>")

    total_net = total_base - discount_val
    if discount_val > 0: 
        table_rows_data.append(["Client Discount:", f"-${int(round(discount_val)):,}"])
    
    table_rows_data.append(["TOTAL FEES:", f"${int(round(total_net)):,}"])
    
    if deposit_val > 0: 
        table_rows_data.append(["DEPOSIT DUE UPON COMMENCEMENT OF SERVICE:", f"${int(round(deposit_val)):,}"])

    is_org_type = meta_ent.lower() in ["s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"]

    out_of_scope_list = []
    
    oos_raw = form.get("out_of_scope_items")
    if isinstance(oos_raw, str) and oos_raw.strip().startswith("{"):
        try:
            oos_raw = json.loads(oos_raw)
        except Exception:
            pass

    if isinstance(oos_raw, dict):
        out_of_scope_list = [
            str(v).strip() for v in oos_raw.values() if v and str(v).strip()
        ]
    
    for k in form:
        if k.startswith("out_of_scope_item_") or k.startswith("custom_"):
            val = get_form_val(form, k)
            if val and val.strip() and val.strip() not in out_of_scope_list:
                out_of_scope_list.append(val.strip())
    
    jinja_tmpl = Template(raw_markdown)
    markdown_content = jinja_tmpl.render(
        TAX_YEAR=TAX_YEAR,
        NEXT_YEAR=NEXT_YEAR,
        TODAY_DATE=datetime.date.today().strftime('%B %d, %Y'),
        CLIENT_ADDRESS=billing_address,
        CLIENT_LEGAL_NAME=xml_safe_escape(legal_name),
        FRIENDLY_NAME=xml_safe_escape(friendly_name),
        GREETING_NAME=xml_safe_escape(greeting_name),
        meta_entity_type=meta_ent.lower(),
        out_of_scope_items=out_of_scope_list,
        DYNAMIC_ESTIMATES_TABLE="{{DYNAMIC_ESTIMATES_TABLE}}",
        DYNAMIC_SERVICES_TEXT="{{DYNAMIC_SERVICES_TEXT}}"
    )

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40, title=f"{TAX_YEAR} Tax Engagement Agreement - {legal_name}")
    styles = getSampleStyleSheet()

    HEADER_BLUE = colors.HexColor('#0078d4')

    company_style = ParagraphStyle(
        'CompanyHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=HEADER_BLUE
    )

    address_style = ParagraphStyle(
        'AddressHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=11,
        textColor=HEADER_BLUE
    )

    body_style = ParagraphStyle('CustomBody', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#333333'))
    h1_style = ParagraphStyle('CustomH1', parent=styles['Heading1'], fontSize=20, leading=24, textColor=HEADER_BLUE, spaceAfter=12)
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

    # ---------------------------------------------------------
    # STRICT HEADER PARSING: Title + Company Addresses ONLY
    # ---------------------------------------------------------
    header_text_nodes = []
    content_lines = markdown_content.split('\n')
    filtered_lines = []

    company_title_found = False
    
    for line in content_lines:
        line_str = line.strip()
        if not line_str or line_str.startswith("{%") or line_str.startswith("%}"):
            continue

        # 1. Match company title line (# Tarrant Advisors LLC)
        if line_str.startswith("# ") and not company_title_found:
            company_title_found = True
            header_text_nodes.append(Paragraph(xml_safe_escape(line_str[2:].strip()), company_style))
            header_text_nodes.append(Spacer(1, 3))
            continue
        
        # 2. Match company office addresses ONLY (stop when hitting ##, Date, or Client)
        if company_title_found and len(header_text_nodes) < 5:
            if line_str.startswith("##") or line_str.startswith("<b>Date:") or line_str.startswith("Date:"):
                filtered_lines.append(line)
                company_title_found = False # Stop adding to header table
                continue
            header_text_nodes.append(Paragraph(xml_safe_escape(line_str), address_style))
            continue

        filtered_lines.append(line)

    # Fallback safety if template header was missing
    if not header_text_nodes:
        header_text_nodes = [
            Paragraph("Tarrant Advisors LLC", company_style),
            Spacer(1, 3),
            Paragraph("1875 Campus Commons Dr., Suite 203, Reston, VA 20191", address_style),
            Paragraph("75 Port City Landing, Suite 110, Mt. Pleasant, SC 29464", address_style)
        ]

    # ---------------------------------------------------------
    # PROPORTIONAL LOGO SCALING
    # ---------------------------------------------------------
    logo_path = os.environ.get("DOCUMENT_ROOT", ".") + "/images/logo.png"
    if os.path.exists(logo_path):
        logo_img = Image(logo_path)
        max_w, max_h = 160.0, 60.0
        aspect = logo_img.imageWidth / float(logo_img.imageHeight)
        
        if aspect > (max_w / max_h):
            logo_img.drawWidth = max_w
            logo_img.drawHeight = max_w / aspect
        else:
            logo_img.drawHeight = max_h
            logo_img.drawWidth = max_h * aspect

        logo_img.hAlign = 'RIGHT'
    else:
        logo_img = Paragraph("", styles['Normal'])

    # Build Top Header Table
    header_table = Table([[header_text_nodes, logo_img]], colWidths=[370, 160])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))

    story.append(header_table)
    story.append(Spacer(1, 10))

    # ---------------------------------------------------------
    # RENDER BODY CONTENT IN CORRECT SEQUENCE
    # ---------------------------------------------------------
    for line in filtered_lines:
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
                # Single item: strip leading bullet and render standalone
                if len(services_annotation_blocks) == 1:
                    single_block = services_annotation_blocks[0]
                    if single_block.startswith("• "):
                        single_block = single_block[2:]
                    story.append(Paragraph(single_block, body_style))
                    story.append(Spacer(1, 4))
                # Multiple items: render each block with its bullet point
                else:
                    for block in services_annotation_blocks:
                        # Ensure bullet point exists for multi-line items
                        bullet_block = block if block.startswith("• ") else f"• {block}"
                        story.append(Paragraph(bullet_block, body_style))
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
    signer1_label = f"<strong>{xml_safe_escape(friendly_name)}<br/>Signing on behalf of {xml_safe_escape(legal_name)}</strong>" if is_org_type else f"<strong>{xml_safe_escape(friendly_name)}</strong>"

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
    """Phase 2: Streams PDF binary to iframe preview by reading active draft state from disk."""
    raw_client_name = get_form_val(form, "client_name")
    
    if raw_client_name:
        try:
            c_id = extract_qbo_id(raw_client_name)
            draft_path = os.path.join(DRAFTS_DIR, f"client_{c_id}.json")
            if os.path.exists(draft_path):
                with open(draft_path, "r", encoding="utf-8") as df:
                    disk_draft = json.load(df)
                    
                # Hydrate form parameters in-memory directly from disk draft JSON
                form["friendly_name"] = [disk_draft.get("friendly_name", "")]
                form["heal_legal_name"] = [disk_draft.get("heal_legal_name", "")]
                form["heal_street"] = [disk_draft.get("heal_street", "")]
                form["heal_city"] = [disk_draft.get("heal_city", "")]
                form["heal_state"] = [disk_draft.get("heal_state", "")]
                form["heal_zip"] = [disk_draft.get("heal_zip", "")]
                form["meta_entity_type"] = [disk_draft.get("meta_entity_type", "individual")]
                form["meta_signature_type"] = [disk_draft.get("meta_signature_type", "single")]
                form["meta_additional_signer"] = [disk_draft.get("meta_additional_signer", "")]
                form["meta_co_signer_name"] = [disk_draft.get("meta_co_signer_name", "")]
                
                if disk_draft.get("rows"):
                    form["selected_rows"] = []
                    for idx, r in enumerate(disk_draft["rows"]):
                        rid = str(idx + 1)
                        form["selected_rows"].append(rid)
                        form[f"row_item_id_{rid}"] = [r.get("item_id", "")]
                        form[f"row_service_{rid}"] = [r.get("service", "")]
                        form[f"row_fee_{rid}"] = [r.get("fee", "0")]
                        form[f"row_notes_{rid}"] = [r.get("notes", "")]
                        form[f"row_bp_{rid}"] = [r.get("bp", "individual")]
                        
                if disk_draft.get("out_of_scope_items"):
                    form["out_of_scope_items"] = disk_draft["out_of_scope_items"]
        except Exception as ex:
            print(f"DEBUG: Preview disk draft read error: {str(ex)}", file=sys.stderr)

    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    sys.stdout.buffer.write(b"Content-Type: application/pdf\n\n")
    sys.stdout.buffer.write(generated_buffer.read())

def handle_download_pdf(form, prefix="DRAFT"):
    """Unified handler for PDF downloads (Draft or Final)."""
    client_name = get_form_val(form, "client_name", "Unknown Client")
    clean_client_title = re.split(r'\s*\(Customer', html.unescape(client_name))[0].strip()
    legal_name = html.unescape(get_form_val(form, "heal_legal_name")).strip() or clean_client_title
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"Tax Agreement {legal_name} ({prefix} {timestamp_str}).pdf"
    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    
    sys.stdout.buffer.write(b"Content-Type: application/pdf\n")
    sys.stdout.buffer.write(f"Content-Disposition: attachment; filename={urllib.parse.quote(filename)}\n\n".encode('utf-8'))
    sys.stdout.buffer.write(generated_buffer.read())

# ==========================================
# TRANSACTION PIPELINE (PHASE 3)
# ==========================================
def execute_transactional_pipeline(form):
    """Executes QBO Estimate creation and Adobe Sign routing."""
    raw_client_name = get_form_val(form, "client_name")
    client_name = html.unescape(raw_client_name)
    client_qbo_id = extract_qbo_id(client_name)
    row_ids = get_form_list(form, "selected_rows")
    friendly_name = get_form_val(form, "friendly_name")
    heal_legal_name = get_form_val(form, "heal_legal_name")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")

    heal_flag = get_form_val(form, "heal_profile_flag", "false")
    raw_sig = get_form_val(form, "meta_additional_signer") or get_form_val(form, "meta_signature_type")
    meta_sig = raw_sig.strip() if "@" in raw_sig else ""
    meta_co_signer_name = html.unescape(get_form_val(form, "meta_co_signer_name"))
    meta_ent = get_form_val(form, "meta_entity_type", "individual")

    delivery_method = get_form_val(form, "delivery_method")
    is_paper_mode = (delivery_method == "paper")
    is_org_type = meta_ent.lower() in ["s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"]

    # ---------------------------------------------------------------------
    # SAFE PRIOR ESTIMATE DELETION LOGIC
    # ---------------------------------------------------------------------
    prior_estimate_id = get_form_val(form, "prior_estimate_id").strip()
    draft_path = os.path.join(DRAFTS_DIR, f"client_{client_qbo_id}.json")
    is_locked, _ = is_draft_locked(draft_path)

    # Fallback to reading draft file if prior_estimate_id was omitted from form payload
    if not prior_estimate_id and os.path.exists(draft_path):
        try:
            with open(draft_path, "r", encoding="utf-8") as df:
                disk_draft = json.load(df)
                prior_estimate_id = str(disk_draft.get("estimate_id", "")).strip()
        except Exception as e:
            print(f"DEBUG: Could not read prior estimate ID from draft: {e}", file=sys.stderr)

    if prior_estimate_id:
        try:
            prior_txn = qbo_api_request(f"estimate/{prior_estimate_id}").get("Estimate", {})
            prior_customer_id = str(prior_txn.get("CustomerRef", {}).get("value", ""))
            prior_sync_token = prior_txn.get("SyncToken")

            # Safety check: Ensure estimate belongs to THIS customer before deleting
            if prior_customer_id == str(client_qbo_id) and prior_sync_token:
                qbo_api_request("estimate?operation=delete", method="POST", payload={
                    "Id": prior_estimate_id, 
                    "SyncToken": prior_sync_token
                })
                print(f"DEBUG: Deleted superseded Estimate #{prior_estimate_id} for Customer {client_qbo_id}", file=sys.stderr)
        except Exception as rollback_err:
            print(f"Warning: Could not wipe prior Estimate #{prior_estimate_id}: {str(rollback_err)}", file=sys.stderr)

    try:
        fresh_customer = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
    except Exception as e:
        return render_pipeline_error(form, f"Pipeline Execution Halted: Unable to verify Customer record from QBO. ({str(e)})")

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
            return render_pipeline_error(form, f"Auto-Sync Data Healing Failure: Unable to update Customer record in QBO. ({str(e)})")

    estimate_lines = []
    deposit_val = 0.0

    disk_rows_list = []
    if os.path.exists(draft_path):
        try:
            with open(draft_path, "r", encoding="utf-8") as df:
                disk_draft = json.load(df)
                disk_rows_list = disk_draft.get("rows", [])
        except Exception:
            pass

    for idx, rid in enumerate(row_ids):
        item_id = get_form_val(form, f"row_item_id_{rid}")
        svc_name = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}", "Service Listing"))
        raw_fee_val = get_form_val(form, f"row_fee_{rid}", "")
        notes = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}"))

        if (raw_fee_val is None or raw_fee_val.strip() == "") and idx < len(disk_rows_list):
            raw_fee_val = disk_rows_list[idx].get("fee", "0")
            if not notes:
                notes = disk_rows_list[idx].get("notes", "")

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
        return render_pipeline_error(form, "Pipeline Halted: Add at least one Service Line Item before submitting.")

    estimate_payload = {
        "CustomerRef": {"value": client_qbo_id},
        "TxnStatus": "Pending",
        "Line": estimate_lines,
        "CustomField": [{"DefinitionId": "1", "StringValue": "JOINT" if (meta_sig and "@" in meta_sig) else "SINGLE", "Name": "Signers"}]
    }

    if deposit_val > 0:
        estimate_payload["PrivateNote"] = f"Deposit Due: ${int(round(deposit_val)):,}"

    if estimate_date_option == "next_year":
        next_year = datetime.date.today().year + 1
        estimate_payload["TxnDate"] = f"{next_year}-01-01"

    try:
        qbo_response = qbo_api_request("estimate", method="POST", payload=estimate_payload)
        generated_estimate = qbo_response.get("Estimate", {})
        estimate_id = generated_estimate.get("Id")
        sync_token = generated_estimate.get("SyncToken")
    except Exception as e:
        return render_pipeline_error(form, f"QuickBooks Error: Failed to generate transaction record. ({str(e)})")

    # ---------------------------------------------------------------------
    # SAFE DRAFT UNLOCKING, UPDATING & LOCKING
    # ---------------------------------------------------------------------
    try:
        if os.path.exists(draft_path):
            unlock_draft(draft_path)  # Restores 'w' permission to avoid Errno 13
            with open(draft_path, "r", encoding="utf-8") as df:
                active_draft = json.load(df)
            active_draft["estimate_id"] = estimate_id
            with open(draft_path, "w", encoding="utf-8") as df:
                json.dump(active_draft, df, indent=2)
            lock_draft(draft_path)    # Re-locks draft file permissions
    except Exception as de:
        print(f"DEBUG: Post-transaction draft update failed: {str(de)}", file=sys.stderr)

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
        return render_pipeline_error(form, f"Adobe Sign Routing Error: Contract delivery failed. QuickBooks transaction backed out. Details: {adobe_error_context}")

    if is_ajax_request(form):
        print("Content-Type: application/json\n")
        print(json.dumps({
            "status": "success",
            "estimate_id": estimate_id,
            "qbo_id": client_qbo_id,
            "delivery_method": delivery_method
        }))
        return

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
            ("heal_legal_name", heal_legal_name),
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
                (f"row_fee_{rid}", get_form_val(form, f"row_fee_{rid}", "0")),
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
    elif action == "save_draft_only":
        handle_save_draft_only(form_data)
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
                unlock_draft(os.path.join(DRAFTS_DIR, f"client_{c_id}.json"))
            except Exception as ex:
                print(f"DEBUG: Could not unlock draft on revert: {str(ex)}", file=sys.stderr)
        render_phase1_workspace(preserved_form=form_data)
    else:
        render_phase1_workspace()