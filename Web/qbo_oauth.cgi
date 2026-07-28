#!/bin/bash

vars="$QUERY_STRING"
while [ "$vars" ]
do
	IFS='&' read -r v vars <<<${vars}
	[ "$v" ] && export $v
done

TOKENFILE=$(urlencode -d $state)
[ -f $TOKENFILE ] && . $TOKENFILE

LOCKFILE=${TOKENFILE%/*}/qboTokens.lock
exec 200>$LOCKFILE

flock -x 200

AUTH=$(echo -n "$QBO_CLIENT:$QBO_SECRET" | base64 -w0)
REDIR=$(urlencode "$QBO_CALLBACK")
json=$(curl -s -H "Authorization: Basic $AUTH" -H "x-include-refresh-token-hard-expires-in: true" -d "grant_type=authorization_code&code=$code&redirect_uri=$REDIR" "$QBO_TOKEN_SERVER")

refresh_token=$(jq -r .refresh_token <<<${json})
access_token=$(jq -r .access_token <<<${json})

sed -i \
	-e "s/\(QBO_REFRESH_TOKEN=\).*/\1\"${refresh_token}\"/" \
	-e "s/\(QBO_ACCESS_TOKEN=\).*/\1\"${access_token}\"/" \
$TOKENFILE

flock -u 200

echo -e "Content-type: text/html\n"
echo "<html>"
echo "<pre>"
jq . <<<${json}
echo "</pre>"
echo "</html>"
