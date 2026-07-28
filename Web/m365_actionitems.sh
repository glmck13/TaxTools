#!/bin/bash

# Configuration
export REPORT_FILE="/var/www/tarrantadvisors/reports/ActionItems.html"
export SHARED_SITE="/sites/TarrantAdvisorsShare"
export COMPANY_SITE="/sites/Company"
export TENANT_URL="https://tarrantadvisors.sharepoint.com" 
export BASE_FOLDER="/Shared Documents"
export LOGIDS_FILE="Client Log UniqueIds.txt"
export CONCURRENCY=15

export AUTH_TOKEN=$(m365 util accesstoken get --resource "$TENANT_URL" --output text)

process_file() {
    local file_id="$1"
    local name="$2"
    name=${name##*/}
    
    #echo "[$(date +%T)] Downloading: $name" >&2
    
    curl -sSL -g \
        -H "Authorization: Bearer $AUTH_TOKEN" \
        -o "$name" \
        "${TENANT_URL}${COMPANY_SITE}/_api/web/GetFileById('${file_id}')/\$value"
    
    if [ $? -eq 0 ] && [ -s "$name" ]; then
        xlsx2csv "$name" >"${name%.*}.csv" 2>/dev/null
        #echo "[$(date +%T)] Finished: $name" >&2
        rm "$name"
    else
        # If curl saved the XML error message, let's see what happened
        if grep -q "m:error" "$name" 2>/dev/null; then
            echo "Error: SharePoint API rejected request for $name" >&2
        else
            echo "Error: Failed to download $name" >&2
        fi
        [ -f "$name" ] && rm "$name"
    fi
}

export -f process_file

WORKING_DIR=$(mktemp -d); cd $WORKING_DIR

#m365 spo file get --webUrl "${TENANT_URL}${SHARED_SITE}" --url "${BASE_FOLDER}/${LOGIDS_FILE}" --asFile --path ids.txt
m365 spo search --webUrl "${TENANT_URL}${COMPANY_SITE}" --queryText 'filename:log* fileextension:xlsx IsDocument:1' --selectProperties "Title,UniqueId,OriginalPath" --allResults --query "[?starts_with(Title, 'Log-') || starts_with(Title, 'log-')].{Name: Title, UUID: UniqueId, URL: OriginalPath}" -o json  | jq -c -r ".[] | select(.URL | contains(\"${COMPANY_SITE}\")) | [.UUID, .URL]" | sed -e 's/^...//' -e 's/..$//' -e 's?.","https://.*/sites/?|/sites/?' >ids.txt

cat ids.txt | xargs -d '\n' -I {} -P "$CONCURRENCY" bash -c '
    line="{}"
    url=${line%|*}
    name=${line#*|}
    [ "$url" -a "$name" ] && process_file "$url" "$name"
'

echo -e "Content-Type: text/html\n"

(
echo "<html><head><title>Action Item Report</title><link rel=\"stylesheet\" href=\"/css/style.min.css\"></link><body>"
echo "<h1>Action Items</h1>"
echo "<p><b>Report created: $(date)</b></p>"
echo "<table><tr><th style=\"width: 300px; text-align: left;\">File</th><th style=\"width: 120px; text-align: left;\">Date</th><th style=\"text-align: left;\">Description</th></tr>"
grep -i ,action *.csv | while read line
do
	log=${line%%:*} line=${line#*:}
	date=${line%%,,*} line=${line#*,,}
	year=${line%%,,*} line=${line#*,,}
	type=${line%%,,*} line=${line#*,,}
	description=${line%%,,*} line=${line#*,,}
	echo "<tr><td style=\"width: 300px; text-align: left;\">${log%.*}.xlsx</td><td style=\"width: 120px; text-align: left;\">${date}</td><td style=\"text-align: left;\">${description}</td></tr>"
done
echo "</table><p>&nbsp;</p></body></html>"
) | tee $REPORT_FILE

cd - >/dev/null; rm -fr $WORKING_DIR
