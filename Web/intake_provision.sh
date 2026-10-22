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

debug "=== Intake request ($REQUEST_METHOD) ==="

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
      --arg bcc "$EMAIL_FROM" \
      --arg subject "$subject" \
      --arg html "$html_body" \
      '{from: $from, to: $to, bcc: [$bcc], subject: $subject, html: $html}')

    debug "Dispatching notification email via Resend API to $recipient (bcc: $EMAIL_FROM)..."
    
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
    'action', 'qbo_id', 'client_name', 'friendly_name', 'client_email', 'client_phone',
    'contact_date', 'responder', 'entity_type', 'delivery_format', 'co_signer_name', 
    'co_signer_email', 'street', 'city', 'state', 'zip', 'notes', 'is_new_lead'
]

for key in keys:
    val = str(params.get(key, ''))
    # Print clean bash uppercase variable assignments safely quoted
    print(f'{key.upper()}={shlex.quote(val)}')
")"

# Fallbacks and normalization
CLIENT_NAME="${CLIENT_NAME:-New Client}"
FRIENDLY_NAME="${FRIENDLY_NAME:-$CLIENT_NAME}"
CONTACT_DATE="${CONTACT_DATE:-$(date +%Y-%m-%d)}"
RESPONDER="${RESPONDER:-${REMOTE_USER:-nobody}}"
ENTITY_TYPE="${ENTITY_TYPE:-individual}"
DELIVERY_FORMAT="${DELIVERY_FORMAT:-electronic}"
IS_NEW_LEAD="${IS_NEW_LEAD:-true}"
QBOSP_FILE="${DOCUMENT_ROOT}/etc/${QBO_SANDBOX}qbosp.csv"

# Derive ACTION fallback if not explicitly provided
if [ -z "$ACTION" ]; then
    if [ "$IS_NEW_LEAD" = "true" ]; then
        ACTION="lead"
    else
        ACTION="heal"
    fi
fi

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

debug "Action Mode: '$ACTION'"
debug "Passed QBO ID: '${QBO_ID:-None}'"
debug "Clean Client Name: '$CLEAN_CLIENT_NAME'"
debug "Is New Lead: $IS_NEW_LEAD | Entity: $ENTITY_TYPE | Delivery Format: $DELIVERY_FORMAT | Responder: $RESPONDER"

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
TENANT_URL="https://tarrantadvisors.sharepoint.com"
if [ "$SANDBOX" ]; then
	COMPANY_SITE="${TENANT_URL}"
	SHARE_SITE="${TENANT_URL}"
	EMAIL_FROM="dianna@tarrantadvisors.com"
	NOTIFY="glmck13@gmail.com"
else
	COMPANY_SITE="${TENANT_URL}/sites/Company"
	SHARE_SITE="${TENANT_URL}/sites/TarrantAdvisorsShare"
	EMAIL_FROM="dianna@tarrantadvisors.com"
	NOTIFY="katie@tarrantadvisors.com,steve@tarrantadvisors.com,stephen@tarrantadvisors.com"
fi

SHARED_FOLDERS=("2026" "Prior to 2026" "Tax Returns")
COMPANY_FOLDERS=("2025 - Not Prepared by TA" "2026" "2026/Agreements & Invoices" "2026/BU Detail")

# ==============================================================================
# QUICKBOOKS ONLINE CUSTOMER LOOKUP
# ==============================================================================
QUERY_URI="/company/${QBO_REALMID}/query"
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

