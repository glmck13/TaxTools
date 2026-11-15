#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# TARRANT ADVISORS — BATCH QBO DEMOGRAPHICS IMPORTER
# Reads a colon-delimited CSV (matching export_qbo_demographics.sh) and applies
# sparse updates to QuickBooks Online ONLY for records with actual changes.
#
# Usage:
#   ./import_qbo_demographics.sh <path/to/demographics.csv> [--apply]
#
# Defaults to --dry-run unless --apply is explicitly passed.
# ==============================================================================

CSV_FILE="${1:-}"
MODE="${2:---dry-run}"

if [[ -z "$CSV_FILE" || ! -f "$CSV_FILE" ]]; then
    echo "Usage: $0 <demographics.csv> [--apply]" >&2
    exit 1
fi

if [[ "$MODE" != "--apply" && "$MODE" != "--dry-run" ]]; then
    echo "Error: Second argument must be '--apply' or '--dry-run' (got '$MODE')." >&2
    exit 1
fi

# Pre-flight dependency checks
for cmd in qbo.sh python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: Required command '$cmd' not found in PATH." >&2
        exit 1
    fi
done

# Single-quoted so ${QBO_REALMID} is passed literally and resolved inside qbo.sh via eval
QUERY_URI='/company/${QBO_REALMID}/query'
POST_URI='/company/${QBO_REALMID}/customer'

export CSV_FILE MODE QUERY_URI POST_URI

python3 - <<'PYEOF'
import csv
import html
import json
import os
import re
import subprocess
import sys

csv_file = os.environ["CSV_FILE"]
apply_changes = os.environ["MODE"] == "--apply"
query_uri = os.environ["QUERY_URI"]
post_uri = os.environ["POST_URI"]

EXPECTED_HEADERS = [
    "qbo_id",
    "client_name",
    "friendly_name",
    "primary_email",
    "phone_number",
    "co_signer_name",
    "co_signer_email",
    "entity_type",
    "delivery_format",
    "street",
    "city",
    "state",
    "zip",
]

VALID_ENTITIES = {
    "individual",
    "sm_llc",
    "s_corp",
    "partnership",
    "c_corp",
    "non_profit",
    "trust",
    "organization",
}


def run_qbo(method: str, uri: str, arg_or_stdin: str) -> dict:
    if method == "GET":
        proc = subprocess.run(
            ["qbo.sh", "GET", uri, arg_or_stdin],
            capture_output=True,
            text=True,
        )
    else:
        proc = subprocess.run(
            ["qbo.sh", "POST", uri],
            input=arg_or_stdin,
            capture_output=True,
            text=True,
        )

    if proc.returncode != 0:
        raise RuntimeError(f"qbo.sh {method} failed: {proc.stderr.strip() or proc.stdout.strip()}")

    raw = proc.stdout.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from qbo.sh: {raw[:300]}") from exc

    if isinstance(data, dict) and data.get("Fault"):
        err = data["Fault"].get("Error", [{}])[0]
        raise RuntimeError(f"QBO Fault: {err.get('Message', 'Unknown')} - {err.get('Detail', '')}")

    return data


def clean_str(val) -> str:
    if val is None:
        return ""
    s = html.unescape(str(val)).strip()
    if s.lower() == "null":
        return ""
    return re.sub(r"[\r\n]+", " ", s).strip()


def normalize_zip(z: str) -> str:
    z = clean_str(z)
    # Restore leading zero stripped by Excel on 5-digit US ZIPs (e.g., 2138 -> 02138)
    if re.fullmatch(r"\d{4}", z):
        return "0" + z
    return z


def normalize_entity(e: str) -> str:
    e = clean_str(e).lower()
    return e if e in VALID_ENTITIES else "individual"


def normalize_format(fmt: str) -> str:
    return "paper" if clean_str(fmt).lower() == "paper" else "electronic"


def parse_qbo_notes(notes_str: str) -> dict:
    """Mirrors parse_acct_num() in intake_lookup.py and parse_notes in export_qbo_demographics.sh."""
    raw = clean_str(notes_str)
    if not raw:
        return {"_valid_json": False, "_raw": ""}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, str):
            parsed = json.loads(parsed.strip())
        if not isinstance(parsed, dict):
            return {"_valid_json": False, "_raw": raw}
    except Exception:
        return {"_valid_json": False, "_raw": raw}

    signers = parsed.get("signers") if isinstance(parsed.get("signers"), list) else []
    p_signer = signers[0] if len(signers) > 0 and isinstance(signers[0], dict) else {}
    c_signer = signers[1] if len(signers) > 1 and isinstance(signers[1], dict) else {}

    return {
        "_valid_json": True,
        "_raw": raw,
        "entity": normalize_entity(parsed.get("entity", "")),
        "delivery_format": normalize_format(parsed.get("delivery_format", "")),
        "p_name": clean_str(p_signer.get("name", "")),
        "p_email": clean_str(p_signer.get("email", "")),
        "c_name": clean_str(c_signer.get("name", "")),
        "c_email": clean_str(c_signer.get("email", "")),
    }


