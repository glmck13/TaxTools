#!/usr/bin/env python3

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

from google import genai
from google.genai import types
import requests
from pydantic import BaseModel

# --- File Target Definitions ---
FILE_1_PATH = "sharepoint_folders.csv"
FILE_2_PATH = "qbo_customers.csv"
OUTPUT_QBO_TO_SP_CSV = "qbosp.csv"
OUTPUT_SP_TO_QBO_CSV = "spqbo_orphans.csv"

# --- Configuration Defaults ---
DEFAULT_BATCH_SIZE = 25
MODEL_NAME = "gemini-2.5-flash"
DETERMINISTIC_SEED = 42


def log(message: str) -> None:
    print(f"[INFO] {message}", file=sys.stderr, flush=True)


# --- Environment Assertions ---
REQUIRED_ENVS = [
    "SITE_URL",
    "AUTH_TOKEN",
    "QBO_APIBASE",
    "QBO_REALMID",
    "QBO_ACCESS_TOKEN",
    "GEMINI_API_KEY",
]
missing_envs = [
    env for env in REQUIRED_ENVS if not os.environ.get(env, "").strip()
]
if missing_envs:
    log(f"[FATAL] Missing required environment variables: {', '.join(missing_envs)}")
    sys.exit(1)

SITE_URL = os.environ["SITE_URL"].strip()
AUTH_TOKEN = os.environ["AUTH_TOKEN"].strip()
QBO_APIBASE = os.environ["QBO_APIBASE"].strip()
QBO_REALMID = os.environ["QBO_REALMID"].strip()
QBO_ACCESS_TOKEN = os.environ["QBO_ACCESS_TOKEN"].strip()

client = genai.Client()

sp_session = requests.Session()
sp_session.headers.update(
    {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Accept": "application/json;odata=verbose",
    }
)
qbo_session = requests.Session()
qbo_session.headers.update(
    {
        "Authorization": f"Bearer {QBO_ACCESS_TOKEN}",
        "Accept": "application/json",
    }
)


# --- 1. SHAREPOINT FETCHING ---
def fetch_folder_sharing_links(folder_path: str) -> Tuple[str, Set[str]]:
    """Extracts explicit user emails and sharing link access addresses.
    Returns the folder path even if no sharing information exists yet.
    """
    emails: Set[str] = set()
    try:
        meta_url = (
            f"{SITE_URL}/_api/web/GetFolderByServerRelativeUrl('{quote(folder_path)}')"
            f"?$select=ListItemAllFields/Id,ListItemAllFields/ParentList/Id"
            f"&$expand=ListItemAllFields,ListItemAllFields/ParentList"
        )
        meta_resp = sp_session.get(meta_url, timeout=30)

        if meta_resp.status_code != 200:
            return folder_path, emails

        meta_data = meta_resp.json()
        d_meta = meta_data.get("d", meta_data)
        item_fields = d_meta.get("ListItemAllFields", {})

        item_id = item_fields.get("Id")
        list_guid = item_fields.get("ParentList", {}).get("Id")

        if item_id and list_guid:
            sharing_url = (
                f"{SITE_URL}/_api/web/Lists(@a1)/GetItemById(@a2)/GetSharingInformation"
                f"?@a1='{list_guid}'&@a2='{item_id}'"
                f"&$Expand=pickerSettings,permissionsInformation,sharingLinkTemplates,addressBarLinkSettings"
            )
            headers = {
                "Accept": "application/json;odata=verbose",
                "Content-Type": "application/json;odata=verbose",
            }
            payload = {
                "request": {
                    "maxPrincipalsToReturn": 100,
                    "maxLinkMembersToReturn": 100,
                }
            }

            response = sp_session.post(
                sharing_url, json=payload, headers=headers, timeout=30
            )

            if response.status_code == 200:
                data = response.json().get("d", {})
                perm_info = data.get("permissionsInformation", {})

                for link_node in perm_info.get("links", {}).get("results", []):
                    for member in link_node.get("linkMembers", {}).get("results", []):
                        email = member.get("email") or member.get("loginName")
                        if email and "@" in email:
                            emails.add(email.split("|")[-1].lower().strip())

                for p_node in perm_info.get("principals", {}).get("results", []):
                    principal = p_node.get("principal", {})
                    email = principal.get("email") or principal.get("loginName")
                    if email and "@" in email:
                        emails.add(email.split("|")[-1].lower().strip())

        return folder_path, emails
    except Exception as e:
        log(f"[WARN] Could not retrieve permissions for {folder_path}: {e}")
        return folder_path, set()


