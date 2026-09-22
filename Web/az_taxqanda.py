#!/usr/bin/env python3

import sys, os
import json
import requests
import subprocess

AZ_DIR = os.environ.get("AZ_DIR", "")
os.environ['AZURE_CONFIG_DIR'] = AZ_DIR
os.environ['HOME'] = AZ_DIR

TENANT = subprocess.run(
        ['az', 'account', 'show', '--query', 'tenantId', '-o', 'tsv'],
        capture_output=True, text=True, check=False, timeout=5).stdout[:-1]

TOKEN = subprocess.run(
        ['az', 'account', 'get-access-token', '--resource', 'https://forms.office.com', '--query', 'accessToken', '--output', 'tsv'],
        capture_output=True, text=True, check=False, timeout=5).stdout[:-1]

USERID = subprocess.run(
        ['az', 'ad', 'signed-in-user', 'show', '--query', 'id', '-o', 'tsv'],
        capture_output=True, text=True, check=False, timeout=5).stdout[:-1]

FORMID = "3ldY-25hvUW4QYupAGZf1U5xmw6h3vpJrX1t2OAg0wFUOU5PNEtERTRKQUlWQ1pBMjBBT0YySVo3Sy4u"

print("Content-Type: text/html\n")

if not (TENANT and TOKEN and USERID and FORMID):
    exit()

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json" }

# Fetch Questions
url = f"https://forms.office.com/formapi/api/{TENANT}/users/{USERID}/light/forms('{FORMID}')?$expand=questions"
rsp = requests.get(url, headers=headers).json()["questions"]

q_and_a = {}
for x in rsp:
    q_and_a[x["id"]] = {"id": x["id"], "order": x["order"], "question": x["title"].strip(), "answers": []}

# Fetch Responses
url = f"https://forms.office.com/formapi/api/{TENANT}/users/{USERID}/light/forms('{FORMID}')/responses?$expand=answers"
rsp = requests.get(url, headers=headers).json()["value"]
for x in rsp:
    for y in json.loads(x["answers"]):
        qid = y["questionId"]
        if qid in q_and_a:
            q_and_a[qid]["answers"].append(y.get("answer1", ""))

# Convert to list and sort strictly chronologically by form order
q_list = list(q_and_a.values())
q_list.sort(key=lambda x: x["order"])

