#!/usr/bin/env python3
"""
Seasonal Engagement Draft Generator Utility
Usage:
    python3 batch.py -s <services_template.md> -e <engagement_template.md> -o <target_output_directory> [-u <dashboard_cgi_url_or_csv>] [-q <qbosp_csv_path>] [--dry-run]
"""

import os
import sys
import json
import html
import re
import time
import argparse
import urllib.parse
import urllib.request

# ==========================================
# CONFIGURATION & ENVIRONMENT SETUP
# ==========================================

DASHBOARD_CGI_URL = os.environ.get(
    "DASHBOARD_CGI_URL",
    "https://appserver.tarrantadvisors.com/cgi/m365_dashboard.cgi"
)

QBO_APIBASE = os.environ.get("QBO_APIBASE", "")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

TAX_YEAR = os.environ.get("TAX_YEAR", "2026")
PRIOR_TAX_YEAR = str(int(TAX_YEAR) - 1)

ORGANIZATION_ENTITY_TYPES = {
    "sm_llc", "s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"
}

DEFAULT_OOS_ITEMS = [
    "Additional state returns",
    "Additional Schedule K-1's or new rental properties or sales",
    "Detailed estimated payment computations or calculations based on actual activity",
    "Tax research including analysis of additional transactions",
    "Detailed correspondence with the tax authorities or audit assistance"
]


def sanitize_fee_int(raw_fee):
    """Converts raw fee values ('$1,000.00', '1000', 1000.0) directly into integers."""
    if raw_fee is None:
        return 0
    clean_str = str(raw_fee).replace('$', '').replace(',', '').strip()
    if not clean_str:
        return 0
    try:
        return int(round(float(clean_str)))
    except (ValueError, TypeError):
        return 0


def qbo_api_request(endpoint, method="GET", payload=None):
    """Executes authenticated HTTP requests against the QuickBooks Online API[cite: 3]."""
    # Unquote first to prevent double-encoding issues
    if "?" in endpoint:
        path, query = endpoint.split("?", 1)
        unquoted_query = urllib.parse.unquote(query)
        if unquoted_query.startswith("query="):
            query_val = unquoted_query[6:]
            endpoint = f"{path}?query={urllib.parse.quote(query_val)}"
        else:
            endpoint = f"{path}?{urllib.parse.quote(unquoted_query)}"

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


