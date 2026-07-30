#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=$HOME/bin:$PATH

export QBO_SANDBOX="sandbox-"
export ADOBE_SANDBOX="sandbox-"
export PIPELINE_SANDBOX="sandbox-"

qboRefresh.sh >/dev/null
. ${HOME}/etc/${QBO_SANDBOX}qboTokens.conf

adobeRefresh.sh >/dev/null
. ${HOME}/etc/${ADOBE_SANDBOX}adobeTokens.conf

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then REDIRECT=true ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then REDIRECT=true ${0%.*}.py
fi
