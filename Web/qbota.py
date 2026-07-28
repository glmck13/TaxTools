#!/usr/bin/env python3
"""
qbota.py

Combines live QBO REST API extraction with google-genai PDF parsing.
Dynamically maps extracted PDF line items against active QBO Service Items via Gemini prompt context.
"""

import sys
import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# Setup logging
DEBUG_MODE = os.getenv("DEBUG", "").lower() in ("1", "true", "yes") or "--debug" in sys.argv
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("qbota")

# Graceful import check for google-genai
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
    logger.debug("google-genai package detected successfully.")
except ImportError:
    HAS_GENAI = False
    logger.warning("google-genai package not found. PDF extraction will be disabled.")

# QBO Environment Configuration
QBO_REALMID = os.getenv("QBO_REALMID", "")
QBO_ACCESS_TOKEN = os.getenv("QBO_ACCESS_TOKEN", "")
QBO_APIBASE = os.getenv("QBO_APIBASE", "https://quickbooks.api.intuit.com/v3/company").rstrip("/").removesuffix("/company")


class ExtractedServiceLine(BaseModel):
    matched_qbo_id: str = Field(
        description="The exact QBO Item ID selected from the provided LIVE QBO SERVICE CATALOG that best matches this line item."
    )
    service_name: str = Field(
        description="Name or title of service or discount line item."
    )
    fee: float = Field(
        description="Fee amount in USD. Use NEGATIVE values for discounts or fee reductions (e.g. -1000.00)."
    )
    notes: str = Field(
        default="",
        description="Context, terms, state details, or billing frequency terms."
    )
    entity_target: str = Field(
        default="both",
        description="'individual', 'organization', or 'both'"
    )


class PDFContractMetadata(BaseModel):
    meta_entity_type: str = Field(
        default="individual",
        description="Extract the entity type of the client: 's_corp', 'partnership', 'c_corp', 'llc', 'non_profit', 'trust', or 'individual'."
    )
    meta_signature_type: str = Field(
        default="single",
        description="Return secondary client spouse/co-signer EMAIL if joint. Return 'single' if 1 client signer. Ignore firm counter-signers like Steve Tarrant."
    )
    meta_co_signer_name: str = Field(
        default="", 
        description="Full human name of secondary client co-signer or spouse (e.g., 'Jane Doe'). Ignore firm counter-signers like Steve Tarrant."
    )
    total_contract_fee: Optional[float] = Field(
        default=0.0,
        description="Total top-line agreement fee stated (e.g., 6500.00)."
    )
    deposit_required: Optional[float] = Field(
        default=0.0,
        description="Deposit amount required upon submission (e.g., 1000.00)."
    )
    hourly_rate_range: Optional[str] = Field(
        default="",
        description="Hourly rate range for out-of-scope work (e.g. '$100-$250/hr')."
    )
    extracted_services: List[ExtractedServiceLine] = Field(
        default_factory=list,
        description="List of distinct services, discounts, and fee breakdowns found in the agreement."
    )
    out_of_scope_list: List[str] = Field(
        default_factory=list, 
        description="List of excluded or additional billable out-of-scope items."
    )


def get_qbo_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {QBO_ACCESS_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity"  # Prevents decompression mismatch errors
    }


def fetch_qbo_items() -> List[Dict[str, Any]]:
    """Queries QBO API to pull all active Products/Services for matching."""
    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/query"
    query = "SELECT Id, Name, Description, Type FROM Item WHERE Active = true MAXRESULTS 1000"
    logger.info("Fetching QBO Item catalog for dynamic service resolution...")

    resp = requests.get(url, headers=get_qbo_headers(), params={"query": query})
    if resp.status_code != 200:
        logger.warning(f"Failed to fetch QBO Items catalog: {resp.text}")
        return []

    items = resp.json().get("QueryResponse", {}).get("Item", [])
    logger.debug(f"Retrieved {len(items)} active items from QBO Catalog.")
    return items