def fetch_all_qbo_customers() -> dict:
    """Fetches all active QBO customers in pages of 1000 keyed by string Id."""
    customers = {}
    start_pos = 1
    page_size = 1000

    while True:
        sql = f"select * from Customer where Active = true startposition {start_pos} maxresults {page_size}"
        resp = run_qbo("GET", query_uri, f"query={sql}")
        batch = resp.get("QueryResponse", {}).get("Customer", [])
        if not batch:
            break
        for c in batch:
            cid = clean_str(c.get("Id", ""))
            if cid:
                customers[cid] = c
        if len(batch) < page_size:
            break
        start_pos += page_size

    return customers


print(f"Mode: {'APPLY (live QBO updates)' if apply_changes else 'DRY-RUN (no changes will be written)'}")
print(f"Reading {csv_file}...")

with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f, delimiter=":")
    if not reader.fieldnames or reader.fieldnames[:13] != EXPECTED_HEADERS:
        sys.exit(
            f"Error: Unexpected CSV headers.\n"
            f"  Expected: {':'.join(EXPECTED_HEADERS)}\n"
            f"  Found:    {':'.join(reader.fieldnames or [])}"
        )
    csv_rows = list(reader)

print(f"Loaded {len(csv_rows)} CSV rows. Fetching live QBO customer records...")
qbo_by_id = fetch_all_qbo_customers()
print(f"Fetched {len(qbo_by_id)} active QBO customers.\n")

stats = {"unchanged": 0, "updated": 0, "skipped_missing": 0, "errors": 0}
expected_col_count = len(reader.fieldnames)

