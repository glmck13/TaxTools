#!/bin/bash

# CGI script executed by Apache web server via POST or GET fetch()
# Output JSON response format

# Output CGI HTTP Header
echo "Content-Type: application/json; charset=utf-8"
echo ""

# Trap unhandled shell errors and output clean JSON
trap 'echo "{\"status\": \"error\", \"message\": \"Script failed unexpectedly at line $LINENO\"}"; exit 1' ERR

# ==============================================================================
# DEBUG LOGGING CONTROL
# Set DEBUG=true to log step-by-step progress to Apache error log (stderr)
# ==============================================================================
DEBUG="true"

debug() {
    if [ "$DEBUG" = "true" ]; then
        echo "[INTAKE DEBUG $(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
    fi
}

debug "=== Intaking new request ($REQUEST_METHOD) ==="

# ==============================================================================
# HELPER: CONSTRUCT ENVIRONMENT-AWARE SERVER-RELATIVE PATHS
# ==============================================================================
to_server_rel_path() {
    local site_url="$1"
    local lib_path="$2"
    
    # Strip TENANT_URL and any leading/trailing slashes
    local site_rel="${site_url#$TENANT_URL}"
    site_rel="${site_rel#/}"
    site_rel="${site_rel%/}"
    
    # Strip leading slash from library path
    local clean_lib_path="${lib_path#/}"
    
    # In Sandbox (site_rel is ""):      "/Shared Documents/..."
    # In Production (site_rel is "sites/X"): "/sites/X/Shared Documents/..."
    echo "/${site_rel:+$site_rel/}${clean_lib_path}"
}

# ==============================================================================
# HELPER: SEND EMAIL VIA RESEND REST API
# ==============================================================================
send_resend_email() {
    local subject="$1"
    local html_body="$2"
    local recipient="$3"

    if [ -z "$RESEND_API_KEY" ]; then
        debug "WARNING: RESEND_API_KEY is not set. Skipping email dispatch."
        return 1
    fi

    # Convert comma-separated emails into a clean, non-empty JSON array
    local to_array
    to_array=$(echo "$recipient" | jq -R 'split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0))')

    local payload
    payload=$(jq -n \
      --arg from "Tarrant Advisors <$EMAIL_FROM>" \
      --argjson to "$to_array" \
      --arg subject "$subject" \
      --arg html "$html_body" \
      '{from: $from, to: $to, subject: $subject, html: $html}')

    debug "Dispatching notification email via Resend API to $recipient..."
    
    curl -s -X POST "https://api.resend.com/emails" \
      -H "Authorization: Bearer ${RESEND_API_KEY}" \
      -H "Content-Type: application/json" \
      -d "$payload" >&2 || true
}

# ==============================================================================
# READ & PARSE INPUT PARAMETERS (SINGLE-PASS EFFICIENT PARSER)
# ==============================================================================
if [ "$REQUEST_METHOD" = "POST" ]; then
    RAW_INPUT_DATA=$(cat)
else
    RAW_INPUT_DATA="$QUERY_STRING"
fi

# Export raw data and request metadata so Python reads them via os.environ safely
export RAW_INPUT_DATA
export REQUEST_METHOD
export CONTENT_TYPE

# Parse ALL incoming variables in a single Python execution
eval "$(python3 -c "
import os, sys, urllib.parse, json, shlex

req_method = os.environ.get('REQUEST_METHOD', 'GET')
content_type = os.environ.get('CONTENT_TYPE', '')
raw_data = os.environ.get('RAW_INPUT_DATA', '')

params = {}
if 'application/json' in content_type and req_method == 'POST':
    try:
        params = json.loads(raw_data)
    except Exception:
        pass
else:
    parsed = urllib.parse.parse_qs(raw_data)
    params = {k: v[0] for k, v in parsed.items() if v}

keys = [
    'qbo_id', 'client_name', 'friendly_name', 'client_email', 'client_phone',
    'contact_date', 'responder', 'entity_type', 'co_signer_name', 
    'co_signer_email', 'street', 'city', 'state', 'zip', 'notes', 'is_new_lead'
]

for key in keys:
    val = str(params.get(key, ''))
    # Print clean bash uppercase variable assignments safely quoted
    print(f'{key.upper()}={shlex.quote(val)}')
")"

