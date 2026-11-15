#!/usr/bin/env bash
set -euo pipefail

# Pre-flight dependency checks
for cmd in qbo.sh jq; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: Required command '$cmd' not found in PATH." >&2
        exit 1
    fi
done

# Single-quoted so ${QBO_REALMID} is passed literally and resolved inside qbo.sh via eval
QUERY_URI='/company/${QBO_REALMID}/query'
START_POS=1
PAGE_SIZE=1000

# Print colon-delimited CSV header
echo "qbo_id:client_name:friendly_name:primary_email:phone_number:co_signer_name:co_signer_email:entity_type:delivery_format:street:city:state:zip"

while true; do
    SQL_QUERY="select * from Customer where Active = true startposition ${START_POS} maxresults ${PAGE_SIZE}"

    # Fetch page of active customers via qbo.sh
    if ! RESPONSE=$(qbo.sh GET "$QUERY_URI" "query=${SQL_QUERY}"); then
        echo "Error: qbo.sh execution failed at startposition ${START_POS}." >&2
        exit 1
    fi

    # Validate JSON and check for QBO API Fault responses
    if ! jq -e . >/dev/null 2>&1 <<< "$RESPONSE"; then
        echo "Error: Invalid JSON returned by qbo.sh: ${RESPONSE}" >&2
        exit 1
    fi

    if jq -e '.Fault != null' >/dev/null 2>&1 <<< "$RESPONSE"; then
        FAULT_MSG=$(jq -r '.Fault.Error[0] | "\(.Message // "Unknown") - \(.Detail // "")"' <<< "$RESPONSE")
        echo "Error: QBO API Fault: ${FAULT_MSG}" >&2
        exit 1
    fi

    CUSTOMER_COUNT=$(jq -r '(.QueryResponse.Customer // []) | length' <<< "$RESPONSE")

    if [[ "$CUSTOMER_COUNT" -eq 0 ]]; then
        break
    fi

    jq -r '
      def unescape_html:
        gsub("&amp;|&#38;|&#x26;"; "&")
        | gsub("&apos;|&#39;|&#x27;"; "'"'"'")
        | gsub("&quot;|&#34;|&#x22;"; "\"")
        | gsub("&lt;|&#60;|&#x3c;"; "<")
        | gsub("&gt;|&#62;|&#x3e;"; ">");

      def trim:
        tostring | gsub("^\\s+|\\s+$"; "");

      def clean:
        trim
        | unescape_html
        | gsub("[\r\n]+"; " ")
        | gsub(":"; ";")
        | trim;

      def parse_notes:
        ((. // "") | trim) as $raw
        | if $raw == "" then {}
          else
            (try ($raw | fromjson) catch {}) as $parsed
            | if ($parsed | type) == "string" then (try ($parsed | trim | fromjson) catch {})
              elif ($parsed | type) == "object" then $parsed
              else {}
              end
          end;

      def normalize_entity:
        ((. // "") | trim | ascii_downcase) as $e
        | if ($e | IN("sm_llc", "s_corp", "partnership", "c_corp", "non_profit", "trust", "organization"))
          then $e
          else "individual"
          end;

      (.QueryResponse.Customer // [])[]
      | (.Notes | parse_notes) as $meta
      | (if ($meta.signers | type) == "array" then $meta.signers else [] end) as $signers
      | (if ($signers[0] | type) == "object" then $signers[0] else {} end) as $p_signer
      | (if ($signers[1] | type) == "object" then $signers[1] else {} end) as $c_signer
      | (($p_signer.email // "") | clean) as $p_email
      | (((.PrimaryEmailAddr.Address // "") | split(",")[0]) | clean) as $qbo_email
      | [
          (.Id // ""),
          (.DisplayName // ""),
          ($p_signer.name // ""),
          (if $p_email != "" then $p_email else $qbo_email end),
          (.PrimaryPhone.FreeFormNumber // ""),
          ($c_signer.name // ""),
          ($c_signer.email // ""),
          ($meta.entity | normalize_entity),
          (if (($meta.delivery_format // "") | trim | ascii_downcase) == "paper" then "paper" else "electronic" end),
          (.BillAddr.Line1 // ""),
          (.BillAddr.City // ""),
          (.BillAddr.CountrySubDivisionCode // ""),
          (.BillAddr.PostalCode // "")
        ]
      | map(clean)
      | join(":")
    ' <<< "$RESPONSE"

    if [[ "$CUSTOMER_COUNT" -lt "$PAGE_SIZE" ]]; then
        break
    fi

    START_POS=$((START_POS + PAGE_SIZE))
done
