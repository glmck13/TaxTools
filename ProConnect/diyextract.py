#!/usr/bin/env python3

import argparse
import os
import sys
import warnings
from typing import List, Optional

import pymupdf
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from openai import APIError, AzureOpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator

warnings.filterwarnings("ignore")

# =============================================================================
# PYDANTIC SCHEMA DEFINITIONS WITH SELF-HEALING VALIDATION
# =============================================================================


class OtherExpenseItem(BaseModel):
    description: str = Field(
        description="Description/line item name of the expense"
    )
    amount: float = Field(description="Expense amount")


class ScheduleCExpenses(BaseModel):
    advertising: Optional[float] = Field(None, description="Line 8: Advertising")
    car_and_truck_expenses: Optional[float] = Field(
        None, description="Line 9: Car and truck expenses"
    )
    commissions_and_fees: Optional[float] = Field(
        None, description="Line 10: Commissions and fees"
    )
    contract_labor: Optional[float] = Field(
        None, description="Line 11: Contract labor"
    )
    depletion: Optional[float] = Field(None, description="Line 12: Depletion")
    depreciation_and_sec_179: Optional[float] = Field(
        None, description="Line 13: Depreciation and section 179 expense"
    )
    employee_benefit_programs: Optional[float] = Field(
        None, description="Line 14: Employee benefit programs"
    )
    insurance_other_than_health: Optional[float] = Field(
        None, description="Line 15: Insurance (other than health)"
    )
    interest_mortgage: Optional[float] = Field(
        None, description="Line 16a: Mortgage interest paid to banks"
    )
    interest_other: Optional[float] = Field(
        None, description="Line 16b: Other interest"
    )
    legal_and_professional_services: Optional[float] = Field(
        None, description="Line 17: Legal and professional services"
    )
    office_expense: Optional[float] = Field(
        None, description="Line 18: Office expense"
    )
    pension_and_profit_sharing_plans: Optional[float] = Field(
        None, description="Line 19: Pension and profit-sharing plans"
    )
    rent_vehicles_machinery: Optional[float] = Field(
        None, description="Line 20a: Rent - Vehicles, machinery, equipment"
    )
    rent_other_business_property: Optional[float] = Field(
        None, description="Line 20b: Rent - Other business property"
    )
    repairs_and_maintenance: Optional[float] = Field(
        None, description="Line 21: Repairs and maintenance"
    )
    supplies: Optional[float] = Field(None, description="Line 22: Supplies")
    taxes_and_licenses: Optional[float] = Field(
        None, description="Line 23: Taxes and licenses"
    )
    travel: Optional[float] = Field(None, description="Line 24a: Travel")
    deductible_meals: Optional[float] = Field(
        None, description="Line 24b: Deductible meals"
    )
    utilities: Optional[float] = Field(None, description="Line 25: Utilities")
    wages: Optional[float] = Field(
        None, description="Line 26: Wages (less employment credits)"
    )
    other_expenses_detail: List[OtherExpenseItem] = Field(
        default=[],
        description="Line 27a / Part V: Itemized breakdown of other expenses",
    )
    other_expenses_total: Optional[float] = Field(
        None, description="Line 27a: Total of other expenses"
    )


