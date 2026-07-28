#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=.:$HOME/bin:$PATH

TOKENFILE=/var/www/etc/qboTokens.conf
qboRefresh.sh >/dev/null
. $TOKENFILE

source /var/www/webenv/bin/activate

export GEMINI_API_KEY=""
qbota.py $*

python3 <<EOF
from google import genai
import os

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

for f in client.files.list():
    try:
        client.files.delete(name=f.name)
        print(f"Deleted: {f.name}")
    except Exception as e:
        print(f"Failed to delete {f.name}: {e}")
EOF
