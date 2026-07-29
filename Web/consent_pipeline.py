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
import unicodedata

from jinja2 import Template

# ReportLab Layout Engine & Platypus Components
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ==========================================
# CONFIGURATION & GLOBAL STATE
# ==========================================
PIPELINE_SANDBOX = os.environ.get("PIPELINE_SANDBOX")
if PIPELINE_SANDBOX:
    JS_FILE = "consent_sandbox.js"
    CSS_FILE = "consent_sandbox.css"
    CONSENT_TEMPLATE = "consent_sandbox.md"
    CARBON_COPIES = []
else:
    JS_FILE = "consent_pipeline.js"
    CSS_FILE = "consent_pipeline.css"
    CONSENT_TEMPLATE = "consent_template.md"
    CARBON_COPIES = ["katie@tarrantadvisors.com"]

SCRIPT_URL = os.environ.get("SCRIPT_NAME", "")

QBO_APIBASE = os.environ.get("QBO_APIBASE", "")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

ADOBE_APIBASE = os.environ.get("ADOBE_APIBASE", "")
ADOBE_TOKEN = os.environ.get("ADOBE_ACCESS_TOKEN", "")

# ==========================================
# FORM DATA EXTRACTION HELPERS
# ==========================================
def get_form_val(form, key, default=""):
    """Safely extracts a string value from form data dictionary."""
    if not form or key not in form:
        return default
    val = form[key]
    if isinstance(val, list):
        return str(val[0]) if val else default
    return str(val) if val is not None else default

# ==========================================
# QUICKBOOKS ONLINE REST WRAPPERS (READ-ONLY)
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
    """Extracts numeric QuickBooks ID from composite selection label."""
    match = re.search(r'Customer ID:\s*(\d+)', client_name_str)
    if match:
        return match.group(1)
    raise ValueError(f"Unable to parse unique Customer ID from label: {client_name_str}")

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

def submit_adobe_sign_transaction(client_qbo_id, pdf_binary_data, additional_signer_email=None):
    """Handles envelope transmission and routing parameters for Adobe Sign."""
    try:
        fresh_customer = qbo_api_request(f"customer/{client_qbo_id}").get("Customer", {})
        primary_email = fresh_customer.get("PrimaryEmailAddr", {}).get("Address", "")

        if not primary_email:
            return False, "Customer record is missing a valid Primary Email Address in QBO."

        files_payload = (f"Section_7216_Consent_{client_qbo_id}.pdf", "application/pdf", pdf_binary_data)
        transient_res = adobe_sign_api_request("transientDocuments", method="POST", files=files_payload)
        transient_id = transient_res.get("transientDocumentId")

        if not transient_id:
            return False, "Adobe Sign Gateway rejected binary buffer authentication check."

        participant_sets = [{"memberInfos": [{"email": primary_email}], "order": 1, "role": "SIGNER"}]

        if additional_signer_email and "@" in additional_signer_email:
            participant_sets.append({
                "memberInfos": [{"email": additional_signer_email.strip()}],
                "order": 2,
                "role": "SIGNER"
            })

        agreement_payload = {
            "fileInfos": [{"transientDocumentId": transient_id}],
            "name": "Tarrant Advisors — Consent to Disclose Tax Return Information",
            "participantSetsInfo": participant_sets,
            "externalId": {"id": f"Consent Agreement:{client_qbo_id}"},
            "signatureType": "ESIGN",
            "state": "IN_PROCESS"
        }

        if CARBON_COPIES:
            agreement_payload["ccs"] = [
                {"email": email, "label": "Executed Consent Copy"} 
                for email in CARBON_COPIES if email.strip()
            ]

        agreement_res = adobe_sign_api_request("agreements", method="POST", payload=agreement_payload)
        agreement_id = agreement_res.get("id")

        if agreement_id:
            return True, agreement_id

        return False, "Adobe Sign accepted envelope configuration but failed to allocate an Agreement ID."
    except Exception as ex:
        return False, str(ex)