# ==============================================================================
# ISOLATED BRANCH 1: CLIENT DEACTIVATION & ARCHIVING (ACTION="deactivate")
# ==============================================================================
if [ "$ACTION" = "deactivate" ]; then
    debug "=== Initiating Client Deactivation Pipeline for '${CLEAN_CLIENT_NAME}' ==="

    TARGET_QBO_ID="${EXISTING_ID:-$QBO_ID}"

    if [ -n "$TARGET_QBO_ID" ] && [ "$TARGET_QBO_ID" != "Unknown" ]; then
        # Ensure SyncToken is present for deactivate payload
        if [ -z "$EXISTING_SYNC_TOKEN" ]; then
            debug "Fetching SyncToken for target QBO ID $TARGET_QBO_ID..."
            SYNC_QUERY_RESP=$(qbo.sh GET "$QUERY_URI" "query=select SyncToken from Customer where Id = '${TARGET_QBO_ID}'" 2>&1 || echo "")
            EXISTING_SYNC_TOKEN=$(echo "$SYNC_QUERY_RESP" | jq -r '.QueryResponse.Customer[0].SyncToken // "0"' 2>/dev/null || echo "0")
        fi

        debug "Deactivating Customer ID $TARGET_QBO_ID in QBO (Active: false)..."
        
        QBO_DEACTIVATE_PAYLOAD=$(jq -n \
          --arg id "$TARGET_QBO_ID" \
          --arg sync_token "$EXISTING_SYNC_TOKEN" \
          '{
            sparse: true,
            Id: $id,
            SyncToken: $sync_token,
            Active: false
          }')

        QBO_POST_URI="/company/${QBO_REALMID}/customer"
        QBO_DEACT_RESP=$(echo "$QBO_DEACTIVATE_PAYLOAD" | qbo.sh POST "$QBO_POST_URI" 2>&1 || echo "")
        debug "QBO Deactivation POST complete."
    else
        debug "WARNING: No valid QBO ID found for deactivation."
    fi

    # 2. MOVE SHAREPOINT FOLDERS TO !Inactive Clients
    debug 'Moving SharePoint folders to !Inactive Clients...'
    QBOSP_CLIENT_NAME=$(grep "^${TARGET_QBO_ID}:" "$QBOSP_FILE" | cut -f3 -d:)

    if [ -n "${QBOSP_CLIENT_NAME}" ]; then
        SHARE_SRC="Shared Documents/${QBOSP_CLIENT_NAME}"
        SHARE_DST="Shared Documents/!Inactive Clients"
        COMPANY_SRC="Shared Documents/${QBOSP_CLIENT_NAME% - SHARED}"
        COMPANY_DST="Shared Documents/!Inactive Clients"
        
        m365 spo folder move \
          --webUrl "$COMPANY_SITE" \
          --sourceUrl "$COMPANY_SRC" \
          --targetUrl "$COMPANY_DST" >&2 || true

        m365 spo folder move \
          --webUrl "$SHARE_SITE" \
          --sourceUrl "$SHARE_SRC" \
          --targetUrl "$SHARE_DST" >&2 || true

        # 3. REVOKE ALL GUEST SHARING LINKS ON MOVED SHARE FOLDER
        MOVED_SHARE_LIB_PATH="Shared Documents/!Inactive Clients/${QBOSP_CLIENT_NAME}"
        MOVED_SHARE_SERVER_REL=$(to_server_rel_path "$SHARE_SITE" "$MOVED_SHARE_LIB_PATH")
        
        debug "Querying list item ID for moved folder: '$MOVED_SHARE_SERVER_REL'..."
        MOVED_ITEM_RESP=$(m365 request \
          --url "${SHARE_SITE}/_api/web/getfolderbyserverrelativeurl('${MOVED_SHARE_SERVER_REL}')/ListItemAllFields" \
          -o json 2>&1 || echo "")
        MOVED_ITEM_ID=$(echo "$MOVED_ITEM_RESP" | jq -r '.ID // .d.ID // empty' 2>/dev/null || echo "")

        if [ -n "$MOVED_ITEM_ID" ]; then
            debug "Revoking guest sharing links on moved folder (Item ID: $MOVED_ITEM_ID)..."
            
            UNSHARE_PAYLOAD=$(jq -n \
              --arg url "${SHARE_SITE}/${MOVED_SHARE_LIB_PATH}" \
              '{
                url: $url
              }')

            m365 request \
              --url "${SHARE_SITE}/_api/SP.Web.UnshareObject" \
              --method POST \
              --headers '{"accept":"application/json;odata=verbose","content-type":"application/json;odata=verbose"}' \
              --body "$UNSHARE_PAYLOAD" >/dev/null 2>&1 || debug "Note: Unshare call completed."
        else
            debug "WARNING: Could not resolve List Item ID for '$MOVED_SHARE_SERVER_REL'."
        fi
    else
        debug "${TARGET_QBO_ID} not found in ${QBOSP_FILE}, skipping..."
    fi

    # 4. SEND EMAIL NOTIFICATION
    debug "Sending client deactivation team email notification..."
    DEACT_EMAIL_BODY="<p><b>Actioned by:</b> ${RESPONDER}</p>\
<h1>Client Deactivated</h1>\
<p>\
<b>Client Name:</b> ${CLEAN_CLIENT_NAME}<br>\
<b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
<b>Primary Email:</b> ${CLIENT_EMAIL}<br>\
<b>Phone Number:</b> ${CLIENT_PHONE}<br>\
<b>Entity Classification:</b> ${ENTITY_TYPE}<br>\
<b>QBO ID:</b> ${TARGET_QBO_ID:-Unknown}<br>\
<b>QBO Status:</b> Marked Inactive (Active: false)<br>\
<b>SharePoint Status:</b> Folders moved to !Inactive Clients & guest permissions revoked\
</p>"

    send_resend_email \
      "Client Deactivated on Tarrant Advisors: ${CLEAN_CLIENT_NAME}" \
      "${DEACT_EMAIL_BODY}" \
      "${NOTIFY}"

    debug "=== Client deactivation complete for '$CLEAN_CLIENT_NAME' ==="
    echo "{\"status\": \"success\", \"action\": \"deactivate\", \"qbo_id\": \"${TARGET_QBO_ID:-Unknown}\", \"message\": \"Client ${CLEAN_CLIENT_NAME} deactivated in QBO and folders archived to !Inactive Clients.\"}"
    exit 0