def get_top_level_folders() -> List[str]:
    lib_url = f"{SITE_URL}/_api/web/DefaultDocumentLibraryServerRelativeUrl"
    lib_resp = sp_session.get(lib_url, timeout=30)

    if lib_resp.status_code == 200:
        library_path = (
            lib_resp.json().get("d", {}).get("value")
            or lib_resp.json().get("value")
        )
    else:
        parsed_path = urlparse(SITE_URL).path.rstrip("/")
        library_path = f"{parsed_path}/Shared Documents"

    safe_param = quote(f"'{library_path}'")
    url = f"{SITE_URL}/_api/web/GetFolderByServerRelativeUrl(@v)/Folders?$select=ServerRelativeUrl&@v={safe_param}"

    response = sp_session.get(url, timeout=30)
    response.raise_for_status()

    data = response.json()
    results = (
        data.get("d", {}).get("results", [])
        if "d" in data
        else data.get("value", [])
    )

    folders = [
        f["ServerRelativeUrl"] for f in results if f.get("ServerRelativeUrl")
    ]
    return [f for f in folders if not f.endswith("/Forms")]


# --- 2. QBO RETRIEVAL ---
def build_qbo_email_map() -> dict:
    log("Querying QBO ledger...")
    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/query"
    qbo_map = {}
    start = 1
    while True:
        query = quote(
            f"SELECT Id, DisplayName, PrimaryEmailAddr FROM Customer WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000"
        )
        resp_raw = qbo_session.get(f"{url}?query={query}", timeout=30)
        resp_raw.raise_for_status()
        resp = resp_raw.json()

        customers = resp.get("QueryResponse", {}).get("Customer", [])
        if not customers:
            break
        for c in customers:
            email = (
                c.get("PrimaryEmailAddr", {}).get("Address", "").lower().strip()
            )
            if email:
                qbo_map.setdefault(email, []).append((c["DisplayName"], c["Id"]))
        start += 1000
    return qbo_map


