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

FILTER = {
	"rcd1283bc3375488ab47e6fea7f84e1e9":
		{"text": "Did you purchase a new car in 2025 and finance it with a loan?",
		"select": ["rddfc13984b6b482fb9fa313f904d1580", "r5632cb4474d54645b24bbb16a5dd73f2"]},

	"r92da72a1acca42f19b9958e710704fa1":
		{"text": "Would you like to discuss tax considerations related to your employer provided benefit (use of flexible spending account, contribution to deductible 401(k) vs. Roth IRA etc.)?",
		"select": ["rddfc13984b6b482fb9fa313f904d1580", "r5632cb4474d54645b24bbb16a5dd73f2"]},

	"r84dfdaee7c6f428d82c8f2620478a12c":
		{"text": "Are you interested in a high-level discussion related to your estate, trust and wealth transfer plan?",
		"select": ["rddfc13984b6b482fb9fa313f904d1580", "r5632cb4474d54645b24bbb16a5dd73f2"]},

	"r55c3206d22d44e468d1a44ede301b9b8":
		{"text": "Have you already signed an Agreement with TARRANT ADVISORS for the preparation of your 2025 tax return?",
		"select": ["rddfc13984b6b482fb9fa313f904d1580", "r5632cb4474d54645b24bbb16a5dd73f2"]}
}

print("Content-Type: text/html\n")

if not (TENANT and TOKEN and USERID and FORMID):
	#print("Usage: TENANT= TOKEN= USERID= {} FORMID".format(sys.argv[0]), file=sys.stderr)
	exit()

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json" }
url = f"https://forms.office.com/formapi/api/{TENANT}/users/{USERID}/light/forms('{FORMID}')/responses?$expand=answers"

rsp = requests.get(url, headers=headers)
rsp = rsp.json()["value"]

tally = {}
for x in rsp:
	answers = json.loads(x["answers"])
	for y in answers:
		id = y["questionId"]
		z = y["answer1"]
		if id not in tally:
			tally[id] = []
		tally[id].append(z)

print("<html><head><title>Tax Questionnaire Report</title><link rel=\"stylesheet\" href=\"/css/style.min.css\"></link><body>")
print("<h1>Tax Questionnaire Report</h1>")
print(f"<h2>Total # of respondents: {len(rsp)}</h2>")
for k, v in FILTER.items():
	print("<h3>", "Clients who responsed 'yes' to: ", "<i>", v["text"], "</i>", "</h3>")
	print("<ol>")
	x = tally[k]
	n = 0
	for y in x:
		if y == "Yes":
			print("<li>", ', '.join([tally[z][n] for z in v["select"]]), "</li>")
		n += 1
	print("</ol>")
print("<br><br></body></html>")