class ScheduleC(BaseModel):
    business_name: Optional[str] = Field(
        None, description="Line C: Business name or principal activity description"
    )
    business_code: Optional[str] = Field(
        None,
        description="Line B: Principal business code (include activity description if present)",
    )
    accounting_method: Optional[str] = Field(
        None,
        description="Line F: Accounting method in human-readable text ('Cash', 'Accrual', or 'Other'). Do not use codes.",
    )

    gross_receipts_or_sales: Optional[float] = Field(
        None, description="Line 1: Gross receipts or sales"
    )
    returns_and_allowances: Optional[float] = Field(
        None, description="Line 2: Returns and allowances"
    )
    cost_of_goods_sold: Optional[float] = Field(
        None, description="Line 4: Cost of goods sold"
    )
    gross_income: Optional[float] = Field(
        None, description="Line 7: Gross income"
    )

    expenses: Optional[ScheduleCExpenses] = Field(
        None,
        description="Itemized business expenses",
    )
    total_expenses: Optional[float] = Field(
        None, description="Line 28: Total expenses"
    )
    expenses_for_business_use_of_home: Optional[float] = Field(
        None, description="Line 30: Expenses for business use of home"
    )
    net_profit_or_loss: Optional[float] = Field(
        None, description="Line 31: Net profit or (loss)"
    )

    @model_validator(mode="after")
    def validate_schedule_c(self) -> "ScheduleC":
        """Generic accounting reconciliation for Schedule C."""
        if self.gross_receipts_or_sales is None and self.returns_and_allowances is None:
            if self.gross_income is not None:
                if self.gross_income < 0 or (
                    self.total_expenses is not None
                    and abs(self.gross_income) == abs(self.total_expenses)
                ):
                    self.gross_income = None
            if self.cost_of_goods_sold is not None and self.cost_of_goods_sold < 0:
                self.cost_of_goods_sold = None

        if self.expenses:
            exp_dict = self.expenses.model_dump()
            items = [
                v for k, v in exp_dict.items()
                if isinstance(v, (int, float)) and k != "other_expenses_detail"
            ]
            calc_total = sum(items) if items else None

            if calc_total is not None and calc_total > 0:
                if self.total_expenses is None or abs(self.total_expenses - calc_total) > 1.0:
                    self.total_expenses = calc_total

            gross = self.gross_income if self.gross_income is not None else 0.0
            if self.total_expenses is not None:
                calc_net = gross - self.total_expenses
                if self.net_profit_or_loss is None or abs(self.net_profit_or_loss - calc_net) > 1.0:
                    self.net_profit_or_loss = calc_net

        return self


class RentalPropertyExpenses(BaseModel):
    advertising: Optional[float] = Field(None, description="Line 5: Advertising")
    auto_and_travel: Optional[float] = Field(
        None, description="Line 6: Auto and travel"
    )
    cleaning_and_maintenance: Optional[float] = Field(
        None, description="Line 7: Cleaning and maintenance"
    )
    commissions: Optional[float] = Field(None, description="Line 8: Commissions")
    insurance: Optional[float] = Field(None, description="Line 9: Insurance")
    legal_and_professional_fees: Optional[float] = Field(
        None, description="Line 10: Legal and other professional fees"
    )
    management_fees: Optional[float] = Field(
        None, description="Line 11: Management fees"
    )
    mortgage_interest_paid_to_banks: Optional[float] = Field(
        None, description="Line 12: Mortgage interest paid to banks"
    )
    other_interest: Optional[float] = Field(
        None, description="Line 13: Other interest"
    )
    repairs: Optional[float] = Field(None, description="Line 14: Repairs")
    supplies: Optional[float] = Field(None, description="Line 15: Supplies")
    taxes: Optional[float] = Field(None, description="Line 16: Taxes")
    utilities: Optional[float] = Field(None, description="Line 17: Utilities")
    depreciation_or_depletion: Optional[float] = Field(
        None, description="Line 18: Depreciation expense or depletion"
    )
    other_expenses_detail: List[OtherExpenseItem] = Field(
        default=[],
        description="Line 19: Itemized breakdown of other expenses for this property",
    )
    other_expenses_total: Optional[float] = Field(
        None, description="Line 19: Total of other expenses"
    )


class RentalProperty(BaseModel):
    property_letter: str = Field(
        description="Property indicator on schedule (e.g., 'A', 'B', 'C')"
    )
    property_address: Optional[str] = Field(
        None, description="Line 1a: Physical street address"
    )
    property_type: Optional[str] = Field(
        None,
        description="Line 1b: Property type description. Map numeric codes 1-8 into full text (1='Single Family Residence', 2='Multi-Family Residence', 3='Vacation/Short-Term Rental', 4='Commercial', 5='Land', 6='Royalties', 7='Self-Rental', 8='Other').",
    )
    rents_received: Optional[float] = Field(
        None, description="Line 3: Rents received"
    )
    expenses: Optional[RentalPropertyExpenses] = Field(
        None,
        description="Itemized expenses for this property",
    )
    total_expenses: Optional[float] = Field(
        None, description="Line 20: Total expenses"
    )
    net_rental_income_or_loss: Optional[float] = Field(
        None, description="Line 21 or Line 22: Net rental income or loss"
    )

    @model_validator(mode="after")
    def validate_totals(self) -> "RentalProperty":
        """Reconciles total_expenses and net_rental_income_or_loss if extracted incorrectly."""
        if self.expenses:
            expense_dict = self.expenses.model_dump()
            line_items = [
                v
                for k, v in expense_dict.items()
                if isinstance(v, (int, float)) and k != "other_expenses_detail"
            ]
            calculated_total = sum(line_items)

            if calculated_total > 0 and (
                self.total_expenses is None
                or abs(self.total_expenses - calculated_total) > 1.0
            ):
                self.total_expenses = calculated_total

            if self.rents_received is not None and self.total_expenses is not None:
                calc_net = self.rents_received - self.total_expenses
                if (
                    self.net_rental_income_or_loss is None
                    or abs(self.net_rental_income_or_loss - calc_net) > 1.0
                ):
                    self.net_rental_income_or_loss = calc_net

        return self


