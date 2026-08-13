#!/usr/bin/env python3

import os
import json
import csv
import re
import io
import requests
from typing import List, Dict, Any, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. ENVIRONMENT & SETUP
# ---------------------------------------------------------------------------
QBO_APIBASE = os.getenv("QBO_APIBASE", "https://quickbooks.api.intuit.com/v3")
QBO_REALMID = os.getenv("QBO_REALMID")
QBO_ACCESS_TOKEN = os.getenv("QBO_ACCESS_TOKEN")
DRAFTS_DIR = os.getenv("DRAFTS_DIR", "./engagements")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://appserver.tarrantadvisors.com/cgi/m365_dashboard.cgi")
WWW_DIR = "/var/www"

os.makedirs(DRAFTS_DIR, exist_ok=True)

if not QBO_REALMID or not QBO_ACCESS_TOKEN:
    raise ValueError("Missing QBO_REALMID or QBO_ACCESS_TOKEN in environment. Ensure qboTokens.conf was sourced.")

ai_client = genai.Client()

# ---------------------------------------------------------------------------
# 2. PYDANTIC SCHEMA DEFINITIONS
# ---------------------------------------------------------------------------
class DraftRow(BaseModel):
    item_id: str = Field(..., description="QBO catalog item ID")
    service: str = Field(..., description="Service line title")
    fee: str = Field(..., description="Resolved fee string")
    notes: str = Field(default="", description="Always output an empty string")
    bp: str = Field(default="individual", description="'individual' or 'organization'")

    @field_validator("fee", mode="before")
    @classmethod
    def coerce_fee_to_str(cls, v: Any) -> str:
        """Coerces numeric float/int fees into formatted string values."""
        if isinstance(v, (int, float)):
            return f"{v:.2f}"
        return str(v)

class ClientDraftSchema(BaseModel):
    qbo_id: Optional[str] = Field(default=None, description="QBO Customer ID")
    estimate_date_option: str = Field(default="next_year")
    friendly_name: str = Field(..., description="Display name")
    heal_legal_name: str = Field(..., description="Full legal name")
    heal_profile_flag: str = Field(default="false")
    meta_additional_signer: str = Field(default="")
    meta_signature_type: str = Field(..., description="Single signer or email/joint")
    meta_co_signer_name: str = Field(default="", description="Spouse name if joint")
    meta_entity_type: str = Field(..., description="'individual', 's_corp', 'partnership', 'c_corp', 'non_profit', or 'trust'")
    heal_street: str = Field(default="")
    heal_city: str = Field(default="")
    heal_state: str = Field(default="")
    heal_zip: str = Field(default="")
    out_of_scope_items: Union[Dict[str, str], List[str]] = Field(default_factory=dict, description="Out of scope items map or list")
    estimate_id: str = Field(default="")
    rows: List[DraftRow] = Field(..., description="Mapped service lines")
    delivery_format: str = Field(default="electronic", description="'electronic' or 'paper'")

# ---------------------------------------------------------------------------
# 3. HELPER FUNCTIONS & DATA PRE-PROCESSING
# ---------------------------------------------------------------------------
def load_dashboard_formats(url: str = DASHBOARD_URL) -> Dict[str, str]:
    """Dynamically fetches the dashboard CSV and extracts map of SharePoint folder name -> lowercased format."""
    print(f"Fetching delivery formats from dashboard ({url})...")
    format_map = {}
    try:
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
        
        reader = csv.DictReader(io.StringIO(resp.text), delimiter="|")
        for row in reader:
            server_url = row.get("ServerUrl", "").strip()
            fmt = row.get("Format", "").strip().lower()
            
            if server_url and fmt:
                folder_name = server_url.rstrip("/").split("/")[-1].strip()
                if folder_name:
                    format_map[folder_name] = fmt
                    
        print(f"Loaded {len(format_map)} delivery format records from dashboard.")
    except Exception as e:
        print(f"Warning: Failed to fetch dashboard CSV: {e}. Defaulting all delivery_formats to 'electronic'.")
        
    return format_map

def load_sp_mappings(csv_path: str = f"{WWW_DIR}/etc/qbosp.csv") -> Dict[str, str]:
    mapping = {}
    if not os.path.exists(csv_path):
        print(f"Warning: '{csv_path}' not found. Proceeding with empty SP mapping.")
        return mapping
    
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=":")
        for row in reader:
            if not row or row[0].startswith("qbo_id") or len(row) < 3:
                continue
            qbo_id = row[0].strip()
            sp_folder = row[2].strip()
            mapping[qbo_id] = sp_folder
    return mapping