# --- 3. DATA PROCESSING & WRITING ---
def fetch_data() -> None:
    folders = get_top_level_folders()

    log(f"Processing permissions across {len(folders)} folders...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        sp_map = dict(executor.map(fetch_folder_sharing_links, folders))

    qbo_map = build_qbo_email_map()

    log(f"Writing File 1 -> {FILE_1_PATH}")
    with open(FILE_1_PATH, "w", encoding="utf-8", newline="") as f1:
        writer = csv.writer(f1)
        writer.writerow(["FolderPath", "Emails"])
        for folder, emails in sp_map.items():
            comma_emails = ",".join(sorted(list(emails)))
            folder_name = folder.split("/")[-1]
            writer.writerow([folder_name, comma_emails])

    log(f"Writing File 2 -> {FILE_2_PATH}")
    with open(FILE_2_PATH, "w", encoding="utf-8", newline="") as f2:
        writer = csv.writer(f2)
        writer.writerow(["DisplayName", "Id", "PrimaryEmailAddr"])
        for email, qids in qbo_map.items():
            for qid in qids:
                writer.writerow([qid[0], qid[1], email])


# --- 4. PYDANTIC SCHEMAS ---
class ForwardMatchResult(BaseModel):
    qbo_id: str
    qbo_name: str
    matched_sp_folder: Optional[str] = None
    confidence_score: float
    match_reason: str


class ForwardMatchResponse(BaseModel):
    matches: List[ForwardMatchResult]


class ReverseMatchResult(BaseModel):
    sp_folder: str
    matched_qbo_id: Optional[str] = None
    matched_qbo_name: Optional[str] = None
    confidence_score: float
    match_reason: str


class ReverseMatchResponse(BaseModel):
    matches: List[ReverseMatchResult]


def load_csv_data() -> Tuple[List[dict], List[dict]]:
    qbo_customers = []
    with open(FILE_2_PATH, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            qbo_customers.append(
                {
                    "id": row.get("Id"),
                    "display_name": row.get("DisplayName"),
                    "email": row.get("PrimaryEmailAddr", ""),
                }
            )

    sp_folders = []
    with open(FILE_1_PATH, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sp_folders.append(
                {
                    "folder_path": row.get("FolderPath"),
                    "sharing_emails": row.get("Emails", ""),
                }
            )

    return qbo_customers, sp_folders


def process_forward_batch(
    qbo_batch: List[dict],
    sp_folders_text: str,
    max_retries: int = 3,
    seed: int = DETERMINISTIC_SEED,
) -> List[dict]:
    qbo_text = json.dumps(qbo_batch, indent=2)

    prompt = f"""
You are an entity resolution expert correlating QBO Customers with SharePoint Folders.

MATCHING CRITERIA (In Order of Priority):

1. DIRECT / NEAR-EXACT NAME & ENTITY MATCHING (Highest Priority):
   - Match exact or near-exact names/entities (e.g., "804 OLD VINTON MILL LLC" -> "804 Old Vinton Mill LLC - SHARED").
   - ALLOW NICKNAMES & COMMON DIMINUTIVES: Treat standard nickname variations as HIGH-CONFIDENCE MATCHES (e.g., Bob/Robert, Bill/William, Jim/James, Mike/Michael, Carol/Carolee, Katie/Catherine, Dave/David, Dan/Daniel).
   - ALLOW MINOR TYPOS & SPELLING VARIATIONS: Minor character differences (1-3 letters, e.g., "Carol" vs "Carolee", "Chiarello" vs "Chiarelo") SHOULD match if the last name or email aligns.
   - DO NOT override a dedicated company/entity folder with an individual household folder if a direct entity folder exists.

2. EMAIL MATCHING & LAST NAME OVERLAP:
   - Compare QBO 'email' against 'sharing_emails'.
   - If the email matches AND the last name or entity matches (e.g., "caroleeaker@gmail.com" for "Aker, Carol" vs "Aker, Carolee - SHARED"), mark as a HIGH-CONFIDENCE MATCH (Score >= 0.95).

3. NAME INVERSIONS & HOUSEHOLD MATCHING:
   - Account for name inversions (e.g., "Smith, John" vs "John Smith").
   - Match individual names to household folders (e.g., "John Smith" -> "John & Mary Smith - SHARED").
   - DO NOT map business entities, DBAs, and trusts to their principal's personal folder

CONSTRAINTS & RULES:
- MUST return a result object for EVERY QBO customer in the batch.
- If matched, set 'matched_sp_folder' to the exact 'folder_path'.
- If NO confident match is found, set 'matched_sp_folder' to null, 'confidence_score' to 0.0, and 'match_reason' to "No matching folder identified".

QBO Customers Batch:
{qbo_text}

SharePoint Folders (Full List):
{sp_folders_text}
"""

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ForwardMatchResponse,
        temperature=0.0,
        seed=seed,
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME, contents=prompt, config=config
            )
            if response.parsed:
                return [m.model_dump() for m in response.parsed.matches]

            data = json.loads(response.text)
            return data.get("matches", [])
        except Exception as e:
            log(f"  [WARN] Attempt {attempt}/{max_retries} failed for forward batch: {e}")
            if attempt < max_retries:
                time.sleep(2 * attempt)

    log("  [ERROR] Forward batch failed after max retries. Constructing fallback records.")
    return [
        {
            "qbo_id": item["id"],
            "qbo_name": item["display_name"],
            "matched_sp_folder": None,
            "confidence_score": 0.0,
            "match_reason": "Batch processing failed",
        }
        for item in qbo_batch
    ]


def process_reverse_batch(
    sp_batch: List[dict],
    qbo_customers_text: str,
    max_retries: int = 3,
    seed: int = DETERMINISTIC_SEED,
) -> List[dict]:
    sp_text = json.dumps(sp_batch, indent=2)

    prompt = f"""
You are an entity resolution expert performing a converse audit: matching SharePoint Folders to QBO Customers.

OBJECTIVE:
Determine if these specific SharePoint folders belong to any active QBO Customer or if they are ORPHANED (no active QBO counterpart).

MATCHING CRITERIA:
1. Exact or near-exact name matching (ignoring standard suffixes like '- SHARED').
2. Match email addresses in folder sharing permissions against QBO PrimaryEmailAddr.
3. Allow standard nickname variations (Bob/Robert, Jim/James) and minor typo tolerances.

CONSTRAINTS & RULES:
- MUST return a result object for EVERY SharePoint folder in this payload.
- If a QBO customer matches, set 'matched_qbo_id' and 'matched_qbo_name' with appropriate confidence score.
- If NO QBO customer matches, set 'matched_qbo_id' to null, 'matched_qbo_name' to null, 'confidence_score' to 0.0, and 'match_reason' to "Orphaned SharePoint folder - No QBO customer found".

Unmatched SharePoint Folders Batch:
{sp_text}

All QBO Customers:
{qbo_customers_text}
"""

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ReverseMatchResponse,
        temperature=0.0,
        seed=seed,
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME, contents=prompt, config=config
            )
            if response.parsed:
                return [m.model_dump() for m in response.parsed.matches]

            data = json.loads(response.text)
            return data.get("matches", [])
        except Exception as e:
            log(f"  [WARN] Attempt {attempt}/{max_retries} failed for reverse batch: {e}")
            if attempt < max_retries:
                time.sleep(2 * attempt)

    log("  [ERROR] Reverse batch failed after max retries. Constructing fallback records.")
    return [
        {
            "sp_folder": item["folder_path"],
            "matched_qbo_id": None,
            "matched_qbo_name": None,
            "confidence_score": 0.0,
            "match_reason": "Reverse batch processing failed",
        }
        for item in sp_batch
    ]


def save_forward_matches_to_csv(matches: List[dict], filename: str) -> None:
    fieldnames = [
        "qbo_id",
        "qbo_name",
        "matched_sp_folder",
        "confidence_score",
        "match_reason",
    ]
    with open(filename, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=":")
        writer.writeheader()
        for record in matches:
            writer.writerow(
                {
                    "qbo_id": record.get("qbo_id", ""),
                    "qbo_name": record.get("qbo_name", ""),
                    "matched_sp_folder": record.get("matched_sp_folder") or "",
                    "confidence_score": record.get("confidence_score", 0.0),
                    "match_reason": record.get("match_reason", ""),
                }
            )


def save_reverse_matches_to_csv(matches: List[dict], filename: str) -> None:
    fieldnames = [
        "sp_folder",
        "matched_qbo_id",
        "matched_qbo_name",
        "confidence_score",
        "match_reason",
    ]
    with open(filename, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=":")
        writer.writeheader()
        for record in matches:
            writer.writerow(
                {
                    "sp_folder": record.get("sp_folder", ""),
                    "matched_qbo_id": record.get("matched_qbo_id") or "",
                    "matched_qbo_name": record.get("matched_qbo_name") or "",
                    "confidence_score": record.get("confidence_score", 0.0),
                    "match_reason": record.get("match_reason", ""),
                }
            )


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Correlate QBO Customers with SharePoint Folders bidirectionally via Gemini LLM."
    )
    parser.add_argument(
        "-p",
        "--prune",
        action="store_true",
        help="Enable dynamic folder pruning (removes matched folders from subsequent forward batch payloads). Default: Disabled.",
    )
    parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of records per batch payload (Default: {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_cli_args()
    batch_size = args.batch_size
    enable_pruning = args.prune

    fetch_data()

    qbo_customers, sp_folders = load_csv_data()
    available_sp_folders = list(sp_folders)
    all_sp_folder_paths = {f["folder_path"] for f in sp_folders}

    total_customers = len(qbo_customers)
    log(
        f"Loaded {total_customers} QBO customers and {len(available_sp_folders)} SharePoint folders."
    )
    log(f"Configuration: Batch Size = {batch_size}, Pruning Enabled = {enable_pruning}")

    # --- PASS 1: QBO -> SHAREPOINT ---
    all_qbo_matches = []
    matched_sp_folders_set: Set[str] = set()

    total_batches = (total_customers + batch_size - 1) // batch_size
    for i in range(0, total_customers, batch_size):
        batch = qbo_customers[i : i + batch_size]
        batch_num = (i // batch_size) + 1

        log(
            f"[Pass 1] Processing Forward Batch {batch_num}/{total_batches} (Customers {i+1} to {min(i+batch_size, total_customers)})..."
        )

        sp_folders_text = json.dumps(available_sp_folders, indent=2)
        batch_results = process_forward_batch(batch, sp_folders_text)
        all_qbo_matches.extend(batch_results)

        # Track successfully mapped folders
        for m in batch_results:
            folder = m.get("matched_sp_folder")
            if folder and m.get("confidence_score", 0.0) >= 0.8:
                matched_sp_folders_set.add(folder)

        if enable_pruning:
            matched_in_batch = {
                m["matched_sp_folder"]
                for m in batch_results
                if m.get("matched_sp_folder") and m.get("confidence_score", 0.0) >= 0.9
            }
            if matched_in_batch:
                available_sp_folders = [
                    f
                    for f in available_sp_folders
                    if f["folder_path"] not in matched_in_batch
                ]
                log(
                    f"  -> Pruned {len(matched_in_batch)} folder(s). Remaining in active batch list: {len(available_sp_folders)}"
                )

        time.sleep(0.5)

    save_forward_matches_to_csv(all_qbo_matches, OUTPUT_QBO_TO_SP_CSV)
    log(f"Pass 1 Complete! Saved QBO->SP matches to {OUTPUT_QBO_TO_SP_CSV}")

    # --- PASS 2: SHAREPOINT -> QBO CONVERSE AUDIT & ORPHAN DETECTION ---
    unmatched_sp_folders = [
        f for f in sp_folders if f["folder_path"] not in matched_sp_folders_set
    ]
    log(
        f"Identified {len(unmatched_sp_folders)} candidate orphaned SharePoint folder(s) out of {len(all_sp_folder_paths)} total."
    )

    all_reverse_matches = []
    
    # Construct converse entries for folders already matched symmetrically in Pass 1
    for m in all_qbo_matches:
        if m.get("matched_sp_folder") and m.get("confidence_score", 0.0) >= 0.8:
            all_reverse_matches.append(
                {
                    "sp_folder": m["matched_sp_folder"],
                    "matched_qbo_id": m["qbo_id"],
                    "matched_qbo_name": m["qbo_name"],
                    "confidence_score": m["confidence_score"],
                    "match_reason": f"Symmetric match from Pass 1: {m['match_reason']}",
                }
            )

    # Re-examine remaining unmatched folders against all QBO customers
    if unmatched_sp_folders:
        qbo_customers_text = json.dumps(qbo_customers, indent=2)
        total_rev_batches = (len(unmatched_sp_folders) + batch_size - 1) // batch_size
        
        for i in range(0, len(unmatched_sp_folders), batch_size):
            sp_batch = unmatched_sp_folders[i : i + batch_size]
            rev_batch_num = (i // batch_size) + 1

            log(
                f"[Pass 2] Processing Reverse Batch {rev_batch_num}/{total_rev_batches} (Folders {i+1} to {min(i+batch_size, len(unmatched_sp_folders))})..."
            )

            reverse_results = process_reverse_batch(sp_batch, qbo_customers_text)
            all_reverse_matches.extend(reverse_results)
            time.sleep(0.5)

    save_reverse_matches_to_csv(all_reverse_matches, OUTPUT_SP_TO_QBO_CSV)
    log(
        f"Pass 2 Complete! Saved SP->QBO converse audit and orphan analysis to {OUTPUT_SP_TO_QBO_CSV}"
    )


if __name__ == "__main__":
    main()