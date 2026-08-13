#!/bin/bash
# CGI script executed by Apache web server via GET fetch()
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

debug "=== Intaking new request ($QUERY_STRING) ==="

# ==============================================================================
# READ & PARSE URL QUERY PARAMETERS ($QUERY_STRING)
# ==============================================================================
urldecode() {
    echo -e "$(echo "$1" | sed 's/+/ /g; s/%/\\x/g')"
}

get_param() {
    echo "$QUERY_STRING" | grep -oP "(?:^|&)$1=\K[^&]*" | head -n 1
}

QBO_ID=$(urldecode "$(get_param "qbo_id")")
CLIENT_NAME=$(urldecode "$(get_param "client_name")")
FRIENDLY_NAME=$(urldecode "$(get_param "friendly_name")")
CLIENT_EMAIL=$(urldecode "$(get_param "client_email")")
CLIENT_PHONE=$(urldecode "$(get_param "client_phone")")
CONTACT_DATE=$(urldecode "$(get_param "contact_date")")
RESPONDER=$(urldecode "$(get_param "responder")")
ENTITY_TYPE=$(urldecode "$(get_param "entity_type")")
CO_SIGNER_NAME=$(urldecode "$(get_param "co_signer_name")")
CO_SIGNER_EMAIL=$(urldecode "$(get_param "co_signer_email")")
STREET=$(urldecode "$(get_param "street")")
CITY=$(urldecode "$(get_param "city")")
STATE=$(urldecode "$(get_param "state")")
ZIP=$(urldecode "$(get_param "zip")")
IS_NEW_LEAD=$(urldecode "$(get_param "is_new_lead")")

# Fallbacks
CLIENT_NAME="${CLIENT_NAME:-New Client}"
FRIENDLY_NAME="${FRIENDLY_NAME:-$CLIENT_NAME}"
CONTACT_DATE="${CONTACT_DATE:-$(date +%Y-%m-%d)}"
RESPONDER="${RESPONDER:-nobody}"
ENTITY_TYPE="${ENTITY_TYPE:-individual}"
IS_NEW_LEAD="${IS_NEW_LEAD:-true}"

# 1. SHAREPOINT NAME: Full name, stripping only trailing spaces and periods
CLEAN_CLIENT_NAME="${CLIENT_NAME%"${CLIENT_NAME##*[!. ]}"}"

# 2. LOGFILE NAME: Take up to 1st 3 words safely without out-of-bounds index errors
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
debug "Is New Lead: $IS_NEW_LEAD | Entity: $ENTITY_TYPE"

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================
TENANT_URL="https://tarrantadvisors.sharepoint.com"
COMPANY_SITE="${TENANT_URL}/sites/Company"
SHARE_SITE="${TENANT_URL}/sites/TarrantAdvisorsShare"

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

if [ -n "$QBO_ID" ]; then
    debug "Using passed QBO ID from frontend JS: $QBO_ID"
    EXISTING_ID="$QBO_ID"
    QUERY_RESP=$(qbo.sh GET "$QUERY_URI" "query=select Id, SyncToken from Customer where Id = '${QBO_ID}'" || echo "")
    EXISTING_SYNC_TOKEN=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].SyncToken // empty' || echo "")
else
    debug "No QBO ID passed. Searching QBO by DisplayName or CompanyName..."
    SEARCH_NAME=$(echo "$CLEAN_CLIENT_NAME" | sed "s/'/\\\\'/g")
    QUERY_RESP=$(qbo.sh GET "$QUERY_URI" "query=select Id, SyncToken from Customer where DisplayName = '${SEARCH_NAME}' or CompanyName = '${SEARCH_NAME}'" || echo "")
    EXISTING_ID=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].Id // empty' || echo "")
    EXISTING_SYNC_TOKEN=$(echo "$QUERY_RESP" | jq -r '.QueryResponse.Customer[0].SyncToken // empty' || echo "")
fi

