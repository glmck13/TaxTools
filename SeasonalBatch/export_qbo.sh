#!/bin/bash
set -e

# Force Production environment by clearing QBO_SANDBOX prefix
export QBO_SANDBOX=""

OUTPUT_DIR="./qbo_export"
mkdir -p "$OUTPUT_DIR"

echo "=== Pulling Service Items from Production QBO ==="
qbo.sh GET '/company/${QBO_REALMID}/query' "query=select * from Item where Type='Service' maxresults 1000" > "$OUTPUT_DIR/raw_service_items.json"

echo "=== Pulling Active Customers from Production QBO ==="
qbo.sh GET '/company/${QBO_REALMID}/query' "query=select * from Customer where Active=true maxresults 1000" > "$OUTPUT_DIR/raw_customers.json"

echo "✅ Export complete. Saved to $OUTPUT_DIR/"