def extract_catalog_data(template_path: str = f"{WWW_DIR}/cgi/services_template.md") -> tuple[Dict[str, Any], Dict[str, str]]:
    """
    Parses services_template.md to build:
    1. catalog_map: { item_id: { "service": title, "catalog_fee": fee } }
    2. migration_map: { old_item_id: new_2026_item_id } parsed from 'Migrates-From: XX' tags
    """
    catalog_map = {}
    migration_map = {}

    if not os.path.exists(template_path):
        print(f"Warning: Template file '{template_path}' not found.")
        return catalog_map, migration_map

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split markdown by sections (heading level 2)
    sections = re.split(r"\n(?=##\s+)", content)

    for section in sections:
        title_match = re.search(r"##\s*([^\n]+)", section)
        id_match = re.search(r"-\s*ID:\s*`?(\d+)`?", section, re.IGNORECASE)
        fee_match = re.search(r"-\s*Fee:\s*\$?([\d\.]+)", section, re.IGNORECASE)
        migrates_match = re.search(r"-\s*Migrates-From:\s*`?(\d+)`?", section, re.IGNORECASE)

        if title_match and id_match:
            item_id = id_match.group(1).strip()
            service_title = title_match.group(1).strip()
            
            fee_val = 0.0
            if fee_match:
                try:
                    fee_val = float(fee_match.group(1))
                except ValueError:
                    fee_val = 0.0

            catalog_map[item_id] = {
                "service": service_title,
                "catalog_fee": fee_val
            }

            if migrates_match:
                old_id = migrates_match.group(1).strip()
                migration_map[old_id] = item_id

    return catalog_map, migration_map

def translate_and_filter_service_lines(
    lines: List[Dict[str, Any]], 
    catalog_map: Dict[str, Any], 
    migration_map: Dict[str, str], 
    target_year: int = 2026
) -> List[Dict[str, Any]]:
    """
    Applies Option C1 migration logic:
    1. Drops lines referencing tax years prior to 2025 (< 2025).
    2. Uses migration_map (Option C1) to cleanly migrate 2025 item_ids & titles to 2026 offerings.
    3. Ageless items pass through untouched.
    4. Unmapped 2025 items retain original 2025 title & ID (sore thumb rule for review).
    """
    prior_year = target_year - 1  # 2025
    filtered_lines = []
    year_pattern = re.compile(r"\b(20\d{2})\b")

    for line in lines:
        service_title = line.get("service", "")
        item_id = str(line.get("item_id", "")).strip()

        years_found = [int(y) for y in year_pattern.findall(service_title)]

        # Rule 1: Omit services referencing tax years older than 2025 (e.g., 2024, 2023)
        if any(y < prior_year for y in years_found):
            continue

        line_copy = dict(line)

        # Rule 2: Clean migration if an explicit 'Migrates-From' link exists in services_template.md
        if item_id in migration_map:
            new_item_id = migration_map[item_id]
            line_copy["item_id"] = new_item_id
            if new_item_id in catalog_map:
                line_copy["service"] = catalog_map[new_item_id]["service"]
            else:
                line_copy["service"] = service_title.replace(str(prior_year), str(target_year))

        # Rule 3 & 4: If no migration mapping exists, preserve original item_id and exact title
        # (Ageless items pass through; unmapped 2025 items stick out as 'sore thumbs')
        filtered_lines.append(line_copy)

    return filtered_lines