# Fallbacks
CLIENT_NAME="${CLIENT_NAME:-New Client}"
FRIENDLY_NAME="${FRIENDLY_NAME:-$CLIENT_NAME}"
CONTACT_DATE="${CONTACT_DATE:-$(date +%Y-%m-%d)}"
RESPONDER="${RESPONDER:-${REMOTE_USER:-nobody}}"
ENTITY_TYPE="${ENTITY_TYPE:-individual}"
IS_NEW_LEAD="${IS_NEW_LEAD:-true}"

# 1. SHAREPOINT NAME: Full name, stripping trailing spaces and periods
CLEAN_CLIENT_NAME="${CLIENT_NAME%"${CLIENT_NAME##*[!. ]}"}"

# 2. LOGFILE NAME: Take up to 1st 3 words safely
IFS=' ' read -r -a NAME_WORDS <<< "$CLEAN_CLIENT_NAME"
W1="${NAME_WORDS[0]:-}"
W2="${NAME_WORDS[1]:-}"
W3="${NAME_WORDS[2]:-}"
PREFIX_COMBINED="${W1}${W2}${W3}"
CLEAN_LOG_PREFIX="${PREFIX_COMBINED//[^a-zA-Z0-9]/}"
LOGFILE_NAME="Log-${CLEAN_LOG_PREFIX:-Client}.xlsx"

debug "Passed QBO ID: '${QBO_ID:-None}'"
debug "Clean Client Name: '$CLEAN_CLIENT_NAME'"
debug "Generated Log File Name: '$LOGFILE_NAME'"
debug "Is New Lead: $IS_NEW_LEAD | Entity: $ENTITY_TYPE | Responder: $RESPONDER"

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
TENANT_URL="https://tarrantadvisors.sharepoint.com"
if [ "$SANDBOX" ]; then
	COMPANY_SITE="${TENANT_URL}"
	SHARE_SITE="${TENANT_URL}"
	EMAIL_FROM="dianna@tarrantadvisors.com"
	NOTIFY="glmck13@gmail.com,glmck13@verizon.net"
else
	COMPANY_SITE="${TENANT_URL}/sites/Company"
	SHARE_SITE="${TENANT_URL}/sites/TarrantAdvisorsShare"
	EMAIL_FROM="dianna@tarrantadvisors.com"
	NOTIFY="katie@tarrantadvisors.com,steve@tarrantadvisors.com,stephen@tarrantadvisors.com"
fi

SHARED_FOLDERS=("2026" "Prior to 2026" "Tax Returns")
COMPANY_FOLDERS=("2025 - Not Prepared by TA" "2026" "2026/Agreements & Invoices" "2026/BU Detail")

# ==============================================================================
# STEP 1: QUICKBOOKS ONLINE CUSTOMER LOOKUP & SYNC
# ==============================================================================
if [ "$ENTITY_TYPE" = "individual" ]; then
    QBO_DISPLAY_NAME="$CLEAN_CLIENT_NAME"
    QBO_COMPANY_NAME=""
else
    QBO_DISPLAY_NAME="$CLEAN_CLIENT_NAME"
    QBO_COMPANY_NAME="$CLEAN_CLIENT_NAME"
fi

debug "Target QBO DisplayName: '$QBO_DISPLAY_NAME' | CompanyName: '$QBO_COMPANY_NAME'"

QUERY_URI="/company/${QBO_REALMID}/query"

# 1. ALWAYS SEARCH QBO BY NAME FIRST (SEQUENTIAL LOOKUP TO AVOID 'OR' SYNTAX ERROR)
SEARCH_NAME=$(echo "$CLEAN_CLIENT_NAME" | sed -e 's/\\/\\\\/g' -e "s/'/\\\\'/g" -e 's/"/\\"/g')

# Search DisplayName
QUERY_RESP=$(qbo.sh GET "$QUERY_URI" "query=select Id, SyncToken, DisplayName from Customer where DisplayName = '${SEARCH_NAME}'" 2>&1 || echo "")
EXISTING_ID=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].Id // empty' 2>/dev/null || echo "")
EXISTING_SYNC_TOKEN=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].SyncToken // empty' 2>/dev/null || echo "")

