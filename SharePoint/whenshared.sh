#!/bin/bash

SiteID=$(m365 spo site get --url https://tarrantadvisors.sharepoint.com/sites/TarrantAdvisorsShare --query "Id")
DriveID=$(m365 request --url "https://graph.microsoft.com/v1.0/sites/${SiteID}/drives" --method get --query "value[?name=='Documents'].id" --output text)

while read Name
do
	echo $Name
	FolderID=$(m365 spo folder get --webUrl https://tarrantadvisors.sharepoint.com/sites/TarrantAdvisorsShare --url "/Shared Documents/${Name}" --query "UniqueId")
	m365 spo folder sharinglink list --webUrl https://tarrantadvisors.sharepoint.com/sites/TarrantAdvisorsShare --folderUrl "/Shared Documents/${Name}" -o json | jq .[].grantedToIdentitiesV2[]
	m365 request --url "https://graph.microsoft.com/v1.0/drives/${DriveID}/items/${FolderID}/activities" --method get --all --output json
done
