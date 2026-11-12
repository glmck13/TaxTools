#!/usr/bin/env python3
"""
Master Checklist Processing Pipeline:
1. Reads ProConnect cURL headers from stdin.
2. Queries QBO API to map QBO_Id <-> ProConnect ClientEntityId and resolve customer emails.
3. Iterates over qbosp.csv (master customer list).
4. Fetches raw JSON checklists from ProConnect API.
5. Builds formatted .xlsx workbooks using openpyxl matching the dropdown styling layout.
6. Ensures /{TAX_YEAR} subfolder exists under client folder on SharePoint.
7. Uploads .xlsx to SharePoint via m365 CLI with local staging to guarantee target file naming.
8. Creates and obtains folder sharing links via 'm365 spo folder sharinglink add' with scope 'users' and recipient email.
9. Generates direct web viewer link for the .xlsx file.
10. Outputs sp_checklists.json keyed by QBO Customer Id.
11. Includes --cleanup mode to back out sharing links and remove created checklist files.
"""

import os
import re
import sys
import json
import time
import shlex
import tempfile
import subprocess
import urllib.parse
import urllib.request
import argparse
from typing import Dict, Any, Optional, Tuple

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.formatting.rule import CellIsRule
except ImportError:
    print("[ERROR] 'openpyxl' is required. Install via: pip install openpyxl", file=sys.stderr)
    sys.exit(1)


# ==========================================
# CONSTANTS & ENVIRONMENT SETUP
# ==========================================
TAX_URL = "https://protaxdata.api.intuit.com"
DOC_URL = "https://protaxonlinecommon.api.intuit.com"

QBO_APIBASE = os.environ.get("QBO_APIBASE", "").rstrip("/")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_ACCESS_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

SPO_SITE_URL = os.environ.get("SPO_SITE_URL", "")
SPO_DOC_LIBRARY = os.environ.get("SPO_DOC_LIBRARY", "Shared Documents")
TAX_YEAR = os.environ.get("TAX_YEAR", "2026")