# Fallback: Search CompanyName if DisplayName search returned empty
if [ -z "$EXISTING_ID" ]; then
    QUERY_RESP=$(qbo.sh GET "$QUERY_URI" "query=select Id, SyncToken, DisplayName from Customer where CompanyName = '${SEARCH_NAME}'" 2>&1 || echo "")
    EXISTING_ID=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].Id // empty' 2>/dev/null || echo "")
    EXISTING_SYNC_TOKEN=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].SyncToken // empty' 2>/dev/null || echo "")
fi

# Fallback: Use passed qbo_id if name queries returned empty
if [ -z "$EXISTING_ID" ] && [ -n "$QBO_ID" ]; then
    debug "Using passed QBO ID from frontend JS: $QBO_ID"
    EXISTING_ID="$QBO_ID"
    QUERY_RESP=$(qbo.sh GET "$QUERY_URI" "query=select Id, SyncToken from Customer where Id = '${QBO_ID}'" 2>&1 || echo "")
    EXISTING_SYNC_TOKEN=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].SyncToken // empty' 2>/dev/null || echo "")
fi

if [ -n "$EXISTING_ID" ]; then
    debug "Auto-adopting existing QBO Customer ID: $EXISTING_ID (SyncToken: $EXISTING_SYNC_TOKEN) for '$CLEAN_CLIENT_NAME'"
else
    debug "No existing QBO Customer found for '$CLEAN_CLIENT_NAME'. Preparing to create new record."
fi

# 2. BUILD PAYLOAD & SYNC TO QBO
NOTES_JSON=$(jq -n -c \
  --arg entity "$ENTITY_TYPE" \
  --arg p_name "$FRIENDLY_NAME" \
  --arg p_email "$CLIENT_EMAIL" \
  --arg c_name "$CO_SIGNER_NAME" \
  --arg c_email "$CO_SIGNER_EMAIL" \
  '{
    entity: $entity,
    signers: (
      [{name: $p_name, email: $p_email}] +
      (if ($c_name != "" or $c_email != "") then [{name: $c_name, email: $c_email}] else [] end)
    )
  }')

QBO_PATCH_PAYLOAD=$(jq -n \
  --arg id "$EXISTING_ID" \
  --arg sync_token "$EXISTING_SYNC_TOKEN" \
  --arg display_name "$QBO_DISPLAY_NAME" \
  --arg company_name "$QBO_COMPANY_NAME" \
  --arg email "$CLIENT_EMAIL" \
  --arg phone "$CLIENT_PHONE" \
  --arg notes "$NOTES_JSON" \
  --arg street "$STREET" \
  --arg city "$CITY" \
  --arg state "$STATE" \
  --arg zip "$ZIP" \
  '{
    sparse: true,
    DisplayName: $display_name,
    CompanyName: $company_name,
    PrimaryEmailAddr: { Address: $email },
    PrimaryPhone: { FreeFormNumber: $phone },
    Notes: $notes,
    BillAddr: { Line1: $street, City: $city, CountrySubDivisionCode: $state, PostalCode: $zip }
  } 
  + (if $id != "" then {Id: $id, SyncToken: $sync_token} else {} end)')

QBO_POST_URI="/company/${QBO_REALMID}/customer"
debug "Posting Customer Payload to QBO (Sparse Update Enabled)..."

QBO_RESPONSE=$(echo "$QBO_PATCH_PAYLOAD" | qbo.sh POST "$QBO_POST_URI" 2>&1 || echo "")

# Extract Customer ID cleanly; fallback to EXISTING_ID if POST response lacks Customer wrapper
QBO_CUSTOMER_ID=$(echo "$QBO_RESPONSE" | jq -r '.Customer.Id // empty' 2>/dev/null)

if [ -z "$QBO_CUSTOMER_ID" ]; then
    QBO_CUSTOMER_ID="${EXISTING_ID:-Unknown}"
fi

debug "QBO Sync complete. Resolved Numeric QBO ID: $QBO_CUSTOMER_ID"

QBOSP_FILE="${HOME}/etc/${QBO_SANDBOX}qbosp.csv"
if [ -f "$QBOSP_FILE" ] && [ -n "$QBO_CUSTOMER_ID" ] && [ "$QBO_CUSTOMER_ID" != "Unknown" ]; then
    echo "${QBO_CUSTOMER_ID}:${CLEAN_CLIENT_NAME}:${CLEAN_CLIENT_NAME} - SHARED:::" >> "$QBOSP_FILE"
    debug "Appended $QBO_CUSTOMER_ID to $QBOSP_FILE"