# ==========================================
# CGI FORM DATA PARSER
# ==========================================
def get_form_data():
    """Extracts query string and POST body parameters for CGI execution."""
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
    """Phase 1: Displays QBO customers and constructs the consent portal form."""
    print("Content-Type: text/html\n")

    try:
        query_res = qbo_api_request("query?query=select * from Customer where Active=true maxresults 1000")
        customers = query_res.get("QueryResponse", {}).get("Customer", [])
    except Exception as e:
        customers = []
        error_msg = f"Failed to retrieve customer catalog from QBO. Details: {str(e)}"

    client_data_map = {}
    for c in customers:
        c_id = c["Id"]
        # Unescape HTML entities first so dictionary keys are plain text ("Duncan & Gerry McKenna")
        c_name = html.unescape(c["DisplayName"])
        addr_obj = c.get("BillAddr", {})
        c_email = c.get("PrimaryEmailAddr", {}).get("Address", "")

        has_addr = bool(addr_obj.get("Line1") and addr_obj.get("City") and addr_obj.get("CountrySubDivisionCode") and addr_obj.get("PostalCode"))

        client_key = f"{c_name} (Customer ID: {c_id})"
        client_data_map[client_key] = {
            "id": c_id,
            "email": c_email,
            "address": {
                "street": addr_obj.get("Line1", ""),
                "city": addr_obj.get("City", ""),
                "state": addr_obj.get("CountrySubDivisionCode", ""),
                "zip": addr_obj.get("PostalCode", "")
            } if has_addr else {}
        }

    selected_client = ""
    preserved_heal_data_json = "{}"

    if preserved_form:
        selected_client = html.unescape(get_form_val(preserved_form, "client_name"))
        heal_data = {
            "friendly_name": html.unescape(get_form_val(preserved_form, "friendly_name")),
            "local_legal_name": html.unescape(get_form_val(preserved_form, "local_legal_name")),
            "tax_years_covered": get_form_val(preserved_form, "tax_years_covered", "2025 and 2026 tax years"),
            "local_street": get_form_val(preserved_form, "local_street"),
            "local_city": get_form_val(preserved_form, "local_city"),
            "local_state": get_form_val(preserved_form, "local_state"),
            "local_zip": get_form_val(preserved_form, "local_zip"),
            "meta_co_signer_name": html.unescape(get_form_val(preserved_form, "meta_co_signer_name")),
            "meta_additional_signer": get_form_val(preserved_form, "meta_additional_signer")
        }
        preserved_heal_data_json = json.dumps(heal_data)

    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Tarrant Advisors - Section 7216 Consent Portal</title>
    <link rel="stylesheet" type="text/css" href="/css/{CSS_FILE}">
    <script>
        window.clientData = {json.dumps(client_data_map)};
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
    <h1>Tarrant Advisors LLC — Consent Request Portal</h1>
    <p style="font-size: 13px; color: #666; margin-bottom: 25px;">
        Generate and dispatch Section 7216 consent agreements allowing disclosure of client tax return information to authorized advisors.
    </p>

    <form method="POST" action="{SCRIPT_URL}">
        {f'<div style="background:#fde8e8; border:1px solid #e53e3e; color:#9b2c2c; padding:15px; margin-bottom:20px; border-radius:4px;">{html.escape(error_msg)}</div>' if error_msg else ''}

        <div class="form-group">
            <label for="client-select">Select QuickBooks Online Customer Account Record:</label>
            <select name="client_name" id="client-select" onchange="onClientChange()" required>
                <option value="">-- Choose Active Customer --</option>
                {"".join([f'<option value="{html.escape(k)}"{" selected" if k == selected_client else ""}>{html.escape(k)}</option>' for k in client_data_map.keys()])}
            </select>
        </div>

        <div class="form-group">
            <label for="tax-years-covered">Tax Years Covered by Consent:</label>
            <select name="tax_years_covered" id="tax-years-covered">
                <option value="2025 and 2026 tax years">2025 and 2026 tax years</option>
                <option value="2026 tax year">2026 tax year</option>
                <option value="2025 tax year">2025 tax year</option>
            </select>
        </div>

        <div id="profile-container" style="display:none;"></div>

        <div class="submit-container" style="margin-top:25px;">
            <button type="submit" id="btn-submit-main" name="action" value="generate_preview" class="btn-submit" style="display:none;">Render PDF Preview</button>
        </div>
    </form>
