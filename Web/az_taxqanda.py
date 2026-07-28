#!/usr/bin/env python3

import sys, os
import json
import requests
import subprocess

AZ_DIR = '/var/www/azure'
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
	#print("Usage: TENANT= TOKEN= USERID= {} FORMID".format(sys.argv[0]), file=sys.stderr)
	exit()

headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json" }

q_and_a = {}
url = f"https://forms.office.com/formapi/api/{TENANT}/users/{USERID}/light/forms('{FORMID}')?$expand=questions"
rsp = requests.get(url, headers=headers)
rsp = rsp.json()["questions"]
for x in rsp:
	q_and_a[x["id"]] = {"order" : x["order"], "question" : x["title"], "answers" : []}

url = f"https://forms.office.com/formapi/api/{TENANT}/users/{USERID}/light/forms('{FORMID}')/responses?$expand=answers"
rsp = requests.get(url, headers=headers)
rsp = rsp.json()["value"]
for x in rsp:
	for y in json.loads(x["answers"]):
		qid = y["questionId"]
		if qid in q_and_a:
			q_and_a[qid]["answers"].append(y["answer1"])

#q_and_a = [x for x in q_and_a.values()].sort(key=lambda x: x['order'])
q_and_a = [x for x in q_and_a.values()]
q_and_a.sort(key=lambda x: x["order"])

html = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dynamic Q&A Selector</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; background-color: #f9f9f9; width: 1000px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 500px; }
        .field-group { margin-bottom: 15px; }
        label { display: block; font-weight: bold; color: #333; margin-bottom: 5px; }
        select, .output-box { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        .output-box { background-color: #e9ecef; color: #495057; min-height: 38px; display: flex; align-items: center; }
        h2 { color: #2c3e50; }
    </style>
</head>
<body>
'''

html += f'<h2>Tax Q&A Responses: {len(q_and_a[0]["answers"])}</h2>'

html += r'''

    <div id="master-container" class="field-group"></div>

    <div id="dependent-fields"></div>

    <script>
        // 1. Your Data (Represented as a JS Array of Objects)
'''

html += "const q_and_a = " + json.dumps(q_and_a) + ";"

html += r'''

    function init() {
        const masterContainer = document.getElementById('master-container');
        const dependentContainer = document.getElementById('dependent-fields');

        // 1. Create a "Map" of the first entry's answers with their original indices
        const masterData = q_and_a[0].answers.map((text, index) => {
            return { text: text, originalIndex: index };
        });

        // 2. Sort the map alphabetically by text
        masterData.sort((a, b) => a.text.localeCompare(b.text));

        // 3. Render the Sorted Select
        masterContainer.innerHTML = `
            <label>${q_and_a[0].question}</label>
            <select id="master-select" onchange="updateFields(this.value)">
                <option value="" disabled selected>Select an option...</option>
                ${masterData.map(item => `
                    <option value="${item.originalIndex}">${item.text}</option>
                `).join('')}
            </select>
        `;

        // 4. Render placeholders for subsequent fields
        for (let i = 1; i < q_and_a.length; i++) {
            const div = document.createElement('div');
            div.innerHTML = `
                <label>${q_and_a[i].question}</label>
                <span id="field-${i}" class="output-box">—</span>
            `;
            dependentContainer.appendChild(div);
        }
    }

    function updateFields(originalIndex) {
        // Since we stored the 'originalIndex' as the value of the option,
        // we can use it directly to find the matching answers in other arrays.
        for (let i = 1; i < q_and_a.length; i++) {
            const display = document.getElementById(`field-${i}`);
            display.textContent = q_and_a[i].answers[originalIndex];
        }
    }

    init();

    </script>

</body>
</html>
'''

print(html)
