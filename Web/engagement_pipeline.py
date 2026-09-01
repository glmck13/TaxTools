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
import base64
import subprocess
import resend

from jinja2 import Template

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# CONFIGURATION & GLOBAL STATE
# ==========================================

PIPELINE_SANDBOX = os.environ.get("PIPELINE_SANDBOX")
if PIPELINE_SANDBOX:
    ENABLE_BATCH_MODE = True
    JS_FILE = "engagement_sandbox.js"
    CSS_FILE = "engagement_sandbox.css"
    ENGAGEMENT_TEMPLATE = "engagement_sandbox.md"
    SERVICES_TEMPLATE = "services_sandbox.md"
    OWNER_EMAIL = "dianna@tarrantadvisors.com"
    OWNER_SIGNATURE = "Where's Waldo"
    OWNER_CORPNAME = "Software Services"
    CARBON_COPIES = []
    DRAFTS_DIR = os.environ.get("DOCUMENT_ROOT", ".") + "/sandbox"
else:
    ENABLE_BATCH_MODE = False
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

ORGANIZATION_ENTITY_TYPES = {
    "sm_llc",
    "s_corp",
    "partnership",
    "c_corp",
    "non_profit",
    "trust",
    "organization",
}

TAG_NEW   = "[+] "
TAG_DRAFT = "[D] "
TAG_FINAL = "[F] "

def sanitize_fee_int(raw_fee):
    """Converts any fee input ('$1,000.00', '1000.00', 1000) directly to a clean integer."""
    if raw_fee is None:
        return 0
    clean_str = str(raw_fee).replace('$', '').replace(',', '').strip()
    if not clean_str:
        return 0
    try:
        return int(round(float(clean_str)))
    except (ValueError, TypeError):
        return 0

def get_asset_url(filename):
    subfolder = "js" if filename.endswith(".js") else "css"
    filepath = os.path.join(os.environ.get("DOCUMENT_ROOT", "."), subfolder, filename)
    if os.path.exists(filepath):
        mtime = int(os.path.getmtime(filepath))
        return f"{filename}?v={mtime}"
    return f"{filename}?v={int(time.time())}"

def get_form_val(form, key, default=""):
    if not form or key not in form:
        return default
    val = form[key]
    if isinstance(val, list):
        return str(val[0]) if val else default
    return str(val) if val is not None else default

def get_form_list(form, key):
    if not form or key not in form:
        return []
    val = form[key]
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]

def is_ajax_request(form):
    header_ajax = os.environ.get("HTTP_X_REQUESTED_WITH", "").lower() == "xmlhttprequest"
    param_ajax = get_form_val(form, "ajax", "false").lower() in ["true", "1", "yes"]
    return header_ajax or param_ajax

def render_pipeline_error(form, error_msg, http_code=400):
    if is_ajax_request(form):
        status_header = "400 Bad Request" if http_code == 400 else "500 Internal Server Error"
        print(f"Status: {status_header}")
        print("Content-Type: application/json\n")
        print(json.dumps({"status": "error", "message": error_msg}))
        return
    render_phase1_workspace(error_msg=error_msg)

def get_draft_file_path(qbo_id, engagement_id):
    return os.path.join(DRAFTS_DIR, f"{qbo_id}_{engagement_id}.json")

def allocate_next_engagement_id(qbo_id):
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    existing_ids = []
    prefix = f"{qbo_id}_"
    
    for filename in os.listdir(DRAFTS_DIR):
        if filename.startswith(prefix) and filename.endswith(".json"):
            eng_part = filename[len(prefix):-5]
            if eng_part.isdigit():
                existing_ids.append(int(eng_part))
                
    if not existing_ids:
        return "1"
    return str(max(existing_ids) + 1)

def is_draft_locked(draft_path):
    if not os.path.exists(draft_path):
        return False, None
    st = os.stat(draft_path)
    is_readonly = not bool(st.st_mode & (stat.S_IWUSR | stat.S_IWGRP))
    mtime_str = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%B %d, %Y at %I:%M %p")
    return is_readonly, mtime_str

def lock_draft(draft_path):
    if os.path.exists(draft_path):
        current_mode = os.stat(draft_path).st_mode
        os.chmod(draft_path, current_mode & ~(stat.S_IWUSR | stat.S_IWGRP))

def unlock_draft(draft_path):
    if os.path.exists(draft_path):
        current_mode = os.stat(draft_path).st_mode
        os.chmod(draft_path, current_mode | (stat.S_IWUSR | stat.S_IWGRP))

def load_exposed_services_from_template():
    services = []
    template_path = SERVICES_TEMPLATE
    
    if not os.path.exists(template_path):
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
            fee_val = 0
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
                
                if id_match:
                    item_id = id_match.group(1)
                elif type_match:
                    entity_type = type_match.group(1).lower()
                elif fee_match:
                    fee_val = sanitize_fee_int(fee_match.group(1))
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

def qbo_api_request(endpoint, method="GET", payload=None):
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
    if not client_name_str:
        raise ValueError("Client selection string is empty.")

    if client_name_str.isdigit():
        return client_name_str
    
    if ":" in client_name_str and not ("QBO ID:" in client_name_str or "Customer ID:" in client_name_str):
        parts = client_name_str.split(":")
        if parts[0].isdigit():
            return parts[0]

    match = re.search(r'(?:QBO|Customer)\s*ID:\s*(\d+)', client_name_str, re.IGNORECASE)
    if match:
        return match.group(1)
    
    match_alt = re.search(r'^(\d+):', client_name_str)
    if match_alt:
        return match_alt.group(1)
    
    clean_name = re.sub(r'^\[[A-Za-z0-9]+\]\s*', '', client_name_str)
    clean_name = re.sub(r'\s*\((?:QBO|Customer)\s*ID:.*?\)', '', clean_name)
    clean_name = clean_name.split(' — ')[0].strip()
    
    escaped_name = clean_name.replace("'", "\\'")
    try:
        query_res = qbo_api_request(f"query?query=select Id from Customer where DisplayName='{escaped_name}'")
        custs = query_res.get("QueryResponse", {}).get("Customer", [])
        if custs:
            return str(custs[0]["Id"])
    except Exception:
        pass

    raise ValueError(f"Unable to parse unique Customer ID from selection: {client_name_str}")

def parse_acct_num(acct_num_str):
    meta = {
        "entity_type": "individual",
        "friendly_name": "",
        "primary_signer_email": "",
        "co_signer_name": "",
        "co_signer_email": ""
    }
    if not acct_num_str or not acct_num_str.strip():
        return meta

    try:
        data = json.loads(acct_num_str.strip())
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
        print(f"DEBUG: QBO Notes is not valid JSON or failed parsing: {str(e)}", file=sys.stderr)

    return meta

def compile_acct_num(friendly_name, primary_email, co_signer_name="", co_signer_email="", entity_type="individual"):
    CLEAR_KEYWORDS = {"none", "null", "single", "n/a", ""}
    
    clean_p_name = friendly_name.strip()
    clean_p_email = primary_email.strip()
    clean_c_name = co_signer_name.strip()
    clean_c_email = co_signer_email.strip()

    signers = [
        {
            "name": clean_p_name,
            "email": clean_p_email
        }
    ]
    
    has_co_name = clean_c_name.lower() not in CLEAR_KEYWORDS
    has_co_email = clean_c_email.lower() not in CLEAR_KEYWORDS

    if has_co_name or has_co_email:
        signers.append({
            "name": clean_c_name if has_co_name else "",
            "email": clean_c_email if has_co_email else ""
        })

    payload = {
        "entity": entity_type.strip().lower(),
        "signers": signers
    }
    return json.dumps(payload)

def extract_base_out_of_scope_boilerplate():
    try:
        if os.path.exists(ENGAGEMENT_TEMPLATE):
            with open(ENGAGEMENT_TEMPLATE, "r", encoding="utf-8") as f:
                content = f.read()
            
            else_match = re.search(r'\{%\s*else\s*%\}(.*?)\{%\s*endif\s*\%}', content, re.DOTALL)
            if else_match:
                raw_block = else_match.group(1).strip()
                items = [re.sub(r'^\*\s*', '', line.strip()).strip() for line in raw_block.split("\n") if line.strip().startswith("*")]
                if items:
                    return items
    except Exception as e:
        print(f"ERROR: Failed parsing out-of-scope items: {str(e)}", file=sys.stderr)
        
    return []

def extract_out_of_scope_dict(form, existing_draft_oos=None):
    oos_submitted = get_form_val(form, "oos_submitted") == "true"

    if not oos_submitted:
        return existing_draft_oos

    oos_dict = {}
    for k in form:
        if k.startswith("out_of_scope_item_") or "custom" in k:
            val = get_form_val(form, k).strip()
            if val:
                oos_dict[k] = val

    return oos_dict

