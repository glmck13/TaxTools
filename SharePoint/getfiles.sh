#!/bin/bash

#
# Add --recursive, --fields, --verbose
#
site=${1:?Enter site name}
folder=$2
m365 spo file list --webUrl "/sites/$site" --folderUrl "Shared Documents/$folder" $M365OPTS