def resolve_qbo_item(extracted_name: str, qbo_items: List[Dict[str, Any]]) -> Dict[str, str]:
    """Fallback utility to match service titles against QBO Items if Gemini match is absent."""
    name_clean = extracted_name.lower().strip()

    for q_item in qbo_items:
        q_name = q_item.get("Name", "").lower()
        if name_clean in q_name or q_name in name_clean:
            return {"item_id": str(q_item.get("Id")), "service": q_item.get("Name")}

    if "deposit" in name_clean or "retainer" in name_clean:
        for q_item in qbo_items:
            if "deposit" in q_item.get("Name", "").lower():
                return {"item_id": str(q_item.get("Id")), "service": q_item.get("Name")}
        return {"item_id": "00000", "service": "Deposit Due"}

    if "discount" in name_clean or "reduction" in name_clean:
        for q_item in qbo_items:
            if "discount" in q_item.get("Name", "").lower():
                return {"item_id": str(q_item.get("Id")), "service": q_item.get("Name")}
        return {"item_id": "18", "service": "Discount"}

    first_item = qbo_items[0] if qbo_items else {"Id": "21", "Name": extracted_name}
    return {"item_id": str(first_item.get("Id")), "service": extracted_name}


def extract_pdf_metadata(pdf_path: str, qbo_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Uses Gemini 2.5 Flash via google-genai to extract metadata and maps services directly to QBO Items."""
    logger.info(f"Starting PDF extraction for: {pdf_path}")

    if not HAS_GENAI:
        logger.warning("Skipping PDF analysis because google-genai module is missing.")
        return {}

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is not set!")
        return {}

    uploaded_file = None

    try:
        catalog_prompt_list = "\n".join([
            f"- ID: {item.get('Id')} | Name: '{item.get('Name')}' | Desc: '{item.get('Description', '')}'"
            for item in qbo_items
        ])
        logger.debug(f"Formatted {len(qbo_items)} active QBO catalog items for prompt context.")

        logger.debug("Initializing google-genai Client...")
        client = genai.Client(api_key=api_key)

        logger.debug(f"Uploading file {pdf_path} to Gemini Files API...")
        uploaded_file = client.files.upload(file=pdf_path)
        logger.debug(f"Uploaded file successfully. Remote URI: {uploaded_file.name}")

        prompt = f"""
        Analyze this signed Tax Services Agreement PDF carefully.
        
        LIVE QBO SERVICE CATALOG:
        {catalog_prompt_list}
        
        EXTRACTION RULES:
        1. Entity Classification: Look for entity clues in client names (e.g., 'LLC', 'Inc', 'Corp', 'Partnership', 'S-Corp') or narrative text. Map to 's_corp', 'partnership', 'c_corp', 'non_profit', 'trust', or 'individual'.
        2. Firm Counter-Signatures: Steve Tarrant (or 'Managing Member') is the firm's counter-signer, NOT a client co-signer. Do NOT treat Steve Tarrant as a co-signer or spouse.
        3. Co-Signers: Set meta_signature_type to 'single' and meta_co_signer_name to "" unless there is a second CLIENT/HUMAN co-signer (e.g., spouse).
        4. Granularity: Break down line items into their smallest explicitly priced components.
        5. Discounts: Express discounts as separate negative fee line items (e.g., -1000.00).
        6. Matching: For every line item, assign the single best matched_qbo_id from the LIVE QBO SERVICE CATALOG above.
        
        Output empty strings ("") rather than "null", "none", or "undefined".
        """

        logger.debug("Sending request to gemini-2.5-flash with structured output schema...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, uploaded_file],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PDFContractMetadata,
                temperature=0.0,
                seed=42,
            ),
        )

        extracted: PDFContractMetadata = response.parsed if response.parsed else PDFContractMetadata()
        logger.debug(f"Raw parsed metadata from Gemini: {extracted}")

        extracted_rows = []

        # Process Deposit
        if extracted.deposit_required and extracted.deposit_required > 0:
            resolved_dep = resolve_qbo_item("Deposit", qbo_items)
            extracted_rows.append({
                "item_id": resolved_dep["item_id"],
                "service": resolved_dep["service"],
                "fee": f"{extracted.deposit_required:.2f}",
                "notes": "Deposit due upon submission of tax information",
                "bp": "both"
            })
            logger.info(f"Deposit extracted: ${extracted.deposit_required:.2f} (Mapped ID: {resolved_dep['item_id']})")

        # Process Extracted Service Lines directly using Gemini's matched QBO ID
        sum_services = 0.0
        for item in extracted.extracted_services:
            sum_services += item.fee
            logger.info(
                f"Extracted Line Item: '{item.service_name}' (${item.fee:.2f}) "
                f"--> Matched QBO ID: '{item.matched_qbo_id}'"
            )
            extracted_rows.append({
                "item_id": str(item.matched_qbo_id),
                "service": item.service_name,
                "fee": f"{item.fee:.2f}",
                "notes": item.notes or item.service_name,
                "bp": item.entity_target
            })

        # Fee Reconciliation Logging
        logger.info(
            f"Contract Fee Summary: PDF Stated Total = ${extracted.total_contract_fee:.2f} | "
            f"Sum of Extracted Rows = ${sum_services:.2f}"
        )
        if abs(extracted.total_contract_fee - sum_services) > 0.01:
            logger.warning("Discrepancy detected between PDF top-line fee and sum of extracted line items!")

        oos_dict = {f"out_of_scope_item_{i}": item for i, item in enumerate(extracted.out_of_scope_list)}
        if extracted.hourly_rate_range:
            oos_dict["out_of_scope_hourly_rate"] = f"Additional work billed at {extracted.hourly_rate_range}"

        return {
            "meta_entity_type": extracted.meta_entity_type,  # <-- Corrected Pass-Through
            "meta_signature_type": extracted.meta_signature_type,
            "meta_co_signer_name": extracted.meta_co_signer_name,
            "pdf_extracted_rows": extracted_rows,
            "out_of_scope_items": oos_dict,
            "total_contract_fee": extracted.total_contract_fee
        }

    except Exception as e:
        logger.error(f"Failed to extract metadata from PDF {pdf_path}: {e}", exc_info=True)
        return {}
    finally:
        if uploaded_file:
            try:
                logger.debug(f"Cleaning up uploaded file {uploaded_file.name} from Gemini...")
                client.files.delete(name=uploaded_file.name)
            except Exception as e:
                logger.warning(f"Failed to delete uploaded file from Gemini: {e}")


def fetch_qbo_customer(customer_id: str) -> Dict[str, Any]:
    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/customer/{customer_id}"
    logger.info(f"Fetching QBO Customer profile for ID: {customer_id}")

    resp = requests.get(url, headers=get_qbo_headers())
    if resp.status_code != 200:
        logger.error(f"QBO Customer Fetch Error: {resp.text}")
        raise RuntimeError(f"QBO API Error ({resp.status_code}): {resp.text}")

    return resp.json().get("Customer", {})


def fetch_latest_qbo_invoice(customer_id: str) -> Optional[Dict[str, Any]]:
    query = f"SELECT * FROM Invoice WHERE CustomerRef = '{customer_id}' ORDERBY TxnDate DESC MAXRESULTS 1"
    url = f"{QBO_APIBASE}/company/{QBO_REALMID}/query"
    logger.info(f"Fetching latest invoice for Customer ID: {customer_id}")

    resp = requests.get(url, headers=get_qbo_headers(), params={"query": query})
    if resp.status_code != 200:
        logger.warning(f"Failed to fetch invoices for customer {customer_id}: {resp.text}")
        return None

    invoices = resp.json().get("QueryResponse", {}).get("Invoice", [])
    return invoices[0] if invoices else None


def resolve_entity_type(customer: Dict[str, Any]) -> str:
    """Infer entity type from QBO customer attributes."""
    company_name = customer.get("CompanyName", "")
    is_company = customer.get("IsProject", False) is False and bool(company_name)

    if is_company:
        name_lower = company_name.lower()
        if "inc" in name_lower or "corp" in name_lower:
            return "c_corp"
        if "llc" in name_lower or "partner" in name_lower:
            return "partnership"
        if "foundation" in name_lower or "nonprofit" in name_lower:
            return "non_profit"
        if "trust" in name_lower:
            return "trust"
        return "s_corp"
    return "individual"


def main():
    if "--debug" in sys.argv:
        sys.argv.remove("--debug")

    if len(sys.argv) < 2:
        print("Usage: python3 qbota.py <QBO_CUSTOMER_ID> [PDF_FILE_PATH] [--debug]")
        sys.exit(1)

    customer_id = sys.argv[1]
    pdf_path = sys.argv[2] if len(sys.argv) > 2 else None

    logger.info(f"Customer = {customer_id}, PDF = {pdf_path if pdf_path else 'None'}")

    if not QBO_REALMID or not QBO_ACCESS_TOKEN:
        logger.critical("Missing QBO_REALMID or QBO_ACCESS_TOKEN environment variables.")
        sys.exit(1)

    try:
        customer = fetch_qbo_customer(customer_id)
        latest_invoice = fetch_latest_qbo_invoice(customer_id)
        qbo_items = fetch_qbo_items()
    except Exception as e:
        logger.critical(f"Error communicating with QBO: {e}", exc_info=DEBUG_MODE)
        sys.exit(1)

    pdf_meta = {}
    if pdf_path and os.path.exists(pdf_path):
        pdf_meta = extract_pdf_metadata(pdf_path, qbo_items)
    elif pdf_path:
        logger.critical(f"File not found: {pdf_path}")
        sys.exit(1)

    display_name = customer.get("DisplayName") or customer.get("FullyQualifiedName", "")
    bill_addr = customer.get("BillAddr", {})

    qbo_entity_type = resolve_entity_type(customer)
    pdf_entity_type = pdf_meta.get("meta_entity_type", "").lower()
    if pdf_entity_type in ['s_corp', 'partnership', 'c_corp', 'llc', 'non_profit', 'trust', 'organization']:
        entity_type = "s_corp" if pdf_entity_type == "llc" else pdf_entity_type
    else:
        entity_type = qbo_entity_type

    is_org = entity_type in ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust', 'organization']
    bp_val = "organization" if is_org else "individual"

    combined_rows = []
    if "pdf_extracted_rows" in pdf_meta and pdf_meta["pdf_extracted_rows"]:
        combined_rows.extend(pdf_meta["pdf_extracted_rows"])
    elif latest_invoice and "Line" in latest_invoice:
        for line in latest_invoice["Line"]:
            detail_type = line.get("DetailType")
            if detail_type == "SalesItemLineDetail":
                item_ref = line.get("SalesItemLineDetail", {}).get("ItemRef", {})
                combined_rows.append({
                    "item_id": str(item_ref.get("value", "")),
                    "service": item_ref.get("name") or line.get("Description") or "",
                    "fee": f"{line.get('Amount', 0.0):.2f}",
                    "notes": line.get("Description") or "",
                    "bp": bp_val
                })

    payload = {
        "estimate_date_option": "next_year",
        "friendly_name": display_name,
        "heal_profile_flag": "false",
        "meta_signature_type": pdf_meta.get("meta_signature_type", "single"),
        "meta_co_signer_name": pdf_meta.get("meta_co_signer_name", ""),
        "meta_entity_type": entity_type,
        "heal_street": bill_addr.get("Line1", ""),
        "heal_city": bill_addr.get("City", ""),
        "heal_state": bill_addr.get("CountrySubDivisionCode", ""),
        "heal_zip": bill_addr.get("PostalCode", ""),
        "out_of_scope_items": pdf_meta.get("out_of_scope_items", {}),
        "estimate_id": str(latest_invoice.get("Id", "")) if latest_invoice else "",
        "rows": combined_rows
    }

    logger.info(f"Successfully generated payload for '{display_name}' with {len(combined_rows)} row(s).")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
