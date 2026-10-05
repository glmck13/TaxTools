#!/usr/bin/env python3

import argparse
import html
import json
import sys


def format_currency(val):
    if val is None:
        return ""
    return f"${val:,.2f}" if val >= 0 else f"(${abs(val):,.2f})"


def generate_html_organizer(json_input: str, output_html_path: str):
    try:
        if json_input == "-":
            # Read directly from sys.stdin without reconfiguring the buffer
            raw_input = sys.stdin.read()
            if not raw_input.strip():
                sys.stderr.write("No JSON received on stdin. Skipping HTML generation.\n")
                sys.exit(0)
            data = json.loads(raw_input)
        else:
            with open(json_input, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception as e:
        input_name = "stdin" if json_input == "-" else f"file '{json_input}'"
        sys.stderr.write(f"Error loading JSON from {input_name}: {e}\n")
        sys.exit(1)

    schedule_e = data.get("schedule_e") or {}
    properties = schedule_e.get("rental_properties") or []
    schedule_c_list = data.get("schedule_c_businesses") or []

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Tax Year Organizer & Input Sheet</title>
    <style>
        :root {{
            --primary: #1e3a8a;
            --border: #cbd5e1;
            --bg-alt: #f8fafc;
            --text: #0f172a;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: var(--text);
            margin: 0;
            padding: 20px;
            background-color: #f1f5f9;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: #ffffff;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        h1 {{
            color: var(--primary);
            margin-top: 0;
            border-bottom: 2px solid var(--primary);
            padding-bottom: 10px;
            font-size: 24px;
        }}
        h2 {{
            color: #334155;
            font-size: 18px;
            margin-top: 25px;
            margin-bottom: 10px;
            background: #e2e8f0;
            padding: 8px 12px;
            border-radius: 4px;
        }}
        .instruction-box {{
            background-color: #eff6ff;
            border-left: 4px solid #3b82f6;
            padding: 12px 16px;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        th, td {{
            border: 1px solid var(--border);
            padding: 8px 12px;
            text-align: left;
        }}
        th {{
            background-color: var(--bg-alt);
            font-weight: 600;
        }}
        .col-label {{ width: 45%; }}
        .col-prior {{ width: 25%; text-align: right; background-color: #fafafa; color: #475569; }}
        .col-input {{ width: 30%; }}
        
        input[type="text"], input[type="number"] {{
            width: 100%;
            padding: 6px 8px;
            box-sizing: border-box;
            border: 1px solid #94a3b8;
            border-radius: 4px;
            font-size: 14px;
        }}
        input[type="number"] {{ text-align: right; }}
        
        .section-subhead {{
            background: #f1f5f9;
            font-weight: bold;
            font-size: 12px;
            color: #334155;
        }}
        
        .page-break {{ page-break-before: always; }}

        /* Print Specific Styles */
        @media print {{
            body {{ background: #fff; padding: 0; }}
            .container {{ box-shadow: none; padding: 0; max-width: 100%; }}
            .no-print {{ display: none; }}
            input {{ border: 1px solid #cbd5e1 !important; background: transparent; }}
        }}
    </style>
</head>
<body>

<div class="container">
    <h1>Tax Data Input Organizer</h1>
    <div class="instruction-box">
        <strong>Instructions for Client:</strong> Please review your prior tax year financial figures in the center column. Enter your current tax year amounts in the right-hand column. You can fill this out directly on your computer and save/email the completed file, or print it out.
    </div>
"""

    # -------------------------------------------------------------------------
    # SCHEDULE E: RENTAL PROPERTIES
    # -------------------------------------------------------------------------
    if properties:
        html_content += "<h1>Schedule E - Rental Real Estate & Royalties</h1>"
        for i, prop in enumerate(properties):
            prop = prop or {}
            raw_addr = prop.get("property_address") or f"Property {prop.get('property_letter', i+1)}"
            addr = html.escape(str(raw_addr))
            p_type = html.escape(str(prop.get("property_type") or "N/A"))
            letter = html.escape(str(prop.get('property_letter', i+1)))
            rents = prop.get("rents_received")
            expenses = prop.get("expenses") or {}

            if i > 0 and i % 2 == 0:
                html_content += '<div class="page-break"></div>'

            html_content += f"""
            <h2>Property {letter}: {addr} ({p_type})</h2>
            <table>
                <thead>
                    <tr>
                        <th class="col-label">Category / Line Item</th>
                        <th class="col-prior">Prior Year Data</th>
                        <th class="col-input">Current Year Input</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Rents Received</strong></td>
                        <td class="col-prior"><strong>{format_currency(rents)}</strong></td>
                        <td><input type="number" step="0.01" name="prop_{i}_rents" placeholder="0.00"></td>
                    </tr>
                    <tr><td colspan="3" class="section-subhead">Standard Expenses</td></tr>
            """

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

            for key, label in expense_fields:
                val = expenses.get(key)
                html_content += f"""
                    <tr>
                        <td>{label}</td>
                        <td class="col-prior">{format_currency(val)}</td>
                        <td><input type="number" step="0.01" name="prop_{i}_{key}" placeholder="0.00"></td>
                    </tr>
                """

            # Breakout of Other Expenses
            other_detail = expenses.get("other_expenses_detail") or []
            other_total = expenses.get("other_expenses_total")

            html_content += """
                    <tr><td colspan="3" class="section-subhead">Other Expenses Breakdown</td></tr>
            """

            if other_detail:
                for idx, item in enumerate(other_detail):
                    desc = html.escape(str(item.get("description", "Other Expense")))
                    amt = item.get("amount")
                    html_content += f"""
                        <tr>
                            <td style="padding-left: 20px;">{desc}</td>
                            <td class="col-prior">{format_currency(amt)}</td>
                            <td><input type="number" step="0.01" name="prop_{i}_other_{idx}" placeholder="0.00"></td>
                        </tr>
                    """
            elif other_total is not None:
                html_content += f"""
                    <tr>
                        <td>Other Expenses Total</td>
                        <td class="col-prior">{format_currency(other_total)}</td>
                        <td><input type="number" step="0.01" name="prop_{i}_other_total" placeholder="0.00"></td>
                    </tr>
                """

            # Blank rows for client to add new categories
            for new_idx in range(2):
                html_content += f"""
                    <tr>
                        <td><input type="text" name="prop_{i}_new_other_desc_{new_idx}" placeholder="Add unlisted expense..."></td>
                        <td class="col-prior">-</td>
                        <td><input type="number" step="0.01" name="prop_{i}_new_other_val_{new_idx}" placeholder="0.00"></td>
                    </tr>
                """

            html_content += """
                </tbody>
            </table>
            """

    # -------------------------------------------------------------------------
    # SCHEDULE C: BUSINESSES
    # -------------------------------------------------------------------------
    if schedule_c_list:
        html_content += '<div class="page-break"></div>'
        html_content += "<h1>Schedule C - Profit or Loss From Business</h1>"

        for i, biz in enumerate(schedule_c_list):
            biz = biz or {}
            raw_b_name = biz.get("business_name") or f"Business {i+1}"
            b_name = html.escape(str(raw_b_name))
            b_code = html.escape(str(biz.get("business_code") or "N/A"))
            method = html.escape(str(biz.get("accounting_method") or "N/A"))
            gross = biz.get("gross_receipts_or_sales")
            expenses = biz.get("expenses") or {}

            html_content += f"""
            <h2>Business: {b_name} (Code: {b_code} | Method: {method})</h2>
            <table>
                <thead>
                    <tr>
                        <th class="col-label">Income & Expenses</th>
                        <th class="col-prior">Prior Year Data</th>
                        <th class="col-input">Current Year Input</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Gross Receipts or Sales</strong></td>
                        <td class="col-prior"><strong>{format_currency(gross)}</strong></td>
                        <td><input type="number" step="0.01" name="biz_{i}_gross" placeholder="0.00"></td>
                    </tr>
                    <tr><td colspan="3" class="section-subhead">Itemized Standard Expenses</td></tr>
            """

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

            for key, label in biz_expense_fields:
                val = expenses.get(key)
                html_content += f"""
                    <tr>
                        <td>{label}</td>
                        <td class="col-prior">{format_currency(val)}</td>
                        <td><input type="number" step="0.01" name="biz_{i}_{key}" placeholder="0.00"></td>
                    </tr>
                """

            # Breakout of Other Expenses
            other_detail = expenses.get("other_expenses_detail") or []
            other_total = expenses.get("other_expenses_total")

            html_content += """
                    <tr><td colspan="3" class="section-subhead">Other Expenses Breakdown (Part V / Line 27a)</td></tr>
            """

            if other_detail:
                for idx, item in enumerate(other_detail):
                    desc = html.escape(str(item.get("description", "Other Expense")))
                    amt = item.get("amount")
                    html_content += f"""
                        <tr>
                            <td style="padding-left: 20px;">{desc}</td>
                            <td class="col-prior">{format_currency(amt)}</td>
                            <td><input type="number" step="0.01" name="biz_{i}_other_{idx}" placeholder="0.00"></td>
                        </tr>
                    """
            elif other_total is not None:
                html_content += f"""
                    <tr>
                        <td>Other Expenses Total</td>
                        <td class="col-prior">{format_currency(other_total)}</td>
                        <td><input type="number" step="0.01" name="biz_{i}_other_total" placeholder="0.00"></td>
                    </tr>
                """

            # Blank rows for client to add new categories
            for new_idx in range(2):
                html_content += f"""
                    <tr>
                        <td><input type="text" name="biz_{i}_new_other_desc_{new_idx}" placeholder="Add unlisted expense..."></td>
                        <td class="col-prior">-</td>
                        <td><input type="number" step="0.01" name="biz_{i}_new_other_val_{new_idx}" placeholder="0.00"></td>
                    </tr>
                """

            html_content += """
                </tbody>
            </table>
            """

    html_content += """
</div>
</body>
</html>
"""

    if output_html_path == "-":
        # Write bytes directly to binary buffer to guarantee UTF-8 across operating systems and flush immediately
        sys.stdout.buffer.write(html_content.encode("utf-8"))
        sys.stdout.buffer.flush()
    else:
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        sys.stderr.write(f"Successfully generated organizer: '{output_html_path}'\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert tax JSON extraction into an interactive client organizer."
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        default="-",
        help="Path to input JSON file, or '-' / omit for stdin (default: -)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="tax_organizer.html",
        help="Path for output HTML organizer (or '-' for stdout, default: tax_organizer.html)",
    )
    args = parser.parse_args()

    generate_html_organizer(args.json_path, args.output)