def populate_form_from_disk_draft(form, c_id, eng_id):
    """Rehydrates form fields directly from the saved JSON draft file on disk."""
    draft_path = get_draft_file_path(c_id, eng_id)
    if not os.path.exists(draft_path):
        return form

    try:
        with open(draft_path, "r", encoding="utf-8") as df:
            disk_draft = json.load(df)

        p_signer = disk_draft.get("primary_signer", {}) if isinstance(disk_draft.get("primary_signer"), dict) else {}
        co_signer = disk_draft.get("co_signer", {}) if isinstance(disk_draft.get("co_signer"), dict) else {}
        b_addr = disk_draft.get("billing_address", {}) if isinstance(disk_draft.get("billing_address"), dict) else {}

        form["friendly_name"] = [p_signer.get("friendly_name", "")]
        form["legal_name"] = [p_signer.get("legal_name", "")]
        form["primary_signer_email"] = [p_signer.get("email", "")]
        form["phone"] = [disk_draft.get("phone", "")]

        form["street"] = [b_addr.get("street", "")]
        form["city"] = [b_addr.get("city", "")]
        form["state"] = [b_addr.get("state", "")]
        form["zip"] = [b_addr.get("zip", "")]

        form["entity_type"] = [disk_draft.get("entity_type", "individual")]
        form["co_signer_email"] = [co_signer.get("email", "")]
        form["co_signer_name"] = [co_signer.get("name", "")]

        if disk_draft.get("rows"):
            form["selected_rows"] = []
            for idx, r in enumerate(disk_draft["rows"]):
                rid = str(idx + 1)
                form["selected_rows"].append(rid)
                form[f"row_item_id_{rid}"] = [r.get("item_id", "")]
                form[f"row_service_{rid}"] = [r.get("service", "")]
                form[f"row_fee_{rid}"] = [sanitize_fee_int(r.get("fee", 0))]
                form[f"row_notes_{rid}"] = [r.get("notes", "")]
                form[f"row_bp_{rid}"] = [r.get("bp", "individual")]

        if "out_of_scope_items" in disk_draft and isinstance(disk_draft["out_of_scope_items"], dict):
            form["oos_submitted"] = ["true"]
            for k, v in disk_draft["out_of_scope_items"].items():
                form[k] = [v]
    except Exception as ex:
        print(f"DEBUG: Disk draft rehydration error for {c_id}_{eng_id}: {str(ex)}", file=sys.stderr)

    return form

def adobe_sign_api_request(endpoint, method="POST", payload=None, files=None):
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