# Exact full-text prompt dictionary map (normalized to lowercase)
EXACT_QUESTION_MAP = {
    "your name:": "client_name",
    "your email address:": "email",
    "were you married as of 12/31/25?": "married",
    "spouse's name:": "spouse_name",
    "have you already signed an agreement with tarrant advisors for the preparation of your 2025 tax return?": "signed_agreement",
    "taxpayer has read the agreement and answers yes to this question to accept the scope of services, fee arrangement and terms. (your 2025 tax agreement can be found in your shared folder).": "taxpayer_terms",
    "spouse has read the agreement and answers yes to this question to accept the scope of services, fee arrangement and terms. (your 2025 tax agreement can be found in your shared folder).": "spouse_terms",
    "do you want tarrant advisors to process your taxes due or refund using your bank account information?": "use_bank_dd",
    "did your bank account information change within the last twelve months, or is this the first time tarrant advisors is preparing your return? if so, please provide bank account information for direct deposit of your refunds or direct payment of your taxes.": "bank_changed",
    "bank name:": "bank_name",
    "account type:": "account_type",
    "routing number:": "routing_num",
    "account number:": "account_num",
    "is your contact information the same as last year?": "contact_same",
    "is this the first year tarrant advisors has prepared your return?": "first_year_client",
    "enter your birthdate(s) and the birthdate(s) of your dependents:": "birthdates",
    "have there been any changes in dependents from last year? if so, please provide updated information.": "dep_changes",
    "did you have any children under age 19 or full-time students under age 24 at the end of 2025, with interest and dividend income in excess of $1,300, or total investment income in excess of $2,600?": "kiddie_tax",
    "did you receive irs document form 1095-a (health insurance marketplace statement)? if so, please upload the form to your shared folder.": "form_1095a",
    "did you receive irs document form 1095-a (health insurance marketplace statement)? if so, please upload the form to your shared folder.": "form_1095a",
    "do you have a high-deductible medical plan?": "high_deductible",
    "did you have any significant difference from your 2024 tax situation (new sources of income or expenses, significant increases to expense or income, non-routine transactions, sale of residence or rental property for discussion)? if so, please explain.": "sit_diff_flag",
    "did you purchase a new car in 2025 and finance it with a loan? if so, please provide the vin and upload the annual interest statement to your shared folder.": "new_car_flag",
    "vin (if available):": "vin_number",
    "did you move, purchase, sell, or refinance your principal home or second home, or did you take a home equity loan?": "home_buy_sell_refi",
    "did you make any residential energy-efficient improvements or purchases involving solar, wind, geothermal or fuel cell energy sources?": "energy_improvements",
    "did you make a contribution to a non employer retirement plan (ira, sep, roth ira, etc.)?": "non_employer_ira",
    "did you transfer or rollover any amount from one retirement plan to another retirement plan?": "retirement_rollover",
    "did you convert part of all of your sep or ira to a roth ira in 2025?": "roth_conversion",
    "did you make a contribution(s) to a qualified tuition program (sec.529 plan)?": "sec_529_flag",
    "state and amount of contribution:": "sec_529_details",
    "did you pay estimated taxes for 2025? if so, please list below.": "est_tax_flag",
    "enter the type (federal/state), date, and amount for each payment:": "est_tax_details",
    "do you expect your 2026 taxable income to be different from 2025? if so, please explain.": "income_diff_2026_flag",
    "are you interested in a high-level discussion related to your estate, trust and wealth transfer plan?": "estate_wealth_talk",
    "do you have the desire to make significant charitable contributions in 2026 or future years?": "future_charity_intent",
    "would you like to discuss tax considerations related to your employer provided benefit (use of flexible spending account, contribution to deductible 401(k) vs. roth ira etc.)?": "employer_benefit_talk",
    "does your compensation include overtime or tips?": "overtime_tips",
    "did you make charitable contributions directly from your ira?": "qcd_charity_ira",
    "do you want to allocate $3 to the presidential election campaign fund?": "pres_fund_taxpayer",
    "does your spouse want to allocate $3 to the presidential election campaign fund?": "pres_fund_spouse",
    "may the irs discuss your tax return with tarrant advisors?": "irs_auth",
    "did you have an interest in or signature or other authority over a financial account in a foreign country or have any interest in a foreign trust or foreign asset?": "foreign_accounts",
    "was your home rented out or used for business?": "rental_business_home",
    "did you engage the services of any household employees in excess of $2,600?": "household_employees",
    "did you or your spouse (as applicable) make any gifts to an individual that total more than $19,000, or make any gifts to a trust?": "gifts_over_19k",
    "how would you like us to handle your final tax package?": "final_package_pref",
    "please provide any additional information or comments related to your 2025 tax situation.": "additional_comments"
}

def assign_exact_key(q_text, prev_text):
    clean_q = " ".join(q_text.strip().split()).lower()
    clean_p = " ".join(prev_text.strip().split()).lower() if prev_text else ""
    
    # Case-insensitive full text lookup
    if clean_q in EXACT_QUESTION_MAP:
        return EXACT_QUESTION_MAP[clean_q]
    
    # Context-based lookup for repeating "Updated Information:" prompts
    if clean_q.startswith("updated information"):
        if "contact information" in clean_p or "dependents" in clean_p:
            return "updated_contact_info"
        if "significant difference" in clean_p:
            return "updated_sit_diff_info"
        if "2026 taxable income" in clean_p:
            return "updated_2026_income_info"
        return "updated_info_generic"

    return "unknown_question"

prev_q = ""
for item in q_list:
    item["key"] = assign_exact_key(item["question"], prev_q)
    prev_q = item["question"]

html = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tax Q&A One-Page Summary</title>
    <style>
        :root {
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --primary: #0f172a;
            --accent: #1e3a8a;
            --border: #cbd5e1;
            --text-main: #1e293b;
            --text-muted: #64748b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            padding: 8px;
            font-size: 10px;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--card-bg);
            padding: 5px 10px;
            border-radius: 4px;
            border: 1px solid var(--border);
            margin-bottom: 6px;
        }
        h2 { font-size: 12px; color: var(--primary); font-weight: 700; }
        .controls { display: flex; align-items: center; gap: 8px; }
        select {
            padding: 2px 6px;
            font-size: 10px;
            border: 1px solid var(--border);
            border-radius: 4px;
            font-weight: 600;
            background-color: #f1f5f9;
        }
        .btn-print {
            background-color: #2563eb;
            color: white;
            border: none;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-print:hover { background-color: #1d4ed8; }
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
        }
        .card {
            background: var(--card-bg);
            border-radius: 4px;
            padding: 6px;
            border: 1px solid var(--border);
        }
        .card h3 {
            font-size: 9.5px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--accent);
            border-bottom: 1.5px solid var(--accent);
            padding-bottom: 2px;
            margin-bottom: 4px;
            font-weight: 700;
        }
        .item-row {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding: 2px 0;
            border-bottom: 1px dashed #e2e8f0;
        }
        .item-row:last-child { border-bottom: none; }
        .label {
            font-weight: 500;
            color: var(--text-main);
            max-width: 55%;
            line-height: 1.15;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .value {
            font-weight: 600;
            color: #0f172a;
            text-align: right;
            max-width: 45%;
            word-break: break-word;
            white-space: pre-line;
            line-height: 1.15;
        }
        .badge {
            padding: 1px 4px;
            border-radius: 3px;
            font-size: 8.5px;
            font-weight: 700;
            display: inline-block;
        }
        .badge-yes { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
        .badge-no { color: var(--text-muted); font-weight: 400; }
        .col-span-2 { grid-column: span 2; }

        @media print {
            @page { size: letter portrait; margin: 0.25in; }
            body { background: white; padding: 0; font-size: 9px; }
            .no-print { display: none !important; }
            header { border: none; padding: 0 0 4px 0; margin-bottom: 4px; border-bottom: 2px solid #000; }
            .dashboard-grid { gap: 5px; }
            .card { border: 1px solid #94a3b8; padding: 5px; page-break-inside: avoid; }
            .badge-yes { background: #f0fdf4 !important; color: #000 !important; border: 1px solid #000; }
            .badge-no { color: #555 !important; }
        }
    </style>
</head>
<body>

    <header>
        <h2 id="header-title">Tax Q&A Summary</h2>
        <div class="controls no-print">
            <div id="master-container"></div>
            <button class="btn-print" onclick="window.print()">Print Summary</button>
        </div>
    </header>

    <div class="dashboard-grid">
        <div class="card">
            <h3>1. Engagement & Identity</h3>
            <div id="group-client"></div>
        </div>
        <div class="card">
            <h3>2. Banking & Direct Deposit</h3>
            <div id="group-banking"></div>
        </div>
        <div class="card">
            <h3>3. Family & Dependents</h3>
            <div id="group-family"></div>
        </div>
        <div class="card col-span-2">
            <h3>4. Income, Deductions & Real Estate</h3>
            <div id="group-tax-info" style="display: grid; grid-template-columns: 1fr 1fr; gap: 0 8px;"></div>
        </div>
        <div class="card">
            <h3>5. Compliance & Admin</h3>
            <div id="group-compliance"></div>
        </div>
    </div>

    <script>
'''

html += "const q_and_a = " + json.dumps(q_list) + ";"

html += r'''
    function getValByKey(keyName, clientIdx) {
        const matches = q_and_a.filter(q => q.key === keyName);
        for (let item of matches) {
            if (item.answers && item.answers[clientIdx]) {
                const val = item.answers[clientIdx].trim();
                if (val !== "" && val !== "—") return val;
            }
        }
        return "—";
    }

    function formatVal(val) {
        if (val === "—" || !val) return `<span class="value" style="color:var(--text-muted);">—</span>`;
        if (val.toLowerCase() === "yes") return `<span class="badge badge-yes">Yes</span>`;
        if (val.toLowerCase() === "no") return `<span class="badge badge-no">No</span>`;
        return `<span class="value">${val}</span>`;
    }

    function renderRow(label, value) {
        return `
            <div class="item-row">
                <span class="label" title="${label}">${label}</span>
                ${formatVal(value)}
            </div>
        `;
    }

    function init() {
        const masterContainer = document.getElementById('master-container');

        const nameObj = q_and_a.find(q => q.key === "client_name") || q_and_a[0];
        const masterData = nameObj.answers.map((text, index) => {
            return { text: text || `Respondent #${index + 1}`, originalIndex: index };
        });

        masterData.sort((a, b) => a.text.localeCompare(b.text));

        masterContainer.innerHTML = `
            <select id="master-select" onchange="updateDashboard(this.value)">
                <option value="" disabled selected>Select Taxpayer...</option>
                ${masterData.map(item => `
                    <option value="${item.originalIndex}">${item.text}</option>
                `).join('')}
            </select>
        `;
    }

    function updateDashboard(idx) {
        const nameObj = q_and_a.find(q => q.key === "client_name");
        const clientName = (nameObj && nameObj.answers[idx]) ? nameObj.answers[idx] : "Taxpayer";
        document.getElementById('header-title').textContent = `Tax Q&A Summary: ${clientName}`;

        // Group 1: Engagement & Profile
        document.getElementById('group-client').innerHTML = 
            renderRow("Email Address", getValByKey("email", idx)) +
            renderRow("Signed Scope Agreement?", getValByKey("signed_agreement", idx)) +
            renderRow("Taxpayer Terms Accepted?", getValByKey("taxpayer_terms", idx)) +
            renderRow("Spouse Terms Accepted?", getValByKey("spouse_terms", idx)) +
            renderRow("Final Package Option", getValByKey("final_package_pref", idx));

        // Group 2: Banking & Direct Deposit
        document.getElementById('group-banking').innerHTML = 
            renderRow("Process Direct Deposit?", getValByKey("use_bank_dd", idx)) +
            renderRow("Bank Info Changed?", getValByKey("bank_changed", idx)) +
            renderRow("Bank Name", getValByKey("bank_name", idx)) +
            renderRow("Account Type", getValByKey("account_type", idx)) +
            renderRow("Routing Number", getValByKey("routing_num", idx)) +
            renderRow("Account Number", getValByKey("account_num", idx)) +
            renderRow("Paid Estimated Taxes?", getValByKey("est_tax_flag", idx)) +
            renderRow("Est. Payment Breakdown", getValByKey("est_tax_details", idx)) +
            renderRow("2026 Income Diff Expected?", getValByKey("income_diff_2026_flag", idx)) +
            renderRow("2026 Income Details", getValByKey("updated_2026_income_info", idx));

        // Group 3: Family & Dependents
        document.getElementById('group-family').innerHTML = 
            renderRow("Married as of 12/31/25?", getValByKey("married", idx)) +
            renderRow("Spouse's Name", getValByKey("spouse_name", idx)) +
            renderRow("Same Contact Info?", getValByKey("contact_same", idx)) +
            renderRow("Updated Contact Details", getValByKey("updated_contact_info", idx)) +
            renderRow("First Year with Firm?", getValByKey("first_year_client", idx)) +
            renderRow("Birthdates (Self/Dep)", getValByKey("birthdates", idx)) +
            renderRow("Kiddie Tax Qualifier?", getValByKey("kiddie_tax", idx));

        // Group 4: Income, Deductions & Real Estate
        document.getElementById('group-tax-info').innerHTML = `
            <div>
                ${renderRow("2024 vs 2025 Sit. Diff?", getValByKey("sit_diff_flag", idx))}
                ${renderRow("Sit. Difference Details", getValByKey("updated_sit_diff_info", idx))}
                ${renderRow("Form 1095-A (Health)?", getValByKey("form_1095a", idx))}
                ${renderRow("High-Deductible Plan?", getValByKey("high_deductible", idx))}
                ${renderRow("New Car Financed?", getValByKey("new_car_flag", idx))}
                ${renderRow("VIN Number", getValByKey("vin_number", idx))}
                ${renderRow("Home Buy/Sell/Refi?", getValByKey("home_buy_sell_refi", idx))}
                ${renderRow("Energy Improvements?", getValByKey("energy_improvements", idx))}
            </div>
            <div>
                ${renderRow("Non-Employer IRA/SEP?", getValByKey("non_employer_ira", idx))}
                ${renderRow("Retirement Rollover?", getValByKey("retirement_rollover", idx))}
                ${renderRow("Roth Conversion in 2025?", getValByKey("roth_conversion", idx))}
                ${renderRow("Sec 529 Tuition Plan?", getValByKey("sec_529_flag", idx))}
                ${renderRow("529 Contribution Details", getValByKey("sec_529_details", idx))}
                ${renderRow("Direct IRA Charity (QCD)?", getValByKey("qcd_charity_ira", idx))}
                ${renderRow("Rental / Business Use Home?", getValByKey("rental_business_home", idx))}
            </div>
        `;

        // Group 5: Compliance & Admin Flags
        document.getElementById('group-compliance').innerHTML = 
            renderRow("Foreign Accounts/Assets?", getValByKey("foreign_accounts", idx)) +
            renderRow("Household Employee >$2.6k?", getValByKey("household_employees", idx)) +
            renderRow("Gifts >$19k or Trust?", getValByKey("gifts_over_19k", idx)) +
            renderRow("Estate / Wealth Discussion?", getValByKey("estate_wealth_talk", idx)) +
            renderRow("Future Charity Intent?", getValByKey("future_charity_intent", idx)) +
            renderRow("Employer Benefit Talk?", getValByKey("employer_benefit_talk", idx)) +
            renderRow("Overtime or Tips Income?", getValByKey("overtime_tips", idx)) +
            renderRow("Taxpayer Pres. Fund ($3)?", getValByKey("pres_fund_taxpayer", idx)) +
            renderRow("Spouse Pres. Fund ($3)?", getValByKey("pres_fund_spouse", idx)) +
            renderRow("IRS Advisor Authorization?", getValByKey("irs_auth", idx)) +
            renderRow("Additional Notes", getValByKey("additional_comments", idx));
    }

    init();
    </script>
</body>
</html>
'''

print(html)