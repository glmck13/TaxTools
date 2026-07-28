#!/bin/bash

cat - <<EOF | curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @- "https://forms.office.com/formapi/api/$TENANT/users/$USERID/forms" 
{
  "title": "API Generated Form",
  "description": "This form was built using curl",
  "questions": [
    {
      "id": "r$(uuid -v4 | sed -e 's/-//g')",
      "title": "",
      "subtitle": null,
      "type": "Question.ColumnGroup",
      "order": 1000500.0
    },
    {
      "id": "r$(uuid -v4 | sed -e 's/-//g')",
      "type": "Question.Choice",
      "title": "What is your gender?",
      "order": 2000500.0,
      "questionInfo": "{\"Choices\":[{\"Description\":\"Male\"},{\"Description\":\"Female\"},{\"Description\":\"Prefer not to say\"}]}"
    },
    {
      "id": "r$(uuid -v4 | sed -e 's/-//g')",
      "title": "",
      "subtitle": null,
      "type": "Question.ColumnGroup",
      "order": 3000500.0
    },
    {
      "id": "r$(uuid -v4 | sed -e 's/-//g')",
      "type": "Question.TextField",
      "title": "Please provide your feedback",
      "order": 4000500.0
    }
  ]
}
EOF