def submit_adobe_sign_transaction(client_qbo_id, engagement_id, estimate_id, pdf_binary_data, co_signer_email=None, is_organization=False, primary_email_override=None):
    try:
        primary_email = primary_email_override.strip() if primary_email_override and primary_email_override.strip() else ""

        if not primary_email:
            fresh_customer = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
            raw_email = fresh_customer.get("PrimaryEmailAddr", {}).get("Address", "")
            primary_email = raw_email.split(",")[0].strip() if raw_email else ""

        if not primary_email:
            return False, "Customer record is missing a valid Primary Email Address inside QBO and no override was provided."

        files_payload = (f"Tax_Engagement_Terms_Est_{estimate_id}.pdf", "application/pdf", pdf_binary_data)
        transient_res = adobe_sign_api_request("transientDocuments", method="POST", files=files_payload)
        transient_id = transient_res.get("transientDocumentId")
        
        if not transient_id:
            return False, "Adobe Sign Gateway rejected binary buffer authentication check."

        participant_sets = []
        current_order = 1

        if is_organization:
            participant_sets.append({
                "memberInfos": [{"email": OWNER_EMAIL}],
                "order": current_order,
                "role": "SIGNER"
            })
            current_order += 1

        participant_sets.append({
            "memberInfos": [{"email": primary_email}],
            "order": current_order,
            "role": "SIGNER"
        })
        current_order += 1

        if co_signer_email and "@" in co_signer_email:
            participant_sets.append({
                "memberInfos": [{"email": co_signer_email.strip()}],
                "order": current_order,
                "role": "SIGNER"
            })

        external_meta = { "doc_type": "Tax Agreement", "qbo_id": str(client_qbo_id), "engagement_id": str(engagement_id) }

        agreement_payload = {
            "fileInfos": [{"transientDocumentId": transient_id}],
            "name": f"Tarrant Advisors {TAX_YEAR} Engagement Agreement",
            "participantSetsInfo": participant_sets,
            "externalId": {"id": json.dumps(external_meta)},
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
            return True, agreement_id

        return False, "Adobe Sign accepted envelope configuration but failed to allocate an Agreement ID."
    except Exception as ex:
        return False, str(ex)

def get_form_data():
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

def render_phase1_workspace(error_msg=None, preserved_form=None):
    print("Content-Type: text/html\n")

    try:
        query_res = qbo_api_request("query?query=select * from Customer where Active=true maxresults 1000")
        customers = query_res.get("QueryResponse", {}).get("Customer", [])
    except Exception as e:
        customers = []
        error_msg = f"Failed to retrieve customer catalog from QBO. Verify tokens. Details: {str(e)}"

    client_data_map = {}
    clone_options_map = {}

    os.makedirs(DRAFTS_DIR, exist_ok=True)

    for c in customers:
        c_id = str(c["Id"])
        c_name = html.unescape(c["DisplayName"])
        acct_num = c.get("Notes", "")
        addr_obj = c.get("BillAddr", {})
        raw_c_email = c.get("PrimaryEmailAddr", {}).get("Address", "")
        qbo_primary_email = raw_c_email.split(",")[0].strip() if raw_c_email else ""
        qbo_phone = c.get("PrimaryPhone", {}).get("FreeFormNumber", "")

        meta = parse_acct_num(acct_num)
        
        if not meta.get("friendly_name"):
            meta["friendly_name"] = c_name
        if not meta.get("primary_signer_email"):
            meta["primary_signer_email"] = qbo_primary_email
        meta["phone"] = qbo_phone

        has_addr = bool(addr_obj.get("Line1") and addr_obj.get("City") and addr_obj.get("CountrySubDivisionCode") and addr_obj.get("PostalCode"))

        engagements_map = {}

        prefix = f"{c_id}_"
        for filename in os.listdir(DRAFTS_DIR):
            if filename.startswith(prefix) and filename.endswith(".json"):
                eng_id = filename[len(prefix):-5]
                draft_path = os.path.join(DRAFTS_DIR, filename)
                is_locked, locked_mtime = is_draft_locked(draft_path)
                try:
                    with open(draft_path, "r", encoding="utf-8") as df:
                        eng_draft = json.load(df)
                        eng_draft["engagement_id"] = eng_id
                        eng_draft["is_locked"] = is_locked
                        eng_draft["locked_mtime"] = locked_mtime

                        if eng_draft.get("rows"):
                            for r in eng_draft["rows"]:
                                r["fee"] = sanitize_fee_int(r.get("fee", 0))

                        engagements_map[eng_id] = eng_draft

                        if eng_draft.get("rows") and len(eng_draft["rows"]) > 0:
                            r_count = len(eng_draft["rows"])
                            t_fee = sum([sanitize_fee_int(r.get("fee", 0)) for r in eng_draft["rows"]])
                            title = eng_draft.get("engagement_title", f"Engagement #{eng_id}")
                            clone_key = f"{c_id}:{eng_id}"
                            clone_options_map[clone_key] = f"{c_name} — {title} ({r_count} items, ${t_fee:,})"
                except Exception:
                    pass

        client_key = f"{c_name} (Customer ID: {c_id})"
        client_data_map[client_key] = {
            "id": c_id,
            "sync_token": c.get("SyncToken", ""),
            "email": qbo_primary_email,
            "phone": qbo_phone,
            "metadata": meta,
            "address": {
                "street": addr_obj.get("Line1", ""),
                "city": addr_obj.get("City", ""),
                "state": addr_obj.get("CountrySubDivisionCode", ""),
                "zip": addr_obj.get("PostalCode", "")
            } if has_addr else {},
            "exposed_services": EXPOSED_SERVICES,
            "engagements": engagements_map
        }

    selected_client_label = ""
    selected_eng_id = "0"
    reconstructed_rows_json = "[]"
    preserved_heal_data_json = "{}"
    boilerplate_items = extract_base_out_of_scope_boilerplate()
    estimate_date_option = "today"
    sync_to_qbo_checked = True

    active_oos_dict = None

    if preserved_form:
        raw_passed_client = html.unescape(get_form_val(preserved_form, "client_name"))
        selected_eng_id = get_form_val(preserved_form, "engagement_id", "0")
        estimate_date_option = get_form_val(preserved_form, "estimate_date_option", "next_year")
        sync_to_qbo_val = get_form_val(preserved_form, "sync_to_qbo", "true").lower()
        sync_to_qbo_checked = sync_to_qbo_val in ["true", "1", "yes"]

        selected_client_label = raw_passed_client
        parsed_qbo_id = ""
        try:
            parsed_qbo_id = extract_qbo_id(raw_passed_client)
        except Exception:
            pass

        if parsed_qbo_id:
            for c_key, c_val in client_data_map.items():
                if c_val["id"] == parsed_qbo_id:
                    c_title = c_key.split(" (Customer")[0]
                    if selected_eng_id != "0" and selected_eng_id in c_val.get("engagements", {}):
                        e_draft = c_val["engagements"][selected_eng_id]
                        e_title = e_draft.get("engagement_title", f"Engagement #{selected_eng_id}")
                        tag = TAG_FINAL if e_draft.get("is_locked") else TAG_DRAFT
                        selected_client_label = f"{tag}{c_title}: {parsed_qbo_id} | {selected_eng_id}: {e_title}"
                    else:
                        selected_client_label = f"{TAG_NEW}{c_title}: {parsed_qbo_id}"
                    break

        co_signer_email_val = get_form_val(preserved_form, "co_signer_email")
        clean_co_signer_email = co_signer_email_val.strip() if "@" in co_signer_email_val else ""

        active_oos_dict = extract_out_of_scope_dict(preserved_form)

        heal_data = {
            "engagement_title": html.unescape(get_form_val(preserved_form, "engagement_title", f"{TAX_YEAR} Tax Services Agreement")),
            "primary_signer": {
                "friendly_name": html.unescape(get_form_val(preserved_form, "friendly_name")),
                "legal_name": html.unescape(get_form_val(preserved_form, "legal_name")),
                "email": get_form_val(preserved_form, "primary_signer_email")
            },
            "phone": get_form_val(preserved_form, "phone"),
            "co_signer": {
                "name": html.unescape(get_form_val(preserved_form, "co_signer_name")),
                "email": clean_co_signer_email
            },
            "billing_address": {
                "street": get_form_val(preserved_form, "street"),
                "city": get_form_val(preserved_form, "city"),
                "state": get_form_val(preserved_form, "state"),
                "zip": get_form_val(preserved_form, "zip")
            },
            "entity_type": get_form_val(preserved_form, "entity_type", "individual"),
            "out_of_scope_items": active_oos_dict
        }
        preserved_heal_data_json = json.dumps(heal_data)

        row_ids = get_form_list(preserved_form, "selected_rows")
        rows_list = [
            {
                "item_id": get_form_val(preserved_form, f"row_item_id_{rid}"),
                "service": urllib.parse.unquote(get_form_val(preserved_form, f"row_service_{rid}")),
                "fee": sanitize_fee_int(get_form_val(preserved_form, f"row_fee_{rid}", "0")),
                "notes": urllib.parse.unquote(get_form_val(preserved_form, f"row_notes_{rid}"))
            }
            for rid in row_ids
        ]
        reconstructed_rows_json = json.dumps(rows_list)

    checklist_html = '<div id="out-of-scope-checklist-container" style="background: #fafbfc; border: 1px solid #cbd5e0; border-radius: 4px; padding: 15px; margin-top: 10px;">\n'
    checklist_html += '            <input type="hidden" name="oos_submitted" value="true">\n'
    
    if boilerplate_items:
        for idx, item in enumerate(boilerplate_items):
            item_key = f"out_of_scope_item_{idx}"
            
            if active_oos_dict is None:
                is_checked = "checked"
            elif isinstance(active_oos_dict, dict):
                is_checked = "checked" if item_key in active_oos_dict else ""
            else:
                is_checked = "checked"

            checklist_html += f"""            <div style="margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0;">
                <label style="font-weight: normal; display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" name="{item_key}" value="{html.escape(item)}" {is_checked}>
                    {html.escape(item)}
                </label>
            </div>\n"""

    if isinstance(active_oos_dict, dict):
        for k, val in active_oos_dict.items():
            if "custom" in k:
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

    master_select_options = []
    for c_key, c_val in client_data_map.items():
        q_id = c_val["id"]
        c_title = c_key.split(" (Customer")[0]
        engs = c_val.get("engagements", {})
        
        master_select_options.append(
            f'<option value="{TAG_NEW}{html.escape(c_title)}: {q_id}" data-value="{q_id}:0"></option>'
        )
        for e_id, e_draft in engs.items():
            e_title = e_draft.get("engagement_title", f"Engagement #{e_id}")
            tag = TAG_FINAL if e_draft.get("is_locked") else TAG_DRAFT
            master_select_options.append(
                f'<option value="{tag}{html.escape(c_title)}: {q_id} | {e_id}: {html.escape(e_title)}" data-value="{q_id}:{e_id}"></option>'
            )

    clone_options_html = "".join([f'<option value="{html.escape(k)}">{html.escape(v)}</option>' for k, v in clone_options_map.items()])

    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Tarrant Advisors - 2026 Engagement Portal</title>
    <link rel="stylesheet" type="text/css" href="/css/{get_asset_url(CSS_FILE)}">
    <script>
        window.APP_CONFIG = {{
            "enableBatchMode": {batch_mode_js}
        }};
        window.clientData = {json.dumps(client_data_map)};
        window.reconstructedRows = {reconstructed_rows_json};
        window.preservedHealData = {preserved_heal_data_json};

        document.addEventListener("DOMContentLoaded", function() {{
            const inputEl = document.getElementById('client-select-input');
            if (inputEl && inputEl.value) {{
                if (typeof onClientInput === 'function') {{
                    onClientInput();
                }} else if (typeof onClientChange === 'function') {{
                    onClientChange();
                }}
            }}
        }});
    </script>
    <script src="/js/{get_asset_url(JS_FILE)}"></script>
</head>
<body>
<div class="wrapper">
    <h1>Tarrant Advisors LLC — Account Engagement Portal</h1>
    
    <div class="mode-tabs">
        <button type="button" id="tab-btn-single" class="tab-btn active" onclick="switchWorkspaceMode('single')">👤 Single Client Intake</button>
        <button type="button" id="tab-btn-batch" class="tab-btn" onclick="switchWorkspaceMode('batch')">📑 Seasonal Batch Dashboard</button>
    </div>

    <div id="single-client-workspace">
        <div id="lock-banner-container" style="display:none;"></div>

        <form method="POST" action="{SCRIPT_URL}">
            <div class="form-group" style="margin-bottom: 25px;">
                <label for="estimate-date-option">Date for Estimate:</label>
                <select name="estimate_date_option" id="estimate-date-option" style="width: 100%; padding: 12px; font-size: 14px; border: 1px solid #ccd1d9; border-radius: 4px;">
                    <option value="today"{" selected" if estimate_date_option == "today" else ""}>This Year</option>
                    <option value="next_year"{" selected" if estimate_date_option == "next_year" else ""}>Next Year</option>
                </select>
            </div>

            {f'<div style="background:#fde8e8; border:1px solid #e53e3e; color:#9b2c2c; padding:15px; margin-bottom:20px; border-radius:4px;">{html.escape(error_msg)}</div>' if error_msg else ''}

            <div class="form-group">
                <label for="client-select-input">Select Customer & Engagement:</label>
                <input type="text" 
                       id="client-select-input" 
                       list="client-select-options" 
                       value="{html.escape(selected_client_label)}"
                       placeholder="Type or select a customer account or engagement..." 
                       oninput="onClientInput()" 
                       style="width: 100%; padding: 12px; font-size: 14px; border: 1px solid #ccd1d9; border-radius: 4px; box-sizing: border-box;" 
                       required>
                <datalist id="client-select-options">
                    {"".join(master_select_options)}
                </datalist>
                <input type="hidden" name="client_name" id="client-select" value="{html.escape(selected_client_label)}">
            </div>

            <div id="profile-healing-container" style="display:none;"></div>

            <!-- QBO Sync Control Toolbar -->
            <div id="qbo-sync-toolbar-container" class="qbo-sync-toolbar" style="display:none;">
                <label class="qbo-sync-checkbox-label">
                    <input type="checkbox" id="sync_to_qbo" name="sync_to_qbo" value="true" {"checked" if sync_to_qbo_checked else ""}>
                    <span>Sync Metadata Updates to QuickBooks Online Customer Profile</span>
                </label>
            </div>

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
                    <button type="button" class="btn-add-row btn-action-copy-trigger" onclick="toggleInlineCopyBar(true)">📋 Copy Scope & Fees from Existing Engagement...</button>
                </div>

                <div id="inline-copy-toolbar" class="inline-copy-toolbar" style="display:none;">
                    <div style="font-weight:600; font-size:13px; color:#0078d4; margin-bottom:6px;">Copy Scope & Exclusions From Source Engagement:</div>
                    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                        <input type="text" 
                               id="clone-source-input" 
                               list="clone-client-options" 
                               placeholder="Type source customer or engagement ID to copy scope from..." 
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

        <div id="batch-bulk-copy-toolbar" class="inline-copy-toolbar" style="display:none; margin-bottom: 20px;">
            <div style="font-weight:600; font-size:13px; color:#0078d4; margin-bottom:6px;">Bulk Apply Scope & Exclusions to Checked Batch Engagements:</div>
            <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                <input type="text" 
                       id="batch-bulk-source-input" 
                       list="clone-client-options" 
                       placeholder="Select source engagement to apply to checked accounts..." 
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
                    <th>Client / Engagement</th>
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

<div id="batch-edit-modal" class="modal-overlay">
    <div class="modal-content">
        <button type="button" class="modal-close-btn" onclick="cancelBatchEditModal()">&times;</button>
        <h2 id="modal-client-title" style="margin-top: 0; color: #0078d4;">Edit Engagement Parameters</h2>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin-bottom: 20px;">
        
        <div id="modal-workspace-container"></div>

        <div style="margin-top: 25px; display: flex; justify-content: flex-end; gap: 12px;">
            <button type="button" onclick="closeBatchEditModal()" class="btn-submit" style="width: auto; padding: 10px 24px;">Save & Return to Grid</button>
        </div>
    </div>
</div>

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
    raw_client_val = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(raw_client_val)
    
    eng_id = get_form_val(form, "engagement_id", "0")
    if eng_id == "0":
        eng_id = allocate_next_engagement_id(client_qbo_id)

    eng_title = html.unescape(get_form_val(form, "engagement_title", "2026 Tax Services Agreement")).strip()
    
    clean_client_title = re.sub(r'^\[[A-Za-z0-9]+\]\s*', '', html.unescape(raw_client_val))
    clean_client_title = re.sub(r'\s*\((?:QBO|Customer)\s*ID:.*?\)', '', clean_client_title)
    clean_client_title = clean_client_title.split(' — ')[0].strip()

    row_ids = get_form_list(form, "selected_rows")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")
    profile_verified = get_form_val(form, "profile_verified", "false")
    sync_to_qbo_val = get_form_val(form, "sync_to_qbo", "true").lower()
    sync_to_qbo = sync_to_qbo_val in ["true", "1", "yes"]

    co_signer_email_val = get_form_val(form, "co_signer_email")
    co_signer_email = co_signer_email_val.strip() if "@" in co_signer_email_val else ""
    co_signer_name = html.unescape(get_form_val(form, "co_signer_name"))
    
    if co_signer_name.lower().strip() in ["none", "null", "single", "n/a"] or co_signer_email_val.lower().strip() in ["none", "null", "single", "n/a"]:
        co_signer_email = co_signer_name = ""

    entity_type = get_form_val(form, "entity_type", "individual")

    primary_email = get_form_val(form, "primary_signer_email")
    phone = get_form_val(form, "phone")
    street = get_form_val(form, "street")
    city = get_form_val(form, "city")
    state = get_form_val(form, "state")
    zip_val = get_form_val(form, "zip")

    prior_estimate_id = ""
    existing_draft = {}
    draft_path = get_draft_file_path(client_qbo_id, eng_id)
    is_locked = False

    try:
        is_locked, _ = is_draft_locked(draft_path)
        if os.path.exists(draft_path):
            with open(draft_path, "r", encoding="utf-8") as df:
                existing_draft = json.load(df)
                prior_estimate_id = existing_draft.get("estimate_id", "")
    except Exception as de:
        print(f"DEBUG: Draft reading failure: {str(de)}", file=sys.stderr)

    p_signer = existing_draft.get("primary_signer", {}) if isinstance(existing_draft.get("primary_signer"), dict) else {}
    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip() or p_signer.get("friendly_name") or clean_client_title
    legal_name = html.unescape(get_form_val(form, "legal_name")).strip() or p_signer.get("legal_name") or clean_client_title

    if not primary_email:
        primary_email = p_signer.get("email", "")

    if not phone:
        phone = existing_draft.get("phone", "")

    if not street:
        try:
            fresh_c = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
            c_addr = fresh_c.get("BillAddr", {})
            if not primary_email:
                raw_c_email = fresh_c.get("PrimaryEmailAddr", {}).get("Address", "")
                primary_email = raw_c_email.split(",")[0].strip() if raw_c_email else ""
            if not phone:
                phone = fresh_c.get("PrimaryPhone", {}).get("FreeFormNumber", "")
            street, city = c_addr.get("Line1", ""), c_addr.get("City", "")
            state, zip_val = c_addr.get("CountrySubDivisionCode", ""), c_addr.get("PostalCode", "")
        except Exception as fe:
            print(f"DEBUG: QBO fallback data extraction failed: {str(fe)}", file=sys.stderr)

    posted_oos_dict = extract_out_of_scope_dict(form, existing_draft.get("out_of_scope_items"))

    disk_rows_list = existing_draft.get("rows", [])

    processed_rows = []
    for idx, rid in enumerate(row_ids):
        item_id = get_form_val(form, f"row_item_id_{rid}")
        svc = urllib.parse.unquote(get_form_val(form, f"row_service_{rid}"))
        fee_val = get_form_val(form, f"row_fee_{rid}", "")
        notes_val = urllib.parse.unquote(get_form_val(form, f"row_notes_{rid}"))
        bp_val = get_form_val(form, f"row_bp_{rid}", "individual")

        if (fee_val is None or fee_val.strip() == "") and idx < len(disk_rows_list):
            fee_val = disk_rows_list[idx].get("fee", 0)
            if not notes_val:
                notes_val = disk_rows_list[idx].get("notes", "")

        processed_rows.append({
            "item_id": item_id,
            "service": svc,
            "fee": sanitize_fee_int(fee_val),
            "notes": notes_val,
            "bp": bp_val
        })

    if not is_locked:
        try:
            os.makedirs(DRAFTS_DIR, exist_ok=True)
            draft_payload = {
                "engagement_id": eng_id,
                "engagement_title": eng_title,
                "estimate_date_option": estimate_date_option,
                "primary_signer": {
                    "friendly_name": friendly_name,
                    "legal_name": legal_name,
                    "email": primary_email
                },
                "phone": phone,
                "co_signer": {
                    "name": co_signer_name,
                    "email": co_signer_email
                },
                "entity_type": entity_type,
                "profile_verified": profile_verified.lower() in ["true", "1", "yes"],
                "billing_address": {
                    "street": street,
                    "city": city,
                    "state": state,
                    "zip": zip_val
                },
                "out_of_scope_items": posted_oos_dict,
                "estimate_id": prior_estimate_id,
                "rows": processed_rows,
                "delivery_format": existing_draft.get("delivery_format", "electronic")
            }
            with open(draft_path, "w", encoding="utf-8") as df:
                json.dump(draft_payload, df, indent=2)
        except Exception as de:
            print(f"DEBUG: Server-side draft writing handling: {str(de)}", file=sys.stderr)

    iframe_src = f"{SCRIPT_URL}?action=render_live_pdf&client_name={urllib.parse.quote(client_qbo_id)}&engagement_id={eng_id}"

    hidden_checklist_fields = f'<input type="hidden" name="estimate_date_option" value="{html.escape(estimate_date_option)}">\n'
    hidden_checklist_fields += '<input type="hidden" name="oos_submitted" value="true">\n'
    
    if isinstance(posted_oos_dict, dict):
        for k, v in posted_oos_dict.items():
            hidden_checklist_fields += f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">\n'

    email_from = OWNER_EMAIL

    cc_badge_html = ""
    if co_signer_email and "@" in co_signer_email:
        cc_badge_html = f'<div class="email-recipient-badge" style="margin-top: -5px;">CC: <span>{html.escape(co_signer_email)}</span></div>'

    print("Content-Type: text/html\n")
    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Review Proposed Engagement Document</title>
    <link rel="stylesheet" type="text/css" href="/css/{get_asset_url(CSS_FILE)}">
    <script src="/js/{get_asset_url(JS_FILE)}"></script>
</head>
<body>
<div class="split-container">
    <div class="editor-panel" style="padding:25px; overflow-y:auto;">
        <form method="POST" action="{SCRIPT_URL}">
            <input type="hidden" name="client_name" value="{html.escape(raw_client_val)}">
            <input type="hidden" name="engagement_id" value="{html.escape(eng_id)}">
            <input type="hidden" name="engagement_title" value="{html.escape(eng_title)}">
            <input type="hidden" name="friendly_name" value="{html.escape(friendly_name)}">
            <input type="hidden" name="legal_name" value="{html.escape(legal_name)}">
            <input type="hidden" name="primary_signer_email" value="{html.escape(primary_email)}">
            <input type="hidden" name="phone" value="{html.escape(phone)}">
            <input type="hidden" name="profile_verified" value="{html.escape(profile_verified)}">
            <input type="hidden" name="co_signer_email" value="{html.escape(co_signer_email)}">
            <input type="hidden" name="co_signer_name" value="{html.escape(co_signer_name)}">
            <input type="hidden" name="entity_type" value="{html.escape(entity_type)}">
            <input type="hidden" name="estimate_date_option" value="{html.escape(estimate_date_option)}">
            <input type="hidden" name="sync_to_qbo" value="{'true' if sync_to_qbo else 'false'}">
            <input type="hidden" name="prior_estimate_id" value="{html.escape(prior_estimate_id)}">
            <input type="hidden" name="street" value="{html.escape(street)}">
            <input type="hidden" name="city" value="{html.escape(city)}">
            <input type="hidden" name="state" value="{html.escape(state)}">
            <input type="hidden" name="zip" value="{html.escape(zip_val)}">
            {hidden_checklist_fields}

            {"".join([f'<input type="hidden" name="selected_rows" value="{html.escape(rid)}">' for rid in row_ids])}
            {"".join([f'''
            <input type="hidden" name="row_item_id_{rid}" value="{html.escape(get_form_val(form, f"row_item_id_{rid}"))}">
            <input type="hidden" name="row_service_{rid}" value="{html.escape(get_form_val(form, f"row_service_{rid}"))}">
            <input type="hidden" name="row_fee_{rid}" value="{sanitize_fee_int(get_form_val(form, f"row_fee_{rid}"))}">
            <input type="hidden" name="row_notes_{rid}" value="{html.escape(get_form_val(form, f"row_notes_{rid}"))}">
            <input type="hidden" name="row_bp_{rid}" value="{html.escape(get_form_val(form, f"row_bp_{rid}", "individual"))}">
            ''' for rid in row_ids])}

            <div style="display:flex; flex-direction:column; gap:12px;">
                <button type="submit" name="action" value="revert_to_workspace" class="btn-submit btn-action-grey" style="text-align:center; padding:12px;">← Go Back & Make Edits</button>
                <button type="submit" name="action" value="download_draft_pdf" class="btn-submit btn-action-yellow" style="text-align:center; padding:12px;">⬇ Download Draft Agreement</button>
                
                <div class="email-composer-container">
                    <button type="button" class="btn-submit btn-action-purple" onclick="toggleEmailComposer()" style="text-align:center; padding:12px;">✉ Compose & Send Email Draft...</button>
                    <div id="email-composer-fields" style="display:none; margin-top: 15px;">
                        <div class="email-composer-box">
                            <label class="field-label">From:</label>
                            <input type="email" name="email_from" value="{html.escape(email_from)}" style="width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #cbd5e0; border-radius: 4px; box-sizing: border-box;">
                            <div class="email-recipient-badge">To: <span>{html.escape(primary_email)}</span></div>
                            {cc_badge_html}
                            <label class="field-label">Subject:</label>
                            <input type="text" name="email_subject" value="Draft Tax Engagement Agreement" style="width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #cbd5e0; border-radius: 4px; box-sizing: border-box;">
                            <label class="field-label">Message:</label>
                            <textarea name="email_body" style="width: 100%; height: 80px; padding: 8px; margin-bottom: 10px; border: 1px solid #cbd5e0; border-radius: 4px; box-sizing: border-box; font-family: inherit;">Please review the attached draft agreement.</textarea>
                            <button type="submit" name="action" value="send_resend_email" class="btn-submit btn-action-purple" style="text-align:center; padding:12px; width: 100%;">🚀 Send via Resend</button>
                        </div>
                    </div>
                </div>

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
    raw_client_val = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(raw_client_val)
    
    eng_id = get_form_val(form, "engagement_id", "0")
    if eng_id == "0":
        eng_id = allocate_next_engagement_id(client_qbo_id)

    eng_title = html.unescape(get_form_val(form, "engagement_title", "2026 Tax Services Agreement")).strip()
    
    clean_client_title = re.sub(r'^\[[A-Za-z0-9]+\]\s*', '', html.unescape(raw_client_val))
    clean_client_title = re.sub(r'\s*\((?:QBO|Customer)\s*ID:.*?\)', '', clean_client_title)
    clean_client_title = clean_client_title.split(' — ')[0].strip()

    row_ids = get_form_list(form, "selected_rows")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")
    profile_verified = get_form_val(form, "profile_verified", "false")

    co_signer_email_val = get_form_val(form, "co_signer_email")
    co_signer_email = co_signer_email_val.strip() if "@" in co_signer_email_val else ""
    co_signer_name = html.unescape(get_form_val(form, "co_signer_name"))
    
    if co_signer_name.lower().strip() in ["none", "null", "single", "n/a"] or co_signer_email_val.lower().strip() in ["none", "null", "single", "n/a"]:
        co_signer_email = co_signer_name = ""

    entity_type = get_form_val(form, "entity_type", "individual")

    primary_email = get_form_val(form, "primary_signer_email")
    phone = get_form_val(form, "phone")
    street = get_form_val(form, "street")
    city = get_form_val(form, "city")
    state = get_form_val(form, "state")
    zip_val = get_form_val(form, "zip")

    draft_path = get_draft_file_path(client_qbo_id, eng_id)
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
    legal_name = html.unescape(get_form_val(form, "legal_name")).strip() or clean_client_title
    
    p_signer = existing_draft.get("primary_signer", {}) if isinstance(existing_draft.get("primary_signer"), dict) else {}
    if not primary_email:
        primary_email = p_signer.get("email", "")

    if not phone:
        phone = existing_draft.get("phone", "")

    posted_oos_dict = extract_out_of_scope_dict(form, existing_draft.get("out_of_scope_items"))

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
            "fee": sanitize_fee_int(fee_val),
            "notes": notes_val,
            "bp": bp_val
        })

    try:
        os.makedirs(DRAFTS_DIR, exist_ok=True)
        target_delivery_fmt = get_form_val(form, "delivery_format") or existing_draft.get("delivery_format", "electronic")

        draft_payload = {
            "engagement_id": eng_id,
            "engagement_title": eng_title,
            "estimate_date_option": estimate_date_option,
            "primary_signer": {
                "friendly_name": friendly_name,
                "legal_name": legal_name,
                "email": primary_email
            },
            "phone": phone,
            "co_signer": {
                "name": co_signer_name,
                "email": co_signer_email
            },
            "entity_type": entity_type,
            "profile_verified": profile_verified.lower() in ["true", "1", "yes"],
            "billing_address": {
                "street": street,
                "city": city,
                "state": state,
                "zip": zip_val
            },
            "out_of_scope_items": posted_oos_dict,
            "estimate_id": existing_draft.get("estimate_id", ""),
            "rows": processed_rows,
            "delivery_format": target_delivery_fmt
        }
        with open(draft_path, "w", encoding="utf-8") as df:
            json.dump(draft_payload, df, indent=2)

        print("Content-Type: application/json\n")
        print(json.dumps({
            "status": "success", 
            "qbo_id": client_qbo_id, 
            "engagement_id": eng_id, 
            "draft": draft_payload
        }))
    except Exception as e:
        render_pipeline_error(form, str(e), http_code=500)