</div>
</body>
</html>""")

def handle_generate_preview(form):
    """Phase 2: Renders split preview view with live iframe consent PDF."""
    raw_client_name = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(raw_client_name)
    clean_client_title = re.split(r'\s*\(Customer', html.unescape(raw_client_name))[0].strip()
    client_name = raw_client_name

    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip() or clean_client_title
    local_legal_name = html.unescape(get_form_val(form, "local_legal_name")).strip() or clean_client_title
    tax_years_covered = get_form_val(form, "tax_years_covered", "2025 and 2026 tax years")

    local_street = get_form_val(form, "local_street")
    local_city = get_form_val(form, "local_city")
    local_state = get_form_val(form, "local_state")
    local_zip = get_form_val(form, "local_zip")

    meta_co_signer_name = html.unescape(get_form_val(form, "meta_co_signer_name"))
    meta_sig = get_form_val(form, "meta_additional_signer").strip()
    if "@" not in meta_sig:
        meta_sig = ""

    pdf_query_args = [
        ("action", "render_live_pdf"),
        ("client_name", client_name),
        ("friendly_name", friendly_name),
        ("local_legal_name", local_legal_name),
        ("tax_years_covered", tax_years_covered),
        ("local_street", local_street),
        ("local_city", local_city),
        ("local_state", local_state),
        ("local_zip", local_zip),
        ("meta_co_signer_name", meta_co_signer_name),
        ("meta_additional_signer", meta_sig)
    ]

    iframe_src = f"{SCRIPT_URL}?{urllib.parse.urlencode(pdf_query_args)}"

    print("Content-Type: text/html\n")
    print(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Review Proposed Consent Document</title>
    <link rel="stylesheet" type="text/css" href="/css/{CSS_FILE}">
</head>
<body>
<div class="split-container">
    <div class="editor-panel" style="padding:25px; overflow-y:auto;">
        <form method="POST" action="{SCRIPT_URL}">
            <input type="hidden" name="client_name" value="{html.escape(client_name)}">
            <input type="hidden" name="friendly_name" value="{html.escape(friendly_name)}">
            <input type="hidden" name="local_legal_name" value="{html.escape(local_legal_name)}">
            <input type="hidden" name="tax_years_covered" value="{html.escape(tax_years_covered)}">
            <input type="hidden" name="local_street" value="{html.escape(local_street)}">
            <input type="hidden" name="local_city" value="{html.escape(local_city)}">
            <input type="hidden" name="local_state" value="{html.escape(local_state)}">
            <input type="hidden" name="local_zip" value="{html.escape(local_zip)}">
            <input type="hidden" name="meta_co_signer_name" value="{html.escape(meta_co_signer_name)}">
            <input type="hidden" name="meta_additional_signer" value="{html.escape(meta_sig)}">

            <div style="display:flex; flex-direction:column; gap:12px; margin-top:15px;">
                <button type="submit" name="action" value="revert_to_workspace" class="btn-submit btn-action-grey" style="text-align:center; padding:12px;">← Go Back & Make Edits</button>
                <button type="submit" name="action" value="download_draft_pdf" class="btn-submit btn-action-yellow" style="text-align:center; padding:12px;">⬇ Download Draft Letter</button>
                <button type="submit" name="action" value="execute_transactional_pipeline_paper" class="btn-submit btn-action-lightgreen" style="text-align:center; padding:12px;">✓ Submit Consent for Paper Signature</button>
                <button type="submit" name="action" value="execute_transactional_pipeline" class="btn-submit btn-action-green" style="text-align:center; padding:12px;">⚡ Submit Consent for Electronic Signature</button>
            </div>
        </form>
    </div>
    <div class="pdf-panel">
        <iframe src="{html.escape(iframe_src)}"></iframe>
    </div>
</div>
</body>
</html>""")

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

    # Case 1: Primary client already contains joint names (e.g., "Jack & Jane Fleisher" or "Jack and Jane Fleisher")
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

    # Case 2: Separate co-signer provided in form
    if primary_first and co_signer_first and primary_first.lower() != co_signer_first.lower():
        return f"{primary_first} and {co_signer_first}"

    # Case 3: Standard single client
    return primary_first or primary_clean

