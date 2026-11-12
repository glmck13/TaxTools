#!/usr/bin/env python3
"""
Seasonal Engagement Draft Generator Utility
Usage:
    python3 qbota.py -s <services_template.md> -e <engagement_template.md> -o <target_output_directory> [-c <sp_checklists.json>] [--xlate <id_mapping.json>] [--dry-run]
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

QBO_APIBASE = os.environ.get("QBO_APIBASE", "")
QBO_REALMID = os.environ.get("QBO_REALMID", "")
QBO_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "")

TAX_YEAR = os.environ.get("TAX_YEAR", "2026")
ENGID = 202600

SANDBOX_OVERRIDE_EMAIL = "katie@tarrantadvisors.com"

ORGANIZATION_ENTITY_TYPES = {
    "sm_llc", "s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"
}


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
    """Executes authenticated HTTP requests against the QuickBooks Online API."""
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


def parse_acct_num(acct_num_str):
    """Extracts entity classification, delivery format, and dual-signer metadata stored in QBO Notes JSON."""
    meta = {
        "entity_type": "individual",
        "delivery_format": "electronic",
        "friendly_name": "",
        "primary_signer_email": "",
        "co_signer_name": "",
        "co_signer_email": ""
    }
    if not acct_num_str or not acct_num_str.strip():
        return meta

    try:
        data = json.loads(acct_num_str.strip())
        if isinstance(data, str):
            data = json.loads(data)

        if isinstance(data, dict):
            raw_ent = str(data.get("entity", "")).lower().strip()
            meta["entity_type"] = raw_ent if raw_ent in ORGANIZATION_ENTITY_TYPES else "individual"

            raw_fmt = str(data.get("delivery_format", "")).lower().strip()
            meta["delivery_format"] = raw_fmt if raw_fmt in ["paper", "electronic"] else "electronic"

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


def load_base_out_of_scope_dict(engagement_template_path):
    """
    Extracts base out-of-scope boilerplate items from engagement_template.md 
    and constructs a dictionary aligned with engagement_pipeline.py schema.
    Returns: {"out_of_scope_item_0": "item text", ...}
    """
    oos_dict = {}
    if engagement_template_path and os.path.exists(engagement_template_path):
        try:
            with open(engagement_template_path, "r", encoding="utf-8") as f:
                content = f.read()

            match = re.search(r'\{#\s*START_OUT_OF_SCOPE\s*#\}(.*?)\{#\s*END_OUT_OF_SCOPE\s*#\}', content, re.DOTALL)
            if match:
                raw_block = match.group(1)
                items = [
                    line.strip().lstrip('*').strip()
                    for line in raw_block.splitlines()
                    if line.strip().startswith('*')
                ]
                for idx, item in enumerate(items):
                    oos_dict[f"out_of_scope_item_{idx}"] = item
        except Exception as e:
            print(f"Warning: Failed parsing out-of-scope items from {engagement_template_path}: {str(e)}", file=sys.stderr)

    return oos_dict


def load_sharepoint_checklists(sp_checklists_path):
    """Loads SharePoint folder and checklist URLs generated by process_checklists.py."""
    if sp_checklists_path and os.path.exists(sp_checklists_path):
        try:
            with open(sp_checklists_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed reading SharePoint checklists file {sp_checklists_path}: {str(e)}", file=sys.stderr)
    return {}


def load_id_mapping(xlate_path):
    """Loads production-to-sandbox ID mapping file."""
    if xlate_path and os.path.exists(xlate_path):
        try:
            with open(xlate_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed reading ID mapping file {xlate_path}: {str(e)}", file=sys.stderr)
    return {"customers": {}, "services": {}}


def load_services_catalog_with_migrations(template_path):
    """Parses services_template.md catalog entries and extracts optional Migrates-From mappings."""
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
    """Dynamically calculates business unit classification (bp) for front-end rendering."""
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
        required=False,
        default=f"{os.environ.get('HOME', '')}/cgi/services_template.md",
        metavar="FILE",
        help="Path to services_template.md catalog file."
    )
    parser.add_argument(
        "-e", "--engagement",
        required=False,
        default=f"{os.environ.get('HOME', '')}/cgi/engagement_template.md",
        metavar="FILE",
        help="Path to engagement_template.md template file."
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        metavar="DIR",
        help="Target destination directory for generated draft JSON files."
    )
    parser.add_argument(
        "-c", "--checklists",
        required=False,
        default="sp_checklists.json",
        metavar="FILE",
        help="Path to sp_checklists.json output file generated by process_checklists.py."
    )
    parser.add_argument(
        "-x", "--xlate",
        required=False,
        default="",
        metavar="FILE",
        help="Path to id_mapping.json to translate production IDs to sandbox IDs."
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
    sp_checklists_path = args.checklists
    xlate_path = args.xlate
    is_dry_run = args.dry_run

    catalog, migration_map, name_lookup = load_services_catalog_with_migrations(services_template_path)
    base_oos_dict = load_base_out_of_scope_dict(engagement_template_path)
    sp_checklists_map = load_sharepoint_checklists(sp_checklists_path)
    id_mapping = load_id_mapping(xlate_path)

    cust_map = id_mapping.get("customers", {})
    serv_map = id_mapping.get("services", {})

    print(f"Loaded {len(catalog)} service offering(s) and {len(migration_map)} migration link(s) from {services_template_path}.")
    print(f"Loaded {len(base_oos_dict)} out-of-scope boilerplate item(s) from {engagement_template_path}.")
    print(f"Loaded {len(sp_checklists_map)} SharePoint link entry/entries from {sp_checklists_path}.")
    if xlate_path:
        print(f"Loaded ID mapping from {xlate_path} ({len(cust_map)} customer(s), {len(serv_map)} service(s) mapped).")
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
        prod_c_id = str(c["Id"])
        # Resolve target customer ID filename using --xlate mapping if available, else fallback to production ID
        file_c_id = cust_map.get(prod_c_id, prod_c_id)
        
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
        co_signer_email = meta.get("co_signer_email", "")
        entity_type = meta.get("entity_type", "individual")
        delivery_format = meta.get("delivery_format", "electronic")

        # HOLE 1 FIX: Redirect primary & co-signer emails if running with --xlate
        if xlate_path:
            primary_email = SANDBOX_OVERRIDE_EMAIL
            if co_signer_email:
                co_signer_email = SANDBOX_OVERRIDE_EMAIL

        # Lookup SharePoint folder and checklist links from sp_checklists.json (keyed by production customer ID)
        sp_links = sp_checklists_map.get(prod_c_id, {})
        folder_url = sp_links.get("folder_url", "")
        checklist_url = sp_links.get("checklist_url", "")

        # 1. Fetch prior tax year invoices for customer
        inv_query = f"select * from Invoice where CustomerRef='{prod_c_id}' and TxnDate >= '{TAX_YEAR}-01-01' and TxnDate <= '{TAX_YEAR}-12-31'"
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
                    notes = mapped_entry["notes"] or inv_desc
                    cat_type = mapped_entry["type"]
                else:
                    target_id = item_ref_id
                    target_name = detail.get("ItemRef", {}).get("name", "Service Item")
                    catalog_fee = 0
                    notes = inv_desc
                    cat_type = "both"

                # TRANSLATION RULE: Translate service item ID to Sandbox ID *after* migration resolution
                final_item_id = serv_map.get(target_id, target_id)

                # HOLE 3 FIX: Discard item and print error message if service ID cannot be translated in xlate mode
                if xlate_path and final_item_id not in serv_map.values():
                    print(
                        f"❌ [Hole 3 Error] Customer '{c_name}' (Prod ID: {prod_c_id}): "
                        f"Discarding unmapped Service Item '{target_name}' (Prod ID: {target_id}). "
                        f"No Sandbox mapping found in {xlate_path}.",
                        file=sys.stderr
                    )
                    continue

                effective_fee = max(inv_fee, catalog_fee)
                bp_value = resolve_item_bp(cat_type, entity_type)

                if final_item_id in merged_services:
                    merged_services[final_item_id]["fee"] = max(merged_services[final_item_id]["fee"], effective_fee)
                else:
                    merged_services[final_item_id] = {
                        "item_id": final_item_id,
                        "service": target_name,
                        "fee": effective_fee,
                        "notes": notes,
                        "bp": bp_value
                    }

        if not merged_services:
            continue

        # Draft schema payload aligned 100% with engagement_pipeline.py
        draft_payload = {
            "engagement_id": "1",
            "engagement_title": f"{TAX_YEAR} Tax Services Agreement",
            "estimate_id": "",
            "estimate_date_option": "next_year",
            "delivery_format": delivery_format,
            "profile_verified": True,
            "is_approved": False,
            "reviewed_by": "",
            "reviewed_at": "",
            "questionnaire_status": "unsent",
            "acceptance_type": "",
            "adobe_agreement_id": "",
            "adobe_completed_at": "",
            "entity_type": entity_type,
            "primary_signer": {
                "friendly_name": friendly_name,
                "legal_name": c_name,
                "email": primary_email
            },
            "co_signer": {
                "name": meta.get("co_signer_name", ""),
                "email": co_signer_email
            },
            "phone": qbo_phone,
            "billing_address": {
                "street": addr_obj.get("Line1", ""),
                "city": addr_obj.get("City", ""),
                "state": addr_obj.get("CountrySubDivisionCode", ""),
                "zip": addr_obj.get("PostalCode", "")
            },
            "sharepoint": {
                "folder_url": folder_url,
                "checklist_url": checklist_url,
                "schedule_ce_url": ""
            },
            "out_of_scope_items": base_oos_dict,
            "rows": list(merged_services.values())
        }

        output_path = os.path.join(target_dir, f"{file_c_id}_{ENGID}.json")
        created_count += 1

        if is_dry_run:
            total_fee = sum(r["fee"] for r in merged_services.values())
            items_summary = ", ".join([f"{r['service']} (${r['fee']:,})" for r in merged_services.values()])
            sp_status = "SP Linked" if checklist_url else "No SP Link"
            print(f"[{created_count}] [DRY RUN] [{delivery_format.upper()}] [{sp_status}] [{c_name}] (Prod ID: {prod_c_id} -> Sandbox ID: {file_c_id}) -> Total: ${total_fee:,} | Items: {items_summary}")
        else:
            with open(output_path, "w", encoding="utf-8") as out_file:
                json.dump(draft_payload, out_file, indent=2)
            print(f"[{created_count}] Generated [{delivery_format.upper()}] draft for [{c_name}] (Prod ID: {prod_c_id} -> Sandbox ID: {file_c_id}) -> {output_path}")

    status_str = "Would generate" if is_dry_run else "Successfully generated"
    print(f"\nExecution Complete: {status_str} {created_count} engagement draft file(s).")


if __name__ == "__main__":
    main()
