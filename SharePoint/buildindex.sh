#!/bin/bash

[ "$REDIRECT" = "true" ] && exit

. ~www-data/cgi/m365.cgi

for s in "" "/sites/TarrantAdvisorsShare" "/sites/Company"
do

# 1. Define the variables and export them
export site="https://tarrantadvisors.sharepoint.com${s}"
echo "Indexing $site..."

echo "Fetching all list items to build the index map..."
# Fetch the Id, UniqueId, and current Index for ALL items in one go
listitems=$(m365 spo listitem list --webUrl "$site" --listTitle "Documents" --fields "Id,UniqueId,Index" -o json)

# Create an associative array (dictionary) to map UniqueId -> "Id|CurrentIndex"
declare -A item_map
while IFS=$'\t' read -r uid id idx; do
	item_map["$uid"]="$id|$idx"
done < <(echo "$listitems" | jq -r '.[] | "\(.UniqueId)\t\(.Id)\t\(.Index // "")"')

echo "Fetching folders from Shared Documents..."
folders=$(m365 spo folder list --webUrl "$site" --parentFolderUrl "/Shared Documents" -o json)

echo "Fetching files from Shared Documents..."
files=$(m365 spo file list --webUrl "$site" --folderUrl "/Shared Documents" -o json)

# 2. Define the minimal update function and export it BEFORE xargs uses it
update_item() {
	IFS='|' read -r id group name type <<< "$1"
	
	val=$(m365 spo listitem set --webUrl "$site" --listTitle "Documents" --id "$id" --Index "$group" -o json 2>/dev/null | jq -r .Index)
	if [[ -n "$val" && "$val" != "null" ]]; then
		echo "$name ($type): ID $id: Index updated to $val"
	else
		echo "$name ($type): ID $id: Failed to update"
	fi
}
export -f update_item

echo "Calculating required updates and applying them with up to 15 workers..."

# 3. Process locally and pipe null-terminated strings DIRECTLY to xargs
{
	# Process Folders
	while IFS=$'\t' read -r name uid; do
		[[ "$name" == "Forms" ]] && continue
		
		first_char="${name:0:1}"
		first_char="${first_char^^}"
		case "$first_char" in
			[A-C]) group="ABC" ;;
			[D-F]) group="DEF" ;;
			[G-I]) group="GHI" ;;
			[J-L]) group="JKL" ;;
			[M-O]) group="MNO" ;;
			[P-S]) group="PQRS" ;;
			[T-V]) group="TUV" ;;
			[W-Z]) group="WXYZ" ;;
			*)     group="0-9" ;;
		esac

		map_val="${item_map["$uid"]}"
		if [[ -n "$map_val" ]]; then
			id="${map_val%|*}"
			current_index="${map_val#*|}"
			
			if [[ "$current_index" != "$group" ]]; then
				# Needs update: print directly to pipeline (null-terminated)
				printf "%s|%s|%s|folder\0" "$id" "$group" "$name"
			else
				# Matches: print to stderr so the user sees it, but xargs doesn't
				#echo "$name (folder): Already set to $group (Skipping)" >&2
				:
			fi
		fi
	done < <(echo "$folders" | jq -r '.[] | "\(.Name)\t\(.UniqueId)"')

	# Process Files
	while IFS=$'\t' read -r name uid; do
		group="[File]"
		map_val="${item_map["$uid"]}"
		
		if [[ -n "$map_val" ]]; then
			id="${map_val%|*}"
			current_index="${map_val#*|}"
			
			if [[ "$current_index" != "$group" ]]; then
				# Needs update: print directly to pipeline (null-terminated)
				printf "%s|%s|%s|file\0" "$id" "$group" "$name"
			else
				#echo "$name (file): Already set to $group (Skipping)" >&2
				:
			fi
		fi
	done < <(echo "$files" | jq -r '.[] | "\(.Name)\t\(.UniqueId)"')
	
} | xargs -0 -r -n 1 -P 15 bash -c 'update_item "$1"' _

echo -e "Index update complete for ${site}!\n"

done
