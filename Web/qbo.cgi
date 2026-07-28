#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=$HOME/bin:$PATH

SANDBOX=$(echo "$QUERY_STRING" | sed -n 's/.*sandbox=\([^&]*\).*/\1/p')
if [ "$SANDBOX" ]; then
export QBO_SANDBOX="sandbox-"
export ADOBE_SANDBOX="sandbox-"
export ENGAGEMENT_SANDBOX="sandbox-"
fi

qboRefresh.sh >/dev/null
. ${HOME}/etc/${QBO_SANDBOX}qboTokens.conf

adobeRefresh.sh >/dev/null
. ${HOME}/etc/${ADOBE_SANDBOX}adobeTokens.conf

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then REDIRECT=true ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then REDIRECT=true ${0%.*}.py
fi