if [ -n "$EXISTING_ID" ]; then
    debug "Resolved QBO Customer ID: $EXISTING_ID (SyncToken: $EXISTING_SYNC_TOKEN)"
else
    debug "No existing QBO Customer found. Preparing to create new record."
fi

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
    DisplayName: $display_name,
    CompanyName: $company_name,
    PrimaryEmailAddr: { Address: $email },
    PrimaryPhone: { FreeFormNumber: $phone },
    Notes: $notes,
    BillAddr: { Line1: $street, City: $city, CountrySubDivisionCode: $state, PostalCode: $zip }
  } 
  + (if $id != "" then {Id: $id, SyncToken: $sync_token} else {} end)')

QBO_POST_URI="/company/${QBO_REALMID}/customer"
debug "Posting Customer Payload to QBO..."
QBO_RESPONSE=$(echo "$QBO_PATCH_PAYLOAD" | qbo.sh POST "$QBO_POST_URI" || echo '{"Customer":{"Id":"Synced"}}')
QBO_CUSTOMER_ID=$(echo "$QBO_RESPONSE" | jq -r '.Customer.Id // "Synced"' || echo "Synced")

debug "QBO Sync complete. Id: $QBO_CUSTOMER_ID"

QBOSP_FILE="${HOME}/etc/${QBO_SANDBOX}qbosp.csv"
if [ -f "$QBOSP_FILE" ] && [ "$QBO_CUSTOMER_ID" != "Synced" ]; then
    echo "${QBO_CUSTOMER_ID}:${CLEAN_CLIENT_NAME}:${CLEAN_CLIENT_NAME} - SHARED:::" >> "$QBOSP_FILE"
    debug "Appended $QBO_CUSTOMER_ID to $QBOSP_FILE"
fi

# ==============================================================================
# BRANCHING POINT: EXISTING CLIENT PROFILE HEALING
# ==============================================================================
if [ "$IS_NEW_LEAD" != "true" ]; then
    debug "Executing Profile Healing notification via m365 CLI..."
    
    EMAIL_BODY="<p><b>Updated by:</b> ${RESPONDER}</p>\
    <h1 style='color:#0369a1;'>QBO Profile Healed / Updated</h1>\
    <p>\
    <b>Legal Name:</b> ${CLEAN_CLIENT_NAME}<br>\
    <b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
    <b>Email address:</b> ${CLIENT_EMAIL}<br>\
    <b>Phone number:</b> ${CLIENT_PHONE}<br>\
    <b>Entity Classification:</b> ${ENTITY_TYPE}<br><br>\
    <b>QBO Sync ID:</b> ${QBO_CUSTOMER_ID}\
    </p>"

    m365 outlook mail send \
      --subject "🟢 Profile Healed/Updated: ${CLEAN_CLIENT_NAME}" \
      --to "glmck13@gmail.com" \
      --bodyContents "$EMAIL_BODY" \
      --bodyContentType "HTML" >&2 || true

    debug "Profile Healing complete. Exiting."
    echo "{\"status\": \"success\", \"is_new_lead\": false, \"qbo_id\": \"$QBO_CUSTOMER_ID\", \"message\": \"Profile for ${CLEAN_CLIENT_NAME} healed successfully.\"}"
    exit 0
fi

# ==============================================================================
# NEW CLIENT PROVISIONING ONLY (IS_NEW_LEAD="true")
# ==============================================================================

# STEP 2: SHAREPOINT CLIENT FOLDER GENERATION
debug "Creating SharePoint folders..."
SHARE_ROOT_PATH="Shared Documents/${CLEAN_CLIENT_NAME} - SHARED"
m365 spo folder add --webUrl "$SHARE_SITE" --parentFolderUrl "Shared Documents" --name "${CLEAN_CLIENT_NAME} - SHARED" >&2 || true

# Note: stdout is captured by jq, while m365's stderr streams straight to Apache log
SHARE_FOLDER_ITEM_ID=$(m365 spo folder get --webUrl "$SHARE_SITE" --folderUrl "$SHARE_ROOT_PATH" -o json 2>/dev/null | jq -r '.ListItemAllFields.ID // empty')

