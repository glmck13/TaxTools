#!/bin/bash

[ "$REDIRECT" = "true" ] && exit

. ~www-data/cgi/qbo.cgi
. ~www-data/cgi/m365.cgi

# ==========================================
# Configuration Variables
# ==========================================
SPO_SITE_URL="https://tarrantadvisors.sharepoint.com/sites/Company"
SPO_LIST_NAME="QBO Clients"

# Temporary files for processing
QBO_DATA=$(mktemp)
QBO_KEYS=$(mktemp)
SPO_RAW=$(mktemp)
SPO_KEYS=$(mktemp)

echo "Starting QBO to SharePoint Client Sync..."

# ==========================================
# 1. Fetch QBO Active Customers
# ==========================================
echo "Fetching active customers and emails from QBO..."
# We use TSV format so we can keep the DisplayName(Id) and Email paired together safely.
# (.PrimaryEmailAddr.Address // "") ensures that if a client has no email, it outputs a blank space instead of "null".
qbo.sh GET '/company/$QBO_REALMID/query' 'query=select * from Customer WHERE Active = true MAXRESULTS 1000' \
    | jq -r '.QueryResponse.Customer[] | ["\(.DisplayName) (\(.Id))", (.PrimaryEmailAddr.Address // "")] | @tsv' > "$QBO_DATA"

cat - <<EOF >>"$QBO_DATA"
Non-Client - General & Administrative
Non-Client - Practice Development
EOF

# Extract just the unique "DisplayName (Id)" strings to use as our comparison keys
cut -f1 "$QBO_DATA" | sort -u > "$QBO_KEYS"

# ==========================================
# 2. Fetch SharePoint List Items
# ==========================================
echo "Fetching items from SharePoint list: $SPO_LIST_NAME..."
# We pull the raw JSON. The internal name for "Client (QBO)" is standardly "Title".
m365 spo listitem list --webUrl "$SPO_SITE_URL" --listTitle "$SPO_LIST_NAME" --output json > "$SPO_RAW"

# Parse out the unique "Title" strings to a sorted text file
jq -r '.[].Title' "$SPO_RAW" | sort -u > "$SPO_KEYS"

# ==========================================
# 3. Process Additions
# ==========================================
echo "Calculating additions..."

# comm -23 outputs lines unique to QBO (Needs to be ADDED)
comm -23 "$QBO_KEYS" "$SPO_KEYS" | while IFS= read -r NEW_CLIENT; do
    if [ -n "$NEW_CLIENT" ]; then
        # Look up the corresponding email from our QBO_DATA TSV file
        EMAIL=$(awk -F'\t' -v key="$NEW_CLIENT" '$1==key {print $2}' "$QBO_DATA")
        
        echo "Adding new client: $NEW_CLIENT"
        
        # If the email isn't blank, include it in the m365 command
        if [ -n "$EMAIL" ]; then
            m365 spo listitem add --webUrl "$SPO_SITE_URL" --listTitle "$SPO_LIST_NAME" --Title "$NEW_CLIENT" --field_1 "$EMAIL"
        else
            m365 spo listitem add --webUrl "$SPO_SITE_URL" --listTitle "$SPO_LIST_NAME" --Title "$NEW_CLIENT"
        fi
    fi
done

# ==========================================
# 4. Process Deletions
# ==========================================
echo "Calculating deletions..."

# comm -13 outputs lines unique to SPO (Needs to be DELETED)
comm -13 "$QBO_KEYS" "$SPO_KEYS" | while IFS= read -r OLD_CLIENT; do
    if [ -n "$OLD_CLIENT" ]; then
        echo "Removing outdated client: $OLD_CLIENT"
        
        # Look up ALL Item IDs associated with this outdated client string
        ITEM_IDS=$(jq -r ".[] | select(.Title == \"$OLD_CLIENT\") | .Id" "$SPO_RAW")
        
        for ITEM_ID in $ITEM_IDS; do
            if [ -n "$ITEM_ID" ]; then
                # Delete the item without prompting for confirmation
                m365 spo listitem remove --webUrl "$SPO_SITE_URL" --listTitle "$SPO_LIST_NAME" --id "$ITEM_ID" --confirm
            fi
        done
    fi
done

# ==========================================
# Cleanup
# ==========================================
rm "$QBO_DATA" "$QBO_KEYS" "$SPO_RAW" "$SPO_KEYS"
echo "Sync complete!"