fi

# ==============================================================================
# BRANCHING POINT: EXISTING CLIENT PROFILE HEALING
# ==============================================================================
if [ "$IS_NEW_LEAD" != "true" ]; then
    debug "Sending profile update email notification..."
    HEAL_EMAIL_BODY="<p><b>Updated by:</b> ${RESPONDER}</p>\
<h1 style='color:#0369a1;'>QBO Profile Updated:</h1>\
<p>\
<b>Name:</b> ${CLEAN_CLIENT_NAME}<br>\
<b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
<b>Email address:</b> ${CLIENT_EMAIL}<br>\
<b>Phone number:</b> ${CLIENT_PHONE}<br>\
<b>Contact date:</b> ${CONTACT_DATE}<br>\
<b>Entity Classification:</b> ${ENTITY_TYPE}<br><br>\
<b>QBO ID:</b> ${QBO_CUSTOMER_ID}\
</p>"

    send_resend_email \
      "QBO Profile Updated on Tarrant Advisors: ${CLEAN_CLIENT_NAME}" \
      "$HEAL_EMAIL_BODY" \
      "$NOTIFY"

    debug "Profile update complete. Exiting."
    echo "{\"status\": \"success\", \"is_new_lead\": false, \"qbo_id\": \"$QBO_CUSTOMER_ID\", \"message\": \"Profile for ${CLEAN_CLIENT_NAME} updated successfully.\"}"
    exit 0
fi

# ==============================================================================
# NEW CLIENT PROVISIONING ONLY (IS_NEW_LEAD="true")
# ==============================================================================

# ==============================================================================
# STEP 2: SHAREPOINT CLIENT FOLDER GENERATION (IDEMPOTENT GET-OR-CREATE)
# ==============================================================================
debug "Creating SharePoint folders..."

SHARE_ROOT_NAME="${CLEAN_CLIENT_NAME} - SHARED"
SHARE_LIB_PATH="Shared Documents/${SHARE_ROOT_NAME}"

# 1. Ensure root shared folder exists
m365 spo folder add \
  --webUrl "$SHARE_SITE" \
  --parentFolderUrl "Shared Documents" \
  --name "$SHARE_ROOT_NAME" >&2 || true

# 2. Query folder's underlying list item ID via SharePoint REST API
SHARE_FOLDER_SERVER_REL=$(to_server_rel_path "$SHARE_SITE" "$SHARE_LIB_PATH")

debug "Querying folder item ID for server-relative path: '$SHARE_FOLDER_SERVER_REL'..."

SHARE_FOLDER_ITEM_ID=$(m365 request \
  --url "${SHARE_SITE}/_api/web/getfolderbyserverrelativeurl('${SHARE_FOLDER_SERVER_REL}')/ListItemAllFields" \
  -o json 2>&1 | jq -r '.ID // .d.ID // empty' 2>/dev/null)

debug "Resolved SharePoint Folder Item ID: '${SHARE_FOLDER_ITEM_ID:-Not Found}'"

# 3. Idempotently create shared subfolders
for subfolder in "${SHARED_FOLDERS[@]}"; do
  m365 spo folder add \
    --webUrl "$SHARE_SITE" \
    --parentFolderUrl "$SHARE_LIB_PATH" \
    --name "$subfolder" >&2 || true
done

# 4. Idempotently create company site folder tree
COMPANY_ROOT_PATH="Shared Documents/${CLEAN_CLIENT_NAME}"
m365 spo folder add \
  --webUrl "$COMPANY_SITE" \
  --parentFolderUrl "Shared Documents" \
  --name "$CLEAN_CLIENT_NAME" >&2 || true

for subfolder in "${COMPANY_FOLDERS[@]}"; do
  m365 spo folder add \
    --webUrl "$COMPANY_SITE" \
    --parentFolderUrl "$COMPANY_ROOT_PATH" \
    --name "$subfolder" >&2 || true
done

# STEP 3: COPY LOGFILE TEMPLATE & UPDATE METADATA
debug "Copying log file template '$LOGFILE_NAME'..."

m365 spo file copy \
  --webUrl "$COMPANY_SITE" \
  --sourceUrl "Shared Documents/Client Log Template.xlsx" \
  --targetUrl "Shared Documents/${CLEAN_CLIENT_NAME}" \
  --newName "$LOGFILE_NAME" \
  --nameConflictBehavior replace >&2 || true

