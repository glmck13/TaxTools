#!/bin/bash

TOKENFILE=$(type -p $0)
TOKENFILE=${TOKENFILE%/bin/*}/etc/${ADOBE_SANDBOX}adobeTokens.conf

EXPIRED=3500 # leaves a little time!
AGE=$(( $(date +%s) - $(date -r $TOKENFILE +%s) ))
if [ $AGE -le $EXPIRED ]; then
        echo "Token only $AGE seconds old, still good!"
        exit
fi

. $TOKENFILE

LOCKFILE=${TOKENFILE%/*}/adobeTokens.lock
exec 200>$LOCKFILE

flock -x 200

json=$(curl -s -d "grant_type=refresh_token&refresh_token=$ADOBE_REFRESH_TOKEN&client_id=$ADOBE_CLIENT&client_secret=$ADOBE_SECRET" "$ADOBE_REFRESH_SERVER")

access_token=$(jq -r .access_token <<<${json})

if [ "$access_token" -a "$access_token" != "null" ]; then
sed -i \
	-e "s/\(ADOBE_ACCESS_TOKEN=\).*/\1\"${access_token}\"/" \
$TOKENFILE
fi

flock -u 200

jq . <<<${json}
