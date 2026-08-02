#!/usr/bin/env python3

import os
import json
import csv
import re
import requests
from typing import List, Dict, Any, Optional
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
        """Coerces numeric float/int fees returned by LLM into formatted string values."""
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
    meta_signature_type: str = Field(..., description="'single' or 'joint'")
    meta_co_signer_name: str = Field(default="", description="Spouse name if joint")
    meta_entity_type: str = Field(..., description="'individual', 's_corp', 'partnership', or 'llc'")
    heal_street: str = Field(default="")
    heal_city: str = Field(default="")
    heal_state: str = Field(default="")
    heal_zip: str = Field(default="")
    out_of_scope_items: List[str] = Field(default_factory=list, description="Always output an empty list")
    estimate_id: str = Field(default="")
    rows: List[DraftRow] = Field(..., description="Mapped service lines")

# ---------------------------------------------------------------------------
# 3. HELPER FUNCTIONS & DATA PRE-PROCESSING
# ---------------------------------------------------------------------------
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

def extract_catalog_fees(template_path: str = f"{WWW_DIR}/cgi/services_template.md") -> Dict[str, Any]:
    if not os.path.exists(template_path):
        return {}

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    catalog_map = {}
    pattern = re.compile(r"ID:\s*`?(\d+)`?.*?Service:\s*\*\*([^\*]+)\*\*.*?Fee:\s*\$?([\d\.]+)", re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(content)

    for item_id, service_title, fee_str in matches:
        try:
            fee_val = float(fee_str)
        except ValueError:
            fee_val = 0.0
            
        catalog_map[item_id.strip()] = {
            "service": service_title.strip(),
            "catalog_fee": fee_val
        }

    return catalog_map

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
        
        resp = requests.get(url, headers=headers)
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

def clean_invoice_payload(inv: Dict[str, Any]) -> Dict[str, Any]:
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
            
    return {"consolidated_lines": cleaned_lines}

def get_qbo_data() -> List[Dict[str, Any]]:
    print("Fetching active customers from QBO...")
    customers = query_qbo_paginated("Customer", "Active = true")
    
    print("Fetching 2026 invoices from QBO...")
    invoices = query_qbo_paginated("Invoice", "TxnDate >= '2026-01-01'")
    
    customer_invoices: Dict[str, Dict[str, Any]] = {}
    for inv in invoices:
        cust_ref = inv.get("CustomerRef", {}).get("value")
        if cust_ref:
            customer_invoices[cust_ref] = inv
            
    sp_mapping = load_sp_mappings()
    combined_records = []
    
    for c in customers:
        q_id = str(c.get("Id"))
        bill_addr = c.get("BillAddr", {})
        raw_inv = customer_invoices.get(q_id, {})
        
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
            "qbo_invoice": clean_invoice_payload(raw_inv),
            "sharepoint_folder": sp_mapping.get(q_id, "")
        })
        
    print(f"Prepared {len(combined_records)} unified client records.")
    return combined_records

# ---------------------------------------------------------------------------
# 4. SINGLE-CLIENT PARALLEL WORKER
# ---------------------------------------------------------------------------
def process_single_client(args: tuple) -> bool:
    """Processes ONE client record through Gemini Flash with full LLM name & address formatting."""
    client_data, catalog_map = args
    
    system_instruction = f"""
You are an accounting ETL engine converting 1 client input into 1 JSON draft.

CATALOG DEFAULT PRICES MAP:
{json.dumps(catalog_map)}

Return 1 valid JSON object with EXACTLY these top-level keys:
- qbo_id (MUST match input client qbo_id string)
- estimate_date_option ("next_year")
- friendly_name
- heal_legal_name
- heal_profile_flag ("false")
- meta_additional_signer ("")
- meta_signature_type ("single" or "joint")
- meta_co_signer_name
- meta_entity_type ("individual", "s_corp", "partnership", or "llc")
- heal_street
- heal_city
- heal_state
- heal_zip
- out_of_scope_items ([])
- estimate_id ("")
- rows (array of row objects with keys: item_id, service, fee, notes="", bp="individual" or "organization")

RULES:
1. Entity Classification: Check company_name, display_name, sharepoint_folder for LLC, Inc, Corp, Partners -> set meta_entity_type ('s_corp', 'partnership', 'llc', or 'individual') and row bp ('organization' or 'individual').
2. Name Formatting & Order:
   - Convert ALL UPPERCASE names into Proper Title Case (e.g., "ALBERTS KERI L." -> "Keri Alberts").
   - friendly_name: Output in "First Last" order in Title Case. Drop middle initials (e.g., "ALBERTS KERI L." becomes "Keri Alberts").
   - heal_legal_name: Output full legal name in Title Case (e.g., "ALBERTS KERI L." becomes "Keri L. Alberts" or "Keri Alberts").
3. Joint Signers: Check display_name and sharepoint_folder for spouse/joint names -> set meta_signature_type='joint' & meta_co_signer_name in Title Case, else 'single' & "".
4. Address Formatting: Map street -> heal_street, city -> heal_city, state -> heal_state, zip -> heal_zip. Format city/street in Title Case if input is ALL CAPS (e.g., "Ashburn" instead of "ASHBURN").
5. Fee Resolution: For each input line, set row fee to catalog_fee from CATALOG MAP if > 0, else historical_fee. Always format fee as a string (e.g. "1100.00").
"""

    user_payload = json.dumps(client_data)

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

        result_data = json.loads(response.text)
        
        # Validate directly against ClientDraftSchema
        draft = ClientDraftSchema(**result_data)
        
        qbo_id = draft.qbo_id or client_data.get("qbo_id")
        if not qbo_id:
            return False
            
        file_path = os.path.join(DRAFTS_DIR, f"client_{qbo_id}.json")
        draft_dict = draft.model_dump()
        draft_dict.pop("qbo_id", None)
        
        raw_oos_list = draft_dict.get("out_of_scope_items", [])
        draft_dict["out_of_scope_items"] = {
            f"out_of_scope_item_{i}": item for i, item in enumerate(raw_oos_list)
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(draft_dict, f, indent=2)
            
        return True
    except Exception as e:
        print(f"  !! Error processing client {client_data.get('qbo_id')}: {e}")
        return False

# ---------------------------------------------------------------------------
# 5. MAIN PARALLEL EXECUTION LOOP
# ---------------------------------------------------------------------------
def main():
    catalog_map = extract_catalog_fees()
    client_records = get_qbo_data()
    
    total_clients = len(client_records)
    print(f"\nProcessing {total_clients} clients concurrently (15 parallel workers) via Gemini 2.5 Flash...")
    
    tasks = [(c, catalog_map) for c in client_records]
    completed = 0
    
    # 15 parallel HTTP connections to Google Gemini
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