#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=$HOME/bin:$PATH

SANDBOX=$(echo "$QUERY_STRING" | sed -n 's/.*sandbox=\([^&]*\).*/\1/p')
if [ "$SANDBOX" ]; then
export ADOBE_SANDBOX="sandbox-"
export SP_WEB_URL="https://tarrantadvisors.sharepoint.com"
export QBOSP_MATCH_FILE="../etc/sandbox-qbosp.csv"
fi

adobeRefresh.sh >/dev/null
. ${HOME}/etc/${ADOBE_SANDBOX}adobeTokens.conf

export HOME=/var/www/m365; cd
. ./.bashrc
cd - >/dev/null

export CLIMICROSOFT365_CONFIG_DIR=$HOME

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then ${0%.*}.py
fi
