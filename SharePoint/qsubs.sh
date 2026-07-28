#!/bin/bash

site="https://tarrantadvisors.sharepoint.com/sites/TarrantAdvisorsShare"

export TOKEN=$(az account get-access-token --resource https://forms.office.com --query accessToken --output tsv)
export TENANT=$(az account show --query tenantId -o tsv)
export USERID=$(az ad signed-in-user show --query id -o tsv)

./${0%.*}.py | while read q
do
	f=$(grep -i "$q" users.txt) f=${f%:*}
	[ "$f" ] || continue

	uid=$(m365 spo folder get --webUrl "$site" --url "/Shared Documents/$f" -o json | jq -r .UniqueId)
	md=$(m365 spo listitem get --webUrl "$site" --listTitle "Documents" --uniqueId "$uid" -o json)

	val=$(jq -r .Questionnaire <<<${md})
	[ "$val" = "Submitted" ] && continue
	[ "$val" = "Form" ] && continue

	id=$(jq -r .Id <<<${md})
	val=$(m365 spo listitem set --webUrl "$site" --listTitle "Documents" --id "$id" --Questionnaire "Form" -o json | jq -r .Questionnaire)
	echo "$q: $f: $id: $val"
done
