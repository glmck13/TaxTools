#!/bin/bash

#
# Add --recursive, --fields, --verbose
#
site=${1:?Enter site name}
folder=$2
m365 spo folder list --webUrl "/sites/$site" --parentFolderUrl "Shared Documents/$folder" $M365OPTS