fi

# ==============================================================================
# QBO CUSTOMER CREATION / UPDATE (RUNS FOR BOTH 'LEAD' AND 'HEAL')
# ==============================================================================
if [ "$ENTITY_TYPE" = "individual" ]; then
    QBO_DISPLAY_NAME="$CLEAN_CLIENT_NAME"
    QBO_COMPANY_NAME=""
else
    QBO_DISPLAY_NAME="$CLEAN_CLIENT_NAME"
    QBO_COMPANY_NAME="$CLEAN_CLIENT_NAME"
fi

NOTES_JSON=$(jq -n -c \
  --arg entity "$ENTITY_TYPE" \
  --arg format "$DELIVERY_FORMAT" \
  --arg p_name "$FRIENDLY_NAME" \
  --arg p_email "$CLIENT_EMAIL" \
  --arg c_name "$CO_SIGNER_NAME" \
  --arg c_email "$CO_SIGNER_EMAIL" \
  '{
    entity: $entity,
    format: $format,
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
QBO_CUSTOMER_ID=$(echo "$QBO_RESPONSE" | jq -r '.Customer.Id // empty' 2>/dev/null)

if [ -z "$QBO_CUSTOMER_ID" ]; then
    QBO_CUSTOMER_ID="${EXISTING_ID:-Unknown}"
fi

debug "QBO Sync complete. Resolved Numeric QBO ID: $QBO_CUSTOMER_ID"

# ==============================================================================
# EXISTING CLIENT PROFILE HEALING (ACTION="heal" or IS_NEW_LEAD="false")
# ==============================================================================
if [ "$ACTION" = "heal" ] || [ "$IS_NEW_LEAD" != "true" ]; then
    debug "Sending profile update email notification..."
    HEAL_EMAIL_BODY="<p><b>Updated by:</b> ${RESPONDER}</p>\
<h1>Client Updated</h1>\
<p>\
<b>Name:</b> ${CLEAN_CLIENT_NAME}<br>\
<b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
<b>Email address:</b> ${CLIENT_EMAIL}<br>\
<b>Phone number:</b> ${CLIENT_PHONE}<br>\
<b>Contact date:</b> ${CONTACT_DATE}<br>\
<b>Entity Classification:</b> ${ENTITY_TYPE}<br>\
<b>Delivery Format:</b> ${DELIVERY_FORMAT}<br><br>\
<b>QBO ID:</b> ${QBO_CUSTOMER_ID}\
</p>"

    send_resend_email \
      "QBO Profile Updated on Tarrant Advisors: ${CLEAN_CLIENT_NAME}" \
      "${HEAL_EMAIL_BODY}" \
      "${NOTIFY}"

    debug "Profile update complete. Exiting."
    echo "{\"status\": \"success\", \"is_new_lead\": false, \"qbo_id\": \"$QBO_CUSTOMER_ID\", \"message\": \"Profile for ${CLEAN_CLIENT_NAME} updated successfully.\"}"
    exit 0
fi

# ==============================================================================
# NEW CLIENT PROVISIONING ONLY (ACTION="lead")
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

SHARE_FOLDER_RESP=$(m365 request \
  --url "${SHARE_SITE}/_api/web/getfolderbyserverrelativeurl('${SHARE_FOLDER_SERVER_REL}')/ListItemAllFields" \
  -o json 2>&1 || echo "")
SHARE_FOLDER_ITEM_ID=$(echo "$SHARE_FOLDER_RESP" | jq -r '.ID // .d.ID // empty' 2>/dev/null || echo "")

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

COPY_RESPONSE=$(m365 spo file copy \
  --webUrl "$SHARE_SITE" \
  --sourceUrl "Shared Documents/Client Log Template.xlsx" \
  --targetUrl "$COMPANY_SITE/Shared Documents/${CLEAN_CLIENT_NAME}" \
  --newName "$LOGFILE_NAME" \
  --nameConflictBehavior replace \
  -o json 2>/dev/null || echo "")

LOGFILE_LINK=$(echo "$COPY_RESPONSE" | jq -r '.LinkingUri // empty' 2>/dev/null)

SPO_FORMAT="Electronic"
if [ "$DELIVERY_FORMAT" = "paper" ]; then
    SPO_FORMAT="Paper"
fi

if [ -n "$SHARE_FOLDER_ITEM_ID" ]; then
    m365 spo listitem set \
      --webUrl "$SHARE_SITE" \
      --listTitle "Documents" \
      --id "$SHARE_FOLDER_ITEM_ID" \
      --TotalFiles 0 \
      --Format "$SPO_FORMAT" \
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
</style>
</head>
<body>
<b>Submitted by: </b>${RESPONDER}<br>
<h1>Client Added</h1>
<b>Name: </b>${CLEAN_CLIENT_NAME}<br>
<b>Contact Name: </b>${FRIENDLY_NAME}<br>
<b>Email address: </b>${CLIENT_EMAIL}<br>
<b>Phone number: </b>${CLIENT_PHONE}<br>
<b>Contact date: </b>${CONTACT_DATE}<br>
<b>Entity Classification: </b>${ENTITY_TYPE}<br>
<b>Delivery Format: </b>${DELIVERY_FORMAT}<br>
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

if [ -n "$QBO_CUSTOMER_ID" ] && [ "$QBO_CUSTOMER_ID" != "Unknown" ]; then
    echo "${QBO_CUSTOMER_ID}:${CLEAN_CLIENT_NAME}:${CLEAN_CLIENT_NAME} - SHARED:::" >> "$QBOSP_FILE"
    debug "Appended $QBO_CUSTOMER_ID to $QBOSP_FILE"
fi

# STEP 5: SEND NOTIFICATION EMAIL VIA RESEND API
debug "Sending team notification email via Resend API..."

EMAIL_BODY="<p><b>Submitted by:</b> ${RESPONDER}</p>\
<h1>Client Added</h1>\
<p>\
<b>Name:</b> ${CLEAN_CLIENT_NAME}<br>\
<b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
<b>Email address:</b> ${CLIENT_EMAIL}<br>\
<b>Phone number:</b> ${CLIENT_PHONE}<br>\
<b>Contact date:</b> ${CONTACT_DATE}<br>\
<b>Entity Classification:</b> ${ENTITY_TYPE}<br>\
<b>Delivery Format:</b> ${DELIVERY_FORMAT}<br>\
<b>Notes:</b> ${NOTES}<br><br>\
<b>QBO ID:</b> ${QBO_CUSTOMER_ID}\
</p>\
<h1>To Do:</h1>\
<ul>\
<li>Add client to Revenue Schedule: ${CLEAN_CLIENT_NAME}</li>\
<li>Create TA Tax Agreement</li>\
<li>Share folder w/ client (and tax organizer if needed)</li>\
<li>Add client to ProConnect only after tax return has been received for download</li>\
</ul>"

send_resend_email \
  "New Client Intake submitted on Tarrant Advisors: ${CLEAN_CLIENT_NAME}" \
  "${EMAIL_BODY}" \
  "${NOTIFY}"

debug "=== Client provisioning complete for '$CLEAN_CLIENT_NAME' ==="

# RETURN SUCCESS JSON TO FETCH CALL
echo "{\"status\": \"success\", \"is_new_lead\": true, \"qbo_id\": \"$QBO_CUSTOMER_ID\", \"message\": \"New client ${CLEAN_CLIENT_NAME} provisioned successfully.\"}"
