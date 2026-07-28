#!/bin/bash

site=${1:?Enter site name}

m365 spo folder list --webUrl "/sites/$site" --parentFolderUrl "Shared Documents" -o json | jq -r .[].ServerRelativeUrl | while read folder
do
	echo "$folder:$(m365 spo folder sharinglink list --webUrl "/sites/$site" --folderUrl "$folder" -o json | jq -r '[.[].grantedToIdentitiesV2[].user.email] | join(",")')"
done
