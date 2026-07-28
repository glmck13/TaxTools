#!/bin/bash

curl -s "https://forms.office.com/formapi/api/${TENANT}/users/${USERID}/light/forms" \
     -H "Authorization: Bearer ${TOKEN}" \
     -H "Content-Type: application/json" | jq -r '.value[] | [.title, .id] | join(",")'