def build_salutation_name(friendly_name, co_signer_name=""):
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
    raw_client_name = get_form_val(form, "client_name", "Unknown Client")
    row_ids = get_form_list(form, "selected_rows")
    if not row_ids:
        row_ids = [k.replace("row_item_id_", "") for k in form if k.startswith("row_item_id_")]

    co_signer_email_val = get_form_val(form, "co_signer_email")
    co_signer_email = co_signer_email_val.strip() if "@" in co_signer_email_val else ""
    co_signer_name = html.unescape(get_form_val(form, "co_signer_name"))
    entity_type = get_form_val(form, "entity_type", "individual")

    clean_client_title = re.sub(r'^\[[A-Za-z0-9]+\]\s*', '', html.unescape(raw_client_name))
    clean_client_title = re.sub(r'\s*\((?:QBO|Customer)\s*ID:.*?\)', '', clean_client_title)
    clean_client_title = clean_client_title.split(' — ')[0].strip()

    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip() or clean_client_title
    legal_name = html.unescape(get_form_val(form, "legal_name")).strip() or clean_client_title

    phone = get_form_val(form, "phone")
    street = get_form_val(form, "street")
    city = get_form_val(form, "city")
    state = get_form_val(form, "state")
    zip_val = get_form_val(form, "zip")

    if not street or not phone:
        try:
            c_id = extract_qbo_id(raw_client_name)
            c_data = qbo_api_request(f"customer/{c_id}").get("Customer", {})
            addr_obj = c_data.get("BillAddr", {})
            if not street:
                street, city = addr_obj.get('Line1',''), addr_obj.get('City','')
                state, zip_val = addr_obj.get('CountrySubDivisionCode',''), addr_obj.get('PostalCode','')
            if not phone:
                phone = c_data.get("PrimaryPhone", {}).get("FreeFormNumber", "")
        except Exception:
            if not street: street = city = state = zip_val = ""
            if not phone: phone = ""

    address_parts = [p.strip() for p in [street, city, state, zip_val] if p and p.strip()]
    billing_address = ", ".join(address_parts) if address_parts else "<i>[Billing Address Sourced on Execution]</i>"
    greeting_name = build_salutation_name(friendly_name, co_signer_name)

    try:
        with open(ENGAGEMENT_TEMPLATE, "r", encoding="utf-8") as f:
            raw_markdown = f.read()
    except FileNotFoundError:
        raw_markdown = "# Tarrant Advisors LLC\n1875 Campus Commons Dr., Suite 203, Reston, VA 20191\n75 Port City Landing, Suite 110, Mt. Pleasant, SC 29464\n## {{TAX_YEAR}} ENGAGEMENT AGREEMENT\n{{DYNAMIC_ESTIMATES_TABLE}}\n{{DYNAMIC_SERVICES_TEXT}}"

    total_base = 0
    discount_val = 0
    deposit_val = 0
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

        fee = sanitize_fee_int(raw_fee_val)

        svc_lower = raw_svc.lower()
        if "discount" in svc_lower or "referral" in svc_lower:
            discount_val += abs(fee)
        elif "deposit" in svc_lower or "retainer" in svc_lower:
            deposit_val += abs(fee)
        else:
            table_rows_data.append([raw_svc, f"${fee:,}"])
            total_base += fee

        if notes:
            services_annotation_blocks.append(f"• <strong>{xml_safe_escape(raw_svc)}:</strong> {xml_safe_escape(notes)}")
        else:
            services_annotation_blocks.append(f"• <strong>{xml_safe_escape(raw_svc)}</strong>")

    total_net = total_base - discount_val
    if discount_val > 0: 
        table_rows_data.append(["Client Discount:", f"-${discount_val:,}"])
    
    table_rows_data.append(["TOTAL FEES:", f"${total_net:,}"])
    
    if deposit_val > 0: 
        table_rows_data.append(["DEPOSIT DUE UPON COMMENCEMENT OF SERVICE:", f"${deposit_val:,}"])

    is_org_type = entity_type.lower() in ORGANIZATION_ENTITY_TYPES

    posted_oos_dict = extract_out_of_scope_dict(form)

    out_of_scope_list = list(posted_oos_dict.values()) if isinstance(posted_oos_dict, dict) else None
    
    jinja_tmpl = Template(raw_markdown)
    markdown_content = jinja_tmpl.render(
        TAX_YEAR=TAX_YEAR,
        NEXT_YEAR=NEXT_YEAR,
        TODAY_DATE=datetime.date.today().strftime('%B %d, %Y'),
        CLIENT_ADDRESS=billing_address,
        CLIENT_PHONE=xml_safe_escape(phone),
        CLIENT_LEGAL_NAME=xml_safe_escape(legal_name),
        FRIENDLY_NAME=xml_safe_escape(friendly_name),
        GREETING_NAME=xml_safe_escape(greeting_name),
        meta_entity_type=entity_type.lower(),
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
        textColor=HEADER_BLUE,
        alignment=2
    )

    address_style = ParagraphStyle(
        'AddressHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=11,
        textColor=HEADER_BLUE,
        alignment=2
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

    header_text_nodes = []
    content_lines = markdown_content.split('\n')
    filtered_lines = []

    company_title_found = False
    
    for line in content_lines:
        line_str = line.strip()
        if not line_str or line_str.startswith("{%") or line_str.startswith("%}"):
            continue

        if line_str.startswith("# ") and not company_title_found:
            company_title_found = True
            header_text_nodes.append(Paragraph(xml_safe_escape(line_str[2:].strip()), company_style))
            header_text_nodes.append(Spacer(1, 3))
            continue
        
        if company_title_found and len(header_text_nodes) < 5:
            if line_str.startswith("##") or "Date:" in line_str:
                filtered_lines.append(line)
                company_title_found = False
                continue
            header_text_nodes.append(Paragraph(xml_safe_escape(line_str), address_style))
            continue

        filtered_lines.append(line)

    if not header_text_nodes:
        header_text_nodes = [
            Paragraph("Tarrant Advisors LLC", company_style),
            Spacer(1, 3),
            Paragraph("1875 Campus Commons Dr., Suite 203, Reston, VA 20191", address_style),
            Paragraph("75 Port City Landing, Suite 110, Mt. Pleasant, SC 29464", address_style)
        ]

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

        logo_img.hAlign = 'LEFT'
    else:
        logo_img = Paragraph("", styles['Normal'])

    header_table = Table([[logo_img, header_text_nodes]], colWidths=[160, 370])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (0,0), 'LEFT'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))

    story.append(header_table)
    story.append(Spacer(1, 10))

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
                if len(services_annotation_blocks) == 1:
                    single_block = services_annotation_blocks[0]
                    if single_block.startswith("• "):
                        single_block = single_block[2:]
                    story.append(Paragraph(single_block, body_style))
                    story.append(Spacer(1, 4))
                else:
                    for block in services_annotation_blocks:
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

    # 1. Firm Counter-Signature (First if Organization)
    if is_org_type:
        sig_elements.extend([
            Paragraph(render_sig_line("Authorized Signature", "{{_es_signer1_signature}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Counter-Signed", "{{_es_signer1_date}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{OWNER_SIGNATURE}<br/>{OWNER_CORPNAME}</strong>", body_style),
            Spacer(1, 15),
        ])

    # 2. Primary Client Signature
    p_tag_idx = "2" if is_org_type else "1"
    sig_elements.extend([
        Paragraph(render_sig_line("Signature", f"{{{{_es_signer{p_tag_idx}_signature}}}}"), body_style),
        Spacer(1, 4),
        Paragraph(render_sig_line("Date Verified", f"{{{{_es_signer{p_tag_idx}_date}}}}", 24), body_style),
        Spacer(1, 4),
        Paragraph(signer1_label, body_style),
    ])

    # 3. Additional/Secondary Signer Signature
    if co_signer_email and "@" in co_signer_email:
        co_signer_label = co_signer_name.strip() if co_signer_name.strip() else co_signer_email.strip()
        s_tag_idx = "3" if is_org_type else "2"

        sig_elements.extend([
            Spacer(1, 15),
            Paragraph(render_sig_line("Signature", f"{{{{_es_signer{s_tag_idx}_signature}}}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Verified", f"{{{{_es_signer{s_tag_idx}_date}}}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{xml_safe_escape(co_signer_label)}</strong>", body_style),
        ])

    story.append(KeepTogether(sig_elements))
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer

def handle_render_live_pdf(form):
    raw_client_val = get_form_val(form, "client_name")
    eng_id = get_form_val(form, "engagement_id", "0")
    
    if raw_client_val and eng_id != "0":
        try:
            c_id = extract_qbo_id(raw_client_val)
            form = populate_form_from_disk_draft(form, c_id, eng_id)
        except Exception as ex:
            print(f"DEBUG: Preview disk draft read error: {str(ex)}", file=sys.stderr)

    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    sys.stdout.buffer.write(b"Content-Type: application/pdf\n\n")
    sys.stdout.buffer.write(generated_buffer.read())

def handle_download_pdf(form, prefix="DRAFT"):
    raw_client_val = get_form_val(form, "client_name", "Unknown Client")
    eng_id = get_form_val(form, "engagement_id", "0")

    if raw_client_val and eng_id != "0":
        try:
            c_id = extract_qbo_id(raw_client_val)
            form = populate_form_from_disk_draft(form, c_id, eng_id)
        except Exception as ex:
            print(f"DEBUG: Download PDF disk draft read error: {str(ex)}", file=sys.stderr)

    clean_client_title = re.sub(r'^\[[A-Za-z0-9]+\]\s*', '', html.unescape(raw_client_val))
    clean_client_title = re.sub(r'\s*\((?:QBO|Customer)\s*ID:.*?\)', '', clean_client_title)
    clean_client_title = clean_client_title.split(' — ')[0].strip()

    legal_name = html.unescape(get_form_val(form, "legal_name")).strip() or clean_client_title
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"Tax Agreement {legal_name} ({prefix} {timestamp_str}).pdf"
    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    
    sys.stdout.buffer.write(b"Content-Type: application/pdf\n")
    sys.stdout.buffer.write(f"Content-Disposition: attachment; filename={urllib.parse.quote(filename)}\n\n".encode('utf-8'))
    sys.stdout.buffer.write(generated_buffer.read())

def handle_send_resend_email(form):
    raw_client_val = get_form_val(form, "client_name")
    eng_id = get_form_val(form, "engagement_id", "0")
    client_qbo_id = extract_qbo_id(raw_client_val)

    posted_subject = get_form_val(form, "email_subject")
    posted_body = get_form_val(form, "email_body")
    email_from = get_form_val(form, "email_from", OWNER_EMAIL).strip()

    if raw_client_val and eng_id != "0":
        try:
            form = populate_form_from_disk_draft(form, client_qbo_id, eng_id)
        except Exception as ex:
            print(f"DEBUG: Resend Email disk draft read error: {str(ex)}", file=sys.stderr)

    primary_email = get_form_val(form, "primary_signer_email")
    if not primary_email:
        p_signer = form.get("primary_signer", {})
        if isinstance(p_signer, dict):
            primary_email = p_signer.get("email", "")

    email_subject = posted_subject or get_form_val(form, "email_subject", "Draft Tax Engagement Agreement")
    email_body = posted_body or get_form_val(form, "email_body", "Please review the attached draft agreement.")

    clean_client_title = re.sub(r'^\[[A-Za-z0-9]+\]\s*', '', html.unescape(raw_client_val))
    clean_client_title = re.sub(r'\s*\((?:QBO|Customer)\s*ID:.*?\)', '', clean_client_title)
    clean_client_title = clean_client_title.split(' — ')[0].strip()

    legal_name = html.unescape(get_form_val(form, "legal_name")).strip() or clean_client_title
    
    pdf_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)
    pdf_bytes = pdf_buffer.read()
    filename = f"Draft_Agreement_{legal_name.replace(' ', '_')}.pdf"

    resend.api_key = os.environ.get("RESEND_API_KEY")

    params = {
        "from": f"Tarrant Advisors <{email_from}>",
        "reply_to": email_from,
        "to": [primary_email],
        "bcc": [email_from],
        "subject": email_subject,
        "text": email_body,
        "attachments": [
            {
                "filename": filename,
                "content": list(pdf_bytes),
            }
        ]
    }

    co_signer_email = get_form_val(form, "co_signer_email").strip()
    if co_signer_email and "@" in co_signer_email:
        params["cc"] = [co_signer_email]

    try:
        resend.Emails.send(params)
    except Exception as e:
        return render_pipeline_error(form, f"Failed to send email via Resend API: {str(e)}")

    success_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Draft Email Dispatched Successfully</title>
    <link rel="stylesheet" type="text/css" href="/css/{get_asset_url(CSS_FILE)}">
</head>
<body>
<div class="success-wrapper">
    <div class="success-card">
        <div class="icon-circle">✉</div>
        <h2 style="margin-top: 0; color: #107c41;">Email Sent Successfully</h2>
        <p>The draft agreement was successfully emailed to <strong>{html.escape(primary_email)}</strong> via Resend.</p>
        <a href="{SCRIPT_URL}" class="btn-submit" style="background:#0078d4; text-decoration:none; display:inline-block; padding: 12px 24px; font-weight: 600;">← Return to Engagement Portal</a>
    </div>
</div>
</body>
</html>"""
    
    print("Content-Type: text/html\n")
    print(success_html)

def execute_transactional_pipeline(form):
    raw_client_val = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(raw_client_val)
    
    eng_id = get_form_val(form, "engagement_id", "0")
    if eng_id == "0":
        eng_id = allocate_next_engagement_id(client_qbo_id)

    eng_title = html.unescape(get_form_val(form, "engagement_title", "2026 Tax Services Agreement")).strip()
    row_ids = get_form_list(form, "selected_rows")
    friendly_name = get_form_val(form, "friendly_name")
    legal_name = get_form_val(form, "legal_name")
    primary_email = get_form_val(form, "primary_signer_email")
    phone = get_form_val(form, "phone")
    street = get_form_val(form, "street")
    city = get_form_val(form, "city")
    state = get_form_val(form, "state")
    zip_val = get_form_val(form, "zip")
    estimate_date_option = get_form_val(form, "estimate_date_option", "next_year")
    sync_to_qbo_val = get_form_val(form, "sync_to_qbo", "true").lower()
    sync_to_qbo = sync_to_qbo_val in ["true", "1", "yes"]

    co_signer_email_val = get_form_val(form, "co_signer_email")
    co_signer_email = co_signer_email_val.strip() if "@" in co_signer_email_val else ""
    co_signer_name = html.unescape(get_form_val(form, "co_signer_name"))
    entity_type = get_form_val(form, "entity_type", "individual")

    delivery_method = get_form_val(form, "delivery_method")
    is_paper_mode = (delivery_method == "paper")
    is_org_type = entity_type.lower() in ORGANIZATION_ENTITY_TYPES

    prior_estimate_id = get_form_val(form, "prior_estimate_id").strip()
    draft_path = get_draft_file_path(client_qbo_id, eng_id)

    if os.path.exists(draft_path):
        try:
            with open(draft_path, "r", encoding="utf-8") as df:
                disk_draft = json.load(df)
                if not prior_estimate_id:
                    prior_estimate_id = str(disk_draft.get("estimate_id", "")).strip()
                if not primary_email:
                    p_signer = disk_draft.get("primary_signer", {}) if isinstance(disk_draft.get("primary_signer"), dict) else {}
                    primary_email = p_signer.get("email", "")
                if not phone:
                    phone = disk_draft.get("phone", "")
        except Exception as e:
            print(f"DEBUG: Could not read prior estimate ID, phone, or email from draft: {e}", file=sys.stderr)

    if prior_estimate_id:
        try:
            prior_txn = qbo_api_request(f"estimate/{prior_estimate_id}").get("Estimate", {})
            prior_customer_id = str(prior_txn.get("CustomerRef", {}).get("value", ""))
            prior_sync_token = prior_txn.get("SyncToken")

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

    raw_primary_email = fresh_customer.get("PrimaryEmailAddr", {}).get("Address", "")
    qbo_primary_email = raw_primary_email.split(",")[0].strip() if raw_primary_email else ""
    effective_primary_email = primary_email.strip() if primary_email and primary_email.strip() else qbo_primary_email

    qbo_phone = fresh_customer.get("PrimaryPhone", {}).get("FreeFormNumber", "")
    effective_phone = phone.strip() if phone and phone.strip() else qbo_phone

    proposed_notes_json = compile_acct_num(
        friendly_name=friendly_name,
        primary_email=effective_primary_email,
        co_signer_name=co_signer_name,
        co_signer_email=co_signer_email,
        entity_type=entity_type
    )

    if sync_to_qbo:
        try:
            company_name_val = None if entity_type.lower() == "individual" else legal_name

            patch_payload = {
                "Id": client_qbo_id,
                "SyncToken": fresh_customer["SyncToken"],
                "sparse": True,
                "DisplayName": legal_name,
                "CompanyName": company_name_val,
                "PrimaryEmailAddr": {
                    "Address": effective_primary_email
                },
                "PrimaryPhone": {
                    "FreeFormNumber": effective_phone
                },
                "BillAddr": {
                    "Line1": street,
                    "City": city,
                    "CountrySubDivisionCode": state,
                    "PostalCode": zip_val
                },
                "Notes": proposed_notes_json
            }
            qbo_api_request("customer", method="POST", payload=patch_payload)
        except Exception as e:
            return render_pipeline_error(form, f"QBO Customer Profile Sync Failure: Unable to update Customer record in QBO. ({str(e)})")

    estimate_lines = []
    deposit_val = 0
    total_fee_sum = 0

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
            raw_fee_val = disk_rows_list[idx].get("fee", 0)
            if not notes:
                notes = disk_rows_list[idx].get("notes", "")

        fee = sanitize_fee_int(raw_fee_val)

        svc_lower = svc_name.lower()
        if item_id == "00000" or "deposit" in svc_lower or "retainer" in svc_lower:
            deposit_val += abs(fee)
            continue 

        if "discount" in svc_lower or "referral" in svc_lower:
            fee = -abs(fee)

        total_fee_sum += fee

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
        "TxnStatus": "Accepted",
        "AutoDocNumber": True,
        "Line": estimate_lines,
        "CustomField": [{"DefinitionId": "1", "StringValue": "JOINT" if (co_signer_email and "@" in co_signer_email) else "SINGLE", "Name": "Signers"}]
    }

    if deposit_val > 0:
        estimate_payload["PrivateNote"] = f"Deposit Due: ${deposit_val:,}"

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

    try:
        if os.path.exists(draft_path):
            unlock_draft(draft_path)
            with open(draft_path, "r", encoding="utf-8") as df:
                active_draft = json.load(df)
            active_draft["engagement_id"] = eng_id
            active_draft["engagement_title"] = eng_title
            active_draft["estimate_id"] = estimate_id
            active_draft["phone"] = effective_phone
            if "primary_signer" not in active_draft:
                active_draft["primary_signer"] = {}
            active_draft["primary_signer"]["email"] = effective_primary_email
            with open(draft_path, "w", encoding="utf-8") as df:
                json.dump(active_draft, df, indent=2)
            lock_draft(draft_path)
    except Exception as de:
        print(f"DEBUG: Post-transaction draft update failed: {str(de)}", file=sys.stderr)

    live_pdf_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=not is_paper_mode)
    live_pdf_buffer.seek(0)

    adobe_agreement_id = ""
    if is_paper_mode:
        adobe_sign_routing_success, adobe_error_context = True, ""
    else:
        adobe_sign_routing_success, adobe_error_context = submit_adobe_sign_transaction(
            client_qbo_id=client_qbo_id,
            engagement_id=eng_id,
            estimate_id=estimate_id,
            pdf_binary_data=live_pdf_buffer.read(),
            co_signer_email=co_signer_email,
            is_organization=is_org_type,
            primary_email_override=effective_primary_email
        )
        if adobe_sign_routing_success:
            adobe_agreement_id = adobe_error_context

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
            "engagement_id": eng_id,
            "delivery_method": delivery_method,
            "adobe_agreement_id": adobe_agreement_id
        }))
        return

    dl_query_args = [
        ("action", "download_final_pdf"),
        ("client_name", raw_client_val),
        ("engagement_id", eng_id)
    ]
        
    paper_dl_link = f"{SCRIPT_URL}?{urllib.parse.urlencode(dl_query_args)}"

    has_co_signer = bool(co_signer_email and "@" in co_signer_email)
    co_signer_label = co_signer_name.strip() if co_signer_name.strip() else co_signer_email.strip()

    signer_sequence_html = """
    <div style="font-weight: 600; font-size: 13px; color: #475569; margin-top: 15px; margin-bottom: 8px;">Signing Workflow Sequence:</div>
    <div style="font-family: monospace; font-size: 13px; line-height: 1.6; color: #334155; background: #ffffff; padding: 12px; border-radius: 4px; border: 1px solid #e2e8f0;">
    """

    next_step_num = 1

    if is_org_type:
        signer_sequence_html += f"""
        <div style="margin-bottom: 8px;">
            <strong>{next_step_num}. Firm Counter-Signature</strong><br>
            &nbsp;&nbsp;&nbsp;&nbsp;• Recipient: {html.escape(OWNER_SIGNATURE)} ({html.escape(OWNER_EMAIL)})<br>
            &nbsp;&nbsp;&nbsp;&nbsp;• Status: <span style="color: #0284c7; font-weight: 600;">📩 Email Dispatched</span>
        </div>
        """
        next_step_num += 1

    p_status = "⏳ Pending Step 1 Completion" if is_org_type else "📩 Email Dispatched (Awaiting Signature)"
    p_status_color = "#64748b" if is_org_type else "#0284c7"

    signer_sequence_html += f"""
    <div style="margin-bottom: 8px;">
        <strong>{next_step_num}. Primary Client Signature</strong><br>
        &nbsp;&nbsp;&nbsp;&nbsp;• Recipient: {html.escape(friendly_name)} ({html.escape(effective_primary_email)})<br>
        &nbsp;&nbsp;&nbsp;&nbsp;• Status: <span style="color: {p_status_color}; font-weight: 600;">{p_status}</span>
    </div>
    """
    next_step_num += 1

    if has_co_signer:
        signer_sequence_html += f"""
        <div>
            <strong>{next_step_num}. Additional Signer Signature</strong><br>
            &nbsp;&nbsp;&nbsp;&nbsp;• Recipient: {html.escape(co_signer_label)} ({html.escape(co_signer_email)})<br>
            &nbsp;&nbsp;&nbsp;&nbsp;• Status: <span style="color: #64748b; font-weight: 600;">⏳ Pending Prior Completion</span>
        </div>
        """

    signer_sequence_html += "</div>"

    if is_paper_mode:
        delivery_card_html = f"""
        <div style="background: #ffffff; border: 1px solid #cbd5e0; border-radius: 6px; padding: 20px; text-align: left; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
            <div style="font-weight: 700; font-size: 16px; color: #166534; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                Physical Paper Delivery Prepared
            </div>
            <p style="margin: 0 0 15px 0; font-size: 13px; color: #475569; line-height: 1.5;">
                This engagement agreement has been flagged for wet/paper signature execution. Download the official PDF document below to print or archive for client delivery.
            </p>
            <div style="text-align: center; margin-top: 15px;">
                <a href="{html.escape(paper_dl_link)}" style="background: #16a34a; color: white; padding: 12px 24px; text-decoration: none; display: inline-block; border-radius: 4px; font-weight: bold; font-size: 15px;">⬇ Download & Print Final PDF</a>
            </div>
        </div>
        """
    else:
        delivery_card_html = f"""
        <div style="background: #ffffff; border: 1px solid #cbd5e0; border-radius: 6px; padding: 20px; text-align: left; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
            <div style="font-weight: 700; font-size: 16px; color: #0078d4; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                Adobe Sign Document Dispatched
            </div>
            <div style="font-size: 13px; color: #334155; line-height: 1.6; margin-bottom: 10px;">
                • <strong>Transaction ID:</strong> <span style="font-family: monospace; background: #f1f5f9; padding: 2px 6px; border-radius: 3px;">{html.escape(adobe_agreement_id if adobe_agreement_id else 'Enqueued')}</span><br>
                • <strong>Status:</strong> <span style="color: #0284c7; font-weight: 600;">Out for Signature</span>
            </div>
            {signer_sequence_html}
        </div>
        """

    formatted_fee_sum = f"${total_fee_sum:,}"

    success_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Pipeline Execution Complete</title>
    <link rel="stylesheet" type="text/css" href="/css/{get_asset_url(CSS_FILE)}">
</head>
<body>
<div class="success-wrapper">
    <div class="success-card">
        <h2 style="margin-top: 0; margin-bottom: 8px; color: #0078d4; font-size: 22px;">{html.escape(legal_name)}</h2>
        <div style="font-size: 15px; color: #334155; font-weight: 600; margin-bottom: 4px;">{html.escape(eng_title)}</div>
        <div style="font-size: 13px; color: #16a34a; font-weight: 600; margin-bottom: 25px;">Status: Dispatched Successfully</div>

        <!-- CARD 1: QUICKBOOKS ONLINE ESTIMATE -->
        <div style="background: #ffffff; border: 1px solid #cbd5e0; border-radius: 6px; padding: 20px; text-align: left; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
            <div style="font-weight: 700; font-size: 16px; color: #166534; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                QuickBooks Online Estimate
            </div>
            <div style="font-size: 13px; color: #334155; line-height: 1.6;">
                • <strong>Estimate ID:</strong> #{html.escape(estimate_id)}<br>
                • <strong>Total Amount:</strong> {formatted_fee_sum}<br>
                • <strong>Status:</strong> Pending Approval
            </div>
        </div>

        <!-- CARD 2: ADOBE SIGN WORKFLOW OR PAPER DOWNLOAD -->
        {delivery_card_html}

        <a href="{SCRIPT_URL}" class="btn-submit" style="background:#0078d4; text-decoration:none; display:inline-block; padding: 12px 24px; font-weight: 600;">← Return to Engagement Portal</a>
    </div>
</div>
</body>
</html>"""

    print("Content-Type: text/html\n")
    print(success_html)

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
    elif action == "send_resend_email":
        handle_send_resend_email(form_data)
    elif action == "execute_transactional_pipeline_paper":
        form_data["delivery_method"] = "paper"
        execute_transactional_pipeline(form_data)
    elif action == "execute_transactional_pipeline":
        form_data["delivery_method"] = ""
        execute_transactional_pipeline(form_data)
    elif action == "revert_to_workspace":
        raw_client_val = get_form_val(form_data, "client_name")
        eng_id = get_form_val(form_data, "engagement_id", "0")
        if raw_client_val and eng_id != "0":
            try:
                c_id = extract_qbo_id(raw_client_val)
                unlock_draft(get_draft_file_path(c_id, eng_id))
            except Exception as ex:
                print(f"DEBUG: Could not unlock draft on revert: {str(ex)}", file=sys.stderr)
        render_phase1_workspace(preserved_form=form_data)
    else:
        render_phase1_workspace()