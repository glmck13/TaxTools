#!/bin/bash

m365 spo folder list --webUrl "/sites/TarrantAdvisorsShare" --parentFolderUrl "Shared Documents" -o json | jq -r '.[] | "\(.Name);\(.UniqueId)"' | while read line
do
	name=${line%;*} uid=${line#*;}
	echo -n "$name;"
	m365 spo listitem get --webUrl "/sites/TarrantAdvisorsShare" --listUrl "/Shared Documents" --uniqueId $uid -o json | jq -r '"\(.Questionnaire);\(.Format)"'
done
