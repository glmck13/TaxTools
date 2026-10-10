#!/usr/bin/env python3

import argparse
import sys
import warnings

# Suppress Google GenAI SDK warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", module="google.*")

from typing import List, Optional
import pymupdf as fitz
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# =============================================================================
# PYDANTIC SCHEMA DEFINITIONS
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
# EXECUTION ROUTINE
# =============================================================================


def extract_tax_data(pdf_path: str):
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
        sys.stderr.write("No PDF stream received (no Schedule C/E pages matched). Skipping extraction.\n")
        sys.exit(0)

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count == 0:
            sys.stderr.write("PDF stream contains 0 pages. Skipping Gemini API call.\n")
            doc.close()
            sys.stdout.buffer.write(b"{}\n")
            sys.stdout.buffer.flush()
            sys.exit(0)
        doc.close()
    except Exception as e:
        sys.stderr.write(f"Invalid PDF stream received: {e}\n")
        sys.exit(1)

    client = genai.Client()
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    prompt = """
    Extract all financial data and summaries from Schedule C and Schedule E in the attached PDF.
    
    Rules:
    1. Tax Year Verification: Verify that each schedule (Schedule C and Schedule E) is for the 2025 tax year (check the header year, e.g., "2025" at the top of the form). Extract data ONLY from forms belonging to the 2025 tax year. If a schedule is for a year other than 2025, or is missing entirely, leave its corresponding schema field/list empty.
    2. Parse numeric values into floats. Convert parenthetical amounts like (1,250.00) or explicit negative signs like -534. into negative floats (e.g., -1250.0 or -534.0).
    3. Map all numeric codes, checkboxes, or abbreviations (such as Property Type codes 1-8 or Accounting Method indicators) into clear, human-readable text descriptions.
    4. If multiple pages belong to a single Schedule C business or Schedule E return (including continuation sheets for properties C, D, E, etc.), consolidate all related pages into single structured business/property entries.
    5. Line Item Precision:
       - On Schedule C Part II, carefully align line numbers with their exact horizontal rows. Line 22 is Supplies; Line 23 is Taxes and licenses. Do not swap adjacent row values.
       - On Schedule E Line 19, if text references a statement (e.g. 'See Stm 1'), include 'See Stm 1' as the description in 'other_expenses_detail' along with the listed amount.
    6. Do NOT extract empty or unpopulated property columns (e.g. columns labeled B or C on a continuation sheet that have no street address or financial entries). Only extract actual properties.
    7. For 'Other Expenses' on Schedule C (Line 27a / Part V) and Schedule E (Line 19), extract every itemized description and amount into 'other_expenses_detail', and extract the sum into 'other_expenses_total'.
    8. If a field is blank, zero, or covered by a black redaction block on the form, return null.
    """

    source_label = "stdin stream" if pdf_path == "-" else f"file '{pdf_path}'"
    sys.stderr.write(f"Processing {source_label} via Gemini API...\n")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ClientTaxReturnSummary,
            temperature=0.0,
            seed=42,  # Enforces deterministic model decoding across identical requests
        ),
    )

    try:
        summary = ClientTaxReturnSummary.model_validate_json(response.text)

        if summary.schedule_e and summary.schedule_e.rental_properties:
            summary.schedule_e.rental_properties = [
                prop
                for prop in summary.schedule_e.rental_properties
                if any([
                    prop.property_address is not None,
                    prop.rents_received is not None,
                    prop.total_expenses is not None,
                    prop.expenses and prop.expenses.other_expenses_total is not None,
                    bool(prop.expenses and prop.expenses.other_expenses_detail)
                ])
            ]

        json_bytes = summary.model_dump_json(indent=2).encode("utf-8") + b"\n"
        sys.stdout.buffer.write(json_bytes)
        sys.stdout.buffer.flush()

        sys.stderr.write("Extraction successful, filtered, and validated.\n")

    except Exception as e:
        sys.stderr.write(f"\n[Validation Error]: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract structured JSON from sanitized tax PDF."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="sanitized_schedules.pdf",
        help="Path to sanitized PDF (or '-' for stdin, default: sanitized_schedules.pdf)",
    )
    args = parser.parse_args()

    extract_tax_data(args.pdf_path)