LOGFILE_LINK="${COMPANY_SITE}/Shared Documents/${CLEAN_CLIENT_NAME}/${LOGFILE_NAME}"

if [ -n "$SHARE_FOLDER_ITEM_ID" ]; then
    m365 spo listitem set \
      --webUrl "$SHARE_SITE" \
      --listTitle "Documents" \
      --id "$SHARE_FOLDER_ITEM_ID" \
      --TotalFiles 0 \
      --Format "Electronic" \
      --Questionnaire "Not Found" \
      --RetLoaded "No" \
      --ClientLog "$LOGFILE_LINK" >&2 || true
fi

# STEP 4: ARCHIVE INTAKE SUMMARY HTML FILE
debug "Archiving intake summary HTML..."
HTML_TEMP_FILE="/tmp/intake_${CLEAN_LOG_PREFIX}.html"
cat <<EOF > "$HTML_TEMP_FILE"
<html>
<head>
<style>
  body { margin: 50px; font-family: sans-serif; }
  h1 { color: #0078d4; }
  ul { line-height: 1.6; }
</style>
</head>
<body>
<b>Submitted by: </b>${RESPONDER}<br>
<h1>Client Info:</h1>
<b>Name: </b>${CLEAN_CLIENT_NAME}<br>
<b>Contact Name: </b>${FRIENDLY_NAME}<br>
<b>Email address: </b>${CLIENT_EMAIL}<br>
<b>Phone number: </b>${CLIENT_PHONE}<br>
<b>Contact date: </b>${CONTACT_DATE}<br>
<b>Entity Classification: </b>${ENTITY_TYPE}<br>
<b>Notes: </b>${NOTES}<br><br>
<b>QBO Status:</b> Synced (ID: ${QBO_CUSTOMER_ID})
<h1>To Do:</h1>
<ul>
  <li>Add client to Revenue Schedule: ${CLEAN_CLIENT_NAME}</li>
  <li>Create TA Tax Agreement</li>
  <li>Share folder w/ client (and tax organizer if needed)</li>
  <li>Add client to ProConnect only after tax return has been received for download</li>
</ul>
</body>
</html>
EOF

m365 spo file add \
  --webUrl "$COMPANY_SITE" \
  --folder "$COMPANY_ROOT_PATH" \
  --path "$HTML_TEMP_FILE" \
  --fileName "Client Intake Form.html" \
  --overwrite true >&2 || true

rm -f "$HTML_TEMP_FILE"

# STEP 5: SEND NOTIFICATION EMAIL VIA RESEND API
debug "Sending team notification email via Resend API..."

EMAIL_BODY="<p><b>Submitted by:</b> ${RESPONDER}</p>\
<h1 style='color:#0078d4;'>Client Info:</h1>\
<p>\
<b>Name:</b> ${CLEAN_CLIENT_NAME}<br>\
<b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
<b>Email address:</b> ${CLIENT_EMAIL}<br>\
<b>Phone number:</b> ${CLIENT_PHONE}<br>\
<b>Contact date:</b> ${CONTACT_DATE}<br>\
<b>Entity Classification:</b> ${ENTITY_TYPE}<br>\
<b>Notes:</b> ${NOTES}<br><br>\
<b>QBO ID:</b> ${QBO_CUSTOMER_ID}\
</p>\
<h1>To do:</h1>\
<ul>\
<li>Add client to Revenue Schedule: ${CLEAN_CLIENT_NAME}</li>\
<li>Create TA Tax Agreement</li>\
<li>Share folder w/ client (and tax organizer if needed)</li>\
<li>Add client to ProConnect only after tax return has been received for download</li>\
</ul>"

send_resend_email \
  "New Client Intake submitted on Tarrant Advisors: ${CLEAN_CLIENT_NAME}" \
  "$EMAIL_BODY" \
  "$NOTIFY"

debug "=== Client provisioning complete for '$CLEAN_CLIENT_NAME' ==="

# RETURN SUCCESS JSON TO FETCH CALL
echo "{\"status\": \"success\", \"is_new_lead\": true, \"qbo_id\": \"$QBO_CUSTOMER_ID\", \"message\": \"New client ${CLEAN_CLIENT_NAME} provisioned successfully.\"}"