# ==========================================
# REPORTLAB PDF GENERATION LEG (PURE / STATELESS)
# ==========================================
def xml_safe_escape(text):
    if not text:
        return ""
    # Unescape existing HTML entities first to prevent double-escaping (&amp; -> & -> &amp;)
    text = html.unescape(str(text))
    text = unicodedata.normalize('NFKD', text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for tag in ["strong", "b", "i", "u"]:
        text = text.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return text.replace("&lt;br/&gt;", "<br/>").replace("&lt;br&gt;", "<br/>")

def compile_reportlab_pdf_buffer(form, include_esign_tags=False):
    """Pure rendering function: Compiles Markdown template into ReportLab PDF binary buffer."""
    raw_client_name = get_form_val(form, "client_name", "Unknown Client")
    clean_client_title = re.split(r'\s*\(Customer', html.unescape(raw_client_name))[0].strip()

    friendly_name = html.unescape(get_form_val(form, "friendly_name")).strip() or clean_client_title
    local_legal_name = html.unescape(get_form_val(form, "local_legal_name")).strip() or clean_client_title
    tax_years_covered = get_form_val(form, "tax_years_covered", "2025 and 2026 tax years")

    street = get_form_val(form, "local_street")
    city = get_form_val(form, "local_city")
    state = get_form_val(form, "local_state")
    zip_val = get_form_val(form, "local_zip")

    meta_co_signer_name = html.unescape(get_form_val(form, "meta_co_signer_name"))
    meta_sig = get_form_val(form, "meta_additional_signer").strip()

    address_parts = [p.strip() for p in [street, city, state, zip_val] if p and p.strip()]
    billing_address = ", ".join(address_parts) if address_parts else "<i>[Address Sourced on Execution]</i>"
    greeting_name = build_salutation_name(friendly_name, meta_co_signer_name)

    try:
        with open(CONSENT_TEMPLATE, "r", encoding="utf-8") as f:
            raw_markdown = f.read()
    except FileNotFoundError:
        raw_markdown = "# Tarrant Advisors LLC\n## CONSENT TO DISCLOSE TAX RETURN INFORMATION"

    jinja_tmpl = Template(raw_markdown)
    markdown_content = jinja_tmpl.render(
        TODAY_DATE=datetime.date.today().strftime('%B %d, %Y'),
        CLIENT_ADDRESS=billing_address,
        CLIENT_LEGAL_NAME=xml_safe_escape(local_legal_name),
        FRIENDLY_NAME=xml_safe_escape(friendly_name),
        GREETING_NAME=xml_safe_escape(greeting_name),
        TAX_YEARS_COVERED=xml_safe_escape(tax_years_covered),
        meta_additional_signer=meta_sig,
        CO_SIGNER_NAME=xml_safe_escape(meta_co_signer_name)
    )

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45, title=f"7216 Consent - {local_legal_name}")
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle('CustomBody', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#222222'))
    h1_style = ParagraphStyle('CustomH1', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#0078d4'), spaceAfter=10)
    h2_style = ParagraphStyle('CustomH2', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#111111'), spaceBefore=10, spaceAfter=6)
    h3_style = ParagraphStyle('CustomH3', parent=styles['Heading3'], fontSize=11, leading=15, textColor=colors.HexColor('#111111'), spaceBefore=8, spaceAfter=4)

    story = []

    for line in markdown_content.split('\n'):
        line_str = line.strip()
        if not line_str:
            story.append(Spacer(1, 4))
            continue

        if line_str.startswith("# "):
            story.append(Paragraph(line_str[2:], h1_style))
        elif line_str.startswith("## "):
            story.append(Paragraph(line_str[3:], h2_style))
        elif line_str.startswith("### "):
            story.append(Paragraph(line_str[4:], h3_style))
        elif line_str == "---":
            story.append(Spacer(1, 10))
        else:
            story.append(Paragraph(xml_safe_escape(line_str), body_style))
            story.append(Spacer(1, 4))

    def render_sig_line(label, tag, underscore_len=27):
        return f"{label}: {tag}" if include_esign_tags else f"{label}: " + "_" * underscore_len

    sig_elements = [Spacer(1, 10)]

    if meta_sig and "@" in meta_sig:
        sig_elements.extend([
            Paragraph(render_sig_line("Client Signature", "{{_es_signer1_signature}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Verified", "{{_es_signer1_date}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{xml_safe_escape(friendly_name)}</strong>", body_style),
            Spacer(1, 12),
            Paragraph(render_sig_line("Co-Signer Signature", "{{_es_signer2_signature}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Verified", "{{_es_signer2_date}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{xml_safe_escape(meta_co_signer_name if meta_co_signer_name else meta_sig)}</strong>", body_style)
        ])
    else:
        sig_elements.extend([
            Paragraph(render_sig_line("Client Signature", "{{_es_signer1_signature}}"), body_style),
            Spacer(1, 4),
            Paragraph(render_sig_line("Date Verified", "{{_es_signer1_date}}", 24), body_style),
            Spacer(1, 4),
            Paragraph(f"<strong>{xml_safe_escape(friendly_name)}</strong>", body_style)
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
    """Unified handler for PDF downloads."""
    client_name = get_form_val(form, "client_name", "Unknown Client")
    clean_client_title = re.split(r'\s*\(Customer', html.unescape(client_name))[0].strip()
    local_legal_name = html.unescape(get_form_val(form, "local_legal_name")).strip() or clean_client_title
    
    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"7216 Consent {local_legal_name} ({prefix} {timestamp_str}).pdf"
    generated_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=False)

    sys.stdout.buffer.write(b"Content-Type: application/pdf\n")
    sys.stdout.buffer.write(f"Content-Disposition: attachment; filename={urllib.parse.quote(filename)}\n\n".encode('utf-8'))
    sys.stdout.buffer.write(generated_buffer.read())

# ==========================================
# TRANSACTION PIPELINE (PHASE 3)
# ==========================================
def execute_transactional_pipeline(form):
    """Executes Adobe Sign routing without updating QBO."""
    client_name = get_form_val(form, "client_name")
    client_qbo_id = extract_qbo_id(client_name)
    friendly_name = html.unescape(get_form_val(form, "friendly_name"))
    local_legal_name = html.unescape(get_form_val(form, "local_legal_name"))
    meta_sig = get_form_val(form, "meta_additional_signer").strip()

    delivery_method = get_form_val(form, "delivery_method")
    is_paper_mode = (delivery_method == "paper")

    live_pdf_buffer = compile_reportlab_pdf_buffer(form, include_esign_tags=not is_paper_mode)
    live_pdf_buffer.seek(0)

    if is_paper_mode:
        adobe_sign_routing_success, adobe_error_context = True, ""
    else:
        adobe_sign_routing_success, adobe_error_context = submit_adobe_sign_transaction(
            client_qbo_id=client_qbo_id,
            pdf_binary_data=live_pdf_buffer.read(),
            additional_signer_email=meta_sig if "@" in meta_sig else None
        )

    if not adobe_sign_routing_success:
        return render_phase1_workspace(error_msg=f"Adobe Sign Routing Error: Consent document delivery failed. Details: {adobe_error_context}")

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
        <h2>Consent Letter Dispatched Successfully</h2>
        <p>
            Section 7216 Consent document for <strong>{html.escape(friendly_name)}</strong> has been routed via Adobe Sign.
        </p>
        <div style="background:#f9fafb; padding:15px; border-radius:4px; border:1px solid #e5e7eb; margin-bottom:20px; text-align:left; font-size:13px; font-family:monospace;">
            <strong>Execution Summary Matrix:</strong><br>
            • Customer Index: {html.escape(client_qbo_id)}<br>
            • Target Email: {html.escape(qbo_api_request(f'customer/{client_qbo_id}').get('Customer', {}).get('PrimaryEmailAddr', {}).get('Address', 'N/A'))}<br>
            • Signature Layout: {"JOINT" if (meta_sig and "@" in meta_sig) else "SINGLE"}
        </div>
        <a href="{SCRIPT_URL}" class="btn-submit" style="background:#0078d4; text-decoration:none; display:inline-block;">Create New Consent Request</a>
    </div>
</div>
</body>
</html>"""

    if is_paper_mode:
        dl_query_args = [
            ("action", "download_final_pdf"),
            ("client_name", client_name),
            ("friendly_name", friendly_name),
            ("local_legal_name", local_legal_name),
            ("tax_years_covered", get_form_val(form, "tax_years_covered")),
            ("local_street", get_form_val(form, "local_street")),
            ("local_city", get_form_val(form, "local_city")),
            ("local_state", get_form_val(form, "local_state")),
            ("local_zip", get_form_val(form, "local_zip")),
            ("meta_co_signer_name", get_form_val(form, "meta_co_signer_name")),
            ("meta_additional_signer", meta_sig)
        ]
        dl_link = f"{SCRIPT_URL}?{urllib.parse.urlencode(dl_query_args)}"
        sandbox_button_html = f"""
        <div style="margin: 20px 0; padding: 20px; background: #f0fdf4; border: 1px solid #16a34a; border-radius: 4px; text-align: center;">
            <p style="margin-top: 0; font-weight: 600; color: #16a34a; font-size: 14px;">Physical Delivery Flow Activated:</p>
            <a href="{html.escape(dl_link)}" style="background: #16a34a; color: white; padding: 12px 24px; text-decoration: none; display: inline-block; border-radius: 4px; font-weight: bold; font-size: 15px;">⬇ Download & Print Final Consent PDF</a>
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
        render_phase1_workspace(preserved_form=form_data)
    else:
        render_phase1_workspace()
