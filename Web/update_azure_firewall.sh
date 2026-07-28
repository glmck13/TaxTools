#!/bin/bash

PATH=$PATH:/usr/sbin

# --- Configuration ---
SET_NAME="azure_logic_apps"
TEMP_SET="azure_logic_apps_temp"
DETAILS_PAGE="https://www.microsoft.com/en-us/download/details.aspx?id=56519"
# Generating a random valid UUID for the ClientRequestId to prevent API rejection
GUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null)
O365_URL="https://endpoints.office.com/endpoints/worldwide?ClientRequestId=$GUID"
TARGET_PORT="443"

# Comprehensive core tags targeting both standard workflow layers and dependency clusters
TARGET_TAGS="LogicApps,AzureConnectors,PowerPlatformInfra,PowerPlatformPlex,AzureActiveDirectory,ApiManagement"

# --- 1. Network & Data Discovery ---
echo "Checking internet connectivity..."
until curl -sLI --connect-timeout 5 https://google.com -o /dev/null; do
  echo "Network not ready... retrying in 5 seconds."
  sleep 5
done

echo "Discovering latest Azure Service Tags URL..."
JSON_URL=$(curl -sL "$DETAILS_PAGE" | grep -Po 'https://download\.microsoft\.com/download/[^"]+ServiceTags_Public_[0-9]+\.json' | head -n 1)

if [ -z "$JSON_URL" ]; then
    echo "Error: Could not find download URL. Firewall was not modified."
    exit 1
fi

echo "Target Endpoint Identified: $JSON_URL"

# --- 2. Firewall Infrastructure Setup ---
echo "Data source confirmed. Initializing IP sets..."
ipset create $SET_NAME hash:net -exist
ipset create $TEMP_SET hash:net -exist
ipset flush $TEMP_SET

# --- 3 & 4. Population & Atomic Swap ---
echo "Downloading and batch-loading IPs into $TEMP_SET..."

# Pipeline 1: Azure Service Tags (Added -exist to the end of the add command)
curl -sL "$JSON_URL" | \
jq -r --arg tags "$TARGET_TAGS" '
  ($tags | split(",") | map(gsub(" "; ""))) as $allowed_tags |
  .values[] | 
  select(.name as $name | $allowed_tags | any($name == . or ($name | startswith(. + ".")))) | 
  .properties.addressPrefixes[] | 
  select(contains(":") | not) |
  (if contains("/") then . else . + "/32" end) |
  "add '"$TEMP_SET"' \(.) -exist"
' | \
ipset restore

# Pipeline 2: Microsoft 365 Endpoints (To cleanly include 52.104.0.0/14 and other O365 blocks)
curl -sL "$O365_URL" | \
jq -r '.[] | select(.ips) | .ips[] | select(contains(":") | not) | "add '"$TEMP_SET"' \(.) -exist"' | \
ipset restore

# Pipeline 3: Adobe Sign Webhook Production Subnets
# https://helpx.adobe.com/sign/system-requirements.html
echo "Injecting Adobe Sign Webhook IP Ranges..."
cat << 'EOF' | while read -r ip; do ipset add $TEMP_SET "$ip" -exist; done
4.152.152.80/28
4.152.152.112/28
4.152.152.160/28
4.152.153.16/28
4.152.153.64/28
4.152.153.224/28
4.152.154.0/28
4.152.154.48/28
4.152.154.80/28
4.152.154.96/28
4.152.154.176/28
4.152.154.224/28
4.152.155.64/28
4.152.155.96/28
20.7.230.176/28
20.7.230.192/28
20.1.216.176/28
20.1.217.128/28
20.1.217.224/28
20.1.217.240/28
20.1.218.0/28
20.1.218.16/28
20.1.218.64/28
20.1.218.80/28
20.1.218.192/28
20.1.218.208/28
20.1.219.0/28
20.1.219.16/28
20.1.219.32/28
20.1.219.48/28
20.1.219.96/28
20.1.219.112/28
4.246.0.0/28
4.246.0.16/28
4.246.0.32/28
4.246.0.48/28
4.246.0.64/28
4.246.0.80/28
4.246.0.96/28
4.246.0.112/28
4.246.0.128/28
4.246.0.144/28
20.36.220.138
20.36.222.77
20.94.104.176/28
20.94.104.240/28
20.94.105.160/28
20.94.105.208/28
20.94.105.240/28
20.94.105.32/28
20.94.105.96/28
20.94.106.16/28
20.94.106.160/28
20.94.106.176/28
20.94.106.192/28
20.94.106.208/28
20.94.106.224/28
20.94.106.240/28
20.94.107.176/28
20.94.107.96/28
20.115.199.160/28
20.115.199.176/28
20.115.199.192/28
20.115.199.208/28
20.115.199.224/28
20.115.199.240/28
34.214.40.128
35.162.126.140
44.212.163.32
52.1.219.111
52.33.110.59
52.36.18.134
52.36.239.65
52.37.6.204
52.44.57.50
52.73.234.82
54.161.158.12
100.25.241.25
EOF

# Check if the temp set actually got populated
COUNT=$(ipset list $TEMP_SET | grep -c '/')

if [ "$COUNT" -gt 0 ]; then
    echo "Swapping sets..."
    ipset swap $SET_NAME $TEMP_SET
    ipset destroy $TEMP_SET
else
    echo "Error: No IPs successfully loaded into stream. Aborting swap."
    ipset destroy $TEMP_SET
    exit 1
fi

# --- 5. Iptables Integration ---
RULE_SPEC="INPUT -m set --match-set $SET_NAME src -p tcp --dport $TARGET_PORT -j ACCEPT"

if ! iptables -C $RULE_SPEC 2>/dev/null; then
    echo "Applying iptables rule..."
    iptables -A $RULE_SPEC
else
    echo "Iptables rule already exists."
fi

echo "Firewall update complete. Current entry count: $(ipset list $SET_NAME | grep -c '/')"
