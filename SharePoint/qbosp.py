#!/usr/bin/env python3

import os
import sys
import html
import json
from urllib.parse import quote, urlparse
import requests
from concurrent.futures import ThreadPoolExecutor

# --- File Target Definitions ---
FILE_1_PATH = "sharepoint_folders.csv"
FILE_2_PATH = "qbo_customers.csv"

def log(message):
    print(f"[INFO] {message}", file=sys.stderr, flush=True)

# --- 1. SETUP ---
SITE_URL = os.environ.get("SITE_URL", "").strip()
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "").strip()

QBO_APIBASE = os.environ.get("QBO_APIBASE", "").strip()
QBO_REALMID = os.environ.get("QBO_REALMID", "").strip()
QBO_ACCESS_TOKEN = os.environ.get("QBO_ACCESS_TOKEN", "").strip()

sp_session = requests.Session()
sp_session.headers.update({"Authorization": f"Bearer {AUTH_TOKEN}", "Accept": "application/json;odata=verbose"})
qbo_session = requests.Session()
qbo_session.headers.update({"Authorization": f"Bearer {QBO_ACCESS_TOKEN}", "Accept": "application/json"})

# --- 2. SHAREPOINT FETCHING ---
def fetch_folder_sharing_links(folder_path):
    """
    Extracts explicit user emails and link member access addresses mapping
    the modern link structure identified via browser diagnostics.
    """
    try:
        meta_url = f"{SITE_URL}/_api/web/GetFolderByServerRelativeUrl('{quote(folder_path)}')?$select=ListItemAllFields/Id,ListItemAllFields/ParentList/Id&$expand=ListItemAllFields,ListItemAllFields/ParentList"
        meta_resp = sp_session.get(meta_url, timeout=30)
        emails = set()
        
        if meta_resp.status_code == 200:
            meta_data = meta_resp.json()
            d_meta = meta_data.get("d", meta_data)
            item_fields = d_meta.get("ListItemAllFields", {})
            
            item_id = item_fields.get("Id")
            list_guid = item_fields.get("ParentList", {}).get("Id")
            
            if item_id and list_guid:
                sharing_url = f"{SITE_URL}/_api/web/Lists(@a1)/GetItemById(@a2)/GetSharingInformation?@a1='{list_guid}'&@a2='{item_id}'&$Expand=pickerSettings,permissionsInformation,sharingLinkTemplates,addressBarLinkSettings"
                
                headers = {
                    "Accept": "application/json;odata=verbose",
                    "Content-Type": "application/json;odata=verbose"
                }
                payload = {
                    "request": {
                        "maxPrincipalsToReturn": 100,
                        "maxLinkMembersToReturn": 100
                    }
                }
                
                response = sp_session.post(sharing_url, json=payload, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    data = response.json().get("d", {})
                    perm_info = data.get("permissionsInformation", {})
                    
                    # Array Parse 1: linkMembers
                    links_list = perm_info.get("links", {}).get("results", [])
                    for link_node in links_list:
                        members = link_node.get("linkMembers", {}).get("results", [])
                        for member in members:
                            email = member.get("email") or member.get("loginName")
                            if email and "@" in email:
                                if "|" in email:
                                    email = email.split("|")[-1]
                                emails.add(email.lower().strip())
                                
                    # Array Parse 2: direct principals collection
                    principals_list = perm_info.get("principals", {}).get("results", [])
                    for p_node in principals_list:
                        principal = p_node.get("principal", {})
                        email = principal.get("email") or principal.get("loginName")
                        if email and "@" in email:
                            if "|" in email:
                                email = email.split("|")[-1]
                            emails.add(email.lower().strip())
                                
        return folder_path, emails
    except Exception as e:
        print(f"[DEBUG] Error compiling shares for {folder_path}: {e}", file=sys.stderr, flush=True)
        return folder_path, set()

def get_top_level_folders():
    lib_url = f"{SITE_URL}/_api/web/DefaultDocumentLibraryServerRelativeUrl"
    lib_resp = sp_session.get(lib_url, timeout=30)
    
    if lib_resp.status_code == 200:
        library_path = lib_resp.json().get("d", {}).get("value") or lib_resp.json().get("value")
    else:
        parsed_path = urlparse(SITE_URL).path.rstrip('/')
        library_path = f"{parsed_path}/Shared Documents"
        
    safe_param = quote(f"'{library_path}'")
    url = f"{SITE_URL}/_api/web/GetFolderByServerRelativeUrl(@v)/Folders?$select=ServerRelativeUrl&@v={safe_param}"
    
    response = sp_session.get(url, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    results = data.get("d", {}).get("results", []) if "d" in data else data.get("value", [])
    
    folders = [f["ServerRelativeUrl"] for f in results if f.get("ServerRelativeUrl")]
    folders = [f for f in folders if not f.endswith('/Forms')]
    return folders

# --- 3. QBO RETRIEVAL ---
def build_qbo_email_map():
    log("Querying QBO ledger...")
    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/query"
    qbo_map = {} 
    start = 1
    while True:
        query = quote(f"SELECT Id, DisplayName, PrimaryEmailAddr FROM Customer WHERE Active = true STARTPOSITION {start} MAXRESULTS 1000")
        resp = qbo_session.get(f"{url}?query={query}", timeout=30).json()
        customers = resp.get("QueryResponse", {}).get("Customer", [])
        if not customers: break
        for c in customers:
            email = c.get("PrimaryEmailAddr", {}).get("Address", "").lower().strip()
            if email: qbo_map.setdefault(email, []).append((c["DisplayName"], c["Id"]))
        start += 1000
    return qbo_map

# --- 4. DATA PROCESSING & WRITING ---
def fetch_data():
    folders = get_top_level_folders()
    
    log(f"Processing permissions across {len(folders)} folders...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        sp_map = dict(executor.map(fetch_folder_sharing_links, folders))
    
    qbo_map = build_qbo_email_map()
    
    # --- WRITE FILE 1: SharePoint Folders & Delimited Emails ---
    log(f"Writing File 1 -> {FILE_1_PATH}")
    with open(FILE_1_PATH, "w", encoding="utf-8") as f1:
        f1.write("FolderPath:Emails\n")
        for folder, emails in sp_map.items():
            comma_emails = ",".join(sorted(list(emails)))
            f1.write(f'{folder.split('/')[-1]}:{comma_emails}\n')
            
    # --- WRITE FILE 2: QBO Customers ---
    log(f"Writing File 2 -> {FILE_2_PATH}")
    with open(FILE_2_PATH, "w", encoding="utf-8") as f2:
        f2.write("DisplayName:Id:PrimaryEmailAddr\n")
        for email, qids in qbo_map.items():
            for qid in qids:
                f2.write(f'{qid[0]}:{qid[1]}:{email}\n')

import csv
import json
import time
from typing import List, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel

# --- Configuration ---
BATCH_SIZE = 25  # Lowered from 50 to prevent output token truncation
MODEL_NAME = "gemini-2.5-flash"
OUTPUT_CSV_FILE = "qbosp.csv"

client = genai.Client()  # Expects GEMINI_API_KEY env variable


# --- Pydantic Schemas for Structured Output ---
class MatchResult(BaseModel):
    qbo_id: str
    qbo_name: str
    matched_sp_folder: Optional[str] = None
    confidence_score: float
    match_reason: str


class MatchResponse(BaseModel):
    matches: List[MatchResult]


def load_csv_data():
    """Load QBO and SharePoint CSV files into clean dict lists."""
    qbo_customers = []
    with open("qbo_customers.csv", mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=':')
        for row in reader:
            qbo_customers.append(
                {
                    "id": row.get("Id") or row.get("QBO_ID"),
                    "display_name": row.get("DisplayName"),
                    "email": row.get("PrimaryEmailAddr", ""),
                }
            )

    sp_folders = []
    with open("sharepoint_folders.csv", mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=':')
        for row in reader:
            sp_folders.append(
                {
                    "folder_path": row.get("FolderPath")
                    or row.get("ServerRelativeUrl"),
                    "sharing_emails": row.get("Emails", ""),
                }
            )

    return qbo_customers, sp_folders


def process_batch(qbo_batch, sp_folders_text, max_retries=3):
    """Processes a single batch of QBO customers against all SharePoint folders with retry logic."""
    qbo_text = json.dumps(qbo_batch, indent=2)

    prompt = f"""
You are an entity resolution expert. Compare the provided batch of QBO Customers against the list of SharePoint Folders and correlate them.
Account for name inversions (Last, First), spouses/households, business DBAs, and legal entities (Trusts/LLCs). Use emails as supporting evidence if available.

QBO Customers Batch:
{qbo_text}

SharePoint Folders (Full List):
{sp_folders_text}
"""

    # Structured Output config using container model MatchResponse
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=MatchResponse,
        temperature=0.1,
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME, contents=prompt, config=config
            )
            data = json.loads(response.text)
            return data.get("matches", [])
        except Exception as e:
            print(f"  [WARN] Attempt {attempt}/{max_retries} failed for batch: {e}")
            if attempt < max_retries:
                time.sleep(2 * attempt)  # Exponential backoff

    print(
        f"  [ERROR] Batch failed after {max_retries} attempts. Returning empty results."
    )
    return []


def save_to_colon_csv(matches, filename):
    """Writes the matches array to a CSV using ':' as the delimiter."""
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
            clean_record = {
                "qbo_id": record.get("qbo_id", ""),
                "qbo_name": record.get("qbo_name", ""),
                "matched_sp_folder": record.get("matched_sp_folder") or "",
                "confidence_score": record.get("confidence_score", 0.0),
                "match_reason": record.get("match_reason", ""),
            }
            writer.writerow(clean_record)


def main():
    fetch_data()

    qbo_customers, sp_folders = load_csv_data()
    sp_folders_text = json.dumps(sp_folders, indent=2)

    total_customers = len(qbo_customers)
    print(
        f"Loaded {total_customers} QBO customers and {len(sp_folders)} SharePoint folders."
    )

    all_matches = []

    # --- Batching Loop ---
    for i in range(0, total_customers, BATCH_SIZE):
        batch = qbo_customers[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total_customers + BATCH_SIZE - 1) // BATCH_SIZE

        print(
            f"Processing Batch {batch_num}/{total_batches} (Customers {i+1} to {min(i+BATCH_SIZE, total_customers)})..."
        )

        batch_results = process_batch(batch, sp_folders_text)
        all_matches.extend(batch_results)

        # Delay to respect rate limits
        time.sleep(1)

    # --- Save Results to Colon-Delimited CSV ---
    save_to_colon_csv(all_matches, OUTPUT_CSV_FILE)
    print(
        f"\nProcessing complete! Exported {len(all_matches)} rows to {OUTPUT_CSV_FILE}"
    )


if __name__ == "__main__":
    main()