for line_num, row in enumerate(csv_rows, start=2):
    # Guard against extra colons ':' introduced during manual Excel edits
    if None in row or any(row.get(k) is None for k in EXPECTED_HEADERS):
        print(
            f"[Line {line_num}] ERROR: Column count mismatch (expected {expected_col_count} columns). "
            f"Check for stray ':' characters.",
            file=sys.stderr,
        )
        stats["errors"] += 1
        continue

    qbo_id = clean_str(row.get("qbo_id", ""))
    if not qbo_id:
        print(f"[Line {line_num}] SKIP: Missing qbo_id.")
        stats["skipped_missing"] += 1
        continue

    live = qbo_by_id.get(qbo_id)
    if not live:
        print(f"[Line {line_num}] SKIP (ID {qbo_id}): Not found among active QBO customers.")
        stats["skipped_missing"] += 1
        continue

    # Desired normalized values from CSV
    desired_display_name = clean_str(row.get("client_name", ""))
    if not desired_display_name:
        print(f"[Line {line_num}] SKIP (ID {qbo_id}): Blank client_name.")
        stats["skipped_missing"] += 1
        continue

    desired_entity = normalize_entity(row.get("entity_type", ""))
    desired_company_name = "" if desired_entity == "individual" else desired_display_name
    desired_friendly = clean_str(row.get("friendly_name", "")) or desired_display_name
    desired_email = clean_str(row.get("primary_email", ""))
    desired_phone = clean_str(row.get("phone_number", ""))
    desired_co_name = clean_str(row.get("co_signer_name", ""))
    desired_co_email = clean_str(row.get("co_signer_email", ""))
    desired_format = normalize_format(row.get("delivery_format", ""))
    desired_street = clean_str(row.get("street", ""))
    desired_city = clean_str(row.get("city", ""))
    desired_state = clean_str(row.get("state", ""))
    desired_zip = normalize_zip(row.get("zip", ""))

    # Current normalized values from live QBO object
    live_display_name = clean_str(live.get("DisplayName", ""))
    live_company_name = clean_str(live.get("CompanyName", ""))
    live_raw_email = clean_str((live.get("PrimaryEmailAddr") or {}).get("Address", ""))
    email_parts = [p.strip() for p in live_raw_email.split(",") if p.strip()] if live_raw_email else []
    live_email = email_parts[0] if email_parts else ""
    extra_live_emails = email_parts[1:] if len(email_parts) > 1 else []

    live_phone = clean_str((live.get("PrimaryPhone") or {}).get("FreeFormNumber", ""))
    live_bill = live.get("BillAddr") or {}
    live_street = clean_str(live_bill.get("Line1", ""))
    live_city = clean_str(live_bill.get("City", ""))
    live_state = clean_str(live_bill.get("CountrySubDivisionCode", ""))
    live_zip = clean_str(live_bill.get("PostalCode", ""))
    live_notes = parse_qbo_notes(live.get("Notes", ""))

    # Build field-by-field diff
    diffs = []
    if desired_display_name != live_display_name:
        diffs.append(f"DisplayName: {live_display_name!r} -> {desired_display_name!r}")
    if desired_company_name != live_company_name:
        diffs.append(f"CompanyName: {live_company_name!r} -> {desired_company_name!r}")
    if desired_email != live_email:
        diffs.append(f"PrimaryEmail: {live_email!r} -> {desired_email!r}")
    if desired_phone != live_phone:
        diffs.append(f"PrimaryPhone: {live_phone!r} -> {desired_phone!r}")
    if desired_street != live_street:
        diffs.append(f"BillAddr.Line1: {live_street!r} -> {desired_street!r}")
    if desired_city != live_city:
        diffs.append(f"BillAddr.City: {live_city!r} -> {desired_city!r}")
    if desired_state != live_state:
        diffs.append(f"BillAddr.State: {live_state!r} -> {desired_state!r}")
    if desired_zip != live_zip:
        diffs.append(f"BillAddr.PostalCode: {live_zip!r} -> {desired_zip!r}")

    # Notes JSON metadata comparison
    if not live_notes["_valid_json"]:
        preview = (live_notes["_raw"][:60] + "...") if len(live_notes["_raw"]) > 60 else live_notes["_raw"]
        diffs.append(f"Notes: ({preview or 'empty'}) -> structured JSON metadata")
    else:
        if desired_entity != live_notes["entity"]:
            diffs.append(f"Notes.entity: {live_notes['entity']!r} -> {desired_entity!r}")
        if desired_format != live_notes["delivery_format"]:
            diffs.append(f"Notes.delivery_format: {live_notes['delivery_format']!r} -> {desired_format!r}")
        if desired_friendly != live_notes["p_name"]:
            diffs.append(f"Notes.signers[0].name: {live_notes['p_name']!r} -> {desired_friendly!r}")
        if desired_email != live_notes["p_email"]:
            diffs.append(f"Notes.signers[0].email: {live_notes['p_email']!r} -> {desired_email!r}")
        if desired_co_name != live_notes["c_name"]:
            diffs.append(f"Notes.signers[1].name: {live_notes['c_name']!r} -> {desired_co_name!r}")
        if desired_co_email != live_notes["c_email"]:
            diffs.append(f"Notes.signers[1].email: {live_notes['c_email']!r} -> {desired_co_email!r}")

    if not diffs:
        stats["unchanged"] += 1
        continue

    print(f"[ID {qbo_id}] {desired_display_name}:")
    for d in diffs:
        print(f"    - {d}")

    if not apply_changes:
        stats["updated"] += 1
        continue

    # Construct Notes JSON matching intake_provision.sh
    signers_payload = [{"name": desired_friendly, "email": desired_email}]
    if desired_co_name or desired_co_email:
        signers_payload.append({"name": desired_co_name, "email": desired_co_email})

    notes_json = json.dumps(
        {
            "entity": desired_entity,
            "delivery_format": desired_format,
            "signers": signers_payload,
        },
        separators=(",", ":"),
    )

    patch_payload = {
        "sparse": True,
        "Id": qbo_id,
        "SyncToken": str(live.get("SyncToken", "0")),
        "DisplayName": desired_display_name,
        "CompanyName": desired_company_name,
        "Notes": notes_json,
    }

    # Handle PrimaryEmailAddr safely (QBO rejects {"Address": ""})
    if desired_email:
        combined_email = ", ".join([desired_email] + extra_live_emails)
        patch_payload["PrimaryEmailAddr"] = {"Address": combined_email}
    elif live_raw_email:
        patch_payload["PrimaryEmailAddr"] = None

    # Handle PrimaryPhone safely
    if desired_phone:
        patch_payload["PrimaryPhone"] = {"FreeFormNumber": desired_phone}
    elif live_phone:
        patch_payload["PrimaryPhone"] = None

    # Handle BillAddr safely (preserve BillAddr.Id if updating an existing address)
    has_desired_addr = any([desired_street, desired_city, desired_state, desired_zip])
    has_live_addr = bool(live.get("BillAddr"))
    if has_desired_addr:
        addr_obj = {
            "Line1": desired_street,
            "City": desired_city,
            "CountrySubDivisionCode": desired_state,
            "PostalCode": desired_zip,
        }
        if isinstance(live.get("BillAddr"), dict) and live["BillAddr"].get("Id"):
            addr_obj["Id"] = live["BillAddr"]["Id"]
        patch_payload["BillAddr"] = addr_obj
    elif has_live_addr:
        patch_payload["BillAddr"] = None

    try:
        run_qbo("POST", post_uri, json.dumps(patch_payload))
        print("    -> SAVED to QBO.")
        stats["updated"] += 1
    except Exception as exc:
        print(f"    -> ERROR: {exc}", file=sys.stderr)
        stats["errors"] += 1

print("\n=== Summary ===")
print(f"Unchanged (skipped): {stats['unchanged']}")
print(f"{'Updated' if apply_changes else 'Would update'}:   {stats['updated']}")
print(f"Missing/Skipped:     {stats['skipped_missing']}")
if apply_changes:
    print(f"Errors:              {stats['errors']}")
PYEOF