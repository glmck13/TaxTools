#!/bin/bash
set -e

# Force Sandbox environment to resolve sandbox-qboTokens.conf
export QBO_SANDBOX="sandbox-"

EXPORT_DIR="./qbo_export"
MAPPING_FILE="$EXPORT_DIR/id_mapping.json"

# CONFIGURABLE SAFETY OVERRIDE: Redirects all customer emails to sandbox testing
SANDBOX_OVERRIDE_EMAIL="katie@tarrantadvisors.com"

if [ ! -d "$EXPORT_DIR" ]; then
    echo "❌ Error: Directory $EXPORT_DIR does not exist. Run export_qbo.sh first."
    exit 1
fi

echo "=== Initializing ID Mapping File ==="
echo '{"customers": {}, "services": {}}' > "$MAPPING_FILE"

echo "=== Resolving Sandbox Income Account ==="
# Search for any active Income account in Sandbox
SANDBOX_INCOME_ACCT_ID=$(qbo.sh GET '/company/${QBO_REALMID}/query' "query=select Id, AccountType from Account maxresults 100" | jq -r '.QueryResponse.Account[]? | select(.AccountType | contains("Income")) | .Id' | head -n 1)

if [ -z "$SANDBOX_INCOME_ACCT_ID" ]; then
    echo "❌ Error: Could not find any active Income Account in Sandbox."
    echo "Please create a Service/Fee Income account in Sandbox first."
    exit 1
fi

echo "Using Sandbox Income Account ID: $SANDBOX_INCOME_ACCT_ID"

echo "=== Processing & Importing Service Items ==="
while read -r item; do
    [ -z "$item" ] && continue
    prod_id=$(echo "$item" | jq -r '.Id')
    name=$(echo "$item" | jq -r '.Name')
    
    # Strip read-only metadata, sub-item references, and assign the Sandbox Income Account ID
    clean_item=$(echo "$item" | jq --arg inc_id "$SANDBOX_INCOME_ACCT_ID" '
        del(.Id, .SyncToken, .MetaData, .domain, .sparse, .FullyQualifiedName, .SubItem, .ParentRef) |
        .IncomeAccountRef = {"value": $inc_id}
    ')
    
    echo "Importing Service Item: $name (Prod ID: $prod_id)"
    
    # Capture both output and error streams for debugging
    response=$(echo "$clean_item" | qbo.sh POST '/company/${QBO_REALMID}/item' 2>&1 || true)
    
    sandbox_id=$(echo "$response" | jq -r '.Item.Id // empty')
    if [ -n "$sandbox_id" ] && [ "$sandbox_id" != "null" ]; then
        echo "  ↳ Assigned Sandbox ID: $sandbox_id"
        tmp_map=$(jq --arg p "$prod_id" --arg s "$sandbox_id" '.services[$p] = $s' "$MAPPING_FILE")
        echo "$tmp_map" > "$MAPPING_FILE"
    else
        echo "  ⚠️ Warning: Could not capture Sandbox ID for service item: $name"
        echo "  🔍 API Response / Error: $response"
    fi
done < <(jq -c '.QueryResponse.Item[]? | select(.Active != false and .Type == "Service")' "$EXPORT_DIR/raw_service_items.json")

echo "=== Processing & Importing Customers ==="
while read -r customer; do
    [ -z "$customer" ] && continue
    prod_id=$(echo "$customer" | jq -r '.Id')
    display_name=$(echo "$customer" | jq -r '.DisplayName')
    
    # Strip read-only metadata, override PrimaryEmailAddr, and sanitize embedded emails in JSON Notes
    clean_customer=$(echo "$customer" | jq --arg email "$SANDBOX_OVERRIDE_EMAIL" '
        del(.Id, .SyncToken, .MetaData, .domain, .sparse, .FullyQualifiedName, .Balance, .BalanceWithJobs, .CurrenciesResponse, .CustomerTypeRef, .SalesTermRef, .PaymentMethodRef) |
        .PrimaryEmailAddr = {"Address": $email} |
        if (.Notes != null and .Notes != "") then
            .Notes = (
                try (
                    (.Notes | fromjson) |
                    if .signers then
                        .signers |= map(if .email then .email = $email else . end)
                    else . end |
                    tojson
                ) catch .Notes
            )
        else . end
    ')
    
    echo "Importing Customer: $display_name (Prod ID: $prod_id) [Emails -> $SANDBOX_OVERRIDE_EMAIL]"
    
    # Capture both output and exit status or inspect error response
    response=$(echo "$clean_customer" | qbo.sh POST '/company/${QBO_REALMID}/customer' 2>&1 || true)
    
    sandbox_id=$(echo "$response" | jq -r '.Customer.Id // empty')
    if [ -n "$sandbox_id" ] && [ "$sandbox_id" != "null" ]; then
        echo "  ↳ Assigned Sandbox ID: $sandbox_id"
        tmp_map=$(jq --arg p "$prod_id" --arg s "$sandbox_id" '.customers[$p] = $s' "$MAPPING_FILE")
        echo "$tmp_map" > "$MAPPING_FILE"
    else
        echo "  ⚠️ Warning: Could not capture Sandbox ID for customer: $display_name"
        echo "  🔍 API Response / Error: $response"
    fi
done < <(jq -c '.QueryResponse.Customer[]? | select(.Active != false)' "$EXPORT_DIR/raw_customers.json")

echo "=== Import Complete ==="
echo "📁 ID mapping successfully saved to $MAPPING_FILE"