def load_delivery_formats(dashboard_url_or_path, qbosp_path=None):
    """
    Builds direct QBO ID and normalized name lookup maps for delivery format resolution.
    """
    dash_format_map = {}
    qbo_id_format_map = {}

    # Normalize double slashes in URL if present
    if dashboard_url_or_path:
        dashboard_url_or_path = re.sub(r'(?<!:)/{2,}', '/', dashboard_url_or_path)

    # 1. Parse M365 Dashboard CSV or CGI Endpoint
    if dashboard_url_or_path:
        content_lines = []
        try:
            if dashboard_url_or_path.startswith("http://") or dashboard_url_or_path.startswith("https://"):
                req = urllib.request.Request(dashboard_url_or_path, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw_data = resp.read().decode("utf-8", errors="ignore")
                    content_lines = raw_data.splitlines()
            elif os.path.exists(dashboard_url_or_path):
                with open(dashboard_url_or_path, "r", encoding="utf-8", errors="ignore") as f:
                    content_lines = f.readlines()
        except Exception as e:
            print(f"Warning: Unable to retrieve dashboard data from {dashboard_url_or_path}: {e}", file=sys.stderr)

        for line in content_lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("ServerUrl"):
                continue
            parts = line_str.split("|")
            if len(parts) >= 3:
                server_url = parts[0].strip()
                fmt = parts[2].strip().lower()
                target_fmt = "paper" if "paper" in fmt else "electronic"
                
                folder = server_url.split('/')[-1]
                folder_clean = re.sub(r'\s*-\s*SHARED$', '', folder, flags=re.IGNORECASE).strip()
                dash_format_map[folder.strip()] = target_fmt
                dash_format_map[folder_clean] = target_fmt

                norm_key = re.sub(r'[^a-z0-9]', '', folder_clean.lower())
                if norm_key:
                    dash_format_map[norm_key] = target_fmt

    # 2. Parse QBO-to-SharePoint Mapping File (qbosp.csv)
    if qbosp_path and os.path.exists(qbosp_path):
        try:
            with open(qbosp_path, "r", encoding="utf-8", errors="ignore") as f:
                f.readline()  # header
                for line in f:
                    parts = line.strip().split(":", 4)
                    if len(parts) >= 3:
                        qbo_id = parts[0].strip()
                        sp_folder = parts[2].strip()
                        if sp_folder and sp_folder in dash_format_map:
                            qbo_id_format_map[qbo_id] = dash_format_map[sp_folder]
        except Exception as e:
            print(f"Warning: Unable to parse qbosp mapping from {qbosp_path}: {e}", file=sys.stderr)

    return qbo_id_format_map, dash_format_map


def parse_acct_num(acct_num_str):
    """Extracts entity classification and dual-signer metadata stored in QBO Notes JSON[cite: 3]."""
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
    except Exception:
        pass

    return meta


def load_base_out_of_scope_items(engagement_template_path):
    """Extracts base out-of-scope boilerplate items from engagement_template.md[cite: 3, 4]."""
    if engagement_template_path and os.path.exists(engagement_template_path):
        try:
            with open(engagement_template_path, "r", encoding="utf-8") as f:
                content = f.read()
            else_match = re.search(r'\{%\s*else\s*%\}(.*?)\{%\s*endif\s*\%}', content, re.DOTALL)
            if else_match:
                raw_block = else_match.group(1).strip()
                items = [re.sub(r'^\*\s*', '', line.strip()).strip() for line in raw_block.split("\n") if line.strip().startswith("*")]
                if items:
                    return {f"out_of_scope_item_{idx}": item for idx, item in enumerate(items)}
        except Exception as e:
            print(f"Warning: Failed parsing out-of-scope items from {engagement_template_path}: {str(e)}", file=sys.stderr)
            
    return {f"out_of_scope_item_{idx}": item for idx, item in enumerate(DEFAULT_OOS_ITEMS)}


def load_services_catalog_with_migrations(template_path):
    """Parses services_template.md catalog entries and extracts optional Migrates-From mappings[cite: 5]."""
    if not os.path.exists(template_path):
        print(f"ERROR: Services template file not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    catalog = {}
    migration_map = {}
    name_lookup = {}

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
        migrates_from_id = ""
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
            mig_match = re.match(r'^-\s*Migrates-From:\s*(\d+)', clean_line, re.IGNORECASE)
            
            if id_match:
                item_id = id_match.group(1)
            elif type_match:
                entity_type = type_match.group(1).lower()
            elif fee_match:
                fee_val = sanitize_fee_int(fee_match.group(1))
            elif mig_match:
                migrates_from_id = mig_match.group(1)
            else:
                notes_lines.append(clean_line)
        
        notes_text = "\n".join(notes_lines).strip() if notes_lines else ""
        if item_id and service_name:
            entry = {
                "id": item_id,
                "name": service_name,
                "type": entity_type,
                "fee": fee_val,
                "notes": notes_text,
                "migrates_from": migrates_from_id
            }
            catalog[item_id] = entry
            name_lookup[service_name.lower()] = entry
            if migrates_from_id:
                migration_map[migrates_from_id] = entry

    return catalog, migration_map, name_lookup


def resolve_item_bp(catalog_type, entity_type):
    """Dynamically calculates business unit classification (bp) for front-end rendering[cite: 2, 3]."""
    cat_type = (catalog_type or "both").lower()
    if cat_type in ["individual", "organization"]:
        return cat_type
    return "organization" if entity_type in ORGANIZATION_ENTITY_TYPES else "individual"


def parse_cli_args():
    parser = argparse.ArgumentParser(
        description="Seasonal Engagement Draft Generator Utility for Tarrant Advisors LLC."
    )
    
    parser.add_argument(
        "-s", "--services",
        required=True,
        metavar="FILE",
        help="Path to services_template.md catalog file."
    )
    parser.add_argument(
        "-e", "--engagement",
        required=False,
        default="engagement_template.md",
        metavar="FILE",
        help="Path to engagement_template.md template file (default: engagement_template.md)."
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        metavar="DIR",
        help="Target destination directory for generated draft JSON files."
    )
    parser.add_argument(
        "-u", "--dashboard-url",
        required=False,
        default=DASHBOARD_CGI_URL,
        metavar="URL_OR_PATH",
        help=f"CGI Endpoint or CSV path for M365 delivery formats (default: {DASHBOARD_CGI_URL})."
    )
    parser.add_argument(
        "-q", "--qbosp",
        required=False,
        default="qbosp.csv",
        metavar="FILE",
        help="Path to qbosp.csv QBO-to-SharePoint lookup map (default: qbosp.csv)."
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="Perform a dry run without creating or modifying JSON files on disk."
    )

    return parser.parse_args()


def main():
    args = parse_cli_args()

    services_template_path = args.services
    engagement_template_path = args.engagement
    target_dir = args.output
    dashboard_url = args.dashboard_url
    qbosp_path = args.qbosp
    is_dry_run = args.dry_run

    catalog, migration_map, name_lookup = load_services_catalog_with_migrations(services_template_path)
    base_oos_items = load_base_out_of_scope_items(engagement_template_path)
    qbo_id_format_map, name_format_map = load_delivery_formats(dashboard_url, qbosp_path)
    
    print(f"Loaded {len(catalog)} service offering(s) and {len(migration_map)} migration link(s) from {services_template_path}.")
    print(f"Loaded out-of-scope boilerplate from {engagement_template_path}.")
    print(f"Loaded delivery format rules: {len(qbo_id_format_map)} via QBO ID mapping, {len(name_format_map)} via SharePoint folder mapping.")
    print(f"Target Output Directory: {target_dir}")
    if is_dry_run:
        print("\n*** DRY RUN MODE ENABLED: No files will be written to disk ***\n")

    print("Querying Active QBO Customer accounts...")

    query_res = qbo_api_request("query?query=select * from Customer where Active=true maxresults 1000")
    customers = query_res.get("QueryResponse", {}).get("Customer", [])
    
    if not is_dry_run:
        os.makedirs(target_dir, exist_ok=True)

    created_count = 0

    for c in customers:
        c_id = str(c["Id"])
        c_name = html.unescape(c["DisplayName"])
        
        # Parse customer demographic metadata
        acct_num = c.get("Notes", "")
        addr_obj = c.get("BillAddr", {})
        raw_c_email = c.get("PrimaryEmailAddr", {}).get("Address", "")
        qbo_primary_email = raw_c_email.split(",")[0].strip() if raw_c_email else ""
        qbo_phone = c.get("PrimaryPhone", {}).get("FreeFormNumber", "")

        meta = parse_acct_num(acct_num)
        friendly_name = meta.get("friendly_name") or c_name
        primary_email = meta.get("primary_signer_email") or qbo_primary_email
        entity_type = meta.get("entity_type", "individual")

        norm_c_name = re.sub(r'[^a-z0-9]', '', c_name.lower())
        if c_id in qbo_id_format_map:
            delivery_format = qbo_id_format_map[c_id]
        elif norm_c_name in name_format_map:
            delivery_format = name_format_map[norm_c_name]
        else:
            delivery_format = "electronic"

        # 1. Fetch prior tax year invoices for customer
        inv_query = f"select * from Invoice where CustomerRef='{c_id}' and TxnDate >= '{TAX_YEAR}-01-01' and TxnDate <= '{TAX_YEAR}-12-31'"
        inv_res = qbo_api_request(f"query?query={inv_query}")
        invoices = inv_res.get("QueryResponse", {}).get("Invoice", [])

        # Throttle QBO API requests to avoid rate limits
        time.sleep(0.05)

        # Filter: Skip customer if no prior invoice exists
        if not invoices:
            continue

        # 2. Extract and merge services across all prior-year invoices
        merged_services = {}

        for inv in invoices:
            lines = inv.get("Line", [])
            for line in lines:
                if line.get("DetailType") != "SalesItemLineDetail":
                    continue
                
                detail = line.get("SalesItemLineDetail", {})
                item_ref_id = str(detail.get("ItemRef", {}).get("value", ""))
                item_ref_name = str(detail.get("ItemRef", {}).get("name", "")).strip().lower()

                inv_fee = sanitize_fee_int(line.get("Amount", detail.get("UnitPrice", 0)))
                inv_desc = line.get("Description", "")

                mapped_entry = None
                if item_ref_id in migration_map:
                    mapped_entry = migration_map[item_ref_id]
                elif item_ref_id in catalog:
                    mapped_entry = catalog[item_ref_id]
                elif item_ref_name in name_lookup:
                    mapped_entry = name_lookup[item_ref_name]

                if mapped_entry:
                    target_id = mapped_entry["id"]
                    target_name = mapped_entry["name"]
                    catalog_fee = mapped_entry["fee"]
                    notes = mapped_entry["notes"]
                    cat_type = mapped_entry["type"]
                else:
                    target_id = item_ref_id
                    target_name = detail.get("ItemRef", {}).get("name", "Service Item")
                    catalog_fee = 0
                    notes = inv_desc
                    cat_type = "both"

                effective_fee = max(inv_fee, catalog_fee)
                bp_value = resolve_item_bp(cat_type, entity_type)

                if target_id in merged_services:
                    merged_services[target_id]["fee"] = max(merged_services[target_id]["fee"], effective_fee)
                else:
                    merged_services[target_id] = {
                        "item_id": target_id,
                        "service": target_name,
                        "fee": effective_fee,
                        "notes": notes,
                        "bp": bp_value
                    }

        if not merged_services:
            continue

        draft_payload = {
            "engagement_id": "1",
            "engagement_title": f"{TAX_YEAR} Tax Services Agreement",
            "estimate_id": "",
            "estimate_date_option": "next_year",
            "delivery_format": delivery_format,
            "profile_verified": True,
            "entity_type": entity_type,
            "primary_signer": {
                "friendly_name": friendly_name,
                "legal_name": c_name,
                "email": primary_email
            },
            "co_signer": {
                "name": meta.get("co_signer_name", ""),
                "email": meta.get("co_signer_email", "")
            },
            "phone": qbo_phone,
            "billing_address": {
                "street": addr_obj.get("Line1", ""),
                "city": addr_obj.get("City", ""),
                "state": addr_obj.get("CountrySubDivisionCode", ""),
                "zip": addr_obj.get("PostalCode", "")
            },
            "out_of_scope_items": base_oos_items,
            "rows": list(merged_services.values())
        }

        output_path = os.path.join(target_dir, f"{c_id}_1.json")
        created_count += 1

        if is_dry_run:
            total_fee = sum(r["fee"] for r in merged_services.values())
            items_summary = ", ".join([f"{r['service']} (${r['fee']:,})" for r in merged_services.values()])
            print(f"[{created_count}] [DRY RUN] [{delivery_format.upper()}] [{c_name}] (QBO ID: {c_id}) -> Total: ${total_fee:,} | Items: {items_summary}")
        else:
            with open(output_path, "w", encoding="utf-8") as out_file:
                json.dump(draft_payload, out_file, indent=2)
            print(f"[{created_count}] Generated [{delivery_format.upper()}] draft for [{c_name}] (QBO ID: {c_id}) -> {output_path}")

    status_str = "Would generate" if is_dry_run else "Successfully generated"
    print(f"\nExecution Complete: {status_str} {created_count} engagement draft file(s).")


if __name__ == "__main__":
    main()
