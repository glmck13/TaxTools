#!/bin/bash

TOKENFILE=$(type -p $0)
TOKENFILE=${TOKENFILE%/bin/*}/etc/${QBO_SANDBOX}qboTokens.conf

EXPIRED=3500 # leaves a little time!
AGE=$(( $(date +%s) - $(date -r $TOKENFILE +%s) ))
if [ $AGE -le $EXPIRED ]; then
	echo "Token only $AGE seconds old, still good!"
	exit
fi

. $TOKENFILE

LOCKFILE=${TOKENFILE%/*}/qboTokens.lock
exec 200>$LOCKFILE

flock -x 200

AUTH=$(echo -n "$QBO_CLIENT:$QBO_SECRET" | base64 -w0)
json=$(curl -s -H "Authorization: Basic $AUTH" -H "x-include-refresh-token-hard-expires-in: true" -d "grant_type=refresh_token&refresh_token=$QBO_REFRESH_TOKEN" "$QBO_TOKEN_SERVER")

refresh_token=$(jq -r .refresh_token <<<${json})
access_token=$(jq -r .access_token <<<${json})

if [ "$refresh_token" -a "$refresh_token" != "null" -a "$access_token" -a "$access_token" != "null" ]; then
sed -i \
	-e "s/\(QBO_REFRESH_TOKEN=\).*/\1\"${refresh_token}\"/" \
	-e "s/\(QBO_ACCESS_TOKEN=\).*/\1\"${access_token}\"/" \
$TOKENFILE
fi

flock -u 200

jq . <<<${json}
