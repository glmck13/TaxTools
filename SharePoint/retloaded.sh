#!/bin/ksh

echo "Copy 'returnstatus' API call, then hit enter when ready..." >&2
read x

wl-paste -t text/plain | xargs -0 printf '%b' >curl.sh
COOKIES=$(grep '^  *-b ' curl.sh) COOKIES=${COOKIES#*-b \'} COOKIES=${COOKIES%? *}
export COOKIES
TOKEN=$(grep '^  -H .authorization' curl.sh) TOKEN=${TOKEN#*-H *: } TOKEN=${TOKEN%? *}
export TOKEN

rm -f accept.txt
site="https://tarrantadvisors.sharepoint.com/sites/TarrantAdvisorsShare"

./${0%.*}.py | while read proconnect
do
	print $proconnect | IFS=' |,' read last first x
	n=0
	grep -i "/$last[^[:alnum:]]" users.txt | grep -i "[^[:alnum:]]$first[^[:alnum:]]" | while read line
	do
		let n=$n+1
		print "$n|$line|$proconnect"
	done
	if [ "$n" -le 0 ]; then
		n=100
		grep -i "/$last[^[:alnum:]]" users.txt | grep -i "[^[:alnum:]]${first%${first#?}}" | while read line
		do
			let n=$n+1
			print "$n|$line|$proconnect"
		done
	fi
	[ "$n" -le 0 ] && print "0|???|$proconnect"
done | sort -k3,3 -t'|' | tee accept.txt | while IFS='|' read n f p s
do
	[[ "$s" == Accepted\|Filed\ and\ Complete* ]] || continue

	u=${f#*:} f=${f%:*}
	[ "$u" ] || continue
	[ "$f" ] || continue
	[ "$n" -gt 1 ] && continue

	uid=$(m365 spo folder get --webUrl "$site" --url "/Shared Documents/$f" -o json | jq -r .UniqueId)
	md=$(m365 spo listitem get --webUrl "$site" --listTitle "Documents" --uniqueId "$uid" -o json)

	format=$(jq -r .Format <<<${md})
	[ "$format" = "Paper" ] && continue

	val=$(jq -r .RetLoaded <<<${md})
	[ "$val" = "Yes" ] && continue
	[ "$val" = "PC" ] && continue

	id=$(jq -r .Id <<<${md})
	val=$(m365 spo listitem set --webUrl "$site" --listTitle "Documents" --id "$id" --RetLoaded "PC" -o json | jq -r .RetLoaded)
	echo "$p: $f: $id: $format: $val"
done
