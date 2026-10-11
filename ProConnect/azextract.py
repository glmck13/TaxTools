#!/usr/bin/env python3

import argparse
import base64
import os
import sys
import warnings
from typing import List, Optional

import pymupdf as fitz
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

            # Sum standard line items 5-18 + Line 19 (other_expenses_total)
            line_items = [
                v
                for k, v in expense_dict.items()
                if isinstance(v, (int, float)) and k != "other_expenses_detail"
            ]
            calculated_total = sum(line_items)

            # Recalculate total_expenses if missing or if model drifted by > $1.00
            if calculated_total > 0 and (
                self.total_expenses is None
                or abs(self.total_expenses - calculated_total) > 1.0
            ):
                self.total_expenses = calculated_total

            # Reconcile net_rental_income_or_loss strictly against reported rents
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
    """Ensure required Azure OpenAI environment variables exist."""
    missing = []
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        missing.append("AZURE_OPENAI_ENDPOINT")
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        missing.append("AZURE_OPENAI_API_KEY")
    if missing:
        sys.stderr.write(
            f"Error: Missing environment variables: {', '.join(missing)}\n"
        )
        sys.stderr.write("Please run:\n")
        sys.stderr.write(
            '  export AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com/"\n'
        )
        sys.stderr.write('  export AZURE_OPENAI_API_KEY="<key>"\n')
        sys.exit(1)


def extract_pdf_page_payloads(pdf_bytes: bytes):
    """Extracts 300 DPI base64 image AND clean text blocks per PDF page."""
    pages = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for idx, page in enumerate(doc):
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            b64_str = base64.b64encode(img_bytes).decode("utf-8")

            text_blocks = page.get_text("blocks")
            clean_text = "\n".join([b[4].strip() for b in text_blocks if b[4].strip()])

            pages.append(
                {
                    "page_num": idx + 1,
                    "b64_img": b64_str,
                    "text": clean_text,
                }
            )
    return pages


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
        sys.stderr.write(f"Error reading input PDF stream/file '{pdf_path}': {e}\n")
        sys.exit(1)

    if not pdf_bytes:
        sys.stderr.write("No PDF stream received. Skipping extraction.\n")
        sys.exit(0)

    try:
        pages = extract_pdf_page_payloads(pdf_bytes)
        if not pages:
            sys.stderr.write("PDF contains 0 pages. Skipping Azure API call.\n")
            sys.stdout.buffer.write(b"{}\n")
            sys.stdout.buffer.flush()
            sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"Error processing PDF content: {e}\n")
        sys.exit(1)

    client = AzureOpenAI(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    )
    deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    prompt = """
    Extract all financial data and summaries from Schedule C and Schedule E in the attached PDF pages into the requested JSON schema.

    Core Extraction Principles:

    1. Document & Year Filtering:
       - Verify that each schedule is for the 2025 tax year (check header years). Extract data ONLY from forms belonging to the 2025 tax year.
       - If a schedule belongs to a different tax year or is missing entirely, leave its corresponding schema section empty.

    2. Multi-Page Continuation:
       - Process ALL attached PDF pages sequentially. If an entity spans multiple continuation sheets or extra columns, aggregate all pages into single structured business/property entries.
       - Do NOT stop parsing after the first page.

    3. Spatial Grid Alignment & Software Layout (Intuit ProConnect):
       - The document features computerized, right-aligned text generated by Intuit ProConnect tax software inside standard form grids.
       - Treat tabular structures as strict 2D grids. Ensure values map precisely to their vertical column and horizontal row boundaries.
       - Never shift column values horizontally across adjacent entity columns, even if a leading or intermediate cell is empty.
       - Maintain strict row-by-row mapping. Do not shift values upward into empty rows or adjacent blank cells.

    4. Value Standardization & Data Integrity:
       - Convert all monetary amounts into numeric floats. Treat parenthetical figures, e.g., (1,250.00), or explicit negative signs, e.g., -534.00, as negative values.
       - Map numeric codes, indicators, or abbreviations into human-readable text strings as requested by the schema.
       - For itemized expense details and line references (including ProConnect statement cross-references like "See Stm 1"), extract both the exact descriptive text and the associated monetary value into the itemized array, storing the column total in the total field.
       - If a cell or field is unpopulated, zero, or redacted, return null rather than guessing or shifting adjacent data.
       - Ignore completely unpopulated columns or placeholder entries that contain no active financial entries or identifiers.
    """

    source_label = "stdin stream" if pdf_path == "-" else f"file '{pdf_path}'"
    sys.stderr.write(f"Processing {source_label} ({len(pages)} pages) via Azure OpenAI ({deployment_name})...\n")

    content_payload = [{"type": "text", "text": prompt}]

    for page in pages:
        p_num = page["page_num"]
        p_text = page["text"]
        b64_img = page["b64_img"]

        content_payload.append(
            {
                "type": "text",
                "text": f"\n=== PAGE {p_num} OF {len(pages)} LAYOUT TEXT ===\n{p_text}\n",
            }
        )
        content_payload.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64_img}",
                    "detail": "high",
                },
            }
        )

    try:
        completion = client.beta.chat.completions.parse(
            model=deployment_name,
            messages=[{"role": "user", "content": content_payload}],
            response_format=ClientTaxReturnSummary,
            temperature=0.0,
        )

        message = completion.choices[0].message

        if getattr(message, "refusal", None):
            sys.stderr.write(f"\n[Model Refusal]: {message.refusal}\n")
            sys.exit(1)

        summary = message.parsed

        if summary and summary.schedule_e and summary.schedule_e.rental_properties:
            summary.schedule_e.rental_properties = [
                prop
                for prop in summary.schedule_e.rental_properties
                if any(
                    [
                        prop.property_address is not None,
                        prop.rents_received is not None,
                        prop.total_expenses is not None,
                        prop.expenses
                        and prop.expenses.other_expenses_total is not None,
                        bool(prop.expenses and prop.expenses.other_expenses_detail),
                    ]
                )
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
        description="Extract structured JSON from sanitized tax PDF using Azure OpenAI."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="sanitized_schedules.pdf",
        help="Path to sanitized PDF (or '-' for stdin, default: sanitized_schedules.pdf)",
    )
    args = parser.parse_args()

    extract_tax_data(args.pdf_path)