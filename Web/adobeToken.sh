#!/bin/bash

TOKENFILE=$(type -p $0)
TOKENFILE=${TOKENFILE%/bin/*}/etc/${ADOBE_SANDBOX}adobeTokens.conf
. $TOKENFILE

echo "$ADOBE_CONNECT_SERVER?client_id=$ADOBE_CLIENT&response_type=code&scope=$ADOBE_SCOPE&redirect_uri=$(urlencode "$ADOBE_CALLBACK")&state=$(urlencode $TOKENFILE)"
