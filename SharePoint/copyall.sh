# 1. Define Variables
TENANT_URL="https://tarrantadvisors.sharepoint.com"
SITE_URL="${TENANT_URL}/sites/Company"
QUERY_TEXT="filename:invoice* fileextension:pdf IsDocument:1"

# 2. Get Access Token for SharePoint
export AUTH_TOKEN=$(m365 util accesstoken get --resource "$TENANT_URL" --output text)

# 3. Define worker function for downloading via dynamic Web REST API
download_file() {
  local sp_site_url="$1"
  local uuid="$2"
  local filename="$3"

  if [ -z "$uuid" ] || [ -z "$filename" ]; then
    return 0
  fi

  echo "Downloading: ${filename} (UUID: ${uuid})"

  curl -s -f -L \
    -H "Authorization: Bearer ${AUTH_TOKEN}" \
    -H "Accept: application/octet-stream" \
    "${sp_site_url}/_api/web/GetFileById('${uuid}')/\$value" \
    -o "${filename}"

  if [ $? -eq 0 ]; then
    echo "Successfully downloaded: ${filename}"
  else
    echo "Failed to download: ${filename}"
  fi
}

export -f download_file

# 4. Stream NUL-delimited records (SPSiteUrl \0 UUID \0 Filename \0) into xargs
m365 spo search \
  --webUrl "${SITE_URL}" \
  --queryText "${QUERY_TEXT}" \
  --selectProperties "Title,UniqueId,OriginalPath,SPSiteUrl" \
  --allResults \
  --query "[*].{Name: Title, UUID: UniqueId, URL: OriginalPath, SiteURL: SPSiteUrl}" \
  -o json | jq -j --arg SITE "$SITE_URL" '.[] | select(.SiteURL == $SITE) | (
      (.SiteURL // ""),                               # Web site URL
      "\u0000",                                       # NUL byte
      ((.UUID // "") | gsub("[{}]"; "")),             # Clean UUID
      "\u0000",                                       # NUL byte
      (
        (.URL // "") 
        | sub(".*Shared Documents/"; "")              # Strip path up to Shared Documents
        | sub("/"; ":")                               # Change first slash to :
        | gsub("[^a-zA-Z0-9._:-]"; "_")               # Clean special characters (fixed range)
        | gsub("_+"; "_")                             # Collapse underscores
        | sub("^_"; "") | sub("_$"; "")               # Trim leading/trailing underscores
      ), "\u0000"                                     # NUL byte
    )' | xargs -0 -n 3 -P 6 bash -c 'download_file "$1" "$2" "$3"' _
