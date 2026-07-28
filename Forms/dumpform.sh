#!/bin/bash

curl "https://forms.office.com/formapi/api/${TENANT}/users/${USERID}/light/forms('${1:?}')?\$expand=questions" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/json" | python3 -m json.tool
