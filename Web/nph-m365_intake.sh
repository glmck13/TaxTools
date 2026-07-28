#!/bin/bash

UUID=$(echo "$QUERY_STRING" | sed -n 's/.*uuid=\([^&]*\).*/\1/p')

export TENANT_URL="https://tarrantadvisors.sharepoint.com" 
export BASE_SITE=""  
export BASE_FOLDER="Shared Documents/Apps/QBO Estimates"  

qboapp=$0 qboapp=${qboapp/m365_/qbo_} qboapp=${qboapp%.*}.cgi

m365 spo file get --webUrl "${TENANT_URL}${BASE_SITE}" --id "$UUID" --asFile --path /dev/stdout 2>/dev/null | ${qboapp}
