#!/bin/bash

# ==========================================
# Configuration Variables
# ==========================================
EXPORT_DIR="./flow_definitions"

# Create export directory if it doesn't exist
mkdir -p "$EXPORT_DIR"

echo "Fetching the default Power Automate environment..."
# This grabs the first environment. If you have a specific environment, 
# you can hardcode ENV_NAME="Default-your-tenant-guid"
ENV_NAME=$(m365 flow environment list -o json | jq -r '.[0].name')

echo "Fetching flows for environment: $ENV_NAME..."
FLOWS=$(m365 flow list --environmentName "$ENV_NAME" -o json)

echo "Extracting and downloading flows..."
# Loop through each flow object using jq
echo "$FLOWS" | jq -c '.[]' | while read -r flow; do
    
    # Extract Flow ID and Display Name
    FLOW_ID=$(echo "$flow" | jq -r '.name')
    
    # Sanitize the display name for a safe filename (replaces spaces/special chars with underscores)
    RAW_NAME=$(echo "$flow" | jq -r '.properties.displayName')
    SAFE_NAME=$(echo "$RAW_NAME" | sed -e 's/[^A-Za-z0-9._-]/_/g')

    echo "Processing: $RAW_NAME ($FLOW_ID)"

    # Set the direct JSON output path
    JSON_PATH="$EXPORT_DIR/${SAFE_NAME}_definition.json"

    # Export the flow directly as a JSON definition
    m365 flow export --environmentName "$ENV_NAME" --name "$FLOW_ID" --format json --path "$JSON_PATH"

    if [ -f "$JSON_PATH" ]; then
	# Pretty-print the JSON using a temporary file
	jq . "$JSON_PATH" > "${JSON_PATH}.tmp" && mv "${JSON_PATH}.tmp" "$JSON_PATH"

        echo "   -> Successfully saved ${SAFE_NAME}_definition.json"
    else
        echo "   -> Error: Failed to export $RAW_NAME"
    fi
done

echo "Script complete! Your definitions are ready to be committed to GitHub."
