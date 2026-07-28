#!/usr/bin/env python3

import json
import subprocess
import os
import sys

SPO_URL = "https://tarrantadvisors.sharepoint.com/sites/TarrantAdvisorsShare"
FIELD_LIST = ["ServerUrl", "TotalFiles", "Format", "Questionnaire", "RetLoaded"]

def run_cli(command):
    """Helper to run M365 CLI commands with error detection."""
    full_cmd = ["m365"] + command + ["--output", "json"]
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict) and "error" in data:
            return None
        return data
    except:
        return None

if __name__ == "__main__":
    dashboard = run_cli([ "spo", "listitem", "list", "--webUrl", SPO_URL,
        "--listId", run_cli(["spo", "list", "get", "--webUrl", SPO_URL, "--title", "Documents"])["Id"],
        "--fields", ','.join(FIELD_LIST)])

    print("Content-Type: text/plain\nContent-Disposition: attachment; filename=\"dashboard.csv\"\n")
    print('|'.join(FIELD_LIST))
    for db in dashboard:
        row = '|'.join([str(db[k]) if db[k] != None else "--UNDEFINED--" for k in FIELD_LIST])
        if "--UNDEFINED--" not in row:
            print(row)