class ScheduleE(BaseModel):
    rental_properties: List[RentalProperty] = Field(
        default=[], description="Properties listed under Part I"
    )
    total_rental_real_estate_income_loss: Optional[float] = Field(
        None, description="Line 26: Total rental real estate income or (loss)"
    )


class ClientTaxReturnSummary(BaseModel):
    schedule_c_businesses: List[ScheduleC] = Field(
        default=[], description="List of Schedule C businesses"
    )
    schedule_e: Optional[ScheduleE] = Field(
        None, description="Schedule E summary"
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def validate_environment():
    """Ensure required Azure OpenAI and Document Intelligence environment variables exist."""
    missing = []
    if not os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"):
        missing.append("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    if not os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY"):
        missing.append("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        missing.append("AZURE_OPENAI_ENDPOINT")
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        missing.append("AZURE_OPENAI_API_KEY")

    if missing:
        sys.stderr.write(f"Error: Missing environment variables: {', '.join(missing)}\n")
        sys.exit(1)


def extract_markdown_pages(pdf_bytes: bytes) -> List[str]:
    """Uses Azure Document Intelligence SDK native page span offsets to slice markdown pages cleanly."""
    doc_client = DocumentIntelligenceClient(
        endpoint=os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"),
        credential=AzureKeyCredential(os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY")),
    )

    sys.stderr.write("Extracting layout via Azure Document Intelligence (Markdown mode)...\n")

    poller = doc_client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=pdf_bytes,
        output_content_format=DocumentContentFormat.MARKDOWN,
    )
    result = poller.result()
    full_markdown = result.content or ""

    pages_content = []
    if getattr(result, "pages", None):
        for page in result.pages:
            if getattr(page, "spans", None):
                page_text_parts = []
                for span in page.spans:
                    start = span.offset
                    end = span.offset + span.length
                    page_text_parts.append(full_markdown[start:end])
                page_str = "".join(page_text_parts).strip()
                if page_str:
                    pages_content.append(page_str)

    return pages_content if pages_content else [full_markdown]


# =============================================================================
# EXECUTION ROUTINE
# =============================================================================

def extract_tax_data(pdf_path: str):
    validate_environment()

    try:
        if pdf_path == "-":
            pdf_bytes = sys.stdin.buffer.read()
        else:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
    except Exception as e:
        sys.stderr.write(f"Error reading input PDF '{pdf_path}': {e}\n")
        sys.exit(1)

    if not pdf_bytes:
        sys.stderr.write("Empty PDF payload received. Exiting.\n")
        sys.exit(0)

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page_count = doc.page_count
        doc.close()
        if page_count == 0:
            sys.stderr.write("PDF contains 0 pages. Exiting.\n")
            sys.stdout.buffer.write(b"{}\n")
            sys.stdout.buffer.flush()
            sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Error opening PDF: {e}\n")
        sys.exit(1)

    # 1. Extract markdown layout pages
    try:
        pages = extract_markdown_pages(pdf_bytes)
        if not pages:
            sys.stderr.write("Document Intelligence returned empty layout text.\n")
            sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error in Document Intelligence analysis: {e}\n")
        sys.exit(1)

    # Format document with clear page delimiters
    formatted_document = ""
    for idx, page_text in enumerate(pages, start=1):
        formatted_document += f"\n\n=== ATTACHED PDF PAGE {idx} OF {len(pages)} MARKDOWN ===\n"
        formatted_document += page_text

    # 2. Process extracted Markdown via Azure OpenAI
    client = AzureOpenAI(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    )
    deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    prompt = f"""
    Extract all financial data and summaries from Schedule C and Schedule E across ALL attached pages in the Markdown text into the requested JSON schema.

    The Markdown text below contains {len(pages)} explicitly numbered page sections extracted directly via Azure Document Intelligence layout tables.

    Core Extraction Principles:

    1. Document & Year Filtering:
       - Verify that each schedule is for the 2025 tax year. Extract data ONLY from forms belonging to the 2025 tax year.
       - If a schedule belongs to a different tax year or is missing entirely, leave its corresponding schema section empty.

    2. Unbounded Multi-Page Schedule E Extraction (CRITICAL):
       - You MUST process EVERY page section from PAGE 1 OF {len(pages)} through PAGE {len(pages)} OF {len(pages)}.
       - Do NOT stop parsing early! Continuation pages often contain a single rental property column.
       - Extract EVERY property column across ALL {len(pages)} pages that has a street address or reported dollar amounts into the rental_properties array.
       - Use the letter printed on the page for `property_letter` ('A', 'B', or 'C'). Duplicate property letters across pages are completely expected and valid.

    3. Markdown Table Grid Reading:
       - Trace input values directly to their line item labels in the Markdown tables.
       - If an input field or table cell is unpopulated, output null. Never pull values horizontally across property columns or vertically across summary rows.

    4. Value Standardization & Anti-Hallucination Rules:
       - LABEL VS VALUE ISOLATION: Form line labels and index numbers are metadata ONLY. Never extract printed labels or line numbers as monetary values!
       - STRIP FORM PROMPT HEADERS: When extracting itemized descriptions for Line 19 / Line 27a, strip out pre-printed template form labels like "Other (list)". Keep only the user-entered text or statement reference (e.g., "See Stm 2").
       - STRICT SINGLE ASSIGNMENT: Each printed monetary amount maps to exactly ONE input cell.
       - INCOME VS NET SUMMARY SEPARATION: Reconcile top-level revenue headers strictly against reported gross sales. Never populate gross income with bottom-page net loss or total expense values.

    === START DOCUMENT INTELLIGENCE MARKDOWN ===
    {formatted_document}
    === END DOCUMENT INTELLIGENCE MARKDOWN ===
    """

    source_label = "stdin stream" if pdf_path == "-" else f"file '{pdf_path}'"
    sys.stderr.write(f"Parsing {len(pages)} layout page(s) for {source_label} via Azure OpenAI ({deployment_name})...\n")

    try:
        completion = client.beta.chat.completions.parse(
            model=deployment_name,
            messages=[{"role": "user", "content": prompt}],
            response_format=ClientTaxReturnSummary,
            temperature=0.0,
            timeout=90.0,
        )

        message = completion.choices[0].message

        if getattr(message, "refusal", None):
            sys.stderr.write(f"\n[Model Refusal]: {message.refusal}\n")
            sys.exit(1)

        summary = message.parsed

        # Post-filter: Keep every property item that has an address or active monetary entry
        if summary and summary.schedule_e and summary.schedule_e.rental_properties:
            summary.schedule_e.rental_properties = [
                prop
                for prop in summary.schedule_e.rental_properties
                if (prop.property_address or prop.rents_received is not None or prop.total_expenses is not None)
            ]

        if summary:
            json_bytes = summary.model_dump_json(indent=2).encode("utf-8") + b"\n"
            sys.stdout.buffer.write(json_bytes)
            sys.stdout.buffer.flush()
            sys.stderr.write("Extraction successful, filtered, and validated.\n")
        else:
            sys.stderr.write("Extraction returned empty response.\n")
            sys.exit(1)

    except APIError as e:
        sys.stderr.write(f"\n[Azure OpenAI API Error]: {e}\n")
        sys.exit(1)
    except ValidationError as e:
        sys.stderr.write(f"\n[Pydantic Validation Error]: {e}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"\n[Execution Error]: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract structured JSON from tax PDF using Azure Document Intelligence Layout + LLM."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="sanitized_schedules.pdf",
        help="Path to sanitized PDF (or '-' for stdin, default: sanitized_schedules.pdf)",
    )
    args = parser.parse_args()

    extract_tax_data(args.pdf_path)