for subfolder in "${SHARED_FOLDERS[@]}"; do
  m365 spo folder add --webUrl "$SHARE_SITE" --parentFolderUrl "$SHARE_ROOT_PATH" --name "$subfolder" >&2 || true
done

COMPANY_ROOT_PATH="Shared Documents/${CLEAN_CLIENT_NAME}"
m365 spo folder add --webUrl "$COMPANY_SITE" --parentFolderUrl "Shared Documents" --name "$CLEAN_CLIENT_NAME" >&2 || true

for subfolder in "${COMPANY_FOLDERS[@]}"; do
  m365 spo folder add --webUrl "$COMPANY_SITE" --parentFolderUrl "$COMPANY_ROOT_PATH" --name "$subfolder" >&2 || true
done

# STEP 3: COPY LOGFILE TEMPLATE & UPDATE METADATA
debug "Copying log file template '$LOGFILE_NAME'..."
m365 spo file copy \
  --webUrl "$SHARE_SITE" \
  --sourceUrl "/sites/TarrantAdvisorsShare/Shared Documents/Client Log Template.xlsx" \
  --targetUrl "/sites/Company/Shared Documents/${CLEAN_CLIENT_NAME}/${LOGFILE_NAME}" >&2 || true

LOGFILE_LINK="${COMPANY_SITE}/Shared Documents/${CLEAN_CLIENT_NAME}/${LOGFILE_NAME}"

if [ -n "$SHARE_FOLDER_ITEM_ID" ]; then
    m365 spo listitem set \
      --webUrl "$SHARE_SITE" \
      --listTitle "Shared Documents" \
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
<b>Entity Classification: </b>${ENTITY_TYPE}<br><br>
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
  --folderUrl "$COMPANY_ROOT_PATH" \
  --path "$HTML_TEMP_FILE" \
  --fileName "Client Intake Form.html" >&2 || true

rm -f "$HTML_TEMP_FILE"

# STEP 5: SEND NOTIFICATION EMAIL VIA M365 CLI
debug "Sending team notification email via m365 CLI..."

EMAIL_BODY="<p><b>Submitted by:</b> ${RESPONDER}</p>\
<h1 style='color:#0078d4;'>Client Info:</h1>\
<p>\
<b>Name:</b> ${CLEAN_CLIENT_NAME}<br>\
<b>Contact Name:</b> ${FRIENDLY_NAME}<br>\
<b>Email address:</b> ${CLIENT_EMAIL}<br>\
<b>Phone number:</b> ${CLIENT_PHONE}<br>\
<b>Contact date:</b> ${CONTACT_DATE}<br>\
<b>Entity Classification:</b> ${ENTITY_TYPE}<br><br>\
<b>QBO Sync ID:</b> ${QBO_CUSTOMER_ID}\
</p>\
<h1>To do:</h1>\
<ul>\
<li>Add client to Revenue Schedule: ${CLEAN_CLIENT_NAME}</li>\
<li>Create TA Tax Agreement</li>\
<li>Share folder w/ client (and tax organizer if needed)</li>\
<li>Add client to ProConnect only after tax return has been received for download</li>\
</ul>"

m365 outlook mail send \
  --subject "✨ New Client Intake submitted on Tarrant Advisors: ${CLEAN_CLIENT_NAME}" \
  --to "glmck13@gmail.com" \
  --bodyContents "$EMAIL_BODY" \
  --bodyContentType "HTML" >&2 || true

debug "=== Client provisioning complete for '$CLEAN_CLIENT_NAME' ==="

# RETURN SUCCESS JSON TO FETCH CALL
echo "{\"status\": \"success\", \"is_new_lead\": true, \"qbo_id\": \"$QBO_CUSTOMER_ID\", \"message\": \"New client ${CLEAN_CLIENT_NAME} provisioned successfully.\"}"
