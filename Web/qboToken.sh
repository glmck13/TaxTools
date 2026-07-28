#!/bin/bash

TOKENFILE=$(type -p $0)
TOKENFILE=${TOKENFILE%/bin/*}/etc/${QBO_SANDBOX}qboTokens.conf
. $TOKENFILE

echo "$QBO_CONNECT_SERVER?client_id=$QBO_CLIENT&response_type=code&scope=$QBO_SCOPE&redirect_uri=$(urlencode "$QBO_CALLBACK")&state=$(urlencode $TOKENFILE)"
