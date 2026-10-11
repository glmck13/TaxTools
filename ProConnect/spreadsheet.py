#!/usr/bin/env python3
import io
import json
import sys
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill


def build_excel_organizer(json_path: str, output_xlsx_path: str):
    # 1. Load JSON safely from file or stdin
    try:
        if json_path == "-":
            raw_input = sys.stdin.read()
            if not raw_input.strip():
                sys.stderr.write("No JSON received on stdin. Skipping Excel generation.\n")
                sys.exit(0)
            data = json.loads(raw_input)
        else:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"Error loading JSON input: {e}\n")
        sys.exit(1)

    wb = openpyxl.Workbook()
    created_sheets = []

    # Styling definitions
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    subhead_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    subhead_font = Font(name="Calibri", size=10, bold=True, color="334155")
    title_font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
    bold_font = Font(name="Calibri", size=11, bold=True)
    currency_fmt = '$#,##0.00;($#,##0.00);"-"'

    def style_header_row(ws, row_idx, headers):
        for col_idx, text in enumerate(headers, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left")

    # -------------------------------------------------------------------------
    # SCHEDULE E: RENTAL REAL ESTATE
    # -------------------------------------------------------------------------
    schedule_e = data.get("schedule_e") or {}
    properties = schedule_e.get("rental_properties") or []

    if properties:
        ws_e = wb.create_sheet(title="Schedule E - Rental")
        created_sheets.append(ws_e)
        ws_e.views.sheetView[0].showGridLines = True
        
        row = 1
        ws_e.cell(row=row, column=1, value="Tax Year Input Organizer - Schedule E").font = title_font
        row += 2

        for i, prop in enumerate(properties):
            prop = prop or {}
            addr = prop.get("property_address") or f"Property {prop.get('property_letter', i+1)}"
            letter = prop.get("property_letter", chr(65 + i))
            p_type = prop.get("property_type") or "N/A"

            ws_e.cell(row=row, column=1, value=f"Property {letter}: {addr} ({p_type})").font = bold_font
            row += 1

            style_header_row(ws_e, row, ["Category / Line Item", "Prior Year Data", "Current Year Input"])
            row += 1

            # Rents Received
            ws_e.cell(row=row, column=1, value="Rents Received").font = bold_font
            c_prior = ws_e.cell(row=row, column=2, value=prop.get("rents_received"))
            c_prior.number_format = currency_fmt
            c_prior.font = bold_font
            c_curr = ws_e.cell(row=row, column=3)
            c_curr.number_format = currency_fmt
            row += 1

            # Expense Subheader
            ws_e.cell(row=row, column=1, value="Standard Itemized Expenses").font = subhead_font
            ws_e.cell(row=row, column=1).fill = subhead_fill
            ws_e.cell(row=row, column=2).fill = subhead_fill
            ws_e.cell(row=row, column=3).fill = subhead_fill
            row += 1

            expenses = prop.get("expenses") or {}
            expense_fields = [
                ("advertising", "Advertising"),
                ("auto_and_travel", "Auto and Travel"),
                ("cleaning_and_maintenance", "Cleaning and Maintenance"),
                ("commissions", "Commissions"),
                ("insurance", "Insurance"),
                ("legal_and_professional_fees", "Legal & Professional Fees"),
                ("management_fees", "Management Fees"),
                ("mortgage_interest_paid_to_banks", "Mortgage Interest (Banks)"),
                ("other_interest", "Other Interest"),
                ("repairs", "Repairs"),
                ("supplies", "Supplies"),
                ("taxes", "Taxes"),
                ("utilities", "Utilities"),
                ("depreciation_or_depletion", "Depreciation / Depletion"),
            ]

            start_exp_row = row
            for key, label in expense_fields:
                ws_e.cell(row=row, column=1, value=label)
                p_val = ws_e.cell(row=row, column=2, value=expenses.get(key))
                p_val.number_format = currency_fmt
                c_val = ws_e.cell(row=row, column=3)
                c_val.number_format = currency_fmt
                row += 1

            # Breakdown of Other Expenses
            other_detail = expenses.get("other_expenses_detail") or []
            if other_detail:
                for item in other_detail:
                    desc = item.get("description", "Other Expense")
                    amt = item.get("amount")
                    ws_e.cell(row=row, column=1, value=f"  {desc}")
                    p_val = ws_e.cell(row=row, column=2, value=amt)
                    p_val.number_format = currency_fmt
                    c_val = ws_e.cell(row=row, column=3)
                    c_val.number_format = currency_fmt
                    row += 1

            # Add 2 Blank Input Rows for New Categories
            for idx in range(2):
                ws_e.cell(row=row, column=1, value=f"  [Add New Expense #{idx+1}]")
                ws_e.cell(row=row, column=2, value="-").alignment = Alignment(horizontal="right")
                c_val = ws_e.cell(row=row, column=3)
                c_val.number_format = currency_fmt
                row += 1

            end_exp_row = row - 1

            # Total Expenses Row
            ws_e.cell(row=row, column=1, value="Total Expenses").font = bold_font
            t_prior = ws_e.cell(row=row, column=2, value=f"=SUM(B{start_exp_row}:B{end_exp_row})")
            t_prior.number_format = currency_fmt
            t_prior.font = bold_font

            t_curr = ws_e.cell(row=row, column=3, value=f"=SUM(C{start_exp_row}:C{end_exp_row})")
            t_curr.number_format = currency_fmt
            t_curr.font = bold_font
            row += 3

    # -------------------------------------------------------------------------
    # SCHEDULE C: BUSINESSES
    # -------------------------------------------------------------------------
    schedule_c_list = data.get("schedule_c_businesses") or []
    if schedule_c_list:
        ws_c = wb.create_sheet(title="Schedule C - Business")
        created_sheets.append(ws_c)
        ws_c.views.sheetView[0].showGridLines = True

        row = 1
        ws_c.cell(row=row, column=1, value="Tax Year Input Organizer - Schedule C").font = title_font
        row += 2

        for i, biz in enumerate(schedule_c_list):
            biz = biz or {}
            b_name = biz.get("business_name") or f"Business {i+1}"
            b_code = biz.get("business_code") or "N/A"
            method = biz.get("accounting_method") or "N/A"

            ws_c.cell(row=row, column=1, value=f"Business: {b_name} (Code: {b_code} | Method: {method})").font = bold_font
            row += 1

            style_header_row(ws_c, row, ["Income & Expenses", "Prior Year Data", "Current Year Input"])
            row += 1

            # Gross Receipts
            ws_c.cell(row=row, column=1, value="Gross Receipts or Sales").font = bold_font
            c_prior = ws_c.cell(row=row, column=2, value=biz.get("gross_receipts_or_sales"))
            c_prior.number_format = currency_fmt
            c_prior.font = bold_font
            c_curr = ws_c.cell(row=row, column=3)
            c_curr.number_format = currency_fmt
            row += 1

            # Itemized Expenses Subheader
            ws_c.cell(row=row, column=1, value="Itemized Expenses").font = subhead_font
            ws_c.cell(row=row, column=1).fill = subhead_fill
            ws_c.cell(row=row, column=2).fill = subhead_fill
            ws_c.cell(row=row, column=3).fill = subhead_fill
            row += 1

            expenses = biz.get("expenses") or {}
            biz_expense_fields = [
                ("advertising", "Advertising"),
                ("car_and_truck_expenses", "Car & Truck Expenses"),
                ("commissions_and_fees", "Commissions & Fees"),
                ("contract_labor", "Contract Labor"),
                ("depletion", "Depletion"),
                ("depreciation_and_sec_179", "Depreciation & Sec 179"),
                ("employee_benefit_programs", "Employee Benefit Programs"),
                ("insurance_other_than_health", "Insurance (Other than Health)"),
                ("interest_mortgage", "Mortgage Interest"),
                ("interest_other", "Other Interest"),
                ("legal_and_professional_services", "Legal & Professional Services"),
                ("office_expense", "Office Expense"),
                ("pension_and_profit_sharing_plans", "Pension & Profit Sharing"),
                ("rent_vehicles_machinery", "Rent (Vehicles/Machinery)"),
                ("rent_other_business_property", "Rent (Other Property)"),
                ("repairs_and_maintenance", "Repairs & Maintenance"),
                ("supplies", "Supplies"),
                ("taxes_and_licenses", "Taxes & Licenses"),
                ("travel", "Travel"),
                ("deductible_meals", "Deductible Meals"),
                ("utilities", "Utilities"),
                ("wages", "Wages"),
            ]

            start_exp_row = row
            for key, label in biz_expense_fields:
                ws_c.cell(row=row, column=1, value=label)
                p_val = ws_c.cell(row=row, column=2, value=expenses.get(key))
                p_val.number_format = currency_fmt
                c_val = ws_c.cell(row=row, column=3)
                c_val.number_format = currency_fmt
                row += 1

            # Breakdown of Other Expenses (Part V)
            other_detail = expenses.get("other_expenses_detail") or []
            if other_detail:
                for item in other_detail:
                    desc = item.get("description", "Other Expense")
                    amt = item.get("amount")
                    ws_c.cell(row=row, column=1, value=f"  {desc}")
                    p_val = ws_c.cell(row=row, column=2, value=amt)
                    p_val.number_format = currency_fmt
                    c_val = ws_c.cell(row=row, column=3)
                    c_val.number_format = currency_fmt
                    row += 1

            # Add 2 Blank Input Rows
            for idx in range(2):
                ws_c.cell(row=row, column=1, value=f"  [Add New Expense #{idx+1}]")
                ws_c.cell(row=row, column=2, value="-").alignment = Alignment(horizontal="right")
                c_val = ws_c.cell(row=row, column=3)
                c_val.number_format = currency_fmt
                row += 1

            end_exp_row = row - 1

            # Total Expenses Row
            ws_c.cell(row=row, column=1, value="Total Expenses").font = bold_font
            t_prior = ws_c.cell(row=row, column=2, value=f"=SUM(B{start_exp_row}:B{end_exp_row})")
            t_prior.number_format = currency_fmt
            t_prior.font = bold_font

            t_curr = ws_c.cell(row=row, column=3, value=f"=SUM(C{start_exp_row}:C{end_exp_row})")
            t_curr.number_format = currency_fmt
            t_curr.font = bold_font
            row += 3

    # -------------------------------------------------------------------------
    # WORKBOOK CLEANUP & ACTIVE SHEET ASSIGNMENT
    # -------------------------------------------------------------------------
    if created_sheets:
        if "Sheet" in wb.sheetnames:
            wb.remove(wb["Sheet"])
        wb.active = created_sheets[0]
    else:
        # Fallback if JSON has no Schedule C or E data
        ws_default = wb.active
        ws_default.title = "Tax Organizer"
        ws_default.cell(row=1, column=1, value="No Schedule C or Schedule E data found in input.").font = bold_font

    # Auto-adjust column widths across all sheets
    for ws in wb.worksheets:
        ws.column_dimensions["A"].width = 42
        ws.column_dimensions["B"].width = 22
        ws.column_dimensions["C"].width = 22

    # Output to File or Stdout
    if output_xlsx_path == "-":
        stream_buffer = io.BytesIO()
        wb.save(stream_buffer)
        sys.stdout.buffer.write(stream_buffer.getvalue())
        sys.stdout.buffer.flush()
    else:
        wb.save(output_xlsx_path)
        sys.stderr.write(f"Successfully generated Excel organizer: '{output_xlsx_path}'\n")


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "-"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "Tax_Organizer.xlsx"
    build_excel_organizer(json_path, output_path)