#!/bin/bash

vars="$QUERY_STRING"
while [ "$vars" ]
do
	IFS='&' read -r v vars <<<${vars}
	[ "$v" ] && export $v
done

TOKENFILE=$(urlencode -d $state)
[ -f $TOKENFILE ] && . $TOKENFILE

LOCKFILE=${TOKENFILE%/*}/adobeTokens.lock
exec 200>$LOCKFILE

flock -x 200

REDIR=$(urlencode "$ADOBE_CALLBACK")
json=$(curl -s -d "grant_type=authorization_code&code=$code&redirect_uri=$REDIR&client_id=$ADOBE_CLIENT&client_secret=$ADOBE_SECRET" "$ADOBE_TOKEN_SERVER")

refresh_token=$(jq -r .refresh_token <<<${json})
access_token=$(jq -r .access_token <<<${json})

sed -i \
	-e "s/\(ADOBE_REFRESH_TOKEN=\).*/\1\"${refresh_token}\"/" \
	-e "s/\(ADOBE_ACCESS_TOKEN=\).*/\1\"${access_token}\"/" \
$TOKENFILE

flock -u 200

echo -e "Content-type: text/html\n"
echo "<html>"
echo "<pre>"
jq . <<<${json}
echo "</pre>"
echo "</html>"
