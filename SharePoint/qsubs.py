#!/usr/bin/env python3

import sys, os
import requests
import json

FORMID = "3ldY-25hvUW4QYupAGZf1U5xmw6h3vpJrX1t2OAg0wFUOU5PNEtERTRKQUlWQ1pBMjBBT0YySVo3Sy4u"
QNAME = "rddfc13984b6b482fb9fa313f904d1580"
QEMAIL =  "r5632cb4474d54645b24bbb16a5dd73f2"

TOKEN = os.getenv("TOKEN")
TENANT = os.getenv("TENANT")
USERID = os.getenv("USERID")

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json" }
url = f"https://forms.office.com/formapi/api/{TENANT}/users/{USERID}/light/forms('{FORMID}')/responses?$expand=answers"

rsp = requests.get(url, headers=headers)
rsp = rsp.json()["value"]

names = []
emails = []
for x in rsp:
	answers = json.loads(x["answers"])
	for y in answers:
		id = y["questionId"]
		txt = y["answer1"]
		if id == QNAME:
			names.append(txt)
		elif id == QEMAIL:
			emails.append(txt)

print('\n'.join(emails))