def query_qbo_paginated(entity_name: str, base_where: str = "") -> List[Dict[str, Any]]:
    results = []
    start_pos = 1
    max_results = 100
    
    headers = {
        "Authorization": f"Bearer {QBO_ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    while True:
        where_clause = f"WHERE {base_where} " if base_where else ""
        query_str = f"SELECT * FROM {entity_name} {where_clause}STARTPOSITION {start_pos} MAXRESULTS {max_results}"
        url = f"{QBO_APIBASE}/company/{QBO_REALMID}/query?query={requests.utils.quote(query_str)}&minorversion=65"
        
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("QueryResponse", {})
        items = data.get(entity_name, [])
        
        if not items:
            break
            
        results.extend(items)
        if len(items) < max_results:
            break
            
        start_pos += max_results

    return results

def clean_invoice_payload(inv: Dict[str, Any], catalog_map: Dict[str, Any], migration_map: Dict[str, str]) -> Dict[str, Any]:
    if not inv:
        return {"consolidated_lines": []}
    
    consolidated: Dict[str, Dict[str, Any]] = {}
    
    for line in inv.get("Line", []):
        detail = line.get("SalesItemLineDetail", {})
        item_ref = detail.get("ItemRef", {})
        item_id = item_ref.get("value")
        item_name = item_ref.get("name", "")
        raw_amt = line.get("Amount", 0.0)
        
        if not item_id:
            continue

        amt = abs(raw_amt) if item_id == "18" else raw_amt

        if item_id in consolidated:
            consolidated[item_id]["historical_fee"] += amt
        else:
            consolidated[item_id] = {
                "item_id": item_id,
                "service": item_name,
                "historical_fee": amt
            }
            
    cleaned_lines = []
    for item_id, line_data in consolidated.items():
        cleaned_lines.append({
            "item_id": item_id,
            "service": line_data["service"],
            "historical_fee": f"{line_data['historical_fee']:.2f}"
        })
            
    # Apply Python service line migration and filtering (< 2025 dropped, Option C1 applied)
    migrated_lines = translate_and_filter_service_lines(cleaned_lines, catalog_map, migration_map, target_year=2026)
    return {"consolidated_lines": migrated_lines}

def get_qbo_data(catalog_map: Dict[str, Any], migration_map: Dict[str, str]) -> List[Dict[str, Any]]:
    dashboard_formats = load_dashboard_formats()
    sp_mapping = load_sp_mappings()
    
    print("Fetching active customers from QBO...")
    customers = query_qbo_paginated("Customer", "Active = true")
    
    print("Fetching 2026 invoices from QBO...")
    invoices = query_qbo_paginated("Invoice", "TxnDate >= '2026-01-01'")
    
    customer_invoices: Dict[str, Dict[str, Any]] = {}
    for inv in invoices:
        cust_ref = inv.get("CustomerRef", {}).get("value")
        if cust_ref:
            customer_invoices[cust_ref] = inv
            
    combined_records = []
    
    for c in customers:
        q_id = str(c.get("Id"))
        bill_addr = c.get("BillAddr", {})
        raw_inv = customer_invoices.get(q_id, {})
        sp_folder = sp_mapping.get(q_id, "")
        
        # Resolve delivery_format using sp_folder cross-reference; default to "electronic"
        delivery_fmt = dashboard_formats.get(sp_folder, "electronic")
        
        combined_records.append({
            "qbo_id": q_id,
            "display_name": c.get("DisplayName", ""),
            "company_name": c.get("CompanyName", ""),
            "address": {
                "street": bill_addr.get("Line1", ""),
                "city": bill_addr.get("City", ""),
                "state": bill_addr.get("CountrySubDivisionCode", ""),
                "zip": bill_addr.get("PostalCode", "")
            },
            "qbo_invoice": clean_invoice_payload(raw_inv, catalog_map, migration_map),
            "sharepoint_folder": sp_folder,
            "delivery_format": delivery_fmt
        })
        
    print(f"Prepared {len(combined_records)} unified client records.")
    return combined_records

# ---------------------------------------------------------------------------
# 4. SINGLE-CLIENT PARALLEL WORKER
# ---------------------------------------------------------------------------
def process_single_client(args: tuple) -> bool:
    """Processes ONE client record through Gemini Flash to extract name, signer & entity classification."""
    client_data, catalog_map = args
    qbo_id = client_data.get("qbo_id")
    expected_delivery_format = client_data.get("delivery_format", "electronic")
    
    system_instruction = """
You are an accounting ETL engine. Extract names, entity classifications, and signer metadata from 1 client record.

Return 1 valid JSON object with EXACTLY these top-level keys:
- friendly_name
- heal_legal_name
- meta_signature_type ("single", "joint", or email address if additional signer email is present)
- meta_co_signer_name (Spouse/co-signer full name if joint, else "")
- meta_entity_type ('individual', 's_corp', 'partnership', 'c_corp', 'non_profit', or 'trust')

RULES:
1. Entity Classification: Check company_name, display_name, sharepoint_folder for LLC, Inc, Corp, Partners, Trust, Org keywords.
   Set meta_entity_type to 'individual', 's_corp', 'partnership', 'c_corp', 'non_profit', or 'trust'.
2. Name Formatting:
   - Convert ALL UPPERCASE names into Proper Title Case (e.g., "ALBERTS KERI L." -> "Keri Alberts").
   - friendly_name: Output in "First Last" order in Title Case. Drop middle initials (e.g., "ALBERTS KERI L." -> "Keri Alberts").
   - heal_legal_name: Output full legal name in Title Case (e.g., "ALBERTS KERI L." -> "Keri L. Alberts").
3. Joint Signers: Check display_name and sharepoint_folder for spouse/joint names.
   - If co-signer name found: set meta_co_signer_name in Title Case.
   - If co-signer email found: set meta_signature_type to that email address.
   - Else if joint co-signer exists without email: set meta_signature_type='joint'.
   - Else if single signer: set meta_signature_type='single' & meta_co_signer_name="".
"""

    user_payload = json.dumps({
        "display_name": client_data.get("display_name", ""),
        "company_name": client_data.get("company_name", ""),
        "sharepoint_folder": client_data.get("sharepoint_folder", "")
    })

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        temperature=0.1
    )

    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_payload,
            config=config,
        )

        llm_data = json.loads(response.text)
        
        # Determine organizational context for BP row tag
        entity_type = llm_data.get("meta_entity_type", "individual").lower()
        is_org = entity_type in ["s_corp", "partnership", "c_corp", "non_profit", "trust"]
        bp_value = "organization" if is_org else "individual"

        # Deterministically build service rows using Python migration & historical_fee priority
        rows = []
        inv_lines = client_data.get("qbo_invoice", {}).get("consolidated_lines", [])
        for line in inv_lines:
            item_id = str(line.get("item_id", ""))
            service_title = line.get("service", "")
            
            # Prioritize historical fee if > 0.00, else fall back to catalog fee
            hist_fee = float(line.get("historical_fee", 0.0))
            if hist_fee > 0.0:
                fee_str = f"{hist_fee:.2f}"
            else:
                cat_fee = catalog_map.get(item_id, {}).get("catalog_fee", 0.0)
                fee_str = f"{cat_fee:.2f}"

            rows.append({
                "item_id": item_id,
                "service": service_title,
                "fee": fee_str,
                "notes": "",
                "bp": bp_value
            })

        # Format address cleanly in Python
        raw_addr = client_data.get("address", {})
        street = raw_addr.get("street", "").title() if raw_addr.get("street", "").isupper() else raw_addr.get("street", "")
        city = raw_addr.get("city", "").title() if raw_addr.get("city", "").isupper() else raw_addr.get("city", "")

        # Assemble full, deterministic ClientDraftSchema payload
        meta_sig = llm_data.get("meta_signature_type", "single")
        add_signer_email = meta_sig if "@" in meta_sig else ""

        draft_dict = {
            "qbo_id": qbo_id,
            "estimate_date_option": "next_year",
            "friendly_name": llm_data.get("friendly_name", client_data.get("display_name", "")),
            "heal_legal_name": llm_data.get("heal_legal_name", client_data.get("display_name", "")),
            "heal_profile_flag": "false",
            "meta_additional_signer": add_signer_email,
            "meta_signature_type": meta_sig,
            "meta_co_signer_name": llm_data.get("meta_co_signer_name", ""),
            "meta_entity_type": entity_type,
            "heal_street": street,
            "heal_city": city,
            "heal_state": raw_addr.get("state", ""),
            "heal_zip": raw_addr.get("zip", ""),
            "out_of_scope_items": {},
            "estimate_id": "",
            "rows": rows,
            "delivery_format": expected_delivery_format
        }

        # Validate directly against ClientDraftSchema
        draft = ClientDraftSchema(**draft_dict)
        
        if not qbo_id:
            return False
            
        file_path = os.path.join(DRAFTS_DIR, f"client_{qbo_id}.json")
        output_dict = draft.model_dump()
        output_dict.pop("qbo_id", None)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(output_dict, f, indent=2)
            
        return True
    except Exception as e:
        print(f"  !! Error processing client {qbo_id}: {e}")
        return False

# ---------------------------------------------------------------------------
# 5. MAIN PARALLEL EXECUTION LOOP
# ---------------------------------------------------------------------------
def main():
    catalog_map, migration_map = extract_catalog_data()
    print(f"Loaded catalog map ({len(catalog_map)} items) and Option C1 migration links ({len(migration_map)} mapped).")
    
    client_records = get_qbo_data(catalog_map, migration_map)
    
    total_clients = len(client_records)
    print(f"\nProcessing {total_clients} clients concurrently (15 parallel workers) via Gemini 2.5 Flash...")
    
    tasks = [(c, catalog_map) for c in client_records]
    completed = 0
    
    MAX_WORKERS = 15
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_single_client, task) for task in tasks]
        for future in as_completed(futures):
            if future.result():
                completed += 1
                if completed % 25 == 0 or completed == total_clients:
                    print(f"  Progress: {completed}/{total_clients} client files generated...")

    print(f"\nETL Pipeline Execution Complete! Generated {completed} client JSON file(s) in '{DRAFTS_DIR}'.")

if __name__ == "__main__":
    main()