# ==========================================
# SHARING LINK BACKOUT & CLEANUP HELPERS
# ==========================================
def backout_sharing_links(site_url: str, folder_relative_path: str):
    """
    Lists and deletes all active sharing links on a target folder using M365 CLI.
    Executed exclusively during --cleanup mode.
    """
    clean_site_url = site_url.rstrip("/")
    clean_folder_path = "/" + urllib.parse.unquote(folder_relative_path).lstrip("/")

    list_cmd = [
        "m365", "spo", "folder", "sharinglink", "list",
        "--webUrl", clean_site_url,
        "--folderUrl", clean_folder_path,
        "-o", "json"
    ]

    try:
        res = subprocess.run(list_cmd, capture_output=True, text=True, check=True)
        links = json.loads(res.stdout or "[]")
        if not isinstance(links, list):
            links = []
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"  ├─ [CLEANUP WARNING] Could not retrieve sharing links for {clean_folder_path}: {e}", file=sys.stderr)
        return

    if not links:
        print(f"  ├─ No active sharing links found on: {clean_folder_path}", file=sys.stderr)
        return

    for link in links:
        link_id = link.get("id")
        if not link_id:
            continue
        
        remove_cmd = [
            "m365", "spo", "folder", "sharinglink", "remove",
            "--webUrl", clean_site_url,
            "--folderUrl", clean_folder_path,
            "--id", link_id,
            "--force"
        ]
        
        try:
            subprocess.run(remove_cmd, capture_output=True, text=True, check=True)
            print(f"  ├─ Removed Sharing Link ID '{link_id}' from {clean_folder_path}", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            err_msg = (e.stderr or e.stdout or "").strip()
            print(f"  ├─ [ERROR] Failed to remove link '{link_id}': {err_msg}", file=sys.stderr)


def run_cleanup_mode(json_file_path: str, site_url: str):
    """
    Reads sp_checklists.json, revokes sharing links on parent client folders via M365 CLI,
    and deletes the created checklist .xlsx files from SharePoint.
    """
    if not os.path.exists(json_file_path):
        print(f"[ERROR] JSON file not found for cleanup: {json_file_path}", file=sys.stderr)
        sys.exit(1)

    if not site_url:
        print("[ERROR] SharePoint site URL is required. Pass --site-url or set SPO_SITE_URL.", file=sys.stderr)
        sys.exit(1)

    clean_site_url = site_url.rstrip("/")

    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to read {json_file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not data:
        print(f"[INFO] {json_file_path} is empty. Nothing to clean up.", file=sys.stderr)
        return

    print(f"\n[CLEANUP] Starting backout for {len(data)} entry/entries from {json_file_path}...\n", file=sys.stderr)

    for qbo_id, entry in data.items():
        folder_url = entry.get("folder_url", "")
        checklist_url = entry.get("checklist_url", "")

        print(f"[*] Processing Cleanup for QBO ID: {qbo_id}", file=sys.stderr)

        # 1. Back out sharing links from parent client folder
        if folder_url:
            parsed_folder = urllib.parse.urlparse(folder_url)
            raw_folder_path = urllib.parse.unquote(parsed_folder.path)
            
            parsed_site = urllib.parse.urlparse(clean_site_url)
            site_path = parsed_site.path.rstrip('/')
            
            if site_path and raw_folder_path.startswith(site_path):
                folder_relative = raw_folder_path[len(site_path):]
            else:
                folder_relative = raw_folder_path

            backout_sharing_links(clean_site_url, folder_relative)

        # 2. Extract and delete target .xlsx file
        if checklist_url and "id=" in checklist_url:
            parsed_checklist = urllib.parse.urlparse(checklist_url)
            qs = urllib.parse.parse_qs(parsed_checklist.query)
            raw_file_id = qs.get("id", [""])[0]
            
            file_server_relative = urllib.parse.unquote(raw_file_id)

            if file_server_relative:
                delete_cmd = [
                    "m365", "spo", "file", "remove",
                    "--webUrl", clean_site_url,
                    "--fileUrl", file_server_relative,
                    "--force"
                ]
                try:
                    subprocess.run(delete_cmd, capture_output=True, text=True, check=True)
                    print(f"  └─ Successfully deleted checklist file: {file_server_relative}", file=sys.stderr)
                except subprocess.CalledProcessError as e:
                    err_msg = (e.stderr or e.stdout or "").strip()
                    print(f"  └─ [ERROR] Failed deleting file {file_server_relative}: {err_msg}", file=sys.stderr)

    print(f"\n[CLEANUP COMPLETE] Finished backing out links and files.", file=sys.stderr)


# ==========================================
# CURL HEADER PARSER (ProConnect Auth)
# ==========================================
def parse_curl_headers() -> Dict[str, str]:
    """Parses cURL command input from stdin or CGI POST data to extract authorization headers."""
    if os.environ.get("REQUEST_METHOD") == "POST":
        length = int(os.environ.get("CONTENT_LENGTH", 0))
        body = sys.stdin.read(length)
        params = urllib.parse.parse_qs(body)
        curl_input = params.get("clipboard_content", [None])[0] or ""
    else:
        if sys.stdin.isatty():
            print("[WARNING] Stdin is a terminal. Paste cURL headers and press Ctrl+D:", file=sys.stderr)
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


def fetch_intuit_json(url: str, headers: Dict[str, str]) -> Optional[Any]:
    """Executes HTTP GET against Intuit ProConnect endpoints."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[FETCH ERROR] Failed request to {url}: {e}", file=sys.stderr)
        return None


# ==========================================
# QUICKBOOKS ONLINE API HELPERS
# ==========================================
def qbo_api_query(query_str: str) -> Dict[str, Any]:
    """Executes authenticated SQL query against QuickBooks Online API."""
    if not QBO_APIBASE or not QBO_REALMID or not QBO_ACCESS_TOKEN:
        print("[ERROR] Missing QBO environment variables (QBO_APIBASE, QBO_REALMID, QBO_ACCESS_TOKEN).", file=sys.stderr)
        sys.exit(1)

    encoded_query = urllib.parse.quote(query_str)
    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/query?query={encoded_query}"
    
    headers = {
        "Authorization": f"Bearer {QBO_ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[QBO ERROR] HTTP {e.code}: {error_body}", file=sys.stderr)
        raise Exception(f"QBO Query Failed: {error_body}")


def get_qbo_customer_metadata() -> Dict[str, Dict[str, str]]:
    """
    Queries active QBO customers and builds metadata lookup:
    QBO_Id -> { "client_entity_id": ..., "email": ... }
    """
    print("[INFO] Querying QBO active customer records...", file=sys.stderr)
    res = qbo_api_query("select * from Customer WHERE Active = true MAXRESULTS 1000")
    customers = res.get("QueryResponse", {}).get("Customer", [])

    qbo_meta = {}
    for c in customers:
        qbo_id = str(c["Id"])
        client_entity_id = c.get("ClientEntityId") or ""
        
        raw_c_email = c.get("PrimaryEmailAddr", {}).get("Address", "")
        primary_email = raw_c_email.split(",")[0].strip() if raw_c_email else ""
        
        notes_email = ""
        if c.get("Notes"):
            try:
                notes_obj = json.loads(c["Notes"])
                if not client_entity_id:
                    client_entity_id = str(notes_obj.get("client_id") or notes_obj.get("ClientEntityId") or "")
                
                signers = notes_obj.get("signers", [])
                if isinstance(signers, list) and len(signers) > 0 and isinstance(signers[0], dict):
                    notes_email = str(signers[0].get("email", "")).strip()
            except Exception:
                pass

        effective_email = primary_email or notes_email

        qbo_meta[qbo_id] = {
            "client_entity_id": str(client_entity_id),
            "email": effective_email
        }

    print(f"[INFO] Fetched metadata for {len(qbo_meta)} QBO customer(s).", file=sys.stderr)
    return qbo_meta


# ==========================================
# EXCEL GENERATOR (openpyxl with Dropdown DataValidation & Color Rules)
# ==========================================
def clean_item_text(text: str) -> str:
    """Strips boilerplate instruction prefixes from document requests."""
    if not text:
        return ""
    pattern = r'^(?:Please\s+)?(?:upload|provide|submit|share)(?:\s+all|\s+your|\s+us)?\s+'
    return re.sub(pattern, '', str(text), flags=re.IGNORECASE).strip()


def build_excel_workbook(data: Dict[str, Any], output_path: str):
    """Generates an Excel checklist workbook matching the styled layout with conditional dropdown formatting."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Document Checklist"
    ws.views.sheetView[0].showGridLines = True

    client_name = str(data.get("client_name") or "Unknown Client")

    font_title = Font(name="Segoe UI", size=16, bold=True, color="1E3A8A")
    font_label_bold = Font(name="Segoe UI", size=10, bold=True, color="0F172A")
    font_label_regular = Font(name="Segoe UI", size=10, color="0F172A")
    font_inst = Font(name="Segoe UI", size=10, color="1E3A8A")
    font_cat = Font(name="Segoe UI", size=11, bold=True, color="334155")
    font_tbl_header = Font(name="Segoe UI", size=10, bold=True, color="0F172A")
    font_data = Font(name="Calibri", size=11, color="000000")

    fill_label = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_inst = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
    fill_cat = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    fill_tbl_header = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    border_side = Side(border_style="thin", color="CBD5E1")
    border_all = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    dv = DataValidation(type="list", formula1='"Pending, Completed"', allow_blank=True)
    ws.add_data_validation(dv)

    ws["A1"] = "Client Tax Document Checklist"
    ws["A1"].font = font_title

    ws.merge_cells("B3:D3")
    ws["A3"] = "Client Name"
    ws["A3"].font = font_label_bold
    ws["A3"].fill = fill_label
    ws["A3"].border = border_all

    ws["B3"] = client_name
    ws["B3"].font = font_label_regular
    for col in range(2, 5):
        ws.cell(row=3, column=col).border = border_all

    ws.merge_cells("A5:D5")
    inst_cell = ws["A5"]
    inst_cell.value = "Instructions: Please gather the requested tax documents listed below. Update status to Completed as you collect each item and submit supporting files to your tax preparer."
    inst_cell.font = font_inst
    inst_cell.fill = fill_inst
    inst_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[5].height = 28

    checklist_obj = data.get("checklist") if "checklist" in data else data
    source_docs = checklist_obj.get("sourceDocuments") if isinstance(checklist_obj, dict) else []
    source_docs = source_docs or []

    categories = {}
    for doc in source_docs:
        if isinstance(doc, dict):
            doc_type = str(doc.get("sourceDocumentType") or "Other").upper()
            categories.setdefault(doc_type, []).append(doc)

    item_counter = 1
    r = 7
    status_cells = []

    for category, docs in categories.items():
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        cat_cell = ws.cell(row=r, column=1, value=f"Category: {category}")
        cat_cell.font = font_cat
        cat_cell.fill = fill_cat
        cat_cell.alignment = align_center
        ws.row_dimensions[r].height = 24
        r += 1

        headers_def = [
            ("Status", align_center),
            ("#", align_center),
            ("Document Requested", align_left),
            ("Notes / Comments", align_left)
        ]

        for col_idx, (h_text, h_align) in enumerate(headers_def, 1):
            cell = ws.cell(row=r, column=col_idx, value=h_text)
            cell.font = font_tbl_header
            cell.fill = fill_tbl_header
            cell.border = border_all
            cell.alignment = h_align
        ws.row_dimensions[r].height = 20
        r += 1

        for doc in docs:
            raw_text = doc.get("text", "")
            display_text = clean_item_text(raw_text)

            c1 = ws.cell(row=r, column=1, value="Pending")
            c1.font = font_data
            c1.alignment = align_center
            c1.border = border_all
            dv.add(c1)
            status_cells.append(f"A{r}")

            c2 = ws.cell(row=r, column=2, value=item_counter)
            c2.font = font_data
            c2.alignment = align_center
            c2.border = border_all

            c3 = ws.cell(row=r, column=3, value=display_text)
            c3.font = font_data
            c3.alignment = align_left
            c3.border = border_all

            c4 = ws.cell(row=r, column=4, value=None)
            c4.font = font_data
            c4.alignment = align_left
            c4.border = border_all

            ws.row_dimensions[r].height = 20
            item_counter += 1
            r += 1

        r += 1

    # Apply Conditional Color Rules to Status Column
    if status_cells:
        cf_range = f"A8:A{r}"
        
        fill_pending = PatternFill(start_color="FFEDD5", end_color="FFEDD5", fill_type="solid")
        font_pending = Font(name="Calibri", size=11, bold=True, color="9A3412")
        rule_pending = CellIsRule(operator='equal', formula=['"Pending"'], fill=fill_pending, font=font_pending)
        
        fill_completed = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        font_completed = Font(name="Calibri", size=11, bold=True, color="166534")
        rule_completed = CellIsRule(operator='equal', formula=['"Completed"'], fill=fill_completed, font=font_completed)

        ws.conditional_formatting.add(cf_range, rule_pending)
        ws.conditional_formatting.add(cf_range, rule_completed)

    ws.column_dimensions['A'].width = 16.0
    ws.column_dimensions['B'].width = 8.0
    ws.column_dimensions['C'].width = 65.0
    ws.column_dimensions['D'].width = 30.0

    wb.save(output_path)


# ==========================================
# SHAREPOINT INTEGRATION (m365 CLI via Sharing Links)
# ==========================================
def ensure_sharepoint_folder(site_url: str, folder_path: str):
    """Ensures a subfolder (e.g. Shared Documents/Client_Folder/2026) exists on SharePoint."""
    cmd = [
        "m365", "spo", "folder", "add",
        "--webUrl", site_url,
        "--folderUrl", folder_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        pass


def process_sharepoint_upload_and_sharing(
    site_url: str,
    doc_lib: str,
    sp_folder: str,
    tax_year: str,
    client_email: str,
    local_file_path: str,
    remote_filename: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    1. Ensures /{TAX_YEAR} subfolder exists under client folder.
    2. Uploads file via m365 spo file add using local named copy.
    3. Creates/obtains folder sharing link via m365 spo folder sharinglink add with scope 'users' and recipients.
    4. Generates direct web-editor viewing URL for the .xlsx file.
    Returns: (folder_url, checklist_url)
    """
    clean_site_url = site_url.rstrip("/")
    base_folder_path = f"{doc_lib}/{sp_folder}".strip("/")
    year_folder_path = f"{base_folder_path}/{tax_year}"

    ensure_sharepoint_folder(clean_site_url, year_folder_path)

    # 1. File Upload via local named copy
    stage_dir = os.path.dirname(local_file_path)
    staged_file_path = os.path.join(stage_dir, remote_filename)
    
    if os.path.exists(staged_file_path):
        os.remove(staged_file_path)
    os.rename(local_file_path, staged_file_path)

    upload_cmd = [
        "m365", "spo", "file", "add",
        "--webUrl", clean_site_url,
        "--folder", year_folder_path,
        "--path", staged_file_path,
        "--overwrite"
    ]
    
    try:
        subprocess.run(upload_cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or e.stdout or "").strip()
        print(f"[M365 UPLOAD ERROR] Failed uploading {remote_filename}: {err_msg}", file=sys.stderr)
        return None, None
    finally:
        if os.path.exists(staged_file_path):
            os.remove(staged_file_path)

    # 2. Obtain Folder Sharing Link via m365 spo folder sharinglink add (Scope: users, with recipients)
    folder_url = ""
    if client_email:
        folder_relative_path = f"/{doc_lib}/{sp_folder}".replace("//", "/")
        add_link_cmd = [
            "m365", "spo", "folder", "sharinglink", "add",
            "--webUrl", clean_site_url,
            "--folderUrl", folder_relative_path,
            "--type", "edit",
            "--scope", "users",
            "--recipients", client_email,
            "-o", "json"
        ]
        try:
            res = subprocess.run(add_link_cmd, capture_output=True, text=True, check=True)
            link_data = json.loads(res.stdout or "{}")
            if isinstance(link_data, dict):
                folder_url = link_data.get("link") or link_data.get("Url") or link_data.get("webUrl") or ""
            elif isinstance(link_data, list) and len(link_data) > 0:
                folder_url = link_data[0].get("link") or link_data[0].get("Url") or link_data[0].get("webUrl") or ""
            print(f"  ├─ Created sharing link for folder {sp_folder} (Recipients: {client_email or 'None'})", file=sys.stderr)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            err_msg = getattr(e, 'stderr', str(e)).strip() if hasattr(e, 'stderr') else str(e)
            print(f"[M365 SHARING LINK WARNING] Failed creating folder sharing link for {sp_folder}: {err_msg}", file=sys.stderr)
            folder_url = f"{clean_site_url}/{urllib.parse.quote(base_folder_path)}"

    # 3. Construct Direct Web-Editor Viewing Link for the Excel Checklist
    parsed_site = urllib.parse.urlparse(clean_site_url)
    site_path = parsed_site.path.rstrip('/')
    
    relative_file_path = f"{site_path}/{year_folder_path}/{remote_filename}".replace("//", "/")
    relative_parent_path = f"{site_path}/{year_folder_path}".replace("//", "/")

    encoded_id = urllib.parse.quote(relative_file_path)
    encoded_parent = urllib.parse.quote(relative_parent_path)

    checklist_url = (
        f"{clean_site_url}/{urllib.parse.quote(doc_lib)}/Forms/AllItems.aspx"
        f"?id={encoded_id}&parent={encoded_parent}"
    )

    return folder_url, checklist_url


# ==========================================
# MAIN EXECUTION PIPELINE
# ==========================================
def parse_qbosp_csv(qbosp_path: str) -> Dict[str, Dict[str, str]]:
    """Parses colon-separated qbosp.csv (QBO_Id:Name:SP_Folder) into customer target lookup."""
    customers = {}
    if not os.path.exists(qbosp_path):
        print(f"[ERROR] qbosp.csv not found at: {qbosp_path}", file=sys.stderr)
        sys.exit(1)

    with open(qbosp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.lower().startswith("qbo_id") or line_str.startswith("#"):
                continue
            parts = line_str.split(":", 4)
            if len(parts) >= 3 and parts[0].strip() and parts[2].strip():
                qbo_id = parts[0].strip()
                c_name = parts[1].strip()
                sp_folder = parts[2].strip()
                customers[qbo_id] = {
                    "name": c_name,
                    "sp_folder": sp_folder
                }
    return customers


def main():
    parser = argparse.ArgumentParser(description="Process ProConnect checklists, build Excel files with dropdowns, upload to SharePoint via m365 CLI.")
    parser.add_argument("-q", "--qbosp", default="qbosp.csv", help="Path to qbosp.csv mapping file (default: qbosp.csv)")
    parser.add_argument("-o", "--output-json", default="sp_checklists.json", help="Path for output JSON link mapping (default: sp_checklists.json)")
    parser.add_argument("--site-url", default=SPO_SITE_URL, help="SharePoint Site Web URL")
    parser.add_argument("--doc-lib", default=SPO_DOC_LIBRARY, help="SharePoint Document Library folder root (default: Shared Documents)")
    parser.add_argument("--tax-year", default=TAX_YEAR, help="Tax year parameter for API requests (default: 2026)")
    parser.add_argument("--cleanup", action="store_true", help="Run in cleanup mode: read JSON output, remove sharing links via CLI, and delete uploaded checklist files.")

    args = parser.parse_args()

    site_url = args.site_url
    doc_lib = args.doc_lib
    qbosp_path = args.qbosp
    out_json_path = args.output_json
    tax_year = args.tax_year

    # If --cleanup is passed, execute the backout process and exit
    if args.cleanup:
        run_cleanup_mode(out_json_path, site_url)
        sys.exit(0)

    if not site_url:
        print("[ERROR] SharePoint site URL is required. Set SPO_SITE_URL env var or pass --site-url.", file=sys.stderr)
        sys.exit(1)

    headers = parse_curl_headers()
    if 'authorization' not in headers:
        print("[ERROR] Missing 'authorization' header in cURL input from stdin.", file=sys.stderr)
        sys.exit(1)

    qbo_meta = get_qbo_customer_metadata()
    qbosp_customers = parse_qbosp_csv(qbosp_path)
    print(f"[INFO] Loaded {len(qbosp_customers)} master customer(s) from {qbosp_path}.", file=sys.stderr)

    print(f"[INFO] Fetching {tax_year} tax returns filter from ProConnect...", file=sys.stderr)
    prior_year = str(int(tax_year) - 1)
    returns_list = fetch_intuit_json(f"{TAX_URL}/v1/returns/filter/{prior_year}?use-oii-client-id=true", headers)
    if not isinstance(returns_list, list):
        print("[ERROR] Failed to retrieve valid returns list from ProConnect.", file=sys.stderr)
        sys.exit(1)

    returns_by_client_id = {}
    for ret in returns_list:
        if isinstance(ret, dict) and ret.get('id_client'):
            returns_by_client_id[str(ret['id_client'])] = ret

    sharepoint_links = {}
    processed_count = 0

    print("\n[INFO] Starting checklist extraction, Excel creation, and SharePoint upload loop...\n", file=sys.stderr)

    for qbo_id, cust_info in qbosp_customers.items():
        c_name = cust_info["name"]
        sp_folder = cust_info["sp_folder"]

        meta = qbo_meta.get(qbo_id, {})
        proconnect_id = meta.get("client_entity_id")
        client_email = meta.get("email", "")

        if not proconnect_id:
            print(f"[-] Skipping QBO ID {qbo_id} ({c_name}): No matching ProConnect ClientEntityId found in QBO.", file=sys.stderr)
            continue

        ret_data = returns_by_client_id.get(proconnect_id)
        return_name = ret_data.get('name') if ret_data else f'{tax_year} Tax Return'

        # Fetch ProConnect Checklist safely
        checklist_url_api = f"{DOC_URL}/v1/doc-checklist/{proconnect_id}?currentYear={tax_year}"
        checklist_data = fetch_intuit_json(checklist_url_api, headers)
        
        if not checklist_data:
            print(f"[-] Warning: No checklist data returned for {c_name} (ProConnect ID: {proconnect_id}). Skipping...", file=sys.stderr)
            continue

        payload = {
            "client_id": proconnect_id,
            "client_name": c_name,
            "return_name": return_name,
            "checklist": checklist_data
        }

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp_file:
            tmp_xlsx_path = tmp_file.name

        try:
            build_excel_workbook(payload, tmp_xlsx_path)

            target_filename = f"Tax_Checklist_{qbo_id}.xlsx"
            processed_count += 1
            print(f"[{processed_count}] Processing [{c_name}] (QBO ID: {qbo_id}) -> Folder: '{sp_folder}/{tax_year}'...", file=sys.stderr)
            
            folder_url, checklist_url = process_sharepoint_upload_and_sharing(
                site_url, doc_lib, sp_folder, tax_year, client_email, tmp_xlsx_path, target_filename
            )

            if checklist_url:
                sharepoint_links[qbo_id] = {
                    "folder_url": folder_url or "",
                    "checklist_url": checklist_url
                }
                print(f"  ├─ Folder URL   : {folder_url}", file=sys.stderr)
                print(f"  └─ Checklist URL: {checklist_url}", file=sys.stderr)
            else:
                print(f"  └─ Warning: Processed but failed retrieving checklist web link for QBO ID {qbo_id}", file=sys.stderr)

        finally:
            if os.path.exists(tmp_xlsx_path):
                os.remove(tmp_xlsx_path)

        time.sleep(0.1)

    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(sharepoint_links, f, indent=2)

    print(f"\n[SUCCESS] Execution complete! Successfully processed {processed_count} checklist(s).", file=sys.stderr)
    print(f"  - Keyed output JSON saved to: {out_json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
