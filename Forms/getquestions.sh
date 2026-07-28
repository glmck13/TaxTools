#!/bin/bash

curl -s "https://forms.office.com/formapi/api/${TENANT}/users/${USERID}/light/forms('${1:?}')?\$expand=questions" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/json" | jq -r '.questions[] | [.order, .id, .title] | join(",")' | sort -k1 -t, -n
