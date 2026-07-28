#!/usr/bin/env python3

import os
import requests
import json

BASE_URL = "https://protaxdata.api.intuit.com"
HEADERS = {
    'authorization': os.getenv("TOKEN"),
    'cookie': os.getenv("COOKIES"),
    'accept': 'application/json',
}

resp = requests.get(f"{BASE_URL}/v1/returnstatus", headers=HEADERS)
codes = {}
for c in resp.json().get("values"):
	codes[c["id"]] = c["description"]
#print(json.dumps(codes, indent=4))

returns = []
resp = requests.get(f"{BASE_URL}/v1/returns/filter/2025?use-oii-client-id=true", headers=HEADERS)
returns = resp.json()
#print(json.dumps(returns, indent=4))

for r in returns:
	if not r["client_inactive"]:
		print(f'{r["name"]}|{r["ef_status"]}|{codes.get(r["id_status"], "Not started")}')
