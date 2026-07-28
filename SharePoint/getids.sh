#!/bin/bash

export SHARED_SITE="/sites/TarrantAdvisorsShare"
export COMPANY_SITE="/sites/Company"
export TENANT_URL="https://tarrantadvisors.sharepoint.com" 
export BASE_FOLDER="/Shared Documents"

m365 spo folder list --webUrl "$TENANT_URL/$COMPANY_SITE" --parentFolderUrl "$BASE_FOLDER" --output json | \
jq -r '.[].ServerRelativeUrl' | while read -r folder_url; do
    m365 spo file list --webUrl "$TENANT_URL/$COMPANY_SITE" --folderUrl "$folder_url" --filter "startswith(Name, 'Log-')" --output json | \
    jq -r '.[] | "\(.UniqueId)|\(.ServerRelativeUrl)"'
done
